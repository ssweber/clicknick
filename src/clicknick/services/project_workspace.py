"""Paths and subprocess environment for a generated pyrung project."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PLC_PACKAGE_PATH = Path("src") / "plc"
PLC_BACKUP_PATH = Path("backup") / PLC_PACKAGE_PATH
GENERATED_SOURCE_STATE_PATH = Path("backup") / "generated-source.json"
_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def plc_source_dir(project_dir: Path) -> Path:
    """Return the generated import package inside a project root."""
    return project_dir / PLC_PACKAGE_PATH


def plc_backup_dir(project_dir: Path) -> Path:
    """Return the recovery snapshot path inside a generated project."""
    return project_dir / PLC_BACKUP_PATH


def generated_source_state_path(project_dir: Path) -> Path:
    """Return the recorded state of the last source generated from CLICK."""
    return project_dir / GENERATED_SOURCE_STATE_PATH


def _source_fingerprint(source: Path) -> dict[str, str]:
    """Return stable content hashes for the meaningful files in *source*."""
    fingerprint: dict[str, str] = {}
    if not source.is_dir():
        return fingerprint

    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint[path.relative_to(source).as_posix()] = digest.hexdigest()
    return fingerprint


def plc_source_is_modified(project_dir: Path) -> bool:
    """Return whether active source differs from the last CLICK generation.

    A pre-existing project without recorded state is treated conservatively as
    modified so its source is snapshotted before the first protected rebuild.
    """
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        return False

    state_path = generated_source_state_path(project_dir)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        recorded = state["files"]
        if not isinstance(recorded, dict):
            return True
    except (OSError, KeyError, TypeError, ValueError):
        return True
    return _source_fingerprint(source) != recorded


def record_generated_plc_source(project_dir: Path) -> Path:
    """Record active source as the clean result of a CLICK regeneration."""
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        raise ValueError(f"generated source directory not found: {source}")

    state_path = generated_source_state_path(project_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    staging = state_path.with_suffix(f"{state_path.suffix}.staging")
    payload = {"version": 1, "files": _source_fingerprint(source)}
    staging.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staging.replace(state_path)
    return state_path


def _replace_trees(pairs: Sequence[tuple[Path, Path]]) -> None:
    """Copy each source over its destination: every destination changes, or none does.

    Each copy is staged beside its destination first. The old trees then move
    aside and the new ones in; if any rename fails, the new trees come out and
    the old ones go back.
    """
    moves: list[tuple[Path, Path, Path]] = []
    for source, destination in pairs:
        if not source.is_dir():
            raise ValueError(f"source directory not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        moves.append(
            (
                destination.parent / f".{destination.name}.staging",
                destination,
                destination.parent / f".{destination.name}.previous",
            )
        )
    for staging, _destination, previous in moves:
        for leftover in (staging, previous):
            if leftover.exists():
                shutil.rmtree(leftover)

    swapped: list[tuple[Path, Path, Path, bool, bool]] = []
    try:
        for (source, _), (staging, _destination, _previous) in zip(pairs, moves, strict=True):
            shutil.copytree(source, staging, ignore=_COPY_IGNORE)
        try:
            for staging, destination, previous in moves:
                aside = placed = False
                try:
                    if destination.exists():
                        destination.replace(previous)
                        aside = True
                    staging.replace(destination)
                    placed = True
                finally:
                    swapped.append((staging, destination, previous, aside, placed))
        except Exception:
            for staging, destination, previous, aside, placed in reversed(swapped):
                try:
                    if placed:
                        destination.replace(staging)
                    if aside:
                        previous.replace(destination)
                except OSError:
                    pass
            raise
        for _staging, _destination, previous in moves:
            shutil.rmtree(previous, ignore_errors=True)
    finally:
        for staging, _destination, _previous in moves:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def _replace_tree(source: Path, destination: Path) -> int:
    """Copy *source* over *destination* without exposing a partial new tree."""
    _replace_trees([(source, destination)])
    return sum(path.is_file() for path in destination.rglob("*"))


def backup_plc_source(project_dir: Path) -> tuple[Path, int]:
    """Replace the recovery snapshot with the active ``src/plc`` tree."""
    source = plc_source_dir(project_dir)
    if not source.is_dir():
        raise ValueError(f"generated source directory not found: {source}")
    destination = plc_backup_dir(project_dir)
    return destination, _replace_tree(source, destination)


def backup_modified_plc_source(project_dir: Path) -> tuple[Path, int] | None:
    """Snapshot active source only when it contains work beyond regeneration."""
    if not plc_source_is_modified(project_dir):
        return None
    return backup_plc_source(project_dir)


def restore_plc_source(project_dir: Path) -> tuple[Path, int]:
    """Replace active ``src/plc`` with the recovery snapshot."""
    source = plc_backup_dir(project_dir)
    if not source.is_dir():
        raise ValueError("no source backup found; run 'clicknick-cli backup' first")
    destination = plc_source_dir(project_dir)
    return source, _replace_tree(source, destination)


#: Creation flags for ClickNick's Python children: no console window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def headless_python() -> str:
    """The interpreter for ClickNick's own Python children (the simulation, checks, exports).

    Started from the ``clicknick`` GUI launcher, ``sys.executable`` is the venv's
    pythonw.exe: a stub that starts the real interpreter as a second process, and
    Windows shows its busy cursor for that GUI start until a window appears, which
    never happens. The console python.exe, started with ``NO_WINDOW``, shows
    neither a window nor the busy cursor.
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def project_environment(project_dir: Path) -> dict[str, str]:
    """Expose the generated src layout to ClickNick-owned subprocesses."""
    env = os.environ.copy()
    src_dir = str(project_dir / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join((src_dir, existing)) if existing else src_dir
    return env
