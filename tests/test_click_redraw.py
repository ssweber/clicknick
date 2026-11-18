"""The CLICK nickname redraw (issue #36) against a fake desktop.

The fake follows what CLICK 2.60, 3.43, 3.71, 3.92 and 4.00 showed for File > Import >
Nickname in a live check (2026-11-18). CLICK shows an Open dialog with three import modes,
the File name edit (1148 in ComboBox 1148), Open (1) and Cancel (2). A BM_CLICK on Cancel
closes the dialog, and CLICK shows no other window.
"""

from __future__ import annotations

import pytest

from clicknick.models.desktop import Control, Window
from clicknick.services import click_redraw
from clicknick.services.click_redraw import (
    IMPORT_NICKNAME,
    RedrawOutcome,
    redraw_nicknames,
)

PID = 7
MAIN = 100

OPEN = 200
PROJECT, FILE, DELETE = 201, 202, 203
COMBO, EDIT = 210, 211
OPEN_BUTTON, CANCEL = 220, 221
MODES = {
    PROJECT: "Merge (Project priority)",
    FILE: "Merge (File priority)",
    DELETE: "Delete Existing",
}


class FakeClick:
    """CLICK's import command, as the desktop shows it to the redraw."""

    def __init__(self) -> None:
        self.time = 0.0
        self.main_enabled = True
        self.answers = True
        self.extra: list[Window] = []  # Windows CLICK shows besides the import's
        self.open_shown = False
        self.opens_dialog = True
        self.open_title = "Open"
        self.button_texts = {OPEN_BUTTON: "&Open", CANCEL: "Cancel"}
        self.radios = dict(MODES)
        self.has_file_name = True
        self.cancel_closes = True
        self.commands: list[tuple[int, int]] = []
        self.pressed: list[int] = []

    # -- what the fake shows ----------------------------------------------------

    def windows(self, pid: int) -> list[Window]:
        assert pid == PID
        found = [Window(MAIN, "Afx:main", "CLICK Programming Software", self.main_enabled)]
        found += self.extra
        if self.open_shown:
            found.append(Window(OPEN, "#32770", self.open_title, True))
        found.append(Window(950, "tooltips_class32", "", True))  # Let be
        return found

    def controls(self, hwnd: int) -> list[Control]:
        if hwnd != OPEN:
            return []
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

    def idle(self, hwnd: int, timeout: float) -> bool:
        assert hwnd == MAIN
        return self.answers

    def post_command(self, hwnd: int, command_id: int) -> None:
        self.commands.append((hwnd, command_id))
        if self.opens_dialog:
            self.open_shown = True

    def press(self, hwnd: int) -> None:
        self.pressed.append(hwnd)
        if hwnd == CANCEL and self.cancel_closes:
            self.open_shown = False

    # -- the clock ----------------------------------------------------------------

    def clock(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.time += seconds


def _redraw(click: FakeClick):
    return redraw_nicknames(click, PID, MAIN, clock=click.clock, sleep=click.sleep)


def test_cancel_in_the_open_dialog_redraws() -> None:
    click = FakeClick()

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.commands == [(MAIN, IMPORT_NICKNAME)]
    assert click.pressed == [CANCEL]  # Nothing else: no mode, no file name, no Open
    assert not click.open_shown


def test_windows_own_strings_in_another_language_do_not_matter() -> None:
    click = FakeClick()
    click.open_title = "Öffnen"
    click.button_texts = {OPEN_BUTTON: "Ö&ffnen", CANCEL: "Abbrechen"}

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.pressed == [CANCEL]


def test_an_open_dialog_that_shows_after_a_moment_is_waited_for() -> None:
    """Live, the dialog showed 0.15 to 0.26 s after the command."""
    click = FakeClick()
    click.opens_dialog = False
    real_windows = click.windows

    def windows(pid: int) -> list[Window]:
        if click.commands and click.time >= 0.25:
            click.open_shown = click.open_shown or not click.pressed
        return real_windows(pid)

    click.windows = windows

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.time >= 0.25
    assert click.pressed == [CANCEL]


def test_import_modes_that_show_seconds_after_the_command_are_waited_for() -> None:
    """Until OPEN_TIMEOUT passes, a dialog without the modes may be the Open dialog being built."""
    click = FakeClick()
    real_controls = click.controls

    def controls(hwnd: int) -> list[Control]:
        found = real_controls(hwnd)
        if hwnd == OPEN and click.time < 3.0:
            return [c for c in found if c.hwnd not in MODES]
        return found

    click.controls = controls

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.time >= 3.0
    assert click.pressed == [CANCEL]


# -- CLICK busy --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setup", "detail"),
    [
        (
            lambda c: c.extra.append(Window(600, "#32770", "Out", True)),
            'CLICK shows "Out"',
        ),
        (
            lambda c: c.extra.append(Window(600, "TfrmPicker", "", True)),
            "CLICK shows TfrmPicker",
        ),
        (lambda c: setattr(c, "main_enabled", False), "CLICK's window is disabled"),
        (lambda c: setattr(c, "answers", False), "CLICK does not answer"),
    ],
    ids=["a dialog open", "an untitled window", "main window disabled", "not answering"],
)
def test_busy_click_is_left_alone(setup, detail) -> None:
    click = FakeClick()
    setup(click)

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.BUSY
    assert result.detail == detail
    assert click.commands == []
    assert click.pressed == []


def test_a_closed_click_window_fails_before_the_command() -> None:
    click = FakeClick()
    click.windows = lambda _pid: []

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "CLICK's window is closed or hidden"
    assert click.commands == []


# -- What is left for the user -----------------------------------------------------------


def test_an_unexpected_box_instead_of_the_open_dialog_is_left_alone() -> None:
    click = FakeClick()
    click.opens_dialog = False

    def box_instead(hwnd: int, command_id: int) -> None:
        click.commands.append((hwnd, command_id))
        click.extra.append(Window(600, "#32770", "CLICK Programming Software", True))

    click.post_command = box_instead

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "CLICK Programming Software"'
    assert click.pressed == []
    # A dialog may still be the Open dialog being built until OPEN_TIMEOUT
    assert click.time < click_redraw.OPEN_TIMEOUT + 1


def test_a_window_of_no_known_kind_fails_the_redraw_at_once() -> None:
    click = FakeClick()
    real_post = click.post_command

    def warning_too(hwnd: int, command_id: int) -> None:
        real_post(hwnd, command_id)
        click.extra.append(Window(600, "TMessageForm", "Warning", True))

    click.post_command = warning_too

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "Warning"'
    assert click.pressed == []
    assert click.time < 1


def test_a_file_dialog_without_the_import_modes_is_never_cancelled() -> None:
    """A dialog that shows only two of the import modes is never cancelled."""
    click = FakeClick()
    click.radios = {PROJECT: "Merge (Project priority)", FILE: "Merge (File priority)"}

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "Open"'
    assert click.pressed == []


def test_the_import_dialog_without_its_file_name_box_is_cancelled_and_fails() -> None:
    click = FakeClick()
    click.has_file_name = False

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "CLICK's Open dialog does not show the File name box"
    assert click.pressed == [CANCEL]


def test_a_dialog_that_loses_its_import_modes_is_not_cancelled() -> None:
    click = FakeClick()
    click.has_file_name = False
    real_controls = click.controls
    looks: list[int] = []

    def controls(hwnd: int) -> list[Control]:
        looks.append(hwnd)
        if len(looks) > 2:  # The import dialog went, and another took its handle
            click.radios = {}
        return real_controls(hwnd)

    click.controls = controls

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert click.pressed == []


def test_an_open_dialog_that_the_user_closes_first_still_redraws() -> None:
    """CLICK reloads its nicknames when the dialog closes, whoever closes it."""
    click = FakeClick()
    real_controls = click.controls
    looks: list[int] = []

    def controls(hwnd: int) -> list[Control]:
        looks.append(hwnd)
        if len(looks) > 1:  # The user closed the dialog after the redraw found it
            click.open_shown = False
            return []
        return real_controls(hwnd)

    click.controls = controls

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.REFRESHED
    assert click.pressed == []


def test_a_second_dialog_beside_the_open_dialog_leaves_both_for_the_user() -> None:
    click = FakeClick()
    real_post = click.post_command

    def two_dialogs(hwnd: int, command_id: int) -> None:
        real_post(hwnd, command_id)
        click.extra.append(Window(600, "#32770", "Open", True))

    click.post_command = two_dialogs

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "Open"'
    assert click.pressed == []  # Not Cancel: the Open dialog is not alone


def test_a_window_after_cancel_is_left_for_the_user() -> None:
    """Live, CLICK showed nothing after Cancel. "Completed!" belongs to an import that ran."""
    click = FakeClick()
    real_press = click.press

    def press(hwnd: int) -> None:
        real_press(hwnd)
        click.extra.append(Window(400, "#32770", "Import Database", True))

    click.press = press

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == 'CLICK showed "Import Database"'
    assert click.pressed == [CANCEL]


# -- Time-outs and failures --------------------------------------------------------------


def test_no_open_dialog_times_out() -> None:
    click = FakeClick()
    click.opens_dialog = False

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "timed out after 10 s waiting for CLICK's Open dialog"
    assert click.pressed == []


def test_an_open_dialog_that_stays_after_cancel_times_out() -> None:
    click = FakeClick()
    click.cancel_closes = False

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "timed out after 10 s waiting for CLICK's Open dialog to close"
    assert click.pressed == [CANCEL, CANCEL]  # Cancel once more, as after any failure
    assert click.time < 30


def test_click_closing_during_the_import_fails() -> None:
    click = FakeClick()
    real_windows = click.windows

    def windows(pid: int) -> list[Window]:
        shown = real_windows(pid)
        return [w for w in shown if w.hwnd != MAIN] if click.open_shown else shown

    click.windows = windows

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "CLICK's window closed"
    assert click.pressed == []


def test_a_win32_call_failing_part_way_cancels_the_open_dialog() -> None:
    click = FakeClick()
    real_press = click.press
    failures = [OSError("access denied")]

    def press(hwnd: int) -> None:
        if failures:
            raise failures.pop()
        real_press(hwnd)

    click.press = press

    result = _redraw(click)

    assert result.outcome is RedrawOutcome.FAILED
    assert result.detail == "access denied"
    assert click.pressed == [CANCEL]
    assert not click.open_shown
