"""DapService without a pyrung subprocess: launch and request failures."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from clicknick.services import dap_service
from clicknick.services.dap_service import DapRequestError, DapService, DapUnavailableError


class _Scripted(DapService):
    """Answers each request from *answers* (None: no answer in time)."""

    def __init__(self, answers, **callbacks) -> None:
        super().__init__(**callbacks)
        self.answers = answers
        self.sent: list[str] = []

    def _send_and_wait(self, command, arguments=None, timeout=10.0):
        self.sent.append(command)
        return self.answers.get(command, {"success": True})


@pytest.fixture()
def no_subprocess(monkeypatch):
    procs: list = []

    def popen(*_args, **_kwargs):
        proc = SimpleNamespace(
            stdin=io.BytesIO(),
            stdout=io.BytesIO(),
            stderr=io.BytesIO(),
            kill=lambda: procs.append("killed"),
            wait=lambda timeout=None: 0,
        )
        return proc

    monkeypatch.setattr(dap_service.subprocess, "Popen", popen)
    monkeypatch.setattr(dap_service, "headless_python", lambda: "python")
    monkeypatch.setattr(dap_service, "project_environment", lambda _dir: {})
    return procs


def test_a_launch_whose_configuration_done_goes_unanswered_fails(tmp_path, no_subprocess):
    (tmp_path / "run.py").write_text("x", encoding="utf-8")
    dap = _Scripted({"configurationDone": None})

    with pytest.raises(RuntimeError, match="configurationDone"):
        dap.launch(tmp_path)

    assert dap.sent == ["initialize", "launch", "configurationDone"]
    assert "killed" in no_subprocess


def test_the_program_is_launched_without_autoreload(tmp_path, no_subprocess):
    """The simulation runs the program ClickNick launched until it launches another."""
    (tmp_path / "run.py").write_text("x", encoding="utf-8")
    dap = _Scripted({})
    sent: dict = {}
    scripted = dap._send_and_wait

    def record(command, arguments=None, timeout=10.0):
        sent[command] = arguments
        return scripted(command, arguments, timeout)

    dap._send_and_wait = record
    dap.launch(tmp_path)

    assert sent["launch"]["program"] == str(tmp_path / "run.py")
    assert not sent["launch"].get("autoReload")


def test_requests_to_a_simulation_that_is_gone_are_unavailable_not_refused():
    dap = _Scripted({})
    with pytest.raises(DapUnavailableError, match="not running"):
        dap.force("X001", True)

    dap._proc = SimpleNamespace()
    dap.answers = {"pyrungForce": None}
    with pytest.raises(DapUnavailableError, match="no response"):
        dap.force("X001", True)

    dap.answers = {"pyrungForce": {"success": False, "message": "unknown tag: BAD1"}}
    with pytest.raises(DapRequestError, match="unknown tag") as refused:
        dap.force("BAD1", True)
    assert not isinstance(refused.value, DapUnavailableError)


def test_a_write_is_one_pyrung_reload_request_with_the_plan():
    plan = {"forces": {"Start": "StartPB"}, "links": {}, "declared": {"Prox": "ProxSensor"}}
    body = {"result": "Reloaded at scan 7 (3 tag(s))", "carried": [{"tag": "Start"}]}
    dap = _Scripted({"pyrungReload": {"success": True, "body": body}})
    dap._proc = SimpleNamespace()
    sent: list = []
    scripted = dap._send_and_wait

    def record(command, arguments=None, timeout=10.0):
        sent.append((command, arguments))
        return scripted(command, arguments, timeout)

    dap._send_and_wait = record
    assert dap.planned_reload(plan) == body
    assert sent == [("pyrungReload", plan)]


def test_a_refused_reload_is_not_asked_again():
    """pyrung pauses a running continue itself before it reloads."""
    refused = {"success": False, "message": "Timed out waiting for execution to pause"}
    dap = _Scripted({"pyrungReload": refused})
    dap._proc = SimpleNamespace()
    with pytest.raises(DapRequestError, match="Timed out waiting"):
        dap.planned_reload({})
    assert dap.sent == ["pyrungReload"]


def test_a_pyrung_without_the_planned_reload_is_named():
    unsupported = {"success": False, "message": "Unsupported command: pyrungReload"}
    dap = _Scripted({"pyrungReload": unsupported})
    dap._proc = SimpleNamespace()
    with pytest.raises(DapRequestError, match=r"pyrung 0\.16\.0 or later") as refused:
        dap.planned_reload({})
    assert not isinstance(refused.value, DapUnavailableError)
    assert dap.sent == ["pyrungReload"]
