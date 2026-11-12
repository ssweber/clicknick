"""An Address Editor opened to Sync staged edits closes itself after the Sync."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from clicknick.views.address_editor.window import AddressEditorWindow

MODULE = "clicknick.views.address_editor.window"


def _editor(*, close_after_sync: bool) -> AddressEditorWindow:
    """An editor on CLICK's database, without Tk."""
    window = AddressEditorWindow.__new__(AddressEditorWindow)
    window._store = Mock(is_database=True)
    window._store.has_errors.return_value = False
    window._store.has_unsaved_changes.return_value = True
    window._store.get_dirty_keys.return_value = {1}
    window._store.save_all_changes.return_value = 1
    window._close_after_sync = close_after_sync
    window._tabs = {}
    window._on_synced = Mock()
    window.status_var = Mock()
    window.save_btn = Mock()
    window._file_menu = Mock()
    window._save_menu_index = 3
    window.close_without_prompt = Mock()
    return window


@pytest.fixture(autouse=True)
def _no_dialogs(monkeypatch) -> None:
    monkeypatch.setattr(f"{MODULE}.messagebox", Mock())


@pytest.mark.parametrize(
    ("close_after_sync", "label"), [(False, "Sync All"), (True, "Sync and Close")]
)
def test_sync_button_says_whether_it_closes(close_after_sync: bool, label: str) -> None:
    window = _editor(close_after_sync=close_after_sync)

    window._update_save_ui_labels()

    window.save_btn.configure.assert_called_once_with(text=f"💾 {label}")
    window._file_menu.entryconfig.assert_called_once_with(3, label=label)


@pytest.mark.parametrize("close_after_sync", [False, True])
def test_sync_and_close_closes_after_a_successful_sync(close_after_sync: bool) -> None:
    window = _editor(close_after_sync=close_after_sync)

    window._save_all()

    window._on_synced.assert_called_once_with({1})
    assert window.close_without_prompt.called is close_after_sync


def test_a_failed_sync_leaves_the_window_open() -> None:
    window = _editor(close_after_sync=True)
    window._store.save_all_changes.side_effect = OSError("database locked")

    window._save_all()

    window.close_without_prompt.assert_not_called()
