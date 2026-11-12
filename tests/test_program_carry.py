"""plan_carry: where a write puts each force and bench link pyrung lists."""

from __future__ import annotations

import pytest
from pyclickplc.addresses import get_addr_key, parse_address

from clicknick.services.program_carry import CarryPlan, LinkTarget, address_of, plan_carry


def _maps(names: dict[str, str]):
    """Tag maps for a program naming *names* (address -> nickname)."""
    keys = {get_addr_key(*parse_address(address)): tag for address, tag in names.items()}
    return {tag: key for key, tag in keys.items()}, keys


OLD = _maps({"X001": "Start", "Y001": "Motor", "C1": "Mode", "DS1": "Speed", "DF1": "Temp"})


@pytest.mark.parametrize(
    ("new", "name", "target", "note"),
    [
        # Internal memory: kept while the name keeps its address.
        ({"C1": "Mode"}, "Mode", "Mode", ""),
        ({"C1": "Auto"}, "Mode", None, "Mode (gone)"),
        ({"DS1": "Spare", "DS5": "Speed"}, "Speed", None, "Speed (DS1 -> DS5)"),
        # Hardware stays on its address, under the address's new name.
        ({"X001": "StartPB", "X005": "Start"}, "Start", "StartPB", "Start -> StartPB (X001)"),
        ({}, "Motor", "Y001", "Motor -> Y001"),
        ({"DF1": "Probe"}, "Temp", "Probe", "Temp -> Probe (DF1)"),
        # Not on a CLICK address: pyrung carries it as it is.
        ({}, "Scratch", "Scratch", ""),
        # An address with a nickname goes by the nickname; its address form is on none.
        ({}, "Y001", "Y001", ""),
        # An unnamed address is its own name.
        ({}, "C2", "C2", ""),
        ({"Y002": "Valve"}, "Y002", "Valve", "Y002 -> Valve"),
    ],
)
def test_forces(new, name, target, note):
    plan = plan_carry(OLD, _maps(new), {name: True}, {}, analog=("DF1",))
    assert plan.forces == {name: target}
    assert (plan.released if target is None else plan.renamed) == ((note,) if note else ())


def test_an_internal_df_is_not_hardware_unless_an_analog_channel_has_it():
    plan = plan_carry(OLD, _maps({"DF1": "Probe"}), {"Temp": 20.5}, {})
    assert plan.forces == {"Temp": None}
    assert plan.released == ("Temp (gone)",)


@pytest.mark.parametrize(
    ("new", "feedback", "enable", "target"),
    [
        # Both names still exist: the link follows them, wherever they are now.
        ({"X001": "Start", "Y001": "Motor"}, "Start", "Motor", LinkTarget("Start", "Motor")),
        ({"X001": "Start", "Y002": "Motor"}, "Start", "Motor", LinkTarget("Start", "Motor")),
        # A name that is gone stays on its address, under its new name.
        ({"X001": "Start", "Y001": "Run"}, "Start", "Motor", LinkTarget("Start", "Run")),
        ({"Y001": "Motor"}, "Start", "Motor", LinkTarget("X001", "Motor")),
        ({"X001": "Begin"}, "Start", None, LinkTarget("Begin", None)),
        # A name on no CLICK address is not the user's: carried as it is.
        ({}, "Scratch", "Motor", LinkTarget("Scratch", "Motor")),
    ],
)
def test_links(new, feedback, enable, target):
    plan = plan_carry(OLD, _maps(new), {}, {feedback: enable})
    assert plan.links == {feedback: target}
    assert plan.released == ()


def test_the_plan_takes_pyrungs_reload_shape():
    plan = plan_carry(
        OLD,
        _maps({"X001": "Begin", "Y001": "Run", "C1": "Mode"}),
        {"Start": True, "Mode": True, "Speed": 4},
        {"Start": "Motor", "X002": None},
    )
    assert plan.as_dap() == {
        "forces": {"Start": "Begin", "Mode": "Mode", "Speed": None},
        "links": {
            "Start": {"en": "Run", "fb": "Begin"},
            "X002": {"cut": True, "fb": "X002"},
        },
    }


def test_the_notice_lists_releases_then_renames():
    plan = plan_carry(
        OLD,
        _maps({"X001": "Begin", "DS5": "Speed"}),
        {"Mode": True, "Speed": 4, "Start": True},
        {"X002": "Start"},
    )
    assert plan.notice == (
        "Writing releases 2 forces: Mode (gone), Speed (DS1 -> DS5). "
        "Kept under new names: Start -> Begin (X001), "
        "the link on X002 from Start -> link on X002 from Begin."
    )
    assert CarryPlan().notice == ""
    one = plan_carry(OLD, _maps({}), {"Mode": True}, {})
    assert one.notice == "Writing releases 1 force: Mode (gone)."


def test_address_of():
    assert address_of("Motor", OLD) == "Y001"
    assert address_of("Y001", OLD) is None, "Y001 goes by Motor"
    assert address_of("Y002", OLD) == "Y002"
    assert address_of("Scratch", OLD) is None
