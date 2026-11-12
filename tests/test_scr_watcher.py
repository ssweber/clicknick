"""Tests for saved-project workflow state tracking."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from clicknick.services.scr_watcher import ScrWatcher


class _Root:
    def after(self, *_args):
        return "after-id"


def _settle(watcher: ScrWatcher) -> None:
    """Two checks: one sees the files change, the next sees them stay that way."""
    watcher._check()
    watcher._check()


def test_click_save_clears_synced_tags_and_staged_rungs(tmp_path) -> None:
    sync_updates: list[int] = []
    changed: list[bool] = []
    watcher = ScrWatcher(
        tmp_path,
        lambda: changed.append(True),
        on_sync_status_changed=sync_updates.append,
    )
    watcher.record_sync(range(7))
    watcher.record_rung_stage(31)
    watcher._active = True
    watcher._tk_root = _Root()
    (tmp_path / "Scr1.tmp").write_text("saved", encoding="utf-8")

    _settle(watcher)

    assert changed == [True]
    assert watcher.synced_pending == 0
    assert watcher.staged_rungs == 0
    assert sync_updates == [7, 0]


def test_click_save_reports_cleared_rungs_without_pending_tags(tmp_path) -> None:
    sync_updates: list[int] = []
    watcher = ScrWatcher(
        tmp_path,
        lambda: None,
        on_sync_status_changed=sync_updates.append,
    )
    watcher.record_rung_stage(2)
    watcher._active = True
    watcher._tk_root = _Root()
    (tmp_path / "Scr1.tmp").write_text("saved", encoding="utf-8")

    _settle(watcher)

    assert watcher.staged_rungs == 0
    assert sync_updates == [0]


def test_syncing_the_same_tags_twice_counts_them_once(tmp_path) -> None:
    sync_updates: list[int] = []
    watcher = ScrWatcher(tmp_path, lambda: None, on_sync_status_changed=sync_updates.append)

    watcher.record_sync({1, 2})
    watcher.record_sync({2, 3})
    watcher.record_sync({3})

    assert watcher.synced_pending == 3
    assert sync_updates == [2, 3]


def _watching(tmp_path, changed: list[bool]) -> ScrWatcher:
    watcher = ScrWatcher(tmp_path, lambda: changed.append(True))
    watcher._active = True
    watcher._tk_root = _Root()
    return watcher


def test_a_save_with_an_earlier_mtime_still_rebuilds(tmp_path) -> None:
    scr = tmp_path / "Scr1.tmp"
    scr.write_text("saved", encoding="utf-8")
    os.utime(scr, (2_000_000_000, 2_000_000_000))
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    # A copied-back file or a clock step: CLICK's new save is older than the last.
    scr.write_text("saved again", encoding="utf-8")
    os.utime(scr, (1_000_000_000, 1_000_000_000))
    _settle(watcher)

    assert changed == [True]


def test_a_save_that_changes_only_the_size_rebuilds(tmp_path) -> None:
    scr = tmp_path / "Scr1.tmp"
    scr.write_text("saved", encoding="utf-8")
    stamp = scr.stat().st_mtime_ns
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    scr.write_text("saved, longer", encoding="utf-8")
    os.utime(scr, ns=(stamp, stamp))
    _settle(watcher)

    assert changed == [True]


def test_a_save_that_deletes_a_subroutine_rebuilds(tmp_path) -> None:
    (tmp_path / "Scr1.tmp").write_text("main", encoding="utf-8")
    (tmp_path / "Scr2.tmp").write_text("sub", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    (tmp_path / "Scr2.tmp").unlink()
    _settle(watcher)

    assert changed == [True]


def test_a_save_caught_half_written_counts_once(tmp_path) -> None:
    (tmp_path / "Scr1.tmp").write_text("main", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    # A check lands while CLICK writes the save: Scr1 is new, Scr2 not there yet.
    (tmp_path / "Scr1.tmp").write_text("main, saved", encoding="utf-8")
    watcher._check()
    (tmp_path / "Scr2.tmp").write_text("sub", encoding="utf-8")
    watcher._check()
    assert changed == []
    watcher._check()
    watcher._check()

    assert changed == [True]


def test_a_second_save_soon_after_counts_again(tmp_path) -> None:
    (tmp_path / "Scr1.tmp").write_text("main", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    (tmp_path / "Scr1.tmp").write_text("main, saved", encoding="utf-8")
    _settle(watcher)
    (tmp_path / "Scr1.tmp").write_text("main, saved again", encoding="utf-8")
    _settle(watcher)

    assert changed == [True, True]


def test_files_put_back_before_they_settle_are_not_a_save(tmp_path) -> None:
    scr = tmp_path / "Scr1.tmp"
    scr.write_text("main", encoding="utf-8")
    stamp = scr.stat().st_mtime_ns
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    scr.write_text("temp", encoding="utf-8")
    watcher._check()
    scr.write_text("main", encoding="utf-8")
    os.utime(scr, ns=(stamp, stamp))
    _settle(watcher)

    assert changed == []


def test_no_scr_files_left_is_not_a_save(tmp_path) -> None:
    (tmp_path / "Scr1.tmp").write_text("main", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    (tmp_path / "Scr1.tmp").unlink()
    _settle(watcher)

    assert changed == []


def _short_name(path: Path) -> Path:
    """The 8.3 short spelling of an existing path, or the path when the volume has none."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer)):
        return path
    return Path(buffer.value)


@pytest.mark.parametrize("spelling", ["dotdot", "case", "short"])
def test_watching_the_same_folder_spelled_another_way_keeps_a_save(tmp_path, spelling) -> None:
    folder = tmp_path / "Long Project Folder"
    folder.mkdir()
    (tmp_path / "sibling").mkdir()
    (folder / "Scr1.tmp").write_text("main", encoding="utf-8")
    if spelling == "dotdot":
        same = tmp_path / "sibling" / ".." / folder.name
    elif spelling == "case":
        same = Path(str(folder).upper())
    else:
        same = _short_name(folder)
        if str(same) == str(folder):
            pytest.skip("this volume has no 8.3 short names")
    changed: list[bool] = []
    watcher = _watching(folder, changed)

    # CLICK saves before the next check; analysis then finds the folder spelled another way.
    (folder / "Scr1.tmp").write_text("main, saved", encoding="utf-8")
    watcher.watch(same)
    _settle(watcher)

    assert changed == [True]


def test_watching_another_folder_starts_from_what_it_holds(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "Scr1.tmp").write_text("main", encoding="utf-8")
    (second / "Scr1.tmp").write_text("other", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(first, changed)

    watcher.watch(second)
    _settle(watcher)

    assert changed == []
    assert watcher.folder == second
