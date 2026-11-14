"""Outline panel: SC/SD entries, expanded state across refreshes, rename arguments."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pyclickplc.banks import DataType

from clicknick.models.address_row import AddressRow
from clicknick.views.nav_window import outline_panel
from clicknick.views.nav_window.outline_panel import OutlinePanel


def _rows(*specs) -> dict[int, AddressRow]:
    rows = {}
    for memory_type, address, nickname in specs:
        row = AddressRow(memory_type=memory_type, address=address, nickname=nickname)
        rows[row.addr_key] = row
    return rows


@pytest.fixture
def panel(tk_root):
    selected: list[tuple[str, list]] = []
    renamed: list[tuple] = []
    widget = OutlinePanel(
        tk_root,
        on_select=lambda path, leaves: selected.append((path, leaves)),
        on_rename=lambda *args: renamed.append(args),
    )
    widget.selected = selected
    widget.renamed = renamed
    yield widget
    widget.destroy()


def _iid_of(panel: OutlinePanel, predicate) -> str:
    return next(iid for iid, item in panel._item_data.items() if predicate(item))


def test_flat_system_entry_selects_by_its_exact_nickname(panel):
    panel.build_tree(_rows(("SC", 1, "_Always_On"), ("DS", 1, "Pump_Run")))
    iid = _iid_of(panel, lambda item: item.leaf == ("SC", 1))
    panel.tree.selection_set(iid)

    panel._on_double_click(None)

    assert panel.selected == [("_Always_On", [("SC", 1)])]


def test_system_group_stays_open_across_a_refresh(panel):
    rows = _rows(("SC", 1, "_Always_On"), ("SD", 1, "_Scan_Time"))
    panel.build_tree(rows)
    sc = _iid_of(panel, lambda item: item.text == "SC")
    panel.tree.item(sc, open=True)

    panel.refresh(rows)

    assert panel.tree.item(_iid_of(panel, lambda item: item.text == "SC"), "open")
    assert not panel.tree.item(_iid_of(panel, lambda item: item.text == "SD"), "open")


class _Dialog:
    def __init__(self, parent, current_text, is_array):
        self.args = (current_text, is_array)
        self.result = "NEW"


@pytest.mark.parametrize(
    ("rows", "text", "occurrence", "expected"),
    [
        # a segment that is a string prefix of its own path
        (
            [("DS", 1, "Tank_T_A"), ("DS", 3, "Tank_T_B"), ("DS", 2, "T_Ambient")],
            "Tank_T",
            0,
            ("Tank_", "T", "NEW", False, False),
        ),
        # the inner of two equal names
        (
            [("DS", 1, "Pump_Pump_X"), ("DS", 3, "Pump_Pump_Y"), ("DS", 2, "Pump_Status")],
            "Pump",
            1,
            ("Pump_", "Pump", "NEW", False, False),
        ),
        # an array keeps its digits out of the renamed text
        (
            [("DS", 1, "Pump01_Run"), ("DS", 2, "Pump02_Run")],
            "Pump[01-02]",
            0,
            ("", "Pump", "NEW", True, False),
        ),
    ],
)
def test_rename_passes_the_segment_and_what_precedes_it(
    panel, monkeypatch, rows, text, occurrence, expected
):
    monkeypatch.setattr(outline_panel, "RenameDialog", _Dialog)
    monkeypatch.setattr(panel, "wait_window", lambda dialog: None)
    panel.build_tree(_rows(*rows))
    matches = [iid for iid, item in panel._item_data.items() if item.text == text]
    panel._selected_iid = matches[occurrence]

    panel._show_rename_dialog()

    assert panel.renamed == [expected]


def test_td_row_follows_its_timer_in_the_outline(panel):
    """A TD row shows its initial value only when its T row is not Retentive, as the editor does."""
    timer = AddressRow(memory_type="T", address=1, nickname="Tmr", retentive=True)
    value = AddressRow(
        memory_type="TD",
        address=1,
        nickname="Tmr_Value",
        data_type=DataType.INT,
        retentive=False,
        initial_value="500",
    )
    panel.build_tree({timer.addr_key: timer, value.addr_key: value})

    texts = [panel.tree.item(iid, "text") for iid in panel._item_data]

    assert not any("500" in text for text in texts)


def test_rename_is_off_for_system_entries_and_gaps(panel, monkeypatch):
    panel.build_tree(
        _rows(
            ("SC", 1, "_Always_On"),
            ("DS", 1, "Mtr1__Debug"),
            ("DS", 2, "Mtr1__Other"),
            ("DS", 3, "Mtr1_Run"),
            ("DS", 4, "Mtr2_Run"),
        )
    )
    monkeypatch.setattr(panel._context_menu, "post", lambda *args: None)

    def menu_state(predicate) -> str:
        iid = _iid_of(panel, predicate)
        monkeypatch.setattr(panel.tree, "identify_row", lambda y: iid)
        panel._on_right_click(SimpleNamespace(y=0, x_root=0, y_root=0))
        return str(panel._context_menu.entrycget(0, "state"))

    assert menu_state(lambda item: item.text == "Run") == "normal"
    assert menu_state(lambda item: item.leaf == ("SC", 1)) == "disabled"
    assert menu_state(lambda item: item.text == "SC") == "disabled"
    assert menu_state(lambda item: item.text == "_") == "disabled"


def test_sc_group_state_does_not_clash_with_a_folder_of_that_name(panel):
    rows = _rows(("SC", 1, "_Always_On"), ("DS", 1, "SC1_X"), ("DS", 2, "SC2_X"))
    panel.build_tree(rows)
    folder = _iid_of(panel, lambda item: item.text == "SC[1-2]")
    panel.tree.item(folder, open=True)

    panel.refresh(rows)

    assert not panel.tree.item(_iid_of(panel, lambda item: item.text == "SC"), "open")
    assert panel.tree.item(_iid_of(panel, lambda item: item.text == "SC[1-2]"), "open")
