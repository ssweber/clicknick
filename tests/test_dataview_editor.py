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
from clicknick.views.dataview_editor.panel import COL_ADDRESS, COL_NEW_VALUE, DataviewPanel
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
        session.dataview = SharedDataviewData(
            session.store, get_folder=lambda: tmp_path / "DataView"
        )
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


def test_a_save_that_fails_in_a_live_folder_keeps_the_tab_and_window(editor, dialogs, tmp_path):
    import stat

    window = editor()
    path = _copy(tmp_path)
    window._open_dataview(path)
    panel = window._get_current_panel()
    panel.add_address("DS1")
    path.chmod(stat.S_IREAD)  # the folder is there; the file cannot be written
    try:
        dialogs.yes_no_cancel.append(True)
        assert window._on_tab_close_request(0) is False
        assert len(dialogs.errors) == 1 and "DataView1" in dialogs.errors[0]
        assert window._iter_open_panels() == [panel]

        dialogs.yes_no_cancel.append(True)
        window._on_close()
        assert _exists(window)
        assert len(dialogs.errors) == 2
        assert panel.is_dirty
    finally:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)


def test_a_failed_save_closes_neither_the_tab_nor_the_window(editor, dialogs, tmp_path):
    window = editor()
    path = _copy(tmp_path)
    window._open_dataview(path)
    panel = window._get_current_panel()
    panel.add_address("DS1")
    shutil.rmtree(path.parent)  # e.g. CLICK closed and removed its temp folder

    # The Save As that replaces the dead folder cannot write there either
    blocked = tmp_path / "blocked"
    (blocked / "DataView1.cdv").mkdir(parents=True)
    dialogs.folders.extend([str(blocked), str(blocked)])
    dialogs.yes_no.extend([True, True])  # overwrite?
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
        if answer is False:  # Reload: CLICK's rows; Ctrl+Z brings the edit back
            assert [row.address for row in panel.rows if not row.is_empty] == on_disk
            assert panel.rows[0].new_value is True
            assert not panel.is_dirty
            assert panel.undo()
            assert "DS1" in [row.address for row in panel.rows]
            assert panel.is_dirty
        if answer is None:  # Cancel: the edit stays, unsaved
            assert panel.is_dirty
            panel._check_file_modified()
            assert len(dialogs.shown) == 1, "the monitor does not ask about the same change"
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
        assert "Ctrl+Z brings them back" in dialogs.shown[0]

        dialogs.yes_no_cancel.append(None)
        assert panel.save() is False
        assert len(dialogs.shown) == 2 and "changed by another program" in dialogs.shown[1]
        assert path.read_bytes() == clicks
    finally:
        panel.destroy()


def test_a_reload_over_unsaved_edits_can_be_undone(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    changed: list[DataviewPanel] = []
    panel = DataviewPanel(
        tk_root,
        file_path=path,
        address_normalizer=normalize_address,
        on_addresses_changed=changed.append,
    )
    try:
        panel.add_address("DS1")
        _click_writes(path)
        changed.clear()

        dialogs.yes_no.append(True)
        panel._check_file_modified()
        assert "Ctrl+Z brings them back" in dialogs.shown[0]
        assert panel.rows[0].new_value is True and not panel.is_dirty
        assert changed == [panel], "the poll list follows the reloaded rows"

        assert panel.undo()
        assert "DS1" in [row.address for row in panel.rows]
        assert panel.is_dirty
    finally:
        panel.destroy()


def test_export_onto_a_file_open_in_another_tab_is_refused(editor, dialogs, tmp_path):
    window = editor()
    path = _copy(tmp_path)
    original = path.read_bytes()
    window._open_dataview(path)
    dialogs.new_names.append("DataView1")
    window._new_dataview()
    window._get_current_panel().add_address("DS1")

    dialogs.folders.append(str(path.parent))
    dialogs.yes_no.append(True)  # would overwrite, if asked
    window._export()

    assert len(dialogs.errors) == 1 and "open in another tab" in dialogs.errors[0]
    assert path.read_bytes() == original


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


def test_saving_rows_undone_past_a_reload_asks_first(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    before_click = DataViewFile.load(path).rows[0].new_value
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        clicks = _click_writes(path)
        dialogs.yes_no.append(True)  # reload
        panel._check_file_modified()
        panel.add_address("DS4321")

        assert panel.undo() and panel.undo()  # the edit, then the reload
        assert panel.rows[0].new_value == before_click and panel.is_dirty

        dialogs.yes_no_cancel.append(None)
        assert panel.save() is False
        assert len(dialogs.shown) == 2 and "changed by another program" in dialogs.shown[1]
        assert path.read_bytes() == clicks
    finally:
        panel.destroy()


def test_saving_after_undoing_a_reload_from_the_save_prompt_asks_first(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        panel.add_address("DS4321")
        clicks = _click_writes(path)
        dialogs.yes_no_cancel.append(False)  # No: reload
        assert panel.save() is False
        _press(panel.sheet.MT, "<Control-z>")
        assert "DS4321" in [row.address for row in panel.rows]

        dialogs.yes_no_cancel.append(None)
        assert panel.save() is False
        assert len(dialogs.shown) == 2 and "changed by another program" in dialogs.shown[1]
        assert path.read_bytes() == clicks

        dialogs.yes_no_cancel.append(True)  # Yes: save over it
        assert panel.save() is True
        assert "DS4321" in [row.address for row in DataViewFile.load(path).rows]
    finally:
        panel.destroy()


def test_saving_rows_undone_past_an_own_save_does_not_ask(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        panel.add_address("DS4321")
        assert panel.save()
        panel.add_address("DS4322")
        assert panel.save()
        assert panel.undo() and panel.undo()

        assert panel.save() is True
        assert dialogs.shown == []
        assert "DS4321" not in [row.address for row in DataViewFile.load(path).rows]
        assert panel.redo() and panel.save() is True
        assert dialogs.shown == []
    finally:
        panel.destroy()


def test_saving_rows_undone_past_a_reload_and_an_own_save_asks_first(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        _click_writes(path)
        dialogs.yes_no.append(True)  # reload
        panel._check_file_modified()
        panel.add_address("DS4321")
        assert panel.save()
        saved = path.read_bytes()  # CLICK's change and the edit

        assert panel.undo() and panel.undo()  # the edit, then the reload
        dialogs.yes_no_cancel.append(None)
        assert panel.save() is False
        assert len(dialogs.shown) == 2 and "changed by another program" in dialogs.shown[1]
        assert path.read_bytes() == saved
    finally:
        panel.destroy()


def test_a_reload_of_the_same_rows_does_not_make_older_steps_ask(tk_root, dialogs, tmp_path):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    try:
        panel.add_address("DS4321")
        assert panel.save()
        mtime = os.path.getmtime(path) + 10
        path.write_bytes(path.read_bytes())  # CLICK writes the same rows again
        os.utime(path, (mtime, mtime))
        dialogs.yes_no.append(True)  # reload
        panel._check_file_modified()

        assert panel.undo()
        assert panel.save() is True
        assert len(dialogs.shown) == 1, "only the reload prompt"
        assert "DS4321" not in [row.address for row in DataViewFile.load(path).rows]
    finally:
        panel.destroy()


@pytest.mark.parametrize("reload", [True, False], ids=["reload", "don't reload"])
def test_after_a_file_prompt_the_sheet_has_the_focus(tk_root, dialogs, tmp_path, reload):
    path = _copy(tmp_path)
    panel = DataviewPanel(tk_root, file_path=path, address_normalizer=normalize_address)
    focused: list[str] = []
    panel.sheet.focus_set = lambda canvas="table": focused.append(canvas)
    try:
        panel.add_address("DS1")
        _click_writes(path)
        dialogs.yes_no.append(reload)
        panel._check_file_modified()
        assert focused == ["table"]

        _click_writes(path)
        dialogs.yes_no_cancel.append(None)
        panel.save()
        assert focused == ["table", "table"]
    finally:
        panel.destroy()


def test_a_background_tab_reloaded_from_the_prompt_drops_its_unsaved_marker(
    editor, dialogs, tmp_path
):
    window = editor()
    path = _copy(tmp_path)
    window._open_dataview(path)
    background = window._get_current_panel()
    background.add_address("DS1")
    dialogs.new_names.append("Other")
    window._new_dataview()
    assert window.notebook.tab(0, "text") == "*DataView1"

    _click_writes(path)
    dialogs.yes_no.append(True)
    background._check_file_modified()

    assert not background.is_dirty
    assert window.notebook.tab(0, "text") == "DataView1"


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


# -- Text typed in a cell is an edit -----------------------------------------


def _cell_editor_window(*, commits_without_focus: bool) -> tuple[DataviewEditorWindow, list]:
    """A window with one tab whose cell editor is open; committing closes it.

    tksheet commits nothing while the application has no focus, so the first
    try may leave it open.
    """
    tries: list[int] = []
    text_editor = SimpleNamespace(open=True)

    def click_outside() -> None:
        tries.append(1)
        if commits_without_focus or len(tries) > 1:
            text_editor.open = False

    mt = SimpleNamespace(
        text_editor=text_editor, mouseclick_outside_editor_or_dropdown_all_canvases=click_outside
    )
    window = DataviewEditorWindow.__new__(DataviewEditorWindow)
    window._iter_open_panels = lambda: [
        SimpleNamespace(sheet=SimpleNamespace(MT=mt), reopen_rejected_edit=lambda: False)
    ]
    window.focus_force = lambda: None
    return window, tries


@pytest.mark.parametrize("commits_without_focus", [True, False], ids=["focused", "no-focus"])
def test_text_typed_in_a_cell_is_committed(commits_without_focus):
    """The app asks this before a project change, so the text is asked about, not dropped."""
    window, tries = _cell_editor_window(commits_without_focus=commits_without_focus)

    assert window.commit_open_cell_editor()

    assert len(tries) == (1 if commits_without_focus else 2)


def test_a_cell_that_will_not_commit_is_reported(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        window_module.messagebox, "showwarning", lambda *args, **_kw: warnings.append(args[0])
    )
    window, _tries = _cell_editor_window(commits_without_focus=False)
    window._iter_open_panels()[0].sheet.MT.mouseclick_outside_editor_or_dropdown_all_canvases = (
        lambda: None
    )

    assert not window.commit_open_cell_editor()
    assert warnings == ["Cell Being Edited"]


def _typed(
    editor,
    tk_root,
    tmp_path,
    monkeypatch,
    *,
    focused: bool = True,
    row: int = 5,
    column: int = COL_ADDRESS,
    text: str = "x1",
) -> tuple[DataviewEditorWindow, DataviewPanel, Path]:
    """An editor on DataView1.cdv with *text* typed into a cell, not committed.

    tksheet commits nothing while the focus is outside ClickNick, so text typed
    before switching to CLICK is still in the editor. Where the focus is is
    stubbed: *focused* puts it in the cell editor, otherwise outside ClickNick.
    The window stays hidden and never takes the focus.
    """
    path = _copy(tmp_path)
    window = editor()
    monkeypatch.setattr(window, "focus_force", lambda: None)
    window._open_dataview(path)
    tk_root.update()
    (panel,) = window._iter_open_panels()
    panel.set_modbus_columns_visible(True)  # New Value is a Modbus column
    tk_root.update()
    panel.sheet.select_cell(row, column)
    panel.sheet.open_cell()
    tk_root.update()
    panel.sheet.set_text_editor_value(text)
    table = panel.sheet.MT
    monkeypatch.setattr(table, "focus_get", lambda: table.text_editor.tktext if focused else None)
    assert table.text_editor.open
    assert not window.has_unsaved_changes()
    return window, panel, path


_FINISH = "Finish the cell edit first (Enter to keep it, Esc to cancel)."


def test_a_new_value_that_does_not_validate_is_said_and_kept_open(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, _path = _typed(
        editor, tk_root, tmp_path, monkeypatch, row=0, column=COL_NEW_VALUE, text="abc"
    )
    before = panel.rows[0].new_value

    mt = panel.sheet.MT
    mt.close_text_editor(SimpleNamespace(keysym="Return"))
    tk_root.update()

    assert dialogs.errors == ["X001: Must be 0 or 1"]
    assert mt.text_editor.open
    assert mt.text_editor.get() == "abc"
    assert panel.rows[0].new_value == before


def test_write_stops_on_a_new_value_that_does_not_validate(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, _path = _typed(
        editor, tk_root, tmp_path, monkeypatch, row=0, column=COL_NEW_VALUE, text="abc"
    )
    sent = []
    monkeypatch.setattr(window, "_write_payload", sent.append)

    window._write_all()

    assert sent == []
    assert dialogs.errors == ["X001: Must be 0 or 1"]


def test_open_and_save_as_start_in_a_folder_that_exists(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window = editor()
    window.shared_data._get_folder = lambda: tmp_path / "gone" / "DataView"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Documents").mkdir()

    assert window._dialog_folder() == tmp_path / "Documents"

    last = tmp_path / "last"
    last.mkdir()
    window._last_folder = last
    assert window._dialog_folder() == last

    shown = tmp_path / "shown"
    shown.mkdir()
    window.shared_data._get_folder = lambda: shown
    assert window._dialog_folder() == shown


def test_write_stops_when_a_refusal_has_not_reopened_its_cell_yet(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, _path = _typed(
        editor, tk_root, tmp_path, monkeypatch, row=0, column=COL_NEW_VALUE, text="abc"
    )
    panel.sheet.MT.close_text_editor(SimpleNamespace(keysym="FocusOut"))
    assert not panel.sheet.MT.text_editor.open  # the reopen is still queued
    sent = []
    monkeypatch.setattr(window, "_write_payload", sent.append)

    window._write_all()

    assert sent == []
    assert dialogs.errors == ["X001: Must be 0 or 1"]


def test_save_of_a_tab_in_a_deleted_folder_asks_where_to_save(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    path = _copy(tmp_path)
    window = editor()
    window._open_dataview(path)
    tk_root.update()
    (panel,) = window._iter_open_panels()
    shutil.rmtree(path.parent)  # CLICK deleted its temp folder
    target = tmp_path / "elsewhere"
    target.mkdir()
    dialogs.folders.append(str(target))

    window._save_current()

    assert not path.parent.exists()
    assert panel.file_path == target / f"{panel.name}.cdv"
    assert panel.file_path.exists()


def test_text_typed_in_a_real_cell_is_committed(editor, dialogs, tk_root, tmp_path, monkeypatch):
    window, panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch)

    assert window.commit_open_cell_editor()

    assert not panel.sheet.MT.text_editor.open
    assert panel.rows[5].address == "X001"
    assert window.has_unsaved_changes()
    assert dialogs.errors == []


def test_closing_the_window_asks_about_text_still_in_a_cell(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch)
    dialogs.yes_no_cancel.append(None)  # Cancel

    window._on_close()

    assert dialogs.shown == ["You have unsaved changes. Save before closing?"]
    assert _exists(window)
    assert panel.rows[5].address == "X001"


def test_closing_a_tab_asks_about_text_still_in_its_cell(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch)
    dialogs.yes_no_cancel.append(None)  # Cancel

    window._close_current_tab()

    assert dialogs.shown == ["'DataView1' has unsaved changes. Save before closing?"]
    assert window._iter_open_panels() == [panel]


def test_save_writes_text_still_in_a_cell(editor, dialogs, tk_root, tmp_path, monkeypatch):
    window, panel, path = _typed(editor, tk_root, tmp_path, monkeypatch)

    window._save_current()

    assert DataViewFile.load(path).rows[5].address == "X001"
    assert not panel.is_dirty


def test_save_all_writes_text_still_in_a_cell(editor, dialogs, tk_root, tmp_path, monkeypatch):
    window, panel, path = _typed(editor, tk_root, tmp_path, monkeypatch)

    assert window.save_all()

    assert DataViewFile.load(path).rows[5].address == "X001"
    assert not panel.is_dirty


def test_export_writes_text_still_in_a_cell(editor, dialogs, tk_root, tmp_path, monkeypatch):
    window, _panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch)
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    dialogs.folders.append(str(export_dir))

    window._export()

    assert DataViewFile.load(export_dir / "DataView1.cdv").rows[5].address == "X001"


def test_write_all_writes_the_value_still_in_a_cell(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    """Clicking Write All leaves the focus in the cell editor: the typed value is written."""
    from clicknick.views.dataview_editor.panel import COL_NEW_VALUE

    window, _panel, _path = _typed(
        editor, tk_root, tmp_path, monkeypatch, row=28, column=COL_NEW_VALUE, text="100"
    )
    written = []
    monkeypatch.setattr(window, "_write_payload", written.append)

    window._write_all()

    assert written == [[("DS1", 100)]]


def test_closing_the_data_asks_about_text_still_in_a_dataview_cell(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, _panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch)
    dialogs.yes_no_cancel.append(None)  # Cancel

    assert not window._session.close(prompt_save=True)

    assert dialogs.shown == ["You have unsaved changes in Dataview Editor. Save before closing?"]
    assert _exists(window)


# -- A cell that will not commit stops the action ---------------------------


def test_save_writes_nothing_while_a_cell_will_not_commit(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, path = _typed(editor, tk_root, tmp_path, monkeypatch, focused=False)
    before = path.read_bytes()

    window._save_current()

    assert dialogs.errors == [_FINISH]
    assert path.read_bytes() == before
    assert panel.sheet.MT.text_editor.open


def test_export_writes_nothing_while_a_cell_will_not_commit(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, _panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch, focused=False)
    dialogs.folders.append(str(tmp_path))

    window._export()

    assert dialogs.errors == [_FINISH]
    assert dialogs.folders == [str(tmp_path)], "no folder was asked for"


def test_a_tab_stays_open_while_its_cell_will_not_commit(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    window, panel, _path = _typed(editor, tk_root, tmp_path, monkeypatch, focused=False)

    window._close_current_tab()

    assert dialogs.errors == [_FINISH]
    assert dialogs.shown == []
    assert window._iter_open_panels() == [panel]


def test_write_all_writes_nothing_while_a_cell_will_not_commit(
    editor, dialogs, tk_root, tmp_path, monkeypatch
):
    from clicknick.views.dataview_editor.panel import COL_NEW_VALUE

    window, _panel, _path = _typed(
        editor,
        tk_root,
        tmp_path,
        monkeypatch,
        focused=False,
        row=28,
        column=COL_NEW_VALUE,
        text="100",
    )
    written = []
    monkeypatch.setattr(window, "_write_payload", written.append)

    window._write_all()
    window._write_checked()

    assert written == []
    assert dialogs.errors == [_FINISH, _FINISH]


def _pasted_new_values(editor, dialogs, tk_root, addresses, texts):
    """A panel with *addresses* in its first rows, *texts* pasted down the New Value column."""
    window = editor()
    dialogs.new_names.append("Pasted")
    window._new_dataview()
    panel = window._get_current_panel()
    for address in addresses:
        panel.add_address(address)
    panel.set_modbus_columns_visible(True)
    tk_root.update()
    panel.sheet.select_cell(0, COL_NEW_VALUE)
    tk_root.clipboard_clear()
    tk_root.clipboard_append("\n".join(texts))
    tk_root.update()
    panel.sheet.MT.ctrl_v()
    tk_root.update()
    return panel


def test_a_paste_applies_the_valid_cells_and_lists_the_rest_in_one_warning(
    editor, dialogs, tk_root
):
    panel = _pasted_new_values(editor, dialogs, tk_root, ["DS1", "DS2", "DS3"], ["abc", "7", "xyz"])

    assert [row.new_value for row in panel.rows[:3]] == [None, 7, None]
    assert len(dialogs.errors) == 1
    lines = dialogs.errors[0].splitlines()
    assert [line.split(":")[0] for line in lines] == ["DS1", "DS3"]
    assert panel.undo()
    assert [row.new_value for row in panel.rows[:3]] == [None, None, None]


def test_a_paste_lists_the_first_ten_rejected_cells_and_counts_the_rest(editor, dialogs, tk_root):
    addresses = [f"DS{n}" for n in range(1, 13)]
    _pasted_new_values(editor, dialogs, tk_root, addresses, ["abc"] * 12)

    assert len(dialogs.errors) == 1
    lines = dialogs.errors[0].splitlines()
    assert len(lines) == 11
    assert lines[-1] == "and 2 more"


def test_a_paste_of_valid_values_shows_no_warning(editor, dialogs, tk_root):
    panel = _pasted_new_values(editor, dialogs, tk_root, ["DS1", "DS2"], ["5", "6"])

    assert [row.new_value for row in panel.rows[:2]] == [5, 6]
    assert dialogs.errors == []


def test_a_fill_of_an_invalid_value_is_said(editor, dialogs, tk_root):
    """Filling one value down a selection pastes it into every selected cell."""
    window = editor()
    dialogs.new_names.append("Filled")
    window._new_dataview()
    panel = window._get_current_panel()
    for address in ("DS1", "DS2", "DS3"):
        panel.add_address(address)
    panel.set_modbus_columns_visible(True)
    tk_root.update()
    panel.sheet.select_cell(0, COL_NEW_VALUE)
    panel.sheet.MT.create_selection_box(0, COL_NEW_VALUE, 3, COL_NEW_VALUE + 1, "cells")
    tk_root.clipboard_clear()
    tk_root.clipboard_append("abc")
    tk_root.update()
    panel.sheet.MT.ctrl_v()
    tk_root.update()

    assert [row.new_value for row in panel.rows[:3]] == [None, None, None]
    assert [line.split(":")[0] for line in dialogs.errors[0].splitlines()] == ["DS1", "DS2", "DS3"]


def _panel_with(editor, dialogs, tk_root, addresses):
    window = editor()
    dialogs.new_names.append("Pasted")
    window._new_dataview()
    panel = window._get_current_panel()
    for address in addresses:
        panel.add_address(address)
    tk_root.update()
    return panel


def _paste(panel, tk_root, row, column, text, *, idle=True):
    panel.sheet.select_cell(row, column)
    tk_root.clipboard_clear()
    tk_root.clipboard_append(text)
    panel.sheet.MT.ctrl_v()
    if idle:
        tk_root.update()


def test_two_pastes_give_two_warnings(editor, dialogs, tk_root):
    panel = _panel_with(editor, dialogs, tk_root, ["DS1", "DS2"])
    panel.set_modbus_columns_visible(True)
    tk_root.update()

    _paste(panel, tk_root, 0, COL_NEW_VALUE, "abc", idle=False)  # no idle between the two
    _paste(panel, tk_root, 1, COL_NEW_VALUE, "xyz")

    assert [message.split(":")[0] for message in dialogs.errors] == ["DS1", "DS2"]


def test_a_paste_into_the_force_column_is_not_checked_as_a_new_value(editor, dialogs, tk_root):
    """With the Modbus columns hidden, the displayed column 3 is Force."""
    panel = _panel_with(editor, dialogs, tk_root, ["DS1"])
    panel.set_modbus_columns_visible(False)
    panel.set_force_column_visible(True)
    tk_root.update()

    _paste(panel, tk_root, 0, 3, "abc")

    assert dialogs.errors == []
    assert panel.rows[0].new_value is None


def test_clearing_a_new_value_is_never_refused(editor, dialogs, tk_root):
    panel = _panel_with(editor, dialogs, tk_root, ["DS1", "DS2"])
    panel.set_modbus_columns_visible(True)
    tk_root.update()
    _paste(panel, tk_root, 0, COL_NEW_VALUE, "5\n6")
    assert [row.new_value for row in panel.rows[:2]] == [5, 6]

    panel.sheet.MT.create_selection_box(0, COL_NEW_VALUE, 2, COL_NEW_VALUE + 1, "cells")
    panel.sheet.MT.delete_key()
    tk_root.update()

    assert [row.new_value for row in panel.rows[:2]] == [None, None]
    assert dialogs.errors == []


def test_a_destroyed_panel_has_no_idle_warning_left(editor, dialogs, tk_root):
    panel = _panel_with(editor, dialogs, tk_root, ["DS1"])
    panel.set_modbus_columns_visible(True)
    tk_root.update()
    panel.sheet.select_cell(0, COL_NEW_VALUE)
    tk_root.clipboard_clear()
    tk_root.clipboard_append("abc")
    panel.sheet.MT.ctrl_v()  # the warning is queued for idle
    assert panel._rejected_pastes_after_id is not None

    panel.destroy()
    tk_root.update()

    assert dialogs.errors == []
