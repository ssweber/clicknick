"""Tests for saved-project workflow state tracking."""

from __future__ import annotations

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
    watcher.record_sync(7)
    watcher.record_rung_stage(31)
    watcher._active = True
    watcher._tk_root = _Root()
    (tmp_path / "Scr1.tmp").write_text("saved", encoding="utf-8")

    watcher._check()

    assert changed == [True]
    assert watcher.synced_pending == 0
    assert watcher.staged_rungs == 0
    assert sync_updates == [7, 0]
