"""Make CLICK redraw its nicknames from SC_.mdb (issue #36).

CLICK's ladder paints nicknames from a table in CLICK's memory. After a Sync writes SC_.mdb,
CLICK still shows the old names, and no window message reloads that table.

CLICK reloads the table from SC_.mdb each time its File > Import > Nickname dialog closes,
after Cancel too. So ``redraw_nicknames`` posts that command to the connected CLICK window
and presses Cancel in the Open dialog. Nothing is imported, and SC_.mdb stays as it was.
CLICK then counts the project as changed. A live check on CLICK 2.60, 3.43, 3.71, 3.92 and
4.00 (2026-11-18) found this with CLICK active, with another program active and with CLICK
minimized. CLICK showed no other window, and the foreground window did not change.

The redraw drives CLICK through a ``ClickDesktop`` (``utils/win32_desktop.py`` on Windows, a
fake in tests). It starts only while CLICK shows its main window alone. So any window that
CLICK shows afterwards comes from the command. The redraw presses only Cancel in the Open
dialog, and it leaves any other window to the user.

Windows' own strings ("Open", "Cancel") differ by language. So the redraw recognises the dialog by
CLICK's three import modes and by control ids. It blocks for up to about 20 seconds. Run
it off the Tk thread.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..models.desktop import Control, Window

logger = logging.getLogger(__name__)

# File > Import > Nickname: the same WM_COMMAND id in CLICK 2.60, 3.43, 3.71, 3.92 and 4.00
IMPORT_NICKNAME = 32900
# The radio buttons in the import's Open dialog. They are CLICK's own strings.
IMPORT_MODES = frozenset({"Merge (Project priority)", "Merge (File priority)", "Delete Existing"})
DIALOG_CLASS = "#32770"
TOOLTIP_CLASS = "tooltips_class32"
# A file dialog's File name edit: the Edit 1148 inside the ComboBox 1148
FILE_NAME_ID = 1148
OPEN_ID = 1  # IDOK
CANCEL_ID = 2  # IDCANCEL

# Seconds. Every wait is bounded, so a CLICK that does not answer ends the redraw.
IDLE_TIMEOUT = 1.0
# A dialog that does not show the import modes yet may be the import's Open dialog, still
# being built, until this many seconds after the command
OPEN_TIMEOUT = 10.0
CLOSE_TIMEOUT = 10.0
POLL = 0.05


class ClickDesktop(Protocol):
    """The Win32 calls that a redraw makes. Every message is posted or sent with a timeout."""

    def windows(self, pid: int) -> list[Window]:
        """Return the visible top-level windows of process *pid*."""
        ...

    def controls(self, hwnd: int) -> list[Control]:
        """Return the child windows of *hwnd*, at any depth."""
        ...

    def idle(self, hwnd: int, timeout: float) -> bool:
        """Return True if *hwnd*'s thread answers a message within *timeout* seconds."""
        ...

    def post_command(self, hwnd: int, command_id: int) -> None:
        """Post WM_COMMAND *command_id* to *hwnd*."""
        ...

    def press(self, hwnd: int) -> None:
        """Post BM_CLICK to the button *hwnd*."""
        ...


class RedrawOutcome(Enum):
    REFRESHED = "refreshed"
    # CLICK showed a dialog or did not answer: nothing was sent to it
    BUSY = "busy"
    FAILED = "failed"


@dataclass(frozen=True)
class RedrawResult:
    outcome: RedrawOutcome
    # What CLICK showed, or why it failed; "" when refreshed
    detail: str = ""


class _Stop(Exception):  # noqa: N818 - control flow, not an error
    """Raised to end the redraw with *result*."""

    def __init__(self, result: RedrawResult) -> None:
        super().__init__(result.detail)
        self.result = result


def _failed(detail: str) -> _Stop:
    return _Stop(RedrawResult(RedrawOutcome.FAILED, detail))


def _describe(window: Window) -> str:
    """Return how a status line names *window*: its title, else its class."""
    return f'"{window.title}"' if window.title else window.cls


def _others(windows: list[Window], main: int) -> list[Window]:
    """Return *windows* without the main window and tooltips."""
    return [w for w in windows if w.hwnd != main and w.cls != TOOLTIP_CLASS]


def _shows_import_modes(controls: list[Control]) -> bool:
    return {c.text for c in controls if c.cls == "TRadioButton"} == IMPORT_MODES


def redraw_nicknames(
    desktop: ClickDesktop,
    pid: int,
    main: int,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RedrawResult:
    """Make CLICK's window *main* (process *pid*) redraw every nickname from SC_.mdb.

    Post File > Import > Nickname, wait for its Open dialog and press Cancel in it. Return
    REFRESHED once the dialog has closed.

    Return BUSY if CLICK's main window is disabled, does not answer or shows another
    window. A BUSY redraw sends no command to CLICK.

    Return FAILED if CLICK shows a window other than the Open dialog, if the Open dialog
    lacks one of its controls, or if CLICK does not answer in time. If the Open dialog is
    then the only window open besides the main window, press its Cancel. Leave any other
    window to the user.

    The redraw never sets the foreground window.
    """
    refused = _refusal(desktop, pid, main)
    if refused is not None:
        return refused
    return _CancelledImport(desktop, pid, main, clock, sleep).run()


def _refusal(desktop: ClickDesktop, pid: int, main: int) -> RedrawResult | None:
    """Return why the redraw cannot start now, or None if CLICK shows its main window alone.

    The main window must also be enabled and answer messages.
    """
    windows = desktop.windows(pid)
    if not any(w.hwnd == main for w in windows):
        return RedrawResult(RedrawOutcome.FAILED, "CLICK's window is closed or hidden")
    others = _others(windows, main)
    if others:
        shown = ", ".join(_describe(w) for w in others)
        return RedrawResult(RedrawOutcome.BUSY, f"CLICK shows {shown}")
    if not next(w for w in windows if w.hwnd == main).enabled:
        return RedrawResult(RedrawOutcome.BUSY, "CLICK's window is disabled")
    if not desktop.idle(main, IDLE_TIMEOUT):
        return RedrawResult(RedrawOutcome.BUSY, "CLICK does not answer")
    return None


class _CancelledImport:
    """One File > Import > Nickname, cancelled in its Open dialog."""

    def __init__(
        self,
        desktop: ClickDesktop,
        pid: int,
        main: int,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.desktop = desktop
        self.pid = pid
        self.main = main
        self.clock = clock
        self.sleep = sleep
        # The import's Open dialog, once a dialog showed the import modes
        self.dialog: int | None = None

    def run(self) -> RedrawResult:
        try:
            return self._run()
        except _Stop as stop:
            self._cancel_lone_dialog()
            return stop.result
        except Exception as exc:  # A Win32 call failed part way
            logger.exception("CLICK's nickname redraw failed")
            self._cancel_lone_dialog()
            return RedrawResult(RedrawOutcome.FAILED, str(exc) or type(exc).__name__)

    def _run(self) -> RedrawResult:
        self.desktop.post_command(self.main, IMPORT_NICKNAME)
        dialog = self._wait("CLICK's Open dialog", {"dialog", "opening"}, self._lone, OPEN_TIMEOUT)
        try:
            cancel = self._cancel_button(self.desktop.controls(dialog.hwnd))
        except _Stop:
            if self._is_shown(dialog.hwnd):
                raise
            # The user closed the Open dialog first. CLICK reloads the table all the same.
            cancel = None
        if cancel is not None:
            self.desktop.press(cancel.hwnd)
        self._wait(
            "CLICK's Open dialog to close", {"dialog"}, lambda found: not found, CLOSE_TIMEOUT
        )
        return RedrawResult(RedrawOutcome.REFRESHED)

    def _is_shown(self, hwnd: int) -> bool:
        """Return True if CLICK still shows the window *hwnd*."""
        return any(w.hwnd == hwnd for w in self.desktop.windows(self.pid))

    def _lone(self, found: list[Window]) -> Window | None:
        """Return the Open dialog once it is enabled, or None before that.

        Raise ``_Stop`` if CLICK shows another window beside the Open dialog. Cancel is
        pressed only while the Open dialog is the only window besides the main one.
        """
        if self.dialog is None:
            return None
        others = [w for w in found if w.hwnd != self.dialog]
        if others:
            raise _failed(f"CLICK showed {', '.join(_describe(w) for w in others)}")
        return next((w for w in found if w.enabled), None)

    def _kind(self, window: Window) -> str | None:
        """Return which of the import's windows *window* is, or None if it is none of them.

        "dialog" is the import's Open dialog: the first dialog that shows the three import
        modes. "opening" is any other dialog that appears before the Open dialog is found.
        It may be the Open dialog still being built.
        """
        if window.hwnd == self.dialog:
            return "dialog"
        if window.cls == DIALOG_CLASS and self.dialog is None:
            if _shows_import_modes(self.desktop.controls(window.hwnd)):
                self.dialog = window.hwnd
                return "dialog"
            return "opening"
        return None

    @staticmethod
    def _cancel_button(controls: list[Control]) -> Control:
        """Return the Open dialog's Cancel button.

        Raise ``_Stop`` unless the dialog shows the import modes, the File name box, Open
        and Cancel.
        """
        boxes = {c.hwnd for c in controls if c.cls == "ComboBox" and c.id == FILE_NAME_ID}
        file_name = any(
            c.cls == "Edit" and c.id == FILE_NAME_ID and c.parent in boxes for c in controls
        )
        open_button = any(c.cls == "Button" and c.id == OPEN_ID for c in controls)
        cancel = next((c for c in controls if c.cls == "Button" and c.id == CANCEL_ID), None)
        missing = []
        if not _shows_import_modes(controls):
            missing.append("the import modes")
        if not file_name:
            missing.append("the File name box")
        if not open_button:
            missing.append("the Open button")
        if cancel is None:
            missing.append("the Cancel button")
        if missing:
            raise _failed(f"CLICK's Open dialog does not show {' or '.join(missing)}")
        assert cancel is not None
        return cancel

    def _wait[T](
        self,
        what: str,
        expected: set[str],
        until: Callable[[list[Window]], T | None | bool],
        timeout: float,
    ) -> T:
        """Poll CLICK's windows until *until* returns something other than None or False.

        *until* is given the windows except the main window and tooltips. The redraw ends as
        FAILED if a window of none of the *expected* kinds (``_kind``) appears, if CLICK's
        main window closes, or if *timeout* seconds pass. If a dialog that never showed the
        import modes is still open at the time-out, the failure names that dialog.
        """
        deadline = self.clock() + timeout
        while True:
            windows = self.desktop.windows(self.pid)
            if not any(w.hwnd == self.main for w in windows):
                raise _failed("CLICK's window closed")
            found = _others(windows, self.main)
            unexpected = [w for w in found if self._kind(w) not in expected]
            if unexpected:
                shown = ", ".join(_describe(w) for w in unexpected)
                raise _failed(f"CLICK showed {shown}")
            value = until(found)
            if value is not None and value is not False:
                return value  # pyright: ignore[reportReturnType]
            if self.clock() >= deadline:
                opening = [w for w in found if self._kind(w) == "opening"]
                if opening:
                    raise _failed(f"CLICK showed {', '.join(_describe(w) for w in opening)}")
                raise _failed(f"timed out after {timeout:g} s waiting for {what}")
            self.sleep(POLL)

    def _cancel_lone_dialog(self) -> None:
        """Press Cancel in the import's Open dialog if it is the only window besides the main one.

        The dialog must also still show the import modes.
        """
        if self.dialog is None:
            return
        try:
            windows = self.desktop.windows(self.pid)
            if not any(w.hwnd == self.main for w in windows):
                return
            found = _others(windows, self.main)
            if len(found) != 1 or found[0].hwnd != self.dialog or not found[0].enabled:
                return
            controls = self.desktop.controls(self.dialog)
            if not _shows_import_modes(controls):
                return
            cancel = next((c for c in controls if c.cls == "Button" and c.id == CANCEL_ID), None)
            if cancel is not None:
                self.desktop.press(cancel.hwnd)
        except Exception:
            logger.exception("Could not cancel CLICK's Open dialog")
