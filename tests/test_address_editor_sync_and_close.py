"""Address Editor Sync: what it reports and whether it closes afterwards."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.models.address_row import AddressRow
from clicknick.views.address_editor.window import AddressEditorWindow

MODULE = "clicknick.views.address_editor.window"


def _editor(*, close_after_sync: bool) -> AddressEditorWindow:
    """An editor on CLICK's database, without Tk."""
    window = AddressEditorWindow.__new__(AddressEditorWindow)
    window._store = Mock(is_database=True)
    window._store.has_errors.return_value = False
    window._store.has_unsaved_changes.return_value = True
    window._store.save_all_changes.return_value = {1}
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


class _ClickDatabase:
    """SC_.mdb, which CLICK writes too without the store being told."""

    supports_used_field = True
    file_path = "live.mdb"
    is_read_only = False
    is_database = True

    def __init__(self) -> None:
        self.rows: dict[int, AddressRow] = {}

    def load_all_addresses(self) -> dict[int, AddressRow]:
        return dict(self.rows)

    def save_changes(self, rows) -> int:
        for row in rows:
            self.rows[row.addr_key] = row
        return len(rows)


def test_sync_counts_only_the_rows_it_wrote() -> None:
    c1, c2 = get_addr_key("C", 1), get_addr_key("C", 2)
    database = _ClickDatabase()
    store = AddressStore(database)
    store.load_initial_data()
    with store.edit_session("Rename") as session:
        session.set_field(c1, "nickname", "Typed")
        session.set_field(c2, "nickname", "Other")
    # CLICK saves C1 with the same nickname before the Sync.
    database.rows[c1] = AddressRow(memory_type="C", address=1, nickname="Typed")
    window = _editor(close_after_sync=False)
    window._store = store

    window._save_all()

    window._on_synced.assert_called_once_with({c2})
    window.status_var.set.assert_called_once_with("Synced 1 changes")


def test_a_sync_click_already_holds_says_so() -> None:
    c1 = get_addr_key("C", 1)
    database = _ClickDatabase()
    store = AddressStore(database)
    store.load_initial_data()
    with store.edit_session("Rename") as session:
        session.set_field(c1, "nickname", "Typed")
    database.rows[c1] = AddressRow(memory_type="C", address=1, nickname="Typed")
    window = _editor(close_after_sync=False)
    window._store = store
    import clicknick.views.address_editor.window as module

    window._save_all()

    window._on_synced.assert_called_once_with(set())
    module.messagebox.showinfo.assert_called_once_with(
        "Sync", "CLICK already had these changes; nothing to write.", parent=window
    )
    assert not store.has_unsaved_changes()
