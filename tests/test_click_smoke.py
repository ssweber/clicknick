"""Test the smoke (devtools/click_smoke.py) with a fake runner and fake checks.

No test starts CLICK or ClickNick's simulation. The fake runner calls the smoke's
``on_new_project`` as the runner's ``new`` mode does, and returns a runner result. The live run
of ``make smoke`` is the real check.
"""

from __future__ import annotations

import codecs
import csv
import dataclasses
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pyclickplc.banks import DataType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtools"))

import click_runner as cr  # noqa: E402
import click_smoke as cs  # noqa: E402

from clicknick.connection_session import SavedProgram  # noqa: E402
from clicknick.ladder.program import PrepareResult  # noqa: E402
from clicknick.models.address_row import AddressRow  # noqa: E402
from clicknick.services.analysis_service import AnalysisStatus  # noqa: E402
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
    # One runner run in new mode for each project, each into the project's runner/ folder. The
    # project with rungs is a project for the CPU that has the program's I/O
    cpus = {cs.PROGRAM_PROJECT: "C0-11DD1E-D"}
    assert [(s.command, s.cpu, s.out) for s in runner.settings] == [
        ("new", cpus.get(name, name), out / name / "runner") for name in cs.PROJECTS
    ]
    # ClickNick's settings go into the run's own LOCALAPPDATA
    assert runner.localappdata == [str(out / "localappdata")] * len(cs.PROJECTS)
    result = read(out / "C2-03CPU" / "result.json")
    assert list(result) == [
        "project",
        "cpu",
        "status",
        "problems",
        "elapsed",
        "runner",
        "checks",
        "callback_errors",
        "teardown",
    ]
    assert (result["project"], result["cpu"]) == ("C2-03CPU", "C2-03CPU")
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
    rungs = read(out / "rungs" / "result.json")
    assert (rungs["project"], rungs["cpu"]) == ("rungs", "C0-11DD1E-D")
    assert rungs["checks"]["first"]["details"] == {"model": "C0-11DD1E-D"}
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


def test_every_project_is_a_cpu_that_the_wizard_lists_no_cpu_or_the_project_with_rungs():
    assert set(cs.PROJECTS) <= {*cr.CPU_MODELS, cr.NO_CPU, cs.PROGRAM_PROJECT}
    assert cs.PROJECTS[-2:] == (cr.NO_CPU, cs.PROGRAM_PROJECT)
    assert cs.PROGRAM_CPU in cr.CPU_MODELS
    assert [cs.project_cpu(name) for name in cs.PROJECTS[-3:]] == [
        "C2-03CPU",
        cr.NO_CPU,
        cs.PROGRAM_CPU,
    ]


def test_the_io_of_a_pasted_program_is_its_x_and_y_addresses_without_xd_and_yd():
    pasted = cs.PastedProgram([], ("X001", "XD0", "C1", "Y002", "YD1", "DS3"))
    assert pasted.io == ("X001", "Y002")


def test_the_cpu_of_the_project_with_rungs_has_every_x_and_y_of_the_program():
    terminals = {
        terminal[2]
        for card in cs.recorded_layouts()[cs.PROGRAM_CPU]["cards"]
        for terminal in card["terminals"]
    }
    io = cs.PastedProgram([], cs.PROGRAM_ADDRESSES).io
    assert io == ("X001", "Y001", "X002", "X003", "X007", "X006", "X004", "Y002")
    assert set(io) <= terminals


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
    # Every CPU that the smoke makes a project for has recorded cards
    assert {cs.project_cpu(name) for name in cs.PROJECTS} <= set(layouts)
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
    """Stands in for ``SimulationSession`` in ``check_layout``.

    It holds a layout or an error, and the X and Y addresses that it counts as used.
    """

    def __init__(
        self, layout: Any, error: str | None = None, used: frozenset[str] = frozenset()
    ) -> None:
        self.layout = layout
        self.layout_error = error
        self.used = used

    def refresh_layout(self, *, force: bool = False) -> None:
        pass

    def _used_io(self) -> set[str]:
        return set(self.used)


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
    monkeypatch.setattr(sim_hardware, "read_panel_layout", lambda path, used: layout)
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


def test_exported_row_reads_a_byte_that_pythons_cp1252_lacks():
    # CLICK 4.00 wrote U+0081 in a nickname to its export as the byte 81
    data = f'{EXPORT_HEADER}\r\nDS100,INT,"Smoke_Init",0,Yes,"50x"\r\n'.encode()
    found = cs.exported_row(data.replace(b"50x", b"50\x81"), "Smoke_Init")
    assert (found["encoding"], found["comment"]) == ("cp1252", "50\x81")
    assert found["comment_bytes"] == "35 30 81"


def test_exported_row_fails_when_a_file_with_the_mark_does_not_decode_as_utf8():
    data = f'{EXPORT_HEADER}\r\nDS100,INT,"Smoke_Init",0,Yes,"x"\r\n'.encode() + b"\xff"
    with pytest.raises(cs.CheckFailed, match=r"^CLICK's export does not decode as utf-8-sig: "):
        cs.exported_row(codecs.BOM_UTF8 + data, "Smoke_Init")


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


def test_the_checks_that_change_the_project_run_after_the_checks_that_read_it():
    names = [spec.name for spec in cs.CHECKS]
    # The paste gives CLICK the program that the other checks read, so it comes first.
    # rung_apply adds a rung and saves the project in CLICK, so it comes last
    assert names[0] == "paste"
    assert names[-4:] == ["check_program", "sync", "csv_round_trip", "rung_apply"]
    needs = {spec.name: spec.needs for spec in cs.CHECKS}
    assert (needs["sync"], needs["csv_round_trip"], needs["rung_apply"]) == (
        ("load",),
        ("sync",),
        ("build",),
    )


# ---------------------------------------------------------------------------
# The rung_apply check
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "click_runner"
# CLICK's save after the rung_apply check pasted its rung and an END rung, from a live run of
# make smoke on 2026-11-21 (C0-02DD1-D)
RUNG_APPLY_SCR = FIXTURES / "rung_apply_Scr1.tmp"
# CLICK's save of a main program whose one rung copies 5 into DS1
OTHER_SCR = FIXTURES / "copy_5_ds1_Scr1.tmp"
# The main.py that pyrung 0.18.0 wrote for a project with no rungs, in a live run
GENERATED_MAIN = (
    "# Generated by pyrung from Click ladder CSV\n\n"
    "from pyrung import Program, rung\n"
    "from .tags import mapping\n\n"
    "with Program() as logic:\n"
    "    pass\n"
)
END_ROW = ["R", *["-"] * 31, "end()"]
COPY_ROW = ["R", *["-"] * 31, "copy(5,DS1)"]
Rows = list[list[str]]


def write_rows(path: Path, rows: Sequence[Sequence[str]]) -> None:
    """Write *rows* as a ladder CSV with laddercodec's header."""
    from laddercodec import CSV_HEADER

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)


def proposes_the_rung(source: str, saves: int) -> Rows:
    """Return what project_to_csv.py exports for main.py *source*: the rung and END, if any."""
    return [cs.RUNG_ROW, END_ROW] if cs.RUNG_SOURCE in source else []


class FakeAnalysis:
    """Stands in for ``AnalysisService`` once it has built the workspace in *project_dir*."""

    is_available = True
    check_selection = None

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.status = AnalysisStatus.READY
        self.error: str | None = None
        self.generation = 1


class FakeWorkspaceSession:
    """Stands in for ``ConnectionSession``: its analysis, and the saves that ScrWatcher counted."""

    def __init__(self, analysis: FakeAnalysis) -> None:
        self.analysis = analysis
        self.save_count = 0
        # With a note, a ready build has no csv folder to compare with, for that reason
        self.no_csv: str | None = None

    def saved_program(self) -> SavedProgram:
        ready = self.analysis.status is AnalysisStatus.READY and self.no_csv is None
        note = self.no_csv or "Could not build the workspace."
        return SavedProgram(
            self,  # pyright: ignore[reportArgumentType]
            self.analysis.generation,
            self.save_count,
            building=self.analysis.status is AnalysisStatus.BUILDING,
            csv_dir=self.analysis.project_dir / "csv" if ready else None,
            note="" if ready else note,
        )


class FakeRungRun(FakeClickRun):
    """Stands in for the runner's ``Run`` with a CLICK that pastes and saves.

    ``paste_payload`` keeps the bytes. ``save_as`` writes *scr* into CLICK's temp folder as its
    Scr1.tmp and calls ``on_save``. ``copy_temp`` copies the Scr*.tmp files.
    """

    def __init__(self, database: FakeDatabase, *, scr: Path) -> None:
        super().__init__(database)
        self.scr = scr
        self.pasted: bytes | None = None
        self.on_save: Callable[[], None] = lambda: None

    def paste_payload(self, payload: bytes, rungs: int, *, before: str, after: str) -> str:
        self.calls.append(("paste_payload", f"{rungs} rung(s)"))
        self.pasted = payload
        return "CLICK pasted"

    def save_as(self, ckp: Path, temp: Path, *, prefix: str = "") -> None:
        self.calls.append(("save_as", ckp.name))
        ckp.write_bytes(b"saved")
        (temp / "Scr1.tmp").write_bytes(self.scr.read_bytes())
        self.on_save()

    def copy_temp(self, temp: Path, click_dir: Path) -> list[Path]:
        self.calls.append(("copy_temp", click_dir.name))
        click_dir.mkdir(parents=True)
        return [Path(shutil.copy2(temp / "Scr1.tmp", click_dir / "Scr1.tmp"))]


class FakeCopyProject(FakeDatabaseProject):
    """A ``Project`` whose Copy encodes as Review Changes does and adds rows to the fake SC_.mdb.

    Copy adds a row for each address that ``prepare_rungs_load`` names, except the addresses
    in ``drops``. It reports ``mdb_error`` as the error that adding them met.
    """

    run: FakeRungRun  # pyright: ignore[reportIncompatibleVariableOverride]
    drops: tuple[str, ...] = ()
    mdb_error: str | None = None

    def prepare_paste(self, rungs: Sequence[Any]) -> PrepareResult:
        from pyclickplc.addresses import parse_address

        from clicknick.ladder.program import prepare_rungs_load

        prepared = prepare_rungs_load(list(rungs), click_v4=True)
        database = self.run.database
        added = [address for address in prepared.addresses if address not in self.drops]
        for address in added:
            memory_type, number = parse_address(address)
            row = AddressRow(memory_type=memory_type, address=number)
            database.rows[row.addr_key] = row
        database.write_file()
        return dataclasses.replace(
            prepared, addresses_inserted=len(added), mdb_error=self.mdb_error
        )


def rung_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    main_py: str = GENERATED_MAIN,
    click_rows: Rows | None = None,
    propose: Callable[[str, int], Rows] = proposes_the_rung,
    scr: Path = RUNG_APPLY_SCR,
    counts_save: bool = True,
    stays_building: bool = False,
    build_error: str | None = None,
    rebuilt_rows: Rows | None = None,
) -> FakeCopyProject:
    """Return a project with a built workspace, for ``check_rung_apply``.

    CLICK's main program holds *click_rows*, and the workspace's main.py holds *main_py*.
    ``rung apply`` runs its own code, with an export that writes what *propose* returns for
    main.py and the saves counted. After CLICK's save, the fake ScrWatcher counts the save,
    unless *counts_save* is False. With *stays_building*, the build after it never ends. With
    *build_error*, it fails. If not, it writes the main program of CLICK's save into csv/, or
    *rebuilt_rows* in its place.
    """
    from laddercodec import decode_program, write_csv

    from clicknick.data.address_store import AddressStore
    from clicknick.live import rung_commands

    monkeypatch.setattr(cs, "AFTER_RUNNER", 0.0)
    temp = tmp_path / "temp"
    temp.mkdir()
    workspace = temp / "pyrung_project"
    write_rows(workspace / "csv" / "main.csv", click_rows or [])
    source = workspace / "src" / "plc" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text(main_py, encoding="utf-8")
    database = FakeDatabase(temp / "SC_.mdb")
    new = cr.NewProject("C2-03CPU", tmp_path / "C2-03CPU.ckp", 4242, 0x1234, temp)
    folder = tmp_path / "project"
    folder.mkdir()
    run = FakeRungRun(database, scr=scr)
    project = FakeCopyProject(run, new, folder, cs.Scheduler(), timeout=5.0)  # pyright: ignore[reportArgumentType]
    project.store = AddressStore(database)  # pyright: ignore[reportArgumentType]
    project.store.load_initial_data()
    analysis = FakeAnalysis(workspace)
    session = FakeWorkspaceSession(analysis)
    project._session = session  # pyright: ignore[reportAttributeAccessIssue]

    def export(project_dir: Path) -> Path:
        main = (project_dir / "src" / "plc" / "main.py").read_text(encoding="utf-8")
        write_rows(project_dir / "csv_output" / "main.csv", propose(main, session.save_count))
        return project_dir / "csv_output"

    def rebuild() -> None:
        session.save_count += 1
        if stays_building:
            analysis.status = AnalysisStatus.BUILDING
            return
        if build_error is not None:
            analysis.status, analysis.error = AnalysisStatus.FAILED, build_error
            return
        main = workspace / "csv" / "main.csv"
        if rebuilt_rows is not None:
            write_rows(main, rebuilt_rows)
        else:
            write_csv(main, decode_program((temp / "Scr1.tmp").read_bytes()).rungs)
        analysis.generation += 1

    monkeypatch.setattr(rung_commands, "_run_export", export)
    if counts_save:
        run.on_save = lambda: project.scheduler.after(10, rebuild)
    return project


def test_the_rung_apply_check_passes_when_clicks_save_holds_the_rung(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch)
    details = run_check(cs.check_rung_apply, project)
    assert "failed" not in details, details["failed"]
    assert details["text"] == (
        "rung apply proposed 2 rung(s) for main. SC_.mdb held X001, C1 before the paste. CLICK "
        "saved the rung at rung 1, and after the build Review Changes has nothing left to paste."
    )
    assert cs.RUNG_SOURCE in details["main_py"]
    assert "\nchanged files:\n  main: R1..2\n" in details["rung_apply"]
    assert (details["click_main"], details["proposal"]) == ([], [cs.RUNG_ROW, END_ROW])
    assert details["copy"]["laddercodec_addresses"] == ["X001", "C1"]
    # CLICK's own save, decoded with laddercodec
    assert details["click_saved"] == [cs.RUNG_ROW, END_ROW]
    assert details["decode_warnings"] == []
    assert (details["saves"], details["generation_before"], details["generation_after"]) == (
        1,
        1,
        2,
    )
    assert "\n(no changes)\n" in details["rung_apply_after_save"]
    assert project.run.calls == [
        ("read_rows", "before_paste.mdb"),
        ("paste_payload", "2 rung(s)"),
        ("save_as", "rung_apply.ckp"),
        ("copy_temp", "click"),
    ]
    assert project.run.pasted is not None
    assert (project.folder / "rung_apply" / "click" / "Scr1.tmp").is_file()


def test_add_smoke_rung_puts_the_rung_in_place_of_pass_and_imports_its_names():
    assert cs.add_smoke_rung(GENERATED_MAIN) == (
        "# Generated by pyrung from Click ladder CSV\n\n"
        "from pyrung import Program, rung\n"
        "from .tags import mapping\n\n"
        "from pyrung import out\n"
        "from pyrung.click import ClickBlocks\n\n"
        "click = ClickBlocks()\n\n"
        "with Program() as logic:\n"
        "    with rung(click.x[1]):\n"
        "        out(click.c[1])\n"
    )


def test_the_rung_apply_check_fails_when_main_py_is_not_an_empty_program(tmp_path, monkeypatch):
    main_py = GENERATED_MAIN.replace("    pass\n", "    with rung(x[2]):\n        out(c[2])\n")
    project = rung_project(tmp_path, monkeypatch, main_py=main_py)
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "The workspace's main.py does not hold the empty program "
        "'with Program() as logic:\\n    pass\\n' once, so the check cannot add its rung there."
    )
    assert project.run.calls == []


def test_the_rung_apply_check_fails_when_rung_apply_proposes_no_change(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch, propose=lambda source, saves: [])
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"].startswith(
        "rung apply proposes no change to the main program. It answered: OK: wrote ladder CSVs"
    )
    assert "\n(no changes)\n" in details["failed"]
    assert project.run.calls == []


def test_the_rung_apply_check_fails_when_clicks_main_program_holds_rungs(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch, click_rows=[COPY_ROW])
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "CLICK's main program holds 1 rung(s). The runner can paste only at rung 1, so the "
        "check needs a main program with no rungs."
    )
    assert project.run.calls == []


def test_the_rung_apply_check_fails_when_the_proposal_starts_with_another_rung(
    tmp_path, monkeypatch
):
    project = rung_project(
        tmp_path, monkeypatch, propose=lambda source, saves: [COPY_ROW, cs.RUNG_ROW]
    )
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "The first rung that rung apply proposes is not the contact on X001 and the Out coil on "
        "C1 that the check added to main.py."
    )
    assert project.run.calls == []


def test_the_rung_apply_check_fails_when_copy_cannot_add_the_addresses(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch)
    project.mdb_error = "SC_.mdb is locked"
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "Copy could not add the rungs' addresses to SC_.mdb: SC_.mdb is locked"
    )
    assert project.run.calls == []


def test_the_rung_apply_check_fails_when_sc_mdb_lacks_an_address_of_the_rung(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch)
    project.drops = ("C1",)
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "SC_.mdb has no row for C1 after Copy. CLICK would drop those operands from the paste."
    )
    assert project.run.calls == [("read_rows", "before_paste.mdb")]


def test_the_rung_apply_check_fails_when_scrwatcher_does_not_count_the_save(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch, counts_save=False)
    project.save_timeout = 0.2
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "Timed out after 0.2 s waiting for ScrWatcher to count CLICK's save and the build "
        "after it to finish."
    )


def test_the_rung_apply_check_fails_when_the_build_after_the_save_does_not_end(
    tmp_path, monkeypatch
):
    project = rung_project(tmp_path, monkeypatch, stays_building=True)
    project.save_timeout = 0.2
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "Timed out after 0.2 s waiting for ScrWatcher to count CLICK's save and the build "
        "after it to finish."
    )


def test_the_rung_apply_check_fails_when_the_build_after_the_save_fails(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch, build_error="OSError: the disk is full")
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == "The build after CLICK's save failed: OSError: the disk is full"


def test_saved_main_program_fails_when_no_scr_file_holds_the_main_program(tmp_path):
    with pytest.raises(
        cs.CheckFailed, match=r"^No Scr\*\.tmp file in .* holds the main program\.$"
    ):
        cs.saved_main_program(tmp_path)


def test_the_rung_apply_check_fails_when_clicks_save_lacks_the_rung(tmp_path, monkeypatch):
    project = rung_project(tmp_path, monkeypatch, scr=OTHER_SCR)
    details = run_check(cs.check_rung_apply, project)
    assert details["click_saved"] == [COPY_ROW]
    assert details["failed"] == (
        "CLICK's save does not hold the contact on X001 and the Out coil on C1 at rung 1."
    )


def test_the_rung_apply_check_fails_when_review_changes_still_has_rungs_to_paste(
    tmp_path, monkeypatch
):
    # The build after the save reads a main program that lacks the END rung
    project = rung_project(tmp_path, monkeypatch, rebuilt_rows=[cs.RUNG_ROW])
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "After CLICK's save and the build, Review Changes still has rung(s) 2 of the proposal "
        "to paste in the main program."
    )


def test_the_rung_apply_check_fails_when_review_changes_still_has_rungs_to_delete(
    tmp_path, monkeypatch
):
    # The build after the save reads a main program with a third rung that the proposal lacks
    rebuilt = [cs.RUNG_ROW, END_ROW, COPY_ROW]
    project = rung_project(tmp_path, monkeypatch, rebuilt_rows=rebuilt)
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "After CLICK's save and the build, Review Changes still has CLICK's rung(s) 3 to delete "
        "in the main program."
    )


def test_the_rung_apply_check_fails_when_review_changes_finds_no_main_program(
    tmp_path, monkeypatch
):
    from clicknick.services import rung_diff

    project = rung_project(tmp_path, monkeypatch)
    compare = rung_diff.compare_bundle

    def compare_without_main_after_the_save(programs, click_dir):
        comparison = compare(programs, click_dir)
        if project.run.pasted is None:
            return comparison
        return dataclasses.replace(comparison, changes={})

    monkeypatch.setattr(rung_diff, "compare_bundle", compare_without_main_after_the_save)
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "After CLICK's save and the build, Review Changes finds no main program to compare."
    )


def test_the_rung_apply_check_fails_when_the_build_after_the_save_has_no_csv_folder(
    tmp_path, monkeypatch
):
    project = rung_project(tmp_path, monkeypatch)
    project._session.no_csv = "The workspace has no csv folder."  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "The build after CLICK's save failed: The workspace has no csv folder."
    )


@pytest.mark.parametrize(
    ("found", "text"),
    [([], "no address"), (["X001"], "X001"), (["X001", "C1", "DS1"], "X001, C1, DS1")],
)
def test_the_rung_apply_check_fails_when_the_copied_rungs_hold_other_addresses(
    tmp_path, monkeypatch, found, text
):
    import laddercodec

    project = rung_project(tmp_path, monkeypatch)
    monkeypatch.setattr(laddercodec, "addresses", lambda payload: list(found))
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (f"laddercodec finds {text} in the copied rungs, not X001 and C1.")
    assert project.run.calls == []


def test_prepare_paste_copies_for_clicks_window_and_its_sc_mdb(tmp_path, monkeypatch):
    from clicknick.ladder import clipboard, program
    from clicknick.utils import mdb_shared

    asked: dict[str, Any] = {}

    def prepare(rungs, *, click_v4, mdb_path):
        asked.update(rungs=rungs, click_v4=click_v4, mdb_path=mdb_path)
        return "prepared"

    def find(*, click_hwnd):
        asked["database_for"] = click_hwnd
        return str(tmp_path / "SC_.mdb")

    def v4(hwnd):
        asked["v4_for"] = hwnd
        return True

    monkeypatch.setattr(program, "prepare_rungs_load", prepare)
    monkeypatch.setattr(mdb_shared, "find_click_database", find)
    monkeypatch.setattr(clipboard, "is_click_v4", v4)
    new = cr.NewProject("C2-03CPU", tmp_path / "C2-03CPU.ckp", 4242, 0x1234, tmp_path)
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    assert project.prepare_paste(("rung",)) == "prepared"
    assert asked == {
        "database_for": 0x1234,
        "v4_for": 0x1234,
        "rungs": ["rung"],
        "click_v4": True,
        "mdb_path": tmp_path / "SC_.mdb",
    }


def test_the_rung_apply_check_fails_when_rung_apply_still_proposes_changes_after_the_save(
    tmp_path, monkeypatch
):
    def proposes_more_after_a_save(source: str, saves: int) -> Rows:
        return proposes_the_rung(source, saves) + ([COPY_ROW] if saves else [])

    project = rung_project(tmp_path, monkeypatch, propose=proposes_more_after_a_save)
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"].startswith(
        "After CLICK's save, rung apply still proposes changes: OK: wrote ladder CSVs"
    )
    assert "\nchanged files:\n  main: R3\n" in details["failed"]


# ---------------------------------------------------------------------------
# The project with rungs
# ---------------------------------------------------------------------------

# CLICK's save after the paste check pasted the rungs of click_smoke_rungs.csv, from a live run
# of make smoke on 2026-11-21 (C0-11DD1E-D)
PROGRAM_SCR = FIXTURES / "program_Scr1.tmp"


def program_rows() -> Rows:
    """Return the rungs of click_smoke_rungs.csv as the rows of laddercodec's CSV."""
    from laddercodec import csv_rows, read_csv

    return csv_rows(list(read_csv(cs.PROGRAM_CSV)))


def pasted_program() -> cs.PastedProgram:
    return cs.PastedProgram(program_rows(), cs.PROGRAM_ADDRESSES)


def test_the_projects_that_click_made_empty_run_every_check_but_the_paste_and_the_panel():
    checks = cs.project_checks(cs.CHECKS, program=False)
    assert [spec.name for spec in checks] == [
        "load",
        "build",
        "layout",
        "simulation",
        "check_program",
        "sync",
        "csv_round_trip",
        "rung_apply",
    ]
    assert {spec.name: spec.needs for spec in checks} == {
        spec.name: spec.needs for spec in cs.CHECKS if spec.projects != "program"
    }


def test_the_project_with_rungs_pastes_first_and_runs_every_check_but_rung_apply():
    checks = cs.project_checks(cs.CHECKS, program=True)
    assert [spec.name for spec in checks] == [
        "paste",
        "load",
        "build",
        "layout",
        "simulation",
        "panel",
        "check_program",
        "sync",
        "csv_round_trip",
    ]
    # If the paste fails, CLICK does not hold the program, so no other check runs. The panel
    # check needs the paste through the simulation check. If the panel check fails, the checks
    # after it still run
    assert {spec.name: spec.needs for spec in checks} == {
        "paste": (),
        "load": ("paste",),
        "build": ("paste", "load"),
        "layout": ("paste",),
        "simulation": ("paste", "build"),
        "panel": ("simulation",),
        "check_program": ("paste", "build"),
        "sync": ("paste", "load"),
        "csv_round_trip": ("paste", "sync"),
    }


def test_only_the_program_checks_at_the_start_are_needed_by_the_checks_for_every_project():
    checks = (
        cs.CheckSpec("paste", passes("pasted"), projects="program"),
        cs.CheckSpec("load", passes("loaded")),
        cs.CheckSpec("panel", passes("pressed"), needs=("load",), projects="program"),
        cs.CheckSpec("sync", passes("synced"), needs=("load",)),
        cs.CheckSpec("rung_apply", passes("applied"), projects="empty"),
    )
    program = cs.project_checks(checks, program=True)
    assert {spec.name: spec.needs for spec in program} == {
        "paste": (),
        "load": ("paste",),
        "panel": ("load",),
        "sync": ("paste", "load"),
    }
    empty = cs.project_checks(checks, program=False)
    assert {spec.name: spec.needs for spec in empty} == {
        "load": (),
        "sync": ("load",),
        "rung_apply": (),
    }


def test_the_smoke_makes_the_project_with_rungs_for_its_cpu_with_the_program(tmp_path, port):
    def program(project: cs.Project, details: dict[str, Any]) -> str:
        details["program"] = project.program
        raise cs.CheckFailed("CLICK refused the paste.")

    checks = (
        cs.CheckSpec("paste", program, projects="program"),
        cs.CheckSpec("first", passes("OK.")),
        cs.CheckSpec("empty", passes("OK."), projects="empty"),
    )
    runner = FakeRunner()
    code, out = smoke(tmp_path, runner, checks, "rungs", "C2-03CPU")
    assert code == cs.EXIT_FAIL
    assert [(s.cpu, s.out) for s in runner.settings] == [
        ("C0-11DD1E-D", out / "rungs" / "runner"),
        ("C2-03CPU", out / "C2-03CPU" / "runner"),
    ]
    rungs = read(out / "rungs" / "result.json")
    assert list(rungs["checks"]) == ["paste", "first"]
    assert rungs["checks"]["paste"]["details"] == {"program": str(cs.PROGRAM_CSV)}
    assert rungs["checks"]["first"]["text"] == "Not run, because paste did not pass."
    assert rungs["problems"] == ["These checks failed: paste, first."]
    cpu = read(out / "C2-03CPU" / "result.json")
    assert list(cpu["checks"]) == ["first", "empty"]
    assert cpu["status"] == "pass"


# The paste check


def paste_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, scr: Path = PROGRAM_SCR
) -> FakeCopyProject:
    """Return the project with rungs before the paste check, with CLICK's main program empty.

    After the save, CLICK's temp folder holds *scr* as its Scr1.tmp.
    """
    monkeypatch.setattr(cs, "AFTER_RUNNER", 0.0)
    temp = tmp_path / "temp"
    temp.mkdir()
    database = FakeDatabase(temp / "SC_.mdb")
    new = cr.NewProject(cs.PROGRAM_CPU, tmp_path / "C0-11DD1E-D.ckp", 4242, 0x1234, temp)
    folder = tmp_path / "project"
    folder.mkdir()
    run = FakeRungRun(database, scr=scr)
    return FakeCopyProject(run, new, folder, cs.Scheduler(), program=cs.PROGRAM_CSV)  # pyright: ignore[reportArgumentType]


def test_the_paste_check_passes_when_clicks_save_holds_the_program(tmp_path, monkeypatch):
    project = paste_project(tmp_path, monkeypatch)
    details = run_check(cs.check_paste, project)
    assert "failed" not in details, details["failed"]
    assert details["text"] == (
        "CLICK pasted the 9 rungs of click_smoke_rungs.csv at rung 1 and saved them. SC_.mdb "
        "held their 18 addresses before the paste."
    )
    rows = program_rows()
    assert len(rows) == 16
    # CLICK's own save, decoded with laddercodec
    assert details["click_saved"] == details["rows"] == rows
    assert details["decode_warnings"] == []
    assert details["copy"]["laddercodec_addresses"] == list(cs.PROGRAM_ADDRESSES)
    assert project.pasted == cs.PastedProgram(rows, cs.PROGRAM_ADDRESSES)
    assert project.run.calls == [
        ("read_rows", "before_program_paste.mdb"),
        ("paste_payload", "9 rung(s)"),
        ("save_as", "program.ckp"),
        ("copy_temp", "click"),
    ]
    # CLICK's window names the saved project, so the session must name it too
    assert project.new.ckp == project.folder / "paste" / "program.ckp"
    assert (project.folder / "paste" / "click" / "Scr1.tmp").is_file()


def test_the_paste_check_fails_when_copy_cannot_add_the_addresses(tmp_path, monkeypatch):
    project = paste_project(tmp_path, monkeypatch)
    project.mdb_error = "SC_.mdb is locked"
    details = run_check(cs.check_paste, project)
    assert details["failed"] == (
        "Copy could not add the rungs' addresses to SC_.mdb: SC_.mdb is locked"
    )
    assert (project.run.calls, project.pasted) == ([], None)


def test_the_paste_check_fails_when_the_copied_rungs_hold_other_addresses(tmp_path, monkeypatch):
    import laddercodec

    project = paste_project(tmp_path, monkeypatch)
    monkeypatch.setattr(laddercodec, "addresses", lambda payload: ["X001", "C1"])
    details = run_check(cs.check_paste, project)
    assert details["failed"] == (
        f"laddercodec finds X001, C1 in the copied rungs, not {', '.join(cs.PROGRAM_ADDRESSES)}."
    )
    assert (project.run.calls, project.pasted) == ([], None)


def test_the_paste_check_fails_when_sc_mdb_lacks_an_address_of_the_program(tmp_path, monkeypatch):
    project = paste_project(tmp_path, monkeypatch)
    project.drops = ("TD2", "DS3")
    details = run_check(cs.check_paste, project)
    assert details["failed"] == (
        "SC_.mdb has no row for TD2, DS3 after Copy. CLICK would drop those operands from the "
        "paste."
    )
    assert project.run.calls == [("read_rows", "before_program_paste.mdb")]
    assert project.pasted is None


def test_the_paste_check_fails_when_clicks_save_holds_another_program(tmp_path, monkeypatch):
    project = paste_project(tmp_path, monkeypatch, scr=RUNG_APPLY_SCR)
    details = run_check(cs.check_paste, project)
    assert details["failed"] == (
        "The main program in CLICK's save is not the program in click_smoke_rungs.csv. The "
        "check's details hold both, as click_saved and rows."
    )
    assert details["click_saved"] == [cs.RUNG_ROW, END_ROW]
    assert project.pasted is None


# The build check


class FakeBuildSession:
    """Stands in for ``ConnectionSession`` in ``check_build``. The build ends READY at once."""

    def __init__(self, analysis: FakeAnalysis) -> None:
        self.built = analysis
        self.analysis: FakeAnalysis | None = None

    def start_analysis(self, root: cs.Scheduler) -> None:
        self.analysis = self.built


class FakeBuiltAnalysis(FakeAnalysis):
    """A ``FakeAnalysis`` with the fields that ``check_build`` reads."""

    error_detail = None
    build_warning = None
    project_is_current = True


def check_build_with(tmp_path: Path, main_rows: Rows | None) -> dict[str, Any]:
    """Run ``check_build`` on the project with rungs, whose workspace csv/ holds *main_rows*."""
    temp = tmp_path / "temp"
    workspace = temp / "pyrung_project"
    main = workspace / "src" / "plc" / "main.py"
    main.parent.mkdir(parents=True)
    main.write_text(GENERATED_MAIN, encoding="utf-8")
    if main_rows is not None:
        write_rows(workspace / "csv" / "main.csv", main_rows)
    new = cr.NewProject(cs.PROGRAM_CPU, tmp_path / "program.ckp", 4242, 0x1234, temp)
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler(), timeout=1.0)  # pyright: ignore[reportArgumentType]
    project._session = FakeBuildSession(FakeBuiltAnalysis(workspace))  # pyright: ignore[reportAttributeAccessIssue]
    project.pasted = pasted_program()
    return run_check(cs.check_build, project)


def test_the_build_check_passes_when_the_workspace_holds_the_program_that_click_saved(tmp_path):
    details = check_build_with(tmp_path, program_rows())
    assert "failed" not in details, details["failed"]
    assert details["text"].endswith("Its csv/main.csv holds the 16 rows that CLICK saved.")
    assert details["main_csv"] == program_rows()


@pytest.mark.parametrize(
    "main_rows",
    [pytest.param(None, id="no-main-csv"), pytest.param([COPY_ROW, END_ROW], id="other-rungs")],
)
def test_the_build_check_fails_when_the_workspace_holds_another_program(tmp_path, main_rows):
    details = check_build_with(tmp_path, main_rows)
    assert details["failed"] == (
        "The workspace's csv/main.csv is not the program that CLICK saved. The details hold it "
        "as main_csv, and the paste check's details hold CLICK's save."
    )
    assert details["main_csv"] == main_rows


# The layout check


PROGRAM_IO = ("X001", "Y001", "X002", "X003", "X007", "X006", "X004", "Y002")


def check_program_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, used: frozenset[str]
) -> tuple[dict[str, Any], list[tuple[str, ...]]]:
    """Run ``check_layout`` on the project with rungs, whose simulation counts *used* as used.

    Return the check's details and the used I/O that each call to ``read_panel_layout`` got.
    """
    from clicknick.services import sim_hardware

    recorded = cs.recorded_layouts()[cs.PROGRAM_CPU]
    layout = sim_hardware.PanelLayout(
        tuple(
            sim_hardware.Card(
                card["location"],
                card["position"],
                card["model"],
                tuple(sim_hardware.Terminal(*terminal) for terminal in card["terminals"]),
                card["installed"],
            )
            for card in recorded["cards"]
        )
    )
    asked: list[tuple[str, ...]] = []

    def read_panel_layout(path: Path, used: tuple[str, ...]) -> Any:
        asked.append(tuple(used))
        return layout

    monkeypatch.setattr(sim_hardware, "read_panel_layout", read_panel_layout)
    ini = tmp_path / "Project.ini"
    ini.write_bytes(b"")
    new = cr.NewProject(cs.PROGRAM_CPU, tmp_path / "program.ckp", 4242, 0x1234, tmp_path)
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    simulation = FakeLayoutSimulation(layout, used=used)
    project._session = FakeLayoutSession(simulation, ini)  # pyright: ignore[reportAttributeAccessIssue]
    project.pasted = pasted_program()
    return run_check(cs.check_layout, project), asked


def test_the_layout_check_reads_project_ini_with_the_x_and_y_of_the_program(tmp_path, monkeypatch):
    # The simulation also counts an address that the program does not use
    used = frozenset({*PROGRAM_IO, "X005"})
    details, asked = check_program_layout(tmp_path, monkeypatch, used)
    assert "failed" not in details, details["failed"]
    assert details["text"] == "1 card(s), as read_panel_layout reads them and as recorded."
    assert asked == [PROGRAM_IO]
    assert details["program_io"] == list(PROGRAM_IO)
    assert details["simulator_used_io"] == sorted(used)


@pytest.mark.parametrize(
    ("used", "unseen"),
    [
        pytest.param(frozenset(), ", ".join(PROGRAM_IO), id="none"),
        pytest.param(frozenset(PROGRAM_IO) - {"X006", "Y002"}, "X006, Y002", id="some"),
    ],
)
def test_the_layout_check_fails_when_the_simulation_does_not_count_the_programs_io_as_used(
    tmp_path, monkeypatch, used, unseen
):
    # The CPU has every X and Y of the program, so the cards are the recorded cards either way
    details, asked = check_program_layout(tmp_path, monkeypatch, used)
    assert details["failed"] == (
        f"The program uses {unseen}, but the simulation does not list them as used."
    )
    assert details["simulator_used_io"] == sorted(used)
    assert asked == []


# The simulation check


class FakeProgramSimulation(FakeSimulation):
    """A ``FakeSimulation`` that runs the first rung of click_smoke_rungs.csv.

    Once the check watches addresses, ``values`` holds them all off, as Modbus reads them.
    With *silent*, Modbus never answers for that address. With *output_on*, Y001 is on from the
    start. Turning X001 on turns Y001 on, unless *dead* is True.
    """

    def __init__(
        self, *, silent: str | None = None, output_on: bool = False, dead: bool = False
    ) -> None:
        super().__init__()
        self.silent = silent
        self.output_on = output_on
        self.dead = dead
        self.io: dict[str, bool] = {}
        self.watched: tuple[str, ...] | None = None

    def watch(self, owner: object, addresses: Sequence[str]) -> None:
        self.watched = tuple(addresses)
        self.io = {address: False for address in addresses if address != self.silent}
        if self.output_on:
            self.io["Y001"] = True

    def unwatch(self, owner: object) -> None:
        self.watched = None

    @property
    def values(self) -> dict[str, bool]:
        return dict(self.io)

    def toggle_switch(self, address: str) -> None:
        self.io[address] = not self.io[address]
        if address == "X001" and self.io[address] and not self.dead:
            self.io["Y001"] = True


def check_program_simulation(
    tmp_path: Path, simulation: FakeProgramSimulation
) -> tuple[dict[str, Any], FakeProgramSimulation]:
    new = cr.NewProject(cs.PROGRAM_CPU, tmp_path / "program.ckp", 4242, 0x1234, tmp_path)
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    project._session = FakeSession(simulation)  # pyright: ignore[reportAttributeAccessIssue]
    project.pasted = pasted_program()
    return run_check(cs.check_simulation, project), simulation


def test_the_simulation_check_turns_x001_on_and_sees_y001_turn_on(tmp_path, port):
    details, simulation = check_program_simulation(tmp_path, FakeProgramSimulation())
    assert "failed" not in details, details["failed"]
    assert details["text"].endswith(
        " Modbus read the program's 8 X and Y addresses. X001 on turned Y001 on."
    )
    io = ("X001", "Y001", "X002", "X003", "X007", "X006", "X004", "Y002")
    assert details["io_before"] == dict.fromkeys(io, False)
    assert details["io_after"] == {**dict.fromkeys(io, False), "X001": True, "Y001": True}
    assert simulation.watched is None


def test_the_simulation_check_fails_when_modbus_never_reads_an_address(tmp_path, port, monkeypatch):
    monkeypatch.setattr(cs, "RUN_WAIT", 1.0)
    details, simulation = check_program_simulation(tmp_path, FakeProgramSimulation(silent="X006"))
    assert details["failed"] == (
        "Timed out after 1 s waiting for Modbus values for X001, Y001, X002, X003, X007, "
        "X006, X004, Y002."
    )
    assert simulation.watched is None


def test_the_simulation_check_fails_when_y001_is_on_before_x001(tmp_path, port):
    details, simulation = check_program_simulation(tmp_path, FakeProgramSimulation(output_on=True))
    assert details["failed"] == (
        "Y001 is on before the check turns X001 on, so the check cannot show that the program "
        "drives it."
    )
    assert simulation.io["X001"] is False
    assert simulation.watched is None


def test_the_simulation_check_fails_when_x001_does_not_turn_y001_on(tmp_path, port, monkeypatch):
    monkeypatch.setattr(cs, "RUN_WAIT", 1.0)
    details, simulation = check_program_simulation(tmp_path, FakeProgramSimulation(dead=True))
    assert details["failed"] == "Timed out after 1 s waiting for Y001 to turn on after X001."
    assert simulation.watched is None


# The panel check


class PanelPlant:
    """Runs the first rung of click_smoke_rungs.csv on the fake pyrung of a ``Harness``.

    X001 latches Y001. Each ``pump`` runs the simulation's scheduled callbacks, answers the DAP
    requests that the simulation sent since the last pump, runs one scan in RUN, and hands the
    values of X001 and Y001 to the simulation, as Modbus does. In STOP, Y001 reads off. A force
    on Y001 replaces its value. Each flag breaks one part of that:

    - with *latches* False, X001 does not turn Y001 on;
    - with *holds* False, Y001 follows X001, as an Out coil does;
    - with *clears* False, the switch from STOP to RUN does not clear Y001;
    - with *forces* False, a force on Y001 does not change its value.

    With *stale_stop* True, the plant does what pyrung 0.18.0 did after STOP. It sends the
    frame of STOP, then the frame of its last scan in RUN once more: mode run, not running.
    """

    def __init__(
        self,
        harness: Any,
        *,
        latches: bool = True,
        holds: bool = True,
        clears: bool = True,
        forces: bool = True,
        stale_stop: bool = False,
    ) -> None:
        self.harness = harness
        self.latches, self.holds, self.clears, self.forces = latches, holds, clears, forces
        self.stale_stop = stale_stop
        self.seen = 0
        self.inputs: dict[str, bool] = {}
        self.output = False

    def pump(self) -> None:
        harness = self.harness
        harness.scheduler.run_ready()
        dap = harness.dap
        while self.seen < len(dap.calls):
            call = dap.calls[self.seen]
            self.seen += 1
            if call[0] == "set_mode":
                self.inputs.update(call[2] or {})
                if call[1] == "stop":
                    dap.frame(mode="stop", running=False)
                    if self.stale_stop:
                        dap.frame(mode="run", running=False)
                else:
                    if self.clears:
                        self.output = False
                    dap.frame(mode="run", running=False)
            elif call[0] == "continue":
                dap.frame(running=True)
            elif call[0] == "patch":
                self.inputs.update(call[1])
        x001 = bool(self.inputs.get("X001"))
        if dap.mode == "run" and dap.running:
            if x001 and self.latches:
                self.output = True
            if not self.holds:
                self.output = x001
            dap.frame(scan_id=(dap.scan_id or 0) + 1)
        y001 = self.output and dap.mode == "run"
        forced = dap.forces.get("Y001") if self.forces else None
        if forced is not None:
            y001 = forced
        harness.modbus[-1].kwargs["on_values"]({"X001": x001, "Y001": y001})
        harness.scheduler.run_ready()


class PlantScheduler(cs.Scheduler):
    """A ``cs.Scheduler`` whose ``run_due`` pumps a ``PanelPlant``."""

    def __init__(self, plant: PanelPlant) -> None:
        super().__init__()
        self.plant = plant

    def run_due(self) -> None:
        self.plant.pump()


@pytest.fixture
def panel_harness(tmp_path, monkeypatch):
    from test_simulation_session import Harness, _ready_analysis

    from clicknick.views.console_panel import ConsolePanel

    # The Console's grammar loads on a thread, which no panel test needs
    monkeypatch.setattr(ConsolePanel, "_start_background", lambda _self, _target, *, name: None)
    project_dir = tmp_path / "workspace"
    project_dir.mkdir()
    return Harness(tmp_path, _ready_analysis(project_dir))


def press_panel_with(
    tmp_path: Path, root: Any, harness: Any, plant: PanelPlant
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Leave the harness's simulation in RUN as the simulation check does, then press the panel.

    The simulation check left X001's switch on and Y001 latched. Return the check's details,
    with its text or failure, and the details' steps by name.
    """
    harness.open()
    harness.sim.set_switch_position("run")
    harness.sim.toggle_switch("X001")
    for _ in range(3):
        plant.pump()
    assert harness.sim.values == {"X001": True, "Y001": plant.latches}
    new = cr.NewProject(cs.PROGRAM_CPU, tmp_path / "program.ckp", 4242, 0x1234, tmp_path)
    project = cs.Project(FakeRun(), new, tmp_path, PlantScheduler(plant))  # pyright: ignore[reportArgumentType]
    project._session = SimpleNamespace(  # pyright: ignore[reportAttributeAccessIssue]
        ensure_simulation=lambda _scheduler: harness.sim, analysis=harness.analysis
    )
    details: dict[str, Any] = {}
    try:
        details["text"] = cs.press_panel(project, root, details, timeout=1.0, realtime=False)
    except cs.CheckFailed as exc:
        details["failed"] = str(exc)
    return details, {step.pop("step"): step for step in details.get("steps", [])}


def test_the_panel_check_presses_x001_and_forces_y001_on_the_panel(
    tmp_path, tk_root, panel_harness
):
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, PanelPlant(panel_harness))
    assert "failed" not in details, details["failed"]
    assert details["text"] == (
        "On the Simulator's panel, STOP and RUN moved the CPU's switch. X001's switch turned "
        "Y001 on, and Y001 stayed on after X001 turned off. A double-click forced Y001 off and "
        "showed its padlock, and a click on the padlock released the force."
    )
    assert list(steps) == [
        "stop",
        "X001 off in STOP",
        "run",
        "X001 on",
        "X001 off",
        "Y001 forced",
        "Y001 released",
    ]
    shown = {
        name: (step["switch_position"], step["run_led"], step["X001"], step["Y001"])
        for name, step in steps.items()
    }
    # In STOP, PanelPlant still reads X001 on. After the release, Y001 shows the latch again,
    # because PanelPlant keeps the latch under the force
    off = {"switch": False, "lit": False, "padlock": False}
    on = {"switch": True, "lit": True, "padlock": False}
    assert shown == {
        "stop": ("stop", False, on, {"lit": False, "padlock": False}),
        "X001 off in STOP": ("stop", False, off, {"lit": False, "padlock": False}),
        "run": ("run", True, off, {"lit": False, "padlock": False}),
        "X001 on": ("run", True, on, {"lit": True, "padlock": False}),
        "X001 off": ("run", True, off, {"lit": True, "padlock": False}),
        "Y001 forced": ("run", True, off, {"lit": False, "padlock": True}),
        "Y001 released": ("run", True, off, {"lit": True, "padlock": False}),
    }  # fmt: skip
    assert steps["Y001 forced"]["forces"] == {"Y001": False}
    assert steps["Y001 forced"]["forces_button"] == "Forces (1)"
    assert steps["Y001 released"]["forces_button"] == "Forces"
    # The panel's clicks reached the simulation as the DAP requests that the panel sends
    dap = panel_harness.dap
    assert ("set_mode", "stop", None, None) in dap.calls
    assert ("patch", {"X001": False}) in dap.calls
    assert ("force", "Y001", False) in dap.calls
    assert ("unforce", "Y001") in dap.calls
    # The check closed the window, which stopped watching the panel's addresses
    assert len(panel_harness.sim._watched) == 0


def test_the_panel_check_fails_when_x001_does_not_light_y001(tmp_path, tk_root, panel_harness):
    plant = PanelPlant(panel_harness, latches=False)
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    assert details["failed"] == (
        "On the Simulator's panel, the check timed out waiting for Y001's LED to light after "
        "X001 turned on."
    )
    assert list(steps) == [
        "stop",
        "X001 off in STOP",
        "run",
        "timed out waiting for Y001's LED to light after X001 turned on",
    ]
    # The step at the timeout shows what the panel showed then
    timed_out = steps["timed out waiting for Y001's LED to light after X001 turned on"]
    assert timed_out["switch_position"] == "run"
    assert timed_out["X001"] == {"switch": True, "lit": True, "padlock": False}
    assert timed_out["Y001"] == {"lit": False, "padlock": False}


def test_the_panel_check_fails_when_the_switch_shows_step_after_stop(
    tmp_path, tk_root, panel_harness
):
    plant = PanelPlant(panel_harness, stale_stop=True)
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    assert details["failed"] == (
        "On the Simulator's panel, the check timed out waiting for STOP, with the RUN LED off."
    )
    assert list(steps) == ["timed out waiting for STOP, with the RUN LED off"]
    assert steps["timed out waiting for STOP, with the RUN LED off"]["switch_position"] == "step"


FORCE_WAIT = (
    "the double-click to force Y001 off, with its LED dark, its padlock showing and the "
    "toolbar's Forces (1)"
)
RELEASE_WAIT = "the click on the padlock to release Y001's force and hide the padlock"


def fill(item: str, color: str) -> Callable[[Any], None]:
    """Return a step that colors the panel's *item* (``"RUN"``, or an address and a part)."""

    def step(win: Any) -> None:
        if item == "RUN":
            canvas_item = win._cpu_leds["RUN"]
        else:
            address, part = item.split(".")
            rows = win._inputs if address.startswith("X") else win._outputs
            canvas_item = rows[address][part]
        win._canvas.itemconfigure(canvas_item, fill=color)

    return step


def after_first_force(step: Callable[[Any, bool], None]) -> Callable[[Any], None]:
    """Return a step that calls *step* with True once the simulation has held a force."""
    forced: list[bool] = []

    def after(win: Any) -> None:
        if win._simulation.forces:
            forced.append(True)
        step(win, bool(forced))

    return after


def panel_faults() -> dict[str, tuple[str, Callable[[Any], None], str, dict[str, bool]]]:
    """Return the ways that a test breaks the panel, by name.

    Each fault names the ``SimulatorWindow`` method after which it draws one thing wrong, the
    step that draws it, the wait that must time out, and the flags for ``PanelPlant``.
    """
    from clicknick.views import sim_palette as p

    def padlock(win: Any, shown: bool) -> None:
        win._show_badge(win._outputs["Y001"]["badge"], shown)

    def counted(win: Any, shown: bool) -> None:
        win._forces_btn.configure(text="Forces (1)" if shown else "Forces")

    def dark_while_forced(win: Any, forced: bool) -> None:
        if forced:
            fill("Y001.led", p.LED_OFF)(win)

    return {
        "the RUN LED stays dark": (
            "_refresh_cpu", fill("RUN", p.LED_OFF), "RUN, with the RUN LED lit", {}
        ),
        "the RUN LED stays lit": (
            "_refresh_cpu", fill("RUN", p.LED_ON), "STOP, with the RUN LED off", {}
        ),
        "X001's switch stays off": (
            "_refresh_inputs", fill("X001.track", p.SWITCH_OFF),
            "X001's switch and LED to show on", {},
        ),
        "X001's LED stays lit": (
            "_refresh_inputs", fill("X001.led", p.LED_ON), "X001's switch and LED to show off", {}
        ),
        "Y001's LED stays dark": (
            "_refresh_outputs", fill("Y001.led", p.LED_OFF),
            "Y001's LED to light after X001 turned on", {},
        ),
        "Y001 shows no padlock": (
            "_refresh_outputs", lambda win: padlock(win, False), FORCE_WAIT, {}
        ),
        "Y001 keeps its padlock": ("_refresh_outputs", after_first_force(padlock), RELEASE_WAIT, {}),
        "the Forces button counts no force": (
            "_refresh_toolbar", lambda win: counted(win, False), FORCE_WAIT, {}
        ),
        "the Forces button keeps its count": (
            "_refresh_toolbar", after_first_force(counted), RELEASE_WAIT, {}
        ),
        # The simulation never applies the force, but the panel draws Y001 dark anyway
        "Y001 shows dark while the simulation reads it on": (
            "_refresh_outputs", after_first_force(dark_while_forced), FORCE_WAIT,
            {"forces": False},
        ),
    }  # fmt: skip


@pytest.mark.parametrize("fault", list(panel_faults()))
def test_the_panel_check_fails_when_the_panel_draws_something_wrong(
    tmp_path, tk_root, panel_harness, monkeypatch, fault
):
    from clicknick.views.simulator_window import SimulatorWindow

    method, step, wait, flags = panel_faults()[fault]
    original = getattr(SimulatorWindow, method)

    def wrong(self: Any, *args: Any) -> None:
        original(self, *args)
        step(self)

    monkeypatch.setattr(SimulatorWindow, method, wrong)
    plant = PanelPlant(panel_harness, **flags)
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    assert (
        details.get("failed")
        == f"On the Simulator's panel, the check timed out waiting for {wait}."
    )
    assert list(steps)[-1] == f"timed out waiting for {wait}"
    # The check released the force that it left in place
    assert panel_harness.sim.forces == {}


def test_the_panel_check_fails_when_y001_goes_off_with_x001(tmp_path, tk_root, panel_harness):
    plant = PanelPlant(panel_harness, holds=False)
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    assert details["failed"] == ("The program latches Y001, but it went off after X001 turned off.")
    assert list(steps)[-1] == "X001 off"


def test_the_panel_check_fails_when_y001_is_on_after_stop_and_run(tmp_path, tk_root, panel_harness):
    plant = PanelPlant(panel_harness, clears=False)
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    assert details["failed"] == (
        "Y001 is on after STOP and RUN with X001 off, so the check cannot show that X001 turns "
        "it on."
    )
    assert list(steps)[-1] == "run"


def test_the_panel_check_fails_and_releases_a_force_that_does_not_reach_y001(
    tmp_path, tk_root, panel_harness
):
    plant = PanelPlant(panel_harness, forces=False)
    details, steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    assert details["failed"] == (
        "On the Simulator's panel, the check timed out waiting for the double-click to force "
        "Y001 off, with its LED dark, its padlock showing and the toolbar's Forces (1)."
    )
    assert list(steps)[-2:] == ["X001 off", f"timed out waiting for {FORCE_WAIT}"]
    assert panel_harness.sim.forces == {}
    assert ("clear_forces",) in panel_harness.dap.calls


def test_the_panel_check_closes_the_window_when_the_release_of_the_forces_raises(
    tmp_path, tk_root, panel_harness, monkeypatch
):
    def raises() -> None:
        raise RuntimeError("the worker is gone")

    monkeypatch.setattr(panel_harness.sim, "release_all_forces", raises)
    plant = PanelPlant(panel_harness, forces=False)
    details, _steps = press_panel_with(tmp_path, tk_root, panel_harness, plant)
    # The scene's failure stands, and the window closed after the release raised
    assert (
        details["failed"]
        == f"On the Simulator's panel, the check timed out waiting for {FORCE_WAIT}."
    )
    assert len(panel_harness.sim._watched) == 0


def test_the_panel_check_fails_when_the_close_of_the_window_raises_after_a_pass(
    tmp_path, tk_root, panel_harness, monkeypatch
):
    from clicknick.views.simulator_window import SimulatorWindow

    original = SimulatorWindow._on_close

    def close_and_raise(self: Any) -> None:
        original(self)
        raise RuntimeError("the window is gone")

    monkeypatch.setattr(SimulatorWindow, "_on_close", close_and_raise)
    details, _steps = press_panel_with(tmp_path, tk_root, panel_harness, PanelPlant(panel_harness))
    assert details["failed"] == (
        "The steps on the Simulator's panel passed, but the check could not close the Simulator "
        "window (RuntimeError: the window is gone)."
    )


class TimeoutPlant(PanelPlant):
    """A ``PanelPlant`` whose pump raises ``TimeoutError`` once, after the panel check starts.

    The pumps after that one work, so the check's cleanup runs as it does after any failure.
    """

    def __init__(self, harness: Any) -> None:
        super().__init__(harness)
        self.pumps = 0

    def pump(self) -> None:
        self.pumps += 1
        # press_panel_with pumps 3 times before the check starts
        if self.pumps == 6:
            raise TimeoutError("timed out")
        super().pump()


def test_the_panel_check_does_not_report_a_timeout_in_a_pump_as_a_wait(
    tmp_path, tk_root, panel_harness
):
    with pytest.raises(TimeoutError, match="^timed out$"):
        press_panel_with(tmp_path, tk_root, panel_harness, TimeoutPlant(panel_harness))


# The csv_round_trip check


def program_click_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **run: Any
) -> FakeDatabaseProject:
    """Return the project with rungs after the paste, whose SC_.mdb holds the program's rows.

    Each of those rows is used and has no content.
    """
    from pyclickplc.addresses import parse_address
    from pyclickplc.banks import DEFAULT_RETENTIVE, MEMORY_TYPE_TO_DATA_TYPE

    rows = []
    for address in cs.PROGRAM_ADDRESSES:
        memory_type, number = parse_address(address)
        row = AddressRow(
            memory_type=memory_type,
            address=number,
            data_type=MEMORY_TYPE_TO_DATA_TYPE[memory_type],
            retentive=DEFAULT_RETENTIVE[memory_type],
            used=True,
        )
        assert not row.has_content
        rows.append(row)
    project = click_project(tmp_path, monkeypatch, rows, **run)
    project.pasted = pasted_program()
    return project


def test_the_csv_round_trip_check_passes_when_the_import_removes_the_rows_of_the_program(
    tmp_path, monkeypatch
):
    project = program_click_project(tmp_path, monkeypatch)
    assert "failed" not in run_check(cs.check_sync, project)
    details = run_check(cs.check_csv_round_trip, project)
    assert "failed" not in details, details["failed"]
    # ClickNick's file holds no row of the program, because none has content
    assert details["addresses"] == {
        "file": ["DS100"],
        "mdb": ["DS100"],
        "program": sorted(cs.PROGRAM_ADDRESSES),
    }


def test_the_csv_round_trip_check_fails_when_sc_mdb_keeps_a_row_of_the_program(
    tmp_path, monkeypatch
):
    def keeps_x001(rows: dict[int, AddressRow]) -> dict[int, AddressRow]:
        row = AddressRow(memory_type="X", address=1, used=True)
        return {**rows, row.addr_key: row}

    project = program_click_project(tmp_path, monkeypatch, misread=keeps_x001)
    assert "failed" not in run_check(cs.check_sync, project)
    details = run_check(cs.check_csv_round_trip, project)
    assert details["failed"] == (
        "After the import, SC_.mdb lacks [] from ClickNick's CSV and holds ['X001'] that the file "
        "lacks."
    )


# The check_program check


class FakeCheckSession:
    """Stands in for ``ConnectionSession`` in ``check_program``."""

    def __init__(self) -> None:
        self.analysis = self
        self.validated = 0

    def run_validation(self) -> object:
        self.validated += 1
        return object()


# The start of the report that Check Program gave on the project with rungs in a live run of
# make smoke on 2026-11-21
CONFLICT_REPORT = (
    "Check Program: 1 error, 1 warning\n15 checks ran. 17 were not run.\n\n"
    "error[COIL_CONFLICTING_OUTPUT] Conflicting Output\n"
    "  Y002 is set by multiple instructions in one scan.\n"
)
CLEAN_REPORT = "Check Program: the 15 selected checks passed. 17 checks were not run."


def check_program_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app: str,
    cli: str,
    *,
    pasted: bool = True,
) -> dict[str, Any]:
    """Run ``check_program``, with *app* as Check Program's report and *cli* as the CLI's text."""
    from clicknick.live import dispatch
    from clicknick.services import program_check

    monkeypatch.setattr(program_check, "format_validation_report", lambda report: app)
    monkeypatch.setattr(dispatch, "dispatch", lambda context, command: cli)
    new = cr.NewProject(cs.PROGRAM_CPU, tmp_path / "program.ckp", 4242, 0x1234, tmp_path)
    project = cs.Project(FakeRun(), new, tmp_path, cs.Scheduler())  # pyright: ignore[reportArgumentType]
    project._session = FakeCheckSession()  # pyright: ignore[reportAttributeAccessIssue]
    if pasted:
        project.pasted = pasted_program()
    return run_check(cs.check_program, project)


def test_the_program_check_passes_when_both_ways_report_the_conflict_on_y002(tmp_path, monkeypatch):
    cli = f"{CONFLICT_REPORT}\nOK: checked"
    details = check_program_with(tmp_path, monkeypatch, CONFLICT_REPORT, cli)
    assert "failed" not in details, details["failed"]
    assert details["text"] == "Both report: Check Program: 1 error, 1 warning"
    assert (details["app"], details["cli"]) == (CONFLICT_REPORT, cli)


def test_the_program_check_does_not_ask_for_the_conflict_in_a_project_with_no_rungs(
    tmp_path, monkeypatch
):
    details = check_program_with(tmp_path, monkeypatch, CLEAN_REPORT, CLEAN_REPORT, pasted=False)
    assert "failed" not in details, details["failed"]


@pytest.mark.parametrize(
    ("app", "cli", "way"),
    [
        pytest.param(CLEAN_REPORT, CLEAN_REPORT, "Check Program", id="no-finding"),
        pytest.param(
            CONFLICT_REPORT.replace("Y002", "Y003"),
            CONFLICT_REPORT.replace("Y002", "Y003"),
            "Check Program",
            id="another-address",
        ),
        pytest.param(
            CONFLICT_REPORT.replace("COIL_CONFLICTING_OUTPUT", "TAG_DEAD_WRITE"),
            CONFLICT_REPORT.replace("COIL_CONFLICTING_OUTPUT", "TAG_DEAD_WRITE"),
            "Check Program",
            id="another-finding",
        ),
    ],
)
def test_the_program_check_fails_when_a_report_lacks_the_conflict_on_y002(
    tmp_path, monkeypatch, app, cli, way
):
    details = check_program_with(tmp_path, monkeypatch, app, cli)
    assert details["failed"] == (
        f"{way} does not report COIL_CONFLICTING_OUTPUT on Y002, but two rungs of the program "
        "drive Y002 with an Out coil."
    )


# The rung_apply check, when ClickNick cannot read CLICK's copy


def test_the_rung_apply_check_fails_when_clicknick_cannot_read_clicks_copy_after_the_save(
    tmp_path, monkeypatch
):
    from clicknick.ladder.program import unreadable_copy
    from clicknick.services import rung_diff

    project = rung_project(tmp_path, monkeypatch)
    compare = rung_diff.compare_bundle

    def compare_unreadable_after_the_save(programs, click_dir):
        comparison = compare(programs, click_dir)
        if project.run.pasted is None:
            return comparison
        # No opcodes, so no rung to paste or to delete. ClickNick cannot read the program
        unreadable = rung_diff.ProgramChange(
            legacy=(unreadable_copy("main.csv", "main", ValueError("bad row")),)
        )
        assert unreadable.unreadable and unreadable.differs
        assert (unreadable.changed, unreadable.removed) == ((), ())
        return dataclasses.replace(comparison, changes={cs.MAIN_CSV: unreadable})

    monkeypatch.setattr(rung_diff, "compare_bundle", compare_unreadable_after_the_save)
    details = run_check(cs.check_rung_apply, project)
    assert details["failed"] == (
        "After CLICK's save and the build, ClickNick cannot read CLICK's copy of the main "
        "program, so Review Changes would paste it whole again."
    )
