"""Tests for staged vendor system-nickname repairs."""

from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.models.address_row import AddressRow


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return self.rows

    def save_changes(self, rows):
        return len(rows)


def _store_with_stale_vendor_names():
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
    store = AddressStore(MockDataSource(rows))
    store.load_initial_data()
    return store


def test_repair_command_stages_known_corrections_in_one_store_operation():
    store = _store_with_stale_vendor_names()
    opened = []

    result = dispatch(
        DispatchContext(store=store, show_address_editor=opened.append),
        "tag repair-system-nicknames",
    )

    assert "4 system nickname repairs staged" in result
    assert len(store.user_overrides) == 4
    assert store.get_visible_row(get_addr_key("SD", 132)).nickname == ("_Port1_AL_Denied_No1_Cnt")
    assert store.get_visible_row(get_addr_key("SD", 133)).nickname == ("_WLAN_AL_Denied_No1_Cnt")
    assert store.get_visible_row(get_addr_key("SD", 134)).nickname == ("_Port1_AL_Denied_Count")
    assert store.get_visible_row(get_addr_key("SD", 135)).nickname == ("_WLAN_AL_Denied_Count")
    assert not store.has_errors()
    assert opened == ["changed"]


def test_repair_command_is_noop_when_values_are_current():
    store = _store_with_stale_vendor_names()
    dispatch(DispatchContext(store=store), "tag repair-system-nicknames")
    store.save_all_changes()

    result = dispatch(DispatchContext(store=store), "tag repair-system-nicknames")

    assert result == "system nickname repair: no known corrections needed"
    assert not store.has_unsaved_changes()
