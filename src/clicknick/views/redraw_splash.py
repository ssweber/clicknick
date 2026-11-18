"""Show a notice over CLICK's main window while ClickNick redraws CLICK's nicknames.

The redraw (``services/click_redraw.py``) leaves the foreground window as it is. So the
notice never takes the focus and never becomes the active window.
"""

from __future__ import annotations

import tkinter as tk

import win32con
import win32gui

TEXT = "Redrawing nicknames in CLICK…"
_NO_ACTIVATE = win32con.SWP_NOACTIVATE | win32con.SWP_NOMOVE | win32con.SWP_NOSIZE


class RedrawSplash:
    """Show a small borderless topmost window centred over the CLICK window *click_hwnd*."""

    def __init__(self, root: tk.Misc, click_hwnd: int) -> None:
        top = tk.Toplevel(root)
        self._top: tk.Toplevel | None = top
        try:
            self._hwnd = self._build(top, click_hwnd)
        except BaseException:
            # The caller gets no notice to close, so a half-built one would stay on screen
            self.close()
            raise

    @staticmethod
    def _build(top: tk.Toplevel, click_hwnd: int) -> int:
        """Lay out *top* over *click_hwnd*, show it without activating it and return its hwnd."""
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
        left, upper, right, lower = _click_rect(top, click_hwnd)
        x = left + (right - left - width) // 2
        y = upper + (lower - upper - height) // 2
        top.geometry(f"{width}x{height}+{x}+{y}")
        top.deiconify()
        top.update_idletasks()
        hwnd = int(top.wm_frame(), 16)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        style |= win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, _NO_ACTIVATE)
        return hwnd

    def close(self) -> None:
        """Remove the window. Calling this again does nothing."""
        if self._top is not None:
            top, self._top = self._top, None
            try:
                top.destroy()
            except tk.TclError:
                pass  # Tk is shutting down, or the window is already gone


def _click_rect(top: tk.Misc, click_hwnd: int) -> tuple[int, int, int, int]:
    """Return the screen rectangle to centre the notice in.

    A minimized CLICK window sits off screen, at about (-32000, -32000). Its import still
    shows its Open dialog on screen (live check on CLICK 2.60 to 4.00, 2026-11-18). So for a
    minimized window, return the rectangle that it has when restored. If the window is gone,
    return the screen.
    """
    try:
        if win32gui.IsIconic(click_hwnd):
            return win32gui.GetWindowPlacement(click_hwnd)[4]
        return win32gui.GetWindowRect(click_hwnd)
    except win32gui.error:
        return 0, 0, top.winfo_screenwidth(), top.winfo_screenheight()
