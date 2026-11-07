"""``tag set-physical`` takes one option per pyrung response key."""

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

    def __init__(self, rows):
        self.rows = rows

    def load_all_addresses(self):
        return self.rows

    def save_changes(self, rows):
        return len(rows)


def _ctx(comment: str = "Feedback") -> tuple[DispatchContext, int]:
    key = get_addr_key("X", 1)
    rows = {key: AddressRow(memory_type="X", address=1, nickname="Fb", comment=comment)}
    store = AddressStore(MockDataSource(rows))
    store.load_initial_data()
    return DispatchContext(store=store), key


def _comment(ctx: DispatchContext, key: int) -> str:
    assert ctx.store is not None
    row = ctx.store.get_visible_row(key)
    assert row is not None
    return row.comment


@pytest.mark.parametrize(
    ("options", "written"),
    [
        ("--on-delay 50ms --off-delay 200ms", "on_delay=50ms, off_delay=200ms"),
        ("--flasher-on 8ms --flasher-off 9ms", "flasher_on=8ms, flasher_off=9ms"),
        ("--timed 200ms --maintained", "timed=200ms, maintained"),
        ("--toggle", "toggle"),
        ("--ramp-on 0.8 --ramp-off -0.05", "ramp_on=0.8, ramp_off=-0.05"),
        ("--approach-to Oven_SP --approach-rate 0.3", "approach_to=Oven_SP, approach_rate=0.3"),
    ],
)
def test_each_kind_is_written_with_its_own_keys(options: str, written: str):
    ctx, key = _ctx()
    dispatch(ctx, f"tag set-physical X001 Clamp {options}")
    assert _comment(ctx, key) == f"[physical=Clamp, {written}] Feedback"


def test_set_physical_replaces_the_old_response_and_keeps_the_system():
    ctx, key = _ctx("[link=Run, ramp_on=1] Feedback")
    dispatch(ctx, "tag set-physical X001 Clamp --toggle --system Press")
    assert _comment(ctx, key) == "[link=Run, physical=Clamp, toggle, system=Press] Feedback"


def test_bad_values_are_refused_by_pyrungs_parsers():
    ctx, key = _ctx()
    with pytest.raises(ValueError, match="on_delay"):
        dispatch(ctx, "tag set-physical X001 Clamp --on-delay 50")
    with pytest.raises(ValueError, match="two kinds"):
        dispatch(ctx, "tag set-physical X001 Clamp --on-delay 50ms --toggle")
    with pytest.raises(ValueError, match="--flasher-on TIME"):
        dispatch(ctx, "tag set-physical X001 Clamp --profile pulse")
    with pytest.raises(ValueError, match="--on-delay is given twice"):
        dispatch(ctx, "tag set-physical X001 Clamp --on-delay 1s --on-delay 2s")
    assert _comment(ctx, key) == "Feedback"


def test_clear_physical_drops_every_response_key():
    ctx, key = _ctx("[link=Run, timed=200ms, maintained, system=Press] Feedback")
    dispatch(ctx, "tag clear-physical X001")
    assert _comment(ctx, key) == "Feedback"


def test_help_lists_every_option():
    from pyrung.core.physical import PHYSICAL_KEYS

    text = dispatch(DispatchContext(), "help")
    for name in PHYSICAL_KEYS:
        assert "--" + name.replace("_", "-") in text
    assert "tag upgrade-project" in text
