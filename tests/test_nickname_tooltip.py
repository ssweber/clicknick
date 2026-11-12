"""The overlay's nickname tooltip and the Tag Browser suffix show Retentive and initial value alike."""

import pytest
from pyclickplc.banks import DataType

from clicknick.models.address_row import AddressRow
from clicknick.models.nickname import Nickname


def _details(address_type: str, data_type: str, retentive: bool, initial_value: str = "0") -> str:
    return Nickname(
        nickname="Name",
        address=f"{address_type}1",
        data_type_display=data_type,
        initial_value=initial_value,
        retentive=retentive,
        address_type=address_type,
    ).details()


def _suffix(memory_type: str, data_type: int, retentive: bool, initial_value: str = "0") -> str:
    return AddressRow(
        memory_type=memory_type,
        address=1,
        data_type=data_type,
        retentive=retentive,
        initial_value=initial_value,
    ).outline_suffix


def test_retentive_ds_shows_no_initial_value():
    assert "Initial Value" not in _details("DS", "INT", retentive=True)


def test_non_retentive_ds_shows_its_initial_value():
    assert "Initial Value = 100" in _details("DS", "INT", retentive=False, initial_value="100")


def test_retentive_counter_is_the_default():
    assert "Retentive" not in _details("CT", "BIT", retentive=True)


def test_retentive_c_bit_is_shown():
    assert "Retentive" in _details("C", "BIT", retentive=True)


def test_non_retentive_counter_is_shown_as_non_retentive():
    details = _details("CT", "BIT", retentive=False)
    assert details.splitlines()[-1] == "Non-retentive"
    assert _suffix("CT", DataType.BIT, retentive=False) == "  : BIT = Non-retentive"


def test_retentive_timer_value_shows_no_initial_value():
    assert len(_details("TD", "INT", retentive=True).splitlines()) == 1
    assert _suffix("TD", DataType.INT, retentive=True) == "  : INT"


def test_non_retentive_timer_value_shows_its_initial_value():
    assert "Initial Value = 500" in _details("TD", "INT", retentive=False, initial_value="500")
    assert _suffix("TD", DataType.INT, retentive=False, initial_value="500") == "  : INT = 500"


def test_default_initial_value_is_not_shown():
    assert len(_details("DS", "INT", retentive=False, initial_value="0").splitlines()) == 1
    assert _suffix("DS", DataType.INT, retentive=False, initial_value="0") == "  : INT"


@pytest.mark.parametrize(
    ("memory_type", "data_type", "retentive", "initial_value"),
    [
        ("C", DataType.BIT, True, "1"),
        ("C", DataType.BIT, False, "1"),
        ("CT", DataType.BIT, False, "1"),
        ("CT", DataType.BIT, True, "0"),
        ("T", DataType.BIT, True, "0"),
        ("TD", DataType.INT, True, "0"),
        ("TD", DataType.INT, False, "500"),
        ("CTD", DataType.INT2, False, "7"),
        ("DS", DataType.INT, True, "42"),
        ("DF", DataType.FLOAT, False, "1.5"),
        ("TXT", DataType.TXT, False, "0"),
        ("TXT", DataType.TXT, False, ""),
    ],
)
def test_tooltip_and_tag_browser_agree(memory_type, data_type, retentive, initial_value):
    row = AddressRow(
        memory_type=memory_type,
        address=1,
        nickname="Name",
        data_type=data_type,
        retentive=retentive,
        initial_value=initial_value,
    )
    details = Nickname(
        nickname=row.nickname,
        address=row.display_address,
        data_type_display=row.data_type_display,
        initial_value=row.initial_value,
        retentive=row.retentive,
        address_type=row.memory_type,
    ).details()
    lines = details.splitlines()
    tooltip_notes = lines[1].replace("Initial Value = ", "") if len(lines) > 1 else ""
    suffix_notes = row.outline_suffix.partition(" = ")[2]
    assert tooltip_notes == suffix_notes
