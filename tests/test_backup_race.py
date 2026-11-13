"""Backups, restores and a build's publish of ``src/plc`` on one workspace never interleave.

The build publishes on its worker thread. ``clicknick-cli backup``/``restore`` and choosing a
workspace run on the Tk thread. ``rung_commands._get_project_dir`` refuses the CLI while the
analysis says it is building, but a build can still be publishing when it does not (a second
save whose database is not found marks the analysis failed while the first build runs). Each
test pauses one side part way through a copy and runs the other.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.services import project_workspace
from clicknick.services.analysis_service import _publish_generated_project
from clicknick.services.project_workspace import (
    backup_plc_source,
    plc_backup_dir,
    plc_source_dir,
    plc_source_is_modified,
    record_generated_plc_source,
)
from clicknick.services.workspace_mirror import sync_workspace_to_mirror

_GENERATED = {"main.py": "generated one\n", "subroutines/a.py": "generated one a\n"}
_NEXT = {"main.py": "generated two\n", "subroutines/a.py": "generated two a\n"}
_BACKED_UP = {"main.py": "edits\n", "subroutines/a.py": "edits a\n"}


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _read(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    _write(plc_backup_dir(workspace), _BACKED_UP)
    _write(plc_source_dir(workspace), _GENERATED)
    (workspace / "csv").mkdir()
    record_generated_plc_source(workspace)
    return workspace


def _staged(tmp_path: Path) -> Path:
    staged = tmp_path / "staged"
    _write(plc_source_dir(staged), _NEXT)
    (staged / "csv").mkdir()
    return staged


class _Paused:
    """Run *target* on a thread that stops when a copy lists *directory*, until released."""

    def __init__(self, monkeypatch, directory: Path, target: Callable[[], object]) -> None:
        self.reached = threading.Event()
        self._release = threading.Event()
        self.error: BaseException | None = None
        ignore = project_workspace._COPY_IGNORE

        def pausing(source, names):
            if Path(source) == directory and not self.reached.is_set():
                self.reached.set()
                self._release.wait(10)
            return ignore(source, names)

        monkeypatch.setattr(project_workspace, "_COPY_IGNORE", pausing)

        def run() -> None:
            try:
                target()
            except BaseException as exc:  # noqa: BLE001 - reported by finish()
                self.error = exc

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        assert self.reached.wait(10), "the copy never reached the directory"

    def finish(self) -> None:
        self._release.set()
        self._thread.join(10)
        assert not self._thread.is_alive()
        if self.error is not None:
            raise self.error


def test_a_build_publishing_waits_for_a_backup_part_way_through(tmp_path: Path, monkeypatch):
    workspace = _workspace(tmp_path)
    staged = _staged(tmp_path)
    backup = _Paused(
        monkeypatch,
        plc_source_dir(workspace) / "subroutines",
        lambda: backup_plc_source(workspace),
    )

    asked = threading.Event()
    writing = project_workspace.workspace_writing

    def asking(project_dir: Path, *, wait: bool = False):
        if wait:
            asked.set()
        return writing(project_dir, wait=wait)

    monkeypatch.setattr(project_workspace, "workspace_writing", asking)
    publish = threading.Thread(target=_publish_generated_project, args=(staged, workspace))
    publish.start()
    assert asked.wait(10), "the publish never asked for the workspace"
    # It cannot finish without the workspace, which the paused backup holds.
    assert publish.is_alive()
    assert _read(plc_source_dir(workspace)) == _GENERATED
    backup.finish()
    publish.join(10)
    assert not publish.is_alive()

    # Not main.py from one generation and subroutines/ from the next.
    assert _read(plc_backup_dir(workspace)) == _GENERATED
    assert _read(plc_source_dir(workspace)) == _NEXT
    assert not plc_source_is_modified(workspace)


class _Analysis:
    """An analysis that does not say it is building (status FAILED or none)."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir


class _Store:
    user_overrides: dict[int, object] = {}

    def get_dirty_keys(self) -> set[int]:
        return set(self.user_overrides)


@pytest.mark.parametrize("command", ["restore", "backup"])
def test_the_cli_is_refused_while_a_build_publishes(tmp_path: Path, monkeypatch, command):
    workspace = _workspace(tmp_path)
    staged = _staged(tmp_path)
    publish = _Paused(
        monkeypatch,
        plc_source_dir(staged) / "subroutines",
        lambda: _publish_generated_project(staged, workspace),
    )
    ctx = DispatchContext(store=_Store(), analysis=_Analysis(workspace))

    try:
        with pytest.raises(ValueError, match="try again when it finishes"):
            dispatch(ctx, command)
    finally:
        publish.finish()

    assert _read(plc_source_dir(workspace)) == _NEXT
    assert _read(plc_backup_dir(workspace)) == _BACKED_UP
    assert not plc_source_is_modified(workspace)


def test_choosing_a_workspace_is_refused_while_a_build_publishes_the_active_one(
    tmp_path: Path, monkeypatch
):
    workspace = _workspace(tmp_path)
    staged = _staged(tmp_path)
    mirror = tmp_path / "mirror"
    publish = _Paused(
        monkeypatch,
        plc_source_dir(staged) / "subroutines",
        lambda: _publish_generated_project(staged, workspace),
    )

    try:
        with pytest.raises(ValueError, match="try again when it finishes"):
            sync_workspace_to_mirror(workspace, mirror)
    finally:
        publish.finish()

    assert not mirror.exists()
    assert _read(plc_source_dir(workspace)) == _NEXT
