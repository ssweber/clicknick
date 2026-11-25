"""SimulationSession tests: lifecycle, the mode switch, forces, Modbus I/O and persistence.

Everything runs inline. A fake scheduler stands in for Tk, a fake DapService for the pyrung
subprocess and a fake ModbusService for the Modbus client.
"""

from __future__ import annotations

import ast
import re
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pyclickplc.addresses import (
    format_address_display,
    get_addr_key,
    normalize_address,
    parse_addr_key,
    parse_address,
)
from pyrung import PHYSICAL_KEYS

from clicknick.data.data_source import CsvDataSource
from clicknick.models.address_row import AddressRow
from clicknick.services.analysis_service import (
    AnalysisResult,
    AnalysisService,
    AnalysisStatus,
    UndecodedRung,
    simulation_stop_notice,
)
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
    """Runs zero-delay callbacks on demand. Keeps timed ones until a test fires them."""

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
    """Return a link's response fields as pyrungListLinks sends them.

    The dict holds the DAP field of every physical key. A field that *values* does not set is
    False for a flag and None otherwise.
    """
    return {
        key.dap_field: values.get(name, False if key.is_flag else None)
        for name, key in PHYSICAL_KEYS.items()
    }


class FakeDap:
    """Models a small part of pyrung's adapter.

    Like pyrung, it keys forces and bench links by tag name. It resolves an address with the
    names of the program it runs (*program_names*, read at launch and at each reload). A
    planned reload places each entry where its plan says. It carries every other entry over
    by name.

    Like pyrung, it knows only the tags that a rung names (*program_known*, read at launch and
    at each reload). It refuses a link on any other tag. A reload drops a link with such a tag,
    and a force on a named tag that the new program does not have, as ``gone``. A frame lists
    the known tags (``program_tags``), and a reload clears that list until the next frame. If
    *frame_after_reload* is set, that frame arrives before the reload's caller sends anything
    more.

    pyrung 0.18.0 refuses a link to an address that no rung names with ``unknown tag: X001``.
    From pyrung PR #119 (after 0.18.0), pyrung says ``no rung uses X001, so the program has no
    tag for it``. If the TagMap names the address ``Start``, the text is ``cannot link Start:
    no rung uses Start (X001), so the program has no tag for it``. After "no rung uses", it
    names the end that pyrung refused, which can be the enable. The fake writes this text if
    *no_rung_uses* is set. The fake looks the name up in its program's names (``names``).

    Like pyrung, it refuses a whole patch or ``set_mode`` request when it cannot resolve one
    address in the patches (*unresolved*). It records the patches of every such request in
    *patch_attempts*, and records only the requests that it accepts in *calls*.
    """

    def __init__(self, **callbacks) -> None:
        self.callbacks = callbacks
        self.program_names = dict  # () -> {address: tag}: what the workspace on disk names
        self.program_known = frozenset  # () -> the tags that a rung in the workspace names
        self.knows: frozenset[str] = frozenset()
        self.program_tags: frozenset[str] | None = None
        self.frame_after_reload = False
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
        self.no_rung_uses = False
        self.unresolved: set[str] = set()  # addresses that the fake cannot resolve
        self.refuse_patches: str | None = (
            None  # refuse every request with patches, with this reason
        )
        self.patch_attempts: list[dict] = []  # the patches of each patch or set_mode request
        self.reload_error: Exception | None = None
        self.plans: list[dict] = []  # each pyrungReload's plan
        self.reload_drops: dict[str, tuple[str, str]] = {}  # tag -> (reason, detail)

    def _tag(self, tag):
        """Return the name pyrung keys *tag* by. An address resolves to its name in the program."""
        address = normalize_address(tag) if isinstance(tag, str) else None
        return tag if address is None else self.names.get(address, address)

    def launch(self, project_dir, **kwargs):
        self.calls.append(("launch", project_dir, kwargs))
        self.names = dict(self.program_names())
        self.knows = frozenset(self.program_known())
        if self.launch_hook is not None:
            self.launch_hook()
        if self.launch_error is not None:
            raise self.launch_error

    def terminate(self):
        self.calls.append(("terminate",))

    def planned_reload(self, plan):
        """Handle pyrungReload. Move each entry that *plan* names to where the plan says.

        Every other entry keeps its name.
        """
        self.calls.append(("reload",))
        self.plans.append(plan)
        if self.reload_error is not None:
            raise self.reload_error  # a failed reload changes nothing
        carried: list[dict] = []
        knows = frozenset(self.program_known())

        def gone(*tags) -> tuple[str, str] | None:
            for tag in tags:
                if tag is not None and tag not in knows:
                    return ("gone", f"{tag} is not in the new program")
            return None

        def report(tag, kind, to, *, planned, enable=None, **fields):
            if kind == "force":
                # pyrung reaches an address by itself, so only a named tag can be gone.
                missing = None if to is None or normalize_address(to) else gone(to)
            elif kind in ("link", "cut"):
                missing = None if to is None else gone(to, enable)
            else:
                missing = None
            reason = self.reload_drops.get(tag) or missing
            if kind != "force":
                fields["enable"] = None if reason and kind != "declared" else enable
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
        self.knows = knows
        # pyrung lists no tags until the frame after the reload. With frame_after_reload set,
        # that frame has already come.
        self.program_tags = knows if self.frame_after_reload else None
        self.links_revision += 1
        return {"result": "Reloaded at scan 7 (3 tag(s))", "carried": carried}

    def _check_patches(self, patches) -> None:
        """Refuse the whole request, as pyrung does, if one address in *patches* is unresolved."""
        if patches and self.refuse_patches is not None:
            raise DapRequestError(self.refuse_patches)
        for address in patches or ():
            if address in self.unresolved:
                raise DapRequestError(f"Unknown tag '{address}'.")

    def set_mode(self, mode, patches=None, forces=None):
        self.patch_attempts.append(dict(patches or {}))
        self._check_patches(patches)
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
        if not patches:
            return  # DapService sends no request for an empty patch
        self.patch_attempts.append(dict(patches))
        self._check_patches(patches)
        self.calls.append(("patch", dict(patches)))

    # Bench links: a small model of pyrung's overlay, keyed by tag name.
    def link(self, feedback, enable, *, trigger=None, response=()):
        self.calls.append(("link", feedback, enable, {"trigger": trigger, "response": response}))
        if feedback in self.refuse_links:
            raise RuntimeError(f"cannot link {feedback}: {self.refuse_links[feedback]}")
        for tag in (feedback, enable):
            name = self._tag(tag)
            if name in self.knows:
                continue
            address = normalize_address(tag)
            if not self.no_rung_uses or address is None:
                raise RuntimeError(f"cannot link {feedback}: unknown tag: {name}")
            where = address if name == address else f"{name} ({address})"
            raise RuntimeError(
                f"cannot link {self._tag(feedback)}: no rung uses {where}, "
                "so the program has no tag for it"
            )
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
            # pyrung also refuses to restore a link that has no bench change.
            raise DapRequestError(f"{self._tag(feedback)} has no bench change")
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
        self.program_tags = self.knows
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
    """Put *svc* in the state that a successful build leaves, with *result* as its result.

    The DataView and the workspace use the same tag maps.
    """
    svc._result = result
    svc._project_tags = result.tag_to_addr_key
    svc._project_keys = result.addr_key_to_tag
    svc._project_is_current = True
    svc._status = AnalysisStatus.READY


#: The addresses that a rung of the default program names: every point of :data:`CPU`. A
#: rung that names an address with no nickname uses the address as the tag name.
CPU_POINTS = ("X001", "X002", "X003", "Y001", "DF1")


def _ready_analysis(
    project_dir: Path, *, generation: int = 1, used: tuple[str, ...] = CPU_POINTS
) -> AnalysisService:
    (project_dir / "run.py").write_text("x", encoding="utf-8")
    keys = {address: get_addr_key(*parse_address(address)) for address in used}
    svc = AnalysisService()
    _publish(
        svc,
        AnalysisResult(
            dataview=SimpleNamespace(tags=set(used)),
            program=MagicMock(),
            project_dir=project_dir,
            tag_to_addr_key=dict(keys),
            addr_key_to_tag={key: address for address, key in keys.items()},
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
            dap.program_known = self.workspace_known
            if self.next_launch_error is not None:
                dap.launch_error = self.next_launch_error
            dap.launch_hook = self.launch_hook
            dap.no_rung_uses = self.no_rung_uses
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
        # If set, each FakeDap words a refused link as pyrung does from PR #119.
        self.no_rung_uses = False
        self.saves = 0
        self.snapshot: dict = {}
        self.read_snapshot = lambda _path: dict(self.snapshot)
        # Where src/plc stops, as read_program_stops would read it, or the error it raises
        self.stops: tuple[UndecodedRung, ...] | Exception = ()
        self.stops_reads = 0

        def read_stops(_project_dir: Path) -> tuple[UndecodedRung, ...]:
            self.stops_reads += 1
            if isinstance(self.stops, Exception):
                raise self.stops
            return self.stops

        self.sim = SimulationSession(
            scheduler=self.scheduler,
            get_analysis=lambda: self.analysis,
            get_project_ini=lambda: project_ini,
            session_name="test",
            on_retry_analysis=lambda: self.retries.append("rebuild"),
            dap_factory=dap_factory,
            modbus_factory=modbus_factory,
            layout_reader=lambda _path, used: build_panel_layout([CPU], used),
            snapshot_reader=lambda path: self.read_snapshot(path),
            stops_reader=read_stops,
            run_background=lambda target, _name: target(),
            run_serial=lambda job: job(),
            send_command=send_command,
            app_data_root=tmp_path / "app",
            get_save_count=lambda: self.saves,
        )
        self.sim.add_listener(self.events.append)

    def workspace_names(self) -> dict[str, str]:
        """Return a map from address to tag name, as the workspace's files name them."""
        if self.analysis is None:
            return {}
        return {
            format_address_display(*parse_addr_key(key)): tag
            for key, tag in self.analysis.project_addr_key_to_tag.items()
        }

    def workspace_known(self) -> frozenset[str]:
        """Return the tags that a rung in the workspace's program names, under their current names."""
        result = None if self.analysis is None else self.analysis._result
        if result is None:
            return frozenset()
        to_key, to_tag = result.tag_to_addr_key, result.addr_key_to_tag
        return frozenset(
            to_tag.get(to_key[tag], tag) if tag in to_key else tag for tag in result.dataview.tags
        )

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
    """During a build the session waits, even though the old result looks fine.

    The folder is half-written, so the session does not read it.
    """
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
    serves = ready.analysis.mark_building()
    ready.open()
    ready.analysis.mark_failed("bad rung", "Traceback details", serves=serves)
    ready.scheduler.fire(ANALYSIS_POLL_MS)
    assert ready.sim.status is SimStatus.FAILED
    assert not ready.sim.is_waiting
    assert "Cannot start simulation: Could not build the workspace.\nbad rung\n" in (
        ready.messages()
    )


def test_guidance_mentions_the_generated_workspace(tmp_path):
    svc = AnalysisService()
    svc._project_dir = tmp_path
    svc.mark_failed("TypeError: boom")
    harness = Harness(tmp_path, svc)
    harness.open()
    assert "Open the generated workspace" in harness.messages()


def _record_unreadable(
    project_dir: Path, *rungs: int | None, unreadable: bool = True, marker: bool = False
) -> None:
    """Save the workspace's ``csv/`` as ``program_save`` does, with findings for *rungs*.

    Conf_Compare's CSV holds an empty stand-in rung at each numbered rung in *rungs*, or
    laddercodec's UNDECODED marker if *marker* is set. Each other rung is a coil.
    """
    from laddercodec import Coil, Rung, Undecoded, marker_rung, write_csv

    from clicknick.ladder.program import (
        STAND_IN_COMMENT,
        LegacyEncoding,
        empty_rung,
        write_legacy_encodings,
    )

    detail = "ClickNick cannot read this Compare."
    csv_dir = project_dir / "csv"
    (csv_dir / "subroutines").mkdir(parents=True, exist_ok=True)
    found = [
        LegacyEncoding(
            "subroutines/Conf_Compare.csv", "Conf_Compare", rung, "Compare", "", detail, unreadable
        )
        for rung in rungs
    ]
    write_legacy_encodings(csv_dir, found)
    numbered = {rung for rung in rungs if rung is not None}
    if not numbered:
        return
    saved = []
    for number in range(1, max(numbered) + 2):
        if number not in numbered:
            saved.append(Rung([["-"] * 31], [Coil(f"C{number}")], None))
        elif marker:
            saved.append(marker_rung(Undecoded(detail, rung=number - 1, row=0)))
        else:
            saved.append(empty_rung(STAND_IN_COMMENT))
    write_csv(csv_dir / "subroutines" / "Conf_Compare.csv", saved)


def _stop_at(harness: Harness, *rungs: UndecodedRung) -> None:
    """Make the workspace's src/plc hold pyrung's undecoded() marker in place of *rungs*."""
    harness.stops = rungs


def test_program_with_a_rung_clicknick_cannot_read_does_not_run(ready):
    _record_unreadable(ready.analysis.project_dir, 4)
    ready.open()

    assert ready.daps == []
    assert ready.sim.status is SimStatus.FAILED
    message = ready.messages("error")
    assert "ClickNick cannot copy this rung from CLICK as it is" in message
    assert "Conf_Compare rung 4, Compare: ClickNick cannot read this Compare." in message
    assert message.endswith(
        "\nPaste it again from your own copy of the program, or fix it in CLICK."
    )
    assert "CsvWriteError" not in message


def test_several_unreadable_rungs_are_named_together(ready):
    _record_unreadable(ready.analysis.project_dir, 4, 5)
    ready.open()

    message = ready.messages("error")
    assert "Conf_Compare rung 4" in message
    assert "Conf_Compare rung 5" in message
    assert message.endswith(
        "\nPaste them again from your own copy of the program, or fix them in CLICK."
    )


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


COMPARE_STOP = UndecodedRung("Conf_Compare", 4)


def test_a_program_with_a_marker_runs_up_to_it_with_a_notice(ready):
    _record_unreadable(ready.analysis.project_dir, 4, marker=True)
    _stop_at(ready, COMPARE_STOP)

    ready.open()

    assert ready.sim.status is SimStatus.READY
    notice = simulation_stop_notice([COMPARE_STOP])
    assert notice.startswith(
        "ClickNick could not read rung 4 of Conf_Compare. The simulation does not run the "
        "rungs after it in that program. The PLC runs them. If only those rungs use an X or "
        "Y point, the panel can leave it out."
    )
    assert ready.sim.stop_notice == notice
    assert notice in ready.messages("progress")
    assert ready.messages("error") == ""


def test_the_stop_notice_names_every_rung_where_the_program_stops():
    notice = simulation_stop_notice([COMPARE_STOP, UndecodedRung("Main Program", 12)])

    assert notice.startswith(
        "ClickNick could not read rung 4 of Conf_Compare and rung 12 of Main Program. "
        "The simulation does not run the rungs after each one in its program."
    )
    assert notice.endswith("paste those rungs again in CLICK and save.")
    assert simulation_stop_notice([]) == ""


def test_the_stop_notice_ends_with_the_simulation(ready):
    _stop_at(ready, COMPARE_STOP)
    ready.open()
    assert ready.sim.stop_notice

    ready.sim.turn_off()
    ready.scheduler.run_ready()

    assert ready.sim.stop_notice is None


def test_a_write_updates_the_stop_notice(ready):
    _running_with_settings(ready)
    assert ready.sim.stop_notice is None

    _rebuild(ready)
    _record_unreadable(ready.analysis.project_dir, 4, marker=True)
    _stop_at(ready, COMPARE_STOP)
    ready.events.clear()
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.sim.stop_notice == simulation_stop_notice([COMPARE_STOP])
    assert ready.sim.stop_notice in ready.messages("progress")
    assert any(event.kind == "desired" for event in ready.events)

    _rebuild(ready)
    _stop_at(ready)  # The user wrote the rung's logic in src/plc
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.sim.stop_notice is None


def test_restart_updates_the_stop_notice(ready):
    _record_unreadable(ready.analysis.project_dir, 4, marker=True)
    _stop_at(ready, COMPARE_STOP)
    ready.open()
    assert ready.sim.stop_notice

    _stop_at(ready)  # The user wrote the rung's logic in src/plc
    ready.sim.restart()
    ready.scheduler.run_ready()

    assert len(ready.daps) == 2 and ready.sim.is_ready
    assert ready.sim.stop_notice is None


def test_a_failed_read_of_a_program_without_markers_shows_only_the_error(ready):
    ready.stops = ValueError("No module named 'plc'")

    ready.open()

    assert ready.sim.is_ready
    assert ready.sim.stop_notice is None
    assert ready.messages("error") == (
        "ClickNick could not read src/plc to find where the program stops: No module named 'plc'"
    )


def test_a_launch_whose_read_fails_names_the_markers_of_the_build(ready):
    ready.analysis._result = replace(ready.analysis._result, undecoded=(COMPARE_STOP,))
    _stop_at(ready, COMPARE_STOP)
    ready.stops = ValueError("reading src/plc took longer than 60 seconds.")

    ready.open()

    assert ready.sim.is_ready
    assert ready.sim.stop_notice == simulation_stop_notice([COMPARE_STOP])
    assert ready.messages("error") == (
        "ClickNick could not read src/plc to find where the program stops: reading src/plc "
        "took longer than 60 seconds.\nThe notice about the rungs that the simulation does "
        "not run may be out of date."
    )


def test_a_write_whose_read_fails_keeps_the_stop_notice(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    _record_unreadable(ready.analysis.project_dir, 4, marker=True)
    _stop_at(ready, COMPARE_STOP)
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    assert ready.sim.stop_notice == simulation_stop_notice([COMPARE_STOP])

    # The build of CLICK's save has no marker, so only the stops of the program can stand in
    _rebuild(ready)
    ready.stops = ValueError("reading src/plc took longer than 60 seconds.")
    ready.events.clear()
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.sim.stop_notice == simulation_stop_notice([COMPARE_STOP])
    assert ready.messages("error").startswith(
        "ClickNick could not read src/plc to find where the program stops: reading src/plc "
        "took longer than 60 seconds.\n"
    )

    # The failed read leaves nothing to compare with, so the next write reads again
    _rebuild(ready, same_program=True)
    ready.stops = ()
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.sim.stop_notice is None


def test_a_write_reads_src_plc_again_only_if_it_changed(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    _record_unreadable(ready.analysis.project_dir, 4, marker=True)
    _stop_at(ready, COMPARE_STOP)
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    reads = ready.stops_reads

    # A Reload from CLICK writes the same source
    _rebuild(ready, saved=False, same_program=True)
    ready.stops = ValueError("src/plc was read again")
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.stops_reads == reads
    assert ready.sim.stop_notice == simulation_stop_notice([COMPARE_STOP])
    assert ready.messages("error") == ""

    _rebuild(ready)
    ready.stops = ()
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.stops_reads == reads + 1
    assert ready.sim.stop_notice is None


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
    """A launch that fails because a rebuild started *and finished* during it is not reported.

    The session waits to launch again. This is the "No module named 'subroutines'" case. The
    launch read a half-written project. The rebuild has completed by the time the failure
    arrives, so the status alone looks healthy.
    """
    ready.analysis._generation = 5

    def rebuild_under_the_launch() -> None:
        ready.analysis._generation = 6  # a rebuild ran under the launch...
        ready.analysis._status = AnalysisStatus.READY  # ...and already finished
        raise RuntimeError("pyrung could not load the program: No module named 'subroutines'")

    ready.launch_hook = rebuild_under_the_launch
    ready.open()
    assert ready.sim.is_waiting, "raced launch should wait and relaunch"
    assert ready.sim.status is SimStatus.WAITING
    assert "failed to start" not in ready.messages()


def test_launch_failure_without_rebuild_is_reported(ready):
    ready.next_launch_error = RuntimeError(
        "pyrung could not load the program: something genuinely broken"
    )
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
    assert "the workspace was still not built after" in ready.messages()
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
    assert "The PLC data file changed. Restarting the simulation from it..." in ready.messages()


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

    # Forces persist through STOP -> RUN (keepForcesOnRun). The transition drops inputs
    # patched in STOP, so the session patches them again.
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
        "Could not restore the bench link on DF1: the old setting "
        "profile=approach:toward=180 has no upgrade. ClickNick removed it from the simulator "
        "settings."
    )
    assert ready.sim.restored_links == 1


def test_restore_drops_analog_values_the_hardware_no_longer_has(ready, tmp_path):
    save_state(
        tmp_path / "app" / "Line1.toml",
        SimulatorState(
            switches={"X001": True, "X009": True},
            analog={"DF1": 2.0, "DF5": 3.0},
            modules=("cpu:OLD",),
        ),
    )
    ready.sim.set_state_location("Line1", None)
    ready.open()
    assert ready.sim.analog_value("DF1") == 2.0
    assert ready.sim.analog_value("DF5") is None
    # No module and no rung has X009, and its switch stays.
    assert ready.sim.switch_on("X001")
    assert ready.sim.switch_on("X009")
    assert ready.sim.notice == (
        "The hardware changed since the last session. ClickNick removed the settings for DF5, "
        "because no installed analog input has those addresses."
    )


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
    ready.analysis._result.dataview.tags.update({"Aux", "Lamp", "_IO1_Module_Error"})
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
    assert (
        ready.sim.notice
        == "Loaded PLC data from dump.csv. The switches and analog inputs now have its values."
    )
    assert ready.dap.calls[0][2]["snapshot_path"] == data


def test_a_text_comma_in_plc_data_reads_back_as_a_comma(tmp_path):
    """Read a PLC data file whose TXT2 holds a comma, as both readers of the Simulator do.

    CLICK writes the comma without quotes, so the TXT1 row has 11 cells. The session reads the
    file for the switches and analog inputs. pyrung reads it again at launch for every value.
    """
    from pyclickplc.banks import DataType
    from pyrung.click import TagMap

    from clicknick.services.analysis_service import _write_nicknames_csv
    from clicknick.simulation_session import _default_snapshot_reader

    lines = [
        "<DS=START>",
        "Address,1,2,3,4,5,6,7,8,9,10,",
        "DS1,7,0,0,0,0,0,0,0,0,0,",
        "</DS=END>",
        "",
        "<TXT=START>",
        "Address,1,2,3,4,5,6,7,8,9,10,",
        "TXT1,A,,,B,C,D,E,F,G,H,I,",
        "</TXT=END>",
        "",
    ]
    data = tmp_path / "data.csv"
    data.write_bytes("\r\n".join(lines).encode("ascii"))
    named = [AddressRow("TXT", n, nickname=f"Msg{n}", data_type=DataType.TXT) for n in (1, 2, 3)]
    rows = {row.addr_key: row for row in named}
    mapping = TagMap.from_nickname_file(_write_nicknames_csv(tmp_path, rows))

    snapshot = _default_snapshot_reader(data)
    state = mapping.load_snapshot(data)

    assert [snapshot[f"TXT{n}"] for n in range(1, 5)] == ["A", ",", "B", "C"]
    assert snapshot["DS1"] == 7
    assert {name: state.tags[name] for name in ("Msg1", "Msg2", "Msg3")} == {
        "Msg1": "A",
        "Msg2": ",",
        "Msg3": "B",
    }


def _plc_data_with_unknown_text(tmp_path: Path) -> Path:
    """Write a PLC data file in which pyclickplc cannot tell what TXT13 to TXT20 hold.

    The TXT11 row holds "Hi," and then empty cells. CLICK writes the comma without quotes, so the
    comma may be in any of TXT13 to TXT20.
    """
    return _write_txt_rows(tmp_path / "data.csv", "TXT1,A,B,C,,,,,,,,", "TXT11,H,i,,,,,,,,,,")


def _write_txt_rows(data: Path, *rows: str) -> Path:
    lines = ["<TXT=START>", "Address,1,2,3,4,5,6,7,8,9,10,", *rows, "</TXT=END>", ""]
    data.write_bytes("\r\n".join(lines).encode("ascii"))
    return data


def _save_without_the_comma(data: Path) -> None:
    """Write the file again without the comma, as CLICK would after the user fixed the Text."""
    import os

    before = data.stat().st_mtime
    _write_txt_rows(data, "TXT1,A,B,C,,,,,,,,", "TXT11,H,i,x,y,z,a,b,c,d,e,")
    os.utime(data, (before + 5, before + 5))


def _assert_one_warning_about(harness: Harness, data: Path) -> None:
    """Check that the messages name the skipped addresses once, in ClickNick's words."""
    messages = harness.messages()
    assert messages.count("TXT13-TXT20") == 1, messages
    assert f"ClickNick cannot tell what TXT13-TXT20 hold in {data.name}." in messages
    assert "The simulation started with them at their power-on values." in messages
    assert "replace the comma in their Text values in CLICK" in messages
    assert "values attribute" not in messages
    assert "read_plc_data" not in messages


def test_a_plc_data_file_with_unknown_text_starts_the_simulation_and_warns_once(ready, tmp_path):
    from clicknick.simulation_session import _default_snapshot_reader

    ready.read_snapshot = _default_snapshot_reader
    data = _plc_data_with_unknown_text(tmp_path)
    ready.sim.set_plc_data_path(data)  # The simulation is off, so nothing starts yet.

    ready.open()

    assert len(ready.daps) == 1
    assert ready.dap.calls[0][2]["snapshot_path"] == data
    assert ready.sim.status is not SimStatus.FAILED
    assert ready.sim.notice is not None and "TXT13-TXT20" in ready.sim.notice
    assert "TXT13-TXT20" in ready.messages("error")
    _assert_one_warning_about(ready, data)


def test_a_plc_data_file_with_unknown_text_sets_the_switches_from_the_rest(ready, tmp_path):
    from pyclickplc import PlcDataReadError

    def unknown_text(_path):
        raise PlcDataReadError({"X001": True, "X002": False}, ("TXT13", "TXT14"))

    ready.read_snapshot = unknown_text
    data = tmp_path / "data.csv"
    data.write_text("x", encoding="utf-8")
    ready.sim.set_plc_data_path(data)

    ready.open()

    assert ready.sim.switch_on("X001")
    assert not ready.sim.switch_on("X002")
    assert ready.sim.notice is not None
    assert ready.sim.notice.startswith("Loaded PLC data from data.csv.")
    assert "TXT13-TXT14" in ready.sim.notice


def test_a_plc_data_file_with_unknown_text_restarts_the_running_simulation(ready, tmp_path):
    from clicknick.simulation_session import _default_snapshot_reader

    ready.open()
    ready.read_snapshot = _default_snapshot_reader
    data = _plc_data_with_unknown_text(tmp_path)

    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()

    assert len(ready.daps) == 2, "the simulation restarts from the file"
    assert ready.dap.calls[0][2]["snapshot_path"] == data
    assert ready.sim.status is not SimStatus.FAILED
    _assert_one_warning_about(ready, data)


def test_saving_the_fixed_file_restarts_without_another_warning(ready, tmp_path):
    from clicknick.simulation_session import WATCH_MS, _default_snapshot_reader

    ready.open()
    ready.read_snapshot = _default_snapshot_reader
    data = _plc_data_with_unknown_text(tmp_path)
    ready.sim.set_plc_data_path(data)
    ready.scheduler.run_ready()
    assert len(ready.daps) == 2

    _save_without_the_comma(data)
    ready.scheduler.fire(WATCH_MS)
    ready.scheduler.run_ready()

    assert len(ready.daps) == 3
    assert ready.dap.calls[0][2]["snapshot_path"] == data
    assert ready.sim.notice is not None and "cannot tell" not in ready.sim.notice
    _assert_one_warning_about(ready, data)

    ready.sim.restart()
    ready.scheduler.run_ready()
    assert len(ready.daps) == 4
    assert ready.messages().count("TXT13-TXT20") == 1, "a restart does not read the file again"


def test_the_warning_lists_runs_of_text_addresses_as_ranges():
    from clicknick.simulation_session import PLC_DATA_LISTED, _address_ranges

    assert _address_ranges(["TXT2", "TXT3", "TXT5", "TXT13", "TXT14"]) == (
        "TXT2-TXT3, TXT5, TXT13-TXT14"
    )
    many = [f"TXT{n}" for n in range(1, 2 * (PLC_DATA_LISTED + 2), 2)]
    assert _address_ranges(many).endswith(", TXT19 and 2 more")


def test_the_plc_data_warning_waits_for_a_launch_that_succeeds(ready, tmp_path):
    from clicknick.simulation_session import _default_snapshot_reader

    ready.read_snapshot = _default_snapshot_reader
    data = _plc_data_with_unknown_text(tmp_path)
    ready.sim.set_plc_data_path(data)
    ready.next_launch_error = RuntimeError("pyrung could not load the program: boom")

    ready.open()

    assert ready.sim.status is SimStatus.FAILED
    assert "TXT13-TXT20" not in ready.messages(), "no simulation started from the file"

    ready.next_launch_error = None
    ready.sim.retry()
    ready.scheduler.run_ready()

    assert ready.sim.is_ready
    _assert_one_warning_about(ready, data)


def test_a_plc_data_file_that_cannot_be_read_still_reaches_the_launch(ready, tmp_path):
    """ClickNick says that it cannot read the file and launches. pyrung reports its own failure."""

    def unreadable(_path):
        raise ValueError("TXT1 row has 9 cells, not 10.")

    ready.read_snapshot = unreadable
    data = tmp_path / "data.csv"
    data.write_text("x", encoding="utf-8")
    ready.sim.set_plc_data_path(data)

    ready.open()

    assert ready.dap.calls[0][2]["snapshot_path"] == data
    assert "Could not read PLC data" in ready.messages("error")


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
    ready.analysis._result.dataview.tags.add(tag)  # a rung names it


def _echoes(ready) -> list[str]:
    return [e.text for e in ready.events if e.kind == "echo"]


def test_to_tag_uses_the_running_programs_names(ready):
    _name(ready, "X001", "Start_PB")
    assert ready.sim.to_tag("X001") == "Start_PB"
    assert ready.sim.to_tag("x2") == "X002", "unnamed points go by their address"


def test_panel_actions_echo_as_console_commands(ready):
    _name(ready, "X001", "Start_PB")
    _name(ready, "Y001", "Motor_Run")
    ready.open()
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


def _write_source(harness: Harness, *, same_program: bool = False) -> None:
    """Write the workspace's ``src/plc`` as a build does. Add a rung unless *same_program*."""
    main = harness.analysis.project_dir / "src" / "plc" / "main.py"
    main.parent.mkdir(parents=True, exist_ok=True)
    held = main.read_text(encoding="utf-8") if main.is_file() else ""
    rungs = held.count("rung")
    main.write_text(held if same_program else f"{held}rung {rungs + 1}\n", encoding="utf-8")


def _rebuild(
    harness: Harness,
    renames: dict[str, str] | None = None,
    *,
    saved: bool = True,
    same_program: bool = False,
    compared: bool = True,
    uses: tuple[str, ...] = (),
    drops: tuple[str, ...] = (),
) -> None:
    """Rebuild the analysis as a CLICK save does. *renames* maps addresses to new tag names.

    If *saved* is false, the rebuild is not a save. It stands for a Reload from CLICK or a
    Sync. The build writes ``src/plc`` again and adds a rung to it, unless *same_program* is
    set. Unless *compared* is false, the session then compares that source with the program
    it runs, as its watch tick or a frame does.

    The rungs of the new program name each address that the old program's rungs named, under
    the new tag names. They also name each address in *renames* and in *uses*, and none in
    *drops*.
    """
    if saved:
        harness.saves += 1
    from pyclickplc.addresses import get_addr_key, parse_address

    old = harness.analysis._result
    _write_source(harness, same_program=same_program)
    key_to_tag = dict(old.addr_key_to_tag)
    for address, tag in (renames or {}).items():
        key_to_tag[get_addr_key(*parse_address(address))] = tag
    uses = (*uses, *(renames or {}))
    for address in uses:
        key_to_tag.setdefault(get_addr_key(*parse_address(address)), address)
    old_keys = old.tag_to_addr_key
    tags = {
        key_to_tag.get(old_keys[tag], tag) if tag in old_keys else tag for tag in old.dataview.tags
    }
    tags |= {key_to_tag[get_addr_key(*parse_address(address))] for address in uses}
    tags -= {key_to_tag.get(get_addr_key(*parse_address(address))) for address in drops}
    _publish(
        harness.analysis,
        AnalysisResult(
            dataview=SimpleNamespace(tags=tags),
            program=old.program,
            project_dir=old.project_dir,
            tag_to_addr_key={tag: key for key, tag in key_to_tag.items()},
            addr_key_to_tag=key_to_tag,
        ),
    )
    harness.analysis._generation += 1
    if compared:
        harness.sim._check_program()


def _bench_by_name(dap: FakeDap, names: dict[str, str]) -> None:
    """Rename the fake's bench rows by tag name, because pyrung lists links by tag name."""
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

    # The user renamed in ClickNick, then synced and saved in CLICK. The analysis has the
    # new names. The simulation still runs the program it was launched with.
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
    assert (
        "Could not restore the force on Start: it is not a CLICK address. ClickNick removed it "
        "from the simulator settings."
    ) in errors
    assert "Could not restore the bench link on Prox: it is not a CLICK address." in errors


def _running_with_settings(ready) -> None:
    """Put the session in RUN with a switch on, a force and a bench link, all acknowledged."""
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

    _write_source(ready)
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
    # The write is one planned reload, and pyrung pauses before it reloads. The plan keeps the
    # force and the link under the names they have.
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
    """Put Y001, named Motor, in RUN with a force on it and a bench link that it enables."""
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
    """X001, named Start, is renamed StartPB, and X005 is given the name Start.

    Frames read `Start` as X001 until the rename is written, and as X005 after it.
    """
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
    """A FakeDap that fails as DapService does once it is terminated.

    After terminate(), its force, link, unlink, set_links and list_links requests raise.
    """

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
    """Hold the jobs of the ordered action worker until the test runs them.

    Return the list that holds the jobs. Each DAP that the session creates after this call is
    a _GoneAfterTerminate.
    """
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
    assert f"Writing the program releases {notice}" in change.text, "listed before the user writes"
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


def test_a_write_is_refused_while_a_stand_in_rung_is_in_the_workspace(ready):
    _running_with_settings(ready)
    _rebuild(ready)
    _record_unreadable(ready.analysis.project_dir, 4)
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert ready.dap.calls[mark:] == [], "the old program runs on"
    notice = ready.sim.notice or ""
    assert notice.startswith("Cannot write the program: ClickNick cannot copy this rung")
    assert "Conf_Compare rung 4" in notice
    assert notice.endswith("The simulation still runs the previous program.")
    assert not ready.sim.writing


def _save_that_does_not_convert(ready, monkeypatch, tmp_path) -> None:
    """Simulate a CLICK save after which the real build() cannot convert the program."""
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
    assert "Cannot restart the simulation: ClickNick cannot copy" in ready.messages("error")

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

    assert "The workspace was rebuilt while the program was written" in ready.messages("error")
    assert ready.sim.to_tag("X001") == "Start"
    change = ready.sim.program_change
    assert change is not None and change.cause == "save"
    assert change.actions == ("run_time_edit", "stop_and_write")


def test_a_build_of_the_program_running_is_not_offered(ready):
    """A build that leaves the program as it was is not offered.

    A Sync, a Reload from CLICK or a save counted twice can make such a build.
    """
    from clicknick.simulation_session import WATCH_MS

    _name(ready, "X001", "Start")
    _running_with_settings(ready)
    _rebuild(ready, {"X001": "StartPB"})
    assert ready.sim.program_change.cause == "save"
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    assert ready.sim.program_change is None
    ready.events.clear()

    _rebuild(ready, same_program=True)
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None, "the simulation runs this program already"
    _rebuild(ready, saved=False, same_program=True)
    ready.dap.frame(mode="run", running=True)  # a frame compares before the views read it
    ready.scheduler.run_ready()
    assert ready.sim.program_change is None
    assert "desired" not in [e.kind for e in ready.events], "nothing was offered"

    _rebuild(ready)  # a save with another rung
    ready.scheduler.fire(WATCH_MS)
    change = ready.sim.program_change
    assert change is not None and change.cause == "save"
    assert change.actions == ("run_time_edit", "stop_and_write")


def test_a_build_is_not_offered_before_it_is_compared(ready):
    """In STOP no frames arrive, so the watch tick compares the build before any offer."""
    from clicknick.simulation_session import WATCH_MS

    _write_source(ready)
    ready.open()
    ready.events.clear()

    _rebuild(ready, saved=False, same_program=True, compared=False)  # a Sync that changes nothing
    assert ready.sim.program_change is None, "what a view drawn now reads"
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None
    assert "desired" not in [e.kind for e in ready.events]

    _rebuild(ready, compared=False)  # a save with another rung
    assert ready.sim.program_change is None, "not compared yet"
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save"
    assert [e.kind for e in ready.events].count("desired") == 1


def test_an_offer_goes_when_a_later_build_holds_the_program_running(ready):
    """The offer is withdrawn when CLICK saves another rung and then the program as it was.

    The second save is what an undo and a save in CLICK produce.
    """
    from clicknick.simulation_session import WATCH_MS

    _write_source(ready)
    ready.open()
    main = ready.analysis.project_dir / "src" / "plc" / "main.py"
    before = main.read_text(encoding="utf-8")
    _rebuild(ready)
    assert ready.sim.program_change.cause == "save"
    ready.events.clear()

    main.write_text(before, encoding="utf-8")
    _rebuild(ready, same_program=True, compared=False)
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change is None
    assert [e.kind for e in ready.events].count("desired") == 1, "the offer's banner goes"


def test_a_build_with_new_names_only_is_offered(ready):
    from clicknick.simulation_session import WATCH_MS

    _name(ready, "X001", "Start")
    ready.open()
    _rebuild(ready, {"X001": "StartPB"}, same_program=True)
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save"


def test_a_build_with_another_run_py_is_offered(ready):
    from clicknick.simulation_session import WATCH_MS

    _write_source(ready)
    ready.open()
    (ready.analysis.project_dir / "run.py").write_text("edited", encoding="utf-8")
    _rebuild(ready, same_program=True)
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save", "pyrung runs run.py too"


def test_a_build_is_offered_when_the_program_running_could_not_be_read(ready, monkeypatch):
    from clicknick.services import project_workspace
    from clicknick.simulation_session import WATCH_MS

    _write_source(ready)
    real = project_workspace._source_fingerprint

    def unreadable(_source):
        raise PermissionError("being written")

    monkeypatch.setattr(project_workspace, "_source_fingerprint", unreadable)
    ready.open()  # the launch could not read src/plc
    monkeypatch.setattr(project_workspace, "_source_fingerprint", real)

    _rebuild(ready, same_program=True)
    ready.scheduler.fire(WATCH_MS)
    assert ready.sim.program_change.cause == "save", "unknown is no proof of the same program"


def test_a_build_after_a_write_that_raced_a_build_is_offered(ready):
    """After a build that finished during a write, a build of the earlier program is offered.

    A CLICK save arrives while the write is under way, so the session cannot tell which
    program pyrung read. A later build of the program as it was before the write is offered.
    """
    from clicknick.simulation_session import WATCH_MS

    _name(ready, "X001", "Start")
    _write_source(ready)
    _running_with_settings(ready)
    main = ready.analysis.project_dir / "src" / "plc" / "main.py"
    before = main.read_text(encoding="utf-8")
    _rebuild(ready, {"X001": "StartPB"})

    ready.sim.run_time_edit()
    _rebuild(ready)  # CLICK saved again before pyrung's answer was handled
    ready.scheduler.run_ready()
    assert "The workspace was rebuilt while the program was written" in ready.messages("error")

    main.write_text(before, encoding="utf-8")  # a save of the program before the write
    _rebuild(ready, {"X001": "Start"}, same_program=True)
    ready.scheduler.fire(WATCH_MS)
    change = ready.sim.program_change
    assert change is not None and change.cause == "save"


def test_a_build_running_when_the_write_is_answered_can_bring_another_program(ready):
    from clicknick.simulation_session import WATCH_MS

    _name(ready, "X001", "Start")
    _running_with_settings(ready)
    _rebuild(ready, {"X001": "StartPB"})

    ready.sim.run_time_edit()
    ready.saves += 1
    ready.analysis._status = AnalysisStatus.BUILDING
    ready.scheduler.run_ready()
    _rebuild(ready, saved=False)  # it built another rung
    ready.scheduler.fire(WATCH_MS)

    assert "The workspace was rebuilt while the program was written" in ready.messages("error")
    assert ready.sim.to_tag("X001") == "Start"
    change = ready.sim.program_change
    assert change is not None and change.cause == "save"
    assert change.actions == ("run_time_edit", "stop_and_write")


def test_writes_that_cannot_start_say_why(ready):
    ready.sim.reload()
    assert (
        "Cannot write the program, because the simulation is not running. Start the simulation "
        "first."
    ) in ready.messages("error")

    jobs = _queued(ready)
    ready.open()
    _run_jobs(ready, jobs)
    _rebuild(ready)
    ready.sim.write_program()
    ready.sim.reload()
    assert (
        "The program is already being written to the simulation. Wait for that write to finish."
    ) in ready.messages("error")
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
    # pyrung's failed reload changed nothing, so there is nothing to send again.
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
    """An `unforce Y001` and a `restore X002` typed in the Console stay in effect.

    The user types them while a CLICK save builds. Neither the write nor a restart forces or
    links again.
    """
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

    serves = ready.analysis.mark_building()
    # `unforce Y001`, `force C1 true` and `unlink X002` in the Console
    ready.dap.bench.pop("X002")
    ready.dap.links_revision += 1
    ready.dap.frame(forces={"C1": True})
    ready.scheduler.run_ready()
    assert ready.sim.forces == {"C1": True}
    assert ready.sim.bench_links == {}

    ready.analysis.mark_failed("no saved ladder files", serves=serves)  # before build() ran
    ready.scheduler.fire(WATCH_MS)
    assert len(ready.daps) == 1
    assert ready.sim.forces == {"C1": True}


def _plc_source(ready) -> Path:
    main = ready.analysis.project_dir / "src" / "plc" / "main.py"
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text("rung = 1\n", encoding="utf-8")
    return main


_saves = iter(range(1, 1_000_000))


def _edit(path: Path, text: str) -> None:
    """Write *text* as an editor save would, and move the file's modification time forward.

    Each call moves it further forward than the call before. Two writes can share one clock
    tick on Windows, and two saves with the same timestamp would read as one.
    """
    import os

    path.write_text(text, encoding="utf-8")
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + next(_saves) * 2_000_000_000))


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
    _edit(main, "rung = 3\n")  # the build writes the new source
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
    assert "The simulation did not answer for the force on Y001." in ready.messages("error")
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


def test_switches_on_unassigned_inputs_stay_through_the_first_build(ready, tmp_path):
    from pyclickplc.addresses import get_addr_key

    ready.analysis._result.tag_to_addr_key["Aux"] = get_addr_key("X", 201)
    ready.analysis._result.dataview.tags.add("Aux")
    save_state(
        tmp_path / "app" / "Line1.toml",
        SimulatorState(switches={"X001": True, "X201": True}, modules=("cpu:C0-02DD1-D",)),
    )
    result = ready.analysis._result
    ready.analysis._result = None  # the app has just connected, and its first build runs
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
# Values through a write, on pyrung's own DAP server
# ----------------------------------------------------------------------

_VALUES_PROGRAM = """\
import warnings
warnings.simplefilter("ignore")
from pyrung import Bool, Int, PLC, Program, rung, calc, out
start = Bool("Start")
light = Bool("Light")
ret = Int("Ret", retentive=True)
nonret = Int("NonRet", retentive=False)
with Program(strict=False) as prog:
    with rung(start):
        out(light)
    with rung():
        calc(ret + 1, ret)
    with rung():
        calc(nonret + 1, nonret)
runner = PLC(prog, dt=0.010)
"""


@pytest.fixture()
def pyrung_dap():
    """Return a DapService class that runs ``python -m pyrung.dap`` in a subprocess, as the app does.

    pyrung scans only when the test calls ``scan()``. Teardown stops every process that the
    class started.
    """
    from clicknick.services.dap_service import DapService

    started: list[DapService] = []

    class SubprocessDap(DapService):
        def __init__(self, *, on_frame=None, **_callbacks):
            # The reader thread runs no session callback, because FakeScheduler is not
            # thread-safe. frame() runs the session's on_frame on the test's thread.
            super().__init__()
            self._session_frame = on_frame
            self._test_session = f"clicknick-test-{uuid.uuid4().hex}"
            started.append(self)

        def launch(self, project_dir, *, snapshot_path=None, **_kwargs):
            # No Modbus server. Each test has a session name of its own.
            super().launch(
                project_dir,
                session_name=self._test_session,
                snapshot_path=snapshot_path,
                start_mode="stop",
                keep_forces_on_run=True,
            )

        def _cache_execution_state(self, body, trace):
            running = self._running
            super()._cache_execution_state(body, trace)
            # pyrung never scans on its own here, and its frames say so. The test scans for it.
            self._running = running

        # In RUN, pyrung only records that it runs. The test scans.
        def continue_(self):
            self._running = True

        def pause(self):
            self._running = False

        def scan(self, count: int = 1) -> None:
            for _ in range(count):
                self._request("pyrungStepScan")

        def frame(self) -> None:
            # pyrung answers a request only after it sends the frames that earlier requests
            # queued. So once list_forces() returns, the cached mode and forces are current.
            self.list_forces()
            if self._session_frame is not None:
                self._session_frame()

        def tag(self, name):
            """Return the value of the tag *name*, as the console's ``get`` reads it."""
            from pyrung.live import send_command

            ok, text = send_command(self._test_session, f"get {name}")
            assert ok, text
            shown, _, value = text.partition(" = ")
            assert shown == name, text
            return ast.literal_eval(value)

        def bench_links(self) -> dict[str, str]:
            """Return the enable of each bench link, keyed by its feedback."""
            return {
                link["feedback"]: link["enable"]
                for link in self.list_links()["links"]
                if link["source"] == "bench"
            }

    yield SubprocessDap
    for dap in started:
        dap.terminate()


@pytest.fixture()
def on_pyrung(tmp_path, pyrung_dap):
    """Return the harness, with the simulation on pyrung's DAP server running a counting program."""
    dap_class = pyrung_dap
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
    dap.frame()  # the baseline that later frames are compared with
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


_TEXT_TAGS_MODULE = """from pyrung import Char
from pyrung.click import ClickBlocks, TagMap

blocks = ClickBlocks()
first = Char("First")
second = Char("Second")
skipped = Char("Skipped", default="z")
mapping = TagMap(
    {first: blocks.txt[1], second: blocks.txt[12], skipped: blocks.txt[13]},
    include_system=False,
)
"""

_TEXT_PROGRAM = """import warnings
warnings.simplefilter("ignore")
from pyrung import PLC, Program, copy, rung
from tags import first, second, skipped
with Program(strict=False) as prog:
    for tag in (first, second, skipped):
        with rung():
            copy(tag, tag)
runner = PLC(prog, dt=0.010)
"""


def test_pyrung_starts_from_unclear_plc_data_with_the_skipped_text_at_power_on(
    tmp_path, pyrung_dap
):
    """The Simulator starts on pyrung from a file with unclear Text, as its notice says."""
    from clicknick.simulation_session import _default_snapshot_reader

    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project))
    (project / "tags.py").write_text(_TEXT_TAGS_MODULE, encoding="utf-8")
    (project / "run.py").write_text(_TEXT_PROGRAM, encoding="utf-8")

    def factory(**callbacks):
        dap = pyrung_dap(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.read_snapshot = _default_snapshot_reader
    data = _plc_data_with_unknown_text(tmp_path)
    harness.sim.set_plc_data_path(data)
    harness.open()

    assert harness.sim.is_ready, harness.messages()
    dap = harness.dap
    assert (dap.tag("First"), dap.tag("Second")) == ("A", "i")
    assert dap.tag("Skipped") == "z", "TXT13 keeps its power-on value"
    _assert_one_warning_about(harness, data)
    assert "pyrung skipped" not in harness.messages()


# ----------------------------------------------------------------------
# pyrung's fallback to a top-level tags module
# ----------------------------------------------------------------------

#: A top-level ``tags`` module, as a hand-written pyrung project has one. Its TagMap puts
#: OldName on X001.
_OLD_TAGS_MODULE = """from pyrung import Bool
from pyrung.click import ClickBlocks, TagMap

blocks = ClickBlocks()
old_name = Bool("OldName")
mapping = TagMap({old_name: blocks.x[1]}, include_system=False)
"""

_OLD_TAGS_PROGRAM = """import warnings
warnings.simplefilter("ignore")
from pyrung import Bool, PLC, Program, out, rung
from tags import old_name
with Program(strict=False) as prog:
    with rung(old_name):
        out(Bool("Lamp"))
runner = PLC(prog, dt=0.010)
"""

#: A program with no TagMap. If no module from the program's folder defines a TagMap named
#: ``mapping``, pyrung 0.18.0 uses the ``mapping`` of ``sys.modules["tags"]``, wherever that
#: module came from.
_NO_TAGMAP_PROGRAM = """import warnings
warnings.simplefilter("ignore")
from pyrung import Bool, PLC, Program, out, rung
with Program(strict=False) as prog:
    with rung(Bool("Start")):
        out(Bool("Lamp"))
runner = PLC(prog, dt=0.010)
"""


def _on_pyrung_at(home: Path, project: Path, pyrung_dap, files: dict[str, str]) -> Harness:
    """Return a harness that runs *project* on pyrung's DAP server once a test opens it.

    *files* maps each file name in *project* to its text. The harness keeps its settings in
    *home*.
    """
    home.mkdir()
    project.mkdir()
    harness = Harness(home, _ready_analysis(project))
    for name, text in files.items():
        (project / name).write_text(text, encoding="utf-8")

    def factory(**callbacks):
        dap = pyrung_dap(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    return harness


def _assert_x001_unmapped(dap) -> None:
    """Assert that pyrung refuses a force on X001, because no TagMap maps it."""
    with pytest.raises(DapRequestError, match=r"X001 is not mapped to a tag"):
        dap.force("X001", True)
    assert dap.list_forces() == {}


def _on_pyrung_built(tmp_path, pyrung_dap, monkeypatch, *, unreadable: bool) -> Harness:
    """Return a harness on pyrung's DAP server for a workspace that a real build wrote.

    CLICK's Main Program is X001 -> C1, then a Compare -> C2, then X002 -> C3. If *unreadable*
    is set, laddercodec cannot read the Compare, and the build holds undecoded() in its place.
    The session reads the markers from src/plc as the app does (``read_program_stops``).
    """
    from laddercodec import Coil, CompareContact, Contact, Program, Rung, UnknownCondition

    from clicknick.services.program_stops import read_program_stops

    def _rung(first: object, output: str) -> Rung:
        return Rung([[first, *["-"] * 30]], [Coil(output)], None)

    compare = UnknownCondition(raw=b"Compare") if unreadable else CompareContact("==", "DS1", "1")
    rungs = [
        _rung(Contact("X001"), "C1"),
        _rung(compare, "C2"),
        _rung(Contact("X002"), "C3"),
    ]
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, rungs),
    )
    monkeypatch.setattr("clicknick.services.analysis_service._channel_inputs", lambda _s: [])
    scr = tmp_path / "scr"
    scr.mkdir()
    (scr / "Scr1.tmp").write_bytes(b"scr")
    analysis = AnalysisService()
    assert analysis.build(scr, None, persist_dir=tmp_path / "pyrung_project")
    assert bool(analysis.undecoded_rungs) is unreadable
    home = tmp_path / "home"
    home.mkdir()
    harness = Harness(home, analysis)

    def factory(**callbacks):
        dap = pyrung_dap(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.sim._stops_reader = read_program_stops
    return harness


def _plc_main(harness: Harness) -> Path:
    return harness.analysis.project_dir / "src" / "plc" / "main.py"


MAIN_STOP = UndecodedRung("Main Program", 2)


def test_pyrung_runs_a_built_program_up_to_its_marker(tmp_path, pyrung_dap, monkeypatch):
    """Main Program's rung 2 is a Compare that laddercodec cannot read.

    pyrung runs rung 1 and never runs rung 3.
    """
    from pyrung.live import send_command

    harness = _on_pyrung_built(tmp_path, pyrung_dap, monkeypatch, unreadable=True)
    harness.open()

    assert harness.sim.is_ready, harness.messages()
    assert harness.sim.stop_notice == simulation_stop_notice([MAIN_STOP])
    # The panel lists X001, which rung 1 uses, and not X002, which only rung 3 uses
    assert {"X001"} <= harness.sim._used_io()
    assert "X002" not in harness.sim._used_io()
    dap = harness.dap
    harness.sim.set_switch_position("run")
    harness.scheduler.run_ready()
    dap.force("X001", True)
    dap.force("X002", True)
    dap.scan(2)
    assert dap.tag("C1") is True
    # The program that pyrung runs has no rung 3, so nothing in it names C3
    assert send_command(dap._test_session, "get C3") == (False, "Unknown tag 'C3'.")


def test_a_write_without_the_marker_clears_the_stop_notice(tmp_path, pyrung_dap, monkeypatch):
    """The user deletes the undecoded() rung in src/plc and writes. CLICK's build still has it."""
    harness = _on_pyrung_built(tmp_path, pyrung_dap, monkeypatch, unreadable=True)
    harness.open()
    assert harness.sim.stop_notice == simulation_stop_notice([MAIN_STOP])
    main = _plc_main(harness)
    source = main.read_text(encoding="utf-8")
    marker = re.search(
        r"\n    comment\('UNDECODED: [^\n]*\n    with rung\(\):[^\n]*\n[^\n]*\n", source
    )
    assert marker is not None, source
    main.write_text(source.replace(marker.group(0), "\n"), encoding="utf-8")

    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert "OK - the simulation runs the new program." in harness.messages(), harness.messages()
    assert harness.analysis.undecoded_rungs == (MAIN_STOP,)
    assert harness.sim.stop_notice is None
    dap = harness.dap
    harness.sim.set_switch_position("run")
    harness.scheduler.run_ready()
    dap.force("X002", True)
    dap.scan(2)
    assert dap.tag("C3") is True, "rung 3 runs"


def test_a_marker_put_in_src_plc_shows_the_stop_notice(tmp_path, pyrung_dap, monkeypatch):
    """The user restores a src/plc backup that holds a marker. CLICK's build has none.

    A write shows the notice, and a Restart keeps it.
    """
    harness = _on_pyrung_built(tmp_path, pyrung_dap, monkeypatch, unreadable=False)
    harness.open()
    assert harness.sim.is_ready, harness.messages()
    assert harness.sim.stop_notice is None
    main = _plc_main(harness)
    source = main.read_text(encoding="utf-8")
    rung_2 = "    with rung(DS1 == 1):  # R2\n        out(C2)\n"
    assert rung_2 in source, source
    marker = '    with rung():  # R2\n        undecoded("bad", rung=1, stop="end")\n'
    main.write_text(
        "from pyrung.click import undecoded\n" + source.replace(rung_2, marker),
        encoding="utf-8",
    )

    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert harness.analysis.undecoded_rungs == ()
    assert harness.sim.stop_notice == simulation_stop_notice([MAIN_STOP])

    harness.sim.restart()
    harness.scheduler.run_ready()

    assert len(harness.daps) == 2 and harness.sim.is_ready, harness.messages()
    assert harness.sim.stop_notice == simulation_stop_notice([MAIN_STOP])


def test_a_restart_on_another_project_starts_a_process_without_its_tags(tmp_path, pyrung_dap):
    """Project A imports a top-level ``tags`` module. Project B has no TagMap.

    The workspace moves from A to B, and the user restarts the simulation. The restart ends A's
    process and starts B in a process of its own, so A's ``tags`` module is not loaded there.
    pyrung finds no TagMap for B and refuses a force on X001.
    """
    harness = _on_pyrung_at(
        tmp_path / "home",
        tmp_path / "a",
        pyrung_dap,
        {"tags.py": _OLD_TAGS_MODULE, "run.py": _OLD_TAGS_PROGRAM},
    )
    harness.open()
    assert harness.sim.is_ready, harness.messages()
    first = harness.dap
    first.force("X001", True)
    assert first.list_forces() == {"OldName": True}, "A's TagMap puts OldName on X001"
    first.unforce("X001")
    process = first._proc

    project_b = tmp_path / "b"
    project_b.mkdir()
    (project_b / "run.py").write_text(_NO_TAGMAP_PROGRAM, encoding="utf-8")
    harness.analysis._result = replace(harness.analysis._result, project_dir=project_b)
    harness.sim.restart()
    harness.scheduler.run_ready()

    assert process.poll() is not None, "the restart ends A's process"
    assert harness.sim.is_ready, harness.messages()
    second = harness.dap
    assert second is not first, "B runs on a DapService of its own"
    second.frame()
    assert second.program_tags == {"Start", "Lamp"}
    _assert_x001_unmapped(second)


def test_a_write_drops_the_tags_module_that_the_old_program_imported(tmp_path, pyrung_dap):
    """The program stops importing its top-level ``tags`` module, and the user writes it.

    The file ``tags.py`` stays beside ``run.py``. Before the reload, pyrung removes every module
    whose file is in the program's folder from ``sys.modules``. So the new program finds no
    TagMap, and pyrung refuses a force on X001.
    """
    project = tmp_path / "project"
    harness = _on_pyrung_at(
        tmp_path / "home",
        project,
        pyrung_dap,
        {"tags.py": _OLD_TAGS_MODULE, "run.py": _OLD_TAGS_PROGRAM},
    )
    harness.open()
    assert harness.sim.is_ready, harness.messages()
    dap = harness.dap
    dap.force("X001", True)
    assert dap.list_forces() == {"OldName": True}, "the old program's TagMap puts OldName on X001"
    dap.unforce("X001")

    (project / "run.py").write_text(_NO_TAGMAP_PROGRAM, encoding="utf-8")
    _rebuild(harness)
    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert harness.messages("error") == ""
    assert harness.dap is dap, "the write reloads in the same process"
    dap.frame()
    assert dap.program_tags == {"Start", "Lamp"}
    _assert_x001_unmapped(dap)


def test_run_time_edit_keeps_every_value_and_the_force(on_pyrung):
    dap = on_pyrung.dap
    _rebuild(on_pyrung)
    on_pyrung.sim.run_time_edit()
    on_pyrung.scheduler.run_ready()
    dap.scan(1)

    # Both counters read 6 before the write, and the program adds 1 each scan.
    # RUN Time Edit keeps every value, so both read 7 after one scan.
    assert (dap.tag("Ret"), dap.tag("NonRet"), dap.tag("Light")) == (7, 7, True)
    assert dap.list_forces() == {"Light": True}
    assert on_pyrung.sim.program_change is None


def test_stop_and_write_clears_non_retentive_values_and_keeps_the_force(on_pyrung):
    dap = on_pyrung.dap
    _rebuild(on_pyrung)
    on_pyrung.sim.stop_and_write()
    on_pyrung.scheduler.run_ready()
    dap.scan(1)

    # Stop and Write clears non-retentive values. NonRet starts again from 0 and reads 1
    # after the scan, while Ret reads 7. The Light force survives.
    assert (dap.tag("Ret"), dap.tag("NonRet"), dap.tag("Light")) == (7, 1, True)
    assert dap.list_forces() == {"Light": True}
    assert dap.mode == "run"


def test_the_named_addresses_come_from_pyrung_and_follow_a_write(on_pyrung):
    """pyrung's frames list the tags that the program knows, and the frame after a write too."""
    sim, dap = on_pyrung.sim, on_pyrung.dap
    assert {"X001", "Y001", "DS1", "DS2"} <= sim.named_addresses
    assert not sim.is_named("X002")

    # The program starts to use X002, as Aux.
    _name(on_pyrung, "X002", "Aux")
    run = on_pyrung.analysis.project_dir / "run.py"
    run.write_text(
        _VALUES_PROGRAM.replace(
            "with rung(start):",
            'with rung(Bool("Aux")):\n        out(Bool("Lamp"))\n    with rung(start):',
        ),
        encoding="utf-8",
    )
    _rebuild(on_pyrung)
    sim.run_time_edit()
    on_pyrung.scheduler.run_ready()
    dap.frame()

    assert "Aux" in dap.program_tags
    assert sim.is_named("X002")
    assert on_pyrung.messages("error") == ""


def test_a_link_that_lands_where_a_followed_name_went_is_dropped(ready):
    """The name Start moves from X001 to X002, and X002 has a cut of its own.

    The write keeps Start's link, on X002, and drops the cut.
    """
    _name(ready, "X001", "Start")
    _name(ready, "Y001", "Motor")
    ready.open()
    ready.sim.link("X001", BenchLink("Y001"))
    ready.dap.bench["X002"] = {"enable": None, "enabled": True}  # `unlink X002` in the Console
    ready.dap.links_revision += 1
    _frame(ready)
    _rebuild(ready, {"X001": "Begin", "X002": "Start"})
    assert (
        "The cut on X002 is removed, because the link on Start moved onto X002."
    ) in ready.sim.program_change.text
    mark = len(ready.dap.calls)

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert _calls_since(ready.dap, mark) == [("reload",)]
    assert ready.dap.plans[-1]["links"] == {"Start": {"en": "Motor", "fb": "Start"}, "X002": None}
    assert ready.dap.bench == {"Start": {"enable": "Motor", "enabled": True, "trigger": None,
                                         "response": {}}}  # fmt: skip
    assert ready.sim.bench_links == {"X002": BenchLink("Y001")}
    assert "The cut on X002 is removed" in (ready.sim.notice or "")


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
    assert (
        "ClickNick cannot tell which program the simulation runs, and it may be paused"
        in ready.messages("error")
    )
    assert ready.sim.program_change.actions[-1] == "restart"


def _console_command(ready, run=lambda: "done"):
    """Start a Console command.

    Return a function that finishes it, and a list of the values that its done callback
    received.
    """
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
    # The write paused it and never sent continue, so frames show it stepping.
    ready.dap.frame(mode="run", running=False, forces={})
    ready.scheduler.run_ready()

    assert ready.sim.switch_position == "step"
    text = ready.sim.program_change.text
    assert "cannot tell which program the simulation runs, and it may be paused" in text
    assert "If the simulation runs the new program, it released the force on Run" in text
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
    """Start a RUN Time Edit in RUN that pyrung never answers. Frames then show it paused."""
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
    ready.sim.write_program()  # the write offered in STEP, which is not offered here
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
    """Simulate CLICK writing the PLC data dump again, then run the watch tick that sees it."""
    import os

    from clicknick.simulation_session import WATCH_MS

    later = data.stat().st_mtime + 5
    os.utime(data, (later, later))
    ready.scheduler.fire(WATCH_MS)


def _writing_with_plc_data(ready, tmp_path) -> tuple[list, Path]:
    """Start a simulation from a PLC data file and ask for a write that nobody answers."""
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
    assert (
        "The PLC data file changed. The simulation restarts from it once the program is written."
    ) in ready.messages()
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

    ready.sim.relaunch()  # the workspace moved, and this launch reads the changed data file
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
    """Return the error that DapService raises when pyrung has no pyrungReload (before 0.16)."""
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

    # The session tries the planned reload once. It does not fall back to a plain reload with
    # a release and re-apply around it.
    assert _calls_since(ready.dap, mark) == [("reload",), ("continue",)]
    assert ready.dap.forces == {"Motor": True}
    assert ready.dap.bench["X002"]["enable"] == "Motor"
    assert ready.sim.forces == {"Y001": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.to_tag("X001") == "Start", "the old program runs on"
    change = ready.sim.program_change
    assert "older than 0.16.0" in change.text
    assert (
        "Use Restart to run the new program. The simulation still runs the previous one."
    ) in ready.messages("error")
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
    ready.dap.bench["Door"] = {"enable": None, "enabled": True}  # a cut stops Door's own link
    _rebuild(ready, {"X002": "ProxSensor", "X003": "DoorSw"})

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert ready.dap.plans[-1]["declared"] == {"Prox": "ProxSensor"}


# A feedback on X002 that a bench link or the program's own link drives from Cmd (X001).
_LINK_PROGRAM = """\
import warnings
warnings.simplefilter("ignore")
from pyrung import Bool, PLC, Physical, Program, rung, out
cmd = Bool({enable!r})
fb = {feedback}
with Program(strict=False) as prog:
    with rung(cmd):
        out(Bool("Lamp"))
    with rung(fb):
        out(Bool("Sink"))
runner = PLC(prog, dt=0.010)
"""


def _link_program(name: str, *, declared: bool, enable: str = "Cmd") -> str:
    if declared:
        feedback = f"Bool({name!r}, physical=Physical({name!r}, timed='100ms'), link={enable!r})"
    else:
        feedback = f"Bool({name!r})"
    return _LINK_PROGRAM.format(feedback=feedback, enable=enable)


def _timing_on_pyrung(tmp_path, dap_class, *, declared: bool):
    """Run the session in RUN on pyrung's DAP server. Return the harness and a timer count.

    Prox, on X002, has a timed link from Cmd. The count is how far its 100 ms timer has run,
    and it is part way through.
    """
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
def test_renaming_a_linked_input_while_it_times_keeps_its_timing(
    tmp_path, pyrung_dap, declared, enable
):
    harness, count = _timing_on_pyrung(tmp_path, pyrung_dap, declared=declared)
    dap = harness.dap
    run = harness.analysis.project_dir / "run.py"
    run.write_text(_link_program("ProxSensor", declared=declared, enable=enable), encoding="utf-8")
    _rebuild(harness, {"X001": enable, "X002": "ProxSensor"})

    harness.sim.run_time_edit()
    harness.scheduler.run_ready()
    dap.scan(1)

    assert harness.sim.program_change is None
    assert dap.tag("__tmd_on__ProxSensor") == count + 10, "one 10 ms scan on, not from 0"
    assert dap.list_forces() == {enable: True}, "X001's force, on its new name"
    assert harness.sim.forces == {"X001": True}
    if declared:
        return
    assert dap.bench_links() == {"ProxSensor": enable}
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
from pyrung import Bool, PLC, Physical, Program, rung, out
cmd, go = Bool("Cmd"), Bool("Go")
start = Bool("Start", physical=Physical("Start", timed="100ms"), link="Cmd")
begin = Bool("Begin", physical=Physical("Begin", timed="100ms"), link="Go")
with Program(strict=False) as prog:
    with rung(cmd):
        out(Bool("Lamp"))
    with rung(go):
        out(Bool("Horn"))
    with rung(start):
        out(Bool("Sink"))
    with rung(begin):
        out(Bool("Drain"))
runner = PLC(prog, dt=0.010)
"""


def test_declared_links_whose_nicknames_and_comments_swap_keep_their_own_timing(
    tmp_path, pyrung_dap
):
    dap_class = pyrung_dap
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

    # In CLICK, X002 and X003 swap nicknames and comments. Each link stays with its name, so
    # it moves to the other address.
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


def test_the_console_runs_assert_and_run_until_on_pyrung(on_pyrung):
    """The Console sends these through ``send_command``, and they need no recording."""
    from pyrung.live import send_command

    session = on_pyrung.dap._test_session
    assert send_command(session, "assert Light == True") == (True, "assert ok: Light = True")
    ok, text = send_command(session, "assert Light == False")
    assert not ok and "expected False" in text
    ok, text = send_command(session, "run until Ret > 20 within 100")
    assert ok and "Ret > 20 is true" in text
    assert on_pyrung.dap.tag("Ret") == 21
    ok, text = send_command(session, "run until Ret > 100000 within 5")
    assert not ok and "still false after 5 scan(s)" in text


# ----------------------------------------------------------------------
# Bench links on an address that no rung names
# ----------------------------------------------------------------------

#: A program in which a rung names every point of :data:`CPU` except X003.
WITHOUT_X003 = ("X001", "X002", "Y001", "DF1")


@pytest.fixture(params=[False, True], ids=["unknown-tag", "no-rung-uses"])
def without_x003(tmp_path, request):
    """Return a harness whose program names every point of :data:`CPU` except X003.

    The fixture runs each test twice. pyrung refuses a link to X003 with ``unknown tag`` in
    one run and with ``no rung uses`` in the other.
    """
    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project, used=WITHOUT_X003))
    harness.no_rung_uses = request.param
    return harness


def _link_calls(dap: FakeDap) -> list[tuple]:
    return [c[:2] for c in dap.calls if c[0] in ("link", "unlink", "restore_link", "set_links")]


def test_linking_an_address_that_no_rung_names_sends_nothing_and_shows_no_error(without_x003):
    harness = without_x003
    harness.open()
    assert harness.sim.named_addresses is None, "unknown until the first frame lists the tags"
    _frame(harness)
    assert harness.sim.named_addresses == frozenset(WITHOUT_X003)
    assert not harness.sim.is_named("X003")
    errors: list[str] = []

    harness.sim.link("X003", ON_DELAY_LINK, on_error=errors.append)
    harness.sim.link("X002", BenchLink("X003", response=response(on_delay="1s")))
    harness.scheduler.run_ready()

    assert _link_calls(harness.dap) == []
    assert errors == []
    assert harness.messages("error") == ""
    assert [e.text for e in harness.events if e.kind == "echo"] == []
    waiting = {link.feedback: link for link in harness.sim.links if link.waiting}
    assert set(waiting) == {"X002", "X003"}
    assert not any(link.active for link in waiting.values())

    harness.sim.set_link_enabled("X003", False)
    harness.sim.restore_link("X003")
    harness.sim.discard_bench_links()
    harness.scheduler.run_ready()
    assert _link_calls(harness.dap) == []
    assert harness.sim.bench_links == {}
    assert harness.messages("error") == ""


def test_a_link_the_simulation_refuses_for_an_unknown_tag_waits_with_no_error(without_x003):
    harness = without_x003
    harness.open()  # no frame yet, so ClickNick does not know what the rungs name
    errors: list[str] = []

    harness.sim.link("X003", ON_DELAY_LINK, on_error=errors.append)
    harness.scheduler.run_ready()

    assert _link_calls(harness.dap) == [("link", "X003")]
    assert errors == []
    assert harness.messages("error") == ""
    assert harness.sim.bench_links == {"X003": ON_DELAY_LINK}
    assert harness.sim.link_waits("X003")
    _frame(harness)
    assert harness.sim.bench_links == {"X003": ON_DELAY_LINK}


def test_a_saved_link_on_an_unnamed_address_waits_then_applies_after_a_write(
    without_x003, tmp_path
):
    harness = without_x003
    path = tmp_path / "app" / "Line1.toml"
    save_state(path, SimulatorState(links={"X002": AUX_LINK, "X003": ON_DELAY_LINK}))
    harness.sim.set_state_location("Line1", None)
    harness.open()

    # Before the first frame, every link goes. pyrung refuses the one on X003, and it waits.
    assert _link_calls(harness.dap) == [("link", "X002"), ("link", "X003")]
    assert harness.messages("error") == ""
    assert harness.sim.link_waits("X003")
    harness.dap.links_revision += 1  # the Console changed a link
    _frame(harness)
    assert harness.sim.bench_links == {"X002": AUX_LINK, "X003": ON_DELAY_LINK}
    assert harness.sim.link_waits("X003")
    harness.scheduler.fire(SAVE_DELAY_MS)
    assert dict(load_state(path).links) == {"X002": AUX_LINK, "X003": ON_DELAY_LINK}

    _rebuild(harness, uses=("X003",))
    mark = len(harness.dap.calls)
    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert ("link", "X003") in [c[:2] for c in harness.dap.calls[mark:]]
    assert harness.dap.bench["X003"]["enable"] == "Y001"
    assert harness.sim.named_addresses is None, "until the frame after the reload"
    _frame(harness)
    assert harness.sim.is_named("X003")
    assert not harness.sim.link_waits("X003")
    assert harness.sim.bench_links == {"X002": AUX_LINK, "X003": ON_DELAY_LINK}
    assert harness.messages("error") == ""


def test_a_write_that_stops_naming_an_address_keeps_its_link_and_force(ready):
    _name(ready, "X003", "Aux")
    _running_with_settings(ready)  # a bench link on X002, and a force on Y001
    ready.sim.force("X003", True)
    ready.scheduler.run_ready()
    _rebuild(ready, drops=("X002", "X003"))
    mark = len(ready.dap.calls)

    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    # pyrung drops both as gone. The force goes again by address, and the link waits.
    assert ("force", "X003", True) in ready.dap.calls[mark:]
    assert "X002" not in ready.dap.bench
    assert ready.sim.forces == {"Y001": True, "X003": True}
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.link_waits("X002")
    assert ready.sim.notice == (
        "The bench link on X002 waits until a rung in the simulation names both X002 and Y001."
    )
    ready.dap.links_revision += 1
    _frame(ready)
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert not ready.sim.is_named("X002")

    _rebuild(ready, uses=("X002",))
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    assert ready.dap.bench["X002"]["enable"] == "Y001"
    assert not ready.sim.link_waits("X002")


def test_a_write_that_stops_naming_only_the_enable_keeps_the_link_waiting(ready):
    ready.open()
    ready.sim.link("X001", BenchLink("X003", response=response(on_delay="1s")))
    _frame(ready)
    _rebuild(ready, drops=("X003",))

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert "X001" not in ready.dap.bench
    assert ready.sim.bench_links == {"X001": BenchLink("X003", response=response(on_delay="1s"))}
    assert ready.sim.link_waits("X001")
    assert "Could not keep" not in (ready.sim.notice or "")
    _frame(ready)
    assert ready.sim.link_waits("X001")
    assert ready.sim.is_named("X001") and not ready.sim.is_named("X003")

    _rebuild(ready, uses=("X003",))
    ready.sim.write_program()
    ready.scheduler.run_ready()
    assert ready.dap.bench["X001"]["enable"] == "X003"


def test_a_link_the_new_program_declares_does_not_wait(ready):
    ready.open()
    ready.sim.link("X002", ON_DELAY_LINK)
    _frame(ready)
    ready.dap.reload_drops = {"X002": ("in program", "the program links X002")}

    ready.sim.write_program()
    ready.scheduler.run_ready()

    assert not ready.sim.link_waits("X002")
    assert ready.sim.bench_links == {}


def test_saved_settings_apply_with_no_cpu(ready, tmp_path):
    ready.sim._layout_reader = lambda _path, used: build_panel_layout((), used)
    path = tmp_path / "app" / "Line1.toml"
    saved = SimulatorState(
        switches={"X001": True, "X009": True},
        analog={"DF1": 4.5},
        forces={"Y001": True},
        links={"X002": AUX_LINK},
        modules=("cpu:C0-02DD1-D",),
    )
    save_state(path, saved)
    ready.sim.set_state_location("Line1", None)
    ready.open()

    assert not ready.sim.layout.has_cpu
    assert ready.sim.layout.addresses("input") == ("X001", "X002", "X003")
    assert ("force", "Y001", True) in ready.dap.calls
    assert _link_calls(ready.dap) == [("link", "X002")]
    ready.sim.set_switch_position("run")
    ready.scheduler.run_ready()
    assert ("set_mode", "run", {"X001": True, "X009": True, "DF1": 4.5}, None) in ready.dap.calls
    assert ready.sim.notice is None
    ready.scheduler.fire(SAVE_DELAY_MS)
    assert load_state(path) == replace(saved, run_hint_seen=True)


def test_restore_trims_analog_values_before_the_first_build(ready, tmp_path):
    save_state(
        tmp_path / "app" / "Line1.toml",
        SimulatorState(switches={"X201": True}, analog={"DF5": 1.0}, modules=("cpu:OLD",)),
    )
    ready.analysis._result = None  # the app has just connected, and its first build runs
    ready.analysis._status = AnalysisStatus.BUILDING
    ready.sim.set_state_location("Line1", None)
    ready.sim.refresh_layout()

    assert ready.sim.analog_value("DF5") is None
    assert ready.sim.switch_on("X201")
    assert ready.sim.notice is not None and "DF5" in ready.sim.notice


def test_a_link_that_pyrung_refuses_with_a_capital_unknown_tag_waits(ready):
    ready.open()  # no frame yet, so ClickNick does not know what the rungs name
    ready.dap.refuse_links["X002"] = "Unknown tag 'X002' (address X002 is not mapped to a tag)"
    errors: list[str] = []

    ready.sim.link("X002", ON_DELAY_LINK, on_error=errors.append)
    ready.scheduler.run_ready()

    assert errors == []
    assert ready.messages("error") == ""
    assert ready.sim.bench_links == {"X002": ON_DELAY_LINK}
    assert ready.sim.link_waits("X002")


def test_a_refused_link_that_the_console_then_makes_no_longer_waits(ready):
    ready.open()
    ready.dap.refuse_links["X002"] = "unknown tag: X002"
    ready.sim.link("X002", ON_DELAY_LINK)
    ready.scheduler.run_ready()
    assert ready.sim.link_waits("X002")

    # The Console makes the same link, and pyrung takes it.
    del ready.dap.refuse_links["X002"]
    ready.dap.link("X002", "Y001", trigger=None, response=ON_DELAY_LINK.response)
    _frame(ready)

    assert not ready.sim.link_waits("X002")
    assert [link.feedback for link in ready.sim.links if link.source == "bench"] == ["X002"]
    mark = len(ready.dap.calls)
    ready.sim.restore_link("X002")
    ready.scheduler.run_ready()
    assert ("restore_link", "X002") in ready.dap.calls[mark:]
    assert ready.sim.bench_links == {}


def test_a_write_keeps_a_link_waiting_from_the_new_tags_without_sending_it(without_x003):
    harness = without_x003
    harness.open()
    _frame(harness)
    harness.sim.link("X003", ON_DELAY_LINK)
    harness.scheduler.run_ready()
    assert harness.sim.link_waits("X003")
    harness.dap.frame_after_reload = True

    # No rung of the new program names X003 either, and its frame comes before the job asks.
    _rebuild(harness)
    mark = len(harness.dap.calls)
    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert _link_calls(harness.dap)[-1:] != [("link", "X003")]
    assert ("link", "X003") not in [c[:2] for c in harness.dap.calls[mark:]]
    assert harness.sim.link_waits("X003")
    assert harness.sim.bench_links == {"X003": ON_DELAY_LINK}
    assert harness.messages("error") == ""

    # A rung of the next program names X003, so the write sends the link.
    _rebuild(harness, uses=("X003",))
    mark = len(harness.dap.calls)
    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert ("link", "X003") in [c[:2] for c in harness.dap.calls[mark:]]
    assert harness.dap.bench["X003"]["enable"] == "Y001"
    assert not harness.sim.link_waits("X003")


def test_a_write_keeps_a_link_waiting_when_pyrung_refuses_it_before_the_new_tags(without_x003):
    harness = without_x003
    harness.open()
    _frame(harness)
    harness.sim.link("X003", ON_DELAY_LINK)
    harness.scheduler.run_ready()
    assert harness.sim.link_waits("X003")

    # No rung of the new program names X003. Its frame has not come, so the write sends the
    # link, and pyrung refuses it.
    _rebuild(harness)
    mark = len(harness.dap.calls)
    harness.sim.write_program()
    harness.scheduler.run_ready()

    assert ("link", "X003") in [c[:2] for c in harness.dap.calls[mark:]]
    assert "Could not apply" not in (harness.sim.notice or "")
    assert harness.messages("error") == ""
    assert harness.sim.link_waits("X003")
    assert harness.sim.bench_links == {"X003": ON_DELAY_LINK}


def _x001_rows(harness: Harness) -> list[tuple]:
    return [
        (row.enable, row.source, row.waiting) for row in harness.sim.links if row.feedback == "X001"
    ]


def test_a_waiting_link_that_replaces_a_running_one_leaves_the_program_wiring(without_x003):
    harness = without_x003
    harness.open()
    _frame(harness)
    harness.sim.link("X001", ON_DELAY_LINK)
    harness.scheduler.run_ready()
    _frame(harness)
    assert harness.dap.bench["X001"]["enable"] == "Y001"

    # No rung names X003, so the new link waits, and pyrung drops the link from Y001.
    relinked = BenchLink("X003", response=response(on_delay="1s"))
    harness.sim.link("X001", relinked)
    harness.scheduler.run_ready()
    assert "X001" not in harness.dap.bench
    assert _x001_rows(harness) == [("X003", "bench", True)], "before the next listing"
    _frame(harness)

    assert _x001_rows(harness) == [("X003", "bench", True)]
    assert harness.sim.link_waits("X001")
    assert harness.sim.driving_link("X001") is None
    assert harness.sim.bench_links == {"X001": relinked}
    assert harness.messages("error") == ""

    # A rung of the next program names X003, so the write sends the new link.
    _rebuild(harness, uses=("X003",))
    harness.sim.write_program()
    harness.scheduler.run_ready()
    _frame(harness)

    assert harness.dap.bench["X001"]["enable"] == "X003"
    assert not harness.sim.link_waits("X001")
    assert _x001_rows(harness) == [("X003", "bench", False)]
    assert harness.sim.bench_links == {"X001": relinked}


def test_a_waiting_link_that_replaces_a_cut_gives_back_the_program_link(without_x003):
    harness = without_x003
    harness.open()
    harness.dap.project["X001"] = "Y001"
    _frame(harness)
    harness.sim.cut_link("X001")
    harness.scheduler.run_ready()
    _frame(harness)
    assert harness.dap.bench["X001"]["enable"] is None

    harness.sim.link("X001", BenchLink("X003", response=response(on_delay="1s")))
    harness.scheduler.run_ready()
    _frame(harness)

    assert "X001" not in harness.dap.bench
    assert _x001_rows(harness) == [("Y001", "project", False), ("X003", "bench", True)]
    assert harness.sim.driving_link("X001").source == "project"


def test_a_link_refused_for_an_unknown_tag_leaves_the_program_wiring(without_x003):
    harness = without_x003
    harness.open()  # no frame yet, so ClickNick sends each link
    harness.sim.link("X001", ON_DELAY_LINK)
    harness.scheduler.run_ready()
    assert harness.dap.bench["X001"]["enable"] == "Y001"

    # pyrung refuses X003, which no rung names, and keeps the link from Y001 until told.
    harness.sim.link("X001", BenchLink("X003", response=response(on_delay="1s")))
    harness.scheduler.run_ready()

    assert ("restore_link", "X001") in _link_calls(harness.dap)
    assert "X001" not in harness.dap.bench
    assert harness.sim.link_waits("X001")
    assert harness.messages("error") == ""


@pytest.mark.parametrize(
    "change",
    [
        lambda sim: sim.restore_link("X001"),
        lambda sim: sim.set_link_enabled("X001", False),
        lambda sim: sim.discard_bench_links(),
    ],
    ids=["restore", "disable", "discard"],
)
def test_a_change_to_a_waiting_link_drops_a_bench_link_that_pyrung_lists_there(
    without_x003, change
):
    harness = without_x003
    harness.open()
    _frame(harness)
    harness.sim.link("X001", BenchLink("X003", response=response(on_delay="1s")))
    harness.scheduler.run_ready()
    assert harness.sim.link_waits("X001")
    # The Console links X001 before ClickNick reads pyrung's links again.
    harness.dap.link("X001", "Y001", trigger=None, response=ON_DELAY_LINK.response)

    change(harness.sim)
    harness.scheduler.run_ready()

    assert "X001" not in harness.dap.bench
    assert harness.messages("error") == ""


def test_a_listing_asked_for_before_a_link_change_does_not_undo_it(without_x003):
    harness = without_x003
    harness.open()
    _frame(harness)
    harness.sim.link("X001", ON_DELAY_LINK)
    harness.scheduler.run_ready()
    _frame(harness)

    # pyrung answers a listing, and the user relinks X001 before ClickNick reads the answer.
    harness.sim._fetch_links(harness.dap, harness.sim._token)
    relinked = BenchLink("X003", response=response(on_delay="1s"))
    harness.sim.link("X001", relinked)
    harness.scheduler.run_ready()

    assert harness.sim.bench_links == {"X001": relinked}
    assert _x001_rows(harness) == [("X003", "bench", True)]
    _frame(harness)  # asks for the links again
    _frame(harness)
    assert harness.sim.bench_links == {"X001": relinked}
    assert harness.sim.link_waits("X001")
    assert "X001" not in harness.dap.bench


def test_disabling_a_held_link_before_the_first_frame_keeps_it(without_x003):
    harness = without_x003
    harness.open()  # no frame, so ClickNick sends the link, and pyrung refuses it
    harness.sim.link("X003", ON_DELAY_LINK)
    harness.scheduler.run_ready()
    assert harness.sim.link_waits("X003")

    harness.sim.set_link_enabled("X003", False)
    harness.scheduler.run_ready()
    harness.sim._fetch_links(harness.dap, harness.sim._token, sync=True)
    harness.scheduler.run_ready()

    assert harness.sim.link_waits("X003")
    assert harness.sim.bench_links == {"X003": replace(ON_DELAY_LINK, enabled=False)}


def test_a_write_that_applies_one_waiting_link_names_only_the_one_still_waiting(ready):
    _name(ready, "X003", "Aux")
    _running_with_settings(ready)  # a bench link on X002
    ready.sim.link("X003", ON_DELAY_LINK)
    ready.scheduler.run_ready()
    _rebuild(ready, drops=("X002", "X003"))
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    assert "X002" in ready.sim.notice and "X003" in ready.sim.notice

    _rebuild(ready, uses=("X002",))
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert not ready.sim.link_waits("X002")
    assert ready.sim.link_waits("X003")
    assert ready.sim.notice == (
        "The bench link on X003 waits until a rung in the simulation names both X003 and Y001."
    )


def test_a_write_that_leaves_no_link_waiting_clears_the_wait_notice(ready):
    _running_with_settings(ready)  # a bench link on X002
    _rebuild(ready, drops=("X002",))
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()
    assert "waits until" in (ready.sim.notice or "")

    _rebuild(ready, uses=("X002",))
    ready.sim.run_time_edit()
    ready.scheduler.run_ready()

    assert not ready.sim.link_waits("X002")
    assert ready.sim.notice is None


def test_the_notice_says_what_a_cut_waits_for():
    from clicknick.simulation_session import _waiting_text

    assert _waiting_text({"X003": BenchLink(None)}) == (
        "The cut on X003 waits until a rung in the simulation names X003."
    )


@pytest.mark.parametrize(
    ("reason", "addresses", "found"),
    [
        ("Unknown tag 'DS10'.", ("DS1", "DS10"), "DS10"),
        ("Unknown tag 'DS10'.", ("DS1",), None),
        ("Unknown tag 'DS1' (address DS1 is not mapped to a tag)", ("DS10", "DS1"), "DS1"),
        ("unknown tag: ds1", ("DS1",), "DS1"),
        (
            "cannot link X001: no rung uses X001, so the program has no tag for it",
            ("X001",),
            "X001",
        ),
        (
            "cannot link Start: no rung uses Start (X001), so the program has no tag for it",
            ("Y001", "X001"),
            "X001",
        ),
        ("DS1 is read-only", ("DS1",), None),
    ],
)
def test_a_refusal_names_an_address_only_as_a_whole_word(reason, addresses, found):
    from clicknick.simulation_session import _unresolved

    assert _unresolved(reason, addresses) == found


@pytest.mark.parametrize(
    ("reason", "unknown"),
    [
        ("unknown tag: X001", True),
        ("cannot link X001: unknown tag: X001", True),
        ("Unknown tag 'X002' (address X002 is not mapped to a tag)", True),
        ("cannot link X001: no rung uses X001, so the program has no tag for it", True),
        ("cannot link Start: no rung uses Start (X001), so the program has no tag for it", True),
        ("X001 is written by the program at Main:R3", False),
    ],
)
def test_pyrung_refuses_an_unknown_tag_in_either_wording(reason, unknown):
    from clicknick.simulation_session import _unknown_tag

    assert _unknown_tag(reason) is unknown


# ----------------------------------------------------------------------
# A switch on an address that pyrung cannot resolve
# ----------------------------------------------------------------------


def _sent_inputs(dap: FakeDap, mark: int) -> list[dict]:
    """Return the inputs of each patch and each switch to RUN that pyrung took since *mark*."""
    return [
        call[1] if call[0] == "patch" else call[2]
        for call in dap.calls[mark:]
        if call[0] == "patch" or call[:2] == ("set_mode", "run")
    ]


def test_a_switch_that_pyrung_cannot_resolve_stays_on_and_run_goes_through(ready):
    ready.open()
    ready.dap.unresolved.add("X002")

    ready.sim.toggle_switch("X001")
    ready.sim.toggle_switch("X002")
    ready.sim.set_switch_position("run")
    ready.scheduler.run_ready()

    # Each request goes again without X002. The patch of X002 alone leaves nothing to send.
    assert ready.dap.patch_attempts == [
        {"X001": True},
        {"X002": True},
        {"X001": True, "X002": True},
        {"X001": True},
    ]
    assert ready.dap.calls[-2:] == [("set_mode", "run", {"X001": True}, None), ("continue",)]
    assert ready.messages("error") == ""
    assert ready.sim.switch_on("X002")


@pytest.mark.parametrize("write", ["run_time_edit", "stop_and_write"])
def test_a_write_sends_a_left_out_switch_again_and_pyrung_takes_it_once_it_resolves(ready, write):
    _running_with_settings(ready)
    ready.dap.unresolved.add("X003")
    ready.sim.toggle_switch("X003")
    ready.scheduler.run_ready()

    _rebuild(ready)
    mark = len(ready.dap.calls)
    getattr(ready.sim, write)()
    ready.scheduler.run_ready()
    assert _sent_inputs(ready.dap, mark) == [{"X001": True}]

    ready.dap.unresolved.clear()  # the program that the next write loads maps X003
    _rebuild(ready, uses=("X003",))
    mark = len(ready.dap.calls)
    getattr(ready.sim, write)()
    ready.scheduler.run_ready()
    assert _sent_inputs(ready.dap, mark) == [{"X001": True, "X003": True}]
    assert ready.messages("error") == ""


def test_a_relaunch_in_run_leaves_out_a_switch_that_pyrung_cannot_resolve(ready):
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.toggle_switch("X002")
    ready.sim.set_switch_position("run")
    ready.dap.frame(mode="run", running=True)
    ready.scheduler.run_ready()
    ready.launch_hook = lambda: ready.daps[-1].unresolved.add("X002")

    ready.sim.restart()
    ready.scheduler.run_ready()

    assert ready.dap.calls[1:] == [("set_mode", "run", {"X001": True}, None), ("continue",)]
    assert ready.messages("error") == ""
    assert ready.sim.switch_on("X002")


@pytest.mark.parametrize(
    ("reason", "attempts"),
    [
        ("X002 is read-only", 1),
        ("Unknown tag 'Pump'.", 1),  # names no address in the patch
        ("Unknown tag 'X001'.", 2),  # names X001 again after the retry left it out
    ],
)
def test_any_other_refusal_of_a_patch_shows_its_error(ready, reason, attempts):
    ready.open()
    ready.sim.toggle_switch("X001")
    ready.sim.toggle_switch("X002")
    ready.scheduler.run_ready()
    ready.dap.refuse_patches = reason
    mark = len(ready.dap.patch_attempts)

    ready.sim.set_switch_position("run")
    ready.scheduler.run_ready()

    assert (
        ready.dap.patch_attempts[mark:] == [{"X001": True, "X002": True}, {"X002": True}][:attempts]
    )
    assert ready.messages("error") == f"Switching to RUN failed: {reason}"
    assert ("set_mode", "run") not in [call[:2] for call in ready.dap.calls]


_UNMAPPED_PROGRAM = """\
import warnings
warnings.simplefilter("ignore")
from pyrung import PLC, Program, rung, out
from pyrung.click import ClickBlocks, TagMap
x, y, *_ = ClickBlocks()
X001 = x[1]
Y001 = y[1]
mapping = TagMap({})
with Program(strict=False) as logic:
    with rung(X001):
        out(Y001)
runner = PLC(logic, dt=0.010)
"""


def test_a_switch_that_pyrung_cannot_resolve_does_not_stop_run_on_pyrung(tmp_path, pyrung_dap):
    """The program's TagMap maps no address, and no rung names X002, so pyrung cannot resolve X002."""
    dap_class = pyrung_dap
    project = tmp_path / "project"
    project.mkdir()
    harness = Harness(tmp_path, _ready_analysis(project, used=("X001", "Y001")))
    (project / "run.py").write_text(_UNMAPPED_PROGRAM, encoding="utf-8")

    def factory(**callbacks):
        dap = dap_class(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.open()
    dap = harness.dap
    dap.frame()
    harness.scheduler.run_ready()
    with pytest.raises(DapRequestError, match="Unknown tag 'X002'"):
        dap.patch({"X001": True, "X002": True})

    harness.sim.toggle_switch("X001")
    harness.sim.toggle_switch("X002")
    harness.sim.set_switch_position("run")
    harness.scheduler.run_ready()
    dap.scan(1)
    dap.frame()
    harness.scheduler.run_ready()

    assert harness.messages("error") == ""
    assert harness.sim.switch_position == "run"
    assert dap.tag("Y001") is True, "the switch on X001 went with the switch to RUN"
    assert harness.sim.switch_on("X002")


_RELINK_RUNGS = """\
import warnings
warnings.simplefilter("ignore")
from pyrung import PLC, Program, rung, out
from pyrung.click import ClickBlocks, TagMap
x, y, *_ = ClickBlocks()
mapping = TagMap({})
with Program(strict=False) as logic:
    with rung(x[1]):
        out(y[1])
    with rung(x[2]):
        out(y[2])
"""


_SPARE_TAGS_MODULE = """from pyrung import Bool
from pyrung.click import ClickBlocks, TagMap

blocks = ClickBlocks()
start = Bool("Start")
lamp = Bool("Lamp")
spare = Bool("Spare")
mapping = TagMap(
    {start: blocks.x[1], lamp: blocks.y[1], spare: blocks.x[2]},
    include_system=False,
)
"""

_SPARE_PROGRAM = """import warnings
warnings.simplefilter("ignore")
from pyrung import PLC, Program, out, rung
from tags import lamp, start
with Program(strict=False) as prog:
    with rung(start):
        out(lamp)
runner = PLC(prog, dt=0.010)
"""


def test_a_link_on_an_address_that_no_rung_uses_waits_on_pyrung_s_own_refusal(tmp_path, pyrung_dap):
    """This test runs the hold against pyrung's own refusal text. The other tests use FakeDap's copy of it.

    The TagMap names X002 ``Spare``, but no rung uses it. Before the first frame, ClickNick does
    not know which addresses the rungs name, so it sends the link. pyrung refuses it, with
    "unknown tag" on 0.18.0 and with "no rung uses" from PR #119. Both leave the link waiting.
    """
    harness = _on_pyrung_at(
        tmp_path / "home",
        tmp_path / "project",
        pyrung_dap,
        {"tags.py": _SPARE_TAGS_MODULE, "run.py": _SPARE_PROGRAM},
    )
    harness.open()
    assert harness.sim.is_ready, harness.messages()

    harness.sim.link("X002", ON_DELAY_LINK)
    harness.scheduler.run_ready()

    assert harness.sim.link_waits("X002")
    assert harness.dap.bench_links() == {}
    assert harness.messages("error") == ""


def test_a_waiting_link_that_replaces_a_running_one_on_pyrung(tmp_path, pyrung_dap):
    """Relink X002 from Y001, which a rung names, to Y003, which no rung names yet."""
    dap_class = pyrung_dap
    project = tmp_path / "project"
    project.mkdir()
    used = ("X001", "X002", "Y001", "Y002")
    harness = Harness(tmp_path, _ready_analysis(project, used=used))
    run = project / "run.py"
    run.write_text(_RELINK_RUNGS + "runner = PLC(logic, dt=0.010)\n", encoding="utf-8")

    def factory(**callbacks):
        dap = dap_class(**callbacks)
        harness.daps.append(dap)
        return dap

    harness.sim._dap_factory = factory
    harness.open()
    dap = harness.dap
    dap.frame()
    harness.scheduler.run_ready()
    harness.sim.link("X002", BenchLink("Y001", response=response(on_delay="1s")))
    harness.scheduler.run_ready()
    assert dap.bench_links() == {"X002": "Y001"}

    relinked = BenchLink("Y003", response=response(on_delay="1s"))
    harness.sim.link("X002", relinked)
    harness.scheduler.run_ready()
    dap.frame()
    harness.scheduler.run_ready()

    assert dap.bench_links() == {}
    assert harness.sim.link_waits("X002")
    rows = [(row.enable, row.source) for row in harness.sim.links if row.feedback == "X002"]
    assert rows == [("Y003", "bench")]
    assert harness.messages("error") == ""

    # The next program has a rung on Y003, so the write sends the new link.
    run.write_text(
        _RELINK_RUNGS + "    with rung(y[3]):\n        out(y[4])\nrunner = PLC(logic, dt=0.010)\n",
        encoding="utf-8",
    )
    _rebuild(harness, uses=("Y003", "Y004"), same_program=True)
    harness.sim.write_program()
    harness.scheduler.run_ready()
    dap.frame()
    harness.scheduler.run_ready()

    assert dap.bench_links() == {"X002": "Y003"}
    assert not harness.sim.link_waits("X002")
    assert harness.sim.bench_links == {"X002": relinked}
    assert harness.messages("error") == ""
