"""Drive CLICK v4 unattended: paste a ladder CSV into a new project, check it, save it, decode it.

    uv run python devtools/click_runner.py paste CSV --out DIR [--record]
    uv run python devtools/click_runner.py record --out DIR

The runner starts its own CLICK, connects to the one PLC on the LAN (so the new project
takes that PLC's hardware) and answers "Don't read" to reading the PLC's project. ``paste``
then pastes CSV into the main program, runs Syntax Check, saves the project as
``DIR/<CSV name>.ckp``, copies CLICK's Scr*.tmp files and Project.ini into ``DIR/click/``,
disconnects, closes CLICK and decodes ``DIR/click/`` into ``DIR/csv/``. ``record`` connects
the same way and dumps every window of CLICK (JSON and PNG) at each step into
``DIR/record/``, then disconnects and ends CLICK (the project was never saved, so it is
terminated rather than closed); ``paste --record`` dumps the same way.

``DIR`` must not exist or be empty. The run ends with ``DIR/result.json``, printed on stdout
too, and logs each step to ``DIR/run.log`` and stderr. Exit code 0 when the status is
``ok``, 1 when ``aborted``, 2 when ``refused`` (nothing was started).

Rules (scratchpad/roadmap.md, item 4):

- It refuses to start while any CLICK.exe runs or any CLICK window is open, or while the
  input desktop is not ``Default`` (a locked screen). It touches only the CLICK it started:
  its windows are found by pid, its files in ``click_temp_dir`` of its main window.
- It never writes to the PLC: every WM_COMMAND goes through ``Desktop.command`` and its
  allowlist (click_desktop.py).
- Each step waits for a condition with a timeout. Any top-level window of CLICK that the
  step does not expect stops the run: every window is dumped into ``DIR/abort/``, CLICK is
  disconnected if it can be and then ended without saving. Every way out (a timeout, an
  error, Ctrl+C) goes through that cleanup.

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
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from click_desktop import (
    DISCONNECT,
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
POLL_INTERVAL = 0.1

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_REFUSED = 2

_MAIN_TITLE = re.compile(r"^CLICK Programming Software \(Version4\.\d+\) - ")
_SYNTAX_RESULT = re.compile(r"(\d+) error\(s\), (\d+) warning\(s\)\s*$")


class Refused(Exception):
    """The run must not start."""


class Aborted(Exception):
    """The run stops here; cleanup ends CLICK."""


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


def _json_default(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON: {value!r}")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    command: str  # "paste" or "record"
    out: Path
    csv: Path | None = None
    exe: Path = DEFAULT_EXE
    password: str = DEFAULT_PASSWORD
    user_type: str = DEFAULT_USER_TYPE
    timeout: float = DEFAULT_TIMEOUT
    poll: float = POLL_INTERVAL
    record: bool = False


def _prepare(csv: Path, mdb: Path | None):
    """Encode *csv* for the clipboard; with *mdb*, add its addresses to that SC_.mdb first."""
    from clicknick.ladder.program import prepare_csv_load

    return prepare_csv_load(csv, click_v4=True, mdb_path=mdb)


def _decode(click_dir: Path, csv_dir: Path):
    from clicknick.ladder.program import program_save

    return program_save(click_dir, csv_dir)


class Run:
    """One run of the runner against one CLICK it starts."""

    def __init__(
        self,
        desktop: Desktop,
        settings: Settings,
        *,
        prepare: Callable[[Path, Path | None], Any] = _prepare,
        decode: Callable[[Path, Path], Any] = _decode,
        stderr: Any = None,
    ) -> None:
        self.desktop = desktop
        self.s = settings
        self.prepare = prepare
        self.decode = decode
        self.stderr = sys.stderr if stderr is None else stderr
        self.started = time.monotonic()
        self.pid: int | None = None
        self.main: int | None = None
        self.connected = False
        self.log_path: Path | None = None
        self._dump_count = 0
        # Windows open before the main frame, and those of them still open
        self._tolerated: set[int] = set()
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
            "files": {},
            "click": {"exe": settings.exe, "pid": None, "main_hwnd": None, "closed": None},
        }

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

        The files are listed in the result under the folder's name.
        """
        assert self.pid is not None
        folder.mkdir(parents=True, exist_ok=True)
        self._dump_count += 1
        written: list[Path] = self.result["files"].setdefault(folder.name, [])
        count = len(written)
        for window in self.desktop.windows(self.pid):
            controls = []
            for control in self.desktop.controls(window.hwnd):
                row = asdict(control)
                if control.cls == "Edit":
                    row["edit_text"] = self.desktop.read_text(control.hwnd)
                controls.append(row)
            base = folder / f"{self._dump_count:02d}-{label}-{window.hwnd}"
            info = {**asdict(window), "controls": controls}
            base.with_suffix(".json").write_text(json.dumps(info, indent=1), encoding="utf-8")
            written.append(base.with_suffix(".json"))
            try:
                if self.desktop.screenshot(window.hwnd, base.with_suffix(".png")):
                    written.append(base.with_suffix(".png"))
            except Exception as exc:  # A screenshot is a nice-to-have
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
    ) -> T:
        """Poll CLICK's windows until *until* returns something other than None or False.

        Any window that is neither the main frame nor one of *expected* aborts the run,
        except one that was open before the main frame first appeared (CLICK starting up,
        a splash screen), until the launch step ends. CLICK exiting aborts too, unless
        *exits* (then the wait ends when it has).
        """
        assert self.pid is not None
        deadline = time.monotonic() + self.s.timeout
        while True:
            if not self.desktop.alive(self.pid):
                if exits:
                    return True  # pyright: ignore[reportReturnType]
                raise Aborted(f"CLICK exited while waiting for {what}")
            found, unexpected = classify(self.desktop.windows(self.pid), expected)
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
            if time.monotonic() > deadline:
                raise Aborted(f"timed out after {self.s.timeout:g} s waiting for {what}")
            time.sleep(self.s.poll)

    def only_main(self, found: dict[str, Window]) -> bool:
        """The main frame alone, enabled and answering messages."""
        main = found.get(MAIN)
        return (
            main is not None
            and len(found) == 1
            and main.enabled
            and self.desktop.idle(main.hwnd, self.s.timeout)
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

    def status_bar(self) -> None:
        """Log the status bar's WM_GETTEXT, to learn what it holds."""
        assert self.main is not None
        for control in self.desktop.controls(self.main):
            if control.cls.startswith("Afx:StatusBar"):
                self.log(f"status bar: {self.desktop.read_text(control.hwnd)!r}")
                return

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
            last: list[tuple[int, int] | None] = [None]

            def listed(_: dict[str, Window]) -> tuple[int, int] | None:
                # The LAN scan fills the list: take it once two polls in a row agree
                counts = self.desktop.list_view_counts(plc_list.hwnd)
                button = _child(self.controls(connect), cls="Button", id=1, text="Connect")
                ready = counts is not None and counts[0] >= 1 and button and button.enabled
                settled = counts if ready and counts == last[0] else None
                last[0] = counts
                return settled

            items, selected = self.wait("a PLC in the list", [STARTUP, CONNECT], listed)
            self.log(f"PLC list: {items} row(s), {selected} selected")
            if items != 1:
                raise Aborted(f"the Connect dialog lists {items} PLCs, expected exactly 1")
            if selected != 1:
                raise Aborted("the one PLC in the Connect dialog is not selected")
            self.record("connect_dialog")
            button = _require(
                _child(self.controls(connect), cls="Button", id=1, text="Connect"),
                "the Connect button",
            )
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
            except Aborted as exc:
                raise Aborted(f"'Don't read' did not take: {exc}") from exc
            self.press(prompt, ok)
            self.connected = True
            self.wait("the main window, connected", [STARTUP, CONNECT, READ_PROMPT], self.only_main)
            self.status_bar()
            self.record("connected")

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
            self.result["rungs"] = {"pasted": prepared.rung_count, "saved_main": None}
            self.desktop.set_clipboard(prepared.payload, self.main)
            self.command(PASTE)
            # A paste shows nothing when it is done, and WM_NULL can be answered before
            # CLICK takes the posted paste. Posted commands run in order, though, so the
            # Syntax Check posted next runs after the paste, and its result is the check.
            self.wait("the main window after the paste", [], self.only_main)
            self.status_bar()
            self.record("pasted")

    def syntax_check(self) -> None:
        assert self.main is not None
        with self.step("syntax_check"):
            controls = self.desktop.controls(self.main)
            bars = {
                c.hwnd
                for c in controls
                if c.cls.startswith("Afx:ControlBar") and c.text == "Output"
            }
            output = _require(
                next(
                    (c for c in controls if c.cls == "Edit" and c.id == 1005 and c.parent in bars),
                    None,
                ),
                "the Output pane's Edit (1005)",
            )
            before = self.desktop.read_text(output.hwnd)
            self.command(SYNTAX_CHECK)

            def finished(found: dict[str, Window]) -> re.Match[str] | None:
                if not self.only_main(found):
                    return None
                text = self.desktop.read_text(output.hwnd)
                if not text or text == before:
                    return None
                return _SYNTAX_RESULT.search(text)

            match = self.wait("the Syntax Check result in Output", [], finished)
            text = self.desktop.read_text(output.hwnd) or ""
            self.result["syntax_check"] = {
                "text": text,
                "errors": int(match.group(1)),
                "warnings": int(match.group(2)),
            }
            self.log(f"Syntax Check: {match.group(0).strip()}")
            self.record("syntax_checked")

    def save(self) -> Path:
        assert self.main is not None and self.s.csv is not None
        ckp = (self.s.out / f"{self.s.csv.stem}.ckp").resolve()
        temp = self.desktop.temp_dir(self.main)
        with self.step("save"):
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
                # files are the same on two polls in a row
                main = found.get(MAIN)
                if main is None or f" - {ckp.name} - " not in main.title or not ckp.is_file():
                    return False
                if not self.only_main(found):
                    return False
                state = _scr_state(temp)
                done = bool(state) and state == last[0]
                last[0] = state
                return done

            self.wait(f"the save to {ckp.name}", [SAVE_AS], saved)
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
        self.status_bar()
        if label:
            self.record(label)

    def close(self) -> None:
        assert self.main is not None and self.pid is not None
        with self.step("close"):
            self.desktop.close(self.main)
            self.wait("CLICK to exit", [], lambda f: False, exits=True)
            self.result["click"]["closed"] = True
            self.log("CLICK exited")

    def decode_saved(self) -> None:
        with self.step("decode"):
            saved = self.decode(self.s.out / "click", self.s.out / "csv")
            files = [saved.main_csv, *saved.subroutine_csvs]
            self.result["files"]["csv"] = files
            main = next((p for p in saved.programs if p.prog_idx == 1), None)
            if self.result["rungs"] is not None and main is not None:
                self.result["rungs"]["saved_main"] = main.rung_count
            self.log(f"decoded {', '.join(p.name for p in files)}")

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
                if unexpected or not self.only_main(found):
                    self.log("not disconnecting: a dialog is open")
                else:
                    self.disconnect(label=None)
                    self.log("disconnected")
            except Exception as exc:
                self.log(f"could not disconnect: {exc}")
        self.end_click()

    def end_click(self) -> None:
        """Terminate CLICK if it still runs and wait until it is gone."""
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
        if gone and self.main is not None:
            # CLICK deletes its temp folder when it closes, not when it is ended
            temp = self.desktop.temp_dir(self.main)
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
                self.log(f"removed {temp}")

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
        try:
            with self.step("refuse"):
                self.refuse_checks()
        except Refused as exc:
            self.log(f"REFUSED: {exc}")
            self.result.update(status="refused", reason=str(exc))
            return self.finish()

        try:
            try:
                self.launch()
                self.connect()
                if self.s.command == "paste":
                    self.paste()
                    self.syntax_check()
                    self.save()
                self.disconnect_step()
                if self.s.command == "paste":
                    self.close()
                else:
                    # The new project was never saved: end CLICK rather than meet a
                    # save prompt nobody has recorded yet
                    with self.step("close"):
                        self.end_click()
                    if not self.result["click"]["closed"]:
                        raise Aborted("CLICK did not end")
            except Aborted as exc:
                self.result.update(status="aborted", reason=str(exc))
                self.abort(str(exc))
            except KeyboardInterrupt:
                self.result.update(status="aborted", reason="interrupted (Ctrl+C)")
                self.abort("interrupted (Ctrl+C)")
            except Exception as exc:
                self.result.update(status="aborted", reason=f"{type(exc).__name__}: {exc}")
                self.abort(f"{type(exc).__name__}: {exc}")
        finally:
            self.end_click()  # Whatever happened, no CLICK of the runner's outlives it

        if self.result["status"] is None and self.s.command == "paste":
            try:
                self.decode_saved()
            except Exception as exc:
                self.result.update(status="aborted", reason=f"decoding failed: {exc}")
                self.log(f"ABORT: decoding failed: {exc}")
        if self.result["status"] is None:
            self.result["status"] = "ok"
        return self.finish()

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
        help=f"seconds each step may take (default {DEFAULT_TIMEOUT:g})",
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
    return parser


def settings_from(argv: list[str] | None, environ: dict[str, str] | None = None) -> Settings:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    return Settings(
        command=args.command,
        out=args.out.resolve(),
        csv=args.csv.resolve() if args.command == "paste" else None,
        exe=args.click_exe,
        password=args.password or env.get("CLICK_RUNNER_PASSWORD") or DEFAULT_PASSWORD,
        user_type=args.user_type or env.get("CLICK_RUNNER_USER_TYPE") or DEFAULT_USER_TYPE,
        timeout=args.timeout,
        poll=POLL_INTERVAL,
        record=getattr(args, "record", False),
    )


def main(argv: list[str] | None = None, desktop: Desktop | None = None, **run_args: Any) -> int:
    settings = settings_from(argv)
    if desktop is None:
        from click_desktop import Win32Desktop

        desktop = Win32Desktop()
    result = Run(desktop, settings, **run_args).execute()
    print(json.dumps(result, indent=2))
    return {"ok": EXIT_OK, "aborted": EXIT_ABORTED}.get(result["status"], EXIT_REFUSED)


if __name__ == "__main__":
    sys.exit(main())
