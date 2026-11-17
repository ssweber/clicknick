"""Make CLICK redraw its nicknames from SC_.mdb (issue #36).

CLICK's ladder paints nicknames from a table that TagDB.dll keeps in memory. After a
Sync writes SC_.mdb, CLICK still shows the old names, and no window message reloads that
table.

File > Import > Nickname does reload it (live runs on CLICK v4.00, 2026-11-17). Import a
CSV that holds only the header line, in Merge (Project priority), which is the dialog's
default. CLICK answers "Completed!", leaves SC_.mdb as it was and redraws every nickname
from it. CLICK then counts the project as changed, as it does after an edit in its
Address Picker.

``redraw_nicknames`` drives that import on the connected CLICK window through a
``ClickDesktop`` (``utils/win32_desktop.py`` on Windows, a fake in tests). It starts only
while CLICK shows its main window alone. It presses only the import mode's radio button,
Open and the button of the "Completed!" box, and it leaves any other window to the user.

CLICK's import makes the active window the owner of its Open dialog. When another program
is active, the dialog has no owner (live run on CLICK v4.00, 2026-11-17). So when
ClickNick is active, the redraw makes CLICK active first. It also tells the import's
windows apart by class and title, never by owner. Before the command, CLICK showed its main
window alone. So any window that CLICK shows afterwards comes from the import.

Windows' own strings ("Open", "OK", "Cancel") differ by language. So it tells the file
dialog and its buttons apart by structure and control ids, and it reads only CLICK's own
strings as text. It blocks for seconds, so run it off the Tk thread.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from ..models.desktop import Control, Window

logger = logging.getLogger(__name__)

# File > Import > Nickname: the same WM_COMMAND id in CLICK 2.60, 3.43, 3.71, 3.92 and 4.00
IMPORT_NICKNAME = 32900
# CLICK's nickname CSV header, byte for byte. A file of this line alone imports no row.
HEADER = b"Address,Data Type,Nickname,Initial Value,Retentive,Address Comment\r\n"
PROJECT_PRIORITY = "Merge (Project priority)"
IMPORT_MODES = frozenset({PROJECT_PRIORITY, "Merge (File priority)", "Delete Existing"})
COMPLETED = "Completed!"
# The progress window is titled by its Delphi form's name at first, and then by the mode.
PROGRESS_TITLES = frozenset({"frmProgress", "Import - Project priority"})
DIALOG_CLASS = "#32770"
TOOLTIP_CLASS = "tooltips_class32"
# A file dialog's File name edit: the Edit 1148 inside the ComboBox 1148
FILE_NAME_ID = 1148
OPEN_ID = 1  # IDOK
CANCEL_ID = 2  # IDCANCEL
BM_CHECKED = 1

# Seconds. Every wait is bounded, so a CLICK that does not answer ends the redraw.
IDLE_TIMEOUT = 1.0
# How long a window may take to become the foreground window after set_foreground
ACTIVATE_TIMEOUT = 1.0
# A dialog that does not show the import modes yet may be the import's Open dialog, still
# being built, until this many seconds after the command
OPEN_TIMEOUT = 10.0
FILL_TIMEOUT = 5.0
# A file dialog that is still opening can empty its File name edit after it was set
# (devtools/click_runner.py, fill_path). The path must read back for this many seconds.
FILL_SETTLE = 1.0
ANSWER_TIMEOUT = 20.0
CLOSE_TIMEOUT = 10.0
POLL = 0.1


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

    def button_checked(self, hwnd: int) -> int | None:
        """Send BM_GETCHECK to *hwnd* and return the answer, or None if it did not answer."""
        ...

    def read_text(self, hwnd: int) -> str | None:
        """Send WM_GETTEXT to *hwnd* and return the text, or None if it did not answer."""
        ...

    def set_text(self, hwnd: int, text: str) -> bool:
        """Send WM_SETTEXT with *text* to *hwnd*. Return False if it did not answer."""
        ...

    def foreground(self) -> int:
        """Return the foreground window, or 0 if there is none."""
        ...

    def window_pid(self, hwnd: int) -> int:
        """Return the process that owns *hwnd*, or 0 if the window is gone."""
        ...

    def last_active_popup(self, hwnd: int) -> int:
        """Call GetLastActivePopup on *hwnd*: its owned window that was active last, else *hwnd*."""
        ...

    def set_foreground(self, hwnd: int) -> None:
        """Bring *hwnd* to the foreground, if Windows lets it."""
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


# CSVs that a redraw could not remove because CLICK still had one open.
# The next redraw removes them.
_leftovers: set[Path] = set()
_leftovers_lock = threading.Lock()


def _remove(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _remove_leftovers() -> None:
    with _leftovers_lock:
        for path in list(_leftovers):
            if _remove(path):
                _leftovers.discard(path)


def redraw_nicknames(
    desktop: ClickDesktop,
    pid: int,
    main: int,
    *,
    own_pid: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    temp_dir: Path | None = None,
) -> RedrawResult:
    """Make CLICK's window *main* (process *pid*) redraw every nickname from SC_.mdb.

    Import a header-only CSV with File > Import > Nickname in Merge (Project priority).

    Return BUSY, with nothing sent, if CLICK's main window is disabled, does not answer or
    shows another window.

    Return FAILED if the import shows a window that it is not known to show, or does not
    answer in time. If the import's Open dialog is then the only window open, cancel it.
    Leave any other window to the user.

    Write the CSV into *temp_dir* (the temp folder by default) and remove it afterwards. If
    CLICK still holds it, the next redraw removes it.

    If one of *own_pid*'s windows (this process by default) has the foreground at the start,
    give the foreground to CLICK's main window before the import. Windows lets only the
    foreground process do that. If CLICK has the foreground at the end, return it to that
    window's last active popup. A message box that ClickNick showed in the meantime gets the
    foreground.
    """
    own = os.getpid() if own_pid is None else own_pid
    foreground = desktop.foreground()
    ours = foreground if foreground and desktop.window_pid(foreground) == own else 0
    _remove_leftovers()
    try:
        return _redraw(desktop, pid, main, bool(ours), clock, sleep, temp_dir)
    finally:
        now = desktop.foreground()
        if ours and now and desktop.window_pid(now) == pid:
            target = desktop.last_active_popup(ours) or ours
            if desktop.window_pid(target) == own:
                _activate(desktop, target, clock, sleep)


def _redraw(
    desktop: ClickDesktop,
    pid: int,
    main: int,
    activate: bool,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    temp_dir: Path | None,
) -> RedrawResult:
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
    if activate:
        _activate(desktop, main, clock, sleep)

    handle, name = tempfile.mkstemp(prefix="clicknick-redraw-", suffix=".csv", dir=temp_dir)
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(HEADER)
        return _Import(desktop, pid, main, path, clock, sleep).run()
    finally:
        if not _remove(path):
            logger.warning("Could not remove %s yet. The next redraw will try again.", path)
            with _leftovers_lock:
                _leftovers.add(path)


def _activate(
    desktop: ClickDesktop,
    hwnd: int,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> None:
    """Give the foreground to *hwnd* and wait until it has it.

    If Windows refuses, return after ACTIVATE_TIMEOUT. The redraw goes on anyway.
    Windows switches the foreground some time after the call returns. A window that
    ClickNick closes before the switch can hand the foreground back to CLICK. So the
    redraw ends only after the switch.
    """
    desktop.set_foreground(hwnd)
    deadline = clock() + ACTIVATE_TIMEOUT
    while desktop.foreground() != hwnd:
        if clock() >= deadline:
            logger.info("Window %#x did not become the foreground window", hwnd)
            return
        sleep(POLL)


class _Import:
    """One File > Import > Nickname of a header-only CSV."""

    def __init__(
        self,
        desktop: ClickDesktop,
        pid: int,
        main: int,
        path: Path,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.desktop = desktop
        self.pid = pid
        self.main = main
        self.path = path
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
        dialog = self._wait(
            "CLICK's Open dialog",
            {"dialog", "opening"},
            lambda found: next((w for w in found if w.hwnd == self.dialog and w.enabled), None),
            OPEN_TIMEOUT,
        )
        mode, file_name, open_button = self._open_controls(self.desktop.controls(dialog.hwnd))

        if self.desktop.button_checked(mode.hwnd) != BM_CHECKED:
            self.desktop.press(mode.hwnd)
            self._wait(
                f"{PROJECT_PRIORITY} to be checked",
                {"dialog"},
                lambda _found: self.desktop.button_checked(mode.hwnd) == BM_CHECKED,
                FILL_TIMEOUT,
            )
        self._fill(file_name)
        # Check last, right before Open, because the user could click another mode meanwhile
        if self.desktop.read_text(file_name.hwnd) != str(self.path):
            raise _failed("CLICK's Open dialog lost the file name")
        if self.desktop.button_checked(mode.hwnd) != BM_CHECKED:
            raise _failed(f"{PROJECT_PRIORITY} is no longer checked in CLICK's Open dialog")
        self.desktop.press(open_button.hwnd)

        box, errors = self._wait(
            "CLICK's answer", {"dialog", "progress", "done", "errors"}, self._answer, ANSWER_TIMEOUT
        )
        if errors:
            memos = [c for c in self.desktop.controls(box.hwnd) if c.cls == "TMemo"]
            text = self.desktop.read_text(memos[0].hwnd) if len(memos) == 1 else None
            first = (text or "").strip().splitlines()
            listed = f": {first[0]}" if first else ""
            raise _failed(f"CLICK's import listed errors{listed}")
        controls = self.desktop.controls(box.hwnd)
        texts = [c.text for c in controls if c.cls == "Static" and c.text]
        buttons = [c for c in controls if c.cls == "Button"]
        if texts != [COMPLETED] or len(buttons) != 1:
            said = " ".join(texts) or "nothing"
            raise _failed(f'CLICK\'s import answered "{said}"')
        self.desktop.press(buttons[0].hwnd)

        def closed(found: list[Window]) -> bool:
            again = [w for w in found if self._kind(w) == "done" and w.hwnd != box.hwnd]
            if again:
                raise _failed(f"CLICK answered again: {_describe(again[0])}")
            return not found

        self._wait("the import to close", {"progress", "done"}, closed, CLOSE_TIMEOUT)
        return RedrawResult(RedrawOutcome.REFRESHED)

    def _kind(self, window: Window) -> str | None:
        """Return which of the import's windows *window* is, or None if it is none of them.

        The window's owner does not count. CLICK's main window owns the import's windows
        only when CLICK was active at the command.

        "dialog" is the import's Open dialog: the first dialog that shows the three import
        modes. "opening" is any other dialog that appears before the Open dialog is found.
        It may be the Open dialog still being built.
        """
        if window.hwnd == self.dialog:
            return "dialog"
        if window.cls == "TfrmProgress" and window.title in PROGRESS_TITLES:
            return "progress"
        if window.cls == DIALOG_CLASS and window.title == "Import Database":
            return "done"
        if window.cls == "TfrmErrorList" and window.title == "Import Error List":
            return "errors"
        if window.cls == DIALOG_CLASS and self.dialog is None:
            if _shows_import_modes(self.desktop.controls(window.hwnd)):
                self.dialog = window.hwnd
                return "dialog"
            return "opening"
        return None

    def _open_controls(self, controls: list[Control]) -> tuple[Control, Control, Control]:
        """Return the Open dialog's Merge (Project priority) radio, File name edit and Open."""
        radios = {c.text: c for c in controls if c.cls == "TRadioButton"}
        boxes = {c.hwnd for c in controls if c.cls == "ComboBox" and c.id == FILE_NAME_ID}
        file_name = next(
            (c for c in controls if c.cls == "Edit" and c.id == FILE_NAME_ID and c.parent in boxes),
            None,
        )
        open_button = next((c for c in controls if c.cls == "Button" and c.id == OPEN_ID), None)
        cancel = next((c for c in controls if c.cls == "Button" and c.id == CANCEL_ID), None)
        missing = []
        if set(radios) != IMPORT_MODES:
            missing.append("the import modes")
        if file_name is None:
            missing.append("the File name box")
        if open_button is None:
            missing.append("the Open button")
        if cancel is None:
            missing.append("the Cancel button")
        if missing:
            raise _failed(f"CLICK's Open dialog does not show {' or '.join(missing)}")
        assert file_name is not None and open_button is not None
        return radios[PROJECT_PRIORITY], file_name, open_button

    def _fill(self, edit: Control) -> None:
        """Set the File name box to the CSV's path. Wait until it has kept it for FILL_SETTLE."""
        text = str(self.path)
        held: list[float | None] = [None]

        def holds(_found: list[Window]) -> bool:
            if self.desktop.read_text(edit.hwnd) != text:
                held[0] = None
                self.desktop.set_text(edit.hwnd, text)
                return False
            if held[0] is None:
                held[0] = self.clock()
            return self.clock() - held[0] >= FILL_SETTLE

        self.desktop.set_text(edit.hwnd, text)
        self._wait("the File name box to keep the path", {"dialog"}, holds, FILL_TIMEOUT)

    def _answer(self, found: list[Window]) -> tuple[Window, bool] | None:
        """Return CLICK's answer window and whether it is the error list, once it is enabled.

        Return None before that.
        """
        done = [w for w in found if self._kind(w) == "done"]
        errors = [w for w in found if self._kind(w) == "errors"]
        if done and errors:
            raise _failed('CLICK shows both "Completed!" and its error list')
        if done and done[0].enabled:
            return done[0], False
        if errors and errors[0].enabled:
            return errors[0], True
        return None

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
