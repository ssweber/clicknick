"""Overlay detection across CLICK versions.

Before v4 the instruction dialogs are Delphi forms (TfrmContactNO, TEdit1); v4 makes them
standard dialogs (#32770) told apart by title. The Data View and Address Picker stay Delphi.
"""

import pytest

from clicknick.detection import window_detector
from clicknick.detection.window_detector import ClickWindowDetector
from clicknick.detection.window_mapping import BITS, CLICK_PLC_WINDOW_MAPPING, window_key


class FakeWin32:
    def __init__(self, window_class: str, focused_control: str, title: str = ""):
        self.window_class = window_class
        self.focused_control = focused_control
        self.title = title
        self.gui_thread_info: bool | None = None

    def get_foreground_pid(self):
        return "42"

    def get_foreground_hwnd(self):
        return 7

    def get_class(self, _hwnd):
        return self.window_class

    def get_title(self, _hwnd):
        return self.title

    def get_focused_control(self, _hwnd, use_gui_thread_info=False):
        self.gui_thread_info = use_gui_thread_info
        return self.focused_control


def detect(monkeypatch, window_class, control, title=""):
    win32 = FakeWin32(window_class, control, title)
    monkeypatch.setattr(window_detector, "WIN32", win32)
    detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, None)
    info = detector.detect_child_window("42")
    if info is None:
        return None, win32
    field = detector.update_window_info(info.window_class, info.edit_control)
    assert field.is_valid
    return (info, field.allowed_address_types), win32


@pytest.mark.parametrize(
    ("window_class", "title", "control", "key"),
    [
        ("TfrmContactNO", "Contact Normally Open", "TEdit1", "frmContactNO"),
        ("#32770", "Contact Normally Open", "Edit1", "Contact Normally Open"),
    ],
)
def test_contact_dialog_matches_in_every_click_version(
    monkeypatch, window_class, title, control, key
):
    found, _ = detect(monkeypatch, window_class, control, title)

    assert found is not None
    info, types = found
    assert info.window_class == key
    assert info.edit_control == control  # kept as CLICK names it, for Win32 lookups
    assert types == BITS


@pytest.mark.parametrize(
    ("window_class", "title", "bit_field", "value_field"),
    [("TfrmTimer", "Timer", "TEdit3", "TEdit2"), ("#32770", "Timer", "Edit1", "Edit2")],
)
def test_timer_fields_follow_each_versions_numbering(
    monkeypatch, window_class, title, bit_field, value_field
):
    found, _ = detect(monkeypatch, window_class, bit_field, title)
    assert found is not None and found[1] == ["T"]
    found, _ = detect(monkeypatch, window_class, value_field, title)
    assert found is not None and found[1] == ["DS"]


@pytest.mark.parametrize("title", ["Find", "Replace"])
def test_find_and_replace_dialog_matches_by_title(monkeypatch, title):
    found, _ = detect(monkeypatch, "#32770", "Edit3", title)

    assert found is not None
    assert found[0].window_class == "Find"


def test_other_standard_dialogs_do_not_match(monkeypatch):
    found, _ = detect(monkeypatch, "#32770", "Edit1", "New Data View")

    assert found is None


@pytest.mark.parametrize("window_class", ["TfrmDataView", "frmDataView"])
def test_dataview_reads_the_focus_through_gui_thread_info(monkeypatch, window_class):
    found, win32 = detect(monkeypatch, window_class, "TEdit1")

    assert found is not None
    assert win32.gui_thread_info is True


def test_unlisted_control_does_not_match(monkeypatch):
    found, _ = detect(monkeypatch, "#32770", "Edit3", "Timer")  # Current Value (read-only)

    assert found is None


def test_window_key_strips_delphis_t_but_keeps_dialog_titles():
    assert window_key("TfrmTagDB", "Address Picker") == "frmTagDB"
    assert window_key("#32770", "Shift Register") == "Shift Register"
    assert window_key("#32770", "Find and Replace") == "Find"
