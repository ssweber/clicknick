"""Test that the window lookups in ``win32_utils`` never stop a window listing early.

pywin32's ``EnumWindows`` raises ``pywintypes.error`` when the callback returns False while
the thread's last error is not zero. Error 126 was observed there right after an ODBC read of
SC_.mdb. In 0.26.0 the pid lookup's callback returned False once it found the window, so
EnumWindows raised. The watch then counted the CLICK window as closed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import pywintypes

from clicknick.detection.window_detector import ClickWindowDetector
from clicknick.utils import win32_utils
from clicknick.utils.win32_utils import WIN32


@dataclass(frozen=True)
class FakeWindow:
    hwnd: int
    pid: int
    title: str = ""
    cls: str = "Window"
    visible: bool = True


class FakeDesktop:
    """win32gui and win32process over a list of windows.

    ``EnumWindows`` raises as pywin32's does when a callback returns False and the thread's
    last error is 126. ``EnumChildWindows`` stops listing when a callback returns False. It
    never raises. pywin32 311's EnumChildWindows was observed to behave the same way.
    """

    def __init__(self, windows: list[FakeWindow]):
        self.windows = {window.hwnd: window for window in windows}

    def EnumWindows(self, callback, extra):  # noqa: N802 (win32gui's name)
        for hwnd in self.windows:
            if not callback(hwnd, extra):
                raise pywintypes.error(
                    126, "EnumWindows", "The specified module could not be found."
                )

    def EnumChildWindows(self, _parent, callback, extra):  # noqa: N802 (win32gui's name)
        for hwnd in self.windows:
            if not callback(hwnd, extra):
                return

    def GetWindowThreadProcessId(self, hwnd):  # noqa: N802 (win32process's name)
        return 1, self.windows[hwnd].pid

    def IsWindowVisible(self, hwnd):  # noqa: N802 (win32gui's name)
        return self.windows[hwnd].visible

    def GetWindowText(self, hwnd):  # noqa: N802 (win32gui's name)
        return self.windows[hwnd].title

    def GetClassName(self, hwnd):  # noqa: N802 (win32gui's name)
        return self.windows[hwnd].cls


@pytest.fixture
def desktop(monkeypatch):
    """Put a fake desktop in place of win32gui and win32process. Fill in its windows."""
    fake = FakeDesktop([])
    monkeypatch.setattr(win32_utils, "win32gui", fake)
    monkeypatch.setattr(win32_utils, "win32process", fake)
    return fake


def _windows(desktop: FakeDesktop, *windows: FakeWindow) -> None:
    desktop.windows = {window.hwnd: window for window in windows}


def test_the_pid_lookup_returns_the_first_visible_window_of_the_process(desktop):
    _windows(
        desktop,
        FakeWindow(1, pid=7),
        FakeWindow(2, pid=42, visible=False),
        FakeWindow(3, pid=42),
        FakeWindow(4, pid=42),
        FakeWindow(5, pid=8),
    )

    assert WIN32.get_hwnd_by_pid(42) == 3
    assert WIN32.win_exist(pid="42")
    assert not WIN32.win_exist(pid="9")


def test_the_watch_sees_the_click_window_while_it_is_open(desktop):
    _windows(desktop, FakeWindow(1, pid=7), FakeWindow(2, pid=42), FakeWindow(3, pid=8))

    assert ClickWindowDetector({}, None).check_window_exists("42")


def test_the_title_lookup_returns_the_first_visible_window_with_the_title(desktop):
    _windows(
        desktop,
        FakeWindow(1, pid=7, title="ClickNickOverlay", visible=False),
        FakeWindow(2, pid=7, title="ClickNickOverlay"),
        FakeWindow(3, pid=8, title="ClickNickOverlay 2"),
    )

    assert WIN32._find_window_by_title("ClickNickOverlay") == 2


def test_the_process_window_lookup_returns_the_first_window_of_the_process(desktop):
    _windows(
        desktop,
        FakeWindow(1, pid=7, title="New Subroutine Program"),
        FakeWindow(2, pid=42, title="New Subroutine Program"),
        FakeWindow(3, pid=42, title="New Subroutine Program"),
    )

    assert WIN32.find_process_window("42", "New Subroutine Program") == 2


def test_the_control_name_counts_the_controls_of_its_class_up_to_the_control(desktop):
    # EnumChildWindows never raises, so 0.26.0 passes this too. The test guards the count.
    _windows(
        desktop,
        FakeWindow(10, pid=42, cls="Edit"),
        FakeWindow(11, pid=42, cls="Button"),
        FakeWindow(12, pid=42, cls="Edit"),
        FakeWindow(13, pid=42, cls="Edit"),
    )

    assert WIN32._hwnd_to_control_name(7, 12) == "Edit2"


def test_a_failed_check_counts_as_an_open_window(monkeypatch):
    def fail(**_kwargs):
        raise pywintypes.error(5, "EnumWindows", "Access is denied.")

    monkeypatch.setattr(WIN32, "win_exist", fail)

    assert ClickWindowDetector({}, None).check_window_exists("42")
