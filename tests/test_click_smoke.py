"""Test the smoke (devtools/click_smoke.py) with a fake runner and fake checks.

No test starts CLICK or ClickNick's simulation. The fake runner calls the smoke's
``on_new_project`` as the runner's ``new`` mode does, and returns a runner result. The live run
of ``make smoke`` is the real check.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from pyclickplc.banks import DataType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtools"))

import click_runner as cr  # noqa: E402
import click_smoke as cs  # noqa: E402

from clicknick.models.address_row import AddressRow  # noqa: E402
from clicknick.simulation_session import SimStatus  # noqa: E402
from clicknick.utils import mdb_operations  # noqa: E402


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

    As the runner does, the fake catches a ``KeyboardInterrupt`` or a ``cr.Aborted`` from
    ``on_new_project`` and ends the run ``aborted``. For a ``cr.ClickErrorBox`` it records the
    box's code as ``click_error``. ``raises`` maps a CPU model to an exception that the fake raises
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
                None if model == cr.NO_CPU else model,
                settings.out / f"{model}.ckp",
                4242,
                0x1234,
                settings.out / "temp",
            )
            try:
                on_new_project(run, new)  # pyright: ignore[reportArgumentType]
            except KeyboardInterrupt:
                result.update(
                    status="aborted", reason="interrupted (Ctrl+C)", step="on_new_project"
                )
            except cr.Aborted as exc:
                result.update(status="aborted", reason=str(exc), step="on_new_project")
                if isinstance(exc, cr.ClickErrorBox):
                    result["click_error"] = exc.code
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
    # The project with no CPU reaches the checks with no model
    assert read(out / "none" / "result.json")["checks"]["first"]["details"] == {"model": None}
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


def test_the_summary_escapes_a_character_that_stdouts_encoding_lacks(tmp_path, port, monkeypatch):
    # Redirected to a file, stdout is cp1252, which has no "→"
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stdout)
    checks = (cs.CheckSpec("arrow", passes("Sync refused '50→60'.")),)
    code, _ = smoke(tmp_path, FakeRunner(), checks, "C2-03CPU")
    assert code == cs.EXIT_PASS
    stdout.flush()
    text = stdout.buffer.getvalue().decode("cp1252")  # pyright: ignore[reportAttributeAccessIssue]
    assert "Sync refused '50\\u219260'." in text


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


def test_every_project_is_a_cpu_that_the_wizard_lists_or_no_cpu():
    assert set(cs.PROJECTS) <= {*cr.CPU_MODELS, cr.NO_CPU}
    assert cs.PROJECTS[-1] == cr.NO_CPU


def test_the_recorded_layouts_name_cpus_that_the_wizard_lists_or_no_cpu():
    layouts = cs.recorded_layouts()
    assert set(layouts) == {
        "C0-00DD1-D",
        "C0-02DD1-D",
        "C0-11DD1E-D",
        "C0-12DD1E-2-D",
        "C2-03CPU",
        "C2-03CPU-2",
        "none",
    }
    # Every project that the smoke makes has recorded cards
    assert set(cs.PROJECTS) <= set(layouts)
    # With no CPU, the layout has no card, and the Simulator shows its No CPU card
    assert layouts.pop(cr.NO_CPU) == {"has_cpu": False, "cards": []}
    for model, layout in layouts.items():
        assert model in cr.CPU_MODELS
        assert layout["has_cpu"] is True
        assert layout["cards"][0]["location"] == "cpu"
        assert layout["cards"][0]["model"] == model


# ---------------------------------------------------------------------------
# The layout check
# ---------------------------------------------------------------------------


class FakeLayoutSimulation:
    """Stands in for ``SimulationSession`` in ``check_layout``. It holds a layout or an error."""

    def __init__(self, layout: Any, error: str | None = None) -> None:
        self.layout = layout
        self.layout_error = error

    def refresh_layout(self, *, force: bool = False) -> None:
        pass


class FakeLayoutSession:
    """Stands in for ``ConnectionSession`` in ``check_layout``."""

    def __init__(self, simulation: FakeLayoutSimulation, project_ini: Path) -> None:
        self.simulation = simulation
        self.project_ini = project_ini

    def ensure_simulation(self, scheduler: cs.Scheduler) -> FakeLayoutSimulation:
        return self.simulation


# Lines from the Project.ini that CLICK 4.00 saved for a project with no CPU, in a live run on
# 2026-11-20. Like that file, it has no [Sec21]
NO_CPU_INI = b"[Sec56]\r\nKey11=0\r\nKey10=587\r\n[Sec52]\r\nKey11_1=1\r\nKey2=0\r\nKey1=1\r\n"


def check_layout_with(
    tmp_path: Path, model: str | None, layout: Any, error: str | None = None
) -> dict[str, Any]:
    ini = tmp_path / "Project.ini"
    ini.write_bytes(NO_CPU_INI)
    new = cr.NewProject(model, tmp_path / "none.ckp", 4242, 0x1234, tmp_path / "temp")
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    session = FakeLayoutSession(FakeLayoutSimulation(layout, error), ini)
    project._session = session  # pyright: ignore[reportAttributeAccessIssue]
    details: dict[str, Any] = {}
    try:
        details["text"] = cs.check_layout(project, details)
    except cs.CheckFailed as exc:
        details["failed"] = str(exc)
    return details


def test_the_layout_check_passes_for_a_project_with_no_cpu(tmp_path):
    from clicknick.services.sim_hardware import read_panel_layout

    (tmp_path / "read.ini").write_bytes(NO_CPU_INI)
    layout = read_panel_layout(tmp_path / "read.ini")
    details = check_layout_with(tmp_path, None, layout)
    assert "failed" not in details
    assert details["text"] == "No CPU, 0 card(s), as read_panel_layout reads them and as recorded."
    assert (details["layout_error"], details["has_cpu"], details["cards"]) == (None, False, [])
    assert details["recorded"] is True


def test_the_layout_check_fails_when_a_project_with_no_cpu_shows_a_cpu(tmp_path, monkeypatch):
    from clicknick.services import sim_hardware

    layout = sim_hardware.PanelLayout((sim_hardware.Card("cpu", 0, "C2-03CPU", ()),))
    monkeypatch.setattr(sim_hardware, "read_panel_layout", lambda path: layout)
    details = check_layout_with(tmp_path, None, layout)
    assert details["failed"] == (
        "The project has no CPU, but the layout has the CPU card ['C2-03CPU']. The Simulator "
        "would not show its No CPU card."
    )


def test_the_layout_check_fails_when_a_project_with_no_cpu_has_a_layout_error(tmp_path):
    details = check_layout_with(tmp_path, None, None, "Project.ini is malformed.")
    assert details["failed"] == (
        "The simulation could not read the hardware: Project.ini is malformed."
    )


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


# ---------------------------------------------------------------------------
# The sync and csv_round_trip checks
# ---------------------------------------------------------------------------

EXPORT_HEADER = "Address,Data Type,Nickname,Initial Value,Retentive,Address Comment"


class FakeDatabase:
    """Stands in for CLICK's SC_.mdb, as ``MdbDataSource`` reads and writes it.

    It keeps each row that ClickNick writes, as ``stored_row`` says SC_.mdb keeps it. After each
    write it writes the file *path* again. The file holds each row's address, and its comment
    in Jet 4's compressed form if the comment has one, and in UTF-16-LE if not.
    """

    supports_used_field = True
    is_read_only = False
    is_database = True
    stored_row = staticmethod(mdb_operations.stored_row)

    def __init__(self, path: Path, rows: Sequence[AddressRow] = ()) -> None:
        self.path = path
        self.rows = {row.addr_key: row for row in rows}
        self.write_file()

    @property
    def file_path(self) -> str:
        return str(self.path)

    def load_all_addresses(self) -> dict[int, AddressRow]:
        return dict(self.rows)

    def save_changes(self, rows: Sequence[AddressRow]) -> int:
        for row in rows:
            stored = self.stored_row(row)
            if stored.has_content:
                self.rows[row.addr_key] = stored
            else:
                self.rows.pop(row.addr_key, None)
        self.write_file()
        return len(rows)

    def write_file(self) -> None:
        parts = [b"Standard Jet DB"]
        for row in self.rows.values():
            parts.append(row.display_address.encode())
            try:
                parts.append(b"\xff\xfe" + row.comment.encode("latin-1"))
            except UnicodeEncodeError:
                parts.append(row.comment.encode("utf-16-le"))
        self.path.write_bytes(b"\x00".join(parts))

    def table(self) -> dict[str, dict[str, Any]]:
        """Return the rows by address, as the runner's ``read_rows`` returns them."""
        return {
            row.display_address: {
                "Nickname": row.nickname,
                "InitialValue": row.initial_value,
                "Retentive": row.retentive,
                "Comment": row.comment,
                "Use": row.used,
            }
            for row in self.rows.values()
        }


class FakeClickRun(FakeRun):
    """Stands in for the runner's ``Run`` with a CLICK whose SC_.mdb is a ``FakeDatabase``.

    ``export`` writes the rows in the form of CLICK's nickname export. It encodes the file as
    *encoding*, and it writes a "?" for a character that *encoding* does not have.
    ``import_one`` replaces the rows with the rows of the CSV, as Delete Existing does, and
    copies the file to ``imported.mdb``. *misread* changes the rows that it reads from the CSV
    before it stores them. With *import_errors*, it answers with that Import Error List and
    changes nothing. With *ignores_import*, it answers "Completed!" and changes nothing.
    ``calls`` records each call.
    """

    def __init__(
        self,
        database: FakeDatabase,
        *,
        encoding: str = "cp1252",
        import_errors: str = "",
        misread: Callable[[dict[int, AddressRow]], dict[int, AddressRow]] | None = None,
        ignores_import: bool = False,
    ) -> None:
        super().__init__()
        self.database = database
        self.encoding = encoding
        self.import_errors = import_errors
        self.misread = misread
        self.ignores_import = ignores_import
        self.calls: list[tuple[str, str]] = []

    def read_rows(self, mdb: Path) -> dict[str, dict[str, Any]]:
        self.calls.append(("read_rows", mdb.name))
        return self.database.table()

    def export(self, folder: Path) -> dict[str, Any]:
        self.calls.append(("export", folder.name))
        lines = [EXPORT_HEADER] + [
            f'{row.display_address},{row.data_type_display},"{row.nickname}",'
            f'{row.initial_value},{"Yes" if row.retentive else "No"},"{row.comment}"'
            for row in self.database.rows.values()
        ]
        folder.mkdir(parents=True)
        copy = folder / "export.csv"
        copy.write_bytes(("\r\n".join(lines) + "\r\n").encode(self.encoding, "replace"))
        return {"copy": copy}

    def import_one(
        self, number: int, name: str, csv: Path, line: int | None, row: bytes | None
    ) -> dict[str, Any]:
        self.calls.append(("import_one", csv.name))
        if self.import_errors:
            return {
                "answer": "errors",
                "message": self.import_errors,
                "errors": [],
                "mdb": None,
                "mdb_changed": False,
            }
        from clicknick.data.data_source import CsvDataSource

        before = self.database.path.read_bytes()
        if not self.ignores_import:
            rows = dict(CsvDataSource(str(csv)).load_all_addresses())
            self.database.rows = rows if self.misread is None else self.misread(rows)
            self.database.write_file()
        copy = self.database.path.with_name("imported.mdb")
        copy.write_bytes(self.database.path.read_bytes())
        return {
            "answer": "completed",
            "message": "Completed!",
            "errors": None,
            "mdb": copy,
            "mdb_changed": copy.read_bytes() != before,
        }


class FakeDatabaseProject(cs.Project):
    """A ``Project`` whose data source is the fake CLICK's ``FakeDatabase``."""

    run: FakeClickRun  # pyright: ignore[reportIncompatibleVariableOverride]

    def data_source(self) -> FakeDatabase:  # pyright: ignore[reportIncompatibleMethodOverride]
        return self.run.database


def click_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: Sequence[AddressRow] = (),
    **run: Any,
) -> FakeDatabaseProject:
    """Return a project whose store has read a fake CLICK's SC_.mdb."""
    from clicknick.data.address_store import AddressStore

    monkeypatch.setattr(cs, "AFTER_RUNNER", 0.0)
    temp = tmp_path / "temp"
    temp.mkdir()
    database = FakeDatabase(temp / "SC_.mdb", rows)
    new = cr.NewProject("C2-03CPU", tmp_path / "C2-03CPU.ckp", 4242, 0x1234, temp)
    folder = tmp_path / "project"
    folder.mkdir()
    fake_run = FakeClickRun(database, **run)
    project = FakeDatabaseProject(fake_run, new, folder, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    project.store = AddressStore(database)  # pyright: ignore[reportArgumentType]
    project.store.load_initial_data()
    return project


def run_check(
    check: Callable[[cs.Project, dict[str, Any]], str], project: cs.Project
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    try:
        details["text"] = check(project, details)
    except cs.CheckFailed as exc:
        details["failed"] = str(exc)
    return details


def test_the_sync_check_passes_when_click_keeps_what_clicknick_writes(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    details = run_check(cs.check_sync, project)
    assert "failed" not in details, details["failed"]
    assert details["text"] == (
        "Sync refused '50→60'. It wrote '50°C' and the initial value 0, and a reload shows the "
        "same. CLICK's export (cp1252) shows the comment as 35 30 b0 43."
    )
    assert details["refused_row"]["comment_error"] == "CLICK cannot hold '→'. Replace it"
    assert details["refusal"] == "Cannot save: 1 row has validation errors. Fix them first."
    assert details["file_unchanged_after_refusal"] is True
    assert details["synced_row"] == details["reloaded_row"]
    assert details["mdb_row"]["InitialValue"] == "0"
    assert details["mdb_comment"] == {
        "utf-16-le": {"bytes": "35 00 30 00 b0 00 43 00", "found": 0},
        "compressed": {"bytes": "ff fe 35 30 b0 43", "found": 1},
    }
    assert details["click_export"] == {
        "encoding": "cp1252",
        "address": "DS100",
        "initial_value": "0",
        "comment": "50°C",
        "comment_bytes": "35 30 b0 43",
        "line_bytes": 'DS100,INT,"Smoke_Init",0,Yes,"50°C"'.encode("cp1252").hex(" "),
    }
    # The check read three copies of SC_.mdb, then asked the runner for one export
    assert project.run.calls == [
        ("read_rows", "before_sync.mdb"),
        ("read_rows", "after_refusal.mdb"),
        ("read_rows", "after_sync.mdb"),
        ("export", "sync"),
    ]
    assert (project.folder / "mdb" / "after_sync.mdb").is_file()


def test_the_sync_check_reads_an_export_in_utf8_with_a_bom(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch, encoding="utf-8-sig")
    details = run_check(cs.check_sync, project)
    assert "failed" not in details, details["failed"]
    found = details["click_export"]
    assert (found["encoding"], found["comment"]) == ("utf-8-sig", "50°C")
    assert found["comment_bytes"] == "35 30 c2 b0 43"


def test_the_sync_check_fails_when_clicks_export_loses_the_degree_sign(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch, encoding="ascii")
    details = run_check(cs.check_sync, project)
    assert details["failed"] == (
        "CLICK's export shows Smoke_Init as ('DS100', '0', '50?C'), not ('DS100', '0', '50°C'). "
        "Its comment's bytes are 35 30 3f 43 (cp1252)."
    )


def test_exported_row_reads_a_file_without_a_byte_order_mark_as_cp1252():
    # As UTF-8, these bytes would read as "50°C"
    data = f'{EXPORT_HEADER}\r\nDS100,INT,"Smoke_Init",0,Yes,"50°C"\r\n'.encode()
    found = cs.exported_row(data, "Smoke_Init")
    assert (found["encoding"], found["comment"]) == ("cp1252", "50Â°C")
    assert found["comment_bytes"] == "35 30 c2 b0 43"


def test_exported_row_fails_when_a_file_does_not_decode_as_cp1252():
    data = f'{EXPORT_HEADER}\r\nDS100,INT,"Smoke_Init",0,Yes,"x"\r\n'.encode() + b"\x81"
    with pytest.raises(cs.CheckFailed, match=r"^CLICK's export does not decode as cp1252: "):
        cs.exported_row(data, "Smoke_Init")


def test_the_sync_check_fails_when_sync_does_not_refuse_the_comment(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    monkeypatch.setattr(cs, "REFUSED_COMMENT", "50-60")
    details = run_check(cs.check_sync, project)
    assert details["failed"] == "Sync did not refuse the comment '50-60'. It wrote 1 row(s)."


def test_the_sync_check_fails_when_sc_mdb_changes_although_sync_refused(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    store = project.store
    assert store is not None
    save = store.save_all_changes
    other = AddressRow(memory_type="DS", address=200, nickname="Other", data_type=DataType.INT)
    details: dict[str, Any] = {}

    def writes_then_refuses() -> set[int]:
        # The first Sync writes a row to SC_.mdb, then refuses
        if "refusal" not in details:
            project.run.database.rows[other.addr_key] = other
            project.run.database.write_file()
        return save()

    monkeypatch.setattr(store, "save_all_changes", writes_then_refuses)
    with pytest.raises(cs.CheckFailed) as failed:
        cs.check_sync(project, details)
    assert str(failed.value) == "Sync refused the comment, but SC_.mdb changed."
    assert details["file_unchanged_after_refusal"] is False


def test_the_sync_check_fails_when_sync_does_not_write_the_row(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    store = project.store
    assert store is not None
    save = store.save_all_changes

    def writes_but_names_no_row() -> set[int]:
        save()
        return set()

    monkeypatch.setattr(store, "save_all_changes", writes_but_names_no_row)
    details = run_check(cs.check_sync, project)
    assert details["failed"] == "Sync did not write DS100."


def test_the_sync_check_fails_when_the_row_keeps_no_initial_value(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    # SC_.mdb keeps the row as ClickNick wrote it, with no initial value
    monkeypatch.setattr(project.run.database, "stored_row", lambda row: row)
    details = run_check(cs.check_sync, project)
    assert details["failed"] == (
        "After the Sync, DS100 shows ('Smoke_Init', '50°C', '', False) (nickname, comment, "
        "initial value, unsaved edit), not ('Smoke_Init', '50°C', '0', False), or the store "
        "still has unsaved edits."
    )


def test_the_sync_check_fails_when_sc_mdb_holds_another_comment(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    read_rows = project.run.read_rows

    def loses_the_degree_sign(mdb: Path) -> dict[str, dict[str, Any]]:
        table = read_rows(mdb)
        if mdb.name == "after_sync.mdb":
            table["DS100"]["Comment"] = "50?C"
        return table

    monkeypatch.setattr(project.run, "read_rows", loses_the_degree_sign)
    details = run_check(cs.check_sync, project)
    assert details["failed"] == (
        "SC_.mdb holds ('Smoke_Init', '50?C') for DS100, not ('Smoke_Init', '50°C')."
    )


def test_the_sync_check_fails_when_a_reload_shows_another_row(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    reloaded = AddressRow(
        memory_type="DS",
        address=100,
        nickname="Smoke_Init",
        comment="50?C",
        initial_value="0",
        data_type=DataType.INT,
    )
    other = FakeDatabase(tmp_path / "reloaded.mdb", [reloaded])
    monkeypatch.setattr(project, "data_source", lambda: other)
    details = run_check(cs.check_sync, project)
    assert details["failed"] == (
        "A store loaded from SC_.mdb again shows DS100 differently, or it has unsaved edits."
    )
    assert details["reloaded_row"]["comment"] == "50?C"


def test_the_sync_check_leaves_a_row_with_content_alone(tmp_path, monkeypatch):
    taken = AddressRow(memory_type="DS", address=100, nickname="Taken", data_type=DataType.INT)
    project = click_project(tmp_path, monkeypatch, [taken])
    details = run_check(cs.check_sync, project)
    assert details["failed"] == "DS100 is not an empty row that no rung uses."
    assert project.run.calls == []
    assert project.run.database.rows == {taken.addr_key: taken}


def test_the_csv_round_trip_check_passes_when_click_imports_clicknicks_file(tmp_path, monkeypatch):
    project = click_project(tmp_path, monkeypatch)
    assert "failed" not in run_check(cs.check_sync, project)
    # CLICK's import empties the table first. So a row that SC_.mdb holds and the file lacks
    # is gone after it
    left_over = AddressRow(memory_type="DS", address=200, nickname="Gone", data_type=DataType.INT)
    project.run.database.rows[left_over.addr_key] = left_over
    project.run.database.write_file()
    details = run_check(cs.check_csv_round_trip, project)
    assert "failed" not in details, details["failed"]
    assert left_over.addr_key not in project.run.database.rows
    assert details["addresses"] == {"file": ["DS100"], "mdb": ["DS100"]}
    assert details["import"]["mdb_changed"] is True
    assert details["text"] == (
        "CLICK imported the 1 row(s) of ClickNick's cp1252 CSV, and its export shows Smoke_Init "
        "with '50°C'."
    )
    assert (details["bom"], details["utf8"], details["cp1252"]) == (None, False, True)
    assert "35 30 b0 43" in details["line_bytes"]
    assert details["import"]["answer"] == "completed"
    assert details["click_export"]["comment_bytes"] == "35 30 b0 43"
    assert project.run.calls[-3:] == [
        ("import_one", "clicknick.csv"),
        ("read_rows", "imported.mdb"),
        ("export", "csv_import"),
    ]
    assert (project.folder / "csv" / "clicknick.csv").is_file()


def test_the_csv_round_trip_check_fails_when_click_lists_import_errors(tmp_path, monkeypatch):
    errors = "Unable to import Address Comment.\r\nLine 2 : Address = DS100"
    project = click_project(tmp_path, monkeypatch, import_errors=errors)
    assert "failed" not in run_check(cs.check_sync, project)
    details = run_check(cs.check_csv_round_trip, project)
    assert details["failed"] == (
        f"CLICK did not import ClickNick's CSV cleanly. It answered: {errors}"
    )
    assert project.run.calls[-1] == ("import_one", "clicknick.csv")


def rewrite_clicknicks_csv(
    monkeypatch: pytest.MonkeyPatch, rewrite: Callable[[bytes], bytes]
) -> None:
    """Make Export to CSV write the bytes that *rewrite* makes of the file that it writes now."""
    from clicknick.data.data_source import CsvDataSource

    save = CsvDataSource.save_changes

    def save_changes(self: CsvDataSource, rows: Sequence[AddressRow]) -> int:
        count = save(self, rows)
        path = Path(self.file_path)
        path.write_bytes(rewrite(path.read_bytes()))
        return count

    monkeypatch.setattr(CsvDataSource, "save_changes", save_changes)


@pytest.mark.parametrize(
    "rewrite",
    [
        # The file is UTF-8, so CLICK would read "50Â°C"
        pytest.param(lambda data: data.decode("cp1252").encode("utf-8"), id="utf-8"),
        # The file starts with a byte order mark
        pytest.param(lambda data: b"\xef\xbb\xbf" + data, id="byte-order-mark"),
        # The file holds a byte that cp1252 does not have
        pytest.param(lambda data: data + b'DS101,INT,"\x81",0,No,""\r\n', id="not-cp1252"),
    ],
)
def test_the_csv_round_trip_check_fails_when_clicknicks_file_is_not_cp1252(
    tmp_path, monkeypatch, rewrite
):
    project = click_project(tmp_path, monkeypatch)
    assert "failed" not in run_check(cs.check_sync, project)
    rewrite_clicknicks_csv(monkeypatch, rewrite)
    details = run_check(cs.check_csv_round_trip, project)
    line = bytes.fromhex(details["line_bytes"])
    assert details["failed"] == (
        "Export to CSV did not write Smoke_Init's comment '50°C' in cp1252 with no byte order "
        f"mark. The file's line for it is {line!r}."
    )
    assert not any(call[0] == "import_one" for call in project.run.calls)


def test_the_csv_round_trip_check_fails_when_the_import_leaves_sc_mdb_as_it_was(
    tmp_path, monkeypatch
):
    project = click_project(tmp_path, monkeypatch, ignores_import=True)
    assert "failed" not in run_check(cs.check_sync, project)
    details = run_check(cs.check_csv_round_trip, project)
    assert details["failed"] == (
        "CLICK answered that it imported ClickNick's CSV, but SC_.mdb did not change."
    )


def test_the_csv_round_trip_check_fails_when_sc_mdb_lacks_a_row_of_the_file(tmp_path, monkeypatch):
    def drops_ds100(rows: dict[int, AddressRow]) -> dict[int, AddressRow]:
        return {key: row for key, row in rows.items() if row.display_address != "DS100"}

    project = click_project(tmp_path, monkeypatch, misread=drops_ds100)
    assert "failed" not in run_check(cs.check_sync, project)
    details = run_check(cs.check_csv_round_trip, project)
    assert details["failed"] == (
        "After the import, SC_.mdb lacks ['DS100'] from ClickNick's CSV and holds [] that the "
        "file lacks."
    )


def test_the_csv_round_trip_check_fails_when_click_misreads_the_comment(tmp_path, monkeypatch):
    def loses_the_degree_sign(rows: dict[int, AddressRow]) -> dict[int, AddressRow]:
        return {
            key: dataclasses.replace(row, comment=row.comment.replace("°", "?"))
            for key, row in rows.items()
        }

    project = click_project(tmp_path, monkeypatch, misread=loses_the_degree_sign)
    assert "failed" not in run_check(cs.check_sync, project)
    details = run_check(cs.check_csv_round_trip, project)
    assert details["failed"] == (
        "CLICK's export shows Smoke_Init as ('DS100', '0', '50?C'), not ('DS100', '0', '50°C'). "
        "Its comment's bytes are 35 30 3f 43 (cp1252)."
    )


def test_a_runner_stop_in_a_check_ends_the_checks_and_reaches_the_runner(tmp_path, port):
    def error_box(project: cs.Project, details: dict[str, Any]) -> str:
        details["asked"] = "export"
        raise cr.ClickErrorBox("PTC-013", "The file is in use.")

    checks = (
        cs.CheckSpec("first", passes("OK.")),
        cs.CheckSpec("in_click", error_box),
        cs.CheckSpec("after", passes("OK.")),
    )
    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, checks, "C2-03CPU", "C0-02DD1-D")
    assert code == cs.EXIT_FAIL
    # The smoke goes on to the next project
    assert [s.cpu for s in runner.settings] == ["C2-03CPU", "C0-02DD1-D"]
    result = read(out / "C2-03CPU" / "result.json")
    entry = result["checks"]["in_click"]
    assert (entry["status"], entry["text"]) == (
        "fail",
        "The runner stopped: ClickErrorBox: CLICK error PTC-013: The file is in use.",
    )
    assert entry["details"]["asked"] == "export"
    assert "after" not in result["checks"]
    assert result["runner"]["status"] == "aborted"
    assert result["runner"]["reason"] == "CLICK error PTC-013: The file is in use."
    assert result["teardown"]["port_free"] is True
    assert result["problems"] == [
        "The runner ended aborted at step on_new_project: CLICK error PTC-013: The file is in use.",
        "These checks failed: in_click.",
        "These checks did not run: after.",
    ]


def test_exported_row_fails_when_no_row_has_the_nickname():
    data = f'{EXPORT_HEADER}\r\nDS1,INT,"Other",0,No,""\r\n'.encode("cp1252")
    with pytest.raises(cs.CheckFailed, match=r"^CLICK's export has no row for Smoke_Init\.$"):
        cs.exported_row(data, "Smoke_Init")


def test_the_checks_that_write_sc_mdb_run_after_the_checks_that_read_the_project():
    names = [spec.name for spec in cs.CHECKS]
    assert names[-3:] == ["check_program", "sync", "csv_round_trip"]
    needs = {spec.name: spec.needs for spec in cs.CHECKS}
    assert (needs["sync"], needs["csv_round_trip"]) == (("load",), ("sync",))
