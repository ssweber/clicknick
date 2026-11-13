"""SimulationSession: lifecycle, the mode switch, forces, Modbus I/O and persistence.

Everything runs inline: a fake scheduler stands in for Tk, a fake DapService
for the pyrung subprocess and a fake ModbusService for the Modbus client.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pyclickplc.addresses import format_address_display, normalize_address, parse_addr_key
from pyrung.core import PHYSICAL_KEYS

from clicknick.data.data_source import CsvDataSource
from clicknick.models.address_row import AddressRow
from clicknick.services.analysis_service import AnalysisResult, AnalysisService, AnalysisStatus
from clicknick.services.dap_service import DapRequestError
from clicknick.services.physical_response import response
from clicknick.services.sim_hardware import build_panel_layout
from clicknick.services.sim_state import BenchLink, SimulatorState, load_state, save_state
from clicknick.simulation_session import (
    ANALYSIS_POLL_MS,
    ANALYSIS_TIMEOUT_MS,
    MODBUS_INFO_MS,
    SAVE_DELAY_MS,
    SimStatus,
    SimulationSession,
)


class FakeScheduler:
    """Runs zero-delay callbacks on demand; keeps timed ones until fired."""

    def __init__(self) -> None:
        self._next = 0
        self.jobs: dict[int, tuple[int, object]] = {}

    def after(self, ms, func):
        self._next += 1
        self.jobs[self._next] = (ms, func)
        return self._next

    def after_cancel(self, job_id):
        self.jobs.pop(job_id, None)

    def run_ready(self) -> None:
        while True:
            ready = [(job_id, f) for job_id, (ms, f) in self.jobs.items() if ms == 0]
            if not ready:
                return
            for job_id, func in ready:
                self.jobs.pop(job_id, None)
                func()

    def fire(self, ms: int) -> None:
        """Run every job scheduled with delay *ms*."""
        for job_id, (delay, func) in list(self.jobs.items()):
            if delay == ms:
                self.jobs.pop(job_id, None)
                func()
        self.run_ready()

    def has(self, ms: int) -> bool:
        return any(delay == ms for delay, _f in self.jobs.values())


def _dap_fields(values):
    """A response as pyrungListLinks sends it: every key's request field, unset ones empty."""
    return {
        key.dap_field: values.get(name, False if key.is_flag else None)
        for name, key in PHYSICAL_KEYS.items()
    }


class FakeDap:
    """A small model of pyrung's adapter.

    Like pyrung, it keys forces and bench links by tag name: an address is
    resolved with the names of the program it runs (*program_names*, read at
    launch and at each reload), and a planned reload places each entry as its
    plan says and carries the rest over by name.
    """

    def __init__(self, **callbacks) -> None:
        self.callbacks = callbacks
        self.program_names = dict  # () -> {address: tag}: what the workspace on disk names
        self.names: dict[str, str] = {}
        self.calls: list[tuple] = []
        self.launch_error: Exception | None = None
        self.launch_hook = None
        self.mode = "stop"
        self.running = False
        self.speed: float | None = 1.0
        self.actual_speed: float | None = None
        self.source: dict[str, str] = {}
        self.forces: dict = {}
        self.pending_patches: dict = {}
        self.scan_id: int | None = 0
        self.known_tags = frozenset()
        self.tag_hints: dict = {}
        self.stderr_text = ""
        self.state = "running"
        self.info = {"running": True, "host": "127.0.0.1", "port": 502, "clients": 1, "error": None}
        self.links_revision = 0
        self.links_pending: dict[str, int] = {}
        self.project: dict[str, str] = {}  # program links: feedback -> enable
        self.bench: dict[str, dict] = {}
        self.bench_on = True
        self.refuse_links: dict[str, str] = {}
        self.reload_error: Exception | None = None
        self.plans: list[dict] = []  # each pyrungReload's plan
        self.reload_drops: dict[str, tuple[str, str]] = {}  # tag -> (reason, detail)

    def _tag(self, tag):
        """The name pyrung keys *tag* by: an address goes by the running program's name."""
        address = normalize_address(tag) if isinstance(tag, str) else None
        return tag if address is None else self.names.get(address, address)

    def launch(self, project_dir, **kwargs):
        self.calls.append(("launch", project_dir, kwargs))
        self.names = dict(self.program_names())
        if self.launch_hook is not None:
            self.launch_hook()
        if self.launch_error is not None:
            raise self.launch_error

    def terminate(self):
        self.calls.append(("terminate",))

    def planned_reload(self, plan):
        """pyrungReload: each entry goes where *plan* says; one it leaves out keeps its name."""
        self.calls.append(("reload",))
        self.plans.append(plan)
        if self.reload_error is not None:
            raise self.reload_error  # a failed reload changes nothing
        carried: list[dict] = []

        def report(tag, kind, to, *, planned, **fields):
            reason = self.reload_drops.get(tag)
            entry = {
                "tag": tag,
                "kind": kind,
                "to": None if reason else to,
                "planned": planned,
                "released": to is None and not reason,
                "dropped": bool(reason),
                **fields,
            }
            if reason:
                entry["reason"], entry["detail"] = reason
            carried.append(entry)
            return entry["to"]  # fmt: skip

        forces, planned_forces = {}, plan.get("forces") or {}
        for tag, value in self.forces.items():
            to = report(tag, "force", planned_forces.get(tag, tag),
                        planned=tag in planned_forces, value=value)  # fmt: skip
            if to is not None:
                forces[to] = value
        bench, planned_links = {}, plan.get("links") or {}
        for fb, entry in self.bench.items():
            target = planned_links.get(fb, {"fb": fb, "en": entry["enable"]})
            kind = "cut" if entry["enable"] is None else "link"
            to = None if target is None else target["fb"]
            enable = None if target is None else target.get("en")
            to = report(fb, kind, to, planned=fb in planned_links, feedback=fb,
                        enable=enable if to else None, enabled=entry["enabled"])  # fmt: skip
            if to is not None:
                bench[to] = {**entry, "enable": enable}
        for fb, to in (plan.get("declared") or {}).items():
            report(fb, "declared", to, planned=True, feedback=fb, enable=self.project.get(fb))
        self.forces, self.bench = forces, bench
        self.names = dict(self.program_names())
        self.links_revision += 1
        return {"result": "Reloaded at scan 7 (3 tag(s))", "carried": carried}

    def set_mode(self, mode, patches=None, forces=None):
        self.calls.append(("set_mode", mode, patches, forces))

    def continue_(self):
        self.calls.append(("continue",))

    def pause(self):
        self.calls.append(("pause",))

    def step_scan(self):
        self.calls.append(("step",))

    def set_speed(self, speed):
        self.calls.append(("set_speed", speed))

    def modbus_info(self):
        return dict(self.info)

    def force(self, tag, value):
        self.calls.append(("force", tag, value))
        if tag == "BAD1":
            raise RuntimeError("unknown tag: BAD1")
        self.forces = {**self.forces, self._tag(tag): value}

    def unforce(self, tag):
        self.calls.append(("unforce", tag))
        self.forces = {k: v for k, v in self.forces.items() if k != self._tag(tag)}

    def list_forces(self):
        return dict(self.forces)

    def clear_forces(self):
        self.calls.append(("clear_forces",))

    def patch(self, patches):
        self.calls.append(("patch", dict(patches)))

    # Bench links: a small model of pyrung's overlay, keyed by address.
    def link(self, feedback, enable, *, trigger=None, response=()):
        self.calls.append(("link", feedback, enable, {"trigger": trigger, "response": response}))
        if feedback in self.refuse_links:
            raise RuntimeError(f"cannot link {feedback}: {self.refuse_links[feedback]}")
        self.bench[self._tag(feedback)] = {
            "enable": self._tag(enable), "enabled": True, "trigger": trigger,
            "response": dict(response),
        }  # fmt: skip
        self.links_revision += 1

    def unlink(self, feedback):
        self.calls.append(("unlink", feedback))
        feedback = self._tag(feedback)
        if feedback in self.project:
            self.bench[feedback] = {"enable": None, "enabled": True}
        elif self.bench.pop(feedback, None) is None:
            raise RuntimeError(f"{feedback} has no link")
        self.links_revision += 1

    def restore_link(self, feedback):
        self.calls.append(("restore_link", feedback))
        if self.bench.pop(self._tag(feedback), None) is None:
            raise DapRequestError(f"{self._tag(feedback)} has no bench change")  # as pyrung
        self.links_revision += 1

    def set_links(self, *, bench=None, enabled=None):
        self.calls.append(("set_links", bench, dict(enabled or {})))
        if bench is not None:
            self.bench_on = bench
        for feedback, on in (enabled or {}).items():
            self.bench[self._tag(feedback)]["enabled"] = on
        self.links_revision += 1

    def list_links(self):
        rows = [
            {"feedback": fb, "enable": en, "source": "project", "kind": "delay",
             **_dap_fields({"on_delay": "1s"}),
             "trigger": None, "active": fb not in self.bench, "pending": False}
            for fb, en in self.project.items()
        ]  # fmt: skip
        for fb, entry in self.bench.items():
            rows.append(
                {
                    "feedback": fb,
                    "enable": entry["enable"],
                    "source": "bench",
                    "cut": entry["enable"] is None,
                    "trigger": entry.get("trigger"),
                    **_dap_fields(entry.get("response", {})),
                    "enabled": entry["enabled"],
                    "active": self.bench_on and entry["enabled"],
                    "pending": False,
                }
            )
        return {"bench": self.bench_on, "revision": self.links_revision, "links": rows}

    def frame(self, **changes) -> None:
        """Simulate a pyrungScanFrame arriving on the reader thread."""
        for name, value in changes.items():
            setattr(self, name, value)
        self.callbacks["on_frame"]()


class FakeModbus:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.connected_with: dict | None = None
        self.polled: list[str] = []
        self.disconnected = False

    def connect(self, host, port, **kwargs):
        self.connected_with = {"host": host, "port": port, **kwargs}

    def set_poll_addresses(self, addresses):
        self.polled = list(addresses)

    def clear_poll_addresses(self):
        self.polled = []

    def disconnect(self):
        self.disconnected = True


def _publish(svc: AnalysisService, result: AnalysisResult) -> None:
    """A build that converted: the graph and the workspace share one snapshot of names."""
    svc._result = result
    svc._project_tags = result.tag_to_addr_key
    svc._project_keys = result.addr_key_to_tag
    svc._project_is_current = True
    svc._status = AnalysisStatus.READY


def _ready_analysis(project_dir: Path, *, generation: int = 1) -> AnalysisService:
    (project_dir / "run.py").write_text("x", encoding="utf-8")
    svc = AnalysisService()
    _publish(
        svc,
        AnalysisResult(
            graph=SimpleNamespace(tag_roles={}),
            program=MagicMock(),
            project_dir=project_dir,
            tag_to_addr_key={},
            addr_key_to_tag={},
        ),
    )
    svc._generation = generation
    return svc


CPU = SimpleNamespace(
    location="cpu",
    position=0,
    module=SimpleNamespace(model="C0-02DD1-D"),
    inputs=("X001", "X002", "X003"),
    outputs=("Y001",),
    analog_inputs=("DF1",),
    analog_outputs=(),
)


class Harness:
    def __init__(self, tmp_path: Path, analysis: AnalysisService | None) -> None:
        self.scheduler = FakeScheduler()
        self.analysis = analysis
        self.daps: list[FakeDap] = []
        self.modbus: list[FakeModbus] = []
        self.retries: list[str] = []
        self.events: list = []
        self.live_commands: list[str] = []
        project_ini = tmp_path / "Project.ini"
        project_ini.write_text("[SystemConfig]\n", encoding="utf-8")
        self.layout = build_panel_layout([CPU])

        def dap_factory(**callbacks):
            dap = FakeDap(**callbacks)
            dap.program_names = self.workspace_names
            if self.next_launch_error is not None:
                dap.launch_error = self.next_launch_error
            dap.launch_hook = self.launch_hook
            self.daps.append(dap)
            return dap

        def modbus_factory(**kwargs):
            service = FakeModbus(**kwargs)
            self.modbus.append(service)
            return service

        def send_command(_session, command):
            self.live_commands.append(command)
            return True, ""

        self.next_launch_error: Exception | None = None
        self.launch_hook = None
        self.saves = 0
        self.snapshot: dict = {}
        self.sim = SimulationSession(
            scheduler=self.scheduler,
            get_analysis=lambda: self.analysis,
            get_project_ini=lambda: project_ini,
            session_name="test",
            on_retry_analysis=lambda: self.retries.append("rebuild"),
            dap_factory=dap_factory,
            modbus_factory=modbus_factory,
            layout_reader=lambda _path, used: build_panel_layout([CPU], used),
            snapshot_reader=lambda _path: dict(self.snapshot),
            run_background=lambda target, _name: target(),
            run_serial=lambda job: job(),
            send_command=send_command,
            app_data_root=tmp_path / "app",
            get_save_count=lambda: self.saves,
        )
        self.sim.add_listener(self.events.append)

    def workspace_names(self) -> dict[str, str]:
        """Address -> tag name, as the workspace's files name them."""
        if self.analysis is None:
            return {}
        return {
            format_address_display(*parse_addr_key(key)): tag
            for key, tag in self.analysis.project_addr_key_to_tag.items()
        }

    @property
    def dap(self) -> FakeDap:
        return self.daps[-1]

    def messages(self, level: str | None = None) -> str:
        return "\n".join(
            e.text for e in self.events if e.kind == "message" and level in (None, e.level)
        )

    def open(self) -> None:
        self.sim.turn_on()
        self.scheduler.run_ready()


@pytest.fixture()
def ready(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return Harness(tmp_path, _ready_analysis(project))


# ----------------------------------------------------------------------
# Startup (moved here from the Console, which used to own the DAP)
# ----------------------------------------------------------------------


def test_build_in_flight_waits_without_error(ready):
    """The folder is rubble mid-build even though the old result looks fine."""
    ready.analysis._status = AnalysisStatus.BUILDING
    ready.open()
    assert ready.sim.status is SimStatus.WAITING
    assert ready.sim.is_waiting
    assert ready.daps == []
    assert ready.messages() == ""


def test_failed_conversion_is_reported_with_details(tmp_path):
    svc = AnalysisService()
    svc.mark_failed("pyrung conversion crashed", "Traceback...\nValueError: boom")
    harness = Harness(tmp_path, svc)
    harness.open()
    assert harness.sim.status is SimStatus.FAILED
    assert not harness.sim.is_waiting
    assert "pyrung conversion crashed" in harness.messages("error")
    assert "Nickname editing is still available" in harness.messages()
    assert "Traceback" not in harness.messages()
    assert harness.sim.error_detail == "Traceback...\nValueError: boom"


def test_failed_rebuild_does_not_launch_previous_program(ready):
    ready.analysis.mark_failed("TypeError: reset() requires at least one condition")
    ready.open()
    assert ready.analysis.is_available, "cached analysis should remain available to editors"
    assert ready.daps == []
    assert ready.sim.status is SimStatus.FAILED
    assert "reset() requires at least one condition" in ready.messages()


def test_failed_conversion_during_poll_is_reported(ready):
    ready.analysis._status = AnalysisStatus.BUILDING
    ready.open()
    ready.analysis.mark_failed("bad rung", "Traceback details")
    ready.scheduler.fire(ANALYSIS_POLL_MS)
    assert ready.sim.status is SimStatus.FAILED
    assert not ready.sim.is_waiting
    assert "pyrung could not build this CLICK program for simulation" in ready.messages()


def test_guidance_mentions_the_generated_workspace(tmp_path):
    svc = AnalysisService()
    svc._project_dir = tmp_path
    svc.mark_failed("TypeError: boom")
    harness = Harness(tmp_path, svc)
    harness.open()
    assert "Open the generated workspace" in harness.messages()


def _record_unreadable(project_dir: Path, *rungs: int | None, unreadable: bool = True) -> None:
    from clicknick.ladder.program import LegacyEncoding, write_legacy_encodings

    detail = "ClickNick cannot read this Compare."
    csv_dir = project_dir / "csv"
    csv_dir.mkdir(exist_ok=True)
    found = [
        LegacyEncoding(
            "subroutines/Conf_Compare.csv", "Conf_Compare", rung, "Compare", "", detail, unreadable
        )
        for rung in rungs
    ]
    write_legacy_encodings(csv_dir, found)


def test_program_with_a_rung_clicknick_cannot_read_does_not_run(ready):
    _record_unreadable(ready.analysis.project_dir, 4)
    ready.open()

    assert ready.daps == []
    assert ready.sim.status is SimStatus.FAILED
    message = ready.messages("error")
    assert "ClickNick cannot read this rung in CLICK" in message
    assert "Conf_Compare rung 4, Compare: ClickNick cannot read this Compare." in message
    assert message.endswith("Paste it again.")
    assert "WriterError" not in message


def test_several_unreadable_rungs_are_named_together(ready):
    _record_unreadable(ready.analysis.project_dir, 4, 5)
    ready.open()

    message = ready.messages("error")
    assert "Conf_Compare rung 4" in message
    assert "Conf_Compare rung 5" in message
    assert message.endswith("Paste them again.")


def test_once_the_rung_is_pasted_again_the_simulation_runs(ready):
    _record_unreadable(ready.analysis.project_dir, 4)
    ready.open()
    assert ready.daps == []

    _record_unreadable(ready.analysis.project_dir)  # CLICK saved the pasted rung
    ready.sim.restart()
    ready.scheduler.run_ready()

    assert ready.sim.status is SimStatus.READY


def test_a_csv_laddercodec_cannot_read_back_does_not_stop_the_simulation(ready):
    # pyrung read that CSV itself, so the simulation runs every rung of it
    _record_unreadable(ready.analysis.project_dir, None)
    ready.open()

    assert ready.sim.status is SimStatus.READY


def test_a_legacy_encoding_alone_does_not_stop_the_simulation(ready):
    _record_unreadable(ready.analysis.project_dir, 4, unreadable=False)
    ready.open()

    assert ready.sim.status is SimStatus.READY


def test_launch_starts_the_simulator_in_stop_with_a_modbus_server(ready):
    ready.open()
    _name, project_dir, kwargs = ready.dap.calls[0]
    assert project_dir == ready.analysis.project_dir
    assert kwargs["modbus"] == {"host": "127.0.0.1", "port": 502}
    assert kwargs["speed"] == 1.0
    assert kwargs["start_mode"] == "stop"
    assert kwargs["keep_forces_on_run"] is True
    assert kwargs["session_name"] == "test"
    assert ready.sim.status is SimStatus.READY
    assert ready.sim.is_ready
    assert "OK - simulation ready." in ready.messages()


def test_launch_failure_during_rebuild_waits(ready):
    """A rebuild that starts *and finishes* mid-launch must not surface as an error.

    This is the "No module named 'subroutines'" case: the launch read a
    half-written project, but by the time the failure arrives the rebuild has
    completed, so the status alone looks healthy.
    """
    ready.analysis._generation = 5

    def rebuild_under_the_launch() -> None:
        ready.analysis._generation = 6  # a rebuild ran under the launch...
        ready.analysis._status = AnalysisStatus.READY  # ...and already finished
        raise RuntimeError("DAP launch failed: No module named 'subroutines'")

    ready.launch_hook = rebuild_under_the_launch
    ready.open()
    assert ready.sim.is_waiting, "raced launch should wait and relaunch"
    assert ready.sim.status is SimStatus.WAITING
    assert "failed to start" not in ready.messages()


def test_launch_failure_without_rebuild_is_reported(ready):
    ready.next_launch_error = RuntimeError("DAP launch failed: something genuinely broken")
    ready.open()
    assert ready.sim.status is SimStatus.FAILED
    assert not ready.sim.is_waiting
    assert "something genuinely broken" in ready.messages("error")


def test_waiting_is_bounded_by_the_timeout(ready):
    ready.analysis._status = AnalysisStatus.BUILDING  # never completes
    ready.open()
    for _ in range(int(ANALYSIS_TIMEOUT_MS / ANALYSIS_POLL_MS) + 5):
        if not ready.sim.is_waiting:
            break
        ready.scheduler.fire(ANALYSIS_POLL_MS)
    assert not ready.sim.is_waiting, "poll loop never terminated"
    assert "timed out" in ready.messages()
    assert ready.sim.status is SimStatus.FAILED


def test_retry_rebuilds_and_launches(tmp_path):
    svc = AnalysisService()
    svc.mark_failed("no ladder files")
    harness = Harness(tmp_path, svc)
    harness.open()
    project = tmp_path / "project"
    project.mkdir()
    harness.analysis = _ready_analysis(project)

    harness.sim.retry()
    harness.scheduler.run_ready()

    assert harness.retries == ["rebuild"]
    assert harness.sim.status is SimStatus.READY
    assert harness.sim.error_detail is None


def test_nothing_starts_until_turned_on(ready):
    assert not ready.sim.enabled
    assert ready.daps == []
    assert ready.sim.summary_text == "off"


def test_turning_off_stops_the_simulation_and_turning_on_again_relaunches(ready):
    ready.open()
    assert ready.sim.summary_text == "on :502"
    ready.sim.turn_off()
    assert ("terminate",) in ready.dap.calls
    assert ready.sim.status is SimStatus.IDLE
    assert ready.sim.status_text == "Simulation off"
    assert "Simulation off." in ready.messages()

    ready.open()
    assert len(ready.daps) == 2
    assert ready.sim.is_ready


def test_turning_on_twice_launches_once(ready):
    ready.open()
    ready.open()
    assert len(ready.daps) == 1


def test_launch_finishing_after_turn_off_is_terminated(ready):
    ready.sim.turn_on()  # launch result queued, not yet delivered
    ready.sim.turn_off()
    ready.scheduler.run_ready()
    assert ("terminate",) in ready.dap.calls
    assert not ready.sim.is_ready


def test_retry_while_off_turns_it_on(ready):
    ready.sim.retry()
    ready.scheduler.run_ready()
    assert ready.sim.enabled
    assert ready.sim.is_ready


def test_dap_dying_is_reported(ready):
    ready.open()
    ready.dap.stderr_text = "Traceback: crashed"
    ready.dap.callbacks["on_state"](SimpleNamespace(value="error"), None)
    ready.scheduler.run_ready()
    assert ready.sim.status is SimStatus.FAILED
    assert ready.sim.error_detail == "Traceback: crashed"
    assert "stopped unexpectedly" in ready.messages("error")


def test_plc_data_change_relaunches_from_the_snapshot(ready, tmp_path):
    ready.open()
    data = tmp_path / "data.csv"
    data.write_text("a", encoding="utf-8")
    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()
    assert len(ready.daps) == 2
    assert ready.dap.calls[0][2]["snapshot_path"] == data
    assert "Loading PLC data" in ready.messages()


def test_saving_the_plc_data_file_again_reloads_it(ready, tmp_path):
    import os

    from clicknick.simulation_session import WATCH_MS

    ready.open()
    data = tmp_path / "data.csv"
    data.write_text("a", encoding="utf-8")
    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == 2, "an unchanged file is not reloaded"

    later = data.stat().st_mtime + 5
    os.utime(data, (later, later))  # CLICK saved the dump again
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == 3
    assert "PLC data file changed. Reloading..." in ready.messages()


# ----------------------------------------------------------------------
# The STOP / STEP / RUN switch
# ----------------------------------------------------------------------


def test_switch_position_is_derived_from_frames(ready):
    ready.open()
    assert ready.sim.switch_position == "stop"
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    assert ready.sim.switch_position == "run"
    ready.dap.frame(mode="run", running=False, source={"origin": "live", "command": "step 10"})
    ready.scheduler.run_ready()
    assert ready.sim.switch_position == "step"
    assert ready.sim.source_text == "Moved to STEP by Console: step 10"


def test_stop_to_run_applies_inputs_and_forces_before_scan_one(ready):
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.set_analog("DF1", 2.5)
    ready.sim.force("Y001", True)

    ready.sim.set_switch_position("run")

    # Forces persist through STOP -> RUN (keepForcesOnRun); inputs patched in STOP
    # are dropped by the transition, so they ride it again.
    assert ready.dap.calls[1:] == [
        ("patch", {"X001": True}),
        ("patch", {"DF1": 2.5}),
        ("force", "Y001", True),
        ("set_mode", "run", {"X001": True, "DF1": 2.5}, None),
        ("continue",),
    ]
    assert ready.sim.run_hint_seen


def test_stop_to_step_waits_before_scan_one(ready):
    ready.open()
    ready.dap.calls.clear()
    ready.sim.set_switch_position("step")
    assert ready.dap.calls == [("set_mode", "run", {}, None)]


def test_run_to_step_pauses_and_step_to_stop_stops(ready):
    ready.open()
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    ready.dap.calls.clear()
    ready.sim.set_switch_position("step")
    assert ready.dap.calls == [("pause",)]

    ready.dap.frame(mode="run", running=False)
    ready.scheduler.run_ready()
    ready.dap.calls.clear()
    ready.sim.set_switch_position("stop")
    assert ready.dap.calls == [("set_mode", "stop", None, None)]


def test_step_n_and_run_for_use_the_live_console_verbs(ready):
    ready.open()
    ready.sim.step()
    ready.sim.step(10)
    ready.sim.run_for("500ms")
    assert ("step",) in ready.dap.calls
    assert ready.live_commands == ["step 10", "run 500ms"]


def test_speed_follows_frames_and_shows_when_behind(ready):
    ready.open()
    ready.sim.set_speed(2.0)
    assert ("set_speed", 2.0) in ready.dap.calls
    ready.dap.frame(mode="run", running=True, speed=10.0, actual_speed=4.0)
    ready.scheduler.run_ready()
    assert ready.sim.speed == 10.0
    assert ready.sim.speed_text == "10x (actual 4x)"
    ready.dap.frame(speed=0.0, actual_speed=None)
    ready.scheduler.run_ready()
    assert ready.sim.speed_text == "Max"


def test_relaunch_restores_run_with_inputs_and_forces(ready):
    ready.open()
    ready.sim.force("Y001", False)
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()

    ready.sim.restart()
    ready.scheduler.run_ready()

    assert ready.dap.calls[1:] == [
        ("force", "Y001", False),
        ("set_mode", "run", {}, None),
        ("continue",),
    ]


def test_relaunch_in_stop_reapplies_forces(ready):
    ready.open()
    ready.sim.force("Y001", True)
    ready.sim.restart()
    ready.scheduler.run_ready()
    assert ready.dap.calls[1:] == [("force", "Y001", True)]


# ----------------------------------------------------------------------
# Forces
# ----------------------------------------------------------------------


def test_forces_set_elsewhere_are_followed(ready):
    ready.open()
    ready.dap.frame(forces={})
    ready.scheduler.run_ready()
    ready.dap.frame(forces={"Y001": True})
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"Y001": True}
    ready.dap.frame(forces={})
    ready.scheduler.run_ready()
    assert ready.sim.forces == {}


def test_first_frame_after_launch_does_not_clear_desired_forces(ready):
    ready.sim.force("Y001", True)  # chosen before the simulation runs
    ready.open()
    ready.dap.frame(forces={})
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"Y001": True}


def test_refused_force_is_undone_and_reported(ready):
    ready.open()
    errors: list[str] = []
    ready.sim.force("BAD1", 1, on_error=errors.append)
    ready.scheduler.run_ready()
    assert "BAD1" not in ready.sim.forces
    assert errors and "unknown tag" in errors[0]


def test_release_all(ready):
    ready.open()
    ready.sim.force("Y001", True)
    ready.sim.release_all_forces()
    assert ready.sim.forces == {}
    assert ("clear_forces",) in ready.dap.calls


# ----------------------------------------------------------------------
# Modbus (values) and inputs (DAP)
# ----------------------------------------------------------------------


def _with_modbus(harness: Harness) -> FakeModbus:
    harness.open()
    harness.scheduler.run_ready()  # modbus info -> connect
    return harness.modbus[-1]


def test_modbus_client_connects_with_fast_poll(ready):
    service = _with_modbus(ready)
    assert service.connected_with == {"host": "127.0.0.1", "port": 502, "timeout": 2}
    assert service.kwargs["poll_interval_s"] == 0.1
    ready.sim.watch("panel", ["X001", "Y001"])
    assert service.polled == ["X001", "Y001"]


def test_modbus_text_excludes_our_own_connection(ready):
    _with_modbus(ready)
    assert ready.sim.modbus_text.endswith("0 clients")


def test_switches_and_analog_are_patched_over_dap(ready):
    _with_modbus(ready)
    ready.sim.toggle_switch("X001")
    ready.sim.set_momentary("X002", True)
    ready.sim.press_input("X002")
    assert ready.sim.switch_on("X002")
    ready.sim.release_input("X002")
    ready.sim.set_analog("DF1", 2.5)
    patches = [call[1] for call in ready.dap.calls if call[0] == "patch"]
    assert patches == [{"X001": True}, {"X002": True}, {"X002": False}, {"DF1": 2.5}]
    assert not ready.sim.switch_on("X002")


def test_without_a_modbus_server_inputs_are_patched(ready):
    ready.open()
    ready.dap.info = {"running": False, "error": "port 502 in use", "port": 502}
    ready.scheduler.fire(MODBUS_INFO_MS)
    ready.sim.toggle_switch("X003")
    assert ("patch", {"X003": True}) in ready.dap.calls
    assert "unavailable" in ready.sim.modbus_text


def test_values_arrive_keyed_by_address(ready):
    service = _with_modbus(ready)
    service.kwargs["on_values"]({"x1": True, "DF1": 1.5})
    ready.scheduler.run_ready()
    assert ready.sim.values == {"X001": True, "DF1": 1.5}


def test_pending_writes_are_reported_by_address(ready):
    ready.open()
    ready.analysis._result.tag_to_addr_key["Start"] = 0
    from pyclickplc.addresses import get_addr_key

    ready.analysis._result.tag_to_addr_key["Start"] = get_addr_key("X", 1)
    ready.dap.pending_patches = {"Start": True}
    assert ready.sim.pending == {"X001": True}


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------


def test_settings_are_saved_and_restored(ready, tmp_path):
    ready.sim.set_state_location("Line1", None)
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.force("Y001", True)
    ready.scheduler.fire(SAVE_DELAY_MS)

    saved = load_state(tmp_path / "app" / "Line1.toml")
    assert saved.switches == {"X001": True}
    assert saved.forces == {"Y001": True}
    assert saved.modules == ("cpu:C0-02DD1-D",)

    fresh = Harness(tmp_path, ready.analysis)
    fresh.sim.set_state_location("Line1", None)
    assert fresh.sim.switch_on("X001")
    assert fresh.sim.restored_forces == 1


def test_a_bench_link_the_file_cannot_hold_is_reported(ready, tmp_path):
    path = tmp_path / "app" / "Line1.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[links]\n"
        "DF1 = {enable = 'Y001', profile = 'approach:toward=180'}\n"
        "X001 = {enable = 'Y002', on_delay = '2s'}\n",
        encoding="utf-8",
    )
    ready.sim.set_state_location("Line1", None)
    assert ready.messages("error") == (
        "Could not restore the bench link on DF1: no upgrade reads "
        "profile=approach:toward=180. Dropped it."
    )
    assert ready.sim.restored_links == 1


def test_restore_drops_inputs_the_hardware_no_longer_has(ready, tmp_path):
    save_state(
        tmp_path / "app" / "Line1.toml",
        SimulatorState(switches={"X001": True, "X009": True}, modules=("cpu:OLD",)),
    )
    ready.sim.set_state_location("Line1", None)
    ready.open()
    assert ready.sim.switch_on("X001")
    assert not ready.sim.switch_on("X009")
    assert ready.sim.notice and "X009" in ready.sim.notice


def test_pairing_a_workspace_moves_settings_into_it(ready, tmp_path):
    ready.sim.set_state_location("Line1", None)
    ready.open()
    ready.sim.toggle_switch("X001")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    ready.sim.set_state_location("Line1", workspace)

    assert ready.sim.state_path == workspace / "simulator.toml"
    assert load_state(workspace / "simulator.toml").switches == {"X001": True}
    assert not (tmp_path / "app" / "Line1.toml").exists()
    assert ready.sim.switch_on("X001")


def test_workspace_settings_win_over_app_data(ready, tmp_path):
    save_state(tmp_path / "app" / "Line1.toml", SimulatorState(switches={"X001": True}))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    save_state(workspace / "simulator.toml", SimulatorState(switches={"X002": True}))
    ready.sim.set_state_location("Line1", None)
    ready.open()

    ready.sim.set_state_location("Line1", workspace)

    assert ready.sim.switch_on("X002")
    assert not ready.sim.switch_on("X001")
    assert "already had simulator settings" in (ready.sim.notice or "")


def test_run_hint_is_remembered(ready, tmp_path):
    ready.sim.set_state_location("Line1", None)
    ready.open()
    assert not ready.sim.run_hint_seen
    ready.sim.set_switch_position("run")
    ready.scheduler.fire(SAVE_DELAY_MS)
    assert load_state(tmp_path / "app" / "Line1.toml").run_hint_seen


def test_layout_lists_unassigned_io_the_program_uses(ready):
    from pyclickplc.addresses import get_addr_key

    ready.analysis._result.tag_to_addr_key.update(
        {
            "Aux": get_addr_key("X", 201),
            "Lamp": get_addr_key("Y", 1),
            "_IO1_Module_Error": get_addr_key("X", 101),  # module status, not a terminal
        }
    )
    ready.analysis._result.graph.tag_roles.update(
        {"Aux": None, "Lamp": None, "_IO1_Module_Error": None}
    )
    ready.open()
    ready.sim.refresh_layout(force=True)
    assert ready.sim.layout is not None
    (placeholder,) = [c for c in ready.sim.layout.cards if not c.installed]
    assert [t.address for t in placeholder.of_kind("input")] == ["X201"]
    assert "X101" not in ready.sim.layout.addresses("input")
    assert ready.sim.layout.modules == ("cpu:C0-02DD1-D",)


def test_loading_plc_data_sets_switches_and_analog_values(ready, tmp_path):
    ready.open()
    ready.sim.toggle_switch("X002")
    ready.sim.set_momentary("X003", True)
    ready.sim.force("Y001", True)
    ready.snapshot = {"X001": True, "X002": False, "X003": True, "DF1": 6.5, "DS1": 4}
    data = tmp_path / "dump.csv"
    data.write_text("x", encoding="utf-8")

    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()

    assert ready.sim.switch_on("X001")
    assert not ready.sim.switch_on("X002")
    assert not ready.sim.switch_on("X003"), "momentary buttons keep no position"
    assert ready.sim.analog_value("DF1") == 6.5
    assert ready.sim.forces == {"Y001": True}, "forces stay"
    assert ready.sim.notice == "Loaded PLC data from dump.csv; switches set from snapshot."
    assert ready.dap.calls[0][2]["snapshot_path"] == data


# ----------------------------------------------------------------------
# Bench links
# ----------------------------------------------------------------------

AUX_LINK = BenchLink("Y001", response=response(on_delay="2s", off_delay="500ms"))


def _frame(harness: Harness) -> None:
    harness.dap.frame()
    harness.scheduler.run_ready()


def test_link_is_sent_and_read_back(ready):
    ready.open()
    ready.sim.link("X002", AUX_LINK)
    assert ready.dap.calls[-1] == (
        "link", "X002", "Y001",
        {"trigger": None, "response": (("on_delay", "2s"), ("off_delay", "500ms"))},
    )  # fmt: skip
    _frame(ready)
    link = ready.sim.driving_link("X002")
    assert link is not None
    assert (link.source, link.enable, link.kind) == ("bench", "Y001", "delay")
    assert link.response_label == "on_delay=2s, off_delay=500ms"
    assert ready.sim.bench_links == {"X002": AUX_LINK}


def test_links_chosen_before_launch_are_applied_with_the_rest(ready):
    ready.sim.link("X002", AUX_LINK)
    ready.sim.cut_link("X003")
    ready.sim.set_bench_wiring(False)
    assert ready.sim.links[0].feedback == "X002"  # shown even while the simulation is off

    ready.open()
    calls = [call[0] for call in ready.dap.calls]
    assert calls[:4] == ["launch", "link", "unlink", "set_links"]
    assert ready.dap.bench_on is False


def test_a_link_the_simulation_refuses_is_undone_and_reported(ready):
    ready.open()
    ready.dap.refuse_links["X001"] = "X001 is written by the program at Main:R3"
    errors: list[str] = []
    ready.sim.link("X001", AUX_LINK, on_error=errors.append)
    ready.scheduler.run_ready()
    assert "X001" not in ready.sim.bench_links
    assert errors and "written by the program" in errors[0]


def test_restore_failure_drops_the_link_with_a_message(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project))
    harness.sim.cut_link("X003")  # the program no longer links X003
    harness.open()
    assert harness.sim.bench_links == {}
    assert "Could not restore the bench link on X003" in harness.messages("error")


def test_changes_made_from_the_console_are_adopted(ready):
    ready.open()
    ready.dap.project["X002"] = "Y001"
    ready.dap.unlink("X002")  # someone typed `unlink X002` in the Console
    _frame(ready)
    assert ready.sim.bench_links == {"X002": BenchLink(None)}
    project = ready.sim.project_link("X002")
    assert project is not None and not project.active
    assert ready.sim.driving_link("X002") is None


def test_restore_and_disable(ready):
    ready.open()
    ready.sim.link("X002", AUX_LINK)
    ready.sim.set_link_enabled("X002", False)
    assert ready.dap.calls[-1] == ("set_links", None, {"X002": False})
    _frame(ready)
    assert ready.sim.driving_link("X002") is None
    assert ready.sim.bench_links["X002"].enabled is False

    ready.sim.restore_link("X002")
    assert ready.dap.calls[-1] == ("restore_link", "X002")
    assert ready.sim.bench_links == {}


def test_bench_links_are_saved_and_restored(ready, tmp_path):
    ready.sim.set_state_location("Line1", None)
    ready.open()
    ready.sim.link("X002", AUX_LINK)
    ready.scheduler.fire(SAVE_DELAY_MS)
    assert load_state(tmp_path / "app" / "Line1.toml").links == {"X002": AUX_LINK}

    fresh = Harness(tmp_path, ready.analysis)
    fresh.sim.set_state_location("Line1", None)
    assert fresh.sim.restored_links == 1
    fresh.sim.discard_bench_links()
    assert fresh.sim.bench_links == {}
    assert fresh.sim.restored_links == 0


# ----------------------------------------------------------------------
# Console echo, tag names and link countdowns
# ----------------------------------------------------------------------


def _name(ready, address: str, tag: str) -> None:
    from pyclickplc.addresses import get_addr_key, parse_address

    key = get_addr_key(*parse_address(address))
    ready.analysis._result.addr_key_to_tag[key] = tag
    ready.analysis._result.tag_to_addr_key[tag] = key


def _echoes(ready) -> list[str]:
    return [e.text for e in ready.events if e.kind == "echo"]


def test_to_tag_uses_the_running_programs_names(ready):
    _name(ready, "X001", "Start_PB")
    assert ready.sim.to_tag("X001") == "Start_PB"
    assert ready.sim.to_tag("x2") == "X002", "unnamed points go by their address"


def test_panel_actions_echo_as_console_commands(ready):
    ready.open()
    _name(ready, "X001", "Start_PB")
    _name(ready, "Y001", "Motor_Run")
    ready.events.clear()

    ready.sim.toggle_switch("X001")
    ready.sim.force("Y001", False)
    ready.sim.release_force("Y001")
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    ready.sim.set_switch_position("step")
    ready.sim.step(10)
    ready.sim.run_for("500ms")
    ready.sim.set_speed(0)
    ready.sim.link("X002", AUX_LINK)
    ready.sim.cut_link("X003")
    ready.sim.restore_link("X003")
    ready.sim.set_bench_wiring(False)

    assert _echoes(ready) == [
        "patch Start_PB true",
        "force Motor_Run false",
        "unforce Motor_Run",
        "mode run",
        "continue",
        "pause",
        "step 10",
        "run 500ms",
        "speed max",
        "link X002 Motor_Run on_delay=2s off_delay=500ms",
        "unlink X003",
        "restore X003",
        "links bench off",
    ]


def test_pushbuttons_do_not_echo_and_a_dragged_value_echoes_once_settled(ready):
    from clicknick.simulation_session import ECHO_SETTLE_MS

    ready.open()
    ready.events.clear()
    ready.sim.set_momentary("X002", True)
    ready.sim.press_input("X002")
    ready.sim.release_input("X002")
    ready.sim.set_analog("DF1", 10.0)
    ready.sim.set_analog("DF1", 42.5)
    assert _echoes(ready) == []
    ready.scheduler.fire(ECHO_SETTLE_MS)
    assert _echoes(ready) == ["patch DF1 42.5"]


def test_nothing_echoes_while_the_simulation_is_off(ready):
    ready.sim.toggle_switch("X001")
    assert _echoes(ready) == []


def test_frames_carry_link_countdowns_by_address(ready):
    ready.open()
    _name(ready, "X002", "Motor_Aux")
    ready.dap.frame(links_pending={"Motor_Aux": 1500})
    ready.scheduler.run_ready()
    assert ready.sim.link_countdown("X002") == 1500
    ready.dap.frame(links_pending={})
    ready.scheduler.run_ready()
    assert ready.sim.link_countdown("X002") is None


# ----------------------------------------------------------------------
# A CLICK save while the simulation runs, and tag renames
# ----------------------------------------------------------------------


def _rebuild(
    harness: Harness, renames: dict[str, str] | None = None, *, saved: bool = True
) -> None:
    """A CLICK save rebuilt the analysis: a new tag map (with *renames* by address).

    Not *saved*: a rebuild without a save (Reload from CLICK, a Sync).
    """
    if saved:
        harness.saves += 1
    from pyclickplc.addresses import get_addr_key, parse_address

    old = harness.analysis._result
    key_to_tag = dict(old.addr_key_to_tag)
    for address, tag in (renames or {}).items():
        key_to_tag[get_addr_key(*parse_address(address))] = tag
    _publish(
        harness.analysis,
        AnalysisResult(
            graph=old.graph,
            program=old.program,
            project_dir=old.project_dir,
            tag_to_addr_key={tag: key for key, tag in key_to_tag.items()},
            addr_key_to_tag=key_to_tag,
        ),
    )
    harness.analysis._generation += 1


def _bench_by_name(dap: FakeDap, names: dict[str, str]) -> None:
    """pyrung lists links by tag name; rename the fake's bench rows the same way."""
    dap.bench = {
        names.get(fb, fb): {**entry, "enable": names.get(entry["enable"], entry["enable"])}
        for fb, entry in dap.bench.items()
    }
    dap.links_revision += 1


ON_DELAY_LINK = BenchLink("Y001", response=response(on_delay="1s"))


def _named_and_running(ready) -> None:
    _name(ready, "X001", "Start")
    _name(ready, "X002", "Prox")
    _name(ready, "Y001", "Motor")
    ready.sim.set_state_location("Line1", None)
    ready.open()
    ready.sim.force("X001", True)
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.dap.forces = {"Start": True}
    _bench_by_name(ready.dap, {"X002": "Prox", "Y001": "Motor"})
    _frame(ready)
    _frame(ready)
    assert ready.sim.forces == {"X001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}


def test_a_rename_keeps_forces_and_links_on_their_addresses(ready, tmp_path):
    _named_and_running(ready)

    # Renamed in ClickNick, synced and saved in CLICK: the analysis has the new names,
    # while the simulation still runs the program it was launched with.
    _rebuild(ready, {"X001": "StartPB", "Y001": "MotorRun"})
    ready.dap.links_revision += 1
    _frame(ready)
    _frame(ready)

    assert ready.sim.forces == {"X001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.to_tag("X001") == "Start", "commands go to the program that runs"
    ready.scheduler.fire(SAVE_DELAY_MS)
    saved = load_state(tmp_path / "app" / "Line1.toml")
    assert dict(saved.forces) == {"X001": True}
    assert dict(saved.links) == {"X002": ON_DELAY_LINK}


def test_a_force_on_a_tag_without_an_address_is_not_kept(ready):
    ready.open()
    ready.sim.force("Y001", True)
    ready.dap.frame(forces={"Y001": True})
    ready.scheduler.run_ready()
    ready.dap.frame(forces={"Y001": True, "Scratch": 5})  # `force Scratch 5` in the Console
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"Y001": True}


def test_a_bench_link_on_a_tag_without_an_address_is_not_kept(ready):
    ready.open()
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.dap.bench["Scratch"] = {"enable": "Y001", "enabled": True, "response": {}}
    _frame(ready)
    ready.dap.links_revision += 1
    _frame(ready)
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}


def test_saved_forces_and_links_not_on_an_address_are_reported(ready, tmp_path):
    path = tmp_path / "app" / "Line1.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[forces]\nStart = true\nY001 = true\n[links]\nProx = {enable = 'Y001', on_delay = '1s'}\n",
        encoding="utf-8",
    )
    ready.sim.set_state_location("Line1", None)
    assert ready.sim.forces == {"Y001": True}
    errors = ready.messages("error")
    assert "Could not restore the force on Start: it is not a CLICK address. Dropped it." in errors
    assert "Could not restore the bench link on Prox: it is not a CLICK address." in errors


def _running_with_settings(ready) -> None:
    """In RUN with a switch on, a force and a bench link, all acknowledged by frames."""
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.force("Y001", True)
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True, forces={"Y001": True})
    ready.scheduler.run_ready()


def _calls_since(dap: FakeDap, mark: int) -> list[tuple]:
    return [call[:3] for call in dap.calls[mark:]]


def test_a_click_save_is_only_offered_until_the_user_writes_it(ready):
    from clicknick.simulation_session import WATCH_MS

    _running_with_settings(ready)
    mark = len(ready.dap.calls)
    ready.events.clear()

    _rebuild(ready)
    ready.scheduler.fire(WATCH_MS)
    ready.scheduler.fire(WATCH_MS)

    assert len(ready.daps) == 1
    assert ready.dap.calls[mark:] == [], "nothing reaches the simulation"
    change = ready.sim.program_change
    assert change is not None and change.cause == "save"
    assert "CLICK saved a new program" in change.text
    assert change.actions == ("run_time_edit", "stop_and_write")
    assert [e.kind for e in ready.events].count("desired") == 1, "offered once"

    ready.dap.frame(mode="stop", running=False)
    ready.scheduler.run_ready()
    assert ready.sim.program_change.actions == ("write",), "in STOP there is one way to write"


def test_a_save_is_offered_once_its_build_is_done(ready):
    from clicknick.simulation_session import WATCH_MS

    ready.open()
    ready.saves += 1
    ready.analysis._generation += 1
    ready.analysis._status = AnalysisStatus.BUILDING
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None

    ready.analysis._status = AnalysisStatus.READY
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save"
    assert len(ready.daps) == 1


def test_run_time_edit_reloads_in_place_and_keeps_running(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert len(ready.daps) == 1 and ("terminate",) not in ready.dap.calls, "no relaunch"
    # One planned reload (pyrung pauses first); the force and the link keep their names.
    assert _calls_since(ready.dap, mark) == [
        ("reload",),
        ("patch", {"X001": True}),
        ("continue",),
    ]
    assert ready.dap.plans == [
        {"forces": {"Y001": "Y001"}, "links": {"X002": {"en": "Y001", "fb": "X002"}},
         "declared": {}},
    ]  # fmt: skip
    assert ready.sim.program_change is None
    assert "Reloaded at scan 7" in ready.messages()
    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert _echoes(ready)[-1] == "reload"


def _motor_running(ready) -> None:
    """Y001 named Motor, in RUN with a force on it and a bench link it enables."""
    _name(ready, "Y001", "Motor")
    _running_with_settings(ready)
    ready.dap.frame(forces={"Motor": True})  # pyrung lists forces by tag name
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"Y001": True}


def test_a_write_moves_onto_the_new_name_only_what_a_rename_would_carry_away(ready):
    _motor_running(ready)
    _rebuild(ready, {"Y001": "MotorRun"})
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [
        ("reload",),
        ("patch", {"X001": True}),
        ("continue",),
    ], "nothing is released and sent again around the reload"
    assert ready.dap.plans[-1] == {
        "forces": {"Motor": "MotorRun"},
        "links": {"X002": {"en": "MotorRun", "fb": "X002"}},  # its enable, Y001, was Motor
        "declared": {},
    }
    assert ready.dap.forces == {"MotorRun": True}
    assert ready.dap.bench["X002"]["enable"] == "MotorRun"
    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.to_tag("Y001") == "MotorRun"
    assert ready.sim.notice == (
        "Kept under new names: Motor -> MotorRun (Y001), "
        "the link on X002 now comes from MotorRun (was Motor)."
    )


def test_stop_and_write_goes_through_stop_to_run_in_the_same_process(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    mark = len(ready.dap.calls)

    ready.sim.stop_and_write()
    ready.scheduler.run_ready()

    assert len(ready.daps) == 1 and ("terminate",) not in ready.dap.calls, "no relaunch"
    assert _calls_since(ready.dap, mark) == [
        ("reload",),
        ("set_mode", "stop", None),
        ("set_mode", "run", {"X001": True}),
        ("continue",),
    ]
    assert ready.sim.program_change is None
    assert ready.dap.forces == {"Y001": True}, "kept through STOP -> RUN (keepForcesOnRun)"


def test_write_in_stop_reloads_and_stays_in_stop(ready):
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.force("Y001", True)
    _rebuild(ready)
    assert ready.sim.program_change.actions == ("write",)
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()  # offered only in RUN
    ready.scheduler.run_ready()
    ready.sim.stop_and_write()
    ready.scheduler.run_ready()
    assert ready.dap.calls[mark:] == []

    ready.sim.write_program()
    ready.scheduler.run_ready()
    assert _calls_since(ready.dap, mark) == [("reload",)], "pyrung's reload keeps STOP"
    assert len(ready.daps) == 1
    assert ready.sim.program_change is None
    assert ready.sim.forces == {"Y001": True}


def test_write_while_stepping_keeps_the_values_and_stays_stepping(ready):
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.set_switch_position("step")
    ready.dap.frame(mode="run", running=False)
    ready.scheduler.run_ready()
    _rebuild(ready)
    assert ready.sim.program_change.actions == ("write",)
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",), ("patch", {"X001": True})]
    assert ready.sim.switch_position == "step"


def test_a_console_reload_writes_for_the_mode_it_is_in(ready):
    ready.open()
    _rebuild(ready)
    mark = len(ready.dap.calls)
    ready.sim.reload()
    ready.scheduler.run_ready()
    assert _calls_since(ready.dap, mark) == [("reload",)]

    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    mark = len(ready.dap.calls)
    ready.sim.reload()
    ready.scheduler.run_ready()
    assert _calls_since(ready.dap, mark) == [("reload",), ("continue",)]


def test_frames_name_tags_as_the_written_program_does_from_its_answer_on(ready, tmp_path):
    """X001 Start renamed StartPB and X005 named Start: `Start` means X001 until it is written."""
    _name(ready, "X001", "Start")
    ready.sim.set_state_location("Line1", None)
    ready.open()
    ready.dap.frame(forces={})
    ready.scheduler.run_ready()
    _rebuild(ready, {"X001": "StartPB", "X005": "Start"})

    ready.dap.frame(forces={"Start": True})  # `force Start 1` in the Console
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"X001": True}, "the running program's Start is X001"
    assert ready.sim.to_tag("X001") == "Start"
    ready.scheduler.fire(SAVE_DELAY_MS)
    assert dict(load_state(tmp_path / "app" / "Line1.toml").forces) == {"X001": True}

    ready.sim.write_program()
    ready.scheduler.run_ready()
    assert ready.dap.plans[-1]["forces"] == {"Start": "StartPB"}, "X001's, under its new name"
    assert ready.dap.forces == {"StartPB": True}, "not on X005, the new Start"
    assert ready.sim.to_tag("X001") == "StartPB"
    ready.dap.frame(forces={"StartPB": True})
    ready.scheduler.run_ready()
    ready.dap.frame(forces={"StartPB": True, "Start": True})  # `force Start 1` again
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"X001": True, "X005": True}


class _GoneAfterTerminate(FakeDap):
    """Like DapService: once terminated, every request fails."""

    gone = False

    def terminate(self):
        super().terminate()
        self.gone = True

    def _check(self, name: str) -> None:
        if self.gone:
            raise RuntimeError(f"{name}: simulation is not running")

    def force(self, tag, value):
        self._check("pyrungForce")
        return super().force(tag, value)

    def link(self, feedback, enable, **kwargs):
        self._check("pyrungLink")
        return super().link(feedback, enable, **kwargs)

    def unlink(self, feedback):
        self._check("pyrungUnlink")
        return super().unlink(feedback)

    def set_links(self, **kwargs):
        self._check("pyrungSetLinks")
        return super().set_links(**kwargs)

    def list_links(self):
        self._check("pyrungListLinks")
        return super().list_links()


def _queued(harness: Harness) -> list:
    """Hold the ordered action worker's jobs until the test runs them."""
    jobs: list = []
    harness.sim._run_serial = jobs.append
    original = harness.sim._dap_factory

    def factory(**callbacks):
        original(**callbacks)
        dap = _GoneAfterTerminate(**callbacks)
        dap.program_names = harness.workspace_names
        dap.launch_hook = harness.launch_hook
        harness.daps[-1] = dap
        return dap

    harness.sim._dap_factory = factory
    return jobs


def _run_jobs(harness: Harness, jobs: list) -> None:
    harness.scheduler.run_ready()
    while jobs:
        while jobs:
            jobs.pop(0)()
        harness.scheduler.run_ready()


def test_internal_forces_whose_name_moves_are_listed_before_the_write_and_released(ready):
    _name(ready, "C1", "Mode")
    _name(ready, "DS1", "Speed")
    _name(ready, "DS2", "Level")
    ready.open()
    for address, value in (("C1", True), ("DS1", 5), ("DS2", 7)):
        ready.sim.force(address, value)
    ready.dap.frame(forces={"Mode": True, "Speed": 5, "Level": 7})
    ready.scheduler.run_ready()
    _rebuild(ready, {"C1": "Auto", "DS1": "Spare", "DS5": "Speed"})

    change = ready.sim.program_change
    notice = "1 force: Speed (now on DS5, was DS1). Kept under new names: Mode -> Auto (C1)."
    assert f"Writing releases {notice}" in change.text, "listed before the user writes"
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",)]
    assert ready.dap.plans[-1]["forces"] == {
        "Mode": "Auto",  # C1 renamed: the force stays on it
        "Speed": None,
        "Level": "Level",
    }
    assert ready.dap.forces == {"Auto": True, "Level": 7}
    assert ready.sim.forces == {"DS2": 7, "C1": True}
    assert ready.sim.notice == f"Released {notice}"


def test_a_write_is_refused_while_a_rung_clicknick_cannot_read_is_in_the_workspace(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    _record_unreadable(ready.analysis.project_dir, 4)
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.dap.calls[mark:] == [], "the old program runs on"
    notice = ready.sim.notice or ""
    assert notice.startswith("Cannot write the program: ClickNick cannot read this rung")
    assert "Conf_Compare rung 4" in notice
    assert notice.endswith("The simulation still runs the previous program.")
    assert not ready.sim.writing


def _save_that_does_not_convert(ready, monkeypatch, tmp_path) -> None:
    """CLICK saved, and the real build() could not convert the program."""
    from clicknick.services import analysis_service

    def fail(*_args, **_kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(analysis_service, "_build_graph", fail)
    with pytest.raises(TypeError):
        ready.analysis.build(tmp_path / "scr", None)


def test_a_console_reload_of_a_save_that_did_not_convert_is_refused(ready, monkeypatch, tmp_path):
    from clicknick.simulation_session import WATCH_MS

    ready.open()
    _save_that_does_not_convert(ready, monkeypatch, tmp_path)
    ready.scheduler.fire(WATCH_MS)
    mark = len(ready.dap.calls)

    ready.sim.reload()
    ready.scheduler.run_ready()

    assert ready.dap.calls[mark:] == []
    assert "Cannot write the program" in ready.messages("error")
    assert "TypeError: boom" in (ready.sim.notice or "")


def test_restart_refuses_a_workspace_that_cannot_start_and_keeps_the_simulation(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    _record_unreadable(ready.analysis.project_dir, 4)

    ready.sim.restart()
    ready.scheduler.run_ready()

    assert len(ready.daps) == 1 and ("terminate",) not in ready.dap.calls
    assert ready.sim.is_ready
    assert "Cannot restart the simulation: ClickNick cannot read" in ready.messages("error")

    ready.analysis._status = AnalysisStatus.BUILDING
    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 1
    assert "still being converted" in (ready.sim.notice or "")

    ready.analysis._status = AnalysisStatus.FAILED  # the save did not convert
    ready.analysis._error = "TypeError: boom"
    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 1 and ready.sim.is_ready
    assert "TypeError: boom" in (ready.sim.notice or "")


def test_a_console_force_the_last_frame_did_not_show_is_kept(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    ready.dap.forces = {**ready.dap.forces, "C1": True}  # `force C1 1`, before any frame

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.dap.forces == {"Y001": True, "C1": True}
    assert ready.sim.forces == {"Y001": True, "C1": True}


def test_a_console_unforce_the_last_frame_did_not_show_is_not_forced_again(ready):
    _motor_running(ready)
    _rebuild(ready, {"Y001": "MotorRun"})
    ready.dap.forces = {}  # `unforce Motor`, before any frame
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert not any(call[0] == "force" for call in ready.dap.calls[mark:])
    assert ready.dap.forces == {}
    assert ready.sim.forces == {}


def test_a_bench_link_follows_its_enable_name_to_its_new_address(ready):
    _name(ready, "Y001", "Motor")
    ready.open()
    ready.sim.link("X002", ON_DELAY_LINK)
    _frame(ready)
    _rebuild(ready, {"Y001": "MotorRun", "Y002": "Motor"})
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",)]
    assert ready.dap.bench["X002"]["enable"] == "Motor"
    assert "The link on X002 now follows Motor on Y002 (was Y001)." in (ready.sim.notice or "")
    assert ready.sim.bench_links == {"X002": BenchLink("Y002", response=response(on_delay="1s"))}


def test_a_save_during_the_write_keeps_the_old_names_and_offers_it_again(ready):
    _name(ready, "X001", "Start")
    _running_with_settings(ready)
    _rebuild(ready, {"X001": "StartPB"})

    ready.sim.run_time_edit()
    _rebuild(ready)  # CLICK saved again before pyrung's answer was handled
    ready.scheduler.run_ready()

    assert "changed while it was written" in ready.messages("error")
    assert ready.sim.to_tag("X001") == "Start"
    change = ready.sim.program_change
    assert change is not None and change.cause == "save"
    assert change.actions == ("run_time_edit", "stop_and_write")


def test_writes_that_cannot_start_say_why(ready):
    ready.sim.reload()
    assert "Cannot write the program: the simulation is not running." in ready.messages("error")

    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    _rebuild(ready)
    ready.sim.write_program()
    ready.sim.reload()
    assert "The program is being written to the simulation." in ready.messages("error")
    _run_jobs(ready, jobs)
    assert ready.dap.calls.count(("reload",)) == 1


def test_only_writes_from_the_simulator_echo_reload(ready):
    ready.open()
    _rebuild(ready)
    ready.sim.reload()  # the Console's own `reload`
    ready.scheduler.run_ready()
    assert "reload" not in _echoes(ready)

    _rebuild(ready)
    ready.sim.write_program()
    ready.scheduler.run_ready()
    assert _echoes(ready)[-1] == "reload"


def test_while_writing_there_is_nothing_to_click_and_the_switch_stays(ready):
    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    ready.sim.set_switch_position("run")
    _run_jobs(ready, jobs)
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    _rebuild(ready)

    ready.sim.run_time_edit()
    assert ready.sim.writing
    assert ready.sim.program_change.actions == ()
    ready.dap.frame(mode="run", running=False)  # paused for the reload
    ready.scheduler.run_ready()
    assert ready.sim.switch_position == "run", "no STEP in between"

    _run_jobs(ready, jobs)
    assert not ready.sim.writing
    assert ready.sim.program_change is None


def test_a_rebuild_without_a_save_is_offered_as_a_rebuild(ready):
    ready.open()
    _rebuild(ready, saved=False)  # Reload from CLICK, or a Sync
    change = ready.sim.program_change
    assert change.cause == "rebuilt"
    assert "rebuilt from CLICK's last save (Reload from CLICK or a Sync)" in change.text
    assert change.actions == ("write",)


def test_a_failed_write_changes_nothing_and_offers_a_restart(ready):
    _name(ready, "X001", "Start")
    _motor_running(ready)
    _rebuild(ready, {"X001": "StartPB", "Y001": "MotorRun"})
    ready.dap.reload_error = DapRequestError("Reload failed: invalid syntax (main.py, line 3)")
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert len(ready.daps) == 1
    # pyrung's failed reload changed nothing: there is nothing to send again.
    assert _calls_since(ready.dap, mark) == [("reload",), ("continue",)], "RUN on the old program"
    assert ready.dap.forces == {"Motor": True}
    assert ready.dap.bench["X002"]["enable"] == "Motor"
    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert "invalid syntax" in ready.messages("error")
    assert ready.sim.to_tag("X001") == "Start"
    change = ready.sim.program_change
    assert change.cause == "save" and "invalid syntax" in change.text
    assert change.actions == ("run_time_edit", "stop_and_write", "restart")

    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 2
    assert ready.sim.program_change is None
    assert ready.sim.to_tag("X001") == "StartPB"


def test_a_save_that_does_not_convert_keeps_the_old_program_running(ready, monkeypatch, tmp_path):
    from clicknick.simulation_session import WATCH_MS

    ready.open()
    _save_that_does_not_convert(ready, monkeypatch, tmp_path)
    ready.scheduler.fire(WATCH_MS)

    assert ready.sim.is_ready
    assert ("terminate",) not in ready.dap.calls
    change = ready.sim.program_change
    assert change is not None and change.cause == "unconverted"
    assert "TypeError: boom" in change.text and change.actions == ()

    _rebuild(ready)  # the next save converts
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save"
    assert len(ready.daps) == 1


def test_restart_starts_over_with_the_users_settings(ready, tmp_path):
    _running_with_settings(ready)
    ready.snapshot = {"X001": True}
    data = tmp_path / "line1_data.csv"
    data.write_text("x", encoding="utf-8")
    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()
    ready.dap.frame(mode="run", running=True, forces={"Y001": True})
    ready.scheduler.run_ready()
    _rebuild(ready)
    launches = len(ready.daps)

    ready.sim.restart()
    ready.scheduler.run_ready()

    assert len(ready.daps) == launches + 1, "one relaunch"
    assert ("terminate",) in ready.daps[-2].calls
    launch = ready.dap.calls[0]
    assert launch[0] == "launch" and launch[2]["snapshot_path"] == data
    calls = [call[:3] for call in ready.dap.calls[1:]]
    assert calls == [
        ("link", "X002", "Y001"),
        ("force", "Y001", True),
        ("set_mode", "run", {"X001": True}),
        ("continue",),
    ]
    assert ready.sim.program_change is None, "it runs the newer program"


def test_console_releases_while_click_saves_are_kept(ready):
    """`unforce Y001` and `restore X002` in the Console while CLICK's save builds."""
    from clicknick.simulation_session import WATCH_MS

    ready.open()
    ready.sim.force("Y001", True)
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.dap.frame(forces={"Y001": True})
    ready.scheduler.run_ready()
    ready.analysis._generation += 1
    ready.analysis._status = AnalysisStatus.BUILDING

    ready.dap.restore_link("X002")
    ready.dap.frame(forces={})
    ready.scheduler.run_ready()
    assert ready.sim.forces == {}
    assert ready.sim.bench_links == {}

    ready.analysis._status = AnalysisStatus.READY
    ready.scheduler.fire(WATCH_MS)
    ready.sim.write_program()
    ready.scheduler.run_ready()
    after = ready.dap.calls[ready.dap.calls.index(("reload",)) :]
    assert not any(call[0] in ("force", "link") for call in after)
    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 2
    assert not any(call[0] in ("force", "link") for call in ready.dap.calls)


def test_console_forces_and_links_made_while_click_saves_are_kept(ready):
    from clicknick.simulation_session import WATCH_MS

    ready.open()
    ready.sim.force("Y001", True)
    ready.dap.frame(forces={"Y001": True})
    ready.scheduler.run_ready()
    ready.analysis._generation += 1
    ready.analysis._status = AnalysisStatus.BUILDING

    # `force C1 true` and `link X002 Y001` in the Console while the save builds
    ready.dap.bench["X002"] = {"enable": "Y001", "enabled": True, "response": {}}
    ready.dap.links_revision += 1
    ready.dap.frame(forces={"Y001": True, "C1": True})
    ready.scheduler.run_ready()

    ready.analysis._status = AnalysisStatus.READY
    ready.scheduler.fire(WATCH_MS)
    ready.sim.write_program()
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"Y001": True, "C1": True}
    assert "X002" in ready.sim.bench_links
    assert ready.dap.forces == {"Y001": True, "C1": True}, "pyrung carried them"
    assert "X002" in ready.dap.bench


def test_console_changes_while_a_build_fails_to_start_are_followed(ready):
    from clicknick.simulation_session import WATCH_MS

    ready.open()
    ready.sim.force("Y001", True)
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.dap.frame(forces={"Y001": True})
    ready.scheduler.run_ready()

    ready.analysis.mark_building()
    # `unforce Y001`, `force C1 true` and `unlink X002` in the Console
    ready.dap.bench.pop("X002")
    ready.dap.links_revision += 1
    ready.dap.frame(forces={"C1": True})
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"C1": True}
    assert ready.sim.bench_links == {}

    ready.analysis.mark_failed("no saved ladder files")  # failed before build() ran
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == 1
    assert ready.sim.forces == {"C1": True}


def _plc_source(ready) -> Path:
    main = ready.analysis.project_dir / "src" / "plc" / "main.py"
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text("rung = 1\n", encoding="utf-8")
    return main


def _edit(path: Path, text: str) -> None:
    import os

    path.write_text(text, encoding="utf-8")
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))


def test_an_edit_to_the_workspace_source_is_offered_until_written(ready):
    from clicknick.simulation_session import WATCH_MS

    main = _plc_source(ready)
    ready.open()
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None

    _edit(main, "rung = 2\n")
    ready.scheduler.fire(WATCH_MS)
    change = ready.sim.program_change
    assert change is not None and change.cause == "source"
    assert "The workspace's ladder source changed" in change.text
    assert change.actions == ("write",)
    assert len(ready.daps) == 1 and ("reload",) not in ready.dap.calls

    ready.sim.write_program()
    ready.scheduler.run_ready()
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None
    assert len(ready.daps) == 1


def test_a_source_edit_undone_is_not_offered(ready):
    from clicknick.simulation_session import WATCH_MS

    main = _plc_source(ready)
    ready.open()
    _edit(main, "rung = 2\n")
    ready.scheduler.fire(WATCH_MS)
    _edit(main, "rung = 1\n")
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None


def test_a_click_save_that_rewrites_the_source_is_offered_as_a_save(ready):
    from clicknick.simulation_session import WATCH_MS

    main = _plc_source(ready)
    ready.open()
    ready.saves += 1
    ready.analysis._generation += 1
    ready.analysis._status = AnalysisStatus.BUILDING
    _edit(main, "rung = 3\n")  # the build publishes the new source
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None, "still building"

    _publish(ready.analysis, ready.analysis._result)
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save"


def test_a_restore_request_that_goes_unanswered_does_not_stop_the_rest(ready):
    from clicknick.services.dap_service import DapUnavailableError

    ready.open()
    ready.sim.force("Y001", True)
    ready.sim.force("C1", True)
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()

    def hang() -> None:
        dap = ready.dap
        real_force, real_list = dap.force, dap.list_links
        listed: list[int] = []

        def force(tag, value):
            if tag == "Y001":
                raise DapUnavailableError("pyrungForce: no response from simulation")
            real_force(tag, value)

        def list_links():
            if not listed:
                listed.append(1)
                raise DapUnavailableError("pyrungListLinks: no response from simulation")
            return real_list()

        dap.force = force
        dap.list_links = list_links

    ready.launch_hook = hang
    ready.sim.restart()
    ready.scheduler.run_ready()

    assert ("force", "C1", True) in ready.dap.calls
    assert [call[0] for call in ready.dap.calls][-2:] == ["set_mode", "continue"]
    assert ready.sim.forces == {"Y001": True, "C1": True}
    assert "no answer for the force on Y001" in ready.messages("error")
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}

    _frame(ready)  # reads the links again
    ready.dap.unlink("X002")  # `unlink X002` in the Console
    _frame(ready)
    assert ready.sim.bench_links == {}


# ----------------------------------------------------------------------
# Stopping while the simulation starts or restores settings
# ----------------------------------------------------------------------


def test_closing_while_the_simulation_starts_terminates_it(ready):
    ready.launch_hook = ready.sim.close
    ready.sim.turn_on()
    ready.scheduler.run_ready()
    assert ("terminate",) in ready.dap.calls


def test_stopping_while_settings_are_restored_keeps_them(ready, tmp_path):
    save_state(
        tmp_path / "app" / "Line1.toml",
        SimulatorState(
            forces={"Y001": True, "C1": True},
            links={"X002": ON_DELAY_LINK},
            modules=("cpu:C0-02DD1-D",),
        ),
    )
    jobs = _queued(ready)
    ready.sim.set_state_location("Line1", None)
    ready.open()

    ready.sim.turn_off()  # before the worker re-applied anything
    _run_jobs(ready, jobs)

    assert ready.sim.forces == {"Y001": True, "C1": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert "Could not restore" not in ready.messages("error")
    ready.scheduler.fire(SAVE_DELAY_MS)
    saved = load_state(tmp_path / "app" / "Line1.toml")
    assert dict(saved.forces) == {"Y001": True, "C1": True}
    assert dict(saved.links) == {"X002": ON_DELAY_LINK}


def test_a_force_sent_to_a_simulation_that_restarted_is_kept(ready):
    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    ready.sim.force("Y001", True)
    ready.sim.link("X002", ON_DELAY_LINK)

    ready.sim.restart()  # the PLC data changed before the worker sent them
    _run_jobs(ready, jobs)

    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ("force", "Y001", True) in ready.dap.calls
    assert ready.messages("error") == ""


def test_a_force_the_simulation_never_answered_is_kept(ready):
    from clicknick.services.dap_service import DapUnavailableError

    ready.open()
    errors: list[str] = []

    def hung(tag, value):
        raise DapUnavailableError("pyrungForce: no response from simulation")

    ready.dap.force = hung
    ready.sim.force("Y001", True, on_error=errors.append)
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"Y001": True}, "only a refusal undoes it"
    assert errors == []
    assert "no response from simulation" in ready.messages("error")


def test_a_refused_link_undoes_only_itself(ready):
    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    ready.dap.refuse_links["X001"] = "X001 is written by the program at Main:R3"
    ready.sim.link("X001", ON_DELAY_LINK)
    ready.sim.link("X002", ON_DELAY_LINK)  # chosen before the first was refused
    _run_jobs(ready, jobs)
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}


# ----------------------------------------------------------------------
# Restored switches, and a simulation that dies as it starts
# ----------------------------------------------------------------------


def test_switches_on_unassigned_inputs_wait_for_the_analysis(ready, tmp_path):
    from pyclickplc.addresses import get_addr_key

    ready.analysis._result.tag_to_addr_key["Aux"] = get_addr_key("X", 201)
    ready.analysis._result.graph.tag_roles["Aux"] = None
    save_state(
        tmp_path / "app" / "Line1.toml",
        SimulatorState(switches={"X001": True, "X201": True}, modules=("cpu:C0-02DD1-D",)),
    )
    result = ready.analysis._result
    ready.analysis._result = None  # the app just connected; the first build runs
    ready.analysis._status = AnalysisStatus.BUILDING
    ready.sim.set_state_location("Line1", None)
    ready.open()
    assert ready.sim.notice is None

    ready.analysis._result = result
    ready.analysis._status = AnalysisStatus.READY
    ready.analysis._generation += 1
    ready.sim.refresh_layout()

    assert "X201" in ready.sim.layout.addresses("input")
    assert ready.sim.switch_on("X201")
    assert ready.sim.notice is None
    ready.scheduler.fire(SAVE_DELAY_MS)
    assert dict(load_state(tmp_path / "app" / "Line1.toml").switches) == {
        "X001": True,
        "X201": True,
    }


def test_a_simulation_that_dies_as_it_starts_is_reported(ready):
    def die() -> None:
        ready.dap.stderr_text = "Traceback: crashed"
        ready.dap.callbacks["on_state"](SimpleNamespace(value="error"), None)

    ready.launch_hook = die
    ready.open()
    assert ready.sim.status is SimStatus.FAILED
    assert not ready.sim.is_ready
    assert ready.sim.error_detail == "Traceback: crashed"
    assert ("terminate",) in ready.dap.calls
    assert "stopped unexpectedly" in ready.messages("error")


# ----------------------------------------------------------------------
# Values through a write, on pyrung's own adapter (in process)
# ----------------------------------------------------------------------

_VALUES_PROGRAM = """\
import warnings
warnings.simplefilter("ignore")
from pyrung.core import Bool, Int, PLC, Program, Rung, calc, out
start = Bool("Start")
light = Bool("Light")
ret = Int("Ret", retentive=True)
nonret = Int("NonRet", retentive=False)
with Program(strict=False) as prog:
    with Rung(start):
        out(light)
    with Rung():
        calc(ret + 1, ret)
    with Rung():
        calc(nonret + 1, nonret)
runner = PLC(prog, dt=0.010)
"""


def _adapter_dap_class():
    """A DapService that talks to pyrung's DAPAdapter in process, scanning only when told."""
    import io

    adapter_module = pytest.importorskip("pyrung.dap.adapter")
    from pyrung.dap.protocol import read_message

    from clicknick.services.dap_service import DapService

    class AdapterDap(DapService):
        def launch(self, project_dir, **_kwargs):
            self._out = io.BytesIO()
            self._adapter = adapter_module.DAPAdapter(in_stream=io.BytesIO(), out_stream=self._out)
            self._proc = object()  # requests go to the adapter
            arguments = {
                "program": str(project_dir / "run.py"),
                "startMode": "stop",
                "keepForcesOnRun": True,
            }
            assert self._send_and_wait("launch", arguments)["success"]
            assert self._send_and_wait("configurationDone")["success"]

        def terminate(self):
            self._proc = None

        def _send_and_wait(self, command, arguments=None, timeout=10.0):
            self._seq += 1
            self._adapter.handle_request(
                {"seq": self._seq, "type": "request", "command": command,
                 "arguments": arguments or {}}
            )  # fmt: skip
            reader = io.BytesIO(self._out.getvalue())
            self._out.seek(0)
            self._out.truncate(0)
            responses = []
            while (message := read_message(reader)) is not None:
                if message.get("type") == "response":
                    responses.append(message)
            return responses[-1] if responses else None

        # RUN free-runs only as a flag; the test scans.
        def continue_(self):
            self._running = True

        def pause(self):
            self._running = False

        def scan(self, count: int = 1) -> None:
            for _ in range(count):
                assert self._send_and_wait("pyrungStepScan")["success"]

        def frame(self) -> None:
            runner = self._adapter._runner
            self._mode = str(getattr(runner.mode, "value", runner.mode))
            self._forces = dict(runner.forces)
            self._on_frame()

        def tag(self, name):
            return self._adapter._runner.current_state.tags.get(name)

    return AdapterDap


@pytest.fixture()
def on_pyrung(tmp_path):
    """The harness, with the simulation on pyrung's adapter running a counting program."""
    dap_class = _adapter_dap_class()
    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project))
    (project / "run.py").write_text(_VALUES_PROGRAM, encoding="utf-8")
    for address, tag in (("X001", "Start"), ("Y001", "Light"), ("DS1", "Ret"), ("DS2", "NonRet")):
        _name(harness, address, tag)

    def factory(**callbacks):
        dap = dap_class(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.open()
    dap = harness.dap
    dap.frame()  # the baseline frames are compared with
    harness.scheduler.run_ready()
    harness.sim.set_switch_position("run")
    harness.scheduler.run_ready()
    dap.scan(5)
    dap.force("Light", True)  # `force Light 1` in the Console
    dap.scan(1)
    dap.frame()
    harness.scheduler.run_ready()
    assert harness.sim.switch_position == "run"
    assert harness.sim.forces == {"Y001": True}
    assert (dap.tag("Ret"), dap.tag("NonRet")) == (6, 6)
    return harness


def test_run_time_edit_keeps_every_value_and_the_force(on_pyrung):
    dap = on_pyrung.dap
    _rebuild(on_pyrung)
    on_pyrung.sim.run_time_edit()
    on_pyrung.scheduler.run_ready()
    dap.scan(1)

    assert (dap.tag("Ret"), dap.tag("NonRet"), dap.tag("Light")) == (7, 7, True)
    assert dict(dap._adapter._runner.forces) == {"Light": True}
    assert on_pyrung.sim.program_change is None


def test_stop_and_write_clears_non_retentive_values_and_keeps_the_force(on_pyrung):
    dap = on_pyrung.dap
    _rebuild(on_pyrung)
    on_pyrung.sim.stop_and_write()
    on_pyrung.scheduler.run_ready()
    dap.scan(1)

    assert (dap.tag("Ret"), dap.tag("NonRet"), dap.tag("Light")) == (7, 1, True)
    assert dict(dap._adapter._runner.forces) == {"Light": True}
    assert dap.mode == "run"


def test_a_link_that_lands_where_a_followed_name_went_is_dropped(ready):
    """Start moves from X001 to X002, which has its own cut: Start's link wins."""
    _name(ready, "X001", "Start")
    _name(ready, "Y001", "Motor")
    ready.open()
    ready.sim.link("X001", BenchLink("Y001"))
    ready.dap.bench["X002"] = {"enable": None, "enabled": True}  # `unlink X002` in the Console
    ready.dap.links_revision += 1
    _frame(ready)
    _rebuild(ready, {"X001": "Begin", "X002": "Start"})
    assert "The cut on X002 is dropped for the link on Start." in ready.sim.program_change.text
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",)]
    assert ready.dap.plans[-1]["links"] == {"Start": {"en": "Motor", "fb": "Start"}, "X002": None}
    assert ready.dap.bench == {"Start": {"enable": "Motor", "enabled": True, "trigger": None,
                                         "response": {}}}  # fmt: skip
    assert ready.sim.bench_links == {"X002": BenchLink("Y001")}
    assert "The cut on X002 is dropped" in (ready.sim.notice or "")


def test_a_write_pyrung_never_answers_sends_nothing_by_name(ready):
    from clicknick.services.dap_service import DapUnavailableError

    _name(ready, "C1", "Run")
    ready.open()
    ready.sim.force("C1", True)
    ready.dap.frame(forces={"Run": True})
    ready.scheduler.run_ready()
    _rebuild(ready, {"C1": "Spare", "C2": "Run"})
    ready.dap.reload_error = DapUnavailableError("evaluate: no response from simulation")
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",)], (
        "`force Run` would land on C2 if pyrung did load the new program"
    )
    assert ready.dap.plans[-1]["forces"] == {"Run": None}
    assert "which program the simulation runs is unknown" in ready.messages("error")
    assert ready.sim.program_change.actions[-1] == "restart"


def _console_command(ready, run=lambda: "done"):
    """Start a Console command; returns (finish it, what its done callback got)."""
    started: list = []
    got: list = []
    ready.sim._run_background = lambda target, _name: started.append(target)
    ready.sim.run_console_command(run, got.append)
    [worker] = started

    def finish() -> None:
        try:
            worker()
        finally:
            ready.scheduler.run_ready()

    return finish, got


def test_no_write_while_a_console_command_runs(ready):
    ready.open()
    _rebuild(ready)
    finish, got = _console_command(ready)
    assert ready.sim.program_change.actions == ()
    mark = len(ready.dap.calls)
    ready.sim.write_program()
    ready.sim.reload()
    ready.scheduler.run_ready()
    assert ready.dap.calls[mark:] == []
    assert "while a Console command runs" in ready.messages("error")

    finish()
    assert got == ["done"]
    assert ready.sim.program_change.actions == ("write",)
    ready.sim.reload()
    ready.scheduler.run_ready()
    assert ("reload",) in ready.dap.calls[mark:]


def test_with_no_console_command_in_flight_nothing_is_busy(ready):
    ready.open()
    _rebuild(ready)
    assert ready.sim.program_change.actions == ("write",)

    first, _ = _console_command(ready)
    second, _ = _console_command(ready)
    first()
    assert ready.sim.program_change.actions == (), "the second command is still in flight"
    second()
    assert ready.sim.program_change.actions == ("write",)


def test_a_console_command_that_raises_still_ends(ready):
    ready.open()
    _rebuild(ready)

    def boom():
        raise RuntimeError("boom")

    finish, got = _console_command(ready, boom)
    with pytest.raises(RuntimeError):
        finish()
    assert got == []
    assert ready.sim.program_change.actions == ("write",)


def test_a_write_pyrung_never_answers_keeps_the_switch_position_for_restart(ready):
    from clicknick.services.dap_service import DapUnavailableError

    _name(ready, "C1", "Run")
    ready.open()
    ready.sim.force("C1", True)
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True, forces={"Run": True})
    ready.scheduler.run_ready()
    _rebuild(ready, {"C1": "Spare", "C2": "Run"})
    ready.dap.reload_error = DapUnavailableError("evaluate: no response from simulation")

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    # The write paused it and never sent continue: frames show it stepping.
    ready.dap.frame(mode="run", running=False, forces={})
    ready.scheduler.run_ready()

    assert ready.sim.switch_position == "step"
    text = ready.sim.program_change.text
    assert "it may be paused" in text
    assert "If it runs the new program, it released the force on Run" in text
    assert ready.sim.program_change.actions[-1] == "restart"

    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 2
    assert [call[:2] for call in ready.dap.calls[1:]] == [
        ("force", "C1"),
        ("set_mode", "run"),
        ("continue",),
    ], "Restart starts in RUN, where the user had it, with the force on C1"


def _unanswered_run_time_edit(ready) -> None:
    """In RUN, a RUN Time Edit pyrung never answers; frames then show it paused."""
    from clicknick.services.dap_service import DapUnavailableError

    ready.open()
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    _rebuild(ready)
    ready.dap.reload_error = DapUnavailableError("evaluate: no response from simulation")
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    ready.dap.frame(mode="run", running=False)
    ready.scheduler.run_ready()
    ready.dap.reload_error = None
    assert ready.sim.switch_position == "step"


def test_choosing_step_where_the_switch_shows_it_ends_the_hold(ready):
    _unanswered_run_time_edit(ready)
    mark = len(ready.dap.calls)
    ready.sim.set_switch_position("step")
    assert ready.dap.calls[mark:] == [], "it already steps"
    assert ready.sim.program_change.actions == ("write", "restart")

    ready.sim.restart()
    ready.scheduler.run_ready()
    assert [call[:2] for call in ready.dap.calls[1:]] == [("set_mode", "run")], "Restart in STEP"


def test_while_the_switch_is_held_the_write_offered_is_for_the_users_position(ready):
    _unanswered_run_time_edit(ready)
    assert ready.sim.program_change.actions == ("run_time_edit", "stop_and_write", "restart")
    mark = len(ready.dap.calls)
    ready.sim.write_program()  # STEP's action: not what a write does here
    ready.scheduler.run_ready()
    assert ready.dap.calls[mark:] == []

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    calls = [call[0] for call in ready.dap.calls[mark:]]
    assert calls == ["reload", "continue"]


def test_moving_the_switch_after_an_unanswered_write_follows_frames_again(ready):
    from clicknick.services.dap_service import DapUnavailableError

    ready.open()
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    _rebuild(ready)
    ready.dap.reload_error = DapUnavailableError("evaluate: no response from simulation")
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    ready.dap.frame(mode="run", running=False)
    ready.scheduler.run_ready()

    ready.sim.set_switch_position("stop")
    ready.dap.frame(mode="stop", running=False)
    ready.scheduler.run_ready()
    ready.dap.frame(mode="run", running=False)  # the Console stepped it
    ready.scheduler.run_ready()
    ready.sim.restart()
    ready.scheduler.run_ready()
    assert [call[:2] for call in ready.dap.calls[1:]] == [("set_mode", "run")]


def test_no_restart_while_the_program_is_written(ready):
    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    _rebuild(ready)
    ready.sim.write_program()
    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 1
    assert "Cannot restart while the program is being written." in ready.messages("error")


def _data_file_saved_again(ready, data: Path) -> None:
    """CLICK wrote the PLC data dump again; the next watch tick sees it."""
    import os

    from clicknick.simulation_session import WATCH_MS

    later = data.stat().st_mtime + 5
    os.utime(data, (later, later))
    ready.scheduler.fire(WATCH_MS)


def _writing_with_plc_data(ready, tmp_path) -> tuple[list, Path]:
    """A simulation started from a PLC data file, with a write asked for and not answered."""
    jobs = _queued(ready)
    ready.open()
    data = tmp_path / "data.csv"
    data.write_text("a", encoding="utf-8")
    ready.sim.set_plc_data_path(data)
    _run_jobs(ready, jobs)
    _rebuild(ready)
    ready.sim.write_program()
    assert ready.sim.writing
    return jobs, data


@pytest.mark.parametrize("answer", ["written", "refused", "unanswered"])
def test_a_plc_data_change_during_a_write_relaunches_once_the_write_is_answered(
    ready, tmp_path, answer
):
    from clicknick.services.dap_service import DapUnavailableError

    jobs, data = _writing_with_plc_data(ready, tmp_path)
    if answer == "refused":
        ready.dap.reload_error = DapRequestError("Reload failed: invalid syntax")
    elif answer == "unanswered":
        ready.dap.reload_error = DapUnavailableError("evaluate: no response from simulation")
    daps = len(ready.daps)

    _data_file_saved_again(ready, data)
    assert len(ready.daps) == daps, "never in the middle of a write"
    assert "PLC data file changed. Reloading once the program is written." in ready.messages()
    assert "Cannot restart" not in ready.messages("error")

    _run_jobs(ready, jobs)
    assert len(ready.daps) == daps + 1
    assert ready.dap.calls[0][2]["snapshot_path"] == data
    assert ready.sim.is_ready

    _data_file_saved_again(ready, data)
    _run_jobs(ready, jobs)
    assert len(ready.daps) == daps + 2, "a change after the write relaunches as before"


def test_choosing_a_plc_data_file_during_a_write_starts_from_it_once_answered(ready, tmp_path):
    jobs, _data = _writing_with_plc_data(ready, tmp_path)
    daps = len(ready.daps)
    other = tmp_path / "other.csv"
    other.write_text("b", encoding="utf-8")

    ready.sim.set_plc_data_path(other)
    assert len(ready.daps) == daps
    assert "Cannot restart" not in ready.messages("error")

    _run_jobs(ready, jobs)
    assert len(ready.daps) == daps + 1
    assert ready.dap.calls[0][2]["snapshot_path"] == other


def test_a_plc_data_change_during_a_write_relaunches_once_if_it_already_relaunched(ready, tmp_path):
    jobs, data = _writing_with_plc_data(ready, tmp_path)
    daps = len(ready.daps)
    _data_file_saved_again(ready, data)

    ready.sim.relaunch()  # the workspace moved: this launch reads the data file
    _run_jobs(ready, jobs)
    assert len(ready.daps) == daps + 1
    assert ready.dap.calls[0][2]["snapshot_path"] == data


def test_a_plc_data_change_during_a_write_that_a_build_overtakes_relaunches_after_the_build(
    ready, tmp_path
):
    from clicknick.simulation_session import WATCH_MS

    jobs, data = _writing_with_plc_data(ready, tmp_path)
    daps = len(ready.daps)
    _data_file_saved_again(ready, data)
    ready.analysis._status = AnalysisStatus.BUILDING  # CLICK saved before the write's answer
    _run_jobs(ready, jobs)
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == daps, "no launch on a workspace being rebuilt"
    assert "still being converted" not in ready.messages("error")

    _rebuild(ready)
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == daps + 1
    assert ready.dap.calls[0][2]["snapshot_path"] == data
    _run_jobs(ready, jobs)
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == daps + 1, "relaunched once"


def test_a_plc_data_change_the_simulation_died_after_relaunches_once_with_the_build(
    ready, tmp_path
):
    from clicknick.simulation_session import WATCH_MS

    jobs, data = _writing_with_plc_data(ready, tmp_path)
    daps = len(ready.daps)
    _data_file_saved_again(ready, data)
    ready.analysis._status = AnalysisStatus.BUILDING
    _run_jobs(ready, jobs)
    ready.dap.callbacks["on_state"](SimpleNamespace(value="error"), None)
    ready.scheduler.run_ready()
    assert ready.sim.status is SimStatus.FAILED

    _rebuild(ready)  # _follow_program starts the simulation on it
    ready.scheduler.fire(WATCH_MS)
    _run_jobs(ready, jobs)
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == daps + 1
    assert ready.dap.calls[0][2]["snapshot_path"] == data


def test_a_modbus_port_change_during_a_write_relaunches_on_it_once_answered(ready):
    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    _rebuild(ready)
    ready.sim.write_program()
    daps = len(ready.daps)

    ready.sim.set_modbus_port(5020)
    assert len(ready.daps) == daps
    assert "Cannot restart" not in ready.messages("error")

    _run_jobs(ready, jobs)
    assert len(ready.daps) == daps + 1
    assert ready.dap.calls[0][2]["modbus"]["port"] == 5020

def test_a_plc_data_change_during_a_console_command_relaunches_at_once(ready, tmp_path):
    ready.open()
    data = tmp_path / "data.csv"
    data.write_text("a", encoding="utf-8")
    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()
    daps = len(ready.daps)
    finish, _got = _console_command(ready)
    ready.sim._run_background = lambda target, _name: target()  # the command stays in flight

    _data_file_saved_again(ready, data)
    ready.scheduler.run_ready()
    assert len(ready.daps) == daps + 1, "Restart does not wait for a Console command"
    finish()


# ----------------------------------------------------------------------
# The write is one planned reload (pyrungReload)
# ----------------------------------------------------------------------


def _refused_by_an_older_pyrung() -> DapRequestError:
    """What DapService raises when pyrung has no pyrungReload (before 0.16)."""
    from clicknick.services.dap_service import DapService

    class OlderPyrung(DapService):
        def _send_and_wait(self, command, arguments=None, timeout=10.0):
            return {"success": False, "message": f"Unsupported command: {command}"}

    dap = OlderPyrung()
    dap._proc = object()
    with pytest.raises(DapRequestError) as refused:
        dap.planned_reload({"forces": {}, "links": {}, "declared": {}})
    return refused.value


def test_a_pyrung_without_the_planned_reload_refuses_the_write_and_nothing_changes(ready):
    _name(ready, "X001", "Start")
    _motor_running(ready)
    _rebuild(ready, {"X001": "StartPB", "Y001": "MotorRun"})
    ready.dap.reload_error = _refused_by_an_older_pyrung()
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    # No release and re-apply around a plain reload instead.
    assert _calls_since(ready.dap, mark) == [("reload",), ("continue",)]
    assert ready.dap.forces == {"Motor": True}
    assert ready.dap.bench["X002"]["enable"] == "Motor"
    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.to_tag("X001") == "Start", "the old program runs on"
    change = ready.sim.program_change
    assert "pyrung 0.16.0 or later" in change.text
    assert "or later can). The simulation still runs the previous one." in ready.messages("error")
    assert change.actions == ("run_time_edit", "stop_and_write", "restart")


def test_a_reload_refused_in_stop_leaves_it_as_it_was(ready):
    ready.open()
    ready.sim.force("Y001", True)
    ready.dap.frame(forces={"Y001": True})
    ready.scheduler.run_ready()
    _rebuild(ready)
    ready.dap.reload_error = DapRequestError("Timed out waiting for execution to pause")
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",)], "no STOP, no forces sent again"
    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.switch_position == "stop"
    assert "Timed out waiting for execution to pause" in ready.sim.program_change.text
    assert ready.sim.program_change.actions == ("write", "restart")


def test_what_pyrung_could_not_keep_is_in_the_notice_and_is_not_kept(ready):
    _motor_running(ready)
    _rebuild(ready, {"Y001": "MotorRun"})
    ready.dap.reload_drops = {"Motor": ("type changed", "MotorRun is an Int in the new program")}

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.dap.forces == {}
    assert ready.sim.forces == {}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.notice == (
        "Kept under new names: the link on X002 now comes from MotorRun (was Motor). "
        "Could not keep the force on Motor: MotorRun is an Int in the new program."
    )


def test_a_console_force_pyrung_carried_without_a_plan_is_kept_by_its_name(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    real = ready.dap.planned_reload

    def late_force(plan):
        ready.dap.forces = {**ready.dap.forces, "C1": True}  # `force C1 1` just before
        return real(plan)

    ready.dap.planned_reload = late_force
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.sim.forces == {"Y001": True, "C1": True}


def test_a_force_changed_just_before_the_reload_keeps_the_value_pyrung_reports(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    real = ready.dap.planned_reload

    def late_force(plan):
        ready.dap.forces = {**ready.dap.forces, "Y001": False}  # `force Y001 0` just before
        return real(plan)

    ready.dap.planned_reload = late_force
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.sim.forces == {"Y001": False}


def test_the_programs_own_links_go_with_the_plan_under_their_addresss_new_name(ready):
    _name(ready, "X002", "Prox")
    _name(ready, "X003", "Door")
    _name(ready, "Y001", "Motor")
    ready.open()
    ready.dap.project = {"Prox": "Motor", "Door": "Motor", "Lamp": "Motor"}
    ready.dap.bench["Door"] = {"enable": None, "enabled": True}  # cut: its coil does not run
    _rebuild(ready, {"X002": "ProxSensor", "X003": "DoorSw"})

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert ready.dap.plans[-1]["declared"] == {"Prox": "ProxSensor"}


# A feedback on X002 that a bench link or the program's own link drives from Cmd (X001).
_LINK_PROGRAM = """\
import warnings
warnings.simplefilter("ignore")
from pyrung.core import Bool, PLC, Physical, Program, Rung, out
cmd = Bool({enable!r})
fb = {feedback}
with Program(strict=False) as prog:
    with Rung(cmd):
        out(Bool("Lamp"))
    with Rung(fb):
        out(Bool("Sink"))
runner = PLC(prog, dt=0.010)
"""


def _link_program(name: str, *, declared: bool, enable: str = "Cmd") -> str:
    if declared:
        feedback = f"Bool({name!r}, physical=Physical({name!r}, timed='100ms'), link={enable!r})"
    else:
        feedback = f"Bool({name!r})"
    return _LINK_PROGRAM.format(feedback=feedback, enable=enable)


def _timing_on_pyrung(tmp_path, *, declared: bool):
    """In RUN on pyrung's adapter, X002 Prox's timed link from Cmd part way through its 100 ms."""
    dap_class = _adapter_dap_class()
    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project))
    (project / "run.py").write_text(_link_program("Prox", declared=declared), encoding="utf-8")
    for address, tag in (("X001", "Cmd"), ("X002", "Prox")):
        _name(harness, address, tag)

    def factory(**callbacks):
        dap = dap_class(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.open()
    dap = harness.dap
    dap.frame()
    harness.scheduler.run_ready()
    harness.sim.set_switch_position("run")
    harness.scheduler.run_ready()
    if not declared:
        dap.link("Prox", "Cmd", response=(("timed", "100ms"),))  # `link Prox Cmd timed=100ms`
    dap.force("Cmd", True)
    dap.scan(3)
    dap.frame()
    harness.scheduler.run_ready()
    count = dap.tag("__tmd_on__Prox")
    assert 0 < count < 100
    return harness, count


@pytest.mark.parametrize(
    ("declared", "enable"),
    [(False, "Cmd"), (False, "Go"), (True, "Cmd"), (True, "Go")],
    ids=["bench link", "bench link and its enable", "program's link", "program's link and enable"],
)
def test_renaming_a_linked_input_while_it_times_keeps_its_timing(tmp_path, declared, enable):
    harness, count = _timing_on_pyrung(tmp_path, declared=declared)
    dap = harness.dap
    run = harness.analysis.project_dir / "run.py"
    run.write_text(_link_program("ProxSensor", declared=declared, enable=enable), encoding="utf-8")
    _rebuild(harness, {"X001": enable, "X002": "ProxSensor"})

    harness.sim.run_time_edit()
    harness.scheduler.run_ready()
    dap.scan(1)

    assert harness.sim.program_change is None
    assert dap.tag("__tmd_on__ProxSensor") == count + 10, "one 10 ms scan on, not from 0"
    assert dict(dap._adapter._runner.forces) == {enable: True}, "X001's force, on its new name"
    assert harness.sim.forces == {"X001": True}
    if declared:
        return
    assert list(dap._adapter._bench_links) == ["ProxSensor"]
    assert dap._adapter._bench_links["ProxSensor"].coupling.en_name == enable
    assert harness.sim.bench_links == {"X002": BenchLink("X001", response=response(timed="100ms"))}
    renamed = ["the link on Prox is now on ProxSensor"]
    if enable != "Cmd":
        renamed = [
            f"Cmd -> {enable} (X001)",
            *renamed,
            f"the link on Prox now comes from {enable} (was Cmd)",
        ]
    assert harness.sim.notice == f"Kept under new names: {', '.join(renamed)}."


# Two timed links the program declares: Start (X002) from Cmd, Begin (X003) from Go.
_TWO_LINKS_PROGRAM = """\
import warnings
warnings.simplefilter("ignore")
from pyrung.core import Bool, PLC, Physical, Program, Rung, out
cmd, go = Bool("Cmd"), Bool("Go")
start = Bool("Start", physical=Physical("Start", timed="100ms"), link="Cmd")
begin = Bool("Begin", physical=Physical("Begin", timed="100ms"), link="Go")
with Program(strict=False) as prog:
    with Rung(cmd):
        out(Bool("Lamp"))
    with Rung(go):
        out(Bool("Horn"))
    with Rung(start):
        out(Bool("Sink"))
    with Rung(begin):
        out(Bool("Drain"))
runner = PLC(prog, dt=0.010)
"""


def test_declared_links_whose_nicknames_and_comments_swap_keep_their_own_timing(tmp_path):
    dap_class = _adapter_dap_class()
    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project))
    (project / "run.py").write_text(_TWO_LINKS_PROGRAM, encoding="utf-8")
    for address, tag in (("X001", "Cmd"), ("X004", "Go"), ("X002", "Start"), ("X003", "Begin")):
        _name(harness, address, tag)

    def factory(**callbacks):
        dap = dap_class(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.open()
    dap = harness.dap
    dap.frame()
    harness.scheduler.run_ready()
    harness.sim.set_switch_position("run")
    harness.scheduler.run_ready()
    dap.force("Cmd", True)
    dap.scan(3)
    dap.force("Go", True)
    dap.scan(2)
    dap.frame()
    harness.scheduler.run_ready()
    start, begin = dap.tag("__tmd_on__Start"), dap.tag("__tmd_on__Begin")
    assert 0 < begin < start < 100, "both part way through, Start further on"

    # In CLICK, X002 and X003 swap nicknames and comments: each link keeps its name.
    (project / "csv").mkdir()
    CsvDataSource(str(project / "csv" / "nicknames.csv")).save_changes(
        [
            AddressRow("X", 2, nickname="Begin", comment="[link=Go, timed=100ms]"),
            AddressRow("X", 3, nickname="Start", comment="[link=Cmd, timed=100ms]"),
        ]
    )
    _rebuild(harness, {"X002": "Begin", "X003": "Start"})

    harness.sim.run_time_edit()
    harness.scheduler.run_ready()
    dap.scan(1)

    assert harness.sim.program_change is None
    assert dap.tag("__tmd_on__Start") == start + 10, "Start's coil, on X003 now"
    assert dap.tag("__tmd_on__Begin") == begin + 10, "Begin's coil, on X002 now"
    assert harness.sim.notice in (None, "")
