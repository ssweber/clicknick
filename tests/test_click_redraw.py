"""The CLICK nickname redraw (issue #36) against a fake desktop.

The fake follows what CLICK v4.00 showed for File > Import > Nickname (live runs,
2026-11-15 to 2026-11-17, ``devtools/click_runner.py``'s ``import_one``): an Open
dialog owned by the main window with three import modes, Merge (Project priority)
checked, the File name edit (1148 in ComboBox 1148), Open (1) and Cancel (2); a
progress window titled "frmProgress" then "Import - <mode>"; then a box "Import
Database" reading "Completed!" with OK, or the "Import Error List".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clicknick.models.desktop import Control, Window
from clicknick.services import click_redraw
from clicknick.services.click_redraw import (
    HEADER,
    IMPORT_NICKNAME,
    RedrawOutcome,
    redraw_nicknames,
)

PID = 7
MAIN = 100
OWN_PID = 1
OWN_WINDOW = 900
OWN_POPUP = 901  # A message box ClickNick shows over its window

OPEN = 200
PROJECT, FILE, DELETE = 201, 202, 203
COMBO, EDIT = 210, 211
OPEN_BUTTON, CANCEL = 220, 221
PROGRESS = 300
DONE, DONE_TEXT, DONE_OK = 400, 401, 402
ERRORS, ERRORS_MEMO, ERRORS_OK = 500, 501, 502
MODES = {
    PROJECT: "Merge (Project priority)",
    FILE: "Merge (File priority)",
    DELETE: "Delete Existing",
}


class FakeClick:
    """CLICK's import, step by step, as the desktop shows it to the redraw."""

    def __init__(self) -> None:
        self.time = 0.0
        self.main_enabled = True
        self.answers = True
        self.extra: list[Window] = []  # Windows CLICK shows besides the import's
        self.open_shown = False
        self.opens_dialog = True
        self.open_title = "Open"
        self.button_texts = {OPEN_BUTTON: "&Open", CANCEL: "Cancel", DONE_OK: "OK"}
        self.progress_title: str | None = None
        self.answer: int | None = None
        self.answer_text = "Completed!"
        self.errors = False
        self.radios = dict(MODES)
        self.has_file_name = True
        self.checked = PROJECT
        self.radio_sticks = True
        self.edit_text = ""
        self.edit_empties = 0  # Times the edit drops the path set (a dialog still opening)
        self.edit_reads = 0
        self.commands: list[tuple[int, int]] = []
        self.pressed: list[int] = []
        self.imported: list[bytes] = []
        self.imported_mode: str | None = None
        self.imported_path: Path | None = None
        self.foreground_window = OWN_WINDOW
        self.click_takes_foreground = True
        self.popups: dict[int, int] = {}  # GetLastActivePopup
        self.foreground_set: list[int] = []
        self.holds_file = False  # CLICK keeps the CSV open (answer never comes)
        self.held = None

    # -- what the fake shows ----------------------------------------------------

    def windows(self, pid: int) -> list[Window]:
        assert pid == PID
        found = [Window(MAIN, "Afx:main", "CLICK Programming Software", 0, self.main_enabled)]
        found += self.extra
        if self.open_shown:
            found.append(Window(OPEN, "#32770", self.open_title, MAIN, True))
        if self.progress_title is not None:
            found.append(Window(PROGRESS, "TfrmProgress", self.progress_title, MAIN, True))
            # Titled by the mode it imports in, from the next look on
            self.progress_title = f"Import - {self.imported_mode.removeprefix('Merge (')}"
            self.progress_title = self.progress_title.removesuffix(")")
            if self.answer is None and self.answers:
                self.answer = ERRORS if self.errors else DONE
            elif self.answer is not None:
                if self.answer == DONE:
                    found.append(Window(DONE, "#32770", "Import Database", MAIN, True))
                else:
                    found.append(Window(ERRORS, "TfrmErrorList", "Import Error List", MAIN, True))
        found.append(Window(950, "tooltips_class32", "", 0, True))  # Let be
        return found

    def controls(self, hwnd: int) -> list[Control]:
        if hwnd == OPEN:
            found = [Control(h, OPEN, "TRadioButton", text, 0) for h, text in self.radios.items()]
            if self.has_file_name:
                found += [
                    Control(COMBO, OPEN, "ComboBox", "", 1148),
                    Control(EDIT, COMBO, "Edit", "", 1148),
                ]
            return [
                *found,
                Control(OPEN_BUTTON, OPEN, "Button", self.button_texts[OPEN_BUTTON], 1),
                Control(CANCEL, OPEN, "Button", self.button_texts[CANCEL], 2),
            ]
        if hwnd == DONE:
            return [
                Control(DONE_TEXT, DONE, "Static", self.answer_text, 0xFFFF),
                Control(DONE_OK, DONE, "Button", self.button_texts[DONE_OK], 2),
            ]
        if hwnd == ERRORS:
            return [
                Control(ERRORS_MEMO, ERRORS, "TMemo", "", 0),
                Control(ERRORS_OK, ERRORS, "TButton", "Ok", 0),
            ]
        return []

    def idle(self, hwnd: int, timeout: float) -> bool:
        assert hwnd == MAIN
        return self.answers

    def post_command(self, hwnd: int, command_id: int) -> None:
        self.commands.append((hwnd, command_id))
        if self.opens_dialog:
            self.open_shown = True
            if self.click_takes_foreground:
                self.foreground_window = OPEN

    def press(self, hwnd: int) -> None:
        self.pressed.append(hwnd)
        if hwnd in MODES and self.radio_sticks:
            self.checked = hwnd
        elif hwnd == OPEN_BUTTON:
            path = Path(self.edit_text)
            self.imported.append(path.read_bytes())
            self.imported_path = path
            self.imported_mode = MODES[self.checked]
            if self.holds_file:
                self.held = path.open("rb")
            self.open_shown = False
            self.progress_title = "frmProgress"
        elif hwnd == CANCEL:
            self.open_shown = False
        elif hwnd == DONE_OK:
            self.progress_title = None
            self.answer = None

    def button_checked(self, hwnd: int) -> int | None:
        return 1 if hwnd == self.checked else 0

    def read_text(self, hwnd: int) -> str | None:
        if hwnd == ERRORS_MEMO:
            return "Line 2 : X1,BIT\r\nCause : bad row\r\n"
        assert hwnd == EDIT
        self.edit_reads += 1
        if self.edit_empties:
            self.edit_empties -= 1
            self.edit_text = ""
        return self.edit_text

    def set_text(self, hwnd: int, text: str) -> bool:
        assert hwnd == EDIT
        self.edit_text = text
        return True

    def foreground(self) -> int:
        return self.foreground_window

    def window_pid(self, hwnd: int) -> int:
        if hwnd in (OWN_WINDOW, OWN_POPUP):
            return OWN_PID
        return 0 if hwnd == 777 else PID  # 777: another program's window

    def last_active_popup(self, hwnd: int) -> int:
        return self.popups.get(hwnd, hwnd)

    def set_foreground(self, hwnd: int) -> None:
        self.foreground_set.append(hwnd)
        self.foreground_window = hwnd

    # -- the clock ----------------------------------------------------------------

    def clock(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.time += seconds


def _redraw(click: FakeClick, tmp_path: Path):
    return redraw_nicknames(
        click,
        PID,
        MAIN,
        own_pid=OWN_PID,
        clock=click.clock,
        sleep=click.sleep,
        temp_dir=tmp_path,
    )


def test_a_completed_import_of_the_header_alone_redraws(tmp_path) -> None:
    click = FakeClick()

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.commands == [(MAIN, IMPORT_NICKNAME)]
    assert click.imported == [HEADER]
    assert click.imported_mode == "Merge (Project priority)"
    assert click.imported_path is not None and click.imported_path.parent == tmp_path
    assert click.pressed == [OPEN_BUTTON, DONE_OK]
    assert list(tmp_path.iterdir()) == []  # The CSV is removed


def test_windows_own_strings_in_another_language_do_not_matter(tmp_path) -> None:
    click = FakeClick()
    click.open_title = "Öffnen"
    click.button_texts = {OPEN_BUTTON: "Ö&ffnen", CANCEL: "Abbrechen", DONE_OK: "OK "}

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.pressed == [OPEN_BUTTON, DONE_OK]


# -- The foreground ----------------------------------------------------------------------


def test_the_foreground_goes_back_to_clicknicks_last_active_popup(tmp_path) -> None:
    click = FakeClick()
    click.popups[OWN_WINDOW] = OWN_POPUP  # "Successfully synced" showed meanwhile

    _redraw(click, tmp_path)

    assert click.foreground_set == [OWN_POPUP]


def test_the_foreground_goes_back_to_clicknicks_window(tmp_path) -> None:
    click = FakeClick()

    _redraw(click, tmp_path)

    assert click.foreground_set == [OWN_WINDOW]


def test_the_foreground_stays_when_clicknick_did_not_have_it(tmp_path) -> None:
    click = FakeClick()
    click.foreground_window = 777

    _redraw(click, tmp_path)

    assert click.foreground_set == []


def test_the_foreground_stays_when_click_never_took_it(tmp_path) -> None:
    click = FakeClick()
    click.popups[OWN_WINDOW] = OWN_POPUP
    click.click_takes_foreground = False

    _redraw(click, tmp_path)

    assert click.foreground_set == []


def test_the_foreground_stays_when_the_user_moved_to_another_program(tmp_path) -> None:
    click = FakeClick()
    real_press = click.press

    def press(hwnd: int) -> None:
        real_press(hwnd)
        if hwnd == DONE_OK:
            click.foreground_window = 777

    click.press = press

    _redraw(click, tmp_path)

    assert click.foreground_set == []


# -- The import mode ---------------------------------------------------------------------


def test_project_priority_is_checked_when_it_is_not(tmp_path) -> None:
    click = FakeClick()
    click.checked = DELETE

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.pressed == [PROJECT, OPEN_BUTTON, DONE_OK]
    assert click.imported_mode == "Merge (Project priority)"


def test_a_radio_that_will_not_check_cancels_the_open_dialog(tmp_path) -> None:
    click = FakeClick()
    click.checked = DELETE
    click.radio_sticks = False

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert "Merge (Project priority) to be checked" in result.detail
    assert click.pressed == [PROJECT, CANCEL]
    assert click.imported == []
    assert list(tmp_path.iterdir()) == []


def test_a_mode_changed_while_the_path_is_set_is_never_imported(tmp_path) -> None:
    click = FakeClick()
    real_read = click.read_text

    def read_text(hwnd: int) -> str | None:
        text = real_read(hwnd)
        if hwnd == EDIT and click.edit_reads == 3:
            click.checked = DELETE  # The user clicks Delete Existing
        return text

    click.read_text = read_text

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "Merge (Project priority) is no longer checked in CLICK's Open dialog"
    assert click.imported == []
    assert click.pressed == [CANCEL]


def test_the_path_is_set_again_when_the_dialog_empties_it(tmp_path) -> None:
    click = FakeClick()
    click.edit_empties = 2

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.imported == [HEADER]


# -- CLICK busy --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setup", "detail"),
    [
        (
            lambda c: c.extra.append(Window(600, "#32770", "Out", MAIN, True)),
            'CLICK shows "Out"',
        ),
        (
            lambda c: c.extra.append(Window(600, "TfrmPicker", "", MAIN, True)),
            "CLICK shows TfrmPicker",
        ),
        (lambda c: setattr(c, "main_enabled", False), "CLICK's window is disabled"),
        (lambda c: setattr(c, "answers", False), "CLICK does not answer"),
    ],
    ids=["a dialog open", "an untitled window", "main window disabled", "not answering"],
)
def test_busy_click_is_left_alone(tmp_path, setup, detail) -> None:
    click = FakeClick()
    setup(click)

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.BUSY
    assert result.detail == detail
    assert click.commands == []
    assert click.pressed == []
    assert list(tmp_path.iterdir()) == []


# -- What is left for the user -----------------------------------------------------------


def test_an_error_list_is_left_for_the_user(tmp_path) -> None:
    click = FakeClick()
    click.errors = True

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "CLICK's import listed errors: Line 2 : X1,BIT"
    assert click.pressed == [OPEN_BUTTON]  # Not its Ok
    assert list(tmp_path.iterdir()) == []


def test_an_answer_other_than_completed_is_left_for_the_user(tmp_path) -> None:
    click = FakeClick()
    click.answer_text = "Some rows were not imported."

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert 'answered "Some rows were not imported."' in result.detail
    assert click.pressed == [OPEN_BUTTON]


def test_an_unexpected_box_instead_of_the_open_dialog_is_left_alone(tmp_path) -> None:
    click = FakeClick()
    click.opens_dialog = False

    def box_instead(hwnd: int, command_id: int) -> None:
        click.commands.append((hwnd, command_id))
        click.extra.append(Window(600, "#32770", "CLICK Programming Software", MAIN, True))

    click.post_command = box_instead

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "CLICK Programming Software"'
    assert click.pressed == []
    assert click.time < 2  # Told apart once DIALOG_GRACE has passed


def test_a_file_dialog_without_the_import_modes_is_never_cancelled(tmp_path) -> None:
    """The user's own File > Open, or another CLICK's import dialog, is left as it is."""
    click = FakeClick()
    click.radios = {PROJECT: "Merge (Project priority)", FILE: "Merge (File priority)"}

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "Open"'
    assert click.pressed == []
    assert click.imported == []


def test_the_import_dialog_without_its_file_name_box_is_cancelled(tmp_path) -> None:
    click = FakeClick()
    click.has_file_name = False

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "CLICK's Open dialog does not show the File name box"
    assert click.pressed == [CANCEL]


def test_a_dialog_that_loses_its_import_modes_is_not_cancelled(tmp_path) -> None:
    click = FakeClick()
    click.radio_sticks = False
    click.checked = DELETE
    real_press = click.press

    def press(hwnd: int) -> None:
        real_press(hwnd)
        if hwnd == PROJECT:
            click.radios = {}  # The import dialog went; another took its handle

    click.press = press

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert click.pressed == [PROJECT]


def test_a_box_over_the_open_dialog_leaves_both_for_the_user(tmp_path) -> None:
    click = FakeClick()
    real_press = click.press

    def press(hwnd: int) -> None:
        if hwnd == OPEN_BUTTON:  # "File not found", owned by the Open dialog
            click.pressed.append(hwnd)
            click.extra.append(Window(600, "#32770", "Open", OPEN, True))
            return
        real_press(hwnd)

    click.press = press

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "Open"'
    assert click.pressed == [OPEN_BUTTON]  # Not Cancel: the Open dialog is not alone


# -- Time-outs and failures --------------------------------------------------------------


def test_no_open_dialog_times_out(tmp_path) -> None:
    click = FakeClick()
    click.opens_dialog = False

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "timed out after 10 s waiting for CLICK's Open dialog"
    assert click.pressed == []
    assert list(tmp_path.iterdir()) == []


def test_no_answer_times_out_and_leaves_the_progress_window(tmp_path) -> None:
    click = FakeClick()
    real_press = click.press

    def press(hwnd: int) -> None:
        real_press(hwnd)
        if hwnd == OPEN_BUTTON:
            click.answers = False  # CLICK is stuck importing

    click.press = press

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "timed out after 20 s waiting for CLICK's answer"
    assert click.pressed == [OPEN_BUTTON]
    assert click.time < 60


def test_a_csv_click_still_holds_is_removed_by_the_next_redraw(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(click_redraw, "_leftovers", set())
    click = FakeClick()
    click.holds_file = True
    real_press = click.press

    def press(hwnd: int) -> None:
        real_press(hwnd)
        if hwnd == OPEN_BUTTON:
            click.answers = False

    click.press = press

    assert _redraw(click, tmp_path).outcome is RedrawOutcome.FAILED
    assert click.imported_path is not None and click.imported_path.exists()

    click.held.close()  # CLICK lets the file go
    later = FakeClick()
    later.extra.append(Window(600, "TfrmProgress", "Import - Project priority", MAIN, True))
    assert _redraw(later, tmp_path).outcome is RedrawOutcome.BUSY

    assert list(tmp_path.iterdir()) == []


def test_click_closing_during_the_import_fails(tmp_path) -> None:
    click = FakeClick()
    real_windows = click.windows

    def windows(pid: int) -> list[Window]:
        shown = real_windows(pid)
        return [w for w in shown if w.hwnd != MAIN] if click.open_shown else shown

    click.windows = windows

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "CLICK's window closed"
    assert click.pressed == []


def test_a_win32_call_failing_part_way_cancels_the_open_dialog(tmp_path) -> None:
    click = FakeClick()

    def set_text(hwnd: int, text: str) -> bool:
        raise OSError("access denied")

    click.set_text = set_text

    result = _redraw(click, tmp_path)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "access denied"
    assert click.pressed == [CANCEL]
    assert list(tmp_path.iterdir()) == []
