"""Shared CLICK name rules used by PLC and DataView names."""

import pytest

from clicknick.models.name_validation import validate_click_name


@pytest.mark.parametrize("name", ["A", "A" * 24, "Line 1", "Line_1", "Line-1"])
def test_valid_click_names(name: str) -> None:
    assert validate_click_name(name) == (True, "")


@pytest.mark.parametrize("name", ["", "   ", "A" * 25, "Line/1", "Line.1", "Line@1"])
def test_invalid_click_names(name: str) -> None:
    assert validate_click_name(name)[0] is False
