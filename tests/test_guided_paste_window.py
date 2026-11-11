"""Guided Paste follows the program in CLICK while it stays open, and steps through what differs."""

from __future__ import annotations

import typing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.connection_session import SavedProgram
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


def _rungs_differ(*numbers: int) -> ProgramChange:
    """A change in which CLICK lacks just the proposed rungs *numbers*."""
    return ProgramChange(after=RUNGS, opcodes=tuple(("insert", 0, 0, n - 1, n) for n in numbers))


def _rungs_removed(*numbers: int) -> ProgramChange:
    """A change in which the proposal drops CLICK's rungs *numbers* and adds none."""
    return ProgramChange(before=RUNGS, opcodes=tuple(("delete", n - 1, n, 0, 0) for n in numbers))


def _changes(differs: dict[str, bool]) -> dict[str, ProgramChange]:
    return {
        name: _rungs_differ(1) if differ else ProgramChange() for name, differ in differs.items()
    }


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
    window._group_idx = 0
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
    window._copy_all_btn = Mock()
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


def _copy_all_state(window) -> str:
    return window._copy_all_btn.configure.call_args.kwargs["state"]


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
    assert _copy_all_state(window) == "normal"
    assert "step 1 of 2" in _status(window)

    window._on_action()
    assert copies == [(RUNGS[:1], 1)]
    assert _action(window) == "Next →"
    assert "r1 of main.csv copied" in _status(window)

    window._on_action()  # Next: the row's second run
    assert window._done == set()
    assert _action(window) == "Copy r3..4"

    window._on_action()
    assert copies[-1] == (RUNGS[2:], 3)

    window._on_action()  # Next: nothing left of the row
    assert window._done == {"main.csv"}
    assert window._current_idx is None


def test_copy_whole_program_finishes_the_row_and_can_be_repeated(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 3, 4))

    window._on_copy_all()
    window._on_copy_all()  # The clipboard got overwritten before the paste

    assert copies == [(RUNGS, 1), (RUNGS, 1)]
    assert _copy_all_state(window) == "normal"
    assert "main.csv copied" in _status(window)

    window._on_action()  # Next
    assert window._done == {"main.csv"}


def test_program_click_lacks_is_copied_whole(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_differ(1, 2, 3, 4), missing=frozenset({"main.csv"}))
    assert _action(window) == "Copy"
    assert _copy_all_state(window) == "disabled"

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


def test_program_that_only_loses_rungs_says_to_delete_them(monkeypatch, copies) -> None:
    window = _on_main(monkeypatch, _rungs_removed(2))

    assert window._current_idx == MAIN
    assert _action(window) == "Copy"
    assert "only removes rungs" in _status(window)


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


def _inserted(window) -> list[tuple[str, str]]:
    """(line, tag) for everything put in the diff pane since it was last cleared."""
    calls = window._text.method_calls
    last_clear = max(i for i, call in enumerate(calls) if call[0] == "delete")
    return [(call.args[1], call.args[2]) for call in calls[last_clear:] if call[0] == "insert"]


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
        ("+R2  out(Y005)  # Y005\n", "added"),
        ("~ R2 -> R3  # Y002\n", "renumbered"),
    ]
    assert window._shown_diff.starts == {2: 2}
    # Line 4 of 5 in the pane: the note, two header lines, then the rung to paste
    window._text.index.return_value = "5.0"
    window._scroll_to_group()
    window._text.yview_moveto.assert_called_with(3 / 5)


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

    window.reload(select=("main.csv", [2]))

    assert window._items[window._current_idx][0] == "main.csv"
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
