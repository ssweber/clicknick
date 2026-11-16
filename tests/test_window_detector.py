"""Overlay detection across CLICK versions.

Before v4 the instruction dialogs are Delphi forms (TfrmContactNO, TEdit1); v4 makes them
standard dialogs (#32770) told apart by title. The Data View and Address Picker stay Delphi.
"""

import pytest

from clicknick.detection import window_detector
from clicknick.detection.window_detector import ClickWindowDetector
from clicknick.detection.window_mapping import BITS, CLICK_PLC_WINDOW_MAPPING, window_key
from clicknick.utils import win32_utils


class FakeWin32:
    def __init__(
        self,
        window_class: str,
        focused_control: str,
        title: str = "",
        texts: dict[str, str] | None = None,
    ):
        self.window_class = window_class
        self.focused_control = focused_control
        self.title = title
        self.texts = texts or {}  # A control's name -> its text
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

    def get_control_text(self, hwnd, name):
        assert hwnd == 7  # The dialog's
        return self.texts.get(name, "")


def detect(monkeypatch, window_class, control, title="", texts=None):
    win32 = FakeWin32(window_class, control, title, texts)
    monkeypatch.setattr(window_detector, "WIN32", win32)
    detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, None)
    info = detector.detect_child_window("42")
    if info is None:
        return None, win32
    field = detector.update_window_info(info.window_class, info.edit_control, info.window_id)
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


# CLICK v4's Edit and ComboBox windows in the dialogs below, in the order EnumChildWindows
# lists them: (class, control id). Live probe f1 (BOB job autocomplete-fields, 2026-11-16)
# listed them, hidden ones included. Receive's and Send's IP address control (5036) holds four
# Edit windows of its own; they show only for CPU Port1 and the WLAN Port (Modbus TCP).
LIVE_CONTROLS = {
    "Out": [
        ("Edit", 5002),
        ("Edit", 5003),
        ("Edit", 5015),
        ("Edit", 5018),
        ("Edit", 5033),
        ("Edit", 5036),
        ("ComboBox", 5013),
    ],
    "Set": [("Edit", 5002), ("Edit", 5003)],
    "Reset": [("Edit", 5002), ("Edit", 5003)],
    "Receive": [
        ("ComboBox", 5000),
        ("Edit", 5011),
        *[("Edit", 5036)] * 4,
        ("Edit", 5039),
        ("Edit", 5014),
        ("ComboBox", 5001),
        ("ComboBox", 5002),
        ("Edit", 5015),
        ("Edit", 5016),
        ("Edit", 5017),
        ("ComboBox", 5003),
        ("ComboBox", 5004),
        ("Edit", 5074),
        ("Edit", 5076),
        ("Edit", 5079),
        ("Edit", 5077),
        ("ComboBox", 5067),
        ("ComboBox", 5068),
        ("Edit", 5020),
        ("Edit", 5023),
        ("Edit", 5026),
        ("Edit", 5029),
        ("Edit", 5091),
        ("Edit", 5094),
        ("Edit", 5084),
    ],
    "Send": [
        ("ComboBox", 5000),
        ("Edit", 5011),
        *[("Edit", 5036)] * 4,
        ("Edit", 5039),
        ("Edit", 5014),
        ("ComboBox", 5001),
        ("ComboBox", 5002),
        ("Edit", 5015),
        ("Edit", 5016),
        ("Edit", 5017),
        ("ComboBox", 5003),
        ("Edit", 5060),
        ("Edit", 5063),
        ("Edit", 5082),
        ("Edit", 5083),
        ("Edit", 5020),
        ("Edit", 5023),
        ("Edit", 5026),
        ("Edit", 5029),
    ],
}
FUNCTION_CODE = 5001  # Receive's and Send's Modbus Function Code list

# The banks the Address Picker leaves open when a field's "..." button opens it
# ("Address Picker : Pickup Mode" greys the rest): (dialog, field id, Function Code shown)
# -> banks. Live probes f1 and f2 (BOB job autocomplete-fields, picker_shots/), CLICK v4.00.
# Out's delay edits are the same for Debounce, Flasher and Timed (Timed opens 5015 and 5018).
PICKER_BANKS = {
    ("Out", 5002, None): {"Y", "C", "SC"},  # Bit Memory Address1
    ("Out", 5003, None): {"Y", "C", "SC"},  # Bit Memory Address2
    ("Out", 5015, None): {"DS"},  # On Time
    ("Out", 5018, None): {"TD"},  # On Timer Number
    ("Out", 5033, None): {"DS"},  # Off Time
    ("Out", 5036, None): {"TD"},  # Off Timer Number
    ("Set", 5002, None): {"Y", "C", "SC"},
    ("Set", 5003, None): {"Y", "C", "SC"},
    ("Reset", 5002, None): {"Y", "C", "SC"},
    ("Reset", 5003, None): {"Y", "C", "SC"},
    ("Receive", 5016, "01 - Read Coil Status"): {"Y", "C"},
    ("Receive", 5016, "02 - Read Input Status"): {"Y", "C"},
    ("Receive", 5016, "03 - Read Holding Registers"): {"DS", "DD", "DH", "DF", "YD", "TXT"},
    ("Receive", 5016, "04 - Read Input Registers"): {"DS", "DD", "DH", "DF", "YD", "TXT"},
    ("Receive", 5020, "01 - Read Coil Status"): {"C"},  # Receiving
    ("Receive", 5023, "01 - Read Coil Status"): {"C"},  # Success
    ("Receive", 5026, "01 - Read Coil Status"): {"C"},  # Error
    ("Receive", 5029, "01 - Read Coil Status"): {"DS", "DD"},  # Exception Response
    ("Receive", 5029, "03 - Read Holding Registers"): {"DS", "DD"},
    ("Send", 5016, "05 - Write Single Coil"): {"X", "Y", "C", "T", "CT", "SC"},
    ("Send", 5016, "06 - Write Single Register"): {"DS", "DH", "XD", "YD", "TD", "SD", "TXT"},
    ("Send", 5016, "15 - Write Multiple Coils"): {"X", "Y", "C", "T", "CT", "SC"},
    ("Send", 5016, "16 - Write Multiple Registers"): {
        *("DS", "DD", "DH", "DF", "TD", "CTD", "SD", "TXT"),
    },
    ("Send", 5020, "05 - Write Single Coil"): {"C"},  # Sending
    ("Send", 5023, "05 - Write Single Coil"): {"C"},  # Success
    ("Send", 5026, "05 - Write Single Coil"): {"C"},  # Error
    ("Send", 5029, "05 - Write Single Coil"): {"DS", "DD"},  # Exception Response
    ("Send", 5029, "16 - Write Multiple Registers"): {"DS", "DD"},
}


class FakeChildWindows:
    """win32gui's child-window listing over a dialog recorded in LIVE_CONTROLS."""

    def __init__(self, controls):
        self.classes = {100 + n: cls for n, (cls, _) in enumerate(controls)}

    def GetClassName(self, hwnd):  # noqa: N802 (win32gui's name)
        return self.classes[hwnd]

    def EnumChildWindows(self, _parent, callback, extra):  # noqa: N802 (win32gui's name)
        for hwnd in self.classes:
            if callback(hwnd, extra) is False:
                return


def live_name(monkeypatch, title, control_id, index=0):
    """The name ClickNick's overlay gives control *control_id* of the live *title* dialog
    (the *index*-th window with that id)."""
    controls = LIVE_CONTROLS[title]
    monkeypatch.setattr(win32_utils, "win32gui", FakeChildWindows(controls))
    hwnd = [100 + n for n, (_, cid) in enumerate(controls) if cid == control_id][index]
    return win32_utils.WIN32._hwnd_to_control_name(7, hwnd)


@pytest.mark.parametrize(("title", "field_id", "function_code"), list(PICKER_BANKS))
def test_v4_fields_offer_the_banks_clicks_picker_offers(
    monkeypatch, title, field_id, function_code
):
    name = live_name(monkeypatch, title, field_id)
    texts = {}
    if function_code is not None:
        texts[live_name(monkeypatch, title, FUNCTION_CODE)] = function_code

    found, _ = detect(monkeypatch, "#32770", name, title, texts)

    assert found is not None, f"{title} {field_id} ({name}) has no popup"
    assert set(found[1]) == PICKER_BANKS[title, field_id, function_code]


@pytest.mark.parametrize("title", ["Receive", "Send"])
@pytest.mark.parametrize("octet", range(4))
def test_receive_and_send_ip_address_has_no_popup(monkeypatch, title, octet):
    name = live_name(monkeypatch, title, 5036, octet)  # Server(Slave) IP Address

    found, _ = detect(monkeypatch, "#32770", name, title)

    assert found is None


# CLICK v4's answers for a Receive's Starting Master Address, its flags and its exception
# field (`try` runs rx2 of BOB job runner-grids and t1 of job autocomplete-fields), and for
# Out's address (t1): what is tried, the Function Code shown, whether OK took it. Each refusal
# was OBJ-004 "The entered address cannot be used in this instruction."
TRY_ANSWERS = [
    ("Receive", 5016, "01 - Read Coil Status", "Y001", True),
    ("Receive", 5016, "01 - Read Coil Status", "C1", True),
    ("Receive", 5016, "01 - Read Coil Status", "X001", False),
    ("Receive", 5016, "01 - Read Coil Status", "T1", False),
    ("Receive", 5016, "01 - Read Coil Status", "CT1", False),
    ("Receive", 5016, "01 - Read Coil Status", "SC1", False),
    ("Receive", 5016, "01 - Read Coil Status", "DS1", False),
    ("Receive", 5016, "02 - Read Input Status", "Y001", True),
    ("Receive", 5016, "02 - Read Input Status", "C1", True),
    ("Receive", 5016, "02 - Read Input Status", "X001", False),
    ("Receive", 5016, "02 - Read Input Status", "DS1", False),
    ("Receive", 5016, "02 - Read Input Status", "SC1", False),
    *[
        ("Receive", 5016, fc, address, True)
        for fc in ("03 - Read Holding Registers", "04 - Read Input Registers")
        for address in ("DS1", "DD1", "DH1", "DF1", "TXT1", "YD0")
    ],
    *[
        ("Receive", 5016, fc, address, False)
        for fc in ("03 - Read Holding Registers", "04 - Read Input Registers")
        for address in ("TD1", "SD1", "XD0", "CTD1", "C1")
    ],
    ("Receive", 5020, "01 - Read Coil Status", "C100", True),  # Receiving
    ("Receive", 5020, "01 - Read Coil Status", "Y001", False),
    ("Receive", 5023, "01 - Read Coil Status", "SC50", False),  # Success
    ("Receive", 5026, "01 - Read Coil Status", "DS1", False),  # Error
    ("Receive", 5029, "01 - Read Coil Status", "DS100", True),  # Exception Response
    ("Receive", 5029, "01 - Read Coil Status", "DD100", True),
    ("Receive", 5029, "01 - Read Coil Status", "DH1", False),
    ("Receive", 5029, "01 - Read Coil Status", "DF1", False),
    ("Out", 5002, None, "Y001", True),
    ("Out", 5002, None, "C1", True),
    ("Out", 5002, None, "SC50", True),
    ("Out", 5002, None, "X001", False),
    ("Out", 5002, None, "T1", False),
    ("Out", 5002, None, "CT1", False),
]


@pytest.mark.parametrize(("title", "field_id", "function_code", "address", "taken"), TRY_ANSWERS)
def test_v4_fields_offer_what_click_takes(
    monkeypatch, title, field_id, function_code, address, taken
):
    name = live_name(monkeypatch, title, field_id)
    texts = {}
    if function_code is not None:
        texts[live_name(monkeypatch, title, FUNCTION_CODE)] = function_code

    found, _ = detect(monkeypatch, "#32770", name, title, texts)

    assert found is not None
    bank = address.rstrip("0123456789")
    assert (bank in found[1]) == taken


@pytest.mark.parametrize(
    ("title", "codes"),
    [
        ("Receive", ["01 - Read Coil Status", "03 - Read Holding Registers"]),
        ("Send", ["05 - Write Single Coil", "06 - Write Single Register"]),
    ],
)
def test_master_address_without_a_function_code_offers_every_codes_banks(monkeypatch, title, codes):
    name = live_name(monkeypatch, title, 5016)

    found, _ = detect(monkeypatch, "#32770", name, title)  # The list reads empty

    assert found is not None
    for code in codes:
        assert set(PICKER_BANKS[title, 5016, code]) <= set(found[1])


@pytest.mark.parametrize(
    ("form", "field", "title"), [("TfrmRD", "TEdit20", "Receive"), ("TfrmSD", "TEdit16", "Send")]
)
def test_v2_v3_master_address_offers_every_function_codes_banks(monkeypatch, form, field, title):
    found, _ = detect(monkeypatch, form, field)

    assert found is not None
    every = set().union(*(b for (t, f, _), b in PICKER_BANKS.items() if t == title and f == 5016))
    assert set(found[1]) == every
