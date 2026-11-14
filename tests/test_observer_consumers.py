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
    manager.set_store(store)

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
    manager.set_store(store)

    # Prime the cache before the external MDB-style deletion arrives.
    assert manager.get_filtered_nicknames(["X"]) == ["Input1"]

    del store._data_source._initial_rows[addr_key]
    store._on_database_update()

    assert manager.get_filtered_nicknames(["X"]) == []
    assert manager.get_address_for_nickname("Input1") is None


def test_shared_dataview_lookup_reads_the_store_live() -> None:
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
    shared = SharedDataviewData(store)
    assert shared.lookup_nickname("X001") == ("Input1", "Existing input")

    with store.edit_session("Rename input") as session:
        session.set_field(addr_key, "nickname", "Input1Renamed")

    assert shared.lookup_nickname("X001") == ("Input1Renamed", "Existing input")
    assert shared.lookup_nickname("not an address") is None


class _SortSettings:
    """Minimal settings stub for NicknameManager filtering."""

    search_mode = "none"
    exclude_sc_sd = False

    def __init__(self, sort_by_nickname: bool) -> None:
        self.sort_by_nickname = sort_by_nickname

    def get_exclude_terms_list(self) -> list[str]:
        return []


def _store_with_unsorted_nicknames() -> AddressStore:
    return _make_store(
        {
            get_addr_key("C", 1): AddressRow(memory_type="C", address=1, nickname="Zeta"),
            get_addr_key("C", 2): AddressRow(memory_type="C", address=2, nickname="Alpha"),
        }
    )


def test_nickname_manager_keeps_sort_after_store_change() -> None:
    store = _store_with_unsorted_nicknames()
    manager = NicknameManager(settings=_SortSettings(sort_by_nickname=True))
    manager.set_store(store)
    assert manager.get_filtered_nicknames(["C"]) == ["Alpha", "Zeta"]

    with store.edit_session("Edit comment") as session:
        session.set_field(get_addr_key("C", 1), "comment", "Changed")

    assert manager.get_filtered_nicknames(["C"]) == ["Alpha", "Zeta"]


def test_nickname_manager_unsort_restores_address_order() -> None:
    store = _store_with_unsorted_nicknames()
    settings = _SortSettings(sort_by_nickname=True)
    manager = NicknameManager(settings=settings)
    manager.set_store(store)
    assert manager.get_filtered_nicknames(["C"]) == ["Alpha", "Zeta"]

    settings.sort_by_nickname = False
    manager.invalidate()

    assert manager.get_filtered_nicknames(["C"]) == ["Zeta", "Alpha"]
