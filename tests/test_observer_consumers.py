"""Regression tests for observer consumers wired to AddressStore."""

from __future__ import annotations

from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.data.nickname_manager import NicknameManager
from clicknick.data.shared_dataview import SharedDataviewData
from clicknick.models.address_row import AddressRow


class _MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, initial_rows=None):
        self._initial_rows = initial_rows or {}

    def load_all_addresses(self):
        return self._initial_rows

    def save_changes(self, rows):
        return len(rows)


def _make_store(initial_rows=None) -> AddressStore:
    store = AddressStore(_MockDataSource(initial_rows))
    store.load_initial_data()
    return store


def test_nickname_manager_invalidates_cache_when_external_update_adds_new_row() -> None:
    addr_key_1 = get_addr_key("X", 1)
    store = _make_store(
        {
            addr_key_1: AddressRow(
                memory_type="X",
                address=1,
                nickname="Input1",
                comment="Existing input",
            )
        }
    )
    manager = NicknameManager()
    manager.set_shared_data(store)

    # Prime the cache before the external MDB-style update arrives.
    assert manager.get_filtered_nicknames(["X"]) == ["Input1"]

    addr_key_3 = get_addr_key("X", 3)
    store._data_source._initial_rows[addr_key_3] = AddressRow(
        memory_type="X",
        address=3,
        nickname="Input3",
        comment="Inserted by MDB update",
        used=True,
    )

    store._on_database_update()

    assert set(manager.get_filtered_nicknames(["X"])) == {"Input1", "Input3"}
    assert manager.get_address_for_nickname("Input3") == "X003"


def test_nickname_manager_invalidates_cache_when_external_update_deletes_row() -> None:
    addr_key = get_addr_key("X", 1)
    store = _make_store(
        {
            addr_key: AddressRow(
                memory_type="X",
                address=1,
                nickname="Input1",
                comment="Existing input",
            )
        }
    )
    manager = NicknameManager()
    manager.set_shared_data(store)

    # Prime the cache before the external MDB-style deletion arrives.
    assert manager.get_filtered_nicknames(["X"]) == ["Input1"]

    del store._data_source._initial_rows[addr_key]
    store._on_database_update()

    assert manager.get_filtered_nicknames(["X"]) == []
    assert manager.get_address_for_nickname("Input1") is None


def test_shared_dataview_refreshes_when_address_store_changes() -> None:
    addr_key = get_addr_key("X", 1)
    store = _make_store(
        {
            addr_key: AddressRow(
                memory_type="X",
                address=1,
                nickname="Input1",
                comment="Existing input",
            )
        }
    )
    shared = SharedDataviewData(address_store=store)

    class _WindowStub:
        def __init__(self) -> None:
            self.refresh_calls = 0

        def refresh_nicknames_from_shared(self) -> None:
            self.refresh_calls += 1

    window = _WindowStub()
    shared.register_window(window)

    with store.edit_session("Rename input") as session:
        session.set_field(addr_key, "nickname", "Input1Renamed")

    assert window.refresh_calls == 1
