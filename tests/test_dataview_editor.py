"""Dataview Editor with real Tk widgets: saving, closing, inserting and undo."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyclickplc.addresses import get_addr_key, normalize_address
from pyclickplc.dataview import DataViewFile
from tksheet.functions import stored_event_dict

from clicknick.data.address_store import AddressStore
from clicknick.data.shared_dataview import SharedDataviewData
from clicknick.data_session import DataSession
from clicknick.models.address_row import AddressRow
from clicknick.views.dataview_editor import window as window_module
from clicknick.views.dataview_editor.panel import COL_ADDRESS, DataviewPanel
from clicknick.views.dataview_editor.window import DataviewEditorWindow

tk = pytest.importorskip("tkinter")

FIXTURES = Path(__file__).parent


@pytest.fixture(scope="module")
def tk_root():
    """One root for the whole module (per-test roots fail intermittently)."""
    for attempt in range(3):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:  # pragma: no cover - depends on the machine
            if attempt == 2:
                pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


class _MockDataSource:
    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, rows):
        self._rows = rows

    def load_all_addresses(self):
        return self._rows

    def save_changes(self, rows):
        return len(rows)


def _store(nicknames: dict[tuple[str, int], str] | None = None) -> AddressStore:
    rows = {
        get_addr_key(memory_type, address): AddressRow(
            memory_type=memory_type, address=address, nickname=nickname
        )
        for (memory_type, address), nickname in (nicknames or {}).items()
    }
    store = AddressStore(_MockDataSource(rows))
    store.load_initial_data()
    return store


@pytest.fixture()
def dialogs(monkeypatch):
    """Answer the message boxes and folder dialog; record what was shown."""
    state = SimpleNamespace(
        yes_no_cancel=[], yes_no=[], folders=[], new_names=[], shown=[], errors=[]
    )

    def ask_yes_no_cancel(title, message, **kwargs):
        state.shown.append(message)
        return state.yes_no_cancel.pop(0)

    def ask_yes_no(title, message, **kwargs):
        state.shown.append(message)
        return state.yes_no.pop(0)

    def show_error(title, message, **kwargs):
        state.errors.append(message)

    class FakeNewDataviewDialog:
        def __init__(self, parent):
            pass

        def show(self):
            return state.new_names.pop(0)

    monkeypatch.setattr("tkinter.messagebox.askyesnocancel", ask_yes_no_cancel)
    monkeypatch.setattr("tkinter.messagebox.askyesno", ask_yes_no)
    monkeypatch.setattr("tkinter.messagebox.showerror", show_error)
    monkeypatch.setattr("tkinter.messagebox.showwarning", show_error)
    monkeypatch.setattr(
        window_module.filedialog, "askdirectory", lambda **kwargs: state.folders.pop(0)
    )
    monkeypatch.setattr(window_module, "NewDataviewDialog", FakeNewDataviewDialog)
    return state


def _exists(widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except tk.TclError:
        return False


@pytest.fixture()
def editor(tk_root, monkeypatch, tmp_path):
    """Build a Dataview Editor on a store; closes whatever is left open."""
    monkeypatch.setattr(DataviewEditorWindow, "_show_dataview_editor_popup", lambda self: None)
    monkeypatch.setattr(DataviewEditorWindow, "_toggle_nav", lambda self: None)
    built: list[DataviewEditorWindow] = []

    def make(store: AddressStore | None = None) -> DataviewEditorWindow:
        session = DataSession(store or _store())
        session.dataview = SharedDataviewData(session.store, dataview_folder=tmp_path / "DataView")
        window = DataviewEditorWindow(tk_root, session)
        window.withdraw()
        built.append(window)
        return window

    yield make
    for window in built:
        if _exists(window):
            window.close_without_prompt()


def _copy(tmp_path: Path, name: str = "DataView1.cdv") -> Path:
    folder = tmp_path / "DataView"
    folder.mkdir(exist_ok=True)
    target = folder / name
    shutil.copy(FIXTURES / name, target)
    return target


def _click_writes(path: Path, seconds: float = 10) -> bytes:
    """Rewrite path as CLICK does while connected, its mtime moved by seconds; return its bytes.

    A negative shift is an older copy put back, such as a restored backup.
    """
    mtime = os.path.getmtime(path) + seconds
    shutil.copy(FIXTURES / "DataView1WithNewValues.cdv", path)
    os.utime(path, (mtime, mtime))
    return path.read_bytes()


def _addresses(panel: DataviewPanel, count: int = 4) -> list[str]:
    return [row.address for row in panel.rows[:count]]


def _sheet_addresses(panel: DataviewPanel, count: int = 4) -> list[str]:
    return [panel.sheet.get_cell_data(i, COL_ADDRESS) for i in range(count)]


def _press(widget, sequence: str) -> None:
    """Run what widget has bound to a key sequence, as pressing the keys would."""
    script = widget.bind(sequence)
    assert script, f"nothing bound to {sequence}"
    command = re.search(r"\[(\S+)", script).group(1)
    # One value per field of tkinter's event substitution (Misc._subst_format)
    fields = ["0", "??", "0", "??", "??", "4", "0", "??", "0", "0"]
    fields += ["", "0", "z", "0", str(widget), "2", "0", "0", "0"]
    widget.tk.call(command, *fields)


def _drag_row(panel: DataviewPanel, row: int, move_to: int) -> None:
    """Drag a row by its index, as tksheet's RowIndex.b1_release does it."""
    table = panel.sheet.MT
    event_data = table.new_event_dict("move_rows", state=True)
    event_data["value"] = move_to
    data_new, displayed_new, event_data = table.move_rows_adjust_options_dict(
        *table.get_args_for_move_rows(move_to=move_to, to_move=[row]),
        move_data=True,
        move_heights=True,
        event_data=event_data,
    )
    event_data["moved"]["rows"] = {"data": data_new, "displayed": displayed_new}
    if table.undo_enabled:
        table.undo_stack.append(stored_event_dict(event_data))
    table.RI.ri_extra_end_drag_drop_func(event_data)
    table.sheet_modified(event_data)


# -- Closing never drops an unsaved dataview ---------------------------------


def test_a_second_new_dataview_keeps_the_first_one_unsaved(editor, dialogs, tmp_path):
    window = editor()
    dialogs.new_names.extend(["First", "Second"])
    window._new_dataview()
    window._get_current_panel().add_address("DS1")
    window._new_dataview()

    assert window.has_unsaved_changes()

    folder = tmp_path / "saved"
    folder.mkdir()
    dialogs.yes_no_cancel.append(True)
    dialogs.folders.append(str(folder))
    window._on_close()

    assert not _exists(window)
    assert [row.address for row in DataViewFile.load(folder / "First.cdv").rows[:1]] == ["DS1"]
    assert not (folder / "Second.cdv").exists(), "an unchanged dataview is not saved"


def test_cancelling_save_as_for_an_untitled_dataview_keeps_the_window_open(editor, dialogs):
    window = editor()
    dialogs.new_names.append("First")
    window._new_dataview()
    panel = window._get_current_panel()
    panel.add_address("DS1")

    dialogs.yes_no_cancel.append(True)
    dialogs.folders.append("")
    window._on_close()

    assert _exists(window)
    assert panel.is_dirty
    assert window._iter_open_panels() == [panel]


def test_closing_the_data_session_saves_untitled_dataviews_or_closes_nothing(
    editor, dialogs, tmp_path
):
    window = editor()
    dialogs.new_names.append("First")
    window._new_dataview()
    window._get_current_panel().add_address("DS1")

    dialogs.yes_no_cancel.append(True)
    dialogs.folders.append("")
    assert not window._session.close(prompt_save=True)
    assert _exists(window)

    dialogs.yes_no_cancel.append(True)
    dialogs.folders.append(str(tmp_path))
    assert window._session.close(prompt_save=True)
    assert not _exists(window)
    assert (tmp_path / "First.cdv").exists()


def test_a_failed_save_closes_neither_the_tab_nor_the_window(editor, dialogs, tmp_path):
    window = editor()
    path = _copy(tmp_path)
    window._open_dataview(path)
    panel = window._get_current_panel()
    panel.add_address("DS1")
    shutil.rmtree(path.parent)  # e.g. CLICK closed and removed its temp folder

    dialogs.yes_no_cancel.append(True)
    assert window._on_tab_close_request(0) is False
    assert len(dialogs.errors) == 1 and "DataView1" in dialogs.errors[0]

    dialogs.yes_no_cancel.append(True)
    window._on_close()
    assert _exists(window)
    assert len(dialogs.errors) == 2
    assert panel.is_dirty
    assert window._iter_open_panels() == [panel]


def test_save_as_onto_a_file_open_in_another_tab_is_refused(editor, dialogs, tmp_path):
    window = editor()
    path = _copy(tmp_path)
    original = path.read_bytes()
    window._open_dataview(path)
    opened = window._get_current_panel()
    dialogs.new_names.append("DataView1")
    window._new_dataview()
    untitled = window._get_current_panel()
    untitled.add_address("DS1")

    dialogs.folders.append(str(path.parent))
    dialogs.yes_no.append(True)  # would overwrite, if asked
    window._save_current()

    assert len(dialogs.errors) == 1 and "open in another tab" in dialogs.errors[0]
    assert path.read_bytes() == original
    assert untitled.file_path is None and untitled.is_dirty
    assert window._panel_for_path(path) is opened
    assert window._iter_open_panels() == [opened, untitled]


# -- A .cdv that could not be read is never saved over -----------------------


def test_an_unreadable_dataview_opens_no_tab(editor, dialogs, tmp_path):
    window = editor()
    path = tmp_path / "Broken.cdv"
    path.write_bytes("".encode("utf-16"))

    window._open_dataview(path)

    assert window._iter_open_panels() == []
    assert len(dialogs.errors) == 1 and "Broken.cdv" in dialogs.errors[0]
    assert path.read_bytes() == "".encode("utf-16")


def test_a_panel_never_saves_over_a_file_it_could_not_read(tk_root, dialogs, tmp_path):
    path = tmp_path / "Broken.cdv"
    broken = "".encode("utf-16")
    path.write_bytes(broken)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        panel.add_address("DS1")

        assert panel.save() is False
        assert path.read_bytes() == broken
        assert len(dialogs.errors) == 1 and "Broken.cdv" in dialogs.errors[0]

        shutil.copy(FIXTURES / "DataView1.cdv", path)  # CLICK writes it again
        panel._reload_file()
        assert panel.load_error is None
        assert panel.save() is True
    finally:
        panel.destroy()


def test_a_failed_save_as_keeps_the_old_path(tk_root, dialogs, tmp_path):
    panel = DataviewPanel(tk_root, address_normalizer=normalize_address, name="New")
    try:
        panel.add_address("DS1")
        assert panel.save_as(tmp_path / "missing" / "New.cdv") is False
        assert panel.file_path is None
        assert panel.is_dirty
    finally:
        panel.destroy()


# -- A save never goes over a newer CLICK write without asking ---------------


@pytest.mark.parametrize("seconds", [10, -100], ids=["newer", "older copy"])
@pytest.mark.parametrize(("answer", "saved"), [(None, False), (True, True), (False, False)])
def test_saving_over_a_change_click_made_between_checks_asks_first(
    tk_root, dialogs, tmp_path, answer, saved, seconds
):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        panel.add_address("DS1")
        clicks = _click_writes(path, seconds)  # inside the 2 s between file checks

        dialogs.yes_no_cancel.append(answer)
        assert panel.save() is saved

        assert len(dialogs.shown) == 1 and "changed by another program" in dialogs.shown[0]
        on_disk = [row.address for row in DataViewFile.load(path).rows if not row.is_empty]
        if answer is True:  # Overwrite
            assert "DS1" in on_disk
            assert not panel.is_dirty
        else:
            assert path.read_bytes() == clicks
        if answer is False:  # Reload: CLICK's rows, the edit dropped
            assert [row.address for row in panel.rows if not row.is_empty] == on_disk
            assert panel.rows[0].new_value is True
            assert not panel.is_dirty
        if answer is None:  # Cancel: the edit stays, unsaved
            assert panel.is_dirty
    finally:
        panel.destroy()


def test_saving_after_declining_a_reload_asks_first(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        panel.add_address("DS1")
        clicks = _click_writes(path)

        dialogs.yes_no.append(False)  # don't reload
        panel._check_file_modified()
        assert "drops this dataview's unsaved edits" in dialogs.shown[0]

        dialogs.yes_no_cancel.append(None)
        assert panel.save() is False
        assert len(dialogs.shown) == 2 and "changed by another program" in dialogs.shown[1]
        assert path.read_bytes() == clicks
    finally:
        panel.destroy()


def test_an_older_copy_put_back_is_offered_for_reload(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        _click_writes(path, -100)

        dialogs.yes_no.append(True)
        panel._check_file_modified()

        assert len(dialogs.shown) == 1 and "modified by another program" in dialogs.shown[0]
        assert panel.rows[0].new_value is True, "the restored file is loaded"
        panel._check_file_modified()
        assert len(dialogs.shown) == 1, "asked once"
    finally:
        panel.destroy()


# -- Inserts store CLICK's address form --------------------------------------


@pytest.mark.parametrize("normalizer", [normalize_address, None])
def test_add_address_stores_clicks_form_and_refuses_anything_else(tk_root, tmp_path, normalizer):
    panel = DataviewPanel(tk_root, address_normalizer=normalizer, name="Added")
    try:
        added = {text: panel.add_address(text) for text in ("x1", "xd0u", "XD0U", "Pump", "1.5")}
        assert added == {"x1": True, "xd0u": True, "XD0U": True, "Pump": False, "1.5": False}

        assert panel.save_as(tmp_path / "Added.cdv")
        saved = DataViewFile.load(tmp_path / "Added.cdv")
        assert [row.address for row in saved.rows if not row.is_empty] == ["X001", "XD0u", "XD0u"]
    finally:
        panel.destroy()


def test_nickname_box_matches_nicknames_without_case_and_refuses_other_text(editor, dialogs):
    window = editor(_store({("X", 1): "Pump_Run", ("X", 2): "Pump_Stop", ("DS", 5): "Speed"}))
    dialogs.new_names.append("Inserts")
    window._new_dataview()
    panel = window._get_current_panel()

    for text in ("pump_run", "SPEED", "x3"):
        window.nickname_combo.set(text)
        window._on_nickname_selected(text)
        assert window.nickname_combo.get() == "", "an insert clears the box"
    assert dialogs.errors == []

    window.nickname_combo.set("Pump")
    window._on_nickname_selected("Pump")
    assert len(dialogs.errors) == 1 and "'Pump'" in dialogs.errors[0]
    assert window.nickname_combo.get() == "Pump", "refused text stays to be corrected"

    assert [row.address for row in panel.rows if not row.is_empty] == ["X001", "DS5", "X003"]


def test_tag_browser_insert_stores_clicks_form(editor, dialogs):
    window = editor()
    dialogs.new_names.append("Inserts")
    window._new_dataview()

    window._insert_addresses([("XD", 1), ("X", 1)])

    rows = window._get_current_panel().rows
    assert [row.address for row in rows if not row.is_empty] == ["XD0u", "X001"]


def test_a_tag_browser_block_insert_is_one_undo_step(editor, dialogs):
    window = editor()
    dialogs.new_names.append("Block")
    window._new_dataview()
    panel = window._get_current_panel()

    window._insert_addresses([("DS", n) for n in range(1, 61)])  # more than 50 undo levels
    assert sum(not row.is_empty for row in panel.rows) == 60

    assert panel.undo()
    assert all(row.is_empty for row in panel.rows)
    assert not panel.is_dirty
    assert not panel.undo()


# -- Undo keeps the sheet and the rows together ------------------------------


def test_ctrl_z_after_a_row_drag_puts_rows_and_sheet_back_together(tk_root, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        start = ["X001", "X002", "X003", "X816"]
        _drag_row(panel, 0, 3)
        dragged = _addresses(panel)
        assert dragged == _sheet_addresses(panel) != start

        _press(panel.sheet.MT, "<Control-z>")
        assert _addresses(panel) == _sheet_addresses(panel) == start
        assert not panel.is_dirty, "back to what the file holds"

        _press(panel.sheet.MT, "<Control-y>")
        assert _addresses(panel) == _sheet_addresses(panel) == dragged

        assert panel.save()
        assert [row.address for row in DataViewFile.load(path).rows[:4]] == dragged
    finally:
        panel.destroy()


def test_ctrl_z_of_an_address_edit_keeps_the_new_value(tk_root, tmp_path):
    path = _copy(tmp_path, "DataView1WithNewValues.cdv")
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        assert (panel.rows[0].address, panel.rows[0].new_value) == ("X001", True)

        panel.sheet.span((0, COL_ADDRESS), undo=True, emit_event=True).data = "X005"
        tk_root.update()
        assert (panel.rows[0].address, panel.rows[0].new_value) == ("X005", None)

        _press(panel.sheet.MT, "<Control-z>")
        assert (panel.rows[0].address, panel.rows[0].new_value) == ("X001", True)
        assert panel.sheet.get_cell_data(0, COL_ADDRESS) == "X001"
        assert not panel.is_dirty
    finally:
        panel.destroy()


def test_clear_selected_rows_is_one_undo_step(tk_root, tmp_path):
    panel = DataviewPanel(tk_root, file_path=_copy(tmp_path), address_normalizer=normalize_address)
    try:
        panel.clear_rows([0, 1])
        assert _addresses(panel, 3) == ["", "", "X003"]

        assert panel.undo()
        assert _addresses(panel, 3) == _sheet_addresses(panel, 3) == ["X001", "X002", "X003"]
        assert not panel.undo()
    finally:
        panel.destroy()
