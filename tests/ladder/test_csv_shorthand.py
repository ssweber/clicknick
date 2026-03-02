"""Tests for clicknick.ladder.csv_shorthand."""

import pytest

from clicknick.ladder.csv_contract import CONDITION_COLUMNS
from clicknick.ladder.csv_shorthand import normalize_shorthand_row


def test_shorthand_wire_fill() -> None:
    row = normalize_shorthand_row("R,X001,->,:,out(Y001)")
    assert row.marker == "R"
    assert row.conditions[0] == "X001"
    assert row.conditions[1:] == ("-",) * (len(CONDITION_COLUMNS) - 1)
    assert row.af == "out(Y001)"


def test_shorthand_blank_fill_and_blank_af() -> None:
    row = normalize_shorthand_row("R,X001,...,:,")
    assert row.marker == "R"
    assert row.conditions[0] == "X001"
    assert row.conditions[1:] == ("",) * (len(CONDITION_COLUMNS) - 1)
    assert row.af == ""


def test_missing_marker_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid marker"):
        normalize_shorthand_row("X001,->,:,out(Y001)")


def test_missing_separator_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one ':'"):
        normalize_shorthand_row("R,X001,->,out(Y001)")


def test_mixed_macros_rejected() -> None:
    with pytest.raises(ValueError, match="At most one shorthand macro"):
        normalize_shorthand_row("R,X001,->,...,:,out(Y001)")


def test_multiple_macros_rejected() -> None:
    with pytest.raises(ValueError, match="At most one shorthand macro"):
        normalize_shorthand_row("R,X001,->,->,:,out(Y001)")


def test_macro_not_last_explicit_token_rejected() -> None:
    with pytest.raises(ValueError, match="last explicit condition token"):
        normalize_shorthand_row("R,X001,->,X002,:,out(Y001)")
