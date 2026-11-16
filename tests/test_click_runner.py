"""The CLICK runner (devtools/click_runner.py) against a fake CLICK.

No test launches CLICK or sends anything to a window. ``FakeClick`` plays CLICK v4's
dialog sequence as the probe of 2026-11-15 recorded it (classes, titles, owners, control
ids and texts from its dumps); a posted message takes effect on a later poll, as it does
in CLICK.
"""

from __future__ import annotations

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
    items: int = 0
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
    effect never happens; *hang_on* one after which CLICK stops answering for *hang_for*
    seconds (Windows then titles its main window "... (Not Responding)"). *interrupt*
    names a Desktop method that raises KeyboardInterrupt once; *fail* one that always
    raises OSError. *late_row* lists a second PLC that many seconds after the first.
    *status_bar* is whether the status bar reads, *plc_pane* whether it names the PLC
    once connected. *leftover* names Scr*.tmp files already in the temp folder, as an
    older CLICK with the same hwnd would leave them. *error_on* names an event after which
    CLICK shows an error box (PTC-013, as live run 3 met it), owned by the Connect dialog
    after "connect" (which then shows no Login) and by the main window otherwise.

    The ribbon's Math, Copy and Out commands open their dialogs as live probe 2 dumped them
    (2026-11-15). *judge* answers OK in one: None accepts, ``(code, message)`` refuses with
    an error box, ``("warn", code, message)`` shows the box and then places the
    instruction, ``"question"`` shows a Yes/No box with no code. The placed instruction
    stays until Delete, unless *delete_works* is off; Syntax Check lists *syntax_lines*'
    line for it, keyed by the dialog's title. Each dialog opens with the button states
    ``INSTRUCTIONS`` names, or *opens_with*'s. With *places* off, a closed dialog leaves
    nothing in rung 1. *box_on_fill* is a text that, set into a dialog's field, makes CLICK
    show an error box owned by the dialog at once. *quick_checks* ignores a Syntax Check
    posted within that many polls of the last check's result, as live probe 3 found
    CLICK ignoring one posted soon after (event ``check_ignored``).

    File > Import > Nickname opens the Open dialog as live probes 1 to 4 dumped it
    (2026-11-15): Merge (Project priority) checked, the other modes beside it. Open hands the
    file's bytes to *import_answer*, which returns the rows the import stores and the error
    list's text (None for "Completed!"); the rows replace the table (Delete Existing) or are
    merged into it, kept as JSON in SC_.mdb. *import_writes* is when SC_.mdb is written:
    ``answer`` as the answer shows, ``ok`` once its OK is pressed, ``late`` ``LATE_WRITE_POLLS``
    polls after the main window is alone again. *mode_takes* off leaves the mode as it was;
    *import_as* names the mode CLICK imports in, whatever is checked; *import_box* ``"question"`` shows a Yes/No box in place of the answer,
    ``"twice"`` the same answer again once the first is closed. ``imported`` lists each
    import's mode and file.
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
        self.judge = judge or judge_like_click
        self.delete_works = delete_works
        self.syntax_lines = syntax_lines or {}
        self.opens_with = opens_with or {}
        self.places = places
        self.box_on_fill = box_on_fill
        self.quick_checks = quick_checks
        self.checked_tick: int | None = None  # The poll the last check's result showed on
        self.placed: str | None = None  # The title of the instruction in rung 1
        self.entered: list[tuple[str, str | None, dict[str, str]]] = []
        self.import_answer = import_answer or import_like_click
        self.import_writes = import_writes
        self.mode_takes = mode_takes
        self.import_box = import_box
        self.import_as = import_as
        self.imported: list[tuple[str, str]] = []
        self.ckps: dict[Path, dict[str, bytes]] = {}  # Each saved project's files
        self.opened: list[Path] = []

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
            if event == self.error_on:
                self._show_error(event)

        self.queue.append((self.tick + self.lag, run))

    def _show_error(self, event: str) -> None:
        """CLICK's error box as live run 3 dumped it (live3/abort/04-abort-288099950.json)."""
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
            self.interrupt = None  # One Ctrl+C
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
        self._control(startup, "TButton", "Close", 0)
        self._control(startup, "TButton", "Help", 0)
        for control in startup.controls:
            control.id = control.hwnd  # A Delphi control's id is its hwnd

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

        # The list is owner-drawn: CLICK paints its own highlight and reports no
        # selection (live run 2, 2026-11-15)
        def scanned() -> None:
            plcs.items = self.options["plc_rows"]
            if self.options["late_row"] is not None:
                self.late_row_at = time.monotonic() + self.options["late_row"]

        self._later("scan", scanned)

    def _after_connect(self) -> None:
        self.connect_dialog.enabled = False
        if self.error_on == "connect":
            return  # The PLC did not answer: CLICK shows its error box instead
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
            # The main program: what was pasted, or the instruction try placed in rung 1
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
        """File > Open Project's Open dialog; opening puts the project's files in the temp folder."""
        assert self.main is not None
        main = self.main
        main.enabled = False
        dialog = self._window("#32770", "Open", main.hwnd)
        box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
        box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
        name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)

        def open_file() -> None:
            path = Path(name.value)
            temp = self.temp_dir(main.hwnd)
            for old in temp.iterdir():
                if old.name != "SC_.mdb":
                    old.unlink()
            for file, data in self.ckps[path].items():
                (temp / file).write_bytes(data)
            self.opened.append(path)
            main.title = f"CLICK Programming Software (Version4.00) - {path.name} - [Main Program]"
            self._drop(dialog)
            main.enabled = True

        self._control(dialog, "Button", "&Open", 1, on_press=lambda: self._later("open", open_file))
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
            # CLICK unloads the project first: its main window is titled bare (live run 4)
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

    def _show_instruction(self, title: str) -> None:
        """An instruction dialog as live probe 2 dumped it: radios, edits, OK and Cancel."""
        assert self.main is not None
        main = self.main
        dialog = self._window("#32770", title, main.hwnd)
        spec = cr.INSTRUCTIONS[title.lower()]
        radios = {
            name: self._control(dialog, "Button", "", id, checked=int(index == 0))
            for index, (name, id) in enumerate(spec.modes.items())
        }
        edits = {
            name: self._control(dialog, "RichEdit20W" if name == "formula" else "Edit", "", id)
            for name, id in spec.fields.items()
        }
        for id, state in {**spec.opens_with, **self.opens_with}.items():
            self._control(dialog, "Button", f"button {id}", id, checked=state)

        def pick(name: str) -> None:
            for other, radio in radios.items():
                radio.checked = int(other == name)
            if title == "Math":  # Picking a type empties Result and the formula
                for edit in edits.values():
                    edit.value = ""
            # As live probe 2 found the Copy dialog's "to" fields
            closed = {
                "single": ("source_end",),
                "pack": ("destination_end",),
                "unpack": ("source_end",),
            }
            for key, edit in edits.items():
                edit.enabled = key not in closed.get(name, ())

        for name, radio in radios.items():
            radio.on_press = lambda n=name: self._later("mode", lambda: pick(n))
        if radios:
            pick(next(iter(radios)))

        def ok() -> None:
            mode = next((n for n, r in radios.items() if r.checked), None)
            values = {name: edit.value for name, edit in edits.items() if edit.value}
            self.entered.append((title, mode, values))
            answer = self.judge(title, mode, values)
            if answer is None:
                place()
            elif answer == "question":
                box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)
                self._control(box, "Static", "Replace the instruction?", 65535)
                self._control(box, "Button", "&Yes", 6)
                self._control(box, "Button", "&No", 7)
                dialog.enabled = False
            else:
                warn = answer[0] == "warn"
                code, message = answer[-2:]
                box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)

                def closed() -> None:
                    self._drop(box)
                    if warn:
                        place()
                    else:
                        dialog.enabled = True

                self._control(box, "Button", "OK", 2, on_press=lambda: self._later("box", closed))
                self._control(box, "Static", "", 20)
                self._control(box, "Static", f"{code}\n{message}", 65535)
                dialog.enabled = False

        def place() -> None:
            if self.places:
                self.placed = title
            self._drop(dialog)
            main.enabled = True

        def cancel() -> None:
            self._drop(dialog)
            main.enabled = True

        self._control(dialog, "Button", "OK", 1, on_press=lambda: self._later("ok", ok))
        self._control(dialog, "Button", "Cancel", 2, on_press=lambda: self._later("cancel", cancel))
        main.enabled = False

    def _show_open(self) -> None:
        """The Open dialog of File > Import > Nickname, as live probe 1 dumped it."""
        assert self.main is not None
        main = self.main
        main.enabled = False
        dialog = self._window("#32770", "Open", main.hwnd)
        self._control(dialog, "ComboBox", "", 1137)
        box_ex = self._control(dialog, "ComboBoxEx32", "", 1148)
        box = self._control(dialog, "ComboBox", "", 1148, parent=box_ex.hwnd)
        name = self._control(dialog, "Edit", "", 1148, parent=box.hwnd)
        self._control(dialog, "Button", "Open as &read-only", 1040, visible=False, enabled=False)
        # The template's panel: Delphi radio buttons, whose ids are their hwnds
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
        """CLICK importing *path*: its progress window, then its answer over it."""
        assert self.main is not None
        main = self.main
        self.imported.append((mode, path.name))
        rows, errors = self.import_answer(path.read_bytes())
        mdb = self.temp_dir(main.hwnd) / "SC_.mdb"

        def write() -> None:
            try:
                table = json.loads(mdb.read_text(encoding="utf-8"))
            except ValueError:
                table = {}  # A new project's SC_.mdb, b"mdb" here
            table = rows if mode == "Delete Existing" else {**table, **rows}
            mdb.write_text(json.dumps(table), encoding="utf-8")

        # Titled by its Delphi form's name at first, then by the mode (live run 1)
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
                # RUNG_CSV's one rung: the cursor moves down a rung; the steps stay as they
                # were (live run 4)
                self.pasted = self.clipboard
                self.cursor_rung += 1

            self._later("paste", paste)
        elif (
            command_id == cd.SYNTAX_CHECK
            and self.checked_tick is not None
            and self.tick - self.checked_tick <= self.quick_checks
        ):
            self._later("check_ignored", lambda: None)
        elif command_id == cd.SYNTAX_CHECK:

            def checking() -> None:
                # What the check lists comes first; the project's total is the last line
                output.visible = True
                output.value = "Checking...\r\nNewProject40 - 0 error(s), 0 warning(s)\r\n"
                self._later("syntax_check", checked)

            def checked() -> None:
                # As live probe 2 read it: an instruction on rung 1 moves the END error on.
                # The total names the project as the title does (a save renames it)
                rung = 1 if self.placed is None else 2
                extra = self.syntax_lines.get(self.placed or "")
                assert self.main is not None
                project = Path(cr._project_file(self.main.title) or "").stem
                output.value += (
                    f"Main Program : Rung {rung} : error C0201: No unconditional END "
                    "instruction in the Main Program.\r\n"
                    + (f"{extra}\r\n" if extra else "")
                    + f"\r\n{project} - 1 error(s), 0 warning(s)\r\n"
                )
                self.checked_tick = self.tick

            self._later("syntax_checking", checking)
        elif command_id == cd.SAVE_PROJECT_AS:
            self._later("save_as", self._show_save_as)
        elif command_id == cd.DISCONNECT:
            self._later("disconnect", self._show_disconnect)
        elif command_id == cd.IMPORT_NICKNAME:
            self._later("import_open", self._show_open)
        elif command_id == cd.OPEN_PROJECT:
            self._later("open_project", self._show_open_project)
        elif command_id == cd.DELETE:

            def delete() -> None:
                if self.delete_works:
                    self.placed = None

            self._later("delete", delete)
        else:
            title = {cd.MATH_DIALOG: "Math", cd.COPY_DIALOG: "Copy", cd.OUT_DIALOG: "Out"}
            self._later("dialog", lambda: self._show_instruction(title[command_id]))

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
        return control.value if control.cls in ("Edit", "RichEdit20W", "TMemo") else control.text

    def set_text(self, hwnd: int, text: str) -> bool:
        if not self._message("WM_SETTEXT"):
            return False
        self._find(hwnd).value = text
        self.typed[self._find(hwnd).id] = text
        if text == self.box_on_fill:
            dialog = next(w for w in self.wins.values() if any(c.hwnd == hwnd for c in w.controls))
            box = self._window("#32770", "CLICK Programming Software", dialog.hwnd)
            self._control(box, "Button", "OK", 2)
            self._control(box, "Static", "OBJ-1001\nThe Formula has an error.", 65535)
            dialog.enabled = False
        return True

    def button_checked(self, hwnd: int) -> int | None:
        return self._find(hwnd).checked if self._message("BM_GETCHECK") else None

    def list_view_items(self, hwnd: int) -> int | None:
        if not self._message("LVM_GETITEMCOUNT"):
            return None
        control = self._find(hwnd)
        if self.late_row_at is not None and time.monotonic() >= self.late_row_at:
            control.items += 1
            self.late_row_at = None
        return control.items

    def status_bar(self, hwnd: int) -> list[str] | None:
        control = self._find(hwnd)
        assert control.cls == "msctls_statusbar32", f"SB_GETTEXT sent to {control.cls}"
        if not self.status_readable or not self._message("SB_GETTEXT"):
            return None
        # As live runs 2 (offline) and 4 (connected, then disconnected) read it
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
            "C2-03CPU" if self.connected else "No select CPU",
            f"{self.cursor_rung}:1:A",
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

    def close(self, hwnd: int) -> None:
        self._message("WM_CLOSE")
        window = self.wins[hwnd]
        if window.on_close is not None:
            window.on_close()

    def idle(self, hwnd: int, timeout: float) -> bool:
        return not self.hung()  # SMTO_ABORTIFHUNG gives up at once on a hung window

    def screenshot(self, hwnd: int, path: Path) -> bool:
        if not self.exists(hwnd):
            raise OSError(1400, "GetWindowRect", "Invalid window handle.")
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


def judge_like_click(title: str, mode: str | None, values: dict[str, str]) -> object:
    """What live CLICK answered: a Math result in SD1, an Out on X and a copy into YD are
    refused (live probe 2, live run try4); so is a Math with no result."""
    if title == "Math" and not values.get("result"):
        return ("OBJ-001", "Enter the result.")
    if title == "Math" and values["result"].startswith("SD"):
        return ("OBJ-003", "The entered address is outside the range.")
    if title == "Out" and values.get("address", "").startswith("X"):
        return ("OBJ-004", "The entered address cannot be used in this instruction.")
    if title == "Copy" and values.get("destination", "").startswith("YD"):  # Live try4, B1
        return ("OBJ-004", "The entered address cannot be used in this instruction.")
    return None


# How many polls after the main window is alone again an import written late writes SC_.mdb
LATE_WRITE_POLLS = 3


def import_like_click(data: bytes) -> tuple[dict[str, dict], str | None]:
    """The rows an import stores and its error list, as live probes 2 and 3 saw three cases:
    a line that is not six cells is refused, so is a quoted address with a space at an end
    (listed twice for a file's first row), and any other row is stored under its address
    without the spaces at its ends."""
    rows: dict[str, dict] = {}
    errors = ""
    lines = data.decode("latin-1").split("\r\n")
    for number, line in enumerate(lines[1:], 2):
        if not line:
            continue
        cells = next(csv_module.reader([line]))
        if len(cells) != 6:  # As live probe 3 saw the second line of a quoted line break
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
    monkeypatch.setattr(cr, "IMPORT_SETTLE", 0.1)


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


def test_a_user_type_that_does_not_take_aborts(tmp_path, setup):
    """The brief's test list had an empty User Type abort; Sam ruled later that the runner
    fills it in. What aborts is a User Type that does not take the text set."""
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
    assert_aborted(fake, out, code, result, "User Type did not take the text set")
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
    """Live run 3: PTC-013 during connect. Nothing is pressed in it and nothing is retried."""
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
    assert fake.commands.count("Disconnect") <= 1  # Only the step's own
    if event == "connect":
        assert "login" not in fake.events and result["plc"] is None


def test_an_error_box_met_by_the_cleanup_is_not_what_stopped_the_run(tmp_path, setup):
    """click_error tells a caller the box stopped the run; one met while the cleanup
    disconnects after a timeout is kept apart."""
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
    """As the main window did while CLICK closed in live run 4: its screenshot found no
    window; that is no error worth a line."""
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
    """Live run 4: after WM_CLOSE the main window is titled "CLICK Programming Software
    (Version4.00)" until it goes; the close waits that out and the decode runs."""
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
    # Connected with nothing else open: the cleanup disconnects before it ends CLICK
    assert fake.commands[-1] == "Disconnect" and not fake.connected


def test_two_plcs_abort(tmp_path, setup):
    csv, exe = setup
    fake = FakeClick(tmp_path, plc_rows=2)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "the Connect dialog lists 2 PLC(s); expected exactly 1")
    assert "timed out" not in result["reason"]
    assert "Connect" not in fake.pressed


def test_a_second_plc_listed_late_aborts(tmp_path, setup, monkeypatch):
    """The scan lists the PLCs one at a time: the list must stay the same for PLC_SETTLE."""
    csv, exe = setup
    monkeypatch.setattr(cr, "PLC_SETTLE", 0.5)
    fake = FakeClick(tmp_path, late_row=0.2)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe)
    assert_aborted(fake, out, code, result, "the Connect dialog lists 2 PLC(s); expected exactly 1")
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
        "the Connect dialog lists 2 PLC(s) as Connect is about to be pressed; expected 1",
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
        "the Connect dialog lists 0 PLC(s); timed out after 0.3 s waiting for one PLC in the list",
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
    """--plc asks for a check the status bar cannot give: the run stops."""
    csv, exe = setup
    fake = FakeClick(tmp_path, status_bar=False)
    out = tmp_path / "out"
    code, result = run(fake, out, csv, exe, "--plc", "Conformance", timeout=0.3)
    assert_aborted(
        fake,
        out,
        code,
        result,
        "the status bar cannot be read to confirm the PLC named 'Conformance'; timed out",
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
    """record ends CLICK rather than closing it: a terminate that fails is in the result."""
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
    assert result["timings"]["dont_read"] >= 0.3  # Read until the wait timed out
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


def test_a_status_bar_out_of_reach_leaves_the_connection_unconfirmed(tmp_path, setup):
    """Win32Desktop.status_bar refuses a buffer a 32-bit CLICK cannot reach: logged once."""
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
    """CLICK's temp folder is never deleted, so a CLICK with an older one's hwnd finds its
    Scr*.tmp: one the save does not rewrite would be decoded with the project."""
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

    assert bar(2, 0).shows_paste(bar(1, 0), 1)  # Live run 4: the steps stay
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


class Nicknames:
    """read_nicknames without a database (the fake's SC_.mdb is not one); records its calls."""

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
    **run_args: object,
) -> tuple[int, dict]:
    file = tmp_path / "cases.json"
    file.write_text(json.dumps(cases), encoding="utf-8")
    out = tmp_path / "out"
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
    # Each mode is picked before the fields: picking Hex empties them
    assert fake.entered[2] == ("Math", "hex", {"result": "YD0", "formula": "DH1 + DH2"})
    assert fake.entered[3][1] == "block" and fake.entered[4][1] == "block"
    # An accepted case's own lines leave out the codes the empty program's check has
    assert result["cases"][0]["syntax_check"]["lines"] == []
    copy = result["cases"][3]["syntax_check"]
    assert copy["lines"] == ["Main Program : Rung 1 : warning W0301: x."]
    assert copy["errors"] == 1 and "Rung 2 : error C0201" in copy["text"]
    assert "Rung 1 : error C0201" in result["baseline_syntax_check"]["text"]
    # Accepted: Syntax Check, Delete, Syntax Check; refused: the box's OK, then Cancel
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
    # The project was never saved: CLICK is disconnected, then ended
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
    # The check after each Delete follows the one before at once: CLICK ignores it
    ignored = fake.events.count("check_ignored")
    assert ignored == 2
    assert fake.commands.count("Syntax Check") == 1 + 2 * 2 + ignored
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert log.count("Output is still empty after 0.3 s: post again") == ignored


def test_no_syntax_check_is_posted_again_while_click_does_not_answer(tmp_path, setup, monkeypatch):
    _, exe = setup
    monkeypatch.setattr(cr, "SYNTAX_REPOST_AFTER", 0.2)
    # Output stays empty for a second while CLICK does not answer: posting again then
    # would queue checks behind a busy CLICK
    fake = FakeClick(tmp_path, quick_checks=3, hang_on="check_ignored", hang_for=1.0)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:1]})
    assert code == cr.EXIT_OK, result["reason"]
    assert fake.events.count("check_ignored") == 1
    assert "WM_COMMAND" not in fake.sent_while_hung
    log = (tmp_path / "out" / "run.log").read_text(encoding="utf-8")
    assert log.count("post again") == 1


def test_try_record_dumps_each_case(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": TRY_CASES[:2]}, "--record")
    assert code == cr.EXIT_OK, result["reason"]
    assert result["nicknames"] is None and "nicknames" not in result["timings"]
    labels = {p.name.split("-")[1] for p in (tmp_path / "out" / "record").glob("*.json")}
    assert {"baseline", "case01_filled", "case01_answer", "case02_answer"} <= labels


class Stored:
    """read_stored for the fake's Scr*.tmp, which holds text; raises for the files named."""

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
    # Saved before each Delete; each later check names the project as last saved
    first = ["Syntax Check", "Math...", "Syntax Check", "Save Project As", "Delete"]
    assert fake.commands[:5] == first
    assert fake.commands.count("Save Project As") == 3
    assert accepted[1]["syntax_check"]["project"] == "case01"
    assert result["baseline_syntax_check"]["project"] == "NewProject4"
    # Decoded once CLICK had ended, which the runner ended rather than closed
    assert fake.terminated and not fake.exited_cleanly
    assert list(result["timings"])[-4:] == ["try", "disconnect", "close", "decode"]
    assert [p.parent.parent.name for p in stored.read] == ["case01", "case03", "case04"]


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
    assert_aborted(fake, out, code, result, "no instruction was placed in rung 1")
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
    assert [c["outcome"] for c in result["cases"]] == ["accepted"]


def test_a_field_closed_in_the_mode_aborts(tmp_path, setup):
    _, exe = setup
    case = {
        "row": "x",
        "case": "a range in single mode",
        "instruction": "copy",
        "mode": "single",
        "fields": {"source": "DS1", "source_end": "DS2", "destination": "DS3"},
    }
    fake = FakeClick(tmp_path)
    code, result = run_try(fake, tmp_path, exe, {"cases": [case]})
    assert_aborted(
        fake, tmp_path / "out", code, result, "source_end field (5009) is not open for entry"
    )
    assert "OK" not in fake.pressed[5:]


@pytest.mark.parametrize(
    ("cases", "reason"),
    [
        ([], "expected an object with a list under 'cases'"),
        ({"cases": []}, "lists no cases"),
        ({"cases": [{"row": "A1"}]}, "case 1 needs a 'row' and a 'case'"),
        (
            {"cases": [{**TRY_CASES[0], "instruction": "timer"}]},
            "'instruction' is not one of math, copy, out",
        ),
        ({"cases": [{**TRY_CASES[0], "mode": None}]}, "'mode' is not one of decimal, hex"),
        ({"cases": [{**TRY_CASES[5], "mode": "single"}]}, "Out has no modes"),
        (
            {"cases": [{**TRY_CASES[3], "mode": "fill"}]},
            "'mode' is not one of single, block, pack, unpack",
        ),
        ({"cases": [{**TRY_CASES[0], "fields": {"source": "DS1"}}]}, "Math has no field source"),
        ({"cases": [{**TRY_CASES[0], "fields": {}}]}, "'fields' must name at least one field"),
        ({"cases": [{**TRY_CASES[0], "extra": 1}]}, "unknown keys: extra"),
        ({"cases": TRY_CASES, "nicknames": ["SD99999"]}, "cannot read the cases"),
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
    """The checked-in cases for the rule table's rows."""
    cases, nicknames = cr.load_cases(Path(cd.__file__).parent / "editor_cases.json")
    rows = {case.row for case in cases}
    assert {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"} <= rows
    assert {"B1", "B2", "B3", "B4", "B5", "B6", "B8"} <= rows
    assert {"SD21", "SD22", "SD24", "SD25", "SD26"} <= set(nicknames)


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
# Lines: the header 1, DS20 2 and 3, an empty line 4, DS32 5, TXT20 6
IMPORT_CSV = HEADER + IMPORT_ROWS[0] + IMPORT_ROWS[1] + b"\r\n" + IMPORT_ROWS[2] + IMPORT_ROWS[3]
IMPORT_LINES = ["line002", "line003", "line005", "line006"]
# The Import Error List's text in live probe 2 (2026-11-15), for tab_checks.csv
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
    """read_rows for the fake's SC_.mdb, which holds JSON; records the files read."""

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
    """Run ``import`` on *fake*, with *data* as the CSV (none written when None)."""
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
    # The answers: the error list's text and its entries, or the box's
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
    # The mode is picked, the path typed, and only the import is sent before Disconnect
    assert fake.pressed.count("Delete Existing") == 5
    assert fake.typed[1148] == str(out / "rows" / "line006.csv")
    assert fake.commands == ["Import Nickname"] * 5 + ["Disconnect"]
    # The project was never saved: CLICK is disconnected, then ended
    assert not fake.connected and fake.terminated and not fake.saved
    assert list(result["timings"])[-4:] == ["import", "disconnect", "close", "read"]
    log = (out / "run.log").read_text(encoding="utf-8")
    assert "line006: 1 row(s) stored" in log and "InitialValue='\\t'" in log
    assert "SC_.mdb changed (already when the answer showed); copied" in log


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
    # SC_.mdb reading the same on two polls is not enough: CLICK may write it later
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
    assert "SC_.mdb changed (not yet when the answer showed; changed after it); copied" in log


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
    # CLICK's answer is left as it is: nothing pressed after Open
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
    # LF line ends, and a last row with none
    assert cr.split_rows(b"A,B\nDS1,x\nDS2,y") == (b"A,B\n", [(2, b"DS1,x\n"), (3, b"DS2,y")])
    # A quote that does not close ends at its line's end; a CR alone ends no line
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
    code, result = run_reopen(fake, tmp_path, exe, "--ini-add", r"[sec20]\nkey1=Probe")
    assert code == cr.EXIT_OK, result["reason"]
    out = tmp_path / "out"
    assert fake.commands == [
        "Disconnect",
        "Save Project As",
        "Save Project As",
        "Open Project",
        "Save Project As",
    ]
    assert fake.opened == [(out / "second.ckp").resolve()]
    points = result["points"]
    assert list(points) == ["first", "second", "opened", "third"]
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


def test_reopen_refuses_lines_that_are_not_ascii(tmp_path, setup):
    _, exe = setup
    fake = FakeClick(tmp_path)
    code, result = run_reopen(fake, tmp_path, exe, "--ini-add", "[Sec20]\\nKey1=caf\xe9")
    assert code == cr.EXIT_REFUSED and "--ini-add is not ASCII" in result["reason"]
    assert fake.pid is None


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


def test_the_allowlist_is_the_twelve_commands():
    assert cd.ALLOWED_COMMANDS == {
        0xE125: "Paste",
        32777: "Delete",
        32846: "Syntax Check",
        32772: "Open Project",
        32898: "Save Project",
        32899: "Save Project As",
        32850: "Disconnect",
        32900: "Import Nickname",
        32851: "Read Data from PLC",
        50010: "Out...",
        50030: "Math...",
        50040: "Copy...",
    }
    # Nothing that reads a project from the PLC or writes anything into it
    assert not {32852, 32853, 32854} & set(cd.ALLOWED_COMMANDS)


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
