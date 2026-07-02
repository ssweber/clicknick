"""Tests for the ``unused``/``free`` live command (next free address)."""

from dataclasses import replace

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, initial_rows=None):
        self._initial_rows = initial_rows or {}

    def load_all_addresses(self):
        return self._initial_rows

    def save_changes(self, rows):
        return len(rows)


@pytest.fixture
def store():
    s = AddressStore(MockDataSource())
    s.load_initial_data()
    return s


def _ctx(store):
    return DispatchContext(store=store)


def _mark_used(store, memory_type, address):
    """Simulate an address referenced in the program (DB 'Used' flag)."""
    key = get_addr_key(memory_type, address)
    store.base_state[key] = replace(store.base_state[key], used=True)
    store.visible_state[key] = replace(store.visible_state[key], used=True)


def test_returns_first_address_when_all_free(store):
    assert dispatch(_ctx(store), "unused C") == "C1"


def test_skips_addresses_with_content(store):
    for addr in (1, 2, 3, 4):
        with store.edit_session("seed") as s:
            s.set_field(get_addr_key("C", addr), "nickname", f"Bit{addr}")
    assert dispatch(_ctx(store), "unused C") == "C5"


def test_skips_used_addresses(store):
    _mark_used(store, "C", 1)
    _mark_used(store, "C", 2)
    assert dispatch(_ctx(store), "unused C") == "C3"


def test_count_returns_multiple_one_per_line(store):
    with store.edit_session("seed") as s:
        s.set_field(get_addr_key("C", 1), "nickname", "First")
    assert dispatch(_ctx(store), "unused C 3") == "C2\nC3\nC4"


def test_start_address_resumes_scan(store):
    assert dispatch(_ctx(store), "unused C100") == "C100"


def test_start_address_skips_taken(store):
    with store.edit_session("seed") as s:
        s.set_field(get_addr_key("C", 100), "comment", "reserved")
    assert dispatch(_ctx(store), "unused C100") == "C101"


def test_free_is_an_alias(store):
    assert dispatch(_ctx(store), "free DS") == "DS1"


def test_respects_pending_unsaved_edits(store):
    # An unsaved nickname edit should make the address unavailable immediately.
    with store.edit_session("edit") as s:
        s.set_field(get_addr_key("DS", 1), "nickname", "Setpoint")
    assert dispatch(_ctx(store), "unused DS") == "DS2"


def test_unknown_type_raises(store):
    with pytest.raises(ValueError, match="unknown memory type"):
        dispatch(_ctx(store), "unused ZZ")


def test_bad_count_raises(store):
    with pytest.raises(ValueError, match="count must be an integer"):
        dispatch(_ctx(store), "unused C x")


def test_no_free_at_or_after_raises(store):
    # DH tops out at 500; fill the last slot, then ask from there.
    with store.edit_session("seed") as s:
        s.set_field(get_addr_key("DH", 500), "comment", "last")
    with pytest.raises(ValueError, match="no free DH addresses at or after DH500"):
        dispatch(_ctx(store), "unused DH500")
