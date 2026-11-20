"""Tests for staged vendor system-nickname repairs."""

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.models.address_row import AddressRow
from clicknick.services.system_nickname_service import find_system_nickname_repairs
from clicknick.utils import mdb_operations


class MockDataSource:
    supports_used_field = True
    stored_row = staticmethod(mdb_operations.stored_row)
    file_path = "test.mdb"
    is_read_only = False
    is_database = True

    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return self.rows

    def save_changes(self, rows):
        return len(rows)


def _store_with_stale_vendor_names(*, is_database: bool = True):
    rows = {
        get_addr_key("SD", 132): AddressRow(
            memory_type="SD", address=132, nickname="_Port1_AL_Denied_Count"
        ),
        get_addr_key("SD", 133): AddressRow(
            memory_type="SD", address=133, nickname="_WLAN_AL_Denied_Count"
        ),
        get_addr_key("SD", 134): AddressRow(memory_type="SD", address=134),
        get_addr_key("SD", 135): AddressRow(memory_type="SD", address=135),
    }
    source = MockDataSource(rows)
    source.is_database = is_database
    store = AddressStore(source)
    store.load_initial_data()
    return store


def test_repair_command_stages_known_corrections_in_one_store_operation():
    store = _store_with_stale_vendor_names()
    opened = []

    result = dispatch(
        DispatchContext(store=store, show_address_editor=opened.append),
        "tag repair-system-nicknames",
    )

    assert "2 system nickname repairs staged" in result
    assert len(store.user_overrides) == 2
    assert store.get_visible_row(get_addr_key("SD", 132)).nickname == ("_Port1_AL_Denied_No1_Cnt")
    assert store.get_visible_row(get_addr_key("SD", 133)).nickname == ("_WLAN_AL_Denied_No1_Cnt")
    assert store.get_visible_row(get_addr_key("SD", 134)).nickname == ""
    assert store.get_visible_row(get_addr_key("SD", 135)).nickname == ""
    assert not store.has_errors()
    assert opened == ["changed"]


def test_repair_command_is_noop_when_values_are_current():
    store = _store_with_stale_vendor_names()
    dispatch(DispatchContext(store=store), "tag repair-system-nicknames")
    store.save_all_changes()

    result = dispatch(DispatchContext(store=store), "tag repair-system-nicknames")

    assert result == "system nickname repair: no known corrections needed"
    assert not store.has_unsaved_changes()


@pytest.mark.parametrize(("is_database", "save"), [(True, "Sync"), (False, "Save")])
def test_repair_command_says_sync_or_save_for_the_data_loaded(is_database, save):
    # The Address Editor syncs CLICK's database and saves a CSV file.
    store = _store_with_stale_vendor_names(is_database=is_database)

    result = dispatch(DispatchContext(store=store), "tag repair-system-nicknames")

    assert result.splitlines()[-2:] == [
        f"Review them in the Address Editor under Changed, then {save} them.",
        f"[2 tags staged | Next: {save} tags in ClickNick]",
    ]


def test_a_blank_nickname_with_a_comment_needs_no_repair():
    # pyclickplc 0.11.0 listed a blank name as an old name for these four addresses.
    rows = {
        get_addr_key("SD", address): AddressRow(
            memory_type="SD", address=address, comment="kept by the user"
        )
        for address in (132, 133, 134, 135)
    }
    store = AddressStore(MockDataSource(rows))
    store.load_initial_data()

    assert find_system_nickname_repairs(store) == ()
    result = dispatch(DispatchContext(store=store), "tag repair-system-nicknames")

    assert result == "system nickname repair: no known corrections needed"
    assert not store.user_overrides
