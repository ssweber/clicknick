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
        # A pure rename: the address keeps the force under its new name.
        ({"C1": "Auto"}, "Mode", "Auto", "Mode -> Auto (C1)"),
        ({}, "Mode", "C1", "Mode -> C1"),
        ({"C2": "Auto"}, "C2", "Auto", "C2 -> Auto"),
        # Its name now sits on another address: released.
        ({"DS1": "Spare", "DS5": "Speed"}, "Speed", None, "Speed (now on DS5, was DS1)"),
        ({"DS5": "Speed"}, "Speed", None, "Speed (now on DS5, was DS1)"),
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
    new = _maps({"DF1": "Probe", "DF2": "Temp"})
    plan = plan_carry(OLD, new, {"Temp": 20.5}, {})
    assert plan.forces == {"Temp": None}
    assert plan.released == ("Temp (now on DF2, was DF1)",)
    plan = plan_carry(OLD, new, {"Temp": 20.5}, {}, analog=("DF1",))
    assert plan.forces == {"Temp": "Probe"}


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


@pytest.mark.parametrize(
    ("new", "feedback", "enable", "moved"),
    [
        ({"X001": "Start", "Y005": "Motor"}, "Start", "Motor",
         ("the link on Start now follows Motor on Y005 (was Y001)",)),
        ({"X005": "Start", "Y001": "Motor"}, "Start", "Motor",
         ("the link on Start now feeds X005 (was X001)",)),
        ({"X005": "Start"}, "Start", None,
         ("the cut on Start now feeds X005 (was X001)",)),
        # A rename, or both names where they were: nothing moved.
        ({"X001": "Start", "Y001": "Run"}, "Start", "Motor", ()),
        ({"X001": "Start", "Y001": "Motor"}, "Start", "Motor", ()),
    ],
)  # fmt: skip
def test_a_link_that_follows_a_name_to_another_address_is_noted(new, feedback, enable, moved):
    plan = plan_carry(OLD, _maps(new), {}, {feedback: enable})
    assert plan.moved == moved


def test_the_plan_takes_pyrungs_reload_shape():
    plan = plan_carry(
        OLD,
        _maps({"X001": "Begin", "Y001": "Run", "C1": "Mode"}),
        {"Start": True, "Mode": True, "Speed": 4},
        {"Start": "Motor", "X002": None},
    )
    assert plan.as_dap() == {
        "forces": {"Start": "Begin", "Mode": "Mode", "Speed": "DS1"},
        "links": {
            "Start": {"en": "Run", "fb": "Begin"},
            "X002": {"cut": True, "fb": "X002"},
        },
    }


def test_the_notice_lists_releases_renames_then_moves():
    plan = plan_carry(
        OLD,
        _maps({"X001": "Begin", "C2": "Mode", "DS5": "Speed", "Y005": "Motor"}),
        {"Mode": True, "Speed": 4, "Start": True},
        {"X002": "Start", "X003": "Motor"},
    )
    assert plan.notice == (
        "Writing releases 2 forces: Mode (now on C2, was C1), Speed (now on DS5, was DS1). "
        "Kept under new names: Start -> Begin (X001), "
        "the link on X002 now comes from Begin (was Start). "
        "The link on X003 now follows Motor on Y005 (was Y001)."
    )
    assert plan.describe(written=True).startswith("Released 2 forces: Mode (now on C2")
    assert CarryPlan().notice == ""
    one = plan_carry(OLD, _maps({"DS5": "Speed"}), {"Speed": 4}, {})
    assert one.notice == "Writing releases 1 force: Speed (now on DS5, was DS1)."
    assert one.describe(written=True) == "Released 1 force: Speed (now on DS5, was DS1)."


@pytest.mark.parametrize(
    ("old", "new", "links", "kept", "dropped", "note"),
    [
        # Start moves from X001 to X002, which has its own cut: Start's link wins.
        ({"X001": "Start", "Y001": "Motor"}, {"X002": "Start", "Y001": "Motor"},
         {"Start": "Motor", "X002": None}, ("Start", LinkTarget("Start", "Motor")), "X002",
         "the cut on X002 is dropped for the link on Start"),
        # The same on internal bits: Run moves from C1 to C2, C2 has a link from C5.
        ({"C1": "Run", "C5": "Aux"}, {"C2": "Run", "C5": "Aux"},
         {"Run": "Aux", "C2": "Aux"}, ("Run", LinkTarget("Run", "Aux")), "C2",
         "the link on C2 is dropped for the link on Run"),
        # Listed the other way round, the followed link still wins.
        ({"X001": "Start", "Y001": "Motor"}, {"X002": "Start", "Y001": "Motor"},
         {"X002": None, "Start": "Motor"}, ("Start", LinkTarget("Start", "Motor")), "X002",
         "the cut on X002 is dropped for the link on Start"),
    ],
)  # fmt: skip
def test_two_links_on_one_new_feedback_keep_the_one_that_followed_its_name(
    old, new, links, kept, dropped, note
):
    plan = plan_carry(_maps(old), _maps(new), {}, links)
    assert plan.links[kept[0]] == kept[1]
    assert plan.links[dropped] is None
    assert note in plan.moved
    about = [t for t in plan.moved + plan.renamed if t.split(" ", 3)[3].startswith(dropped + " ")]
    assert about == [note], "no note says the dropped link was kept"
    assert plan.as_dap()["links"][dropped] is None


def test_address_of():
    assert address_of("Motor", OLD) == "Y001"
    assert address_of("Y001", OLD) is None, "Y001 goes by Motor"
    assert address_of("Y002", OLD) == "Y002"
    assert address_of("Scratch", OLD) is None
