"""Show a notice over CLICK's main window while ClickNick redraws CLICK's nicknames.

The redraw (``services/click_redraw.py``) needs CLICK to stay the active window. So the
notice never takes the focus and never becomes the active window.
"""

from __future__ import annotations

import tkinter as tk

import win32con
import win32gui

TEXT = "Redrawing nicknames in CLICK…"
_NO_ACTIVATE = win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE


class RedrawSplash:
    """A small borderless topmost window, centred over the CLICK window *click_hwnd*."""

    def __init__(self, root: tk.Misc, click_hwnd: int) -> None:
        top = tk.Toplevel(root)
        self._top = top
        top.withdraw()
        top.overrideredirect(True)
        top.configure(background="#3c3c3c")
        tk.Label(
            top,
            text=TEXT,
            background="#ffffe1",
            foreground="#000000",
            padx=18,
            pady=10,
        ).pack(padx=1, pady=1)
        top.update_idletasks()
        width, height = top.winfo_reqwidth(), top.winfo_reqheight()
        try:
            left, upper, right, lower = win32gui.GetWindowRect(click_hwnd)
        except win32gui.error:
            left, upper, right, lower = 0, 0, top.winfo_screenwidth(), top.winfo_screenheight()
        x = left + (right - left - width) // 2
        y = upper + (lower - upper - height) // 2
        top.geometry(f"{width}x{height}+{x}+{y}")
        top.deiconify()
        top.update_idletasks()
        self._hwnd = int(top.wm_frame(), 16)
        style = win32gui.GetWindowLong(self._hwnd, win32con.GWL_EXSTYLE)
        style |= win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST
        win32gui.SetWindowLong(self._hwnd, win32con.GWL_EXSTYLE, style)
        win32gui.SetWindowPos(self._hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, _NO_ACTIVATE)

    def close(self) -> None:
        """Remove the window. Calling this again does nothing."""
        if self._top is not None:
            top, self._top = self._top, None
            try:
                top.destroy()
            except tk.TclError:
                pass  # Tk is shutting down, or the window is already gone
