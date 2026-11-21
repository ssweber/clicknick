"""Test the CLICK runner (devtools/click_runner.py) against a fake CLICK.

No test launches CLICK or sends anything to a window. ``FakeClick`` plays CLICK v4's
dialogs in the order that CLICK shows them. Their window classes, titles, owners, control
ids and texts are copied from the real CLICK v4 windows. A posted message takes effect on a
later poll, as it does in CLICK.
"""

from __future__ import annotations

import codecs
import csv as csv_module
import io
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import laddercodec
import pytest
from laddercodec import Program, read_csv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtools"))

import click_desktop as cd  # noqa: E402
import click_runner as cr  # noqa: E402

from clicknick.ladder.program import empty_rung, prepare_csv_load  # noqa: E402

RUNG_CSV = (
    "marker,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF\n"
    "R,X001,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,out(Y001)\n"
)
# The start of the text of the box that CLICK showed at Connect in a live run on 2026-11-18,
# when the PLC still held the connection of a CLICK that had crashed
CPU_TYPE_TEXT = (
    "CLICK Programming Software could not read the CPU type. Please check these 3 possible "
    "causes:\n\n1) If the CPU is powered through USB (Low Power mode) and a C2-Slot Module "
    "Unknown is installed, please supply the CPU with 24VDC."
)
MAIN_CLASS = "Afx:002E0000:8:00010003:00000000:10D30AE3"
# The module ids that CLICK 4.00 wrote in [Sec21] for these CPUs in live runs on 2026-11-20
CPU_IDS = {"C0-02DD1-D": 241, "C0-11DD1E-D": 212, "C2-03CPU": 198, "C2-03CPU-2": 201}
OUTPUT_BAR = "Afx:ControlBar:2e0000:8:10003:10"


@dataclass
class FakeControl:
    hwnd: int
    parent: int
    cls: str
    text: str
    id: int
    visible: bool = True
    enabled: bool = True
    rect: tuple[int, int, int, int] = (0, 0, 10, 10)
    value: str = ""  # An edit's text, which only WM_GETTEXT reads
    checked: int = 0
    items: int = 0
    options: list[str] = field(default_factory=list)  # A ComboBox's items
    selected: int = -1  # The ComboBox item selected
    limit: int = 30000  # An edit's EM_GETLIMITTEXT
    on_press: Callable[[], None] | None = None
    on_key: Callable[[int], None] | None = None
    on_send: Callable[[], None] | None = None  # Run when BM_CLICK is sent, not posted


@dataclass
class FakeWindow:
    hwnd: int
    cls: str
    title: str
    owner: int
    enabled: bool = True
    controls: list[FakeControl] = field(default_factory=list)
    on_close: Callable[[], None] | None = None
    on_text: Callable[[], None] | None = None  # Run when a field's text is set (EN_CHANGE)
    on_drop: Callable[[], None] | None = None  # Run when the window goes


# SYSTEM_ROWS holds two of the system rows that CLICK's Address Picker writes into SC_.mdb on
# OK. RESERVED holds two of the words that the Picker's editor refuses in any letter case.
SYSTEM_ROWS = {"SD19": {"Nickname": "_RTC_Year(4 digits)"}, "SD26": {"Nickname": "_RTC_Second"}}
RESERVED = {"MAX", "LOG"}
# The drop-down lists of CLICK's Receive dialog, by control id. Each entry holds the list's
# items and the index of the item that is selected when the dialog opens.
RECEIVE_LISTS = {
    5000: (["CPU Port1", "CPU Port2", "CPU Port3", "WLAN Port"], 1),
    5001: (
        [
            "01 - Read Coil Status",
            "02 - Read Input Status",
            "03 - Read Holding Registers",
            "04 - Read Input Registers",
        ],
        0,
    ),
    5002: (["Modbus 984 Addressing", "Modbus Hex Addressing", "CLICK Addressing"], 0),
    5003: (["ON", "OFF"], 1),
}
# The Receive fields whose length limit (EM_GETLIMITTEXT) is below the default, by control id
RECEIVE_LIMITS = {5014: 6, 5017: 4, 5020: 16, 5023: 16, 5026: 16, 5029: 16}
# Slave ID and Number of Bits are the Receive fields that hold a value when the dialog opens
RECEIVE_FILLED = {5014: "1", 5017: "1"}
# The Function Code items under which Word Swap (5003) is enabled: 03 and 04, which read
# registers. CLICK disables Word Swap under the other codes.
WORD_SWAP_OPEN_FOR = {2, 3}
# The drop-down lists of CLICK's Send dialog, as the live run on 2026-11-18 dumped them. A PLC
# with no Slot0 or Slot1 module lists no port of theirs.
SEND_LISTS = {
    5000: (["CPU Port1", "CPU Port2", "CPU Port3", "WLAN Port"], 1),
    5001: (
        [
            "05 - Write Single Coil",
            "06 - Write Single Register",
            "15 - Write Multiple Coils",
            "16 - Write Multiple Registers",
        ],
        0,
    ),
    5002: (["Modbus 984 Addressing", "Modbus Hex Addressing", "CLICK Addressing"], 0),
    5003: (["ON", "OFF"], 1),
}
SEND_LIMITS = {5014: 6, 5017: 4, 5020: 16, 5023: 16, 5026: 16, 5029: 16, 5039: 5}
SEND_FILLED = {5014: "0", 5017: "1", 5039: "502"}
# Send enables Number of Bits (5017) under 15 and 16, and Word Swap (5003) only under 16.
# CPU Port1 and WLAN Port show the Server IP Address and the Server Port Number.
SEND_COUNT_FOR = {2, 3}
SEND_WORD_SWAP_FOR = {3}
SEND_IP_PORTS = {0, 3}
UNITS = (["ms", "sec", "min", "hour", "day"], 0)
# The drop-down lists of each instruction dialog, by its title and then by control id
DIALOG_LISTS = {
    "Receive": RECEIVE_LISTS,
    "Send": SEND_LISTS,
    "Timer": {5006: UNITS},
    "Drum": {5003: UNITS},
}
# The option buttons of the Copy and Search dialogs as they open, by control id. Each entry
# holds the label, whether the button is visible, whether it is enabled and whether it is
# checked. In Copy, 5019 and 5020 are a pair of radio buttons, and so are 5036 and 5037. The
# rest are check boxes.
OPTION_BUTTONS = {
    "Copy": {
        5019: ("Suppress zero", True, False, 1),
        5020: ("Do not suppress zero", True, False, 0),
        5036: ("Suppress zero", False, True, 1),
        5037: ("Do not suppress zero", False, True, 0),
        5021: ("Termination Code", True, False, 0),
    },
    "Search": {
        5021: ("Continuous Search", True, True, 0),
        5022: ("One Shot (Execute one time)", True, True, 0),
    },
}
OPTION_RADIOS = {5019: 5020, 5020: 5019, 5036: 5037, 5037: 5036}
# Timer's "Current value will not be retained" (5010) and Retentive (5011) are a pair
TIMER_RADIOS = {5010: 5011, 5011: 5010}


def copy_options(source: str, destination: str) -> tuple[tuple[str, str], bool, bool, bool]:
    """Return the state of Copy's option buttons for the addresses in its fields.

    The tuple holds the labels of 5019 and 5020, whether 5019 and 5020 are enabled, whether 5036
    and 5037 are visible, and whether Termination Code (5021) is enabled. The states copy what
    CLICK showed for -5, 1.5, DS1 and DF1 copied into TXT1, CTD1 into DF1, and TXT1 into TXT21.
    With no destination, the buttons are as the dialog opens them."""
    if not destination:
        return ("Suppress zero", "Do not suppress zero"), False, False, False
    if not destination.startswith("TXT"):
        return ("Copy Value", "Copy Binary"), True, False, False
    if source.startswith("TXT"):
        return ("Suppress zero", "Do not suppress zero"), False, False, True
    if "." in source or source.startswith("DF"):
        return ("Real Numbering", "Exponential Numbering"), True, False, True
    return ("Copy Value", "Copy Binary"), True, True, True


# The instructions that --wire places as contacts. A rung that holds only these has no coil,
# and CLICK's Syntax Check reports C0003 for it.
CONTACT_TITLES = ("Contact Normally Open", "Compare (A with B)")


class FakeClick(cd.Desktop):
    """A fake CLICK v4, with switches that make it go wrong in known ways.

    *surprise* names an event after which an unknown dialog appears. *stall* names an event
    whose effect never happens. *hang_on* names an event after which CLICK stops answering
    for *hang_for* seconds. While CLICK hangs, Windows adds " (Not Responding)" to the title
    of its main window. *interrupt* names a Desktop method that raises KeyboardInterrupt
    once. *fail* names a Desktop method that always raises OSError. *late_row* is a number
    of seconds. That long after the scan, the Connect dialog's list shows a second PLC.
    With *status_bar* off, the status bar cannot be read. With *plc_pane* off, the status bar
    does not name the PLC once CLICK is connected. *leftover* names Scr*.tmp files that are
    in the temp folder before CLICK starts. An earlier CLICK whose main window had the same
    hwnd would leave them there. *error_on* names an event after which CLICK shows its
    PTC-013 error box. After "connect", the Connect dialog owns the box and no Login
    follows. After any other event, the main window owns the box. CLICK answers the first
    *cpu_type* presses of Connect with a box that the Connect dialog owns. By default the box
    is the one that says CLICK could not read the CPU type (``CPU_TYPE_TEXT``, one OK).
    *cpu_type_box* gives the box another text and other buttons. *cpu_type_extra* adds a
    control to the box, as a class and a text. Each of the box's buttons closes it and
    enables the Connect dialog again. With *cpu_type_slow*, each takes that many polls.

    The ribbon's Math, Copy, Out, Contact(NO), Compare and Search commands open their
    dialogs as CLICK lays them out. *judge* decides what happens when OK is pressed in one
    of these dialogs. It returns None to accept, ``(code, message)`` to refuse with an error
    box, ``("warn", code, message)`` to show the box and then place the instruction, or
    ``"question"`` to show a Yes/No box with no code. It returns ``"crash"`` to make CLICK exit,
    as real CLICK did after OK on some cases. ``rung`` lists the instructions placed
    in rung 1, in order. After a contact (``CONTACT_TITLES``) the cursor is at column B, and
    after any other instruction it is at AF. Syntax Check lists the line that
    *syntax_lines* gives for each placed instruction, keyed by the dialog's title. It also
    lists C0003 when the rung has no coil. If a click on rung 1's number
    (``cr.RUNG1_POINT``, posted to the ladder view) has selected the rung, Delete removes
    the whole rung. Otherwise Delete removes the instruction under the cursor at AF. With
    *delete_works* off, Delete does nothing. Edit > Copy of the selected rung puts
    ``copy_payload`` on the clipboard, or ``RUNG_CSV``'s payload if ``copy_payload`` is
    None. With *copies* off, Edit > Copy does nothing.
    *ladder_views* is how many visible ladder views the main window has. Each dialog opens
    with the button states that its ``cr.INSTRUCTIONS`` entry names, and *opens_with*
    overrides them. With *places* off, a dialog closed by OK places nothing in rung 1.
    When a field is set to the text *box_on_fill*, CLICK at once shows an error box that
    the dialog owns. *quick_checks* is a number of polls. CLICK ignores a Syntax Check that
    is posted within that many polls of the last check's result, and the fake records the
    event ``check_ignored``. Real CLICK ignored a check posted soon after the last one.

    Copy's option buttons open as ``OPTION_BUTTONS`` lists them. When a field is set, the
    buttons take the states that ``copy_options`` returns. Checking Termination Code
    enables the Termination code field. Compare hides its >, <, >= and <= buttons when Data
    A holds a TXT address. The first *lost_presses* presses on option buttons have no
    effect, and each records the event ``lost_press``. Real CLICK lost such a press once.
    With *slow_options*, the first press on an option button leaves the dialog busy
    (``idle`` returns False) for longer than ``cr.OPTION_WAIT``. The button shows its new
    state without waiting for that.

    Timer, Counter, Shift Register, For, Drum and Send open as a live run on 2026-11-18
    dumped them. Timer and Counter fill their read-only fields once the timer's or the
    counter's number is set. Timer's OFF Delay disables its retentive pair. Drum's Event
    Base disables Unit and Elapsed Time and empties the step rows, and Time and Event shows
    the durations' column. Send's Com Port shows or hides the server's IP address and port,
    and sets the Function Code to 06 again. Its Function Code enables Number of
    Bits and Word Swap. Its IP address control holds four Edits with its id. When *judge*
    returns a list of ``(code, message)``, CLICK shows those boxes one after another, each
    after the last one's OK. CLICK ignores the first *sticky_boxes* presses on an error
    box's OK, and records ``ok_ignored`` for each. Another program holds the clipboard for
    the first *clipboard_held* calls that set or empty it, and each records
    ``clipboard_held``. *list_on_fill* names a list of Receive, Send, Timer or Drum and what
    setting any field does to it. With ``reset``, the list selects its first item. With
    ``stuck``, it selects its first item and ignores every later key. With ``closed``, it is
    disabled. With *mode_resets_on_fill*, setting any field checks the dialog's first mode.

    File > Import > Nickname opens CLICK's Open dialog, with a radio button for each import
    mode. Merge (Project priority) is checked when it opens. Open passes the file's bytes to
    *import_answer*. That returns the rows that the import stores and the text of the error
    list, or None to show "Completed!". The fake keeps the nickname table as JSON in
    SC_.mdb. In Delete Existing mode the rows replace the table, and in the other modes
    they are merged into it. *import_writes* says when the fake writes SC_.mdb. ``answer``
    writes it when the answer shows, ``ok`` when the answer's OK is pressed, and ``late``
    ``LATE_WRITE_POLLS`` polls after the answer closes. With *mode_takes* off, a press on a
    mode's radio button does not change the checked mode. *import_as* names the mode that
    CLICK imports in, whichever mode is checked. With *import_box* set to ``"question"``,
    CLICK shows a Yes/No box in place of the answer. With ``"twice"``, it shows the answer
    a second time after the first is closed. ``imported`` lists the mode and the file name
    of each import.

    File > Export > Nickname opens a Save As dialog. Save shows a progress window titled
    "frmProgress", then writes the export and shows a box titled "Export Database". These
    windows are those of the comment at ``EXPORT_SAVE``. The export holds the fake's SC_.mdb
    rows as CP1252 text with CR LF line ends, as CLICK wrote them in live runs on 2026-11-18,
    or *export_bytes* if given. With *export_writes* off, the export writes no file. *export_box* is
    ``completed`` for the box reading "Completed!" with OK, ``question`` for a Yes/No box,
    ``other`` for a box with OK and another text, ``disabled`` for the "Completed!" box that
    stays disabled, or None for no box. *create_prompt* is the box in which Windows asks
    whether to create the file, before the progress window: ``windows`` for Windows' wording
    with Yes and No, ``text`` for a text that does not name the file, ``buttons`` for the
    file's name with OK and Cancel, ``exists`` for Windows' wording after an empty file has
    appeared at the path, or None for no box.
    ``exported`` lists the path of each export. With *shadow*, a drop shadow (``SysShadow``,
    no title, no owner) shows while a Save As dialog is open. A paste moves the cursor down
    by *paste_rungs*, the number of rungs that the test pastes (RUNG_CSV has one).

    PLC > Read Data from PLC opens CLICK's form, Save dialog and progress window. With
    *writes_data* off, the reading writes no file. With *save_clears*, the Save dialog
    empties its File name edit a few polls after it shows. Real CLICK did this once. If the
    edit is empty when the reading runs, CLICK writes ``plcdata.csv`` into the folder that
    it last saved in (``last_folder``). Program > Address Picker opens a grid. Two Right
    keys and then F2 open the editor on the current row's Nickname cell. The Find box moves
    to an address's row. Enter keeps the name in the editor unless it is a reserved word
    (``RESERVED``). OK writes the kept names into SC_.mdb with CLICK's system rows
    (``SYSTEM_ROWS``). Closing the Picker without OK writes nothing. That matches real
    CLICK for a Picker closed with nothing typed. Nobody has closed it that way after
    typing.

    Startup's left button opens Select a CPU Module, as a live run on 2026-11-20 dumped it.
    Its list box lists *cpu_list*, and its OK makes a project for the CPU selected. For a
    CLICK PLUS CPU, and for a CPU whose name holds "E-" (an Ethernet CPU), User Account Setup
    shows first. Live runs showed it for C0-11DD1E-D, C2-03CPU and C2-03CPU-2. Its OK shows the
    error box GUI-153, and its Cancel makes the project. The project's Project.ini then names
    that CPU in [Sec21], or the CPU *saved_cpu* if given. With *lists_follow_keys* off, Down
    does not move the list's selection. With *user_accounts* True or False, User Account Setup
    shows for every CPU or for none. With *accounts_cancel* off, it has no Cancel.

    Cancel in Select a CPU Module enables Startup again, and the main window stays disabled.
    WM_CLOSE to Startup then closes it and enables the main window, on a project with no CPU.
    Live runs on 2026-11-20 showed both. The Project.ini then has no [Sec21], or names
    *saved_cpu* if given. With *cancel_first* "form" or "startup", the Cancel makes that change
    first: it removes the form, or it enables Startup. It makes the other change 3 polls later.

    File > New Project asks "Save changes to <path>?" (Yes 6, No 7, Cancel 2) unless the
    project was saved, as live runs on 2026-11-21 showed. *new_box* gives that box another
    text, other buttons as (text, id, enabled), and controls of other classes. With
    *new_second_box*, No shows a second box before the project unloads. No, or no box,
    empties the temp folder, titles the main window bare and shows Startup. The CPU's OK
    closes Startup and writes Project.ini. ``NEW_MDB_POLLS`` polls later the fake writes
    SC_.mdb (event ``new_mdb``). *new_title_polls* polls after that it titles the main window
    "NewProject1.ckp" (event ``new_title``). *new_writes* is how many times it writes SC_.mdb
    again, each ``NEW_WRITE_POLLS`` polls after the last (event ``new_mdb_again``).
    """

    def __init__(
        self,
        tmp_path: Path,
        *,
        guide: bool = True,
        login: bool = True,
        prefilled_user: str = "admin",
        password: str = "123click",
        plc_rows: int = 1,
        late_row: float | None = None,
        same_lan: bool = True,
        tooltip: bool = False,
        startup_buttons: int = 3,
        dont_read_takes: bool = True,
        splash: bool = False,
        surprise: str | None = None,
        error_on: str | None = None,
        cpu_type: int = 0,
        cpu_type_box: tuple[str, tuple[str, ...]] | None = None,
        cpu_type_extra: tuple[str, str] | None = None,
        cpu_type_slow: int = 0,
        stall: str | None = None,
        interrupt: str | None = None,
        fail: str | None = None,
        lag: int = 2,
        hang_on: str | None = None,
        hang_for: float = 0.0,
        status_bar: bool = True,
        plc_pane: bool = True,
        leftover: tuple[str, ...] = (),
        desktop_name: str | None = "Default",
        running: tuple[int, ...] = (),
        open_windows: tuple[int, ...] = (),
        judge: Callable[[str, str | None, dict[str, str]], object] | None = None,
        delete_works: bool = True,
        syntax_lines: dict[str, str] | None = None,
        opens_with: dict[int, int] | None = None,
        places: bool = True,
        box_on_fill: str | None = None,
        quick_checks: int = 0,
        import_answer: Callable[[bytes], tuple[dict[str, dict], str | None]] | None = None,
        import_writes: str = "answer",
        mode_takes: bool = True,
        import_box: str | None = None,
        import_as: str | None = None,
        writes_data: bool = True,
        open_gap: int = 0,
        save_clears: bool = False,
        system_config_notice: bool = False,
        ansi_fields: bool = False,
        lists_follow_keys: bool = True,
        list_on_fill: tuple[str, str] | None = None,
        mode_resets_on_fill: bool = False,
        lost_presses: int = 0,
        slow_options: bool = False,
        copies: bool = True,
        ladder_views: int = 1,
        sticky_boxes: int = 0,
        clipboard_held: int = 0,
        paste_rungs: int = 1,
        shadow: bool = False,
        export_bytes: bytes | None = None,
        export_writes: bool = True,
        export_box: str | None = "completed",
        create_prompt: str | None = None,
        cpu_list: tuple[str, ...] = cr.CPU_MODELS,
        saved_cpu: str | None = None,
        user_accounts: bool | None = None,
        accounts_cancel: bool = True,
        cancel_first: str | None = None,
        new_box: tuple[str, tuple[tuple[str, int, bool], ...], tuple[str, ...]] | None = None,
        new_second_box: bool = False,
        new_title_polls: int = 5,
        new_writes: int = 0,
    ) -> None:
        self.temp_root = tmp_path / "temp"
        self.temp_root.mkdir()
        self.options = {
            "guide": guide,
            "login": login,
            "prefilled_user": prefilled_user,
            "password": password,
            "plc_rows": plc_rows,
            "plc_pane": plc_pane,
            "leftover": leftover,
            "late_row": late_row,
            "same_lan": same_lan,
            "tooltip": tooltip,
            "startup_buttons": startup_buttons,
            "dont_read_takes": dont_read_takes,
            "splash": splash,
        }
        self.surprise, self.stall = surprise, stall
        self.error_on = error_on
        self.error_answered = False
        self.cpu_type = cpu_type
        self.cpu_type_box = cpu_type_box or (CPU_TYPE_TEXT, ("OK",))
        self.cpu_type_extra = cpu_type_extra
        self.cpu_type_slow = cpu_type_slow
        self.cpu_type_shown = 0
        self.cpu_type_closed_at: list[float] = []  # The runner's clock as each box closed
        self.went_offline = False
        self.interrupt, self.fail = interrupt, fail
        self.lag = lag
        self.hang_on, self.hang_for = hang_on, hang_for
        self.hung_until = 0.0
        self.sent_while_hung: list[str] = []
        self.status_readable = status_bar
        self.cursor_rung, self.steps = 1, 0
        self.late_row_at: float | None = None
        self.desktop_name = desktop_name
        self.running, self.open_windows = running, open_windows
        self.pid: int | None = None
        self.is_running = False
        self.terminated = False
        self.exited_cleanly = False
        self.read_from_plc = False
        self.connected = False
        self.saved = False
        self.pasted: bytes | None = None
        self.clipboard: bytes | None = None
        self.copy_payload: bytes | None = None  # None makes Edit > Copy use RUNG_CSV's payload
        self.commands: list[str] = []
        self.keys: list[tuple[str, int | str]] = []
        self.pressed: list[str] = []
        self.typed: dict[int, str] = {}
        self.events: list[str] = []
        self.wins: dict[int, FakeWindow] = {}
        self.tick = 0
        self.queue: list[tuple[int, Callable[[], None]]] = []
        self._next = 1000
        self.main: FakeWindow | None = None
        self.output: FakeControl | None = None
        self.judge = judge or judge_like_click
        self.delete_works = delete_works
        self.syntax_lines = syntax_lines or {}
        self.opens_with = opens_with or {}
        self.places = places
        self.box_on_fill = box_on_fill
        self.quick_checks = quick_checks
        self.checked_tick: int | None = None  # The poll that showed the last check's result
        self.rung: list[str] = []  # The titles of the instructions in rung 1, as placed
        self.cursor_column = "A"
        self.rung_selected = False
        self.clicks: list[tuple[int, int]] = []
        self.copied: list[list[str]] = []  # The rung each Edit > Copy copied
        self.option_states: list[dict[int, int]] = []  # The option states at each OK, by id
        self.lost_presses = lost_presses
        self.slow_options = slow_options
        self.busy_until = 0.0  # ``idle`` returns False until this time
        self.copies = copies
        self.ladder_views = ladder_views
        self.sticky_boxes = sticky_boxes
        self.clipboard_held = clipboard_held
        self.on_dialog: Callable[[FakeWindow], None] | None = None  # Run as a dialog opens
        self.entered: list[tuple[str, str | None, dict[str, str]]] = []
        self.import_answer = import_answer or import_like_click
        self.import_writes = import_writes
        self.mode_takes = mode_takes
        self.import_box = import_box
        self.import_as = import_as
        self.imported: list[tuple[str, str]] = []
        self.writes_data = writes_data
        self.open_gap = open_gap
        self.save_clears = save_clears
        self.system_config_notice = system_config_notice
        self.system_config_shown = False
        self.ansi_fields = ansi_fields
        self.lists_follow_keys = lists_follow_keys
        # If set, the Receive dialog's Function Code goes back to 01 whenever a field is set
        self.list_on_fill = list_on_fill
        self.mode_resets_on_fill = mode_resets_on_fill
        self.stuck_list: FakeControl | None = None  # A list that ignores its keys
        self.mode_radios: list[int] = []  # The open dialog's mode buttons, in order
        self.receive_lists: dict[str, FakeControl] = {}
        self.last_folder = tmp_path / "last folder"
        self.editor_keys: Callable[[int], None] = lambda vk: None
        self.ckps: dict[Path, dict[str, bytes]] = {}  # Each saved project's files
        self.paste_rungs = paste_rungs
        self.shadow = shadow
        self.export_bytes = export_bytes
        self.export_writes = export_writes
        self.export_box = export_box
        self.create_prompt = create_prompt
        self.exported: list[Path] = []
        self.opened: list[Path] = []
        self.cpu_list = cpu_list
        self.saved_cpu = saved_cpu
        self.user_accounts = user_accounts
        self.accounts_cancel = accounts_cancel
        self.cancel_first = cancel_first
        self.new_box = new_box
        self.new_second_box = new_second_box
        self.new_title_polls = new_title_polls
        self.new_writes = new_writes
        self.new_mdb_writes: list[int] = []  # The tick of each write of SC_.mdb after File > New
        self.cpu: str | None = None  # The CPU of the project that the wizard made

    @property
    def placed(self) -> str | None:
        """Return the title of the instruction placed last in rung 1."""
        return self.rung[-1] if self.rung else None

    @placed.setter
    def placed(self, title: str | None) -> None:
        self.rung = [title] if title else []

    # -- building windows ---------------------------------------------------

    def _hwnd(self) -> int:
        self._next += 2
        return self._next

    def _window(self, cls: str, title: str, owner: int, **kw) -> FakeWindow:
        window = FakeWindow(self._hwnd(), cls, title, owner, **kw)
        self.wins[window.hwnd] = window
        return window

    def _control(self, window: FakeWindow, cls: str, text: str, id: int, *, parent: int = 0, **kw):
        control = FakeControl(self._hwnd(), parent or window.hwnd, cls, text, id, **kw)
        window.controls.append(control)
        return control

    def _drop(self, window: FakeWindow | None) -> None:
        if window is not None:
            self.wins.pop(window.hwnd, None)
            if window.on_drop is not None:
                window.on_drop()

    def _later(self, event: str, action: Callable[[], None], polls: int | None = None) -> None:
        """Run *action* *polls* polls from now, or ``lag`` polls if *polls* is None.

        A message posted to CLICK also takes effect on a later poll."""

        def run() -> None:
            if event == self.stall:
                return
            action()
            self.events.append(event)
            if event == self.hang_on:
                self.hung_until = cr.time.monotonic() + self.hang_for
            if event == self.surprise:
                assert self.main is not None
                self._window("#32770", "Set a Project Password", self.main.hwnd)
            if event == self.error_on:
                self._show_error(event)

        self.queue.append((self.tick + (self.lag if polls is None else polls), run))

    def _show_error(self, event: str) -> None:
        """Show CLICK's PTC-013 error box, which reports a timeout while connecting to the PLC."""
        assert self.main is not None
        owner = self.connect_dialog if event == "connect" else self.main
        box = self._window("#32770", "CLICK Programming Software", owner.hwnd)

        def answered() -> None:
            self.error_answered = True

        self._control(box, "Button", "OK", 2, on_press=answered)
        self._control(box, "Static", "", 20)
        self._control(box, "Static", "PTC-013\nTimeout on attempting to connect to PLC.", 65535)

    def _check(self, method: str) -> None:
        if method == self.interrupt:
            self.interrupt = None  # Raise only once, like one Ctrl+C
            raise KeyboardInterrupt
        if method == self.fail:
            raise OSError(f"{method} failed")

    # -- CLICK's dialogs ------------------------------------------------------

    def _launch_windows(self) -> None:
        if self.options["splash"]:
            splash = self._window("TfrmSplash", "", 0)

            def show_main() -> None:
                self._show_main()
                self._later("splash", lambda: self._drop(splash))

            self._later("main", show_main)
        else:
            self._show_main()

    def _show_main(self) -> None:
        main = self._window(
            MAIN_CLASS,
            "CLICK Programming Software (Version4.00) - NewProject4.ckp - [Main Program]",
            0,
            enabled=False,
        )
        self.main = main
        bar = self._control(main, OUTPUT_BAR, "Output", 32911, visible=False)
        self.output = self._control(main, "Edit", "", 1005, parent=bar.hwnd, visible=False)
        floating = self._control(main, "Afx:002E0000:8:00010003:00100063:00000000", "Output", 158)
        self._control(main, "Edit", "", 1005, parent=floating.hwnd, visible=False)
        self._control(main, "Afx:StatusBar:2e0000:8:10003:10", "", 59393)
        self._control(main, "msctls_statusbar32", "", 59393)
        # The visible ladder views, and a hidden one behind them
        for _ in range(self.ladder_views):
            self._control(main, cd.LADDER_VIEW_CLASS, "", 59648)
        self._control(main, cd.LADDER_VIEW_CLASS, "", 59649, visible=False)
        main.on_close = self._close_main
        temp = self.temp_dir(main.hwnd)
        temp.mkdir()
        (temp / "SC_.mdb").write_bytes(b"mdb")
        (temp / "Project.ini").write_bytes(b"[Project]\r\n")
        for name in self.options["leftover"]:
            (temp / name).write_bytes(b"old")
        if self.options["tooltip"]:
            self._window("tooltips_class32", "", main.hwnd)
            self._window("tooltips_class32", "Paste", 0)
        if self.options["guide"]:
            guide = self._window("#32770", "What’s New Feature Guide", main.hwnd)
            self._control(guide, "Button", "Next", 1003)
            guide.on_close = lambda: self._later("guide", lambda: self._close_guide(guide))
        else:
            self._show_startup()

    def _close_guide(self, guide: FakeWindow) -> None:
        self._drop(guide)
        self._show_startup()

    def _show_startup(self) -> None:
        assert self.main is not None
        startup = self._window("TfrmStartup", "Startup", self.main.hwnd)
        group = self._control(startup, "TGroupBox", "Select an Operation", 0)
        # CLICK lists the three buttons in this order: middle, right, left
        lefts = {"middle": 891, "right": 1035, "left": 747}
        for name in list(lefts)[: self.options["startup_buttons"]]:
            if name == "right":
                action = lambda s=startup: self._later("startup", lambda: self._show_connect(s))
            elif name == "left":
                action = lambda s=startup: self._later("cpu", lambda: self._select_cpu(s))
            else:
                action = None  # Open an existing project, which no test presses
            self._control(
                startup,
                "TButton",
                "",
                0,
                parent=group.hwnd,
                rect=(lefts[name], 466, lefts[name] + 135, 601),
                on_press=action,
            )
        self._control(startup, "TButton", "Close", 0)
        self._control(startup, "TButton", "Help", 0)
        for control in startup.controls:
            control.id = control.hwnd  # A Delphi control's id is its hwnd

    def _select_cpu(self, startup: FakeWindow) -> None:
        """Show Select a CPU Module, owned by Startup, with the first CPU selected.

        A key sent to the list box moves its selection. OK makes the project for the CPU
        selected. For some CPUs, User Account Setup shows first."""
        startup.enabled = False
        form = self._window("TfrmCPU", "Select a CPU Module", startup.hwnd)
        self._control(form, "TComboBox", "", 0, value="ALL")
        self._control(form, "TTntListView.UnicodeClass", "", 0)
        self._control(form, "TMemo", "", 0)
        self._control(form, "TEdit", "", 0)
        cpus = self._control(form, "TListBox", "", 0, options=list(self.cpu_list), selected=0)

        def key(vk: int) -> None:
            if vk == cr._VIRTUAL_KEYS["HOME"]:
                cpus.selected = 0
            elif vk == cr._VIRTUAL_KEYS["DOWN"] and self.lists_follow_keys:
                cpus.selected = min(cpus.selected + 1, len(cpus.options) - 1)

        def ok() -> None:
            model = cpus.options[cpus.selected]
            self._drop(form)
            # Live runs showed User Account Setup for C2-03CPU, C2-03CPU-2 and C0-11DD1E-D, and
            # not for C0-02DD1-D. The fake extends that to every PLUS and Ethernet CPU
            accounts = model.startswith("C2-") or "E-" in model
            if accounts if self.user_accounts is None else self.user_accounts:
                self._show_user_accounts(startup, model)
            else:
                self._made_project(startup, model)

        def cancel() -> None:
            startup.on_close = lambda: self._later("startup_close", lambda: close(startup))

            def drop() -> None:
                self._drop(form)

            def enable() -> None:
                startup.enabled = True

            if self.cancel_first is None:
                drop()
                enable()
            elif self.cancel_first == "form":
                drop()
                self._later("startup_enabled", enable, 3)
            else:
                enable()
                self._later("form_dropped", drop, 3)

        def close(startup: FakeWindow) -> None:
            assert self.main is not None
            self._drop(startup)
            if self.saved_cpu is not None:
                self._write_sec21(self.saved_cpu)
            self.main.enabled = True

        cpus.on_key = key
        self._control(form, "TButton", "OK", 0, on_press=lambda: self._later("cpu_ok", ok))
        self._control(
            form, "TButton", "Cancel", 0, on_press=lambda: self._later("cpu_cancel", cancel)
        )
        self._control(form, "TButton", "Help", 0)
        for control in form.controls:
            control.id = control.hwnd  # A Delphi control's id is its hwnd

    def _show_user_accounts(self, startup: FakeWindow, model: str) -> None:
        """Show User Account Setup. OK shows the error box GUI-153. Cancel makes the project."""
        dialog = self._window("TfrmUserAccountsSetupDlg", "User Account Setup", startup.hwnd)

        def ok() -> None:
            dialog.enabled = False
            box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)
            self._control(box, "Button", "OK", 2)
            self._control(box, "Static", "", 20)
            self._control(box, "Static", "GUI-153\nadmin password setting is required.", 65535)

        def cancel() -> None:
            self._drop(dialog)
            self._made_project(startup, model)

        tnt = "TTntButton.UnicodeClass"
        self._control(dialog, "TTntCheckBox.UnicodeClass", "Disable Password Requirement", 0)
        self._control(dialog, tnt, "Password Setting", 0)
        self._control(dialog, tnt, "OK", 0, on_press=lambda: self._later("accounts_ok", ok))
        if self.accounts_cancel:
            self._control(
                dialog, tnt, "Cancel", 0, on_press=lambda: self._later("accounts_cancel", cancel)
            )
        self._control(dialog, tnt, "Help", 0)
        for control in dialog.controls:
            control.id = control.hwnd

    def _made_project(self, startup: FakeWindow, model: str) -> None:
        """Close Startup and make the project for *model*, as CLICK writes its [Sec21].

        After File > New Project, the fake then writes SC_.mdb, names the project in the
        title, and writes SC_.mdb *new_writes* more times, each some polls after the last.
        """
        assert self.main is not None
        main = self.main
        self._drop(startup)
        self.cpu = model
        self._write_sec21(self.saved_cpu or model)
        if cr._project_file(main.title) is None:
            mdb = self.temp_dir(main.hwnd) / "SC_.mdb"

            def write(count: int) -> None:
                mdb.write_bytes(b"new mdb" + b"!" * count)
                if count:
                    self.new_mdb_writes.append(self.tick)
                if count < self.new_writes:
                    self._later("new_mdb_again", lambda: write(count + 1), NEW_WRITE_POLLS)

            def title() -> None:
                main.title = (
                    "CLICK Programming Software (Version4.00) - NewProject1.ckp - [Main Program]"
                )

            self._later("new_mdb", lambda: write(0), NEW_MDB_POLLS)
            self._later("new_title", title, NEW_MDB_POLLS + self.new_title_polls)
        main.enabled = True

    def _file_new(self) -> None:
        """Ask whether to save unless the project was saved, then unload it and show Startup."""
        assert self.main is not None
        main = self.main

        def unload() -> None:
            main.title = "CLICK Programming Software (Version4.00)"
            main.enabled = False
            for path in self.temp_dir(main.hwnd).iterdir():
                path.unlink()
            self._show_startup()

        if self.saved and self.new_box is None:
            unload()
            return
        main.enabled = False
        text, buttons, others = self.new_box or (SAVE_CHANGES_TEXT, SAVE_CHANGES_BUTTONS, ())
        box = self._window("#32770", "CLICK Programming Software", main.hwnd)
        for name, id, enabled in buttons:

            def press(name: str = name) -> None:
                self._drop(box)
                if name != "&No":
                    main.enabled = True
                elif self.new_second_box:
                    second = self._window("#32770", "CLICK Programming Software", main.hwnd)
                    self._control(second, "Static", "Could not close the project.", 65535)
                    self._control(second, "Button", "OK", 2)
                else:
                    self._later("file_new_no", unload)

            button = self._control(box, "Button", name, id, on_press=press)
            button.enabled = enabled
        self._control(box, "Static", "", 20)
        self._control(box, "Static", text, 65535)
        for cls in others:
            self._control(box, cls, "", 1000)

    def _write_sec21(self, saved: str) -> None:
        """Write a Project.ini whose [Sec21] names the CPU *saved*, as CLICK writes it."""
        assert self.main is not None
        # Key3_1 is the CPU. Key3_10 and Key3_11 are the option slots, and CLICK fills each
        # slot that a CLICK PLUS CPU has with C2-FILL (8192)
        modules = [0] * 12
        modules[1] = CPU_IDS[saved]
        if saved.startswith("C2-"):
            modules[10] = 8192
            if saved.endswith("-2"):
                modules[11] = 8192
        lines = ["[Sec21]", "Key4=0", "Key1=0", "Key2=1"]
        lines += [f"Key3_{n}={module}" for n, module in enumerate(modules)]
        lines += ["[Sec24]", f"Key1={CPU_IDS[saved]}"]
        ini = "".join(f"{line}\r\n" for line in lines)
        (self.temp_dir(self.main.hwnd) / "Project.ini").write_bytes(ini.encode("ascii"))

    def _show_connect(self, startup: FakeWindow) -> None:
        startup.enabled = False
        dialog = self._window("#32770", "Connect to CLICK PLC", startup.hwnd)
        self.connect_dialog = dialog
        same_lan = self.options["same_lan"]
        self._control(
            dialog,
            "Button",
            "In the same LAN (Scan all CLICK PLCs in the LAN automatically.)",
            20059,
            checked=int(same_lan),
        )
        self._control(
            dialog,
            "Button",
            "Outside this LAN (You need to allocate IP address and port number manually.)",
            20060,
            checked=int(not same_lan),
        )
        plcs = self._control(dialog, "SysListView32", "List1", 20061)
        self._control(dialog, "Button", "Refresh", 20027)
        self._control(
            dialog,
            "Button",
            "Connect",
            1,
            on_press=lambda: self._later("connect", self._after_connect),
        )
        self._control(dialog, "Button", "Cancel", 2)

        # The PLC list is owner-drawn. CLICK paints its own highlight and reports no
        # selection.
        def scanned() -> None:
            plcs.items = self.options["plc_rows"]
            if self.options["late_row"] is not None:
                self.late_row_at = cr.time.monotonic() + self.options["late_row"]

        self._later("scan", scanned)

    def _after_connect(self) -> None:
        self.connect_dialog.enabled = False
        if self.error_on == "connect":
            return  # The PLC did not answer, and CLICK shows its error box in place of Login
        if self.cpu_type_shown < self.cpu_type:
            self._show_cpu_type_box()
            return
        if self.options["login"]:
            self._show_login()
        else:
            self._show_read_prompt()

    def _show_cpu_type_box(self) -> None:
        """Show the box that says CLICK could not read the CPU type, as the Connect dialog's.

        Its OK closes it, and the Connect dialog is enabled again. With *cpu_type_slow*, the
        box closes that many polls after the press, and the dialog is enabled that many polls
        after the box closes."""
        self.cpu_type_shown += 1
        text, buttons = self.cpu_type_box
        box = self._window("#32770", "CLICK Programming Software", self.connect_dialog.hwnd)
        slow = self.cpu_type_slow or None

        def enabled() -> None:
            self.connect_dialog.enabled = True

        def closed() -> None:
            self._drop(box)
            self.cpu_type_closed_at.append(cr.time.monotonic())
            if slow is None:
                enabled()
            else:
                self._later("cpu_type_enabled", enabled, slow)

        for number, label in enumerate(buttons, 2):
            self._control(
                box,
                "Button",
                label,
                number,
                on_press=lambda: self._later("cpu_type_ok", closed, slow),
            )
        self._control(box, "Static", "", 20)
        self._control(box, "Static", text, 65535)
        if self.cpu_type_extra is not None:
            self._control(box, self.cpu_type_extra[0], self.cpu_type_extra[1], 1001)

    def _show_login(self) -> None:
        login = self._window("#32770", "Login", self.connect_dialog.hwnd)
        user = self._control(login, "Edit", "", 20141, value=self.options["prefilled_user"])
        password = self._control(login, "Edit", "", 20142)
        failed = self._control(login, "Static", "Failed login attempt : 1", 20144, visible=False)
        self._control(login, "Static", 'Factory Default Password = "click"', 20149)

        def ok() -> None:
            if user.value and password.value == self.options["password"]:
                self._drop(login)
                self._show_read_prompt()
            else:
                failed.visible = True

        self._control(login, "Button", "OK", 18002, on_press=lambda: self._later("login", ok))
        self._control(login, "Button", "Cancel", 18003)

    def _show_read_prompt(self) -> None:
        prompt = self._window("#32770", "Connect", self.connect_dialog.hwnd)
        self._control(prompt, "Static", "Do you want to read the project from the PLC?", 65535)
        read = self._control(prompt, "Button", "Read the project from the PLC.", 1027, checked=1)
        dont = self._control(prompt, "Button", "Don't read the project from the PLC.", 1028)

        def choose_dont_read() -> None:
            if self.options["dont_read_takes"]:
                read.checked, dont.checked = 0, 1

        def ok() -> None:
            if read.checked:
                self.read_from_plc = True
            for window in list(self.wins.values()):
                if window is not self.main:
                    self._drop(window)
            assert self.main is not None
            self.main.enabled = True
            self.connected = True

        dont.on_press = lambda: self._later("dont_read_choice", choose_dont_read)
        self._control(prompt, "Button", "OK", 1, on_press=lambda: self._later("dont_read", ok))
        self._control(prompt, "Button", "Cancel", 2)

    def _show_save_dialog(self) -> tuple[FakeWindow, FakeControl]:
        """Show a Save As dialog owned by the main window, and return it and its File name edit.

        With *shadow*, a drop shadow shows with the dialog and goes when the dialog goes.
        """
        assert self.main is not None
        self.main.enabled = False
        dialog = self._window("#32770", "Save As", self.main.hwnd)
        self._control(dialog, "ComboBox", "", 1137)
        box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
        box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
        name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)
        if self.shadow:
            shadow = self._window("SysShadow", "", 0)
            dialog.on_drop = lambda: self._drop(shadow)
        return dialog, name

    def _show_save_as(self) -> None:
        assert self.main is not None
        main = self.main
        dialog, name = self._show_save_dialog()

        def save() -> None:
            path = Path(name.value)
            path.write_bytes(b"ckp")
            # The main program holds what was pasted, or else what ``try`` placed in rung 1
            placed = f"placed {self.placed} ({path.name})".encode() if self.placed else None
            scr = self.pasted or placed or b"empty"
            temp = self.temp_dir(main.hwnd)
            (temp / "Scr1.tmp").write_bytes(scr)
            # The project file holds the temp folder's files as they are
            self.ckps[path] = {p.name: p.read_bytes() for p in temp.iterdir()}
            main.title = f"CLICK Programming Software (Version4.00) - {path.name} - [Main Program]"
            self._drop(dialog)
            main.enabled = True
            self.saved = True

        self._control(dialog, "Button", "&Save", 1, on_press=lambda: self._later("save", save))
        self._control(dialog, "Button", "Cancel", 2)

    def _show_open_project(self) -> None:
        """Show File > Open Project's Open dialog.

        Opening puts the project's files in the temp folder.

        With *open_gap*, Open closes the dialog at once. For *open_gap* polls after that, the
        main window is enabled, has no dialog and keeps its old title. Then the open begins.
        """
        assert self.main is not None
        main = self.main
        main.enabled = False
        dialog = self._window("#32770", "Open", main.hwnd)
        box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
        box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
        name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)

        def read_file() -> None:
            # While CLICK reads the project, the main window's title names no project, and
            # CLICK shows Project Reading
            self._drop(dialog)
            main.title = "CLICK Programming Software (Version4.00)"
            reading = self._window("#32770", "Project Reading", main.hwnd)
            self._later("read", lambda: open_file(reading))

        def open_file(reading: FakeWindow) -> None:
            path = Path(name.value)
            temp = self.temp_dir(main.hwnd)
            for old in temp.iterdir():
                if old.name != "SC_.mdb":
                    old.unlink()
            for file, data in self.ckps[path].items():
                (temp / file).write_bytes(data)
            self.opened.append(path)
            main.title = f"CLICK Programming Software (Version4.00) - {path.name} - [Main Program]"
            self._drop(reading)
            main.enabled = True

        def press_open() -> None:
            if not self.open_gap:
                self._later("open", read_file)
                return
            self._drop(dialog)
            main.enabled = True

            def begin() -> None:
                main.enabled = False
                read_file()

            self._later("open_begins", begin, polls=self.open_gap)

        self._control(dialog, "Button", "&Open", 1, on_press=press_open)
        self._control(dialog, "Button", "Cancel", 2)

    def _show_read_data(self) -> None:
        assert self.main is not None
        main = self.main
        main.enabled = False
        form = self._window("TfrmReadWriteDataMemory", "Read Data from PLC", main.hwnd)
        group = self._control(form, "TGroupBox", "Select Read Memory Type", 0)
        banks = ("TXT", "CTD", "TD", "DF", "DH", "DD", "DS", "CT", "T", "C", "Y", "X")
        boxes = [
            self._control(
                form, "TCheckBox", bank, 0, parent=group.hwnd, checked=int(bank in "DS DD DH DF")
            )
            for bank in banks
        ]

        def every() -> None:
            for box in boxes:
                box.checked = 1

        def save() -> None:
            form.enabled = False
            dialog = self._window("#32770", "Save", form.hwnd)
            box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
            box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
            name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)
            if self.save_clears:

                def clear() -> None:
                    if dialog.hwnd in self.wins:
                        name.value = ""

                self._later("save_clears", clear, polls=self.lag + 3)

            def read() -> None:
                self._drop(dialog)
                status = self._window(
                    "TfrmReadWriteDataMemoryStatus", "Data Memory Reading..", form.hwnd
                )

                def done() -> None:
                    if self.writes_data:
                        read = [b.text.encode() for b in reversed(boxes) if b.checked]
                        path = Path(name.value) if name.value else self.last_folder / "plcdata.csv"
                        path.parent.mkdir(exist_ok=True)
                        path.write_bytes(
                            b"".join(b"<%s=START>\r\n</%s=END>\r\n" % (b, b) for b in read)
                        )
                    self._drop(status)
                    form.enabled = True

                self._later("reading", done)

            self._control(dialog, "Button", "&Save", 1, on_press=lambda: self._later("save", read))
            self._control(dialog, "Button", "Cancel", 2)

        def close() -> None:
            self._drop(form)
            main.enabled = True

        for text, action in (("Read", save), ("Close", close), ("Help", None), ("All", every)):
            self._control(
                form,
                "TButton",
                text,
                0,
                parent=group.hwnd if text == "All" else 0,
                on_press=None if action is None else lambda a=action: self._later("press", a),
            )
        for control in form.controls:
            control.id = control.hwnd  # A Delphi form's controls have no ids of their own

    def _show_system_config(self) -> None:
        """Show CLICK's System Configuration form.

        Its PLC Name edit shows the first Key1 of the first [Sec20] section in the temp
        folder's Project.ini (``plc_name_in``). In a real run, CLICK showed the added name at
        the ``second`` point, before any open. That run cannot tell whether the save or System
        Configuration read the name from Project.ini. With *system_config_notice*, a notice
        with one OK button covers the first System Configuration form. Real CLICK showed that
        notice over a first form opened while connected, and not over one opened disconnected.
        The runner must never press OK, and a press fails the test.
        """
        assert self.main is not None
        main = self.main
        main.enabled = False
        form = self._window("TfrmSystemConfig", "System Configuration", main.hwnd)
        ini = self.temp_dir(main.hwnd) / "Project.ini"
        name = plc_name_in(ini.read_bytes() if ini.is_file() else b"")
        self._control(form, "TEdit", "", 0, value=name)
        self._control(form, "TCheckBox", "Start-up I/O Config Check", 0)

        def ok() -> None:
            raise AssertionError("System Configuration's OK was pressed")

        def cancel() -> None:
            self._drop(form)
            main.enabled = True

        for text, action in (("View I/O MODBUS Addresses", None), ("OK", ok), ("Cancel", cancel)):
            self._control(
                form,
                "TButton",
                text,
                0,
                on_press=None if action is None else lambda a=action: self._later("press", a),
            )
        if self.system_config_notice and not self.system_config_shown:
            self.system_config_shown = True
            form.enabled = False
            notice = self._window(
                "TfrmInformationSystemConfigDlg", "System Configuration", form.hwnd
            )
            self._control(notice, "TButton", "OK", 0, on_press=ok)

            def close() -> None:
                self._drop(notice)
                form.enabled = True

            notice.on_close = lambda: self._later("notice_close", close)
        for control in form.controls:
            control.id = control.hwnd

    def _show_picker(self) -> None:
        assert self.main is not None
        main = self.main
        main.enabled = False
        picker = self._window("TfrmTagDB", "Address Picker : Edit Mode", main.hwnd)
        mdb = self.temp_dir(main.hwnd) / "SC_.mdb"
        at: dict[str, Any] = {"row": "X001", "column": 0}
        taken: dict[str, str] = {}
        editor: list[FakeControl] = []
        grid = self._control(picker, "TStringGrid", "", 0)

        def key(vk: int) -> None:
            if vk == 0x27:
                at["column"] += 1
            elif vk == 0x71 and at["column"] == 2 and not editor:
                editor.append(self._control(picker, "TEdit", "", 0, parent=grid.hwnd))

        def enter(vk: int) -> None:
            if vk != 0x0D or not editor:
                return
            if editor[0].value.upper() not in RESERVED:
                taken[at["row"]] = editor[0].value
            editor[0].visible = False
            editor.clear()

        grid.on_key = key
        self.editor_keys = enter
        box = self._control(picker, "TComboBox", "", 0)
        find = self._control(picker, "Edit", "", 0, parent=box.hwnd)

        def found() -> None:
            at.update(row=find.value, column=0)

        def close() -> None:
            self._drop(picker)
            main.enabled = True

        def ok() -> None:
            rows = {address: dict(row) for address, row in SYSTEM_ROWS.items()}
            rows.update({address: {"Nickname": name} for address, name in taken.items()})
            mdb.write_text(json.dumps(rows), encoding="utf-8")
            close()

        picker.on_close = lambda: self._later("picker_close", close)
        for text, action in (("Find", found), ("OK", ok), ("Cancel", close)):
            self._control(
                picker,
                "TButton",
                text,
                0,
                on_press=lambda a=action: self._later("press", a),
                on_send=action,
            )
        for control in picker.controls:
            control.id = control.hwnd

    def _show_disconnect(self) -> None:
        assert self.main is not None
        main = self.main
        main.enabled = False
        prompt = self._window("#32770", "CLICK Programming Software", main.hwnd)
        self._control(prompt, "Static", "Disconnect from PLC?", 65535)

        def yes() -> None:
            self._drop(prompt)
            main.enabled = True
            self.connected = False
            self.went_offline = True

        self._control(
            prompt, "Button", "&Yes", 6, on_press=lambda: self._later("disconnect_yes", yes)
        )
        self._control(prompt, "Button", "&No", 7)

    def _close_main(self) -> None:
        def close() -> None:
            assert self.main is not None
            if not self.saved:
                self._window("#32770", "CLICK Programming Software", self.main.hwnd)
                return
            # CLICK unloads the project first, and its main window's title then names no project
            self.main.title = "CLICK Programming Software (Version4.00)"
            self._later("exit", exit)

        def exit() -> None:
            assert self.main is not None
            self.wins.clear()
            self.is_running = False
            self.exited_cleanly = True
            temp = self.temp_dir(self.main.hwnd)
            for path in temp.iterdir():
                path.unlink()
            temp.rmdir()

        self._later("close", close)

    def _show_instruction(self, spec: cr.Instruction) -> None:
        """Show the instruction dialog for *spec*, with its mode buttons, edits, OK and Cancel."""
        assert self.main is not None
        main = self.main
        title = spec.title
        dialog = self._window("#32770", title, main.hwnd)
        radios = {
            name: self._control(dialog, "Button", "", id, checked=int(index == 0))
            for index, (name, id) in enumerate(spec.modes.items())
        }
        self.mode_radios = list(spec.modes.values())
        self.stuck_list = None
        # One control per id. Drum's mode fields share some ids (a step's duration in Time
        # Base is its event in Event Base), so several names may lead to one control
        ids = {**spec.fields, **spec.read_only}
        for more in spec.mode_fields.values():
            ids.update(more)
        by_id: dict[int, FakeControl] = {}
        for name, id in ids.items():
            if id in by_id:
                continue
            if name == "formula":
                cls = "RichEdit20W"
            elif title == "Send" and name == "ip":
                cls = cd.IP_ADDRESS_CLASS
            else:
                cls = "Edit"
            by_id[id] = self._control(dialog, cls, "", id)
        edits = {name: by_id[id] for name, id in ids.items()}
        limits = {"Receive": RECEIVE_LIMITS, "Send": SEND_LIMITS}.get(title, {})
        filled = {"Receive": RECEIVE_FILLED, "Send": SEND_FILLED}.get(title, {})
        if title == "Drum":
            filled = {5021: "1", 5022: "1"}
        for id, edit in by_id.items():
            edit.limit = limits.get(id, 30000)
            edit.value = filled.get(id, "")
        if title == "Send":
            # The IP address control holds four Edits with its id. Windows lists them from
            # right to left
            ip = edits["ip"]
            for part in reversed(range(4)):
                left = 10 * part
                self._control(
                    dialog, "Edit", "", ip.id, parent=ip.hwnd, rect=(left, 0, left + 8, 8)
                )
        buttons: dict[int, FakeControl] = {}
        for id, (text, visible, enabled, checked) in OPTION_BUTTONS.get(title, {}).items():
            buttons[id] = self._control(
                dialog, "Button", text, id, visible=visible, enabled=enabled, checked=checked
            )
        for id, state in {**spec.opens_with, **self.opens_with}.items():
            if id in buttons:
                buttons[id].checked = state
            elif id not in spec.modes.values():
                buttons[id] = self._control(dialog, "Button", f"button {id}", id, checked=state)
        if title == "Copy":  # The Termination code field opens holding $00, and disabled
            edits["termination_code"].value = "$00"
            edits["termination_code"].enabled = False

        def follow_fields() -> None:
            # Copy's option buttons follow its fields. Compare hides its >, <, >= and <=
            # buttons when Data A holds a TXT address. Timer and Counter fill their
            # read-only fields from the number of the timer or counter.
            done = edits["done"].value if "done" in edits else ""
            if title == "Timer":
                edits["accumulator"].value = f"TD{done[1:]}" if done.startswith("T") else ""
            if title == "Counter":
                counter = done.startswith("CT")
                edits["accumulator"].value = f"CTD{done[2:]}" if counter else ""
                edits["completion_bit"].value = done if counter else ""
            if title == "Compare (A with B)":
                text = edits["a"].value.startswith("TXT")
                for name in (">", "<", ">=", "<="):
                    radios[name].visible = not text
            if title != "Copy":
                return
            labels, opened, zero, terminates = copy_options(
                edits["source"].value, edits["destination"].value
            )
            buttons[5019].text, buttons[5020].text = labels
            buttons[5019].enabled = buttons[5020].enabled = opened
            buttons[5036].visible = buttons[5037].visible = zero
            buttons[5021].enabled = terminates
            edits["termination_code"].enabled = terminates and buttons[5021].checked == 1

        radio_pairs = TIMER_RADIOS if title == "Timer" else OPTION_RADIOS

        def toggle(button: FakeControl) -> None:
            if button.id in radio_pairs:
                button.checked = 1
                buttons[radio_pairs[button.id]].checked = 0
            else:
                button.checked = 1 - button.checked
            if title == "Drum":  # Load New Step Number opens the step's field
                edits["jump_step"].enabled = buttons[5017].checked == 1
            follow_fields()

        def press_option(button: FakeControl) -> None:
            if self.lost_presses:
                self.lost_presses -= 1
                self.events.append("lost_press")
                return
            if self.slow_options:
                self.slow_options = False
                self.busy_until = cr.time.monotonic() + 1.5 * cr.OPTION_WAIT
            self._later("option", lambda: toggle(button))

        for id in spec.options:
            buttons[id].on_press = lambda b=buttons[id]: press_option(b)
        dialog.on_text = follow_fields
        lists = {}
        for name, list_id in spec.lists.items():
            items, selected = DIALOG_LISTS[title][list_id]
            lists[name] = self._control(
                dialog, "ComboBox", "", list_id, options=list(items), selected=selected
            )

        def key(combo: FakeControl, vk: int) -> None:
            # Home, Up and Down move a drop-down list's selection. The list tells the dialog
            # at once, with a sent CBN_SELCHANGE.
            if not self.lists_follow_keys or combo is self.stuck_list:
                return
            last = len(combo.options) - 1
            if vk == 0x24:
                combo.selected = 0
            elif vk == 0x28:
                combo.selected = min(combo.selected + 1, last)
            elif vk == 0x26:
                combo.selected = max(combo.selected - 1, 0)

        def follow_send() -> None:
            # Send's Function Code opens Number of Bits and Word Swap. Its port shows the
            # server's fields
            function = lists["function"].selected
            edits["count"].enabled = function in SEND_COUNT_FOR
            lists["word_swap"].enabled = function in SEND_WORD_SWAP_FOR
            shown = lists["port"].selected in SEND_IP_PORTS
            for name in ("ip", "server_port"):
                edits[name].visible = shown
            for child in dialog.controls:
                if child.parent == edits["ip"].hwnd:
                    child.visible = shown

        def follow(combo: FakeControl, vk: int) -> None:
            key(combo, vk)
            if title == "Send":
                if combo is lists["port"]:  # A port sets the Function Code to 06 again
                    lists["function"].selected = 1
                follow_send()
            elif combo is lists.get("function"):
                lists["word_swap"].enabled = combo.selected in WORD_SWAP_OPEN_FOR

        for combo in lists.values():
            combo.on_key = lambda vk, c=combo: follow(c, vk)
        if title == "Receive":
            lists["word_swap"].enabled = lists["function"].selected in WORD_SWAP_OPEN_FOR
        if title == "Send":
            follow_send()
        if title in ("Receive", "Send"):
            # The runner must never press this button, because it edits the port setup
            self._control(dialog, "Button", "COM Port Setup", 5013)
        if title == "Drum":
            edits["jump_step"].enabled = False
        self.receive_lists = lists

        def pick(name: str) -> None:
            for other, radio in radios.items():
                radio.checked = int(other == name)
            if title == "Math":  # Picking a type empties Result and the formula
                for edit in edits.values():
                    edit.value = ""
            # Each Copy mode disables one of the "to" fields, as CLICK does
            closed = {
                "single": ("source_end",),
                "pack": ("destination_end",),
                "unpack": ("source_end",),
            }
            if title == "Copy":
                for key, edit in edits.items():
                    if key != "termination_code":  # Its check box enables it
                        edit.enabled = key not in closed.get(name, ())
            if title == "Timer":  # OFF Delay cannot retain the current value
                for id in (5010, 5011):
                    buttons[id].enabled = name == "on_delay"
            if title == "Drum":
                # Event Base has no unit and no elapsed time, and it empties the step rows.
                # Time and Event shows a second column, for the durations
                events = name == "event_drum"
                lists["unit"].enabled = edits["accumulator"].enabled = not events
                if events:
                    lists["unit"].selected = 0
                for step in range(16):
                    if events:
                        by_id[5094 + step].value = ""
                    by_id[5130 + step].visible = name == "time_event_drum"

        for name, radio in radios.items():
            radio.on_press = lambda n=name: self._later("mode", lambda: pick(n))
        if radios:
            pick(next(iter(radios)))

        def ok() -> None:
            mode = next((n for n, r in radios.items() if r.checked), None)
            live = {**spec.fields_in(mode), **spec.read_only}
            values = {name: by_id[id].value for name, id in live.items() if by_id[id].value}
            values.update({name: c.options[c.selected] for name, c in lists.items()})
            self.entered.append((title, mode, values))
            self.option_states.append({id: buttons[id].checked for id in spec.options})
            answer = self.judge(title, mode, values)
            if answer is None:
                place()
            elif answer == "crash":
                self.is_running = False
                self.wins.clear()
            elif answer == "question":
                box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)
                self._control(box, "Static", "Replace the instruction?", 65535)
                self._control(box, "Button", "&Yes", 6)
                self._control(box, "Button", "&No", 7)
                dialog.enabled = False
            elif isinstance(answer, list):  # A chain of error boxes, one after another
                show_box(answer, 0, warn=False)
            else:
                show_box([answer[-2:]], 0, warn=answer[0] == "warn")

        def show_box(chain: list, index: int, *, warn: bool) -> None:
            # Show the error box *chain*[*index*]. Its OK shows the next box a few polls
            # later, and the last box's OK enables the dialog again (or, with *warn*, places
            # the instruction). While *sticky_boxes* lasts, CLICK ignores an OK press.
            code, message = chain[index]
            box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)

            def closed() -> None:
                self._drop(box)
                if index + 1 < len(chain):
                    self._later("next_box", lambda: show_box(chain, index + 1, warn=warn))
                elif warn:
                    place()
                else:
                    dialog.enabled = True

            def pressed() -> None:
                if self.sticky_boxes:
                    self.sticky_boxes -= 1
                    self.events.append("ok_ignored")
                    return
                self._later("box", closed)

            self._control(box, "Button", "OK", 2, on_press=pressed)
            self._control(box, "Static", "", 20)
            self._control(box, "Static", f"{code}\n{message}", 65535)
            dialog.enabled = False

        def place() -> None:
            if self.places:
                self.rung.append(title)
                self.cursor_column = "B" if title in CONTACT_TITLES else "AF"
                self.rung_selected = False
            self._drop(dialog)
            main.enabled = True

        def cancel() -> None:
            self._drop(dialog)
            main.enabled = True

        self._control(dialog, "Button", "OK", 1, on_press=lambda: self._later("ok", ok))
        self._control(dialog, "Button", "Cancel", 2, on_press=lambda: self._later("cancel", cancel))
        main.enabled = False
        if self.on_dialog is not None:
            self.on_dialog(dialog)

    def _show_open(self) -> None:
        """Show the Open dialog of File > Import > Nickname."""
        assert self.main is not None
        main = self.main
        main.enabled = False
        dialog = self._window("#32770", "Open", main.hwnd)
        self._control(dialog, "ComboBox", "", 1137)
        box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
        box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
        name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)
        self._control(dialog, "Button", "Open as &read-only", 1040, visible=False, enabled=False)
        # CLICK adds a panel of Delphi radio buttons to the dialog. Their ids are their hwnds.
        template = self._control(dialog, "#32770", "", 0)
        panel = self._control(dialog, "TPanel", "", 0, parent=template.hwnd)
        modes = {
            text: self._control(dialog, "TRadioButton", text, 0, parent=panel.hwnd)
            for text in ("Delete Existing", "Merge (File priority)", "Merge (Project priority)")
        }
        modes["Merge (Project priority)"].checked = 1
        for control in (panel, *modes.values()):
            control.id = control.hwnd

        def pick(text: str) -> None:
            if self.mode_takes:
                for other, radio in modes.items():
                    radio.checked = int(other == text)

        for text, radio in modes.items():
            radio.on_press = lambda t=text: self._later("import_mode", lambda: pick(t))

        def open_file() -> None:
            mode = next(t for t, r in modes.items() if r.checked)
            self._drop(dialog)
            mode = self.import_as or mode.removeprefix("Merge (").removesuffix(")")
            self._import(Path(name.value), mode)

        self._control(
            dialog, "Button", "&Open", 1, on_press=lambda: self._later("import", open_file)
        )
        self._control(dialog, "Button", "Cancel", 2)

    def _import(self, path: Path, mode: str) -> None:
        """Import *path* as CLICK does: show its progress window, then its answer over it."""
        assert self.main is not None
        main = self.main
        self.imported.append((mode, path.name))
        rows, errors = self.import_answer(path.read_bytes())
        mdb = self.temp_dir(main.hwnd) / "SC_.mdb"

        def write() -> None:
            try:
                table = json.loads(mdb.read_text(encoding="utf-8"))
            except ValueError:
                table = {}  # A new project's SC_.mdb, which holds b"mdb" in this fake
            table = rows if mode == "Delete Existing" else {**table, **rows}
            mdb.write_text(json.dumps(table), encoding="utf-8")

        # CLICK titles the progress window with its Delphi form's name, and later with the mode
        progress = self._window("TfrmProgress", "frmProgress", main.hwnd, enabled=False)
        self._control(progress, "TProgressBar", "", 0)

        def titled() -> None:
            progress.title = f"Import - {mode}"
            if self.import_writes == "answer":
                write()
            show(self.import_box == "twice")

        def closed(box: FakeWindow, again: bool) -> None:
            self._drop(box)
            if again:
                show(False)
                return
            self._drop(progress)
            if self.import_writes == "ok":
                write()
            main.enabled = True
            if self.import_writes == "late":
                self.queue.append((self.tick + LATE_WRITE_POLLS, write))

        def show(again: bool) -> None:
            if self.import_box == "question":
                box = self._window("#32770", "Import Database", main.hwnd)
                self._control(box, "Static", "Overwrite the nicknames?", 65535)
                self._control(box, "Button", "&Yes", 6)
                self._control(box, "Button", "&No", 7)
            elif errors is None:
                box = self._window("#32770", "Import Database", main.hwnd)
                self._control(box, "Button", "OK", 2)
                self._control(box, "Static", "", 20)
                self._control(box, "Static", "Completed!", 65535)
            else:
                box = self._window("TfrmErrorList", "Import Error List", main.hwnd)
                self._control(box, "TButton", "Ok", 0)
                self._control(box, "TMemo", "", 0, value=errors)
                for control in box.controls:
                    control.id = control.hwnd
            for button in box.controls:
                if button.text in ("OK", "Ok"):
                    button.on_press = lambda b=box: self._later(
                        "import_closed", lambda: closed(b, again)
                    )

        self._later("import_progress", titled)

    def _show_export(self) -> None:
        """Show the Save As dialog of File > Export > Nickname."""
        assert self.main is not None
        main = self.main
        dialog, name = self._show_save_dialog()

        def answer() -> None:
            if self.export_box is None:
                main.enabled = True
                return
            box = self._window("#32770", "Export Database", main.hwnd)
            if self.export_box == "question":
                self._control(box, "Static", "Overwrite the file?", 65535)
                self._control(box, "Button", "&Yes", 6)
                self._control(box, "Button", "&No", 7)
                return
            if self.export_box == "disabled":
                box.enabled = False

            def closed() -> None:
                self._drop(box)
                main.enabled = True

            self._control(box, "Button", "OK", 2, on_press=lambda: self._later("export_ok", closed))
            self._control(box, "Static", "", 20)
            text = "No data to export." if self.export_box == "other" else "Completed!"
            self._control(box, "Static", text, 65535)

        def save() -> None:
            if self.create_prompt is None:
                export()
                return
            path = Path(name.value)
            if self.create_prompt == "exists":
                path.write_bytes(b"")
            prompt = self._window("#32770", "Save As", dialog.hwnd)
            self._control(prompt, "Static", "", 20)
            if self.create_prompt == "text":
                self._control(prompt, "Static", "Create the file?", 65535)
            else:
                self._control(prompt, "Static", f"{path.name}\nThis file does not exist.", 65535)
                self._control(prompt, "Static", "Create the file?", 65536)
            yes, no = ("OK", "Cancel") if self.create_prompt == "buttons" else ("&Yes", "&No")

            def created() -> None:
                self._drop(prompt)
                export()

            self._control(prompt, "Button", yes, 6, on_press=lambda: self._later("create", created))
            self._control(prompt, "Button", no, 7)

        def export() -> None:
            path = Path(name.value)
            self._drop(dialog)
            progress = self._window("TfrmProgress", "frmProgress", main.hwnd, enabled=False)

            def write() -> None:
                self.exported.append(path)
                if self.export_writes:
                    path.write_bytes(self._export_data())
                self._drop(progress)
                answer()

            self._later("export_write", write)

        self._control(dialog, "Button", "&Save", 1, on_press=lambda: self._later("export", save))
        self._control(dialog, "Button", "Cancel", 2)

    def _export_data(self) -> bytes:
        """Return *export_bytes*, or else the header and the rows of the fake's SC_.mdb."""
        if self.export_bytes is not None:
            return self.export_bytes
        assert self.main is not None
        try:
            table = json.loads((self.temp_dir(self.main.hwnd) / "SC_.mdb").read_text("utf-8"))
        except ValueError:
            table = {}  # A new project's SC_.mdb, which holds b"mdb" in this fake
        lines = ["Address,Data Type,Nickname,Initial Value,Retentive,Address Comment"]
        for address, row in table.items():
            retentive = "Yes" if row["Retentive"] else "No"
            lines.append(
                f'{address},{row["DataType"]},"{row["Nickname"]}",{row["InitialValue"] or ""},'
                f'{retentive},"{row["Comment"] or ""}"'
            )
        return "".join(f"{line}\r\n" for line in lines).encode("cp1252")

    # -- Desktop ----------------------------------------------------------------

    def _post_command(self, hwnd: int, command_id: int) -> None:
        self._check("command")
        self._message("WM_COMMAND")
        assert self.main is not None and hwnd == self.main.hwnd
        name = cd.ALLOWED_COMMANDS[command_id]
        self.commands.append(name)
        output = self.output
        assert output is not None
        if command_id == cd.PASTE:

            def paste() -> None:
                # The cursor moves down by the rungs pasted. The step count does not change.
                self.pasted = self.clipboard
                self.cursor_rung += self.paste_rungs

            self._later("paste", paste)
        elif (
            command_id == cd.SYNTAX_CHECK
            and self.checked_tick is not None
            and self.tick - self.checked_tick <= self.quick_checks
        ):
            self._later("check_ignored", lambda: None)
        elif command_id == cd.SYNTAX_CHECK:

            def checking() -> None:
                # The output lists what the check found first. The project's total is the
                # last line.
                output.visible = True
                output.value = "Checking...\r\nNewProject40 - 0 error(s), 0 warning(s)\r\n"
                self._later("syntax_check", checked)

            def checked() -> None:
                # An instruction on rung 1 moves the END error to rung 2. The total names
                # the project from the window title, which a save changes.
                lines = [self.syntax_lines[t] for t in self.rung if t in self.syntax_lines]
                if self.rung and all(t in CONTACT_TITLES for t in self.rung):
                    lines.insert(
                        0,
                        "Main Program : Rung 1 : error C0003: There is no Coil instruction in "
                        "the rung.",
                    )
                rung = 2 if self.rung else 1
                lines.append(
                    f"Main Program : Rung {rung} : error C0201: No unconditional END "
                    "instruction in the Main Program."
                )
                errors = sum(" : error " in line for line in lines)
                assert self.main is not None
                project = Path(cr._project_file(self.main.title) or "").stem
                output.value += "".join(f"{line}\r\n" for line in lines) + (
                    f"\r\n{project} - {errors} error(s), 0 warning(s)\r\n"
                )
                self.checked_tick = self.tick

            self._later("syntax_checking", checking)
        elif command_id == cd.SAVE_PROJECT_AS:
            self._later("save_as", self._show_save_as)
        elif command_id == cd.DISCONNECT:
            self._later("disconnect", self._show_disconnect)
        elif command_id == cd.IMPORT_NICKNAME:
            self._later("import_open", self._show_open)
        elif command_id == cd.EXPORT_NICKNAME:
            self._later("export_open", self._show_export)
        elif command_id == cd.OPEN_PROJECT:
            self._later("open_project", self._show_open_project)
        elif command_id == cd.READ_DATA_FROM_PLC:
            self._later("read_data", self._show_read_data)
        elif command_id == cd.ADDRESS_PICKER:
            self._later("picker", self._show_picker)
        elif command_id == cd.SYSTEM_CONFIGURATION:
            self._later("system_config", self._show_system_config)
        elif command_id == cd.NEW_PROJECT:
            self._later("file_new", self._file_new)
        elif command_id == cd.DELETE:

            def delete() -> None:
                # A selected rung is deleted whole. Otherwise Delete removes the output
                # instruction under the cursor at AF.
                if not self.delete_works:
                    return
                if self.rung_selected:
                    self.rung, self.rung_selected = [], False
                elif self.cursor_column == "AF" and self.rung:
                    if self.rung[-1] not in CONTACT_TITLES:
                        self.rung.pop()

            self._later("delete", delete)
        elif command_id == cd.EDIT_COPY:

            def copy() -> None:
                if self.copies and self.rung_selected and self.rung:
                    self.copied.append(list(self.rung))
                    self.clipboard = self.copy_payload or rung_payload()

            self._later("copy", copy)
        else:
            dialogs = [*cr.INSTRUCTIONS.values(), cr.WIRE_CONTACT_DIALOG]
            spec = next(d for d in dialogs if d.command == command_id)
            self._later("dialog", lambda: self._show_instruction(spec))

    def click_processes(self) -> list[int]:
        self._check("click_processes")
        return list(self.running)

    def click_windows(self) -> list[int]:
        return list(self.open_windows)

    def input_desktop(self) -> str | None:
        return self.desktop_name

    def launch(self, exe: Path) -> int:
        assert self.pid is None, "launched twice"
        self.pid = 4242
        self.is_running = True
        self._launch_windows()
        return self.pid

    def alive(self, pid: int) -> bool:
        assert pid == self.pid
        return self.is_running

    def terminate(self, pid: int) -> None:
        assert pid == self.pid
        self._check("terminate")
        self.is_running = False
        self.terminated = True
        self.hung_until = 0.0
        self.wins.clear()

    def windows(self, pid: int) -> list[cd.Window]:
        assert pid == self.pid
        self._check("windows")
        hung = self.hung()
        if not hung:  # A hung CLICK handles no posted message
            self.tick += 1
            due = [item for item in self.queue if item[0] <= self.tick]
            self.queue = [item for item in self.queue if item[0] > self.tick]
            for _, action in due:
                action()
        return [
            cd.Window(
                w.hwnd,
                w.cls,
                w.title + (" (Not Responding)" if hung and w is self.main else ""),
                w.owner,
                w.enabled,
                (0, 0, 100, 100),
            )
            for w in self.wins.values()
        ]

    def _find(self, hwnd: int) -> FakeControl:
        for window in self.wins.values():
            for control in window.controls:
                if control.hwnd == hwnd:
                    return control
        raise AssertionError(f"no control {hwnd}")

    def exists(self, hwnd: int) -> bool:
        return hwnd in self.wins or any(
            c.hwnd == hwnd for w in self.wins.values() for c in w.controls
        )

    def controls(self, hwnd: int) -> list[cd.Control]:
        window = self.wins.get(hwnd)
        if window is None:
            return []
        return [
            cd.Control(c.hwnd, c.parent, c.cls, c.text, c.id, c.visible, c.enabled, c.rect)
            for c in window.controls
        ]

    def hung(self) -> bool:
        return cr.time.monotonic() < self.hung_until

    def _message(self, what: str) -> bool:
        """Return whether a message is answered, and note any sent or posted while CLICK hangs."""
        if self.hung():
            self.sent_while_hung.append(what)
            return False
        return True

    def read_text(self, hwnd: int) -> str | None:
        if not self._message("WM_GETTEXT"):
            return None
        control = self._find(hwnd)
        if control.id == 20142:
            return ""  # Another process reads an ES_PASSWORD edit as empty
        edits = ("Edit", "TEdit", "RichEdit20W", "TMemo")
        return control.value if control.cls in edits else control.text

    def set_text(self, hwnd: int, text: str) -> bool:
        if not self._message("WM_SETTEXT"):
            return False
        if self.ansi_fields:  # An ANSI dialog turns a character outside its code page into "?"
            text = text.encode("cp1252", "replace").decode("cp1252")
        self._find(hwnd).value = text
        self.typed[self._find(hwnd).id] = text
        window = next(w for w in self.wins.values() if any(c.hwnd == hwnd for c in w.controls))
        if window.on_text is not None:
            window.on_text()
        if self.list_on_fill is not None and self.list_on_fill[0] in self.receive_lists:
            name, effect = self.list_on_fill
            combo = self.receive_lists[name]
            if effect == "closed":
                combo.enabled = False
            else:
                combo.selected = 0
                if effect == "stuck":
                    self.stuck_list = combo
        if self.mode_resets_on_fill:
            radios = [c for c in window.controls if c.id in self.mode_radios]
            for radio in radios:
                radio.checked = int(radio is radios[0])
        if text == self.box_on_fill:
            dialog = next(w for w in self.wins.values() if any(c.hwnd == hwnd for c in w.controls))
            box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)
            self._control(box, "Button", "OK", 2)
            self._control(box, "Static", "OBJ-1001\nThe Formula has an error.", 65535)
            dialog.enabled = False
        return True

    def _ip_parts(self, hwnd: int) -> list[FakeControl]:
        control = self._find(hwnd)
        assert control.cls == cd.IP_ADDRESS_CLASS, f"IPM_ sent to {control.cls}"
        window = next(w for w in self.wins.values() if control in w.controls)
        parts = [c for c in window.controls if c.parent == hwnd]
        assert len(parts) == 4
        return sorted(parts, key=lambda c: c.rect[0])

    def set_ip_address(self, hwnd: int, numbers: tuple[int, int, int, int]) -> bool:
        if not self._message("IPM_SETADDRESS"):
            return False
        for part, number in zip(self._ip_parts(hwnd), numbers, strict=True):
            part.value = str(number)
        text = ".".join(map(str, numbers))
        self._find(hwnd).value = text
        self.typed[self._find(hwnd).id] = text
        return True

    def ip_address(self, hwnd: int) -> str | None:
        if not self._message("WM_GETTEXT"):
            return None
        return ".".join(part.value for part in self._ip_parts(hwnd))

    def button_checked(self, hwnd: int) -> int | None:
        return self._find(hwnd).checked if self._message("BM_GETCHECK") else None

    def list_box(self, hwnd: int) -> tuple[list[str], int] | None:
        if not self._message("LB_GETCOUNT"):
            return None
        control = self._find(hwnd)
        assert control.cls == "TListBox", f"LB_GETCOUNT sent to {control.cls}"
        return list(control.options), control.selected

    def combo_box(self, hwnd: int) -> tuple[list[str], int] | None:
        if not self._message("CB_GETCOUNT"):
            return None
        control = self._find(hwnd)
        assert control.cls == "ComboBox", f"CB_GETCOUNT sent to {control.cls}"
        return list(control.options), control.selected

    def edit_limit(self, hwnd: int) -> int | None:
        if not self._message("EM_GETLIMITTEXT"):
            return None
        return self._find(hwnd).limit

    def list_view_items(self, hwnd: int) -> int | None:
        if not self._message("LVM_GETITEMCOUNT"):
            return None
        control = self._find(hwnd)
        if self.late_row_at is not None and cr.time.monotonic() >= self.late_row_at:
            control.items += 1
            self.late_row_at = None
        return control.items

    def status_bar(self, hwnd: int) -> list[str] | None:
        control = self._find(hwnd)
        assert control.cls == "msctls_statusbar32", f"SB_GETTEXT sent to {control.cls}"
        if not self.status_readable or not self._message("SB_GETTEXT"):
            return None
        # The panes as CLICK shows them before connecting, while connected and after a disconnect
        mode = "RUN" if self.connected else "Offline" if self.went_offline else "-----"
        named = self.connected and self.options["plc_pane"]
        return [
            "",
            "Bit",
            "Integer",
            "Integer(2 words)",
            "Floating point",
            "Hex",
            "Text",
            "Ascii",
            mode,
            f"{self.steps:04d}/8000",
            "C2-03CPU" if self.connected else self.cpu or "No select CPU",
            f"{self.cursor_rung}:1:{self.cursor_column}",
            "",
            "",
            "192.168.1.241(Conformance)" if named else "",
            "",
            "",
            "NUM",
            "",
        ]

    def press(self, hwnd: int) -> None:
        self._message("BM_CLICK")
        control = self._find(hwnd)
        self.pressed.append(control.text or f"{control.cls}@{control.rect[0]}")
        if control.on_press is not None:
            control.on_press()

    def send_press(self, hwnd: int) -> bool:
        if not self._message("BM_CLICK"):
            return False
        control = self._find(hwnd)
        self.pressed.append(control.text or f"{control.cls}@{control.rect[0]}")
        action = control.on_send or control.on_press
        if action is not None:
            action()
        return True

    def close(self, hwnd: int) -> None:
        self._message("WM_CLOSE")
        window = self.wins[hwnd]
        if window.on_close is not None:
            window.on_close()

    def send_key(self, hwnd: int, vk: int) -> bool:
        if not self._message("WM_KEYDOWN"):
            return False
        self.keys.append((self._find(hwnd).cls, vk))
        control = self._find(hwnd)
        if control.on_key is not None:
            control.on_key(vk)
        elif control.cls == "TEdit":
            self.editor_keys(vk)
        return True

    def send_chars(self, hwnd: int, text: str) -> bool:
        if not self._message("WM_CHAR"):
            return False
        self.keys.append((self._find(hwnd).cls, text))
        control = self._find(hwnd)
        control.value += text
        return True

    def idle(self, hwnd: int, timeout: float) -> bool:
        # SMTO_ABORTIFHUNG gives up at once on a hung window
        return not self.hung() and cr.time.monotonic() >= self.busy_until

    def screenshot(self, hwnd: int, path: Path) -> bool:
        if not self.exists(hwnd):
            raise OSError(1400, "GetWindowRect", "Invalid window handle.")
        if self.hung():
            self.sent_while_hung.append("screenshot")  # The shot would show Windows' ghost window
        path.write_bytes(b"\x89PNG fake")
        return True

    def _hold_clipboard(self) -> None:
        # Another program holds the clipboard for the first *clipboard_held* calls. The text
        # is what ClickNick's clipboard code raises then
        if self.clipboard_held:
            self.clipboard_held -= 1
            self.events.append("clipboard_held")
            raise RuntimeError(
                "Could not open the clipboard after 20 attempts. Another program may hold it "
                "open. Try again."
            )

    def set_clipboard(self, payload: bytes, owner: int) -> None:
        self._check("set_clipboard")
        assert self.main is not None and owner == self.main.hwnd
        self._hold_clipboard()
        self.clipboard = payload

    def empty_clipboard(self) -> None:
        self._check("empty_clipboard")
        self._hold_clipboard()
        self.clipboard = None
        self.events.append("empty_clipboard")

    def read_clipboard(self) -> bytes | None:
        self._check("read_clipboard")
        return self.clipboard

    def _post_click(self, hwnd: int, x: int, y: int) -> None:
        self._check("click")
        self._message("WM_LBUTTONDOWN")
        control = self._find(hwnd)
        assert self.main is not None and control in self.main.controls
        assert control.cls == cd.LADDER_VIEW_CLASS and control.visible
        self.clicks.append((x, y))

        def select() -> None:
            if (x, y) == cr.RUNG1_POINT:  # Rung 1's number
                self.cursor_rung, self.cursor_column = 1, "A"
                self.rung_selected = True

        self._later("rung_click", select)

    def temp_dir(self, hwnd: int) -> Path:
        return self.temp_root / f"CLICK ({hwnd:08X})"


_RUNG_PAYLOAD: list[bytes] = []


def rung_payload() -> bytes:
    """Return ``RUNG_CSV``'s rung in CLICK's clipboard format, as the fake's Edit > Copy puts it."""
    if not _RUNG_PAYLOAD:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            csv = Path(folder) / "rung.csv"
            csv.write_text(RUNG_CSV, encoding="utf-8")
            _RUNG_PAYLOAD.append(prepare_csv_load(csv, click_v4=True, mdb_path=None).payload)
    return _RUNG_PAYLOAD[0]


def unknown_contact_payload() -> bytes:
    """Return ``RUNG_CSV``'s payload with its contact's class named ``ContactXX``.

    laddercodec decodes that as an unknown condition."""
    old, new = "ContactNO".encode("utf-16-le"), "ContactXX".encode("utf-16-le")
    data = rung_payload()
    assert data.count(old) == 1
    return data.replace(old, new)


def unwalkable_payload() -> bytes:
    """Return ``RUNG_CSV``'s payload with a byte of row 0's cells changed.

    laddercodec then cannot find cell 0 of the row and decodes a marker rung in its place.
    laddercodec 0.4.0 raised DecodeError instead. The offset of the byte is right for the
    laddercodec version that these tests run with."""
    data = bytearray(rung_payload())
    data[0xA69] = 0xFF
    return bytes(data)


def plc_name_in(ini: bytes) -> str:
    """Return the PLC Name that CLICK shows for a Project.ini.

    The name is the value of the first Key1 in the first [Sec20] section. CLICK matches the
    section and the key in any letter case. With no [Sec20] section, there is no name."""
    section = None
    for line in ini.decode("latin-1").splitlines():
        if line.startswith("[") and line.endswith("]"):
            if section == "sec20":
                break
            section = line[1:-1].lower()
        elif section == "sec20" and line.lower().startswith("key1="):
            return line[len("key1=") :]
    return ""


def judge_like_click(title: str, mode: str | None, values: dict[str, str]) -> object:
    """Return what CLICK answers when OK is pressed in an instruction dialog.

    CLICK refuses a Math with no result, a Math result in SD, an Out on X, a Copy into YD, and a
    Receive with Function Code 03 and a slave address that does not start with 4. None means
    that CLICK accepts."""
    if title == "Math" and not values.get("result"):
        return ("OBJ-001", "Enter the result.")
    if title == "Math" and values["result"].startswith("SD"):
        return ("OBJ-003", "The entered address is outside the range.")
    if title == "Out" and values.get("address", "").startswith("X"):
        return ("OBJ-004", "The entered address cannot be used in this instruction.")
    if title == "Copy" and values.get("destination", "").startswith("YD"):
        return ("OBJ-004", "The entered address cannot be used in this instruction.")
    if (
        title == "Receive"
        and values["function"].startswith("03")
        and not values.get("slave_address", "").startswith("4")
    ):  # A Function Code 03 with a slave address meant for 01
        return ("OBJ-010", "The entered value is outside the range. Range: <400001> to <465535>")
    return None


# An import written late writes SC_.mdb this many polls after the main window is alone again
LATE_WRITE_POLLS = 3
# File > New Project: the polls from Startup closing to the fake's first write of SC_.mdb
NEW_MDB_POLLS = 5
# At the tests' poll of 0.001 s, 150 polls last 0.15 s. That is longer than IMPORT_SETTLE (0.1 s
# in the tests) and shorter than NEW_SETTLE (0.3 s in the tests). CLICK's gaps between writes in
# the live runs fell between the two real values in the same way.
NEW_WRITE_POLLS = 150
# CLICK's question whether to save, as the fake shows it after File > New Project
SAVE_CHANGES_TEXT = "Save changes to C:\\projects\\C0-02DD1-D.ckp?"
SAVE_CHANGES_BUTTONS = (("&Yes", 6, True), ("&No", 7, True), ("Cancel", 2, True))


def import_like_click(data: bytes) -> tuple[dict[str, dict], str | None]:
    """Return the rows that a CLICK import stores, and the text of its error list or None.

    The fake copies three cases seen in CLICK. A line that does not have six cells is refused.
    So is a line whose quoted address has a space at either end, and the error list shows that
    refusal twice for the file's first data row. Any other row is stored under its address, with
    the spaces at the address's ends removed."""
    rows: dict[str, dict] = {}
    errors = ""
    lines = data.decode("latin-1").split("\r\n")
    for number, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cells = next(csv_module.reader([line]))
        if len(cells) != 6:  # Such as the line after a line break inside a quoted cell
            errors += (
                f"Error : Unable to import to Database.\r\nLine {number} : {line}\r\n"
                "Cause : The file format is not correct.\r\n\r\n"
            )
            continue
        address, data_type, nickname, initial, retentive, comment = cells
        if line.startswith('"') and address != address.strip():
            entry = (
                f"Error : Unable to import to Database.\r\nLine {number} : {line}\r\n"
                "Cause : The memory address is not supported by this CLICK CPU module.\r\n\r\n"
            )
            errors += entry * (2 if number == 2 else 1)
            continue
        rows[address.strip()] = {
            "DataType": {"INT": 1, "TEXT": 6, "FLOAT": 3}.get(data_type),
            "Nickname": nickname,
            "InitialValue": initial or None,
            "Retentive": retentive == "Yes",
            "Comment": comment or None,
            "Use": False,
        }
    return rows, errors or None


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    csv = tmp_path / "rung.csv"
    csv.write_text(RUNG_CSV, encoding="utf-8")
    exe = tmp_path / "CLICK.exe"
    exe.write_bytes(b"")
    rungs = read_csv(csv)
    # The fake's Scr1.tmp holds the pasted payload, which is not a real program. Decode it as
    # the CSV's rungs, and decode the fake's b"empty" as no rungs.
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda data: Program("Main Program", 1, rungs if data != b"empty" else []),
    )
    for name in ("CLICK_RUNNER_PASSWORD", "CLICK_RUNNER_USER_TYPE"):
        monkeypatch.delenv(name, raising=False)
    return csv, exe


class Prepare:
    """A stand-in for prepare_csv_load that ignores SC_.mdb and records which MDB was asked for.

    The fake's SC_.mdb is not a database."""

    def __init__(self) -> None:
        self.mdbs: list[Path | None] = []

    def __call__(self, csv: Path, mdb: Path | None):
        self.mdbs.append(mdb)
        return prepare_csv_load(csv, click_v4=True, mdb_path=None)


def run(
    fake: FakeClick,
    out: Path,
    csv: Path | None,
    exe: Path,
    *args: str,
    timeout: float = 5,
    paste_timeout: float | None = None,
    capsys: pytest.CaptureFixture[str] | None = None,
) -> tuple[int, dict]:
    """Run the CLI on *fake* and return its exit code and result.

    The paste timeout is *timeout* unless *paste_timeout* is given."""
    argv = ["paste", str(csv)] if csv is not None else ["record"]
    argv += ["--out", str(out), "--click-exe", str(exe), "--timeout", str(timeout)]
    argv += ["--paste-timeout", str(timeout if paste_timeout is None else paste_timeout), *args]
    code = cr.main(argv, desktop=fake, prepare=Prepare(), stderr=io.StringIO())
    result_file = out / "result.json"
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
    if capsys is not None:
        printed = json.loads(capsys.readouterr().out)
        assert printed == result or not result_file.exists()
        result = result or printed
    return code, result


class VirtualClock:
    """The runner's clock, which moves only when the runner sleeps.

    It moves by the length of the sleep, and it never waits.

    The fakes answer by poll count, and the runner's settle times and timeouts count
    seconds. On a machine busy with other test runs the two drift apart on the wall
    clock (a hold of 0.1 s ends between two polls), so a test runs on this clock and
    gives the same answer however loaded the machine is. The timings the runner records
    (``timings``, ``elapsed``, ``seconds``) are virtual seconds under it.

    A loop that reads the clock this many times without a sleep would wait for ever, so
    it fails the test instead.
    """

    MAX_READS_WITHOUT_SLEEP = 100_000

    def __init__(self) -> None:
        self.now = 1000.0
        self.reads = 0

    def monotonic(self) -> float:
        self.reads += 1
        assert self.reads <= self.MAX_READS_WITHOUT_SLEEP, (
            "the runner read the clock "
            f"{self.MAX_READS_WITHOUT_SLEEP} times without sleeping: a loop that never sleeps "
            "would wait for ever on this clock"
        )
        return self.now

    def sleep(self, seconds: float) -> None:
        self.reads = 0
        self.now += seconds


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cr, "time", VirtualClock())
    monkeypatch.setattr(cr, "POLL_INTERVAL", 0.001)
    monkeypatch.setattr(cr, "PLC_SETTLE", 0.02)
    monkeypatch.setattr(cr, "IMPORT_SETTLE", 0.1)
    monkeypatch.setattr(cr, "NEW_SETTLE", 0.3)
    monkeypatch.setattr(cr, "FILL_SETTLE", 0.02)
    monkeypatch.setattr(cr, "OPTION_WAIT", 0.2)
    monkeypatch.setattr(cr, "CPU_TYPE_WAIT", 0.5)


def assert_aborted(fake: FakeClick, out: Path, code: int, result: dict, reason: str) -> None:
    assert code == cr.EXIT_ABORTED
    assert result["status"] == "aborted"
    assert reason in result["reason"]
    assert fake.terminated and not fake.is_running
    assert result["click"]["closed"] is True
    assert list((out / "abort").glob("*-abort-*.json")), "no abort dump"
    assert list((out / "abort").glob("*-abort-*.png")), "no abort screenshot"
    assert "ABORT: " in (out / "run.log").read_text(encoding="utf-8")
    assert not fake.read_from_plc
    assert "Read Project from PLC" not in fake.commands
    assert "Write Project into PLC" not in fake.commands
    assert_temp_left_to_click(fake, out, still_there=True)


def assert_temp_left_to_click(fake: FakeClick, out: Path, *, still_there: bool) -> None:
    """Check that the runner never deletes CLICK's temp folder and logs whether CLICK left it."""
    assert fake.main is not None
    temp = fake.temp_dir(fake.main.hwnd)
    assert temp.exists() == still_there
    state = "is still there" if still_there else "is gone"
    assert f"{temp} {state}" in (out / "run.log").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_paste_end_to_end(tmp_path, setup, capsys):
    csv, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"

    code, result = run(fake, out, csv, exe, capsys=capsys)

    assert code == cr.EXIT_OK, result["reason"]
    assert result["status"] == "ok"
    assert result["step"] == "decode"
    assert fake.commands == ["Paste", "Syntax Check", "Save Project As", "Disconnect"]
    assert fake.pressed == [
        "TButton@1035",
        "Connect",
        "OK",
        "Don't read the project from the PLC.",
        "OK",
        "&Save",
        "&Yes",
    ]
    assert fake.typed[20142] == "123click"
    assert 20141 not in fake.typed  # CLICK prefilled User Type
    assert fake.pasted == fake.clipboard and fake.pasted
    assert fake.exited_cleanly and not fake.terminated and not fake.read_from_plc
    assert result["syntax_check"]["errors"] == 1
    assert result["syntax_check"]["warnings"] == 0
    assert result["syntax_check"]["text"].endswith("1 error(s), 0 warning(s)\r\n")
    assert result["rungs"] == {"pasted": 1, "saved_main": 1, "same": True}
    assert result["plc"] == "192.168.1.241(Conformance)"
    assert "scr_before_paste" not in result
    assert Path(result["files"]["ckp"]) == out / "rung.ckp"
    assert (out / "rung.ckp").read_bytes() == b"ckp"
    assert sorted(p.name for p in (out / "click").iterdir()) == ["Project.ini", "Scr1.tmp"]
    assert (out / "click" / "Scr1.tmp").read_bytes() == fake.pasted
    assert result["files"]["csv"] == [str(out / "csv" / "main.csv")]
    assert "X001" in (out / "csv" / "main.csv").read_text(encoding="utf-8")
    assert result["click"]["closed"] is True
    assert list(result["timings"]) == [
        "refuse",
        "launch",
        "startup",
        "connect",
        "login",
        "dont_read",
        "paste",
        "syntax_check",
        "save",
        "copy",
        "disconnect",
        "close",
        "decode",
    ]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "User Type: 'admin' (prefilled by CLICK)" in log
    assert "123click" not in log
    assert not (out / "record").exists() and not (out / "abort").exists()
    # CLICK closed cleanly and removed its own temp folder
    assert_temp_left_to_click(fake, out, still_there=False)


@pytest.mark.parametrize("empty_main", [[], [empty_rung("")]])
def test_a_paste_that_did_not_land_aborts(tmp_path, setup, monkeypatch, empty_main):
    """With no status bar to read, the decoded save is the only check of a paste."""
    csv, exe = setup
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda data: Program("Main Program", 1, empty_main),
    )
    fake = FakeClick(tmp_path, stall="paste", status_bar=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert code == cr.EXIT_ABORTED
    assert result["status"] == "aborted" and result["step"] == "decode"
    assert result["reason"].startswith("the paste did not land. The saved main program has")
    assert result["rungs"]["same"] is False
    # CLICK itself had closed cleanly by then
    assert fake.exited_cleanly and not fake.terminated


def test_a_saved_main_that_differs_is_reported_not_aborted(tmp_path, setup, monkeypatch):
    """A saved main that differs from the pasted rung is reported in the result, not aborted on.

    What CLICK makes of a rung is what a run is for."""
    csv, exe = setup
    other = read_csv(csv)
    other[0] = empty_rung("CLICK changed it")
    other.append(read_csv(csv)[0])
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda data: Program("Main Program", 1, other),
    )
    code, result = run(FakeClick(tmp_path), tmp_path / "out", csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert result["rungs"] == {"pasted": 1, "saved_main": 2, "same": False}


def test_stdout_carries_only_the_result(tmp_path, setup, capfd):
    """Opening SC_.mdb prints the ODBC driver it used, and that line goes to stderr."""
    csv, exe = setup

    def prepare(csv: Path, mdb: Path | None):
        print("Successfully connected using driver: Microsoft Access Driver")
        os.write(1, b"and a DLL writing to fd 1\n")
        return prepare_csv_load(csv, click_v4=True, mdb_path=None)

    out = tmp_path / "out"
    argv = ["paste", str(csv), "--out", str(out), "--click-exe", str(exe), "--timeout", "5"]
    code = cr.main(argv, desktop=FakeClick(tmp_path), prepare=prepare, stderr=io.StringIO())
    captured = capfd.readouterr()
    assert code == cr.EXIT_OK
    assert json.loads(captured.out) == json.loads((out / "result.json").read_text("utf-8"))
    assert "Successfully connected using driver" in captured.err
    assert "and a DLL writing to fd 1" in captured.err


def test_paste_provisions_the_runners_own_mdb(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path)
    prepare = Prepare()
    settings = cr.Settings(
        "paste", tmp_path / "out", csv=csv, exe=exe, timeout=5, paste_timeout=5, poll=0.001
    )
    result = cr.Run(fake, settings, prepare=prepare, stderr=io.StringIO()).execute()
    assert result["status"] == "ok", result["reason"]
    assert prepare.mdbs == [None, fake.temp_dir(fake.main.hwnd) / "SC_.mdb"]


def test_tooltips_are_let_be(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, tooltip=True)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert log.count("ignoring a tooltip: 'tooltips_class32'") == 2


def test_a_drop_shadow_is_let_be(tmp_path, setup):
    """A drop shadow over Save As does not stop the run.

    Three live runs on 2026-11-18 stopped while the runner filled Save As. Each met a window of
    class ``SysShadow`` with no title and no owner.
    """
    csv, exe = setup
    fake = FakeClick(tmp_path, shadow=True)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.saved
    log = (out / "run.log").read_text(encoding="utf-8")
    assert log.count("ignoring a drop shadow: 'SysShadow' ''") == 1


@pytest.mark.parametrize(
    ("cls", "title", "owner", "what"),
    [
        ("SysShadow", "", 0, "a drop shadow"),
        ("SysShadow", "Shadow", 0, None),  # A shadow has no title
        ("SysShadow", "", 7, None),  # A shadow has no owner
        ("tooltips_class32", "Save", 7, "a tooltip"),
        ("#32770", "", 0, None),
    ],
)
def test_only_tooltips_and_untitled_unowned_shadows_are_let_be(cls, title, owner, what):
    window = cd.Window(1, cls, title, owner, True, (0, 0, 1, 1))
    assert cr._ignored_as(window) == what


# ---------------------------------------------------------------------------
# paste --add-end
# ---------------------------------------------------------------------------


def decode_as(monkeypatch: pytest.MonkeyPatch, csv: Path) -> None:
    """Decode the fake's saved main program as the rungs of *csv*, once *csv* exists."""
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda data: Program("Main Program", 1, read_csv(csv) if data != b"empty" else []),
    )


def test_paste_add_end_pastes_the_csv_with_an_end_rung(tmp_path, setup, monkeypatch):
    csv, exe = setup
    out = tmp_path / "out"
    pasted = out / "pasted.csv"
    decode_as(monkeypatch, pasted)
    fake = FakeClick(tmp_path, paste_rungs=2)

    code, result = run(fake, out, csv, exe, "--add-end")

    assert code == cr.EXIT_OK, result["reason"]
    assert result["added_end"] is True
    assert result["files"]["pasted_csv"] == str(pasted)
    data = csv.read_bytes()
    assert pasted.read_bytes() == cr.with_end(data)
    assert pasted.read_bytes().startswith(data)
    # The pasted rungs are the CSV's and then the end() rung, and the comparison counts both
    assert fake.pasted == prepare_csv_load(pasted, click_v4=True, mdb_path=None).payload
    assert result["rungs"] == {"pasted": 2, "saved_main": 2, "same": True}
    assert cr.ends_unconditionally(read_csv(pasted))
    # The project is named after the CSV that was given
    assert Path(result["files"]["ckp"]) == out / "rung.ckp"


def test_paste_add_end_pastes_a_csv_that_ends_with_end_as_it_is(tmp_path, setup, monkeypatch):
    _, exe = setup
    csv = tmp_path / "ended.csv"
    csv.write_bytes((RUNG_CSV + cr.END_ROW + "\n").encode("ascii"))
    decode_as(monkeypatch, csv)
    fake = FakeClick(tmp_path, paste_rungs=2)
    out = tmp_path / "out"

    code, result = run(fake, out, csv, exe, "--add-end")

    assert code == cr.EXIT_OK, result["reason"]
    assert result["added_end"] is False
    assert not (out / "pasted.csv").exists() and "pasted_csv" not in result["files"]
    assert fake.pasted == prepare_csv_load(csv, click_v4=True, mdb_path=None).payload
    assert result["rungs"] == {"pasted": 2, "saved_main": 2, "same": True}


def test_paste_without_add_end_adds_no_rung(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert "added_end" not in result and not (out / "pasted.csv").exists()
    assert fake.pasted == prepare_csv_load(csv, click_v4=True, mdb_path=None).payload
    assert result["rungs"] == {"pasted": 1, "saved_main": 1, "same": True}


def test_paste_add_end_refuses_a_csv_that_does_not_read(tmp_path, setup):
    _, exe = setup
    csv = tmp_path / "bad.csv"
    csv.write_text("not a ladder CSV\n", encoding="utf-8")
    fake = FakeClick(tmp_path)
    code, result = run(fake, tmp_path / "out", csv, exe, "--add-end")
    assert code == cr.EXIT_REFUSED
    assert result["reason"].startswith(f"cannot read {csv}: ")
    assert fake.pid is None


def test_with_end_adds_the_end_row_with_the_files_line_end():
    row = cr.END_ROW.encode("ascii")
    assert row.split(b",") == [b"R", *[b"-"] * 31, b"end()"]
    assert cr.with_end(b"h\r\nR,x\r\n") == b"h\r\nR,x\r\n" + row + b"\r\n"
    assert cr.with_end(b"h\nR,x\n") == b"h\nR,x\n" + row + b"\n"
    # A last line without a line end gets one before the row
    assert cr.with_end(b"h\r\nR,x") == b"h\r\nR,x\r\n" + row + b"\r\n"
    assert cr.with_end(b"h") == b"h\n" + row + b"\n"


WIRE_TO_AE = ",".join(["-"] * 30)  # The wire from column B to column AE


@pytest.mark.parametrize(
    ("rows", "ends"),
    [
        ([cr.END_ROW], True),
        ([RUNG_CSV.splitlines()[1].replace("out(Y001)", "end()")], False),  # Behind a contact
        ([RUNG_CSV.splitlines()[1]], False),
        ([], False),  # No rung at all
        # end() behind X001 OR X002: one rung of two rows
        ([f"R,T:X001,{WIRE_TO_AE},end()", ",X002" + "," * 31], False),
        # X001 to out(Y001), and under it a wire to end(). laddercodec splits the two circuits
        # into two rungs, as CLICK does, so the last rung is an unconditional end()
        ([f"R,T:X001,{WIRE_TO_AE},out(Y001)", f",-,{WIRE_TO_AE},end()"], True),
    ],
    ids=["end_row", "behind_a_contact", "a_coil", "no_rung", "or_branch", "wire_to_end_below"],
)
def test_ends_unconditionally_reads_the_last_rung(tmp_path, rows, ends):
    csv = tmp_path / "rungs.csv"
    lines = RUNG_CSV.splitlines()[:1] + rows
    csv.write_bytes("".join(f"{line}\n" for line in lines).encode("ascii"))
    assert cr.ends_unconditionally(read_csv(csv)) is ends


def test_no_guide_no_login_and_a_splash(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, guide=False, login=False, splash=True)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert "login" not in result["timings"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "no Login dialog" in log
    assert "a window was open before the main window appeared: 'TfrmSplash'" in log


def test_a_splash_still_open_after_launch_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, splash=True, stall="splash")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(
        fake, out, code, result, "for every window that was open before the main window to close"
    )
    assert result["step"] == "launch"


def test_empty_user_type_is_filled_in(tmp_path, setup, monkeypatch):
    csv, exe = setup
    monkeypatch.setenv("CLICK_RUNNER_USER_TYPE", "operator")
    monkeypatch.setenv("CLICK_RUNNER_PASSWORD", "secret")
    fake = FakeClick(tmp_path, prefilled_user="", password="secret")
    code, result = run(fake, tmp_path / "out", csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.typed[20141] == "operator"
    assert fake.typed[20142] == "secret"


def test_a_user_type_that_does_not_take_aborts(tmp_path, setup):
    """The run aborts at login when the User Type edit does not keep the text that the runner sets.

    The runner then types no password and does not press OK."""
    csv, exe = setup
    fake = FakeClick(tmp_path, prefilled_user="")
    real = fake.set_text

    def set_text(hwnd: int, text: str) -> bool:
        if fake._find(hwnd).id == 20141:
            return True  # Answered, but the edit keeps its text
        return real(hwnd, text)

    fake.set_text = set_text
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(
        fake, out, code, result, "User Type does not read back the text that the runner set in it"
    )
    assert result["step"] == "login"
    assert 20142 not in fake.typed and "OK" not in fake.pressed[2:]


def test_empty_user_type_defaults_to_admin(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, prefilled_user="")
    code, result = run(fake, tmp_path / "out", csv, exe, "--password", "123click")
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.typed[20141] == "admin"


def test_record_dumps_each_step_and_ends_click(tmp_path, setup, capsys):
    _, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    code, result = run(fake, out, None, exe, capsys=capsys)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.commands == ["Disconnect"]
    assert not fake.connected and fake.terminated and not fake.saved
    labels = {p.name.split("-")[1] for p in (out / "record").glob("*.json")}
    assert labels == {
        "launched",
        "guide_closed",
        "connect_dialog",
        "login",
        "read_prompt",
        "connected",
        "disconnected",
    }
    dumps = [
        json.loads(p.read_text(encoding="utf-8")) for p in (out / "record").glob("*-login-*.json")
    ]
    (login,) = [d for d in dumps if d["title"] == "Login"]
    user = next(c for c in login["controls"] if c["id"] == 20141)
    assert user["text"] == "" and user["edit_text"] == "admin"
    assert list((out / "record").glob("*-login-*.png"))
    # record ends CLICK rather than closing it, so CLICK's temp folder stays. The runner leaves
    # the folder for CLICK to deal with.
    assert_temp_left_to_click(fake, out, still_there=True)


def test_paste_record_dumps_too(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, "--record")
    assert code == cr.EXIT_OK, result["reason"]
    labels = {p.name.split("-")[1] for p in (out / "record").glob("*.json")}
    assert {"pasted", "syntax_checked", "save_as", "saved", "disconnected"} <= labels


# ---------------------------------------------------------------------------
# Refusals: nothing is launched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("switches", "reason"),
    [
        ({"running": (77,)}, "CLICK is already running (CLICK.exe pid 77)"),
        ({"open_windows": (1234,)}, "a CLICK window is already open"),
        ({"desktop_name": "Winlogon"}, "the input desktop is 'Winlogon'"),
        ({"desktop_name": None}, "the input desktop is locked or cannot be opened"),
    ],
)
def test_refuses_to_start(tmp_path, setup, switches, reason):
    csv, exe = setup
    fake = FakeClick(tmp_path, **switches)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_REFUSED
    assert result["status"] == "refused"
    assert reason in result["reason"]
    assert fake.pid is None


def test_refuses_a_folder_that_is_not_empty(tmp_path, setup, capsys):
    csv, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("mine", encoding="utf-8")
    code, result = run(fake, out, csv, exe, capsys=capsys)
    assert code == cr.EXIT_REFUSED
    assert (
        result["status"] == "refused"
        and "is a file or a folder that is not empty" in result["reason"]
    )
    assert sorted(p.name for p in out.iterdir()) == ["keep.txt"]
    assert fake.pid is None


def test_refuses_a_csv_that_does_not_encode(tmp_path, setup):
    _, exe = setup
    bad = tmp_path / "bad.csv"
    bad.write_text("not,a,ladder\n", encoding="utf-8")
    fake = FakeClick(tmp_path)
    code, result = run(fake, tmp_path / "out", bad, exe)
    assert code == cr.EXIT_REFUSED and "cannot encode" in result["reason"]
    assert fake.pid is None


def test_an_empty_out_folder_is_fine(tmp_path, setup):
    csv, exe = setup
    out = tmp_path / "out"
    out.mkdir()
    code, result = run(FakeClick(tmp_path), out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]


# ---------------------------------------------------------------------------
# Aborts: dumped, CLICK ended
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "step"),
    [
        ("guide", "launch"),
        ("startup", "connect"),
        ("connect", "connect"),
        ("login", "login"),
        ("dont_read", "dont_read"),
        ("paste", "paste"),
        ("syntax_check", "syntax_check"),
        ("save", "save"),
        ("disconnect_yes", "disconnect"),
    ],
)
def test_an_unexpected_dialog_aborts(tmp_path, setup, event, step):
    csv, exe = setup
    fake = FakeClick(tmp_path, surprise=event)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "unexpected window")
    assert "'Set a Project Password'" in result["reason"]
    assert result["step"] == step
    dumped = [
        json.loads(p.read_text(encoding="utf-8"))["title"] for p in (out / "abort").glob("*.json")
    ]
    assert "Set a Project Password" in dumped


def test_an_unexpected_dialog_after_saving_is_not_answered(tmp_path, setup):
    """A dialog is open when the run stops, so the cleanup does not disconnect first."""
    csv, exe = setup
    fake = FakeClick(tmp_path, surprise="save")
    code, result = run(fake, tmp_path / "out", csv, exe)
    assert code == cr.EXIT_ABORTED
    assert "Disconnect" not in fake.commands
    assert "not disconnecting: a dialog is open" in (tmp_path / "out" / "run.log").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("event", "step"),
    [
        ("connect", "connect"),
        ("paste", "paste"),
        ("save", "save"),
        ("disconnect", "disconnect"),
        ("disconnect_yes", "disconnect"),
    ],
)
def test_a_click_error_box_aborts_with_its_code(tmp_path, setup, event, step):
    """A CLICK error box at connect, paste, save or disconnect aborts the run with its code.

    The box is the PTC-013 box that CLICK shows when connecting to the PLC times out. Nothing is
    pressed in the box and nothing is retried."""
    csv, exe = setup
    fake = FakeClick(tmp_path, error_on=event)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(
        fake, out, code, result, "CLICK error PTC-013: Timeout on attempting to connect to PLC."
    )
    assert result["reason"] == "CLICK error PTC-013: Timeout on attempting to connect to PLC."
    assert result["click_error"] == "PTC-013" and result["step"] == step
    assert result["cleanup_click_error"] is None
    assert not fake.error_answered
    assert fake.commands.count("Disconnect") <= 1  # The cleanup sends no second Disconnect
    if event == "connect":
        assert "login" not in fake.events and result["plc"] is None


def pressed_at(fake: FakeClick) -> list[tuple[str, float]]:
    """Return a list that gets the text of each button that the runner presses in *fake*, and
    the runner's clock at the press."""
    times: list[tuple[str, float]] = []
    real = fake.press

    def press(hwnd: int) -> None:
        times.append((fake._find(hwnd).text, cr.time.monotonic()))
        real(hwnd)

    fake.press = press
    return times


def test_a_cpu_type_box_at_connect_is_answered_and_connect_pressed_again(tmp_path, setup):
    """CLICK answers the first Connect with the box that says it could not read the CPU type.

    The runner presses the box's OK, waits ``CPU_TYPE_WAIT`` and presses Connect again. The
    second Connect gets the Login, and the paste goes on."""
    csv, exe = setup
    fake = FakeClick(tmp_path, cpu_type=1)
    times = pressed_at(fake)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.cpu_type_shown == 1 and fake.events.count("cpu_type_ok") == 1
    assert fake.saved and not fake.read_from_plc and result["plc"]
    connects = [at for text, at in times if text == "Connect"]
    box_ok = next(at for text, at in times if text == "OK")
    assert len(connects) == 2 and connects[0] < box_ok < connects[1]
    assert connects[1] - box_ok >= cr.CPU_TYPE_WAIT
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "CLICK could not read the PLC's CPU type (Connect press 1 of 3)" in log


def test_a_cpu_type_box_that_closes_slowly_is_waited_for(tmp_path, setup):
    """The box stays open for a few polls after its OK, and the Connect dialog is enabled a
    few polls after the box closes. The runner waits for both before ``CPU_TYPE_WAIT``
    starts, so no window is open that the pause does not expect."""
    csv, exe = setup
    fake = FakeClick(tmp_path, cpu_type=1, cpu_type_slow=5)
    times = pressed_at(fake)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.events.count("cpu_type_ok") == 1 and "cpu_type_enabled" in fake.events
    connects = [at for text, at in times if text == "Connect"]
    assert len(connects) == 2
    assert connects[1] - fake.cpu_type_closed_at[0] >= cr.CPU_TYPE_WAIT


def test_a_cpu_type_box_on_every_press_of_connect_aborts(tmp_path, setup):
    """The box answers all ``CPU_TYPE_TRIES`` presses of Connect. The run stops with a reason that
    names the box, and the runner leaves the last box open."""
    csv, exe = setup
    fake = FakeClick(tmp_path, cpu_type=cr.CPU_TYPE_TRIES)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "could not read the PLC's CPU type after 3 presses")
    assert "'CLICK Programming Software'" in result["reason"]
    assert cr.CPU_TYPE_LINE in result["reason"]
    assert result["step"] == "connect" and result["click_error"] is None
    assert fake.cpu_type_shown == 3 and fake.events.count("cpu_type_ok") == 2
    assert fake.pressed.count("Connect") == 3 and "login" not in fake.events
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "(Connect press 1 of 3)" in log and "(Connect press 2 of 3)" in log


@pytest.mark.parametrize(
    ("box", "extra"),
    [
        (("Another message.", ("OK",)), None),
        ((CPU_TYPE_TEXT, ("OK", "Cancel")), None),
        ((CPU_TYPE_TEXT, ("&Yes",)), None),
        (("Note\n" + CPU_TYPE_TEXT, ("OK",)), None),
        ((CPU_TYPE_TEXT, ("OK",)), ("Static", "Another message.")),
        ((CPU_TYPE_TEXT, ("OK",)), ("Edit", "Another message.")),
        ((CPU_TYPE_TEXT, ("OK",)), ("SysLink", "")),
    ],
    ids=[
        "other text",
        "two buttons",
        "no OK",
        "other first line",
        "a second text",
        "text in an Edit",
        "a control of another class",
    ],
)
def test_an_unknown_box_at_connect_aborts_and_is_not_pressed(tmp_path, setup, box, extra):
    """A box at Connect with the CPU-type box's title and owner, but another text, other
    buttons or another control, stops the run. The runner presses nothing in it."""
    csv, exe = setup
    fake = FakeClick(tmp_path, cpu_type=1, cpu_type_box=box, cpu_type_extra=extra)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "unexpected window while waiting for Login")
    assert "'CLICK Programming Software'" in result["reason"] and result["step"] == "connect"
    assert fake.cpu_type_shown == 1 and "cpu_type_ok" not in fake.events
    assert not set(box[1]) & set(fake.pressed)
    assert fake.pressed.count("Connect") == 1


def test_an_error_box_met_by_the_cleanup_is_not_what_stopped_the_run(tmp_path, setup):
    """An error box that the cleanup meets is reported apart from what stopped the run.

    ``click_error`` names only a box that stopped the run. Here a timeout stops the run, and the
    cleanup meets a box while it disconnects. The result reports that box in
    ``cleanup_click_error`` and leaves ``click_error`` None."""
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check", error_on="disconnect")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(fake, out, code, result, "timed out after 0.3 s waiting for the Syntax Check")
    assert result["click_error"] is None and result["cleanup_click_error"] == "PTC-013"
    assert not fake.error_answered
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "could not disconnect: CLICK error PTC-013" in log


def test_click_error_reads_only_a_code_then_a_message():
    window = cd.Window(1, "#32770", "CLICK Programming Software", 2, True, (0, 0, 1, 1))

    def static(text: str) -> cd.Control:
        return cd.Control(3, 1, "Static", text, 65535, True, True, (0, 0, 1, 1))

    error = cr.click_error(window, [static("PTC-013\r\nTimeout on\nattempting it.")])
    assert error == ("PTC-013", "Timeout on attempting it.")
    assert cr.click_error(window, [static("Disconnect from PLC?")]) is None
    assert cr.click_error(window, [static("PTC-013")]) is None
    other = cd.Window(1, "TfrmStartup", "Startup", 2, True, (0, 0, 1, 1))
    assert cr.click_error(other, [static("PTC-013\nTimeout")]) is None


def test_a_window_that_closes_while_dumped_is_left_out_quietly(tmp_path, setup):
    """A window that closes between the listing and its screenshot is left out quietly.

    CLICK's main window did this while CLICK closed."""
    csv, exe = setup
    fake = FakeClick(tmp_path, surprise="save")
    original = fake.idle

    def idle(hwnd: int, timeout: float) -> bool:
        window = fake.wins.get(hwnd)
        if window is not None and window.title == "Set a Project Password":
            fake._drop(window)  # It closes between the listing and its screenshot
        return original(hwnd, timeout)

    fake.idle = idle
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "'Set a Project Password'")
    assert "no screenshot" not in (out / "run.log").read_text(encoding="utf-8")


def test_closing_click_retitles_its_main_window_first(tmp_path, setup):
    """After WM_CLOSE, CLICK titles its main window "CLICK Programming Software (Version4.00)"
    until the window goes. The runner waits until the window has gone, and then decodes."""
    csv, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.events[-2:] == ["close", "exit"] and fake.exited_cleanly
    assert "decode" in result["timings"]


def test_a_timeout_aborts_and_disconnects(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(fake, out, code, result, "timed out after 0.3 s waiting for the Syntax Check")
    assert result["step"] == "syntax_check"
    # CLICK is connected and has no dialog open, so the cleanup disconnects before it ends CLICK
    assert fake.commands[-1] == "Disconnect" and not fake.connected


def test_two_plcs_abort(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, plc_rows=2)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the Connect dialog lists 2 PLC(s), and the runner connects only when it lists exactly 1",
    )
    assert "timed out" not in result["reason"]
    assert "Connect" not in fake.pressed


def test_a_second_plc_listed_late_aborts(tmp_path, setup, monkeypatch):
    """The scan lists the PLCs one at a time. The list must stay the same for PLC_SETTLE."""
    csv, exe = setup
    monkeypatch.setattr(cr, "PLC_SETTLE", 0.5)
    fake = FakeClick(tmp_path, late_row=0.2)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the Connect dialog lists 2 PLC(s), and the runner connects only when it lists exactly 1",
    )
    assert "Connect" not in fake.pressed


def test_a_plc_listed_while_dumping_is_seen_before_connect(tmp_path, setup):
    """The PLC list is read again right before Connect is pressed."""
    csv, exe = setup
    fake = FakeClick(tmp_path)
    original = fake.screenshot

    def screenshot(hwnd: int, path: Path) -> bool:
        if "-connect_dialog-" in path.name:
            fake.late_row_at = 0.0
        return original(hwnd, path)

    fake.screenshot = screenshot
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, "--record")
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the Connect dialog lists 2 PLC(s) as Connect is about to be pressed, and the runner connects only when it lists exactly 1",
    )
    assert "Connect" not in fake.pressed


def test_a_connect_dialog_not_scanning_the_lan_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, same_lan=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "the Connect dialog does not scan the same LAN")
    assert "Connect" not in fake.pressed


def test_no_plc_times_out(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="scan")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the Connect dialog lists 0 PLC(s). The runner timed out after 0.3 s waiting for one PLC in the list",
    )


def test_a_status_bar_naming_no_plc_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, plc_pane=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(fake, out, code, result, "the status bar names no PLC (")
    assert "No select CPU" not in result["reason"] and "C2-03CPU" in result["reason"]
    assert result["step"] == "dont_read" and result["plc"] is None


@pytest.mark.parametrize(("plc", "ok"), [("Conformance", True), ("Other", False)])
def test_plc_names_the_plc_to_connect_to(tmp_path, setup, plc, ok):
    csv, exe = setup
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, "--plc", plc)
    if ok:
        assert code == cr.EXIT_OK, result["reason"]
        assert result["plc"] == "192.168.1.241(Conformance)"
    else:
        assert_aborted(
            fake,
            out,
            code,
            result,
            "connected to 192.168.1.241(Conformance), not to the PLC named 'Other'",
        )


def test_plc_with_a_status_bar_that_cannot_be_read_aborts(tmp_path, setup):
    """The run stops when --plc asks for a check that the status bar cannot give."""
    csv, exe = setup
    fake = FakeClick(tmp_path, status_bar=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, "--plc", "Conformance", timeout=0.3)
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the status bar cannot be read to confirm the PLC named 'Conformance'. The runner timed out",
    )
    assert result["step"] == "dont_read" and result["plc"] is None


def test_a_status_bar_unreadable_at_first_confirms_once_it_reads(tmp_path, setup):
    """The bar is read over the whole wait, not judged on its first reading."""
    csv, exe = setup
    fake = FakeClick(tmp_path)
    original, misses = fake.status_bar, [5]

    def slow(hwnd: int) -> list[str] | None:
        if fake.connected and misses[0]:
            misses[0] -= 1
            return None
        return original(hwnd)

    fake.status_bar = slow
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, "--plc", "Conformance")
    assert code == cr.EXIT_OK, result["reason"]
    assert misses == [0] and result["plc"] == "192.168.1.241(Conformance)"
    assert "unconfirmed" not in (out / "run.log").read_text(encoding="utf-8")


def test_a_missing_startup_button_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, startup_buttons=2)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "2 textless operation button(s), expected 3")
    assert fake.pressed == []


def test_dont_read_not_taking_aborts_before_ok(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, dont_read_takes=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(fake, out, code, result, "'Don't read' did not become checked after the press")
    assert fake.pressed[-1] == "Don't read the project from the PLC."
    assert not fake.connected


def test_a_refused_login_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, password="other")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "CLICK refused the login")


def test_ctrl_c_ends_click(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, interrupt="set_clipboard")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "interrupted (Ctrl+C)")
    assert result["step"] == "paste"


def test_an_error_ends_click(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, fail="command")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "OSError: command failed")


def test_ctrl_c_while_dumping_still_ends_click(tmp_path, setup):
    """Even when the cleanup itself is interrupted, CLICK is ended and the result written."""
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check")
    original = fake.screenshot

    def interrupted(hwnd: int, path: Path) -> bool:
        if path.parent.name == "abort":
            raise KeyboardInterrupt
        return original(hwnd, path)

    fake.screenshot = interrupted
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.2)
    assert code == cr.EXIT_ABORTED
    assert "timed out after 0.2 s" in result["reason"]
    assert fake.terminated and not fake.is_running and result["click"]["closed"] is True
    assert "the cleanup was cut short: KeyboardInterrupt()" in (out / "run.log").read_text(
        encoding="utf-8"
    )


def test_ctrl_c_while_ending_click_still_ends_it(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check", interrupt="terminate")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.2)
    assert code == cr.EXIT_ABORTED and result["status"] == "aborted"
    assert fake.terminated and not fake.is_running and result["click"]["closed"] is True
    assert "the cleanup was cut short: KeyboardInterrupt()" in (out / "run.log").read_text(
        encoding="utf-8"
    )


def test_ending_click_is_tried_again_when_cut_short(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, interrupt="terminate")
    stderr = io.StringIO()
    runner = cr.Run(
        fake, cr.Settings("record", tmp_path / "out", exe=exe, poll=0.001), stderr=stderr
    )
    runner.pid = fake.launch(exe)
    runner.end_click_surely()
    assert fake.terminated and not fake.is_running
    assert runner.result["click"]["closed"] is True
    assert "ending CLICK failed: KeyboardInterrupt()" in stderr.getvalue()


def test_click_that_cannot_be_ended_is_reported(tmp_path, setup):
    """record ends CLICK rather than closing it, and a terminate that fails shows in the result."""
    _, exe = setup
    fake = FakeClick(tmp_path, fail="terminate")
    out = tmp_path / "out"
    code, result = run(fake, out, None, exe, timeout=0.2)
    assert code == cr.EXIT_ABORTED and result["status"] == "aborted"
    assert result["reason"] == "OSError: terminate failed"
    assert result["click"]["closed"] is not True
    assert fake.is_running


@pytest.mark.parametrize(
    ("switches", "reason"),
    [
        ({"interrupt": "click_processes"}, "interrupted (Ctrl+C) before CLICK was started"),
        (
            {"fail": "click_processes"},
            "the checks before starting CLICK failed: OSError: click_processes failed",
        ),
    ],
)
def test_the_checks_failing_still_write_the_result(tmp_path, setup, capsys, switches, reason):
    csv, exe = setup
    fake = FakeClick(tmp_path, **switches)
    code, result = run(fake, tmp_path / "out", csv, exe, capsys=capsys)
    assert code == cr.EXIT_REFUSED
    assert result["status"] == "refused" and result["reason"] == reason
    assert fake.pid is None


def test_click_exiting_by_itself_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check")
    real = fake._post_command

    def crash(hwnd: int, command_id: int) -> None:
        real(hwnd, command_id)
        if command_id == cd.SYNTAX_CHECK:
            fake.is_running = False

    fake._post_command = crash
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_ABORTED
    assert "CLICK exited while waiting" in result["reason"]
    assert result["click"]["closed"] is True


# ---------------------------------------------------------------------------
# A busy CLICK: the paste, a hang, the status bar
# ---------------------------------------------------------------------------


def test_a_slow_paste_is_waited_out_without_a_message(tmp_path, setup):
    """CLICK freezes during the paste for longer than the dialog timeout. The runner waits and
    sends CLICK nothing while it is frozen."""
    csv, exe = setup
    fake = FakeClick(tmp_path, hang_on="paste", hang_for=0.6)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.2, paste_timeout=10)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.sent_while_hung == []
    assert result["timings"]["paste"] >= 0.6
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "paste done: CLICK answers on 3 polls in a row, and its status bar shows rung 2" in log
    before, after = result["status_bar"]["before_paste"], result["status_bar"]["pasted"]
    assert "1:1:A" in before and "2:1:A" in after
    assert "0000/8000" in before and "0000/8000" in after


def test_a_paste_the_status_bar_does_not_show_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="paste")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3, paste_timeout=10)
    assert_aborted(
        fake, out, code, result, "CLICK answers again, but after 0.3 s its status bar does not"
    )
    assert result["step"] == "paste"
    assert "1:1:A" in result["reason"]
    assert "Syntax Check" not in fake.commands


def test_a_paste_with_no_status_bar_to_read_ends_when_click_answers(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, status_bar=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert code == cr.EXIT_OK, result["reason"]
    assert result["timings"]["dont_read"] >= 0.3  # The runner read the bar until the wait ended
    assert result["status_bar"] == {
        "connected": None,
        "before_paste": None,
        "pasted": None,
        "disconnected": None,
    }
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "status bar: cannot be read" in log
    assert "the connection is unconfirmed: the status bar cannot be read" in log
    assert "(no status bar to check it with)" in log
    assert result["plc"] is None


def test_a_hung_click_is_dumped_without_a_message_and_ended(tmp_path, setup, monkeypatch):
    """When CLICK stops answering for good, the runner dumps its windows without a message and
    ends CLICK. The dump takes no screenshot, because Windows would show its ghost window. The
    cleanup does not disconnect."""
    csv, exe = setup
    monkeypatch.setattr(cr, "STATUS_EVERY", 0.05)
    fake = FakeClick(tmp_path, hang_on="syntax_check", hang_for=60)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert code == cr.EXIT_ABORTED
    assert "timed out after 0.3 s waiting for the Syntax Check" in result["reason"]
    assert fake.sent_while_hung == []
    assert fake.terminated and not fake.is_running and result["click"]["closed"] is True
    dumps = [json.loads(p.read_text(encoding="utf-8")) for p in (out / "abort").glob("*.json")]
    assert dumps and not list((out / "abort").glob("*.png"))
    assert all("edit_text" not in c for d in dumps for c in d["controls"])
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "does not answer. Its dump has no edit text and no PNG." in log
    assert "not disconnecting: CLICK does not answer" in log
    assert "CLICK does not answer. The runner is still waiting for the Syntax Check result" in log
    assert "Disconnect" not in fake.commands


def test_a_status_bar_out_of_reach_leaves_the_connection_unconfirmed(tmp_path, setup):
    """Win32Desktop.status_bar refuses a buffer that a 32-bit CLICK cannot reach.

    The runner logs the refusal once and leaves the connection unconfirmed."""
    csv, exe = setup
    fake = FakeClick(tmp_path)

    def out_of_reach(hwnd: int) -> list[str] | None:
        raise OSError("the buffer for SB_GETTEXT lies at 0x100000000")

    fake.status_bar = out_of_reach
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert code == cr.EXIT_OK, result["reason"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert log.count("status bar: the buffer for SB_GETTEXT lies at 0x100000000") == 1
    assert "the connection is unconfirmed" in log and result["plc"] is None


def test_a_stale_scr_file_aborts(tmp_path, setup):
    """A leftover Scr*.tmp that the save does not rewrite aborts the run.

    The runner never deletes CLICK's temp folder, and the folder is named after the main window's
    hwnd. A CLICK whose main window gets an earlier CLICK's hwnd can find that CLICK's Scr*.tmp
    files there. The runner would decode such a file as part of the project."""
    csv, exe = setup
    fake = FakeClick(tmp_path, leftover=("Scr2.tmp",))
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "Scr2.tmp in CLICK's temp folder predates the paste")
    assert result["step"] == "save" and result["scr_before_paste"] == ["Scr2.tmp"]
    assert not (out / "click").exists()


def test_a_scr_file_the_save_rewrites_is_noted(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, leftover=("Scr1.tmp",))
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert result["scr_before_paste"] == ["Scr1.tmp"]
    assert (out / "click" / "Scr1.tmp").read_bytes() == fake.pasted


def test_a_long_wait_logs_the_status_bar(tmp_path, setup, monkeypatch):
    csv, exe = setup
    monkeypatch.setattr(cr, "STATUS_EVERY", 0.05)
    fake = FakeClick(tmp_path, stall="syntax_check")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=5, paste_timeout=0.4)
    assert_aborted(fake, out, code, result, "timed out after 0.4 s waiting for the Syntax Check")
    log = (out / "run.log").read_text(encoding="utf-8")
    assert log.count("status bar:  | Bit | Integer | Integer(2 words) |") >= 3
    assert "| RUN | 0000/8000 | C2-03CPU | 2:1:A |  |  | 192.168.1.241(Conformance) |" in log


def test_a_paste_shows_by_the_cursor_or_the_steps():
    def bar(rung: int, steps: int) -> cr.StatusBar:
        return cr.StatusBar(("RUN", f"{steps:04d}/8000", "C2-03CPU", f"{rung}:1:A"))

    assert bar(2, 0).shows_paste(bar(1, 0), 1)  # The cursor moved and the step count stayed
    assert bar(1, 4).shows_paste(bar(1, 0), 1)
    assert not bar(1, 0).shows_paste(bar(1, 0), 1)
    assert not bar(2, 0).shows_paste(bar(1, 0), 2)


@pytest.mark.parametrize(
    ("title", "file"),
    [
        (
            "CLICK Programming Software (Version4.00) - NewProject4.ckp - [Main Program]",
            "NewProject4.ckp",
        ),
        ("CLICK Programming Software (Version4.00) - NewProject7.ckp", "NewProject7.ckp"),
        ("CLICK Programming Software (Version4.00) - rung.ckp - [Main Program]", "rung.ckp"),
        (
            "CLICK Programming Software (Version4.00) - a - b.ckp - [Main Program] (Not Responding)",
            "a - b.ckp",
        ),
        ("CLICK Programming Software (Version4.00) - rung.ckp (Not Responding)", "rung.ckp"),
        ("CLICK Programming Software", None),
    ],
)
def test_the_project_file_in_the_main_title(title, file):
    assert cr._project_file(title) == file


# ---------------------------------------------------------------------------
# try: CLICK's instruction dialogs
# ---------------------------------------------------------------------------

TRY_CASES = [
    {
        "row": "control",
        "case": "DS1 = DS2 + 1",
        "instruction": "math",
        "mode": "decimal",
        "fields": {"result": "DS1", "formula": "DS2 + 1"},
    },
    {
        "row": "A9",
        "case": "SD1",
        "instruction": "math",
        "mode": "decimal",
        "fields": {"result": "SD1", "formula": "DS1 + 1"},
    },
    {
        "row": "A10",
        "case": "YD0 (hex)",
        "instruction": "math",
        "mode": "hex",
        "fields": {"result": "YD0", "formula": "DH1 + DH2"},
    },
    {
        "row": "control",
        "case": "block DS1..DS2 to DS11",
        "instruction": "copy",
        "mode": "block",
        "fields": {"source": "DS1", "source_end": "DS2", "destination": "DS11"},
    },
    {
        "row": "B1",
        "case": "block DS1..DS2 to YD1",
        "instruction": "copy",
        "mode": "block",
        "fields": {"source": "DS1", "source_end": "DS2", "destination": "YD1"},
    },
    {"row": "B8", "case": "X001", "instruction": "out", "fields": {"address": "X001"}},
]
# A Receive that reads coils into C1, with the lists left as the dialog opens them (CPU Port2,
# MODBUS, Function Code 01)
RECEIVE = {
    "row": "B7",
    "case": "receive coils into C1",
    "instruction": "receive",
    "fields": {
        "slave_address": "1",
        "master_address": "C1",
        "receiving": "C100",
        "success": "C101",
        "error": "C102",
        "exception": "DS100",
    },
}


class Nicknames:
    """A stand-in for read_nicknames without a database. It records its calls.

    The fake's SC_.mdb is not a database."""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, list[str]]] = []

    def __call__(self, mdb: Path, addresses: list[str]) -> dict[str, str | None]:
        self.calls.append((mdb, list(addresses)))
        return {a: f"_{a}" if a != "SD23" else None for a in addresses}


def run_try(
    fake: FakeClick,
    tmp_path: Path,
    exe: Path,
    cases: object,
    *args: str,
    timeout: float = 5,
    nicknames: Nicknames | None = None,
    out: Path | None = None,
    **run_args: object,
) -> tuple[int, dict]:
    file = tmp_path / "cases.json"
    file.write_text(json.dumps(cases), encoding="utf-8")
    out = out or tmp_path / "out"
    argv = ["try", str(file), "--out", str(out), "--click-exe", str(exe)]
    argv += ["--timeout", str(timeout), "--paste-timeout", str(timeout), *args]
    code = cr.main(
        argv,
        desktop=fake,
        prepare=Prepare(),
        read_nicknames=nicknames or Nicknames(),
        stderr=io.StringIO(),
        **run_args,
    )
    result_file = out / "result.json"
    return code, json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}


def test_try_records_each_answer(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, syntax_lines={"Copy": "Main Program : Rung 1 : warning W0301: x."})
    nicknames = Nicknames()
    cases = {"cases": TRY_CASES, "nicknames": ["SD21", "SD23"]}

    code, result = run_try(fake, tmp_path, exe, cases, nicknames=nicknames)

    assert code == cr.EXIT_OK, result["reason"]
    answers = [(c["row"], c["outcome"], c["code"]) for c in result["cases"]]
    assert answers == [
        ("control", "accepted", None),
        ("A9", "refused", "OBJ-003"),
        ("A10", "accepted", None),
        ("control", "accepted", None),
        ("B1", "refused", "OBJ-004"),
        ("B8", "refused", "OBJ-004"),
    ]
    refused = result["cases"][1]
    assert refused["message"] == "The entered address is outside the range."
    assert refused["syntax_check"] is None
    assert refused["fields"] == {"result": "SD1", "formula": "DS1 + 1"}
    # The runner picks each mode before it fills the fields, because picking Hex empties them
    assert fake.entered[2] == ("Math", "hex", {"result": "YD0", "formula": "DH1 + DH2"})
    assert fake.entered[3][1] == "block" and fake.entered[4][1] == "block"
    # An accepted case's lines leave out the codes that the check of the empty program reports
    assert result["cases"][0]["syntax_check"]["lines"] == []
    copy = result["cases"][3]["syntax_check"]
    assert copy["lines"] == ["Main Program : Rung 1 : warning W0301: x."]
    assert copy["errors"] == 1 and "Rung 2 : error C0201" in copy["text"]
    assert "Rung 1 : error C0201" in result["baseline_syntax_check"]["text"]
    # After an accepted case the runner sends Syntax Check, Delete and Syntax Check. After a
    # refused case it presses the box's OK and then Cancel.
    assert fake.commands == [
        "Syntax Check",
        "Math...",
        "Syntax Check",
        "Delete",
        "Syntax Check",
        "Math...",
        "Math...",
        "Syntax Check",
        "Delete",
        "Syntax Check",
        "Copy...",
        "Syntax Check",
        "Delete",
        "Syntax Check",
        "Copy...",
        "Out...",
        "Disconnect",
    ]
    assert fake.pressed.count("Cancel") == 3 and fake.placed is None
    # The nicknames come from a copy of the new project's SC_.mdb, not from CLICK's file
    assert nicknames.calls == [(out_mdb := tmp_path / "out" / "SC_.mdb", ["SD21", "SD23"])]
    assert out_mdb.read_bytes() == b"mdb"
    assert result["nicknames"] == {"SD21": "_SD21", "SD23": None}
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "SD21: '_SD21'" in log and "SD23: no row" in log
    # The project was never saved, so the runner ends CLICK instead of closing it. It disconnects first.
    assert not fake.connected and fake.terminated and not fake.saved
    assert list(result["timings"])[-5:] == ["nicknames", "baseline", "try", "disconnect", "close"]
    assert all(c["seconds"] is not None for c in result["cases"])


def test_a_syntax_check_that_never_starts_is_posted_again(tmp_path, setup, monkeypatch):
    _, exe = setup
    monkeypatch.setattr(cr, "SYNTAX_REPOST_AFTER", 0.3)
    fake = FakeClick(tmp_path, quick_checks=3)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:3]})
    assert code == cr.EXIT_OK, result["reason"]
    assert [c["outcome"] for c in result["cases"]] == ["accepted", "refused", "accepted"]
    # The check after each Delete comes right after the check before it, and CLICK ignores it
    ignored = fake.events.count("check_ignored")
    assert ignored == 2
    assert fake.commands.count("Syntax Check") == 1 + 2 * 2 + ignored
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert log.count("Output is still empty after 0.3 s. Posting Syntax Check again.") == ignored


def test_no_syntax_check_is_posted_again_while_click_does_not_answer(tmp_path, setup, monkeypatch):
    _, exe = setup
    monkeypatch.setattr(cr, "SYNTAX_REPOST_AFTER", 0.2)
    # Output stays empty for a second while CLICK does not answer. Posting again then
    # would queue checks behind a busy CLICK
    fake = FakeClick(tmp_path, quick_checks=3, hang_on="check_ignored", hang_for=1.0)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.events.count("check_ignored") == 1
    assert "WM_COMMAND" not in fake.sent_while_hung
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert log.count("Posting Syntax Check again") == 1


def test_try_record_dumps_each_case(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:2]}, "--record")
    assert code == cr.EXIT_OK, result["reason"]
    assert result["nicknames"] is None and "nicknames" not in result["timings"]
    labels = {p.name.split("-")[1] for p in (tmp_path / "out" / "record").glob("*.json")}
    assert {"baseline", "case01_filled", "case01_answer", "case02_answer"} <= labels


class Stored:
    """A stand-in for read_stored that reads the fake's Scr*.tmp files as text.

    It raises ValueError for a file in a case folder that *fails* names."""

    def __init__(self, *, fails: tuple[str, ...] = ()) -> None:
        self.read: list[Path] = []
        self.fails = fails

    def __call__(self, scr: Path) -> dict[str, object]:
        self.read.append(scr)
        if scr.parent.parent.name in self.fails:
            raise ValueError("Not an SC-SCR file")
        return {"text": scr.read_text(encoding="utf-8")}


def test_try_keep_saves_each_accepted_case(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    stored = Stored()
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES}, "--keep", read_stored=stored)
    assert code == cr.EXIT_OK, result["reason"]
    assert result["keep"] is True
    saves = tmp_path / "out" / "saves"
    kept = {c["row"] + c["case"]: c["kept"] for c in result["cases"]}
    accepted = [c for c in result["cases"] if c["outcome"] == "accepted"]
    assert [Path(c["kept"]["ckp"]).name for c in accepted] == [
        "case01.ckp",
        "case03.ckp",
        "case04.ckp",
    ]
    assert all(c["kept"] is None for c in result["cases"] if c["outcome"] != "accepted")
    assert len(kept) == len(TRY_CASES)
    # Each save is the project with that case's instruction in rung 1, copied as it was then
    for case, title in zip(accepted, ["Math", "Math", "Copy"], strict=True):
        folder = Path(case["kept"]["ckp"]).with_suffix("")
        assert folder.parent == saves and Path(case["kept"]["ckp"]).read_bytes() == b"ckp"
        assert sorted(p.name for p in (folder / "click").iterdir()) == ["Project.ini", "Scr1.tmp"]
        text = f"placed {title} ({folder.name}.ckp)"
        assert case["kept"]["stored"] == {"Scr1.tmp": {"text": text}}
        assert case["kept"]["csv"] == [str(folder / "csv" / "main.csv")]
        assert case["kept"]["main"] and "X001" in case["kept"]["main"][0]
        assert case["kept"]["legacy"] == [] and case["kept"]["error"] is None
    # The runner saves before each Delete. Each later check names the project from the last save.
    first = ["Syntax Check", "Math...", "Syntax Check", "Save Project As", "Delete"]
    assert fake.commands[:5] == first
    assert fake.commands.count("Save Project As") == 3
    assert accepted[1]["syntax_check"]["project"] == "case01"
    assert result["baseline_syntax_check"]["project"] == "NewProject4"
    # The runner decodes once CLICK has ended, and it ends CLICK rather than closing it
    assert fake.terminated and not fake.exited_cleanly
    assert list(result["timings"])[-4:] == ["try", "disconnect", "close", "decode"]
    assert [p.parent.parent.name for p in stored.read] == ["case01", "case03", "case04"]


def test_read_stored_reads_the_tags_click_stored():
    # The Scr1.tmp that CLICK saved for a Copy of 005 into DS1
    scr = Path(__file__).parent / "fixtures" / "click_runner" / "copy_5_ds1_Scr1.tmp"
    assert cr._read_stored(scr) == {
        "program": "Main Program",
        "prog_idx": 1,
        "rungs": [
            [
                {
                    "row": 0,
                    "column": 31,
                    "class": "Copy",
                    "type": 10017,
                    "tags": {"0x6074": "5", "0x6076": "DS1", "0x1201": "", "0x0000": ""},
                    "indexed": {},
                }
            ],
            [],
        ],
        "error": None,
    }


def test_try_without_keep_saves_nothing(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]}, read_stored=Stored())
    assert code == cr.EXIT_OK, result["reason"]
    assert result["keep"] is False and result["cases"][0]["kept"] is None
    assert not fake.saved and not (tmp_path / "out" / "saves").exists()
    assert "decode" not in result["timings"]


def test_a_kept_case_that_cannot_be_read_fails_once_all_are_read(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(
        fake, tmp_path, exe, {"cases": TRY_CASES}, "--keep", read_stored=Stored(fails=("case03",))
    )
    assert code == cr.EXIT_ABORTED
    assert result["status"] == "aborted" and result["step"] == "decode"
    assert result["reason"] == (
        "decoding the kept cases failed: RuntimeError: the copies of case03 could not be read"
    )
    by_name = {Path(c["kept"]["ckp"]).stem: c["kept"] for c in result["cases"] if c["kept"]}
    assert by_name["case03"]["error"] == "ValueError: Not an SC-SCR file"
    assert by_name["case04"]["error"] is None and by_name["case04"]["stored"]


def test_the_cases_kept_before_an_abort_are_decoded(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, delete_works=False)
    out = tmp_path / "out"
    code, result = run_try(
        fake, tmp_path, exe, {"cases": TRY_CASES}, "--keep", read_stored=Stored()
    )
    assert_aborted(fake, out, code, result, "Delete did not leave the main program empty")
    assert result["step"] == "try"
    (case,) = result["cases"]
    assert case["kept"]["stored"] == {"Scr1.tmp": {"text": "placed Math (case01.ckp)"}}
    assert case["kept"]["error"] is None


def test_a_box_that_closes_the_dialog_is_an_acceptance(tmp_path, setup):
    _, exe = setup

    def judge(title: str, mode: str | None, values: dict[str, str]) -> object:
        return ("warn", "OBJ-050", "Something to know.")

    fake = FakeClick(tmp_path, judge=judge)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert code == cr.EXIT_OK, result["reason"]
    (case,) = result["cases"]
    assert (case["outcome"], case["code"], case["message"]) == (
        "accepted",
        "OBJ-050",
        "Something to know.",
    )
    assert case["syntax_check"] is not None and fake.placed is None


def test_a_dialog_closed_with_nothing_placed_stops_the_run(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, places=False)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:2]})
    assert_aborted(fake, out, code, result, "names rung 1 for the missing END, not rung 2")
    (case,) = result["cases"]
    assert case["outcome"] == "other" and "Rung 1 : error C0201" in case["syntax_check"]["text"]
    assert "Delete" not in fake.commands


def test_a_box_that_closes_the_dialog_with_nothing_placed_stops_the_run(tmp_path, setup):
    _, exe = setup

    def judge(title: str, mode: str | None, values: dict[str, str]) -> object:
        return ("warn", "OBJ-099", "Refused and closed.")

    fake = FakeClick(tmp_path, judge=judge, places=False)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert_aborted(fake, out, code, result, "No instruction was placed in rung 1")
    (case,) = result["cases"]
    assert (case["outcome"], case["code"]) == ("other", "OBJ-099")


def test_a_baseline_without_the_end_error_in_rung_1_stops_the_run(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    fake.placed = "Out"  # Rung 1 already holds an instruction
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert_aborted(fake, out, code, result, "does not name rung 1 for its missing END")
    assert result["step"] == "baseline" and result["cases"] == []


def test_a_box_shown_while_filling_stops_the_run(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, box_on_fill="DS2 + 1")
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert_aborted(fake, out, code, result, "CLICK error OBJ-1001")
    assert fake.entered == []  # OK was never pressed
    assert result["cases"][0]["outcome"] is None


@pytest.mark.parametrize(
    ("case", "opens_with", "reason"),
    [
        (0, {2005: 1}, "Math's button 2005 (2005) is checked as the dialog opens"),
        (0, {2007: 0}, "Math's button 2007 (2007) is not checked as the dialog opens"),
        (3, {5024: 1}, "Copy's button 5024 (5024) is checked as the dialog opens"),
        (5, {5009: 0, 5010: 1}, "Out's button 5009 (5009) is not checked as the dialog opens"),
        (5, {5008: 1}, "Out's button 5008 (5008) is checked as the dialog opens"),
    ],
)
def test_a_dialog_that_opens_otherwise_stops_the_run(tmp_path, setup, case, opens_with, reason):
    _, exe = setup
    fake = FakeClick(tmp_path, opens_with=opens_with)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": [TRY_CASES[case]]})
    assert_aborted(fake, out, code, result, reason)
    assert fake.entered == []


def test_a_question_after_ok_stops_the_run(tmp_path, setup):
    _, exe = setup

    def judge(title: str, mode: str | None, values: dict[str, str]) -> object:
        return "question" if title == "Copy" else judge_like_click(title, mode, values)

    fake = FakeClick(tmp_path, judge=judge)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES})
    assert_aborted(fake, out, code, result, "CLICK asked something the runner does not answer")
    assert result["step"] == "try" and result["click_error"] is None
    assert [c["outcome"] for c in result["cases"]] == ["accepted", "refused", "accepted", "other"]
    assert result["cases"][3]["message"] == "Replace the instruction?"


def test_an_error_box_not_owned_by_the_dialog_still_aborts(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, error_on="dialog")
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert_aborted(fake, out, code, result, "CLICK error PTC-013")
    assert result["click_error"] == "PTC-013"


def test_a_delete_that_leaves_the_instruction_aborts(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, delete_works=False)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES})
    assert_aborted(fake, out, code, result, "Delete did not leave the main program empty")
    # CLICK accepted the case, but then the run stopped. The stop records the answer, and a
    # resume tries the case again.
    (entry,) = result["cases"]
    assert entry["outcome"] is None and entry["stops"][-1]["outcome"] == "accepted"
    assert entry["syntax_check"]["lines"] == []


def test_a_field_closed_in_the_mode_is_not_taken(tmp_path, setup):
    _, exe = setup
    case = {
        "row": "x",
        "case": "a range in single mode",
        "instruction": "copy",
        "mode": "single",
        "fields": {"source": "DS1", "source_end": "DS2", "destination": "DS3"},
    }
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case, TRY_CASES[0]]})
    assert code == cr.EXIT_OK, result["reason"]
    first, second = result["cases"]
    assert first["outcome"] == "not_taken" and first["code"] is None
    assert first["message"] == "these fields are closed for entry in single mode: source_end"
    assert first["read_back"] == {"source": "DS1", "destination": "DS3"}
    assert first["syntax_check"] is None
    # The runner never presses OK. It presses Cancel and tries the next case.
    assert fake.entered == [("Math", "decimal", {"result": "DS1", "formula": "DS2 + 1"})]
    assert "Cancel" in fake.pressed and second["outcome"] == "accepted"
    assert fake.commands[:3] == ["Syntax Check", "Copy...", "Math..."]


@pytest.mark.parametrize(
    ("cases", "reason"),
    [
        ([], "expected an object with a list under 'cases'"),
        ({"cases": []}, "lists no cases"),
        ({"cases": [{"row": "A1"}]}, "case 1 needs a 'row' and a 'case'"),
        (
            {"cases": [{**TRY_CASES[0], "instruction": "sequencer"}]},
            "'instruction' is not one of math, copy, out",
        ),
        ({"cases": [{**TRY_CASES[0], "mode": None}]}, "'mode' is not one of decimal, hex"),
        ({"cases": [{**TRY_CASES[5], "mode": "single"}]}, "Out has no modes"),
        (
            {"cases": [{**TRY_CASES[3], "mode": "spread"}]},
            "'mode' is not one of single, block, pack, unpack, fill",
        ),
        ({"cases": [{**TRY_CASES[0], "fields": {"source": "DS1"}}]}, "Math has no field source"),
        ({"cases": [{**TRY_CASES[0], "fields": {}}]}, "'fields' must name at least one field"),
        ({"cases": [{**TRY_CASES[0], "extra": 1}]}, "unknown keys: extra"),
        ({"cases": TRY_CASES, "nicknames": ["SD99999"]}, "cannot read the cases"),
        (
            {"cases": [TRY_CASES[0], {**TRY_CASES[1], "case": TRY_CASES[0]["case"]}]},
            "case 2 (A9 DS1 = DS2 + 1) has the same 'case' id as case 1. Give each case its own 'case'.",
        ),
        ({"cases": [{**TRY_CASES[0], "choices": {"port": "x"}}]}, "Math has no list port"),
        ({"cases": [{**RECEIVE, "choices": {"port": ""}}]}, "'choices' must name lists"),
        (
            {"cases": [{**RECEIVE, "choices": {"protocol": "x"}}]},
            "Receive has no list protocol (its lists: port, function, addressing, word_swap)",
        ),
        ({"cases": [{**TRY_CASES[0], "options": {"x": 1}}]}, "Math has no option buttons"),
        (
            {"cases": [{**TRY_CASES[3], "options": {"Termination Code": 2}}]},
            "'options' must name option buttons, each with 1 (checked) or 0",
        ),
        (
            {"cases": [{**TRY_CASES[3], "options": {"Termination Code": True}}]},
            "'options' must name option buttons, each with 1 (checked) or 0",
        ),
        (
            {"cases": [{**TRY_CASES[3], "options": {"": 1}}]},
            "'options' must name option buttons, each with 1 (checked) or 0",
        ),
        (
            {"cases": [{**TRY_CASES[3], "options": {"5000": 1}}]},
            "Copy has no option button 5000 (its option buttons: 5019, 5020, 5036, 5037, 5021, "
            "5024)",
        ),
    ],
)
def test_try_refuses_a_bad_cases_file(tmp_path, setup, cases, reason):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, cases)
    assert code == cr.EXIT_REFUSED
    assert result["status"] == "refused" and reason in result["reason"]
    assert fake.pid is None


def test_the_cases_file_loads():
    """The checked-in editor_cases.json loads, and it has cases for the table's rows.

    The table is pyrung's and laddercodec's table of what CLICK's editor accepts. The rows
    checked are A1 to A10, B1 to B6 and B8.
    """
    cases, nicknames = cr.load_cases(Path(cd.__file__).parent / "editor_cases.json")
    rows = {case.row for case in cases}
    assert {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"} <= rows
    assert {"B1", "B2", "B3", "B4", "B5", "B6", "B8"} <= rows
    assert {"SD21", "SD22", "SD24", "SD25", "SD26"} <= set(nicknames)


# ---------------------------------------------------------------------------
# try: option buttons, operators after the fields, and the dialog's controls
# ---------------------------------------------------------------------------

# A copy of a number with a decimal point into TXT. Copy relabels 5019 and 5020 as Real
# Numbering and Exponential Numbering.
COPY_REAL = {
    "row": "D1",
    "case": "1.5 to TXT1 exponential",
    "instruction": "copy",
    "mode": "single",
    "fields": {"source": "1.5", "destination": "TXT1"},
    "options": {"Exponential Numbering": 1},
}
# A copy of an integer into TXT. 5019 and 5020 read Copy Value and Copy Binary, and Suppress
# zero and Do not suppress zero (5036, 5037) show beside them.
COPY_VALUE = {
    "row": "D3",
    "case": "DS1 to TXT1 binary",
    "instruction": "copy",
    "mode": "single",
    "fields": {"source": "DS1", "destination": "TXT1"},
    "options": {"Copy Binary": 1},
}
# A copy of a counter value into a float. Termination Code shows, but it is disabled.
COPY_COUNT = {
    "row": "D4",
    "case": "CTD1 to DF1",
    "instruction": "copy",
    "mode": "single",
    "fields": {"source": "CTD1", "destination": "DF1"},
}
# A copy of TXT into TXT with a termination code. The code's field is enabled once
# Termination Code is checked.
COPY_TERMINATED = {
    "row": "D2",
    "case": "TXT1 to TXT11 terminated",
    "instruction": "copy",
    "mode": "single",
    "fields": {"source": "TXT1", "destination": "TXT11", "termination_code": "$0D"},
    "options": {"Termination Code": 1},
}
COMPARE = {
    "row": "E1",
    "case": "DS1 >= DS2",
    "instruction": "compare",
    "mode": ">=",
    "fields": {"a": "DS1", "b": "DS2"},
}
SEARCH = {
    "row": "E2",
    "case": "search DS1..DS10 for 5, continuous",
    "instruction": "search",
    "mode": ">",
    "fields": {"value": "5", "start": "DS1", "end": "DS10", "result": "DS20", "found": "C1"},
    "options": {"Continuous Search": 1, "5022": 0},
}


def test_an_option_is_found_by_the_label_it_shows_now(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_REAL]})
    assert code == cr.EXIT_OK, result["reason"]
    (case,) = result["cases"]
    assert case["outcome"] == "accepted" and case["options"] == {"Exponential Numbering": 1}
    # 5020 read "Do not suppress zero" when the dialog opened, and the fields relabelled it
    assert fake.option_states == [{5019: 0, 5020: 1, 5036: 1, 5037: 0, 5021: 0, 5024: 0}]
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "option 'Exponential Numbering' (5020) reads 1 after 1 press(es)" in log


def test_an_option_is_found_by_its_id(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    case = {**COPY_REAL, "options": {"5020": 1, "5024": 1}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.option_states[0][5020] == 1 and fake.option_states[0][5024] == 1


def test_an_option_already_as_asked_is_not_pressed(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, lost_presses=OPTION_ALL_LOST)
    case = {**COPY_REAL, "options": {"Real Numbering": 1}}  # 5019 opens checked
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    assert "lost_press" not in fake.events


# More presses lost than the runner makes
OPTION_ALL_LOST = cr.OPTION_PRESSES + 1


@pytest.mark.parametrize(
    ("case", "options", "reason"),
    [
        # 1.5 into TXT1: 5019 and 5020 read Real Numbering and Exponential Numbering. 5036
        # reads Suppress zero, but it is hidden.
        (COPY_REAL, {"Copy Binary": 1}, "no option button shows 'Copy Binary'"),
        (COPY_REAL, {"Suppress zero": 1}, "option 'Suppress zero' (5036) is closed for entry"),
        (COPY_REAL, {"5036": 1}, "option 'Suppress zero' (5036) is closed for entry"),
        # CTD1 into DF1: Termination Code shows, but it is disabled
        (
            COPY_COUNT,
            {"Termination Code": 1},
            "option 'Termination Code' (5021) is closed for entry",
        ),
        # A press on a radio button only checks it, so the runner refuses to uncheck one
        (
            COPY_VALUE,
            {"Copy Value": 0},
            "option 'Copy Value' (5019) is a checked radio button, and a press cannot uncheck it",
        ),
    ],
)
def test_an_option_that_cannot_be_set_is_not_taken(tmp_path, setup, case, options, reason):
    _, exe = setup
    fake = FakeClick(tmp_path)
    case = {**case, "options": options}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken" and answer["message"] == reason
    # The runner answered once Cancel closed the dialog. It pressed neither OK nor any option.
    assert fake.entered == [] and "Cancel" in fake.pressed
    assert any(c["id"] == 5020 for c in answer["controls"])
    assert "option" not in fake.events


def test_an_option_is_found_by_the_copy_value_label(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_VALUE]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.option_states == [{5019: 0, 5020: 1, 5036: 1, 5037: 0, 5021: 0, 5024: 0}]


@pytest.mark.parametrize(
    "options",
    [
        {"Do not suppress zero": 1, "Suppress zero": 0},
        # Here 0 is asked first. The runner presses the pair asked for 1 first, so Suppress
        # zero already reads 0 when its turn comes.
        {"Suppress zero": 0, "Do not suppress zero": 1},
    ],
)
def test_a_label_shown_by_5036_and_hidden_5019_is_found_on_5036(tmp_path, setup, options):
    """For an integer copied into TXT, the runner finds Suppress zero and Do not suppress zero on
    5036 and 5037. Those two buttons show then, and 5019 and 5020 read Copy Value and Copy
    Binary."""
    _, exe = setup
    fake = FakeClick(tmp_path)
    case = {**COPY_VALUE, "options": options}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.option_states == [{5019: 1, 5020: 0, 5036: 0, 5037: 1, 5021: 0, 5024: 0}]


def test_two_visible_option_buttons_with_one_label_are_not_taken(tmp_path, setup):
    """Two visible option buttons with the same label leave the case not taken.

    CLICK has not been seen to show two such buttons. It shows 5036 only while 5019 reads Copy
    Value. If CLICK ever shows two, the runner does not pick one."""
    _, exe = setup
    fake = FakeClick(tmp_path)
    case = {**COPY_VALUE, "options": {"Suppress zero": 1}}

    def show_both(dialog: FakeWindow) -> None:  # 5019 reads Suppress zero beside 5036
        follow = dialog.on_text
        assert follow is not None

        def relabel() -> None:
            follow()
            next(c for c in dialog.controls if c.id == 5019).text = "Suppress zero"

        dialog.on_text = relabel

    fake.on_dialog = show_both
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken"
    assert answer["message"] == "option buttons 5019, 5036 all show 'Suppress zero'"


def test_a_lost_option_press_is_pressed_again(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, lost_presses=cr.OPTION_PRESSES - 1)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_REAL]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.events.count("lost_press") == cr.OPTION_PRESSES - 1
    assert fake.option_states[0][5020] == 1
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert f"(5020) reads 1 after {cr.OPTION_PRESSES} press(es)" in log
    assert log.count("does not read 1 0.2 s after a press") == cr.OPTION_PRESSES - 1


def test_an_option_is_read_again_before_it_is_pressed_again(tmp_path, setup):
    """The dialog stays busy for longer than the runner waits after a press, but the button
    already reads as asked.

    The runner reads the button again and does not press it a second time, which would uncheck
    it."""
    _, exe = setup
    fake = FakeClick(tmp_path, slow_options=True)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_TERMINATED]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.events.count("option") == 1 and fake.option_states[0][5021] == 1
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "(5021) does not read 1 0.2 s after a press" in log
    assert "(5021) reads 1 after 1 press(es)" in log


def test_an_option_changed_by_a_later_one_is_not_taken(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)

    def one_shot_unchecks_termination(dialog: FakeWindow) -> None:
        one_shot = next(c for c in dialog.controls if c.id == 5024)
        termination = next(c for c in dialog.controls if c.id == 5021)
        press = one_shot.on_press
        assert press is not None

        def both() -> None:
            press()
            fake._later("uncheck", lambda: setattr(termination, "checked", 0))

        one_shot.on_press = both

    fake.on_dialog = one_shot_unchecks_termination
    case = {**COPY_TERMINATED, "options": {"Termination Code": 1, "5024": 1}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken" and fake.entered == []
    assert answer["message"] == (
        "option 'Termination Code' (5021) reads 0 once the dialog was filled, not 1"
    )


def test_an_option_that_never_reads_as_asked_stops_the_run(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, lost_presses=OPTION_ALL_LOST)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_REAL]})
    reason = (
        "Copy's option 'Exponential Numbering' (5020) does not read 1 after "
        f"{cr.OPTION_PRESSES} presses"
    )
    assert_aborted(fake, out, code, result, reason)
    assert fake.events.count("lost_press") == cr.OPTION_PRESSES and fake.entered == []


def test_a_field_an_option_opens_is_filled_once_it_opens(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_TERMINATED]})
    assert code == cr.EXIT_OK, result["reason"]
    (case,) = result["cases"]
    assert case["outcome"] == "accepted"
    assert case["read_back"]["termination_code"] == "$0D"
    assert fake.entered[0][2]["termination_code"] == "$0D"
    assert fake.option_states[0][5021] == 1
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "Copy's termination_code field opened after a press. Filling it." in log


def test_a_field_open_after_filling_without_a_press_is_not_taken(tmp_path, setup):
    """If a field is closed while the fields are filled, the runner treats it as closed.

    It counts the field as open only if an option or a mode pressed after the fields opened it.
    Here the field opens with no press, and the case is not taken."""
    _, exe = setup
    fake = FakeClick(tmp_path)

    def opens_on_source(dialog: FakeWindow) -> None:  # 5023 is enabled once the source has text
        follow = dialog.on_text
        assert follow is not None
        termination = next(c for c in dialog.controls if c.id == 5023)
        source = next(c for c in dialog.controls if c.id == 5006)

        def text() -> None:
            follow()
            termination.enabled = termination.enabled or bool(source.value)

        dialog.on_text = text

    fake.on_dialog = opens_on_source
    case = {**COPY_TERMINATED, "options": {}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken"
    assert answer["message"] == "these fields are closed for entry in single mode: termination_code"
    assert 5023 not in fake.typed


def test_a_field_no_option_opens_is_not_taken(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    case = {**COPY_TERMINATED, "options": {}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken"
    assert answer["message"] == "these fields are closed for entry in single mode: termination_code"


def test_the_dialog_s_controls_are_kept_as_ok_finds_them(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_TERMINATED]})
    assert code == cr.EXIT_OK, result["reason"]
    controls = {c["id"]: c for c in result["cases"][0]["controls"]}
    assert controls[5021] == {
        "id": 5021,
        "cls": "Button",
        "text": "Termination Code",
        "enabled": True,
        "checked": 1,
    }
    assert controls[5023] == {
        "id": 5023,
        "cls": "Edit",
        "text": "",
        "enabled": True,
        "edit_text": "$0D",
    }
    assert controls[5019]["enabled"] is False and controls[1]["text"] == "OK"
    # Hidden buttons are left out, as is any class but Button, Static and Edit
    assert 5036 not in controls and 5037 not in controls
    assert {c["cls"] for c in controls.values()} <= {"Button", "Static", "Edit"}


def test_a_group_box_is_kept_in_the_controls(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)

    def group(dialog: FakeWindow) -> None:
        fake._control(dialog, "Button", "Option", -1)
        fake._control(dialog, "Static", "Source", -1)

    fake.on_dialog = group
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_TERMINATED]})
    assert code == cr.EXIT_OK, result["reason"]
    groups = [c for c in result["cases"][0]["controls"] if c["id"] == -1]
    assert [(c["cls"], c["text"]) for c in groups] == [("Button", "Option"), ("Static", "Source")]


def test_a_case_without_options_runs_as_before(tmp_path, setup):
    """A case that names no options presses no option button and wires nothing."""
    _, exe = setup
    fake = FakeClick(tmp_path, lost_presses=OPTION_ALL_LOST)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[3:4]})
    assert code == cr.EXIT_OK, result["reason"]
    (case,) = result["cases"]
    assert case["outcome"] == "accepted" and case["options"] == {} and case["wired"] is False
    assert result["wire"] is False
    commands = ["Syntax Check", "Copy...", "Syntax Check", "Delete", "Syntax Check", "Disconnect"]
    assert fake.commands == commands
    assert fake.clicks == [] and "lost_press" not in fake.events


# ---------------------------------------------------------------------------
# try --wire: each case in a rung of its own
# ---------------------------------------------------------------------------


def test_wire_places_an_output_behind_a_contact(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEARCH]}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    (case,) = result["cases"]
    assert case["outcome"] == "accepted" and case["wired"] is True and result["wire"] is True
    assert case["syntax_check"]["lines"] == []
    # The runner places the contact at A and then Search at AF. Delete removes the selected rung.
    assert fake.entered[0] == ("Contact Normally Open", None, {"address": cr.WIRE_CONTACT})
    assert fake.entered[1][:2] == ("Search", ">")
    assert fake.option_states[1] == {5021: 1, 5022: 0}
    assert fake.commands == [
        "Syntax Check",
        "Contact(NO)...",
        "Search...",
        "Syntax Check",
        "Delete",
        "Syntax Check",
        "Disconnect",
    ]
    assert fake.clicks == [cr.RUNG1_POINT] and fake.rung == []


def test_wire_gives_a_contact_its_coil(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COMPARE]}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    (case,) = result["cases"]
    assert case["outcome"] == "accepted" and case["syntax_check"]["lines"] == []
    # The runner presses the operator after it fills the fields
    assert fake.entered == [
        ("Compare (A with B)", ">=", {"a": "DS1", "b": "DS2"}),
        ("Out", None, {"address": cr.WIRE_COIL}),
    ]
    assert fake.commands == [
        "Syntax Check",
        "Compare...",
        "Out...",
        "Syntax Check",
        "Delete",
        "Syntax Check",
        "Disconnect",
    ]
    assert fake.clicks == [cr.RUNG1_POINT] and fake.rung == []


def test_a_contact_is_refused_without_wire(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COMPARE]})
    assert code == cr.EXIT_REFUSED
    assert result["reason"] == "Compare (A with B) is a contact. Run try with --wire to try it."
    assert fake.pid is None


def test_an_operator_closed_by_the_fields_is_not_taken(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    case = {**COMPARE, "fields": {"a": "TXT1", "b": "TXT2"}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken" and answer["message"] == "mode >= is closed for entry"
    assert fake.entered == [] and "Cancel" in fake.pressed
    shown = {c["id"] for c in answer["controls"]}
    assert {5006, 5007} <= shown and not {5008, 5009, 5010, 5011} & shown
    # The Compare contact was not placed, so there is no rung to delete
    assert "Delete" not in fake.commands and fake.clicks == []


def test_a_field_closed_before_the_operator_names_the_mode_it_was_filled_in(tmp_path, setup):
    """The runner fills Compare's fields in the mode that the dialog opened in (==).

    It picks the operator after that, so a field closed before then is reported with mode ==."""
    _, exe = setup
    fake = FakeClick(tmp_path)

    def close_b(dialog: FakeWindow) -> None:
        next(c for c in dialog.controls if c.id == 5003).enabled = False

    fake.on_dialog = close_b
    case = {**COMPARE, "fields": {"a": "TXT1", "b": "TXT2"}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    (answer,) = result["cases"]
    assert answer["outcome"] == "not_taken"
    assert (
        answer["message"]
        == "these fields are closed for entry in == mode: b. mode >= is closed for entry"
    )


@pytest.mark.parametrize("outcome", ["refused", "not_taken"])
def test_wire_deletes_the_contact_of_a_case_not_placed(tmp_path, setup, outcome):
    _, exe = setup
    fake = FakeClick(tmp_path)
    if outcome == "refused":
        case = {**SEARCH, "options": {}}
        fake.judge = lambda title, mode, values: ("OBJ-004", "No.") if title == "Search" else None
    else:
        case = {**SEARCH, "options": {"Copy Binary": 1}}
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == outcome
    assert fake.commands[-3:] == ["Delete", "Syntax Check", "Disconnect"]
    assert fake.clicks == [cr.RUNG1_POINT] and fake.rung == []


def test_wire_stops_on_a_rung_that_does_not_check_clean(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, syntax_lines={"Search": "Main Program : Rung 1 : warning W0301: x."})
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEARCH]}, "--wire")
    assert_aborted(fake, out, code, result, "the wired rung's Syntax Check names more than")
    (case,) = result["cases"]
    assert case["outcome"] == "other"
    assert case["syntax_check"]["lines"] == ["Main Program : Rung 1 : warning W0301: x."]


def test_wire_stops_on_a_contact_with_no_coil(tmp_path, setup):
    """The run stops when no coil is placed after the contact.

    CLICK then reports C0003, which the check of the empty program does not report."""
    _, exe = setup
    fake = FakeClick(tmp_path)
    original = fake._show_instruction

    def no_coil(spec: cr.Instruction) -> None:
        original(spec)
        fake.places = spec.title != "Out"

    fake._show_instruction = no_coil
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": [COMPARE]}, "--wire")
    assert_aborted(fake, out, code, result, "error C0003: There is no Coil instruction")
    assert result["cases"][0]["outcome"] == "other"


def test_wire_stops_when_delete_leaves_the_rung(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, delete_works=False)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEARCH]}, "--wire")
    assert_aborted(fake, out, code, result, "Delete did not leave the main program empty")


@pytest.mark.parametrize("views", [0, 2])
def test_wire_stops_without_one_ladder_view(tmp_path, setup, views):
    _, exe = setup
    fake = FakeClick(tmp_path, ladder_views=views)
    out = tmp_path / "out"
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEARCH]}, "--wire")
    assert_aborted(fake, out, code, result, "cannot select rung 1 for Delete after case 1")
    assert fake.clicks == []


def test_wire_keep_copies_each_accepted_rung(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    cases = {"cases": [SEARCH, COMPARE]}
    code, result = run_try(fake, tmp_path, exe, cases, "--wire", "--keep", read_stored=Stored())
    assert code == cr.EXIT_OK, result["reason"]
    saves = tmp_path / "out" / "saves"
    assert fake.copied == [["Contact Normally Open", "Search"], ["Compare (A with B)", "Out"]]
    for number, case in enumerate(result["cases"], 1):
        kept = case["kept"]
        assert kept["clip"] == str(saves / f"case{number:02d}.clip.bin")
        assert Path(kept["clip"]).read_bytes() == rung_payload()
        # The clipboard's CSV has the same form as main.csv: the header, then the rung
        assert kept["clip_csv"] == str(saves / f"case{number:02d}.clip.csv")
        lines = Path(kept["clip_csv"]).read_text(encoding="utf-8").splitlines()
        assert lines == RUNG_CSV.splitlines() and kept["clip_error"] is None
    # The runner saves, copies and then deletes, and it empties the clipboard before each Copy
    assert fake.commands[4:8] == ["Save Project As", "Copy", "Delete", "Syntax Check"]
    clipboard = [e for e in fake.events if e in ("empty_clipboard", "copy")]
    assert clipboard == ["empty_clipboard", "copy"] * 2
    assert fake.clicks == [cr.RUNG1_POINT] * 4


def test_wire_keep_records_a_clipboard_it_cannot_decode(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)

    def decode_clip(clip: Path, csv: Path) -> cr.ClipCsv:
        raise ValueError("Invalid magic")

    code, result = run_try(
        fake,
        tmp_path,
        exe,
        {"cases": [SEARCH]},
        "--wire",
        "--keep",
        read_stored=Stored(),
        decode_clip=decode_clip,
    )
    assert code == cr.EXIT_OK, result["reason"]
    kept = result["cases"][0]["kept"]
    assert kept["clip_csv"] is None and kept["clip_error"] == "ValueError: Invalid magic"
    assert kept["error"] is None and kept["main"]


UNKNOWN_CONTACT = (
    "ClickNick, rungs from 1: rung 1, ContactXX: ClickNick cannot read this ContactXX."
)


def keep_clip(tmp_path: Path, exe: Path, payload: bytes) -> dict[str, Any]:
    """Try SEARCH with ``--wire --keep`` while Edit > Copy gives *payload*.

    Return the case's ``kept`` entry."""
    fake = FakeClick(tmp_path)
    fake.copy_payload = payload
    code, result = run_try(
        fake, tmp_path, exe, {"cases": [SEARCH]}, "--wire", "--keep", read_stored=Stored()
    )
    assert code == cr.EXIT_OK, result["reason"]
    kept = result["cases"][0]["kept"]
    assert kept["error"] is None and kept["main"]  # The saved project still reads without error
    return kept


def logged(tmp_path: Path) -> str:
    return (tmp_path / "out" / "run.log").read_text(encoding="utf-8")


def test_wire_keep_names_an_instruction_laddercodec_cannot_read_in_a_clipboard(tmp_path, setup):
    """ClickNick names the instruction before laddercodec writes the CSV, whatever laddercodec
    does after that."""
    _, exe = setup
    kept = keep_clip(tmp_path, exe, unknown_contact_payload())
    assert kept["clip_error"].startswith(f"{UNKNOWN_CONTACT}; laddercodec")
    assert f"case01: laddercodec cannot read all of the clipboard: {UNKNOWN_CONTACT}" in logged(
        tmp_path
    )


def test_wire_keep_names_what_laddercodec_cannot_write(tmp_path, setup, monkeypatch):
    """If laddercodec cannot write the rung, no CSV is left.

    The case's ``clip_error`` gives what ClickNick found and then laddercodec's reason.
    laddercodec raises CsvWriteError for a rung that it cannot write, such as one that needs
    more than 32 rows."""
    _, exe = setup

    def write_csv(path: Path, rungs: list) -> None:
        Path(path).write_text("marker,A", encoding="utf-8")  # Write part of the file, then refuse
        raise laddercodec.CsvWriteError("rungs[0] needs more than 32 rows")

    monkeypatch.setattr(laddercodec, "write_csv", write_csv)
    kept = keep_clip(tmp_path, exe, unknown_contact_payload())
    assert kept["clip_error"] == (
        f"{UNKNOWN_CONTACT}; laddercodec: the CSV cannot be written: CsvWriteError: rungs[0]"
        " needs more than 32 rows"
    )
    assert kept["clip_csv"] is None
    assert not (tmp_path / "out" / "saves" / "case01.clip.csv").exists()
    assert "the clipboard decoded into" not in logged(tmp_path)


@pytest.mark.parametrize(
    ("payload", "unreadable"),
    [
        # Named by ClickNick, then by laddercodec's warning as it writes the marker rung
        (
            unknown_contact_payload,
            f"{UNKNOWN_CONTACT}; laddercodec UndecodedRungWarning, rungs from 0: rung 0, row 0"
            " is not decoded, and an undecoded marker stands in for it: no CSV token holds"
            " this unknown condition (96 bytes)",
        ),
        # Cells that laddercodec cannot walk. Decoding puts the marker rung in and warns.
        (
            unwalkable_payload,
            "laddercodec UndecodedRungWarning, rungs from 0: rung 0, row 0 is not decoded, and"
            " an undecoded marker stands in for it: grid row 0 has no cell 0 at 0xa60; decoding"
            " stopped, so this marker stands for rung 0 to the end",
        ),
    ],
)
def test_wire_keep_names_what_laddercodec_writes_a_marker_rung_for(
    tmp_path, setup, payload, unreadable
):
    _, exe = setup
    kept = keep_clip(tmp_path, exe, payload())
    assert kept["clip_error"] == unreadable
    (rung,) = read_csv(Path(kept["clip_csv"]))
    assert rung.comment is not None and rung.comment.startswith("UNDECODED: rung 0, row 0: ")
    assert f"case01: laddercodec cannot read all of the clipboard: {unreadable}" in logged(tmp_path)


def test_wire_keep_stops_when_copy_leaves_nothing(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, copies=False)
    fake.clipboard = b"left over"
    out = tmp_path / "out"
    code, result = run_try(
        fake,
        tmp_path,
        exe,
        {"cases": [SEARCH]},
        "--wire",
        "--keep",
        timeout=1,
        read_stored=Stored(),
    )
    assert_aborted(fake, out, code, result, "case01: Edit > Copy left no CLICK data")
    assert fake.clipboard is None  # The runner emptied it before the Copy


def test_wire_keep_stops_when_the_clipboard_cannot_be_emptied(tmp_path, setup, monkeypatch):
    _, exe = setup
    fake = FakeClick(tmp_path)

    def held() -> None:
        raise RuntimeError("OpenClipboard failed after 20 attempts")

    monkeypatch.setattr(fake, "empty_clipboard", held)
    monkeypatch.setattr(cr, "CLIPBOARD_WAIT", 1.0)
    out = tmp_path / "out"
    code, result = run_try(
        fake, tmp_path, exe, {"cases": [SEARCH]}, "--wire", "--keep", read_stored=Stored()
    )
    # The runner tries for CLIPBOARD_WAIT seconds before it stops
    reason = (
        "case01: the clipboard could not be emptied: OpenClipboard failed after 20 attempts. "
        "The runner timed out after 1 s waiting for the clipboard to be emptied"
    )
    assert_aborted(fake, out, code, result, reason)
    assert "Copy" not in fake.commands
    log = (out / "run.log").read_text(encoding="utf-8")
    assert log.count("Trying again.") == 1  # The same failure is logged once


@pytest.mark.parametrize("method", ["empty_clipboard", "set_clipboard"])
def test_the_runner_waits_for_a_clipboard_that_another_program_holds(tmp_path, setup, method):
    # Another program holds the clipboard for the first 50 tries (compare case413 in a live
    # run on 2026-11-18). ``set_clipboard`` is ``paste``'s, ``empty_clipboard`` that of
    # ``--keep``'s Edit > Copy
    csv, exe = setup
    if method == "set_clipboard":
        fake = FakeClick(tmp_path, clipboard_held=50)
        out = tmp_path / "out"
        code, result = run(fake, out, csv, exe)
    else:
        fake, code, result = try_again(
            tmp_path, exe, "held", {"cases": [SEARCH]}, "--wire", "--keep", clipboard_held=50
        )
        out = tmp_path / "held" / "out"
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.events.count("clipboard_held") == 50
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "the clipboard could not be" in log
    assert "after 50 failure(s)" in log
    if method == "set_clipboard":
        assert fake.pasted is not None
    else:
        assert result["cases"][0]["kept"]["clip"] is not None


def test_keep_without_wire_copies_nothing(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(
        fake, tmp_path, exe, {"cases": TRY_CASES[:1]}, "--keep", read_stored=Stored()
    )
    assert code == cr.EXIT_OK, result["reason"]
    kept = result["cases"][0]["kept"]
    assert kept["clip"] is None and kept["clip_csv"] is None and kept["clip_error"] is None
    assert "Copy" not in fake.commands and fake.clicks == []


def test_a_resume_refuses_cases_tried_otherwise_wired(tmp_path, setup):
    _, exe = setup
    fake, code, result = try_again(tmp_path, exe, "first", {"cases": [SEARCH]}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    first = tmp_path / "first" / "out"
    fake, code, result = try_again(
        tmp_path, exe, "second", {"cases": [SEARCH]}, "--resume", str(first)
    )
    assert code == cr.EXIT_REFUSED
    assert (
        "case 'search DS1..DS10 for 5, continuous' was tried with --wire there"
        in (result["reason"])
    )


def test_a_resume_reads_lines_written_before_options_and_wire(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, "--stop-after", "2")
    prev = tmp_path / "a" / "out"
    lines = read_log(prev)
    for line in lines:
        del line["options"], line["wired"]
    text = "".join(json.dumps(line) + "\n" for line in lines)
    (prev / cr.CASES_LOG).write_text(text, encoding="utf-8")
    fake, code, result = try_again(tmp_path, exe, "b", cases, "--resume", str(prev))
    assert code == cr.EXIT_OK, result["reason"]
    assert len(result["cases"]) == len(TRY_CASES)
    # The two answered cases are carried, and the third case is the first one tried
    assert fake.entered[0] == ("Math", "hex", TRY_CASES[2]["fields"])


def test_compare_and_search_in_the_cases_file_load(tmp_path):
    file = tmp_path / "cases.json"
    file.write_text(json.dumps({"cases": [COMPARE, SEARCH, COPY_TERMINATED]}), encoding="utf-8")
    cases, _ = cr.load_cases(file)
    assert [(c.instruction, c.mode, c.options) for c in cases] == [
        ("compare", ">=", {}),
        ("search", ">", {"Continuous Search": 1, "5022": 0}),
        ("copy", "single", {"Termination Code": 1}),
    ]
    assert cases[1].asks()["options"] == {"Continuous Search": 1, "5022": 0}


def test_the_ladder_view_click_is_made_in_one_place():
    """The runner never posts a mouse message itself. ``Desktop.click_ladder`` is the one caller
    of ``_post_click``, and it finds the ladder view first."""
    runner = Path(cr.__file__).read_text(encoding="utf-8")
    assert "_post_click" not in runner and "WM_LBUTTON" not in runner
    desktop = Path(cd.__file__).read_text(encoding="utf-8")
    assert desktop.count("self._post_click(") == 1


# ---------------------------------------------------------------------------
# try: long runs, written as they go and resumed
# ---------------------------------------------------------------------------


def read_log(out: Path) -> list[dict]:
    """Return the lines of ``DIR/cases.jsonl``."""
    lines = (out / cr.CASES_LOG).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def last_lines(out: Path) -> dict[str, dict]:
    """Return the last line for each case id, as a resume reads them."""
    return {line["id"]: line for line in read_log(out)}


def try_again(
    tmp_path: Path, exe: Path, name: str, cases: object, *args: str, **fake_args: object
) -> tuple[FakeClick, int, dict]:
    """Run ``run_try`` into ``tmp_path/<name>`` with a CLICK of its own.

    Each kept save's Scr*.tmp is read with ``Stored``, because the fake writes text there and
    the installed laddercodec may have no stored-tag walk."""
    (tmp_path / name).mkdir()
    fake = FakeClick(tmp_path / name, **fake_args)  # pyright: ignore[reportArgumentType]
    out = tmp_path / name / "out"
    code, result = run_try(fake, tmp_path, exe, cases, *args, out=out, read_stored=Stored())
    return fake, code, result


def test_try_writes_each_case_as_it_is_answered(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES})
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out"
    # The log has one line per case, in the order tried, and each line is the case's entry in
    # result.json
    assert read_log(out) == result["cases"]
    assert [c["index"] for c in result["cases"]] == [1, 2, 3, 4, 5, 6]
    assert [c["id"] for c in result["cases"]] == [c["case"] for c in TRY_CASES]
    assert result["files"]["cases"] == str(out / cr.CASES_LOG)
    assert (result["left"], result["carried"], result["stopped_at"]) == (0, 0, None)
    assert all(c["out"] == str(out) and c["stops"] == [] for c in result["cases"])
    # A case records each field's length limit and the field's text as read back before OK
    assert result["cases"][0]["limits"] == {"result": 30000, "formula": 30000}
    assert result["cases"][0]["read_back"] == TRY_CASES[0]["fields"]


def test_an_abort_marks_the_case_it_stopped_at(tmp_path, setup):
    _, exe = setup
    # Copy opens with One Shot checked, so the 4th case stops the run before OK
    fake = FakeClick(tmp_path, opens_with={5024: 1})
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES})
    assert_aborted(fake, tmp_path / "out", code, result, "button 5024 (5024) is checked")
    assert result["stopped_at"] == {"index": 4, "id": TRY_CASES[3]["case"]}
    assert result["left"] == 3
    lines = read_log(tmp_path / "out")
    assert [line["outcome"] for line in lines] == ["accepted", "refused", "accepted", None]
    assert lines[-1]["stops"] == [{"out": str(tmp_path / "out"), "reason": result["reason"]}]
    assert lines == result["cases"]


def test_resume_carries_the_answers_and_tries_the_rest(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    _, code, first = try_again(tmp_path, exe, "a", cases, opens_with={5024: 1})
    assert code == cr.EXIT_ABORTED
    prev = tmp_path / "a" / "out"
    fake, code, result = try_again(tmp_path, exe, "b", cases, "--resume", str(prev))
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "b" / "out"
    # The case that stopped the first run is tried again, with that stop kept
    assert fake.commands[1:2] == ["Copy..."] and fake.commands.count("Math...") == 0
    assert result["resumed_from"] == str(prev) and result["carried"] == 3
    assert [c["index"] for c in result["cases"]] == [1, 2, 3, 4, 5, 6]
    assert [c["out"] for c in result["cases"]] == [str(prev)] * 3 + [str(out)] * 3
    assert result["cases"][:3] == first["cases"][:3]
    assert result["cases"][3]["stops"] == first["cases"][3]["stops"]
    assert result["cases"][3]["outcome"] == "accepted" and result["left"] == 0
    # This run's log holds every case. The carried cases come first. The case tried again
    # comes next with its stops, so that a run killed during that case keeps them. Then each
    # case follows as it is answered.
    log = read_log(out)
    assert [line["index"] for line in log] == [1, 2, 3, 4, 4, 5, 6]
    assert log[3]["outcome"] is None and log[3]["stops"] == first["cases"][3]["stops"]
    assert list(last_lines(out).values()) == result["cases"]


def test_stop_after_then_resume_loses_and_repeats_nothing(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    whole, code, once = try_again(tmp_path, exe, "whole", cases)
    assert code == cr.EXIT_OK
    first, code, part = try_again(tmp_path, exe, "a", cases, "--stop-after", "2")
    assert code == cr.EXIT_OK, part["reason"]
    assert (part["stopped_after"], part["left"], part["stop_after"]) == (2, 4, 2)
    assert len(part["cases"]) == 2 and not first.connected and first.terminated
    second, code, rest = try_again(
        tmp_path, exe, "b", cases, "--resume", str(tmp_path / "a" / "out"), "--stop-after", "3"
    )
    assert code == cr.EXIT_OK and rest["left"] == 1 and rest["stopped_after"] == 3
    third, code, done = try_again(
        tmp_path, exe, "c", cases, "--resume", str(tmp_path / "b" / "out")
    )
    assert code == cr.EXIT_OK and done["left"] == 0 and done["stopped_after"] is None
    # Each case was tried in exactly one run, and the answers match one run of all the cases
    assert len(first.entered) + len(second.entered) + len(third.entered) == len(TRY_CASES)
    assert first.entered + second.entered + third.entered == whole.entered

    def answers(result: dict) -> list[tuple]:
        return [(c["index"], c["id"], c["outcome"], c["code"]) for c in result["cases"]]

    assert answers(done) == answers(once)


def test_a_case_that_stopped_two_runs_is_not_tried_again(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, opens_with={5024: 1})
    _, code, second = try_again(
        tmp_path, exe, "b", cases, "--resume", str(tmp_path / "a" / "out"), opens_with={5024: 1}
    )
    assert code == cr.EXIT_ABORTED and second["stopped_at"]["index"] == 4
    assert len(second["cases"][3]["stops"]) == 2
    fake, code, third = try_again(
        tmp_path, exe, "c", cases, "--resume", str(tmp_path / "b" / "out")
    )
    assert code == cr.EXIT_OK, third["reason"]
    # Case 4 is carried with no answer and its two stops. The runner tries the next Copy case.
    assert third["cases"][3]["outcome"] is None and len(third["cases"][3]["stops"]) == 2
    assert third["carried"] == 4 and third["left"] == 1
    assert [entry[0] for entry in fake.entered] == ["Copy", "Out"]


def crashes_on(*values: str) -> Callable[[str, str | None, dict[str, str]], object]:
    """Return a judge that makes CLICK exit on OK when a field holds one of *values*.

    It answers every other case as ``judge_like_click`` does."""

    def judge(title: str, mode: str | None, entered: dict[str, str]) -> object:
        if set(values) & set(entered.values()):
            return "crash"
        return judge_like_click(title, mode, entered)

    return judge


# TRY_CASES's third case holds this formula and its fifth this destination
THIRD, FIFTH = "DH1 + DH2", "YD1"
CRASH_REASON = "CLICK exited while waiting for CLICK's answer to case {}"


def test_a_case_that_crashed_click_is_recorded_as_crashed_on_resume(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    judge = crashes_on(THIRD)
    _, code, first = try_again(tmp_path, exe, "a", cases, judge=judge)
    prev = tmp_path / "a" / "out"
    # The crash stops the run. That run gives the case no outcome, and its stop says crashed
    assert code == cr.EXIT_ABORTED and first["step"] == "try"
    assert first["reason"].startswith(CRASH_REASON.format(3))
    assert first["stopped_at"] == {"index": 3, "id": TRY_CASES[2]["case"]}
    assert first["cases"][2]["outcome"] is None and first["crashed"] == [] and first["left"] == 4
    assert first["cases"][2]["stops"] == [
        {"out": str(prev), "reason": first["reason"], "crashed": True}
    ]
    assert first["click"]["closed"] is True
    fake, code, result = try_again(tmp_path, exe, "b", cases, "--resume", str(prev), judge=judge)
    assert code == cr.EXIT_OK, result["reason"]
    # The resume records the crash and goes on at the next case
    crashed = result["cases"][2]
    assert crashed["outcome"] == "crashed" and crashed["message"] == first["reason"]
    assert crashed["out"] == str(prev) and crashed["stops"] == first["cases"][2]["stops"]
    assert result["crashed"] == [{"index": 3, "id": TRY_CASES[2]["case"]}]
    assert (result["carried"], result["left"], result["stopped_at"]) == (3, 0, None)
    assert [entry[0] for entry in fake.entered] == ["Copy", "Copy", "Out"]
    assert [c["outcome"] for c in result["cases"]][3:] == ["accepted", "refused", "refused"]
    assert last_lines(tmp_path / "b" / "out")[TRY_CASES[2]["case"]] == crashed
    log = (tmp_path / "b" / "out" / "run.log").read_text(encoding="utf-8")
    assert f"case 3 ({TRY_CASES[2]['case']}) crashed CLICK in {prev}." in log


def test_a_second_crash_after_a_resume_is_recorded_on_the_next_resume(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    judge = crashes_on(THIRD, FIFTH)
    a, code, _ = try_again(tmp_path, exe, "a", cases, judge=judge)
    assert code == cr.EXIT_ABORTED
    b, code, second = try_again(
        tmp_path, exe, "b", cases, "--resume", str(tmp_path / "a" / "out"), judge=judge
    )
    # The resume records case 3 as crashed, accepts case 4, and case 5 crashes CLICK
    assert code == cr.EXIT_ABORTED and second["reason"].startswith(CRASH_REASON.format(5))
    assert second["crashed"] == [{"index": 3, "id": TRY_CASES[2]["case"]}]
    assert second["cases"][4]["stops"][-1]["crashed"] is True
    c, code, third = try_again(
        tmp_path, exe, "c", cases, "--resume", str(tmp_path / "b" / "out"), judge=judge
    )
    assert code == cr.EXIT_OK, third["reason"]
    assert third["crashed"] == [
        {"index": 3, "id": TRY_CASES[2]["case"]},
        {"index": 5, "id": TRY_CASES[4]["case"]},
    ]
    assert [c["outcome"] for c in third["cases"]] == [
        "accepted",
        "refused",
        "crashed",
        "accepted",
        "crashed",
        "refused",
    ]
    assert third["cases"][2]["out"] == str(tmp_path / "a" / "out")
    assert third["cases"][4]["out"] == str(tmp_path / "b" / "out")
    assert third["cases"][4]["message"] == second["reason"] and third["left"] == 0
    # Each case was tried once, the crashing ones too
    entered = a.entered + b.entered + c.entered
    assert [entry[0] for entry in entered] == ["Math", "Math", "Math", "Copy", "Copy", "Out"]


def test_click_exiting_after_it_answered_is_not_a_crash_of_the_case(tmp_path, setup):
    """CLICK closes the first case's dialog and then exits during the Syntax Check that
    follows. CLICK had answered the OK, so the case's stop does not have ``crashed``, and a
    resume tries the case again."""
    _, exe = setup
    cases = {"cases": TRY_CASES}
    (tmp_path / "a").mkdir()
    fake = FakeClick(tmp_path / "a")
    real = fake._post_command
    checks = [0]

    def exit_on_second_check(hwnd: int, command_id: int) -> None:
        if command_id == cd.SYNTAX_CHECK:
            checks[0] += 1
            if checks[0] == 2:
                fake.is_running = False
                return
        real(hwnd, command_id)

    fake._post_command = exit_on_second_check
    prev = tmp_path / "a" / "out"
    code, first = run_try(fake, tmp_path, exe, cases, out=prev)
    assert code == cr.EXIT_ABORTED and "CLICK exited while waiting for" in first["reason"]
    assert first["stopped_at"]["index"] == 1
    assert first["cases"][0]["stops"] == [{"out": str(prev), "reason": first["reason"]}]
    again, code, result = try_again(tmp_path, exe, "b", cases, "--resume", str(prev))
    assert code == cr.EXIT_OK and result["crashed"] == [] and len(again.entered) == 6


def test_a_last_line_cut_short_is_left_out(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, "--stop-after", "3")
    log = tmp_path / "a" / "out" / cr.CASES_LOG
    text = log.read_text(encoding="utf-8")
    log.write_text(text[: text.rindex("\n", 0, len(text) - 1) + 20], encoding="utf-8")
    fake, code, result = try_again(tmp_path, exe, "b", cases, "--resume", str(log.parent))
    assert code == cr.EXIT_OK, result["reason"]
    assert result["carried"] == 2 and len(fake.entered) == 4
    assert "line 3 is cut short. The runner leaves it out." in (
        tmp_path / "b" / "out" / "run.log"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("missing", "cannot read"),
        ("unknown", "case 'gone' is not in"),
        ("asks", "does not ask the same as in"),
        ("garbled", "line 1 is not JSON"),
        ("own", "--resume names the same folder as --out"),
    ],
)
def test_resume_refuses_answers_that_do_not_fit(tmp_path, setup, change, reason):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, "--stop-after", "2")
    prev = tmp_path / "a" / "out"
    log = prev / cr.CASES_LOG
    lines = read_log(prev)
    if change == "missing":
        log.unlink()
    elif change == "unknown":
        lines[0]["id"] = "gone"
    elif change == "asks":
        lines[1]["fields"] = {"result": "SD2", "formula": "DS1 + 1"}
    if change in ("unknown", "asks"):
        log.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    if change == "garbled":
        log.write_text("{\n" + log.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "b").mkdir()
    fake = FakeClick(tmp_path / "b")
    out = tmp_path / "b" / "out"
    if change == "own":
        prev = out
    code, result = run_try(fake, tmp_path, exe, cases, "--resume", str(prev), out=out)
    assert code == cr.EXIT_REFUSED
    assert reason in result["reason"] and fake.pid is None


def test_resume_with_keep_decodes_what_the_stopped_run_left(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, "--keep", "--stop-after", "1")
    prev = tmp_path / "a" / "out"
    # As if the first run's process had ended before it decoded its copies
    lines = read_log(prev)
    log = prev / cr.CASES_LOG
    log.write_text(json.dumps(lines[0]) + "\n", encoding="utf-8")
    assert lines[0]["kept"]["csv"] is None and lines[-1]["kept"]["csv"]
    stored = Stored()
    (tmp_path / "b").mkdir()
    fake = FakeClick(tmp_path / "b")
    out = tmp_path / "b" / "out"
    code, result = run_try(
        fake, tmp_path, exe, cases, "--keep", "--resume", str(prev), out=out, read_stored=stored
    )
    assert code == cr.EXIT_OK, result["reason"]
    carried, *rest = (c["kept"] for c in result["cases"] if c["kept"])
    assert carried["ckp"] == str(prev / "saves" / "case01.ckp")
    assert carried["csv"] == [str(out / "saves" / "case01" / "csv" / "main.csv")]
    assert [Path(k["ckp"]).name for k in rest] == ["case03.ckp", "case04.ckp"]
    assert [p.parent.parent for p in stored.read] == [
        prev / "saves" / "case01",
        out / "saves" / "case03",
        out / "saves" / "case04",
    ]
    # The runner writes the decoded entries again. A resume reads the last line for each case.
    assert last_lines(out)["DS1 = DS2 + 1"]["kept"]["csv"] == carried["csv"]
    assert all(c["kept"]["main"] for c in last_lines(out).values() if c["kept"])


def test_resume_reads_the_last_line_for_a_case(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, "--keep", "--stop-after", "1")
    lines = read_log(tmp_path / "a" / "out")
    assert [line["id"] for line in lines] == ["DS1 = DS2 + 1"] * 2
    assert lines[0]["kept"]["csv"] is None and lines[1]["kept"]["csv"] is not None


# ---------------------------------------------------------------------------
# try: what the dialog does not take, and its lists
# ---------------------------------------------------------------------------


def test_a_field_that_reads_back_otherwise_is_not_taken(tmp_path, setup):
    _, exe = setup
    case = {
        "row": "risky",
        "case": "single ٣ -> DS1",
        "instruction": "copy",
        "mode": "single",
        "fields": {"source": "٣", "destination": "DS1"},
    }
    fake = FakeClick(tmp_path, ansi_fields=True)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case, TRY_CASES[0]]})
    assert code == cr.EXIT_OK, result["reason"]
    entry = result["cases"][0]
    assert entry["outcome"] == "not_taken"
    assert entry["message"] == "these read back other than the case asked: source"
    assert entry["read_back"] == {"source": "?", "destination": "DS1"}
    assert [e[0] for e in fake.entered] == ["Math"]  # OK was pressed only for the next case


def test_receive_picks_its_lists_by_keys(tmp_path, setup):
    _, exe = setup
    registers = {
        **RECEIVE,
        "case": "receive registers into DD1",
        "choices": {"function": "03 - Read Holding Registers"},
        "fields": {**RECEIVE["fields"], "slave_address": "400001", "master_address": "DD1"},
    }
    # CLICK refuses Function Code 03 with a slave address meant for 01
    slave_for_01 = {**registers, "case": "registers from slave 1", "fields": RECEIVE["fields"]}
    back = {**RECEIVE, "case": "back to coils", "choices": {"function": "01 - Read Coil Status"}}
    fake = FakeClick(tmp_path)
    cases = [RECEIVE, registers, slave_for_01, back]
    code, result = run_try(fake, tmp_path, exe, {"cases": cases})
    assert code == cr.EXIT_OK, result["reason"]
    assert [(c["outcome"], c["code"]) for c in result["cases"]] == [
        ("accepted", None),
        ("accepted", None),
        ("refused", "OBJ-010"),
        ("accepted", None),
    ]
    assert fake.commands.count("Receive...") == 4
    # CLICK received each list as picked and each field as typed
    assert [values["function"] for _, _, values in fake.entered] == [
        "01 - Read Coil Status",
        "03 - Read Holding Registers",
        "03 - Read Holding Registers",
        "01 - Read Coil Status",
    ]
    assert fake.entered[0][2]["port"] == "CPU Port2"
    assert fake.entered[0][2]["master_address"] == "C1"
    # Each 03 case sends two Down keys to the list alone, from 01 to 03. The 01 cases send no
    # key, because 01 is already selected.
    assert [k for k in fake.keys if k[0] == "ComboBox"] == [("ComboBox", 0x28)] * 4
    assert result["cases"][1]["choices"] == {"function": "03 - Read Holding Registers"}
    assert result["cases"][0]["limits"]["receiving"] == 16
    # read_back holds every field as OK found it, with Slave ID and Number of Bits as the
    # dialog filled them
    assert result["cases"][0]["read_back"] == {**RECEIVE["fields"], "slave_id": "1", "count": "1"}
    assert "COM Port Setup" not in fake.pressed


def test_receive_picks_by_up_and_by_home(tmp_path, setup, monkeypatch):
    _, exe = setup
    registers = {"function": "03 - Read Holding Registers"}
    fields = {**RECEIVE["fields"], "slave_address": "400001", "master_address": "DS1"}
    # Word Swap shows OFF, and ON is the item above it
    up = {**RECEIVE, "choices": {**registers, "word_swap": "ON"}, "fields": fields}
    fake, code, result = try_again(tmp_path, exe, "up", {"cases": [up]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.entered[0][2]["word_swap"] == "ON"
    assert [k for k in fake.keys if k[0] == "ComboBox"] == [("ComboBox", 0x28)] * 2 + [
        ("ComboBox", 0x26)
    ]
    # A list that shows no item gets Home first, then Down
    monkeypatch.setitem(RECEIVE_LISTS, 5003, (["ON", "OFF"], -1))
    home = {**up, "case": "home", "choices": {**registers, "word_swap": "OFF"}}
    fake, code, result = try_again(tmp_path, exe, "home", {"cases": [home]})
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.entered[0][2]["word_swap"] == "OFF"
    assert [k[1] for k in fake.keys if k[0] == "ComboBox"] == [0x28, 0x28, 0x24, 0x28]
    assert "COM Port Setup" not in fake.pressed


def test_a_list_closed_for_entry_is_not_taken(tmp_path, setup):
    _, exe = setup
    # Word Swap is disabled under Function Code 01
    case = {**RECEIVE, "choices": {"word_swap": "ON"}}
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case, TRY_CASES[0]]})
    assert code == cr.EXIT_OK, result["reason"]
    first, second = result["cases"]
    assert (first["outcome"], first["message"]) == (
        "not_taken",
        "list word_swap is closed for entry",
    )
    assert [k for k in fake.keys if k[0] == "ComboBox"] == []
    assert [e[0] for e in fake.entered] == ["Math"] and second["outcome"] == "accepted"


# Cases from laddercodec's editor grids (tests/fixtures/editor_grids), one per dialog
COPY_FILL = {
    "row": "F1",
    "case": "fill DS1..DS10 with 5",
    "instruction": "copy",
    "mode": "fill",
    "fields": {"source": "5", "destination": "DS1", "destination_end": "DS10"},
}
TIMER = {
    "row": "T1",
    "case": "on delay T1, 100 sec, retained",
    "instruction": "timer",
    "mode": "on_delay",
    "fields": {"done": "T1", "preset": "100"},
    "choices": {"unit": "sec"},
    "options": {"retained": 1},
}
COUNTER = {
    "row": "K1",
    "case": "count up and down CT1 to 10",
    "instruction": "counter",
    "mode": "count_up_down",
    "fields": {"done": "CT1", "preset": "10"},
}
SHIFT = {
    "row": "S1",
    "case": "shift C1..C10",
    "instruction": "shift",
    "fields": {"start_bit": "C1", "end_bit": "C10"},
}
FOR = {
    "row": "L1",
    "case": "for 10, one shot",
    "instruction": "for",
    "fields": {"count": "10"},
    "options": {"oneshot": 1},
}
DRUM = {
    "row": "D1",
    "case": "time drum, 2 steps",
    "instruction": "drum",
    "mode": "time_drum",
    "fields": {
        "num_steps": "2",
        "num_outputs": "1",
        "current_step": "DS1",
        "accumulator": "TD1",
        "completion_flag": "C1",
        "outputs[0]": "Y001",
        "presets[0]": "100",
        "presets[1]": "200",
        "jump_step": "DS2",
    },
    "choices": {"unit": "sec"},
    "options": {"jog_enabled": 0, "jump_enabled": 1},
}
SEND = {
    "row": "M1",
    "case": "send registers to 192.168.1.10",
    "instruction": "send",
    "fields": {
        "slave_id": "1",
        "slave_address": "400001",
        "master_address": "DS1",
        "count": "2",
        "sending": "C100",
        "success": "C101",
        "error": "C102",
        "exception": "DS100",
        "ip": "192.168.1.10",
        "server_port": "502",
    },
    "choices": {
        "port": "CPU Port1",
        "function": "16 - Write Multiple Registers",
        "addressing": "Modbus 984 Addressing",
        "word_swap": "ON",
    },
}


def test_try_answers_the_seven_dialogs(tmp_path, setup):
    _, exe = setup
    cases = [COPY_FILL, TIMER, COUNTER, SHIFT, FOR, DRUM, SEND]
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": cases})
    assert code == cr.EXIT_OK, result["reason"]
    assert [c["outcome"] for c in result["cases"]] == ["accepted"] * 7
    assert [name for name in fake.commands if name.endswith("...")] == [
        "Copy...",
        "Timer...",
        "Counter...",
        "Shift Register...",
        "For...",
        "Drum...",
        "Send...",
    ]
    fill, timer, counter, shift, loop, drum, send = fake.entered
    assert fill[:2] == ("Copy", "fill")
    assert {k: fill[2][k] for k in COPY_FILL["fields"]} == COPY_FILL["fields"]
    assert shift[2] == SHIFT["fields"]
    assert loop[2] == FOR["fields"]
    assert fake.option_states[4] == {5003: 1}
    # Timer: the unit picked by keys, Retentive checked, and Current Value as CLICK filled it
    assert timer[:2] == ("Timer", "on_delay")
    assert timer[2] == {**TIMER["fields"], "unit": "sec", "accumulator": "TD1"}
    assert fake.option_states[1] == {5011: 1}
    assert result["cases"][1]["read_back"] == {**TIMER["fields"], "accumulator": "TD1"}
    # Counter: both read-only fields read back
    assert counter[:2] == ("Counter", "count_up_down")
    assert result["cases"][2]["read_back"] == {
        **COUNTER["fields"],
        "accumulator": "CTD1",
        "completion_bit": "CT1",
    }
    # Drum: Load New Step Number opened the step's field, which the runner filled then
    assert drum[:2] == ("Drum", "time_drum")
    assert drum[2] == {**DRUM["fields"], "unit": "sec"}
    assert fake.option_states[5] == {5016: 0, 5017: 1}
    # Send: the lists picked port first, the IP address set as four numbers
    assert send[2] == {**SEND["fields"], **SEND["choices"]}
    assert result["cases"][6]["read_back"] == SEND["fields"]
    assert result["cases"][6]["limits"]["server_port"] == 5
    assert "ip" not in result["cases"][6]["limits"]
    assert "COM Port Setup" not in fake.pressed
    # With --wire, each one that has a single input sits behind the contact X001, in a rung of
    # its own
    timer = {**TIMER, "options": {"retained": 0}}
    wired = [COPY_FILL, timer, SEND]
    fake, code, result = try_again(tmp_path, exe, "wire", {"cases": wired}, "--wire")
    assert code == cr.EXIT_OK, result["reason"]
    assert [c["outcome"] for c in result["cases"]] == ["accepted"] * 3
    assert fake.commands.count("Contact(NO)...") == 3


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        (TIMER, "A retentive Timer has a Reset input."),
        ({**TIMER, "options": {"5011": 1}}, "A retentive Timer has a Reset input."),
        # Only the open dialog shows which button has a label, so a label may name 5011
        (
            {
                **TIMER,
                "options": {"Current value will be retained while this timer is disabled.": 1},
            },
            "A retentive Timer has a Reset input.",
        ),
        (COUNTER, "Counter has a Reset input."),
        (SHIFT, "Shift Register has a Clock input and a Reset input."),
        (FOR, "For needs a Next after it."),
        (DRUM, "Drum has a Reset input."),
    ],
)
def test_wire_refuses_an_instruction_with_more_than_one_input(tmp_path, setup, case, reason):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_FILL, case]}, "--wire")
    assert code == cr.EXIT_REFUSED
    assert result["reason"] == (
        f"try --wire cannot place 1 case(s). The first is {case['case']!r}. {reason} --wire "
        "wires only an instruction's first input, and it places no Next. CLICK's Syntax Check "
        "would then report an error. Run try without --wire to try these cases."
    )
    assert fake.pid is None


def test_a_read_only_field_is_read_back_and_never_set(tmp_path, setup):
    _, exe = setup
    # A grid case may name what CLICK fills. The case is taken only if CLICK filled that
    timer = {
        **TIMER,
        "case": "timer names TD1",
        "fields": {**TIMER["fields"], "accumulator": "TD1"},
    }
    counter = {
        **COUNTER,
        "case": "counter names CTD2",
        "fields": {**COUNTER["fields"], "accumulator": "CTD2"},
    }
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [timer, counter]})
    assert code == cr.EXIT_OK, result["reason"]
    first, second = result["cases"]
    assert first["outcome"] == "accepted"
    assert (second["outcome"], second["message"]) == (
        "not_taken",
        "accumulator is read-only, and CLICK filled it with 'CTD1'",
    )
    # Each entry names the fields that the case gave and the runner never typed
    assert first["filled_by_click"] == second["filled_by_click"] == ["accumulator"]
    assert second["read_back"]["completion_bit"] == "CT1"
    # Timer's Current Value is 5007, and Counter's are 5006 and 5007. The runner set none
    assert not {5006, 5007} & set(fake.typed)
    assert [title for title, _, _ in fake.entered] == ["Timer"]


def test_off_delay_cannot_retain(tmp_path, setup):
    _, exe = setup
    case = {**TIMER, "mode": "off_delay"}
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    answer = result["cases"][0]
    assert answer["outcome"] == "not_taken"
    assert "is closed for entry" in answer["message"]
    assert fake.entered == []


def test_drum_takes_each_mode_and_refuses_a_pattern_cell(tmp_path, setup):
    _, exe = setup
    events = {
        **DRUM,
        "case": "event drum",
        "mode": "event_drum",
        "fields": {"num_steps": "1", "outputs[0]": "Y001", "events[0]": "X001"},
        "choices": {},
        "options": {},
    }
    both = {
        **events,
        "case": "time and event drum",
        "mode": "time_event_drum",
        "fields": {**events["fields"], "presets[0]": "100"},
    }
    pattern = {**events, "case": "a pattern cell", "fields": {"pattern[0][0]": "1"}}
    misplaced = {**DRUM, "case": "an event in a time drum", "fields": {"events[0]": "X001"}}
    unit = {**events, "case": "event drum in sec", "choices": {"unit": "sec"}}
    fake = FakeClick(tmp_path)
    cases = [events, both, pattern, misplaced, unit]
    code, result = run_try(fake, tmp_path, exe, {"cases": cases})
    assert code == cr.EXIT_OK, result["reason"]
    answers = [(c["outcome"], c["message"]) for c in result["cases"]]
    assert answers[:2] == [("accepted", None), ("accepted", None)]
    assert answers[2] == (
        "not_taken",
        "the Drum dialog's pattern is a grid whose cells have no control ids, so the runner "
        "cannot set a cell: pattern[0][0]",
    )
    assert answers[3] == (
        "not_taken",
        "these fields have no control in time_drum mode: events[0]",
    )
    assert answers[4] == ("not_taken", "list unit is closed for entry in event_drum mode")
    # In Time and Event, a step's duration has a column of its own (5130) beside its event.
    # Number of Outputs stays at the 1 that it opens with
    opened = {"num_outputs": "1", "unit": "ms"}
    assert fake.entered[0][2] == {**events["fields"], **opened}
    assert fake.entered[1][2] == {**both["fields"], **opened}
    assert fake.typed[5130] == "100" and fake.typed[5094] == "X001"


def test_send_refuses_a_port_the_plc_lacks_and_a_bad_address(tmp_path, setup):
    _, exe = setup
    slot = {**SEND, "case": "slot port", "choices": {**SEND["choices"], "port": "Slot0 Port1"}}
    bad = {**SEND, "case": "bad ip", "fields": {**SEND["fields"], "ip": "192.168.1.300"}}
    hidden = {
        **SEND,
        "case": "ip on port 2",
        "choices": {**SEND["choices"], "port": "CPU Port2"},
    }
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [slot, bad, hidden]})
    assert code == cr.EXIT_OK, result["reason"]
    answers = [(c["outcome"], c["message"]) for c in result["cases"]]
    items = SEND_LISTS[5000][0]
    assert answers[0] == (
        "not_taken",
        f"port: the list has no item 'Slot0 Port1' (its items: {items!r})",
    )
    assert answers[1] == (
        "not_taken",
        "ip '192.168.1.300' is not four numbers from 0 to 255, and an IP address control "
        "takes nothing else",
    )
    # CPU Port2 hides the server's fields
    assert answers[2] == (
        "not_taken",
        "these fields are closed for entry: ip, server_port",
    )
    assert fake.entered == []


def test_send_picks_its_port_before_its_function_code(tmp_path, setup):
    _, exe = setup
    # The case lists its choices in another order. A port pick sets the Function Code again,
    # so the runner picks in the dialog's order
    choices = dict(reversed(list(SEND["choices"].items())))
    case = {**SEND, "choices": choices}
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    assert result["cases"][0]["outcome"] == "accepted"
    assert fake.entered[0][2]["function"] == "16 - Write Multiple Registers"


def test_an_ip_address_control_reads_its_four_edits_from_left_to_right(monkeypatch):
    target = cd.Win32Desktop()
    sent: list[tuple[int, ...]] = []

    def send(hwnd: int, message: int, wparam: int = 0, lparam: int = 0) -> int:
        sent.append((hwnd, message, wparam, lparam))
        return 0

    monkeypatch.setattr(target, "_send", send)
    assert target.set_ip_address(7, (192, 168, 1, 10))
    assert sent == [(7, cd.IPM_SETADDRESS, 0, 0xC0A8010A)]
    with pytest.raises(ValueError, match="not four numbers"):
        target.set_ip_address(7, (192, 168, 1, 256))
    # EnumChildWindows lists the Edits from right to left. An Edit elsewhere is not one of them
    texts = {11: "10", 12: "1", 13: "168", 14: "192", 15: "x"}

    def edit(hwnd: int, parent: int, left: int) -> cd.Control:
        return cd.Control(hwnd, parent, "Edit", "", 5036, True, True, (left, 0, left + 8, 8))

    children = [edit(11, 7, 30), edit(12, 7, 20), edit(13, 7, 10), edit(14, 7, 0), edit(15, 9, 0)]
    monkeypatch.setattr(target, "controls", lambda hwnd: children)
    monkeypatch.setattr(target, "read_text", lambda hwnd: texts[hwnd])
    assert target.ip_address(7) == "192.168.1.10"
    texts[12] = None  # pyright: ignore[reportArgumentType]
    assert target.ip_address(7) is None


CHAIN = [
    ("OBJ-041", "The data type of the source and the destination do not match."),
    ("OBJ-024", "The entered range is not correct."),
]


def test_a_chain_of_error_boxes_is_one_answer(tmp_path, setup):
    _, exe = setup

    def judge(title: str, mode: str | None, values: dict[str, str]) -> object:
        return list(CHAIN) if title == "Copy" else None

    fake = FakeClick(tmp_path, judge=judge)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_FILL, TRY_CASES[0]]})
    assert code == cr.EXIT_OK, result["reason"]
    first, second = result["cases"]
    assert (first["outcome"], first["code"], first["message"]) == ("refused", *CHAIN[0])
    assert first["boxes"] == [list(box) for box in CHAIN]
    assert "ok_presses" not in first
    assert fake.pressed.count("OK") >= 2 and second["outcome"] == "accepted"
    assert "boxes" not in second


def test_a_box_that_stays_gets_a_second_ok(tmp_path, setup, monkeypatch):
    _, exe = setup
    monkeypatch.setattr(cr, "REPRESS_AFTER", 0.5)

    def judge(title: str, mode: str | None, values: dict[str, str]) -> object:
        return CHAIN[0] if title == "Copy" else None

    fake = FakeClick(tmp_path, judge=judge, sticky_boxes=1)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_FILL, TRY_CASES[0]]})
    assert code == cr.EXIT_OK, result["reason"]
    first, second = result["cases"]
    assert (first["outcome"], first["code"]) == ("refused", CHAIN[0][0])
    assert first["ok_presses"] == 2 and "boxes" not in first
    assert fake.events.count("ok_ignored") == 1
    assert second["outcome"] == "accepted"
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "the box is still open 0.5 s after its OK. Pressing OK again." in log


class ClosesBeforeTheSecondOk(FakeClick):
    """A CLICK whose error box closes just as the runner presses its OK a second time.

    CLICK ignores the first OK. With *at* "check", the box closes as the runner looks for
    its OK again. With *at* "post", it closes after that. The post of BM_CLICK then fails,
    as PostMessage fails on a window that has gone."""

    def __init__(self, *args, at: str, **kwargs) -> None:
        super().__init__(*args, sticky_boxes=1, **kwargs)
        self.at = at
        self.box: FakeWindow | None = None

    def close_box(self) -> None:
        assert self.box is not None
        self.wins[self.box.owner].enabled = True
        self._drop(self.box)
        self.box = None
        self.events.append("box_closed")

    def controls(self, hwnd: int) -> list[cd.Control]:
        if self.at == "check" and self.box is not None and hwnd == self.box.hwnd:
            self.close_box()
        return super().controls(hwnd)

    def press(self, hwnd: int) -> None:
        box = next(w for w in self.wins.values() if any(c.hwnd == hwnd for c in w.controls))
        if self.at == "post" and box is self.box:
            self.close_box()
            raise OSError(1400, "Invalid window handle.")
        ignored = self.events.count("ok_ignored")
        super().press(hwnd)
        if self.events.count("ok_ignored") > ignored:
            self.box = box


@pytest.mark.parametrize("at", ["check", "post"])
def test_a_box_that_closes_before_its_second_ok_is_the_answer(tmp_path, setup, monkeypatch, at):
    _, exe = setup
    monkeypatch.setattr(cr, "REPRESS_AFTER", 0.5)

    def judge(title: str, mode: str | None, values: dict[str, str]) -> object:
        return CHAIN[0] if title == "Copy" else None

    fake = ClosesBeforeTheSecondOk(tmp_path, judge=judge, at=at)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_FILL, TRY_CASES[0]]})
    assert code == cr.EXIT_OK, result["reason"]
    first, second = result["cases"]
    assert (first["outcome"], first["code"]) == ("refused", CHAIN[0][0])
    assert "ok_presses" not in first
    assert fake.events.count("box_closed") == 1
    assert second["outcome"] == "accepted"
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "the box closed before the runner pressed OK again" in log


def test_a_box_that_stays_after_two_oks_stops_the_run(tmp_path, setup, monkeypatch):
    _, exe = setup
    monkeypatch.setattr(cr, "REPRESS_AFTER", 0.5)
    fake = FakeClick(tmp_path, judge=lambda *_: CHAIN[0], sticky_boxes=2)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_FILL]})
    assert_aborted(
        fake,
        tmp_path / "out",
        code,
        result,
        "timed out after 5 s waiting for the error box to close",
    )


def test_more_than_max_boxes_stops_the_run(tmp_path, setup):
    _, exe = setup
    chain = [(f"OBJ-{n:03d}", "Again.") for n in range(cr.MAX_BOXES + 1)]
    fake = FakeClick(tmp_path, judge=lambda *_: chain)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COPY_FILL]})
    reason = f"CLICK showed more than {cr.MAX_BOXES} error boxes for one OK"
    assert_aborted(fake, tmp_path / "out", code, result, reason)


# Send under Function Code 16, with Word Swap OFF. Word Swap opens on OFF, and its first item
# is ON
SEND_NO_SWAP = {**SEND, "choices": {**SEND["choices"], "word_swap": "OFF"}}


def test_a_list_that_a_field_resets_is_picked_again(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, list_on_fill=("word_swap", "reset"))
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEND_NO_SWAP]})
    assert code == cr.EXIT_OK, result["reason"]
    (entry,) = result["cases"]
    assert entry["outcome"] == "accepted"
    assert fake.entered[0][2]["word_swap"] == "OFF"
    # The entry shows the list after the picks, once the fields were filled, and after the
    # second pick
    lists = entry["lists"]
    assert [lists[stage]["word_swap"]["selected"] for stage in lists] == [1, 0, 1]
    assert list(lists) == ["picked", "filled", "picked_again"]
    assert lists["filled"]["word_swap"] == {
        "items": ["ON", "OFF"],
        "selected": 0,
        "visible": True,
        "enabled": True,
    }
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "list 5003 shows 'ON' once the fields are filled. Picking 'OFF' again." in log


@pytest.mark.parametrize(
    ("effect", "message"),
    [
        (
            "stuck",
            "list word_swap shows 'ON' once the fields are filled, and again after the runner "
            "picked 'OFF' once more",
        ),
        ("closed", "list word_swap is closed for entry once the fields are filled"),
    ],
)
def test_a_list_that_a_field_changes_for_good_is_not_taken(tmp_path, setup, effect, message):
    _, exe = setup
    fake = FakeClick(tmp_path, list_on_fill=("word_swap", effect))
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEND_NO_SWAP]})
    assert code == cr.EXIT_OK, result["reason"]
    (entry,) = result["cases"]
    assert (entry["outcome"], entry["message"]) == ("not_taken", message)
    assert entry["lists"]["filled"]["word_swap"]["enabled"] == (effect != "closed")
    assert ("picked_again" in entry["lists"]) == (effect == "stuck")
    assert fake.entered == []


# A Send case that picks a port and no Function Code. The port pick sets the Function Code
# to 06, and the case takes that as CLICK's default
SEND_ON_PORT3 = {
    "row": "M2",
    "case": "send on CPU Port3",
    "instruction": "send",
    "fields": {"slave_id": "1"},
    "choices": {"port": "CPU Port3"},
}


def test_a_list_that_the_case_does_not_choose_keeps_what_the_picks_set(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEND_ON_PORT3]})
    assert code == cr.EXIT_OK, result["reason"]
    (entry,) = result["cases"]
    assert entry["outcome"] == "accepted"
    assert fake.entered[0][2]["function"] == "06 - Write Single Register"
    assert entry["lists"]["picked"]["function"]["selected"] == 1
    assert "picked_again" not in entry["lists"]


def test_a_list_that_the_case_does_not_choose_and_a_field_changes_is_not_taken(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, list_on_fill=("function", "reset"))
    code, result = run_try(fake, tmp_path, exe, {"cases": [SEND_ON_PORT3]})
    assert code == cr.EXIT_OK, result["reason"]
    (entry,) = result["cases"]
    assert (entry["outcome"], entry["message"]) == (
        "not_taken",
        "list function shows '05 - Write Single Coil' once the fields are filled. It showed "
        "'06 - Write Single Register' after the picks, and the case does not choose it",
    )
    # The runner does not pick in a list that the case does not choose
    assert "picked_again" not in entry["lists"]
    assert fake.entered == []


def test_a_mode_that_a_field_resets_is_not_taken(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, mode_resets_on_fill=True)
    code, result = run_try(fake, tmp_path, exe, {"cases": [COUNTER]})
    assert code == cr.EXIT_OK, result["reason"]
    (entry,) = result["cases"]
    assert (entry["outcome"], entry["message"]) == (
        "not_taken",
        "mode count_up_down is not checked once the fields are filled. The dialog shows mode "
        "count_up",
    )
    # The runner pressed the mode once, before the fields, and never again
    assert fake.pressed.count("Button@0") == 1
    assert fake.entered == []


class StallsInTheFill(FakeClick):
    """A CLICK that stops answering once the first field of an instruction dialog is set.

    With *on* "set", each later WM_SETTEXT to the dialog goes unanswered. With *on* "read", each
    later WM_GETTEXT to the dialog goes unanswered. With *on* "interrupt", setting the first
    field raises KeyboardInterrupt instead."""

    def __init__(self, *args, on: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.on = on
        self.stalled = False

    def _in_instruction(self, hwnd: int) -> bool:
        titles = {spec.title for spec in cr.INSTRUCTIONS.values()}
        return any(
            w.title in titles and any(c.hwnd == hwnd for c in w.controls)
            for w in self.wins.values()
        )

    def set_text(self, hwnd: int, text: str) -> bool:
        if not self._in_instruction(hwnd):
            return super().set_text(hwnd, text)
        if self.on == "interrupt" and not self.stalled:
            self.stalled = True
            raise KeyboardInterrupt
        if self.stalled and self.on == "set":
            return False
        answered = super().set_text(hwnd, text)
        self.stalled = True
        return answered

    def read_text(self, hwnd: int) -> str | None:
        if self.stalled and self.on == "read" and self._in_instruction(hwnd):
            return None
        return super().read_text(hwnd)


@pytest.mark.parametrize(
    ("on", "reason"),
    [
        ("set", "CLICK did not answer setting Copy's source_end field"),
        ("read", "CLICK did not answer reading Copy's source field"),
    ],
)
def test_a_stalled_click_stops_the_run_and_is_tried_again(tmp_path, setup, on, reason):
    _, exe = setup
    cases = {"cases": [TRY_CASES[3], TRY_CASES[0]]}
    (tmp_path / "a").mkdir()
    fake = StallsInTheFill(tmp_path / "a", on=on)
    out = tmp_path / "a" / "out"
    code, result = run_try(fake, tmp_path, exe, cases, out=out)
    assert_aborted(fake, out, code, result, reason)
    (entry,) = result["cases"]
    assert entry["outcome"] is None and entry["stops"][0]["reason"] == result["reason"]
    assert fake.entered == []
    # A resume tries it again, and the case after it
    fake, code, again = try_again(tmp_path, exe, "b", cases, "--resume", str(out))
    assert code == cr.EXIT_OK, again["reason"]
    assert again["carried"] == 0 and again["left"] == 0
    assert [e[0] for e in fake.entered] == ["Copy", "Math"]


def test_a_case_not_taken_is_answered_only_once_cancel_closed_it(tmp_path, setup):
    _, exe = setup
    case = {**RECEIVE, "choices": {"word_swap": "ON"}}
    fake = FakeClick(tmp_path, stall="cancel")
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]}, timeout=0.5)
    assert_aborted(fake, tmp_path / "out", code, result, "the Receive dialog to close")
    (entry,) = result["cases"]
    assert entry["outcome"] is None and len(entry["stops"]) == 1


def test_resume_with_keep_tries_an_accepted_case_without_its_save_again(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES[:2]}
    try_again(tmp_path, exe, "a", cases)
    prev = tmp_path / "a" / "out"
    assert read_log(prev)[0]["outcome"] == "accepted" and read_log(prev)[0]["kept"] is None
    (tmp_path / "b").mkdir()
    fake = FakeClick(tmp_path / "b")
    args = ("--keep", "--resume", str(prev))
    out = tmp_path / "b" / "out"
    code, result = run_try(fake, tmp_path, exe, cases, *args, out=out, read_stored=Stored())
    assert code == cr.EXIT_OK, result["reason"]
    # The refused case is carried. The accepted case is tried again so that it gets a save.
    assert result["carried"] == 1 and [e[0] for e in fake.entered] == ["Math"]
    assert result["cases"][0]["kept"]["ckp"].endswith("case01.ckp")


def test_resume_with_keep_decodes_each_case_into_a_folder_of_its_own(tmp_path, setup):
    _, exe = setup
    a, b = TRY_CASES[0], TRY_CASES[2]  # Both accepted
    (tmp_path / "a").mkdir()
    prev = tmp_path / "a" / "out"
    fake = FakeClick(tmp_path / "a")
    code, _ = run_try(fake, tmp_path, exe, {"cases": [a]}, "--keep", out=prev, read_stored=Stored())
    assert code == cr.EXIT_OK
    log = prev / cr.CASES_LOG
    log.write_text(log.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    # This cases file puts another accepted case first, so the carried case is case 2
    (tmp_path / "b").mkdir()
    fake = FakeClick(tmp_path / "b")
    out = tmp_path / "b" / "out"
    code, result = run_try(
        fake,
        tmp_path,
        exe,
        {"cases": [b, a]},
        "--keep",
        "--resume",
        str(prev),
        out=out,
        read_stored=Stored(),
    )
    assert code == cr.EXIT_OK, result["reason"]
    first, second = (c["kept"]["csv"] for c in result["cases"])
    assert first == [str(out / "saves" / "case01" / "csv" / "main.csv")]
    assert second == [str(out / "saves" / "case02" / "csv" / "main.csv")]
    assert result["cases"][1]["kept"]["ckp"] == str(prev / "saves" / "case01.ckp")


def test_a_resumed_run_that_stops_before_its_cases_keeps_their_lines(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, opens_with={5024: 1})
    prev = tmp_path / "a" / "out"
    fake, code, result = try_again(
        tmp_path, exe, "b", cases, "--resume", str(prev), error_on="connect"
    )
    assert code == cr.EXIT_ABORTED and result["step"] == "connect"
    # The carried answers and the stopped case's stops are in this run's log already
    lines = last_lines(tmp_path / "b" / "out")
    assert [line["index"] for line in lines.values()] == [1, 2, 3, 4]
    assert len(lines[TRY_CASES[3]["case"]]["stops"]) == 1
    fake, code, done = try_again(tmp_path, exe, "c", cases, "--resume", str(tmp_path / "b" / "out"))
    assert code == cr.EXIT_OK and done["carried"] == 3 and done["left"] == 0
    assert len(done["cases"][3]["stops"]) == 1


def test_a_ctrl_c_is_not_counted_as_a_stop(tmp_path, setup):
    _, exe = setup
    cases = {"cases": TRY_CASES}
    try_again(tmp_path, exe, "a", cases, "--stop-after", "3")
    # Two runs that each end on a Ctrl+C in case 4
    for prev, name in (("a", "b"), ("b", "c")):
        (tmp_path / name).mkdir()
        fake = StallsInTheFill(tmp_path / name, on="interrupt")
        args = ("--resume", str(tmp_path / prev / "out"))
        code, result = run_try(fake, tmp_path, exe, cases, *args, out=tmp_path / name / "out")
        assert code == cr.EXIT_ABORTED and result["stopped_at"]["index"] == 4
    fake, code, result = try_again(
        tmp_path, exe, "d", cases, "--resume", str(tmp_path / "c" / "out")
    )
    assert code == cr.EXIT_OK, result["reason"]
    # A stop by Ctrl+C does not count toward MAX_STOPS, so the case is tried again
    stops = result["cases"][3]["stops"]
    assert result["carried"] == 3 and result["cases"][3]["outcome"] == "accepted"
    assert [stop.get("interrupted") for stop in stops] == [True, True]


def test_receive_without_the_item_asked_for_is_not_taken(tmp_path, setup):
    _, exe = setup
    case = {**RECEIVE, "choices": {"function": "05 - Write Single Coil"}}
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert code == cr.EXIT_OK, result["reason"]
    (entry,) = result["cases"]
    assert entry["outcome"] == "not_taken" and fake.entered == []
    assert entry["message"].startswith("function: the list has no item '05 - Write Single Coil'")


def test_a_list_that_does_not_follow_the_keys_stops_the_run(tmp_path, setup):
    _, exe = setup
    case = {**RECEIVE, "choices": {"function": "02 - Read Input Status"}}
    fake = FakeClick(tmp_path, lists_follow_keys=False)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]}, timeout=0.5)
    assert_aborted(fake, tmp_path / "out", code, result, "to show '02 - Read Input Status'")
    assert fake.entered == []


@pytest.mark.parametrize(
    ("lists", "reason"),
    [
        (
            {5000: (["CPU Port1", "CPU Port2"], 0)},
            "list 5000 shows 'CPU Port1' as the dialog opens",
        ),
        ({5001: (["01 - Read Coil Status"], -1)}, "list 5001 shows None as the dialog opens"),
    ],
)
def test_receive_that_opens_otherwise_stops_the_run(tmp_path, setup, monkeypatch, lists, reason):
    _, exe = setup
    for list_id, shown in lists.items():
        monkeypatch.setitem(RECEIVE_LISTS, list_id, shown)
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [RECEIVE]})
    assert_aborted(fake, tmp_path / "out", code, result, reason)
    assert fake.entered == []


# ---------------------------------------------------------------------------
# import: a nickname CSV through CLICK's own import
# ---------------------------------------------------------------------------

HEADER = b"Address,Data Type,Nickname,Initial Value,Retentive,Address Comment\r\n"
# DS20's comment holds a quoted line break, which CLICK reads as the end of its line
IMPORT_ROWS = [
    b'DS20,INT,"Line Break",0,No,"first\r\n',
    b'second"\r\n',
    b'" DS32",INT,"Addr Quoted Lead",0,No,""\r\n',
    b'TXT20,TEXT,"Bare Tab",\t,No,""\r\n',
]
# The file's lines: the header is 1, DS20 is 2 and 3, 4 is empty, DS32 is 5 and TXT20 is 6
IMPORT_CSV = HEADER + IMPORT_ROWS[0] + IMPORT_ROWS[1] + b"\r\n" + IMPORT_ROWS[2] + IMPORT_ROWS[3]
IMPORT_LINES = ["line002", "line003", "line005", "line006"]
# The text of an Import Error List that CLICK showed for a real import
LIVE_ERROR_LIST = (
    "Unable to import Intial Value.\r\nLine 14 : Address = DS25, Initial Value =  5 \r\n"
    "Cause : The file format is not correct.\r\n\r\n"
    "Unable to import Intial Value.\r\nLine 15 : Address = DS26, Initial Value = \t5\r\n"
    "Cause : The file format is not correct.\r\n\r\n"
    "Error : Unable to import to Database.\r\n"
    'Line 19 : " DS32",INT,"Addr Quoted Lead",0,No,""\r\n'
    "Cause : The memory address is not supported by this CLICK CPU module.\r\n\r\n"
)


class Rows:
    """A stand-in for read_rows on the fake's SC_.mdb, which holds JSON.

    It records the files read.
    """

    def __init__(self, *, fails: bool = False) -> None:
        self.read: list[Path] = []
        self.fails = fails

    def __call__(self, mdb: Path) -> dict[str, dict]:
        self.read.append(mdb)
        if self.fails:
            raise RuntimeError("no Access ODBC driver")
        return json.loads(mdb.read_text(encoding="utf-8"))


def run_import(
    fake: FakeClick,
    tmp_path: Path,
    exe: Path,
    *args: str,
    data: bytes | None = IMPORT_CSV,
    timeout: float = 5,
    rows: Rows | None = None,
) -> tuple[int, dict]:
    """Run ``import`` on *fake* with *data* as the CSV, and return the exit code and result.

    If *data* is None, no CSV is written."""
    csv = tmp_path / "nicknames.csv"
    if data is not None:
        csv.write_bytes(data)
    out = tmp_path / "out"
    argv = ["import", str(csv), "--out", str(out), "--click-exe", str(exe)]
    argv += ["--timeout", str(timeout), "--paste-timeout", str(timeout), *args]
    code = cr.main(
        argv, desktop=fake, prepare=Prepare(), read_rows=rows or Rows(), stderr=io.StringIO()
    )
    result_file = out / "result.json"
    return code, json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}


def test_import_each_row(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    rows = Rows()
    out = tmp_path / "out"

    code, result = run_import(fake, tmp_path, exe, "--each-row", rows=rows)

    assert code == cr.EXIT_OK, result["reason"]
    assert result["import_mode"] == "Delete Existing" and result["each_row"] is True
    imports = result["imports"]
    assert [(i["name"], i["line"], i["answer"]) for i in imports] == [
        ("whole", None, "errors"),
        ("line002", 2, "completed"),
        ("line003", 3, "errors"),
        ("line005", 5, "errors"),
        ("line006", 6, "completed"),
    ]
    # Each row's file is the header and the line, byte for byte; a quoted line break ends it
    for name, row in zip(IMPORT_LINES, IMPORT_ROWS, strict=True):
        assert (out / "rows" / f"{name}.csv").read_bytes() == HEADER + row
    assert imports[1]["row"] == IMPORT_ROWS[0].decode("latin-1")
    assert fake.imported == [("Delete Existing", "nicknames.csv")] + [
        ("Delete Existing", f"{name}.csv") for name in IMPORT_LINES
    ]
    # Each import records CLICK's answer: the error list's text and entries, or the box's text
    whole = imports[0]
    assert [(e["line"], e["cause"]) for e in whole["errors"]] == [
        (3, "The file format is not correct."),
        (5, "The memory address is not supported by this CLICK CPU module."),
    ]
    assert whole["errors"][0]["text"] == 'second"'
    assert "Line 5 : " in whole["message"]
    assert imports[2]["errors"][0]["text"] == 'second"'
    assert len(imports[3]["errors"]) == 2 and imports[4]["message"] == "Completed!"
    # What each import stored, read from its own copy of SC_.mdb once CLICK had ended
    assert set(whole["stored"]) == {"DS20", "TXT20"}
    assert whole["stored"]["DS20"]["Comment"] == "first"
    assert imports[1]["stored"] == {"DS20": whole["stored"]["DS20"]}
    assert imports[2]["stored"] == imports[3]["stored"] == {}
    assert imports[4]["stored"] == {"TXT20": whole["stored"]["TXT20"]}
    assert whole["stored"]["TXT20"]["InitialValue"] == "\t"
    copies = [out / "mdb" / f"{n:02d}-{i['name']}.mdb" for n, i in enumerate(imports, 1)]
    assert rows.read == copies and [Path(i["mdb"]) for i in imports] == copies
    assert whole["mdb_changed_at_answer"] is True and whole["mdb_changed"] is True
    assert whole["mdb_changed_after_answer"] is False
    assert all(i["seconds"] is not None for i in imports)
    # The runner picks the mode and types the path. It sends no command but Import Nickname
    # before Disconnect.
    assert fake.pressed.count("Delete Existing") == 5
    assert fake.typed[1148] == str(out / "rows" / "line006.csv")
    assert fake.commands == ["Import Nickname"] * 5 + ["Disconnect"]
    # The project was never saved, so the runner ends CLICK instead of closing it. It disconnects first.
    assert not fake.connected and fake.terminated and not fake.saved
    assert list(result["timings"])[-4:] == ["import", "disconnect", "close", "read"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "line006: 1 row(s) stored" in log and "InitialValue='\\t'" in log
    assert (
        "SC_.mdb changed. It had already changed when the answer showed. The runner copied it."
        in log
    )


def test_import_once_without_each_row(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_import(fake, tmp_path, exe, "--record")
    assert code == cr.EXIT_OK, result["reason"]
    assert [i["name"] for i in result["imports"]] == ["whole"]
    assert result["each_row"] is False and not (tmp_path / "out" / "rows").exists()
    labels = {p.name.split("-")[1] for p in (tmp_path / "out" / "record").glob("*.json")}
    assert {"import01_open", "import01_answer", "import01_done"} <= labels


def test_an_import_written_after_its_ok_is_waited_for(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, import_writes="ok")
    code, result = run_import(fake, tmp_path, exe)
    assert code == cr.EXIT_OK, result["reason"]
    (whole,) = result["imports"]
    assert whole["mdb_changed_at_answer"] is False and whole["mdb_changed"] is True
    assert set(whole["stored"]) == {"DS20", "TXT20"}


def test_an_import_written_after_the_main_window_is_alone_is_waited_for(tmp_path, setup):
    # The runner keeps waiting after SC_.mdb reads the same on two polls, because CLICK may
    # write it later
    _, exe = setup
    fake = FakeClick(tmp_path, import_writes="late")
    code, result = run_import(fake, tmp_path, exe, "--each-row")
    assert code == cr.EXIT_OK, result["reason"]
    whole, *rows = result["imports"]
    assert set(whole["stored"]) == {"DS20", "TXT20"}
    assert [set(row["stored"]) for row in rows] == [{"DS20"}, set(), set(), {"TXT20"}]
    assert whole["mdb_changed_at_answer"] is False and whole["mdb_changed"] is True
    assert whole["mdb_changed_after_answer"] is True
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert (
        "SC_.mdb changed. It had not yet changed when the answer showed, and it changed after the answer. The runner copied it."
        in log
    )


def test_a_mode_that_does_not_take_stops_the_import(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, mode_takes=False)
    out = tmp_path / "out"
    code, result = run_import(fake, tmp_path, exe, timeout=1)
    assert_aborted(fake, out, code, result, "'Delete Existing' to be checked")
    assert result["step"] == "import" and fake.imported == []


def test_an_import_in_another_mode_aborts(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, import_as="Project priority")
    out = tmp_path / "out"
    code, result = run_import(fake, tmp_path, exe)
    assert_aborted(fake, out, code, result, "unexpected window")
    assert "'Import - Project priority'" in result["reason"] and result["step"] == "import"
    # The runner leaves CLICK's answer open and presses nothing after Open
    assert fake.pressed[fake.pressed.index("Delete Existing") :] == ["Delete Existing", "&Open"]


@pytest.mark.parametrize("event", ["import_open", "import", "import_closed"])
def test_an_unexpected_dialog_during_an_import_aborts(tmp_path, setup, event):
    _, exe = setup
    fake = FakeClick(tmp_path, surprise=event)
    out = tmp_path / "out"
    code, result = run_import(fake, tmp_path, exe)
    assert_aborted(fake, out, code, result, "unexpected window")
    assert "'Set a Project Password'" in result["reason"] and result["step"] == "import"


@pytest.mark.parametrize(
    ("box", "reason"),
    [
        ("question", "CLICK asked something the runner does not answer"),
        ("twice", "import01: CLICK answered again"),
    ],
)
def test_an_import_answer_the_runner_does_not_know_aborts(tmp_path, setup, box, reason):
    _, exe = setup
    fake = FakeClick(tmp_path, import_box=box)
    out = tmp_path / "out"
    code, result = run_import(fake, tmp_path, exe)
    assert_aborted(fake, out, code, result, reason)
    assert "&Yes" not in fake.pressed and "&No" not in fake.pressed


def test_an_abort_keeps_the_imports_done_and_their_rows(tmp_path, setup):
    _, exe = setup
    calls: list[bytes] = []

    def answer(data: bytes) -> tuple[dict[str, dict], str | None]:
        calls.append(data)
        if len(calls) == 2:
            fake.import_box = "question"
        return import_like_click(data)

    fake = FakeClick(tmp_path, import_answer=answer)
    out = tmp_path / "out"
    code, result = run_import(fake, tmp_path, exe, "--each-row")
    assert_aborted(fake, out, code, result, "does not answer")
    assert result["step"] == "import"
    done, stopped = result["imports"]
    assert set(done["stored"]) == {"DS20", "TXT20"}
    assert (stopped["name"], stopped["mdb"], stopped["stored"]) == ("line002", None, None)


def test_reading_the_copies_failing_stops_the_run(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_import(fake, tmp_path, exe, rows=Rows(fails=True))
    assert code == cr.EXIT_ABORTED
    assert result["reason"] == (
        "reading the copies of SC_.mdb failed: RuntimeError: no Access ODBC driver"
    )
    assert result["step"] == "read" and fake.terminated and result["click"]["closed"] is True
    assert (tmp_path / "out" / "mdb" / "01-whole.mdb").is_file()


@pytest.mark.parametrize(
    ("data", "args", "reason"),
    [
        (None, (), "no CSV at"),
        (HEADER, ("--each-row",), "has no rows after its header to import one by one"),
    ],
)
def test_import_refuses(tmp_path, setup, data, args, reason):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_import(fake, tmp_path, exe, *args, data=data)
    assert code == cr.EXIT_REFUSED and reason in result["reason"]
    assert fake.pid is None


def test_a_header_alone_is_imported_once(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_import(fake, tmp_path, exe, data=HEADER)
    assert code == cr.EXIT_OK, result["reason"]
    (whole,) = result["imports"]
    assert (whole["answer"], whole["stored"]) == ("completed", {})


def test_split_rows_keeps_each_record_as_in_the_file():
    header, rows = cr.split_rows(IMPORT_CSV)
    assert header == HEADER
    assert rows == list(zip([2, 3, 5, 6], IMPORT_ROWS, strict=True))
    # Rows may end in LF, and the last row may have no line ending
    assert cr.split_rows(b"A,B\nDS1,x\nDS2,y") == (b"A,B\n", [(2, b"DS1,x\n"), (3, b"DS2,y")])
    # A quote that does not close ends at the end of its line. A CR alone ends no line.
    assert cr.split_rows(b'A\nDS1,"x\nDS2,y\n') == (b"A\n", [(2, b'DS1,"x\n'), (3, b"DS2,y\n")])
    assert cr.split_rows(b"A,B\rDS1,x\r") == (b"A,B\rDS1,x\r", [])
    assert cr.split_rows(b"") == (b"", [])
    assert cr.split_rows(b"A,B") == (b"A,B", [])


def test_parse_import_errors_reads_the_live_error_list():
    entries = cr.parse_import_errors(LIVE_ERROR_LIST)
    assert entries == [
        {
            "error": "Unable to import Intial Value.",
            "line": 14,
            "text": "Address = DS25, Initial Value =  5 ",
            "cause": "The file format is not correct.",
        },
        {
            "error": "Unable to import Intial Value.",
            "line": 15,
            "text": "Address = DS26, Initial Value = \t5",
            "cause": "The file format is not correct.",
        },
        {
            "error": "Error : Unable to import to Database.",
            "line": 19,
            "text": '" DS32",INT,"Addr Quoted Lead",0,No,""',
            "cause": "The memory address is not supported by this CLICK CPU module.",
        },
    ]
    # A vertical tab or form feed is text, and a line in no known form is kept
    (entry,) = cr.parse_import_errors("Odd.\r\nLine 3 : a\x0bb\x0c\r\nmore\r\n\r\n")
    assert entry["text"] == "a\x0bb\x0c" and entry["other"] == ["more"]
    # An empty line is no part of an entry
    (entry,) = cr.parse_import_errors("\r\nOdd.\r\nLine 2 : x\r\n\r\n\r\n")
    assert (entry["error"], entry["line"], entry["text"]) == ("Odd.", 2, "x")


def test_rows_by_address_keeps_each_row_as_stored():
    columns = (1, "Nick", "0", False, None, False)
    rows = cr._rows_by_address([(100663326, "DS ", "30", *columns), (1, "X", 1, *columns)])
    assert list(rows) == ["DS30", "X001"]
    assert rows["DS30"] == {
        "AddrKey": 100663326,
        "MemoryType": "DS ",
        "Address": "30",
        **dict(zip(cr._ROW_COLUMNS, columns, strict=True)),
    }
    with pytest.raises(RuntimeError, match="two rows for DS30: AddrKey 7 and 8"):
        cr._rows_by_address([(7, "DS", 30, *columns), (8, "DS", "30", *columns)])


# ---------------------------------------------------------------------------
# reopen: Project.ini over save and open
# ---------------------------------------------------------------------------


def run_reopen(fake: FakeClick, tmp_path: Path, exe: Path, *args: str) -> tuple[int, dict]:
    out = tmp_path / "out"
    argv = ["reopen", "--out", str(out), "--click-exe", str(exe)]
    argv += ["--timeout", "5", "--paste-timeout", "5", *args]
    code = cr.main(argv, desktop=fake, prepare=Prepare(), stderr=io.StringIO())
    result_file = out / "result.json"
    return code, json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}


def test_reopen_copies_each_point(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    # Another CLICK's temp folder, which the runner reads and writes nothing in
    other = fake.temp_root / "CLICK (00ABCDEF)"
    other.mkdir()
    theirs = {"Project.ini": b"[Project]\r\nmine\r\n", "Scr1.tmp": b"mine", "SC_.mdb": b"mine"}
    for name, data in theirs.items():
        (other / name).write_bytes(data)
    code, result = run_reopen(fake, tmp_path, exe, "--ini-add", r"[sec20]\nkey1=Probe")
    assert code == cr.EXIT_OK, result["reason"]
    assert {p.name: p.read_bytes() for p in other.iterdir()} == theirs
    out = tmp_path / "out"
    copied = [p for p in out.rglob("*") if p.is_file()]
    assert copied and all(b"mine" not in p.read_bytes() for p in copied)
    looks = "System Configuration"
    assert fake.commands == [
        "Disconnect",
        *("Save Project As", looks) * 2,
        *("Open Project", looks),
        *("Save Project As", looks),
    ]
    assert fake.opened == [(out / "second.ckp").resolve()]
    points = result["points"]
    assert list(points) == ["first", "second", "opened", "third"]
    # Real CLICK showed the name from the second point on. The letter case of the section and
    # the key does not matter.
    assert [points[p]["plc_name"] for p in points] == ["", "Probe", "Probe", "Probe"]
    assert fake.pressed.count("Cancel") == 4
    assert points["first"]["project_ini"] == "[Project]\r\n"
    added = "[sec20]\r\nkey1=Probe\r\n"
    assert result["ini_added"] == added
    for point in ("second", "opened", "third"):
        assert points[point]["project_ini"] == "[Project]\r\n" + added
        assert (
            out / point / "click" / "Project.ini"
        ).read_bytes() == b"[Project]\r\n" + added.encode()
    assert points["opened"]["title"].endswith("- second.ckp - [Main Program]")
    assert points["third"]["title"].endswith("- third.ckp - [Main Program]")
    assert points["third"]["status_bar"][8] == "Offline"
    assert not fake.connected and fake.terminated
    assert list(result["timings"])[-6:] == [
        "first_save",
        "ini",
        "second_save",
        "open",
        "third_save",
        "close",
    ]


def test_reopen_waits_for_the_open_to_begin(tmp_path, setup):
    # Open closes the dialog before the open begins, and the main window keeps the title
    # second.ckp that Save As gave it. A check of the title and the Scr*.tmp files alone would
    # pass on the old files.
    _, exe = setup
    fake = FakeClick(tmp_path, open_gap=8)
    code, result = run_reopen(fake, tmp_path, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.opened == [(tmp_path / "out" / "second.ckp").resolve()]
    assert fake.commands[-2:] == ["Save Project As", "System Configuration"]
    assert result["points"]["third"]["title"].endswith("- third.ckp - [Main Program]")


@pytest.mark.parametrize(
    ("lines", "name"),
    [
        # The PLC Name that CLICK's System Configuration showed for each Project.ini
        ("[Sec20]\nKey1=UpperCase", "UpperCase"),
        ("[sec20]\nkey1=LowerCase", "LowerCase"),
        ("[SEC20]\nKEY1=AllCaps", "AllCaps"),
        ("[Sec20]\nkey1=MixedKey", "MixedKey"),
        ("[sec20]\nKey1=MixedSection", "MixedSection"),
        ("[Sec20]\nKey1=Upper\n[sec20]\nkey1=Lower", "Upper"),
        ("[sec20]\nkey1=Lower\n[Sec20]\nKey1=Upper", "Lower"),
        ("[Sec20]\nKey1=FirstKey\nKEY1=SecondKey", "FirstKey"),
        ("[PLCName]\nPLCName=Legacy", ""),
        ("[PLCName]\nPLCName=Legacy\n[Sec20]\nKey1=Placeholder", "Placeholder"),
    ],
)
def test_reopen_reads_the_plc_name_system_configuration_shows(tmp_path, setup, lines, name):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_reopen(fake, tmp_path, exe, "--ini-add", lines)
    assert code == cr.EXIT_OK, result["reason"]
    assert result["points"]["opened"]["plc_name"] == name
    assert result["points"]["third"]["plc_name"] == name


def test_reopen_closes_system_configurations_notice_without_ok(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, system_config_notice=True)
    code, result = run_reopen(fake, tmp_path, exe, "--ini-add", r"[Sec20]\nKey1=Probe")
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.events.count("notice_close") == 1
    assert "OK" not in fake.pressed[fake.pressed.index("&Yes") + 1 :]
    assert result["points"]["third"]["plc_name"] == "Probe"


def test_reopen_refuses_lines_that_are_not_ascii(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_reopen(fake, tmp_path, exe, "--ini-add", "[Sec20]\\nKey1=caf\xe9")
    assert code == cr.EXIT_REFUSED and "--ini-add is not ASCII" in result["reason"]
    assert fake.pid is None


# ---------------------------------------------------------------------------
# read-data: the PLC's data values into a file
# ---------------------------------------------------------------------------


def run_command(
    fake: FakeClick, tmp_path: Path, exe: Path, command: str, *args: str, **run_args: Any
) -> tuple[int, dict]:
    out = tmp_path / "out"
    argv = [command, "--out", str(out), "--click-exe", str(exe)]
    argv += ["--timeout", "5", "--paste-timeout", "5", *args]
    code = cr.main(argv, desktop=fake, prepare=Prepare(), stderr=io.StringIO(), **run_args)
    result_file = out / "result.json"
    return code, json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}


def test_read_data_saves_every_memory_type(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "read-data")
    assert code == cr.EXIT_OK, result["reason"]
    dump = (tmp_path / "out" / "plcdata.csv").resolve()
    assert result["files"]["plc_data"] == str(dump)
    # The runner pressed All before Read. All checks every memory type, not only the four that
    # are checked when the form opens.
    banks = ("X", "Y", "C", "T", "CT", "DS", "DD", "DH", "DF", "TD", "CTD", "TXT")
    assert dump.read_bytes().decode("ascii") == "".join(
        f"<{b}=START>\r\n</{b}=END>\r\n" for b in banks
    )
    assert result["reading_seen"] is True
    assert fake.commands == ["Read Data from PLC", "Disconnect"]
    at = fake.pressed.index("All")
    assert fake.pressed[at : at + 4] == ["All", "Read", "&Save", "Close"]
    assert not fake.connected and fake.terminated


def test_read_data_sets_the_path_again_when_the_save_dialog_empties_it(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, save_clears=True)
    code, result = run_command(fake, tmp_path, exe, "read-data")
    assert code == cr.EXIT_OK, result["reason"]
    assert (tmp_path / "out" / "plcdata.csv").is_file()
    assert not fake.last_folder.exists()
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert "the File name edit reads ''; setting the path again" in log
    assert not (tmp_path / "out" / "record").exists()


def test_read_data_that_writes_no_file_aborts_once_the_reading_ends(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, writes_data=False)
    code, result = run_command(fake, tmp_path, exe, "read-data")
    assert code == cr.EXIT_ABORTED
    assert result["reason"] == "CLICK read the PLC's data but wrote no plcdata.csv"
    assert result["step"] == "read_data"
    assert fake.terminated


# ---------------------------------------------------------------------------
# export-nicknames: CLICK's nickname export, byte for byte
# ---------------------------------------------------------------------------

# A nickname export with `€` in a nickname and `café` in a comment, in UTF-8 with a BOM and in
# CP1252. Which of them CLICK writes is what a live run is to find out
EXPORT_ROW = 'DS1,INT,"Price€",0,No,"café"\r\n'
UTF8_BOM_EXPORT = codecs.BOM_UTF8 + HEADER + EXPORT_ROW.encode("utf-8")
CP1252_EXPORT = HEADER + EXPORT_ROW.encode("cp1252")


@pytest.mark.parametrize("data", [UTF8_BOM_EXPORT, CP1252_EXPORT], ids=["utf8_bom", "cp1252"])
def test_export_nicknames_copies_the_file_that_click_writes(tmp_path, setup, data):
    _, exe = setup
    fake = FakeClick(tmp_path, export_bytes=data)
    out = tmp_path / "out"

    code, result = run_command(fake, tmp_path, exe, "export-nicknames")

    assert code == cr.EXIT_OK, result["reason"]
    written = (out / "click" / "nicknames.csv").resolve()
    assert fake.exported == [written] and written.read_bytes() == data
    assert (out / "export.csv").read_bytes() == data
    assert result["files"]["export"] == str(out / "export.csv")
    export = result["export"]
    assert export == {
        "written": str(written),
        "create_prompt": None,
        "answer": "Completed!",
        "copy": str(out / "export.csv"),
        **json.loads(json.dumps(cr.export_facts(data))),
    }
    assert "imports" not in result
    # The runner typed the path into the export's Save As, pressed Save and the box's OK. It
    # sent no command but Export Nickname before Disconnect
    assert fake.typed[1148] == str(written)
    assert fake.pressed[-3:] == ["&Save", "OK", "&Yes"]
    assert fake.commands == ["Export Nickname", "Disconnect"]
    # The project was never saved, so the runner ends CLICK instead of closing it
    assert not fake.connected and fake.terminated and not fake.saved
    assert list(result["timings"])[-3:] == ["export", "disconnect", "close"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert f"exported {len(data)} bytes into {written}" in log


def test_an_export_without_a_box_ends_once_the_file_stays_the_same(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, export_bytes=CP1252_EXPORT, export_box=None)
    out = tmp_path / "out"
    code, result = run_command(fake, tmp_path, exe, "export-nicknames")
    assert code == cr.EXIT_OK, result["reason"]
    assert result["export"]["answer"] is None
    assert (out / "export.csv").read_bytes() == CP1252_EXPORT
    assert "OK" not in fake.pressed[fake.pressed.index("&Save") :]


def test_export_nicknames_imports_first(tmp_path, setup):
    _, exe = setup
    csv = tmp_path / "nicknames.csv"
    csv.write_bytes(IMPORT_CSV)
    fake = FakeClick(tmp_path, shadow=True)
    rows = Rows()
    out = tmp_path / "out"

    code, result = run_command(
        fake, tmp_path, exe, "export-nicknames", "--import", str(csv), "--record", read_rows=rows
    )

    assert code == cr.EXIT_OK, result["reason"]
    assert fake.imported == [("Delete Existing", "nicknames.csv")]
    assert fake.commands == ["Import Nickname", "Export Nickname", "Disconnect"]
    assert result["import_mode"] == "Delete Existing"
    (whole,) = result["imports"]
    assert whole["name"] == "whole" and whole["answer"] == "errors"
    assert set(whole["stored"]) == {"DS20", "TXT20"}
    assert rows.read == [out / "mdb" / "01-whole.mdb"]
    # The fake's export lists what the import stored
    lines = result["export"]["first_lines"]
    assert lines[0] == HEADER.decode("ascii").rstrip("\r\n")
    assert [line.split(",")[0] for line in lines[1:]] == ["DS20", "TXT20"]
    assert list(result["timings"])[-5:] == ["import", "export", "disconnect", "close", "read"]
    labels = {p.name.split("-")[1] for p in (out / "record").glob("*.json")}
    assert {"export_save", "export_answer", "exported"} <= labels
    # The drop shadow under the export's Save As did not stop the run
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "ignoring a drop shadow: 'SysShadow' ''" in log


@pytest.mark.parametrize(
    ("switches", "reason"),
    [
        (
            {"export_box": "question"},
            "the export: CLICK asked something the runner does not answer",
        ),
        (
            {"export_box": "other"},
            "the export: CLICK asked something the runner does not answer: "
            "['No data to export.'], buttons ['OK']",
        ),
        ({"surprise": "export"}, "unexpected window while waiting for CLICK to write"),
        (
            {"create_prompt": "text"},
            "the export's Save As: Windows asked something the runner does not answer: "
            "['Create the file?'], buttons ['&Yes', '&No']",
        ),
        (
            {"create_prompt": "buttons"},
            "the export's Save As: Windows asked something the runner does not answer",
        ),
        # A question about a file that exists asks whether to replace it, not to create it
        ({"create_prompt": "exists"}, "the export's Save As asks about "),
    ],
    ids=[
        "question",
        "other_text",
        "another_window",
        "prompt_text",
        "prompt_buttons",
        "prompt_file_exists",
    ],
)
def test_an_unknown_box_during_the_export_stops_the_run(tmp_path, setup, switches, reason):
    _, exe = setup
    fake = FakeClick(tmp_path, **switches)
    out = tmp_path / "out"
    code, result = run_command(fake, tmp_path, exe, "export-nicknames")
    assert_aborted(fake, out, code, result, reason)
    written = (out / "click" / "nicknames.csv").resolve()
    assert result["step"] == "export"
    assert result["export"] == {"written": str(written), "create_prompt": None, "answer": None}
    assert not (out / "export.csv").exists()
    # The runner pressed nothing after Save
    assert fake.pressed[fake.pressed.index("&Save") :] == ["&Save"]


def test_export_nicknames_answers_windows_question_to_create_the_file(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, export_bytes=CP1252_EXPORT, create_prompt="windows")
    out = tmp_path / "out"
    code, result = run_command(fake, tmp_path, exe, "export-nicknames")
    assert code == cr.EXIT_OK, result["reason"]
    assert result["export"]["create_prompt"] == {
        "title": "Save As",
        "texts": ["nicknames.csv\nThis file does not exist.", "Create the file?"],
    }
    assert result["export"]["answer"] == "Completed!"
    assert (out / "export.csv").read_bytes() == CP1252_EXPORT
    # The last &Yes answers the question whether to disconnect
    assert fake.pressed[fake.pressed.index("&Save") :] == ["&Save", "&Yes", "OK", "&Yes"]


def test_an_export_whose_box_stays_disabled_names_the_main_window(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, export_bytes=CP1252_EXPORT, export_box="disabled")
    out = tmp_path / "out"
    code, result = run_command(fake, tmp_path, exe, "export-nicknames")
    written = (out / "click" / "nicknames.csv").resolve()
    assert_aborted(
        fake,
        out,
        code,
        result,
        f"CLICK wrote {written}, but its main window was not alone, enabled and answering. "
        "The runner timed out",
    )
    assert written.read_bytes() == CP1252_EXPORT
    assert not (out / "export.csv").exists()
    assert fake.pressed[fake.pressed.index("&Save") :] == ["&Save"]


def test_an_export_that_writes_no_file_stops_on_a_timeout(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, export_writes=False)
    out = tmp_path / "out"
    code, result = run_command(fake, tmp_path, exe, "export-nicknames")
    written = (out / "click" / "nicknames.csv").resolve()
    assert_aborted(fake, out, code, result, f"CLICK wrote no {written}. The runner timed out")
    assert result["step"] == "export" and "copy" not in result["export"]
    assert fake.exported == [written] and not written.exists()
    assert not (out / "export.csv").exists()


def test_export_nicknames_refuses_an_import_csv_that_is_not_there(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    missing = tmp_path / "missing.csv"
    code, result = run_command(fake, tmp_path, exe, "export-nicknames", "--import", str(missing))
    assert code == cr.EXIT_REFUSED
    assert result["reason"] == f"no CSV at {missing} to import before the export"
    assert fake.pid is None


def test_export_facts_of_utf8_with_a_bom():
    facts = cr.export_facts(UTF8_BOM_EXPORT)
    assert facts["size"] == len(UTF8_BOM_EXPORT)
    assert (facts["bom"], facts["utf8"], facts["cp1252"]) == ("utf-8", True, True)
    assert facts["line_endings"] == {"crlf": 2, "lf": 0, "cr": 0}
    assert facts["line_ending"] == "crlf"
    # Latin-1 keeps each byte, the BOM's too
    assert facts["first_lines"] == [
        "\xef\xbb\xbf" + HEADER.decode("ascii").rstrip("\r\n"),
        'DS1,INT,"Price\xe2\x82\xac",0,No,"caf\xc3\xa9"',
    ]
    assert facts["non_ascii"] == [
        {"line": 1, "column": 1, "bytes": "ef bb bf", "utf8": "﻿", "cp1252": "ï»¿"},
        {"line": 2, "column": 15, "bytes": "e2 82 ac", "utf8": "€", "cp1252": "â‚¬"},
        {"line": 2, "column": 29, "bytes": "c3 a9", "utf8": "é", "cp1252": "Ã©"},
    ]


def test_export_facts_of_cp1252():
    facts = cr.export_facts(CP1252_EXPORT)
    assert (facts["bom"], facts["utf8"], facts["cp1252"]) == (None, False, True)
    assert facts["line_ending"] == "crlf"
    assert facts["first_lines"][1] == 'DS1,INT,"Price\x80",0,No,"caf\xe9"'
    # Not UTF-8, so each byte from 0x80 up is one character
    assert facts["non_ascii"] == [
        {"line": 2, "column": 15, "bytes": "80", "utf8": None, "cp1252": "€"},
        {"line": 2, "column": 27, "bytes": "e9", "utf8": None, "cp1252": "é"},
    ]


def test_export_facts_count_each_kind_of_line_end():
    facts = cr.export_facts(b"a\r\nb\nc\rd")
    assert facts["line_endings"] == {"crlf": 1, "lf": 1, "cr": 1}
    assert facts["line_ending"] == "mixed"
    assert facts["first_lines"] == ["a", "b", "c", "d"]
    assert cr.export_facts(b"x\ny\n")["line_ending"] == "lf"
    assert cr.export_facts(b"x\ny\n")["first_lines"] == ["x", "y"]
    empty = cr.export_facts(b"")
    assert (empty["size"], empty["line_ending"], empty["first_lines"]) == (0, None, [])
    assert cr.export_facts(b"1\n2\n3\n4\n5\n6\n")["first_lines"] == ["1", "2", "3", "4", "5"]
    # Only CR and LF end a line. CP1252's 0x85 is "…", and Latin-1 reads it as NEL
    nel = cr.export_facts(b"a\x85b\r\n")
    assert nel["first_lines"] == ["a\x85b"]
    assert nel["non_ascii"] == [
        {"line": 1, "column": 2, "bytes": "85", "utf8": None, "cp1252": "…"}
    ]
    # CP1252 has no character at 0x81
    assert cr.export_facts(b"\x81")["cp1252"] is False


@pytest.mark.parametrize(
    ("argv", "csv"),
    [
        (["export-nicknames", "--out", "o"], None),
        (["export-nicknames", "--out", "o", "--import", "n.csv"], "n.csv"),
    ],
)
def test_export_nicknames_settings(argv, csv):
    settings = cr.settings_from(argv, environ={})
    assert settings.command == "export-nicknames"
    assert settings.csv == (None if csv is None else Path(csv).resolve())
    assert settings.add_end is False


def test_paste_add_end_settings():
    assert cr.settings_from(["paste", "r.csv", "--out", "o", "--add-end"], environ={}).add_end
    assert not cr.settings_from(["paste", "r.csv", "--out", "o"], environ={}).add_end


# ---------------------------------------------------------------------------
# picker: CLICK's Address Picker and what it writes into SC_.mdb
# ---------------------------------------------------------------------------


class PickerRows(Rows):
    """Rows that read a new project's SC_.mdb (``b"mdb"`` in the fake) as no rows."""

    def __call__(self, mdb: Path) -> dict[str, dict]:
        if mdb.read_bytes() == b"mdb":
            self.read.append(mdb)
            return {}
        return super().__call__(mdb)


def name_keys(address: str, name: str) -> list[str]:
    return [f"--key=find:{address}", "--key=RIGHT", "--key=RIGHT", "--key=F2"] + [
        f"--key=chars:{name}",
        "--key=RETURN",
    ]


def test_picker_ok_writes_the_names_taken_and_the_system_rows(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    rows = PickerRows()
    keys = [*name_keys("X001", "Test"), *name_keys("DS1", "Max")]
    code, result = run_command(fake, tmp_path, exe, "picker", *keys, "--ok", read_rows=rows)
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out" / "mdb"
    assert rows.read == [out / "before.mdb", out / "after.mdb"]
    copies = result["mdb_copies"]
    assert copies["before"]["rows"] == {}
    assert result["close"] == "ok"
    # The editor refused the reserved word Max, so OK wrote only Test
    assert copies["after"]["rows"] == {**SYSTEM_ROWS, "X001": {"Nickname": "Test"}}
    assert fake.commands == ["Address Picker", "Disconnect"]
    typed = [k for k in result["keys"] if k["key"].startswith("chars:")]
    assert [(k["editor"], k["editor_shown"]) for k in typed] == [("Test", True), ("Max", True)]
    enters = [k for k in result["keys"] if k["key"] == "RETURN"]
    assert [k["editor_shown"] for k in enters] == [False, False]
    # Each key went to the grid, or to the editor once it showed
    assert [cls for cls, _ in fake.keys] == ["TStringGrid"] * 3 + ["TEdit"] * 2 + [
        "TStringGrid"
    ] * 3 + ["TEdit"] * 2
    timings = list(result["timings"])
    assert timings[-6:] == ["before", "picker", "after", "disconnect", "close", "read"]


def test_picker_closed_with_nothing_typed_writes_nothing(tmp_path, setup):
    # The runner closes the Picker by WM_CLOSE, and nothing was typed in it
    _, exe = setup
    fake = FakeClick(tmp_path)
    rows = PickerRows()
    code, result = run_command(
        fake, tmp_path, exe, "picker", "--key", "find:X001", "--key", "F2", read_rows=rows
    )
    assert code == cr.EXIT_OK, result["reason"]
    copies = result["mdb_copies"]
    assert copies["before"]["rows"] == copies["after"]["rows"] == {}
    assert "picker_close" in fake.events
    assert result["close"] == "wm_close"


def test_picker_cancel_presses_cancel_and_the_fake_writes_nothing(tmp_path, setup):
    # The fake's Cancel closes the picker without writing SC_.mdb. CLICK 4.00 was observed to
    # do the same: it asked nothing, and SC_.mdb stayed byte for byte the same.
    _, exe = setup
    fake = FakeClick(tmp_path)
    rows = PickerRows()
    keys = name_keys("DS2", "Test")
    code, result = run_command(fake, tmp_path, exe, "picker", *keys, "--cancel", read_rows=rows)
    assert code == cr.EXIT_OK, result["reason"]
    # Cancel closed the picker, and &Yes answered the question about disconnecting
    assert fake.pressed[fake.pressed.index("Find") + 1 :] == ["Cancel", "&Yes"]
    assert "picker_close" not in fake.events
    copies = result["mdb_copies"]
    assert copies["before"]["rows"] == copies["after"]["rows"] == {}
    assert result["close"] == "cancel"
    timings = list(result["timings"])
    assert timings[-6:] == ["before", "picker", "after", "disconnect", "close", "read"]


def test_a_find_while_the_editor_shows_stops_the_run(tmp_path, setup):
    # In CLICK, Find does not move the cursor while the editor shows, so the keys after it
    # would edit the editor's row. The runner stops before it presses Find
    _, exe = setup
    fake = FakeClick(tmp_path)
    rows = PickerRows()
    keys = name_keys("X001", "Test")[:-1] + name_keys("DS1", "Max")
    code, result = run_command(fake, tmp_path, exe, "picker", *keys, "--ok", read_rows=rows)
    assert_aborted(
        fake,
        tmp_path / "out",
        code,
        result,
        "the key 'find:DS1' came while CLICK's editor showed. Find does not move the cursor "
        "while the editor shows, so the keys after it would edit the editor's row. Send RETURN "
        "before the find: key to close the editor.",
    )
    assert result["step"] == "picker"
    # Find was pressed once, for X001, and OK never
    assert fake.pressed[fake.pressed.index("Find") :] == ["Find"]
    assert [k["key"] for k in result["keys"]][-1] == "chars:Test"
    assert result["close"] is None


def test_picker_refuses_ok_with_cancel(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "picker", "--ok", "--cancel")
    assert code == cr.EXIT_REFUSED
    assert result["reason"] == "--ok and --cancel both close the Address Picker. Give one of them."
    assert fake.pid is None


def test_settings_take_picker_cancel():
    assert cr.settings_from(["picker", "--out", "o", "--cancel"], environ={}).cancel
    assert not cr.settings_from(["picker", "--out", "o", "--ok"], environ={}).cancel


def test_a_picker_key_that_opens_a_box_stops_the_run(tmp_path, setup):
    # A sent key that opens a modal box is not answered while the box shows
    _, exe = setup
    fake = FakeClick(tmp_path)
    real = fake.send_key

    def send_key(hwnd: int, vk: int) -> bool:
        if vk != 0x0D:
            return real(hwnd, vk)
        picker = next(w for w in fake.wins.values() if w.cls == "TfrmTagDB")
        box = fake._window("#32770", "CLICK Programming Software", picker.hwnd)
        fake._control(box, "Button", "OK", 2)
        picker.enabled = False
        return False

    fake.send_key = send_key
    code, result = run_command(fake, tmp_path, exe, "picker", *name_keys("X001", "Test"))
    assert_aborted(fake, tmp_path / "out", code, result, "CLICK did not answer the key 'RETURN'")
    assert result["step"] == "picker"
    assert "OK" not in fake.pressed[fake.pressed.index("Find") :]


def test_picker_refuses_a_key_it_does_not_know(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "picker", "--key", "F9")
    assert code == cr.EXIT_REFUSED
    assert result["reason"] == (
        "--key 'F9' is not a key the runner knows. Use one of RETURN, ESCAPE, TAB, END, HOME, "
        "LEFT, UP, RIGHT, DOWN, F2, or chars:TEXT, text:TEXT or find:TEXT."
    )
    assert fake.pid is None


# ---------------------------------------------------------------------------
# new: a project for a CPU, through CLICK's new-project wizard
# ---------------------------------------------------------------------------

HOME, DOWN = cr._VIRTUAL_KEYS["HOME"], cr._VIRTUAL_KEYS["DOWN"]


@pytest.mark.parametrize(
    ("model", "pressed", "slots"),
    [
        ("C0-02DD1-D", ["TButton@747", "OK", "&Save"], {}),
        ("C0-11DD1E-D", ["TButton@747", "OK", "Cancel", "&Save"], {}),
        ("C2-03CPU", ["TButton@747", "OK", "Cancel", "&Save"], {"0": "C2-FILL"}),
        ("C2-03CPU-2", ["TButton@747", "OK", "Cancel", "&Save"], {"0": "C2-FILL", "1": "C2-FILL"}),
    ],
)
def test_new_picks_the_cpu_by_name_and_saves_the_project(tmp_path, setup, model, pressed, slots):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", model)
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out"
    # The runner pressed Start a new project, the leftmost of Startup's three buttons. It never
    # pressed Connect, and it sent no command but Save As
    assert fake.pressed == pressed
    assert fake.commands == ["Save Project As"]
    assert not fake.connected and not fake.went_offline
    # Home, then Down once for each CPU above the model in CLICK's list
    assert fake.keys == [("TListBox", HOME)] + [("TListBox", DOWN)] * cr.CPU_MODELS.index(model)
    assert result["cpu"] == model
    assert result["cpu_list"] == list(cr.CPU_MODELS)
    accounts = "Cancel" in pressed
    assert result["user_accounts"] == ("cancelled" if accounts else None)
    assert result["project"]["cpu"] == model
    assert result["project"]["slots"] == slots
    assert result["project"]["expansions"] == {}
    assert result["project"]["sec21"].startswith("[Sec21]\r\nKey4=0\r\n")
    assert f"Key3_1={CPU_IDS[model]}\r\n" in result["project"]["sec21"]
    assert "[Sec24]" not in result["project"]["sec21"]
    assert result["status_bar"]["new_project"][10] == model
    assert Path(result["files"]["ckp"]) == out / f"{model}.ckp"
    assert sorted(p.name for p in (out / "click").iterdir()) == ["Project.ini", "Scr1.tmp"]
    assert list(result["timings"]) == [
        "refuse",
        "launch",
        "startup",
        "cpu",
        *(["user_accounts"] if accounts else []),
        "new_project",
        "save",
        "copy",
        "check",
        "close",
    ]
    # The project was saved, so CLICK closed cleanly and removed its own temp folder
    assert fake.exited_cleanly and not fake.terminated
    assert_temp_left_to_click(fake, out, still_there=False)


@pytest.mark.parametrize("model", ["C9-99CPU", "c2-03cpu", "C0-00DA-D", "None"])
def test_new_refuses_a_cpu_that_the_wizard_does_not_list_before_click_starts(
    tmp_path, setup, model
):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", model)
    assert code == cr.EXIT_REFUSED
    assert result["status"] == "refused"
    assert result["reason"].startswith(
        f"--cpu {model!r} is not a CPU that CLICK's new-project wizard lists. "
        "Use one of C0-00DD1-D, C0-00DD2-D,"
    )
    assert result["reason"].endswith("C2-03CPU-2, or none for a project with no CPU.")
    assert fake.pid is None


@pytest.mark.parametrize(
    ("model", "event", "step"),
    [
        ("C0-02DD1-D", "cpu", "cpu"),
        ("C0-02DD1-D", "cpu_ok", "cpu"),
        ("C2-03CPU", "cpu_ok", "cpu"),
        ("C2-03CPU", "accounts_cancel", "new_project"),
        ("C0-02DD1-D", "save", "save"),
    ],
)
def test_new_stops_at_an_unexpected_window(tmp_path, setup, model, event, step):
    _, exe = setup
    fake = FakeClick(tmp_path, surprise=event)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", model)
    assert_aborted(fake, tmp_path / "out", code, result, "unexpected window")
    assert "'Set a Project Password'" in result["reason"]
    assert result["step"] == step
    assert "Connect" not in fake.pressed


@pytest.mark.parametrize("shown", [True, False])
def test_new_cancels_user_account_setup_whenever_it_shows(tmp_path, setup, shown):
    # The runner does not decide from the model whether User Account Setup shows
    _, exe = setup
    fake = FakeClick(tmp_path, user_accounts=shown)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C2-03CPU")
    assert code == cr.EXIT_OK, result["reason"]
    assert result["user_accounts"] == ("cancelled" if shown else None)
    assert ("Cancel" in fake.pressed) is shown
    assert result["project"]["slots"] == {"0": "C2-FILL"}


def test_new_record_dumps_each_window_of_the_wizard(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C2-03CPU", "--record")
    assert code == cr.EXIT_OK, result["reason"]
    labels = {p.name.split("-")[1] for p in (tmp_path / "out" / "record").glob("*.json")}
    assert {"cpu_form", "cpu_picked", "user_accounts", "new_project"} <= labels


def test_new_counts_the_keys_from_the_list_that_click_shows(tmp_path, setup):
    # The row comes from the list box, not from CPU_MODELS
    _, exe = setup
    fake = FakeClick(tmp_path, cpu_list=("C2-01CPU", "C2-02CPU", "C2-03CPU"))
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C2-03CPU")
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.keys == [("TListBox", HOME), ("TListBox", DOWN), ("TListBox", DOWN)]
    assert result["cpu_list"] == ["C2-01CPU", "C2-02CPU", "C2-03CPU"]


def test_new_never_presses_user_account_setups_ok(tmp_path, setup):
    # Without a Cancel, the run stops. OK would show the error box GUI-153
    _, exe = setup
    fake = FakeClick(tmp_path, accounts_cancel=False)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C2-03CPU")
    assert_aborted(fake, tmp_path / "out", code, result, "User Account Setup's Cancel not found")
    assert result["step"] == "user_accounts"
    # The only OK pressed is Select a CPU Module's
    assert fake.pressed.count("OK") == 1


@pytest.mark.parametrize(("leftover", "ok"), [("Scr2.tmp", False), ("Scr1.tmp", True)])
def test_new_stops_at_a_stale_scr_file_that_the_save_does_not_rewrite(
    tmp_path, setup, leftover, ok
):
    # A terminated CLICK leaves its temp folder, and a later CLICK with the same hwnd reuses it
    _, exe = setup
    fake = FakeClick(tmp_path, leftover=(leftover,))
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C0-02DD1-D")
    assert result["scr_before_save"] == [leftover]
    if ok:
        assert code == cr.EXIT_OK, result["reason"]
        return
    assert_aborted(
        fake, tmp_path / "out", code, result, "Scr2.tmp in CLICK's temp folder predates the save"
    )
    assert result["step"] == "save"
    assert not (tmp_path / "out" / "click").exists()


def test_new_stops_when_the_list_does_not_show_the_cpu(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, cpu_list=cr.CPU_MODELS[:-1])
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C2-03CPU-2")
    assert_aborted(
        fake, tmp_path / "out", code, result, "the list of CPUs does not show C2-03CPU-2"
    )
    assert result["step"] == "cpu"
    assert fake.keys == [] and "OK" not in fake.pressed


def test_new_stops_when_the_list_does_not_select_the_cpu(tmp_path, setup):
    # Down does not move the selection, so the list stays on its first CPU
    _, exe = setup
    fake = FakeClick(tmp_path, lists_follow_keys=False)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C2-03CPU")
    assert_aborted(fake, tmp_path / "out", code, result, "the list of CPUs to select C2-03CPU")
    assert result["step"] == "cpu"
    assert "OK" not in fake.pressed


def test_new_stops_when_the_saved_project_names_another_cpu(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, saved_cpu="C0-11DD1E-D")
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C0-02DD1-D")
    assert_aborted(
        fake,
        tmp_path / "out",
        code,
        result,
        "the saved Project.ini names the CPU C0-11DD1E-D, not C0-02DD1-D",
    )
    assert result["step"] == "check"
    assert result["project"]["cpu"] == "C0-11DD1E-D"


def test_new_calls_on_new_project_while_click_has_the_project_open(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    seen: list[tuple[cr.NewProject, bool, str]] = []

    def on_new_project(run: cr.Run, project: cr.NewProject) -> None:
        assert fake.main is not None
        seen.append((project, fake.is_running, fake.main.title))
        run.log("on_new_project ran")

    code, result = run_command(
        fake, tmp_path, exe, "new", "--cpu", "C2-03CPU", on_new_project=on_new_project
    )
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out"
    assert fake.main is not None
    [(project, running, title)] = seen
    assert project == cr.NewProject(
        model="C2-03CPU",
        ckp=(out / "C2-03CPU.ckp").resolve(),
        pid=4242,
        main=fake.main.hwnd,
        temp=fake.temp_dir(fake.main.hwnd),
    )
    assert running and "C2-03CPU.ckp" in title
    assert list(result["timings"])[-3:] == ["check", "on_new_project", "close"]
    # The call may have changed the project, so the runner ended CLICK instead of closing it
    assert fake.terminated and not fake.exited_cleanly
    assert "on_new_project ran" in (out / "run.log").read_text(encoding="utf-8")


def test_new_stops_when_on_new_project_raises(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)

    def on_new_project(run: cr.Run, project: cr.NewProject) -> None:
        raise cr.Aborted("the smoke found a fault")

    code, result = run_command(
        fake, tmp_path, exe, "new", "--cpu", "C0-02DD1-D", on_new_project=on_new_project
    )
    assert_aborted(fake, tmp_path / "out", code, result, "the smoke found a fault")
    assert result["step"] == "on_new_project"


def test_on_new_project_can_import_and_export_into_folders_of_its_own(tmp_path, setup):
    # new has already copied CLICK's files into DIR/click/, where export writes by default
    _, exe = setup
    csv = tmp_path / "nicknames.csv"
    csv.write_bytes(IMPORT_CSV)
    fake = FakeClick(tmp_path)
    out = tmp_path / "out"
    seen: dict[str, Any] = {}

    def on_new_project(run: cr.Run, project: cr.NewProject) -> None:
        seen["import"] = run.import_one(1, "smoke", csv, None, None)
        seen["first"] = run.export(out / "first")
        seen["second"] = run.export(out / "second")

    code, result = run_command(
        fake, tmp_path, exe, "new", "--cpu", "C2-03CPU", on_new_project=on_new_project
    )
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.imported == [("Delete Existing", "nicknames.csv")]
    assert seen["import"]["answer"] == "errors"
    assert seen["import"]["mdb"] == out / "mdb" / "01-smoke.mdb"
    assert result["imports"] == [json.loads(json.dumps(seen["import"], default=str))]
    for name in ("first", "second"):
        assert seen[name]["copy"] == out / name / "export.csv"
        assert (
            fake.exported[-1 if name == "second" else 0]
            == (out / name / "click" / "nicknames.csv").resolve()
        )
        # The fake's export lists what the import stored
        assert [line.split(",")[0] for line in seen[name]["first_lines"][1:]] == ["DS20", "TXT20"]
    # The result keeps the last export
    assert result["export"]["copy"] == str(out / "second" / "export.csv")


# ---------------------------------------------------------------------------
# new --cpu none: a project with no CPU
# ---------------------------------------------------------------------------


def test_new_none_cancels_the_cpu_closes_startup_and_saves_a_project_with_no_cpu(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "none")
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out"
    # The runner pressed Start a new project and then Cancel in Select a CPU Module. It closed
    # Startup with WM_CLOSE, sent no key to the list and no command but Save As, and never
    # connected
    assert fake.pressed == ["TButton@747", "Cancel", "&Save"]
    wizard = ("cpu", "cpu_ok", "cpu_cancel", "startup_close")
    assert [e for e in fake.events if e in wizard] == ["cpu", "cpu_cancel", "startup_close"]
    assert fake.keys == []
    assert fake.commands == ["Save Project As"]
    assert not fake.connected and not fake.went_offline
    assert result["cpu"] is None
    assert result["cpu_list"] is None
    assert result["user_accounts"] is None
    assert result["project"] == {"cpu": None, "slots": {}, "expansions": {}, "sec21": None}
    assert result["status_bar"]["new_project"][10] == "No select CPU"
    assert Path(result["files"]["ckp"]) == out / "none.ckp"
    assert sorted(p.name for p in (out / "click").iterdir()) == ["Project.ini", "Scr1.tmp"]
    assert list(result["timings"]) == [
        "refuse",
        "launch",
        "startup",
        "cpu",
        "close_startup",
        "new_project",
        "save",
        "copy",
        "check",
        "close",
    ]
    assert fake.exited_cleanly and not fake.terminated
    assert_temp_left_to_click(fake, out, still_there=False)


@pytest.mark.parametrize(
    ("event", "step"), [("cpu_cancel", "cpu"), ("startup_close", "close_startup")]
)
def test_new_none_stops_at_an_unexpected_window(tmp_path, setup, event, step):
    _, exe = setup
    fake = FakeClick(tmp_path, surprise=event)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "none")
    assert_aborted(fake, tmp_path / "out", code, result, "unexpected window")
    assert "'Set a Project Password'" in result["reason"]
    assert result["step"] == step
    assert fake.commands == []
    assert "Connect" not in fake.pressed


@pytest.mark.parametrize("first", ["form", "startup"])
def test_new_none_closes_startup_only_once_the_form_is_gone_and_startup_is_enabled(
    tmp_path, setup, first
):
    # After the Cancel, the form goes and Startup is enabled on different polls
    _, exe = setup
    fake = FakeClick(tmp_path, cancel_first=first)
    seen: list[tuple[bool, bool]] = []
    close = fake.close

    def close_and_note(hwnd: int) -> None:
        window = fake.wins[hwnd]
        if window.cls == "TfrmStartup":
            form_open = any(w.cls == "TfrmCPU" for w in fake.wins.values())
            seen.append((form_open, window.enabled))
        close(hwnd)

    fake.close = close_and_note
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "none")
    assert code == cr.EXIT_OK, result["reason"]
    assert seen == [(False, True)]
    later = "startup_enabled" if first == "form" else "form_dropped"
    assert fake.events.index(later) < fake.events.index("startup_close")


def test_new_none_stops_when_the_saved_project_names_a_cpu(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, saved_cpu="C2-03CPU")
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "none")
    assert_aborted(
        fake,
        tmp_path / "out",
        code,
        result,
        "the saved Project.ini names the CPU C2-03CPU. A project for --cpu none must name no CPU.",
    )
    assert result["step"] == "check"
    assert result["cpu"] is None
    assert result["project"]["cpu"] == "C2-03CPU"


def test_new_stops_when_the_saved_project_names_no_cpu(tmp_path, setup, monkeypatch):
    # CLICK wrote no [Sec21] for the CPU that the runner picked
    _, exe = setup
    fake = FakeClick(tmp_path)
    monkeypatch.setattr(fake, "_write_sec21", lambda saved: None)
    code, result = run_command(fake, tmp_path, exe, "new", "--cpu", "C0-02DD1-D")
    assert_aborted(
        fake, tmp_path / "out", code, result, "the saved Project.ini names no CPU, not C0-02DD1-D"
    )
    assert result["step"] == "check"


def test_new_none_records_each_window_and_calls_on_new_project_with_no_model(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    seen: list[cr.NewProject] = []

    def on_new_project(run: cr.Run, project: cr.NewProject) -> None:
        seen.append(project)

    code, result = run_command(
        fake, tmp_path, exe, "new", "--cpu", "none", "--record", on_new_project=on_new_project
    )
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out"
    assert fake.main is not None
    assert seen == [
        cr.NewProject(
            model=None,
            ckp=(out / "none.ckp").resolve(),
            pid=4242,
            main=fake.main.hwnd,
            temp=fake.temp_dir(fake.main.hwnd),
        )
    ]
    labels = {p.name.split("-")[1] for p in (out / "record").glob("*.json")}
    assert {"cpu_form", "cpu_cancelled", "new_project"} <= labels
    assert "cpu_picked" not in labels


def test_ini_section_keeps_the_sections_lines_as_clicks_file_holds_them():
    data = (
        b"[Sec21]\r\nKey1=0\r\nKey3_1=198\r\n"
        b"[Sec52]\r\nKey11_1=1\nKey10_1=1\r\n"
        b"[Sec13]\r\nKey13=0\nKey4=\xb0"
    )
    assert cr._ini_section(data, "Sec21") == "[Sec21]\r\nKey1=0\r\nKey3_1=198\r\n"
    assert cr._ini_section(data, "Sec52") == "[Sec52]\r\nKey11_1=1\nKey10_1=1\r\n"
    assert cr._ini_section(data, "Sec13") == "[Sec13]\r\nKey13=0\nKey4=°"
    assert cr._ini_section(data, "Sec2") is None


def test_every_cpu_the_wizard_lists_is_in_pyclickplcs_catalog():
    # pyclickplc has no public list of its models, so this reads its private catalog
    from pyclickplc._module_catalog import _MODULE_CATALOG

    models = {module.model for module in _MODULE_CATALOG.values()}
    assert set(cr.CPU_MODELS) <= models
    assert len(set(cr.CPU_MODELS)) == len(cr.CPU_MODELS) == 37


# ---------------------------------------------------------------------------
# The command allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command_id", "message"),
    [
        (cd.READ_PROJECT_FROM_PLC, "Read Project from PLC"),
        (cd.WRITE_PROJECT_INTO_PLC, "Write Project into PLC"),
        (32853, "Read Project from PLC"),
        (32854, "Write Project into PLC"),
        (32852, "Write Data into PLC"),
        (12345, "a command with no name in the runner"),
    ],
)
@pytest.mark.parametrize("desktop", ["win32", "fake"])
def test_commands_outside_the_allowlist_are_refused(
    tmp_path, monkeypatch, command_id, message, desktop
):
    if desktop == "win32":
        target = cd.Win32Desktop()
    else:
        target = FakeClick(tmp_path)

    def posted(*_: object) -> None:
        raise AssertionError("a refused command was posted")

    monkeypatch.setattr(target, "_post_command", posted)
    with pytest.raises(cd.ForbiddenCommandError, match=message):
        target.command(1, command_id)


def test_the_allowlist_is_the_twenty_seven_commands():
    assert cd.ALLOWED_COMMANDS == {
        0xE125: "Paste",
        0xE122: "Copy",
        32777: "Delete",
        32846: "Syntax Check",
        32771: "New Project",
        32772: "Open Project",
        32898: "Save Project",
        32899: "Save Project As",
        32850: "Disconnect",
        32900: "Import Nickname",
        32901: "Export Nickname",
        32851: "Read Data from PLC",
        32834: "Address Picker",
        32827: "System Configuration",
        50001: "Contact(NO)...",
        50004: "Compare...",
        50010: "Out...",
        50030: "Math...",
        50040: "Copy...",
        50041: "Search...",
        50060: "Receive...",
        # The ids where the live run on 2026-11-18 opened these dialogs (dump_probe.py)
        50020: "Timer...",
        50021: "Counter...",
        50031: "Drum...",
        50036: "Shift Register...",
        50052: "For...",
        50061: "Send...",
    }
    # Nothing that reads a project from the PLC or writes anything into it
    assert not {32852, 32853, 32854} & set(cd.ALLOWED_COMMANDS)


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows'")
def test_a_process_in_the_job_dies_when_the_job_closes():
    """A process in the job dies when the job closes, so CLICK cannot outlive a killed runner.

    Windows closes the job's handle when the runner's process ends, however it ends."""
    # This test runs on the real clock on purpose. The virtual clock (``fast_poll``) has no
    # effect on a real child process and a kernel job.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = cd.kill_on_close(int(child._handle))  # pyright: ignore[reportAttributeAccessIssue]
        assert child.poll() is None
        began = time.monotonic()
        cd._kernel32().CloseHandle(job)
        child.wait(timeout=10)  # Far less than the minute that the child sleeps
        assert time.monotonic() - began < 10
    finally:
        child.kill()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32Desktop is Windows'")
@pytest.mark.parametrize("fails", [False, True])
def test_launch_puts_click_in_the_job(tmp_path, monkeypatch, fails):
    class Process:
        pid = 31
        _handle = 77
        killed = waited = False

        def kill(self) -> None:
            self.killed = True

        def wait(self) -> int:
            self.waited = True
            return 1

    process = Process()
    jobs: list[int] = []

    def kill_on_close(handle: int) -> int:
        if fails:
            raise OSError("no job")
        jobs.append(handle)
        return 5

    monkeypatch.setattr(cd.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(cd, "kill_on_close", kill_on_close)
    desktop = cd.Win32Desktop()
    if fails:
        with pytest.raises(OSError, match="no job"):
            desktop.launch(tmp_path / "CLICK.exe")
        assert process.killed and process.waited
    else:
        assert desktop.launch(tmp_path / "CLICK.exe") == 31
        assert jobs == [77] and not process.killed


@pytest.mark.parametrize("views", [1, 0, 2])
def test_the_ladder_click_is_posted_to_the_one_visible_view(monkeypatch, views):
    target = cd.Win32Desktop()
    posted: list[tuple[int, ...]] = []
    monkeypatch.setattr(target, "_post", lambda *message: posted.append(message))

    def control(hwnd: int, cls: str, visible: bool) -> cd.Control:
        return cd.Control(hwnd, 1, cls, "", 59648, visible, True, (0, 0, 9, 9))

    shown = [control(10 + n, cd.LADDER_VIEW_CLASS, True) for n in range(views)]
    others = [control(30, cd.LADDER_VIEW_CLASS, False), control(31, "msctls_statusbar32", True)]
    monkeypatch.setattr(target, "controls", lambda hwnd: [*others, *shown])
    if views != 1:
        with pytest.raises(cd.LadderViewError, match=f"{views} visible ladder views"):
            target.click_ladder(1, 25, 70)
        assert posted == []
        return
    assert target.click_ladder(1, 25, 70) == 10
    point = 70 << 16 | 25
    assert posted == [
        (10, cd.WM_LBUTTONDOWN, cd.MK_LBUTTON, point),
        (10, cd.WM_LBUTTONUP, 0, point),
    ]


def test_wm_command_is_posted_in_one_place():
    """Only Win32Desktop._post_command posts WM_COMMAND, only Desktop.command calls it, and
    the runner reaches Win32 only through Desktop."""
    devtools = Path(cd.__file__).parent
    desktop = (devtools / "click_desktop.py").read_text(encoding="utf-8")
    runner = (devtools / "click_runner.py").read_text(encoding="utf-8")
    assert desktop.count("WM_COMMAND,") == 1  # self._post(hwnd, WM_COMMAND, command_id)
    assert desktop.count("._post_command(") == 1  # in Desktop.command
    for name in ("0x0111", "_post", "ctypes", "win32", "Message"):
        assert name not in runner, name


# ---------------------------------------------------------------------------
# File > New Project from an open project (Run.file_new, called by on_new_project)
# ---------------------------------------------------------------------------


def run_file_new(fake: FakeClick, tmp_path: Path, exe: Path, model: str, *, unsaved: bool = False):
    """Make a project for *model* by ``new``, then call ``file_new`` from the hook."""
    entries: list[dict] = []

    def on_new_project(run: cr.Run, project: cr.NewProject) -> None:
        if unsaved:
            fake.saved = False
        entries.append(run.file_new())

    code, result = run_command(
        fake, tmp_path, exe, "new", "--cpu", model, on_new_project=on_new_project
    )
    return code, result, entries


def test_file_new_makes_a_new_project_in_the_same_window_and_temp_folder(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result, entries = run_file_new(fake, tmp_path, exe, "C0-02DD1-D")
    assert code == cr.EXIT_OK, result["reason"]
    [entry] = entries
    # The project was saved, so CLICK asked nothing. Startup's left button started the wizard
    assert entry["save_changes"] is None
    assert fake.commands == ["Save Project As", "New Project"]
    assert fake.pressed == ["TButton@747", "OK", "&Save", "TButton@747", "OK"]
    assert entry["title_before"].endswith(" - C0-02DD1-D.ckp - [Main Program]")
    assert entry["title_after"].endswith(" - NewProject1.ckp - [Main Program]")
    assert entry["main"] == fake.main.hwnd
    assert Path(entry["temp"]) == fake.temp_dir(fake.main.hwnd)
    assert entry["temp_created_before"] == entry["temp_created_after"] is not None
    # CLICK deleted the saved project's Scr1.tmp. A new project has none until it is saved
    assert entry["files_after"] == ["Project.ini", "SC_.mdb"]
    assert entry["user_accounts"] is None
    assert result["file_new"]["title_after"] == entry["title_after"]
    assert list(result["timings"])[-3:] == ["file_new", "on_new_project", "close"]


def test_file_new_answers_no_when_click_asks_whether_to_save(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result, entries = run_file_new(fake, tmp_path, exe, "C0-02DD1-D", unsaved=True)
    assert code == cr.EXIT_OK, result["reason"]
    assert entries[0]["save_changes"] == SAVE_CHANGES_TEXT
    assert fake.pressed[-3:] == ["&No", "TButton@747", "OK"]
    assert "&Yes" not in fake.pressed and "Cancel" not in fake.pressed


def test_file_new_answers_no_for_the_open_project_whatever_the_case(tmp_path, setup):
    _, exe = setup
    text = "Save changes to D:\\Work\\c0-02dd1-d.CKP?"
    fake = FakeClick(tmp_path, new_box=(text, SAVE_CHANGES_BUTTONS, ()))
    code, result, entries = run_file_new(fake, tmp_path, exe, "C0-02DD1-D")
    assert code == cr.EXIT_OK, result["reason"]
    assert entries[0]["save_changes"] == text
    assert "&No" in fake.pressed


@pytest.mark.parametrize(
    "box",
    [
        # Another file than the open project
        ("Save changes to C:\\other\\x.cdv?", SAVE_CHANGES_BUTTONS, ()),
        ("Save changes to C:\\projects\\C0-02DD1-D.ckp.bak?", SAVE_CHANGES_BUTTONS, ()),
        # Another question
        ("Discard the project?", SAVE_CHANGES_BUTTONS, ()),
        # Other buttons, or No with another id, disabled, or with a control of another class
        (SAVE_CHANGES_TEXT, (("&Yes", 6, True), ("&No", 7, True)), ()),
        (SAVE_CHANGES_TEXT, (("&Yes", 6, True), ("&No", 8, True), ("Cancel", 2, True)), ()),
        (SAVE_CHANGES_TEXT, (("&Yes", 6, True), ("&No", 7, False), ("Cancel", 2, True)), ()),
        (SAVE_CHANGES_TEXT, SAVE_CHANGES_BUTTONS, ("Edit",)),
    ],
)
def test_file_new_stops_at_a_question_that_it_does_not_answer(tmp_path, setup, box):
    _, exe = setup
    fake = FakeClick(tmp_path, new_box=box)
    code, result, _ = run_file_new(fake, tmp_path, exe, "C0-02DD1-D")
    assert_aborted(fake, tmp_path / "out", code, result, "CLICK asked something")
    assert "with 'C0-02DD1-D.ckp' open" in result["reason"]
    assert result["step"] == "file_new"
    # Nothing was pressed in the box
    assert fake.pressed == ["TButton@747", "OK", "&Save"]


def test_file_new_stops_at_a_second_box_after_no(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, new_second_box=True)
    code, result, _ = run_file_new(fake, tmp_path, exe, "C0-02DD1-D", unsaved=True)
    assert_aborted(fake, tmp_path / "out", code, result, "a second box after No")
    # The run stopped at the box, not at the timeout
    assert "'CLICK Programming Software'" in result["reason"]
    assert "timed out" not in result["reason"]
    assert fake.pressed[-1] == "&No"


def test_file_new_cancels_user_account_setup(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result, entries = run_file_new(fake, tmp_path, exe, "C2-03CPU")
    assert code == cr.EXIT_OK, result["reason"]
    assert entries[0]["user_accounts"] == "cancelled"
    assert fake.pressed[-3:] == ["TButton@747", "OK", "Cancel"]


def test_file_new_waits_until_sc_mdb_stops_changing(tmp_path, setup):
    # CLICK wrote SC_.mdb again more than a second after the title named the new project
    _, exe = setup
    fake = FakeClick(tmp_path, new_writes=3)
    code, result, entries = run_file_new(fake, tmp_path, exe, "C0-02DD1-D")
    assert code == cr.EXIT_OK, result["reason"]
    assert len(fake.new_mdb_writes) == 3
    temp = Path(entries[0]["temp"])
    assert (temp / "SC_.mdb").read_bytes() == b"new mdb!!!"
    assert "file_new" in result["status_bar"]


def test_file_new_waits_for_the_title_to_name_the_project(tmp_path, setup):
    # The title stays bare for longer than NEW_SETTLE after SC_.mdb is written
    _, exe = setup
    fake = FakeClick(tmp_path, new_title_polls=600)
    code, result, entries = run_file_new(fake, tmp_path, exe, "C0-02DD1-D")
    assert code == cr.EXIT_OK, result["reason"]
    assert entries[0]["title_after"].endswith(" - NewProject1.ckp - [Main Program]")


def test_file_new_stops_when_sc_mdb_never_appears(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path, stall="new_mdb")
    code, result, _ = run_file_new(fake, tmp_path, exe, "C0-02DD1-D")
    assert_aborted(fake, tmp_path / "out", code, result, "waiting for the new project's SC_.mdb")
    assert "new_title" in fake.events
    assert result["file_new"]["title_after"] is None


@pytest.mark.parametrize(
    ("event", "waiting_for"),
    [
        # The second CPU OK: while the runner waits for User Account Setup
        ("cpu_ok", "User Account Setup or the main window alone"),
        # While SC_.mdb settles
        ("new_title", "the new project's SC_.mdb to settle"),
    ],
)
def test_file_new_stops_at_an_unexpected_window(tmp_path, setup, event, waiting_for):
    _, exe = setup
    fake = FakeClick(tmp_path)
    surprise = {"armed": False}

    def arm(run: cr.Run, project: cr.NewProject) -> None:
        # Only after the first project is made, so the surprise comes in File > New Project
        fake.surprise = event
        surprise["armed"] = True
        run.file_new()

    code, result = run_command(
        fake, tmp_path, exe, "new", "--cpu", "C0-02DD1-D", on_new_project=arm
    )
    assert surprise["armed"]
    assert_aborted(fake, tmp_path / "out", code, result, f"while waiting for {waiting_for}")
    assert "'Set a Project Password'" in result["reason"]
    assert result["step"] == "file_new"


def test_file_new_refuses_a_project_with_no_cpu(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result, _ = run_file_new(fake, tmp_path, exe, "none")
    assert_aborted(fake, tmp_path / "out", code, result, "needs a CPU that the wizard lists")
    assert "New Project" not in fake.commands
