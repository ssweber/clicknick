"""Contracts for the generated ``src/plc`` project layout."""

from __future__ import annotations

import datetime as dt
import os
import shutil
from pathlib import Path

import pytest

from clicknick.live.rung_commands import (
    _all_file_stems,
    _extract_rungs,
    _get_csv_stem,
    _resolve_file,
)
from clicknick.services import project_workspace
from clicknick.services.project_workspace import (
    KEPT_PLC_BACKUPS,
    backup_plc_source,
    headless_python,
    older_plc_backups,
    plc_backup_time,
    project_environment,
    restore_plc_source,
)


def _write_project(project_dir: Path) -> None:
    package_dir = project_dir / "src" / "plc"
    subroutines = package_dir / "subroutines"
    subroutines.mkdir(parents=True)
    (package_dir / "main.py").write_text("logic = object()\n", encoding="utf-8")
    (subroutines / "__init__.py").write_text("", encoding="utf-8")
    (subroutines / "startup.py").write_text(
        '@subroutine("Startup Sequence")\ndef startup():\n    pass\n',
        encoding="utf-8",
    )


def test_rung_paths_resolve_inside_src_plc(tmp_path: Path):
    _write_project(tmp_path)

    assert _resolve_file(tmp_path, "main") == tmp_path / "src" / "plc" / "main.py"
    assert _resolve_file(tmp_path, "startup") == (
        tmp_path / "src" / "plc" / "subroutines" / "startup.py"
    )
    assert _all_file_stems(tmp_path) == ["main", "startup"]
    assert _get_csv_stem(tmp_path, "startup") == "Startup Sequence"


def test_project_environment_prepends_src_to_pythonpath(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "existing")

    env = project_environment(tmp_path)

    assert env["PYTHONPATH"] == os.pathsep.join((str(tmp_path / "src"), "existing"))


def test_children_use_the_console_interpreter_under_the_gui_launcher(tmp_path: Path, monkeypatch):
    import sys

    (tmp_path / "pythonw.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert headless_python() == str(tmp_path / "pythonw.exe"), "no python.exe beside it"

    (tmp_path / "python.exe").write_bytes(b"")
    assert headless_python() == str(tmp_path / "python.exe")

    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert headless_python() == str(tmp_path / "python.exe")


def test_backup_and_restore_replace_the_complete_plc_tree(tmp_path: Path):
    _write_project(tmp_path)
    source = tmp_path / "src" / "plc"
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "main.pyc").write_bytes(b"cache")

    backup_dir, file_count = backup_plc_source(tmp_path)

    assert backup_dir == tmp_path / "backup" / "src" / "plc"
    assert file_count == 3
    assert not (backup_dir / "__pycache__").exists()

    (source / "main.py").write_text("changed\n", encoding="utf-8")
    (source / "extra.py").write_text("remove me\n", encoding="utf-8")
    (source / "subroutines" / "startup.py").unlink()

    restored_from, restored_count = restore_plc_source(tmp_path)

    assert restored_from == backup_dir
    assert restored_count == 3
    assert (source / "main.py").read_text(encoding="utf-8") == "logic = object()\n"
    assert (source / "subroutines" / "startup.py").is_file()
    assert not (source / "extra.py").exists()
    assert (backup_dir / "main.py").is_file()


def _clock(monkeypatch, start: dt.datetime) -> list[dt.datetime]:
    """Make each backup one minute after the one before; return the times handed out."""
    times: list[dt.datetime] = []

    def now() -> dt.datetime:
        times.append(start + dt.timedelta(minutes=len(times)))
        return times[-1]

    monkeypatch.setattr(project_workspace, "_now", now)
    return times


def _back_up(project_dir: Path, text: str) -> None:
    source = project_dir / "src" / "plc"
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.py").write_text(text, encoding="utf-8")
    backup_plc_source(project_dir)


def _older_text(project_dir: Path, name: str) -> str:
    return (project_dir / "backup" / "older" / name / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    )


def test_a_backup_moves_the_one_before_it_aside_under_its_time(tmp_path: Path, monkeypatch):
    start = dt.datetime(2026, 11, 12, 9, 30, 0).astimezone()
    _clock(monkeypatch, start)

    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")

    newest = tmp_path / "backup" / "src" / "plc"
    assert (newest / "main.py").read_text(encoding="utf-8") == "edits B\n"
    assert older_plc_backups(tmp_path) == ["20261112-093000"]
    assert _older_text(tmp_path, "20261112-093000") == "edits A\n"
    assert plc_backup_time(tmp_path) == start + dt.timedelta(minutes=1)

    (tmp_path / "src" / "plc" / "main.py").write_text("regenerated\n", encoding="utf-8")
    restored_from, _count = restore_plc_source(tmp_path)

    assert restored_from == newest
    assert (tmp_path / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "edits B\n"


def test_backups_keep_the_newest_five(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0).astimezone())

    for index in range(KEPT_PLC_BACKUPS + 2):
        _back_up(tmp_path, f"edits {index}\n")

    names = older_plc_backups(tmp_path)
    assert KEPT_PLC_BACKUPS == 5
    assert names == ["20261112-090500", "20261112-090400", "20261112-090300", "20261112-090200"]
    assert [_older_text(tmp_path, name) for name in names] == [
        "edits 5\n",
        "edits 4\n",
        "edits 3\n",
        "edits 2\n",
    ]
    assert (tmp_path / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "edits 6\n"


def test_backups_in_the_same_second_are_kept_in_order(tmp_path: Path, monkeypatch):
    same = dt.datetime(2026, 11, 12, 9, 0, 0).astimezone()
    monkeypatch.setattr(project_workspace, "_now", lambda: same)

    for index in range(KEPT_PLC_BACKUPS + 6):
        _back_up(tmp_path, f"edits {index}\n")

    names = older_plc_backups(tmp_path)
    assert names == [
        "20261112-090000-10",
        "20261112-090000-9",
        "20261112-090000-8",
        "20261112-090000-7",
    ]
    assert [_older_text(tmp_path, name) for name in names] == [
        "edits 9\n",
        "edits 8\n",
        "edits 7\n",
        "edits 6\n",
    ]


def test_a_backup_matching_the_newest_makes_no_new_one(tmp_path: Path, monkeypatch):
    times = _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0).astimezone())

    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")
    _back_up(tmp_path, "edits B\n")
    _back_up(tmp_path, "edits B\n")

    assert older_plc_backups(tmp_path) == ["20261112-090000"]
    assert plc_backup_time(tmp_path) == times[-1]


def test_a_backup_without_a_recorded_time_moves_aside_under_its_newest_file(
    tmp_path: Path, monkeypatch
):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0).astimezone())
    earlier = tmp_path / "backup" / "src" / "plc"
    earlier.mkdir(parents=True)
    (earlier / "main.py").write_text("edits from an earlier version\n", encoding="utf-8")
    taken = dt.datetime(2026, 10, 1, 8, 15, 30).timestamp()
    os.utime(earlier / "main.py", (taken, taken))
    assert plc_backup_time(tmp_path) == dt.datetime.fromtimestamp(taken).astimezone()

    _back_up(tmp_path, "edits A\n")

    assert older_plc_backups(tmp_path) == ["20261001-081530"]
    assert _older_text(tmp_path, "20261001-081530") == "edits from an earlier version\n"


def test_pruning_leaves_folders_not_named_like_a_backup(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0).astimezone())
    keep = tmp_path / "backup" / "older" / "before the rewrite" / "src" / "plc"
    keep.mkdir(parents=True)

    for index in range(KEPT_PLC_BACKUPS + 2):
        _back_up(tmp_path, f"edits {index}\n")

    assert keep.is_dir()
    assert len(older_plc_backups(tmp_path)) == KEPT_PLC_BACKUPS - 1


def test_restore_takes_an_older_backup_by_name(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0).astimezone())
    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")

    restored_from, count = restore_plc_source(tmp_path, "20261112-090000")

    assert restored_from == tmp_path / "backup" / "older" / "20261112-090000" / "src" / "plc"
    assert count == 1
    assert (tmp_path / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "edits A\n"
    with pytest.raises(ValueError, match="older backups: 20261112-090000"):
        restore_plc_source(tmp_path, "20261112-080000")


def test_a_failed_backup_leaves_the_newest_backup_in_place(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0).astimezone())
    _back_up(tmp_path, "edits A\n")

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copytree", fail)
    with pytest.raises(OSError, match="disk full"):
        _back_up(tmp_path, "edits B\n")

    assert (tmp_path / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "edits A\n"
    assert older_plc_backups(tmp_path) == []
    assert not (tmp_path / "backup" / "older" / "20261112-090000").exists()


def test_rung_list_metadata_uses_preceding_click_comments():
    source = '''\
with Program() as logic:
    comment("""\
        # ====================
        # Battery handling
        More detail that should not fill the listing.""")
    with rung():  # R1
        out(BatteryOk)

    with rung():  # R2
        comment("This belongs inside R2, not to R3")

    with rung():  # R3
        """Manual rung description"""
        out(Ready)
'''

    rungs = _extract_rungs(source)

    assert [rung[0] for rung in rungs] == [1, 2, 3]
    assert rungs[0][3] == "Battery handling"
    assert rungs[1][3] == ""
    assert rungs[2][3] == "Manual rung description"


def test_rung_comment_summary_is_compact():
    source = f'''\
with Program() as logic:
    comment("{"description " * 20}")
    with rung():  # R1
        pass
'''

    summary = _extract_rungs(source)[0][3]

    assert len(summary) == 88
    assert summary.endswith("...")
