"""Make CLICK redraw its nicknames from SC_.mdb (issue #36).

CLICK's ladder paints nicknames from a table TagDB.dll keeps in memory, so after a
Sync writes SC_.mdb it shows the old names, and no window message reloads that table.
File > Import > Nickname does (live runs on CLICK v4.00, 2026-11-17): imported in
Merge (Project priority), the dialog's default, a CSV holding only the header line
answers "Completed!", leaves SC_.mdb as it was and redraws every nickname from it.
CLICK then counts the project as changed, as after an edit in its Address Picker.

``redraw_nicknames`` drives that import on the connected CLICK window through a
``ClickDesktop`` (``utils/win32_desktop.py`` on Windows; tests use a fake). It starts
only while CLICK shows its main window alone, presses only the import mode's radio
button, Open and the "Completed!" box's button, and leaves any other window to the
user. Windows' own strings ("Open", "OK", "Cancel") differ by language, so the file
dialog and its buttons are told by structure and control ids, and only CLICK's own
strings are read as text. It blocks for seconds: run it off the Tk thread.
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
# CLICK's nickname CSV header, byte for byte: a file of this line alone imports no row
HEADER = b"Address,Data Type,Nickname,Initial Value,Retentive,Address Comment\r\n"
PROJECT_PRIORITY = "Merge (Project priority)"
IMPORT_MODES = frozenset({PROJECT_PRIORITY, "Merge (File priority)", "Delete Existing"})
COMPLETED = "Completed!"
# The progress window is titled by its Delphi form's name at first, then by the mode
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
OPEN_TIMEOUT = 10.0
# A dialog of CLICK's owned by its main window that does not show the import modes
# is taken for the import's Open dialog still being built for this long
DIALOG_GRACE = 1.0
FILL_TIMEOUT = 5.0
# A file dialog still opening can empty its File name edit after it was set
# (devtools/click_runner.py, fill_path): the path must read back for this long
FILL_SETTLE = 1.0
ANSWER_TIMEOUT = 20.0
CLOSE_TIMEOUT = 10.0
POLL = 0.1


class ClickDesktop(Protocol):
    """The Win32 calls a redraw makes. Every message is posted or sent with a timeout."""

    def windows(self, pid: int) -> list[Window]:
        """The visible top-level windows of process *pid*."""
        ...

    def controls(self, hwnd: int) -> list[Control]:
        """The child windows of *hwnd*, at any depth."""
        ...

    def idle(self, hwnd: int, timeout: float) -> bool:
        """Whether *hwnd*'s thread answers a message within *timeout* seconds."""
        ...

    def post_command(self, hwnd: int, command_id: int) -> None:
        """Post WM_COMMAND *command_id* to *hwnd*."""
        ...

    def press(self, hwnd: int) -> None:
        """Post BM_CLICK to the button *hwnd*."""
        ...

    def button_checked(self, hwnd: int) -> int | None:
        """BM_GETCHECK of *hwnd*; None if it did not answer."""
        ...

    def read_text(self, hwnd: int) -> str | None:
        """WM_GETTEXT of *hwnd*; None if it did not answer."""
        ...

    def set_text(self, hwnd: int, text: str) -> bool:
        """WM_SETTEXT *text* into *hwnd*; False if it did not answer."""
        ...

    def foreground(self) -> int:
        """The foreground window, 0 for none."""
        ...

    def window_pid(self, hwnd: int) -> int:
        """The process that owns *hwnd*, 0 if it is gone."""
        ...

    def last_active_popup(self, hwnd: int) -> int:
        """GetLastActivePopup of *hwnd*: its owned window that was active last, else *hwnd*."""
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
    """Ends the redraw with *result*."""

    def __init__(self, result: RedrawResult) -> None:
        super().__init__(result.detail)
        self.result = result


def _failed(detail: str) -> _Stop:
    return _Stop(RedrawResult(RedrawOutcome.FAILED, detail))


def _describe(window: Window) -> str:
    """How a status line names *window*: its title, else its class."""
    return f'"{window.title}"' if window.title else window.cls


def _others(windows: list[Window], main: int) -> list[Window]:
    """*windows* but the main window and tooltips."""
    return [w for w in windows if w.hwnd != main and w.cls != TOOLTIP_CLASS]


def _shows_import_modes(controls: list[Control]) -> bool:
    return {c.text for c in controls if c.cls == "TRadioButton"} == IMPORT_MODES


# CSVs a redraw could not remove (CLICK still had one open): removed by the next redraw
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

    Imports a header-only CSV by File > Import > Nickname in Merge (Project priority).
    BUSY, with nothing sent, when CLICK's main window is disabled, does not answer or
    shows another window. FAILED when the import shows anything other than the
    windows it is known to show, or does not answer in time: the import's Open dialog
    is then cancelled if it is the one window open, and anything else is left to the
    user. The CSV is written into *temp_dir* (the temp folder by default) and removed
    afterwards, or by the next redraw when CLICK still holds it. When one of
    *own_pid*'s windows (this process by default) had the foreground and CLICK has it
    at the end, it goes back to that window's last active popup (a message box
    ClickNick showed meanwhile keeps it).
    """
    own = os.getpid() if own_pid is None else own_pid
    foreground = desktop.foreground()
    ours = foreground if foreground and desktop.window_pid(foreground) == own else 0
    _remove_leftovers()
    try:
        return _redraw(desktop, pid, main, clock, sleep, temp_dir)
    finally:
        now = desktop.foreground()
        if ours and now and desktop.window_pid(now) == pid:
            target = desktop.last_active_popup(ours) or ours
            if desktop.window_pid(target) == own:
                desktop.set_foreground(target)


def _redraw(
    desktop: ClickDesktop,
    pid: int,
    main: int,
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

    handle, name = tempfile.mkstemp(prefix="clicknick-redraw-", suffix=".csv", dir=temp_dir)
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(HEADER)
        return _Import(desktop, pid, main, path, clock, sleep).run()
    finally:
        if not _remove(path):
            logger.warning("Could not remove %s yet; the next redraw tries again", path)
            with _leftovers_lock:
                _leftovers.add(path)


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
        # When each dialog not yet told apart was first seen (DIALOG_GRACE)
        self._first_seen: dict[int, float] = {}

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
        # Checked last thing before Open, as the user could click another mode meanwhile
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
        """Which of the import's windows *window* is, or None.

        "dialog" is the import's Open dialog: a dialog owned by CLICK's main window
        that shows the three import modes. "opening" is a dialog owned by the main
        window, seen for less than DIALOG_GRACE, before the Open dialog was found.
        """
        if window.owner != self.main:
            return None
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
            first = self._first_seen.setdefault(window.hwnd, self.clock())
            if self.clock() - first < DIALOG_GRACE:
                return "opening"
        return None

    def _open_controls(self, controls: list[Control]) -> tuple[Control, Control, Control]:
        """The Open dialog's Merge (Project priority) radio button, File name edit and Open."""
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
        """Set the File name box to the CSV's path, and wait until it keeps it for FILL_SETTLE."""
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
        """CLICK's answer once it shows enabled: (the window, whether it is the error list)."""
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
        """Poll CLICK's windows until *until* (given the windows but the main window and
        tooltips) returns something other than None or False.

        A window that is none of the *expected* kinds (``_kind``), CLICK's main window
        closing, or *timeout* seconds passing ends the redraw as FAILED.
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
                raise _failed(f"timed out after {timeout:g} s waiting for {what}")
            self.sleep(POLL)

    def _cancel_lone_dialog(self) -> None:
        """Press Cancel in the import's Open dialog when it is the one window CLICK shows
        besides its main window, and still shows the import modes."""
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
