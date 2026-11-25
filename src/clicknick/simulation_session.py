"""Simulation session: one simulated PLC for the connected CLICK project.

A ConnectionSession owns the session. The session has no tkinter code. It owns the pyrung
DAP subprocess, which starts with a Modbus server, real-time pacing and STOP mode. It also
owns the Modbus client that polls the values the Simulator window shows, the switch, analog
and force settings and the bench links that the user chose, and the saving of those choices.
The Simulator window (with its console) and the Dataview editor observe the session and call
its methods. Neither of them owns the simulation.

Two channels reach the simulated PLC. The session reads values over Modbus, exactly as from
real hardware. Inputs (switches, analog values), mode, speed, stepping, forces and bench
links go over DAP. pyclickplc's Modbus client refuses an X write. The Simulator's Modbus
server accepts one, as a CLICK does, so a client outside ClickNick can change an input.

Every public method runs on the UI thread. Work that blocks runs on worker threads, and the
results come back through ``scheduler.after(0, ...)``.
"""

from __future__ import annotations

import enum
import operator
import os
import queue
import re
import threading
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pyclickplc.addresses import (
    format_address_display,
    get_addr_key,
    normalize_address,
    parse_addr_key,
    parse_address,
)

from .services.link_annotation import linked_feedbacks
from .services.physical_response import (
    Response,
    response_from_dap,
    response_kind,
    response_label,
    response_tokens,
)
from .services.program_carry import CarryPlan, LinkTarget, address_of, plan_carry
from .services.sim_hardware import (
    MODULE_STATUS_PREFIX,
    PanelLayout,
    build_panel_layout,
    io_addresses,
    layout_error_text,
)
from .services.sim_state import (
    BenchLink,
    RestoreResult,
    SimulatorState,
    StateFile,
    adopt_snapshot,
    load_state,
    restore_state,
    save_state,
    settle_state_file,
)

if TYPE_CHECKING:
    from .services.analysis_service import AnalysisService
    from .services.dap_service import DapService
    from .services.project_workspace import PlcSourceWatch

PlcValue = bool | int | float | str

MODBUS_HOST = "127.0.0.1"
#: Simulation speed choices: multiples of wall time; 0 = as fast as possible.
SPEEDS: tuple[float, ...] = (0.5, 1.0, 2.0, 10.0, 0.0)

ANALYSIS_POLL_MS = 500
#: Give a large program room to convert, but never poll forever.
ANALYSIS_TIMEOUT_MS = 120_000
WATCH_MS = 2000
#: How long an analog value must hold still before its console echo shows.
ECHO_SETTLE_MS = 500
MODBUS_INFO_MS = 1000
SAVE_DELAY_MS = 500
MODBUS_POLL_S = 0.1
#: A refusal to run lists this many rungs ClickNick cannot read and counts the rest.
UNREADABLE_LISTED = 10
#: The PLC data notice lists this many ranges of Text addresses and counts the rest.
PLC_DATA_LISTED = 10


SwitchPosition = Literal["stop", "step", "run"]
#: Labels for the CPU mode switch. The middle position's name is not final;
#: rename it here only.
STEP_LABEL = "STEP"
SWITCH_LABELS: dict[SwitchPosition, str] = {"stop": "STOP", "step": STEP_LABEL, "run": "RUN"}

#: Labels for a frame's ``source.origin``. When the origin is listed here, the UI says who
#: moved the mode switch. ``dap`` is ClickNick itself, and ``worker`` is the scan loop
#: reporting its own pause, so neither is listed. Modbus writes never change the mode.
_ORIGIN_LABELS = {"live": "Console"}


def format_speed(speed: float) -> str:
    """``0`` -> ``"Max"``; ``0.5`` -> ``"0.5x"``; ``2.0`` -> ``"2x"``."""
    if speed <= 0:
        return "Max"
    return f"{speed:.2f}".rstrip("0").rstrip(".") + "x"


class Scheduler(Protocol):
    """What the session needs from the UI toolkit (a Tk root satisfies it)."""

    def after(self, ms: int, func: Callable[[], object]) -> Any: ...

    def after_cancel(self, id: Any) -> None: ...


class SimStatus(enum.Enum):
    IDLE = "idle"  # nobody is using the simulator
    WAITING = "waiting"  # waiting for program analysis
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


EventKind = Literal["status", "frame", "values", "modbus", "desired", "layout", "message", "echo"]
MessageLevel = Literal["output", "progress", "error"]


@dataclass(frozen=True)
class SimEvent:
    """A change that listeners may want to show.

    ``kind`` is one of these:

    - ``status``: the session's lifecycle changed.
    - ``frame``: the mode, scan, forces or pending writes changed.
    - ``values``: new Modbus values arrived.
    - ``modbus``: the server info changed.
    - ``desired``: the switch, analog or force settings changed.
    - ``layout``: the hardware layout changed.
    - ``message``: a line for the transcript, in ``text`` and ``level``.
    - ``echo``: the console command (in ``text``) that does what the user just did on the panel.
    """

    kind: EventKind
    text: str = ""
    level: MessageLevel = "output"


ChangeCause = Literal["save", "rebuilt", "source", "unconverted"]
#: How a changed program reaches the simulation, the same as when you write to a CLICK.
#: In RUN it is ``run_time_edit`` or ``stop_and_write``. Otherwise it is ``write``. After a
#: write fails, ``restart`` is offered as well. It starts a new process.
ProgramAction = Literal["run_time_edit", "stop_and_write", "write", "restart"]


@dataclass(frozen=True)
class ProgramChange:
    """A program that the simulation does not run: CLICK saved one, or the workspace source changed.

    Nothing reaches the simulation until the user writes the program (see *actions*). If CLICK
    saved a program that could not be converted, there is nothing to write.
    """

    cause: ChangeCause
    text: str
    actions: tuple[ProgramAction, ...] = ()


LinkSource = Literal["project", "bench"]


@dataclass(frozen=True)
class WiredLink:
    """One feedback link, either from the program (``project``) or a bench change.

    Addresses are CLICK display addresses. A bench change that cuts a link has no enable.
    ``active`` is True while the simulation runs the link. A project link is not active while
    a bench change replaces or cuts it.
    """

    feedback: str
    enable: str | None
    source: LinkSource
    trigger: int | str | None = None
    response: Response = ()
    active: bool = False
    pending: bool = False
    enabled: bool = True
    #: True for a bench link that the simulation does not have yet, because no rung in the
    #: simulation names its feedback or its enable (:func:`link_waits`).
    waiting: bool = False

    @property
    def cut(self) -> bool:
        return self.enable is None

    @property
    def response_label(self) -> str:
        """Return the response as label text, such as ``on_delay=2s, off_delay=500ms``."""
        return response_label(self.response)

    @property
    def kind(self) -> str:
        """Return the response's kind (``delay``, ``ramp``...), or ``""`` if it has none."""
        kind = response_kind(self.response)
        return "" if kind is None else kind.name


class _SerialWorker:
    """Runs submitted jobs one at a time, in order, on one daemon thread."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._queue: queue.SimpleQueue[Callable[[], None] | None] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            job()

    def submit(self, job: Callable[[], None]) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name=self._name)
            self._thread.start()
        self._queue.put(job)

    def close(self) -> None:
        if self._thread is not None:
            self._queue.put(None)
            self._thread = None


def _start_thread(target: Callable[[], None], name: str) -> None:
    threading.Thread(target=target, daemon=True, name=name).start()


def _default_dap_factory(**callbacks: Any) -> DapService:
    from .services.dap_service import DapService

    return DapService(**callbacks)


def _default_modbus_factory(**kwargs: Any) -> Any:
    from pyclickplc import ModbusService, ReconnectConfig

    return ModbusService(reconnect=ReconnectConfig(delay_s=0.5, max_delay_s=2.0), **kwargs)


def _default_layout_reader(project_ini: Path, used_io: Iterable[str]) -> PanelLayout:
    from .services.sim_hardware import read_panel_layout

    return read_panel_layout(project_ini, used_io)


def _default_snapshot_reader(path: Path) -> Mapping[str, PlcValue]:
    from pyclickplc import read_plc_data

    return read_plc_data(path)


def _default_send_command(session_name: str, command: str) -> tuple[bool, str]:
    from pyrung.live import send_command

    return send_command(session_name, command)


def _command_value(value: PlcValue) -> str:
    """Return *value* as you type it in the console: ``true``, ``false`` or a number."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _unavailable(exc: BaseException) -> bool:
    """Return True if the simulation never answered because it stopped, died or hung.

    Return False for any other error, such as a refusal.
    """
    from .services.dap_service import DapUnavailableError

    return isinstance(exc, DapUnavailableError)


def link_waits(feedback: str, link: BenchLink, named: frozenset[str] | None) -> bool:
    """Return True if *named* lacks the feedback or the enable of *link*.

    *named* holds the addresses that a rung in the simulation names. pyrung links only those
    addresses, so ClickNick keeps such a link and sends it once a rung names both ends. If
    *named* is None, nobody knows what the rungs name yet, and no link waits.
    """
    if named is None:
        return False
    return feedback not in named or (link.enable is not None and link.enable not in named)


def _named_addresses(
    tags: Iterable[str], maps: tuple[Mapping[str, int], Mapping[int, str]]
) -> frozenset[str]:
    """Return the CLICK addresses of the pyrung tags in *tags*, mapped through *maps*."""
    return frozenset(a for tag in tags if (a := address_of(tag, maps)) is not None)


def _waiting_text(waiting: Mapping[str, BenchLink]) -> str:
    """Return the notice for the bench links in *waiting*, which a write left waiting."""
    parts = []
    for feedback in sorted(waiting):
        link = waiting[feedback]
        if link.cut:
            parts.append(
                f"The cut on {feedback} waits until a rung in the simulation names {feedback}."
            )
        else:
            parts.append(
                f"The bench link on {feedback} waits until a rung in the simulation names both "
                f"{feedback} and {link.enable}."
            )
    return " ".join(parts)


def _unknown_tag(reason: str) -> bool:
    """Return True if pyrung refused a request because it does not know a tag in the request.

    pyrung words this in more than one way, such as ``unknown tag: X001`` and
    ``Unknown tag 'X001' (address X001 is not mapped to a tag)``. From pyrung PR #119
    (after 0.18.0), pyrung refuses a link to an address that no rung uses with ``cannot link
    X001: no rung uses X001, so the program has no tag for it``.
    """
    reason = reason.lower()
    return "unknown tag" in reason or "no rung uses" in reason


def _unresolved(reason: str, addresses: Iterable[str]) -> str | None:
    """Return the address in *addresses* that *reason* names as an unknown tag, or None."""
    if not _unknown_tag(reason):
        return None
    for address in addresses:
        if re.search(rf"\b{re.escape(address)}\b", reason, re.IGNORECASE):
            return address
    return None


def _send_patches(
    send: Callable[[dict[str, PlcValue]], object], patches: Mapping[str, PlcValue]
) -> None:
    """Send *patches* with *send*, and leave out each address that pyrung cannot resolve.

    pyrung refuses the whole request when it cannot resolve one address in it. The refusal
    names that address as an unknown tag. This function then sends the request again without
    that address. Each retry leaves out one more address, so the loop ends. Any other refusal
    raises.

    The caller keeps the values that this function leaves out, and sends them again with the
    next patch. A left-out value applies with the first patch after pyrung can resolve its
    address.
    """
    left = dict(patches)
    while True:
        try:
            send(left)
            return
        except Exception as exc:
            address = None if _unavailable(exc) else _unresolved(str(exc), left)
            if address is None:
                raise
            del left[address]


def _patch_inputs(dap: Any, patches: Mapping[str, PlcValue]) -> None:
    """Patch *patches* into the simulation, and leave out each address that pyrung cannot resolve."""
    _send_patches(dap.patch, patches)


def _enter_run(dap: Any, patches: Mapping[str, PlcValue]) -> None:
    """Switch the simulation to RUN with *patches*.

    Leave out each address that pyrung cannot resolve, so that the switch to RUN goes through.
    """
    _send_patches(lambda left: dap.set_mode("run", patches=left), patches)


def _send_link(dap: Any, feedback: str, link: BenchLink) -> None:
    """Send one bench link to the simulation, either a cut or a link with its response."""
    if link.cut:
        dap.unlink(feedback)
        return
    assert link.enable is not None
    dap.link(feedback, link.enable, trigger=link.trigger, response=link.response)


def _restore_bench(dap: Any, feedbacks: Iterable[str]) -> None:
    """Restore the program's own wiring on each of *feedbacks* that has a bench row.

    A bench row is a bench link or cut that the simulation lists. *feedbacks* are tag names, as
    the simulation lists them. A feedback with no bench row is left alone, because pyrung
    refuses to restore it.
    """
    wanted = set(feedbacks)
    listed = {
        str(row.get("feedback", ""))
        for row in dap.list_links().get("links") or ()
        if isinstance(row, Mapping) and row.get("source") == "bench"
    }
    for feedback in sorted(wanted & listed):
        dap.restore_link(feedback)


def _watch_source(project_dir: Path) -> PlcSourceWatch | None:
    """Return a snapshot of ``src/plc`` in *project_dir*, to tell later if it changed."""
    from .services.project_workspace import PlcSourceWatch

    try:
        return PlcSourceWatch(project_dir)
    except OSError:
        return None


def _link_enable(row: Mapping[str, Any]) -> str | None:
    """Return the enable tag of a bench row in pyrung's link listing, or None for a cut."""
    enable = row.get("enable")
    return None if row.get("cut") or enable is None else str(enable)


def _bench_link(row: Mapping[str, Any], enable: str | None) -> BenchLink:
    """Return a bench row of pyrung's link listing as the user's link, driven by *enable*."""
    enabled = row.get("enabled", True) is not False
    return BenchLink(enable, row.get("trigger"), response_from_dap(row), enabled)


@dataclass(frozen=True)
class _Listing:
    """The forces and links that pyrung had around a write, keyed by CLICK address."""

    forces: Mapping[str, PlcValue]
    links: Mapping[str, BenchLink]
    bench_wiring: bool
    problems: tuple[str, ...] = ()
    #: Text saying what the write released, renamed or could not keep (``CarryPlan.written``).
    carried: str = ""
    #: The bench links that the simulation does not have, because they wait (:func:`link_waits`).
    waiting: Mapping[str, BenchLink] = field(default_factory=dict)


@dataclass(frozen=True)
class _WriteTarget:
    """The program that a write loads, with the build it came from and the names it uses."""

    generation: int
    names: tuple[Mapping[str, int], Mapping[int, str]]
    saves: int | None


def _address_ranges(addresses: Iterable[str]) -> str:
    """Return *addresses* as text, with each run of consecutive addresses as one range.

    For example, TXT13 to TXT20 becomes ``TXT13-TXT20``. After :data:`PLC_DATA_LISTED` ranges,
    the text counts the rest.
    """
    runs: list[tuple[str, int, int]] = []
    for address in addresses:
        memory_type, number = parse_address(address)
        if runs and runs[-1][0] == memory_type and runs[-1][2] == number - 1:
            runs[-1] = (memory_type, runs[-1][1], number)
        else:
            runs.append((memory_type, number, number))
    parts = [
        format_address_display(memory_type, first)
        if first == last
        else f"{format_address_display(memory_type, first)}-"
        f"{format_address_display(memory_type, last)}"
        for memory_type, first, last in runs
    ]
    text = ", ".join(parts[:PLC_DATA_LISTED])
    if len(parts) > PLC_DATA_LISTED:
        text += f" and {len(parts) - PLC_DATA_LISTED} more"
    return text


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


class SimulationSession:
    """One simulated PLC, shared by the Simulator, its console and the Dataview."""

    def __init__(
        self,
        *,
        scheduler: Scheduler,
        get_analysis: Callable[[], AnalysisService | None],
        get_project_ini: Callable[[], Path | None],
        session_name: str,
        on_retry_analysis: Callable[[], None] | None = None,
        dap_factory: Callable[..., Any] = _default_dap_factory,
        modbus_factory: Callable[..., Any] = _default_modbus_factory,
        layout_reader: Callable[[Path, Iterable[str]], PanelLayout] = _default_layout_reader,
        snapshot_reader: Callable[[Path], Mapping[str, PlcValue]] = _default_snapshot_reader,
        run_background: Callable[[Callable[[], None], str], None] = _start_thread,
        run_serial: Callable[[Callable[[], None]], None] | None = None,
        send_command: Callable[[str, str], tuple[bool, str]] = _default_send_command,
        app_data_root: Path | None = None,
        get_save_count: Callable[[], int] | None = None,
    ) -> None:
        self._send_command = send_command
        # How many times CLICK saved, to tell a save from a rebuild (Reload from CLICK, a Sync).
        self._get_save_count = get_save_count
        self._scheduler = scheduler
        self._get_analysis = get_analysis
        self._get_project_ini = get_project_ini
        self._session_name = session_name
        self._on_retry_analysis = on_retry_analysis
        self._dap_factory = dap_factory
        self._modbus_factory = modbus_factory
        self._layout_reader = layout_reader
        self._snapshot_reader = snapshot_reader
        self._run_background = run_background
        self._worker = _SerialWorker("sim-actions")
        self._run_serial = run_serial or self._worker.submit
        self._app_data_root = app_data_root

        self._listeners: list[Callable[[SimEvent], None]] = []
        # On from turn_on() until turn_off(); windows opening or closing never change it.
        self._enabled = False
        self._closed = False

        # Lifecycle
        self._status = SimStatus.IDLE
        self._error: str | None = None
        self._error_detail: str | None = None
        self._dap: Any | None = None
        self._token = 0
        # The program that the simulation runs. These fields hold the analysis generation it
        # came from, the CLICK save count at that time, its tag names, its folder and what its
        # source held. A launch and a write set them. pyrung never loads files on its own,
        # because autoreload is off.
        self._program_generation = -1
        self._program_saves: int | None = None
        self._program_names: tuple[Mapping[str, int], Mapping[int, str]] | None = None
        # The addresses that a rung in the simulation names, read from its frames, and the tag
        # list and names that they were read from. None until a frame lists the tags.
        self._named: frozenset[str] | None = None
        self._named_from: tuple[object, ...] | None = None
        # The feedbacks of the bench links that the simulation refused or dropped because it
        # does not know one of their tags. They wait like the links that link_waits names.
        self._held: set[str] = set()
        self._program_dir: Path | None = None
        self._program_source: PlcSourceWatch | None = None
        self._source_changed = False
        # The last finished build that was compared with the program the simulation runs.
        self._examined = -1
        # True while a write (a pyrung reload) waits for its answer. The next field says why the
        # last write failed.
        self._writing = False
        self._write_error: str | None = None
        self._shown_change: ProgramChange | None = None
        # True when a change to the PLC data file or the Modbus port needs a restart that cannot
        # run yet. The restart waits until the write in flight is answered and no build runs.
        # Any launch clears this flag.
        self._restart_due = False
        # The number of Console commands in flight (see run_console_command). No write starts
        # while one runs, because a command could change the forces or links between the
        # write's listing and its reload. The session keeps the count, not the panel, so the
        # count stays right if the user closes the panel that sent a command.
        self._console_commands = 0
        # The notice that a write or Restart was refused. It stays until one goes through.
        self._refusal: str | None = None
        # The token of a launch whose process died before _on_launched ran for it.
        self._died_token: int | None = None
        self._waited_ms = 0
        self._analysis_after_id: Any | None = None
        self._watch_after_id: Any | None = None
        self._frame_posted = False

        # PLC data snapshot the simulation starts from
        self._plc_data_path: Path | None = None
        self._analog_echo_ids: dict[str, Any] = {}
        # Simulated ms left on each linked input's running delay, by address.
        self._links_pending: dict[str, int] = {}
        self._plc_data_mtime: float | None = None
        # The notice that names the Text addresses pyrung skips in the PLC data file. It shows
        # once the next launch succeeds, because it says how that simulation started.
        self._plc_data_warning: str | None = None

        # Modbus
        self._modbus_info: dict[str, Any] = {}
        self._modbus_info_after_id: Any | None = None
        self._modbus: Any | None = None
        self._modbus_connected = False
        self._watched: dict[int, tuple[object, tuple[str, ...]]] = {}
        self._values: dict[str, PlcValue] = {}
        self._values_posted = False
        self._pending_values: Mapping[str, PlcValue] = {}

        # What the user chose, and where it is remembered
        self._state = SimulatorState()
        self._state_path: Path | None = None
        self._save_after_id: Any | None = None
        self._restore_pending = False
        self._restored_forces = 0
        self._notice: str | None = None
        self._written_notice: str | None = None  # the notice that the last write showed
        self._pressed: set[str] = set()
        self._speed = 1.0
        self._desired_position: SwitchPosition = "stop"
        # If pyrung never answered a write, the simulation may be left paused. The switch
        # position the user had stays the position that a Restart starts in, until the user
        # moves the switch or a write goes through.
        self._position_held = False
        self._forces_baseline: dict[str, PlcValue] | None = None
        self._analog_queued: set[str] = set()
        # The links (project and bench) as the simulation reports them. After a launch, the
        # bench links are applied again. Until that has happened, a listing only updates the
        # display and never overwrites what the user chose.
        self._link_rows: tuple[WiredLink, ...] | None = None
        self._links_revision_seen: int | None = None
        self._links_synced = False
        # Read the links again on the next frame, because the simulation did not answer the listing.
        self._links_refetch = False
        # The count of the user's changes to bench links. _on_links copies no listing into the
        # settings if the user changed a link after ClickNick asked for that listing.
        self._links_edits = 0
        self._restored_links = 0

        # Hardware
        self._layout: PanelLayout | None = None
        self._layout_error: str | None = None
        self._layout_key: tuple[float | None, tuple[int, Any] | None] | None = None

    # ------------------------------------------------------------------
    # Listeners and thread hand-off
    # ------------------------------------------------------------------

    def add_listener(self, listener: Callable[[SimEvent], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[SimEvent], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _emit(self, kind: EventKind, text: str = "", level: MessageLevel = "output") -> None:
        event = SimEvent(kind, text, level)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                traceback.print_exc()

    def _message(self, text: str, level: MessageLevel = "output") -> None:
        self._emit("message", text, level)

    def _echo(self, command: str) -> None:
        """Show the console command for what the user just did, when it reaches the PLC."""
        if self._dap is not None:
            self._emit("echo", command)

    def _cancel(self, after_id: Any | None) -> None:
        if after_id is not None:
            try:
                self._scheduler.after_cancel(after_id)
            except Exception:
                pass

    def _echo_settled(self, address: str) -> None:
        """Echo an analog value once it stops changing. A dragged slider sends many values."""
        self._cancel(self._analog_echo_ids.pop(address, None))

        def echo() -> None:
            self._analog_echo_ids.pop(address, None)
            value = self._state.analog.get(address)
            if value is not None:
                self._echo(f"patch {self.to_tag(address)} {_command_value(value)}")

        self._analog_echo_ids[address] = self._scheduler.after(ECHO_SETTLE_MS, echo)

    def _post(self, callback: Callable[[], None]) -> bool:
        """Run *callback* on the UI thread, from any thread. Return False if it never will."""
        if self._closed:
            return False
        try:
            self._scheduler.after(0, callback)
        except Exception:
            return False  # the UI is gone
        return True

    def _report_action_error(
        self, token: int, text: str, on_error: Callable[[str], None] | None
    ) -> None:
        if token != self._token:
            return  # That simulation is gone. The next one gets the user's settings anyway.
        self._message(text, "error")
        if on_error is not None:
            on_error(text)

    def _submit(
        self,
        job: Callable[[], None],
        what: str,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Run *job* on the ordered action worker and report a failure as a message.

        *on_error* undoes the action. It runs only if the simulation refused the action. It does
        not run if the simulation stopped, restarted or never answered.
        """
        token = self._token

        def run() -> None:
            try:
                job()
            except Exception as exc:
                text = f"{what} failed: {exc}"
                undo = None if _unavailable(exc) else on_error
                self._post(lambda: self._report_action_error(token, text, undo))

        self._run_serial(run)

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------

    @property
    def session_name(self) -> str:
        """Name of the pyrung live session, for console text commands."""
        return self._session_name

    @property
    def status(self) -> SimStatus:
        return self._status

    @property
    def is_ready(self) -> bool:
        return self._status is SimStatus.READY and self._dap is not None

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def write_error(self) -> str | None:
        """Return why the last program write failed, or None if it did not fail.

        :attr:`program_change` shows this text until a write succeeds or the simulation stops.
        """
        return self._write_error

    @property
    def error_detail(self) -> str | None:
        return self._error_detail

    @property
    def mode(self) -> str:
        """Return ``"run"`` or ``"stop"``, as the simulated PLC last reported it."""
        return self._dap.mode if self._dap is not None else "stop"

    @property
    def running(self) -> bool:
        """Return True while the PLC scans continuously (in RUN and not paused)."""
        return self._dap is not None and self._dap.running

    @property
    def scan_id(self) -> int | None:
        return self._dap.scan_id if self._dap is not None else None

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def actual_speed(self) -> float | None:
        """Return the measured speed while free-running, if the simulation reports it."""
        return self._dap.actual_speed if self._dap is not None else None

    @property
    def speed_text(self) -> str:
        """Return ``"1x"`` or ``"Max"``, or ``"1x (actual 0.6x)"`` if the simulation lags."""
        text = format_speed(self._speed)
        actual = self.actual_speed
        if self.running and self._speed > 0 and actual is not None and actual < self._speed * 0.9:
            text += f" (actual {format_speed(actual)})"
        return text

    @property
    def source_text(self) -> str:
        """Return who last moved the mode switch, e.g. ``"Moved to STEP by Console: step 10"``."""
        if self._dap is None:
            return ""
        source = self._dap.source
        origin = _ORIGIN_LABELS.get(source.get("origin", ""), "")
        if not origin:
            return ""
        command = source.get("command", "")
        position = SWITCH_LABELS[self.switch_position]
        return f"Moved to {position} by {origin}{f': {command}' if command else ''}"

    @property
    def known_tags(self) -> frozenset[str]:
        return self._dap.known_tags if self._dap is not None else frozenset()

    @property
    def status_text(self) -> str:
        status = self._status
        if status is SimStatus.READY:
            scan = self.scan_id
            scan_text = f" | Scan {scan}" if scan is not None else ""
            return f"{SWITCH_LABELS[self.switch_position]}{scan_text}"
        if status is SimStatus.WAITING:
            seconds = self._waited_ms // 1000
            return f"Preparing the workspace...{f' ({seconds}s)' if seconds else ''}"
        if status is SimStatus.STARTING:
            return "Starting..."
        if status is SimStatus.FAILED:
            return "Not available"
        return "Simulation off"

    @property
    def summary_text(self) -> str:
        """Return a word or two for the main window's Test legend, such as ``"on :502"``."""
        if not self._enabled:
            return "off"
        if self._status is SimStatus.FAILED:
            return "failed"
        if not self.is_ready:
            return "starting"
        if self.modbus_available:
            port = self._modbus_info.get("port") or self._state.modbus_port
            return f"on :{port}"
        return "on"

    @property
    def values(self) -> dict[str, PlcValue]:
        """Return the latest values read over Modbus, keyed by CLICK address."""
        return dict(self._values)

    @property
    def forces(self) -> dict[str, PlcValue]:
        """Return the active forces by CLICK address. They stay in step with the simulation."""
        return dict(self._state.forces)

    @property
    def pending(self) -> dict[str, PlcValue]:
        """Return the writes that wait for the next scan, by CLICK address."""
        if self._dap is None:
            return {}
        return {self.to_address(k): v for k, v in self._dap.pending_patches.items()}

    @property
    def tag_hints(self) -> dict[str, dict[str, Any]]:
        """Return pyrung's per-tag hints (min/max ranges, choices), keyed by CLICK address."""
        if self._dap is None:
            return {}
        return {self.to_address(k): v for k, v in self._dap.tag_hints.items()}

    @property
    def run_hint_seen(self) -> bool:
        return self._state.run_hint_seen

    @property
    def modbus_port(self) -> int:
        return self._state.modbus_port

    @property
    def modbus_info(self) -> dict[str, Any]:
        return dict(self._modbus_info)

    @property
    def modbus_available(self) -> bool:
        """Return True if the simulation's Modbus server is up and accepting clients."""
        info = self._modbus_info
        return self.is_ready and bool(info.get("running")) and not info.get("error")

    @property
    def modbus_text(self) -> str:
        if self._dap is None:
            return "Modbus: off"
        info = self._modbus_info
        if not info:
            return "Modbus: starting..."
        host = info.get("host") or MODBUS_HOST
        port = info.get("port") or self._state.modbus_port
        if info.get("error"):
            return f"Modbus {host}:{port} unavailable: {info['error']}"
        if not info.get("running"):
            return "Modbus: not running"
        own = 1 if self._modbus_connected else 0
        clients = max(0, int(info.get("clients") or 0) - own)
        return f"{host}:{port} \N{BLACK CIRCLE} {clients} client{'s' if clients != 1 else ''}"

    @property
    def layout(self) -> PanelLayout | None:
        return self._layout

    @property
    def layout_error(self) -> str | None:
        return self._layout_error

    @property
    def notice(self) -> str | None:
        """Return a message about restored settings. It stays until the user dismisses it."""
        return self._notice

    @property
    def restored_forces(self) -> int:
        """Return how many forces were restored, until released or dismissed."""
        return self._restored_forces if self._state.forces else 0

    @property
    def restored_links(self) -> int:
        """Return how many bench links were restored, until discarded or dismissed."""
        return self._restored_links if self._state.links else 0

    @property
    def bench_links(self) -> dict[str, BenchLink]:
        """Return the bench changes that the user chose, by feedback address."""
        return dict(self._state.links)

    @property
    def bench_wiring(self) -> bool:
        """Return False while every bench change is set aside."""
        return self._state.bench_wiring

    @property
    def links(self) -> tuple[WiredLink, ...]:
        """Return every link as the simulation reports it, or the bench changes while it is off.

        While the simulation runs, the bench links that wait (:meth:`link_waits`) follow the
        simulation's own links. A link that waits takes the place of a bench row that the
        simulation still lists for the same feedback, so each feedback has one bench row.
        ClickNick asks the simulation to drop that row (:meth:`_change_links`), and the next
        listing no longer has it.
        """
        rows = self._link_rows
        own = tuple(
            WiredLink(
                address,
                link.enable,
                "bench",
                link.trigger,
                link.response,
                enabled=link.enabled,
                waiting=waits,
            )  # fmt: skip
            for address, link in self._state.links.items()
            if (waits := self._waits(address, link)) or rows is None
        )
        if rows is None:
            return own
        waiting = {row.feedback for row in own}
        return (
            tuple(row for row in rows if row.source != "bench" or row.feedback not in waiting) + own
        )

    @property
    def named_addresses(self) -> frozenset[str] | None:
        """The CLICK addresses that a rung in the simulation names, or None while unknown.

        These are the tags that pyrung knows, as its frames list them. pyrung refuses a bench
        link on any other address. A slot that a rung reaches only through a range, such as
        X005 in ``pack_bits(X003..X010, DS1)``, is not in the set. The set is None while the
        simulation is off, from a launch until its first frame, and from a write until the
        frame after it.
        """
        return self._named

    def is_named(self, address: str) -> bool:
        """Return True if a rung in the simulation names *address*, or if nobody knows yet."""
        named = self._named
        return named is None or address in named

    def link_waits(self, feedback: str) -> bool:
        """Return True if the bench link on *feedback* waits for a rung to name its ends."""
        link = self._state.links.get(feedback)
        return link is not None and self._waits(feedback, link)

    def _waits(self, feedback: str, link: BenchLink) -> bool:
        """Return True if ClickNick holds *link* back, because the simulation would refuse it."""
        return feedback in self._held or link_waits(feedback, link, self._named)

    def _read_named(self) -> frozenset[str] | None:
        """Return the addresses of the tags that the simulation's latest frame listed."""
        dap = self._dap
        tags = None if dap is None else dap.program_tags
        if tags is None:
            self._named_from = None
            return None
        maps = self._tag_maps()
        # A frame can arrive every scan. Map the tags again only when the list or the names
        # changed. DapService replaces its list only when the tags change.
        source = (tags, *maps)
        if self._named_from is not None and all(map(operator.is_, self._named_from, source)):
            return self._named
        self._named_from = source
        return _named_addresses(tags, maps)

    def _refresh_named(self) -> None:
        """Read the named addresses from the simulation's latest frame."""
        self._named = self._read_named()

    def driving_link(self, address: str) -> WiredLink | None:
        """Return the link that drives *address* right now, or None. A cut drives nothing."""
        for link in self.links:
            if link.feedback == address and link.active and not link.cut:
                return link
        return None

    def project_link(self, address: str) -> WiredLink | None:
        """Return the program's own link on *address*, whether or not it is active."""
        for link in self.links:
            if link.feedback == address and link.source == "project":
                return link
        return None

    @property
    def plc_data_path(self) -> Path | None:
        return self._plc_data_path

    def _tag_maps(self) -> tuple[Mapping[str, int], Mapping[int, str]]:
        """Return the tag names of the program that the simulation runs.

        These are the names that its workspace was generated with (``project_tag_to_addr_key``).
        The session takes them when it launches or writes the program. The process runs that
        program until the next launch or write, so frames and commands use these names even
        after a CLICK save renamed tags. While nothing runs, return the names of the workspace
        that a launch would read.
        """
        if self._program_names is not None:
            return self._program_names
        analysis = self._get_analysis()
        if analysis is None:
            return {}, {}
        return analysis.project_tag_to_addr_key, analysis.project_addr_key_to_tag

    def to_tag(self, address: str) -> str:
        """Return the running program's tag name for a CLICK *address*, or the address if none."""
        normalized = normalize_address(address)
        if normalized is None:
            return address
        tag = self._tag_maps()[1].get(get_addr_key(*parse_address(normalized)))
        return tag or normalized

    def link_countdown(self, address: str) -> int | None:
        """Return the simulated ms before the link that drives *address* flips it.

        Return None unless the link's delay is counting.
        """
        return self._links_pending.get(address) if self._dap is not None else None

    def to_address(self, key: str) -> str:
        """Return the CLICK address for a pyrung tag or address. Unmapped names pass through."""
        address = normalize_address(key)
        if address is not None:
            return address
        addr_key = self._tag_maps()[0].get(key)
        if addr_key is None:
            return key
        return format_address_display(*parse_addr_key(addr_key))

    def _addressed(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Return *values* keyed by CLICK address instead of pyrung tag name.

        Skip any tag that has no CLICK address.
        """
        found: dict[str, Any] = {}
        for key, value in values.items():
            address = self.to_address(key)
            if normalize_address(address) == address:
                found[address] = value
        return found

    def _save_now(self) -> None:
        self._save_after_id = None
        path = self._state_path
        if path is None:
            return
        state = self._state
        if self._layout is not None and self._layout.has_cpu:
            state = replace(state, modules=self._layout.modules)
        try:
            save_state(path, state)
        except OSError as exc:
            self._message(f"Could not save simulator settings to {path}: {exc}", "error")

    def _schedule_save(self) -> None:
        if self._state_path is None or self._closed:
            return
        self._cancel(self._save_after_id)
        self._save_after_id = self._scheduler.after(SAVE_DELAY_MS, self._save_now)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _set_notice(self, text: str, level: MessageLevel = "progress") -> None:
        self._notice = text
        self._message(text, level)
        self._emit("desired")

    def _plc_data_changed(self) -> bool:
        """Return True if the PLC data file changed since the session last recorded its time.

        Record the new modification time.
        """
        mtime = _mtime(self._plc_data_path)
        if mtime is None or (self._plc_data_mtime is not None and mtime <= self._plc_data_mtime):
            return False
        self._plc_data_mtime = mtime
        return True

    def _adopt_snapshot(self, path: Path) -> None:
        """Set the switches and analog inputs from the PLC data file at *path*.

        pyclickplc raises ``PlcDataReadError`` when it cannot tell what some Text addresses
        hold. The session then sets the switches and analog inputs from the other addresses.
        Its notice names the skipped ones once the next launch succeeds (``_on_launched``).
        pyrung skips the same addresses when it loads the file at launch. pyrung names them in
        a console output event, and ClickNick does not show that event. So the user reads this
        notice and nothing else about them.
        """
        from pyclickplc import PlcDataReadError

        self._plc_data_warning = None
        skipped: tuple[str, ...] = ()
        try:
            snapshot = self._snapshot_reader(path)
        except PlcDataReadError as exc:
            snapshot, skipped = exc.values, exc.addresses
        except (OSError, ValueError) as exc:
            self._message(f"Could not read PLC data {path}: {exc}", "error")
            return
        layout = self._layout
        if layout is not None and layout.cards:
            inputs: Iterable[str] = layout.addresses("input")
            analog_inputs: Iterable[str] = layout.addresses("analog_in")
        else:
            inputs = [a for a in snapshot if a.startswith("X")]
            analog_inputs = ()
        self._pressed.clear()
        self._state = adopt_snapshot(
            self._state, snapshot, inputs=inputs, analog_inputs=analog_inputs
        )
        self._schedule_save()
        loaded = (
            f"Loaded PLC data from {path.name}. The switches and analog inputs now have its values."
        )
        if not skipped:
            self._set_notice(loaded)
            return
        self._plc_data_warning = (
            f"{loaded}\nClickNick cannot tell what {_address_ranges(skipped)} hold in "
            f"{path.name}. The simulation started with them at their power-on values. CLICK "
            "writes a Text comma without quotes. A comma next to an empty Text address can then "
            "belong to more than one address. To load those addresses, replace the comma in "
            "their Text values in CLICK and save the PLC data file again."
        )

    def _follow_program(self) -> bool:
        """Restart a failed simulation if CLICK saved a program since. Return True if it did.

        A running simulation never changes program by itself. It offers
        :attr:`program_change` until the user writes the new program.
        """
        from .services.analysis_service import AnalysisStatus

        if self._status is not SimStatus.FAILED or self._dap is not None:
            return False
        analysis = self._get_analysis()
        if (
            analysis is None
            or analysis.status is AnalysisStatus.BUILDING
            or analysis.generation == self._program_generation
        ):
            return False
        self.restart()
        return True

    @property
    def _write_position(self) -> SwitchPosition:
        """Return the position that a write goes back to.

        While the position is held, that is the user's position. Otherwise it is the switch.
        """
        return self._desired_position if self._position_held else self.switch_position

    def _write_actions(self) -> tuple[ProgramAction, ...]:
        if self._writing or self._console_commands:
            return ()  # Allow one write at a time, and none while a Console command runs.
        actions: tuple[ProgramAction, ...] = (
            ("run_time_edit", "stop_and_write") if self._write_position == "run" else ("write",)
        )
        return (*actions, "restart") if self._write_error else actions

    def _save_count(self) -> int | None:
        return None if self._get_save_count is None else self._get_save_count()

    def _analog_channels(self) -> frozenset[str]:
        """Return the DF registers of the configured analog channels, which are hardware."""
        layout = self._layout
        if layout is None:
            return frozenset()
        kinds = ("analog_in", "analog_out")
        return frozenset(a for kind in kinds for a in layout.addresses(kind))

    def _carry_plan(self, analysis: AnalysisService) -> CarryPlan:
        """Return what writing the program of *analysis* would do to the forces and links.

        The plan covers the forces and links that the last frame showed.
        """
        old = self._tag_maps()
        dap = self._dap
        forces = dict(dap.forces) if dap is not None else {}
        links = {
            self.to_tag(row.feedback): None if row.enable is None else self.to_tag(row.enable)
            for row in self._link_rows or ()
            if row.source == "bench"
        }
        new = (analysis.project_tag_to_addr_key, analysis.project_addr_key_to_tag)
        return plan_carry(old, new, forces, links, self._analog_channels())

    def _to_compare(self, analysis: AnalysisService) -> bool:
        """Return True if build *analysis* is not yet compared with the running program."""
        from .services.analysis_service import AnalysisStatus

        return (
            self.is_ready
            and not self._writing
            and not self._write_error
            and self._program_source is not None
            and self._program_names is not None
            and analysis.status is AnalysisStatus.READY
            and analysis.generation not in (self._examined, self._program_generation)
        )

    @property
    def program_change(self) -> ProgramChange | None:
        """Return the program that CLICK or the workspace holds, if the simulation runs another."""
        from .services.analysis_service import AnalysisStatus

        analysis = self._get_analysis()
        if not self.is_ready or analysis is None:
            return None
        new_build = analysis.generation != self._program_generation
        if not new_build and not self._source_changed:
            return None
        tail = (
            f" Could not write the program: {self._write_error}. Restart starts a new "
            "simulation from the workspace as it is now (CLICK's last save and any edits), "
            "from power-on values or the PLC data file."
            if self._write_error
            else ""
        )
        carry = self._carry_plan(analysis).notice
        if carry:
            tail = f" {carry}{tail}"  # Say what a write would do before the user writes.
        if self._console_commands and not self._writing:
            tail += (
                " A Console command is still running. You can write the program once it ends. "
                "Type stop to cancel it."
            )
        if new_build:
            if analysis.status is AnalysisStatus.FAILED:
                text = (
                    "Could not build the workspace from CLICK's last save. The simulation still "
                    "runs the previous program."
                )
                if analysis.error:
                    text = f"{text} The error was: {analysis.error}"
                return ProgramChange("unconverted", text)
            if analysis.status is not AnalysisStatus.READY:
                return None  # The build is not finished.
            if self._to_compare(analysis):
                return None  # _examine_build compares this build first.
            saves = self._save_count()
            if saves is not None and saves == self._program_saves:
                return ProgramChange(
                    "rebuilt",
                    "The workspace was rebuilt from CLICK's last save (Reload from CLICK or a "
                    "Sync). The simulation runs the previous program until you write it." + tail,
                    self._write_actions(),
                )
            return ProgramChange(
                "save",
                "CLICK saved a new program. The simulation runs the previous one until you "
                "write it." + tail,
                self._write_actions(),
            )
        return ProgramChange(
            "source",
            "The workspace's ladder source changed. The simulation runs the program it "
            "started with until you write it." + tail,
            self._write_actions(),
        )

    def _runs_workspace_program(self, analysis: AnalysisService) -> bool:
        """Return True if the workspace certainly holds the program that the simulation runs.

        The check compares the folder, the tag names, and ``src/plc`` and ``run.py`` as the
        session read them when it launched or wrote the program. A file that cannot be read
        proves nothing, so the answer is then False.
        """
        names = self._program_names
        watch = self._program_source
        return (
            names is not None
            and watch is not None
            and analysis.project_dir == self._program_dir
            and dict(names[0]) == dict(analysis.project_tag_to_addr_key)
            and dict(names[1]) == dict(analysis.project_addr_key_to_tag)
            and watch.same()
        )

    def _examine_build(self) -> bool:
        """Compare the latest finished build with the program that the simulation runs.

        If the build's workspace holds the same program, record that build as the running one.
        The session then does not offer it as a change. This happens after a Sync or a Reload
        from CLICK that leaves the program as it was. Each build is compared once. Return True
        if this call compared a build.
        """
        analysis = self._get_analysis()
        if analysis is None or not self._to_compare(analysis):
            return False
        self._examined = analysis.generation
        if self._runs_workspace_program(analysis):
            self._program_generation = analysis.generation
            self._program_saves = self._save_count()
            self._source_changed = False
        return True

    def _check_program(self) -> None:
        """Check for an edit to the workspace source, and tell listeners when the offer changes."""
        watch = self._program_source
        if watch is not None and self.is_ready and not self._writing:
            self._source_changed = watch.changed()
        self._examine_build()
        change = self.program_change
        if change != self._shown_change:
            self._shown_change = change
            self._emit("desired")

    def _restart_if_due(self) -> None:
        """Run the restart that :meth:`_restart_when_free` asked for, unless a write or build runs.

        If the restart is refused for any other reason, drop it. The simulation then runs on
        until the user restarts it.
        """
        from .services.analysis_service import AnalysisStatus

        if not self._restart_due or self._writing:
            return
        analysis = self._get_analysis()
        if (
            self._dap is not None
            and analysis is not None
            and analysis.status is AnalysisStatus.BUILDING
        ):
            return  # The watch tick asks again.
        self._restart_due = False
        self.restart()

    def _restart_when_free(self) -> None:
        """Restart now, or once the write in flight is answered and no build runs."""
        self._restart_due = True
        self._restart_if_due()

    def _watch_tick(self) -> None:
        self._watch_after_id = None
        if self._closed or not self._enabled:
            return
        self.refresh_layout()
        if self.is_ready and self._plc_data_path is not None:
            if self._plc_data_changed():
                if self._writing:
                    self._message(
                        "The PLC data file changed. The simulation restarts from it once the "
                        "program is written."
                    )
                else:
                    self._message("The PLC data file changed. Restarting the simulation from it...")
                self._adopt_snapshot(self._plc_data_path)
                self._restart_due = True
        if not self._follow_program():  # A launch also does any restart that is due.
            self._restart_if_due()
        self._check_program()
        self._watch_after_id = self._scheduler.after(WATCH_MS, self._watch_tick)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Return True from :meth:`turn_on` to :meth:`turn_off`, even while starting or failed."""
        return self._enabled

    def turn_on(self) -> None:
        """Start the simulation. It keeps running, with or without windows, until turned off.

        The app never calls this at launch. A subprocess and a listening Modbus port start only
        when the user asks for them.
        """
        if self._closed:
            return
        if self._enabled:
            self._emit("status")
            return
        self._enabled = True
        self._waited_ms = 0
        self.refresh_layout()
        if self._watch_after_id is None:
            self._watch_after_id = self._scheduler.after(WATCH_MS, self._watch_tick)
        self.start()

    def _set_status(self, status: SimStatus) -> None:
        self._status = status
        if status is not SimStatus.FAILED:
            self._error = None
            self._error_detail = None
        self._emit("status")

    def _disconnect_modbus(self) -> None:
        service = self._modbus
        self._modbus = None
        self._modbus_connected = False
        self._values = {}
        self._analog_queued.clear()
        if service is not None:

            def job() -> None:
                try:
                    service.disconnect()
                except Exception:
                    pass

            self._run_background(job, "sim-modbus-stop")

    def _stop_dap(self) -> None:
        """Terminate the simulation and its Modbus client. Leave the status as it is."""
        self._token += 1
        self._cancel(self._modbus_info_after_id)
        self._modbus_info_after_id = None
        self._disconnect_modbus()
        self._modbus_info = {}
        self._pressed.clear()
        self._link_rows = None
        self._links_pending = {}
        self._links_revision_seen = None
        self._links_synced = False
        self._links_refetch = False
        self._program_names = None
        self._named = None
        self._named_from = None
        self._held.clear()
        self._program_dir = None
        self._program_source = None
        self._source_changed = False
        self._examined = -1
        self._writing = False
        self._write_error = None
        self._position_held = False
        self._restart_due = False
        dap = self._dap
        self._dap = None
        if dap is not None:
            self._run_background(dap.terminate, "sim-dap-stop")

    def _flush_save(self) -> None:
        if self._save_after_id is not None:
            self._cancel(self._save_after_id)
            self._save_now()

    def _shutdown(self) -> None:
        self._stop_dap()
        for name in ("_analysis_after_id", "_watch_after_id"):
            self._cancel(getattr(self, name))
            setattr(self, name, None)
        self._waited_ms = 0
        self._flush_save()
        if self._status is not SimStatus.IDLE:
            self._set_status(SimStatus.IDLE)

    def turn_off(self) -> None:
        """Stop the simulation. Windows observing it stay open and offer to start it again."""
        if not self._enabled:
            return
        self._enabled = False
        self._message("Simulation off.", "progress")
        self._shutdown()

    def _fail(self, reason: str, detail: str | None = None) -> None:
        self._status = SimStatus.FAILED
        self._error = reason
        self._error_detail = detail
        self._message(f"Cannot start simulation: {reason}", "error")
        self._emit("status")

    @staticmethod
    def _analysis_failure(analysis: AnalysisService) -> tuple[str, str | None]:
        guidance = (
            "Open the generated workspace to inspect and edit the source. "
            if analysis.project_dir is not None
            else ""
        )
        error = f"{analysis.error}\n" if analysis.error else ""
        return (
            f"Could not build the workspace.\n{error}{guidance}Nickname editing is still available.",
            analysis.error_detail,
        )

    def _fail_analysis(self, analysis: AnalysisService) -> None:
        self._fail(*self._analysis_failure(analysis))

    @staticmethod
    def _unreadable_reason(csv_dir: Path) -> str | None:
        """Return why the program must not run, or None if it may.

        The program must not run if ``program_save`` replaced a rung that ClickNick cannot read
        with an empty stand-in rung. The simulation would run without that rung and look fine.
        A finding with no rung number is not a reason. It means that laddercodec could not read
        the program's CSV back. No stand-in rung was written, the CSV still holds every rung,
        and pyrung parses that CSV itself.
        """
        from .ladder.program import (
            describe_legacy_encoding,
            read_legacy_encodings,
            stand_in_fix,
        )

        found = [
            item
            for item in read_legacy_encodings(csv_dir)
            if item.unreadable and item.rung is not None
        ]
        if not found:
            return None
        lines = [f"  {describe_legacy_encoding(item)}" for item in found[:UNREADABLE_LISTED]]
        if len(found) > UNREADABLE_LISTED:
            lines.append(f"  ...and {len(found) - UNREADABLE_LISTED} more")
        one = len({(item.file, item.rung) for item in found}) == 1
        head = "this rung from CLICK as it is" if one else "these rungs from CLICK as they are"
        without = "it" if one else "them"
        fix = stand_in_fix(found, one=one)
        return (
            f"ClickNick cannot copy {head}, so the simulation would run without {without}.\n"
            + "\n".join(lines)
            + (f"\n{fix}" if fix else "")
        )

    def _workspace_problem(self, analysis: AnalysisService | None) -> tuple[str, str | None] | None:
        """Return why the workspace's program cannot run now, as (reason, detail), or None.

        A launch, a write and a Restart all run this check first. It needs a conversion that
        succeeded, a workspace that holds it, a ``run.py``, and no rung that ClickNick cannot
        read. If a build is under way, the caller waits for it or refuses.
        """
        from .services.analysis_service import AnalysisStatus

        if analysis is None:
            return (
                "ClickNick has not started building the workspace. Save the project in "
                "CLICK, then try again.",
                None,
            )
        if analysis.status is AnalysisStatus.FAILED:
            return self._analysis_failure(analysis)
        if not analysis.is_available or not analysis.project_is_current:
            return "ClickNick has not finished building the workspace.", None
        project_dir = analysis.project_dir
        if project_dir is None:
            return (
                "ClickNick has not generated the workspace. Save the project in CLICK, then "
                "try again.",
                None,
            )
        # A rebuild empties this folder before it regenerates it, so the folder can exist
        # before run.py is written.
        if not (project_dir / "run.py").is_file():
            return (
                f"the workspace at {project_dir} has no run.py. Save the project in CLICK, "
                "then try again.",
                None,
            )
        unreadable = self._unreadable_reason(project_dir / "csv")
        return None if unreadable is None else (unreadable, None)

    def _refuse(self, text: str) -> None:
        """Say why a write or Restart did not happen. The simulation runs on as it was."""
        self._refusal = text
        self._notice = text
        self._message(text, "error")
        self._emit("desired")

    def _clear_refusal(self) -> None:
        if self._refusal is not None and self._notice == self._refusal:
            self._notice = None
            self._emit("desired")
        self._refusal = None

    def _wait_for_analysis(self) -> None:
        """Poll for the conversion again, or fail once the wait reaches ANALYSIS_TIMEOUT_MS.

        Every path that waits for the conversion calls this method, so none waits forever.
        """
        if self._waited_ms >= ANALYSIS_TIMEOUT_MS:
            self._fail(f"the workspace was still not built after {ANALYSIS_TIMEOUT_MS // 1000} s.")
            return
        self._cancel(self._analysis_after_id)
        self._analysis_after_id = self._scheduler.after(ANALYSIS_POLL_MS, self._poll_analysis)
        self._set_status(SimStatus.WAITING)
        self._waited_ms += ANALYSIS_POLL_MS

    def _poll_analysis(self) -> None:
        from .services.analysis_service import AnalysisStatus

        self._analysis_after_id = None
        if self._closed or not self._enabled:
            return
        analysis = self._get_analysis()
        if analysis is not None and analysis.is_available:
            self.start()
            return
        if analysis is not None and analysis.status is AnalysisStatus.FAILED:
            self._fail_analysis(analysis)
            return
        self._wait_for_analysis()

    @property
    def is_waiting(self) -> bool:
        return self._analysis_after_id is not None

    def _on_launch_failed(self, token: int, exc: Exception) -> None:
        from .services.analysis_service import AnalysisStatus

        if token != self._token or self._closed:
            return
        analysis = self._get_analysis()
        if analysis is not None and (
            analysis.status is AnalysisStatus.BUILDING
            or analysis.generation != self._program_generation
        ):
            # The launch read files on disk while a rebuild rewrote them, which gives partial
            # imports or a missing run.py. The generation check catches a rebuild that already
            # finished. Wait and relaunch instead of reporting that as a real failure.
            self._wait_for_analysis()
            return
        self._status = SimStatus.FAILED
        self._error = f"the simulation could not start: {exc}"
        self._error_detail = None
        self._message(f"The simulation could not start: {exc}", "error")
        self._emit("status")

    def _update_state(self, **changes: Any) -> None:
        self._state = replace(self._state, **changes)
        self._emit("desired")
        self._schedule_save()

    def _drop_failed_forces(self, token: int, failed: list[str]) -> None:
        if token != self._token:
            return  # That simulation is gone. The next one tries again.
        forces = {a: v for a, v in self._state.forces.items() if a not in failed}
        self._update_state(forces=forces)
        self._message(
            f"Could not restore forces on {', '.join(failed)}. They were released.", "error"
        )

    def _input_patches(self) -> dict[str, PlcValue]:
        patches: dict[str, PlcValue] = {}
        for address, on in self._state.switches.items():
            if address not in self._state.momentary:
                patches[address] = bool(on)
        for address in self._pressed:
            patches[address] = True
        patches.update(self._state.analog)
        return patches

    def _drop_failed_links(self, token: int, failed: list[tuple[str, str]]) -> None:
        """Remove the bench links that the simulation refused, and say why.

        A link that the simulation refused because it does not know one of its tags waits.
        """
        if token != self._token:
            return
        held = {address for address, reason in failed if _unknown_tag(reason)}
        self._held |= held
        failed = [(address, reason) for address, reason in failed if address not in held]
        links = dict(self._state.links)
        for address, _reason in failed:
            links.pop(address, None)
        self._update_state(links=links)
        for address, reason in failed:
            self._message(
                f"Could not restore the bench link on {address}: {reason}. ClickNick removed it "
                "from the simulator settings.",
                "error",
            )

    def _wired(self, row: Mapping[str, Any]) -> WiredLink:
        enable = row.get("enable")
        return WiredLink(
            feedback=self.to_address(str(row.get("feedback", ""))),
            enable=None if row.get("cut") or enable is None else self.to_address(str(enable)),
            source="project" if row.get("source") == "project" else "bench",
            trigger=row.get("trigger"),
            response=response_from_dap(row),
            active=bool(row.get("active")),
            pending=bool(row.get("pending")),
            enabled=row.get("enabled", True) is not False,
        )

    def _on_links(self, token: int, body: Mapping[str, Any], *, sync: bool, edits: int) -> None:
        """Store the simulation's links for display.

        From the first listing with *sync* set, also copy the bench links into the user's
        settings. The settings then follow changes made elsewhere, such as in the Console.

        *edits* is the count of the user's link changes when the listing was asked for. If the
        user changed a link since, the listing may predate that change. The rows are then only
        shown, and the next frame asks for the links again.
        """
        if token != self._token or self._dap is None:
            return
        rows = tuple(
            self._wired(row) for row in body.get("links") or () if isinstance(row, Mapping)
        )
        self._link_rows = rows
        if edits != self._links_edits:
            self._links_refetch = True
            self._emit("desired")
            return
        # A bench link that pyrung lists no longer waits, even one that it refused before. The
        # Console may have made it since.
        self._held.difference_update(row.feedback for row in rows if row.source == "bench")
        if sync:
            self._links_synced = True
            revision = body.get("revision")
            self._links_revision_seen = revision if isinstance(revision, int) else None
        if self._links_synced:
            # Copy only the bench links between CLICK addresses. A link on a tag with no CLICK
            # address is not one that the user chose.
            adopted = {
                row.feedback: BenchLink(row.enable, row.trigger, row.response, row.enabled)
                for row in rows
                if row.source == "bench"
                and normalize_address(row.feedback) == row.feedback
                and (row.enable is None or normalize_address(row.enable) == row.enable)
            }
            # The simulation does not list a link that waits, so keep it from the settings.
            for address, link in self._state.links.items():
                if address not in adopted and self._waits(address, link):
                    adopted[address] = link
            bench = body.get("bench") is not False
            if adopted != dict(self._state.links) or bench != self._state.bench_wiring:
                self._update_state(links=adopted, bench_wiring=bench)
                return
        self._emit("desired")

    def _refetch_links(self, token: int) -> None:
        if token == self._token:
            self._links_refetch = True  # The listing went unanswered, so the next frame asks again.

    # ------------------------------------------------------------------
    # Bench links
    # ------------------------------------------------------------------

    def _fetch_links(self, dap: Any, token: int, *, sync: bool = False) -> None:
        """Read the links back after any queued actions. Any thread may call this."""
        # A link change that comes after this point sends its job after the listing.
        edits = self._links_edits

        def job() -> None:
            try:
                body = dict(dap.list_links())
            except Exception as exc:
                if _unavailable(exc):
                    self._post(lambda: self._refetch_links(token))
                return
            self._post(lambda: self._on_links(token, body, sync=sync, edits=edits))

        self._run_serial(job)

    def _reapply(self, dap: Any) -> None:
        """Bring a fresh simulation back to the switches, values, forces and links the user chose.

        Call this only after a launch. A write keeps the same process, and pyrung's planned
        reload moves the forces and links that pyrung already holds (:meth:`_write_program`).
        """
        forces = dict(self._state.forces)
        # The simulation would refuse a link that waits, so it stays in the settings unsent.
        # Until the first frame lists the tags, nothing waits, and every link goes.
        links = {a: link for a, link in self._state.links.items() if not self._waits(a, link)}
        bench_wiring = self._state.bench_wiring
        position = self._desired_position
        patches = self._input_patches()
        token = self._token

        # A refusal drops the entry. A simulation that stopped or never answered did not refuse,
        # so the entry stays and the rest is still sent.
        def job() -> None:
            unanswered: list[str] = []
            problems: list[str] = []

            def refusal(what: str, request: Callable[[], object]) -> str | None:
                """Send *request* and return why it was refused, or None.

                If the simulation did not answer, add *what* to the unanswered list.
                """
                try:
                    request()
                except Exception as exc:
                    if not _unavailable(exc):
                        return str(exc)
                    if what not in unanswered:
                        unanswered.append(what)
                return None

            failed_links: list[tuple[str, str]] = []
            for address, link in links.items():
                what = f"the bench link on {address}"
                reason = refusal(what, partial(_send_link, dap, address, link))
                if reason is None and not link.enabled:
                    reason = refusal(what, partial(dap.set_links, enabled={address: False}))
                if reason is not None:
                    failed_links.append((address, reason))
            if failed_links:
                self._post(lambda: self._drop_failed_links(token, failed_links))
            if not bench_wiring:
                reason = refusal("bench wiring off", partial(dap.set_links, bench=False))
                if reason is not None:
                    problems.append(
                        f"The simulation refused to stop applying bench links: {reason}."
                    )
            self._fetch_links(dap, token, sync=True)
            # Launched with keepForcesOnRun, so forces set in STOP survive into RUN.
            failed = [
                address
                for address, value in forces.items()
                if refusal(f"the force on {address}", partial(dap.force, address, value))
                is not None
            ]
            if failed:
                self._post(lambda: self._drop_failed_forces(token, failed))
            if position != "stop":
                reason = refusal("the switch position", partial(_enter_run, dap, patches))
                if reason is None and position == "run":
                    reason = refusal("the switch position", dap.continue_)
                if reason is not None:
                    problems.append(f"The simulation refused the switch position: {reason}.")
            if unanswered:
                problems.append(
                    f"The simulation did not answer for {', '.join(unanswered)}. ClickNick keeps "
                    "them in your settings."
                )
            if problems:
                raise RuntimeError(" ".join(problems))

        self._submit(job, "Restoring simulator settings")

    # ------------------------------------------------------------------
    # Modbus
    # ------------------------------------------------------------------

    def _poll_modbus_info(self) -> None:
        self._modbus_info_after_id = None
        dap = self._dap
        if dap is None:
            return
        token = self._token

        def job() -> None:
            try:
                info = dict(dap.modbus_info())
            except Exception as exc:
                info = {"running": False, "error": str(exc)}
            self._post(lambda: self._on_modbus_info(token, info))

        self._run_background(job, "sim-modbus-info")

    def _report_died(self, detail: str | None) -> None:
        self._stop_dap()
        self._status = SimStatus.FAILED
        self._error = "the simulation stopped unexpectedly."
        self._error_detail = detail
        self._message("The simulation stopped unexpectedly.", "error")
        self._emit("status")

    def _on_launched(self, token: int, dap: Any, source: PlcSourceWatch | None) -> None:
        if token != self._token or self._closed or not self._enabled:
            self._run_background(dap.terminate, "sim-dap-stop")
            return
        if token == self._died_token or getattr(dap.state, "value", dap.state) == "error":
            # The process exited after answering launch, before this ran.
            self._run_background(dap.terminate, "sim-dap-stop")
            self._report_died(getattr(dap, "stderr_text", "") or None)
            return
        self._dap = dap
        self._program_source = source
        self._forces_baseline = None
        self._modbus_info = {}
        # Say in the transcript that it worked, so a "Retrying..." line does not trail off.
        self._message("OK - simulation ready.", "progress")
        self._set_status(SimStatus.READY)
        self._clear_refusal()
        if self._plc_data_warning is not None:
            self._set_notice(self._plc_data_warning, "error")
            self._plc_data_warning = None
        self._check_program()
        self._reapply(dap)
        self._modbus_info_after_id = self._scheduler.after(0, self._poll_modbus_info)

    def _on_dap_died(self, token: int) -> None:
        if token != self._token:
            return
        dap = self._dap
        if dap is None:
            self._died_token = token  # Still starting. _on_launched reports the death.
            return
        self._report_died(getattr(dap, "stderr_text", "") or None)

    def _adopt_forces(self, actual: dict[str, PlcValue]) -> None:
        """Follow forces changed elsewhere (the Console, `pyrung live`).

        Compare each frame with the previous one. The first frame of a fresh simulation only
        sets the baseline. The session's own requests are already in the desired forces, so
        they change nothing.
        """
        baseline = self._forces_baseline
        self._forces_baseline = actual
        if baseline is None:
            return
        missing = object()
        added = {a: v for a, v in actual.items() if baseline.get(a, missing) != v}
        removed = [a for a in baseline if a not in actual]
        if not added and not removed:
            return
        forces = dict(self._state.forces)
        forces.update(added)
        for address in removed:
            forces.pop(address, None)
        if forces != dict(self._state.forces):
            self._update_state(forces=forces)

    def _on_frame(self, token: int) -> None:
        self._frame_posted = False
        dap = self._dap
        if token != self._token or dap is None:
            return
        if dap.speed is not None:
            self._speed = dap.speed
        self._links_pending = {self.to_address(k): ms for k, ms in dap.links_pending.items()}
        if self._writing:
            # A write is in flight, and the tag names change when its answer arrives. Until
            # then, only redraw. Do not read the switch position or forces from this frame.
            self._emit("frame")
            return
        self._refresh_named()
        if self._examine_build():  # Compare the build before the views read program_change.
            self._check_program()
        # Others can drive the simulation too, such as the Console or an agent through
        # `pyrung live`. The session takes the mode, pacing and forces from each frame, so it
        # shows the result of the most recent command from anyone.
        if not self._position_held:
            self._desired_position = self.switch_position
        self._adopt_forces(self._addressed(dap.forces))
        revision = dap.links_revision
        if self._links_refetch or (self._links_synced and revision != self._links_revision_seen):
            self._links_refetch = False
            if self._links_synced:
                self._links_revision_seen = revision
            self._fetch_links(dap, token, sync=not self._links_synced)
        self._emit("frame")

    # ------------------------------------------------------------------
    # Frames from the simulation
    # ------------------------------------------------------------------

    def _on_frame_bg(self, token: int) -> None:
        # A frame can arrive every scan. Collapse them into one UI update.
        if self._frame_posted:
            return
        self._frame_posted = True
        self._post(lambda: self._on_frame(token))

    def _on_dap_state_bg(self, token: int, state: Any, _error: Exception | None) -> None:
        if getattr(state, "value", state) == "error":
            self._post(lambda: self._on_dap_died(token))
        else:
            self._on_frame_bg(token)

    def start(self) -> None:
        """Launch the simulation from the current program analysis."""
        from .services.analysis_service import AnalysisStatus

        if self._closed or not self._enabled:
            return
        self._stop_dap()
        self._cancel(self._analysis_after_id)
        self._analysis_after_id = None

        analysis = self._get_analysis()
        if analysis is not None:
            # A build rewrites the generated project in place. While one runs, the folder on disk
            # is partial, whatever the previous result still says. Wait for the build before
            # touching any of it.
            if analysis.status is AnalysisStatus.BUILDING:
                self._wait_for_analysis()
                return
            # Remember the generation, so a failure can tell "the project was rewritten under the
            # launch" from "this project genuinely does not run". It also lets the next CLICK
            # save (a new generation) be offered.
            self._program_generation = analysis.generation
            self._program_saves = self._save_count()
            if analysis.status is not AnalysisStatus.FAILED and not analysis.is_available:
                self._wait_for_analysis()
                return
        # Open editors may still use a cached graph from an earlier build. The simulation must
        # use a successful conversion of the current CLICK program.
        problem = self._workspace_problem(analysis)
        if problem is not None:
            self._fail(*problem)
            return
        plc_data = self._plc_data_path
        if plc_data is not None and self._plc_data_changed():
            # The watch tick reads a changed file only while a simulation runs. Read it here, so
            # that the switches come from it and the next watch tick does not restart.
            self._adopt_snapshot(plc_data)
        assert analysis is not None and analysis.project_dir is not None
        project_dir = analysis.project_dir

        # The process runs this program, under these tag names, until the next launch or write.
        self._program_names = (analysis.project_tag_to_addr_key, analysis.project_addr_key_to_tag)
        self._program_dir = project_dir
        self._token += 1
        token = self._token
        self._set_status(SimStatus.STARTING)
        self.refresh_layout(force=True)

        snapshot_path = self._plc_data_path
        modbus = {"host": MODBUS_HOST, "port": self._state.modbus_port}
        speed = self._speed

        def launch() -> None:
            # Snapshot the source before pyrung imports it. An edit made while pyrung starts then
            # counts as a change.
            source = _watch_source(project_dir)
            dap = self._dap_factory(
                on_state=lambda state, error: self._on_dap_state_bg(token, state, error),
                on_scan=lambda _scan: self._on_frame_bg(token),
                on_frame=lambda: self._on_frame_bg(token),
            )
            try:
                dap.launch(
                    project_dir,
                    snapshot_path=snapshot_path,
                    session_name=self._session_name,
                    modbus=modbus,
                    speed=speed,
                    start_mode="stop",
                    keep_forces_on_run=True,
                )
            except Exception as exc:
                self._post(lambda error=exc: self._on_launch_failed(token, error))
                return
            if not self._post(lambda: self._on_launched(token, dap, source)):
                dap.terminate()  # The session closed while it started. Nobody else will stop it.

        self._run_background(launch, "sim-dap-launch")

    def retry(self) -> None:
        """Rebuild the analysis (if possible) and launch again."""
        self._waited_ms = 0
        self._message("Retrying...", "progress")
        if self._on_retry_analysis is not None:
            try:
                self._on_retry_analysis()
            except Exception as exc:
                self._message(f"Could not start the workspace build: {exc}", "error")
        if self._enabled:
            self.start()
        else:
            self.turn_on()

    def restart(self) -> None:
        """Start over on what the workspace holds now (CLICK's last save and any edits).

        The new process starts from power-on values (or the PLC data file). It keeps the user's
        mode, switches, forces and bench links by address. If the workspace cannot start a
        simulation, Restart does not stop the running one. It says why, and the simulation runs
        on.
        """
        from .services.analysis_service import AnalysisStatus

        if not self._enabled or self._closed:
            return
        if self._writing:
            self._message("Cannot restart while the program is being written.", "error")
            return
        if self._dap is not None:
            analysis = self._get_analysis()
            if analysis is not None and analysis.status is AnalysisStatus.BUILDING:
                reason = "CLICK's save is still being converted. Restart once it is done."
            else:
                problem = self._workspace_problem(analysis)
                reason = problem[0] if problem is not None else None
            if reason is not None:
                self._refuse(
                    f"Cannot restart the simulation: {reason}\n"
                    "The simulation still runs the previous program."
                )
                return
        self.relaunch()

    def relaunch(self) -> None:
        """Launch again if the simulation is on, after the workspace moved.

        Wait for a build to finish first.
        """
        if self._enabled and not self._closed:
            self._waited_ms = 0
            self.start()

    # ------------------------------------------------------------------
    # Writing a changed program, as to a CLICK
    # ------------------------------------------------------------------

    @property
    def console_busy(self) -> bool:
        """Return True while a Console command is in flight (:meth:`run_console_command`)."""
        return self._console_commands > 0

    @property
    def writing(self) -> bool:
        """Return True from a write's request until pyrung answers. The Console waits meanwhile."""
        return self._writing

    def _end_console_command(self, finish: Callable[[], None] | None) -> None:
        self._console_commands -= 1
        if not self._console_commands:
            self._emit("desired")
        if finish is not None:
            finish()

    def run_console_command(self, run: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run a Console command: *run* on a worker thread, then *done* with its result.

        The command is in flight from now until *run* returns, whether or not the panel that
        sent it is still open. The session offers no write meanwhile. *done* runs on the UI
        thread, after the session lowers its count of commands in flight. If *run* raises,
        *done* is not called.
        """
        self._console_commands += 1
        if self._console_commands == 1:
            self._emit("desired")

        def worker() -> None:
            finish: Callable[[], None] | None = None
            try:
                result = run()
                finish = partial(done, result)
            finally:
                self._post(partial(self._end_console_command, finish))

        self._run_background(worker, "console-cmd")

    def _adopt_listing(self, listing: _Listing) -> None:
        """Set the user's forces, bench links and bench wiring to those in *listing*.

        After a write that went through, *listing* holds what pyrung placed on the new program.
        After a write that pyrung refused, it holds what pyrung had before the write. Both are
        keyed by CLICK address. The bench links that wait join the ones that pyrung holds.
        """
        state = self._state
        links = {**listing.waiting, **listing.links}
        self._held = set(listing.waiting) - set(listing.links)
        if (
            dict(listing.forces) != dict(state.forces)
            or links != dict(state.links)
            or listing.bench_wiring != state.bench_wiring
        ):
            self._update_state(
                forces=dict(listing.forces),
                links=links,
                bench_wiring=listing.bench_wiring,
            )
        # Compare later frames with this listing, by address.
        self._forces_baseline = dict(listing.forces)
        if listing.problems:
            self._message("The program was written. " + " ".join(listing.problems), "error")

    def _on_written(
        self,
        token: int,
        summary: str,
        target: _WriteTarget,
        source: PlcSourceWatch | None,
        listing: _Listing,
    ) -> None:
        from .services.analysis_service import AnalysisStatus

        dap = self._dap
        if token != self._token or dap is None:
            return  # The process was replaced meanwhile, and the new one has its own names.
        self._writing = False
        self._write_error = None
        self._position_held = False
        self._clear_refusal()
        # Adopt the forces and links where the write placed them, by CLICK address. Do it before
        # the tag names switch.
        self._adopt_listing(listing)
        if summary:
            self._message(summary)
        analysis = self._get_analysis()
        if (
            analysis is None
            or analysis.generation != target.generation
            or analysis.status is AnalysisStatus.BUILDING
        ):
            # A build rewrote the workspace during the reload, so it is unknown which files
            # pyrung read. Keep the old names and offer the change again. Until the next write
            # or launch, do not record any build as the running program.
            self._program_source = None
            self._message(
                "The workspace was rebuilt while the program was written, so ClickNick "
                "cannot tell which files the simulation read. Write the program again when "
                "the build finishes.",
                "error",
            )
        else:
            self._program_names = target.names
            self._refresh_named()
            self._program_generation = target.generation
            self._program_saves = target.saves
            self._program_source = source
            self._source_changed = False
            self._message("OK - the simulation runs the new program.", "progress")
            if listing.carried:
                self._set_notice(listing.carried)
                self._written_notice = listing.carried
            elif self._written_notice is not None and self._notice == self._written_notice:
                # The notice of an earlier write may name a link that no longer waits. Name only
                # the links that still wait, or clear the notice if none does.
                text = _waiting_text(listing.waiting) if listing.waiting else None
                if text is None:
                    self._notice = None
                    self._emit("desired")
                elif text != self._notice:
                    self._set_notice(text)
                    self._written_notice = text
        # Read the links back with the tag names that apply after the write. In a reload,
        # pyrung drops a bench link that the new program declares with the same wiring, a
        # bench cut whose declared link is gone, and a bench link that does not fit the new
        # program. Reading its listing back makes the user's links the ones that it kept.
        self._links_synced = False
        self._links_refetch = False
        self._fetch_links(dap, token, sync=True)
        self._check_program()
        self._restart_if_due()

    def _on_write_failed(
        self,
        token: int,
        text: str,
        listing: _Listing | None,
        *,
        known: bool = True,
        released: tuple[str, ...] = (),
    ) -> None:
        """Handle a failed write.

        If *known* is False, pyrung never answered, so nobody knows which program the
        simulation runs.

        *released* names what the reload's plan releases.
        """
        dap = self._dap
        if token != self._token or dap is None:
            return
        self._writing = False
        if not known:
            text = (
                f"{text}. ClickNick cannot tell which program the simulation runs, and it may be "
                "paused"
            )
            if released:
                text = (
                    f"{text}. If the simulation runs the new program, it released "
                    f"{', '.join(released)}"
                )
            # Frames may show it paused. Restart starts in the position that the user had.
            self._position_held = True
        self._write_error = text
        if listing is not None:
            self._adopt_listing(listing)
        else:
            self._forces_baseline = None
        still = " The simulation still runs the previous one." if known else ""
        self._message(f"Writing the program failed: {text}.{still}", "error")
        self._links_synced = False
        self._links_refetch = False
        self._fetch_links(dap, token, sync=True)
        self._check_program()
        self._restart_if_due()

    def _write_refusal(self) -> str | None:
        """Return why the workspace's program cannot be written to the simulation, or None."""
        from .services.analysis_service import AnalysisStatus

        analysis = self._get_analysis()
        if analysis is not None and analysis.status is AnalysisStatus.BUILDING:
            return "CLICK's save is still being converted. Write it once it is done."
        problem = self._workspace_problem(analysis)
        if problem is not None:
            return problem[0]
        assert analysis is not None
        if analysis.project_dir != self._program_dir:
            return "the workspace is in another folder now. Restart runs it from there."
        return None

    @staticmethod
    def _listing_as_set(
        forced: Mapping[str, PlcValue],
        rows: Mapping[str, Mapping[str, Any]],
        bench_wiring: bool,
        names: tuple[Mapping[str, int], Mapping[int, str]],
        waiting: Mapping[str, BenchLink],
    ) -> _Listing:
        """Return pyrung's listing keyed by CLICK address, with the names of the program it runs.

        *waiting* holds the bench links that pyrung does not have, because they wait.
        """
        forces: dict[str, PlcValue] = {}
        for name, value in forced.items():
            address = address_of(name, names)
            if address is not None:
                forces[address] = value
        links: dict[str, BenchLink] = {}
        for fb, row in rows.items():
            address = address_of(fb, names)
            enable = _link_enable(row)
            enable_at = None if enable is None else address_of(enable, names)
            if address is not None and (enable is None or enable_at is not None):
                links[address] = _bench_link(row, enable_at)
        return _Listing(forces, links, bench_wiring, waiting=waiting)

    def _write_program(self, how: Literal["keep", "stop"], *, echo: bool = True) -> None:
        """Reload the workspace's program in the running process, without a relaunch.

        This is one job on the action worker, and the Console waits for it. The job reads the
        forces and bench links that pyrung holds and plans where each one goes under the new
        tag names (:func:`plan_carry`). It sends the plan with pyrung's planned reload. The
        reload pauses the scan if it was running, keeps the mode, and moves each force and link
        as planned. Then the job puts the switch position back, so the simulation scans as it
        did before. The forces and links that pyrung reports it placed become the user's. If
        pyrung refuses the reload, nothing changes in pyrung. The old program runs on, and
        Restart is offered.

        A bench link waits while no rung in the simulation names its feedback or its enable
        (:meth:`link_waits`). After the reload, the job sends each link that waited, unless the
        new program's tags have arrived and a rung there still does not name both ends. A link
        that pyrung refuses because it does not know a tag waits on. When pyrung drops a link
        or a force because the new program does not have its tag (reason ``gone``), the link
        waits, and the job sends the force again by address.
        """
        dap = self._dap
        if not self.is_ready or dap is None:
            self._message(
                "Cannot write the program, because the simulation is not running. Start the "
                "simulation first.",
                "error",
            )
            return
        if self._writing:
            self._message(
                "The program is already being written to the simulation. Wait for that write "
                "to finish.",
                "error",
            )
            return
        if self._console_commands:
            self._message("Cannot write the program while a Console command runs.", "error")
            return
        reason = self._write_refusal()
        if reason is not None:
            self._refuse(
                f"Cannot write the program: {reason}\n"
                "The simulation still runs the previous program."
            )
            return
        analysis = self._get_analysis()
        assert analysis is not None and self._program_dir is not None
        old_names = self._tag_maps()
        old = (dict(old_names[0]), dict(old_names[1]))
        target = _WriteTarget(
            analysis.generation,
            (dict(analysis.project_tag_to_addr_key), dict(analysis.project_addr_key_to_tag)),
            self._save_count(),
        )
        waiting_before = {a: link for a, link in self._state.links.items() if self._waits(a, link)}
        analog = self._analog_channels()
        project_dir = self._program_dir
        position = self._desired_position
        patches = self._input_patches()
        token = self._token
        self._writing = True
        self._message("Writing the program to the simulation...", "progress")
        if echo:
            self._echo("reload")
        self._emit("desired")

        def job() -> None:
            source = _watch_source(project_dir)
            problems: list[str] = []
            unanswered: list[str] = []

            def refusal(what: str, request: Callable[[], object]) -> str | None:
                """Send *request* and return why it was refused, or None.

                If the simulation did not answer, add *what* to the unanswered list.
                """
                try:
                    request()
                except Exception as exc:
                    if not _unavailable(exc):
                        return str(exc)
                    if what not in unanswered:
                        unanswered.append(what)
                return None

            try:
                forced = dict(dap.list_forces())
                listed = dict(dap.list_links())
            except Exception as exc:
                text = str(exc)
                self._post(lambda: self._on_write_failed(token, text, None))
                return

            # Use pyrung's listing, not ClickNick's copy, because the Console may have changed it.
            rows = {
                str(row.get("feedback", "")): row
                for row in listed.get("links") or ()
                if isinstance(row, Mapping) and row.get("source") == "bench"
            }
            enables = {name: _link_enable(row) for name, row in rows.items()}
            declared = [
                str(row.get("feedback", ""))
                for row in listed.get("links") or ()
                if isinstance(row, Mapping) and row.get("source") == "project" and row.get("active")
            ]
            linked = linked_feedbacks(project_dir / "csv")
            plan = plan_carry(old, target.names, forced, enables, analog, declared, linked)
            bench_wiring = listed.get("bench") is not False
            try:
                body = dap.planned_reload(plan.as_dap())
            except Exception as exc:
                error = str(exc)
                if _unavailable(exc):
                    # No answer, so it is unknown which program runs and which names apply.
                    # Send nothing by name. Restart starts over.
                    released = tuple(
                        [f"the force on {name}" for name, new in plan.forces.items() if new is None]
                        + [
                            f"the bench link on {fb}"
                            for fb, new in plan.links.items()
                            if new is None
                        ]
                    )
                    self._post(
                        partial(
                            self._on_write_failed,
                            token,
                            error,
                            None,
                            known=False,
                            released=released,
                        )
                    )
                    return
                # The simulation refused, so nothing changed. It may have paused if it was
                # running, so continue it if the switch is at RUN.
                if position == "run":
                    refusal("the switch position", dap.continue_)
                listing = self._listing_as_set(forced, rows, bench_wiring, old, waiting_before)
                self._post(lambda: self._on_write_failed(token, error, listing))
                return

            reason = None
            if how == "stop":
                # STOP -> RUN on the new program keeps retentive values and clears the rest.
                # Forces stay too, because the launch set keepForcesOnRun.
                reason = refusal("STOP", partial(dap.set_mode, "stop"))
                if reason is None:
                    reason = refusal("the switch position", partial(_enter_run, dap, patches))
            elif position != "stop" and patches:
                # Send the inputs again. An input whose tag was renamed lost its value under the
                # old name.
                reason = refusal("the switch position", partial(_patch_inputs, dap, patches))
            if reason is None and position == "run":
                reason = refusal("the switch position", dap.continue_)
            if reason is not None:
                problems.append(f"The simulation refused the switch position: {reason}.")

            carried = [e for e in body.get("carried") or () if isinstance(e, Mapping)]
            names = target.names
            # Collect what pyrung placed, by CLICK address, as the user's forces and links.
            forces: dict[str, PlcValue] = {}
            links: dict[str, BenchLink] = {}
            for entry in carried:
                tag, to = str(entry.get("tag", "")), entry.get("to")
                if to is None:
                    continue  # pyrung released or dropped this entry.
                address = address_of(str(to), names)
                if address is None:
                    continue  # It has no CLICK address, so it is not the user's.
                kind = entry.get("kind")
                if kind == "force":
                    # Use pyrung's value. A force can change between the listing and the reload.
                    forces[address] = entry["value"] if "value" in entry else forced.get(tag)
                elif kind in ("link", "cut") and tag in rows:
                    enable = entry.get("enable")
                    enable_at = None if enable is None else address_of(str(enable), names)
                    if enable is None or enable_at is not None:
                        links[address] = _bench_link(rows[tag], enable_at)

            def where(name: str) -> str | None:
                """Return the address of *name* in the new program, else in the old one."""
                return address_of(name, names) or address_of(name, old)

            # pyrung drops an entry as "gone" when the new program does not have one of its
            # tags. A link there waits. A force there goes again by address. If pyrung refuses
            # that too, the notice reports the force as dropped.
            waiting: dict[str, BenchLink] = {}
            kept: set[tuple[str, str]] = set()
            for entry in carried:
                if entry.get("reason") != "gone":
                    continue
                tag, kind = str(entry.get("tag", "")), entry.get("kind")
                if kind == "force":
                    to = plan.forces.get(tag, tag)
                    address = None if to is None else where(to)
                    if address is None:
                        continue
                    value = entry["value"] if "value" in entry else forced.get(tag)
                    if refusal(f"the force on {address}", partial(dap.force, address, value)):
                        continue
                    forces[address] = value
                    kept.add(("force", tag))
                elif kind in ("link", "cut") and tag in rows:
                    moved = plan.links.get(tag, LinkTarget(tag, enables.get(tag)))
                    if moved is None:
                        continue  # The plan dropped the link.
                    address = where(moved.feedback)
                    enable_at = None if moved.enable is None else where(moved.enable)
                    if address is not None and (moved.enable is None or enable_at is not None):
                        waiting[address] = _bench_link(rows[tag], enable_at)
                        kept.add(("link", tag))
            # After the reload's answer, pyrung sends a frame that lists the new program's tags.
            # If that frame has arrived, it says which links can go. If not, send each link,
            # and a link that pyrung refuses for an unknown tag waits.
            tags = dap.program_tags
            named = None if tags is None else _named_addresses(tags, names)
            for address, link in waiting_before.items():
                if address in links or address in waiting:
                    continue
                if link_waits(address, link, named):
                    waiting[address] = link
                    continue
                what = f"the bench link on {address}"
                reason = refusal(what, partial(_send_link, dap, address, link))
                if reason is None and not link.enabled:
                    reason = refusal(what, partial(dap.set_links, enabled={address: False}))
                if reason is None:
                    links[address] = link
                elif _unknown_tag(reason):
                    waiting[address] = link
                else:
                    problems.append(f"Could not apply the bench link on {address}: {reason}.")
            if unanswered:
                problems.append(f"The simulation did not answer for {', '.join(unanswered)}.")
            written = plan.written(
                e
                for e in carried
                if ("force" if e.get("kind") == "force" else "link", str(e.get("tag"))) not in kept
            )
            parked = {a: link for a, link in waiting.items() if a not in waiting_before}
            if parked:
                written = " ".join(part for part in (written, _waiting_text(parked)) if part)
            listing = _Listing(
                forces, links, bench_wiring, tuple(problems), written, waiting=waiting
            )
            summary = str(body.get("result") or "")
            self._post(lambda: self._on_written(token, summary, target, source, listing))

        self._run_serial(job)

    def run_time_edit(self) -> None:
        """Write the workspace's program while in RUN, keeping every value, timer and force."""
        if self._write_position == "run":
            self._write_program("keep")

    def stop_and_write(self) -> None:
        """Go to STOP, write the workspace's program and RUN again.

        pyrung's STOP -> RUN keeps retentive values and forces and clears the
        rest, as a CLICK does after a write in STOP.
        """
        if self._write_position == "run":
            self._write_program("stop")

    def write_program(self) -> None:
        """Write the workspace's program in STOP or while stepping; values and mode stay."""
        if self._write_position != "run":
            self._write_program("keep")

    def reload(self) -> None:
        """Do what a Console ``reload`` does: RUN Time Edit in RUN, Write otherwise."""
        self._write_program("keep", echo=False)

    def close(self) -> None:
        """Stop everything and save. The session is unusable afterwards."""
        self._enabled = False
        self._shutdown()
        self._closed = True
        self._worker.close()
        self._listeners.clear()

    def set_plc_data_path(self, path: Path) -> None:
        """Start the simulation from a CLICK data dump.

        Restart the simulation as soon as no write or build is running, and again each time the
        file changes. The switch positions and analog inputs are set from the dump's values.
        Forces stay as they are.
        """
        self._plc_data_path = path
        self._plc_data_mtime = _mtime(path)
        self._message(f"Loading PLC data: {path}")
        self._adopt_snapshot(path)
        self._restart_when_free()

    def _on_modbus_connect_failed(self, service: Any, text: str) -> None:
        if service is not self._modbus:
            return
        self._disconnect_modbus()
        self._message(text, "error")

    def _on_modbus_state(self, service: Any, connected: bool) -> None:
        if service is None or service is not self._modbus:
            return
        if connected != self._modbus_connected:
            self._modbus_connected = connected
            self._emit("modbus")

    def _on_modbus_values(self, service: Any) -> None:
        self._values_posted = False
        if service is None or service is not self._modbus:
            return
        self._values = {
            normalize_address(str(k)) or str(k): v for k, v in dict(self._pending_values).items()
        }
        self._emit("values")

    def _poll_addresses(self) -> list[str]:
        found: dict[str, None] = {}
        for _owner, addresses in self._watched.values():
            found.update(dict.fromkeys(addresses))
        return list(found)

    def _connect_modbus(self) -> None:
        port = int(self._modbus_info.get("port") or self._state.modbus_port)
        holder: list[Any] = []

        def on_state(state: Any, _error: Exception | None) -> None:
            connected = getattr(state, "value", state) == "connected"
            self._post(lambda: self._on_modbus_state(holder[0] if holder else None, connected))

        def on_values(values: Mapping[str, PlcValue]) -> None:
            self._pending_values = values
            if not self._values_posted:
                self._values_posted = True
                self._post(lambda: self._on_modbus_values(holder[0] if holder else None))

        service = self._modbus_factory(
            poll_interval_s=MODBUS_POLL_S, on_state=on_state, on_values=on_values
        )
        holder.append(service)
        self._modbus = service
        addresses = self._poll_addresses()

        def job() -> None:
            try:
                service.connect(MODBUS_HOST, port, timeout=2)
                if addresses:
                    service.set_poll_addresses(addresses)
            except Exception as exc:
                text = f"Could not connect to the simulator's Modbus server: {exc}"
                self._post(lambda: self._on_modbus_connect_failed(service, text))
                return
            self._post(lambda: self._on_modbus_state(service, True))

        self._run_serial(job)

    def _on_modbus_info(self, token: int, info: dict[str, Any]) -> None:
        if token != self._token or self._dap is None:
            return
        changed = info != self._modbus_info
        self._modbus_info = info
        if self.modbus_available and self._modbus is None:
            self._connect_modbus()
        if changed:
            self._emit("modbus")
        self._modbus_info_after_id = self._scheduler.after(MODBUS_INFO_MS, self._poll_modbus_info)

    def _update_poll(self) -> None:
        service = self._modbus
        if service is None:
            return
        addresses = self._poll_addresses()

        def job() -> None:
            if addresses:
                service.set_poll_addresses(addresses)
            else:
                service.clear_poll_addresses()

        self._submit(job, "Updating the Modbus poll list")

    def watch(self, owner: object, addresses: Iterable[str]) -> None:
        """Poll *addresses* over Modbus for *owner* until :meth:`unwatch`."""
        self._watched[id(owner)] = (owner, tuple(addresses))
        self._update_poll()

    def unwatch(self, owner: object) -> None:
        if self._watched.pop(id(owner), None) is not None:
            self._update_poll()

    def _write(self, values: dict[str, PlcValue], what: str) -> None:
        """Patch inputs over DAP. pyclickplc's client refuses an X write."""
        dap = self._dap
        if dap is None:
            return  # The values are applied when the simulation (re)starts or enters RUN.
        self._submit(lambda: _patch_inputs(dap, values), what)

    def set_modbus_port(self, port: int) -> None:
        """Move the simulation's Modbus server to *port*. This relaunches the simulation."""
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        if port == self._state.modbus_port:
            return
        self._update_state(modbus_port=port)
        self._restart_when_free()

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    def is_momentary(self, address: str) -> bool:
        return address in self._state.momentary

    def set_momentary(self, address: str, momentary: bool) -> None:
        """Choose whether *address* is a pushbutton (Momentary) or a latching switch."""
        current = set(self._state.momentary)
        if momentary == (address in current):
            return
        switches = dict(self._state.switches)
        if momentary:
            current.add(address)
            was_on = switches.pop(address, False)
            self._update_state(momentary=frozenset(current), switches=switches)
            if was_on:
                self._write({address: False}, f"Writing {address}")
        else:
            current.discard(address)
            if address in self._pressed:
                self._pressed.discard(address)
                self._write({address: False}, f"Writing {address}")
            self._update_state(momentary=frozenset(current))

    def switch_on(self, address: str) -> bool:
        """Return True if the user put the switch on. The PLC may not have seen it yet."""
        if address in self._state.momentary:
            return address in self._pressed
        return bool(self._state.switches.get(address, False))

    def toggle_switch(self, address: str) -> None:
        """Flip a Maintained switch."""
        on = not self.switch_on(address)
        switches = dict(self._state.switches)
        if on:
            switches[address] = True
        else:
            switches.pop(address, None)
        self._update_state(switches=switches)
        self._write({address: on}, f"Writing {address}")
        self._echo(f"patch {self.to_tag(address)} {_command_value(on)}")

    def press_input(self, address: str) -> None:
        """Hold a Momentary switch down."""
        if address in self._pressed:
            return
        self._pressed.add(address)
        self._emit("desired")
        self._write({address: True}, f"Writing {address}")

    def release_input(self, address: str) -> None:
        """Let go of a Momentary switch."""
        if address not in self._pressed:
            return
        self._pressed.discard(address)
        self._emit("desired")
        self._write({address: False}, f"Writing {address}")

    def analog_value(self, address: str) -> float | None:
        return self._state.analog.get(address)

    def set_analog(self, address: str, value: float) -> None:
        """Set an analog input's DF value.

        While a write for *address* waits in the queue, a further change updates the value that
        it sends instead of queueing another write. A dragged slider sends many changes.
        """
        analog = dict(self._state.analog)
        analog[address] = float(value)
        self._update_state(analog=analog)
        self._echo_settled(address)
        if self._dap is None or address in self._analog_queued:
            return
        self._analog_queued.add(address)
        dap = self._dap

        def job() -> None:
            # This runs later on the worker. Send the newest value, not the one that queued it.
            self._analog_queued.discard(address)
            _patch_inputs(dap, {address: self._state.analog.get(address, float(value))})

        self._submit(job, f"Writing {address}")

    # ------------------------------------------------------------------
    # Forces
    # ------------------------------------------------------------------

    def force(
        self, address: str, value: PlcValue, *, on_error: Callable[[str], None] | None = None
    ) -> None:
        """Override *address* until released. The program cannot change it."""
        previous = self._state.forces.get(address)
        forces = dict(self._state.forces)
        forces[address] = value
        self._update_state(forces=forces)
        dap = self._dap
        if dap is None:
            return

        def undo(text: str) -> None:
            restored = dict(self._state.forces)
            if previous is None:
                restored.pop(address, None)
            else:
                restored[address] = previous
            self._update_state(forces=restored)
            if on_error is not None:
                on_error(text)

        self._submit(lambda: dap.force(address, value), f"Forcing {address}", undo)
        self._echo(f"force {self.to_tag(address)} {_command_value(value)}")

    def release_force(self, address: str) -> None:
        if address not in self._state.forces:
            return
        forces = dict(self._state.forces)
        forces.pop(address)
        self._update_state(forces=forces)
        dap = self._dap
        if dap is not None:
            self._submit(lambda: dap.unforce(address), f"Releasing {address}")
            self._echo(f"unforce {self.to_tag(address)}")

    def release_all_forces(self) -> None:
        self._restored_forces = 0
        released = list(self._state.forces)
        self._update_state(forces={})
        dap = self._dap
        if dap is not None:
            self._submit(dap.clear_forces, "Releasing all forces")
            for address in released:
                self._echo(f"unforce {self.to_tag(address)}")

    def dismiss_restored_forces(self) -> None:
        self._restored_forces = 0
        self._emit("desired")

    def _change_links(
        self,
        links: dict[str, BenchLink],
        job: Callable[[Any], object] | None,
        what: str,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Record the bench links the user chose, then make the simulation agree with them.

        *job* sends the changes to links that do not wait. It is None when there is nothing
        to send. A link that waits is not in the simulation. If the change makes a link wait,
        or drops a link that waited, the simulation may still list a bench link or cut on that
        feedback, such as the link that the waiting one replaces. ClickNick then restores the
        program's own wiring there (:func:`_restore_bench`), before it sends *job*.
        """
        self._links_edits += 1
        previous = dict(self._state.links)
        changed = [a for a in previous.keys() | links.keys() if previous.get(a) != links.get(a)]
        waited = {a for a in changed if a in previous and self._waits(a, previous[a])}
        # A held link that the user only disables or enables is the same link, so it stays held.
        self._held.difference_update(
            a
            for a in changed
            if a not in links
            or a not in previous
            or replace(previous[a], enabled=True) != replace(links[a], enabled=True)
        )
        self._update_state(links=links)
        dap = self._dap
        if dap is None:
            return  # The change is applied when the simulation (re)starts.
        quiet = {
            self.to_tag(a)
            for a in changed
            if (a in links and self._waits(a, links[a])) or (a not in links and a in waited)
        }
        if not quiet and job is None:
            return

        def undo(text: str) -> None:
            # Undo only this change. Links chosen since then stay.
            restored = dict(self._state.links)
            for address in changed:
                if address in previous:
                    restored[address] = previous[address]
                else:
                    restored.pop(address, None)
            self._update_state(links=restored)
            if on_error is not None:
                on_error(text)

        def run() -> None:
            if quiet:
                _restore_bench(dap, quiet)
            if job is not None:
                job(dap)

        self._submit(run, what, undo)

    def _link_command(self, feedback: str, link: BenchLink) -> str:
        """Return the console command that makes *link*, such as ``link X002 Y001 on_delay=2s``."""
        from .services.link_annotation import link_text

        fb = self.to_tag(feedback)
        if link.cut:
            return f"unlink {fb}"
        assert link.enable is not None
        return " ".join(
            ["link", fb, link_text(self.to_tag(link.enable), link), *response_tokens(link.response)]
        )

    def link(
        self, feedback: str, link: BenchLink, *, on_error: Callable[[str], None] | None = None
    ) -> None:
        """Wire *feedback* on the bench. If ``link.enable`` is None, cut it.

        If no rung in the simulation names *feedback* or the enable, the link waits
        (:meth:`link_waits`), and the link does not go to the simulation. ClickNick keeps the
        link and sends it at the next write. Until the first frame lists the named tags, the
        link goes to the simulation. If the simulation refuses it because it does not know a
        tag, the link waits too, with no error. While the link waits, the simulation runs the
        program's own wiring on *feedback*.
        """
        link = replace(link, enabled=True)
        links = dict(self._state.links)
        links[feedback] = link
        what = f"{'Cutting the link on' if link.cut else 'Linking'} {feedback}"
        if link_waits(feedback, link, self._named):
            self._change_links(links, None, what, on_error)
            return
        token = self._token
        tag = self.to_tag(feedback)

        def send(dap: Any) -> None:
            try:
                _send_link(dap, feedback, link)
            except Exception as exc:
                if _unavailable(exc) or not _unknown_tag(str(exc)):
                    raise
                # pyrung checks a link before it replaces anything, so the bench link or cut
                # that this link was to replace still runs.
                _restore_bench(dap, (tag,))
                self._post(lambda: self._hold(token, feedback, link))

        self._change_links(links, send, what, on_error)
        self._echo(self._link_command(feedback, link))

    def _hold(self, token: int, feedback: str, link: BenchLink) -> None:
        """Let *link* wait, because the simulation refused it for a tag that it does not know."""
        if token == self._token and self._state.links.get(feedback) == link:
            self._held.add(feedback)
            self._emit("desired")

    def cut_link(self, feedback: str, *, on_error: Callable[[str], None] | None = None) -> None:
        """Cut the program's link on *feedback*, as if the sensor failed."""
        self.link(feedback, BenchLink(None), on_error=on_error)

    def restore_link(self, feedback: str) -> None:
        """Drop the bench change on *feedback*, going back to what the program declares."""
        if feedback not in self._state.links:
            return
        waits = self.link_waits(feedback)
        links = dict(self._state.links)
        links.pop(feedback)
        self._change_links(
            links,
            None if waits else lambda dap: dap.restore_link(feedback),
            f"Restoring the link on {feedback}",
        )
        if not waits:
            self._echo(f"restore {self.to_tag(feedback)}")

    def set_link_enabled(self, feedback: str, enabled: bool) -> None:
        """Set one bench change aside, or bring it back, without forgetting it."""
        link = self._state.links.get(feedback)
        if link is None or link.enabled == enabled:
            return
        waits = self.link_waits(feedback)
        links = dict(self._state.links)
        links[feedback] = replace(link, enabled=enabled)
        self._change_links(
            links,
            None if waits else lambda dap: dap.set_links(enabled={feedback: enabled}),
            f"{'Enabling' if enabled else 'Disabling'} the bench link on {feedback}",
        )
        if not waits:
            self._echo(f"links {'enable' if enabled else 'disable'} {self.to_tag(feedback)}")

    def set_bench_wiring(self, on: bool) -> None:
        """Apply the bench changes, or set all of them aside."""
        if on == self._state.bench_wiring:
            return
        self._update_state(bench_wiring=on)
        dap = self._dap
        if dap is not None:
            self._submit(
                lambda: dap.set_links(bench=on), f"Turning bench wiring {'on' if on else 'off'}"
            )
            self._echo(f"links bench {'on' if on else 'off'}")

    def discard_bench_links(self) -> None:
        """Drop every bench change."""
        self._restored_links = 0
        # The simulation does not have a link that waits. _change_links restores whatever the
        # simulation still lists on such a feedback.
        addresses = [a for a in self._state.links if not self.link_waits(a)]

        def job(dap: Any) -> None:
            for address in addresses:
                dap.restore_link(address)

        self._change_links({}, job, "Discarding bench links")
        for address in addresses:
            self._echo(f"restore {self.to_tag(address)}")

    def dismiss_restored_links(self) -> None:
        self._restored_links = 0
        self._emit("desired")

    def dismiss_notice(self) -> None:
        self._notice = None
        self._emit("desired")

    # ------------------------------------------------------------------
    # Mode, stepping and speed
    # ------------------------------------------------------------------

    @property
    def switch_position(self) -> SwitchPosition:
        """Return where the CPU's mode switch sits, taken from the latest frame.

        STOP means mode stop. STEP means mode run, not scanning on its own, so scans only
        advance on Step, the Console or an agent. RUN means mode run, free-running.
        """
        if self._writing:
            # A reload pauses scanning, and Stop and Write passes through STOP. Show the user's
            # position until the write is answered, not those passing states.
            return self._desired_position
        if self.mode != "run":
            return "stop"
        return "run" if self.running else "step"

    def set_switch_position(self, position: SwitchPosition) -> None:
        """Move the CPU's mode switch.

        Leaving STOP enters RUN mode with the user's switches, analog values and forces in
        place for scan 1. STEP then waits before that scan.
        """
        dap = self._dap
        if dap is None:
            return
        current = self.switch_position
        if position == current:
            if self._position_held:
                # The switch already shows this position. Make it the user's choice and stop
                # holding the old one.
                self._desired_position = position
                self._position_held = False
                self._emit("desired")
            return
        if not self._state.run_hint_seen:
            self._update_state(run_hint_seen=True)
        self._desired_position = position
        self._position_held = False
        if position == "stop":
            self._submit(lambda: dap.set_mode("stop"), "Switching to STOP")
            self._echo("mode stop")
            return
        if current == "stop":
            # Forces are already in place (keepForcesOnRun). The switch and analog values go
            # with the transition, so scan 1 sees them.
            patches = self._input_patches()

            def enter_run() -> None:
                _enter_run(dap, patches)
                if position == "run":
                    dap.continue_()

            self._submit(enter_run, f"Switching to {SWITCH_LABELS[position]}")
            self._echo("mode run")
            if position == "run":
                self._echo("continue")
        elif position == "run":
            self._submit(dap.continue_, "Switching to RUN")
            self._echo("continue")
        else:
            self._submit(dap.pause, f"Switching to {SWITCH_LABELS['step']}")
            self._echo("pause")

    def _send_live(self, command: str) -> None:
        ok, text = self._send_command(self._session_name, command)
        if not ok:
            raise RuntimeError(text or command)

    def step(self, count: int = 1) -> None:
        """Advance *count* scans as fast as possible, then wait."""
        dap = self._dap
        if dap is None:
            return
        if count <= 1:
            self._submit(dap.step_scan, "Stepping")
            self._echo("step")
        else:
            self._submit(lambda: self._send_live(f"step {count}"), f"Stepping {count} scans")
            self._echo(f"step {count}")

    def run_for(self, duration: str) -> None:
        """Scan for *duration* of simulated time (``"500ms"``, ``"2 s"``) or N scans."""
        if self._dap is not None:
            text = duration.strip()
            self._submit(lambda: self._send_live(f"run {text}"), f"Running for {text}")
            self._echo(f"run {text}")

    def set_speed(self, speed: float) -> None:
        """Run at *speed* x real time (0 = as fast as possible)."""
        self._speed = float(speed)
        dap = self._dap
        if dap is not None:
            self._submit(lambda: dap.set_speed(speed), "Changing speed")
            self._echo(f"speed {f'{speed:g}' if speed else 'max'}")
        self._emit("frame")

    # ------------------------------------------------------------------
    # Hardware layout
    # ------------------------------------------------------------------

    def _used_io(self) -> set[str]:
        analysis = self._get_analysis()
        if analysis is None or not analysis.is_available:
            return set()
        tag_to_key = analysis.tag_to_addr_key
        return io_addresses(
            tag_to_key[tag]
            for tag in analysis.known_tag_names()
            if tag in tag_to_key and not tag.startswith(MODULE_STATUS_PREFIX)
        )

    def _apply_restore(self, layout: PanelLayout) -> None:
        self._restore_pending = False
        result: RestoreResult = restore_state(
            self._state, analog_inputs=layout.addresses("analog_in"), modules=layout.modules
        )
        changed = result.state != self._state
        self._state = result.state
        if result.dropped:
            lead = (
                "The hardware changed since the last session. " if result.hardware_changed else ""
            )
            self._set_notice(
                f"{lead}ClickNick removed the settings for {', '.join(result.dropped)}, "
                "because no installed analog input has those addresses."
            )
        if changed:
            self._emit("desired")
            self._schedule_save()

    def _restore_when_known(self) -> None:
        """Trim the remembered analog values to the hardware, once ClickNick has read it.

        Until then, every saved setting stays and applies. Only a module assigns a DF to an
        analog input, so the trim waits for a hardware configuration that has a CPU. It does not
        wait for a build. Switches, forces and bench links are never trimmed here.
        """
        layout = self._layout
        if (
            self._restore_pending
            and layout is not None
            and self._layout_error is None
            and layout.has_cpu
        ):
            self._apply_restore(layout)

    def refresh_layout(self, *, force: bool = False) -> None:
        """Re-read the hardware when Project.ini or the program changed."""
        path = self._get_project_ini()
        analysis = self._get_analysis()
        # The generation changes when a build starts, and the status changes when it ends.
        program = (analysis.generation, analysis.status) if analysis is not None else None
        key = (_mtime(path), program)
        if not force and key == self._layout_key:
            return
        self._layout_key = key
        used = self._used_io()
        if path is None or key[0] is None:
            layout = build_panel_layout((), used)
            error = "CLICK's Project.ini was not found. Save the project in CLICK."
        else:
            try:
                layout = self._layout_reader(path, used)
                error = None
            except Exception as exc:
                layout = build_panel_layout((), used)
                error = layout_error_text(exc)
        changed = layout != self._layout or error != self._layout_error
        self._layout = layout
        self._layout_error = error
        self._restore_when_known()
        if changed:
            self._emit("layout")

    def set_state_location(self, plc_name: str, workspace_dir: Path | None) -> None:
        """Load the remembered settings, moving them into a newly paired workspace."""
        self._flush_save()
        try:
            state_file = settle_state_file(
                plc_name, workspace_dir, app_data_root=self._app_data_root
            )
        except OSError as exc:
            self._message(f"Could not move simulator settings: {exc}", "error")
            state_file = StateFile(
                settle_state_file(plc_name, None, app_data_root=self._app_data_root).path
            )
        if state_file.path == self._state_path:
            return
        first_load = self._state_path is None
        self._state_path = state_file.path
        # Read the file on the first load, or when the workspace had its own settings file.
        # Otherwise the file only moved, and the settings in memory are already right.
        if first_load or state_file.notice is not None:
            try:
                loaded = load_state(state_file.path)
            except (OSError, ValueError) as exc:
                self._message(
                    f"Could not read the simulator settings: {exc}. ClickNick starts without "
                    "them and replaces the file at the next change.",
                    "error",
                )
                loaded = SimulatorState()
            for key in loaded.unread_forces:
                self._message(
                    f"Could not restore the force on {key}: it is not a CLICK address. ClickNick "
                    "removed it from the simulator settings.",
                    "error",
                )
            for key, reason in loaded.unread_links:
                self._message(
                    f"Could not restore the bench link on {key}: {reason}. ClickNick removed it "
                    "from the simulator settings.",
                    "error",
                )
            loaded = replace(loaded, unread_links=(), unread_forces=())
            self._state = loaded
            self._restore_pending = True
            self._restored_forces = len(loaded.forces)
            self._restored_links = len(loaded.links)
            self._restore_when_known()
            self._emit("desired")
        if state_file.notice:
            self._set_notice(state_file.notice)

    @property
    def state_path(self) -> Path | None:
        return self._state_path
