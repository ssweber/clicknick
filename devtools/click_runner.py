"""Drive CLICK v4 unattended: paste a ladder CSV into a new project, check it, save it, decode it.

    uv run python devtools/click_runner.py paste CSV --out DIR [--record]
    uv run python devtools/click_runner.py record --out DIR
    uv run python devtools/click_runner.py try CASES.json --out DIR [--wire] [--keep]
        [--resume PREV_DIR] [--stop-after N] [--record]
    uv run python devtools/click_runner.py import CSV --out DIR [--each-row] [--record]
    uv run python devtools/click_runner.py reopen --out DIR [--ini-add LINES] [--record]
    uv run python devtools/click_runner.py read-data --out DIR [--record]
    uv run python devtools/click_runner.py picker --out DIR [--key KEY ...] [--ok] [--record]

The runner starts its own CLICK. It connects to the one PLC on the LAN, so the new project
takes that PLC's hardware. It answers "Don't read" to the question about reading the PLC's
project. ``paste`` then pastes the CSV into the main program and runs Syntax Check. It saves
the project as ``DIR/<CSV name>.ckp`` and copies CLICK's Scr*.tmp files and Project.ini into
``DIR/click/``. It disconnects, closes CLICK and decodes ``DIR/click/`` into ``DIR/csv/``.

``record`` connects the same way and dumps every window of CLICK (JSON and PNG) into
``DIR/record/`` at each step. It then disconnects and ends CLICK. The project was never
saved, so the runner terminates CLICK instead of closing it. ``paste --record`` and
``try --record`` dump the same way. A PNG is a picture of the screen where the window is,
so anything that lies over CLICK there is in it.

``try`` asks CLICK's instruction dialogs whether they accept an instruction (``CASES``).
Once connected, it copies the new project's SC_.mdb to ``DIR/SC_.mdb``. From the copy it
reads the nicknames of the addresses that CASES.json lists under ``nicknames``. A new
project's SC_.mdb holds few: live run try3 found SC202, SC203 and SD13 only. Then it runs
Syntax Check on the empty main program (``baseline_syntax_check``). That check must name
rung 1 for the missing END (C0201).

Then, for each case, ``try`` opens the instruction's dialog from the ribbon's command at the
ladder's cursor. It checks the buttons and lists that the case takes as given: One Shot off,
Out's type Out/Toggle, Receive's CPU Port2 and Function Code 01. It picks the mode, and it
picks in each list the item that the case's ``choices`` name. A mode button that is already
checked is left alone, because Math empties its fields on any type click. Up and Down keys
are sent to the list alone. It fills the fields by WM_SETTEXT. It picks the operator of
Compare and Search (the mode) after the fields, because a TXT address hides some operators.

Then it sets the case's ``options``. Each option is named by the label its button shows now,
or by its id. CLICK relabels Copy's buttons as the fields change. Options asked 1 are set
before options asked 0, so that a radio button's press has unchecked its pair asked 0
already. A field that the case asks for may open only after such a press (Copy's Termination
code, once its option is checked). The runner fills that field then.

It reads back the fields, every list and every option it set. For Receive it reads back
every open field, including the ones that the case leaves as the dialog filled them. It
waits until the dialog is alone and presses OK.

A case is ``not_taken`` when any of these is true: a field, list, mode or option is closed
for entry (hidden or disabled); no option button shows the label that the case names; a
radio button is asked to be unchecked; a field, list or option reads back otherwise; or a
list lacks the item asked for. In that case the runner closes the dialog with Cancel and
does not press OK.
The run stops if CLICK does not answer when a field is set or read, because CLICK may have
stalled. It also stops if an option does not read as asked after ``OPTION_PRESSES`` presses.
Live probe d4c saw a press lost. The case's ``controls`` list the dialog's visible buttons,
statics and edits as they are when OK (or Cancel) is pressed.

After OK, CLICK either shows an error box owned by the dialog or closes the dialog. With the
box, the case is ``refused`` and carries the box's code and message. The box's OK and the
dialog's Cancel then close both. A dialog that closed gets a Syntax Check of its own. The
case keeps the lines that name a code the empty program's check does not. The case is
``accepted`` only when that check names rung 2 for the missing END, as an instruction in
rung 1 makes it. Otherwise it is ``other``, and that stops the run. Edit > Delete then
removes the instruction, and the next Syntax Check must read as the empty program's did.

All cases run in one CLICK. The runner then disconnects it and ends it, as ``record`` does.
result.json holds one entry per case under ``cases``, in the file's order. After an abort it
keeps the entries that were done before.

``try --wire`` tries each case in a rung of its own, as a program holds it. An output
instruction (Copy, Math, Out, Receive, Search) is placed behind a contact ``X001`` (the
ribbon's Contact(NO), whose OK leaves the cursor at column B). A contact instruction
(Compare, which ``try`` takes only with ``--wire``) gets an Out coil ``Y001`` once its
dialog closes. The Syntax Check of an accepted case must then name nothing that the empty
program's check does not. After each case the whole rung is deleted. That includes a contact
placed for a case that CLICK refused or that was not taken. The runner posts a click on
rung 1's number in the ladder view, which selects the rung (``Desktop.click_ladder``), then
runs Edit > Delete. A resume refuses a run whose cases were tried otherwise, with ``--wire``
or without.

A case's id is its ``case``, unique in its file. The runner appends each case's entry to
``DIR/cases.jsonl`` as one line as soon as it is known. A run that stops therefore keeps
every answer before the stop. A case that stops the run gets a line too, with the stop under
``stops``, and is the result's ``stopped_at``.

``--resume PREV_DIR`` reads PREV_DIR's ``cases.jsonl`` before CLICK starts. It takes the last
line for each case. Each such entry must ask what this file's case of that id asks. The
runner carries the entries into this run's ``cases`` and ``cases.jsonl``, and tries only the
other cases, in a CLICK of its own. It does not try again a case that has an outcome. It
also does not try again a case that stopped ``MAX_STOPS`` runs, and a Ctrl+C is not counted.
A case that stopped fewer runs is tried again, and the runner writes its line with its
stops too. If the run stopped after an answer (Delete or the save failed), the stop keeps
the answer and the case has no outcome. With ``--keep``, an accepted case without its save
counts as unanswered. ``--stop-after N`` ends the run cleanly once it has tried N cases
(``stopped_after``). ``left`` counts the cases with no outcome. An unexpected window still
stops the run. Nothing starts a CLICK again by itself.

``try --keep`` also saves the project before each Delete, so that you can read what CLICK
stores for an accepted instruction. It runs File > Save As ``DIR/saves/caseNN.ckp`` (NN is
the case's number). Then it copies CLICK's Scr*.tmp files and Project.ini into
``DIR/saves/caseNN/click/``. With ``--wire``, CLICK's Edit > Copy then also copies rung 1,
and the runner writes the clipboard's CLICK data to ``DIR/saves/caseNN.clip.bin``. If the
clipboard has none, the run stops. Once CLICK has ended (after an abort too), the runner
decodes each copy into ``DIR/saves/caseNN/csv/`` and reads the tags that each instruction
holds, as stored. It decodes the clipboard's file into ``DIR/saves/caseNN.clip.csv``.
The case's ``clip_error`` names what in it laddercodec cannot read or write, or why it
cannot be decoded at all. Each save renames the project, so a Syntax Check is compared with
the empty program's without the project's name. The runner writes each decoded case's line
again with what was read. A resumed run decodes the carried copies that its run left
undecoded, because that run's process ended first. It decodes them into its own
``DIR/saves/caseNN/csv/``.

``import`` imports a nickname CSV through CLICK's own File > Import > Nickname (32900) and
reads what CLICK stored. With ``--each-row`` it then imports each row on its own, in a file
of the CSV's header and that row, byte for byte (``DIR/rows/``). It does this because a row
that CLICK refuses may change another. A row is one line, as CLICK reads it, so a line break
inside quotes ends the row (``split_rows``). Every import picks the mode Delete Existing in
the Open dialog, so CLICK empties the address table first and what it stores is what it made
of that file alone. The runner fills in the path and presses Open. CLICK answers with a box
reading "Completed!" or with its Import Error List, a text that lists each line CLICK could
not take, and why. The runner keeps that text and presses the box's OK. It then waits until
the main window is alone and CLICK's SC_.mdb has been unchanged for ``IMPORT_SETTLE``, and
copies SC_.mdb into ``DIR/mdb/``. Once CLICK has ended (disconnected and ended, as ``try``
ends it), the runner reads each copy through Access ODBC, so a NULL stays None and a text
keeps every character. result.json holds one entry per import under ``imports``
(``Run.import_one``), after an abort too.

``reopen`` asks what CLICK does with a project's Project.ini. It disconnects, saves the new
project as ``DIR/first.ckp``, adds the ASCII lines of ``--ini-add`` to the end of the
Project.ini in CLICK's temp folder (the runner's own CLICK's), saves as ``DIR/second.ckp``,
opens ``second.ckp`` by File > Open Project (32772; CLICK shows "Project Reading" meanwhile)
and saves it as ``DIR/third.ckp``. At each point (``first``, ``second``, ``opened``,
``third``) the runner copies CLICK's files into ``DIR/<point>/click/``. Under ``points``,
result.json keeps the main window's title, the status bar, Project.ini's text and the PLC
Name that System Configuration (32827) shows (``plc_name``). The runner closes System
Configuration by Cancel, never by OK, because OK saves setup into the project. The first
time, System Configuration shows a notice over itself. The runner closes that notice by
WM_CLOSE.

``read-data`` saves the PLC's data values through PLC > Read Data from PLC (32851). It
presses All, waits until every memory type is checked, presses Read, gives CLICK's Save
dialog ``DIR/plcdata.csv`` and waits until CLICK's reading window has gone and the file
keeps its size on two polls (``files.plc_data``; ``reading_seen`` says the reading window
showed). The run stops if the reading window has shown and gone, the form is back, and no
file has appeared for ``IMPORT_SETTLE``. If the reading window never shows, the runner waits
out ``--paste-timeout``. It reads; it never writes into the PLC.

``picker`` opens Program > Address Picker (32834), CLICK's address editor, between two
copies of SC_.mdb (``DIR/mdb/before.mdb`` and ``after.mdb``, each taken once SC_.mdb is
unchanged for ``IMPORT_SETTLE``; ``mdb_copies``). The runner sends (does not post) each
``--key`` to the grid or, once it shows, to CLICK's in-place editor. A key is one of: a key
by name (WM_KEYDOWN and WM_KEYUP), ``chars:TEXT`` (WM_CHAR), ``text:TEXT`` (WM_SETTEXT) or
``find:TEXT`` (the Find box's text, then Find, its BM_CLICK sent too). Each key has been
handled when the send returns, so the next key goes to the row it left. The run stops if
CLICK does not answer a key within 5 s, as happens when a key opens a box over the picker
(the abort dump shows the box). It also stops if a window is over the picker after a key.
After each key result.json keeps the editor's text, whether it shows and the hints CLICK
shows under it (``keys``). ``--ok`` closes the picker by OK. Without it, WM_CLOSE closes the
picker. The runner reads the copies through Access ODBC once CLICK has ended. ``read-data``
and ``picker`` dump CLICK's windows into ``DIR/record/`` only with ``--record``.

Every Syntax Check (``paste``'s too) empties Output first, so a result that reads as the one
before is still seen. CLICK ignores a Syntax Check posted soon after the last one's result
showed (live probe 3). Nothing it shows says when it would take one. So if Output stays
empty while CLICK answers, the runner posts the check again after ``SYNTAX_REPOST_AFTER``
seconds, up to ``SYNTAX_POSTS`` posts in all.

``DIR`` must not exist or be empty. However the run ends, it ends with ``DIR/result.json``,
and the runner prints that file on stdout. Nothing else goes there. Each step is logged to
``DIR/run.log`` and stderr. The exit code is 0 when the status is ``ok``, 1 when ``aborted``
and 2 when ``refused`` (nothing was started). result.json holds: the status, the step
reached and the reason; the Syntax Check's text with its error and warning counts; the
rungs pasted and saved (``same`` when the saved main program starts with the CSV's rungs);
the PLC that the status bar named once connected (``plc``); the status bar's panes at each
step; the code of a CLICK error box that stopped the run (``click_error``; one met while the
cleanup disconnects is ``cleanup_click_error``); the files written; and how long each step
took.

Rules (scratchpad/roadmap.md, item 4):

- It refuses to start while any CLICK.exe runs or any CLICK window is open, or while the
  input desktop is not ``Default`` (a locked screen). It touches only the CLICK it started.
  It finds its windows by pid, and its files in ``click_temp_dir`` of its main window. It
  never deletes a temp folder, because CLICK looks after its own.
- It never writes to the PLC: every WM_COMMAND goes through ``Desktop.command`` and its
  allowlist (click_desktop.py). The one mouse click it makes (``try --wire``) is posted to
  the ladder view, through ``Desktop.click_ladder``.
- It connects only when the Connect dialog scans the same LAN and its PLC list has read
  one PLC for ``PLC_SETTLE`` seconds. If the list shows two or more PLCs, the run stops.
  Once connected, the status bar must name a PLC within ``--timeout`` (``plc`` in
  result.json; ``--plc NAME`` requires that one). If the bar cannot be read in that time,
  the connection stays unconfirmed, unless ``--plc`` is given. Then the run stops.
- If a Scr*.tmp is in CLICK's temp folder before the paste (``scr_before_paste``) and the
  save does not rewrite it, the run stops. Otherwise the runner would decode it with the
  project.
- Each step waits for a condition. Waiting for a dialog gives up after ``--timeout``
  seconds (default 60). CLICK freezes while it pastes, so the paste, Syntax Check, save
  and close may take up to ``--paste-timeout`` (default 300). Live run 7 (2026-11-15)
  saw a paste of 301 rungs freeze it for 16 s and their Syntax Check for 6 s. The paste
  is done when CLICK answers again and, if its status bar can be read, shows the rungs
  pasted. The final check is that the saved main program holds them. Nothing is sent to a
  CLICK that does not answer. A wait logs the status bar every ``STATUS_EVERY`` seconds.
- A CLICK error box (a dialog whose text is a code on a line of its own, then a message:
  "PTC-013", "Timeout on attempting to connect to PLC.") stops the run at any step. The
  code goes in ``click_error``, so a caller can decide to run again. Nothing is pressed in
  it. A box met while the cleanup disconnects after another stop is logged and kept as
  ``cleanup_click_error``. It is not what stopped the run. The one exception is ``try``: a
  box owned by an instruction dialog after its OK is the case's answer. A box there with no
  code, or with buttons other than one OK, is a question the runner does not answer. The
  case is kept as ``other`` and the run stops. An import's answer is the "Import Database"
  box with one text and one OK, or the error list with one text and Ok. Any other box
  there, or a second answer, stops the run.
- Any top-level window of CLICK that the step does not expect (a tooltip aside) stops the
  run. The runner dumps every window into ``DIR/abort/`` (a window that does not answer is
  dumped without its edit text or a PNG). If CLICK answers with no dialog open, the runner
  disconnects it. It then ends CLICK without saving. A timeout, an error or Ctrl+C ends the
  run the same way. CLICK runs in a job that ends it when the runner's process ends,
  however that ends.

Login: CLICK fills in User Type itself (``admin``). The runner fills it in only when it is
empty, from ``--user-type`` or ``CLICK_RUNNER_USER_TYPE`` (default ``admin``). The password
comes from ``--password`` or ``CLICK_RUNNER_PASSWORD`` (default ``123click``). A PLC with
no password shows no Login dialog.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import sys
import time
import warnings
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager, redirect_stdout
from dataclasses import KW_ONLY, asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from click_desktop import (
    ADDRESS_PICKER,
    COMPARE_DIALOG,
    CONTACT_NO_DIALOG,
    COPY_DIALOG,
    DELETE,
    DISCONNECT,
    EDIT_COPY,
    IMPORT_NICKNAME,
    MATH_DIALOG,
    OPEN_PROJECT,
    OUT_DIALOG,
    PASTE,
    READ_DATA_FROM_PLC,
    RECEIVE_DIALOG,
    SAVE_PROJECT_AS,
    SEARCH_DIALOG,
    SYNTAX_CHECK,
    SYSTEM_CONFIGURATION,
    Control,
    Desktop,
    LadderViewError,
    Window,
)

DEFAULT_EXE = Path(r"C:\Program Files (x86)\AutomationDirect\CLICK Ver4.00\CLICK.exe")
DEFAULT_PASSWORD = "123click"
DEFAULT_USER_TYPE = "admin"
DEFAULT_TIMEOUT = 60.0
# The ceiling for the steps that CLICK may be busy in (paste, Syntax Check, save, close).
# CLICK freezes until a paste is done
DEFAULT_PASTE_TIMEOUT = 300.0
POLL_INTERVAL = 0.1
# How long one check waits for CLICK to answer (WM_NULL); a busy CLICK is no error
IDLE_TIMEOUT = 2.0
# After a paste, CLICK answers on this many polls in a row before the paste is done
RESPONSIVE_POLLS = 3
# How often a wait logs the status bar (or that CLICK does not answer)
STATUS_EVERY = 10.0
# SYNTAX_REPOST_AFTER is how many seconds Output may stay empty, with CLICK idle, before
# Syntax Check is posted again. SYNTAX_POSTS is the most posts. CLICK ignores a Syntax Check
# posted soon after the last one's result showed (live probe 3: 4 of 4 posted 0 to 0.5 s
# after it; 5 of 5 posted 1.5 s or more after it ran). Nothing it shows says when it would
# take one
SYNTAX_REPOST_AFTER = 2.0
SYNTAX_POSTS = 3
STATUS_BAR_ID = 59393  # AFX_IDW_STATUS_BAR
# The runner takes the Connect dialog's PLC list once it has read the same for this many
# seconds. The LAN scan adds its rows one at a time
PLC_SETTLE = 2.0
# An import is done once CLICK's main window is alone and its SC_.mdb has read the same for
# this many seconds. The live runs saw SC_.mdb written before the answer showed. The wait
# catches a write that comes later
IMPORT_SETTLE = 1.0
# How long a file dialog's File name edit must read the path set before it is pressed
# (``Run.fill_path``)
FILL_SETTLE = 1.0
# ``try`` writes each case's entry here as soon as it is known, one JSON line each
CASES_LOG = "cases.jsonl"
# A case that stopped this many runs before CLICK answered it is not tried again by --resume
MAX_STOPS = 2
# What ``choose`` returns for a list not open for entry
_CLOSED = "closed"
# The runner presses an option button up to this many times, and gives each press this many
# seconds to show the state asked for. Live probe d4c (2026-11-17, job copy-encodings) saw
# the first BM_CLICK, posted to Copy's Termination Code after its address fields were set by
# WM_SETTEXT, leave it unchecked. The next BM_CLICK checked it
OPTION_PRESSES = 3
OPTION_WAIT = 3.0
# try --wire: rung 1's number in the ladder view, as a client point at CLICK v4.00's default
# zoom. A click posted there selects the rung and moves the cursor to 1:1:A. Edit > Delete
# then removes the whole rung (live probe d2, 2026-11-17)
RUNG1_POINT = (25, 70)
RUNG1_CURSOR = "1:1:A"
# The contact that an output instruction is wired behind, and the coil that a contact
# instruction drives. After the contact's OK the cursor is at 1:1:B, and an output
# instruction lands at AF
WIRE_CONTACT = "X001"
WIRE_COIL = "Y001"
CONTACT_CURSOR = "1:1:B"

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_REFUSED = 2

_MAIN_TITLE = re.compile(r"^CLICK Programming Software \(Version4\.\d+\) - ")
_NOT_RESPONDING = " (Not Responding)"
_CURSOR = re.compile(r"\b(\d+):(\d+):([A-Z]+)\b")
_STEPS = re.compile(r"\b(\d+)/(\d+)\b")
# The text of a CLICK error box: a code, then the message ("PTC-013\nTimeout on ...")
_CLICK_ERROR = re.compile(r"^([A-Z]{2,}-\d{2,})\s*[\r\n]+\s*(\S.*)$", re.DOTALL)
# A Syntax Check line's code: "Main Program : Rung 2 : error C0201: No unconditional END ..."
_SYNTAX_CODE = re.compile(r"\b(?:error|warning) ([A-Z]\d{4}):")
# The rung CLICK names for the missing END: rung 1 in an empty main program, rung 2 once an
# instruction sits in rung 1 (live probes 2 and 3)
_END_RUNG = re.compile(r"\bRung (\d+) : error C0201:")
# The status bar's pane naming the PLC connected to, "192.168.1.241(Conformance)"
_PLC_PANE = re.compile(r"^\d+\.\d+\.\d+\.\d+\(.+\)$")
# Windows that may come and go over CLICK's at any step (a toolbar's tip)
TOOLTIP_CLASS = "tooltips_class32"


class Refused(Exception):
    """The run must not start."""


class Aborted(Exception):
    """The run stops here; cleanup ends CLICK."""


class ClickErrorBox(Aborted):
    """CLICK showed an error box: its code (``PTC-013``) and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"CLICK error {code}: {message}")
        self.code = code


class _Unconfirmed(Exception):
    """The status bar could not be read over the whole wait to confirm the connection."""


# ---------------------------------------------------------------------------
# The windows each step expects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expect:
    """A top-level window of CLICK a step may see: its class, title and owner."""

    name: str
    cls: str
    title: str
    owner: str  # The name of the expected window that owns it


# The main frame is told apart by its title (_MAIN_TITLE) and no owner; its Afx class
# name carries a hash that changes.
MAIN = "main"
GUIDE = Expect("guide", "#32770", "What\u2019s New Feature Guide", MAIN)
STARTUP = Expect("startup", "TfrmStartup", "Startup", MAIN)
CONNECT = Expect("connect", "#32770", "Connect to CLICK PLC", "startup")
LOGIN = Expect("login", "#32770", "Login", "connect")
READ_PROMPT = Expect("read_prompt", "#32770", "Connect", "connect")
SAVE_AS = Expect("save_as", "#32770", "Save As", MAIN)
DISCONNECT_PROMPT = Expect("disconnect_prompt", "#32770", "CLICK Programming Software", MAIN)
# File > Import > Nickname, as live probes 1 to 4 (2026-11-15) dumped it. It opens an Open
# dialog whose template adds three import modes (Delphi radio buttons, Merge (Project
# priority) checked as it opens). Then a progress window shows. One answer then shows while
# the progress window is still up: a box reading "Completed!" or the error list. The progress
# window is titled by its Delphi form's name at first, then by the mode (live run 1)
IMPORT_MODE = "Delete Existing"
OPEN = Expect("open", "#32770", "Open", MAIN)
IMPORT_STARTING = Expect("import_starting", "TfrmProgress", "frmProgress", MAIN)
IMPORT_PROGRESS = Expect("import_progress", "TfrmProgress", f"Import - {IMPORT_MODE}", MAIN)
IMPORT_DONE = Expect("import_done", "#32770", "Import Database", MAIN)
IMPORT_ERRORS = Expect("import_errors", "TfrmErrorList", "Import Error List", MAIN)
# File > Open Project: while CLICK reads the project it shows this progress box (live run
# c1, 2026-11-16: a progress bar, "Reading ..." and a hidden button) and titles the main
# window bare
PROJECT_READING = Expect("project_reading", "#32770", "Project Reading", MAIN)
# PLC > Read Data from PLC, as live probe d1 (2026-11-16) dumped it: a Delphi form with a
# check box per memory type (DS, DD, DH and DF checked as it opens), All, Read, Close, Help
READ_DATA = Expect("read_data", "TfrmReadWriteDataMemory", "Read Data from PLC", MAIN)
# Its Read opens a Save dialog owned by the form (live probe d3), then a progress window
# (two bars and Cancel) while it reads (live probe d5)
SAVE_DATA = Expect("save_data", "#32770", "Save", "read_data")
READING_DATA = Expect(
    "reading_data", "TfrmReadWriteDataMemoryStatus", "Data Memory Reading..", "read_data"
)
# Program > Address Picker, as live probe e1 (2026-11-16) dumped it: a Delphi form with a
# TStringGrid of every address (Address, Data Type, Nickname, Used, Initial Value, Retentive,
# Address Comment), the memory types as tabs, filters, OK, Cancel and Help
PICKER = Expect("picker", "TfrmTagDB", "Address Picker : Edit Mode", MAIN)
# System Configuration, and the notice it shows over itself the first time it opens in a
# CLICK (one OK button; live probe C2)
SYSTEM_CONFIG = Expect("system_config", "TfrmSystemConfig", "System Configuration", MAIN)
SYSTEM_CONFIG_NOTICE = Expect(
    "system_config_notice",
    "TfrmInformationSystemConfigDlg",
    "System Configuration",
    "system_config",
)
# The instruction dialog ``try`` has open, and the error box it may own after OK
DIALOG = "dialog"
ANSWER_BOX = "answer_box"
# The classes of an instruction dialog's fields (Math's formula is a RichEdit)
_FIELD_CLASSES = ("Edit", "RichEdit20W")


# ---------------------------------------------------------------------------
# The instruction dialogs ``try`` fills, and its cases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Instruction:
    """An instruction dialog: the ribbon command that opens it, its title, fields and modes.

    The control ids come from the dialog's template in CLICK's Inst_<name>.dll. The live
    probe of 2026-11-15 found them in the open dialogs. A mode is a radio button.
    *opens_with* gives the state (BM_GETCHECK) of the buttons that the cases take as given,
    as the dialog showed them when it opened in live probe 2. ``try`` checks them before
    filling. A list is a drop-down list (a ComboBox) in which a case may pick an item.
    *opens_listing* gives the item that each list shows as the dialog opens, and ``try``
    checks that too. With *reads_every_field*, a case's answer has the text of every open
    field, as OK found it.

    *options* are the ids of the buttons (check boxes or radio buttons) that a case may set
    by the label they show or by id. ``try`` sets them once the fields are filled, because the
    fields decide which options show. With *mode_after_fields*, ``try`` presses the mode
    after the fields too, because the fields decide which modes are open (Compare's
    operators). Otherwise it presses the mode before them (Math empties its fields on a type
    click). *kind* is where the instruction sits in a rung: ``output`` (at AF, behind a
    contact with ``--wire``) or ``contact`` (at A, driving a coil with ``--wire``).
    *option_radios* are the options that are radio buttons. Pressing a radio button checks
    it. Only a press on its pair unchecks it, so the runner never presses a radio button to
    uncheck it.
    """

    command: int
    title: str
    fields: dict[str, int]  # A field's name -> its edit's control id
    modes: dict[str, int]  # A mode's name -> its radio button's id
    opens_with: dict[int, int]  # A button's id -> its state (1 checked, 0 not)
    lists: dict[str, int] = field(default_factory=dict)  # A list's name -> its ComboBox's id
    opens_listing: dict[int, str] = field(default_factory=dict)  # A ComboBox's id -> its item
    # Whether ``read_back`` (and ``limits``) holds every open field as OK is pressed,
    # including the ones that a case leaves as the dialog filled them
    reads_every_field: bool = False
    options: tuple[int, ...] = ()  # The ids of the option buttons a case may set
    mode_after_fields: bool = False
    kind: str = "output"  # OUTPUT or CONTACT
    option_radios: tuple[int, ...] = ()


OUTPUT = "output"
CONTACT = "contact"

INSTRUCTIONS = {
    # Result is an Edit, the formula a RichEdit20W. Picking Hex empties both. The formula
    # shows addresses (Address 2007, not Nickname 2008); One Shot (2005) is off
    "math": Instruction(
        MATH_DIALOG,
        "Math",
        {"result": 2001, "formula": 2006},
        {"decimal": 2003, "hex": 2004},
        {2005: 0, 2007: 1},
    ),
    # The "to" fields are the end of a range. Block and Pack take a source range. Unpack takes
    # a destination range. Block shows the destination's end, which CLICK works out itself.
    # Fill (5002) is left out: no probe has picked it. One Shot (5024) is off. CLICK relabels
    # the option radios 5019 and 5020 as the fields change ("Copy Value"/"Copy Binary",
    # "Real Numbering"/"Exponential Numbering", "Copy Character Value"/"Copy ASCII Code
    # Value", "Suppress zero"/"Do not suppress zero"); 5036 and 5037 open hidden, reading
    # "Suppress zero" and "Do not suppress zero". The Termination code field (5023, "$00" as
    # the dialog opens) is open only while Termination Code (5021) is checked (live probes d1
    # and d4c, 2026-11-17)
    "copy": Instruction(
        COPY_DIALOG,
        "Copy",
        {
            "source": 5006,
            "source_end": 5009,
            "destination": 5014,
            "destination_end": 5017,
            "termination_code": 5023,
        },
        {"single": 5000, "block": 5001, "pack": 5003, "unpack": 5004},
        {5024: 0},
        options=(5019, 5020, 5036, 5037, 5021, 5024),
        option_radios=(5019, 5020, 5036, 5037),
    ),
    # The output type Out/Toggle (5009) is picked; Immediate (5006), One Shot (5007) and
    # Toggle Output (5008) are off
    "out": Instruction(
        OUT_DIALOG,
        "Out",
        {"address": 5002, "address_end": 5003},
        {},
        {5009: 1, 5006: 0, 5007: 0, 5008: 0},
    ),
    # Receive, as live probes r1 and r2 (2026-11-16) dumped it from Inst_RD.dll's template.
    # It opens on CPU Port2, Function Code 01 and Modbus 984 Addressing. The conformance
    # PLC's project sets Port2's protocol to MODBUS (a serial master: Slave ID, then the
    # Modbus fields). Slave ID reads 1 and Number of Bits 1. CPU Port1 shows the Modbus TCP
    # fields (an IP address control the runner does not fill). The runner never presses its
    # COM Port Setup, which edits the project's port setup. Number of Bits is "Number of
    # Master Addresses" for Function Code 03 and 04. Slave ID and Number of Bits open filled
    # (``reads_every_field``), so what a case leaves there is in its answer
    "receive": Instruction(
        RECEIVE_DIALOG,
        "Receive",
        {
            "slave_id": 5014,
            "slave_address": 5015,
            "master_address": 5016,
            "count": 5017,
            "receiving": 5020,
            "success": 5023,
            "error": 5026,
            "exception": 5029,
        },
        {},
        {},
        lists={"port": 5000, "function": 5001, "addressing": 5002, "word_swap": 5003},
        opens_listing={
            5000: "CPU Port2",
            5001: "01 - Read Coil Status",
            5002: "Modbus 984 Addressing",
        },
        reads_every_field=True,
    ),
    # Compare and Search, as live probe d3 (2026-11-17, job copy-encodings) dumped them from
    # Inst_Compare.dll's and Inst_Search.dll's templates. Their operators are unlabelled
    # radio buttons. d3 placed DS1 ? DS2 with each and decoded them in this order. Compare
    # opens on ==. With TXT1 in Data A only == and != stay visible, so its operator is
    # pressed once the fields are in. It is a contact: ``try`` runs it with --wire only
    "compare": Instruction(
        COMPARE_DIALOG,
        "Compare (A with B)",
        {"a": 5002, "b": 5003},
        {"==": 5006, "!=": 5007, ">": 5008, "<": 5009, ">=": 5010, "<=": 5011},
        {5006: 1},
        mode_after_fields=True,
        kind=CONTACT,
    ),
    # Search opens on ==, with Continuous Search (5021) and One Shot (5022) off
    "search": Instruction(
        SEARCH_DIALOG,
        "Search",
        {"value": 5007, "start": 5010, "end": 5013, "result": 5016, "found": 5019},
        {"==": 5000, "!=": 5001, ">": 5002, "<": 5003, ">=": 5004, "<=": 5005},
        {5000: 1, 5021: 0, 5022: 0},
        options=(5021, 5022),
        mode_after_fields=True,
    ),
}
# try --wire: the contact an output instruction is placed behind (Inst_ContactNO.dll's
# dialog, live probe d1: its address edit 5001, Immediate 5003 off and closed), and the Out
# coil a contact instruction drives (the case instruction ``out``'s dialog)
WIRE_CONTACT_DIALOG = Instruction(
    CONTACT_NO_DIALOG, "Contact Normally Open", {"address": 5001}, {}, {5003: 0}, kind=CONTACT
)
WIRE_COIL_DIALOG = INSTRUCTIONS["out"]


@dataclass(frozen=True)
class Case:
    """One instruction to try: the rule table's row, what is tried, what is entered.

    *name* is the case's id. It is unique in its file, and a resumed run matches answers by it.
    """

    row: str  # The rule table's row ("A9")
    name: str  # What this case tries ("SD1")
    instruction: str  # A key of INSTRUCTIONS
    mode: str | None
    fields: dict[str, str]
    choices: dict[str, str] = field(default_factory=dict)  # A list's name -> the item picked
    # An option button's label or id (a decimal string) -> its state (1 checked, 0 not)
    options: dict[str, int] = field(default_factory=dict)

    def asks(self) -> dict[str, Any]:
        """Return what the case asks, under the keys that its entry in ``cases`` uses."""
        return {
            "row": self.row,
            "case": self.name,
            "instruction": INSTRUCTIONS[self.instruction].title,
            "mode": self.mode,
            "fields": self.fields,
            "choices": self.choices,
            "options": self.options,
        }


class OptionSet(NamedTuple):
    """What ``Run.set_option`` did.

    ``button`` is the button that *key* named, or None when no one button shows it.
    ``pressed`` says whether it was pressed. ``problem`` says why it cannot be set, or is None
    once it reads as asked.
    """

    button: Control | None
    pressed: bool
    problem: str | None


# The value to assume when an entry that an older runner wrote lacks a key that
# ``Case.asks`` now returns
_ASKED_BEFORE = {"options": {}}


def _is_id(key: str) -> bool:
    """Return whether an ``options`` key names its button by id (a decimal string), not by label."""
    return key.isascii() and key.isdecimal()


def load_cases(path: Path) -> tuple[list[Case], list[str]]:
    """Return the cases in *path* and the addresses whose nicknames to read.

    Raise ValueError if the file is malformed. The file is
    ``{"cases": [{"row", "case", "instruction", "mode", "fields"}, ...],
    "nicknames": ["SD21", ...]}``. ``mode`` is required where the dialog has modes, and
    rejected where it has none. ``fields`` names the dialog's fields, each with its text. An
    optional ``choices`` names the dialog's lists, each with the item to pick. An optional
    ``options`` names the dialog's option buttons, each by the label it shows or by its id
    (a decimal string, one of the instruction's ``options``), with 1 (checked) or 0. A label
    is checked only against the open dialog, because CLICK relabels some buttons. ``case`` is
    the case's id and must be unique in the file.
    """
    from pyclickplc.addresses import parse_address

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("expected an object with a list under 'cases'")
    cases: list[Case] = []
    numbers: dict[str, int] = {}
    for number, entry in enumerate(data["cases"], 1):
        where = f"case {number}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object")
        unknown = set(entry) - {
            "row",
            "case",
            "instruction",
            "mode",
            "fields",
            "choices",
            "options",
        }
        if unknown:
            raise ValueError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
        row, name = entry.get("row"), entry.get("case")
        if not isinstance(row, str) or not row or not isinstance(name, str) or not name:
            raise ValueError(f"{where} needs a 'row' and a 'case'")
        where = f"case {number} ({row} {name})"
        if name in numbers:
            raise ValueError(f"{where}: case {numbers[name]} has the same 'case', its id")
        numbers[name] = number
        instruction = INSTRUCTIONS.get(entry.get("instruction"))  # pyright: ignore[reportArgumentType]
        if instruction is None:
            raise ValueError(f"{where}: 'instruction' is not one of {', '.join(INSTRUCTIONS)}")
        mode = entry.get("mode")
        if instruction.modes and mode not in instruction.modes:
            raise ValueError(f"{where}: 'mode' is not one of {', '.join(instruction.modes)}")
        if not instruction.modes and mode is not None:
            raise ValueError(f"{where}: {instruction.title} has no modes")
        fields = entry.get("fields")
        if (
            not isinstance(fields, dict)
            or not fields
            or not all(isinstance(v, str) for v in fields.values())
        ):
            raise ValueError(f"{where}: 'fields' must name at least one field, each with text")
        unknown = set(fields) - set(instruction.fields)
        if unknown:
            raise ValueError(
                f"{where}: {instruction.title} has no field {', '.join(sorted(unknown))} "
                f"(its fields: {', '.join(instruction.fields)})"
            )
        choices = entry.get("choices", {})
        if not isinstance(choices, dict) or not all(
            isinstance(v, str) and v for v in choices.values()
        ):
            raise ValueError(f"{where}: 'choices' must name lists, each with an item")
        unknown = set(choices) - set(instruction.lists)
        if unknown:
            raise ValueError(
                f"{where}: {instruction.title} has no list {', '.join(sorted(unknown))}"
                + (f" (its lists: {', '.join(instruction.lists)})" if instruction.lists else "")
            )
        options = entry.get("options", {})
        if not isinstance(options, dict) or not all(
            isinstance(k, str) and k and type(v) is int and v in (0, 1) for k, v in options.items()
        ):
            raise ValueError(
                f"{where}: 'options' must name option buttons, each with 1 (checked) or 0"
            )
        if options and not instruction.options:
            raise ValueError(f"{where}: {instruction.title} has no option buttons")
        unknown = {k for k in options if _is_id(k) and int(k) not in instruction.options}
        if unknown:
            raise ValueError(
                f"{where}: {instruction.title} has no option button {', '.join(sorted(unknown))} "
                f"(its option buttons: {', '.join(map(str, instruction.options))})"
            )
        cases.append(
            Case(
                row,
                name,
                entry["instruction"],
                mode,
                dict(fields),
                dict(choices),
                dict(options),
            )
        )
    nicknames = data.get("nicknames", [])
    if not isinstance(nicknames, list) or not all(isinstance(a, str) for a in nicknames):
        raise ValueError("'nicknames' must be a list of addresses")
    for address in nicknames:
        parse_address(address)  # ValueError names the address
    return cases, nicknames


# ---------------------------------------------------------------------------
# ``import``: a nickname CSV, its rows, and CLICK's error list
# ---------------------------------------------------------------------------

# A line of an error list entry naming the file's line: "Line 14 : Address = DS25, ..."
_IMPORT_LINE = re.compile(r"^Line (\d+) : (.*)$", re.DOTALL)
_IMPORT_CAUSE = "Cause : "


def split_rows(data: bytes) -> tuple[bytes, list[tuple[int, bytes]]]:
    """Return the first line of the CSV *data* (its header) and each line after it with its number.

    CLICK reads a nickname CSV line by line. A line break inside a quoted cell ends the row
    there, and the error list names the rest as the next line (live probe 3). So each row
    is one line, with its line end. Lines are numbered from 1 for the header, as CLICK's
    error list numbers them. A line that is only a line end is no row. The function keeps the
    bytes as they are and splits after each line feed byte. That works for an ASCII-compatible
    encoding (UTF-8, Latin-1, CP1252) and not for UTF-16. A file with CR line ends only is one
    line: a header and no rows.
    """
    *ended, last = data.split(b"\n")
    lines = [line + b"\n" for line in ended] + ([last] if last else [])
    if not lines:
        return b"", []
    header, *rows = lines
    return header, [(number, row) for number, row in enumerate(rows, 2) if row.strip(b"\r\n")]


def parse_import_errors(text: str) -> list[dict[str, Any]]:
    """Return the entries of CLICK's Import Error List: its error, the line it names, the cause.

    Live probe 2 (2026-11-15) read entries such as "Error : Unable to import to
    Database.", "Line 19 : <the line as in the file>", "Cause : The memory address is not
    supported by this CLICK CPU module.", each followed by an empty line. The function keeps
    the line's text exactly, because an edge space or a tab is the point. An empty line is no
    part of an entry. A line in no known form goes under ``other``. Lines split at CR LF or
    LF only. A vertical tab or form feed is text.
    """
    entries: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n", text):
        lines = [part for part in re.split(r"\r?\n", block) if part]
        if not lines:
            continue
        first, *rest = lines
        entry: dict[str, Any] = {"error": first, "line": None, "text": None, "cause": None}
        for part in rest:
            match = _IMPORT_LINE.match(part)
            if match and entry["line"] is None:
                entry.update(line=int(match.group(1)), text=match.group(2))
            elif part.startswith(_IMPORT_CAUSE) and entry["cause"] is None:
                entry["cause"] = part.removeprefix(_IMPORT_CAUSE)
            else:
                entry.setdefault("other", []).append(part)
        entries.append(entry)
    return entries


def _file_state(path: Path) -> tuple[int, int] | None:
    """Return *path*'s size and modification time, or None if it cannot be read."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _end_rung(text: str) -> int | None:
    """Return the rung that a Syntax Check's text names for the missing END (C0201), or None."""
    match = _END_RUNG.search(text)
    return int(match.group(1)) if match else None


def _unnamed(check: dict[str, Any]) -> str:
    """Return a Syntax Check's text with its project's name replaced by ``<project>``.

    The name is ``check_syntax``'s ``project``. Checks of projects saved under other names
    then compare equal.
    """
    name = re.escape(check["project"])
    return re.sub(rf"(?<!\w){name}(?!\w)", "<project>", check["text"])


def _is_main(window: Window) -> bool:
    return (
        window.owner == 0
        and window.cls.startswith("Afx:")
        and bool(_MAIN_TITLE.match(window.title))
    )


def _describe(window: Window) -> str:
    return f"{window.cls!r} {window.title!r} (hwnd {window.hwnd}, owner {window.owner})"


def classify(
    windows: list[Window], expected: list[Expect], *, main: int | None = None
) -> tuple[dict[str, Window], list[Window]]:
    """Match *windows* to the main frame and *expected*.

    Return (name -> window, windows matching none). Each expectation matches at most one
    window. That window must be owned by the window that its ``owner`` names. So a second
    Login, or a Login owned by the wrong dialog, is unexpected. With *main*, the window with
    that hwnd is the main frame whatever its title. CLICK titles it bare while it closes or
    reads a project.
    """
    found: dict[str, Window] = {}
    rest = list(windows)
    mains = [w for w in rest if _is_main(w)] or [w for w in rest if w.hwnd == main]
    if mains:
        found[MAIN] = mains[0]
        rest.remove(mains[0])
    progress = True
    while progress:
        progress = False
        for expect in expected:
            if expect.name in found or expect.owner not in found:
                continue
            owner = found[expect.owner].hwnd
            for window in rest:
                if (
                    window.cls == expect.cls
                    and window.title == expect.title
                    and window.owner == owner
                ):
                    found[expect.name] = window
                    rest.remove(window)
                    progress = True
                    break
    return found, rest


def click_error(window: Window, controls: list[Control]) -> tuple[str, str] | None:
    """Return the (code, message) of *window* if it is a CLICK error box, else None.

    Live run 3 (2026-11-15) met one during connect. It was a ``#32770`` titled "CLICK
    Programming Software" with an OK button (id 2) and a Static. The Static read "PTC-013"
    and, on the next line, "Timeout on attempting to connect to PLC.".
    """
    if window.cls != "#32770":
        return None
    for control in controls:
        match = _CLICK_ERROR.match(control.text) if control.cls == "Static" else None
        if match:
            return match.group(1), " ".join(match.group(2).split())
    return None


def _child(
    controls: list[Control], *, cls: str, id: int, text: str | None = None
) -> Control | None:
    for control in controls:
        if control.cls == cls and control.id == id and (text is None or control.text == text):
            return control
    return None


# The keys ``picker --key`` takes by name
_VIRTUAL_KEYS = {
    "RETURN": 0x0D,
    "ESCAPE": 0x1B,
    "TAB": 0x09,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "F2": 0x71,
}


def _labelled(controls: list[Control], cls: str, text: str) -> Control | None:
    """Return the one *cls* control that reads *text*, or None if there is none or more than one.

    A Delphi form's controls have no ids of their own: each reads its hwnd.
    """
    found = [c for c in controls if c.cls == cls and c.text == text]
    return found[0] if len(found) == 1 else None


def _require(control: Control | None, what: str) -> Control:
    if control is None:
        raise Aborted(f"{what} not found")
    return control


@dataclass(frozen=True)
class StatusBar:
    """The panes of the main window's status bar.

    Live run 2 (2026-11-15) read these panes offline: "", "Bit", "Integer", "Integer(2
    words)", "Floating point", "Hex", "Text", "Ascii", "-----", "0000/8000" (program steps),
    "No select CPU", "1:1:A" (cursor), five empty panes, "NUM", "". Live run 4 read these
    panes while connected: "RUN" in place of "-----", "C2-03CPU", and
    "192.168.1.241(Conformance)" three panes after the cursor. Disconnected again, it read
    "Offline" and "No select CPU".
    """

    panes: tuple[str, ...]

    @property
    def rung(self) -> int | None:
        """Return the rung in the cursor pane ("2:1:A" is rung 2)."""
        match = _CURSOR.search("  ".join(self.panes))
        return int(match.group(1)) if match else None

    @property
    def cursor(self) -> str | None:
        """Return the cursor pane ("1:1:AF"), or None."""
        match = _CURSOR.search("  ".join(self.panes))
        return match.group(0) if match else None

    @property
    def steps(self) -> int | None:
        """Return the program steps used ("0004/8000" is 4)."""
        match = _STEPS.search("  ".join(self.panes))
        return int(match.group(1)) if match else None

    @property
    def plc(self) -> str | None:
        """Return the pane that names the PLC connected to ("192.168.1.241(Conformance)")."""
        return next((p.strip() for p in self.panes if _PLC_PANE.match(p.strip())), None)

    @property
    def plc_name(self) -> str | None:
        """Return the PLC's name from the ``plc`` pane ("Conformance")."""
        plc = self.plc
        return plc[plc.index("(") + 1 : -1] if plc else None

    def shows_paste(self, before: StatusBar, rungs: int) -> bool:
        """Return whether this reading, compared with *before* the paste, shows *rungs* pasted.

        A paste moves the cursor down by the rungs pasted, or raises the program steps. Live
        run 4 (2026-11-15) saw the steps stay at 0000/8000 after a paste of a rung with a
        contact and a coil. So the cursor is what shows a paste. A rise of the steps counts
        too.
        """
        if before.rung is not None and self.rung == before.rung + rungs:
            return True
        return before.steps is not None and self.steps is not None and self.steps > before.steps


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON: {value!r}")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    command: str  # "paste", "record", "try", "import", "read-data", "reopen" or "picker"
    out: Path
    # The rest are keyword-only. A field added among them then cannot shift a caller's
    # arguments
    _: KW_ONLY
    csv: Path | None = None  # paste's ladder CSV, import's nickname CSV
    each_row: bool = False  # import: each row on its own too
    cases: Path | None = None  # try's CASES.json
    keep: bool = False  # try: save each accepted case's project and decode it
    wire: bool = False  # try: wire each case into a rung of its own (contact, coil)
    resume: Path | None = None  # try: the run whose answers to carry (its DIR)
    stop_after: int | None = None  # try: stop cleanly once this many cases were tried
    ini_add: str | None = None  # reopen: lines added to the end of the project's Project.ini
    keys: tuple[str, ...] = ()  # picker: keys sent to the Address Picker's grid (probe)
    ok: bool = False  # picker: close the Address Picker by OK (else by WM_CLOSE)
    exe: Path = DEFAULT_EXE
    password: str = DEFAULT_PASSWORD
    user_type: str = DEFAULT_USER_TYPE
    timeout: float = DEFAULT_TIMEOUT
    paste_timeout: float = DEFAULT_PASTE_TIMEOUT
    plc: str | None = None  # The PLC's name the status bar must show once connected
    poll: float = POLL_INTERVAL
    record: bool = False


def _prepare(csv: Path, mdb: Path | None):
    """Encode *csv* for the clipboard. With *mdb*, first add its addresses to that SC_.mdb."""
    from clicknick.ladder.program import prepare_csv_load

    return prepare_csv_load(csv, click_v4=True, mdb_path=mdb)


def _decode(click_dir: Path, csv_dir: Path):
    from clicknick.ladder.program import program_save

    return program_save(click_dir, csv_dir)


class ClipCsv(NamedTuple):
    """What ``_decode_clip`` made of a clipboard.

    ``written`` says whether it wrote the CSV. ``unreadable`` names what in the clipboard
    laddercodec cannot read or write, or is None when nothing.
    """

    written: bool
    unreadable: str | None


def _decode_clip(clip: Path, csv: Path) -> ClipCsv:
    """Decode the CLICK clipboard data in *clip* into the ladder CSV *csv*.

    The function decodes with laddercodec's ``decode`` and writes with its ``write_csv``,
    the way ``program_save`` writes main.csv. ``decode`` raises on data it cannot decode at
    all, and so does this function. Data that it decodes but cannot read is listed in
    ``unreadable``. Each part is labelled with who found it and how it counts rungs.
    ClickNick names an instruction that laddercodec cannot read before the CSV is written,
    as ``program_save`` names it (``ClickNick, rungs from 1``: ``_unreadable_instructions``).
    laddercodec names each warning that it raises while decoding or writing, if the warning's
    category is one that laddercodec defines, in its own words (``laddercodec <warning>,
    rungs from 0``). A plain ``UserWarning`` from laddercodec (such as the writer's lost
    trailing blank rows) is not listed. It is raised again as it would have been. A
    laddercodec that writes a marker rung for a rung it cannot read warns. One that cannot
    write the rung raises ``WriterError``. Then no CSV is kept and the list ends with why
    (``laddercodec: the CSV cannot be written``).
    """
    from laddercodec import decode, write_csv
    from laddercodec.csv.writer import WriterError

    from clicknick.ladder.program import _unreadable_detail, _unreadable_instructions

    found: list[str] = []
    refused: str | None = None  # Why write_csv refused, if it did
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        decoded = decode(clip.read_bytes())
        rungs = decoded if isinstance(decoded, list) else [decoded]
        found.extend(
            f"ClickNick, rungs from 1: rung {number}, {name}: {_unreadable_detail(name)}"
            for number, rung in enumerate(rungs, start=1)
            for name in _unreadable_instructions(rung)
        )
        try:
            write_csv(csv, rungs)
        except WriterError as exc:
            csv.unlink(missing_ok=True)  # Remove what was written before it raised
            refused = f"laddercodec: the CSV cannot be written: {type(exc).__name__}: {exc}"
    for warning in caught:
        category = warning.category
        if category.__module__.split(".")[0] == "laddercodec":
            found.append(f"laddercodec {category.__name__}, rungs from 0: {warning.message}")
        else:  # Not about the clipboard: show it as it would have been shown
            warnings.warn_explicit(warning.message, category, warning.filename, warning.lineno)
    if refused is not None:
        found.append(refused)
    return ClipCsv(refused is None, "; ".join(found) or None)


def _read_nicknames(mdb: Path, addresses: list[str]) -> dict[str, str | None]:
    """Return the nickname of each of *addresses* in the SC_.mdb at *mdb*, or None if no row."""
    from pyclickplc.addresses import get_addr_key, parse_address

    from clicknick.utils.mdb_operations import MdbConnection, load_all_addresses

    with MdbConnection(str(mdb)) as connection:
        rows = load_all_addresses(connection)
    found: dict[str, str | None] = {}
    for address in addresses:
        row = rows.get(get_addr_key(*parse_address(address)))
        found[address] = None if row is None else row.nickname
    return found


_ROW_COLUMNS = ("DataType", "Nickname", "InitialValue", "Retentive", "Comment", "Use")


def _rows_by_address(rows: Iterable[Sequence[Any]]) -> dict[str, dict[str, Any]]:
    """Return the address table's *rows* keyed by their address as CLICK shows it ("DS31").

    Each of the *rows* holds ``AddrKey``, ``MemoryType``, ``Address``, then ``_ROW_COLUMNS``.
    The result keeps the order given. Each row maps every column to its value as stored,
    including the first three. Two rows for one address raise RuntimeError, because a reading
    by address would hide one of them.
    """
    from pyclickplc.addresses import format_address_display

    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        key, memory_type, address, *values = row
        shown = format_address_display(str(memory_type).strip(), int(address))
        if shown in found:
            raise RuntimeError(
                f"two rows for {shown}: AddrKey {found[shown]['AddrKey']!r} and {key!r}"
            )
        found[shown] = {
            "AddrKey": key,
            "MemoryType": memory_type,
            "Address": address,
            **dict(zip(_ROW_COLUMNS, values, strict=True)),
        }
    return found


def _read_rows(mdb: Path) -> dict[str, dict[str, Any]]:
    """Return every row of the address table in the SC_.mdb at *mdb*, as stored, by address.

    It reads through Access ODBC only, so a NULL stays None and a text keeps every
    character. See ``_rows_by_address`` for what each row holds.
    """
    import pyodbc

    from clicknick.utils.mdb_shared import create_access_connection

    connection = create_access_connection(mdb)
    if not isinstance(connection, pyodbc.Connection):
        connection.close()
        raise RuntimeError("reading SC_.mdb as stored needs an Access ODBC driver")
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT AddrKey, MemoryType, Address, {', '.join(_ROW_COLUMNS)} "
            "FROM address ORDER BY AddrKey"
        )
        rows = cursor.fetchall()
    finally:
        connection.close()
    return _rows_by_address(rows)


def _reads_stored_tags() -> bool:
    """Return whether this laddercodec has the private walk that ``_read_stored`` uses.

    laddercodec 0.4.0 has none. It came after, in ac7d910.
    """
    module = importlib.import_module("laddercodec.decode_program")
    return all(hasattr(module, name) for name in ("_parse_header", "_walk_until_framing_error"))


def _read_stored(scr: Path) -> dict[str, Any]:
    """Return the instructions in the Scr*.tmp at *scr* with the tags CLICK stored for them.

    Each rung is a list of its instructions. Each instruction has ``row`` (from 0),
    ``column``, ``class``, ``type``, every scalar tag (``tags``, by its id in hex; a flag
    reads ``""``) and the indexed tags that are not empty (``indexed``). ``error`` is
    laddercodec's framing error, or None. This function uses laddercodec's own walk of the
    file. The walk is private, but no public reader keeps the tags as stored. If laddercodec
    changes the walk, this function fails. The run itself does not fail.
    """
    from laddercodec.decode_program import _parse_header, _walk_until_framing_error

    data = scr.read_bytes()
    header = _parse_header(data)
    records, error = _walk_until_framing_error(data, header)
    rungs = []
    for record in records:
        rung = []
        for row, column, name, type_code, tags, _, numbers, texts, _ in record.instructions:
            indexed: dict[str, dict[str, object]] = {}
            for tag, entries in [*numbers.items(), *texts.items()]:
                filled = {str(index): value for index, value in entries.items() if value}
                if filled:
                    indexed[f"0x{tag:04X}"] = filled
            rung.append(
                {
                    "row": row,
                    "column": column,
                    "class": name,
                    "type": type_code,
                    "tags": {f"0x{tag:04X}": value for tag, value in tags.items()},
                    "indexed": indexed,
                }
            )
        rungs.append(rung)
    return {"program": header.name, "prog_idx": header.prog_idx, "rungs": rungs, "error": error}


class Run:
    """One run of the runner against one CLICK it starts."""

    def __init__(
        self,
        desktop: Desktop,
        settings: Settings,
        *,
        prepare: Callable[[Path, Path | None], Any] = _prepare,
        decode: Callable[[Path, Path], Any] = _decode,
        decode_clip: Callable[[Path, Path], ClipCsv] = _decode_clip,
        read_nicknames: Callable[[Path, list[str]], dict[str, str | None]] = _read_nicknames,
        read_rows: Callable[[Path], dict[str, dict[str, Any]]] = _read_rows,
        read_stored: Callable[[Path], dict[str, Any]] = _read_stored,
        stderr: Any = None,
    ) -> None:
        self.desktop = desktop
        self.s = settings
        self.prepare = prepare
        self.decode = decode
        self.decode_clip = decode_clip
        self.read_nicknames = read_nicknames
        self.read_rows = read_rows
        self.read_stored = read_stored
        self.cases: list[Case] = []
        self.nickname_addresses: list[str] = []
        # try --resume: the carried entries by case id, then the earlier stops and the last
        # entries of the cases that are tried again
        self.carried: dict[str, dict[str, Any]] = {}
        self.earlier_stops: dict[str, list[dict[str, Any]]] = {}
        self.retried: dict[str, dict[str, Any]] = {}
        # import's CSV: its header and each row with the line it starts on
        self.header = b""
        self.rows: list[tuple[int, bytes]] = []
        self.stderr = sys.stderr if stderr is None else stderr
        self.started = time.monotonic()
        self.pid: int | None = None
        self.main: int | None = None
        self.connected = False
        self.log_path: Path | None = None
        self._dump_count = 0
        # Windows open before the main frame, and those of them still open
        self._tolerated: set[int] = set()
        self._tooltips: set[int] = set()
        self._status_errors: set[str] = set()
        # CLICK's Scr*.tmp files before the paste (a new project has none)
        self._scr_before: tuple[tuple[str, int, int], ...] = ()
        self.starting: list[Window] = []
        self.result: dict[str, Any] = {
            "command": settings.command,
            "status": None,
            "step": None,
            "reason": None,
            "csv": settings.csv,
            "out": settings.out,
            "started": datetime.now(UTC).isoformat(timespec="seconds"),
            "elapsed": None,
            "timings": {},
            "syntax_check": None,
            "rungs": None,
            "plc": None,
            "click_error": None,
            "cleanup_click_error": None,
            "status_bar": {},
            "files": {},
            "click": {"exe": settings.exe, "pid": None, "main_hwnd": None, "closed": None},
        }
        if settings.command == "try":
            self.result.update(
                cases_file=settings.cases,
                keep=settings.keep,
                wire=settings.wire,
                resumed_from=settings.resume,
                carried=0,
                stop_after=settings.stop_after,
                stopped_after=None,
                stopped_at=None,
                left=None,
                nicknames=None,
                baseline_syntax_check=None,
                cases=[],
            )
        if settings.command == "import":
            self.result.update(import_mode=IMPORT_MODE, each_row=settings.each_row, imports=[])
        if settings.command == "reopen":
            self.result.update(ini_add=settings.ini_add, points={})
        if settings.command == "read-data":
            self.result.update(reading_seen=False)
        if settings.command == "picker":
            self.result.update(mdb_copies={}, keys=[])

    # -- logging, timing, dumps ---------------------------------------------

    def log(self, message: str) -> None:
        line = f"{time.monotonic() - self.started:8.2f}  {message}"
        if self.log_path is not None:
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        print(line, file=self.stderr, flush=True)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        self.result["step"] = name
        self.log(f"step {name}")
        began = time.monotonic()
        yield
        self.result["timings"][name] = round(time.monotonic() - began, 3)

    def dump(self, folder: Path, label: str) -> None:
        """Write every window of CLICK as JSON (with its controls) and PNG into *folder*.

        The PNG is a picture of the screen where the window is, so windows over it are in it.
        The result lists the files under the folder's name.
        """
        assert self.pid is not None
        folder.mkdir(parents=True, exist_ok=True)
        self._dump_count += 1
        written: list[Path] = self.result["files"].setdefault(folder.name, [])
        count = len(written)
        for window in self.desktop.windows(self.pid):
            # Skip a window that closed since it was listed (CLICK closing)
            if not self.desktop.exists(window.hwnd):
                continue
            # Listing sends CLICK no message, and neither does the screenshot. A window that
            # does not answer is drawn as Windows' ghost, so it gets no edit text and no PNG
            answers = self.desktop.idle(window.hwnd, IDLE_TIMEOUT)
            if not answers:
                self.log(f"{window.hwnd} does not answer: its dump has no edit text and no PNG")
            controls = []
            for control in self.desktop.controls(window.hwnd):
                row = asdict(control)
                if control.cls in ("Edit", "TEdit") and answers:
                    row["edit_text"] = self.desktop.read_text(control.hwnd)
                controls.append(row)
            base = folder / f"{self._dump_count:02d}-{label}-{window.hwnd}"
            info = {**asdict(window), "controls": controls}
            base.with_suffix(".json").write_text(json.dumps(info, indent=1), encoding="utf-8")
            written.append(base.with_suffix(".json"))
            if not answers:
                continue
            try:
                if self.desktop.screenshot(window.hwnd, base.with_suffix(".png")):
                    written.append(base.with_suffix(".png"))
            except Exception as exc:  # A screenshot is optional
                if self.desktop.exists(window.hwnd):
                    self.log(f"no screenshot of {window.hwnd}: {exc}")
        self.log(f"dumped {len(written) - count} file(s) as {label} into {folder}")

    def record(self, label: str) -> None:
        if self.s.record or self.s.command == "record":
            self.dump(self.s.out / "record", label)

    # -- waiting --------------------------------------------------------------

    def wait[T](
        self,
        what: str,
        expected: list[Expect],
        until: Callable[[dict[str, Window]], T | None],
        *,
        exits: bool = False,
        unloading: bool = False,
        on_timeout: Callable[[], str] | None = None,
        timeout: float | None = None,
        answering: int | None = None,
    ) -> T:
        """Poll CLICK's windows until *until* returns something other than None or False.

        Any window that is neither the main frame nor one of *expected* aborts the run. The
        exception is a window that was open before the main frame first appeared (CLICK
        starting up, a splash screen), until the launch step ends. CLICK exiting aborts too,
        unless *exits* is set. Then the wait ends when CLICK has exited. With *unloading*, the
        main window is expected whatever its title, because CLICK titles it bare while it
        closes or reads a project. A CLICK error box aborts at once (``check_error_boxes``),
        except one owned by the window that *answering* names (an instruction dialog whose OK
        was pressed). The wait gives up after *timeout* seconds (default
        ``Settings.timeout``). The reason starts with *on_timeout*'s text when it is given.
        Every ``STATUS_EVERY`` seconds it logs the status bar, or that CLICK does not answer.
        """
        assert self.pid is not None
        limit = self.s.timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        next_status = time.monotonic() + STATUS_EVERY
        while True:
            if not self.desktop.alive(self.pid):
                if exits:
                    return True  # pyright: ignore[reportReturnType]
                raise Aborted(f"CLICK exited while waiting for {what}")
            windows = self.desktop.windows(self.pid)
            self.check_error_boxes(
                [w for w in windows if answering is None or w.owner != answering]
            )
            found, unexpected = classify(windows, expected, main=self.main if unloading else None)
            unexpected = self._without_tooltips(unexpected)
            if self.main is None and MAIN not in found:
                for window in unexpected:
                    if window.hwnd not in self._tolerated:
                        self._tolerated.add(window.hwnd)
                        self.log(f"before the main window: {_describe(window)}")
            elif self.main is None:
                self.main = found[MAIN].hwnd
                self.result["click"]["main_hwnd"] = self.main
                self.log(f"main window {self.main}: {found[MAIN].title!r}")
            elif MAIN in found and found[MAIN].hwnd != self.main:
                raise Aborted(f"a second main window: {_describe(found[MAIN])}")
            self.starting = [w for w in unexpected if w.hwnd in self._tolerated]
            if self.result["step"] == "launch":
                unexpected = [w for w in unexpected if w.hwnd not in self._tolerated]
            if unexpected:
                listed = "; ".join(_describe(w) for w in unexpected)
                raise Aborted(f"unexpected window while waiting for {what}: {listed}")
            value = until(found)
            if value is not None and value is not False:
                return value
            now = time.monotonic()
            if now > deadline:
                reason = f"timed out after {limit:g} s waiting for {what}"
                raise Aborted(f"{on_timeout()}; {reason}" if on_timeout else reason)
            if now >= next_status and self.main is not None:
                next_status = now + STATUS_EVERY
                if self.desktop.idle(self.main, IDLE_TIMEOUT):
                    self.status_bar(None)
                else:
                    self.log(f"CLICK does not answer; still waiting for {what}")
            time.sleep(self.s.poll)

    def check_error_boxes(self, windows: list[Window]) -> None:
        """Raise ``ClickErrorBox`` for a CLICK error box among *windows*.

        Nothing is pressed in it. The cleanup that follows leaves it open and ends CLICK. It
        does not disconnect, because a dialog is open.
        """
        for window in windows:
            if window.cls != "#32770":
                continue
            error = click_error(window, self.desktop.controls(window.hwnd))
            if error is not None:
                raise ClickErrorBox(*error)

    def _without_tooltips(self, windows: list[Window]) -> list[Window]:
        """Return *windows* without the tooltips, and log each tooltip when first seen."""
        for window in windows:
            if window.cls == TOOLTIP_CLASS and window.hwnd not in self._tooltips:
                self._tooltips.add(window.hwnd)
                self.log(f"a tooltip, let be: {_describe(window)}")
        return [w for w in windows if w.cls != TOOLTIP_CLASS]

    def only_main(self, found: dict[str, Window]) -> bool:
        """Return true when the main frame is alone, enabled and answering messages."""
        main = found.get(MAIN)
        return (
            main is not None
            and len(found) == 1
            and main.enabled
            and self.desktop.idle(main.hwnd, IDLE_TIMEOUT)
        )

    def controls(self, window: Window) -> list[Control]:
        return self.desktop.controls(window.hwnd)

    def press(self, window: Window, button: Control) -> None:
        """Post BM_CLICK to *button*, a button found among *window*'s controls."""
        if button.cls not in ("Button", "TButton", "TRadioButton") or button.hwnd not in {
            c.hwnd for c in self.controls(window)
        }:
            raise Aborted(f"{button.cls} {button.hwnd} is not a button of {_describe(window)}")
        self.log(f"press {button.text or button.cls}, id {button.id}, in {window.title!r}")
        self.desktop.press(button.hwnd)

    def send_press(self, window: Window, button: Control) -> bool:
        """Do what ``press`` does, but send BM_CLICK instead of posting it.

        Return True once the button has handled the click (``Desktop.send_press``).
        """
        if button.cls not in ("Button", "TButton") or button.hwnd not in {
            c.hwnd for c in self.controls(window)
        }:
            raise Aborted(f"{button.cls} {button.hwnd} is not a button of {_describe(window)}")
        self.log(f"press {button.text or button.cls} (sent), id {button.id}, in {window.title!r}")
        return self.desktop.send_press(button.hwnd)

    def command(self, command_id: int) -> None:
        assert self.main is not None
        name = self.desktop.command(self.main, command_id)
        self.log(f"command {name} ({command_id})")

    def read_status_bar(self) -> StatusBar | None:
        """Return the main window's status bar, read by SB_GETTEXT, or None if it cannot be read.

        CLICK's main window has two children with the status bar's id: an MFC bar
        (``Afx:StatusBar...``) and a common control. Live run 2 (2026-11-15) read the
        common control by SB_GETTEXT. The runner sends the MFC bar nothing. Call this method
        only while CLICK answers, because reading sends it messages.
        """
        assert self.main is not None
        for bar in self.desktop.controls(self.main):
            if (bar.parent, bar.id, bar.cls) != (self.main, STATUS_BAR_ID, "msctls_statusbar32"):
                continue
            try:
                panes = self.desktop.status_bar(bar.hwnd)
            except OSError as exc:
                if str(exc) not in self._status_errors:
                    self._status_errors.add(str(exc))
                    self.log(f"status bar: {exc}")
                return None
            return None if panes is None else StatusBar(tuple(panes))
        return None

    def status_bar(self, label: str | None) -> StatusBar | None:
        """Read and log the status bar, and keep it in the result under *label* if given."""
        status = self.read_status_bar()
        if status is None:
            self.log("status bar: cannot be read")
        else:
            self.log(f"status bar: {' | '.join(status.panes)}")
        if label is not None:
            self.result["status_bar"][label] = None if status is None else list(status.panes)
        return status

    # -- the steps ------------------------------------------------------------

    def refuse_checks(self) -> None:
        """Refuse to start unless the desktop is free, CLICK is installed and the CSV encodes."""
        name = self.desktop.input_desktop()
        if name != "Default":
            raise Refused(
                "the input desktop is locked or cannot be opened"
                if name is None
                else f"the input desktop is {name!r}, not 'Default' (is the screen locked?)"
            )
        pids = self.desktop.click_processes()
        if pids:
            raise Refused(f"CLICK is already running (CLICK.exe pid {', '.join(map(str, pids))})")
        hwnds = self.desktop.click_windows()
        if hwnds:
            raise Refused(f"a CLICK window is already open (hwnd {', '.join(map(str, hwnds))})")
        if not self.s.exe.is_file():
            raise Refused(f"CLICK not found at {self.s.exe}")
        if self.s.command == "paste":
            assert self.s.csv is not None
            if not self.s.csv.is_file():
                raise Refused(f"no CSV at {self.s.csv}")
            try:
                self.prepare(self.s.csv, None)
            except Exception as exc:
                raise Refused(f"cannot encode {self.s.csv}: {exc}") from exc
        if self.s.command == "try":
            assert self.s.cases is not None
            if not self.s.cases.is_file():
                raise Refused(f"no cases file at {self.s.cases}")
            try:
                self.cases, self.nickname_addresses = load_cases(self.s.cases)
            except Exception as exc:
                raise Refused(f"cannot read the cases in {self.s.cases}: {exc}") from exc
            if not self.cases:
                raise Refused(f"{self.s.cases} lists no cases")
            contacts = {
                INSTRUCTIONS[c.instruction].title
                for c in self.cases
                if INSTRUCTIONS[c.instruction].kind == CONTACT
            }
            if contacts and not self.s.wire:
                # Placed at A, it leaves the cursor at B, where Delete removes nothing
                raise Refused(f"{', '.join(sorted(contacts))} is a contact: try it with --wire")
            if self.s.resume is not None:
                if self.s.resume.resolve() == self.s.out.resolve():
                    raise Refused("--resume names the run's own folder")
                self.load_resume()
            if self.s.keep and self.read_stored is _read_stored and not _reads_stored_tags():
                raise Refused(
                    "try --keep needs laddercodec newer than 0.4.0 (_walk_until_framing_error)"
                )
        if self.s.command == "import":
            assert self.s.csv is not None
            if not self.s.csv.is_file():
                raise Refused(f"no CSV at {self.s.csv}")
            try:
                self.header, self.rows = split_rows(self.s.csv.read_bytes())
            except OSError as exc:
                raise Refused(f"cannot read {self.s.csv}: {exc}") from exc
            if self.s.each_row and not self.rows:
                raise Refused(f"{self.s.csv} has no rows after its header to import one by one")
        if self.s.ini_add is not None and not self.s.ini_add.isascii():
            raise Refused(f"--ini-add is not ASCII: {self.s.ini_add!r}")
        for token in self.s.keys:
            if not token.startswith(("chars:", "text:", "find:")) and token not in _VIRTUAL_KEYS:
                raise Refused(f"--key {token!r} is not a key the runner knows")

    def launch(self) -> None:
        with self.step("launch"):
            self.pid = self.desktop.launch(self.s.exe)
            self.result["click"]["pid"] = self.pid
            self.log(f"started {self.s.exe}, pid {self.pid}")
            found = self.wait(
                "the main window with the What's New guide or Startup, "
                "and any window open before it closed",
                [GUIDE, STARTUP],
                lambda f: (
                    f
                    if MAIN in f and (GUIDE.name in f or STARTUP.name in f) and not self.starting
                    else None
                ),
            )
            self.record("launched")
            if GUIDE.name in found:
                self.log("close the What's New guide")
                self.desktop.close(found[GUIDE.name].hwnd)
                self.wait(
                    "Startup after the guide",
                    [GUIDE, STARTUP],
                    lambda f: STARTUP.name in f and GUIDE.name not in f,
                )
                self.record("guide_closed")

    def connect(self) -> None:
        with self.step("startup"):
            startup = self.wait("Startup", [STARTUP], lambda f: f.get(STARTUP.name))
            group = self.wait(
                "the 'Select an Operation' group",
                [STARTUP],
                lambda f: next(
                    (
                        c
                        for c in self.controls(startup)
                        if c.cls == "TGroupBox" and c.text == "Select an Operation"
                    ),
                    None,
                ),
            )
            buttons = [
                c
                for c in self.controls(startup)
                if c.parent == group.hwnd and c.cls == "TButton" and c.text == ""
            ]
            if len(buttons) != 3:
                raise Aborted(
                    f"Startup has {len(buttons)} textless operation button(s), expected 3"
                )
            self.press(startup, max(buttons, key=lambda c: c.rect[0]))  # Connect to PLC

        with self.step("connect"):
            connect = self.wait(
                "Connect to CLICK PLC", [STARTUP, CONNECT], lambda f: f.get(CONNECT.name)
            )
            plc_list = _require(
                self.wait(
                    "the PLC list",
                    [STARTUP, CONNECT],
                    lambda f: _child(self.controls(connect), cls="SysListView32", id=20061),
                ),
                "the PLC list",
            )
            last: list[int | None] = [None]
            since = [time.monotonic()]

            def lists(items: int | None) -> str:
                if items is None:
                    return "the Connect dialog's PLC list does not answer"
                return f"the Connect dialog lists {items} PLC(s)"

            def listed(_: dict[str, Window]) -> bool:
                # Done when the list has one row, unchanged for PLC_SETTLE seconds, and
                # Connect is enabled. Two or more rows stop the run. The list is owner-drawn.
                # CLICK paints its own highlight and connects to its current row, and the
                # list reports no selection (live run 2). So the runner selects nothing.
                items = self.desktop.list_view_items(plc_list.hwnd)
                if items != last[0]:
                    last[0], since[0] = items, time.monotonic()
                    return False
                if items is None or time.monotonic() - since[0] < PLC_SETTLE:
                    return False
                if items >= 2:
                    raise Aborted(f"{lists(items)}; expected exactly 1")
                button = _child(self.controls(connect), cls="Button", id=1, text="Connect")
                return items == 1 and button is not None and button.enabled

            self.wait(
                "one PLC in the list",
                [STARTUP, CONNECT],
                listed,
                on_timeout=lambda: lists(last[0]),
            )
            self.log(f"PLC list: 1 row for {PLC_SETTLE:g} s")
            self.record("connect_dialog")
            controls = self.controls(connect)
            same_lan = _require(
                _child(controls, cls="Button", id=20059), "'In the same LAN' (20059)"
            )
            if not (
                same_lan.text.startswith("In the same LAN")
                and same_lan.visible
                and self.desktop.button_checked(same_lan.hwnd) == 1
            ):
                raise Aborted(
                    f"the Connect dialog does not scan the same LAN: {same_lan.text!r} "
                    f"(visible {same_lan.visible}) is not checked"
                )
            button = _require(
                _child(controls, cls="Button", id=1, text="Connect"), "the Connect button"
            )
            items = self.desktop.list_view_items(plc_list.hwnd)
            if items != 1:
                raise Aborted(f"{lists(items)} as Connect is about to be pressed; expected 1")
            self.press(connect, button)
            found = self.wait(
                "Login or the read-project question",
                [STARTUP, CONNECT, LOGIN, READ_PROMPT],
                lambda f: f if LOGIN.name in f or READ_PROMPT.name in f else None,
            )

        if LOGIN.name in found:
            with self.step("login"):
                self.login(found[LOGIN.name])
        else:
            self.log("no Login dialog (the PLC has no password)")

        with self.step("dont_read"):
            prompt = self.wait(
                "the read-project question",
                [STARTUP, CONNECT, READ_PROMPT],
                lambda f: f.get(READ_PROMPT.name),
            )
            self.record("read_prompt")
            controls = self.controls(prompt)
            dont_read = _require(_child(controls, cls="Button", id=1028), "'Don't read' (1028)")
            if not dont_read.text.startswith("Don't read the project"):
                raise Aborted(f"button 1028 reads {dont_read.text!r}, expected 'Don't read ...'")
            ok = _require(_child(controls, cls="Button", id=1, text="OK"), "OK (1)")
            self.press(prompt, dont_read)
            try:
                self.wait(
                    "'Don't read' to be checked",
                    [STARTUP, CONNECT, READ_PROMPT],
                    lambda f: self.desktop.button_checked(dont_read.hwnd) == 1,
                )
            except ClickErrorBox:
                raise
            except Aborted as exc:
                raise Aborted(f"'Don't read' did not take: {exc}") from exc
            self.press(prompt, ok)
            self.connected = True
            self.wait("the main window, connected", [STARTUP, CONNECT, READ_PROMPT], self.only_main)
            self.confirm_connected()
            self.record("connected")

    def confirm_connected(self) -> None:
        """Wait for the status bar to name the PLC (the one ``--plc`` names, if given).

        The runner reads the bar until the wait times out. Then a bar that was read but named
        no PLC stops the run. A bar that was never read leaves the connection unconfirmed,
        and the run goes on. The exception is ``--plc``: a bar that cannot be read cannot
        confirm it, so the run stops.
        """
        last: list[StatusBar | None] = [None]

        def named(found: dict[str, Window]) -> StatusBar | None:
            if not self.only_main(found):
                return None
            status = self.read_status_bar()
            if status is None:
                return None
            last[0] = status
            if status.plc and self.s.plc is not None and status.plc_name != self.s.plc:
                raise Aborted(f"connected to {status.plc}, not to the PLC named {self.s.plc!r}")
            return status if status.plc else None

        def shows() -> str:
            if last[0] is not None:
                return f"the status bar names no PLC ({' | '.join(last[0].panes)})"
            if self.s.plc is None:
                raise _Unconfirmed
            return f"the status bar cannot be read to confirm the PLC named {self.s.plc!r}"

        try:
            status = self.wait(
                "the status bar to name the PLC connected to",
                [STARTUP, CONNECT, READ_PROMPT],
                named,
                on_timeout=shows,
            )
        except _Unconfirmed:
            self.status_bar("connected")
            self.log("the connection is unconfirmed: the status bar cannot be read")
            return
        self.result["status_bar"]["connected"] = list(status.panes)
        self.result["plc"] = status.plc
        self.log(f"connected to {status.plc} (status bar: {' | '.join(status.panes)})")

    def login(self, login: Window) -> None:
        self.record("login")
        controls = self.controls(login)
        user = _require(_child(controls, cls="Edit", id=20141), "User Type (20141)")
        password = _require(_child(controls, cls="Edit", id=20142), "Password (20142)")
        ok = _require(_child(controls, cls="Button", id=18002, text="OK"), "OK (18002)")
        prefilled = self.desktop.read_text(user.hwnd)
        if prefilled is None:
            raise Aborted("User Type did not answer WM_GETTEXT")
        if prefilled:
            self.log(f"User Type: {prefilled!r} (prefilled by CLICK)")
        else:
            self.desktop.set_text(user.hwnd, self.s.user_type)
            if self.desktop.read_text(user.hwnd) != self.s.user_type:
                raise Aborted("User Type did not take the text set")
            self.log(f"User Type: {self.s.user_type!r} (filled in by the runner)")
        if not self.desktop.set_text(password.hwnd, self.s.password):
            raise Aborted("Password did not answer WM_SETTEXT")
        self.log(f"password set ({len(self.s.password)} characters)")
        self.press(login, ok)

        def answered(found: dict[str, Window]) -> Window | None:
            if LOGIN.name in found:
                failed = _child(self.controls(found[LOGIN.name]), cls="Static", id=20144)
                if failed is not None and failed.visible:
                    raise Aborted(f"CLICK refused the login: {failed.text!r}")
            return found.get(READ_PROMPT.name)

        self.wait(
            "the read-project question after Login",
            [STARTUP, CONNECT, LOGIN, READ_PROMPT],
            answered,
        )

    def paste(self) -> None:
        assert self.main is not None and self.s.csv is not None
        with self.step("paste"):
            mdb = self.desktop.temp_dir(self.main) / "SC_.mdb"
            if not mdb.is_file():
                raise Aborted(f"CLICK's SC_.mdb is not at {mdb}")
            prepared = self.prepare(self.s.csv, mdb)
            if prepared.mdb_error:
                raise Aborted(f"cannot add the CSV's addresses to {mdb}: {prepared.mdb_error}")
            self.log(
                f"{prepared.rung_count} rung(s), {len(prepared.payload)} bytes; "
                f"{prepared.addresses_inserted} address(es) added to SC_.mdb"
            )
            self.result["rungs"] = {"pasted": prepared.rung_count, "saved_main": None, "same": None}
            self._scr_before = _scr_state(mdb.parent)
            if self._scr_before:
                names = [name for name, _, _ in self._scr_before]
                self.result["scr_before_paste"] = names
                self.log(f"CLICK's temp folder holds {', '.join(names)} before the first save")
            before = self.status_bar("before_paste")
            self.desktop.set_clipboard(prepared.payload, self.main)
            self.command(PASTE)
            how = self.wait(
                "CLICK to finish the paste",
                [],
                self._pasted(before, prepared.rung_count),
                timeout=self.s.paste_timeout,
            )
            self.log(f"paste done: {how}")
            self.status_bar("pasted")
            self.record("pasted")

    def _pasted(
        self, before: StatusBar | None, rungs: int
    ) -> Callable[[dict[str, Window]], str | None]:
        """Return the condition for ``wait`` that says the paste is done.

        CLICK freezes while it pastes and shows nothing when it is done. The paste is done
        when CLICK answers again on ``RESPONSIVE_POLLS`` polls in a row, with the main window
        alone and enabled. If the status bar showed a cursor or a step count before the
        paste, it must then also show the rungs pasted (``StatusBar.shows_paste``). If CLICK
        answers for ``Settings.timeout`` seconds without that, the run aborts. The decoded
        save is the final check (``check_landed``).
        """
        answered = [0]
        since: list[float | None] = [None]

        def done(found: dict[str, Window]) -> str | None:
            if not self.only_main(found):
                answered[0], since[0] = 0, None
                return None
            answered[0] += 1
            if answered[0] < RESPONSIVE_POLLS:
                return None
            polls = f"CLICK answers on {RESPONSIVE_POLLS} polls in a row"
            if before is None or (before.rung is None and before.steps is None):
                return f"{polls} (no status bar to check it with)"
            now = self.read_status_bar()
            if now is None:
                return f"{polls} (the status bar no longer reads)"
            if now.shows_paste(before, rungs):
                return (
                    f"{polls}, and its status bar shows rung {now.rung}, {now.steps} step(s) "
                    f"(before: rung {before.rung}, {before.steps} step(s))"
                )
            if since[0] is None:
                since[0] = time.monotonic()
            elif time.monotonic() - since[0] > self.s.timeout:
                raise Aborted(
                    f"CLICK answers again, but after {self.s.timeout:g} s its status bar does "
                    f"not show the {rungs} rung(s) pasted. It shows {' | '.join(now.panes)}. "
                    f"Before the paste it showed {' | '.join(before.panes)}."
                )
            return None

        return done

    def syntax_check(self) -> None:
        with self.step("syntax_check"):
            self.result["syntax_check"] = self.check_syntax()
            self.record("syntax_checked")

    def check_syntax(self) -> dict[str, Any]:
        """Run Syntax Check, wait for its result in Output and return it.

        The result holds the text, the counts, and the project it names (``project``, the
        stem of the file that the main window's title names). The runner empties Output first
        (WM_SETTEXT), so a check that reads as the one before is still seen to finish. Live
        probe 1 (2026-11-15) waited out a second check whose text was the first's.
        """
        assert self.main is not None
        controls = self.desktop.controls(self.main)
        bars = {
            c.hwnd for c in controls if c.cls.startswith("Afx:ControlBar") and c.text == "Output"
        }
        output = _require(
            next(
                (c for c in controls if c.cls == "Edit" and c.id == 1005 and c.parent in bars),
                None,
            ),
            "the Output pane's Edit (1005)",
        )
        main = classify(self.desktop.windows(self.pid), [])[0].get(MAIN)
        project = _project_file(main.title) if main is not None else None
        if project is None:
            raise Aborted("the main window's title names no project")
        # The check lists what it finds, then "<project> - N error(s), M warning(s)" last
        total = re.compile(
            rf"^{re.escape(Path(project).stem)} - (\d+) error\(s\), (\d+) warning\(s\)\s*$",
            re.MULTILINE,
        )
        self.desktop.set_text(output.hwnd, "")
        before = self.desktop.read_text(output.hwnd)
        self.command(SYNTAX_CHECK)
        posts = [time.monotonic()]

        def finished(found: dict[str, Window]) -> tuple[str, re.Match[str]] | None:
            if not self.only_main(found):
                return None
            text = self.desktop.read_text(output.hwnd)
            if not text or text == before:
                if (
                    len(posts) < SYNTAX_POSTS
                    and time.monotonic() - posts[-1] >= SYNTAX_REPOST_AFTER
                ):
                    self.log(f"Output is still empty after {SYNTAX_REPOST_AFTER:g} s: post again")
                    self.command(SYNTAX_CHECK)
                    posts.append(time.monotonic())
                return None
            matches = list(total.finditer(text))
            return (text, matches[-1]) if matches else None

        text, match = self.wait(
            f"the Syntax Check result in Output ('{Path(project).stem} - ...')",
            [],
            finished,
            timeout=self.s.paste_timeout,
        )
        self.log(f"Syntax Check: {match.group(0).strip()}")
        return {
            "text": text,
            "errors": int(match.group(1)),
            "warnings": int(match.group(2)),
            "project": Path(project).stem,
        }

    # -- try: CLICK's instruction dialogs -------------------------------------

    def try_cases(self) -> None:
        """Read the nicknames asked for, check the empty main program, then try each case.

        ``execute`` writes the entries carried from ``--resume``'s run to
        ``DIR/cases.jsonl`` before CLICK starts. Each case that was not carried is then tried
        in the file's order. ``try_case`` writes its line once the answer is known or the case
        stopped the run. With ``--stop-after N`` the run ends cleanly before its (N+1)th case.
        """
        if self.nickname_addresses:
            with self.step("nicknames"):
                self.copy_nicknames()
        with self.step("baseline"):
            baseline = self.check_syntax()
            self.result["baseline_syntax_check"] = baseline
            self.record("baseline")
            if _end_rung(baseline["text"]) != 1:
                raise Aborted(
                    "the empty main program's Syntax Check does not name rung 1 for its missing "
                    "END (C0201). The runner cannot tell whether an instruction was placed. "
                    f"The check reads {baseline['text']!r}."
                )
        with self.step("try"):
            tried = 0
            for number, case in enumerate(self.cases, 1):
                if case.name in self.carried:
                    continue
                if self.s.stop_after is not None and tried >= self.s.stop_after:
                    self.log(f"stopping after {tried} case(s), as --stop-after asks")
                    self.result["stopped_after"] = tried
                    break
                tried += 1
                self.try_case(number, case, baseline)

    def load_resume(self) -> None:
        """Read the entries of ``--resume``'s run from its ``cases.jsonl``.

        Raise Refused if they do not fit the cases file. The last line for a case is its
        entry. Each entry must name a case of the file by its id and ask what that case asks.
        The run carries an entry that has an outcome, and one whose case stopped ``MAX_STOPS``
        runs (a Ctrl+C is not counted). It does not try either again. With ``keep``, an
        accepted entry without its save (``kept``) has no outcome here. The run tries any
        other entry again (a case that stopped a run before CLICK answered it) and keeps its
        ``stops``. It leaves out a last line that was cut short because the run's process
        ended while writing it.
        """
        assert self.s.resume is not None
        path = self.s.resume / CASES_LOG
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise Refused(f"cannot read {path} to resume from: {exc}") from exc
        by_id = {case.name: (number, case) for number, case in enumerate(self.cases, 1)}
        last: dict[str, dict[str, Any]] = {}
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError as exc:
                if line_number == len(lines):
                    self.log(f"{path} line {line_number} is cut short: left out")
                    continue
                raise Refused(f"{path} line {line_number} is not JSON: {exc}") from exc
            case_id = entry.get("id") if isinstance(entry, dict) else None
            if case_id not in by_id:
                raise Refused(
                    f"{path} line {line_number}: case {case_id!r} is not in {self.s.cases}"
                )
            asks = by_id[case_id][1].asks()
            if {key: entry.get(key, _ASKED_BEFORE.get(key)) for key in asks} != asks:
                raise Refused(
                    f"{path} line {line_number}: case {case_id!r} asks otherwise there than in "
                    f"{self.s.cases}"
                )
            if entry.get("wired", False) != self.s.wire:
                raise Refused(
                    f"{path} line {line_number}: case {case_id!r} was tried "
                    f"{'with' if entry.get('wired') else 'without'} --wire there"
                )
            last[case_id] = entry
        for case_id, entry in last.items():
            entry["index"] = by_id[case_id][0]
            stops = list(entry.get("stops", []))
            counted = [stop for stop in stops if not stop.get("interrupted")]
            answered = entry.get("outcome") is not None
            if answered and self.s.keep and entry["outcome"] == "accepted":
                answered = entry.get("kept") is not None
            if answered or len(counted) >= MAX_STOPS:
                self.carried[case_id] = entry
            else:
                self.earlier_stops[case_id] = stops
                self.retried[case_id] = entry
        self.log(
            f"resuming from {self.s.resume}: {len(self.carried)} case(s) carried, "
            f"{len(self.earlier_stops)} to try again"
        )

    def write_carried(self) -> None:
        """Write the carried entries into the result and ``DIR/cases.jsonl``, in the file's order.

        Also write the entries to try again into ``cases.jsonl`` with their stops, so that a
        run that ends before it tries them still keeps their stops. A case that is tried
        writes its own line after them. The method creates the file even when there is
        nothing to write, so that a run stopped before its first case can be resumed.
        """
        path = self.s.out / CASES_LOG
        path.touch()
        self.result["files"]["cases"] = path
        for entry in sorted(self.carried.values(), key=lambda e: e["index"]):
            self.result["cases"].append(entry)
            self.write_case(entry)
        for entry in sorted(self.retried.values(), key=lambda e: e["index"]):
            self.write_case({**entry, "outcome": None})
        self.result["carried"] = len(self.carried)

    def write_case(self, entry: dict[str, Any]) -> None:
        """Append *entry* to ``DIR/cases.jsonl`` as one line, and flush it to disk."""
        path = self.s.out / CASES_LOG
        self.result["files"]["cases"] = path
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, default=_json_default) + "\n")
            file.flush()
            os.fsync(file.fileno())

    def copy_nicknames(self) -> None:
        """Copy the new project's SC_.mdb into DIR and read the nicknames asked for from the copy.

        The runner only copies CLICK's own file and opens the copy.
        """
        assert self.main is not None
        mdb = self.desktop.temp_dir(self.main) / "SC_.mdb"
        if not mdb.is_file():
            raise Aborted(f"CLICK's SC_.mdb is not at {mdb}")
        copy = Path(shutil.copy2(mdb, self.s.out / "SC_.mdb"))
        self.result["files"]["mdb"] = copy
        names = self.read_nicknames(copy, self.nickname_addresses)
        self.result["nicknames"] = names
        for address in self.nickname_addresses:
            name = names.get(address)
            self.log(f"{address}: {'no row' if name is None else repr(name)}")

    def try_case(self, number: int, case: Case, baseline: dict[str, Any]) -> None:
        """Try *case* (``ask``) and write its entry to ``DIR/cases.jsonl`` however that ends.

        The case's entry in ``cases`` has these keys. ``index`` is its number in the file and
        ``id`` is its ``case``. Then come the keys for what it asks (row, case, instruction,
        mode, fields, choices, options). ``wired`` says whether it was tried with ``--wire``.
        ``outcome`` is ``accepted``, ``refused``, ``not_taken`` or ``other``. ``code`` and
        ``message`` come from the box. An accepted case has them only if CLICK closed the
        dialog along with a box. A ``not_taken`` case's message says what the dialog did not
        take. ``limits`` holds each field's EM_GETLIMITTEXT. ``read_back`` holds each field's
        text as read back before OK, and with ``reads_every_field`` every open field's.
        ``controls`` holds each visible Button, Static and Edit of the dialog as OK or Cancel
        found it, with ``id``, ``cls``, ``text``, ``enabled``, and ``checked`` for a Button or
        ``edit_text`` for an Edit. A group box is a Button of id -1 whose text is its
        section's label. ``syntax_check`` is set once the dialog closed. It holds the text,
        the counts, and the ``lines`` that name a code the empty program's check does not.
        ``kept`` is an accepted case's save with ``keep`` (see ``keep_case``), and None
        otherwise. ``seconds`` is how long the case took. ``out`` is the run it was tried in.
        ``stops`` lists each run that the case stopped. Each stop has that run's ``out`` and
        ``reason``. A stop that Ctrl+C caused also has ``interrupted``. If the case had an
        answer other than ``other`` when it stopped, the stop holds that answer as its own
        ``outcome``, and the case's ``outcome`` is None. A case that stops the run is the
        result's ``stopped_at``.
        """
        entry: dict[str, Any] = {
            "index": number,
            "id": case.name,
            **case.asks(),
            "wired": self.s.wire,
            "outcome": None,
            "code": None,
            "message": None,
            "limits": None,
            "read_back": None,
            "controls": None,
            "syntax_check": None,
            "kept": None,
            "seconds": None,
            "out": self.s.out,
            "stops": list(self.earlier_stops.get(case.name, [])),
        }
        self.result["cases"].append(entry)
        began = time.monotonic()
        try:
            self.ask(number, case, entry, baseline)
        except BaseException as exc:
            interrupted = isinstance(exc, KeyboardInterrupt)
            if interrupted:
                reason = "interrupted (Ctrl+C)"
            elif isinstance(exc, Aborted):
                reason = str(exc)
            else:
                reason = f"{type(exc).__name__}: {exc}"
            stop: dict[str, Any] = {"out": self.s.out, "reason": reason}
            if interrupted:
                stop["interrupted"] = True
            # An answer that the run stopped after (Delete or a save failed) is not the case's.
            # The stop keeps it and the case is tried again. ``other`` is the stop itself
            if entry["outcome"] not in (None, "other"):
                stop["outcome"] = entry["outcome"]
                entry["outcome"] = None
            entry["stops"].append(stop)
            self.result["stopped_at"] = {"index": number, "id": case.name}
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - began, 3)
            self.write_case(entry)

    def ask(self, number: int, case: Case, entry: dict[str, Any], baseline: dict[str, Any]) -> None:
        """Try *case* in a rung of its own and record CLICK's answer in *entry* (``answer``).

        With ``wire``, the runner places an output instruction behind a contact
        (``WIRE_CONTACT``, by its own dialog). Once CLICK has answered the case, whatever it
        answered, the runner removes the rung that the contact starts (``clear_rung``). A case
        that stops the run leaves the rung, and CLICK is ended. A contact instruction gets its
        coil once its dialog closes (``placed``).
        """
        instruction = INSTRUCTIONS[case.instruction]
        what = f"case {number} ({case.row} {case.name})"
        label = f"case{number:02d}"
        behind = self.s.wire and instruction.kind == OUTPUT
        if behind:
            self.place_wired(what, label, WIRE_CONTACT_DIALOG, WIRE_CONTACT, CONTACT_CURSOR)
        self.answer(what, label, case, instruction, entry, baseline)
        if behind and entry["outcome"] in ("refused", "not_taken"):
            self.clear_rung(what, baseline)

    def answer(
        self,
        what: str,
        label: str,
        case: Case,
        instruction: Instruction,
        entry: dict[str, Any],
        baseline: dict[str, Any],
    ) -> None:
        """Open *case*'s dialog, fill it, press OK and record CLICK's answer in *entry*.

        The runner presses the mode before the fields, or after them with
        ``mode_after_fields``. In that case a field closed for entry is named with the mode
        the dialog opened in. It sets the options once the fields are filled, those asked 1
        before those asked 0. It reads the fields again only when an option or the mode was
        pressed after the fields. Such a press may open a field that the case asks for, and
        the runner fills it then. It reads each option set again before OK.

        The case becomes ``not_taken`` once the dialog's Cancel has closed it, and OK is not
        pressed, when any of these is true: a field, list, mode or option is closed for entry
        (hidden or disabled); no option button shows the label that the case names; a radio
        button is asked to be unchecked; a field, list or option reads back other than asked;
        or a list lacks the item asked for. The run stops (``Aborted``) if CLICK does not
        answer for a field, or if an option does not read as asked after ``OPTION_PRESSES``
        presses. A closed dialog is ``accepted`` only when its Syntax Check names rung 2 for
        the missing END, as an instruction in rung 1 makes it (``placed``). Otherwise the
        case is ``other`` and the run stops.
        """
        title = instruction.title
        detail = " ".join(
            str(part)
            for part in (case.mode, case.choices, case.fields, case.options)
            if part is not None and part != {}
        )
        self.log(f"{what}: {title} {detail}")
        dialog_expect = Expect(DIALOG, "#32770", title, MAIN)
        box_expect = Expect(ANSWER_BOX, "#32770", "CLICK Programming Software", DIALOG)
        expected = [dialog_expect, box_expect]

        self.wait("the main window alone", [], self.only_main)
        self.command(instruction.command)
        dialog = self.wait(
            f"the {title} dialog",
            [dialog_expect],
            lambda f: f[DIALOG] if DIALOG in f and f[DIALOG].enabled else None,
        )
        self.check_opening(what, instruction, dialog)
        # The mode that the fields are filled in. With ``mode_after_fields`` it is the mode
        # the dialog opened in
        mode = case.mode
        if case.mode is not None and instruction.mode_after_fields:
            mode = self.checked_mode(dialog, instruction)
        elif case.mode is not None:
            # Math empties its fields on a type click: the mode goes first, the fields after
            self.press_mode(what, dialog, dialog_expect, instruction, case.mode)
        in_mode = f" in {mode} mode" if mode else ""
        for name, item in case.choices.items():
            missing = self.choose(what, dialog, dialog_expect, instruction.lists[name], item)
            if missing is not None:
                if missing == _CLOSED:
                    message = f"closed for entry{in_mode}: {name}"
                else:
                    message = f"{name}: {missing}"
                self.not_taken(what, dialog, dialog_expect, entry, message)
                return
        names = list(instruction.fields if instruction.reads_every_field else case.fields)
        fields = self.field_controls(dialog, instruction, names)
        entry["limits"] = {name: self.desktop.edit_limit(c.hwnd) for name, c in fields.items()}
        closed = [
            name
            for name, c in fields.items()
            if name in case.fields and not (c.visible and c.enabled)
        ]
        typed: dict[str, str] = {}
        for name, text in case.fields.items():
            if name not in closed:
                typed[name] = self.fill(what, title, name, fields[name], text)
        # Collect what the fields may leave closed: the mode pressed after them, and the options
        shut: list[str] = []
        pressed = False
        if case.mode is not None and instruction.mode_after_fields:
            radio = self.mode_button(dialog, instruction, case.mode)
            if radio.visible and radio.enabled:
                pressed = self.press_mode(what, dialog, dialog_expect, instruction, case.mode)
                in_mode = f" in {case.mode} mode"
            else:
                shut.append(f"mode {case.mode} closed for entry")
        options: dict[str, tuple[Control, int]] = {}
        # Set the options asked 1 first. A radio button's press unchecks its pair, so a pair
        # asked {0, 1} reads as asked whichever the case names first
        for key, state in sorted(case.options.items(), key=lambda item: -item[1]):
            option = self.set_option(what, dialog, dialog_expect, instruction, key, state)
            pressed |= option.pressed
            if option.problem is not None:
                shut.append(option.problem)
            elif option.button is not None:
                options[key] = (option.button, state)
        # Fill a field that a press after the fields (an option, the mode) has opened
        if pressed:
            fields = self.field_controls(dialog, instruction, names)
            for name in list(closed):
                if fields[name].visible and fields[name].enabled:
                    self.log(f"{what}: {title}'s {name} field is open now: filled")
                    typed[name] = self.fill(what, title, name, fields[name], case.fields[name])
                    closed.remove(name)
        # Check that each option still reads as asked, because a later option or field may
        # change it
        controls = {c.id: c for c in self.controls(dialog)}
        for button, state in options.values():
            now = controls.get(button.id)
            name = f"option {button.text!r} ({button.id})"
            if now is None or not (now.visible and now.enabled):
                shut.append(f"{name} closed for entry once the dialog was filled")
            elif (got := self.desktop.button_checked(button.hwnd)) != state:
                shut.append(f"{name} reads {got} once the dialog was filled, not {state}")
        # Read again, as OK will find them. First the fields (with ``reads_every_field``, each
        # open one), then every list
        read = [
            name
            for name, c in fields.items()
            if name in typed or (name not in case.fields and c.visible and c.enabled)
        ]
        entry["read_back"] = {
            name: self.read_field(what, title, name, fields[name]) for name in read
        }
        off = [
            name
            for name, text in typed.items()
            if text != case.fields[name] or entry["read_back"][name] != case.fields[name]
        ]
        shown = {name: instruction.opens_listing.get(i) for name, i in instruction.lists.items()}
        shown.update(case.choices)
        for name, item in shown.items():
            if item is not None and self.list_item(dialog, instruction.lists[name]) != item:
                off.append(name)
        # A box that CLICK showed while the fields were filled aborts here. It is not taken
        # for OK's answer
        self.wait(
            f"the filled {title} dialog alone",
            [dialog_expect],
            lambda f: len(f) == 2 and DIALOG in f and f[DIALOG].enabled,
        )
        self.record(f"{label}_filled")
        if closed or shut or off:
            told = []
            if closed:
                told.append(f"closed for entry{in_mode}: {', '.join(closed)}")
            told += shut
            if off:
                told.append(f"reads back otherwise: {', '.join(off)}")
            self.log(f"{what}: read back {entry['read_back']!r}")
            self.not_taken(what, dialog, dialog_expect, entry, "; ".join(told))
            return
        ok = _require(
            _child(self.controls(dialog), cls="Button", id=1, text="OK"), f"{title}'s OK (1)"
        )
        entry["controls"] = self.visible_controls(dialog)
        self.press(dialog, ok)

        def answered(found: dict[str, Window]) -> Window | bool | None:
            if ANSWER_BOX in found:
                return found[ANSWER_BOX]
            return DIALOG not in found and self.only_main(found)

        answer = self.wait(f"CLICK's answer to {what}", expected, answered, answering=dialog.hwnd)
        self.record(f"{label}_answer")
        if isinstance(answer, Window) and not self.answer_box(
            what, entry, dialog, answer, expected
        ):
            entry["outcome"] = "refused"
        else:
            self.placed(what, label, entry, baseline, instruction)

    def check_opening(self, what: str, instruction: Instruction, dialog: Window) -> None:
        """Abort unless *dialog* opened with the buttons and lists *instruction* takes as given."""
        title = instruction.title
        controls = self.controls(dialog)
        for button_id, state in instruction.opens_with.items():
            button = _require(
                _child(controls, cls="Button", id=button_id), f"{title}'s button {button_id}"
            )
            if self.desktop.button_checked(button.hwnd) != state:
                raise Aborted(
                    f"{what}: {title}'s {button.text or 'button'} ({button_id}) is "
                    f"{'not ' if state else ''}checked as the dialog opens"
                )
        for list_id, item in instruction.opens_listing.items():
            shown = self.list_item(dialog, list_id)
            if shown != item:
                raise Aborted(
                    f"{what}: {title}'s list {list_id} shows {shown!r} as the dialog opens, "
                    f"not {item!r}"
                )

    def field_controls(
        self, dialog: Window, instruction: Instruction, names: list[str]
    ) -> dict[str, Control]:
        """Return the edits of *dialog*'s fields *names*, as they are now."""
        controls = self.controls(dialog)
        found = {}
        for name in names:
            field_id = instruction.fields[name]
            found[name] = _require(
                next((c for c in controls if c.id == field_id and c.cls in _FIELD_CLASSES), None),
                f"{instruction.title}'s {name} field ({field_id})",
            )
        return found

    def fill(self, what: str, title: str, name: str, control: Control, text: str) -> str:
        """Set *title*'s field *name* to *text* by WM_SETTEXT. Return the text it then reads."""
        if not self.desktop.set_text(control.hwnd, text):
            raise Aborted(f"{what}: CLICK did not answer setting {title}'s {name} field")
        return self.read_field(what, title, name, control)

    def mode_button(self, dialog: Window, instruction: Instruction, mode: str) -> Control:
        """Return *dialog*'s radio button for *mode*, as it is now."""
        return _require(
            _child(self.controls(dialog), cls="Button", id=instruction.modes[mode]),
            f"{instruction.title}'s {mode} button ({instruction.modes[mode]})",
        )

    def checked_mode(self, dialog: Window, instruction: Instruction) -> str | None:
        """Return the mode whose radio button *dialog* has checked now, or None."""
        controls = self.controls(dialog)
        for mode, button_id in instruction.modes.items():
            radio = _child(controls, cls="Button", id=button_id)
            if radio is not None and self.desktop.button_checked(radio.hwnd) == 1:
                return mode
        return None

    def press_mode(
        self, what: str, dialog: Window, expect: Expect, instruction: Instruction, mode: str
    ) -> bool:
        """Check *mode*'s radio button unless it is checked already. Return whether it pressed.

        The runner posts BM_CLICK. Math empties its fields on a type click even on the type
        already checked, so the runner does not press a button that is already checked.
        """
        title = instruction.title
        radio = self.mode_button(dialog, instruction, mode)
        if self.desktop.button_checked(radio.hwnd) == 1:
            return False
        self.press(dialog, radio)
        self.wait(
            f"{title}'s {mode} button to be checked",
            [expect],
            lambda f: self.desktop.button_checked(radio.hwnd) == 1,
        )
        # Its click is handled in full once the dialog's thread answers again
        if not self.desktop.idle(dialog.hwnd, self.s.timeout):
            raise Aborted(f"{what}: the {title} dialog stopped answering")
        return True

    def set_option(
        self,
        what: str,
        dialog: Window,
        expect: Expect,
        instruction: Instruction,
        key: str,
        state: int,
    ) -> OptionSet:
        """Set the option button *key* (the label it shows now, or its id) to *state*.

        The runner looks only at the buttons that *instruction* lists as its ``options``. Of
        those that show the label, it looks at the visible one. The result names the button,
        says whether it was pressed, and says why the button cannot be set, if it cannot. The
        reasons are: no button shows the label; more than one visible button does (never seen
        in CLICK, and the runner does not pick one); the button is closed (hidden or
        disabled); or it is a radio button asked for 0 while checked (a press never unchecks
        one). The runner reads the button's state before each press (BM_CLICK, posted). It
        gives each press ``OPTION_WAIT`` seconds to show *state*. If the button does not read
        *state* after ``OPTION_PRESSES`` presses, the run stops.
        """
        title = instruction.title
        buttons = [
            c for c in self.controls(dialog) if c.cls == "Button" and c.id in instruction.options
        ]
        if _is_id(key):
            found = [c for c in buttons if c.id == int(key)]
            if not found:
                raise Aborted(f"{what}: {title}'s option button {key} not found")
        else:
            found = [c for c in buttons if c.text == key]
            if not found:
                return OptionSet(None, False, f"no option button shows {key!r}")
        shown = [c for c in found if c.visible]
        if len(shown) > 1:
            ids = ", ".join(str(c.id) for c in shown)
            return OptionSet(None, False, f"option buttons {ids} all show {key!r}")
        button = shown[0] if shown else found[0]
        name = f"option {button.text!r} ({button.id})"
        if not (button.visible and button.enabled):
            return OptionSet(button, False, f"{name} closed for entry")
        presses = 0
        while (checked := self.desktop.button_checked(button.hwnd)) != state:
            if state == 0 and checked == 1 and button.id in instruction.option_radios:
                return OptionSet(button, False, f"{name}: a radio button cannot be unchecked")
            if presses == OPTION_PRESSES:
                raise Aborted(
                    f"{what}: {title}'s {name} does not read {state} after {presses} presses"
                )
            self.press(dialog, button)
            presses += 1
            deadline = time.monotonic() + OPTION_WAIT

            def reads(found: dict[str, Window], deadline: float = deadline) -> str | None:
                if self.desktop.button_checked(button.hwnd) == state and self.desktop.idle(
                    dialog.hwnd, IDLE_TIMEOUT
                ):
                    return "set"
                return "late" if time.monotonic() > deadline else None

            got = self.wait(
                f"{title}'s {name} to read {state}",
                [expect],
                reads,
                timeout=OPTION_WAIT + self.s.timeout,
            )
            if got == "late":
                self.log(f"{what}: {name} does not read {state} {OPTION_WAIT:g} s after a press")
        if presses:
            self.log(f"{what}: {name} reads {state} after {presses} press(es)")
        return OptionSet(button, presses > 0, None)

    def visible_controls(self, dialog: Window) -> list[dict[str, Any]]:
        """Return each visible Button, Static and Edit of *dialog*, whatever its id.

        Each is a row with ``id``, ``cls``, ``text``, ``enabled``, and ``checked`` (a Button)
        or ``edit_text`` (an Edit). A group box is a Button of id -1 whose text is its
        section's label.
        """
        rows = []
        for control in self.controls(dialog):
            if not control.visible or control.cls not in ("Button", "Static", "Edit"):
                continue
            row: dict[str, Any] = {
                "id": control.id,
                "cls": control.cls,
                "text": control.text,
                "enabled": control.enabled,
            }
            if control.cls == "Button":
                row["checked"] = self.desktop.button_checked(control.hwnd)
            if control.cls == "Edit":
                row["edit_text"] = self.desktop.read_text(control.hwnd)
            rows.append(row)
        return rows

    def place_wired(
        self,
        what: str,
        label: str,
        instruction: Instruction,
        address: str,
        cursor: str | None = None,
    ) -> None:
        """Place what ``--wire`` adds to a case's rung (*instruction*: the contact or the
        coil) at the ladder's cursor, with *address* in its address field.

        Its dialog must open as ``check_opening`` expects, and its address field must read
        *address* back. Once OK has closed the dialog, the status bar must show the cursor at
        *cursor* (when given), if the bar can be read. A CLICK error box stops the run.
        """
        title = instruction.title
        expect = Expect(DIALOG, "#32770", title, MAIN)
        self.wait("the main window alone", [], self.only_main)
        self.command(instruction.command)
        dialog = self.wait(
            f"the {title} dialog",
            [expect],
            lambda f: f[DIALOG] if DIALOG in f and f[DIALOG].enabled else None,
        )
        self.check_opening(what, instruction, dialog)
        controls = self.controls(dialog)
        field_id = instruction.fields["address"]
        edit = _require(
            _child(controls, cls="Edit", id=field_id), f"{title}'s address field ({field_id})"
        )
        shown = self.fill(what, title, "address", edit, address)
        if shown != address:
            raise Aborted(f"{what}: {title}'s address field reads {shown!r}, not {address!r}")
        self.wait(
            f"the filled {title} dialog alone",
            [expect],
            lambda f: len(f) == 2 and DIALOG in f and f[DIALOG].enabled,
        )
        ok = _require(_child(controls, cls="Button", id=1, text="OK"), f"{title}'s OK (1)")
        self.press(dialog, ok)

        def done(found: dict[str, Window]) -> bool:
            if not self.only_main(found):
                return False
            status = None if cursor is None else self.read_status_bar()
            return status is None or status.cursor == cursor

        at = f", the cursor at {cursor}" if cursor else ""
        self.wait(f"{title} {address} placed{at}", [expect], done)
        self.log(f"{what}: {title} {address} placed")
        self.record(f"{label}_{'contact' if instruction.kind == CONTACT else 'coil'}")

    def select_rung(self, why: str) -> None:
        """Select rung 1 by posting a click on its number in the ladder view (``RUNG1_POINT``).

        Wait until the main window is alone and, if the status bar can be read, shows the
        cursor at ``RUNG1_CURSOR``.
        """
        assert self.main is not None
        self.wait("the main window alone", [], self.only_main)
        try:
            view = self.desktop.click_ladder(self.main, *RUNG1_POINT)
        except LadderViewError as exc:
            raise Aborted(f"cannot select rung 1 for {why}: {exc}") from exc
        self.log(f"click at {RUNG1_POINT} in the ladder view ({view}) for {why}")

        def selected(found: dict[str, Window]) -> bool:
            if not self.only_main(found):
                return False
            status = self.read_status_bar()
            return status is None or status.cursor == RUNG1_CURSOR

        self.wait(f"rung 1 selected (the cursor at {RUNG1_CURSOR}) for {why}", [], selected)

    def clear_rung(self, what: str, baseline: dict[str, Any]) -> None:
        """Remove what *what* left in rung 1, and check that the main program is empty again.

        Edit > Delete removes what is under the cursor. That is an output instruction,
        because CLICK leaves the cursor there once it has placed one. With ``wire``, the
        runner selects rung 1 first (``select_rung``), so Delete removes the whole rung.
        Nothing outside the ladder view shows that Delete landed. The status bar, the title
        and the main window's controls stay as they were (live probe 3). So the proof is the
        next Syntax Check, which must read as the empty program's did, except for the
        project's name (a save renames it).
        """
        if self.s.wire:
            self.select_rung(f"Delete after {what}")
        self.command(DELETE)
        self.wait(f"Delete after {what}", [], self.only_main)
        cleared = self.check_syntax()
        if _unnamed(cleared) != _unnamed(baseline):
            raise Aborted(
                f"after {what}, Delete did not leave the main program empty. Its Syntax "
                f"Check reads {cleared['text']!r}. The empty program's reads {baseline['text']!r}."
            )

    def read_field(self, what: str, title: str, name: str, control: Control) -> str:
        """Return the text of *title*'s field *name*.

        Raise Aborted if CLICK does not answer, because a stalled CLICK is no answer of the
        dialog's.
        """
        text = self.desktop.read_text(control.hwnd)
        if text is None:
            raise Aborted(f"{what}: CLICK did not answer reading {title}'s {name} field")
        return text

    def not_taken(
        self, what: str, dialog: Window, expect: Expect, entry: dict[str, Any], message: str
    ) -> None:
        """Close *dialog* by its Cancel, then make the case ``not_taken`` with *message*.

        The answer is set only once the dialog is closed. The case's ``controls`` are read as
        Cancel finds them.
        """
        entry["controls"] = self.visible_controls(dialog)
        self.cancel(dialog, expect)
        entry.update(outcome="not_taken", message=message)
        self.log(f"{what}: not taken: {message}")

    def list_item(self, dialog: Window, list_id: int) -> str | None:
        """Return the item that the ComboBox *list_id* of *dialog* shows, or None."""
        combo = _require(
            _child(self.controls(dialog), cls="ComboBox", id=list_id),
            f"{dialog.title}'s list {list_id}",
        )
        read = self.desktop.combo_box(combo.hwnd)
        if read is None:
            raise Aborted(f"{dialog.title}'s list {list_id} does not answer")
        items, selected = read
        return items[selected] if 0 <= selected < len(items) else None

    def choose(
        self, what: str, dialog: Window, expect: Expect, list_id: int, item: str
    ) -> str | None:
        """Pick *item* in the drop-down list *list_id* with Up and Down keys.

        Return None once it is picked. Otherwise return why it cannot be: ``_CLOSED`` for a
        list not open for entry (hidden or disabled), else a text saying that the list has no
        such item. The runner sends each key to the list alone (WM_KEYDOWN, WM_KEYUP), as
        ``picker`` sends its keys. Each key moves the selection one item. The list tells the
        dialog itself, as when a user picks. A list that shows no item gets Home first.
        """
        combo = _require(
            _child(self.controls(dialog), cls="ComboBox", id=list_id),
            f"{dialog.title}'s list {list_id}",
        )
        if not (combo.visible and combo.enabled):
            return _CLOSED
        read = self.desktop.combo_box(combo.hwnd)
        if read is None:
            raise Aborted(f"{dialog.title}'s list {list_id} does not answer")
        items, selected = read
        if item not in items:
            return f"the list has no item {item!r} (its items: {items!r})"
        target = items.index(item)
        keys = []
        if selected < 0:
            keys.append(_VIRTUAL_KEYS["HOME"])
            selected = 0
        step = _VIRTUAL_KEYS["DOWN" if target > selected else "UP"]
        keys += [step] * abs(target - selected)
        for vk in keys:
            if not self.desktop.send_key(combo.hwnd, vk):
                raise Aborted(f"{what}: {dialog.title}'s list {list_id} did not answer a key")
        self.wait(
            f"{dialog.title}'s list {list_id} to show {item!r}",
            [expect],
            lambda f: (
                len(f) == 2
                and DIALOG in f
                and f[DIALOG].enabled
                and self.list_item(dialog, list_id) == item
                and self.desktop.idle(dialog.hwnd, IDLE_TIMEOUT)
            ),
        )
        self.log(f"{what}: {dialog.title}'s list {list_id} shows {item!r}")
        return None

    def cancel(self, dialog: Window, expect: Expect) -> None:
        """Close the instruction *dialog* by its Cancel and wait for the main window alone."""
        cancel = _require(
            _child(self.controls(dialog), cls="Button", id=2, text="Cancel"),
            f"{dialog.title}'s Cancel (2)",
        )
        self.press(dialog, cancel)
        self.wait(f"the {dialog.title} dialog to close", [expect], self.only_main)

    def placed(
        self,
        what: str,
        label: str,
        entry: dict[str, Any],
        baseline: dict[str, Any],
        instruction: Instruction,
    ) -> None:
        """Check that the closed dialog left its instruction in rung 1, then remove it.

        With ``wire``, a contact instruction gets its coil first (``WIRE_COIL``, by the Out
        dialog). A Syntax Check that does not name rung 2 for the missing END makes the case
        ``other`` and stops the run, because CLICK closed the dialog and placed nothing. With
        ``wire``, a Syntax Check with a line whose code the empty program's check does not
        have does the same. The wired rung is whole, so it must check clean except for the
        missing END. With ``keep``, the runner then saves the project (``keep_case``).
        ``clear_rung`` then removes the rung's instructions.
        """
        if self.s.wire and instruction.kind == CONTACT:
            self.place_wired(what, label, WIRE_COIL_DIALOG, WIRE_COIL)
        check = self.check_syntax()
        known = {m.group(1) for m in _SYNTAX_CODE.finditer(baseline["text"])}
        lines = [
            line.strip()
            for line in check["text"].splitlines()
            if (m := _SYNTAX_CODE.search(line)) and m.group(1) not in known
        ]
        entry["syntax_check"] = {**check, "lines": lines}
        rung = _end_rung(check["text"])
        if rung != 2:
            entry["outcome"] = "other"
            raise Aborted(
                f"{what}: CLICK closed the dialog, but its Syntax Check names rung {rung} for "
                "the missing END, not rung 2. No instruction was placed in rung 1."
            )
        if self.s.wire and lines:
            entry["outcome"] = "other"
            raise Aborted(
                f"{what}: CLICK closed the dialog, but the wired rung's Syntax Check names "
                f"more than the empty program's does: {lines!r}"
            )
        entry["outcome"] = "accepted"
        self.log(f"{what}: accepted")
        if self.s.keep:
            self.keep_case(label, entry)
        self.clear_rung(what, baseline)

    def keep_case(self, label: str, entry: dict[str, Any]) -> None:
        """Save the project with the case's instruction in it as ``DIR/saves/<label>.ckp``.

        The runner copies CLICK's Scr*.tmp files and Project.ini into
        ``DIR/saves/<label>/click/``, as ``paste`` copies them. With ``wire``, CLICK's
        Edit > Copy then copies rung 1 (``copy_rung``) into ``DIR/saves/<label>.clip.bin``.
        The runner decodes both copies once CLICK has ended (``decode_kept``).

        The case's ``kept`` has these keys. ``ckp`` and ``click`` are the files copied.
        ``clip`` is the clipboard's file, or None. The decoding then sets ``csv`` (the files
        written into ``DIR/saves/<label>/csv/``), ``main`` (main.csv's lines after its
        header), ``legacy`` (the rungs laddercodec lists as held in a legacy encoding or
        unreadable), ``stored`` (each Scr*.tmp's instructions with their tags as stored:
        ``_read_stored``) and ``error`` (why the copy could not be read, or None).
        ``clip_csv`` is the clipboard decoded into ``DIR/saves/<label>.clip.csv``, written as
        main.csv is, or None. ``clip_error`` is what in the clipboard laddercodec cannot read
        or write, or why it could not be decoded, or None. It does not stop the run.
        """
        assert self.main is not None
        saves = self.s.out / "saves"
        saves.mkdir(exist_ok=True)
        temp = self.desktop.temp_dir(self.main)
        ckp = (saves / f"{label}.ckp").resolve()
        self.save_as(ckp, temp, prefix=f"{label}_")
        entry["kept"] = {
            "ckp": ckp,
            "click": self.copy_temp(temp, saves / label / "click"),
            "clip": None,
            "csv": None,
            "main": None,
            "legacy": None,
            "stored": None,
            "error": None,
            "clip_csv": None,
            "clip_error": None,
        }
        if self.s.wire:
            entry["kept"]["clip"] = self.copy_rung(label, saves / f"{label}.clip.bin")

    def copy_rung(self, label: str, path: Path) -> Path:
        """Copy rung 1 by CLICK's Edit > Copy and write the clipboard's CLICK data to *path*.

        The runner selects rung 1 first (``select_rung``) and empties the clipboard, so what
        it reads is that Copy's. The run stops if no CLICK data is on the clipboard within
        ``Settings.timeout``.
        """
        self.select_rung(f"{label}'s Edit > Copy")
        try:
            self.desktop.empty_clipboard()
        except (OSError, RuntimeError) as exc:  # Another program holds the clipboard
            raise Aborted(f"{label}: the clipboard could not be emptied: {exc}") from exc
        self.command(EDIT_COPY)
        failures: set[str] = set()

        def copied(found: dict[str, Window]) -> bytes | None:
            if not self.only_main(found):
                return None
            try:
                return self.desktop.read_clipboard() or None
            except OSError as exc:  # Another program (CLICK, copying) holds the clipboard
                if str(exc) not in failures:
                    failures.add(str(exc))
                    self.log(f"the clipboard: {exc}")
                return None

        data = self.wait(
            "CLICK's data on the clipboard after Edit > Copy",
            [],
            copied,
            on_timeout=lambda: f"{label}: Edit > Copy left no CLICK data on the clipboard",
        )
        path.write_bytes(data)
        self.log(f"{label}: Edit > Copy put {len(data)} bytes on the clipboard: {path}")
        return path

    def answer_box(
        self,
        what: str,
        entry: dict[str, Any],
        dialog: Window,
        box: Window,
        expected: list[Expect],
    ) -> bool:
        """Take CLICK's error box after OK as the case's answer and close it.

        Return whether CLICK closed the dialog along with the box. If it did not, the
        dialog's Cancel closes it. A box that is not one CLICK error with one OK is a
        question. The case is then ``other`` and the run stops.
        """
        controls = self.controls(box)
        error = click_error(box, controls)
        buttons = [c for c in controls if c.cls == "Button"]
        if error is None or [b.text for b in buttons] != ["OK"]:
            texts = [c.text for c in controls if c.cls == "Static" and c.text]
            entry.update(outcome="other", message=" | ".join(texts))
            raise Aborted(
                f"{what}: CLICK asked something the runner does not answer: {texts!r}, "
                f"buttons {[b.text for b in buttons]!r}"
            )
        entry.update(code=error[0], message=error[1])
        self.log(f"{what}: {error[0]} {error[1]}")
        self.press(box, buttons[0])
        after = self.wait(
            "the error box to close",
            expected,
            lambda f: f if ANSWER_BOX not in f and (DIALOG not in f or f[DIALOG].enabled) else None,
            answering=dialog.hwnd,
        )
        if DIALOG not in after:
            return True
        cancel = _require(
            _child(self.controls(after[DIALOG]), cls="Button", id=2, text="Cancel"),
            f"{dialog.title}'s Cancel (2)",
        )
        self.press(after[DIALOG], cancel)
        self.wait(f"the {dialog.title} dialog to close", expected[:1], self.only_main)
        return False

    # -- import: a nickname CSV through CLICK's own import ---------------------

    def import_csvs(self) -> None:
        """Import the CSV, then with ``each_row`` each of its rows in a file of its own.

        A row's file is the CSV's header and that row, byte for byte, in ``DIR/rows/``.
        """
        assert self.s.csv is not None
        plan: list[tuple[str, Path, int | None, bytes | None]] = [("whole", self.s.csv, None, None)]
        if self.s.each_row:
            folder = self.s.out / "rows"
            folder.mkdir()
            written: list[Path] = self.result["files"].setdefault("rows", [])
            for line, row in self.rows:
                path = folder / f"line{line:03d}.csv"
                path.write_bytes(self.header + row)
                written.append(path)
                plan.append((f"line{line:03d}", path, line, row))
        (self.s.out / "mdb").mkdir()
        with self.step("import"):
            for number, (name, csv, line, row) in enumerate(plan, 1):
                self.import_one(number, name, csv, line, row)

    def import_one(
        self, number: int, name: str, csv: Path, line: int | None, row: bytes | None
    ) -> None:
        """Import *csv* by File > Import > Nickname, take CLICK's answer, copy SC_.mdb.

        The import's entry in ``imports`` has these keys. ``name`` is ``whole``, or
        ``line014`` for the row starting on line 14. ``csv`` is the file imported. ``line``
        and ``row`` are the row's line and text (its bytes as Latin-1). ``answer`` is
        ``completed`` for the box reading "Completed!", ``message`` for that box with any
        other text, or ``errors`` for the Import Error List. ``message`` is the box's or
        list's text. ``errors`` holds the list's entries (see ``parse_import_errors``).
        ``mdb`` is the copy of SC_.mdb. ``mdb_changed_at_answer`` says whether CLICK's
        SC_.mdb had changed when the answer showed, ``mdb_changed`` whether it had changed
        once it settled, and ``mdb_changed_after_answer`` whether it changed between the two.
        ``stored`` holds the rows read from the copy once CLICK has ended. ``seconds`` is how
        long the import took.

        The mode is ``IMPORT_MODE`` (Delete Existing). CLICK empties the address table and
        stores what it takes from the file. In live probe 4 an import whose every row fails,
        or whose header is wrong, left no row. So ``stored`` is what CLICK made of this file
        alone.
        """
        assert self.main is not None
        label = f"import{number:02d}"
        entry: dict[str, Any] = {
            "name": name,
            "csv": csv,
            "line": line,
            "row": None if row is None else row.decode("latin-1"),
            "answer": None,
            "message": None,
            "errors": None,
            "mdb": None,
            "mdb_changed_at_answer": None,
            "mdb_changed": None,
            "mdb_changed_after_answer": None,
            "stored": None,
            "seconds": None,
        }
        self.result["imports"].append(entry)
        began = time.monotonic()
        self.log(f"{label}: {name}, {csv}")
        mdb = self.desktop.temp_dir(self.main) / "SC_.mdb"
        self.wait("the main window alone", [], self.only_main)
        before = _file_state(mdb)
        if before is None:
            raise Aborted(f"CLICK's SC_.mdb is not at {mdb}")
        self.command(IMPORT_NICKNAME)
        dialog = self.wait(
            "the Open dialog",
            [OPEN],
            lambda f: f[OPEN.name] if OPEN.name in f and f[OPEN.name].enabled else None,
        )
        self.record(f"{label}_open")
        controls = self.controls(dialog)
        mode = _require(
            next((c for c in controls if c.cls == "TRadioButton" and c.text == IMPORT_MODE), None),
            f"the Open dialog's {IMPORT_MODE!r} option",
        )
        if self.desktop.button_checked(mode.hwnd) != 1:
            self.press(dialog, mode)
            self.wait(
                f"{IMPORT_MODE!r} to be checked",
                [OPEN],
                lambda f: self.desktop.button_checked(mode.hwnd) == 1,
            )
        file_name = self._file_name_edit(controls)
        button = _require(_child(controls, cls="Button", id=1, text="&Open"), "Open (1)")
        self.fill_path(file_name, csv, [OPEN])
        self.wait(
            f"the Open dialog alone, {IMPORT_MODE!r} checked",
            [OPEN],
            lambda f: len(f) == 2 and self.desktop.button_checked(mode.hwnd) == 1,
        )
        self.press(dialog, button)

        expected = [OPEN, IMPORT_STARTING, IMPORT_PROGRESS, IMPORT_DONE, IMPORT_ERRORS]

        def answered(found: dict[str, Window]) -> tuple[Expect, Window] | None:
            shown = [e for e in (IMPORT_DONE, IMPORT_ERRORS) if e.name in found]
            if len(shown) > 1:
                raise Aborted(f"{label}: CLICK shows both 'Completed!' and the error list")
            if shown and found[shown[0].name].enabled:
                return shown[0], found[shown[0].name]
            return None

        kind, box = self.wait(
            f"CLICK's answer to {label}", expected, answered, timeout=self.s.paste_timeout
        )
        at_answer = _file_state(mdb)
        entry["mdb_changed_at_answer"] = at_answer != before
        self.record(f"{label}_answer")
        controls = self.controls(box)
        if kind is IMPORT_DONE:
            texts = [c.text for c in controls if c.cls == "Static" and c.text]
            buttons = [c for c in controls if c.cls == "Button"]
            if len(texts) != 1 or [b.text for b in buttons] != ["OK"]:
                raise Aborted(
                    f"{label}: CLICK asked something the runner does not answer: {texts!r}, "
                    f"buttons {[b.text for b in buttons]!r}"
                )
            message = texts[0]
            entry.update(answer="completed" if message == "Completed!" else "message")
        else:
            memos = [c for c in controls if c.cls == "TMemo"]
            buttons = [c for c in controls if c.cls == "TButton"]
            if len(memos) != 1 or [b.text for b in buttons] != ["Ok"]:
                raise Aborted(
                    f"{label}: the error list is not one text with Ok: {len(memos)} text(s), "
                    f"buttons {[b.text for b in buttons]!r}"
                )
            text = self.desktop.read_text(memos[0].hwnd)
            if text is None:
                raise Aborted(f"{label}: the error list's text did not answer WM_GETTEXT")
            message = text
            entry.update(answer="errors", errors=parse_import_errors(text))
        entry["message"] = message
        self.log(f"{label}: {entry['answer']}: {message!r}")
        self.press(box, buttons[0])
        # SC_.mdb's state, and since when it has read so with the main window alone
        held: list[Any] = [None, 0.0]

        def settled(found: dict[str, Window]) -> bool:
            # The answer closes with the progress window; the import is done once the main
            # window is alone and CLICK's SC_.mdb has read the same for IMPORT_SETTLE
            again = found.get(kind.name)
            if again is not None and again.hwnd != box.hwnd:
                raise Aborted(f"{label}: CLICK answered again: {_describe(again)}")
            if not self.only_main(found):
                held[0] = None
                return False
            state, now = _file_state(mdb), time.monotonic()
            if state is None or state != held[0]:
                held[:] = [state, now]
                return False
            return now - held[1] >= IMPORT_SETTLE

        self.wait(
            f"the import of {csv.name} to finish",
            [IMPORT_STARTING, IMPORT_PROGRESS, kind],
            settled,
            timeout=self.s.paste_timeout,
        )
        entry["mdb_changed"] = held[0] != before
        entry["mdb_changed_after_answer"] = held[0] != at_answer
        copy = Path(shutil.copy2(mdb, self.s.out / "mdb" / f"{number:02d}-{name}.mdb"))
        entry["mdb"] = copy
        self.result["files"].setdefault("mdb", []).append(copy)
        changed = "changed" if entry["mdb_changed"] else "unchanged"
        shown = "already" if entry["mdb_changed_at_answer"] else "not yet"
        after = "; changed after it" if entry["mdb_changed_after_answer"] else ""
        self.log(f"{label}: SC_.mdb {changed} ({shown} when the answer showed{after}); copied")
        self.record(f"{label}_done")
        entry["seconds"] = round(time.monotonic() - began, 3)

    def read_imports(self) -> None:
        """Read the rows each import left from its copy of SC_.mdb (CLICK's file is not opened)."""
        with self.step("read"):
            for entry in self.result["imports"]:
                if entry["mdb"] is None:
                    continue
                stored = self.read_rows(Path(entry["mdb"]))
                entry["stored"] = stored
                self.log(f"{entry['name']}: {len(stored)} row(s) stored")
                for address, row in stored.items():
                    values = ", ".join(f"{column}={value!r}" for column, value in row.items())
                    self.log(f"  {address}: {values}")

    # -- read-data: the PLC's data values into a file -------------------------

    def read_data(self) -> None:
        """Read every memory type through PLC > Read Data from PLC into ``DIR/plcdata.csv``."""
        with self.step("read_data"):
            self.wait("the main window alone", [], self.only_main)
            self.command(READ_DATA_FROM_PLC)
            dialog = self.wait("Read Data from PLC", [READ_DATA], lambda f: f.get(READ_DATA.name))
            controls = self.controls(dialog)
            every = _require(_labelled(controls, "TButton", "All"), "All")
            read = _require(_labelled(controls, "TButton", "Read"), "Read")
            self.press(dialog, every)
            boxes = [c for c in controls if c.cls == "TCheckBox"]

            def all_checked(found: dict[str, Window]) -> bool:
                return bool(boxes) and all(self.desktop.button_checked(c.hwnd) == 1 for c in boxes)

            self.wait("every memory type checked", [READ_DATA], all_checked)
            self.record("read_data")
            self.press(dialog, read)
            save = self.wait("Save", [READ_DATA, SAVE_DATA], lambda f: f.get(SAVE_DATA.name))
            self.record("save_data")
            dump = (self.s.out / "plcdata.csv").resolve()
            controls = self.controls(save)
            name = self._file_name_edit(controls)
            button = _require(_child(controls, cls="Button", id=1, text="&Save"), "Save (1)")
            self.fill_path(name, dump, [READ_DATA, SAVE_DATA])
            self.press(save, button)
            last: list[int | None] = [None]
            # The time at which the reading window had gone, the form was back and there was
            # still no file. That happens when a reading writes its file elsewhere, as live run
            # d8's did before ``fill_path``
            idle: list[float | None] = [None]

            def written(found: dict[str, Window]) -> bool:
                form = found.get(READ_DATA.name)
                if READING_DATA.name in found and not self.result["reading_seen"]:
                    self.result["reading_seen"] = True
                    self.log("CLICK is reading the PLC's data")
                busy = SAVE_DATA.name in found or READING_DATA.name in found
                if busy or form is None or not form.enabled:
                    idle[0] = None
                    return False
                size = dump.stat().st_size if dump.is_file() else None
                if size is None and self.result["reading_seen"]:
                    now = time.monotonic()
                    if idle[0] is None:
                        idle[0] = now
                    elif now - idle[0] >= IMPORT_SETTLE:
                        self.record("no_file")
                        raise Aborted(f"CLICK read the PLC's data but wrote no {dump.name}")
                done = size is not None and size == last[0]
                last[0] = size
                return done

            self.wait(
                f"{dump.name} to be written",
                [READ_DATA, SAVE_DATA, READING_DATA],
                written,
                timeout=self.s.paste_timeout,
            )
            self.result["files"]["plc_data"] = dump
            self.log(f"read the PLC's data into {dump} ({dump.stat().st_size} bytes)")
            self.record("read")
            close = _require(_labelled(self.controls(dialog), "TButton", "Close"), "Close")
            self.press(dialog, close)
            self.wait("Read Data from PLC to close", [READ_DATA], self.only_main)

    # -- picker: CLICK's Address Picker and what it writes into SC_.mdb ----------

    def picker(self) -> None:
        """Copy SC_.mdb, open Program > Address Picker, dump it, close it, copy SC_.mdb again."""
        assert self.main is not None
        mdb = self.desktop.temp_dir(self.main) / "SC_.mdb"
        with self.step("before"):
            self.copy_mdb(mdb, "before")
        with self.step("picker"):
            self.command(ADDRESS_PICKER)
            window = self.wait("the Address Picker", [PICKER], lambda f: f.get(PICKER.name))
            self.record("picker")
            controls = self.controls(window)
            grids = [c for c in controls if c.cls == "TStringGrid"]
            if len(grids) != 1:
                raise Aborted(f"the Address Picker has {len(grids)} grid(s), not one")
            grid, at_open = grids[0], {c.hwnd for c in controls}
            for number, token in enumerate(self.s.keys, 1):
                # The grid's in-place editor, once it shows, is a control the picker did not
                # have when it opened
                now = self.controls(window)
                new = [c for c in now if c.hwnd not in at_open and c.visible and c.cls == "TEdit"]
                target = new[-1] if new else grid
                self.log(f"key {token!r} to {target.cls} {target.hwnd}")
                if token.startswith("find:"):
                    # The Find box (an Edit in a TComboBox) and its Find button
                    boxes = {c.hwnd for c in now if c.cls == "TComboBox"}
                    edit = _require(
                        next((c for c in now if c.cls == "Edit" and c.parent in boxes), None),
                        "the Find box",
                    )
                    button = _require(_labelled(now, "TButton", "Find"), "Find")
                    answered = self.desktop.set_text(edit.hwnd, token[len("find:") :])
                    answered = answered and self.send_press(window, button)
                elif token.startswith("chars:"):
                    answered = self.desktop.send_chars(target.hwnd, token[len("chars:") :])
                elif token.startswith("text:"):
                    answered = self.desktop.set_text(target.hwnd, token[len("text:") :])
                else:
                    answered = self.desktop.send_key(target.hwnd, _VIRTUAL_KEYS[token])
                if not answered:
                    raise Aborted(f"CLICK did not answer the key {token!r}")
                # The key was sent, so CLICK has handled it. No window may have come over
                # the picker
                self.wait(
                    f"the Address Picker after the key {token!r}",
                    [PICKER],
                    lambda f: (shown := f.get(PICKER.name)) is not None and shown.enabled,
                )
                self.after_key(window, token, at_open)
                self.record(f"key{number:02d}")
            if self.s.ok:
                ok = _require(_labelled(self.controls(window), "TButton", "OK"), "OK")
                self.press(window, ok)
            else:
                self.desktop.close(window.hwnd)
            self.wait("the Address Picker to close", [PICKER], self.only_main)
        with self.step("after"):
            self.copy_mdb(mdb, "after")

    def after_key(self, window: Window, token: str, at_open: set[int]) -> None:
        """Record what the Address Picker shows after *token* under ``keys``.

        That is its editor's text, whether the editor shows, and the hints (CLICK's hints
        under the editor).
        """
        now = self.controls(window)
        editors = [c for c in now if c.hwnd not in at_open and c.cls == "TEdit"]
        editor = editors[-1] if editors else None
        hints = [
            " ".join(c.text.split())
            for c in now
            if c.hwnd not in at_open and c.cls == "TStaticText" and c.visible and c.text
        ]
        entry = {
            "key": token,
            "editor": None if editor is None else self.desktop.read_text(editor.hwnd),
            "editor_shown": None if editor is None else editor.visible,
            "hints": hints,
        }
        self.result["keys"].append(entry)
        self.log(f"  editor {entry['editor']!r} (shown {entry['editor_shown']}), hints {hints!r}")

    def copy_mdb(self, mdb: Path, label: str) -> None:
        """Wait until the main window is alone and *mdb* is unchanged for ``IMPORT_SETTLE``.

        Then copy it to ``DIR/mdb/<label>.mdb`` (``mdb_copies``).
        """
        held: list[Any] = [None, 0.0]

        def settled(found: dict[str, Window]) -> bool:
            if not self.only_main(found):
                held[0] = None
                return False
            state, now = _file_state(mdb), time.monotonic()
            if state is None or state != held[0]:
                held[:] = [state, now]
                return False
            return now - held[1] >= IMPORT_SETTLE

        self.wait(f"SC_.mdb to settle ({label})", [], settled)
        folder = self.s.out / "mdb"
        folder.mkdir(exist_ok=True)
        copy = Path(shutil.copy2(mdb, folder / f"{label}.mdb"))
        self.result["mdb_copies"][label] = {"mdb": copy, "rows": None}
        self.log(f"copied SC_.mdb as {label}")

    def read_mdb_copies(self) -> None:
        """Read the rows of each copy of SC_.mdb (CLICK's file is not opened)."""
        with self.step("read"):
            for label, entry in self.result["mdb_copies"].items():
                entry["rows"] = self.read_rows(Path(entry["mdb"]))
                self.log(f"{label}: {len(entry['rows'])} row(s): {', '.join(entry['rows'])}")

    # -- reopen: what CLICK does with its Project.ini over save and open ---------

    def reopen(self) -> None:
        """Save, edit Project.ini, save again, open that save, and save once more.

        The runner disconnects CLICK first, so opening a project compares it with no PLC. At
        each point (``first``, ``second``, ``opened``, ``third``) it copies CLICK's files into
        ``DIR/<point>/click/`` (``copy_point``). Between ``first`` and ``second`` it adds
        ``ini_add`` to the end of the Project.ini in CLICK's temp folder (the runner's own
        CLICK's; ``edit_ini``). After each copy it reads ``plc_name`` from what System
        Configuration shows (``read_plc_name``).
        """
        assert self.main is not None
        temp = self.desktop.temp_dir(self.main)
        with self.step("disconnect"):
            self.disconnect()
        for point in ("first", "second"):
            if point == "second" and self.s.ini_add is not None:
                with self.step("ini"):
                    self.edit_ini(temp / "Project.ini")
            with self.step(f"{point}_save"):
                self.save_as((self.s.out / f"{point}.ckp").resolve(), temp, prefix=f"{point}_")
                self.copy_point(point, temp)
                self.read_plc_name(point)
        with self.step("open"):
            self.open_project((self.s.out / "second.ckp").resolve(), temp)
            self.copy_point("opened", temp)
            self.read_plc_name("opened")
        with self.step("third_save"):
            self.save_as((self.s.out / "third.ckp").resolve(), temp, prefix="third_")
            self.copy_point("third", temp)
            self.read_plc_name("third")

    def read_plc_name(self, point: str) -> None:
        """Open System Configuration, keep the PLC Name it shows as *point*'s ``plc_name``,
        and close it by Cancel.

        The PLC Name is the form's one TEdit. The runner closes the notice that comes over
        the form the first time by WM_CLOSE, as its title bar's close does. It presses OK on
        neither.
        """
        self.wait("the main window alone", [], self.only_main)
        self.command(SYSTEM_CONFIGURATION)
        closed: set[int] = set()

        def shown(found: dict[str, Window]) -> Window | None:
            notice = found.get(SYSTEM_CONFIG_NOTICE.name)
            if notice is not None:
                if notice.hwnd not in closed:
                    closed.add(notice.hwnd)
                    self.log("close System Configuration's notice")
                    self.desktop.close(notice.hwnd)
                return None
            form = found.get(SYSTEM_CONFIG.name)
            return form if form is not None and form.enabled else None

        form = self.wait("System Configuration", [SYSTEM_CONFIG, SYSTEM_CONFIG_NOTICE], shown)
        self.record(f"{point}_system_config")
        controls = self.controls(form)
        edits = [c for c in controls if c.cls == "TEdit"]
        if len(edits) != 1:
            raise Aborted(f"System Configuration has {len(edits)} TEdit(s), not one")
        name = self.desktop.read_text(edits[0].hwnd)
        if name is None:
            raise Aborted("System Configuration's PLC Name did not answer")
        self.result["points"][point]["plc_name"] = name
        self.log(f"{point}: System Configuration shows the PLC Name {name!r}")
        cancel = _require(_labelled(controls, "TButton", "Cancel"), "Cancel")
        self.press(form, cancel)
        self.wait("System Configuration to close", [SYSTEM_CONFIG], self.only_main)

    def edit_ini(self, ini: Path) -> None:
        """Add ``ini_add``'s lines (separated by ``\\n`` or line breaks) to the end of *ini*,
        each ended CRLF as CLICK ends them."""
        assert self.s.ini_add is not None
        before = ini.read_bytes()
        lines = self.s.ini_add.replace("\\n", "\n").replace("\r\n", "\n").split("\n")
        added = "".join(f"{line}\r\n" for line in lines if line).encode("ascii")
        joint = b"" if not before or before.endswith(b"\n") else b"\r\n"
        ini.write_bytes(before + joint + added)
        self.result["ini_added"] = (joint + added).decode("ascii")
        self.log(f"added {added!r} to {ini}")

    def copy_point(self, point: str, temp: Path) -> None:
        """Copy CLICK's files into ``DIR/<point>/click/`` and keep the point's title, status
        bar and Project.ini (as text, Latin-1 so every byte is kept) under ``points``."""
        main = classify(self.desktop.windows(self.pid), [])[0].get(MAIN)
        bar = self.read_status_bar()
        copied = self.copy_temp(temp, self.s.out / point / "click")
        ini = next((p for p in copied if p.name == "Project.ini"), None)
        self.result["points"][point] = {
            "title": main.title if main is not None else None,
            "status_bar": bar.panes if bar is not None else None,
            "files": copied,
            "project_ini": ini.read_bytes().decode("latin-1") if ini is not None else None,
        }

    def open_project(self, ckp: Path, temp: Path) -> None:
        """Open *ckp* by File > Open Project, and wait until the open has begun.

        The wait also needs the title to name *ckp* and CLICK's Scr*.tmp files to be the same
        on two polls in a row.

        The open has begun once Project Reading or the bare title has shown, or the Scr*.tmp
        files differ from those before the command. The title can name *ckp* already (reopen
        opens the project it saved last), so the title alone proves nothing.
        """
        self.wait("the main window alone", [], self.only_main)
        before = _scr_state(temp)
        self.command(OPEN_PROJECT)
        dialog = self.wait("Open", [OPEN], lambda f: f.get(OPEN.name))
        self.record("open")
        controls = self.controls(dialog)
        name = self._file_name_edit(controls)
        button = _require(_child(controls, cls="Button", id=1, text="&Open"), "Open (1)")
        self.fill_path(name, ckp, [OPEN])
        self.press(dialog, button)
        last: list[object] = [None]
        begun = [False]

        def opened(found: dict[str, Window]) -> bool:
            main = found.get(MAIN)
            state = _scr_state(temp)
            if (
                PROJECT_READING.name in found
                or (main is not None and _project_file(main.title) is None)
                or (state and state != before)
            ):
                begun[0] = True
            if not begun[0]:
                return False
            if main is None or _project_file(main.title) != ckp.name or not self.only_main(found):
                return False
            done = bool(state) and state == last[0]
            last[0] = state
            return done

        self.wait(
            f"{ckp.name} to open",
            [OPEN, PROJECT_READING],
            opened,
            unloading=True,
            timeout=self.s.paste_timeout,
        )
        self.log(f"opened {ckp}")
        self.record("opened")

    def fill_path(self, edit: Control, path: Path, expected: list[Expect]) -> None:
        """Set a file dialog's File name *edit* to *path*, and wait until it has read *path*
        for ``FILL_SETTLE`` seconds, setting it again whenever it reads something else.

        A dialog that is still opening can empty the edit after the path is set. CLICK's Read
        Data Save dialog, filled as soon as it showed, then saved plcdata.csv into the folder
        it last saved in. Live run d8 (2026-11-16) wrote the file there. The D2 runs r1 and
        r1c met that file as "plcdata.csv already exists". In r1e the edit read '' once set.
        When the dialog was filled after a ``--record`` dump, it kept the path (d7, d10 to
        d13).
        """
        text = str(path)
        held: list[float | None] = [None]

        def holds(found: dict[str, Window]) -> bool:
            now = self.desktop.read_text(edit.hwnd)
            if now != text:
                if held[0] is not None:
                    self.log(f"the File name edit reads {now!r}; setting the path again")
                held[0] = None
                self.desktop.set_text(edit.hwnd, text)
                return False
            if held[0] is None:
                held[0] = time.monotonic()
            return time.monotonic() - held[0] >= FILL_SETTLE

        self.desktop.set_text(edit.hwnd, text)
        self.wait("the File name edit to keep the path", expected, holds)

    def _file_name_edit(self, controls: list[Control]) -> Control:
        """A file dialog's File name edit: the Edit 1148 inside the ComboBox 1148."""
        boxes = {c.hwnd for c in controls if c.cls == "ComboBox" and c.id == 1148}
        return _require(
            next(
                (c for c in controls if c.cls == "Edit" and c.id == 1148 and c.parent in boxes),
                None,
            ),
            "the File name edit (1148)",
        )

    def save(self) -> Path:
        assert self.main is not None and self.s.csv is not None
        ckp = (self.s.out / f"{self.s.csv.stem}.ckp").resolve()
        temp = self.desktop.temp_dir(self.main)
        with self.step("save"):
            self.save_as(ckp, temp)
            stale = sorted(set(self._scr_before) & set(_scr_state(temp)))
            if stale:
                raise Aborted(
                    f"{', '.join(name for name, _, _ in stale)} in CLICK's temp folder "
                    "predates the paste, and the save did not change it. It may be left over "
                    "from another run."
                )
            self.result["files"]["ckp"] = ckp
        with self.step("copy"):
            self.result["files"]["click"] = self.copy_temp(temp, self.s.out / "click")
        return ckp

    def save_as(self, ckp: Path, temp: Path, *, prefix: str = "") -> None:
        """Save the project as *ckp*, a file that does not exist, and wait until CLICK saved.

        CLICK has saved once its title names the file, the file exists, and its Scr*.tmp
        files in *temp* differ from before Save As and are the same on two polls in a row.
        The dumps of ``--record`` are labelled *prefix* then ``save_as`` and ``saved``.
        """
        unsaved = _scr_state(temp)
        self.command(SAVE_PROJECT_AS)
        dialog = self.wait("Save As", [SAVE_AS], lambda f: f.get(SAVE_AS.name))
        self.record(f"{prefix}save_as")
        controls = self.controls(dialog)
        name = self._file_name_edit(controls)
        button = _require(_child(controls, cls="Button", id=1, text="&Save"), "Save (1)")
        self.fill_path(name, ckp, [SAVE_AS])
        self.press(dialog, button)
        last: list[object] = [None]

        def saved(found: dict[str, Window]) -> bool:
            main = found.get(MAIN)
            if main is None or _project_file(main.title) != ckp.name or not ckp.is_file():
                return False
            if not self.only_main(found):
                return False
            state = _scr_state(temp)
            done = bool(state) and state != unsaved and state == last[0]
            last[0] = state
            return done

        self.wait(f"the save to {ckp.name}", [SAVE_AS], saved, timeout=self.s.paste_timeout)
        self.log(f"saved {ckp}")
        self.record(f"{prefix}saved")

    def copy_temp(self, temp: Path, click_dir: Path) -> list[Path]:
        """Copy CLICK's Scr*.tmp files and Project.ini from *temp* into *click_dir*.

        *click_dir* is a new folder. Return the files copied. The run stops if there is no
        Scr*.tmp.
        """
        from clicknick.utils.click_temp import scr_files

        click_dir.mkdir(parents=True)
        copied: list[Path] = []
        for path in [*scr_files(temp), temp / "Project.ini"]:
            if path.is_file():
                copied.append(Path(shutil.copy2(path, click_dir / path.name)))
            else:
                self.log(f"not found: {path}")
        if not any(p.name != "Project.ini" for p in copied):
            raise Aborted(f"no Scr*.tmp in {temp}")
        self.log(f"copied {', '.join(p.name for p in copied)} into {click_dir}")
        return copied

    def disconnect(self, *, label: str | None = "disconnected") -> None:
        self.command(DISCONNECT)
        prompt = self.wait(
            "Disconnect from PLC?",
            [DISCONNECT_PROMPT],
            lambda f: f.get(DISCONNECT_PROMPT.name),
        )
        controls = self.controls(prompt)
        _require(
            _child(controls, cls="Static", id=65535, text="Disconnect from PLC?"),
            "'Disconnect from PLC?'",
        )
        yes = _require(_child(controls, cls="Button", id=6, text="&Yes"), "Yes (6)")
        self.press(prompt, yes)
        self.wait("the main window, disconnected", [DISCONNECT_PROMPT], self.only_main)
        self.connected = False
        self.status_bar(label)
        if label:
            self.record(label)

    def close(self) -> None:
        assert self.main is not None and self.pid is not None
        with self.step("close"):
            self.desktop.close(self.main)
            # CLICK unloads the project first. The main window is titled bare, then goes
            self.wait(
                "CLICK to exit",
                [],
                lambda f: False,
                exits=True,
                unloading=True,
                timeout=self.s.paste_timeout,
            )
            self.result["click"]["closed"] = True
            self.log("CLICK exited")
            self.note_temp()

    def decode_saved(self) -> None:
        with self.step("decode"):
            saved = self.decode(self.s.out / "click", self.s.out / "csv")
            files = [saved.main_csv, *saved.subroutine_csvs]
            self.result["files"]["csv"] = files
            self.log(f"decoded {', '.join(p.name for p in files)}")
            self.check_landed(saved.main_csv)

    def decode_kept(self) -> None:
        """Decode each kept case's copy of CLICK's files and read the tags stored in it.

        The method reads every copy not read yet, after an abort too, and writes the case's
        line again with what was read. A copy that cannot be read keeps why in its ``error``.
        Once all are read, any such copy fails the step. A kept clipboard (``clip``) is
        decoded too, into ``DIR/saves/<label>.clip.csv``. Its ``clip_error`` names what in it
        laddercodec cannot read or write (``_decode_clip``), or says why it cannot be decoded
        at all. It fails nothing, since the clipboard may hold what laddercodec does not read
        yet. A carried case's copy, kept in the run it was tried in, is decoded into this
        run's ``DIR/saves/``.
        """
        from clicknick.utils.click_temp import scr_files

        with self.step("decode"):
            failed = []
            for entry in self.result["cases"]:
                kept = entry["kept"]
                if kept is None or kept["csv"] is not None or kept["error"] is not None:
                    continue
                # The case's number in this file names its folder. A carried case's save was
                # numbered in the run it was tried in, so it cannot collide with another case's
                label = f"case{entry['index']:02d}"
                click = Path(kept["ckp"]).with_suffix("") / "click"
                if kept.get("clip") is not None:
                    self.decode_kept_clip(label, kept)
                try:
                    saved = self.decode(click, self.s.out / "saves" / label / "csv")
                    kept["csv"] = [saved.main_csv, *saved.subroutine_csvs]
                    lines = saved.main_csv.read_text(encoding="utf-8").splitlines()
                    kept["main"] = lines[1:]
                    kept["legacy"] = [asdict(e) for e in saved.legacy_encodings]
                    kept["stored"] = {p.name: self.read_stored(p) for p in scr_files(click)}
                except Exception as exc:
                    kept["error"] = f"{type(exc).__name__}: {exc}"
                    failed.append(label)
                    self.log(f"{label}: could not be read: {kept['error']}")
                    self.write_case(entry)
                    continue
                self.log(f"{label}: main.csv {kept['main']!r}")
                self.write_case(entry)
            if failed:
                raise RuntimeError(f"the copies of {', '.join(failed)} could not be read")

    def decode_kept_clip(self, label: str, kept: dict[str, Any]) -> None:
        """Decode the clipboard that *kept* holds into ``DIR/saves/<label>.clip.csv``.

        ``clip_csv`` is None when the file is not written. ``clip_error`` keeps what in the
        clipboard laddercodec cannot read or write (``_decode_clip``), or why it cannot be
        decoded at all.
        """
        csv = self.s.out / "saves" / f"{label}.clip.csv"
        try:
            csv.parent.mkdir(parents=True, exist_ok=True)
            decoded = self.decode_clip(Path(kept["clip"]), csv)
        except Exception as exc:
            kept["clip_error"] = f"{type(exc).__name__}: {exc}"
            self.log(f"{label}: the clipboard could not be decoded: {kept['clip_error']}")
            return
        kept["clip_error"] = decoded.unreadable
        if decoded.written:
            kept["clip_csv"] = csv
            self.log(f"{label}: the clipboard decoded into {csv}")
        if decoded.unreadable is not None:
            self.log(f"{label}: laddercodec cannot read all of the clipboard: {decoded.unreadable}")

    def check_landed(self, main_csv: Path) -> None:
        """Abort unless the saved main program holds the rungs pasted.

        Nothing in CLICK shows that a paste is done, so this is the check. A paste that did
        not land leaves the new project's empty main program. That happens when another
        program took the clipboard, or when CLICK refused the payload.
        """
        from laddercodec import read_csv

        from clicknick.ladder.program import is_empty_rung, rung_fingerprint

        assert self.s.csv is not None
        pasted = read_csv(self.s.csv)
        saved = read_csv(main_csv)
        same = [rung_fingerprint(r) for r in pasted] == [
            rung_fingerprint(r) for r in saved[: len(pasted)]
        ]
        self.result["rungs"] = {"pasted": len(pasted), "saved_main": len(saved), "same": same}
        self.log(
            f"saved main: {len(saved)} rung(s) for {len(pasted)} pasted; the first "
            f"{len(pasted)} {'match' if same else 'differ from'} the CSV"
        )
        if len(saved) < len(pasted) or (
            not all(is_empty_rung(r) for r in pasted) and all(is_empty_rung(r) for r in saved)
        ):
            raise Aborted(
                f"the paste did not land: the saved main program has {len(saved)} rung(s) "
                f"({sum(not is_empty_rung(r) for r in saved)} not empty), {len(pasted)} pasted"
            )

    # -- cleanup --------------------------------------------------------------

    def abort(self, reason: str) -> None:
        """Dump every window, then end CLICK without saving and check it is gone."""
        self.log(f"ABORT: {reason}")
        if self.pid is None:
            return
        try:
            if self.desktop.alive(self.pid):
                self.dump(self.s.out / "abort", "abort")
        except Exception as exc:
            self.log(f"could not dump the windows: {exc!r}")
        if self.connected and self.main is not None and self.desktop.alive(self.pid):
            try:
                found, unexpected = classify(self.desktop.windows(self.pid), [])
                unexpected = self._without_tooltips(unexpected)
                if not self.desktop.idle(self.main, IDLE_TIMEOUT):
                    self.log("not disconnecting: CLICK does not answer")
                elif unexpected or not self.only_main(found):
                    self.log("not disconnecting: a dialog is open")
                else:
                    self.disconnect(label=None)
                    self.log("disconnected")
            except ClickErrorBox as exc:
                # Not what stopped the run: kept apart from click_error, which says it was
                self.result["cleanup_click_error"] = exc.code
                self.log(f"could not disconnect: {exc}")
            except Exception as exc:
                self.log(f"could not disconnect: {exc}")
        self.end_click()

    def end_click(self) -> None:
        """Terminate CLICK if it still runs and wait until it is gone.

        Its temp folder is left alone (CLICK looks after it); the log says whether it is there.
        """
        if self.pid is None:
            return
        if self.desktop.alive(self.pid):
            self.log("terminating CLICK")
            self.desktop.terminate(self.pid)
        deadline = time.monotonic() + self.s.timeout
        while self.desktop.alive(self.pid) and time.monotonic() < deadline:
            time.sleep(self.s.poll)
        gone = not self.desktop.alive(self.pid)
        self.result["click"]["closed"] = gone
        self.log("CLICK is gone" if gone else "CLICK is STILL RUNNING")
        if gone:
            self.note_temp()

    def note_temp(self) -> None:
        """Log whether CLICK's temp folder is there.

        CLICK looks after it, and the runner never deletes one.
        """
        if self.main is not None:
            temp = self.desktop.temp_dir(self.main)
            self.log(f"{temp} {'is still there' if temp.exists() else 'is gone'}")

    # -- the whole run -----------------------------------------------------------

    def execute(self) -> dict[str, Any]:
        out = self.s.out
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            self.result.update(status="refused", step="refuse", reason=f"{out} is not empty")
            return self.finish(write=False)
        out.mkdir(parents=True, exist_ok=True)
        self.log_path = out / "run.log"
        self.result["files"]["run_log"] = self.log_path
        self.log(f"{self.s.command} into {out}")
        # Every way out below writes result.json. Nothing is started until the checks pass
        refused: str | None = None
        try:
            with self.step("refuse"):
                self.refuse_checks()
        except Refused as exc:
            refused = str(exc)
        except KeyboardInterrupt:
            refused = "interrupted (Ctrl+C) before CLICK was started"
        except Exception as exc:
            refused = f"the checks before starting CLICK failed: {type(exc).__name__}: {exc}"
        if refused is not None:
            self.log(f"REFUSED: {refused}")
            self.result.update(status="refused", reason=refused)
            return self.finish()
        if self.s.command == "try":
            self.write_carried()

        try:
            try:
                self.launch()
                self.connect()
                if self.s.command == "paste":
                    self.paste()
                    self.syntax_check()
                    self.save()
                elif self.s.command == "try":
                    self.try_cases()
                elif self.s.command == "import":
                    self.import_csvs()
                elif self.s.command == "read-data":
                    self.read_data()
                elif self.s.command == "reopen":
                    self.reopen()
                elif self.s.command == "picker":
                    self.picker()
                if self.connected:
                    self.disconnect_step()
                if self.s.command == "paste":
                    self.close()
                else:
                    # End CLICK rather than meet a save prompt that nobody has recorded
                    # yet. The new project was never saved, or (try --keep) a Delete has
                    # changed it since. try leaves it changed too
                    with self.step("close"):
                        self.end_click()
                    if not self.result["click"]["closed"]:
                        raise Aborted("CLICK did not end")
            except Aborted as exc:
                if isinstance(exc, ClickErrorBox):
                    self.result["click_error"] = exc.code
                self.stop(str(exc))
            except KeyboardInterrupt:
                self.stop("interrupted (Ctrl+C)")
            except Exception as exc:
                self.stop(f"{type(exc).__name__}: {exc}")
        finally:
            self.end_click_surely()  # Whatever happened, no CLICK of the runner's outlives it
        if self.result["status"] is None and self.result["click"]["closed"] is not True:
            self.result.update(status="aborted", reason="CLICK did not end")

        if self.result["status"] is None and self.s.command == "paste":
            try:
                self.decode_saved()
            except Aborted as exc:
                self.result.update(status="aborted", reason=str(exc))
                self.log(f"ABORT: {exc}")
            except KeyboardInterrupt:
                self.result.update(status="aborted", reason="interrupted (Ctrl+C) while decoding")
                self.log("ABORT: interrupted (Ctrl+C) while decoding")
            except Exception as exc:
                self.result.update(status="aborted", reason=f"decoding failed: {exc}")
                self.log(f"ABORT: decoding failed: {exc}")
        if self.result["click"]["closed"] is True:
            if self.s.command == "import":
                self.read_after_click(self.read_imports, "reading the copies of SC_.mdb")
            elif self.s.command == "picker":
                self.read_after_click(self.read_mdb_copies, "reading the copies of SC_.mdb")
            elif self.s.command == "try" and self.s.keep:
                self.read_after_click(self.decode_kept, "decoding the kept cases")
        if self.result["status"] is None:
            self.result["status"] = "ok"
        return self.finish()

    def read_after_click(self, read: Callable[[], None], what: str) -> None:
        """Call *read* on the copies made while CLICK ran, once CLICK has ended, after an abort too.

        The imports or cases done before an abort keep what was read of them. The step that
        the abort names stays the result's step. A read that fails (*what* says which) stops a
        run that had not stopped.
        """
        stopped_at = self.result["step"] if self.result["status"] is not None else None
        try:
            read()
            return
        except KeyboardInterrupt:
            reason = f"interrupted (Ctrl+C) while {what}"
        except Exception as exc:
            reason = f"{what} failed: {type(exc).__name__}: {exc}"
        finally:
            if stopped_at is not None:
                self.result["step"] = stopped_at
        if self.result["status"] is None:
            self.result.update(status="aborted", reason=reason)
            self.log(f"ABORT: {reason}")
        else:
            self.log(reason)

    def stop(self, reason: str) -> None:
        """Abort the run for *reason*. Log a cleanup that is cut short (Ctrl+C again)."""
        self.result.update(status="aborted", reason=reason)
        try:
            self.abort(reason)
        except BaseException as exc:
            self.log(f"the cleanup was cut short: {exc!r}")

    def end_click_surely(self) -> None:
        """Call ``end_click`` unless CLICK is already known gone. Call it again if cut short.

        The method logs what still fails. The job that CLICK runs in (``Desktop.launch``) ends
        it when the runner's process ends.
        """
        if self.result["click"]["closed"] is True:
            return
        for _ in range(2):
            try:
                self.end_click()
                return
            except BaseException as exc:
                self.log(f"ending CLICK failed: {exc!r}")

    def disconnect_step(self) -> None:
        with self.step("disconnect"):
            self.disconnect()

    def finish(self, *, write: bool = True) -> dict[str, Any]:
        self.result["elapsed"] = round(time.monotonic() - self.started, 3)
        if self.s.command == "try" and self.cases:
            self.result["cases"].sort(key=lambda entry: entry["index"])
            answered = sum(entry["outcome"] is not None for entry in self.result["cases"])
            self.result["left"] = len(self.cases) - answered
        if write:
            self.result["files"]["result"] = self.s.out / "result.json"
        text = json.dumps(self.result, indent=2, default=_json_default)
        if write:
            self.log(f"status {self.result['status']}")
            (self.s.out / "result.json").write_text(text + "\n", encoding="utf-8")
        return json.loads(text)


def _project_file(title: str) -> str | None:
    """Return the project file that a main window's title names ("NewProject4.ckp"), or None.

    The title is ``CLICK Programming Software (Version4.00) - <file>.ckp``, then
    `` - [<program>]`` while a program is open, and `` (Not Responding)`` while CLICK
    does not answer.
    """
    title = title.removesuffix(_NOT_RESPONDING)
    prefix = _MAIN_TITLE.match(title)
    if prefix is None:
        return None
    match = re.match(r"(.+?\.ckp)(?: - .*)?$", title[prefix.end() :], re.IGNORECASE)
    return match.group(1) if match else None


def _scr_state(folder: Path) -> tuple[tuple[str, int, int], ...]:
    from clicknick.utils.click_temp import scr_files

    state = []
    for path in scr_files(folder):
        try:
            stat = path.stat()
        except OSError:
            return ()
        state.append((path.name, stat.st_size, stat.st_mtime_ns))
    return tuple(state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a number of cases above 0")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="click_runner.py",
        description="Drive CLICK v4 without a person at the keyboard. See this file's docstring.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", type=Path, required=True, help="a folder that is new or empty")
    common.add_argument("--click-exe", type=Path, default=DEFAULT_EXE, help="CLICK.exe to start")
    common.add_argument(
        "--password",
        default=None,
        help=f"Login password (default: CLICK_RUNNER_PASSWORD, else {DEFAULT_PASSWORD!r})",
    )
    common.add_argument(
        "--user-type",
        default=None,
        help="Login User Type to enter when CLICK leaves it empty "
        f"(default: CLICK_RUNNER_USER_TYPE, else {DEFAULT_USER_TYPE!r})",
    )
    common.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds each step may wait for a dialog (default {DEFAULT_TIMEOUT:g})",
    )
    common.add_argument(
        "--paste-timeout",
        type=float,
        default=DEFAULT_PASTE_TIMEOUT,
        help="the longest CLICK may stay busy pasting, checking, saving or closing, in seconds "
        f"(default {DEFAULT_PASTE_TIMEOUT:g})",
    )
    common.add_argument(
        "--plc",
        default=None,
        metavar="NAME",
        help="the PLC name that the status bar must show once connected (default: any)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    paste = commands.add_parser(
        "paste", parents=[common], help="paste one ladder CSV into the main program and save"
    )
    paste.add_argument("csv", type=Path, help="the ladder CSV")
    paste.add_argument("--record", action="store_true", help="also dump every window at each step")
    commands.add_parser(
        "record", parents=[common], help="connect, dump every window at each step, close"
    )
    tries = commands.add_parser(
        "try", parents=[common], help="ask CLICK's instruction dialogs whether they accept cases"
    )
    tries.add_argument("cases", type=Path, help="the cases (JSON; see load_cases)")
    tries.add_argument(
        "--keep",
        action="store_true",
        help="save each accepted case's project into DIR/saves/ and decode it once CLICK ends",
    )
    tries.add_argument(
        "--wire",
        action="store_true",
        help="place each case in a rung of its own. An output instruction goes behind a "
        f"contact {WIRE_CONTACT}. A contact drives a coil {WIRE_COIL}. With --keep, also copy "
        "each accepted rung to the clipboard",
    )
    tries.add_argument(
        "--resume",
        type=Path,
        default=None,
        metavar="PREV_DIR",
        help="reuse the answers from the run in PREV_DIR and try only the cases it left",
    )
    tries.add_argument(
        "--stop-after",
        type=_positive,
        default=None,
        metavar="N",
        help="stop cleanly after N cases have been tried in this run",
    )
    tries.add_argument("--record", action="store_true", help="also dump every window at each step")
    imports = commands.add_parser(
        "import",
        parents=[common],
        help="import a nickname CSV into CLICK and read what CLICK stored",
    )
    imports.add_argument("csv", type=Path, help="the nickname CSV")
    imports.add_argument(
        "--each-row",
        action="store_true",
        help="then import each line after the header on its own, in a file with the header",
    )
    imports.add_argument(
        "--record", action="store_true", help="also dump every window at each step"
    )
    reads = commands.add_parser(
        "read-data", parents=[common], help="read the PLC's data values into a file"
    )
    reads.add_argument("--record", action="store_true", help="also dump every window at each step")
    pickers = commands.add_parser(
        "picker", parents=[common], help="open CLICK's Address Picker and copy SC_.mdb around it"
    )
    pickers.add_argument(
        "--record", action="store_true", help="also dump every window at each step"
    )
    pickers.add_argument(
        "--key",
        action="append",
        default=[],
        dest="keys",
        metavar="KEY",
        help=f"a key to send to the grid or its editor: {', '.join(_VIRTUAL_KEYS)}, "
        "chars:TEXT (WM_CHAR), text:TEXT (WM_SETTEXT) or find:TEXT (the Find box, then "
        "Find). Repeat the option to send more keys",
    )
    pickers.add_argument("--ok", action="store_true", help="close the Address Picker by OK")
    reopens = commands.add_parser(
        "reopen",
        parents=[common],
        help="save, edit Project.ini, save, open that save and save again, copying each point",
    )
    reopens.add_argument(
        "--ini-add",
        default=None,
        metavar="LINES",
        help="ASCII lines to add to the end of the project's Project.ini before the second "
        r"save. Separate them with \n (a backslash, then n) or with line breaks",
    )
    reopens.add_argument(
        "--record", action="store_true", help="also dump every window at each step"
    )
    return parser


def settings_from(argv: list[str] | None, environ: dict[str, str] | None = None) -> Settings:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    return Settings(
        command=args.command,
        out=args.out.resolve(),
        csv=args.csv.resolve() if args.command in ("paste", "import") else None,
        each_row=getattr(args, "each_row", False),
        cases=args.cases.resolve() if args.command == "try" else None,
        keep=getattr(args, "keep", False),
        wire=getattr(args, "wire", False),
        resume=args.resume.resolve() if getattr(args, "resume", None) else None,
        stop_after=getattr(args, "stop_after", None),
        ini_add=getattr(args, "ini_add", None),
        keys=tuple(getattr(args, "keys", ())),
        ok=getattr(args, "ok", False),
        exe=args.click_exe,
        password=args.password or env.get("CLICK_RUNNER_PASSWORD") or DEFAULT_PASSWORD,
        user_type=args.user_type or env.get("CLICK_RUNNER_USER_TYPE") or DEFAULT_USER_TYPE,
        timeout=args.timeout,
        paste_timeout=args.paste_timeout,
        plc=args.plc,
        poll=POLL_INTERVAL,
        record=getattr(args, "record", False),
    )


@contextmanager
def _stdout_to_stderr() -> Iterator[None]:
    """Send what is printed to stdout to stderr, Python's and the process's (fd 1) alike.

    stdout carries only the result. Output from what runs on the way (an ODBC driver's
    notice, a DLL) must not get into it.
    """
    sys.stdout.flush()
    try:
        saved = os.dup(1)
        os.dup2(2, 1)
    except OSError:  # No fd 1 (pythonw), or it cannot be duplicated
        saved = None
    try:
        with redirect_stdout(sys.stderr):
            yield
    finally:
        if saved is not None:
            os.dup2(saved, 1)
            os.close(saved)


def main(argv: list[str] | None = None, desktop: Desktop | None = None, **run_args: Any) -> int:
    settings = settings_from(argv)
    if desktop is None:
        from click_desktop import Win32Desktop

        desktop = Win32Desktop()
    with _stdout_to_stderr():
        result = Run(desktop, settings, **run_args).execute()
    print(json.dumps(result, indent=2), flush=True)
    return {"ok": EXIT_OK, "aborted": EXIT_ABORTED}.get(result["status"], EXIT_REFUSED)


if __name__ == "__main__":
    sys.exit(main())
