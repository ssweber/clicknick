"""The CLICK runner (devtools/click_runner.py) against a fake CLICK.

No test launches CLICK or sends anything to a window. ``FakeClick`` plays CLICK v4's
dialog sequence as the probe of 2026-11-15 recorded it (classes, titles, owners, control
ids and texts from its dumps); a posted message takes effect on a later poll, as it does
in CLICK.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from laddercodec import read_csv
from laddercodec.model import Program

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtools"))

import click_desktop as cd  # noqa: E402
import click_runner as cr  # noqa: E402

from clicknick.ladder.program import empty_rung, prepare_csv_load  # noqa: E402

RUNG_CSV = (
    "marker,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF\n"
    "R,X001,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,out(Y001)\n"
)
MAIN_CLASS = "Afx:002E0000:8:00010003:00000000:10D30AE3"
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
    counts: tuple[int, int] = (0, 0)
    on_press: Callable[[], None] | None = None


@dataclass
class FakeWindow:
    hwnd: int
    cls: str
    title: str
    owner: int
    enabled: bool = True
    controls: list[FakeControl] = field(default_factory=list)
    on_close: Callable[[], None] | None = None


class FakeClick(cd.Desktop):
    """CLICK v4 as the probe saw it, with switches for what can go wrong.

    *surprise* names an event after which an unknown dialog appears; *stall* one whose
    effect never happens; *interrupt* a Desktop method that raises KeyboardInterrupt;
    *late_row* lists a second PLC that many seconds after the first is selected.
    *hang_on* one after which CLICK stops answering for *hang_for* seconds (Windows then
    titles its main window "... (Not Responding)"). *status_bar* is how its status bar
    reads (``Desktop.status_bar``), None when no way works.
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
        plc_selected: int = 1,
        select_lag: int = 4,
        late_row: float | None = None,
        same_lan: bool = True,
        tooltip: bool = False,
        startup_buttons: int = 3,
        dont_read_takes: bool = True,
        splash: bool = False,
        surprise: str | None = None,
        stall: str | None = None,
        interrupt: str | None = None,
        fail: str | None = None,
        lag: int = 2,
        hang_on: str | None = None,
        hang_for: float = 0.0,
        status_bar: str | None = "MSAA",
        desktop_name: str | None = "Default",
        running: tuple[int, ...] = (),
        open_windows: tuple[int, ...] = (),
    ) -> None:
        self.temp_root = tmp_path / "temp"
        self.temp_root.mkdir()
        self.options = {
            "guide": guide,
            "login": login,
            "prefilled_user": prefilled_user,
            "password": password,
            "plc_rows": plc_rows,
            "plc_selected": plc_selected,
            "select_lag": select_lag,
            "late_row": late_row,
            "same_lan": same_lan,
            "tooltip": tooltip,
            "startup_buttons": startup_buttons,
            "dont_read_takes": dont_read_takes,
            "splash": splash,
        }
        self.surprise, self.stall = surprise, stall
        self.interrupt, self.fail = interrupt, fail
        self.lag = lag
        self.hang_on, self.hang_for = hang_on, hang_for
        self.hung_until = 0.0
        self.sent_while_hung: list[str] = []
        self.status_method = status_bar
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
        self.commands: list[str] = []
        self.pressed: list[str] = []
        self.typed: dict[int, str] = {}
        self.events: list[str] = []
        self.wins: dict[int, FakeWindow] = {}
        self.tick = 0
        self.queue: list[tuple[int, Callable[[], None]]] = []
        self._next = 1000
        self.main: FakeWindow | None = None
        self.output: FakeControl | None = None

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

    def _later(self, event: str, action: Callable[[], None]) -> None:
        """Run *action* a few polls from now, as a posted message is."""

        def run() -> None:
            if event == self.stall:
                return
            action()
            self.events.append(event)
            if event == self.hang_on:
                self.hung_until = time.monotonic() + self.hang_for
            if event == self.surprise:
                assert self.main is not None
                self._window("#32770", "Set a Project Password", self.main.hwnd)

        self.queue.append((self.tick + self.lag, run))

    def _check(self, method: str) -> None:
        if method == self.interrupt:
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
        self._control(main, "msctls_statusbar32", "", 59393, rect=(0, 1, 0, 1))
        main.on_close = self._close_main
        temp = self.temp_dir(main.hwnd)
        temp.mkdir()
        (temp / "SC_.mdb").write_bytes(b"mdb")
        (temp / "Project.ini").write_text("[Project]\n", encoding="utf-8")
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
        group = self._control(startup, "TGroupBox", "Select an Operation", 1)
        # Listed middle, right, left, as CLICK's children are
        lefts = {"middle": 891, "right": 1035, "left": 747}
        for name in list(lefts)[: self.options["startup_buttons"]]:
            if name == "right":
                action = lambda s=startup: self._later("startup", lambda: self._show_connect(s))
            else:
                action = lambda: self._later("cpu", self._select_cpu)
            self._control(
                startup,
                "TButton",
                "",
                0,
                parent=group.hwnd,
                rect=(lefts[name], 466, lefts[name] + 135, 601),
                on_press=action,
            )
        self._control(startup, "TButton", "Close", 2)

    def _select_cpu(self) -> None:
        assert self.main is not None
        self._window("TfrmCPU", "Select a CPU Module", self.main.hwnd)

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

        # As the live run of 2026-11-15 saw: the scan adds the rows, and selects one a
        # few polls later
        def selected() -> None:
            plcs.counts = (self.options["plc_rows"], self.options["plc_selected"])
            if self.options["late_row"] is not None:
                self.late_row_at = time.monotonic() + self.options["late_row"]

        def scanned() -> None:
            plcs.counts = (self.options["plc_rows"], 0)
            if self.options["plc_selected"]:
                self.queue.append((self.tick + self.options["select_lag"], selected))

        self._later("scan", scanned)

    def _after_connect(self) -> None:
        self.connect_dialog.enabled = False
        if self.options["login"]:
            self._show_login()
        else:
            self._show_read_prompt()

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

    def _show_save_as(self) -> None:
        assert self.main is not None
        main = self.main
        main.enabled = False
        dialog = self._window("#32770", "Save As", main.hwnd)
        self._control(dialog, "ComboBox", "", 1137)
        box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
        box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
        name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)

        def save() -> None:
            path = Path(name.value)
            path.write_bytes(b"ckp")
            (self.temp_dir(main.hwnd) / "Scr1.tmp").write_bytes(self.pasted or b"empty")
            main.title = f"CLICK Programming Software (Version4.00) - {path.name} - [Main Program]"
            self._drop(dialog)
            main.enabled = True
            self.saved = True

        self._control(dialog, "Button", "&Save", 1, on_press=lambda: self._later("save", save))
        self._control(dialog, "Button", "Cancel", 2)

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
            self.wins.clear()
            self.is_running = False
            self.exited_cleanly = True
            temp = self.temp_dir(self.main.hwnd)
            for path in temp.iterdir():
                path.unlink()
            temp.rmdir()

        self._later("close", close)

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
                # RUNG_CSV's one rung: the cursor moves down a rung, and it uses steps
                self.pasted = self.clipboard
                self.cursor_rung += 1
                self.steps += 3

            self._later("paste", paste)
        elif command_id == cd.SYNTAX_CHECK:

            def checking() -> None:
                # What the check lists comes first; the project's total is the last line
                output.visible = True
                output.value = "Checking...\r\nNewProject40 - 0 error(s), 0 warning(s)\r\n"
                self._later("syntax_check", checked)

            def checked() -> None:
                output.value += (
                    "C0201 END instruction is missing.\r\n"
                    "NewProject4 - 1 error(s), 0 warning(s)\r\n"
                )

            self._later("syntax_checking", checking)
        elif command_id == cd.SAVE_PROJECT_AS:
            self._later("save_as", self._show_save_as)
        elif command_id == cd.DISCONNECT:
            self._later("disconnect", self._show_disconnect)

    def click_processes(self) -> list[int]:
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
        self.is_running = False
        self.terminated = True
        self.hung_until = 0.0
        self.wins.clear()

    def windows(self, pid: int) -> list[cd.Window]:
        assert pid == self.pid
        self._check("windows")
        hung = self.hung()
        if not hung:  # A hung CLICK takes no posted message
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

    def controls(self, hwnd: int) -> list[cd.Control]:
        window = self.wins.get(hwnd)
        if window is None:
            return []
        return [
            cd.Control(c.hwnd, c.parent, c.cls, c.text, c.id, c.visible, c.enabled, c.rect)
            for c in window.controls
        ]

    def hung(self) -> bool:
        return time.monotonic() < self.hung_until

    def _message(self, what: str) -> bool:
        """Whether a message is answered; one sent or posted while CLICK hangs is noted."""
        if self.hung():
            self.sent_while_hung.append(what)
            return False
        return True

    def read_text(self, hwnd: int) -> str | None:
        if not self._message("WM_GETTEXT"):
            return None
        control = self._find(hwnd)
        if control.id == 20142:
            return ""  # ES_PASSWORD: another process reads nothing
        return control.value if control.cls == "Edit" else control.text

    def set_text(self, hwnd: int, text: str) -> bool:
        if not self._message("WM_SETTEXT"):
            return False
        self._find(hwnd).value = text
        self.typed[self._find(hwnd).id] = text
        return True

    def button_checked(self, hwnd: int) -> int | None:
        return self._find(hwnd).checked if self._message("BM_GETCHECK") else None

    def list_view_counts(self, hwnd: int) -> tuple[int, int] | None:
        if not self._message("LVM_GETITEMCOUNT"):
            return None
        control = self._find(hwnd)
        if self.late_row_at is not None and time.monotonic() >= self.late_row_at:
            control.counts = (control.counts[0] + 1, control.counts[1])
            self.late_row_at = None
        return control.counts

    def status_bar(self, hwnd: int) -> tuple[str, list[str]] | None:
        control = self._find(hwnd)
        if not control.cls.startswith("Afx:StatusBar") or self.status_method is None:
            return None  # The common control of no size holds nothing
        if not self._message("status bar"):
            return None
        panes = [
            "RUN" if self.connected else "",
            f"{self.steps:04d}/8000",
            "C2-03CPU",
            f"{self.cursor_rung}:1:A",
            "192.168.1.241(Conformance)" if self.connected else "",
        ]
        return self.status_method, panes

    def press(self, hwnd: int) -> None:
        self._message("BM_CLICK")
        control = self._find(hwnd)
        self.pressed.append(control.text or f"{control.cls}@{control.rect[0]}")
        if control.on_press is not None:
            control.on_press()

    def close(self, hwnd: int) -> None:
        self._message("WM_CLOSE")
        window = self.wins[hwnd]
        if window.on_close is not None:
            window.on_close()

    def idle(self, hwnd: int, timeout: float) -> bool:
        return not self.hung()  # SMTO_ABORTIFHUNG gives up at once on a hung window

    def screenshot(self, hwnd: int, path: Path) -> bool:
        if self.hung():
            self.sent_while_hung.append("screenshot")  # It would show Windows' ghost
        path.write_bytes(b"\x89PNG fake")
        return True

    def set_clipboard(self, payload: bytes, owner: int) -> None:
        self._check("set_clipboard")
        assert self.main is not None and owner == self.main.hwnd
        self.clipboard = payload

    def temp_dir(self, hwnd: int) -> Path:
        return self.temp_root / f"CLICK ({hwnd:08X})"


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
    # The fake's Scr1.tmp holds the pasted payload; decode it as the CSV's rungs
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda data: Program("Main Program", 1, rungs if data != b"empty" else []),
    )
    for name in ("CLICK_RUNNER_PASSWORD", "CLICK_RUNNER_USER_TYPE"):
        monkeypatch.delenv(name, raising=False)
    return csv, exe


class Prepare:
    """prepare_csv_load without SC_.mdb (the fake's is not a database); records the MDB asked for."""

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
    """Run the CLI on *fake*; the paste timeout is *timeout* unless given."""
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


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cr, "POLL_INTERVAL", 0.001)
    monkeypatch.setattr(cr, "PLC_SETTLE", 0.02)


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
    """The runner never deletes CLICK's temp folder; it logs whether CLICK left it."""
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
    fake = FakeClick(tmp_path, stall="paste", status_bar=None)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_ABORTED
    assert result["status"] == "aborted" and result["step"] == "decode"
    assert result["reason"].startswith("the paste did not land: the saved main program has")
    assert result["rungs"]["same"] is False
    # CLICK itself had closed cleanly by then
    assert fake.exited_cleanly and not fake.terminated


def test_a_saved_main_that_differs_is_reported_not_aborted(tmp_path, setup, monkeypatch):
    """What CLICK makes of a rung is the point of a run: a different rung is a result."""
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
    """Opening SC_.mdb prints the ODBC driver it used; that goes to stderr."""
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
        "paste", tmp_path / "out", csv, exe, timeout=5, paste_timeout=5, poll=0.001
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
    assert log.count("a tooltip, let be: 'tooltips_class32'") == 2


def test_no_guide_no_login_and_a_splash(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, guide=False, login=False, splash=True)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert "login" not in result["timings"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "no Login dialog" in log
    assert "before the main window: 'TfrmSplash'" in log


def test_a_splash_still_open_after_launch_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, splash=True, stall="splash")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(fake, out, code, result, "and any window open before it closed")
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
    # Ended rather than closed: CLICK's temp folder stays, for CLICK to deal with
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
    assert result["status"] == "refused" and "is not empty" in result["reason"]
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


def test_a_timeout_aborts_and_disconnects(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(fake, out, code, result, "timed out after 0.3 s waiting for the Syntax Check")
    assert result["step"] == "syntax_check"
    # Connected with nothing else open: the cleanup disconnects before it ends CLICK
    assert fake.commands[-1] == "Disconnect" and not fake.connected


def test_two_plcs_abort(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, plc_rows=2, plc_selected=1)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    # Two rows that stay listed: no waiting for a selection
    assert_aborted(fake, out, code, result, "the Connect dialog lists 2 PLC(s), ")
    assert result["reason"].endswith("selected; expected exactly 1")
    assert "timed out" not in result["reason"]
    assert "Connect" not in fake.pressed


@pytest.mark.parametrize("select_lag", [1, 4])
def test_a_plc_selected_after_it_is_listed_connects(tmp_path, setup, select_lag):
    """The live run of 2026-11-15: the row came first, unselected, and was selected later.

    With a lag of 4 polls, (1 row, 0 selected) reads the same on two polls in a row.
    """
    csv, exe = setup
    fake = FakeClick(tmp_path, select_lag=select_lag)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert "PLC list: 1 row, selected" in (out / "run.log").read_text(encoding="utf-8")


def test_a_second_plc_listed_late_aborts(tmp_path, setup, monkeypatch):
    """The scan lists the PLCs one at a time: the list must stay the same for PLC_SETTLE."""
    csv, exe = setup
    monkeypatch.setattr(cr, "PLC_SETTLE", 0.5)
    fake = FakeClick(tmp_path, late_row=0.2)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(
        fake, out, code, result, "the Connect dialog lists 2 PLC(s), 1 selected; expected exactly 1"
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
        "the Connect dialog lists 2 PLC(s), 1 selected as Connect is about to be pressed",
    )
    assert "Connect" not in fake.pressed


def test_a_connect_dialog_not_scanning_the_lan_aborts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, same_lan=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "the Connect dialog does not scan the same LAN")
    assert "Connect" not in fake.pressed


def test_a_plc_never_selected_aborts_with_the_counts(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, plc_selected=0)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=0.3)
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the Connect dialog lists 1 PLC(s), 0 selected; timed out after 0.3 s",
    )
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
        "the Connect dialog lists 0 PLC(s), 0 selected; timed out after 0.3 s "
        "waiting for one PLC in the list, selected",
    )


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
    assert_aborted(fake, out, code, result, "'Don't read' did not take")
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
    """Even when the cleanup itself is interrupted, CLICK is ended."""
    csv, exe = setup
    fake = FakeClick(tmp_path, stall="syntax_check")
    original = fake.screenshot

    def interrupted(hwnd: int, path: Path) -> bool:
        if path.parent.name == "abort":
            raise KeyboardInterrupt
        return original(hwnd, path)

    fake.screenshot = interrupted
    with pytest.raises(KeyboardInterrupt):
        run(fake, tmp_path / "out", csv, exe, timeout=0.2)
    assert fake.terminated and not fake.is_running


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
    """CLICK freezes while it pastes, longer than any dialog may take; nothing is sent then."""
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
    assert before["method"] == after["method"] == "MSAA"
    assert before["control"].startswith("Afx:StatusBar")
    assert "1:1:A" in before["panes"] and "2:1:A" in after["panes"]
    assert "0000/8000" in before["panes"] and "0003/8000" in after["panes"]


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
    fake = FakeClick(tmp_path, status_bar=None)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert code == cr.EXIT_OK, result["reason"]
    assert result["status_bar"] == {
        "connected": None,
        "before_paste": None,
        "pasted": None,
        "disconnected": None,
    }
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "status bar: no way of reading it worked" in log
    assert "(no status bar to check it with)" in log


def test_a_hung_click_is_dumped_without_a_message_and_ended(tmp_path, setup, monkeypatch):
    """CLICK stops answering for good: the dump sends it nothing and takes no screenshot
    (Windows would show its ghost), the cleanup does not disconnect, and CLICK is ended."""
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
    assert "does not answer: its dump has no edit text and no PNG" in log
    assert "not disconnecting: CLICK does not answer" in log
    assert "CLICK does not answer; still waiting for the Syntax Check result" in log
    assert "Disconnect" not in fake.commands


def test_a_long_wait_logs_the_status_bar(tmp_path, setup, monkeypatch):
    csv, exe = setup
    monkeypatch.setattr(cr, "STATUS_EVERY", 0.05)
    fake = FakeClick(tmp_path, stall="syntax_check")
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, timeout=5, paste_timeout=0.4)
    assert_aborted(fake, out, code, result, "timed out after 0.4 s waiting for the Syntax Check")
    log = (out / "run.log").read_text(encoding="utf-8")
    assert log.count("status bar (Afx:StatusBar:2e0000:8:10003:10, MSAA): RUN | 0003/8000") >= 3


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
# The command allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command_id", "message"),
    [
        (cd.READ_PROJECT_FROM_PLC, "Read Project from PLC"),
        (cd.WRITE_PROJECT_INTO_PLC, "Write Project into PLC"),
        (32853, "Read Project from PLC"),
        (32854, "Write Project into PLC"),
        (12345, "not on the runner's allowlist"),
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


def test_the_allowlist_is_the_five_commands():
    assert cd.ALLOWED_COMMANDS == {
        0xE125: "Paste",
        32846: "Syntax Check",
        32898: "Save Project",
        32899: "Save Project As",
        32850: "Disconnect",
    }
    assert 32853 not in cd.ALLOWED_COMMANDS and 32854 not in cd.ALLOWED_COMMANDS


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows'")
def test_a_process_in_the_job_dies_when_the_job_closes():
    """What keeps CLICK from outliving a runner that is killed: Windows closes the job's
    handle when the runner's process ends, however it ends."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = cd.kill_on_close(int(child._handle))  # pyright: ignore[reportAttributeAccessIssue]
        assert child.poll() is None
        began = time.monotonic()
        cd._kernel32().CloseHandle(job)
        child.wait(timeout=10)  # Not the minute it sleeps
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
