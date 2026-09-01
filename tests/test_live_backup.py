"""Recovery snapshots for the generated pyrung source tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from clicknick.live import rung_commands
from clicknick.live.dispatch import DispatchContext, dispatch


class _Store:
    user_overrides: dict[int, object] = {}


class _Analysis:
    is_available = True

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir


def _context(project_dir: Path) -> DispatchContext:
    return DispatchContext(store=_Store(), analysis=_Analysis(project_dir))


def _write_source(project_dir: Path, text: str) -> Path:
    source = project_dir / "src" / "plc"
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.py").write_text(text, encoding="utf-8")
    return source


def test_backup_and_restore_commands_round_trip_active_source(tmp_path: Path):
    source = _write_source(tmp_path, "proposal\n")
    ctx = _context(tmp_path)

    assert "backed up 1 source file" in dispatch(ctx, "backup")
    (source / "main.py").write_text("regenerated\n", encoding="utf-8")

    result = dispatch(ctx, "restore")

    assert "restored 1 source file" in result
    assert (source / "main.py").read_text(encoding="utf-8") == "proposal\n"


def test_restore_requires_an_existing_backup(tmp_path: Path):
    _write_source(tmp_path, "proposal\n")

    with pytest.raises(ValueError, match="no source backup found"):
        dispatch(_context(tmp_path), "restore")


def test_rung_apply_does_not_replace_regeneration_recovery_snapshot(tmp_path: Path, monkeypatch):
    source = _write_source(tmp_path, "proposal\n")
    backup = tmp_path / "backup" / "src" / "plc"
    backup.mkdir(parents=True)
    (backup / "main.py").write_text("recovery snapshot\n", encoding="utf-8")

    def _export(project_dir: Path) -> Path:
        (source / "main.py").write_text("export touched source\n", encoding="utf-8")
        return project_dir / "csv_output"

    monkeypatch.setattr(rung_commands, "_run_export", _export)
    monkeypatch.setattr(rung_commands, "_open_proposal", lambda _ctx, _parts: ("opened", 1))

    staged: list[int] = []
    ctx = _context(tmp_path)
    ctx.record_staged_rungs = staged.append
    result = dispatch(ctx, "rung apply main")

    assert "backed up" not in result
    assert "wrote ladder CSVs" in result
    assert "opened" in result
    assert staged == [1]
    assert (tmp_path / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "recovery snapshot\n"


def test_failed_rung_apply_does_not_create_a_misleading_snapshot(tmp_path: Path, monkeypatch):
    _write_source(tmp_path, "proposal\n")

    def _fail_export(_project_dir: Path) -> Path:
        raise ValueError("export failed")

    monkeypatch.setattr(rung_commands, "_run_export", _fail_export)

    with pytest.raises(ValueError, match="export failed"):
        dispatch(_context(tmp_path), "rung apply main")

    assert not (tmp_path / "backup").exists()


def test_rung_preview_command_was_folded_into_apply(tmp_path: Path):
    _write_source(tmp_path, "proposal\n")

    with pytest.raises(ValueError, match="unknown rung subcommand 'preview'"):
        dispatch(_context(tmp_path), "rung preview")
