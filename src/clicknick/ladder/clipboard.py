"""Clipboard I/O for Click PLC Programming Software.

Uses Win32 API to read/write Click's private clipboard format (format 522).
Requires pywin32.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

CLICK_CLIPBOARD_FORMAT = 522  # 0x020A

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_user32.SetClipboardData.restype = ctypes.c_void_p
_user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
_user32.OpenClipboard.argtypes = [ctypes.c_void_p]
_user32.GetClipboardOwner.restype = ctypes.c_void_p
GMEM_MOVEABLE = 0x0002


def find_click_hwnd() -> int:
    """Find Click Programming Software's main window handle."""
    import win32gui

    results: list[int] = []

    def callback(hwnd, _):
        if "CLICK Programming Software" in win32gui.GetWindowText(hwnd):
            results.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    if not results:
        raise RuntimeError("Click Programming Software not found. Is it running?")
    return results[0]


def copy_to_clipboard(data: bytes) -> None:
    """Place bytes on clipboard in Click's private format (HWND-spoofed)."""
    hwnd = find_click_hwnd()
    if not _user32.OpenClipboard(hwnd):
        raise RuntimeError(f"OpenClipboard failed for HWND 0x{hwnd:08X}")
    try:
        _user32.EmptyClipboard()
        hmem = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not hmem:
            raise RuntimeError("GlobalAlloc failed")
        ptr = _kernel32.GlobalLock(hmem)
        ctypes.memmove(ptr, data, len(data))
        _kernel32.GlobalUnlock(hmem)
        if not _user32.SetClipboardData(CLICK_CLIPBOARD_FORMAT, hmem):
            raise RuntimeError("SetClipboardData failed")
    finally:
        _user32.CloseClipboard()


def read_from_clipboard() -> bytes:
    """Read Click clipboard data."""
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        raw = win32clipboard.GetClipboardData(CLICK_CLIPBOARD_FORMAT)
        return bytes(raw) if not isinstance(raw, bytes) else raw
    finally:
        win32clipboard.CloseClipboard()
