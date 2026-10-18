"""SimulationSession: lifecycle, the mode switch, forces, Modbus I/O and persistence.

Everything runs inline: a fake scheduler stands in for Tk, a fake DapService
for the pyrung subprocess and a fake ModbusService for the Modbus client.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.services.analysis_service import AnalysisResult, AnalysisService, AnalysisStatus
from clicknick.services.sim_hardware import build_panel_layout
from clicknick.services.sim_state import SimulatorState, load_state, save_state
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


class FakeDap:
    def __init__(self, **callbacks) -> None:
        self.callbacks = callbacks
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
        self.info = {"running": True, "host": "127.0.0.1", "port": 502, "clients": 1, "error": None}

    def launch(self, project_dir, **kwargs):
        self.calls.append(("launch", project_dir, kwargs))
        if self.launch_hook is not None:
            self.launch_hook()
        if self.launch_error is not None:
            raise self.launch_error

    def terminate(self):
        self.calls.append(("terminate",))

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

    def unforce(self, tag):
        self.calls.append(("unforce", tag))

    def clear_forces(self):
        self.calls.append(("clear_forces",))

    def patch(self, patches):
        self.calls.append(("patch", dict(patches)))

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
        self.writes: list[list] = []
        self.disconnected = False

    def connect(self, host, port, **kwargs):
        self.connected_with = {"host": host, "port": port, **kwargs}

    def set_poll_addresses(self, addresses):
        self.polled = list(addresses)

    def clear_poll_addresses(self):
        self.polled = []

    def write(self, values):
        self.writes.append(list(values))
        return [{"address": a, "ok": True, "error": None} for a, _v in values]

    def disconnect(self):
        self.disconnected = True


def _ready_analysis(project_dir: Path, *, generation: int = 1) -> AnalysisService:
    (project_dir / "run.py").write_text("x", encoding="utf-8")
    svc = AnalysisService()
    svc._result = AnalysisResult(
        graph=SimpleNamespace(tag_roles={}),
        program=MagicMock(),
        project_dir=project_dir,
        tag_to_addr_key={},
        addr_key_to_tag={},
    )
    svc._status = AnalysisStatus.READY
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
        )
        self.sim.add_listener(self.events.append)

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


def test_launch_starts_the_simulator_in_stop_with_a_modbus_server(ready):
    ready.open()
    _name, project_dir, kwargs = ready.dap.calls[0]
    assert project_dir == ready.analysis.project_dir
    assert kwargs["modbus"] == {"host": "127.0.0.1", "port": 502, "allowInputWrites": True}
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
    assert ready.sim.summary_text == "Off"


def test_turning_off_stops_the_simulation_and_turning_on_again_relaunches(ready):
    ready.open()
    assert ready.sim.summary_text == "On (Modbus :502)"
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

    # Forces persist through STOP -> RUN (keepForcesOnRun); inputs ride the transition.
    assert ready.dap.calls[1:] == [
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
# Inputs over Modbus
# ----------------------------------------------------------------------


def _with_modbus(harness: Harness) -> FakeModbus:
    harness.open()
    harness.scheduler.run_ready()  # modbus info -> connect
    return harness.modbus[-1]


def test_modbus_client_connects_with_input_writes_and_fast_poll(ready):
    service = _with_modbus(ready)
    assert service.connected_with == {
        "host": "127.0.0.1",
        "port": 502,
        "timeout": 2,
        "allow_input_writes": True,
    }
    assert service.kwargs["poll_interval_s"] == 0.1
    ready.sim.watch("panel", ["X001", "Y001"])
    assert service.polled == ["X001", "Y001"]


def test_modbus_text_excludes_our_own_connection(ready):
    _with_modbus(ready)
    assert ready.sim.modbus_text.endswith("0 clients")


def test_switches_write_over_modbus(ready):
    service = _with_modbus(ready)
    ready.sim.toggle_switch("X001")
    ready.sim.set_momentary("X002", True)
    ready.sim.press_input("X002")
    assert ready.sim.switch_on("X002")
    ready.sim.release_input("X002")
    assert service.writes == [[("X001", True)], [("X002", True)], [("X002", False)]]
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
        {"Aux": get_addr_key("X", 201), "Lamp": get_addr_key("Y", 1)}
    )
    ready.analysis._result.graph.tag_roles.update({"Aux": None, "Lamp": None})
    ready.open()
    ready.sim.refresh_layout(force=True)
    assert ready.sim.layout is not None
    assert ready.sim.layout.unassigned_inputs == ("X201",)


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
