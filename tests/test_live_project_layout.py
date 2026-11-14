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
    PlcRestore,
    backup_modified_plc_source,
    backup_plc_source,
    headless_python,
    older_plc_backups,
    plc_backup_time,
    project_environment,
    record_generated_plc_source,
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

    restored = restore_plc_source(tmp_path)

    assert restored.file_count == 3
    assert (source / "main.py").read_text(encoding="utf-8") == "logic = object()\n"
    assert (source / "subroutines" / "startup.py").is_file()
    assert not (source / "extra.py").exists()
    # No generation was recorded, so the changed tree counts as edits and is backed up first.
    assert restored.edits_backed_up
    assert (backup_dir / "main.py").read_text(encoding="utf-8") == "changed\n"
    assert (backup_dir / "extra.py").is_file()
    assert restored.restored_from.parent.parent.parent == tmp_path / "backup" / "older"
    assert (restored.restored_from / "subroutines" / "startup.py").is_file()


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
    start = dt.datetime(2026, 11, 12, 9, 30, 0, tzinfo=dt.UTC)
    _clock(monkeypatch, start)

    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")

    newest = tmp_path / "backup" / "src" / "plc"
    assert (newest / "main.py").read_text(encoding="utf-8") == "edits B\n"
    assert older_plc_backups(tmp_path) == ["20261112T093000Z"]
    assert _older_text(tmp_path, "20261112T093000Z") == "edits A\n"
    assert plc_backup_time(tmp_path) == start + dt.timedelta(minutes=1)

    (tmp_path / "src" / "plc" / "main.py").write_text("regenerated\n", encoding="utf-8")
    record_generated_plc_source(tmp_path)
    restored = restore_plc_source(tmp_path)

    # Clean source makes no new backup.
    assert restored == PlcRestore(newest, 1, edits_backed_up=False)
    assert older_plc_backups(tmp_path) == ["20261112T093000Z"]
    assert (tmp_path / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "edits B\n"


def test_backups_keep_the_newest_five(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))

    for index in range(KEPT_PLC_BACKUPS + 2):
        _back_up(tmp_path, f"edits {index}\n")

    names = older_plc_backups(tmp_path)
    assert KEPT_PLC_BACKUPS == 5
    assert names == ["20261112T090500Z", "20261112T090400Z", "20261112T090300Z", "20261112T090200Z"]
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
    same = dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(project_workspace, "_now", lambda: same)

    for index in range(KEPT_PLC_BACKUPS + 6):
        _back_up(tmp_path, f"edits {index}\n")

    names = older_plc_backups(tmp_path)
    assert names == [
        "20261112T090000Z-10",
        "20261112T090000Z-9",
        "20261112T090000Z-8",
        "20261112T090000Z-7",
    ]
    assert [_older_text(tmp_path, name) for name in names] == [
        "edits 9\n",
        "edits 8\n",
        "edits 7\n",
        "edits 6\n",
    ]


def test_a_backup_matching_the_newest_makes_no_new_one(tmp_path: Path, monkeypatch):
    times = _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))

    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")
    _back_up(tmp_path, "edits B\n")
    _back_up(tmp_path, "edits B\n")

    assert older_plc_backups(tmp_path) == ["20261112T090000Z"]
    assert plc_backup_time(tmp_path) == times[-1]


def test_a_backup_without_a_recorded_time_moves_aside_under_its_newest_file(
    tmp_path: Path, monkeypatch
):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    earlier = tmp_path / "backup" / "src" / "plc"
    earlier.mkdir(parents=True)
    (earlier / "main.py").write_text("edits from an earlier version\n", encoding="utf-8")
    taken = dt.datetime(2026, 10, 1, 8, 15, 30, tzinfo=dt.UTC).timestamp()
    os.utime(earlier / "main.py", (taken, taken))
    assert plc_backup_time(tmp_path) == dt.datetime.fromtimestamp(taken).astimezone()

    _back_up(tmp_path, "edits A\n")

    assert older_plc_backups(tmp_path) == ["20261001T081530Z"]
    assert _older_text(tmp_path, "20261001T081530Z") == "edits from an earlier version\n"


def test_pruning_leaves_folders_not_named_like_a_backup(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    keep = tmp_path / "backup" / "older" / "before the rewrite" / "src" / "plc"
    keep.mkdir(parents=True)

    for index in range(KEPT_PLC_BACKUPS + 2):
        _back_up(tmp_path, f"edits {index}\n")

    assert keep.is_dir()
    assert len(older_plc_backups(tmp_path)) == KEPT_PLC_BACKUPS - 1


def test_restore_takes_an_older_backup_by_name(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")

    restored = restore_plc_source(tmp_path, "20261112T090000Z")

    # src/plc held B, which stays the newest backup: no new one is made.
    assert restored == PlcRestore(
        tmp_path / "backup" / "older" / "20261112T090000Z" / "src" / "plc", 1, True
    )
    assert older_plc_backups(tmp_path) == ["20261112T090000Z"]
    assert (tmp_path / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "edits A\n"
    with pytest.raises(ValueError, match="older backups: 20261112T090000Z"):
        restore_plc_source(tmp_path, "20261112T080000Z")


def test_a_backup_whose_time_cannot_be_written_is_still_made(tmp_path: Path, monkeypatch):
    times = _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    _back_up(tmp_path, "edits A\n")
    (tmp_path / "backup" / "backup-time.txt.staging").mkdir()  # the write fails

    _back_up(tmp_path, "edits B\n")

    assert (tmp_path / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "edits B\n"
    assert older_plc_backups(tmp_path) == ["20261112T090000Z"]
    # Not the time of the backup before: its files are dated to when it was taken.
    assert plc_backup_time(tmp_path) == times[1]


def test_a_backup_made_newest_again_without_a_written_time_is_not_pruned_next(
    tmp_path: Path, monkeypatch
):
    times = _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = tmp_path / "src" / "plc"
    source.mkdir(parents=True)
    (source / "main.py").write_text("edits A\n", encoding="utf-8")
    edited = dt.datetime(2026, 11, 1, 8, 0, 0, tzinfo=dt.UTC).timestamp()
    os.utime(source / "main.py", (edited, edited))  # A was edited days ago
    backup_plc_source(tmp_path)
    for text in ("edits B\n", "edits C\n", "edits D\n", "edits E\n"):
        _back_up(tmp_path, text)
    staging = tmp_path / "backup" / "backup-time.txt.staging"
    staging.mkdir()  # the write fails

    _back_up(tmp_path, "edits A\n")  # A, the oldest backup, becomes the newest

    assert plc_backup_time(tmp_path) == times[5]
    staging.rmdir()
    _back_up(tmp_path, "edits F\n")

    assert older_plc_backups(tmp_path) == [
        "20261112T090500Z",
        "20261112T090400Z",
        "20261112T090300Z",
        "20261112T090200Z",
    ]
    assert _older_text(tmp_path, "20261112T090500Z") == "edits A\n"


def test_a_failed_backup_leaves_the_newest_backup_in_place(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
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
    assert not (tmp_path / "backup" / "older" / "20261112T090000Z").exists()


def _generate(project_dir: Path, text: str) -> None:
    """Stand in for a CLICK save: back up edited source, regenerate, record the generation."""
    backup_modified_plc_source(project_dir)
    source = project_dir / "src" / "plc"
    source.mkdir(parents=True, exist_ok=True)
    (source / "main.py").write_text(text, encoding="utf-8")
    record_generated_plc_source(project_dir)


def _main(path: Path) -> str:
    return (path / "main.py").read_text(encoding="utf-8")


def test_restore_backs_up_edits_no_backup_holds(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = tmp_path / "src" / "plc"
    _generate(tmp_path, "generated one\n")
    (source / "main.py").write_text("edits A\n", encoding="utf-8")
    _generate(tmp_path, "generated two\n")  # A goes to the backup
    (source / "main.py").write_text("edits B\n", encoding="utf-8")

    restored = restore_plc_source(tmp_path)

    assert _main(source) == "edits A\n"
    assert restored.edits_backed_up
    assert _main(tmp_path / "backup" / "src" / "plc") == "edits B\n"
    assert restored.restored_from == (
        tmp_path / "backup" / "older" / "20261112T090000Z" / "src" / "plc"
    )
    assert _main(restored.restored_from) == "edits A\n"


def test_restoring_an_older_backup_backs_up_the_current_edits(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = tmp_path / "src" / "plc"
    _generate(tmp_path, "generated\n")
    for text in ("edits A\n", "edits B\n"):
        (source / "main.py").write_text(text, encoding="utf-8")
        _generate(tmp_path, "generated\n")
    (source / "main.py").write_text("edits C\n", encoding="utf-8")
    (older_a,) = older_plc_backups(tmp_path)

    restored = restore_plc_source(tmp_path, older_a)

    assert _main(source) == "edits A\n"
    assert restored.edits_backed_up
    assert restored.restored_from == tmp_path / "backup" / "older" / older_a / "src" / "plc"
    assert _main(tmp_path / "backup" / "src" / "plc") == "edits C\n"
    assert [_older_text(tmp_path, name) for name in older_plc_backups(tmp_path)] == [
        "edits B\n",
        "edits A\n",
    ]


def test_restore_of_clean_source_makes_no_backup(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = tmp_path / "src" / "plc"
    _generate(tmp_path, "generated one\n")
    (source / "main.py").write_text("edits A\n", encoding="utf-8")
    _generate(tmp_path, "generated two\n")

    restored = restore_plc_source(tmp_path)

    assert not restored.edits_backed_up
    assert _main(source) == "edits A\n"
    assert older_plc_backups(tmp_path) == []


def _full_set(project_dir: Path) -> Path:
    """Older O1-O4, newest N, and edits C in src/plc that no backup holds."""
    source = project_dir / "src" / "plc"
    _generate(project_dir, "generated\n")
    for text in ("O1\n", "O2\n", "O3\n", "O4\n", "N\n"):
        (source / "main.py").write_text(text, encoding="utf-8")
        _generate(project_dir, "generated\n")
    (source / "main.py").write_text("C\n", encoding="utf-8")
    return source


def _every_backup(project_dir: Path) -> list[str]:
    older = [_older_text(project_dir, name) for name in older_plc_backups(project_dir)]
    return [_main(project_dir / "backup" / "src" / "plc"), *older]


def test_repeated_restores_keep_every_backup(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = _full_set(tmp_path)

    first = restore_plc_source(tmp_path)
    assert _main(source) == "N\n"
    assert sorted(_every_backup(tmp_path)) == ["C\n", "N\n", "O1\n", "O2\n", "O3\n", "O4\n"]

    for expected in ("C\n", "N\n", "C\n"):
        restored = restore_plc_source(tmp_path)
        assert _main(source) == expected
        assert restored.restored_from.is_dir()

    # Each tree src/plc held was already a backup: none is made, none goes.
    assert first.edits_backed_up
    assert sorted(_every_backup(tmp_path)) == ["C\n", "N\n", "O1\n", "O2\n", "O3\n", "O4\n"]


def test_a_backup_an_older_one_holds_becomes_the_newest(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    _back_up(tmp_path, "edits A\n")
    _back_up(tmp_path, "edits B\n")
    _back_up(tmp_path, "edits C\n")

    _back_up(tmp_path, "edits A\n")

    assert _main(tmp_path / "backup" / "src" / "plc") == "edits A\n"
    assert [_older_text(tmp_path, name) for name in older_plc_backups(tmp_path)] == [
        "edits C\n",
        "edits B\n",
    ]


def test_a_failed_restore_of_the_oldest_keeps_every_backup(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = _full_set(tmp_path)
    oldest = older_plc_backups(tmp_path)[-1]
    replace_tree = project_workspace._replace_tree

    def failing(tree: Path, destination: Path) -> int:
        if destination == source:
            raise OSError("src/plc in use")
        return replace_tree(tree, destination)

    monkeypatch.setattr(project_workspace, "_replace_tree", failing)
    with pytest.raises(OSError, match="src/plc in use"):
        restore_plc_source(tmp_path, oldest)

    assert _main(source) == "C\n"
    assert sorted(_every_backup(tmp_path)) == ["C\n", "N\n", "O1\n", "O2\n", "O3\n", "O4\n"]


def test_restoring_the_oldest_keeps_its_backup(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    source = _full_set(tmp_path)
    oldest = older_plc_backups(tmp_path)[-1]

    restored = restore_plc_source(tmp_path, oldest)

    assert _main(source) == "O1\n"
    assert restored.restored_from.is_dir()
    assert _main(restored.restored_from) == "O1\n"
    # Six for now; the next backup trims to five.
    assert sorted(_every_backup(tmp_path)) == ["C\n", "N\n", "O1\n", "O2\n", "O3\n", "O4\n"]
    (source / "main.py").write_text("D\n", encoding="utf-8")
    backup_plc_source(tmp_path)
    assert sorted(_every_backup(tmp_path)) == ["C\n", "D\n", "N\n", "O3\n", "O4\n"]


def test_backups_keep_their_order_when_the_clocks_go_back(tmp_path: Path, monkeypatch):
    summer = dt.timezone(dt.timedelta(hours=-4))
    winter = dt.timezone(dt.timedelta(hours=-5))
    times = iter(
        [
            dt.datetime(2026, 11, 1, 1, 40, tzinfo=summer),
            dt.datetime(2026, 11, 1, 1, 45, tzinfo=summer),
            dt.datetime(2026, 11, 1, 1, 50, tzinfo=summer),
            dt.datetime(2026, 11, 1, 1, 55, tzinfo=summer),
            # The clocks go back an hour: later moments, earlier wall-clock times.
            dt.datetime(2026, 11, 1, 1, 5, tzinfo=winter),
            dt.datetime(2026, 11, 1, 1, 10, tzinfo=winter),
            dt.datetime(2026, 11, 1, 1, 15, tzinfo=winter),
        ]
    )
    monkeypatch.setattr(project_workspace, "_now", lambda: next(times))

    for index in range(7):
        _back_up(tmp_path, f"edits {index}\n")

    names = older_plc_backups(tmp_path)
    assert [_older_text(tmp_path, name) for name in names] == [
        "edits 5\n",
        "edits 4\n",
        "edits 3\n",
        "edits 2\n",
    ]
    assert names[0] == "20261101T061000Z"  # 01:10 after the change


def test_a_backup_pruned_part_way_is_no_longer_listed(tmp_path: Path, monkeypatch):
    _clock(monkeypatch, dt.datetime(2026, 11, 12, 9, 0, 0, tzinfo=dt.UTC))
    for index in range(KEPT_PLC_BACKUPS):
        _back_up(tmp_path, f"edits {index}\n")
    oldest = tmp_path / "backup" / "older" / "20261112T090000Z"
    assert oldest.is_dir()

    deleted: list[Path] = []
    rmtree = shutil.rmtree

    def delete_part(path, *args, **kwargs):
        if not Path(path).name.startswith(".pruning-"):
            return rmtree(path, *args, **kwargs)
        deleted.append(Path(path))
        (Path(path) / "src" / "plc" / "main.py").unlink()  # then stops
        return None

    monkeypatch.setattr(project_workspace.shutil, "rmtree", delete_part)
    _back_up(tmp_path, "edits 5\n")

    assert not oldest.exists()
    assert deleted == [tmp_path / "backup" / "older" / ".pruning-20261112T090000Z"]
    names = older_plc_backups(tmp_path)
    assert "20261112T090000Z" not in names
    assert len(names) == KEPT_PLC_BACKUPS - 1
    with pytest.raises(ValueError, match="no older backup named"):
        restore_plc_source(tmp_path, "20261112T090000Z")

    monkeypatch.undo()
    _back_up(tmp_path, "edits 6\n")  # the next prune clears what was left

    assert not deleted[0].exists()


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
