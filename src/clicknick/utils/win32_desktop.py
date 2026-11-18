"""Drive the Windows desktop for a CLICK nickname redraw (``services/click_redraw.py``).

The module posts messages, or sends them with SendMessageTimeout, so a hung CLICK cannot
hang ClickNick.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import win32gui
import win32process

from ..models.desktop import Control, Window

WM_NULL = 0x0000
WM_COMMAND = 0x0111
BM_CLICK = 0x00F5
SMTO_ABORTIFHUNG = 0x0002
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
    return user32


class Win32ClickDesktop:
    """``ClickDesktop`` on the real desktop."""

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
