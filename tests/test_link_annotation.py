"""Bench links written into a feedback tag's comment, and recognized there."""

from __future__ import annotations

import pytest

from clicknick.services.link_annotation import (
    comment_has_link,
    comment_with_link,
    profile_token,
    split_profile,
)
from clicknick.services.sim_state import BenchLink

AUX = BenchLink("Y001", on_delay="2s", off_delay="500ms")


def test_the_link_joins_the_comment_keeping_block_tag_and_text():
    comment = comment_with_link("<Pump:block> [public] Aux contact", AUX, "Motor_Run")
    assert comment == (
        "<Pump:block> [public, link=Motor_Run, on_delay=2s, off_delay=500ms] Aux contact"
    )
    assert comment_has_link(comment, AUX, ("Motor_Run", "Y001"))


def test_a_new_link_replaces_the_old_response_and_physical_name():
    comment = comment_with_link(
        "[link=Old, physical=Shared, profile=ramp:up=1.0|down=0.0] Level",
        BenchLink("Y002", on_delay="1s"),
        "Y002",
    )
    assert comment == "[link=Y002, on_delay=1s] Level"


def test_comment_has_link_compares_the_response():
    comment = comment_with_link("", AUX, "Motor_Run")
    assert not comment_has_link(comment, BenchLink("Y001", on_delay="3s"), ("Motor_Run",))
    assert not comment_has_link("Aux contact", AUX, ("Motor_Run",))


def test_a_cut_is_not_written():
    with pytest.raises(ValueError, match="cut"):
        comment_with_link("", BenchLink(None), "")


def test_profile_tokens():
    assert profile_token("ramp", "0.8", "-0.05") == "ramp:up=0.8|down=-0.05"
    assert split_profile("approach:toward=Setpoint|rate=0.3") == (
        "approach",
        {"toward": "Setpoint", "rate": "0.3"},
    )
    assert split_profile("2s") == ("", {})


def test_bit_enables_are_on_or_off():
    from clicknick.services.link_annotation import bit_enable, when_text

    assert bit_enable("Y001") and bit_enable("c5") and not bit_enable("DS1")
    assert not bit_enable("Motor_Run"), "only CLICK addresses"
    assert when_text("Y001", None) == ""
    assert when_text("Y001", 0) == " when OFF"
    assert when_text("DS1", 3) == " = 3"
