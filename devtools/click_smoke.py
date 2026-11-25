"""Check ClickNick against new projects that the CLICK runner makes, one project at a time.

    uv run python devtools/click_smoke.py [--out DIR] [--cpu MODEL|none|rungs ...] [--timeout S]

For each project, the smoke runs the runner's ``new`` mode (click_runner.py). CLICK makes a
project for a CPU through its new-project wizard and saves it. For ``none``, the runner cancels
the wizard's choice of CPU, and CLICK saves a project with no CPU. For ``rungs``
(``PROGRAM_PROJECT``), CLICK makes a project for ``PROGRAM_CPU``. CLICK never connects to a
PLC. While CLICK still has the project open, the runner calls ``on_new_project``. There
ClickNick connects to that CLICK with no window, the way the app does after you pick the
window:

- ``ClickConnection(pid, hwnd, filename)`` and a ``ConnectionSession``;
- an ``AddressStore`` that reads the project's SC_.mdb (``MdbDataSource``);
- the workspace build (``ConnectionSession.start_analysis``);
- a ``SimulationSession`` from ``ConnectionSession.ensure_simulation``.

Then the smoke runs the checks in ``CHECKS`` in order. ``project_checks`` picks the checks for
each project:

- ``paste``: only in ``rungs``, before ClickNick reads the project. CLICK's main program is
  empty. The check copies the rungs of ``PROGRAM_CSV`` as Review Changes' Copy does, and Copy
  adds their addresses to SC_.mdb. SC_.mdb must then hold a row for each address that
  laddercodec finds in the copied bytes. The runner pastes the rungs at rung 1 and saves the
  project. The main program that laddercodec decodes from CLICK's saved Scr*.tmp must hold the
  same rungs. In ``rungs``, every other check needs this one;
- ``load``: the store reads SC_.mdb;
- ``build``: the workspace builds, with no warning, into CLICK's temp folder. In ``rungs``, the
  workspace's csv/main.csv must hold the rungs that CLICK saved;
- ``layout``: ``SimulationSession.layout`` has no error, and its cards are what
  ``read_panel_layout`` reads in the project's Project.ini. Its CPU card must be the project's
  CPU. For ``none``, the layout must have no CPU card. The Simulator then shows its No CPU card.
  For a project in ``click_smoke_layouts.json``, the cards must also be the cards recorded
  there. In ``rungs``, the check passes the program's X and Y addresses to
  ``read_panel_layout``, and the simulation must list each of them as used. ``PROGRAM_CPU``
  has all of them, so the cards must still be the recorded cards, with no placeholder card;
- ``simulation``: the simulation reaches READY, and it scans in RUN. In ``rungs``, the
  simulation must read each X and Y address of the program over Modbus. ``PROGRAM_OUTPUT``
  must be off. After the check turns ``PROGRAM_INPUT`` on, the program must turn
  ``PROGRAM_OUTPUT`` on;
- ``panel``: only in ``rungs``, after ``simulation``. The check opens ClickNick's Simulator
  window on the simulation, and ``sim_driver.Driver`` presses its panel with synthetic Tk
  events, as record_simulator_gif.py does. The window shows on the desktop while the check
  runs. The check switches the CPU to STOP and back to RUN, and turns ``PROGRAM_INPUT`` on and
  off. It forces ``PROGRAM_OUTPUT`` off with a double-click, and releases the force with a
  click on its padlock. After each step, the panel's LEDs, switch, padlock and Forces button
  must show what the program does. ``panel_scene`` lists the steps. If the check fails, the
  checks after it still run;
- ``check_program``: Check Program runs both ways, as ``analysis.run_validation()`` and as
  ``clicknick-cli check`` through ``dispatch()``, and both report the same findings. In
  ``rungs``, both must report ``PROGRAM_FINDING`` on ``PROGRAM_FINDING_ADDRESS``;
- ``sync``: the check sets DS100's nickname to ``Smoke_Init`` and its comment to ``50→60``
  through an edit session. Sync (``save_all_changes``) must refuse, because cp1252 has no
  ``→``. SC_.mdb must stay as it was. Then the check changes the comment to ``50°C``, and Sync
  must write the row with the initial value 0. The row must show no unsaved edit. A store
  that loads SC_.mdb again must show the same row, and CLICK's own nickname export (the
  runner's ``export``) must show it.
  The check does not redraw CLICK's ladder after the Sync, because the redraw opens CLICK's
  Import dialog, and the runner stops at a window that it does not expect;
- ``csv_round_trip``: File > Export to CSV (``CsvDataSource.save_changes``) writes the
  nicknames. The file must be cp1252, with ``°`` as the byte B0. The runner imports the file
  into the same CLICK (``import_one``). The import picks Delete Existing, so CLICK first
  empties its address table. The import must change SC_.mdb, and SC_.mdb must then hold a
  row for each address in the file and no other row. In ``rungs`` too, SC_.mdb must then hold
  no row for an address of the program that the file lacks. CLICK's export after the import
  must show ``Smoke_Init`` with ``50°C``;
- ``rung_apply``: the check adds a rung to the workspace's main.py: a contact on X001 that
  drives an Out coil on C1. ``rung apply`` through ``dispatch()`` must propose that rung for
  CLICK's empty main program. The check copies the proposal as Review Changes' Copy does.
  Copy adds the rung's addresses to SC_.mdb, and SC_.mdb must then hold a row for each
  address that laddercodec finds in the copied bytes. The runner pastes the rungs at rung 1
  (``paste_payload``) and saves the project (``save_as``). The check waits until ScrWatcher
  has counted the save and the build after the save has finished. Then laddercodec decodes
  CLICK's saved Scr*.tmp. Its main program must start with the rung. Review Changes must have
  nothing left to paste, and ``rung apply`` must answer "(no changes)". The check needs an
  empty main program, so it does not run in ``rungs``.

``sync`` and ``csv_round_trip`` write SC_.mdb, so they run after the checks that read the
project as CLICK made it. They run on every project. In a live run on 2026-11-20 they took
about 13 s for each project, so the whole smoke took about 80 s longer. In return, the smoke
checks Sync and CLICK's import against the SC_.mdb of each CPU's project. The import goes into
the same CLICK, because a second project would need a second runner run and a second CLICK.
CLICK empties its table before the import. So the ``Smoke_Init`` row in CLICK's export after
the import comes from ClickNick's file.

``rung_apply`` saves the project in CLICK, so it runs last. It runs on every project except
``rungs``. In a live run on 2026-11-21 it took about 6 s for each project, so the whole smoke
took about 35 s longer. In return, the smoke pastes into and saves the project of each CPU,
and the project with no CPU. In the same run, ``paste`` took about 5 s, and ``rungs`` took
about 32 s, as long as each of the other projects.

A check passes or fails, and it says why. A check that needs another check runs only when that
one passed. To add a check, add a ``CheckSpec`` to ``CHECKS``. Its function receives the
``Project`` and a dict for details, returns the text for a pass, and raises ``CheckFailed`` for a
fail. ``Project.run`` is the runner's ``Run``, so a check can also ask the runner to act in CLICK.
If the runner stops while it acts for a check, it raises ``cr.Aborted``. The check then fails,
and the smoke runs no more checks on the project. The runner then ends the run as it ends any
other: it dumps CLICK's windows, ends CLICK and records why.

A check that a later change adds must follow two rules:

- While a check calls a runner method, no scheduled callback runs. Call the method through
  ``project.in_click``, which runs the callbacks for ``AFTER_RUNNER`` seconds after the call.
  After a call that saves the project in CLICK, also call ``project.scheduler.wait(...)``, so
  that ScrWatcher sees CLICK's save.
- A check that changes the project, such as Sync or ``rung apply``, changes what the checks after
  it see. So the order in ``CHECKS`` is part of the contract.

ClickNick runs in the runner's process. A check can then call the runner's methods directly,
while ClickNick's build and simulation threads keep running. ``Scheduler`` stands in for the Tk
root. Whenever the smoke waits, ``Scheduler`` runs the callbacks that ClickNick scheduled.

Each project gets a folder ``DIR/<model>/``, ``DIR/none/`` or ``DIR/rungs/``:

- ``runner/``: the runner's ``--out`` folder, with its result.json and run.log. Its
  ``mdb/`` holds the copy of SC_.mdb that the runner made after the import in ``csv_round_trip``;
- ``mdb/``: the copies of SC_.mdb that ``sync`` read, before and after each Sync, and the
  copies that ``paste`` and ``rung_apply`` read before their paste;
- ``paste/``: the project that ``paste`` saved in CLICK, as ``program.ckp``, and its Scr*.tmp
  files and Project.ini, in ``click/``;
- ``sync/`` and ``csv_import/``: CLICK's nickname export after the Sync and after the import,
  as ``click/nicknames.csv`` and its copy ``export.csv``;
- ``csv/clicknick.csv``: the file that ``csv_round_trip`` wrote with Export to CSV;
- ``rung_apply/``: the project that ``rung_apply`` saved in CLICK, as ``rung_apply.ckp``, and
  its Scr*.tmp files and Project.ini, in ``click/``;
- ``result.json``: the smoke's result for the project. The smoke writes it again after each
  check.

The project's result.json holds these fields:

- ``project``: the project's name;
- ``cpu``: the CPU that the runner picked, or ``none``;
- ``status``: ``pass`` or ``fail``;
- ``problems``: why the project failed, one sentence each;
- ``runner``: the runner's status, reason, step, timings and ``scr_before_save``;
- ``checks``: one entry per check, in order, with its ``status``, ``text``, ``seconds`` and
  ``details``;
- ``callback_errors``: the traceback of each scheduled callback that raised;
- ``teardown``: how long closing ClickNick took, whether the Modbus port was free after, and
  the smoke's threads that still ran.

A project fails in any of these cases:

- the runner did not end ``ok``;
- a check failed or did not run;
- a scheduled callback raised;
- port 502 was still in use after ClickNick closed;
- a thread that a check started still ran after ClickNick closed.

``DIR/summary.json`` lists each project with its checks, and the smoke prints the same summary on
stdout. The exit code is 0 when every project passed, 1 when any failed and 2 when the smoke
refused to start or stopped early. The smoke stops early in these cases:

- the runner refused to start;
- you pressed Ctrl+C;
- the smoke itself raised an exception;
- a thread that a check started still ran after ClickNick closed;
- port 502 was in use before the next project.

These rules keep the smoke away from your own work:

- ``LOCALAPPDATA`` points at ``DIR/localappdata`` before ClickNick is imported. The smoke pairs
  no workspace, so each build writes a temporary workspace into the runner's CLICK's temp folder.
  Your simulator settings, workspace pairings, check preferences and workspaces stay untouched.
- The simulation's Modbus server listens on port 502 (``MODBUS_PORT``). The smoke refuses to
  start, and stops before the next project, while another program has the port. It names the
  port. It never stops that program.
- The runner refuses to start while any CLICK runs. The smoke then stops. It uses one CLICK at a
  time, and only CLICKs that the runner starts.
- The smoke never connects to a PLC, and no check writes to one.

``make smoke`` runs this file. It is never part of ``make test`` or CI.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import heapq
import io
import itertools
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pyclickplc.nicknames import CSV_ENCODING

sys.path.insert(0, str(Path(__file__).resolve().parent))

import click_runner as cr  # noqa: E402
from sim_driver import Driver, Scene  # noqa: E402

if TYPE_CHECKING:
    import tkinter as tk

    from clicknick.connection_session import ConnectionSession
    from clicknick.data.address_store import AddressStore
    from clicknick.data.data_source import DataSource
    from clicknick.ladder.program import PrepareResult
    from clicknick.simulation_session import SimulationSession
    from clicknick.views.simulator_window import SimulatorWindow

# The name of the project that holds a program. The runner makes a new project for PROGRAM_CPU,
# and the paste check pastes PROGRAM_CSV into its main program before the other checks
PROGRAM_PROJECT = "rungs"
# The CPU's built-in I/O is X001-X008 and Y001-Y006, so it has every X and Y that the program
# uses
PROGRAM_CPU = "C0-11DD1E-D"
# Nine of the 23 rungs of tests/click/ladder_realistic_output/main.csv in pyrung (commit
# 98b0bfb), copied as they are: rungs 1 to 6 and 21 to 23. They hold contacts, edge contacts,
# latch and reset coils, an on-delay and an off-delay timer, an up and a down counter, a
# compare, an Out coil and END. Rungs 7 to 13 use ranges, a pointer, text or drums. No check
# has shown that Copy adds every address of a range or a drum to SC_.mdb, and rung 7 also uses
# DS100, which the sync check needs unused. Rung 17 calls a subroutine, and a paste into the
# main program cannot make the subroutine. Rungs 19 and 20 send and receive over Modbus.
# Rungs 14 to 16 (a For loop, its Out coil on Y002 and Next) and rung 18 (four Copy
# instructions) have none of these problems. They are left out because no check reads what
# they add, and each new instruction is one more thing that the paste could get wrong
PROGRAM_CSV = Path(__file__).resolve().parent / "click_smoke_rungs.csv"
# The addresses that laddercodec's addresses() finds in the program's clipboard data
PROGRAM_ADDRESSES = (
    "X001",
    "Y001",
    "X002",
    "X003",
    "X007",
    "T1",
    "TD1",
    "X006",
    "T2",
    "TD2",
    "CT1",
    "CTD1",
    "CT2",
    "CTD2",
    "X004",
    "Y002",
    "C1",
    "DS3",
)
# The simulation check turns this input on in RUN. The program's first rung must then latch
# the output
PROGRAM_INPUT = "X001"
PROGRAM_OUTPUT = "Y001"
# Rungs 7 and 8 of PROGRAM_CSV both drive Y002 with an Out coil, so Check Program must report
# this finding on that address
PROGRAM_FINDING = "COIL_CONFLICTING_OUTPUT"
PROGRAM_FINDING_ADDRESS = "Y002"
# How long the panel check waits for the simulation and the Simulator's panel to show each step,
# in seconds
PANEL_WAIT = 15.0
# How long the panel check lets Modbus read the values again after the scans that it waits for,
# in seconds. The simulation reads them every 0.1 s
PANEL_SETTLE = 0.5
# The projects that the smoke makes, in order. Each is a CPU in cr.CPU_MODELS, cr.NO_CPU for a
# project with no CPU, or PROGRAM_PROJECT
PROJECTS = (
    "C0-00DD1-D",
    "C0-02DD1-D",
    "C0-11DD1E-D",
    "C0-12DD1E-2-D",
    "C2-03CPU",
    cr.NO_CPU,
    PROGRAM_PROJECT,
)
# The port that the simulation's Modbus server listens on, with ClickNick's default settings
MODBUS_PORT = 502
# The cards that read_panel_layout read in the Project.ini that CLICK 4.00 wrote for each CPU,
# and for no CPU (cr.NO_CPU), in live runs on 2026-11-20
LAYOUTS_FILE = Path(__file__).resolve().parent / "click_smoke_layouts.json"
# How long a check waits for the build, the simulation's start and Check Program, in seconds
DEFAULT_TIMEOUT = 180.0
# How long the smoke waits, after it closed ClickNick, for the Modbus port to be free and for
# the threads that the checks started to end, in seconds
CLOSE_WAIT = 20.0
# The scans that the simulation must run in RUN for the check to pass
RUN_SCANS = 10
# How long the simulation check waits for RUN, and then for RUN_SCANS scans, in seconds
RUN_WAIT = 60.0
# The row that the sync and csv_round_trip checks write. A new project has no rungs, so no rung
# uses the address
SMOKE_ADDRESS = "DS100"
SMOKE_NICKNAME = "Smoke_Init"
# cp1252 has no "→", so Sync must refuse this comment
REFUSED_COMMENT = "50→60"
# cp1252 has "°", as the byte B0
SYNCED_COMMENT = "50°C"
# How long the smoke runs ClickNick's callbacks after each call to the runner, in seconds
AFTER_RUNNER = 1.0
# The program that pyrung writes into main.py for a project with no rungs
EMPTY_PROGRAM = "with Program() as logic:\n    pass\n"
# The rung that the rung_apply check puts in place of that program's "pass": a contact on X001
# that drives an Out coil on C1. The tags.py that pyrung generates always binds `blocks`. It
# binds the short names `x` and `c` only when it declares a tag. In a new project, only the
# CPUs with analog inputs (DF1 and DF2) were observed to declare one. So the rung makes its
# own `ClickBlocks()`
RUNG_IMPORTS = (
    "from pyrung import out\nfrom pyrung.click import ClickBlocks\n\nclick = ClickBlocks()\n"
)
RUNG_SOURCE = "    with rung(click.x[1]):\n        out(click.c[1])\n"
# The rung as laddercodec's CSV writes it: the contact in column A, a wire to column AE, and
# the coil in AF
RUNG_ROW = ["R", "X001", *["-"] * 30, "out(C1)"]
# The addresses that the rung's clipboard data holds, as laddercodec's addresses() finds them
RUNG_ADDRESSES = ("X001", "C1")
# The main program's name in a ladder CSV bundle
MAIN_CSV = "main.csv"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2


class CheckFailed(Exception):
    """Raised by a check when ClickNick does not do what the check expects."""


def port_free(port: int) -> bool:
    """Return True when no socket on this computer is bound to *port*.

    The test binds a socket to the port on every address, with SO_EXCLUSIVEADDRUSE, and closes
    it again. Windows refuses that bind while any socket uses the port, on any address.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        probe.bind(("", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def port_busy_text(port: int) -> str:
    """Return the message that the smoke prints when another program has *port*."""
    return (
        f"Port {port} is in use. The simulation's Modbus server needs it. If a ClickNick "
        "Simulator is open, turn it off or close ClickNick, then run the smoke again."
    )


class Scheduler:
    """Run the callbacks that ClickNick schedules, on the thread that calls ``pump``.

    ClickNick's build, ScrWatcher and simulation schedule work with ``after`` and
    ``after_cancel``, as on a Tk root. Their threads call ``after(0, ...)`` to hand a result
    back. The smoke has no Tk root, so this class queues the callbacks, and ``pump`` runs each
    one that is due. Any thread may call ``after`` and ``after_cancel``. ``errors`` keeps the
    traceback of each callback that raised. ``threads`` keeps each thread that ``background``
    started.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: list[tuple[float, int, Callable[[], object]]] = []
        self._cancelled: set[int] = set()
        self._ids = itertools.count(1)
        self.errors: list[str] = []
        self.threads: list[threading.Thread] = []

    def after(self, ms: int, func: Callable[[], object]) -> int:
        with self._lock:
            after_id = next(self._ids)
            heapq.heappush(self._queue, (time.monotonic() + ms / 1000, after_id, func))
        return after_id

    def after_cancel(self, id: Any) -> None:
        with self._lock:
            self._cancelled.add(id)

    def run_due(self) -> None:
        """Run every callback that is due, including those that the callbacks schedule at once.

        The method runs at most 1000 callbacks, so a callback that keeps scheduling itself with
        ``after(0, ...)`` cannot hold it forever.
        """
        for _ in range(1000):
            with self._lock:
                if not self._queue or self._queue[0][0] > time.monotonic():
                    return
                _, after_id, func = heapq.heappop(self._queue)
                if after_id in self._cancelled:
                    self._cancelled.discard(after_id)
                    continue
            try:
                func()
            except Exception:
                text = traceback.format_exc()
                self.errors.append(text)
                print(f"a scheduled callback raised:\n{text}", file=sys.stderr, flush=True)

    def pump(self, seconds: float = 0.0) -> None:
        """Run due callbacks for *seconds*, or once when *seconds* is 0."""
        end = time.monotonic() + seconds
        while True:
            self.run_due()
            if time.monotonic() >= end:
                return
            time.sleep(0.02)

    def wait[T](self, what: str, until: Callable[[], T | None], timeout: float) -> T:
        """Run due callbacks until *until* returns a true value, and return that value.

        Raise ``CheckFailed`` after *timeout* seconds. The message names *what*.
        """
        deadline = time.monotonic() + timeout
        while True:
            self.run_due()
            value = until()
            if value:
                return value
            if time.monotonic() > deadline:
                raise CheckFailed(f"Timed out after {timeout:g} s waiting for {what}.")
            time.sleep(0.05)

    def background[T](self, what: str, func: Callable[[], T], timeout: float) -> T:
        """Call *func* on a thread so that the smoke can stop waiting after *timeout* seconds.

        Meanwhile this thread runs due callbacks. Return what *func* returned, raise what it
        raised, or raise ``CheckFailed`` after *timeout* seconds. After a timeout the thread
        keeps running, and ``live_threads`` lists it.
        """
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["value"] = func()
            except BaseException as exc:  # noqa: BLE001 - raised again on the pumping thread
                box["error"] = exc

        thread = threading.Thread(target=call, name=f"smoke {what}", daemon=True)
        self.threads.append(thread)
        thread.start()
        self.wait(what, lambda: "value" in box or "error" in box, timeout)
        # The thread has set the box, so it ends at once
        thread.join()
        if "error" in box:
            raise box["error"]
        return box["value"]

    def live_threads(self) -> list[str]:
        """Return the names of the threads that ``background`` started and that still run."""
        return [thread.name for thread in self.threads if thread.is_alive()]


@dataclass(frozen=True)
class PastedProgram:
    """The rungs that the paste check pasted into CLICK's main program and that CLICK saved."""

    # The rungs as the rows of laddercodec's CSV
    rows: list[list[str]]
    # The addresses that laddercodec found in the clipboard data
    addresses: tuple[str, ...]

    @property
    def io(self) -> tuple[str, ...]:
        """The X and Y addresses among ``addresses``. XD and YD are not among them."""
        return tuple(address for address in self.addresses if re.fullmatch(r"[XY]\d+", address))


class Project:
    """ClickNick connected to the project that the runner's ``new`` made, with no window.

    The session is made when a check first asks for it. A check makes the store and the
    simulation. ``close`` closes the session, and the session closes its simulation.
    """

    def __init__(
        self,
        run: cr.Run,
        new: cr.NewProject,
        folder: Path,
        scheduler: Scheduler,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        save_timeout: float | None = None,
        program: Path | None = None,
    ) -> None:
        self.run = run
        self.new = new
        self.folder = folder
        self.scheduler = scheduler
        self.timeout = timeout
        # How long a check waits for ScrWatcher to count a save in CLICK and for the build
        # after it. Unless the caller passes save_timeout, the wait uses *timeout*.
        self.save_timeout = timeout if save_timeout is None else save_timeout
        # The ladder CSV that the paste check pastes before the other checks, or None
        self.program = program
        # What the paste check pasted, once CLICK has saved it
        self.pasted: PastedProgram | None = None
        self.store: AddressStore | None = None
        self._session: ConnectionSession | None = None

    @property
    def session(self) -> ConnectionSession:
        """The session for CLICK's window, as the app opens it when you pick the window."""
        if self._session is None:
            from clicknick.connection_session import ClickConnection, ConnectionSession

            click = ClickConnection(str(self.new.pid), self.new.main, self.new.ckp.name)
            self._session = ConnectionSession(click)
        return self._session

    def simulation(self) -> SimulationSession:
        """Return the session's simulation. ``ensure_simulation`` makes it on the first call."""
        return self.session.ensure_simulation(self.scheduler)  # pyright: ignore[reportArgumentType]

    def data_source(self) -> DataSource:
        """Return a data source for the project's SC_.mdb, as the app makes it after you connect."""
        from clicknick.data.data_source import MdbDataSource

        click = self.session.click
        return MdbDataSource(click_pid=click.pid, click_hwnd=click.hwnd)

    def read_database(self, label: str) -> tuple[Path, dict[str, dict[str, Any]]]:
        """Copy CLICK's SC_.mdb to ``mdb/<label>.mdb`` in the project's folder, and read the copy.

        Return the copy and its address table by address ("DS100"). The runner's
        ``read_rows`` reads the copy through Access ODBC, so a text keeps every character.
        """
        folder = self.folder / "mdb"
        folder.mkdir(exist_ok=True)
        copy = Path(shutil.copy2(self.new.temp / "SC_.mdb", folder / f"{label}.mdb"))
        return copy, self.run.read_rows(copy)

    def prepare_paste(self, rungs: Sequence[Any]) -> PrepareResult:
        """Encode *rungs* for CLICK's clipboard, the same way Review Changes' Copy does.

        Like Copy, it adds to CLICK's SC_.mdb each address of the rungs that SC_.mdb lacks
        (``prepare_rungs_load``).
        """
        from clicknick.ladder.clipboard import is_click_v4
        from clicknick.ladder.program import prepare_rungs_load
        from clicknick.utils.mdb_shared import find_click_database

        # The paste check copies before the session exists. ``new.main`` is the window that the
        # session connects to
        hwnd = self.new.main
        mdb = find_click_database(click_hwnd=hwnd)
        return prepare_rungs_load(
            list(rungs), click_v4=is_click_v4(hwnd), mdb_path=Path(mdb) if mdb else None
        )

    def in_click[T](self, call: Callable[[], T]) -> T:
        """Call *call*, which asks the runner to act in CLICK, and return what it returns.

        No scheduled callback runs during the call. So after the call, whether it raised or
        not, the smoke runs ClickNick's callbacks for ``AFTER_RUNNER`` seconds.
        """
        try:
            return call()
        finally:
            self.scheduler.pump(AFTER_RUNNER)

    def close(self) -> dict[str, Any]:
        """Close the session, and wait until the Modbus port is free and the threads have ended.

        Return how long that took, whether the port was free after, and the names of the
        threads that ``background`` started and that still ran.
        """
        began = time.monotonic()
        if self._session is not None:
            self._session.close()
            self.scheduler.pump(1.0)
        deadline = time.monotonic() + CLOSE_WAIT
        while True:
            free = port_free(MODBUS_PORT)
            threads = self.scheduler.live_threads()
            if (free and not threads) or time.monotonic() >= deadline:
                break
            self.scheduler.pump(0.1)
        return {
            "seconds": round(time.monotonic() - began, 3),
            "port_free": free,
            "threads": threads,
        }


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckSpec:
    """One check that the smoke runs on each project."""

    name: str
    # Return the text for a pass, or raise CheckFailed. The dict receives details for the result
    run: Callable[[Project, dict[str, Any]], str]
    # The checks that must pass before this one runs
    needs: tuple[str, ...] = ()
    # The projects that the check runs on: "all", "program" for only the project that holds a
    # program (``Project.program``), or "empty" for only the projects that CLICK made empty
    projects: str = "all"


def project_checks(checks: Sequence[CheckSpec], *, program: bool) -> tuple[CheckSpec, ...]:
    """Return the specs of *checks* that run on a project, in order.

    With *program* True, the project holds a program, and the specs for "program" and "all"
    run. The "program" specs at the start of *checks* put the program into CLICK, as the paste
    does. Each "all" spec then also needs every one of them. If the paste fails, CLICK's program
    is not the program that those checks expect. A "program" spec later in *checks* needs only
    the checks that it names.
    With *program* False, the specs for "empty" and "all" run.
    """
    if not program:
        return tuple(spec for spec in checks if spec.projects in ("all", "empty"))
    first = tuple(
        spec.name for spec in itertools.takewhile(lambda spec: spec.projects == "program", checks)
    )
    return tuple(
        spec if spec.projects == "program" else replace(spec, needs=(*first, *spec.needs))
        for spec in checks
        if spec.projects in ("all", "program")
    )


def check_load(project: Project, details: dict[str, Any]) -> str:
    """Read the project's SC_.mdb into an ``AddressStore``, as the app does after you connect."""
    from clicknick.data.address_store import AddressStore

    store = AddressStore(project.data_source())
    store.load_initial_data()
    project.store = store
    project.session.has_database = True
    details["rows"] = store.loaded_row_count
    return f"Read {store.loaded_row_count} rows from SC_.mdb."


def check_build(project: Project, details: dict[str, Any]) -> str:
    """Build the workspace, as the app starts it once the database has loaded."""
    from clicknick.services.analysis_service import AnalysisStatus

    session = project.session
    session.start_analysis(project.scheduler)  # pyright: ignore[reportArgumentType]
    analysis = project.scheduler.wait(
        "the workspace build",
        lambda: (
            session.analysis
            if session.analysis is not None
            and session.analysis.status in (AnalysisStatus.READY, AnalysisStatus.FAILED)
            else None
        ),
        project.timeout,
    )
    project_dir = analysis.project_dir
    details.update(
        status=analysis.status.value,
        error=analysis.error,
        error_detail=analysis.error_detail,
        generation=analysis.generation,
        project_dir=project_dir,
        warning=analysis.build_warning,
    )
    if analysis.status is not AnalysisStatus.READY:
        raise CheckFailed(f"The build failed: {analysis.error}")
    if project_dir is None or not analysis.project_is_current:
        raise CheckFailed("The build reported READY, but it wrote no current workspace.")
    if not project_dir.resolve().is_relative_to(project.new.temp.resolve()):
        raise CheckFailed(
            f"The build wrote the workspace outside CLICK's temp folder: {project_dir}"
        )
    main = project_dir / "src" / "plc" / "main.py"
    if not main.is_file():
        raise CheckFailed(f"The workspace has no {main}.")
    if analysis.build_warning:
        raise CheckFailed(f"The build warned: {analysis.build_warning}")
    if project.pasted is None:
        return f"Built the workspace in {project_dir}."
    built = built_main_program(project_dir / "csv")
    details["main_csv"] = built
    if built != project.pasted.rows:
        raise CheckFailed(
            f"The workspace's csv/{MAIN_CSV} is not the program that CLICK saved. The details "
            "hold it as main_csv, and the paste check's details hold CLICK's save."
        )
    return (
        f"Built the workspace in {project_dir}. Its csv/{MAIN_CSV} holds the "
        f"{len(built)} rows that CLICK saved."
    )


def built_main_program(csv_dir: Path) -> list[list[str]] | None:
    """Return the main program in the workspace's *csv_dir* as laddercodec's CSV rows.

    Return None when the folder has no main program or laddercodec cannot read it.
    """
    from clicknick.services.rung_diff import load_bundle

    for program in load_bundle(csv_dir):
        if program.name == MAIN_CSV:
            return None if program.rungs is None else rung_rows(program.rungs)
    return None


def _cards(layout: Any) -> list[dict[str, Any]]:
    """Return the cards of a ``PanelLayout`` in the form that click_smoke_layouts.json uses."""
    return [
        {
            "title": card.title,
            "location": card.location,
            "position": card.position,
            "model": card.model,
            "installed": card.installed,
            "terminals": [[t.kind, t.channel, t.address] for t in card.terminals],
        }
        for card in layout.cards
    ]


def recorded_layouts() -> dict[str, dict[str, Any]]:
    """Return the layouts that click_smoke_layouts.json records, by CPU model or cr.NO_CPU."""
    return json.loads(LAYOUTS_FILE.read_text(encoding="utf-8"))


def check_layout(project: Project, details: dict[str, Any]) -> str:
    """Compare the simulation's panel layout with what ``read_panel_layout`` reads.

    The program of a new project uses no I/O, so ``read_panel_layout`` reads the Project.ini
    with no used I/O. In the project that holds a program, it reads the Project.ini with the X
    and Y addresses that the paste check found in the program. For a used address that no
    module has, the layout gets a placeholder card, and its cards then differ from the cards
    that ``click_smoke_layouts.json`` records for the CPU. ``PROGRAM_CPU`` has every one of
    them, so the cards stay the same if the Simulator finds no used I/O. So the simulation must
    also list each of them as used. In a project with no CPU, the layout must have no CPU card.
    The Simulator then shows its No CPU card in its place.
    """
    from clicknick.services.sim_hardware import read_panel_layout

    simulation = project.simulation()
    simulation.refresh_layout(force=True)
    layout, error = simulation.layout, simulation.layout_error
    cards = _cards(layout) if layout is not None else None
    details.update(
        layout_error=error, has_cpu=layout.has_cpu if layout is not None else None, cards=cards
    )
    if error is not None:
        raise CheckFailed(f"The simulation could not read the hardware: {error}")
    if layout is None:
        raise CheckFailed("The simulation has no layout.")
    used = project.pasted.io if project.pasted is not None else ()
    details["program_io"] = list(used)
    if used:
        # SimulationSession has no public way to give its used I/O. refresh_layout passes this
        # set to the layout reader, so it is the set that the Simulator's cards come from
        simulator_used = simulation._used_io()  # noqa: SLF001
        details["simulator_used_io"] = sorted(simulator_used)
        unseen = [address for address in used if address not in simulator_used]
        if unseen:
            raise CheckFailed(
                f"The program uses {', '.join(unseen)}, but the simulation does not list them as "
                "used."
            )
    expected = _cards(read_panel_layout(project.session.project_ini, used))
    if cards != expected:
        details["read_panel_layout"] = expected
        raise CheckFailed("The simulation's cards differ from what read_panel_layout reads.")
    model = project.new.model
    cpu = [card["model"] for card in cards if card["location"] == "cpu"]
    if model is None and layout.has_cpu:
        raise CheckFailed(
            f"The project has no CPU, but the layout has the CPU card {cpu}. The Simulator "
            "would not show its No CPU card."
        )
    if model is not None and cpu != [model]:
        raise CheckFailed(f"The layout's CPU card is {cpu}, not {model}.")
    recorded = recorded_layouts().get(model or cr.NO_CPU)
    counted = f"{len(cards)} card(s)" if model is not None else f"No CPU, {len(cards)} card(s)"
    if recorded is None:
        details["recorded"] = None
        return f"{counted}, as read_panel_layout reads them. No layout is recorded."
    details["recorded"] = True
    if layout.has_cpu != recorded["has_cpu"] or cards != recorded["cards"]:
        raise CheckFailed(
            f"The simulation's cards differ from the cards recorded in {LAYOUTS_FILE.name}."
        )
    return f"{counted}, as read_panel_layout reads them and as recorded."


def check_simulation(project: Project, details: dict[str, Any]) -> str:
    """Start the simulation, wait until it is READY, and switch it to RUN."""
    from clicknick.simulation_session import SimStatus

    if not port_free(MODBUS_PORT):
        raise CheckFailed(port_busy_text(MODBUS_PORT))
    simulation = project.simulation()
    simulation.turn_on()
    project.scheduler.wait(
        "the simulation to start",
        lambda: simulation.status in (SimStatus.READY, SimStatus.FAILED),
        project.timeout,
    )
    details.update(
        status=simulation.status.value,
        error=simulation.error,
        error_detail=simulation.error_detail,
        notice=simulation.notice,
    )
    if not simulation.is_ready:
        raise CheckFailed(f"The simulation did not start: {simulation.error}")
    began = time.monotonic()
    simulation.set_switch_position("run")
    first = project.scheduler.wait(
        "RUN",
        lambda: simulation.scan_id if simulation.mode == "run" and simulation.running else None,
        RUN_WAIT,
    )
    last = project.scheduler.wait(
        f"{RUN_SCANS} scans in RUN",
        lambda: (
            scan
            if simulation.mode == "run" and (scan := simulation.scan_id or 0) >= first + RUN_SCANS
            else None
        ),
        RUN_WAIT,
    )
    seconds = round(time.monotonic() - began, 3)
    details.update(mode=simulation.mode, first_scan=first, last_scan=last, run_seconds=seconds)
    text = f"READY. In RUN it scanned from scan {first} to scan {last} in {seconds:g} s."
    if project.pasted is None:
        return text
    return f"{text} {drive_program(project, simulation, project.pasted, details)}"


def drive_program(
    project: Project, simulation: SimulationSession, pasted: PastedProgram, details: dict[str, Any]
) -> str:
    """Turn ``PROGRAM_INPUT`` on in the simulation, and wait until ``PROGRAM_OUTPUT`` is on.

    The simulation polls the program's X and Y addresses over Modbus, as the Simulator's panel
    does. The check waits until it has read each of them once. ``PROGRAM_OUTPUT`` must be off
    then, and ``PROGRAM_INPUT``'s switch turns it on through the program's first rung. Return
    the text for a pass.

    Raises:
        CheckFailed: Modbus never answers for an address, ``PROGRAM_OUTPUT`` is already on, or
            it does not turn on.
    """
    io = pasted.io

    def read_all() -> dict[str, Any] | None:
        values = simulation.values
        return {address: values[address] for address in io} if set(io) <= set(values) else None

    def output_on() -> dict[str, Any] | None:
        values = simulation.values
        return values if values.get(PROGRAM_OUTPUT) else None

    simulation.watch(project, io)
    try:
        before = project.scheduler.wait(f"Modbus values for {', '.join(io)}", read_all, RUN_WAIT)
        details["io_before"] = before
        if before[PROGRAM_OUTPUT]:
            raise CheckFailed(
                f"{PROGRAM_OUTPUT} is on before the check turns {PROGRAM_INPUT} on, so the check "
                "cannot show that the program drives it."
            )
        simulation.toggle_switch(PROGRAM_INPUT)
        after = project.scheduler.wait(
            f"{PROGRAM_OUTPUT} to turn on after {PROGRAM_INPUT}", output_on, RUN_WAIT
        )
        details["io_after"] = {address: after.get(address) for address in io}
    finally:
        simulation.unwatch(project)
    return (
        f"Modbus read the program's {len(io)} X and Y addresses. {PROGRAM_INPUT} on turned "
        f"{PROGRAM_OUTPUT} on."
    )


class StillPointer:
    """A ``sim_driver.Pointer`` that draws nothing, because the panel check records no gif.

    Its bounds start at the screen's top left, so ``Driver`` works in screen coordinates.
    """

    def __init__(self) -> None:
        self.bounds = (0, 0, 0, 0)
        self.pointer = (0, 0)

    def show_click(self, seconds: float = 0.0) -> None:
        pass


def panel_shows(win: SimulatorWindow, address: str) -> dict[str, bool]:
    """Return what the Simulator's panel *win* shows for the X or Y terminal *address*.

    ``lit`` is True while the terminal's LED is lit, and ``padlock`` while its padlock shows.
    For an X terminal, ``switch`` is True while its switch shows on.
    """
    from clicknick.views import sim_palette

    canvas = win._canvas  # noqa: SLF001
    shown: dict[str, bool] = {}
    if address in win._inputs:  # noqa: SLF001
        info = win._inputs[address]  # noqa: SLF001
        shown["switch"] = canvas.itemcget(info["track"], "fill") == sim_palette.SWITCH_ON
    else:
        info = win._outputs[address]  # noqa: SLF001
    shown["lit"] = canvas.itemcget(info["led"], "fill") == sim_palette.LED_ON
    # The padlock is an arc and a rectangle. Both show or hide together
    shown["padlock"] = canvas.itemcget(info["badge"][1], "state") == "normal"
    return shown


def run_led_lit(win: SimulatorWindow) -> bool:
    """Return True while the RUN LED on the CPU card of the panel *win* is lit."""
    from clicknick.views import sim_palette

    led = win._cpu_leds["RUN"]  # noqa: SLF001
    return win._canvas.itemcget(led, "fill") == sim_palette.LED_ON  # noqa: SLF001


def panel_scene(driver: Driver, details: dict[str, Any], timeout: float) -> Scene:
    """Press the Simulator's panel as a user does, and check what the panel shows after each step.

    The simulation must be in RUN when the scene starts. In the first rung of ``PROGRAM_CSV``,
    ``PROGRAM_INPUT`` latches ``PROGRAM_OUTPUT``. The scene presses no switch that resets it.
    The steps:

    1. Switch the CPU to STOP. If ``PROGRAM_INPUT``'s switch is on, turn it off.
    2. Switch the CPU to RUN. The check expects the switch to RUN to clear ``PROGRAM_OUTPUT``,
       so ``PROGRAM_OUTPUT`` must be off.
    3. Turn ``PROGRAM_INPUT`` on. ``PROGRAM_OUTPUT`` must light.
    4. Turn ``PROGRAM_INPUT`` off. ``PROGRAM_OUTPUT`` must stay lit.
    5. Double-click ``PROGRAM_OUTPUT``. The panel forces it off, so it must go dark and show its
       padlock, and the toolbar must count one force.
    6. Click the padlock. The force must be released and the padlock gone.

    ``details["steps"]`` receives what the panel showed after each step. If a wait passes
    *timeout* seconds, ``details["steps"]`` also receives what the panel showed then.

    Raises:
        CheckFailed: A wait passed *timeout* seconds, ``PROGRAM_OUTPUT`` is on after the switch
            to RUN, or ``PROGRAM_OUTPUT`` does not stay lit after ``PROGRAM_INPUT`` turns off.
    """
    sim, win = driver.sim, driver.win
    steps: list[dict[str, Any]] = details.setdefault("steps", [])

    def record(step: str) -> None:
        steps.append(
            {
                "step": step,
                "switch_position": sim.switch_position,
                "scan": sim.scan_id,
                "run_led": run_led_lit(win),
                "values": {
                    address: sim.values.get(address) for address in (PROGRAM_INPUT, PROGRAM_OUTPUT)
                },
                "forces": sim.forces,
                "forces_button": win._forces_btn.cget("text"),  # noqa: SLF001
                PROGRAM_INPUT: panel_shows(win, PROGRAM_INPUT),
                PROGRAM_OUTPUT: panel_shows(win, PROGRAM_OUTPUT),
            }
        )

    def until(condition: Callable[[], bool], what: str) -> Scene:
        """Wait for *condition*. If the wait times out, record what the panel shows, and fail."""
        try:
            yield from driver.wait_until(condition, what, timeout)
        except TimeoutError as exc:
            record(f"timed out waiting for {what}")
            raise CheckFailed(f"On the Simulator's panel, the check {exc}.") from exc

    def scans(count: int) -> Scene:
        """Wait for *count* scans, then for Modbus to read the values again."""
        first = sim.scan_id or 0
        yield from until(lambda: (sim.scan_id or 0) >= first + count, f"{count} scans in RUN")
        yield PANEL_SETTLE

    def click(point: tuple[int, int]) -> Scene:
        yield from driver.click(point)
        driver.leave_canvas()

    def double_click(point: tuple[int, int]) -> Scene:
        yield from driver.double_click(point)
        driver.leave_canvas()

    yield from click(driver.mode_point("stop"))
    yield from until(
        lambda: sim.switch_position == "stop" and not run_led_lit(win),
        "STOP, with the RUN LED off",
    )
    record("stop")
    if sim.switch_on(PROGRAM_INPUT):
        yield from click(driver.switch_point(PROGRAM_INPUT))
        yield from until(
            lambda: not panel_shows(win, PROGRAM_INPUT)["switch"],
            f"{PROGRAM_INPUT}'s switch to show off",
        )
        record(f"{PROGRAM_INPUT} off in STOP")

    yield from click(driver.mode_point("run"))
    yield from until(
        lambda: sim.switch_position == "run" and run_led_lit(win), "RUN, with the RUN LED lit"
    )
    yield from scans(RUN_SCANS)
    record("run")
    if sim.values.get(PROGRAM_OUTPUT) or panel_shows(win, PROGRAM_OUTPUT)["lit"]:
        raise CheckFailed(
            f"{PROGRAM_OUTPUT} is on after STOP and RUN with {PROGRAM_INPUT} off, so the check "
            f"cannot show that {PROGRAM_INPUT} turns it on."
        )

    yield from click(driver.switch_point(PROGRAM_INPUT))
    yield from until(
        lambda: panel_shows(win, PROGRAM_INPUT) == {"switch": True, "lit": True, "padlock": False},
        f"{PROGRAM_INPUT}'s switch and LED to show on",
    )
    yield from until(
        lambda: panel_shows(win, PROGRAM_OUTPUT)["lit"],
        f"{PROGRAM_OUTPUT}'s LED to light after {PROGRAM_INPUT} turned on",
    )
    record(f"{PROGRAM_INPUT} on")

    yield from click(driver.switch_point(PROGRAM_INPUT))
    yield from until(
        lambda: not any(panel_shows(win, PROGRAM_INPUT).values()),
        f"{PROGRAM_INPUT}'s switch and LED to show off",
    )
    yield from scans(RUN_SCANS)
    record(f"{PROGRAM_INPUT} off")
    if not (sim.values.get(PROGRAM_OUTPUT) and panel_shows(win, PROGRAM_OUTPUT)["lit"]):
        raise CheckFailed(
            f"The program latches {PROGRAM_OUTPUT}, but it went off after {PROGRAM_INPUT} "
            "turned off."
        )

    yield from double_click(driver.output_point(PROGRAM_OUTPUT))
    yield from until(
        lambda: (
            sim.forces == {PROGRAM_OUTPUT: False}
            and sim.values.get(PROGRAM_OUTPUT) is False
            and panel_shows(win, PROGRAM_OUTPUT) == {"lit": False, "padlock": True}
            and win._forces_btn.cget("text") == "Forces (1)"  # noqa: SLF001
        ),
        f"the double-click to force {PROGRAM_OUTPUT} off, with its LED dark, its padlock "
        "showing and the toolbar's Forces (1)",
    )
    record(f"{PROGRAM_OUTPUT} forced")

    # Tk gives a generated event the time 0. A second double-click on the same spot would count
    # both of its presses as a double-click. That would release the force and force the output
    # again.
    yield from click(driver.padlock_point(PROGRAM_OUTPUT))
    yield from until(
        lambda: (
            not sim.forces
            and not panel_shows(win, PROGRAM_OUTPUT)["padlock"]
            and win._forces_btn.cget("text") == "Forces"  # noqa: SLF001
        ),
        f"the click on the padlock to release {PROGRAM_OUTPUT}'s force and hide the padlock",
    )
    record(f"{PROGRAM_OUTPUT} released")


def play(scene: Scene, pump: Callable[[], None], *, realtime: bool = True) -> None:
    """Run *scene* to its end, and call *pump* while it runs.

    After each step, the function calls *pump* until the delay that the step yielded has
    passed. With *realtime* False, it calls *pump* once and goes on at once.
    """
    for delay in scene:
        end = time.monotonic() + (delay if realtime else 0.0)
        pump()
        while time.monotonic() < end:
            time.sleep(0.01)
            pump()


def press_panel(
    project: Project,
    root: tk.Misc,
    details: dict[str, Any],
    *,
    timeout: float = PANEL_WAIT,
    realtime: bool = True,
) -> str:
    """Open the Simulator on *root* for the project's simulation, and run ``panel_scene`` on it.

    The window is ClickNick's own ``SimulatorWindow``. ``sim_driver.Driver`` presses it with
    synthetic Tk events, as record_simulator_gif.py does. While the scene runs, the function
    runs ClickNick's scheduled callbacks and Tk's events. At the end, it releases any force
    that the scene left in place and closes the window. Return the text for a pass.

    Raises:
        CheckFailed: The scene failed, or one of its waits timed out. Or the scene passed, and
            the release of the forces, the close of the window or the callbacks after them
            raised.
    """
    from clicknick.views.simulator_window import SimulatorWindow

    simulation = project.simulation()
    win = SimulatorWindow(
        root,
        simulation=simulation,
        get_store=lambda: project.store,
        get_analysis=lambda: project.session.analysis,
        open_dataview=lambda: None,
        title_suffix="make smoke",
    )

    def pump() -> None:
        project.scheduler.run_due()
        root.update()

    def release_forces() -> None:
        # release_all_forces only queues the release for the simulation's worker. The pump after
        # it does not wait for the release. No later check reads the forces.
        if simulation.forces:
            simulation.release_all_forces()

    cleanup = (
        ("release the forces", release_forces),
        ("close the Simulator window", win._on_close),  # noqa: SLF001
        ("run the callbacks after the close", pump),
    )
    failed: list[str] = []
    try:
        pump()
        driver = Driver(win, simulation, StillPointer())
        play(panel_scene(driver, details, timeout), pump, realtime=realtime)
    finally:
        # Each step runs even if the one before it raised
        for name, step in cleanup:
            try:
                step()
            except Exception as exc:
                traceback.print_exc()
                failed.append(f"{name} ({type(exc).__name__}: {exc})")
    if failed:
        raise CheckFailed(
            "The steps on the Simulator's panel passed, but the check could not "
            f"{', '.join(failed)}."
        )
    return (
        f"On the Simulator's panel, STOP and RUN moved the CPU's switch. {PROGRAM_INPUT}'s switch "
        f"turned {PROGRAM_OUTPUT} on, and {PROGRAM_OUTPUT} stayed on after {PROGRAM_INPUT} turned "
        f"off. A double-click forced {PROGRAM_OUTPUT} off and showed its padlock, and a click on "
        "the padlock released the force."
    )


def check_panel(project: Project, details: dict[str, Any]) -> str:
    """Press switches on the Simulator's panel, and check what the simulation and the panel show.

    ``press_panel`` says how, and ``panel_scene`` says what the check presses. The check runs
    after the simulation check, which leaves the simulation in RUN.
    """
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        return press_panel(project, root, details)
    finally:
        root.destroy()


def check_program(project: Project, details: dict[str, Any]) -> str:
    """Run Check Program as the app runs it, and ``clicknick-cli check`` as dispatch runs it.

    The CLI's text holds notes and a status line around the report, so the check passes when
    the CLI's text contains the app's report.

    A new project has no rungs, so there the check shows only that both ways run and print the
    same report. In the project that holds a program, both ways check that program, and both
    reports must hold ``PROGRAM_FINDING`` on ``PROGRAM_FINDING_ADDRESS``. The check keeps both
    reports in its details and judges no other finding.
    """
    from clicknick.live.dispatch import DispatchContext, dispatch
    from clicknick.services.program_check import format_validation_report

    session = project.session
    analysis = session.analysis
    assert analysis is not None
    timeout = project.timeout
    run = project.scheduler.background("Check Program", analysis.run_validation, timeout)
    if run is None:
        raise CheckFailed("analysis.run_validation() returned None, so the analysis has no result.")
    app_text = format_validation_report(run.report)
    details["app"] = app_text
    context = DispatchContext(store=project.store, analysis=analysis, get_session=lambda: session)
    cli_text = project.scheduler.background(
        "clicknick-cli check", lambda: dispatch(context, "check"), timeout
    )
    details["cli"] = cli_text
    if app_text not in cli_text:
        raise CheckFailed("The CLI's check does not report what Check Program reports.")
    if project.pasted is not None:
        for way, text in (("Check Program", app_text), ("The CLI's check", cli_text)):
            if PROGRAM_FINDING not in text or PROGRAM_FINDING_ADDRESS not in text:
                raise CheckFailed(
                    f"{way} does not report {PROGRAM_FINDING} on {PROGRAM_FINDING_ADDRESS}, but "
                    f"two rungs of the program drive {PROGRAM_FINDING_ADDRESS} with an Out coil."
                )
    return f"Both report: {app_text.splitlines()[0]}"


def _row(store: AddressStore, key: int) -> dict[str, Any]:
    """Return the fields of the row *key* that the Address Editor shows, and its edit state."""
    row = store.visible_state[key]
    return {
        "nickname": row.nickname,
        "comment": row.comment,
        "initial_value": row.initial_value,
        "retentive": row.retentive,
        "used": row.used,
        "comment_error": row.comment_error,
        "dirty": store.is_dirty(key),
    }


def stored_forms(data: bytes, text: str) -> dict[str, dict[str, Any]]:
    """Count how often the file *data* holds *text* in each form that Access may store it in.

    The forms are UTF-16-LE, and Jet 4's Unicode compression. Jet 4 stores a compressed text
    as the bytes FF FE, then one byte for each character. Only a text whose characters are
    all below U+0100 has that form. The result maps each form to its bytes in hex and its
    count.
    """
    forms = {"utf-16-le": text.encode("utf-16-le")}
    try:
        forms["compressed"] = b"\xff\xfe" + text.encode("latin-1")
    except UnicodeEncodeError:
        pass
    return {name: {"bytes": raw.hex(" "), "found": data.count(raw)} for name, raw in forms.items()}


def exported_row(data: bytes, nickname: str) -> dict[str, Any]:
    """Return the row for *nickname* in the nickname CSV *data* that CLICK exported.

    A file that starts with the UTF-8 byte order mark is read as UTF-8, and any other file as
    cp1252. A file without the mark is not read as UTF-8 even when it decodes as UTF-8. If it
    were, a cp1252 file that holds "50Â°C" would read as "50°C". A cp1252 file is read with
    pyclickplc's ``CSV_ENCODING``. That codec also reads the five bytes that Python's cp1252
    lacks, such as 81, which CLICK 4.00 writes for U+0081. The result holds the encoding, the
    row's address, initial value and comment, and the bytes of the comment and of its line, in
    hex.

    Raises:
        CheckFailed: A file with the mark does not decode as UTF-8, or no row has *nickname*.
    """
    bom = data.startswith(codecs.BOM_UTF8)
    encoding = "utf-8-sig" if bom else "cp1252"
    codec = "utf-8-sig" if bom else CSV_ENCODING
    try:
        text = data.decode(codec)
    except UnicodeDecodeError as exc:
        raise CheckFailed(f"CLICK's export does not decode as {encoding}: {exc}") from exc
    found = next(
        (
            row
            for row in csv.DictReader(io.StringIO(text, newline=""))
            if row.get("Nickname") == nickname
        ),
        None,
    )
    if found is None:
        raise CheckFailed(f"CLICK's export has no row for {nickname}.")
    comment = found.get("Address Comment") or ""
    plain = codec.removesuffix("-sig")
    line = next(line for line in data.splitlines() if nickname.encode(plain) in line)
    return {
        "encoding": encoding,
        "address": found.get("Address"),
        "initial_value": found.get("Initial Value"),
        "comment": comment,
        "comment_bytes": comment.encode(plain).hex(" "),
        "line_bytes": line.hex(" "),
    }


def check_exported(found: dict[str, Any]) -> None:
    """Raise ``CheckFailed`` unless CLICK's export shows the row that the sync check wrote."""
    got = (found["address"], found["initial_value"], found["comment"])
    expected = (SMOKE_ADDRESS, "0", SYNCED_COMMENT)
    if got != expected:
        raise CheckFailed(
            f"CLICK's export shows {SMOKE_NICKNAME} as {got!r}, not {expected!r}. Its "
            f"comment's bytes are {found['comment_bytes']} ({found['encoding']})."
        )


def check_sync(project: Project, details: dict[str, Any]) -> str:
    """Give an empty DS row a nickname and a comment, as the Address Editor does, and Sync.

    Sync must refuse the comment ``REFUSED_COMMENT`` and leave SC_.mdb as it was. It must
    write ``SYNCED_COMMENT``, with the initial value 0. A fresh store must read the same row
    from SC_.mdb, and CLICK's own nickname export must show it. The check calls
    ``save_all_changes`` as the Address Editor's Sync does. The store has no sync listener, so
    nothing redraws CLICK's ladder. The redraw would open CLICK's Import dialog, and the runner
    stops at a window that it does not expect.

    The details hold the bytes of the comment in SC_.mdb (``stored_forms``) and in CLICK's
    export (``exported_row``).
    """
    from pyclickplc.addresses import get_addr_key, parse_address

    from clicknick.data.address_store import AddressStore

    store = project.store
    assert store is not None
    key = get_addr_key(*parse_address(SMOKE_ADDRESS))
    details["row_before"] = _row(store, key)
    if store.visible_state[key].has_content or store.visible_state[key].used:
        raise CheckFailed(f"{SMOKE_ADDRESS} is not an empty row that no rung uses.")
    copy, table = project.read_database("before_sync")
    file_before = hashlib.sha256(copy.read_bytes()).hexdigest()

    with store.edit_session(f"Smoke: {SMOKE_NICKNAME}") as session:
        session.set_field(key, "nickname", SMOKE_NICKNAME)
        session.set_field(key, "comment", REFUSED_COMMENT)
    details["refused_row"] = _row(store, key)
    try:
        written = store.save_all_changes()
    except RuntimeError as exc:
        details["refusal"] = str(exc)
    else:
        raise CheckFailed(
            f"Sync did not refuse the comment {REFUSED_COMMENT!r}. It wrote {len(written)} row(s)."
        )
    copy, refused = project.read_database("after_refusal")
    details["file_unchanged_after_refusal"] = (
        hashlib.sha256(copy.read_bytes()).hexdigest() == file_before
    )
    if refused != table:
        raise CheckFailed("Sync refused the comment, but SC_.mdb changed.")

    with store.edit_session(f"Smoke: {SYNCED_COMMENT}") as session:
        session.set_field(key, "comment", SYNCED_COMMENT)
    written = store.save_all_changes()
    details["written"] = [hex(written_key) for written_key in sorted(written)]
    synced = _row(store, key)
    details["synced_row"] = synced
    if key not in written:
        raise CheckFailed(f"Sync did not write {SMOKE_ADDRESS}.")
    expected = (SMOKE_NICKNAME, SYNCED_COMMENT, "0", False)
    got = (synced["nickname"], synced["comment"], synced["initial_value"], synced["dirty"])
    if got != expected or store.has_unsaved_changes():
        raise CheckFailed(
            f"After the Sync, {SMOKE_ADDRESS} shows {got!r} (nickname, comment, initial value, "
            f"unsaved edit), not {expected!r}, or the store still has unsaved edits."
        )

    copy, table = project.read_database("after_sync")
    stored = table.get(SMOKE_ADDRESS)
    details["mdb_row"] = stored
    details["mdb_comment"] = stored_forms(copy.read_bytes(), SYNCED_COMMENT)
    got = None if stored is None else (stored["Nickname"], stored["Comment"])
    if got != (SMOKE_NICKNAME, SYNCED_COMMENT):
        raise CheckFailed(
            f"SC_.mdb holds {got!r} for {SMOKE_ADDRESS}, not {(SMOKE_NICKNAME, SYNCED_COMMENT)!r}."
        )

    fresh = AddressStore(project.data_source())
    fresh.load_initial_data()
    details["reloaded_row"] = _row(fresh, key)
    if details["reloaded_row"] != synced or fresh.has_unsaved_changes():
        raise CheckFailed(
            f"A store loaded from SC_.mdb again shows {SMOKE_ADDRESS} differently, or it has "
            "unsaved edits."
        )

    export = project.in_click(lambda: project.run.export(project.folder / "sync"))
    found = exported_row(Path(export["copy"]).read_bytes(), SMOKE_NICKNAME)
    details["click_export"] = found
    check_exported(found)
    return (
        f"Sync refused {REFUSED_COMMENT!r}. It wrote {SYNCED_COMMENT!r} and the initial value "
        f"0, and a reload shows the same. CLICK's export ({found['encoding']}) shows the "
        f"comment as {found['comment_bytes']}."
    )


def check_csv_round_trip(project: Project, details: dict[str, Any]) -> str:
    """Export the nicknames to CSV, as File > Export to CSV does, and import the file into CLICK.

    ClickNick's file must be cp1252, with ``SYNCED_COMMENT`` as the bytes ``35 30 B0 43``.
    The runner imports the file into the same CLICK. Its import picks Delete Existing, so
    CLICK first empties its address table. The import must change SC_.mdb, and SC_.mdb must
    then hold a row for each address in the file and no other row. CLICK's own export after
    the import must show the row that the sync check wrote.

    The comparison holds in the project that holds a program too. ClickNick's file holds only
    the rows with content (``AddressRow.has_content``), so it lacks the addresses of the
    program that have none. Before the import, SC_.mdb holds rows for them. In a live run on
    2026-11-21, CLICK's Delete Existing removed those rows, and CLICK's own nickname export did
    not list them either.

    The check compares the file's addresses with SC_.mdb, not with CLICK's export. The export
    also lists each system address that has a built-in nickname, and SC_.mdb has no row for
    most of them.
    """
    from clicknick.data.data_source import CsvDataSource

    store = project.store
    assert store is not None
    folder = project.folder / "csv"
    folder.mkdir()
    path = folder / "clicknick.csv"
    count = CsvDataSource(str(path)).save_changes(list(store.visible_state.values()))
    data = path.read_bytes()
    facts = cr.export_facts(data)
    line = next((line for line in data.splitlines() if SMOKE_NICKNAME.encode() in line), b"")
    details.update(
        csv=path,
        rows=count,
        bom=facts["bom"],
        utf8=facts["utf8"],
        cp1252=facts["cp1252"],
        line_bytes=line.hex(" "),
    )
    if (
        facts["bom"] is not None
        or not facts["cp1252"]
        or SYNCED_COMMENT.encode("cp1252") not in line
    ):
        raise CheckFailed(
            f"Export to CSV did not write {SMOKE_NICKNAME}'s comment {SYNCED_COMMENT!r} in "
            f"cp1252 with no byte order mark. The file's line for it is {line!r}."
        )

    entry = project.in_click(lambda: project.run.import_one(1, "clicknick", path, None, None))
    details["import"] = {
        name: entry[name] for name in ("answer", "message", "errors", "mdb", "mdb_changed")
    }
    if entry["answer"] != "completed":
        raise CheckFailed(
            f"CLICK did not import ClickNick's CSV cleanly. It answered: {entry['message']}"
        )
    if not entry["mdb_changed"]:
        raise CheckFailed(
            "CLICK answered that it imported ClickNick's CSV, but SC_.mdb did not change."
        )
    in_file = {
        row["Address"] for row in csv.DictReader(io.StringIO(data.decode(CSV_ENCODING), newline=""))
    }
    stored = set(project.run.read_rows(Path(entry["mdb"])))
    details["addresses"] = {"file": sorted(in_file), "mdb": sorted(stored)}
    if project.pasted is not None:
        details["addresses"]["program"] = sorted(project.pasted.addresses)
    if stored != in_file:
        raise CheckFailed(
            f"After the import, SC_.mdb lacks {sorted(in_file - stored)} from ClickNick's CSV "
            f"and holds {sorted(stored - in_file)} that the file lacks."
        )
    export = project.in_click(lambda: project.run.export(project.folder / "csv_import"))
    found = exported_row(Path(export["copy"]).read_bytes(), SMOKE_NICKNAME)
    details["click_export"] = found
    check_exported(found)
    return (
        f"CLICK imported the {count} row(s) of ClickNick's cp1252 CSV, and its export shows "
        f"{SMOKE_NICKNAME} with {SYNCED_COMMENT!r}."
    )


def rung_rows(rungs: Sequence[Any]) -> list[list[str]]:
    """Return *rungs* as the rows of laddercodec's CSV, one row per rung row."""
    from laddercodec import csv_rows

    return csv_rows(list(rungs))


def is_smoke_rung(rung: Any) -> bool:
    """Return whether *rung* is the rung that ``RUNG_SOURCE`` writes, and nothing else."""
    return rung_rows([rung]) == [RUNG_ROW]


def add_smoke_rung(source: str) -> str:
    """Return the workspace's main.py *source* with ``RUNG_SOURCE`` as the program's one rung.

    Raises:
        CheckFailed: *source* does not hold the empty program that pyrung generates for a
            project with no rungs.
    """
    if source.count(EMPTY_PROGRAM) != 1:
        raise CheckFailed(
            "The workspace's main.py does not hold the empty program "
            f"{EMPTY_PROGRAM!r} once, so the check cannot add its rung there."
        )
    program = EMPTY_PROGRAM.replace("    pass\n", RUNG_SOURCE)
    return source.replace(EMPTY_PROGRAM, f"{RUNG_IMPORTS}\n{program}")


def saved_main_program(click_dir: Path) -> tuple[list[Any], list[str]]:
    """Decode the main program from the Scr*.tmp files in *click_dir* with laddercodec.

    Return the main program's rungs and the text of each warning that laddercodec issued.

    Raises:
        CheckFailed: No Scr*.tmp file holds the main program.
    """
    from laddercodec import decode_program

    from clicknick.utils.click_temp import scr_files

    rungs: list[Any] | None = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for path in scr_files(click_dir):
            program = decode_program(path.read_bytes())
            if program.prog_idx == 1:
                rungs = list(program.rungs)
    if rungs is None:
        raise CheckFailed(f"No Scr*.tmp file in {click_dir} holds the main program.")
    return rungs, [f"{warning.category.__name__}: {warning.message}" for warning in caught]


def check_paste(project: Project, details: dict[str, Any]) -> str:
    """Paste the project's program into CLICK's empty main program, and save the project.

    The check reads the ladder CSV ``Project.program`` and copies its rungs as Review Changes'
    Copy does (``Project.prepare_paste``). Copy adds the rungs' addresses to SC_.mdb. The
    addresses that laddercodec's ``addresses`` finds in the copied bytes must be
    ``PROGRAM_ADDRESSES``, and SC_.mdb must then hold a row for each of them. CLICK drops a
    pasted operand whose address SC_.mdb lacks.

    The runner pastes the rungs at rung 1 and saves the project as ``paste/program.ckp``. The
    main program that laddercodec decodes from the saved Scr*.tmp must hold the same rungs as
    the CSV. The check runs before ClickNick reads the project, so no build and no ScrWatcher
    sees the save.
    """
    from laddercodec import addresses, read_csv

    assert project.program is not None
    rungs = list(read_csv(project.program))
    rows = rung_rows(rungs)
    details["csv"] = project.program
    details["rows"] = rows
    prepared = project.prepare_paste(rungs)
    needed = addresses(prepared.payload)
    details["copy"] = {
        "rungs": prepared.rung_count,
        "clicknick_addresses": prepared.addresses,
        "laddercodec_addresses": needed,
        "inserted": prepared.addresses_inserted,
        "mdb_error": prepared.mdb_error,
    }
    if prepared.mdb_error:
        raise CheckFailed(
            f"Copy could not add the rungs' addresses to SC_.mdb: {prepared.mdb_error}"
        )
    if sorted(needed) != sorted(PROGRAM_ADDRESSES):
        raise CheckFailed(
            f"laddercodec finds {', '.join(needed) or 'no address'} in the copied rungs, not "
            f"{', '.join(PROGRAM_ADDRESSES)}."
        )
    _copy, table = project.read_database("before_program_paste")
    missing = [address for address in needed if address not in table]
    if missing:
        raise CheckFailed(
            f"SC_.mdb has no row for {', '.join(missing)} after Copy. CLICK would drop those "
            "operands from the paste."
        )

    folder = project.folder / "paste"
    folder.mkdir()
    ckp = folder / "program.ckp"

    def paste_and_save() -> str:
        run, temp = project.run, project.new.temp
        how = run.paste_payload(
            prepared.payload, prepared.rung_count, before="before_program", after="program_pasted"
        )
        run.save_as(ckp, temp, prefix="program_")
        run.copy_temp(temp, folder / "click")
        return how

    details["paste"] = project.in_click(paste_and_save)
    # CLICK's window names the saved file now, so the session that the next checks make must too
    project.new = replace(project.new, ckp=ckp)
    saved, found = saved_main_program(folder / "click")
    details["click_saved"] = rung_rows(saved)
    details["decode_warnings"] = found
    if details["click_saved"] != rows:
        raise CheckFailed(
            f"The main program in CLICK's save is not the program in {project.program.name}. "
            "The check's details hold both, as click_saved and rows."
        )
    project.pasted = PastedProgram(rows, tuple(needed))
    return (
        f"CLICK pasted the {len(rungs)} rungs of {project.program.name} at rung 1 and saved "
        f"them. SC_.mdb held their {len(needed)} addresses before the paste."
    )


def check_rung_apply(project: Project, details: dict[str, Any]) -> str:
    """Add a rung to the workspace's main.py, and take it into CLICK as Review Changes does.

    The check adds ``RUNG_SOURCE`` to main.py and runs ``rung apply`` through ``dispatch()``,
    as ``clicknick-cli rung apply`` does. ``rung apply`` writes the proposal into
    ``csv_output/``. The check reads it and compares it with CLICK's program, as Review
    Changes does. CLICK's main program must hold no rungs, because the runner can paste only
    at rung 1. Then the check copies the proposed main program as Review Changes' Copy does
    (``Project.prepare_paste``). Copy adds the rungs' addresses to SC_.mdb. Each address that
    laddercodec's ``addresses`` finds in the copied bytes must then have a row in SC_.mdb,
    because CLICK drops a pasted operand whose address SC_.mdb lacks.

    The runner pastes at rung 1 and saves the project as ``rung_apply/rung_apply.ckp``. The
    check waits until ScrWatcher has counted that save and the build after it has finished.
    Then these must hold:

    - The first rung of the main program, decoded from the saved Scr*.tmp with laddercodec,
      is the contact on X001 and the Out coil on C1.
    - The proposal that the check read before the paste no longer differs from CLICK's main
      program. Review Changes then has nothing left to paste for it.
    - ``rung apply`` again answers "(no changes)".
    """
    from laddercodec import addresses

    from clicknick.live.dispatch import DispatchContext, dispatch
    from clicknick.services.analysis_service import AnalysisStatus
    from clicknick.services.rung_diff import compare_bundle, load_bundle

    session = project.session
    analysis = session.analysis
    assert analysis is not None and analysis.project_dir is not None
    project_dir = analysis.project_dir
    main = project_dir / "src" / "plc" / "main.py"
    edited = add_smoke_rung(main.read_text(encoding="utf-8"))
    main.write_text(edited, encoding="utf-8", newline="\n")
    details["main_py"] = edited

    context = DispatchContext(store=project.store, analysis=analysis, get_session=lambda: session)
    applied = project.scheduler.background(
        "rung apply", lambda: dispatch(context, "rung apply"), project.timeout
    )
    details["rung_apply"] = applied
    programs = load_bundle(project_dir / "csv_output")
    change = compare_bundle(programs, project_dir / "csv").changes.get(MAIN_CSV)
    if change is None or not change.differs:
        raise CheckFailed(
            f"rung apply proposes no change to the main program. It answered: {applied}"
        )
    details["click_main"] = rung_rows(change.before)
    details["proposal"] = rung_rows(change.after)
    if change.before:
        raise CheckFailed(
            f"CLICK's main program holds {len(change.before)} rung(s). The runner can paste "
            "only at rung 1, so the check needs a main program with no rungs."
        )
    if not is_smoke_rung(change.after[0]):
        raise CheckFailed(
            "The first rung that rung apply proposes is not the contact on X001 and the Out "
            "coil on C1 that the check added to main.py."
        )

    prepared = project.prepare_paste(change.after)
    needed = addresses(prepared.payload)
    details["copy"] = {
        "rungs": prepared.rung_count,
        "clicknick_addresses": prepared.addresses,
        "laddercodec_addresses": needed,
        "inserted": prepared.addresses_inserted,
        "mdb_error": prepared.mdb_error,
    }
    if prepared.mdb_error:
        raise CheckFailed(
            f"Copy could not add the rungs' addresses to SC_.mdb: {prepared.mdb_error}"
        )
    if sorted(needed) != sorted(RUNG_ADDRESSES):
        found = ", ".join(needed) or "no address"
        raise CheckFailed(
            f"laddercodec finds {found} in the copied rungs, not {' and '.join(RUNG_ADDRESSES)}."
        )
    _copy, table = project.read_database("before_paste")
    missing = [address for address in needed if address not in table]
    if missing:
        raise CheckFailed(
            f"SC_.mdb has no row for {', '.join(missing)} after Copy. CLICK would drop those "
            "operands from the paste."
        )

    folder = project.folder / "rung_apply"
    folder.mkdir()
    saves = session.saved_program().save_count
    details["generation_before"] = analysis.generation

    def paste_and_save() -> str:
        run, temp = project.run, project.new.temp
        how = run.paste_payload(
            prepared.payload,
            prepared.rung_count,
            before="before_rung_apply",
            after="rung_apply_pasted",
        )
        run.save_as(folder / "rung_apply.ckp", temp, prefix="rung_apply_")
        run.copy_temp(temp, folder / "click")
        return how

    details["paste"] = project.in_click(paste_and_save)
    saved = project.scheduler.wait(
        "ScrWatcher to count CLICK's save and the build after it to finish",
        lambda: (
            program
            if (program := session.saved_program()).save_count > saves and not program.building
            else None
        ),
        project.save_timeout,
    )
    details["generation_after"] = analysis.generation
    details["saves"] = saved.save_count - saves
    if analysis.status is not AnalysisStatus.READY or saved.csv_dir is None:
        raise CheckFailed(f"The build after CLICK's save failed: {analysis.error or saved.note}")

    rungs, found = saved_main_program(folder / "click")
    details["click_saved"] = rung_rows(rungs)
    details["decode_warnings"] = found
    if not rungs or not is_smoke_rung(rungs[0]):
        raise CheckFailed(
            "CLICK's save does not hold the contact on X001 and the Out coil on C1 at rung 1."
        )
    after = compare_bundle(programs, saved.csv_dir).changes.get(MAIN_CSV)
    if after is None:
        raise CheckFailed(
            "After CLICK's save and the build, Review Changes finds no main program to compare."
        )
    if after.differs:
        work = []
        if after.changed:
            numbers = ", ".join(map(str, after.changed))
            work.append(f"rung(s) {numbers} of the proposal to paste")
        if after.removed:
            numbers = ", ".join(map(str, after.removed))
            work.append(f"CLICK's rung(s) {numbers} to delete")
        if not work:
            raise CheckFailed(
                "After CLICK's save and the build, ClickNick cannot read CLICK's copy of the main "
                "program, so Review Changes would paste it whole again."
            )
        raise CheckFailed(
            f"After CLICK's save and the build, Review Changes still has {' and '.join(work)} "
            "in the main program."
        )
    again = project.scheduler.background(
        "rung apply after the save", lambda: dispatch(context, "rung apply"), project.timeout
    )
    details["rung_apply_after_save"] = again
    if "(no changes)" not in again.splitlines():
        raise CheckFailed(f"After CLICK's save, rung apply still proposes changes: {again}")
    return (
        f"rung apply proposed {len(change.after)} rung(s) for main. SC_.mdb held "
        f"{', '.join(needed)} before the paste. CLICK saved the rung at rung 1, and after the "
        "build Review Changes has nothing left to paste."
    )


CHECKS: tuple[CheckSpec, ...] = (
    # The checks below must see the program that CLICK saved, so the paste runs first
    CheckSpec("paste", check_paste, projects="program"),
    CheckSpec("load", check_load),
    CheckSpec("build", check_build, needs=("load",)),
    CheckSpec("layout", check_layout),
    CheckSpec("simulation", check_simulation, needs=("build",)),
    # The panel check needs the simulation in RUN, as the simulation check leaves it. It presses
    # the program's I/O, so it runs only in the project that holds the program
    CheckSpec("panel", check_panel, needs=("simulation",), projects="program"),
    CheckSpec("check_program", check_program, needs=("build",)),
    # Sync and CLICK's import write SC_.mdb. The checks above must see the project as CLICK
    # made it, so these two run after them
    CheckSpec("sync", check_sync, needs=("load",)),
    # After the import, SC_.mdb must hold a row for each address in ClickNick's CSV and no
    # other row. The check's docstring says why that holds in a project with rungs too
    CheckSpec("csv_round_trip", check_csv_round_trip, needs=("sync",)),
    # rung_apply pastes a rung and saves the project in CLICK, so it runs last. Its proof
    # needs a main program with no rungs, so it runs only on the projects that CLICK made empty
    CheckSpec("rung_apply", check_rung_apply, needs=("build",), projects="empty"),
)


def run_checks(
    project: Project,
    checks: Sequence[CheckSpec],
    results: dict[str, dict[str, Any]],
    written: Callable[[], None],
) -> None:
    """Run *checks* on *project* in order, and put each one's entry into *results*.

    Call *written* after each check, so that the project's result.json keeps what was done
    if the process dies.

    Raises:
        cr.Aborted: A check asked the runner to act in CLICK, and the runner stopped. The
            check's entry is in *results*, and the checks after it do not run.
    """
    for spec in checks:
        began = time.monotonic()
        details: dict[str, Any] = {}
        aborted: cr.Aborted | None = None
        failed = [name for name in spec.needs if results.get(name, {}).get("status") != "pass"]
        if failed:
            status, text = "fail", f"Not run, because {', '.join(failed)} did not pass."
        else:
            project.run.log(f"smoke check {spec.name}")
            try:
                status, text = "pass", spec.run(project, details)
            except CheckFailed as exc:
                status, text = "fail", str(exc)
            except cr.Aborted as exc:
                # The runner stopped in CLICK. The run must end as the runner ends it, with its
                # dump of CLICK's windows and the code of CLICK's error box
                aborted = exc
                status, text = "fail", f"The runner stopped: {type(exc).__name__}: {exc}"
                details["traceback"] = traceback.format_exc()
            except Exception as exc:
                status, text = "fail", f"{type(exc).__name__}: {exc}"
                details["traceback"] = traceback.format_exc()
            project.run.log(f"smoke check {spec.name}: {status}: {text}")
        results[spec.name] = {
            "status": status,
            "text": text,
            "seconds": round(time.monotonic() - began, 3),
            "details": details,
        }
        written()
        if aborted is not None:
            raise aborted


# ---------------------------------------------------------------------------
# The projects
# ---------------------------------------------------------------------------

RunNew = Callable[[cr.Settings, Callable[[cr.Run, cr.NewProject], None]], dict[str, Any]]


def run_new(settings: cr.Settings, on_new_project: Callable[[cr.Run, cr.NewProject], None]):
    """Run the runner's ``new`` mode with *on_new_project*, and return the runner's result."""
    from click_desktop import Win32Desktop

    return cr.Run(Win32Desktop(), settings, on_new_project=on_new_project).execute()


def _json(value: object) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False) + "\n"


def project_cpu(name: str) -> str:
    """Return the CPU that the runner picks for the project *name*, or cr.NO_CPU."""
    return PROGRAM_CPU if name == PROGRAM_PROJECT else name


def smoke_project(
    name: str,
    folder: Path,
    *,
    checks: Sequence[CheckSpec] = CHECKS,
    runner: RunNew = run_new,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Make the project *name* with the runner, run *checks* on it, and return the result.

    *name* is a CPU model, cr.NO_CPU or PROGRAM_PROJECT. For PROGRAM_PROJECT, the runner makes
    a project for PROGRAM_CPU, and the project's ``program`` is PROGRAM_CSV. The checks that
    run are the ones that ``project_checks`` picks from *checks*. The function writes the
    result to ``folder/result.json`` and returns it.
    """
    program = PROGRAM_CSV if name == PROGRAM_PROJECT else None
    checks = project_checks(checks, program=program is not None)
    folder.mkdir(parents=True)
    began = time.monotonic()
    result: dict[str, Any] = {
        "project": name,
        "cpu": project_cpu(name),
        "status": None,
        "problems": [],
        "elapsed": None,
        "runner": None,
        "checks": {},
        "callback_errors": [],
        "teardown": None,
    }

    def write() -> None:
        (folder / "result.json").write_text(_json(result), encoding="utf-8")

    def on_new_project(run: cr.Run, new: cr.NewProject) -> None:
        scheduler = Scheduler()
        project = Project(run, new, folder, scheduler, timeout=timeout, program=program)
        try:
            run_checks(project, checks, result["checks"], write)
        finally:
            result["teardown"] = project.close()
            result["callback_errors"] = scheduler.errors
            write()

    write()
    settings = cr.Settings("new", folder / "runner", cpu=result["cpu"])
    runner_result = runner(settings, on_new_project)
    result["runner"] = {
        "status": runner_result.get("status"),
        "reason": runner_result.get("reason"),
        "step": runner_result.get("step"),
        "elapsed": runner_result.get("elapsed"),
        "timings": runner_result.get("timings"),
        "scr_before_save": runner_result.get("scr_before_save"),
        "out": settings.out,
    }
    problems: list[str] = result["problems"]
    if runner_result.get("status") != "ok":
        problems.append(
            f"The runner ended {runner_result.get('status')} at step "
            f"{runner_result.get('step')}: {runner_result.get('reason')}"
        )
    failed = [name for name, entry in result["checks"].items() if entry["status"] != "pass"]
    if failed:
        problems.append(f"These checks failed: {', '.join(failed)}.")
    missing = [spec.name for spec in checks if spec.name not in result["checks"]]
    if missing:
        problems.append(f"These checks did not run: {', '.join(missing)}.")
    if result["callback_errors"]:
        problems.append(f"{len(result['callback_errors'])} scheduled callback(s) raised.")
    teardown = result["teardown"]
    if teardown is not None and not teardown["port_free"]:
        problems.append(f"Port {MODBUS_PORT} was still in use after ClickNick closed.")
    if teardown is not None and teardown["threads"]:
        problems.append(
            f"These threads still ran after ClickNick closed: {', '.join(teardown['threads'])}."
        )
    result["status"] = "fail" if problems else "pass"
    result["elapsed"] = round(time.monotonic() - began, 3)
    write()
    return result


def summary_lines(summary: dict[str, Any]) -> list[str]:
    """Return the summary as lines of text: each project, then each of its checks."""
    lines: list[str] = []
    for project in summary["projects"]:
        lines.append(f"{project['project']}: {project['status']} ({project['elapsed']:g} s)")
        for name, check in project["checks"].items():
            lines.append(f"  {name}: {check['status']} ({check['seconds']:g} s) {check['text']}")
        lines.append(f"  scr_before_save: {project['scr_before_save']}")
        lines.extend(f"  problem: {problem}" for problem in project["problems"])
    if summary["stopped"]:
        lines.append(summary["stopped"])
    lines.append(f"Status: {summary['status']}")
    return lines


def stop_reason(model: str, result: dict[str, Any]) -> str | None:
    """Return why the smoke must stop after the project for *model*, or None to go on."""
    runner = result["runner"]
    if (runner["reason"] or "").startswith("interrupted"):
        return f"The smoke stopped during {model}, because you pressed Ctrl+C."
    if runner["status"] == "refused":
        return f"The smoke stopped, because the runner refused {model}: {runner['reason']}"
    teardown = result["teardown"]
    if teardown is not None and teardown["threads"]:
        return (
            f"The smoke stopped after {model}, because these threads still ran after ClickNick "
            f"closed: {', '.join(teardown['threads'])}."
        )
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check ClickNick against new projects that the CLICK runner makes."
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="a new or empty folder for the results (default: tmp/smoke/<date and time>)",
    )
    parser.add_argument(
        "--cpu",
        action="append",
        choices=(*cr.CPU_MODELS, cr.NO_CPU, PROGRAM_PROJECT),
        metavar=f"MODEL|{cr.NO_CPU}|{PROGRAM_PROJECT}",
        help=f"make a project for this CPU only, {cr.NO_CPU} for a project with no CPU, or "
        f"{PROGRAM_PROJECT} for a {PROGRAM_CPU} project with the rungs of {PROGRAM_CSV.name}. "
        f"Repeat it for more projects (default: {', '.join(PROJECTS)})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="seconds to wait for the build, the simulation's start and Check Program "
        f"(default {DEFAULT_TIMEOUT:g})",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    checks: Sequence[CheckSpec] = CHECKS,
    runner: RunNew = run_new,
) -> int:
    args = _parser().parse_args(argv)
    out: Path = args.out or Path("tmp") / "smoke" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print(f"{out} is a file or a folder that is not empty. Give --out a new or empty folder.")
        return EXIT_REFUSED
    if not port_free(MODBUS_PORT):
        print(port_busy_text(MODBUS_PORT))
        return EXIT_REFUSED
    out.mkdir(parents=True, exist_ok=True)
    # ClickNick reads LOCALAPPDATA each time it saves settings. live/session.py reads it once, on
    # import. So the smoke sets it before anything imports ClickNick.
    os.environ["LOCALAPPDATA"] = str(out / "localappdata")
    summary: dict[str, Any] = {
        "status": None,
        "stopped": None,
        "out": out,
        "localappdata": os.environ["LOCALAPPDATA"],
        "projects": [],
    }
    # stdout holds only the summary. ClickNick and ODBC drivers print to stdout too
    with cr._stdout_to_stderr():
        # A CPU given twice runs once. The second time, its folder would already exist
        for model in dict.fromkeys(args.cpu or PROJECTS):
            if not port_free(MODBUS_PORT):
                summary["stopped"] = (
                    f"The smoke stopped before {model}. {port_busy_text(MODBUS_PORT)}"
                )
                break
            try:
                result = smoke_project(
                    model, out / model, checks=checks, runner=runner, timeout=args.timeout
                )
            except KeyboardInterrupt:
                summary["stopped"] = (
                    f"The smoke stopped during {model}, because you pressed Ctrl+C."
                )
                break
            except Exception as exc:
                traceback.print_exc()
                summary["stopped"] = (
                    f"The smoke stopped during {model}, because it raised "
                    f"{type(exc).__name__}: {exc}"
                )
                break
            summary["projects"].append(
                {
                    "project": model,
                    "status": result["status"],
                    "elapsed": result["elapsed"],
                    "checks": {
                        name: {key: entry[key] for key in ("status", "text", "seconds")}
                        for name, entry in result["checks"].items()
                    },
                    "scr_before_save": result["runner"]["scr_before_save"],
                    "problems": result["problems"],
                }
            )
            summary["stopped"] = stop_reason(model, result)
            if summary["stopped"]:
                break
    if summary["stopped"]:
        summary["status"] = "stopped"
        code = EXIT_REFUSED
    elif all(project["status"] == "pass" for project in summary["projects"]):
        summary["status"] = "pass"
        code = EXIT_PASS
    else:
        summary["status"] = "fail"
        code = EXIT_FAIL
    (out / "summary.json").write_text(_json(summary), encoding="utf-8")
    # When stdout is a file, its encoding is cp1252, which has no "→". Python's stderr writes
    # such a character as an escape. The smoke prints the summary the same way
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")
    print("\n".join(summary_lines(summary)), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
