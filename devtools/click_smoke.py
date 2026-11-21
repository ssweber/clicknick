"""Check ClickNick against new projects that the CLICK runner makes, one CPU at a time.

    uv run python devtools/click_smoke.py [--out DIR] [--cpu MODEL|none ...] [--timeout S]

For each CPU, the smoke runs the runner's ``new`` mode (click_runner.py). CLICK makes a project
for that CPU through its new-project wizard and saves it. For ``none``, the runner cancels the
wizard's choice of CPU, and CLICK saves a project with no CPU. CLICK never connects to a PLC.
While CLICK still has the project open, the runner calls ``on_new_project``. There ClickNick
connects to that CLICK with no window, the way the app does after you pick the window:

- ``ClickConnection(pid, hwnd, filename)`` and a ``ConnectionSession``;
- an ``AddressStore`` that reads the project's SC_.mdb (``MdbDataSource``);
- the workspace build (``ConnectionSession.start_analysis``);
- a ``SimulationSession`` from ``ConnectionSession.ensure_simulation``.

Then the smoke runs the checks in ``CHECKS`` in order:

- ``load``: the store reads SC_.mdb;
- ``build``: the workspace builds, with no warning, into CLICK's temp folder;
- ``layout``: ``SimulationSession.layout`` has no error, and its cards are what
  ``read_panel_layout`` reads in the project's Project.ini. Its CPU card must be the project's
  CPU. For ``none``, the layout must have no CPU card. The Simulator then shows its No CPU card.
  For a project in ``click_smoke_layouts.json``, the cards must also be the cards recorded
  there;
- ``simulation``: the simulation reaches READY, and it scans in RUN;
- ``check_program``: Check Program runs both ways, as ``analysis.run_validation()`` and as
  ``clicknick-cli check`` through ``dispatch()``, and both report the same findings.

A check passes or fails, and it says why. A check that needs another check runs only when that
one passed. To add a check, add a ``CheckSpec`` to ``CHECKS``. Its function receives the
``Project`` and a dict for details, returns the text for a pass, and raises ``CheckFailed`` for a
fail. ``Project.run`` is the runner's ``Run``, so a check can also ask the runner to act in CLICK.

A check that a later change adds must follow two rules:

- While a check calls a runner method, no scheduled callback runs. After the call, call
  ``project.scheduler.wait(...)``, so that ScrWatcher sees CLICK's save.
- A check that changes the project, such as Sync or ``rung apply``, changes what the checks after
  it see. So the order in ``CHECKS`` is part of the contract.

ClickNick runs in the runner's process. A check can then call the runner's methods directly,
while ClickNick's build and simulation threads keep running. ``Scheduler`` stands in for the Tk
root. Whenever the smoke waits, ``Scheduler`` runs the callbacks that ClickNick scheduled.

Each project gets a folder ``DIR/<model>/``, or ``DIR/none/``:

- ``runner/``: the runner's ``--out`` folder, with its result.json and run.log;
- ``result.json``: the smoke's result for the project. The smoke writes it again after each
  check.

The project's result.json holds these fields:

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
import heapq
import itertools
import json
import os
import socket
import sys
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import click_runner as cr  # noqa: E402

if TYPE_CHECKING:
    from clicknick.connection_session import ConnectionSession
    from clicknick.data.address_store import AddressStore
    from clicknick.simulation_session import SimulationSession

# The projects that the smoke makes, in order. Each is a CPU in cr.CPU_MODELS, or cr.NO_CPU for
# a project with no CPU
PROJECTS = ("C0-00DD1-D", "C0-02DD1-D", "C0-11DD1E-D", "C0-12DD1E-2-D", "C2-03CPU", cr.NO_CPU)
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
    ) -> None:
        self.run = run
        self.new = new
        self.folder = folder
        self.scheduler = scheduler
        self.timeout = timeout
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


def check_load(project: Project, details: dict[str, Any]) -> str:
    """Read the project's SC_.mdb into an ``AddressStore``, as the app does after you connect."""
    from clicknick.data.address_store import AddressStore
    from clicknick.data.data_source import MdbDataSource

    session = project.session
    store = AddressStore(MdbDataSource(click_pid=session.click.pid, click_hwnd=session.click.hwnd))
    store.load_initial_data()
    project.store = store
    session.has_database = True
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
    return f"Built the workspace in {project_dir}."


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
    with no used I/O. In a project with no CPU, the layout must have no CPU card. The Simulator
    then shows its No CPU card in its place.
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
    expected = _cards(read_panel_layout(project.session.project_ini))
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
    return f"READY. In RUN it scanned from scan {first} to scan {last} in {seconds:g} s."


def check_program(project: Project, details: dict[str, Any]) -> str:
    """Run Check Program as the app runs it, and ``clicknick-cli check`` as dispatch runs it.

    The CLI's text holds notes and a status line around the report, so the check passes when
    the CLI's text contains the app's report.

    A new project has no rungs. So this check shows only that both ways run and print the same
    report. It does not show that both ways report a finding the same way.
    """
    from clicknick.live.dispatch import DispatchContext, dispatch
    from clicknick.services.program_check import format_validation_report

    session = project.session
    analysis = session.analysis
    assert analysis is not None
    timeout = project.timeout
    report = project.scheduler.background("Check Program", analysis.run_validation, timeout)
    if report is None:
        raise CheckFailed("analysis.run_validation() returned None, so the analysis has no result.")
    app_text = format_validation_report(report)
    details["app"] = app_text
    context = DispatchContext(store=project.store, analysis=analysis, get_session=lambda: session)
    cli_text = project.scheduler.background(
        "clicknick-cli check", lambda: dispatch(context, "check"), timeout
    )
    details["cli"] = cli_text
    if app_text not in cli_text:
        raise CheckFailed("The CLI's check does not report what Check Program reports.")
    return f"Both report: {app_text.splitlines()[0]}"


CHECKS: tuple[CheckSpec, ...] = (
    CheckSpec("load", check_load),
    CheckSpec("build", check_build, needs=("load",)),
    CheckSpec("layout", check_layout),
    CheckSpec("simulation", check_simulation, needs=("build",)),
    CheckSpec("check_program", check_program, needs=("build",)),
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
    """
    for spec in checks:
        began = time.monotonic()
        details: dict[str, Any] = {}
        failed = [name for name in spec.needs if results.get(name, {}).get("status") != "pass"]
        if failed:
            status, text = "fail", f"Not run, because {', '.join(failed)} did not pass."
        else:
            project.run.log(f"smoke check {spec.name}")
            try:
                status, text = "pass", spec.run(project, details)
            except CheckFailed as exc:
                status, text = "fail", str(exc)
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


def smoke_project(
    model: str,
    folder: Path,
    *,
    checks: Sequence[CheckSpec] = CHECKS,
    runner: RunNew = run_new,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Make the project for *model* with the runner, run *checks* on it, and return the result.

    The function writes the result to ``folder/result.json`` and returns it.
    """
    folder.mkdir(parents=True)
    began = time.monotonic()
    result: dict[str, Any] = {
        "project": model,
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
        project = Project(run, new, folder, scheduler, timeout=timeout)
        try:
            run_checks(project, checks, result["checks"], write)
        finally:
            result["teardown"] = project.close()
            result["callback_errors"] = scheduler.errors
            write()

    write()
    settings = cr.Settings("new", folder / "runner", cpu=model)
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
        choices=(*cr.CPU_MODELS, cr.NO_CPU),
        metavar="MODEL|none",
        help=f"make a project for this CPU only, or {cr.NO_CPU} for a project with no CPU. "
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
    print("\n".join(summary_lines(summary)), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
