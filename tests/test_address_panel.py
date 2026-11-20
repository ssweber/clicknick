"""Cover the Address Editor panel and tab strip: hidden columns, read-only cells and Ctrl+W."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.utils import mdb_operations
from clicknick.views.address_editor.panel import AddressPanel
from clicknick.views.address_editor.panel_constants import (
    COL_COMMENT,
    COL_INIT_VALUE,
    COL_NICKNAME,
    COL_RETENTIVE,
)
from clicknick.views.address_editor.view_builder import build_unified_view
from clicknick.views.address_editor.window import AddressEditorWindow
from clicknick.widgets.char_limit_tooltip import CharLimitTooltip
from clicknick.widgets.custom_notebook import CustomNotebook


class _DataSource:
    supports_used_field = True
    stored_row = staticmethod(mdb_operations.stored_row)
    file_path = "test.mdb"
    is_read_only = False

    def load_all_addresses(self):
        return {}

    def save_changes(self, rows):
        return 0


@pytest.fixture
def store() -> AddressStore:
    s = AddressStore(_DataSource())
    s.load_initial_data()
    return s


@pytest.fixture
def panel(tk_root, store):
    view = build_unified_view(store.visible_state)
    store.set_unified_view(view)
    frame = ttk.Frame(tk_root)
    panel = AddressPanel(frame, store, section_boundaries=view.section_boundaries)
    panel.pack()
    panel.initialize_from_view(view.rows)
    yield panel
    frame.destroy()


def _row_index(panel, memory_type: str, address: int) -> int:
    key = get_addr_key(memory_type, address)
    return next(i for i, row in enumerate(panel.rows) if row.addr_key == key)


def _menu_labels(panel, *, display_col: int, row: int) -> list[str]:
    """Return what the right-click menu offers at a displayed column."""
    panel._update_context_menu("table", row, panel.sheet.MT.datacn(display_col))
    return list(panel.sheet.MT.extra_table_rc_menu_funcs)


DISCARD = "↩ Discard changes"


def _edit(store, memory_type: str, address: int, **fields) -> None:
    with store.edit_session("Edit") as session:
        for field, value in fields.items():
            session.set_field(get_addr_key(memory_type, address), field, value)


def test_hiding_used_leaves_the_context_menu_on_the_right_column(panel, store) -> None:
    _edit(store, "DS", 1, nickname="Old", comment="note")
    panel.hide_used_var.set(True)
    panel._toggle_used_column()
    row = _row_index(panel, "DS", 1)

    # With Used hidden, displayed column 0 is Nickname and 1 is Comment
    assert panel.sheet.MT.datacn(0) == COL_NICKNAME
    assert DISCARD in _menu_labels(panel, display_col=0, row=row)
    assert "Edit Annotations..." not in _menu_labels(panel, display_col=0, row=row)
    assert "Edit Annotations..." in _menu_labels(panel, display_col=1, row=row)


def test_discarding_a_cell_with_used_hidden_discards_that_cell(panel, store) -> None:
    _edit(store, "DS", 1, nickname="Old", comment="note")
    panel.hide_used_var.set(True)
    panel._toggle_used_column()
    row = _row_index(panel, "DS", 1)
    panel.sheet.select_cell(row, 1)  # Comment, displayed second

    panel._discard_cell_changes()

    key = get_addr_key("DS", 1)
    assert store.visible_state[key].comment == ""
    assert store.visible_state[key].nickname == "Old"


def test_char_limit_follows_the_data_column_with_used_hidden(panel) -> None:
    panel.hide_used_var.set(True)
    panel._toggle_used_column()
    scheduled = []
    sheet = Mock(after=lambda ms, fn: scheduled.append(fn))
    sheet.MT.datacn = panel.sheet.MT.datacn
    tooltip = CharLimitTooltip.__new__(CharLimitTooltip)
    tooltip.sheet = sheet
    tooltip.char_limits = {COL_NICKNAME: 24, COL_COMMENT: 128}
    tooltip._destroy_tooltip = Mock()

    tooltip._on_edit_begin(Mock(column=0, value=""))  # displayed Nickname

    assert len(scheduled) == 1
    tooltip._setup_tracking = Mock()
    scheduled[0]()
    tooltip._setup_tracking.assert_called_once_with(24)


@pytest.mark.parametrize("memory_type", ["SC", "SD"])
def test_init_and_retentive_cells_of_read_only_rows_take_no_edit(panel, memory_type) -> None:
    row = _row_index(panel, memory_type, 1)
    sheet = panel.sheet

    for col in (COL_INIT_VALUE, COL_RETENTIVE):
        assert sheet.MT.get_cell_kwargs(row, col, key="readonly"), col


def test_retentive_cells_of_editable_rows_stay_editable(panel) -> None:
    row = _row_index(panel, "DS", 1)

    assert not panel.sheet.MT.get_cell_kwargs(row, COL_RETENTIVE, key="readonly")


def test_a_notebook_binds_no_ctrl_w_of_its_own(tk_root) -> None:
    top = tk.Toplevel(tk_root)
    notebook = CustomNotebook(top)
    try:
        assert not top.bind_all("<Control-w>")
        assert not notebook.bind("<Control-w>")
    finally:
        top.destroy()


def test_close_icons_survive_the_first_notebook(tk_root) -> None:
    import gc

    first = CustomNotebook(tk_root)
    first.destroy()
    del first
    gc.collect()

    CustomNotebook(tk_root)

    assert {"img_close", "img_closeactive", "img_closepressed"} <= set(tk_root.image_names())


def test_ctrl_w_after_a_notebook_is_destroyed_raises_nothing(tk_root) -> None:
    top = tk.Toplevel(tk_root)
    CustomNotebook(top).pack()
    top.destroy()

    assert not tk_root.bind_all("<Control-w>")


def test_removing_a_block_keeps_the_rest_of_the_comment(store) -> None:
    _edit(store, "DS", 1, comment="<Pumps> Fill")
    _edit(store, "DS", 2, comment="</Pumps>")
    row = store.visible_state[get_addr_key("DS", 1)]
    window = AddressEditorWindow.__new__(AddressEditorWindow)
    window._store = store
    panel = Mock(rows=[row], _displayed_rows=[0])
    window._get_selected_row_indices = lambda: [0]
    window._get_current_panel = lambda: panel
    window._update_add_block_button_state = Mock()
    window._update_status = Mock()

    window._on_remove_block_clicked()

    assert store.visible_state[get_addr_key("DS", 1)].comment == "Fill"
    assert store.visible_state[get_addr_key("DS", 2)].comment == ""


def test_analysis_filters_use_the_current_analysis(tk_root, store) -> None:
    view = build_unified_view(store.visible_state)
    store.set_unified_view(view)
    frame = ttk.Frame(tk_root)
    old = Mock(is_available=True, **{"get_role_keys.return_value": {1}})
    new = Mock(is_available=True, **{"get_role_keys.return_value": {2}})
    current = [old]
    panel = AddressPanel(frame, store, get_analysis_service=lambda: current[0])
    try:
        assert panel._resolve_analysis_prefix("input", None) == {1}
        # After a project change, a new ConnectionSession has its own analysis service.
        # The panel reads the getter each time, so it uses the new session's roles.
        current[0] = new
        assert panel._resolve_analysis_prefix("input", None) == {2}
    finally:
        frame.destroy()


@pytest.mark.parametrize("edge", [" {}", "{} ", "\t{}", "{}\t"])
@pytest.mark.parametrize(
    ("col", "field", "stored"),
    [
        (COL_NICKNAME, "nickname", "Pump"),
        (COL_INIT_VALUE, "initial_value", "5"),
    ],
)
def test_a_cell_typed_with_an_edge_space_or_tab_shows_the_value_stored(
    panel, store, col, field, stored, edge
):
    """Typing "Pump\\t" over "Pump" changes nothing, and the cell says so.

    CLICK keeps no space or tab at either end of a nickname or a number.
    """
    _edit(store, "DS", 1, retentive=False, **{field: stored})
    row = _row_index(panel, "DS", 1)
    frames = len(store.undo_stack)
    typed = edge.format(stored)

    panel.sheet.set_cell_data(row, col, typed)
    panel._on_sheet_modified(SimpleNamespace(cells={"table": {(row, col): stored}}))

    assert panel.sheet.get_cell_data(row, col) == stored
    assert getattr(store.visible_state[get_addr_key("DS", 1)], field) == stored
    assert len(store.undo_stack) == frames


@pytest.mark.parametrize("edge", [" {}", "{} ", "\t{}", "{}\t"])
def test_a_comment_typed_with_an_edge_space_or_tab_keeps_it(panel, store, edge):
    """Typing "Pump\\t" over the comment "Pump" is an edit. The row and the cell keep the tab.

    CLICK 4.00 keeps the spaces at either end of a comment.
    """
    _edit(store, "DS", 1, comment="Pump")
    row = _row_index(panel, "DS", 1)
    frames = len(store.undo_stack)
    typed = edge.format("Pump")

    panel.sheet.set_cell_data(row, COL_COMMENT, typed)
    panel._on_sheet_modified(SimpleNamespace(cells={"table": {(row, COL_COMMENT): "Pump"}}))

    assert panel.sheet.get_cell_data(row, COL_COMMENT) == typed
    assert store.visible_state[get_addr_key("DS", 1)].comment == typed
    assert not store.has_errors()
    assert len(store.undo_stack) == frames + 1


def test_pasted_comments_keep_their_edge_spaces(panel, store):
    rows = [_row_index(panel, "DS", 1), _row_index(panel, "DS", 2)]
    pasted = [" Note2 ", "\tNote3"]
    for row, text in zip(rows, pasted, strict=True):
        panel.sheet.set_cell_data(row, COL_COMMENT, text)

    panel._on_sheet_modified(
        SimpleNamespace(cells={"table": {(row, COL_COMMENT): "" for row in rows}})
    )

    keys = [get_addr_key("DS", 1), get_addr_key("DS", 2)]
    assert [store.visible_state[key].comment for key in keys] == pasted
    assert not store.has_errors()


def test_the_footer_counts_only_the_rows_that_the_filter_shows() -> None:
    rows = [
        SimpleNamespace(addr_key=1, has_reportable_error=True),
        SimpleNamespace(addr_key=2, has_reportable_error=False),
        SimpleNamespace(addr_key=3, has_reportable_error=True),  # hidden by the filter
    ]
    panel = AddressPanel.__new__(AddressPanel)
    panel.rows = rows
    panel._displayed_rows = [0, 1]
    panel._store = SimpleNamespace(is_dirty=lambda key: key in {2, 3})
    panel.status_label = Mock()

    panel._update_status()

    panel.status_label.config.assert_called_once_with(text="Rows shown: 2 | Changed: 1 | Errors: 1")
