"""Tests for clicknick.ladder.csv_contract."""

import pytest

from clicknick.ladder.csv_contract import (
    CONDITION_COLUMNS,
    CSV_HEADER,
    TOTAL_COLUMNS,
    is_valid_marker,
    validate_header,
)
from clicknick.ladder.csv_parser import parse_row


def test_header_exact_match() -> None:
    validate_header(list(CSV_HEADER))


def test_header_mismatch_rejected() -> None:
    bad = list(CSV_HEADER)
    bad[0] = "Marker"
    with pytest.raises(ValueError, match="Invalid CSV header"):
        validate_header(bad)


def test_total_columns_is_33() -> None:
    assert len(CONDITION_COLUMNS) == 31
    assert TOTAL_COLUMNS == 33


def test_parse_row_requires_33_columns() -> None:
    with pytest.raises(ValueError, match="Expected 33 columns"):
        parse_row("R,X001,:out(Y001)", syntax="canonical")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("R", True),
        ("", True),
        ("X", False),
        ("r", False),
    ],
)
def test_marker_validation(value: str, expected: bool) -> None:
    assert is_valid_marker(value) is expected
