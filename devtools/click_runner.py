"""Drive CLICK v4 unattended: paste a ladder CSV into a new project, check it, save it, decode it.

    uv run python devtools/click_runner.py paste CSV --out DIR [--record]
    uv run python devtools/click_runner.py record --out DIR
    uv run python devtools/click_runner.py try CASES.json --out DIR [--record]

The runner starts its own CLICK, connects to the one PLC on the LAN (so the new project
takes that PLC's hardware) and answers "Don't read" to reading the PLC's project. ``paste``
then pastes CSV into the main program, runs Syntax Check, saves the project as
``DIR/<CSV name>.ckp``, copies CLICK's Scr*.tmp files and Project.ini into ``DIR/click/``,
disconnects, closes CLICK and decodes ``DIR/click/`` into ``DIR/csv/``. ``record`` connects
the same way and dumps every window of CLICK (JSON and PNG) at each step into
``DIR/record/``, then disconnects and ends CLICK (the project was never saved, so it is
terminated rather than closed); ``paste --record`` and ``try --record`` dump the same way.
A PNG is the screen where the window is, so whatever lies over CLICK there is in it.

``try`` asks CLICK's instruction dialogs whether they accept an instruction (``CASES``).
Once connected, it copies the new project's SC_.mdb to ``DIR/SC_.mdb`` and reads the
nicknames of the addresses CASES.json lists under ``nicknames`` from the copy (a new
project's SC_.mdb holds few: live run try3 found SC202, SC203 and SD13 only). It runs Syntax
Check on the empty main program (``baseline_syntax_check``), then, for each case: opens the
instruction's dialog from the ribbon's command at the ladder's cursor, picks its mode (a
mode button already checked is left alone: Math empties its fields on any type click), fills
its fields by WM_SETTEXT, reads them back and presses OK. CLICK either closes the dialog
(``accepted``) or shows an error box owned by it (``refused``, with the box's code and
message); the box's OK and the dialog's Cancel then close both. An accepted case gets a
Syntax Check of its own (the lines naming a code the empty program's check does not), then
Edit > Delete removes the instruction, and the next Syntax Check must read as the empty
program's did. A Syntax Check whose Output stays empty while CLICK is idle is posted again
(``SYNTAX_REPOST_AFTER``): in live run try3 CLICK ran 1 of the 30 posted just after a
Delete. All cases run in one CLICK, which is then disconnected and ended, as ``record`` ends
it. result.json holds one entry per case under ``cases``, in the order tried, and an abort
keeps the entries done before it.

``DIR`` must not exist or be empty. The run ends with ``DIR/result.json``, however it ends,
and prints it on stdout (nothing else goes there); each step is logged to ``DIR/run.log``
and stderr. Exit code 0 when the status is ``ok``, 1 when ``aborted``, 2 when ``refused``
(nothing was started). result.json holds the status, the step reached and the reason, the
Syntax Check's text with its error and warning counts, the rungs pasted and saved
(``same`` when the saved main program starts with the CSV's rungs), the PLC the status
bar named once connected (``plc``), the status bar's panes at each step, the code of a
CLICK error box that stopped the run (``click_error``; one met while the cleanup
disconnects is ``cleanup_click_error``), the files written, and how long each step took.

Rules (scratchpad/roadmap.md, item 4):

- It refuses to start while any CLICK.exe runs or any CLICK window is open, or while the
  input desktop is not ``Default`` (a locked screen). It touches only the CLICK it started:
  its windows are found by pid, its files in ``click_temp_dir`` of its main window. It
  never deletes a temp folder: CLICK looks after its own.
- It never writes to the PLC: every WM_COMMAND goes through ``Desktop.command`` and its
  allowlist (click_desktop.py).
- It connects only when the Connect dialog scans the same LAN and its PLC list has read
  one PLC for ``PLC_SETTLE`` seconds; two or more stop the run. Once connected, the status
  bar must name a PLC (``plc`` in result.json; ``--plc NAME`` requires that one) within
  ``--timeout``. A bar that cannot be read in that time leaves the connection unconfirmed,
  unless ``--plc`` is given: then the run stops.
- A Scr*.tmp in CLICK's temp folder before the paste (``scr_before_paste``) that the save
  does not rewrite stops the run: it would be decoded with the project.
- Each step waits for a condition. Waiting for a dialog gives up after ``--timeout``
  seconds (default 60). CLICK freezes while it pastes, so the paste, Syntax Check, save
  and close may take up to ``--paste-timeout`` (default 300); live run 7 (2026-11-15)
  saw a paste of 301 rungs freeze it for 16 s and their Syntax Check for 6 s. The paste
  is done when CLICK answers again and, if its status bar can be read, shows the rungs
  pasted; the saved main program holding them is the final check. Nothing is sent to a
  CLICK that does not answer, and a wait logs the status bar every ``STATUS_EVERY``
  seconds.
- A CLICK error box (a dialog whose text is a code on a line of its own, then a message:
  "PTC-013", "Timeout on attempting to connect to PLC.") stops the run at any step, with
  the code in ``click_error`` so a caller can decide to run again. Nothing is pressed in it.
  A box met while the cleanup disconnects after another stop is logged and kept as
  ``cleanup_click_error``; it is not what stopped the run. The one exception is ``try``:
  a box owned by an instruction dialog after its OK is the case's answer. A box there with
  no code, or with buttons other than one OK, is a question the runner does not answer:
  the case is kept as ``other`` and the run stops.
- Any top-level window of CLICK that the step does not expect (a tooltip aside) stops the
  run: every window is dumped into ``DIR/abort/`` (a window that does not answer without
  its edit text or a PNG), CLICK is disconnected if it answers with no dialog open, then
  ended without saving. A timeout, an error or Ctrl+C ends the same way. CLICK runs in a
  job that ends it when the runner's process ends, however that ends.

Login: CLICK fills in User Type itself (``admin``); the runner fills it in only when it is
empty, from ``--user-type`` or ``CLICK_RUNNER_USER_TYPE`` (default ``admin``). The password
comes from ``--password`` or ``CLICK_RUNNER_PASSWORD`` (default ``123click``). A PLC with
no password shows no Login dialog.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from click_desktop import (
    COPY_DIALOG,
    DELETE,
    DISCONNECT,
    MATH_DIALOG,
    OUT_DIALOG,
    PASTE,
    SAVE_PROJECT_AS,
    SYNTAX_CHECK,
    Control,
    Desktop,
    Window,
)

DEFAULT_EXE = Path(r"C:\Program Files (x86)\AutomationDirect\CLICK Ver4.00\CLICK.exe")
DEFAULT_PASSWORD = "123click"
DEFAULT_USER_TYPE = "admin"
DEFAULT_TIMEOUT = 60.0
# The ceiling for the steps CLICK may be busy in (paste, Syntax Check, save, close): CLICK
# freezes until a paste is done
DEFAULT_PASTE_TIMEOUT = 300.0
POLL_INTERVAL = 0.1
# How long one check waits for CLICK to answer (WM_NULL); a busy CLICK is no error
IDLE_TIMEOUT = 2.0
# After a paste, CLICK answers on this many polls in a row before the paste is done
RESPONSIVE_POLLS = 3
# How often a wait logs the status bar (or that CLICK does not answer)
STATUS_EVERY = 10.0
# Seconds Output may stay empty, CLICK idle, before Syntax Check is posted again, and the most
# posts. CLICK writes the check's header at once; live run try1 (2026-11-15) met a Syntax
# Check posted just after Delete that CLICK never ran (MFC drops a posted command that is
# disabled when it arrives, which is the likely cause).
SYNTAX_REPOST_AFTER = 5.0
SYNTAX_POSTS = 3
STATUS_BAR_ID = 59393  # AFX_IDW_STATUS_BAR
# The Connect dialog's PLC list is taken once it reads the same for this many seconds:
# the LAN scan adds its rows one at a time
PLC_SETTLE = 2.0

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

    The control ids are those of the dialog's template in CLICK's Inst_<name>.dll, as the
    live probe of 2026-11-15 found them in the open dialogs. A mode is a radio button.
    """

    command: int
    title: str
    fields: dict[str, int]  # A field's name -> its edit's control id
    modes: dict[str, int]  # A mode's name -> its radio button's id


INSTRUCTIONS = {
    # Result is an Edit, the formula a RichEdit20W. Picking Hex empties both
    "math": Instruction(
        MATH_DIALOG,
        "Math",
        {"result": 2001, "formula": 2006},
        {"decimal": 2003, "hex": 2004},
    ),
    # "to" fields are the end of a range: Block and Pack take a source range, Unpack a
    # destination range; Block shows the destination's end, which CLICK works out itself
    "copy": Instruction(
        COPY_DIALOG,
        "Copy",
        {"source": 5006, "source_end": 5009, "destination": 5014, "destination_end": 5017},
        {"single": 5000, "block": 5001, "fill": 5002, "pack": 5003, "unpack": 5004},
    ),
    # Out/Toggle, the dialog's first output type, is picked when it opens
    "out": Instruction(OUT_DIALOG, "Out", {"address": 5002, "address_end": 5003}, {}),
}


@dataclass(frozen=True)
class Case:
    """One instruction to try: the rule table's row, what is tried, and what is entered."""

    row: str  # The rule table's row ("A9")
    name: str  # What this case tries ("SD1")
    instruction: str  # A key of INSTRUCTIONS
    mode: str | None
    fields: dict[str, str]


def load_cases(path: Path) -> tuple[list[Case], list[str]]:
    """The cases in *path*, and the addresses whose nicknames to read; ValueError if malformed.

    The file is ``{"cases": [{"row", "case", "instruction", "mode", "fields"}, ...],
    "nicknames": ["SD21", ...]}``. ``mode`` is required where the dialog has modes and
    refused where it has none; ``fields`` names the dialog's fields, each with its text.
    """
    from pyclickplc.addresses import parse_address

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("expected an object with a list under 'cases'")
    cases: list[Case] = []
    for number, entry in enumerate(data["cases"], 1):
        where = f"case {number}"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} is not an object")
        unknown = set(entry) - {"row", "case", "instruction", "mode", "fields"}
        if unknown:
            raise ValueError(f"{where} has unknown keys: {', '.join(sorted(unknown))}")
        row, name = entry.get("row"), entry.get("case")
        if not isinstance(row, str) or not row or not isinstance(name, str) or not name:
            raise ValueError(f"{where} needs a 'row' and a 'case'")
        where = f"case {number} ({row} {name})"
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
        cases.append(Case(row, name, entry["instruction"], mode, dict(fields)))
    nicknames = data.get("nicknames", [])
    if not isinstance(nicknames, list) or not all(isinstance(a, str) for a in nicknames):
        raise ValueError("'nicknames' must be a list of addresses")
    for address in nicknames:
        parse_address(address)  # ValueError names the address
    return cases, nicknames


def _is_main(window: Window) -> bool:
    return (
        window.owner == 0
        and window.cls.startswith("Afx:")
        and bool(_MAIN_TITLE.match(window.title))
    )


def _describe(window: Window) -> str:
    return f"{window.cls!r} {window.title!r} (hwnd {window.hwnd}, owner {window.owner})"


def classify(
    windows: list[Window], expected: list[Expect]
) -> tuple[dict[str, Window], list[Window]]:
    """Match *windows* to the main frame and *expected*: (name -> window, windows matching none).

    Each expectation matches at most one window, and only one owned by the window its
    ``owner`` names, so a second Login, or a Login owned by the wrong dialog, is unexpected.
    """
    found: dict[str, Window] = {}
    rest = list(windows)
    mains = [w for w in rest if _is_main(w)]
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
    """The (code, message) of *window* if it is a CLICK error box, else None.

    Live run 3 (2026-11-15) met one during connect: a ``#32770`` titled "CLICK Programming
    Software", an OK button (id 2) and a Static reading "PTC-013" and, on the next line,
    "Timeout on attempting to connect to PLC.".
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


def _require(control: Control | None, what: str) -> Control:
    if control is None:
        raise Aborted(f"{what} not found")
    return control


@dataclass(frozen=True)
class StatusBar:
    """The panes of the main window's status bar.

    Live run 2 (2026-11-15) read, offline: "", "Bit", "Integer", "Integer(2 words)",
    "Floating point", "Hex", "Text", "Ascii", "-----", "0000/8000" (program steps),
    "No select CPU", "1:1:A" (cursor), five empty panes, "NUM", "". Live run 4, connected:
    "RUN" in place of "-----", "C2-03CPU", and "192.168.1.241(Conformance)" three panes
    after the cursor; disconnected again: "Offline" and "No select CPU".
    """

    panes: tuple[str, ...]

    @property
    def rung(self) -> int | None:
        """The cursor pane's rung ("2:1:A" is rung 2)."""
        match = _CURSOR.search("  ".join(self.panes))
        return int(match.group(1)) if match else None

    @property
    def steps(self) -> int | None:
        """The program steps used ("0004/8000" is 4)."""
        match = _STEPS.search("  ".join(self.panes))
        return int(match.group(1)) if match else None

    @property
    def plc(self) -> str | None:
        """The pane naming the PLC connected to ("192.168.1.241(Conformance)"), if any."""
        return next((p.strip() for p in self.panes if _PLC_PANE.match(p.strip())), None)

    @property
    def plc_name(self) -> str | None:
        """The PLC's name in the ``plc`` pane ("Conformance")."""
        plc = self.plc
        return plc[plc.index("(") + 1 : -1] if plc else None

    def shows_paste(self, before: StatusBar, rungs: int) -> bool:
        """Whether this reading, against *before* the paste, shows *rungs* rungs pasted.

        The cursor moves down by the rungs pasted, or the program steps rise. Live run 4
        (2026-11-15) saw the steps stay at 0000/8000 after a paste of a rung with a contact
        and a coil, so the cursor is what shows a paste; a rise of the steps is taken too.
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
    command: str  # "paste", "record" or "try"
    out: Path
    csv: Path | None = None
    cases: Path | None = None  # try's CASES.json
    exe: Path = DEFAULT_EXE
    password: str = DEFAULT_PASSWORD
    user_type: str = DEFAULT_USER_TYPE
    timeout: float = DEFAULT_TIMEOUT
    paste_timeout: float = DEFAULT_PASTE_TIMEOUT
    plc: str | None = None  # The PLC's name the status bar must show once connected
    poll: float = POLL_INTERVAL
    record: bool = False


def _prepare(csv: Path, mdb: Path | None):
    """Encode *csv* for the clipboard; with *mdb*, add its addresses to that SC_.mdb first."""
    from clicknick.ladder.program import prepare_csv_load

    return prepare_csv_load(csv, click_v4=True, mdb_path=mdb)


def _decode(click_dir: Path, csv_dir: Path):
    from clicknick.ladder.program import program_save

    return program_save(click_dir, csv_dir)


def _read_nicknames(mdb: Path, addresses: list[str]) -> dict[str, str | None]:
    """Each of *addresses*' nickname in the SC_.mdb at *mdb*; None where it has no row."""
    from pyclickplc.addresses import get_addr_key, parse_address

    from clicknick.utils.mdb_operations import MdbConnection, load_all_addresses

    with MdbConnection(str(mdb)) as connection:
        rows = load_all_addresses(connection)
    found: dict[str, str | None] = {}
    for address in addresses:
        row = rows.get(get_addr_key(*parse_address(address)))
        found[address] = None if row is None else row.nickname
    return found


class Run:
    """One run of the runner against one CLICK it starts."""

    def __init__(
        self,
        desktop: Desktop,
        settings: Settings,
        *,
        prepare: Callable[[Path, Path | None], Any] = _prepare,
        decode: Callable[[Path, Path], Any] = _decode,
        read_nicknames: Callable[[Path, list[str]], dict[str, str | None]] = _read_nicknames,
        stderr: Any = None,
    ) -> None:
        self.desktop = desktop
        self.s = settings
        self.prepare = prepare
        self.decode = decode
        self.read_nicknames = read_nicknames
        self.cases: list[Case] = []
        self.nickname_addresses: list[str] = []
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
                cases_file=settings.cases, nicknames=None, baseline_syntax_check=None, cases=[]
            )

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

        The PNG is the screen where the window is, windows over it included. The files
        are listed in the result under the folder's name.
        """
        assert self.pid is not None
        folder.mkdir(parents=True, exist_ok=True)
        self._dump_count += 1
        written: list[Path] = self.result["files"].setdefault(folder.name, [])
        count = len(written)
        for window in self.desktop.windows(self.pid):
            # A window that closed since it was listed (CLICK closing) is left out
            if not self.desktop.exists(window.hwnd):
                continue
            # Listing sends CLICK no message, and neither does the screenshot, but a window
            # that does not answer is drawn as Windows' ghost: no edit text and no PNG then
            answers = self.desktop.idle(window.hwnd, IDLE_TIMEOUT)
            if not answers:
                self.log(f"{window.hwnd} does not answer: its dump has no edit text and no PNG")
            controls = []
            for control in self.desktop.controls(window.hwnd):
                row = asdict(control)
                if control.cls == "Edit" and answers:
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
            except Exception as exc:  # A screenshot is a nice-to-have
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

        Any window that is neither the main frame nor one of *expected* aborts the run,
        except one that was open before the main frame first appeared (CLICK starting up,
        a splash screen), until the launch step ends. CLICK exiting aborts too, unless
        *exits* (then the wait ends when it has). With *unloading*, the main window is
        expected whatever its title: CLICK titles it bare while it closes. A CLICK error
        box aborts at once (``check_error_boxes``), except one owned by the window
        *answering* names (an instruction dialog whose OK was pressed). It gives up after
        *timeout* seconds (default ``Settings.timeout``), with a reason that starts with
        *on_timeout*'s text when it is given. Every ``STATUS_EVERY`` seconds it logs the
        status bar, or that CLICK does not answer.
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
            found, unexpected = classify(windows, expected)
            if unloading and MAIN not in found:
                for window in unexpected:
                    if window.hwnd == self.main:
                        found[MAIN] = window
                        unexpected.remove(window)
                        break
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

        Nothing is pressed in it; the cleanup that follows leaves it open (a dialog is open,
        so it does not disconnect) and ends CLICK.
        """
        for window in windows:
            if window.cls != "#32770":
                continue
            error = click_error(window, self.desktop.controls(window.hwnd))
            if error is not None:
                raise ClickErrorBox(*error)

    def _without_tooltips(self, windows: list[Window]) -> list[Window]:
        """*windows* but tooltips, each logged the first time it is seen."""
        for window in windows:
            if window.cls == TOOLTIP_CLASS and window.hwnd not in self._tooltips:
                self._tooltips.add(window.hwnd)
                self.log(f"a tooltip, let be: {_describe(window)}")
        return [w for w in windows if w.cls != TOOLTIP_CLASS]

    def only_main(self, found: dict[str, Window]) -> bool:
        """The main frame alone, enabled and answering messages."""
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
        """BM_CLICK *button*, a button found among *window*'s controls."""
        if button.cls not in ("Button", "TButton") or button.hwnd not in {
            c.hwnd for c in self.controls(window)
        }:
            raise Aborted(f"{button.cls} {button.hwnd} is not a button of {_describe(window)}")
        self.log(f"press {button.text or button.cls}, id {button.id}, in {window.title!r}")
        self.desktop.press(button.hwnd)

    def command(self, command_id: int) -> None:
        assert self.main is not None
        name = self.desktop.command(self.main, command_id)
        self.log(f"command {name} ({command_id})")

    def read_status_bar(self) -> StatusBar | None:
        """The main window's status bar, by SB_GETTEXT; None if it cannot be read.

        CLICK's main window has two children with the status bar's id: an MFC bar
        (``Afx:StatusBar...``) and a common control. Live run 2 (2026-11-15) read the
        common control by SB_GETTEXT; the MFC bar is sent nothing. Call it only while
        CLICK answers: reading sends it messages.
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
                # One row, unchanged for PLC_SETTLE seconds, with Connect enabled; two or
                # more stop the run. The list is owner-drawn: CLICK paints its own highlight
                # and connects to its current row, and the list reports no selection (live
                # run 2), so the runner selects nothing.
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

        The bar is read until the wait times out. Then a bar that read but named no PLC
        stops the run; one that never read leaves the connection unconfirmed and the run
        goes on, unless ``--plc`` is given, which a bar that cannot be read cannot confirm.
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
        """The paste's done condition, for ``wait``.

        CLICK freezes while it pastes and shows nothing when it is done. Done is CLICK
        answering again, with the main window alone and enabled, on ``RESPONSIVE_POLLS``
        polls in a row; then, when the status bar showed a cursor or a step count before
        the paste, the status bar showing the rungs pasted (``StatusBar.shows_paste``).
        CLICK answering for ``Settings.timeout`` seconds without that aborts the run.
        The decoded save is the final check (``check_landed``).
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
                    f"not show the {rungs} rung(s) pasted: {' | '.join(now.panes)} "
                    f"(before: {' | '.join(before.panes)})"
                )
            return None

        return done

    def syntax_check(self) -> None:
        with self.step("syntax_check"):
            self.result["syntax_check"] = self.check_syntax()
            self.record("syntax_checked")

    def check_syntax(self) -> dict[str, Any]:
        """Run Syntax Check and wait for its result in Output: its text and counts.

        Output is emptied first (WM_SETTEXT), so a check that reads as the one before is
        still seen to finish; live probe 1 (2026-11-15) waited out a second check whose
        text was the first's.
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
        return {"text": text, "errors": int(match.group(1)), "warnings": int(match.group(2))}

    # -- try: CLICK's instruction dialogs -------------------------------------

    def try_cases(self) -> None:
        """Read the nicknames asked for, check the empty main program, then try each case."""
        if self.nickname_addresses:
            with self.step("nicknames"):
                self.copy_nicknames()
        with self.step("baseline"):
            baseline = self.check_syntax()
            self.result["baseline_syntax_check"] = baseline
            self.record("baseline")
        with self.step("try"):
            for number, case in enumerate(self.cases, 1):
                self.try_case(number, case, baseline)

    def copy_nicknames(self) -> None:
        """Copy the new project's SC_.mdb into DIR and read the nicknames asked for from the copy.

        CLICK's own file is only copied; the copy is what is opened.
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
        """Open *case*'s dialog, fill it, press OK and record CLICK's answer.

        The case's entry in ``cases``: its row, name, instruction, mode and fields, then
        ``outcome`` (``accepted``, ``refused`` or ``other``), the box's ``code`` and
        ``message`` (an accepted case has them only if CLICK closed the dialog along with
        a box), ``syntax_check`` for an accepted case (its text, counts, and the ``lines``
        naming a code the empty program's check does not) and ``seconds``.
        """
        instruction = INSTRUCTIONS[case.instruction]
        title = instruction.title
        what = f"case {number} ({case.row} {case.name})"
        label = f"case{number:02d}"
        entry: dict[str, Any] = {
            "row": case.row,
            "case": case.name,
            "instruction": title,
            "mode": case.mode,
            "fields": case.fields,
            "outcome": None,
            "code": None,
            "message": None,
            "syntax_check": None,
            "seconds": None,
        }
        self.result["cases"].append(entry)
        began = time.monotonic()
        self.log(f"{what}: {title} {case.mode or ''} {case.fields}")
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
        if case.mode is not None:
            radio = _require(
                _child(self.controls(dialog), cls="Button", id=instruction.modes[case.mode]),
                f"{title}'s {case.mode} button ({instruction.modes[case.mode]})",
            )
            # BM_CLICK is posted, and Math empties its fields on a type click even on the
            # type already checked: press only a button that is not, and fill after it
            if self.desktop.button_checked(radio.hwnd) != 1:
                self.press(dialog, radio)
                self.wait(
                    f"{title}'s {case.mode} button to be checked",
                    [dialog_expect],
                    lambda f: self.desktop.button_checked(radio.hwnd) == 1,
                )
                # Its click is handled in full once the dialog's thread answers again
                if not self.desktop.idle(dialog.hwnd, self.s.timeout):
                    raise Aborted(f"{what}: the {title} dialog stopped answering")
        controls = self.controls(dialog)
        for field, text in case.fields.items():
            field_id = instruction.fields[field]
            control = _require(
                next((c for c in controls if c.id == field_id and c.cls in _FIELD_CLASSES), None),
                f"{title}'s {field} field ({field_id})",
            )
            if not (control.visible and control.enabled):
                raise Aborted(
                    f"{what}: {title}'s {field} field ({field_id}) is not open for entry"
                    f"{f' in {case.mode} mode' if case.mode else ''}"
                )
            self.desktop.set_text(control.hwnd, text)
            if self.desktop.read_text(control.hwnd) != text:
                raise Aborted(f"{what}: {title}'s {field} field did not take {text!r}")
        for field, text in case.fields.items():
            control = next(c for c in controls if c.id == instruction.fields[field])
            if self.desktop.read_text(control.hwnd) != text:
                raise Aborted(f"{what}: {title}'s {field} field lost {text!r} before OK")
        self.record(f"{label}_filled")
        ok = _require(_child(controls, cls="Button", id=1, text="OK"), f"{title}'s OK (1)")
        self.press(dialog, ok)

        def answered(found: dict[str, Window]) -> Window | bool | None:
            if ANSWER_BOX in found:
                return found[ANSWER_BOX]
            return DIALOG not in found and self.only_main(found)

        answer = self.wait(f"CLICK's answer to {what}", expected, answered, answering=dialog.hwnd)
        self.record(f"{label}_answer")
        if isinstance(answer, Window):
            self.answer_box(what, entry, dialog, answer, expected)
        else:
            entry["outcome"] = "accepted"
        if entry["outcome"] == "accepted":
            self.log(f"{what}: accepted")
            check = self.check_syntax()
            known = {m.group(1) for m in _SYNTAX_CODE.finditer(baseline["text"])}
            entry["syntax_check"] = {
                **check,
                "lines": [
                    line.strip()
                    for line in check["text"].splitlines()
                    if (m := _SYNTAX_CODE.search(line)) and m.group(1) not in known
                ],
            }
            self.command(DELETE)
            self.wait(f"Delete after {what}", [], self.only_main)
            cleared = self.check_syntax()
            if cleared["text"] != baseline["text"]:
                raise Aborted(
                    f"after {what}, Delete did not leave the main program empty: its Syntax "
                    f"Check reads {cleared['text']!r}, the empty program's {baseline['text']!r}"
                )
        entry["seconds"] = round(time.monotonic() - began, 3)

    def answer_box(
        self,
        what: str,
        entry: dict[str, Any],
        dialog: Window,
        box: Window,
        expected: list[Expect],
    ) -> None:
        """Take CLICK's error box after OK as the case's answer, close it, Cancel the dialog.

        A box that is not one CLICK error with one OK is a question: the case is ``other``
        and the run stops. A dialog CLICK closed along with its box was accepted.
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
            entry["outcome"] = "accepted"
            return
        entry["outcome"] = "refused"
        cancel = _require(
            _child(self.controls(after[DIALOG]), cls="Button", id=2, text="Cancel"),
            f"{dialog.title}'s Cancel (2)",
        )
        self.press(after[DIALOG], cancel)
        self.wait(f"the {dialog.title} dialog to close", expected[:1], self.only_main)

    def save(self) -> Path:
        assert self.main is not None and self.s.csv is not None
        ckp = (self.s.out / f"{self.s.csv.stem}.ckp").resolve()
        temp = self.desktop.temp_dir(self.main)
        with self.step("save"):
            unsaved = _scr_state(temp)
            self.command(SAVE_PROJECT_AS)
            dialog = self.wait("Save As", [SAVE_AS], lambda f: f.get(SAVE_AS.name))
            self.record("save_as")
            controls = self.controls(dialog)
            boxes = {c.hwnd for c in controls if c.cls == "ComboBox" and c.id == 1148}
            name = _require(
                next(
                    (c for c in controls if c.cls == "Edit" and c.id == 1148 and c.parent in boxes),
                    None,
                ),
                "the File name edit (1148)",
            )
            button = _require(_child(controls, cls="Button", id=1, text="&Save"), "Save (1)")
            self.desktop.set_text(name.hwnd, str(ckp))
            if self.desktop.read_text(name.hwnd) != str(ckp):
                raise Aborted("the File name edit did not take the path")
            self.press(dialog, button)
            last: list[object] = [None]

            def saved(found: dict[str, Window]) -> bool:
                # Saved once the title names the file, it exists, and CLICK's Scr*.tmp
                # files differ from before Save As and are the same on two polls in a row
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
            stale = sorted(set(self._scr_before) & set(_scr_state(temp)))
            if stale:
                raise Aborted(
                    f"{', '.join(name for name, _, _ in stale)} in CLICK's temp folder "
                    "predates the paste and the save left it as it was (from another run?)"
                )
            self.log(f"saved {ckp}")
            self.result["files"]["ckp"] = ckp
            self.record("saved")
        with self.step("copy"):
            self.copy_temp(temp)
        return ckp

    def copy_temp(self, temp: Path) -> None:
        from clicknick.utils.click_temp import scr_files

        click_dir = self.s.out / "click"
        click_dir.mkdir()
        copied: list[Path] = []
        for path in [*scr_files(temp), temp / "Project.ini"]:
            if path.is_file():
                copied.append(Path(shutil.copy2(path, click_dir / path.name)))
            else:
                self.log(f"not found: {path}")
        if not any(p.name != "Project.ini" for p in copied):
            raise Aborted(f"no Scr*.tmp in {temp}")
        self.log(f"copied {', '.join(p.name for p in copied)} into {click_dir}")
        self.result["files"]["click"] = copied

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
            # CLICK unloads the project first: the main window is titled bare, then goes
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

    def check_landed(self, main_csv: Path) -> None:
        """Abort unless the saved main program holds the rungs pasted.

        Nothing in CLICK shows that a paste is done, so this is the check: a paste that
        did not land (the clipboard taken by another program, a payload CLICK refused)
        leaves the new project's empty main program.
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
        """Log whether CLICK's temp folder is there; CLICK looks after it, the runner never
        deletes one."""
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
        # Every way out below writes result.json; nothing is started until the checks pass
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
                self.disconnect_step()
                if self.s.command == "paste":
                    self.close()
                else:
                    # The new project was never saved: end CLICK rather than meet a
                    # save prompt nobody has recorded yet (try leaves it changed, too)
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
        if self.result["status"] is None:
            self.result["status"] = "ok"
        return self.finish()

    def stop(self, reason: str) -> None:
        """Abort the run for *reason*; a cleanup cut short (Ctrl+C again) is logged."""
        self.result.update(status="aborted", reason=reason)
        try:
            self.abort(reason)
        except BaseException as exc:
            self.log(f"the cleanup was cut short: {exc!r}")

    def end_click_surely(self) -> None:
        """``end_click`` unless CLICK is already known gone; tried again if it is cut short.

        What still fails is logged. The job CLICK runs in (``Desktop.launch``) ends it when
        the runner's process ends.
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
        if write:
            self.result["files"]["result"] = self.s.out / "result.json"
        text = json.dumps(self.result, indent=2, default=_json_default)
        if write:
            self.log(f"status {self.result['status']}")
            (self.s.out / "result.json").write_text(text + "\n", encoding="utf-8")
        return json.loads(text)


def _project_file(title: str) -> str | None:
    """The project file a main window's title names ("NewProject4.ckp"), or None.

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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="click_runner.py",
        description="Drive CLICK v4 unattended (see this file's docstring).",
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
        help="Login User Type when CLICK leaves it empty "
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
        help="the most seconds CLICK may stay busy pasting, checking, saving or closing "
        f"(default {DEFAULT_PASTE_TIMEOUT:g})",
    )
    common.add_argument(
        "--plc",
        default=None,
        metavar="NAME",
        help="the name of the PLC the status bar must show once connected (default: any)",
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
    tries.add_argument("--record", action="store_true", help="also dump every window at each step")
    return parser


def settings_from(argv: list[str] | None, environ: dict[str, str] | None = None) -> Settings:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    return Settings(
        command=args.command,
        out=args.out.resolve(),
        csv=args.csv.resolve() if args.command == "paste" else None,
        cases=args.cases.resolve() if args.command == "try" else None,
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

    stdout carries only the result: what runs on the way (an ODBC driver's notice, a DLL)
    must not get into it.
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
