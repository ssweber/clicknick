"""Drive the Windows desktop for a CLICK nickname redraw (``services/click_redraw.py``).

The module posts messages, or sends them with SendMessageTimeout, so a hung CLICK cannot
hang ClickNick. WM_GETTEXT and WM_SETTEXT reach another process's controls because
Windows copies their text across.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import win32gui
import win32process

from ..models.desktop import Control, Window

WM_NULL = 0x0000
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_COMMAND = 0x0111
BM_GETCHECK = 0x00F0
BM_CLICK = 0x00F5
SMTO_ABORTIFHUNG = 0x0002
GW_OWNER = 4
_MESSAGE_TIMEOUT_MS = 5000
_ULONG_PTR = ctypes.c_size_t


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(_ULONG_PTR),
    ]
    user32.SendMessageTimeoutW.restype = _ULONG_PTR
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetLastActivePopup.argtypes = [wintypes.HWND]
    user32.GetLastActivePopup.restype = wintypes.HWND
    return user32


class Win32ClickDesktop:
    """Implement ``ClickDesktop`` on the real desktop."""

    def __init__(self) -> None:
        self._user32 = _user32()

    def _send(
        self, hwnd: int, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 0
    ) -> int | None:
        result = _ULONG_PTR()
        answered = self._user32.SendMessageTimeoutW(
            hwnd,
            msg,
            wparam,
            lparam,
            SMTO_ABORTIFHUNG,
            timeout_ms or _MESSAGE_TIMEOUT_MS,
            ctypes.byref(result),
        )
        return result.value if answered else None

    def _post(self, hwnd: int, msg: int, wparam: int = 0) -> None:
        if not self._user32.PostMessageW(hwnd, msg, wparam, 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def windows(self, pid: int) -> list[Window]:
        found: list[Window] = []

        def callback(hwnd: int, _: object) -> bool:
            try:
                if (
                    win32gui.IsWindowVisible(hwnd)
                    and win32process.GetWindowThreadProcessId(hwnd)[1] == pid
                ):
                    found.append(
                        Window(
                            hwnd=hwnd,
                            cls=win32gui.GetClassName(hwnd),
                            title=win32gui.GetWindowText(hwnd),
                            owner=win32gui.GetWindow(hwnd, GW_OWNER),
                            enabled=bool(win32gui.IsWindowEnabled(hwnd)),
                        )
                    )
            except win32gui.error:
                pass  # It closed while being listed
            return True

        win32gui.EnumWindows(callback, None)
        return found

    def controls(self, hwnd: int) -> list[Control]:
        found: list[Control] = []

        def callback(child: int, _: object) -> bool:
            try:
                found.append(
                    Control(
                        hwnd=child,
                        parent=win32gui.GetParent(child),
                        cls=win32gui.GetClassName(child),
                        text=win32gui.GetWindowText(child),
                        id=win32gui.GetDlgCtrlID(child),
                    )
                )
            except win32gui.error:
                pass  # It closed while being listed
            return True

        try:
            win32gui.EnumChildWindows(hwnd, callback, None)
        except win32gui.error:
            pass  # No children, or the window closed
        return found

    def idle(self, hwnd: int, timeout: float) -> bool:
        return self._send(hwnd, WM_NULL, timeout_ms=max(1, int(timeout * 1000))) is not None

    def post_command(self, hwnd: int, command_id: int) -> None:
        self._post(hwnd, WM_COMMAND, command_id)

    def press(self, hwnd: int) -> None:
        self._post(hwnd, BM_CLICK)

    def button_checked(self, hwnd: int) -> int | None:
        return self._send(hwnd, BM_GETCHECK)

    def read_text(self, hwnd: int) -> str | None:
        length = self._send(hwnd, WM_GETTEXTLENGTH)
        if length is None:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        if self._send(hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer)) is None:
            return None
        return buffer.value

    def set_text(self, hwnd: int, text: str) -> bool:
        buffer = ctypes.create_unicode_buffer(text)
        return self._send(hwnd, WM_SETTEXT, 0, ctypes.addressof(buffer)) is not None

    def foreground(self) -> int:
        return win32gui.GetForegroundWindow() or 0

    def window_pid(self, hwnd: int) -> int:
        if not hwnd or not win32gui.IsWindow(hwnd):
            return 0
        return win32process.GetWindowThreadProcessId(hwnd)[1]

    def last_active_popup(self, hwnd: int) -> int:
        return self._user32.GetLastActivePopup(hwnd) or hwnd

    def set_foreground(self, hwnd: int) -> None:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except win32gui.error:
            pass  # Windows refused, so the window stays where it is
