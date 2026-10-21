"""DAP subprocess service for pyrung simulation.

Manages a pyrung DAP adapter subprocess, handles the DAP wire protocol
(Content-Length framing over stdin/stdout), correlates requests to responses,
and dispatches events (pyrungScanFrame, stopped, etc.) via callbacks.
"""

from __future__ import annotations

import enum
import json
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .project_workspace import project_environment


class DapRequestError(RuntimeError):
    """The adapter refused a request, or never answered it."""


class SimState(enum.Enum):
    IDLE = "idle"
    LAUNCHING = "launching"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


PlcValue = bool | int | float | str

TagValues = dict[str, Any]
TagChange = dict[str, str]


def _coerce_string(value: str, tag_type: str) -> PlcValue:
    """Convert a DAP string value to its native Python type.

    *tag_type* is a pyrung ``TagType`` value: ``bool``, ``int``, ``dint``,
    ``real``, ``word`` or ``char``.
    """
    if tag_type == "bool":
        return value.lower() in ("true", "1")
    if tag_type in ("int", "dint", "word"):
        try:
            return int(value)
        except ValueError:
            return value
    if tag_type == "real":
        try:
            return float(value)
        except ValueError:
            return value
    return value


class DapService:
    """Manages a pyrung DAP subprocess and provides a high-level API.

    All public methods are thread-safe.  Callbacks are invoked on the
    background reader thread -- callers must marshal to the UI thread
    themselves (typically via ``root.after(0, cb)``).
    """

    def __init__(
        self,
        *,
        on_state: Callable[[SimState, Exception | None], None] | None = None,
        on_tags: Callable[[TagValues], None] | None = None,
        on_changes: Callable[[list[TagChange]], None] | None = None,
        on_scan: Callable[[int | None], None] | None = None,
        on_frame: Callable[[], None] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        self._on_state = on_state
        self._on_tags = on_tags
        self._on_changes = on_changes
        self._on_scan = on_scan
        self._on_frame = on_frame
        self._on_output = on_output

        self._proc: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict[str, Any]] = {}
        self._state = SimState.IDLE

        self._tag_types: dict[str, str] = {}
        self._tag_hints: dict[str, dict[str, Any]] = {}
        self._tag_groups: dict[str, list[str]] = {}
        self._tag_values: TagValues = {}
        self._scan_id: int | None = None

        # Execution state reported by pyrungScanFrame (see the simulator contract).
        self._mode: str = "stop"
        self._running = False
        self._speed: float | None = None
        self._actual_speed: float | None = None
        self._source: dict[str, str] = {}
        self._forces: dict[str, PlcValue] = {}
        self._pending_patches: dict[str, PlcValue] = {}
        self._links_revision = 0

    @property
    def state(self) -> SimState:
        return self._state

    @property
    def scan_id(self) -> int | None:
        """Scan id of the most recent scan frame / stop event."""
        return self._scan_id

    @property
    def tag_types(self) -> dict[str, str]:
        return dict(self._tag_types)

    @property
    def known_tags(self) -> frozenset[str]:
        """All pyrung tag names seen so far (populated after first scan)."""
        return frozenset(self._tag_types.keys())

    @property
    def tag_hints(self) -> dict[str, dict[str, Any]]:
        return dict(self._tag_hints)

    @property
    def tag_groups(self) -> dict[str, list[str]]:
        return dict(self._tag_groups)

    @property
    def tag_values(self) -> TagValues:
        return dict(self._tag_values)

    @property
    def mode(self) -> str:
        """PLC mode from the latest frame: ``"run"`` or ``"stop"``."""
        return self._mode

    @property
    def running(self) -> bool:
        """True while the executor is continuously scanning."""
        return self._running

    @property
    def speed(self) -> float | None:
        """Pacing from the latest frame (0 = as fast as possible); None before one."""
        return self._speed

    @property
    def actual_speed(self) -> float | None:
        """How fast the simulation really ran, as a multiple of wall time."""
        return self._actual_speed

    @property
    def source(self) -> dict[str, str]:
        """Who caused the latest frame: ``{"origin": "live"|"dap"|..., "command": ...}``."""
        return dict(self._source)

    @property
    def forces(self) -> dict[str, PlcValue]:
        """Every active force from the latest frame, keyed as pyrung reports them."""
        return dict(self._forces)

    @property
    def pending_patches(self) -> dict[str, PlcValue]:
        """Writes waiting for the next scan, keyed as pyrung reports them."""
        return dict(self._pending_patches)

    @property
    def links_revision(self) -> int:
        """Changes whenever the feedback wiring does (bench links, reloads)."""
        return self._links_revision

    @property
    def stderr_text(self) -> str:
        """Everything the adapter has written to stderr so far."""
        with self._lock:
            return "\n".join(self._stderr_lines)

    # ------------------------------------------------------------------
    # DAP wire protocol
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def _write_message(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        try:
            proc.stdin.write(header)
            proc.stdin.write(payload)
            proc.stdin.flush()
        except OSError:
            pass

    def _read_message(self) -> dict[str, Any] | None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return None
        headers: dict[str, str] = {}
        while True:
            line = proc.stdout.readline()
            if line == b"":
                return None
            if line in (b"\r\n", b"\n"):
                break
            if b":" not in line:
                continue
            key, value = line.split(b":", 1)
            headers[key.decode("ascii").strip().lower()] = value.decode("ascii").strip()

        raw_length = headers.get("content-length")
        if raw_length is None:
            return None
        length = int(raw_length)
        payload = proc.stdout.read(length)
        if len(payload) != length:
            return None
        return json.loads(payload.decode("utf-8"))

    # ------------------------------------------------------------------
    # Request / response helpers
    # ------------------------------------------------------------------

    def _send_request(self, command: str, arguments: dict[str, Any] | None = None) -> int:
        seq = self._next_seq()
        msg: dict[str, Any] = {
            "seq": seq,
            "type": "request",
            "command": command,
        }
        if arguments:
            msg["arguments"] = arguments
        event = threading.Event()
        with self._lock:
            self._pending[seq] = event
        self._write_message(msg)
        return seq

    def _wait_response(self, seq: int, timeout: float = 10.0) -> dict[str, Any] | None:
        event = self._pending.get(seq)
        if event is None:
            return None
        if not event.wait(timeout):
            with self._lock:
                self._pending.pop(seq, None)
            return None
        with self._lock:
            self._pending.pop(seq, None)
            return self._responses.pop(seq, None)

    def _send_and_wait(
        self, command: str, arguments: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> dict[str, Any] | None:
        seq = self._send_request(command, arguments)
        return self._wait_response(seq, timeout)

    def _request(
        self, command: str, arguments: dict[str, Any] | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        """Send a request and return its body, raising DapRequestError on failure."""
        if self._proc is None:
            raise DapRequestError(f"{command}: simulation is not running")
        resp = self._send_and_wait(command, arguments, timeout)
        if resp is None:
            raise DapRequestError(f"{command}: no response from simulation")
        if not resp.get("success"):
            raise DapRequestError(resp.get("message") or f"{command} failed")
        return resp.get("body") or {}

    def _handle_response(self, msg: dict[str, Any]) -> None:
        request_seq = msg.get("request_seq")
        if request_seq is not None:
            with self._lock:
                self._responses[request_seq] = msg
                event = self._pending.get(request_seq)
            if event is not None:
                event.set()

    def _cache_tag_metadata(self, trace: dict[str, Any]) -> None:
        tag_types = trace.get("tagTypes")
        if tag_types:
            self._tag_types = tag_types
        tag_hints = trace.get("tagHints")
        if tag_hints:
            self._tag_hints = tag_hints
        tag_groups = trace.get("tagGroups")
        if tag_groups:
            self._tag_groups = tag_groups

    def _coerce_tag_values(self, tag_values: Mapping[str, Any]) -> TagValues:
        """Coerce string values to native types using cached tagTypes."""
        coerced: TagValues = {}
        for tag, value in tag_values.items():
            tag_type = self._tag_types.get(tag, "")
            if isinstance(value, str):
                coerced[tag] = _coerce_string(value, tag_type)
            else:
                coerced[tag] = value
        return coerced

    def _cache_execution_state(self, body: dict[str, Any], trace: dict[str, Any]) -> None:
        mode = body.get("mode")
        if mode in ("run", "stop"):
            self._mode = mode
        running = body.get("running")
        if running is not None:
            self._running = bool(running)
        speed = body.get("speed")
        if isinstance(speed, int | float) and not isinstance(speed, bool):
            self._speed = float(speed)
        actual = body.get("actualSpeed")
        self._actual_speed = (
            float(actual)
            if isinstance(actual, int | float) and not isinstance(actual, bool)
            else None
        )
        source = body.get("source")
        if isinstance(source, Mapping):
            self._source = {
                "origin": str(source.get("origin") or ""),
                "command": str(source.get("command") or ""),
            }
        elif isinstance(source, str):
            self._source = {"origin": source, "command": ""}
        else:
            self._source = {}
        pending = body.get("pendingPatches")
        if isinstance(pending, Mapping):
            self._pending_patches = self._coerce_tag_values(pending)
        forces = trace.get("forces")
        if isinstance(forces, Mapping):
            self._forces = self._coerce_tag_values(forces)
        revision = body.get("linksRevision")
        if isinstance(revision, int) and not isinstance(revision, bool):
            self._links_revision = revision

    def _handle_scan_frame(self, body: dict[str, Any]) -> None:
        trace = body.get("trace") or {}
        self._cache_tag_metadata(trace)
        # Cache the scan id before on_tags fires so a listener handling the
        # values can pair them with the correct scan.
        self._scan_id = body.get("scanId")
        self._cache_execution_state(body, trace)

        tag_values = trace.get("tagValues")
        if tag_values is not None:
            tag_values = self._coerce_tag_values(tag_values)
            self._tag_values = tag_values
            if self._on_tags:
                self._on_tags(dict(tag_values))

        if self._on_scan:
            self._on_scan(self._scan_id)

        changes = body.get("changes", [])
        if changes and self._on_changes:
            self._on_changes(changes)

        if self._on_frame:
            self._on_frame()

    def _extract_tag_data_from_trace(self, body: dict[str, Any]) -> None:
        trace = body.get("trace") or body
        self._cache_tag_metadata(trace)
        tag_values = trace.get("tagValues")
        if tag_values:
            tag_values = self._coerce_tag_values(tag_values)
            self._tag_values = tag_values
            if self._on_tags:
                self._on_tags(dict(tag_values))

    def _set_state(self, state: SimState, error: Exception | None = None) -> None:
        self._state = state
        if self._on_state:
            self._on_state(state, error)

    def _handle_event(self, msg: dict[str, Any]) -> None:
        event_name = msg.get("event", "")
        body = msg.get("body", {})

        if event_name == "stopped":
            reason = body.get("reason", "")
            if reason == "entry":
                self._set_state(SimState.STOPPED)
            elif reason == "pause":
                self._set_state(SimState.PAUSED)
            else:
                self._set_state(SimState.PAUSED)
            # A step or pause reports the scan it landed on; cache it before
            # the trace fires on_tags so listeners pair values with this scan.
            scan_id = body.get("scanId")
            if scan_id is not None:
                self._scan_id = scan_id
            self._extract_tag_data_from_trace(body)
            if scan_id is not None and self._on_scan:
                self._on_scan(scan_id)

        elif event_name == "pyrungScanFrame":
            self._handle_scan_frame(body)

        elif event_name == "output":
            text = body.get("output")
            if text and self._on_output:
                self._on_output(str(text))

        elif event_name == "terminated":
            self._set_state(SimState.IDLE)

    # ------------------------------------------------------------------
    # Reader thread
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        while True:
            msg = self._read_message()
            if msg is None:
                self._set_state(SimState.ERROR, None)
                break
            msg_type = msg.get("type")
            if msg_type == "response":
                self._handle_response(msg)
            elif msg_type == "event":
                self._handle_event(msg)

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for raw_line in proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                with self._lock:
                    self._stderr_lines.append(line)

    def _drain_stderr(self) -> str:
        with self._lock:
            lines = self._stderr_lines.copy()
            self._stderr_lines.clear()
        return "\n".join(lines)

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
        with self._lock:
            for event in self._pending.values():
                event.set()
            self._pending.clear()
            self._responses.clear()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def launch(
        self,
        project_dir: Path,
        *,
        snapshot_path: Path | None = None,
        session_name: str = "clicknick",
        modbus: Mapping[str, Any] | None = None,
        speed: float | None = None,
        start_mode: str | None = None,
        keep_forces_on_run: bool | None = None,
    ) -> None:
        """Start the DAP subprocess and launch the pyrung project.

        *project_dir* must contain a ``run.py`` generated by
        ``ladder_to_pyrung_project()``. *modbus* (``{"host", "port"}``)
        starts a Modbus TCP server inside the session; *speed* paces scanning against wall time (0 = unpaced); *start_mode*
        is ``"stop"`` or ``"run"``; *keep_forces_on_run* keeps forces through
        the STOP -> RUN transition instead of clearing them.
        """
        if self._proc is not None:
            self.terminate()

        run_py = project_dir / "run.py"
        if not run_py.is_file():
            raise FileNotFoundError(f"No run.py found in {project_dir}")

        self._set_state(SimState.LAUNCHING)

        self._proc = subprocess.Popen(
            [sys.executable, "-m", "pyrung.dap"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(project_dir),
            env=project_environment(project_dir),
        )

        self._stderr_lines.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="dap-reader"
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop, daemon=True, name="dap-stderr"
        )
        self._reader_thread.start()
        self._stderr_thread.start()

        resp = self._send_and_wait("initialize")
        if resp is None or not resp.get("success"):
            stderr = self._drain_stderr()
            self._kill()
            raise RuntimeError(
                f"DAP initialize failed\n{stderr}" if stderr else "DAP initialize failed"
            )

        launch_args: dict[str, object] = {
            "program": str(run_py),
            "autoReload": True,
            "session": session_name,
        }
        if snapshot_path is not None:
            launch_args["snapshotPath"] = str(snapshot_path)
        if modbus is not None:
            launch_args["modbus"] = dict(modbus)
        if speed is not None:
            launch_args["speed"] = float(speed)
        if start_mode is not None:
            launch_args["startMode"] = start_mode
        if keep_forces_on_run is not None:
            launch_args["keepForcesOnRun"] = keep_forces_on_run
        resp = self._send_and_wait("launch", launch_args, timeout=60.0)
        if resp is None or not resp.get("success"):
            error_msg = (resp or {}).get("message") or str(resp)
            stderr = self._drain_stderr()
            self._kill()
            detail = f"{error_msg}\n{stderr}" if stderr else error_msg
            raise RuntimeError(f"DAP launch failed: {detail}")

        self._send_and_wait("configurationDone")

    def terminate(self) -> None:
        """Shut down the DAP subprocess."""
        if self._proc is None:
            return
        try:
            self._send_request("disconnect")
        except OSError:
            pass
        self._kill()
        self._set_state(SimState.IDLE)

    # ------------------------------------------------------------------
    # Execution control
    # ------------------------------------------------------------------

    def continue_(self) -> None:
        """Start or resume continuous scanning."""
        self._send_request("continue", {"threadId": 1})
        self._set_state(SimState.RUNNING)

    def pause(self) -> None:
        """Pause continuous scanning."""
        self._send_request("pause", {"threadId": 1})

    def step_scan(self) -> None:
        """Advance one full scan cycle."""
        self._send_request("pyrungStepScan")

    def set_mode(
        self,
        mode: str,
        patches: Mapping[str, PlcValue] | None = None,
        forces: Mapping[str, PlcValue] | None = None,
    ) -> dict[str, Any]:
        """Switch the PLC between ``"run"`` and ``"stop"``.

        Entering RUN resets non-retentive memory without scanning, then
        applies *forces* and *patches*, so the first scan sees them. The
        executor stays paused; call :meth:`continue_` or :meth:`step_scan`.
        """
        arguments: dict[str, Any] = {"mode": mode}
        if patches:
            arguments["patches"] = dict(patches)
        if forces:
            arguments["forces"] = dict(forces)
        return self._request("pyrungSetMode", arguments)

    def set_speed(self, speed: float) -> dict[str, Any]:
        """Pace scanning to *speed* x wall time (0 = as fast as possible)."""
        return self._request("pyrungSetSpeed", {"speed": float(speed)})

    def modbus_info(self) -> dict[str, Any]:
        """Report the session's Modbus server.

        ``{running, host, port, clients, error}``.
        """
        return self._request("pyrungModbusInfo", timeout=3.0)

    # ------------------------------------------------------------------
    # Force / patch
    # ------------------------------------------------------------------

    def force(self, tag: str, value: PlcValue) -> dict[str, Any]:
        """Force a tag (or CLICK address) to a fixed value."""
        return self._request("pyrungForce", {"tag": tag, "value": value})

    def patch(self, patches: Mapping[str, PlcValue]) -> dict[str, Any]:
        """Apply one-scan patches to one or more tags (or CLICK addresses).

        Unlike :meth:`force`, a patch is not sticky -- the next scan's logic
        may overwrite the value.
        """
        if not patches:
            return {}
        return self._request("pyrungPatch", {"patches": dict(patches)})

    def unforce(self, tag: str) -> dict[str, Any]:
        """Remove a force from a tag (or CLICK address)."""
        return self._request("pyrungUnforce", {"tag": tag})

    def clear_forces(self) -> dict[str, Any]:
        """Remove all active forces."""
        return self._request("pyrungClearForces")

    def list_forces(self) -> dict[str, PlcValue]:
        """Return the current set of forced tags."""
        resp = self._send_and_wait("pyrungListForces")
        if resp and resp.get("success"):
            return (resp.get("body") or {}).get("forces", {})
        return {}

    # ------------------------------------------------------------------
    # Bench links
    # ------------------------------------------------------------------

    def link(
        self,
        feedback: str,
        enable: str,
        *,
        trigger: int | str | None = None,
        on_delay: str | None = None,
        off_delay: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Add or replace the bench link on *feedback* (tags or CLICK addresses).

        Returns ``{text, command}``; *command* is the equivalent console line.
        """
        arguments: dict[str, Any] = {"feedback": feedback, "enable": enable}
        for key, value in (
            ("trigger", trigger),
            ("onDelay", on_delay),
            ("offDelay", off_delay),
            ("profile", profile),
        ):
            if value is not None:
                arguments[key] = value
        return self._request("pyrungLink", arguments)

    def unlink(self, feedback: str) -> dict[str, Any]:
        """Cut the program's link on *feedback*, or remove its bench-only link."""
        return self._request("pyrungUnlink", {"feedback": feedback})

    def restore_link(self, feedback: str) -> dict[str, Any]:
        """Drop the bench change on *feedback*: back to what the program declares."""
        return self._request("pyrungRestoreLink", {"feedback": feedback})

    def set_links(
        self, *, bench: bool | None = None, enabled: Mapping[str, bool] | None = None
    ) -> dict[str, Any]:
        """Turn all bench changes on or off, or set individual ones aside."""
        arguments: dict[str, Any] = {}
        if bench is not None:
            arguments["bench"] = bench
        if enabled:
            arguments["enabled"] = dict(enabled)
        return self._request("pyrungSetLinks", arguments)

    def list_links(self) -> dict[str, Any]:
        """``{bench, revision, links: [...]}``: program links and bench changes."""
        return self._request("pyrungListLinks")

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload(self) -> dict[str, Any] | None:
        """Hot-reload the program file, preserving PLC state and forces."""
        return self._send_and_wait("evaluate", {"expression": "reload", "context": "repl"})

    # ------------------------------------------------------------------
    # Causal analysis
    # ------------------------------------------------------------------

    def cause(self, tag: str, *, scan: int | None = None, to: Any = None) -> dict[str, Any] | None:
        """Query a causal chain for *tag*.

        Returns the response body dict or None on failure.
        """
        query = f"cause:{tag}"
        if scan is not None:
            query = f"cause:{tag}@{scan}"
        elif to is not None:
            query = f"cause:{tag}:{to}"
        resp = self._send_and_wait("pyrungCausal", {"query": query})
        if resp and resp.get("success"):
            return resp.get("body")
        return None

    # ------------------------------------------------------------------
    # Tag queries via LiveServer console
    # ------------------------------------------------------------------

    def read_tags(self) -> TagValues:
        """Return the latest cached tag values."""
        return dict(self._tag_values)
