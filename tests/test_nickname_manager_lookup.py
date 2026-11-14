"""NicknameManager: sort order, and lookups that match what the dropdown listed."""

from __future__ import annotations

from types import SimpleNamespace

from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.data.nickname_manager import NicknameManager
from clicknick.models.address_row import AddressRow


class _Source:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, rows):
        self._rows = rows

    def load_all_addresses(self):
        return self._rows

    def save_changes(self, rows):
        return len(rows)


def _manager(rows, **settings) -> NicknameManager:
    store = AddressStore(_Source({get_addr_key(r.memory_type, r.address): r for r in rows}))
    store.load_initial_data()
    defaults = {
        "sort_by_nickname": False,
        "search_mode": "none",
        "exclude_sc_sd": False,
        "get_exclude_terms_list": lambda: [],
    }
    manager = NicknameManager(settings=SimpleNamespace(**{**defaults, **settings}))
    manager.set_store(store)
    return manager


def _row(memory_type, address, nickname):
    return AddressRow(memory_type=memory_type, address=address, nickname=nickname)


def test_sort_by_nickname_ignores_case():
    manager = _manager(
        [_row("C", 1, "Zebra"), _row("C", 2, "alarm"), _row("C", 3, "Motor")],
        sort_by_nickname=True,
    )

    assert manager.get_filtered_nicknames(["C"]) == ["alarm", "Motor", "Zebra"]


def test_a_repeated_nickname_is_listed_once_and_inserts_the_listed_row():
    manager = _manager([_row("C", 1, "Motor"), _row("C", 2, "Motor"), _row("C", 3, "Pump")])

    assert manager.get_filtered_nicknames(["C"]) == ["Motor", "Pump"]
    assert manager.get_address_for_nickname("Motor", ["C"]) == "C1"


def test_lookup_stays_within_the_types_the_dropdown_listed():
    manager = _manager([_row("Y", 1, "Motor"), _row("C", 1, "Motor")])

    assert manager.get_filtered_nicknames(["C"]) == ["Motor"]
    assert manager.get_address_for_nickname("Motor", ["C"]) == "C1"
    assert "C1" in manager.get_nickname_details("Motor", ["C"])
