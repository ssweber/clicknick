"""Address Editor window: cell editor vs shortcuts, Fill Down targets, Tag Browser rename."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyclickplc.addresses import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.views.address_editor.panel_constants import COL_COMMENT, COL_NICKNAME
from clicknick.views.address_editor.window import AddressEditorWindow

MODULE = "clicknick.views.address_editor.window"


class _DataSource:
    supports_used_field = True
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


@pytest.fixture(autouse=True)
def _no_dialogs(monkeypatch) -> None:
    monkeypatch.setattr(f"{MODULE}.messagebox", Mock())


def _panel(rows, *, editor_open: bool = False):
    """A panel showing `rows`, whose open cell editor commits by closing."""
    text_editor = SimpleNamespace(open=editor_open)
    mt = SimpleNamespace(text_editor=text_editor)

    def commit() -> None:
        text_editor.open = False

    mt.mouseclick_outside_editor_or_dropdown_all_canvases = Mock(side_effect=commit)
    return SimpleNamespace(
        sheet=SimpleNamespace(MT=mt), rows=rows, _displayed_rows=list(range(len(rows)))
    )


def _window(store, panel) -> AddressEditorWindow:
    window = AddressEditorWindow.__new__(AddressEditorWindow)
    window._store = store
    window._tabs = {".tab": (panel, None)}
    window._get_current_panel = lambda: panel
    window.status_var = Mock()
    window._update_status = Mock()
    window.close_without_prompt = Mock()
    return window


def test_undo_and_redo_do_nothing_while_a_cell_editor_is_open() -> None:
    window = _window(Mock(), _panel([], editor_open=True))

    window._on_undo()
    window._on_redo()

    window._store.undo.assert_not_called()
    window._store.redo.assert_not_called()


def test_undo_works_once_the_cell_editor_is_closed() -> None:
    window = _window(Mock(), _panel([]))

    window._on_undo()

    window._store.undo.assert_called_once()


def test_save_commits_the_open_cell_editor_first() -> None:
    panel = _panel([], editor_open=True)
    window = _window(Mock(), panel)
    window._store.has_errors = Mock(return_value=False)
    window._store.has_unsaved_changes = Mock(
        side_effect=lambda: not panel.sheet.MT.text_editor.open
    )

    window._save_all()

    panel.sheet.MT.mouseclick_outside_editor_or_dropdown_all_canvases.assert_called_once()
    # the commit came before the unsaved-changes check, so typed text was seen
    window._store.save_all_changes.assert_called_once()


def test_closing_commits_the_open_cell_editor_before_asking_about_unsaved_changes() -> None:
    panel = _panel([], editor_open=True)
    window = _window(Mock(), panel)
    # Typed text is an unsaved change only once it has been committed
    window._store.has_unsaved_changes = Mock(
        side_effect=lambda: not panel.sheet.MT.text_editor.open
    )
    window._get_save_label = lambda: "Sync"
    window._save_all = Mock()

    import clicknick.views.address_editor.window as module

    module.messagebox.askyesnocancel.return_value = None  # the user cancels

    window._on_closing()

    module.messagebox.askyesnocancel.assert_called_once()
    window.close_without_prompt.assert_not_called()


def _fill_down_window(store, keys):
    rows = [store.visible_state[k] for k in keys]
    window = _window(store, _panel(rows))
    window._get_selected_row_indices = lambda: list(range(len(rows)))
    return window


def test_fill_down_over_t_td_numbers_only_the_t_rows(store) -> None:
    with store.edit_session("Setup") as session:
        session.set_field(get_addr_key("T", 1), "nickname", "Delay1")
    keys = [get_addr_key(m, n) for n in range(1, 5) for m in ("T", "TD")][:7]  # T1 .. T4
    window = _fill_down_window(store, keys)
    window.fill_down_btn = Mock()
    window._update_fill_down_button_state = Mock()

    window._on_fill_down_clicked()

    nicknames = {k: store.visible_state[k].nickname for k in keys}
    assert [nicknames[get_addr_key("T", n)] for n in (1, 2, 3, 4)] == [
        "Delay1",
        "Delay2",
        "Delay3",
        "Delay4",
    ]
    assert all(nicknames[get_addr_key("TD", n)] == "" for n in (1, 2, 3))


def test_commit_retries_once_the_window_has_focus() -> None:
    panel = _panel([], editor_open=True)
    mt = panel.sheet.MT
    calls = []

    def commit() -> None:
        calls.append(1)
        if len(calls) > 1:  # the first try finds no focus and commits nothing
            mt.text_editor.open = False

    mt.mouseclick_outside_editor_or_dropdown_all_canvases = Mock(side_effect=commit)
    window = _window(Mock(), panel)
    window.focus_force = Mock()

    window.commit_open_cell_editor()

    window.focus_force.assert_called_once()
    assert not mt.text_editor.open


def test_discard_commits_the_open_cell_editor_first() -> None:
    panel = _panel([], editor_open=True)
    window = _window(Mock(), panel)
    window._store.has_unsaved_changes.return_value = False

    window._discard_changes()

    panel.sheet.MT.mouseclick_outside_editor_or_dropdown_all_canvases.assert_called_once()


def test_a_new_tab_applies_its_state_after_the_view_is_built(store, monkeypatch) -> None:
    from clicknick.views.address_editor.tab_state import TabState

    panel_cls = Mock()
    monkeypatch.setattr(f"{MODULE}.AddressPanel", panel_cls)
    window = AddressEditorWindow.__new__(AddressEditorWindow)
    window._store = store
    window._tabs = {}
    window._tab_counter = 0
    window._analysis_service = None
    window.notebook = Mock()
    window._bind_panel_selection = Mock()
    window._apply_state_to_panel = Mock()
    order = Mock()
    order.attach_mock(panel_cls.return_value.initialize_from_view, "initialize")
    order.attach_mock(window._apply_state_to_panel, "apply_state")

    assert window._create_new_tab(TabState.fresh())

    assert [c[0] for c in order.mock_calls] == ["initialize", "apply_state"]


def test_replace_all_in_nickname_column_leaves_comments_alone(tk_root) -> None:
    from clicknick.views.address_editor.sheet import AddressEditorSheet

    sheet = AddressEditorSheet(tk_root)
    data = [["", "Motor_Start", "Motor"], ["", "Motor_1", "Motor_1 overload"]]
    sheet.set_sheet_data(data)

    count = sheet.regex_replace_all_direct(
        "Motor", "Drive", selection_only=False, visible_rows_only=False, columns={COL_NICKNAME}
    )

    assert count == 2
    assert sheet.get_cell_data(0, COL_NICKNAME) == "Drive_Start"
    assert sheet.get_cell_data(0, COL_COMMENT) == "Motor"
    assert sheet.get_cell_data(1, COL_COMMENT) == "Motor_1 overload"


def test_styling_covers_rows_a_filter_hides(tk_root, store) -> None:
    from clicknick.views.address_editor.row_styler import AddressRowStyler
    from clicknick.views.address_editor.sheet import AddressEditorSheet

    with store.edit_session("Edit") as session:
        session.set_field(get_addr_key("DS", 1), "nickname", "bad name!")
    row = store.visible_state[get_addr_key("DS", 1)]
    sheet = AddressEditorSheet(tk_root)
    sheet.set_sheet_data([["", "", "", "", ""]])
    styler = AddressRowStyler(
        sheet=sheet,
        store=store,
        get_rows=lambda: [row],
    )

    styler.apply_all_styling()

    assert (0, COL_NICKNAME) in sheet.cell_notes


def test_rename_changes_nicknames_and_leaves_comments(tk_root) -> None:
    from clicknick.views.address_editor.sheet import AddressEditorSheet

    sheet = AddressEditorSheet(tk_root)
    sheet.set_sheet_data([["", "Motor_Start", "Motor"], ["", "Motor_1", "Motor_1 overload"]])
    panel = SimpleNamespace(
        sheet=sheet,
        filter_enabled_var=Mock(),
        filter_var=Mock(),
        row_filter_var=Mock(),
        _apply_filters=Mock(),
    )
    window = _window(Mock(), panel)

    window._on_rename("", "Motor", "Drive", False)

    assert [sheet.get_cell_data(r, COL_NICKNAME) for r in (0, 1)] == ["Drive_Start", "Drive_1"]
    assert [sheet.get_cell_data(r, COL_COMMENT) for r in (0, 1)] == ["Motor", "Motor_1 overload"]
    import clicknick.views.address_editor.window as module

    assert "Renamed 2 nicknames" in module.messagebox.showinfo.call_args.args[1]


@pytest.mark.parametrize("action", ["_save_all", "_discard_changes", "_on_closing"])
def test_a_cell_editor_that_will_not_commit_stops_save_discard_and_close(action) -> None:
    panel = _panel([], editor_open=True)
    panel.sheet.MT.mouseclick_outside_editor_or_dropdown_all_canvases = Mock()  # commits nothing
    window = _window(Mock(), panel)
    window.focus_force = Mock()
    import clicknick.views.address_editor.window as module

    getattr(window, action)()

    module.messagebox.showwarning.assert_called_once()
    window._store.save_all_changes.assert_not_called()
    window._store.discard_all_changes.assert_not_called()
    window.close_without_prompt.assert_not_called()
