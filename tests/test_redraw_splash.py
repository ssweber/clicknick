"""The notice that shows over CLICK while ClickNick redraws CLICK's nicknames."""

from __future__ import annotations

import pytest
import win32con
import win32gui

from clicknick.views import redraw_splash
from clicknick.views.redraw_splash import RedrawSplash

CLICK = 0x1234  # Not a real window: the tests answer for it


def _geometry(splash: RedrawSplash) -> tuple[int, int, int, int]:
    size, x, y = splash._top.geometry().split("+")
    width, height = size.split("x")
    return int(width), int(height), int(x), int(y)


def test_the_notice_shows_without_taking_the_focus(tk_root) -> None:
    splash = RedrawSplash(tk_root, win32gui.GetDesktopWindow())
    try:
        style = win32gui.GetWindowLong(splash._hwnd, win32con.GWL_EXSTYLE)
        assert style & win32con.WS_EX_NOACTIVATE
        assert style & win32con.WS_EX_TOPMOST
    finally:
        splash.close()
    splash.close()  # Closing again does nothing
    assert tk_root.winfo_children() == []


def test_a_notice_that_fails_part_way_is_removed(tk_root, monkeypatch) -> None:
    def fails(*_args) -> None:
        raise win32gui.error(5, "SetWindowPos", "Access is denied.")

    monkeypatch.setattr(redraw_splash.win32gui, "SetWindowPos", fails)

    with pytest.raises(win32gui.error):
        RedrawSplash(tk_root, win32gui.GetDesktopWindow())

    assert tk_root.winfo_children() == []


def test_the_notice_shows_where_a_minimized_click_would_be_restored(tk_root, monkeypatch) -> None:
    """A minimized window sits at about (-32000, -32000), off screen."""
    monkeypatch.setattr(redraw_splash.win32gui, "IsIconic", lambda hwnd: hwnd == CLICK)
    monkeypatch.setattr(
        redraw_splash.win32gui,
        "GetWindowPlacement",
        lambda _hwnd: (
            0,
            win32con.SW_SHOWMINIMIZED,
            (-1, -1),
            (-32000, -32000),
            (100, 200, 500, 600),
        ),
    )

    splash = RedrawSplash(tk_root, CLICK)
    try:
        width, height, x, y = _geometry(splash)
    finally:
        splash.close()

    assert (x, y) == (100 + (400 - width) // 2, 200 + (400 - height) // 2)
