"""Simulation session: one simulated PLC for the connected CLICK project.

Owned by ConnectionSession. Pure logic (no tkinter): it owns the pyrung DAP
subprocess (launched with a Modbus server, real-time pacing and STOP mode),
the Modbus client the Simulator window reads values through, the
switch/analog/force settings and bench links the user chose, and their
persistence. The
Simulator window (with its console) and the Dataview editor observe it and
call its methods; neither owns the simulation.

Two channels reach the simulated PLC: values are read over Modbus exactly
as from real hardware; inputs (switches, analog values), mode, speed,
stepping, forces and bench links go over DAP. X stays read-only over Modbus, as on a
real CLICK.

Everything public runs on the UI thread. Work that blocks runs on worker
threads, and its results come back through ``scheduler.after(0, ...)``.
"""

from __future__ import annotations

import enum
import os
import queue
import threading
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pyclickplc.addresses import (
    format_address_display,
    get_addr_key,
    normalize_address,
    parse_addr_key,
    parse_address,
)

from .services.sim_hardware import PanelLayout, build_panel_layout, io_addresses
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


SwitchPosition = Literal["stop", "step", "run"]
#: Labels for the CPU mode switch. The middle position's name is not final;
#: rename it here only.
STEP_LABEL = "STEP"
SWITCH_LABELS: dict[SwitchPosition, str] = {"stop": "STOP", "step": STEP_LABEL, "run": "RUN"}

#: Frame ``source.origin`` values worth naming in the UI: someone other than
#: this window moved the switch. ``dap`` is ClickNick itself, ``worker`` the
#: scan loop reporting its own pause, and Modbus writes never change the mode.
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
    """A change listeners may want to show.

    ``status``: lifecycle; ``frame``: mode/scan/forces/pending writes;
    ``values``: Modbus values; ``modbus``: server info; ``desired``: switch,
    analog or force settings; ``layout``: hardware; ``message``: a line for
    the transcript (``text`` and ``level``); ``echo``: the console command
    equivalent to something the user just did on the panel (``text``).
    """

    kind: EventKind
    text: str = ""
    level: MessageLevel = "output"


LinkSource = Literal["project", "bench"]


@dataclass(frozen=True)
class WiredLink:
    """One feedback link: the program's own (``project``) or a bench change.

    Addresses are CLICK display addresses. A cut bench change has no enable.
    ``active`` says whether the simulation runs it right now; a project link
    stops being active while a bench change replaces or cuts it.
    """

    feedback: str
    enable: str | None
    source: LinkSource
    trigger: int | str | None = None
    on_delay: str | None = None
    off_delay: str | None = None
    profile: str | None = None
    active: bool = False
    pending: bool = False
    enabled: bool = True

    @property
    def cut(self) -> bool:
        return self.enable is None

    @property
    def response(self) -> str:
        """``2s / 500ms`` or the profile token, for labels."""
        if self.profile is not None:
            return self.profile
        return " / ".join(d for d in (self.on_delay or "0ms", self.off_delay) if d)


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
    from pyrung.dap.live import send_command

    return send_command(session_name, command)


def _command_value(value: PlcValue) -> str:
    """*value* as the console types it: ``true``, ``false`` or a number."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _send_link(dap: Any, feedback: str, link: BenchLink) -> None:
    """Send one bench link to the simulation: a cut, or a link with its response."""
    if link.cut:
        dap.unlink(feedback)
        return
    assert link.enable is not None
    dap.link(
        feedback,
        link.enable,
        trigger=link.trigger,
        on_delay=link.on_delay,
        off_delay=link.off_delay,
        profile=link.profile,
    )


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
    ) -> None:
        self._send_command = send_command
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
        self._launch_generation = -1
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
        self._pressed: set[str] = set()
        self._speed = 1.0
        self._desired_position: SwitchPosition = "stop"
        self._forces_baseline: dict[str, PlcValue] | None = None
        self._analog_queued: set[str] = set()
        # Links as the simulation reports them (project + bench). Until the
        # bench links have been re-applied after a launch, a listing only
        # updates the display and never overwrites what the user chose.
        self._link_rows: tuple[WiredLink, ...] | None = None
        self._links_revision_seen: int | None = None
        self._links_synced = False
        self._restored_links = 0

        # Hardware
        self._layout: PanelLayout | None = None
        self._layout_error: str | None = None
        self._layout_key: tuple[float | None, int | None] | None = None

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
        """Echo an analog value once it stops changing (a dragged slider sends many)."""
        self._cancel(self._analog_echo_ids.pop(address, None))

        def echo() -> None:
            self._analog_echo_ids.pop(address, None)
            value = self._state.analog.get(address)
            if value is not None:
                self._echo(f"patch {self.to_tag(address)} {_command_value(value)}")

        self._analog_echo_ids[address] = self._scheduler.after(ECHO_SETTLE_MS, echo)

    def _post(self, callback: Callable[[], None]) -> None:
        """Run *callback* on the UI thread (callable from any thread)."""
        if self._closed:
            return
        try:
            self._scheduler.after(0, callback)
        except Exception:
            pass  # the UI is gone

    def _report_action_error(self, text: str, on_error: Callable[[str], None] | None) -> None:
        self._message(text, "error")
        if on_error is not None:
            on_error(text)

    def _submit(
        self,
        job: Callable[[], None],
        what: str,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Run *job* on the ordered action worker; report a failure as a message."""

        def run() -> None:
            try:
                job()
            except Exception as exc:
                text = f"{what} failed: {exc}"
                self._post(lambda: self._report_action_error(text, on_error))

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
    def error_detail(self) -> str | None:
        return self._error_detail

    @property
    def mode(self) -> str:
        """``"run"`` or ``"stop"``, as the simulated PLC last reported it."""
        return self._dap.mode if self._dap is not None else "stop"

    @property
    def running(self) -> bool:
        """True while scanning continuously (RUN and not paused)."""
        return self._dap is not None and self._dap.running

    @property
    def scan_id(self) -> int | None:
        return self._dap.scan_id if self._dap is not None else None

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def actual_speed(self) -> float | None:
        """Measured speed while free-running, when the simulation reports it."""
        return self._dap.actual_speed if self._dap is not None else None

    @property
    def speed_text(self) -> str:
        """``"1x"``, ``"Max"``, or ``"1x (actual 0.6x)"`` when it cannot keep up."""
        text = format_speed(self._speed)
        actual = self.actual_speed
        if self.running and self._speed > 0 and actual is not None and actual < self._speed * 0.9:
            text += f" (actual {format_speed(actual)})"
        return text

    @property
    def source_text(self) -> str:
        """Who last moved the mode switch, e.g. ``"Moved to STEP by Console: step 10"``."""
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
            return f"Building program analysis...{f' ({seconds}s)' if seconds else ''}"
        if status is SimStatus.STARTING:
            return "Starting..."
        if status is SimStatus.FAILED:
            return "Not available"
        return "Simulation off"

    @property
    def summary_text(self) -> str:
        """A word or two for the main window's Test legend: ``"on :502"``, ``"off"``..."""
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
        """Latest values read over Modbus, keyed by CLICK address."""
        return dict(self._values)

    @property
    def forces(self) -> dict[str, PlcValue]:
        """Active forces by CLICK address (kept in step with the simulation)."""
        return dict(self._state.forces)

    @property
    def pending(self) -> dict[str, PlcValue]:
        """Writes waiting for the next scan, by CLICK address."""
        if self._dap is None:
            return {}
        return {self.to_address(k): v for k, v in self._dap.pending_patches.items()}

    @property
    def tag_hints(self) -> dict[str, dict[str, Any]]:
        """pyrung's per-tag hints (min/max ranges, choices), keyed by CLICK address."""
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
        """True when the simulation's Modbus server is up and accepting clients."""
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
        """Something about restored settings the user should know, until dismissed."""
        return self._notice

    @property
    def restored_forces(self) -> int:
        """Forces restored from the last session, until released or dismissed."""
        return self._restored_forces if self._state.forces else 0

    @property
    def restored_links(self) -> int:
        """Bench links restored from the last session, until discarded or dismissed."""
        return self._restored_links if self._state.links else 0

    @property
    def bench_links(self) -> dict[str, BenchLink]:
        """The bench changes the user chose, by feedback address."""
        return dict(self._state.links)

    @property
    def bench_wiring(self) -> bool:
        """False while every bench change is set aside."""
        return self._state.bench_wiring

    @property
    def links(self) -> tuple[WiredLink, ...]:
        """Every link: as the simulation reports it, or the bench changes alone while it is off."""
        if self._link_rows is not None:
            return self._link_rows
        return tuple(
            WiredLink(
                address,
                link.enable,
                "bench",
                link.trigger,
                link.on_delay,
                link.off_delay,
                link.profile,
                enabled=link.enabled,
            )  # fmt: skip
            for address, link in self._state.links.items()
        )

    def driving_link(self, address: str) -> WiredLink | None:
        """The link driving *address* right now, if any (a cut drives nothing)."""
        for link in self.links:
            if link.feedback == address and link.active and not link.cut:
                return link
        return None

    def project_link(self, address: str) -> WiredLink | None:
        """The program's own link on *address*, active or not."""
        for link in self.links:
            if link.feedback == address and link.source == "project":
                return link
        return None

    @property
    def plc_data_path(self) -> Path | None:
        return self._plc_data_path

    def to_tag(self, address: str) -> str:
        """The running program's tag name for a CLICK *address* (the address if unnamed)."""
        analysis = self._get_analysis()
        normalized = normalize_address(address)
        if analysis is None or normalized is None:
            return address
        tag = analysis.addr_key_to_tag.get(get_addr_key(*parse_address(normalized)))
        return tag or normalized

    def link_countdown(self, address: str) -> int | None:
        """Simulated ms before the link driving *address* flips it, while its delay counts."""
        return self._links_pending.get(address) if self._dap is not None else None

    def to_address(self, key: str) -> str:
        """CLICK address for a pyrung tag name or address (unmapped names pass through)."""
        address = normalize_address(key)
        if address is not None:
            return address
        analysis = self._get_analysis()
        addr_key = analysis.tag_to_addr_key.get(key) if analysis is not None else None
        if addr_key is None:
            return key
        return format_address_display(*parse_addr_key(addr_key))

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

    def _set_notice(self, text: str) -> None:
        self._notice = text
        self._message(text, "progress")
        self._emit("desired")

    def _adopt_snapshot(self, path: Path) -> None:
        try:
            snapshot = self._snapshot_reader(path)
        except (OSError, ValueError) as exc:
            self._message(f"Could not read PLC data {path}: {exc}", "error")
            return
        layout = self._layout
        if layout is not None and (layout.cards or layout.unassigned_inputs):
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
        self._set_notice(f"Loaded PLC data from {path.name}; switches set from snapshot.")

    def _watch_tick(self) -> None:
        self._watch_after_id = None
        if self._closed or not self._enabled:
            return
        self.refresh_layout()
        if self.is_ready and self._plc_data_path is not None:
            mtime = _mtime(self._plc_data_path)
            if mtime is not None and (self._plc_data_mtime is None or mtime > self._plc_data_mtime):
                self._plc_data_mtime = mtime
                self._message("PLC data file changed. Reloading...")
                self._adopt_snapshot(self._plc_data_path)
                self.restart()
        self._watch_after_id = self._scheduler.after(WATCH_MS, self._watch_tick)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True from :meth:`turn_on` until :meth:`turn_off` (even while starting or failed)."""
        return self._enabled

    def turn_on(self) -> None:
        """Start the simulation. It keeps running, with or without windows, until turned off.

        Never called at app launch: a subprocess and a listening Modbus port
        start only when the user asks for them.
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
        """Terminate the simulation and its Modbus client (status unchanged)."""
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

    def _fail_analysis(self, analysis: AnalysisService) -> None:
        guidance = (
            "Open the generated workspace to inspect and edit the source. "
            if analysis.project_dir is not None
            else ""
        )
        self._fail(
            "pyrung could not build this CLICK program for simulation.\n"
            f"{analysis.error or 'Program conversion failed.'}\n"
            f"{guidance}Nickname editing is still available.",
            analysis.error_detail,
        )

    def _wait_for_analysis(self) -> None:
        """Wait for the conversion; every waiting path is bounded here."""
        if self._waited_ms >= ANALYSIS_TIMEOUT_MS:
            self._fail(
                f"timed out after {ANALYSIS_TIMEOUT_MS // 1000}s waiting for "
                "program analysis to finish."
            )
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
            or analysis.generation != self._launch_generation
        ):
            # The launch read files on disk while a rebuild rewrote them, which
            # yields partial imports or a missing run.py. The generation check
            # catches a rebuild that already finished. Wait and relaunch rather
            # than reporting the rubble as a real failure.
            self._wait_for_analysis()
            return
        self._status = SimStatus.FAILED
        self._error = f"the simulation backend failed to start: {exc}"
        self._error_detail = None
        self._message(f"Simulation backend failed to start: {exc}", "error")
        self._emit("status")

    def _update_state(self, **changes: Any) -> None:
        self._state = replace(self._state, **changes)
        self._emit("desired")
        self._schedule_save()

    def _drop_failed_forces(self, failed: list[str]) -> None:
        forces = {a: v for a, v in self._state.forces.items() if a not in failed}
        self._update_state(forces=forces)
        self._message(f"Could not restore forces on {', '.join(failed)}; released them.", "error")

    def _input_patches(self) -> dict[str, PlcValue]:
        patches: dict[str, PlcValue] = {}
        for address, on in self._state.switches.items():
            if address not in self._state.momentary:
                patches[address] = bool(on)
        for address in self._pressed:
            patches[address] = True
        patches.update(self._state.analog)
        return patches

    def _drop_failed_links(self, failed: list[tuple[str, str]]) -> None:
        links = dict(self._state.links)
        for address, _reason in failed:
            links.pop(address, None)
        self._update_state(links=links)
        for address, reason in failed:
            self._message(
                f"Could not restore the bench link on {address}: {reason}. Dropped it.", "error"
            )

    def _wired(self, row: Mapping[str, Any]) -> WiredLink:
        enable = row.get("enable")
        return WiredLink(
            feedback=self.to_address(str(row.get("feedback", ""))),
            enable=None if row.get("cut") or enable is None else self.to_address(str(enable)),
            source="project" if row.get("source") == "project" else "bench",
            trigger=row.get("trigger"),
            on_delay=row.get("onDelay"),
            off_delay=row.get("offDelay"),
            profile=row.get("profile"),
            active=bool(row.get("active")),
            pending=bool(row.get("pending")),
            enabled=row.get("enabled", True) is not False,
        )

    def _on_links(self, token: int, body: Mapping[str, Any], *, sync: bool) -> None:
        """Show the simulation's links; once synced, follow changes made elsewhere (the Console)."""
        if token != self._token or self._dap is None:
            return
        rows = tuple(
            self._wired(row) for row in body.get("links") or () if isinstance(row, Mapping)
        )
        self._link_rows = rows
        if sync:
            self._links_synced = True
            revision = body.get("revision")
            self._links_revision_seen = revision if isinstance(revision, int) else None
        if self._links_synced:
            adopted = {
                row.feedback: BenchLink(
                    row.enable, row.trigger, row.on_delay, row.off_delay, row.profile, row.enabled
                )
                for row in rows
                if row.source == "bench"
            }
            bench = body.get("bench") is not False
            if adopted != dict(self._state.links) or bench != self._state.bench_wiring:
                self._update_state(links=adopted, bench_wiring=bench)
                return
        self._emit("desired")

    # ------------------------------------------------------------------
    # Bench links
    # ------------------------------------------------------------------

    def _fetch_links(self, dap: Any, token: int, *, sync: bool = False) -> None:
        """Read the links back, after any actions already queued (call from any thread)."""

        def job() -> None:
            try:
                body = dict(dap.list_links())
            except Exception:
                return
            self._post(lambda: self._on_links(token, body, sync=sync))

        self._run_serial(job)

    def _reapply(self, dap: Any) -> None:
        """Bring a fresh simulation back to the switches, values, forces and links the user chose."""
        forces = dict(self._state.forces)
        links = dict(self._state.links)
        bench_wiring = self._state.bench_wiring
        position = self._desired_position
        patches = self._input_patches()
        token = self._token

        def job() -> None:
            failed_links: list[tuple[str, str]] = []
            for address, link in links.items():
                try:
                    _send_link(dap, address, link)
                    if not link.enabled:
                        dap.set_links(enabled={address: False})
                except Exception as exc:
                    failed_links.append((address, str(exc)))
            if failed_links:
                self._post(lambda: self._drop_failed_links(failed_links))
            if not bench_wiring:
                dap.set_links(bench=False)
            self._fetch_links(dap, token, sync=True)
            # Launched with keepForcesOnRun, so forces set in STOP survive into RUN.
            failed: list[str] = []
            for address, value in forces.items():
                try:
                    dap.force(address, value)
                except Exception:
                    failed.append(address)
            if failed:
                self._post(lambda: self._drop_failed_forces(failed))
            if position != "stop":
                dap.set_mode("run", patches=patches)
                if position == "run":
                    dap.continue_()

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

    def _on_launched(self, token: int, dap: Any) -> None:
        if token != self._token or self._closed or not self._enabled:
            self._run_background(dap.terminate, "sim-dap-stop")
            return
        self._dap = dap
        self._forces_baseline = None
        self._modbus_info = {}
        # Confirm success in the transcript; a "Retrying..." line should not trail off.
        self._message("OK - simulation ready.", "progress")
        self._set_status(SimStatus.READY)
        self._reapply(dap)
        self._modbus_info_after_id = self._scheduler.after(0, self._poll_modbus_info)

    def _on_dap_died(self, token: int) -> None:
        dap = self._dap
        if token != self._token or dap is None:
            return
        detail = getattr(dap, "stderr_text", "") or None
        self._stop_dap()
        self._status = SimStatus.FAILED
        self._error = "the simulation stopped unexpectedly."
        self._error_detail = detail
        self._message("Simulation stopped unexpectedly.", "error")
        self._emit("status")

    def _adopt_forces(self, actual: dict[str, PlcValue]) -> None:
        """Follow forces changed elsewhere (the Console, `pyrung live`).

        Compares each frame with the previous one, so a fresh simulation's
        first frame only sets the baseline and the session's own requests,
        already reflected in the desired forces, change nothing.
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
        # Anyone can drive (the Console, an agent through `pyrung live`), and
        # the last command wins: mode, pacing and forces follow the frames.
        self._desired_position = self.switch_position
        if dap.speed is not None:
            self._speed = dap.speed
        self._adopt_forces({self.to_address(k): v for k, v in dap.forces.items()})
        self._links_pending = {self.to_address(k): ms for k, ms in dap.links_pending.items()}
        revision = dap.links_revision
        if revision != self._links_revision_seen and self._links_synced:
            self._links_revision_seen = revision
            self._fetch_links(dap, token)
        self._emit("frame")

    # ------------------------------------------------------------------
    # Frames from the simulation
    # ------------------------------------------------------------------

    def _on_frame_bg(self, token: int) -> None:
        # Frames can arrive every scan; collapse them into one UI update.
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
        if analysis is None:
            self._fail(
                "program analysis has not started. Connect to a Click project, "
                "then save it in Click Software."
            )
            return
        # A build rewrites the generated project in place, so while one is
        # running the folder on disk is rubble regardless of what the previous
        # result still advertises. Wait it out before touching any of it.
        if analysis.status is AnalysisStatus.BUILDING:
            self._wait_for_analysis()
            return
        # A cached graph may still serve open editors, but simulation must use
        # a successful conversion of the current CLICK program.
        if analysis.status is AnalysisStatus.FAILED:
            self._fail_analysis(analysis)
            return
        if not analysis.is_available:
            self._wait_for_analysis()
            return

        project_dir = analysis.project_dir
        if project_dir is None:
            self._fail(
                "no pyrung project folder was generated. "
                "Save the project in Click Software, then retry."
            )
            return
        # A rebuild empties this folder before regenerating it, so the
        # directory can exist with run.py not yet written.
        if not (project_dir / "run.py").is_file():
            self._fail(
                f"the generated project at {project_dir} has no run.py. "
                "Save the project in Click Software, then retry."
            )
            return

        # Remembered so a failure can tell "the project was rewritten under the
        # launch" from "this project genuinely does not run".
        self._launch_generation = analysis.generation
        self._token += 1
        token = self._token
        self._set_status(SimStatus.STARTING)
        self.refresh_layout(force=True)

        snapshot_path = self._plc_data_path
        modbus = {"host": MODBUS_HOST, "port": self._state.modbus_port}
        speed = self._speed

        def launch() -> None:
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
            self._post(lambda: self._on_launched(token, dap))

        self._run_background(launch, "sim-dap-launch")

    def retry(self) -> None:
        """Rebuild the analysis (if possible) and launch again."""
        self._waited_ms = 0
        self._message("Retrying...", "progress")
        if self._on_retry_analysis is not None:
            try:
                self._on_retry_analysis()
            except Exception as exc:
                self._message(f"Retry failed: {exc}", "error")
        if self._enabled:
            self.start()
        else:
            self.turn_on()

    def restart(self) -> None:
        """Relaunch if the simulation is on (e.g. the workspace or PLC data changed)."""
        if self._enabled and not self._closed:
            self._waited_ms = 0
            self.start()

    def close(self) -> None:
        """Stop everything and save. The session is unusable afterwards."""
        self._enabled = False
        self._shutdown()
        self._closed = True
        self._worker.close()
        self._listeners.clear()

    def set_plc_data_path(self, path: Path) -> None:
        """Start the simulation from a CLICK data dump, relaunching now and when it changes.

        The dump wins for inputs: switch positions and analog values take its
        values (forces stay).
        """
        self._plc_data_path = path
        self._plc_data_mtime = _mtime(path)
        self._message(f"Loading PLC data: {path}")
        self._adopt_snapshot(path)
        self.restart()

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
        """Patch inputs over DAP (X is read-only over Modbus, as on a real CLICK)."""
        dap = self._dap
        if dap is None:
            return  # applied when the simulation (re)starts or enters RUN
        self._submit(lambda: dap.patch(values), what)

    def set_modbus_port(self, port: int) -> None:
        """Move the simulation's Modbus server to *port* (relaunches)."""
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        if port == self._state.modbus_port:
            return
        self._update_state(modbus_port=port)
        self.restart()

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
        """Where the user put the switch (not necessarily what the PLC has seen yet)."""
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
        """Set an analog input's DF value. Rapid changes (a dragged slider) coalesce."""
        analog = dict(self._state.analog)
        analog[address] = float(value)
        self._update_state(analog=analog)
        self._echo_settled(address)
        if self._dap is None or address in self._analog_queued:
            return
        self._analog_queued.add(address)
        dap = self._dap

        def job() -> None:
            # Runs on the worker: read the newest value, not the one queued.
            self._analog_queued.discard(address)
            dap.patch({address: self._state.analog.get(address, float(value))})

        self._submit(job, f"Writing {address}")

    # ------------------------------------------------------------------
    # Forces
    # ------------------------------------------------------------------

    def force(
        self, address: str, value: PlcValue, *, on_error: Callable[[str], None] | None = None
    ) -> None:
        """Override *address* until released; the program cannot change it."""
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
        job: Callable[[Any], object],
        what: str,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Record the bench links the user chose, then send *job* to the simulation."""
        previous = dict(self._state.links)
        self._update_state(links=links)
        dap = self._dap
        if dap is None:
            return  # applied when the simulation (re)starts

        def undo(text: str) -> None:
            self._update_state(links=previous)
            if on_error is not None:
                on_error(text)

        self._submit(lambda: job(dap), what, undo)

    def _link_command(self, feedback: str, link: BenchLink) -> str:
        """The console command that makes *link*: ``link X002 Y001 on_delay=2s``."""
        from .services.link_annotation import link_text

        fb = self.to_tag(feedback)
        if link.cut:
            return f"unlink {fb}"
        assert link.enable is not None
        keys = [
            f"{key}={value}"
            for key, value in (
                ("on_delay", link.on_delay),
                ("off_delay", link.off_delay),
                ("profile", link.profile),
            )
            if value
        ]
        return " ".join(["link", fb, link_text(self.to_tag(link.enable), link), *keys])

    def link(
        self, feedback: str, link: BenchLink, *, on_error: Callable[[str], None] | None = None
    ) -> None:
        """Wire *feedback* on the bench (a cut when ``link.enable`` is None)."""
        link = replace(link, enabled=True)
        links = dict(self._state.links)
        links[feedback] = link
        verb = "Cutting the link on" if link.cut else "Linking"
        self._change_links(
            links, lambda dap: _send_link(dap, feedback, link), f"{verb} {feedback}", on_error
        )
        self._echo(self._link_command(feedback, link))

    def cut_link(self, feedback: str, *, on_error: Callable[[str], None] | None = None) -> None:
        """Cut the program's link on *feedback*, as if the sensor failed."""
        self.link(feedback, BenchLink(None), on_error=on_error)

    def restore_link(self, feedback: str) -> None:
        """Drop the bench change on *feedback*: back to what the program declares."""
        if feedback not in self._state.links:
            return
        links = dict(self._state.links)
        links.pop(feedback)
        self._change_links(
            links, lambda dap: dap.restore_link(feedback), f"Restoring the link on {feedback}"
        )
        self._echo(f"restore {self.to_tag(feedback)}")

    def set_link_enabled(self, feedback: str, enabled: bool) -> None:
        """Set one bench change aside (or back) without forgetting it."""
        link = self._state.links.get(feedback)
        if link is None or link.enabled == enabled:
            return
        links = dict(self._state.links)
        links[feedback] = replace(link, enabled=enabled)
        self._change_links(
            links,
            lambda dap: dap.set_links(enabled={feedback: enabled}),
            f"{'Enabling' if enabled else 'Disabling'} the bench link on {feedback}",
        )
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
        addresses = list(self._state.links)

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
        """Where the CPU's mode switch sits, derived from the latest frame.

        STOP: mode stop. STEP: mode run, not scanning on its own (scans only
        advance on Step, the Console or an agent). RUN: mode run, free-running.
        """
        if self.mode != "run":
            return "stop"
        return "run" if self.running else "step"

    def set_switch_position(self, position: SwitchPosition) -> None:
        """Move the CPU's mode switch.

        Leaving STOP enters RUN mode with the user's switches, analog values
        and forces in place for scan 1; STEP then waits before that scan.
        """
        dap = self._dap
        if dap is None:
            return
        current = self.switch_position
        if position == current:
            return
        if not self._state.run_hint_seen:
            self._update_state(run_hint_seen=True)
        self._desired_position = position
        if position == "stop":
            self._submit(lambda: dap.set_mode("stop"), "Switching to STOP")
            self._echo("mode stop")
            return
        if current == "stop":
            # Forces are already in place (keepForcesOnRun); the switch and
            # analog values go with the transition so scan 1 sees them.
            patches = self._input_patches()

            def enter_run() -> None:
                dap.set_mode("run", patches=patches)
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
        """Advance *count* scans (as fast as possible), then wait."""
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
            tag_to_key[tag] for tag in analysis.known_tag_names() if tag in tag_to_key
        )

    def _apply_restore(self, layout: PanelLayout) -> None:
        self._restore_pending = False
        result: RestoreResult = restore_state(
            self._state,
            inputs=layout.addresses("input"),
            analog_inputs=layout.addresses("analog_in"),
            modules=layout.modules,
        )
        changed = result.state != self._state
        self._state = result.state
        if result.dropped:
            lead = (
                "The hardware changed since the last session. " if result.hardware_changed else ""
            )
            self._set_notice(
                f"{lead}Settings for {', '.join(result.dropped)} no longer match an "
                "installed input and were dropped."
            )
        if changed:
            self._emit("desired")
            self._schedule_save()

    def refresh_layout(self, *, force: bool = False) -> None:
        """Re-read the hardware when Project.ini or the program changed."""
        path = self._get_project_ini()
        analysis = self._get_analysis()
        generation = analysis.generation if analysis is not None else None
        key = (_mtime(path), generation)
        if not force and key == self._layout_key:
            return
        self._layout_key = key
        used = self._used_io()
        if path is None or key[0] is None:
            layout = build_panel_layout((), used)
            error = "CLICK's Project.ini was not found; save the project in CLICK."
        else:
            try:
                layout = self._layout_reader(path, used)
                error = None
            except Exception as exc:
                layout = build_panel_layout((), used)
                error = f"Could not read the hardware configuration: {exc}"
        changed = layout != self._layout or error != self._layout_error
        self._layout = layout
        self._layout_error = error
        if self._restore_pending and error is None and layout.has_cpu:
            self._apply_restore(layout)
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
        # Otherwise the file moved with the settings already in memory.
        if first_load or state_file.notice is not None:
            try:
                loaded = load_state(state_file.path)
            except (OSError, ValueError) as exc:
                self._message(f"Simulator settings could not be read: {exc}", "error")
                loaded = SimulatorState()
            self._state = loaded
            self._restore_pending = True
            self._restored_forces = len(loaded.forces)
            self._restored_links = len(loaded.links)
            if self._layout is not None and self._layout_error is None and self._layout.has_cpu:
                self._apply_restore(self._layout)
            self._emit("desired")
        if state_file.notice:
            self._set_notice(state_file.notice)

    @property
    def state_path(self) -> Path | None:
        return self._state_path
