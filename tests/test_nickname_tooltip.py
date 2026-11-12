"""The overlay's nickname tooltip and the Tag Browser suffix show Retentive and initial value alike."""

import pytest
from pyclickplc.banks import PAIRED_RETENTIVE_TYPES, DataType

from clicknick.data.address_store import AddressStore
from clicknick.data.nickname_manager import NicknameManager
from clicknick.models.address_row import AddressRow, value_notes
from clicknick.models.nickname import Nickname
from clicknick.views.address_editor.view_builder import find_paired_row
from clicknick.views.nav_window.outline_panel import OutlinePanel


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


class _Source:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, rows):
        self._rows = rows

    def load_all_addresses(self):
        return self._rows

    def save_changes(self, rows):
        return len(rows)


# (memory type, data type, retentive, its T/CT row's retentive or None, initial value)
_CASES = [
    ("C", DataType.BIT, True, None, "1"),
    ("C", DataType.BIT, False, None, "1"),
    ("CT", DataType.BIT, False, None, "1"),
    ("CT", DataType.BIT, True, None, "0"),
    ("T", DataType.BIT, True, None, "0"),
    ("TD", DataType.INT, True, True, "0"),
    ("TD", DataType.INT, False, False, "500"),
    ("TD", DataType.INT, False, True, "500"),
    ("TD", DataType.INT, True, False, "500"),
    ("CTD", DataType.INT2, False, False, "7"),
    ("CTD", DataType.INT2, False, True, "7"),
    ("CTD", DataType.INT2, True, False, "7"),
    ("DS", DataType.INT, True, None, "42"),
    ("DF", DataType.FLOAT, False, None, "1.5"),
    ("TXT", DataType.TXT, False, None, "0"),
    ("TXT", DataType.TXT, False, None, ""),
]


@pytest.mark.parametrize(("memory_type", "data_type", "retentive", "pair", "initial_value"), _CASES)
def test_tooltip_and_tag_browser_agree(
    tk_root, memory_type, data_type, retentive, pair, initial_value
):
    """The overlay tooltip, the Tag Browser and the Address Editor's masked initial value agree.

    A TD/CTD row's Retentive is its T/CT row's, in all three.
    """
    row = AddressRow(
        memory_type=memory_type,
        address=1,
        nickname="Name",
        data_type=data_type,
        retentive=retentive,
        initial_value=initial_value,
        used=True,
    )
    rows = {row.addr_key: row}
    pair_type = PAIRED_RETENTIVE_TYPES.get(memory_type)
    if pair is not None:
        pair_row = AddressRow(memory_type=pair_type, address=1, nickname="Pair", retentive=pair)
        rows[pair_row.addr_key] = pair_row
    store = AddressStore(_Source(rows))
    store.load_initial_data()

    manager = NicknameManager()
    manager.set_store(store)
    lines = manager.get_nickname_details("Name").splitlines()
    tooltip_notes = lines[1].replace("Initial Value = ", "") if len(lines) > 1 else ""

    panel = OutlinePanel(tk_root, on_select=lambda *_: None)
    try:
        panel.build_tree(store.visible_state)
        item = next(i for i in panel._item_data.values() if i.addr_key == row.addr_key)
        iid = next(k for k, v in panel._item_data.items() if v is item)
        suffix_notes = panel.tree.item(iid, "text").partition(" = ")[2]
    finally:
        panel.destroy()
    assert tooltip_notes == suffix_notes

    paired = find_paired_row(row, list(store.visible_state.values()))
    masked = row.is_initial_value_masked(paired.retentive if paired else row.retentive)
    if masked:
        assert "Initial Value" not in " ".join(lines)
    else:
        initial, _ = value_notes(
            memory_type,
            row.data_type_display,
            paired.retentive if paired else row.retentive,
            initial_value,
        )
        assert ("Initial Value" in " ".join(lines)) == bool(initial)
