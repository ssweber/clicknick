"""Tests for saved-project workflow state tracking."""

from __future__ import annotations

import os

from clicknick.services.scr_watcher import ScrWatcher


class _Root:
    def after(self, *_args):
        return "after-id"


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

    watcher._check()

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

    watcher._check()

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
    watcher._check()

    assert changed == [True]


def test_a_save_that_changes_only_the_size_rebuilds(tmp_path) -> None:
    scr = tmp_path / "Scr1.tmp"
    scr.write_text("saved", encoding="utf-8")
    stamp = scr.stat().st_mtime_ns
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    scr.write_text("saved, longer", encoding="utf-8")
    os.utime(scr, ns=(stamp, stamp))
    watcher._check()

    assert changed == [True]


def test_a_save_that_deletes_a_subroutine_rebuilds(tmp_path) -> None:
    (tmp_path / "Scr1.tmp").write_text("main", encoding="utf-8")
    (tmp_path / "Scr2.tmp").write_text("sub", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    (tmp_path / "Scr2.tmp").unlink()
    watcher._check()
    watcher._check()

    assert changed == [True]


def test_no_scr_files_left_is_not_a_save(tmp_path) -> None:
    (tmp_path / "Scr1.tmp").write_text("main", encoding="utf-8")
    changed: list[bool] = []
    watcher = _watching(tmp_path, changed)

    (tmp_path / "Scr1.tmp").unlink()
    watcher._check()

    assert changed == []
