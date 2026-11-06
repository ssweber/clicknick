"""Guided Paste follows the program in CLICK while it stays open."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from clicknick.connection_session import SavedProgram
from clicknick.ladder.program import FolderComparison
from clicknick.views.guided_paste_window import GuidedPasteWindow

MODULE = "clicknick.views.guided_paste_window"
NAMES = ["subroutines/a.csv", "subroutines/b.csv", "main.csv"]


def _window(
    monkeypatch,
    program: SavedProgram,
    differs_by_dir: dict[Path, dict[str, bool]],
    missing: frozenset[str] = frozenset(),
):
    """A window without Tk widgets, comparing against canned results per CSV folder."""
    monkeypatch.setattr(
        f"{MODULE}.compare_csv_folder",
        lambda _folder, csv_dir: FolderComparison(
            compared=True, differs=differs_by_dir[csv_dir], missing_in_click=missing
        ),
    )
    window = GuidedPasteWindow.__new__(GuidedPasteWindow)
    window._folder = Path("bundle")
    window._folder_items = [(name, Path(name), 1, "") for name in NAMES]
    window._items = []
    window._done = set()
    window._current_idx = None
    window._copied = False
    window._nickname_path = None
    window._differs = {}
    window._only_in_click = set()
    window._missing_in_click = frozenset()
    window._click_compared = False
    window._adding_subroutine = False
    window._compare_note = ""
    window._sheet = Mock()
    window._progress_lbl = Mock()
    window._compare_lbl = Mock()
    window._action_btn = Mock()
    window._add_sub_btn = Mock()
    window._status_var = Mock()
    window.current = program
    window._get_saved_program = lambda: window.current
    window._compare_with_click()
    window._project_session = window._saved_program.session
    window._populate_sheet()
    window._advance_to_first_pending()
    return window


def _change(window, program: SavedProgram) -> None:
    window.current = program
    window._on_saved_program_changed(program)


def _note(window) -> str:
    return window._compare_lbl.configure.call_args.kwargs["text"]


def test_comparison_appears_once_the_new_project_is_read(monkeypatch) -> None:
    session = object()
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, building=True, note="reading"),
        {csv_dir: {"main.csv": False, "subroutines/a.csv": False, "subroutines/b.csv": True}},
    )
    assert window._differs == {}
    assert window._current_idx == 0
    assert _note(window) == "reading"

    _change(window, SavedProgram(session, generation=1, csv_dir=csv_dir, note=""))

    assert window._matches_click("main.csv")
    assert window._current_idx == NAMES.index("subroutines/b.csv")
    assert _note(window) == "Compared with CLICK's last save"


def test_opening_another_project_recompares_and_forgets_what_was_pasted(monkeypatch) -> None:
    old_dir, new_dir = Path("old/csv"), Path("new/csv")
    old, new = object(), object()
    window = _window(
        monkeypatch,
        SavedProgram(old, generation=1, csv_dir=old_dir, note=""),
        {
            old_dir: dict.fromkeys(NAMES, True),
            new_dir: {"main.csv": False, "subroutines/a.csv": False, "subroutines/b.csv": True},
        },
    )
    window._done.add("main.csv")
    window._copied = True

    # The title changed: the old session is gone before the new one is ready.
    _change(window, SavedProgram())
    assert window._done == {"main.csv"}

    window._copied = False
    _change(window, SavedProgram(new, building=True, note="reading"))
    assert window._done == set()
    assert window._differs == {}
    assert _note(window) == "reading"

    _change(window, SavedProgram(new, generation=1, csv_dir=new_dir, note=""))
    assert window._differs["main.csv"] is False
    assert window._current_idx == NAMES.index("subroutines/b.csv")


def test_click_save_keeps_rows_while_building_and_the_row_being_pasted(monkeypatch) -> None:
    session = object()
    before, after = Path("before/csv"), Path("after/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, generation=1, csv_dir=before, note=""),
        {before: dict.fromkeys(NAMES, True), after: dict.fromkeys(NAMES, False)},
    )
    window._copied = True

    _change(window, SavedProgram(session, generation=2, building=True, note="reading"))
    assert window._differs == dict.fromkeys(NAMES, True)
    assert _note(window) == "reading"

    _change(window, SavedProgram(session, generation=2, csv_dir=after, note=""))
    assert window._differs == dict.fromkeys(NAMES, False)
    assert window._current_idx == 0
    assert window._copied is True


def _add_sub_state(window) -> str:
    return window._add_sub_btn.configure.call_args.kwargs["state"]


def test_new_subroutine_only_for_subroutines_click_lacks(monkeypatch) -> None:
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: {"main.csv": True, "subroutines/a.csv": True, "subroutines/b.csv": True}},
        # main.csv is never offered, even if the comparison says CLICK lacks it
        missing=frozenset({"main.csv", "subroutines/b.csv"}),
    )

    window._select_row(NAMES.index("main.csv"))
    assert _add_sub_state(window) == "disabled"
    window._select_row(NAMES.index("subroutines/a.csv"))  # changed, but CLICK has it
    assert _add_sub_state(window) == "disabled"
    window._select_row(NAMES.index("subroutines/b.csv"))
    assert _add_sub_state(window) == "normal"


def test_new_subroutine_for_every_subroutine_when_click_cannot_be_compared(monkeypatch) -> None:
    # An unsaved project: CLICK's program cannot be read, so it may lack any subroutine
    window = _window(monkeypatch, SavedProgram(object(), generation=1, note="Could not read"), {})

    for name in NAMES:
        window._select_row(NAMES.index(name))
        assert _add_sub_state(window) == ("disabled" if name == "main.csv" else "normal")


@pytest.fixture
def adding(monkeypatch):
    """A window on new subroutine b.csv, with CLICK and timers faked."""
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: dict.fromkeys(NAMES, True)},
        missing=frozenset({"subroutines/b.csv"}),
    )
    window._select_row(NAMES.index("subroutines/b.csv"))
    window._get_click_hwnd = lambda: 100
    window.winfo_exists = lambda: True
    window.after = lambda _ms, callback: callback()
    win32 = Mock()
    win32.get_pid.return_value = "42"
    win32.get_foreground_pid.return_value = "42"
    win32.set_control_text.return_value = True
    monkeypatch.setattr(f"{MODULE}.WIN32", win32)
    return window, win32


def test_new_subroutine_sends_ctrl_u_and_names_the_dialog(adding) -> None:
    window, win32 = adding
    win32.find_process_window.side_effect = [None, None, 200]  # opens on the 2nd poll

    window._on_add_subroutine()

    win32.activate.assert_called_once_with(100)
    win32.send_ctrl_key.assert_called_once_with("U")
    win32.find_process_window.assert_called_with("42", "New Subroutine Program")
    win32.set_control_text.assert_called_once_with(200, "Edit1", "b")
    assert window._adding_subroutine is False
    assert _add_sub_state(window) == "normal"


def test_new_subroutine_fills_a_dialog_that_is_already_open(adding) -> None:
    window, win32 = adding
    win32.find_process_window.return_value = 200

    window._on_add_subroutine()

    win32.send_ctrl_key.assert_not_called()
    win32.set_control_text.assert_called_once_with(200, "Edit1", "b")


def test_new_subroutine_needs_click_in_front(adding) -> None:
    window, win32 = adding
    win32.find_process_window.return_value = None
    win32.get_foreground_pid.return_value = "7"

    window._on_add_subroutine()

    win32.send_ctrl_key.assert_not_called()
    assert window._adding_subroutine is False


def test_new_subroutine_gives_up_when_the_dialog_never_opens(adding) -> None:
    window, win32 = adding
    win32.find_process_window.return_value = None

    window._on_add_subroutine()

    win32.send_ctrl_key.assert_called_once_with("U")
    win32.set_control_text.assert_not_called()
    assert "did not open" in window._status_var.set.call_args.args[0]
    assert window._adding_subroutine is False


def test_first_time_tips_show_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    showinfo = Mock()
    monkeypatch.setattr(f"{MODULE}.messagebox.showinfo", showinfo)
    window = GuidedPasteWindow.__new__(GuidedPasteWindow)
    window.winfo_exists = lambda: True

    window._show_first_time_tips()
    window._show_first_time_tips()

    showinfo.assert_called_once()
    assert (tmp_path / "ClickNick" / "guided_paste_popup_seen").exists()


@pytest.mark.parametrize(("rungs", "warned"), [(99, False), (100, True)])
def test_copy_pops_up_from_100_rungs(monkeypatch, rungs: int, warned: bool) -> None:
    result = SimpleNamespace(payload=b"", rung_count=rungs, addresses_inserted=0, mdb_error=None)
    showinfo = Mock()
    monkeypatch.setattr(f"{MODULE}.prepare_csv_load", lambda *_a, **_k: result)
    monkeypatch.setattr(f"{MODULE}.copy_to_clipboard", lambda *_a, **_k: None)
    monkeypatch.setattr(f"{MODULE}.is_click_v4", lambda _hwnd: True)
    monkeypatch.setattr(f"{MODULE}.messagebox.showinfo", showinfo)
    window = GuidedPasteWindow.__new__(GuidedPasteWindow)
    window._items = [("main.csv", Path("main.csv"), rungs, "")]
    window._get_mdb_path = lambda: None
    window._get_click_hwnd = lambda: 0
    window._show_nicks_var = Mock()
    window._update_action_btn = Mock()
    window._status_var = Mock()

    window._do_copy_to_clipboard(0)

    assert showinfo.called is warned
    assert window._copied is True
