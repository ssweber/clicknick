"""``tag set-range`` writes a numeric range and names an argument that is not a number."""

from __future__ import annotations

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.models.address_row import AddressRow


class MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False
    is_database = True

    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return self.rows

    def save_changes(self, rows):
        return len(rows)


def _ctx() -> tuple[DispatchContext, int]:
    key = get_addr_key("DF", 1)
    rows = {key: AddressRow(memory_type="DF", address=1, nickname="Temp_PV", comment="Oven")}
    store = AddressStore(MockDataSource(rows))
    store.load_initial_data()
    return DispatchContext(store=store), key


def test_set_range_writes_the_range():
    ctx, key = _ctx()

    dispatch(ctx, "tag set-range DF1 0 100.5")

    assert ctx.store is not None
    assert ctx.store.visible_state[key].comment == "[min=0, max=100.5] Oven"


@pytest.mark.parametrize(("command", "word"), [("x 100", "'x'"), ("0 high", "'high'")])
def test_set_range_names_an_argument_that_is_not_a_number(command: str, word: str):
    ctx, key = _ctx()

    with pytest.raises(ValueError) as refused:
        dispatch(ctx, f"tag set-range DF1 {command}")

    assert str(refused.value) == (
        f"{word} is not a number\nusage: tag set-range <identifier> <min> <max>"
    )
    assert ctx.store is not None
    assert not ctx.store.is_dirty(key)
