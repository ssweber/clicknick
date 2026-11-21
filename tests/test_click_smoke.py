"""Test the smoke (devtools/click_smoke.py) with a fake runner and fake checks.

No test starts CLICK or ClickNick's simulation. The fake runner calls the smoke's
``on_new_project`` as the runner's ``new`` mode does, and returns a runner result. The live run
of ``make smoke`` is the real check.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtools"))

import click_runner as cr  # noqa: E402
import click_smoke as cs  # noqa: E402

from clicknick.simulation_session import SimStatus  # noqa: E402


class FakeRun:
    """Stands in for the runner's ``Run`` that the smoke's checks receive."""

    def __init__(self) -> None:
        self.logged: list[str] = []

    def log(self, text: str) -> None:
        self.logged.append(text)


class FakeRunner:
    """Stands in for ``click_smoke.run_new``. It records each call and returns a runner result.

    ``outcomes`` maps a CPU model to the runner's status. For ``ok`` the fake calls
    ``on_new_project`` first. For any other status it does not, as when the runner stops before
    CLICK has the project. ``reasons`` maps a CPU model to the reason for that status.

    As the runner does, the fake catches a ``KeyboardInterrupt`` from ``on_new_project`` and
    ends the run ``aborted``. ``raises`` maps a CPU model to an exception that the fake raises
    itself, as when something outside the runner's own handlers fails.
    """

    def __init__(
        self,
        outcomes: dict[str, str] | None = None,
        *,
        reasons: dict[str, str] | None = None,
        raises: dict[str, BaseException] | None = None,
        scr_before_save: list[str] | None = None,
        after: Callable[[str], None] | None = None,
    ) -> None:
        self.outcomes = outcomes or {}
        self.reasons = reasons or {}
        self.raises = raises or {}
        self.scr_before_save = scr_before_save
        self.after = after
        self.settings: list[cr.Settings] = []
        self.localappdata: list[str | None] = []
        self.runs: list[FakeRun] = []

    def __call__(
        self, settings: cr.Settings, on_new_project: Callable[[cr.Run, cr.NewProject], None]
    ) -> dict[str, Any]:
        self.settings.append(settings)
        self.localappdata.append(os.environ.get("LOCALAPPDATA"))
        model = settings.cpu
        assert model is not None
        if model in self.raises:
            raise self.raises[model]
        status = self.outcomes.get(model, "ok")
        result: dict[str, Any] = {
            "status": status,
            "reason": None if status == "ok" else self.reasons.get(model, f"CLICK refused {model}"),
            "step": "close" if status == "ok" else "launch",
            "elapsed": 12.5,
            "timings": {"launch": 3.5},
        }
        if self.scr_before_save is not None:
            result["scr_before_save"] = self.scr_before_save
        if status == "ok":
            run = FakeRun()
            self.runs.append(run)
            new = cr.NewProject(
                model, settings.out / f"{model}.ckp", 4242, 0x1234, settings.out / "temp"
            )
            try:
                on_new_project(run, new)  # pyright: ignore[reportArgumentType]
            except KeyboardInterrupt:
                result.update(
                    status="aborted", reason="interrupted (Ctrl+C)", step="on_new_project"
                )
        if self.after is not None:
            self.after(model)
        return result


def passes(text: str) -> Callable[[cs.Project, dict[str, Any]], str]:
    def check(project: cs.Project, details: dict[str, Any]) -> str:
        details["model"] = project.new.model
        return text

    return check


def fails(text: str) -> Callable[[cs.Project, dict[str, Any]], str]:
    def check(project: cs.Project, details: dict[str, Any]) -> str:
        raise cs.CheckFailed(text)

    return check


def breaks(project: cs.Project, details: dict[str, Any]) -> str:
    raise ValueError("the check itself broke")


PASSING = (cs.CheckSpec("first", passes("First passed.")), cs.CheckSpec("second", passes("OK.")))


@pytest.fixture
def port(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Make the smoke's port check read a flag, not the real port 502."""
    state = {"free": True}
    monkeypatch.setattr(cs, "port_free", lambda port: state["free"])
    monkeypatch.setattr(cs, "CLOSE_WAIT", 0.1)
    return state


def smoke(
    tmp_path: Path,
    runner: FakeRunner,
    checks: tuple[cs.CheckSpec, ...] = PASSING,
    *models: str,
) -> tuple[int, Path]:
    out = tmp_path / "out"
    argv = ["--out", str(out)] + [arg for model in models for arg in ("--cpu", model)]
    return cs.main(argv, checks=checks, runner=runner), out


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The port check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_port_free_is_false_while_a_socket_listens_on_the_port(host):
    # The simulation's server listens on 127.0.0.1. Another program may listen on every address
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((host, 0))
    listener.listen()
    taken = listener.getsockname()[1]
    try:
        assert cs.port_free(taken) is False
    finally:
        listener.close()
    assert cs.port_free(taken) is True


def test_the_smoke_refuses_to_start_while_the_modbus_port_is_in_use(tmp_path, port, capsys):
    port["free"] = False
    runner = FakeRunner()
    code, out = smoke(tmp_path, runner)
    assert code == cs.EXIT_REFUSED
    assert runner.settings == []
    assert "Port 502 is in use." in capsys.readouterr().out
    assert not out.exists()


def test_the_smoke_refuses_an_out_folder_that_is_not_empty(tmp_path, port, capsys):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "summary.json").write_text("{}", encoding="utf-8")
    runner = FakeRunner()
    code, _ = smoke(tmp_path, runner)
    assert code == cs.EXIT_REFUSED
    assert runner.settings == []
    assert "Give --out a new or empty folder." in capsys.readouterr().out


def test_the_smoke_stops_before_the_next_project_while_the_port_is_in_use(tmp_path, port):
    # Another program takes the port while the first project runs
    runner = FakeRunner(after=lambda model: port.update(free=False))
    code, out = smoke(tmp_path, runner, PASSING, "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_REFUSED
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D"]
    summary = read(out / "summary.json")
    assert summary["status"] == "stopped"
    assert summary["stopped"].startswith("The smoke stopped before C2-03CPU. Port 502 is in use.")
    assert not (out / "C2-03CPU").exists()


def test_a_port_still_in_use_after_clicknick_closed_fails_the_project(tmp_path, port):
    def take_port(project: cs.Project, details: dict[str, Any]) -> str:
        port["free"] = False
        return "Took the port."

    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, (cs.CheckSpec("take", take_port),), "C2-03CPU")
    assert code == cs.EXIT_FAIL
    result = read(out / "C2-03CPU" / "result.json")
    assert result["teardown"]["port_free"] is False
    assert result["problems"] == ["Port 502 was still in use after ClickNick closed."]


# ---------------------------------------------------------------------------
# The results and the exit code
# ---------------------------------------------------------------------------


def test_every_project_passes_when_every_check_passes(tmp_path, port, capsys):
    runner = FakeRunner(scr_before_save=["Scr1.tmp"])
    code, out = smoke(tmp_path, runner)
    assert code == cs.EXIT_PASS
    # One runner run in new mode for each CPU, each into the project's runner/ folder
    assert [(s.command, s.cpu, s.out) for s in runner.settings] == [
        ("new", model, out / model / "runner") for model in cs.PROJECTS
    ]
    # ClickNick's settings go into the run's own LOCALAPPDATA
    assert runner.localappdata == [str(out / "localappdata")] * len(cs.PROJECTS)
    result = read(out / "C2-03CPU" / "result.json")
    assert list(result) == [
        "project",
        "status",
        "problems",
        "elapsed",
        "runner",
        "checks",
        "callback_errors",
        "teardown",
    ]
    assert result["project"] == "C2-03CPU"
    assert result["status"] == "pass"
    assert result["problems"] == []
    assert result["runner"] == {
        "status": "ok",
        "reason": None,
        "step": "close",
        "elapsed": 12.5,
        "timings": {"launch": 3.5},
        "scr_before_save": ["Scr1.tmp"],
        "out": str(out / "C2-03CPU" / "runner"),
    }
    assert list(result["checks"]) == ["first", "second"]
    first = result["checks"]["first"]
    assert list(first) == ["status", "text", "seconds", "details"]
    assert (first["status"], first["text"]) == ("pass", "First passed.")
    assert first["details"] == {"model": "C2-03CPU"}
    assert isinstance(first["seconds"], float)
    assert result["callback_errors"] == []
    assert result["teardown"]["port_free"] is True
    assert result["teardown"]["threads"] == []
    summary = read(out / "summary.json")
    assert summary["status"] == "pass"
    assert summary["stopped"] is None
    assert [p["project"] for p in summary["projects"]] == list(cs.PROJECTS)
    assert summary["projects"][0]["checks"]["first"]["text"] == "First passed."
    assert summary["projects"][0]["scr_before_save"] == ["Scr1.tmp"]
    # stdout holds the summary and nothing else
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("C0-00DD1-D: pass (")
    assert lines[1].startswith("  first: pass (")
    assert lines[1].endswith(" First passed.")
    assert lines[3] == "  scr_before_save: ['Scr1.tmp']"
    assert lines[-1] == "Status: pass"
    assert "smoke check first: pass: First passed." in runner.runs[0].logged


def test_a_failed_check_fails_the_project_and_the_checks_that_need_it_do_not_run(tmp_path, port):
    checks = (
        cs.CheckSpec("build", fails("The build failed: no Scr*.tmp.")),
        cs.CheckSpec("simulation", passes("Ran."), needs=("build",)),
        cs.CheckSpec("layout", passes("2 cards.")),
        cs.CheckSpec("broken", breaks),
    )
    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, checks, "C0-02DD1-D")
    assert code == cs.EXIT_FAIL
    result = read(out / "C0-02DD1-D" / "result.json")
    assert result["status"] == "fail"
    assert {name: (c["status"], c["text"]) for name, c in result["checks"].items()} == {
        "build": ("fail", "The build failed: no Scr*.tmp."),
        "simulation": ("fail", "Not run, because build did not pass."),
        "layout": ("pass", "2 cards."),
        "broken": ("fail", "ValueError: the check itself broke"),
    }
    assert (
        "ValueError: the check itself broke" in result["checks"]["broken"]["details"]["traceback"]
    )
    assert result["problems"] == ["These checks failed: build, simulation, broken."]
    assert read(out / "summary.json")["status"] == "fail"


def test_a_runner_that_stops_before_the_project_fails_it_and_the_smoke_goes_on(tmp_path, port):
    runner = FakeRunner({"C0-02DD1-D": "aborted"})
    code, out = smoke(tmp_path, runner, PASSING, "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_FAIL
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D", "C2-03CPU"]
    result = read(out / "C0-02DD1-D" / "result.json")
    assert result["status"] == "fail"
    assert result["checks"] == {}
    assert result["teardown"] is None
    assert result["problems"] == [
        "The runner ended aborted at step launch: CLICK refused C0-02DD1-D",
        "These checks did not run: first, second.",
    ]
    assert read(out / "C2-03CPU" / "result.json")["status"] == "pass"
    summary = read(out / "summary.json")
    assert [p["status"] for p in summary["projects"]] == ["fail", "pass"]


def test_the_smoke_stops_when_the_runner_refuses_to_start(tmp_path, port, capsys):
    # The runner refuses while any CLICK runs. The next project would be refused too
    runner = FakeRunner({"C0-02DD1-D": "refused"})
    code, out = smoke(tmp_path, runner, PASSING, "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_REFUSED
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D"]
    summary = read(out / "summary.json")
    assert summary["status"] == "stopped"
    assert summary["stopped"] == (
        "The smoke stopped, because the runner refused C0-02DD1-D: CLICK refused C0-02DD1-D"
    )
    assert capsys.readouterr().out.splitlines()[-2] == summary["stopped"]


def test_a_cpu_given_twice_runs_once(tmp_path, port):
    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, PASSING, "C2-03CPU", "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_PASS
    assert [s.cpu for s in runner.settings] == ["C2-03CPU", "C0-02DD1-D"]
    assert [p["project"] for p in read(out / "summary.json")["projects"]] == [
        "C2-03CPU",
        "C0-02DD1-D",
    ]


def test_an_exception_in_the_smoke_writes_the_summary_and_stops_it(tmp_path, port, capsys):
    runner = FakeRunner(raises={"C0-02DD1-D": OSError("the desktop is locked")})
    code, out = smoke(tmp_path, runner, PASSING, "C2-03CPU", "C0-02DD1-D", "C0-11DD1E-D")
    assert code == cs.EXIT_REFUSED
    assert [s.cpu for s in runner.settings] == ["C2-03CPU", "C0-02DD1-D"]
    summary = read(out / "summary.json")
    assert summary["status"] == "stopped"
    assert summary["stopped"] == (
        "The smoke stopped during C0-02DD1-D, because it raised OSError: the desktop is locked"
    )
    assert [p["project"] for p in summary["projects"]] == ["C2-03CPU"]
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-2] == summary["stopped"]
    # The traceback goes to stderr, with the rest of the smoke's log
    assert "OSError: the desktop is locked" in captured.err


def test_ctrl_c_in_a_check_stops_the_smoke(tmp_path, port):
    def interrupt(project: cs.Project, details: dict[str, Any]) -> str:
        raise KeyboardInterrupt

    checks = (cs.CheckSpec("first", passes("OK.")), cs.CheckSpec("interrupt", interrupt))
    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, checks, "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_REFUSED
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D"]
    result = read(out / "C0-02DD1-D" / "result.json")
    # ClickNick was closed before the runner saw the interrupt
    assert result["teardown"]["port_free"] is True
    assert result["runner"]["reason"] == "interrupted (Ctrl+C)"
    summary = read(out / "summary.json")
    assert summary["status"] == "stopped"
    assert summary["stopped"] == "The smoke stopped during C0-02DD1-D, because you pressed Ctrl+C."
    assert [p["status"] for p in summary["projects"]] == ["fail"]


def test_ctrl_c_outside_the_runner_stops_the_smoke(tmp_path, port):
    runner = FakeRunner(raises={"C0-02DD1-D": KeyboardInterrupt()})
    code, out = smoke(tmp_path, runner, PASSING, "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_REFUSED
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D"]
    summary = read(out / "summary.json")
    assert summary["stopped"] == "The smoke stopped during C0-02DD1-D, because you pressed Ctrl+C."
    assert summary["projects"] == []


def test_ctrl_c_before_the_runner_starts_click_stops_the_smoke(tmp_path, port):
    # The runner reports this interrupt as a refusal
    runner = FakeRunner(
        {"C0-02DD1-D": "refused"},
        reasons={"C0-02DD1-D": "interrupted (Ctrl+C) before CLICK was started"},
    )
    code, out = smoke(tmp_path, runner, PASSING, "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_REFUSED
    assert read(out / "summary.json")["stopped"] == (
        "The smoke stopped during C0-02DD1-D, because you pressed Ctrl+C."
    )


def test_a_thread_that_still_runs_after_its_check_timed_out_stops_the_smoke(tmp_path, port):
    release = threading.Event()

    def stuck(project: cs.Project, details: dict[str, Any]) -> str:
        return project.scheduler.background("the stuck call", lambda: str(release.wait(10)), 0.05)

    runner = FakeRunner()
    try:
        code, out = smoke(
            tmp_path, runner, (cs.CheckSpec("stuck", stuck),), "C0-02DD1-D", "C2-03CPU"
        )
    finally:
        release.set()
    assert code == cs.EXIT_REFUSED
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D"]
    result = read(out / "C0-02DD1-D" / "result.json")
    assert result["checks"]["stuck"]["text"] == (
        "Timed out after 0.05 s waiting for the stuck call."
    )
    assert result["teardown"]["threads"] == ["smoke the stuck call"]
    assert result["problems"] == [
        "These checks failed: stuck.",
        "These threads still ran after ClickNick closed: smoke the stuck call.",
    ]
    summary = read(out / "summary.json")
    assert summary["status"] == "stopped"
    assert summary["stopped"] == (
        "The smoke stopped after C0-02DD1-D, because these threads still ran after ClickNick "
        "closed: smoke the stuck call."
    )


def test_a_thread_that_ends_while_clicknick_closes_does_not_stop_the_smoke(
    tmp_path, port, monkeypatch
):
    monkeypatch.setattr(cs, "CLOSE_WAIT", 10.0)
    release = threading.Event()

    def slow(project: cs.Project, details: dict[str, Any]) -> str:
        # The call outlives its timeout. A callback that runs while the smoke waits for the close
        # ends it
        project.scheduler.after(100, release.set)
        return project.scheduler.background("the slow call", lambda: str(release.wait(10)), 0.05)

    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, (cs.CheckSpec("slow", slow),), "C0-02DD1-D", "C2-03CPU")
    assert code == cs.EXIT_FAIL
    assert [s.cpu for s in runner.settings] == ["C0-02DD1-D", "C2-03CPU"]
    result = read(out / "C0-02DD1-D" / "result.json")
    assert result["teardown"]["threads"] == []
    assert result["problems"] == ["These checks failed: slow."]
    assert read(out / "summary.json")["stopped"] is None


def test_a_scheduled_callback_that_raises_fails_the_project(tmp_path, port):
    def schedule(project: cs.Project, details: dict[str, Any]) -> str:
        def boom() -> None:
            raise RuntimeError("a callback broke")

        project.scheduler.after(0, boom)
        project.scheduler.pump()
        return "Scheduled."

    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, (cs.CheckSpec("schedule", schedule),), "C2-03CPU")
    assert code == cs.EXIT_FAIL
    result = read(out / "C2-03CPU" / "result.json")
    assert result["checks"]["schedule"]["status"] == "pass"
    [error] = result["callback_errors"]
    assert "RuntimeError: a callback broke" in error
    assert result["problems"] == ["1 scheduled callback(s) raised."]


def test_the_project_result_is_written_after_each_check(tmp_path, port):
    seen: list[list[str]] = []

    def look(project: cs.Project, details: dict[str, Any]) -> str:
        seen.append(list(read(project.folder / "result.json")["checks"]))
        return "Looked."

    checks = (cs.CheckSpec("first", passes("OK.")), cs.CheckSpec("look", look))
    code, _ = smoke(tmp_path, FakeRunner(), checks, "C2-03CPU")
    assert code == cs.EXIT_PASS
    assert seen == [["first"]]


# ---------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------


def test_the_scheduler_runs_callbacks_from_other_threads_when_it_pumps():
    scheduler = cs.Scheduler()
    ran: list[str] = []
    thread = threading.Thread(target=lambda: scheduler.after(0, lambda: ran.append("thread")))
    thread.start()
    thread.join()
    assert ran == []
    scheduler.pump()
    assert ran == ["thread"]


def test_the_scheduler_runs_callbacks_in_order_of_due_time_and_skips_cancelled_ones():
    scheduler = cs.Scheduler()
    ran: list[str] = []
    scheduler.after(30, lambda: ran.append("later"))
    scheduler.after(0, lambda: ran.append("now"))
    cancelled = scheduler.after(0, lambda: ran.append("cancelled"))
    scheduler.after_cancel(cancelled)
    scheduler.pump()
    assert ran == ["now"]
    scheduler.pump(0.1)
    assert ran == ["now", "later"]


def test_the_scheduler_wait_returns_the_value_or_times_out_naming_what_it_waited_for():
    scheduler = cs.Scheduler()
    box: dict[str, int] = {}
    scheduler.after(10, lambda: box.update(value=7))
    assert scheduler.wait("the value", lambda: box.get("value"), 5) == 7
    with pytest.raises(cs.CheckFailed, match=r"Timed out after 0\.05 s waiting for nothing\."):
        scheduler.wait("nothing", lambda: None, 0.05)


def test_the_scheduler_background_pumps_while_the_call_waits_for_a_callback():
    # A call that waits for a callback would hang if the pumping thread were blocked
    scheduler = cs.Scheduler()
    done = threading.Event()

    def call() -> str:
        scheduler.after(0, done.set)
        assert done.wait(5)
        return "answered"

    assert scheduler.background("the call", call, 5) == "answered"

    def broken() -> str:
        raise ValueError("no answer")

    with pytest.raises(ValueError, match="no answer"):
        scheduler.background("the broken call", broken, 5)


# ---------------------------------------------------------------------------
# The projects and the recorded layouts
# ---------------------------------------------------------------------------


def test_every_project_is_a_cpu_that_the_wizard_lists():
    assert set(cs.PROJECTS) <= set(cr.CPU_MODELS)


def test_the_recorded_layouts_name_cpus_that_the_wizard_lists():
    layouts = cs.recorded_layouts()
    assert set(layouts) == {
        "C0-00DD1-D",
        "C0-02DD1-D",
        "C0-11DD1E-D",
        "C0-12DD1E-2-D",
        "C2-03CPU",
        "C2-03CPU-2",
    }
    # Every CPU that the smoke makes a project for has recorded cards
    assert set(cs.PROJECTS) <= set(layouts)
    for model, layout in layouts.items():
        assert model in cr.CPU_MODELS
        assert layout["has_cpu"] is True
        assert layout["cards"][0]["location"] == "cpu"
        assert layout["cards"][0]["model"] == model


# ---------------------------------------------------------------------------
# The import order
# ---------------------------------------------------------------------------


def test_importing_the_smoke_imports_no_clicknick_module():
    # The smoke sets LOCALAPPDATA in main(). live/session.py reads it once, on import, so no
    # clicknick module may load before main() runs
    devtools = Path(__file__).resolve().parents[1] / "devtools"
    code = (
        f"import sys; sys.path.insert(0, {str(devtools)!r}); import click_smoke; "
        "loaded = [m for m in sys.modules if m.startswith('clicknick')]; "
        "assert not loaded, loaded"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr


# ---------------------------------------------------------------------------
# The simulation check
# ---------------------------------------------------------------------------


class FakeSimulation:
    """Stands in for ``SimulationSession`` in ``check_simulation``.

    Each read of ``scan_id`` counts one more scan. With *leaves_run*, the simulated PLC goes to
    STOP at the first scan that the check reads in RUN, and the scan count still rises.
    """

    def __init__(self, *, leaves_run: bool = False) -> None:
        self.leaves_run = leaves_run
        self.status = SimStatus.IDLE
        self.error: str | None = None
        self.error_detail: str | None = None
        self.notice: str | None = None
        self.mode = "stop"
        self.running = False
        self._scans = 0

    @property
    def is_ready(self) -> bool:
        return self.status is SimStatus.READY

    def turn_on(self) -> None:
        self.status = SimStatus.READY

    def set_switch_position(self, position: str) -> None:
        self.mode = position
        self.running = position == "run"

    @property
    def scan_id(self) -> int:
        self._scans += 1
        if self.leaves_run:
            self.mode = "stop"
        return self._scans


class FakeSession:
    """Stands in for ``ConnectionSession``. It returns one simulation."""

    def __init__(self, simulation: FakeSimulation) -> None:
        self.simulation = simulation

    def ensure_simulation(self, scheduler: cs.Scheduler) -> FakeSimulation:
        return self.simulation


def check_simulation_with(tmp_path: Path, simulation: FakeSimulation) -> dict[str, Any]:
    new = cr.NewProject("C2-03CPU", tmp_path / "C2-03CPU.ckp", 4242, 0x1234, tmp_path / "temp")
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    project._session = FakeSession(simulation)  # pyright: ignore[reportAttributeAccessIssue]
    details: dict[str, Any] = {}
    try:
        details["text"] = cs.check_simulation(project, details)
    except cs.CheckFailed as exc:
        details["failed"] = str(exc)
    return details


def test_the_simulation_check_passes_after_ten_scans_in_run(tmp_path, port):
    details = check_simulation_with(tmp_path, FakeSimulation())
    assert "failed" not in details
    assert (details["status"], details["mode"]) == ("ready", "run")
    assert details["last_scan"] >= details["first_scan"] + cs.RUN_SCANS
    assert details["text"].startswith(
        f"READY. In RUN it scanned from scan {details['first_scan']} to scan "
        f"{details['last_scan']} in "
    )


def test_the_simulation_check_fails_when_the_plc_leaves_run_before_ten_scans(
    tmp_path, port, monkeypatch
):
    monkeypatch.setattr(cs, "RUN_WAIT", 0.2)
    details = check_simulation_with(tmp_path, FakeSimulation(leaves_run=True))
    assert details["failed"] == "Timed out after 0.2 s waiting for 10 scans in RUN."
