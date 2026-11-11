"""Guided Paste follows the program in CLICK while it stays open, and steps through what differs."""

from __future__ import annotations

import typing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.connection_session import SavedProgram
from clicknick.ladder.program import LegacyEncoding
from clicknick.services.rung_diff import (
    BundleComparison,
    BundleSources,
    ProgramChange,
    ProposedProgram,
    compare_rungs,
)
from clicknick.views.guided_paste_window import GuidedPasteWindow

MODULE = "clicknick.views.guided_paste_window"
NAMES = ["subroutines/a.csv", "subroutines/b.csv", "main.csv"]
MAIN = NAMES.index("main.csv")


def _coils(*coils: str) -> list[Rung]:
    out = typing.get_type_hints(Contact)["type"].COIL_OUT
    return [
        Rung(logical_rows=1, conditions=[["-"] * 31], instructions=[Coil(out, coil)], comment=coil)
        for coil in coils
    ]


# What each program in the folder holds
RUNGS = tuple(_coils("Y001", "Y002", "Y003", "Y004"))


def _without(*numbers: int) -> list[Rung]:
    return [rung for number, rung in enumerate(RUNGS, start=1) if number not in numbers]


def _rungs_differ(*numbers: int) -> ProgramChange:
    """CLICK has the program without the proposed rungs *numbers*: they are new."""
    return compare_rungs(_without(*numbers), RUNGS)


def _rungs_removed(*numbers: int) -> ProgramChange:
    """CLICK has all four rungs; the proposal is them without *numbers*."""
    return compare_rungs(RUNGS, _without(*numbers))


def _changes(differs: dict[str, bool]) -> dict[str, ProgramChange]:
    return {
        name: _rungs_differ(1) if differ else ProgramChange() for name, differ in differs.items()
    }


@pytest.fixture(autouse=True)
def _own_preferences(monkeypatch, tmp_path: Path) -> Path:
    """Keep each test's Guided Paste preferences out of the real per-user folder."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return tmp_path / "appdata" / "ClickNick" / "guided-paste.json"


class _Var:
    """A Tk variable without Tk."""

    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


def _bare_window(folder_names: list[str] = NAMES):
    """A window with mocks for widgets and nothing compared yet."""
    window = GuidedPasteWindow.__new__(GuidedPasteWindow)
    window._folder = Path("bundle")
    window._source_dir = None
    window._programs = {
        name: ProposedProgram(name, Path(name), RUNGS, len(RUNGS)) for name in folder_names
    }
    window._folder_items = [(name, Path(name), len(RUNGS), "") for name in folder_names]
    window._items = list(window._folder_items)
    window._done = set()
    window._current_idx = None
    window._copied = False
    window._step_idx = 0
    window._selection = {}
    window._nickname_path = None
    window._changes = {}
    window._only_in_click = {}
    window._missing_in_click = frozenset()
    window._click_compared = False
    window._adding_subroutine = False
    window._compare_note = ""
    window._view_name = None
    window._saved_program = SavedProgram()
    window._before_sources = None
    window._after_sources = BundleSources()
    window._expanded = {}
    window._expanded_change = None
    window._sheet = Mock()
    window._text = Mock()
    window._text.index.return_value = "1.0"
    window._progress_lbl = Mock()
    window._nick_lbl = Mock()
    window._notice_lbl = Mock()
    window._opts = Mock()
    window._read_at = "10:42"
    window._on_pasted = Mock()
    window.destroy = Mock()
    window._compare_lbl = Mock()
    window._action_btn = Mock()
    window._copy_whole_var = _Var(False)
    window._add_sub_btn = Mock()
    window._status_var = Mock()
    window._show_nicks_var = Mock()
    window._get_mdb_path = lambda: None
    window._get_click_hwnd = lambda: 0
    return window


def _window(
    monkeypatch,
    program: SavedProgram,
    changes_by_dir: dict[Path, dict[str, ProgramChange]],
    missing: frozenset[str] = frozenset(),
    only_in_click: dict[str, ProgramChange] | None = None,
):
    """A window without Tk widgets, comparing against canned results per CSV folder."""
    monkeypatch.setattr(
        f"{MODULE}.compare_bundle",
        lambda _programs, csv_dir: BundleComparison(
            compared=True,
            changes=changes_by_dir[csv_dir],
            only_in_click=only_in_click or {},
            missing_in_click=missing,
        ),
    )
    window = _bare_window()
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


def _differs(window) -> dict[str, bool]:
    return {name: change.differs for name, change in window._changes.items()}


def _action(window) -> str:
    return window._action_btn.configure.call_args.kwargs["text"]


def _status(window) -> str:
    return window._status_var.set.call_args.args[0]


# ---------------------------------------------------------------------------
# Following the program in CLICK
# ---------------------------------------------------------------------------


def test_comparison_appears_once_the_new_project_is_read(monkeypatch) -> None:
    session = object()
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, building=True, note="reading"),
        {
            csv_dir: _changes(
                {"main.csv": False, "subroutines/a.csv": False, "subroutines/b.csv": True}
            )
        },
    )
    assert _differs(window) == {}
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
            old_dir: _changes(dict.fromkeys(NAMES, True)),
            new_dir: _changes(
                {"main.csv": False, "subroutines/a.csv": False, "subroutines/b.csv": True}
            ),
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
    assert _differs(window) == {}
    assert _note(window) == "reading"

    _change(window, SavedProgram(new, generation=1, csv_dir=new_dir, note=""))
    assert _differs(window)["main.csv"] is False
    assert window._current_idx == NAMES.index("subroutines/b.csv")


def test_click_save_keeps_rows_while_building_and_the_row_being_pasted(monkeypatch) -> None:
    session = object()
    before, after = Path("before/csv"), Path("after/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, generation=1, csv_dir=before, note=""),
        {
            before: _changes(dict.fromkeys(NAMES, True)),
            # The save took the row being pasted; main.csv is still to do
            after: _changes({**dict.fromkeys(NAMES, False), "main.csv": True}),
        },
    )
    window._copied = True

    _change(window, SavedProgram(session, generation=2, building=True, note="reading"))
    assert _differs(window) == dict.fromkeys(NAMES, True)
    assert _note(window) == "reading"

    _change(window, SavedProgram(session, generation=2, csv_dir=after, note=""))
    assert _differs(window)["subroutines/a.csv"] is False
    assert window._current_idx == 0
    assert window._copied is True
    window.destroy.assert_not_called()


def test_window_closes_once_click_has_saved_everything(monkeypatch) -> None:
    session = object()
    before, after = Path("before/csv"), Path("after/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, generation=1, csv_dir=before, note=""),
        {
            before: _changes(dict.fromkeys(NAMES, True)),
            after: _changes(dict.fromkeys(NAMES, False)),
        },
    )
    window._copied = True  # The last paste was saved without clicking "Next"

    _change(window, SavedProgram(session, generation=2, csv_dir=after, note=""))

    window._on_pasted.assert_called_once_with()
    window.destroy.assert_called_once_with()


def test_window_opened_on_an_up_to_date_folder_stays_open(monkeypatch) -> None:
    session = object()
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, building=True, note="reading"),
        {csv_dir: _changes(dict.fromkeys(NAMES, False))},
    )

    # The first comparison arrives; a later save changes nothing
    _change(window, SavedProgram(session, generation=1, csv_dir=csv_dir, note=""))
    _change(window, SavedProgram(session, generation=2, csv_dir=csv_dir, note=""))

    window.destroy.assert_not_called()
    assert "Every changed program has been pasted" in _status(window)


def test_window_stays_open_while_click_has_a_program_the_folder_dropped(monkeypatch) -> None:
    session = object()
    before, after = Path("before/csv"), Path("after/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, generation=1, csv_dir=before, note=""),
        {
            before: _changes(dict.fromkeys(NAMES, True)),
            after: _changes(dict.fromkeys(NAMES, False)),
        },
        only_in_click={"subroutines/old.csv": _rungs_removed(1)},
    )

    _change(window, SavedProgram(session, generation=2, csv_dir=after, note=""))

    window.destroy.assert_not_called()


# ---------------------------------------------------------------------------
# New subroutine in CLICK
# ---------------------------------------------------------------------------


def _add_sub_state(window) -> str:
    return window._add_sub_btn.configure.call_args.kwargs["state"]


def test_new_subroutine_only_for_subroutines_click_lacks(monkeypatch) -> None:
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: _changes(dict.fromkeys(NAMES, True))},
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
        {csv_dir: _changes(dict.fromkeys(NAMES, True))},
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
    assert "did not open" in _status(window)
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


# ---------------------------------------------------------------------------
# Copying: the whole program, or the rungs that differ
# ---------------------------------------------------------------------------


@pytest.fixture
def copies(monkeypatch) -> list[tuple[tuple, int]]:
    """What each copy put on the clipboard: (rungs, number of the first)."""
    made: list[tuple[tuple, int]] = []

    def _prepare(rungs, *, first_rung=1, **_kwargs):
        made.append((tuple(rungs), first_rung))
        return SimpleNamespace(
            payload=b"", rung_count=len(rungs), addresses_inserted=0, mdb_error=None
        )

    monkeypatch.setattr(f"{MODULE}.prepare_rungs_load", _prepare)
    monkeypatch.setattr(f"{MODULE}.copy_to_clipboard", lambda *_a, **_k: None)
    monkeypatch.setattr(f"{MODULE}.is_click_v4", lambda _hwnd: True)
    return made


def _on_main(monkeypatch, change: ProgramChange, missing: frozenset[str] = frozenset()):
    """A window whose only step is main.csv, differing from CLICK by *change*."""
    csv_dir = Path("workspace/csv")
    changes = {**_changes(dict.fromkeys(NAMES, False)), "main.csv": change}
    return _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: changes},
        missing=missing,
    )


@pytest.mark.parametrize(("rungs", "warned"), [(99, False), (100, True)])
def test_copy_pops_up_from_100_rungs(monkeypatch, rungs: int, warned: bool) -> None:
    result = SimpleNamespace(payload=b"", rung_count=rungs, addresses_inserted=0, mdb_error=None)
    showinfo = Mock()
    monkeypatch.setattr(f"{MODULE}.prepare_rungs_load", lambda *_a, **_k: result)
    monkeypatch.setattr(f"{MODULE}.copy_to_clipboard", lambda *_a, **_k: None)
    monkeypatch.setattr(f"{MODULE}.is_click_v4", lambda _hwnd: True)
    monkeypatch.setattr(f"{MODULE}.messagebox.showinfo", showinfo)
    window = _bare_window(["main.csv"])

    assert window._copy_rungs(0, None) is True

    assert showinfo.called is warned
    assert window._copied is True


def test_changed_program_is_stepped_through_by_runs_of_differing_rungs(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))
    assert window._current_idx == MAIN
    assert _action(window) == "Copy r1"
    assert "step 1 of 2" in _status(window)

    window._on_action()
    assert copies == [(RUNGS[:1], 1)]
    assert _action(window) == "Next →"
    assert "r1 of main.csv copied" in _status(window)
    assert "To copy it again, click its row" in _status(window)

    window._on_action()  # Next: the row's second run
    assert window._done == set()
    assert _action(window) == "Copy r3..4"

    window._on_action()
    assert copies[-1] == (RUNGS[2:], 3)

    window._on_action()  # Next: nothing left of the row
    assert window._done == {"main.csv"}
    assert window._current_idx is None


def _switch_copy(window, *, whole: bool) -> None:
    """Pick "Whole program" or "Changed rungs" on the Copy switch."""
    window._copy_whole_var.set(whole)
    window._on_copy_mode()


def test_whole_program_switch_copies_the_program_in_one_step(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))
    assert _action(window) == "Copy r1"

    _switch_copy(window, whole=True)
    assert _action(window) == "Copy"
    assert "the whole program, 4 rungs, replaces what CLICK has" in _status(window)
    clear_first = "select all of its rungs (Shift+Up/Down) and delete them, then paste"
    assert clear_first in _status(window)

    window._on_action()
    assert copies == [(RUNGS, 1)]
    assert _action(window) == "Next →"
    assert clear_first in _status(window)  # Still on screen while pasting

    window._on_action()  # Next
    assert window._done == {"main.csv"}


def test_copy_switch_is_remembered_for_the_next_window(monkeypatch, _own_preferences) -> None:
    from clicknick.views.guided_paste_window import _read_copy_whole

    assert _read_copy_whole() is False  # Changed rungs until the user chooses otherwise
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))

    _switch_copy(window, whole=True)
    assert _read_copy_whole() is True

    _switch_copy(window, whole=False)
    assert _read_copy_whole() is False

    _own_preferences.write_text("not json", encoding="utf-8")
    assert _read_copy_whole() is False


# ---------------------------------------------------------------------------
# Reading the folder
# ---------------------------------------------------------------------------


def _folder_window(tmp_path: Path, source_dir: Path | None = None):
    """A window on a real folder holding main.csv and nicknames.csv, nothing in CLICK."""
    folder = tmp_path / "bundle"
    folder.mkdir(exist_ok=True)
    write_csv(folder / "main.csv", _coils("Y001", "Y002"))
    (folder / "nicknames.csv").write_text("", encoding="utf-8")
    window = _bare_window([])
    window._folder = folder
    window._source_dir = source_dir
    window._get_saved_program = SavedProgram
    return window


def test_rungs_asked_for_by_number_do_not_change_the_remembered_switch(tmp_path: Path) -> None:
    from clicknick.views.guided_paste_window import _read_copy_whole, _save_copy_whole

    _save_copy_whole(True)
    window = _folder_window(tmp_path)
    window._copy_whole_var.set(True)

    window.reload(select=("main.csv", [2]))

    assert window._copy_whole_var.get() is False
    assert _read_copy_whole() is True


def test_switching_copy_mode_starts_the_rows_step_over(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))
    window._on_action()  # Copy r1
    window._on_action()  # Next
    window._on_action()  # Copy r3..4, not yet pasted
    assert _action(window) == "Next →"

    _switch_copy(window, whole=True)
    assert window._copied is False
    assert _action(window) == "Copy"

    _switch_copy(window, whole=False)
    assert _action(window) == "Copy r1"
    assert window._done == set()


def test_whole_program_switch_stays_on_for_the_next_row(monkeypatch, copies) -> None:
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: dict.fromkeys(NAMES, _rungs_differ(1, 3))},
    )
    _switch_copy(window, whole=True)

    window._on_action()  # Copy
    window._on_action()  # Next: on to the second program

    assert window._current_idx == 1
    assert _action(window) == "Copy"


def test_sheet_selection_follows_the_current_step(monkeypatch, copies) -> None:
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: dict.fromkeys(NAMES, _rungs_differ(1))},
    )
    window._sheet.select_cell.assert_called_with(0, 1, run_binding_func=False)

    window._on_action()  # Copy
    window._on_action()  # Next: on to the second program

    assert window._current_idx == 1
    window._sheet.select_cell.assert_called_with(1, 1, run_binding_func=False)
    window._sheet.see.assert_called_with(1, 1, keep_xscroll=True)

    # A cell the user clicked in the row stays the selected one
    window._sheet.select_cell.reset_mock()
    window._sheet.get_currently_selected.return_value = SimpleNamespace(row=2, column=4)
    window._on_cell_select(None)
    assert window._current_idx == 2
    window._sheet.select_cell.assert_not_called()


def test_program_click_lacks_is_copied_whole(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 2, 3, 4), missing=frozenset({"main.csv"}))
    assert _action(window) == "Copy"

    window._on_action()

    assert copies == [(RUNGS, 1)]


def test_selected_rungs_replace_the_differing_ones(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))
    window._selection = {"main.csv": [2, 3]}
    window._select_row(MAIN)
    assert _action(window) == "Copy r2..3"

    window._on_action()

    assert copies == [(RUNGS[1:3], 2)]


def test_reselecting_the_row_allows_copying_the_same_run_again(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))
    window._on_action()
    window._on_action()  # Next
    window._on_action()  # Copy r3..4

    window._select_row(MAIN)

    assert window._copied is False
    assert _action(window) == "Copy r3..4"


def test_click_save_part_way_steps_through_what_is_left(monkeypatch, copies) -> None:
    session = object()
    before, after = Path("before/csv"), Path("after/csv")
    same = _changes(dict.fromkeys(NAMES, False))
    window = _window(
        monkeypatch,
        SavedProgram(session, generation=1, csv_dir=before, note=""),
        {
            before: {**same, "main.csv": _rungs_differ(1, 3, 4)},
            after: {**same, "main.csv": _rungs_differ(3, 4)},
        },
    )
    window._on_action()  # Copy r1, then paste and save in CLICK without "Next"

    _change(window, SavedProgram(session, generation=2, csv_dir=after, note=""))

    assert window._current_idx == MAIN
    assert window._copied is False
    assert _action(window) == "Copy r3..4"
    assert "step 1 of 1" in _status(window)


def test_removed_rungs_are_a_step_with_nothing_to_copy(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_removed(2, 3))

    assert window._current_idx == MAIN
    assert _action(window) == "Next →"
    assert "step 1 of 1: rungs 2 to 3 are not in the program any more" in _status(window)
    assert "Select them in CLICK (Shift+Up/Down) and delete them" in _status(window)

    window._on_action()

    assert copies == []
    assert window._done == {"main.csv"}


def test_each_step_says_where_its_rungs_go_in_click(monkeypatch, copies) -> None:
    # After Y001, CLICK has three rungs where the proposal has three others
    click = _coils("Y001", "Y007", "Y008", "Y009")
    window = _on_main(monkeypatch, compare_rungs(click, RUNGS))

    assert _action(window) == "Copy r2..4"
    assert "step 1 of 2: r2..4 replaces rung 2" in _status(window)
    assert "In CLICK, select rung 2 and paste over it (Ctrl+V)" in _status(window)

    window._on_action()  # Copy
    assert copies == [(RUNGS[1:], 2)]
    assert "In CLICK, select rung 2 and paste over it (Ctrl+V), then click" in _status(window)

    window._on_action()  # Next: the two rungs the paste did not take the place of
    assert _action(window) == "Next →"
    assert "step 2 of 2: rungs 5 to 6 are not in the program any more" in _status(window)

    window._on_action()
    assert window._done == {"main.csv"}


def test_new_rungs_go_over_an_empty_rung(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))

    assert "step 1 of 2: r1 is new" in _status(window)
    assert "insert an empty rung above rung 1 and paste over it" in _status(window)

    window._on_action()  # Copy
    window._on_action()  # Next

    assert "step 2 of 2: r3..4 is new" in _status(window)
    assert "insert an empty rung after the last rung and paste over it" in _status(window)


def test_program_with_many_steps_suggests_copying_it_whole(monkeypatch) -> None:
    proposed = _coils(*(f"Y{n:03d}" for n in range(1, 14)))
    click = proposed[1::2]  # Every other rung is new: seven steps
    window = _on_main(monkeypatch, compare_rungs(click, proposed))

    assert 'With 7 steps, switching Copy to "Whole program" may be quicker' in _status(window)

    few = _on_main(monkeypatch, _rungs_differ(1, 3))
    assert "may be quicker" not in _status(few)


def test_unreadable_program_is_not_copied(monkeypatch, copies) -> None:
    window = _bare_window(["main.csv"])
    window._programs["main.csv"] = ProposedProgram(
        "main.csv", Path("main.csv"), None, 0, error="bad row 3"
    )

    assert window._copy_rungs(0, None) is False

    assert copies == []
    assert window._copied is False
    assert "bad row 3" in _status(window)


# ---------------------------------------------------------------------------
# The "vs CLICK" column and the diff pane
# ---------------------------------------------------------------------------


def test_vs_click_column_says_how_each_program_differs(monkeypatch) -> None:
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {
            csv_dir: {
                "subroutines/a.csv": ProgramChange(),
                "subroutines/b.csv": _rungs_differ(1, 2, 3, 4),
                "main.csv": ProgramChange(
                    before=RUNGS,
                    after=RUNGS,
                    opcodes=(("insert", 0, 0, 0, 2), ("delete", 3, 4, 2, 2)),
                ),
            }
        },
        missing=frozenset({"subroutines/b.csv"}),
        only_in_click={"subroutines/old.csv": _rungs_removed(1, 2, 3)},
    )

    rows = {row[1]: row for row in window._sheet.set_sheet_data.call_args.args[0]}

    assert rows["subroutines/a.csv"][3] == "Up to date"
    assert rows["subroutines/b.csv"][3] == "New"
    assert rows["main.csv"][3] == "2 changed, 1 removed"
    assert rows["subroutines/old.csv"][2:4] == ["4", "Only in CLICK"]
    assert window._click_label("not compared.csv") == ""


@pytest.mark.parametrize(
    ("change", "label"),
    [
        (_rungs_differ(2), "1 rung changed"),
        (_rungs_differ(2, 3), "2 rungs changed"),
        (_rungs_removed(1), "1 rung removed"),
    ],
)
def test_vs_click_column_counts_rungs(monkeypatch, change: ProgramChange, label: str) -> None:
    window = _on_main(monkeypatch, change)

    assert window._click_label("main.csv") == label


def _pieces(window) -> list[tuple[str, str | tuple[str, ...]]]:
    """(text, tags) of each insert into the diff pane since it was last cleared."""
    calls = window._text.method_calls
    last_clear = max(i for i, call in enumerate(calls) if call[0] == "delete")
    return [(call.args[1], call.args[2]) for call in calls[last_clear:] if call[0] == "insert"]


def _inserted(window) -> list[tuple[str, str]]:
    """(line, line tag) for everything put in the diff pane since it was last cleared.

    A line put in piece by piece (its gutter, its changed words) is joined.
    """
    lines: list[tuple[str, str]] = []
    for text, tags in _pieces(window):
        if lines and not lines[-1][0].endswith("\n"):
            lines[-1] = (lines[-1][0] + text, lines[-1][1])
        else:
            lines.append((text, tags if isinstance(tags, str) else "".join(tags[:1])))
    return lines


def test_pane_marks_the_gutter_and_the_changed_words(monkeypatch) -> None:
    window = _on_main(monkeypatch, compare_rungs(_coils("Y001"), _coils("Y009")))

    assert _pieces(window)[-6:] == [
        ("+", ("added", "added_gutter")),
        ("R1  out(", "added"),
        ("Y009", ("added", "added_word")),
        (")  # ", "added"),
        ("Y009", ("added", "added_word")),
        ("\n", "added"),
    ]


def test_pane_shows_the_current_rows_difference_and_scrolls_to_its_step(monkeypatch) -> None:
    change = compare_rungs(_coils("Y001", "Y002"), _coils("Y001", "Y005", "Y002"))
    window = _on_main(monkeypatch, change)

    assert _inserted(window) == [
        (
            "pyrung could not show this program as text;"
            " each rung is listed by its instructions.\n",
            "note",
        ),
        ("--- CLICK/main.csv\n", "file_header"),
        ("+++ proposed/main.csv\n", "file_header"),
        (" R1  out(Y001)  # Y001\n", ""),
        ("+R2  out(Y005)  # Y005\n", "added"),
        (" R3  out(Y002)  # Y002\n", ""),
    ]
    assert window._shown_diff.starts == {2: 2}
    # Line 4 of 6 in the pane: the note, two header lines, then the rung above
    # the one to paste
    window._text.index.return_value = "6.0"
    window._scroll_to_step()
    window._text.yview_moveto.assert_called_with(3 / 6)


def test_clicking_a_separator_arrow_shows_more_unchanged_rungs(monkeypatch) -> None:
    coils = [f"Y00{number}" for number in range(1, 9)]
    window = _on_main(monkeypatch, compare_rungs(_coils(*coils), _coils(*coils[:7], "Y009")))
    assert _inserted(window)[3] == ("↑ @@ R1..6 unchanged @@\n", "separator")

    # The arrow is on line 4: the note and two header lines are above it
    positions = {"@3,40": "4.0", "@0,0": "1.0", "end-1c": "9.0"}
    window._text.index.side_effect = positions.__getitem__
    window._text.get.return_value = "↑"
    window._on_expand(SimpleNamespace(x=3, y=40))

    assert _inserted(window)[3] == ("↑ @@ R1..3 unchanged @@\n", "separator")
    assert [line for line, _tag in _inserted(window)[4:8]] == [
        f" R{number}  out(Y00{number})  # Y00{number}\n" for number in range(4, 8)
    ]
    # Where the pane was, not the step's difference
    window._text.yview_moveto.assert_called_with(0)


def test_pane_explains_rows_with_nothing_to_show(monkeypatch) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1))
    window._programs["subroutines/b.csv"] = ProposedProgram(
        "subroutines/b.csv", Path("b.csv"), None, 0, error="bad row 3"
    )
    del window._changes["subroutines/b.csv"]

    def _shown(name: str) -> str:
        window._view_name = name
        note, diff = window._describe_view()
        assert not diff.lines
        return note

    assert _shown("subroutines/a.csv") == "subroutines/a.csv matches CLICK's last save."
    assert _shown("subroutines/b.csv") == "subroutines/b.csv could not be read: bad row 3"
    assert "no rungs" in _shown("nicknames.csv")

    window._changes = {}
    window._saved_program = SavedProgram(note="Connect to CLICK to see which programs changed")
    assert _shown("main.csv") == "Connect to CLICK to see which programs changed"


def test_clicking_a_program_only_in_click_shows_what_click_has(monkeypatch) -> None:
    csv_dir = Path("workspace/csv")
    window = _window(
        monkeypatch,
        SavedProgram(object(), generation=1, csv_dir=csv_dir, note=""),
        {csv_dir: _changes(dict.fromkeys(NAMES, True))},
        only_in_click={"subroutines/old.csv": compare_rungs(_coils("Y009"), [])},
    )
    current = window._current_idx
    window._sheet.get_currently_selected.return_value = SimpleNamespace(row=len(NAMES))

    window._on_cell_select(None)

    assert window._current_idx == current  # Reading it does not make it a step
    assert _inserted(window)[-1] == ("-R1  out(Y009)  # Y009\n", "removed")
    assert "Pasting cannot remove it" in _status(window)


def test_plain_folder_starts_with_the_nicknames_import(tmp_path: Path) -> None:
    window = _folder_window(tmp_path)

    window._start()

    assert [name for name, *_ in window._items] == ["nicknames.csv", "main.csv"]
    assert window._items[1][2] == 2
    assert _action(window) == "Import"


def test_workspace_proposal_leaves_nicknames_to_the_address_editor(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "plc"
    source_dir.mkdir(parents=True)
    (source_dir / "main.py").write_text("workspace source\n", encoding="utf-8")
    window = _folder_window(tmp_path, source_dir)

    window._start()

    assert [name for name, *_ in window._items] == ["main.csv"]
    assert window._proposed_sources().text("main.csv") == "workspace source\n"


def test_reload_starts_on_the_named_program_with_its_selected_rungs(tmp_path: Path) -> None:
    window = _folder_window(tmp_path)
    window._copy_whole_var.set(True)

    window.reload(select=("main.csv", [2]))

    assert window._items[window._current_idx][0] == "main.csv"
    # Rungs asked for by number are what gets copied, whatever the switch said
    assert _action(window) == "Copy r2"


def test_reload_keeps_done_programs_whose_rungs_did_not_change(tmp_path: Path) -> None:
    window = _folder_window(tmp_path, tmp_path / "src" / "plc")
    sub = window._folder / "subroutines" / "fill.csv"
    sub.parent.mkdir()
    write_csv(sub, _coils("Y003"))
    window._start()
    window._done = {"subroutines/fill.csv", "main.csv"}

    write_csv(window._folder / "main.csv", _coils("Y001", "Y009"))  # exported again
    window.reload(source_dir=window._source_dir)

    assert window._done == {"subroutines/fill.csv"}
    assert window._items[window._current_idx][0] == "main.csv"

    window._start()  # Restart clears the rest
    assert window._done == set()


def test_folder_emptied_by_a_click_save_keeps_what_was_read(tmp_path: Path, copies) -> None:
    window = _folder_window(tmp_path, tmp_path / "src" / "plc")
    window._start()
    (window._folder / "main.csv").unlink()

    window._start()  # Restart
    window._on_action()

    assert [name for name, *_ in window._items] == ["main.csv"]
    assert len(copies[0][0]) == 2
    # The window says what it is still pasting, and how to get the source back
    notice = window._notice_lbl.configure.call_args.kwargs["text"]
    assert "still holds the proposal exported at" in notice
    assert "clicknick-cli restore" in notice
    window._notice_lbl.pack.assert_called()


def test_no_notice_while_the_folder_still_holds_what_was_read(tmp_path: Path) -> None:
    window = _folder_window(tmp_path, tmp_path / "src" / "plc")

    window._start()

    window._notice_lbl.pack.assert_not_called()
    window._notice_lbl.pack_forget.assert_called()


# ---------------------------------------------------------------------------
# Rungs CLICK holds in a legacy encoding
# ---------------------------------------------------------------------------


def _legacy(rung: int | None, file: str = "main.csv") -> LegacyEncoding:
    detail = "it is stored as 16-bit and CLICK runs it as 4464."
    return LegacyEncoding(file, "Main Program", rung, "Math", "H70000", detail)


def _legacy_click_copy(*rungs: int | None) -> ProgramChange:
    """CLICK's copy reads the same as the proposal, but holds *rungs* in a legacy encoding."""
    return compare_rungs(RUNGS, RUNGS, [_legacy(rung) for rung in rungs])


def test_program_whose_click_copy_has_a_legacy_encoding_needs_pasting(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _legacy_click_copy(3))

    assert not window._matches_click("main.csv")
    assert window._needs_paste("main.csv")
    assert window._current_idx == MAIN
    assert _action(window) == "Copy r3"
    status = _status(window)
    assert "r3 replaces rung 3" in status
    assert (
        "CLICK's copy has an old encoding. Math H70000: it is stored as 16-bit and CLICK runs"
        " it as 4464. Paste it again." in status
    )
    assert window._click_label("main.csv") == "1 rung changed, old encoding"

    window._on_action()
    assert copies == [(RUNGS[2:3], 3)]


def test_legacy_encoding_row_is_red_until_it_is_the_current_row(monkeypatch) -> None:
    window = _on_main(monkeypatch, _legacy_click_copy(3))
    window._sheet.reset_mock()
    window._current_idx = None
    window._update_highlights()

    red = {
        call.kwargs["row"]
        for call in window._sheet.highlight_cells.call_args_list
        if call.kwargs.get("bg") == "#f8d7da"
    }
    assert red == {MAIN}

    window._sheet.reset_mock()
    window._current_idx = MAIN
    window._update_highlights()
    assert {call.kwargs.get("bg") for call in window._sheet.highlight_cells.call_args_list} == {
        "#cce5ff",
        None,
    }


def test_pane_says_which_rungs_click_holds_in_a_legacy_encoding(monkeypatch) -> None:
    window = _on_main(monkeypatch, _legacy_click_copy(2, 4))

    note, _diff = window._describe_view()

    assert note.splitlines()[:3] == [
        "CLICK's copy of rungs 2, 4 has an old encoding. Paste them again.",
        "  rung 2, Math H70000: it is stored as 16-bit and CLICK runs it as 4464.",
        "  rung 4, Math H70000: it is stored as 16-bit and CLICK runs it as 4464.",
    ]
    # The diff starts below every line of the note
    assert window._diff_first_line == note.count("\n") + 2


def test_legacy_encoding_without_a_rung_number_pastes_the_whole_program(monkeypatch) -> None:
    window = _on_main(monkeypatch, _legacy_click_copy(None))

    assert window._needs_paste("main.csv")
    assert "Paste the whole program again." in window._describe_view()[0]

    _switch_copy(window, whole=True)
    assert "CLICK's copy has an old encoding" in _status(window)


def test_row_clears_once_click_saves_a_clean_copy(monkeypatch) -> None:
    session = object()
    before, after = Path("before/csv"), Path("after/csv")
    window = _window(
        monkeypatch,
        SavedProgram(session, generation=1, csv_dir=before, note=""),
        {
            before: {**_changes(dict.fromkeys(NAMES, False)), "main.csv": _legacy_click_copy(3)},
            after: _changes(dict.fromkeys(NAMES, False)),
        },
    )
    assert window._needs_paste("main.csv")

    _change(window, SavedProgram(session, generation=2, csv_dir=after, note=""))

    assert window._matches_click("main.csv")
    window.destroy.assert_called_once_with()


def test_legacy_note_names_runs_of_rungs_and_counts_past_five() -> None:
    from clicknick.views.guided_paste_window import _legacy_note

    rungs = _coils(*(f"Y{n:03d}" for n in range(1, 10)))
    change = compare_rungs(rungs, rungs, [_legacy(n) for n in (1, 2, 3, 4, 5, 6, 9)])

    lines = _legacy_note(change).splitlines()

    assert lines[0] == "CLICK's copy of rungs 1 to 6, 9 has an old encoding. Paste them again."
    assert len(lines) == 7
    assert lines[-1] == "  ...and 2 more"


def test_deleting_a_legacy_encoded_rung_says_why(monkeypatch, copies) -> None:
    # CLICK's first Y001 is the stale one. The matcher keeps its second Y001,
    # so the stale rung is deleted and a good copy goes in after the last rung.
    rungs = _coils("Y001", "Y001")
    change = compare_rungs(rungs, rungs, [_legacy(1)])
    assert [opcode[0] for opcode in change.opcodes] == ["delete", "equal", "insert"]
    window = _on_main(monkeypatch, change)

    status = _status(window)
    assert "step 1 of 2: rung 1 is not in the program any more" in status
    assert status.endswith(
        "CLICK's copy has an old encoding. Math H70000: it is stored as 16-bit and CLICK"
        " runs it as 4464."
    )

    window._on_action()  # Next: the good copy
    assert "step 2 of 2: r2 is new" in _status(window)
    assert "old encoding" not in _status(window)


def test_old_copies_left_after_pasting_stale_rungs_are_named_as_such(monkeypatch, copies) -> None:
    # Pasting r2..4 over CLICK's rung 2 leaves CLICK's old rungs 3 and 4 below them
    window = _on_main(monkeypatch, _legacy_click_copy(2, 3, 4))
    assert _action(window) == "Copy r2..4"

    window._on_action()  # Copy
    window._on_action()  # Next: the old copies

    status = _status(window)
    assert status.startswith(
        "main.csv, step 2 of 2: CLICK's old copies of these rungs are now below the pasted"
        " ones, at rungs 5 to 6.\nSelect them in CLICK"
    )
    assert "not in the program any more" not in status
    assert status.endswith(
        "CLICK's copy has an old encoding. Math H70000: it is stored as 16-bit and CLICK"
        " runs it as 4464."
    )
