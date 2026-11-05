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
NAMES = ["main.csv", "subroutines/a.csv", "subroutines/b.csv"]


def _window(monkeypatch, program: SavedProgram, differs_by_dir: dict[Path, dict[str, bool]]):
    """A window without Tk widgets, comparing against canned results per CSV folder."""
    monkeypatch.setattr(
        f"{MODULE}.compare_csv_folder",
        lambda _folder, csv_dir: FolderComparison(differs=differs_by_dir[csv_dir]),
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
    window._compare_note = ""
    window._sheet = Mock()
    window._progress_lbl = Mock()
    window._compare_lbl = Mock()
    window._action_btn = Mock()
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
