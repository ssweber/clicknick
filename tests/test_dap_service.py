"""Check DapService: how it fails without a pyrung subprocess, and how it launches pyrung."""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from clicknick.services import dap_service
from clicknick.services.dap_service import DapRequestError, DapService, DapUnavailableError


class _Scripted(DapService):
    """Answers each request from *answers*. None means no answer arrived in time."""

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

    with pytest.raises(RuntimeError, match="stopped answering after it loaded the program"):
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
    with pytest.raises(DapUnavailableError, match="the simulation is not running"):
        dap.force("X001", True)

    dap._proc = SimpleNamespace()
    dap.answers = {"pyrungForce": None}
    with pytest.raises(DapUnavailableError, match="the simulation did not answer"):
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
    with pytest.raises(DapRequestError, match=r"pyrung is older than 0\.16\.0") as refused:
        dap.planned_reload({})
    assert not isinstance(refused.value, DapUnavailableError)
    assert dap.sent == ["pyrungReload"]


def _frame(dap: DapService, tags: dict[str, str]) -> None:
    dap._handle_event({"event": "pyrungScanFrame", "body": {"trace": {"tagTypes": tags}}})


def test_the_program_tags_follow_the_frames_and_a_reload_clears_them():
    dap = DapService()
    assert dap.program_tags is None, "unknown until the first frame"
    _frame(dap, {"Start": "bool", "Light": "bool"})
    assert dap.program_tags == {"Start", "Light"}

    dap._handle_response({"request_seq": 1, "command": "pyrungReload", "success": True})
    assert dap.program_tags is None, "the new program's tags come in the next frame"
    _frame(dap, {})
    assert dap.program_tags == frozenset(), "an empty program knows no tags"

    _frame(dap, {"Start": "bool"})
    dap._handle_response({"request_seq": 2, "command": "pyrungReload", "success": False})
    assert dap.program_tags == {"Start"}, "a refused reload keeps the old program"


# ----------------------------------------------------------------------
# A workspace behind a junction, on pyrung's own DAP server
# ----------------------------------------------------------------------

_PLC_TAGS = """from pyrung import Bool
from pyrung.click import ClickBlocks, TagMap

blocks = ClickBlocks()
start = Bool("Start")
mapping = TagMap({start: blocks.x[1]}, include_system=False)
"""

_PLC_MAIN = """from pyrung import Bool, Program, out, rung
from .tags import mapping, start
with Program(strict=False) as logic:
    with rung(start):
        out(Bool("Lamp"))
"""

_RUN = """from pyrung import PLC
from plc.main import logic
runner = PLC(logic)
"""


def _junction(link: Path, target: Path) -> None:
    """Make *link* a junction to the folder *target*, or skip the test."""
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError, OSError) as exc:
        pytest.skip(f"cannot make a junction here: {exc}")


def test_a_workspace_behind_a_junction_keeps_its_tagmap_and_a_write_loads_the_new_program(
    tmp_path,
):
    """The workspace path goes through a junction, as a temp folder behind one does.

    pyrung resolves the path of ``run.py``. It looks for the TagMap, and for the modules to load
    again at a write, only among modules whose file is under that resolved folder. So the
    folder, ``PYTHONPATH`` and ``run.py`` that ClickNick gives pyrung must be resolved too.
    """
    real = tmp_path / "real"
    plc = real / "src" / "plc"
    plc.mkdir(parents=True)
    (plc / "__init__.py").write_text("", encoding="utf-8")
    (plc / "tags.py").write_text(_PLC_TAGS, encoding="utf-8")
    (plc / "main.py").write_text(_PLC_MAIN, encoding="utf-8")
    (real / "run.py").write_text(_RUN, encoding="utf-8")
    link = tmp_path / "link"
    _junction(link, real)

    dap = DapService()
    try:
        dap.launch(link, session_name=f"clicknick-test-{uuid.uuid4().hex}", start_mode="stop")
        dap.force("X001", True)
        assert dap.list_forces() == {"Start": True}, "the TagMap in plc.tags puts Start on X001"
        dap.unforce("X001")

        (plc / "main.py").write_text(
            _PLC_MAIN.replace("rung(start)", 'rung(Bool("Other"))'), encoding="utf-8"
        )
        dap.planned_reload({"forces": {}, "links": {}, "declared": {}})
        dap.list_forces()  # pyrung sends the frame after the reload before it answers this
        assert dap.program_tags == {"Other", "Lamp"}, "the write loads the new plc.main"
    finally:
        dap.terminate()
