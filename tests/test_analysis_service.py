"""Tests for AnalysisService — mapping and query methods.

The full pipeline (Scr*.tmp → pyrung → graph) requires real ladder files,
so these tests focus on the mapping and query layers using a mock graph.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pyclickplc.addresses import get_addr_key, iter_address_slots, parse_address
from pyclickplc.banks import MEMORY_TYPE_TO_DATA_TYPE, DataType
from pyrung import Program
from pyrung.click import SystemNicknameRepair, SystemNicknameRepairRequired

from clicknick.models.address_row import AddressRow
from clicknick.services.analysis_service import (
    AnalysisResult,
    AnalysisService,
    AnalysisStatus,
    _build_tag_addr_key_map,
    _clean_generated,
    _publish_generated_project,
    _regenerate_persisted_project,
    _write_nicknames_csv,
)
from clicknick.services.project_workspace import (
    backup_plc_source,
    generated_source_state_path,
    older_plc_backups,
    plc_source_is_modified,
)


class TestBuildTagAddrKeyMap:
    """The tag map comes from the same nickname snapshot as the generated code."""

    def test_maps_nicknames(self, tmp_path):
        y1, y2 = get_addr_key("Y", 1), get_addr_key("Y", 2)
        rows = {
            y1: AddressRow(memory_type="Y", address=1, nickname="MotorOut"),
            y2: AddressRow(memory_type="Y", address=2, nickname="PumpRun"),
        }
        tag_to_key, key_to_tag = _build_tag_addr_key_map(_write_nicknames_csv(tmp_path, rows), rows)
        assert tag_to_key["MotorOut"] == y1
        assert tag_to_key["PumpRun"] == y2
        assert key_to_tag[y1] == "MotorOut"

    def test_a_blank_sd132_with_a_comment_is_a_tag_named_by_its_address(self, tmp_path):
        # pyclickplc 0.11.0 listed a blank name as an old name for SD132, and pyrung refused it.
        sd132 = get_addr_key("SD", 132)
        rows = {
            sd132: AddressRow(
                memory_type="SD", address=132, nickname="", comment="note", data_type=DataType.INT
            )
        }

        _tag_to_key, key_to_tag = _build_tag_addr_key_map(
            _write_nicknames_csv(tmp_path, rows), rows
        )

        assert key_to_tag[sd132] == "SD132"

    def test_unnamed_addresses_fall_back_to_display_address(self):
        tag_to_key, key_to_tag = _build_tag_addr_key_map(None, {})
        x1 = get_addr_key("X", 1)
        assert tag_to_key["X001"] == x1
        assert key_to_tag[x1] == "X001"

    def test_names_are_the_tags_pyrung_reads_from_the_snapshot(self, tmp_path):
        """The tag map names each tag as the installed pyrung does, whatever it does with spaces."""
        from pyrung.click import TagMap

        rows = {
            get_addr_key("C", 1): AddressRow(memory_type="C", address=1, nickname="Pump "),
            get_addr_key("C", 2): AddressRow(memory_type="C", address=2, nickname=" Fan"),
            get_addr_key("C", 3): AddressRow(memory_type="C", address=3, nickname="Motor"),
            get_addr_key("C", 4): AddressRow(memory_type="C", address=4, nickname="  "),
        }
        nickname_csv = _write_nicknames_csv(tmp_path, rows)
        pyrung_names = {
            get_addr_key(*parse_address(entry.hardware.name)): entry.logical.name
            for entry in TagMap.from_nickname_file(nickname_csv).tags()
        }

        _tag_to_key, key_to_tag = _build_tag_addr_key_map(nickname_csv, rows)

        # If pyrung gives an address no tag, the map names it by its address. The generated code
        # does the same.
        assert {key: key_to_tag[key] for key in rows} == {
            key: pyrung_names.get(key, row.display_address) for key, row in rows.items()
        }

    def test_clicks_system_points_keep_their_nicknames(self, tmp_path):
        sc1, sd9 = get_addr_key("SC", 1), get_addr_key("SD", 9)
        rows = {
            sc1: AddressRow(memory_type="SC", address=1, nickname="_Always_ON"),
            sd9: AddressRow(
                memory_type="SD", address=9, nickname="_Scan_Counter", data_type=DataType.INT
            ),
        }

        _tag_to_key, key_to_tag = _build_tag_addr_key_map(
            _write_nicknames_csv(tmp_path, rows), rows
        )

        assert (key_to_tag[sc1], key_to_tag[sd9]) == ("_Always_ON", "_Scan_Counter")
        assert key_to_tag[get_addr_key("SC", 2)] == "SC2"

    def test_an_unnamed_slot_of_a_block_has_the_name_the_program_gives_it(self, tmp_path):
        """pyrung names the slots of a ``:block`` range after the block.

        The tag map uses the same names.
        """
        rows = {
            get_addr_key("C", 1): AddressRow("C", 1, nickname="Fill_A", comment="<Fill:block>"),
            get_addr_key("C", 4): AddressRow("C", 4, comment="</Fill:block>"),
            get_addr_key("DS", 5): AddressRow(
                "DS", 5, comment="<Empty:block />", data_type=DataType.INT
            ),
        }

        tag_to_key, key_to_tag = _build_tag_addr_key_map(_write_nicknames_csv(tmp_path, rows), rows)

        names = [key_to_tag[get_addr_key("C", n)] for n in range(1, 6)]
        assert names == ["Fill_A", "Fill2", "Fill3", "Fill4", "C5"]
        assert key_to_tag[get_addr_key("DS", 5)] == "Empty1"
        assert tag_to_key["Fill3"] == get_addr_key("C", 3)
        assert "C3" not in tag_to_key

    def test_covers_every_address_slot(self):
        tag_to_key, key_to_tag = _build_tag_addr_key_map(None, {})
        assert len(key_to_tag) == sum(1 for _ in iter_address_slots())
        assert len(tag_to_key) == len(key_to_tag)

    def test_pyrung_reads_a_row_at_every_address_that_the_snapshot_can_hold(self, tmp_path):
        """pyrung refuses a row whose Address or Data Type CLICK would not write.

        Each address here has its bank's type, as CLICK's SC_.mdb gives it. The comments keep
        a space or a tab at their ends, and hold a comma, a double quote and a line break. The
        Text values are a space, a comma, a double quote and a tab.
        """
        from pyrung.click import TagMap

        comments = [" lead", "trail ", "\tTab", "a,b", 'say "hi"', "line1\r\nline2", ""]
        texts = [" ", ",", '"', "\t", "a", ""]
        rows = {}
        for n, (memory_type, address) in enumerate(iter_address_slots()):
            data_type = MEMORY_TYPE_TO_DATA_TYPE[memory_type]
            rows[get_addr_key(memory_type, address)] = AddressRow(
                memory_type,
                address,
                nickname=f"Tag{n}",
                comment=comments[n % len(comments)],
                data_type=data_type,
                initial_value=texts[n % len(texts)] if data_type == DataType.TXT else "",
            )

        tag_map = TagMap.from_nickname_file(_write_nicknames_csv(tmp_path, rows))

        names = {
            get_addr_key(*parse_address(entry.hardware.name)): entry.logical.name
            for entry in tag_map.tags()
        }
        assert names.items() <= {key: row.nickname for key, row in rows.items()}.items()
        # pyrung keeps its own names for some of CLICK's SC and SD system points, and lists no tag
        # there.
        assert {rows[key].memory_type for key in rows.keys() - names.keys()} == {"SC", "SD"}


@dataclass(frozen=True)
class _FakeDataView:
    """The part of pyrung's ``DataView`` that AnalysisService queries."""

    roles: dict[str, str]
    cones: dict[str, dict[str, frozenset[str]]]
    tags: frozenset[str] = frozenset()

    def _of(self, tags) -> _FakeDataView:
        return replace(self, tags=frozenset(tags))

    def _role(self, role: str) -> _FakeDataView:
        return self._of(tag for tag in self.tags if self.roles[tag] == role)

    def inputs(self) -> _FakeDataView:
        return self._role("input")

    def terminals(self) -> _FakeDataView:
        return self._role("terminal")

    def pivots(self) -> _FakeDataView:
        return self._role("pivot")

    def isolated(self) -> _FakeDataView:
        return self._role("isolated")

    def upstream(self, tag: str) -> _FakeDataView:
        return self._of(self.cones["upstream"].get(tag, frozenset()))

    def downstream(self, tag: str) -> _FakeDataView:
        return self._of(self.cones["downstream"].get(tag, frozenset()))


def _make_service_with_mock_graph(
    tag_roles: dict[str, str],
    tag_to_addr_key: dict[str, int],
    upstream: dict[str, frozenset[str]] | None = None,
    downstream: dict[str, frozenset[str]] | None = None,
) -> AnalysisService:
    """Create an AnalysisService whose program's DataView is a fake."""
    dataview = _FakeDataView(
        roles=dict(tag_roles),
        cones={"upstream": upstream or {}, "downstream": downstream or {}},
        tags=frozenset(tag_roles),
    )

    addr_key_to_tag = {v: k for k, v in tag_to_addr_key.items()}

    svc = AnalysisService()
    svc._result = AnalysisResult(
        dataview=dataview,
        program=MagicMock(),
        tag_to_addr_key=dict(tag_to_addr_key),
        addr_key_to_tag=addr_key_to_tag,
    )
    return svc


class TestAnalysisServiceRoleQueries:
    def setup_method(self):
        self.svc = _make_service_with_mock_graph(
            tag_roles={
                "Sensor1": "input",
                "Sensor2": "input",
                "MotorOut": "terminal",
                "Logic1": "pivot",
                "Orphan": "isolated",
            },
            tag_to_addr_key={
                "Sensor1": 100,
                "Sensor2": 200,
                "MotorOut": 300,
                "Logic1": 400,
                "Orphan": 500,
            },
        )

    def test_input_keys(self):
        assert self.svc.get_role_keys("input") == {100, 200}

    def test_output_keys(self):
        assert self.svc.get_role_keys("output") == {300}

    def test_pivot_keys(self):
        assert self.svc.get_role_keys("pivot") == {400}

    def test_isolated_keys(self):
        assert self.svc.get_role_keys("isolated") == {500}

    def test_unknown_role(self):
        assert self.svc.get_role_keys("bogus") == set()

    def test_role_cache(self):
        result1 = self.svc.get_role_keys("input")
        result2 = self.svc.get_role_keys("input")
        assert result1 is result2

    def test_unmapped_tag_excluded(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"Mapped": "input", "Unmapped": "input"},
            tag_to_addr_key={"Mapped": 100},
        )
        assert svc.get_role_keys("input") == {100}


class TestAnalysisServiceGraphQueries:
    def test_upstream_keys(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"A": "input", "B": "pivot", "C": "terminal"},
            tag_to_addr_key={"A": 100, "B": 200, "C": 300},
            upstream={"C": frozenset({"A", "B"})},
        )
        assert svc.get_upstream_keys("C") == {100, 200}

    def test_downstream_keys(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"A": "input", "B": "pivot", "C": "terminal"},
            tag_to_addr_key={"A": 100, "B": 200, "C": 300},
            downstream={"A": frozenset({"B", "C"})},
        )
        assert svc.get_downstream_keys("A") == {200, 300}

    def test_upstream_unmapped_excluded(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"A": "input", "B": "pivot"},
            tag_to_addr_key={"A": 100},
            upstream={"B": frozenset({"A", "Unmapped"})},
        )
        assert svc.get_upstream_keys("B") == {100}


_SUBROUTINE_PROGRAM = """from pyrung import Bool, Program, call, out, rung, subroutine

with Program(strict=False) as logic:
    with rung(Bool("Permit")):
        out(Bool("Enable"))
    with rung(Bool("Enable")):
        call("Fill")
    with subroutine("Fill"):
        with rung(Bool("Level")):
            out(Bool("Valve"))
"""


class TestAnalysisServiceCallSiteCones:
    """``upstream:`` and ``downstream:`` stop at the rung that calls a subroutine."""

    @pytest.fixture()
    def svc(self) -> AnalysisService:
        namespace: dict[str, object] = {}
        exec(compile(_SUBROUTINE_PROGRAM, "<program>", "exec"), namespace)  # noqa: S102
        program = namespace["logic"]
        assert isinstance(program, Program)
        tag_to_addr_key = {"Permit": 1, "Enable": 2, "Level": 3, "Valve": 4}
        svc = AnalysisService()
        svc._result = AnalysisResult(
            dataview=program.dataview(),
            program=program,
            tag_to_addr_key=tag_to_addr_key,
            addr_key_to_tag={key: tag for tag, key in tag_to_addr_key.items()},
        )
        return svc

    def test_upstream_of_a_subroutine_write_stops_at_the_call_condition(self, svc):
        # Enable is the call rung's condition. Permit, which writes Enable, is left out.
        assert svc.get_upstream_keys("Valve") == {2, 3}

    def test_downstream_of_a_call_condition_reaches_what_the_subroutine_writes(self, svc):
        assert svc.get_downstream_keys("Enable") == {4}
        # Only the tag that you start from crosses into the subroutine.
        assert svc.get_downstream_keys("Permit") == {2}

    def test_roles_come_from_the_dataview(self, svc):
        assert svc.get_role_keys("input") == {1, 3}
        assert svc.get_role_keys("output") == {4}
        assert svc.known_tag_names() == frozenset({"Permit", "Enable", "Level", "Valve"})


class TestAnalysisServiceLifecycle:
    def test_not_available_initially(self):
        svc = AnalysisService()
        assert not svc.is_available
        assert svc.get_role_keys("input") == set()
        assert svc.get_upstream_keys("X") == set()
        assert svc.known_tag_names() == frozenset()

    def test_invalidate(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"A": "input"},
            tag_to_addr_key={"A": 100},
        )
        assert svc.is_available
        svc.invalidate()
        assert not svc.is_available

    def test_known_tag_names(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"A": "input", "B": "pivot", "C": "terminal"},
            tag_to_addr_key={"A": 100, "B": 200},
        )
        assert svc.known_tag_names() == frozenset({"A", "B"})


class TestAnalysisStatus:
    """The status machine views poll to tell 'still building' from 'failed'."""

    def test_starts_idle(self):
        svc = AnalysisService()
        assert svc.status is AnalysisStatus.IDLE
        assert svc.error is None
        assert not svc.is_available

    def test_mark_failed_records_reason(self):
        svc = AnalysisService()
        svc.mark_failed("No saved ladder files.")
        assert svc.status is AnalysisStatus.FAILED
        assert svc.error == "No saved ladder files."
        assert not svc.is_available

    def test_build_failure_records_reason_and_reraises(self, monkeypatch, tmp_path):
        svc = AnalysisService()

        def _boom(*_args, **_kwargs):
            msg = "bad rung"
            raise ValueError(msg)

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _boom)
        with pytest.raises(ValueError, match="bad rung"):
            svc.build(tmp_path, None)

        assert svc.status is AnalysisStatus.FAILED
        assert svc.error == "ValueError: bad rung"
        assert "bad rung" in (svc.error_detail or "")
        assert not svc.is_available

    def test_build_failure_exposes_structured_system_nickname_repairs(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        repair = SystemNicknameRepair(
            memory_type="SD",
            address=132,
            current="_Port1_AL_Denied_Count",
            replacement="_Port1_AL_Denied_No1_Cnt",
        )

        def _needs_repair(*_args, **_kwargs):
            raise SystemNicknameRepairRequired((repair,))

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _needs_repair)
        with pytest.raises(SystemNicknameRepairRequired):
            svc.build(tmp_path, None)

        assert svc.status is AnalysisStatus.FAILED
        assert svc.system_nickname_repairs == (repair,)
        assert "CLICK system nicknames need repair" in (svc.error or "")

    @pytest.mark.parametrize("wrapped", ["raised", "cause", "context"])
    def test_a_build_refusing_an_old_comment_form_asks_for_upgrade_project(
        self, monkeypatch, tmp_path, wrapped
    ):
        from pyrung.click import OldCommentFormError

        svc = AnalysisService()

        def _old_form(*_args, **_kwargs):
            error = OldCommentFormError("profile=ramp:up=1", "Level at DF1")
            if wrapped == "raised":
                raise error
            try:
                raise error
            except OldCommentFormError as exc:
                # With "context", the RuntimeError's cause is a different error. Only its context
                # leads back to pyrung's error.
                cause = exc if wrapped == "cause" else KeyError("other")
                raise RuntimeError("project load failed") from cause

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _old_form)
        with pytest.raises((OldCommentFormError, RuntimeError)):
            svc.build(tmp_path, None)

        assert svc.status is AnalysisStatus.FAILED
        assert svc.needs_comment_upgrade
        svc.mark_building()
        assert not svc.needs_comment_upgrade

    def test_another_failure_does_not_ask_for_upgrade_project(self, monkeypatch, tmp_path):
        svc = AnalysisService()

        def _fails(*_args, **_kwargs):
            raise ValueError("bad rung")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _fails)
        with pytest.raises(ValueError):
            svc.build(tmp_path, None)
        assert not svc.needs_comment_upgrade

    def test_build_success_is_ready(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path, ({}, {})),
        )
        svc.build(tmp_path, None)
        assert svc.status is AnalysisStatus.READY
        assert svc.error is None
        assert svc.is_available

    @pytest.mark.parametrize("fails", [False, True])
    def test_a_build_asked_for_since_keeps_it_building(self, monkeypatch, tmp_path, fails):
        """If a save queues a build while another build runs, the running build publishes the
        earlier save.
        """
        svc = AnalysisService()
        outcomes = iter([fails, False])

        def _graph(*_args, **_kwargs):
            if next(outcomes):
                raise ValueError("bad rung")
            return MagicMock(), MagicMock(), tmp_path, ({}, {})

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _graph)
        first = svc.mark_building()
        second = svc.mark_building()  # CLICK saved while the first build runs

        if fails:
            with pytest.raises(ValueError):
                svc.build(tmp_path, None, serves=first)
        else:
            assert svc.build(tmp_path, None, serves=first)
        assert svc.status is AnalysisStatus.BUILDING
        assert svc.error is None
        svc.mark_failed("selection unreadable", serves=first)
        assert svc.status is AnalysisStatus.BUILDING

        assert svc.build(tmp_path, None, serves=second)
        assert svc.status is AnalysisStatus.READY

    @pytest.mark.parametrize("fails", [False, True])
    def test_a_request_failing_before_it_is_queued_waits_for_the_build_running(
        self, monkeypatch, tmp_path, fails
    ):
        """CLICK saves while a build runs and the save's database is not found."""
        svc = AnalysisService()
        during: list[AnalysisStatus] = []

        def _graph(*_args, on_project_generated=None, **_kwargs):
            svc.mark_failed("No Click project database found.")
            during.append(svc.status)
            if fails:
                raise ValueError("bad rung")
            return MagicMock(), MagicMock(), tmp_path, ({}, {})

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _graph)
        serves = svc.mark_building()

        if fails:
            with pytest.raises(ValueError):
                svc.build(tmp_path, None, serves=serves)
        else:
            assert svc.build(tmp_path, None, serves=serves), "the build was discarded"
            assert svc.is_available
        assert during == [AnalysisStatus.BUILDING]
        assert svc.status is AnalysisStatus.FAILED
        assert svc.error == "No Click project database found."
        # The failed request is a save the workspace does not hold.
        assert not svc.project_is_current

    def test_a_failed_request_waits_for_the_build_queued_before_it(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path, ({}, {})),
        )
        first = svc.mark_building()
        second = svc.mark_building()
        svc.mark_failed("No saved ladder files.")

        assert svc.build(tmp_path, None, serves=first)
        assert svc.status is AnalysisStatus.BUILDING
        svc.mark_failed("selection unreadable", serves=second)  # its build never ran
        assert svc.status is AnalysisStatus.FAILED
        assert svc.error == "No saved ladder files."

    def test_a_later_request_replaces_a_failed_one(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path, ({}, {})),
        )
        first = svc.mark_building()
        svc.mark_failed("No saved ladder files.")
        second = svc.mark_building()

        assert svc.build(tmp_path, None, serves=first)
        assert svc.status is AnalysisStatus.BUILDING
        assert svc.build(tmp_path, None, serves=second)
        assert svc.status is AnalysisStatus.READY
        assert svc.error is None

    def test_failed_rebuild_keeps_previous_result(self, monkeypatch, tmp_path):
        """A failed rebuild must not take working analysis away from open windows."""
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path, ({}, {})),
        )
        svc.build(tmp_path, None)
        assert svc.is_available

        def _boom(*_args, **_kwargs):
            raise RuntimeError("conversion broke")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _boom)
        with pytest.raises(RuntimeError):
            svc.build(tmp_path, None)

        assert svc.status is AnalysisStatus.FAILED
        assert svc.is_available, "previous good result was discarded"

    def test_invalidate_clears_error(self):
        svc = AnalysisService()
        svc.mark_failed("nope")
        svc.invalidate()
        assert svc.status is AnalysisStatus.IDLE
        assert svc.error is None

    def test_invalidated_inflight_build_cannot_publish_stale_result(self, monkeypatch, tmp_path):
        svc = AnalysisService()

        def _build_then_switch(*_args, **_kwargs):
            svc.invalidate()
            return MagicMock(), MagicMock(), tmp_path / "old-workspace", ({}, {})

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _build_then_switch)

        svc.build(tmp_path, None)

        assert svc.status is AnalysisStatus.IDLE
        assert not svc.is_available
        assert svc.project_dir is None


class TestBuildValidation:
    @pytest.mark.parametrize(
        ("code", "error_type", "message"),
        [
            (
                'raise TypeError("reset() requires at least one condition")',
                TypeError,
                "requires at least one condition",
            ),
            ("with rung(:", SyntaxError, "invalid syntax"),
            ("logic = object()", TypeError, "must define logic as a pyrung Program"),
        ],
    )
    def test_invalid_generated_code_remains_available_for_editing(
        self, monkeypatch, tmp_path, code, error_type, message
    ):
        source = tmp_path / "src" / "plc" / "main.py"
        source.parent.mkdir(parents=True)
        source.write_text("# existing workspace edits\n", encoding="utf-8")
        monkeypatch.setattr("clicknick.ladder.program.program_save", MagicMock())
        monkeypatch.setattr("pyrung.click.ladder_to_pyrung", lambda *_a, **_k: code)

        def generate(_csv_dir, *, output_dir, **_kwargs):
            generated_source = output_dir / "src" / "plc" / "main.py"
            generated_source.parent.mkdir(parents=True)
            generated_source.write_text(code, encoding="utf-8")

        monkeypatch.setattr("pyrung.click.ladder_to_pyrung_project", generate)
        svc = AnalysisService()

        with pytest.raises(error_type, match=message):
            svc.build(tmp_path, None, persist_dir=tmp_path)

        assert svc.status is AnalysisStatus.FAILED
        assert not svc.is_available
        assert "Traceback" in svc.error_detail
        assert svc.project_dir == tmp_path
        assert source.read_text(encoding="utf-8") == code
        assert (tmp_path / "backup" / "src" / "plc" / "main.py").read_text(
            encoding="utf-8"
        ) == "# existing workspace edits\n"

        exported = tmp_path.parent / f"{tmp_path.name}-export"
        svc.export_project(exported)
        assert (exported / "src" / "plc" / "main.py").read_text(encoding="utf-8") == code

        svc.invalidate()
        assert svc.project_dir is None

    def test_graph_failure_keeps_generated_project_available(self, monkeypatch, tmp_path):
        monkeypatch.setattr("clicknick.ladder.program.program_save", MagicMock())
        monkeypatch.setattr(
            "pyrung.click.ladder_to_pyrung",
            lambda *_a, **_k: "from pyrung import Program\nwith Program() as logic:\n    pass\n",
        )
        monkeypatch.setattr(
            Program, "dataview", MagicMock(side_effect=ValueError("unsupported instruction"))
        )
        project = tmp_path / "workspace"
        regenerate = MagicMock(return_value=project)
        monkeypatch.setattr(
            "clicknick.services.analysis_service._regenerate_persisted_project", regenerate
        )

        svc = AnalysisService()
        with pytest.raises(ValueError, match="unsupported instruction"):
            svc.build(tmp_path, None, persist_dir=project)

        regenerate.assert_called_once()
        assert svc.project_dir == project
        assert not svc.is_available

    def test_failed_codegen_does_not_expose_preexisting_folder(self, monkeypatch, tmp_path):
        monkeypatch.setattr("clicknick.ladder.program.program_save", MagicMock())
        monkeypatch.setattr("pyrung.click.ladder_to_pyrung", MagicMock(return_value="logic = None"))
        monkeypatch.setattr(
            "clicknick.services.analysis_service._regenerate_persisted_project",
            MagicMock(side_effect=ValueError("codegen failed")),
        )
        svc = AnalysisService()

        with pytest.raises(ValueError, match="codegen failed"):
            svc.build(tmp_path, None, persist_dir=tmp_path)

        assert svc.project_dir is None

    def test_invalidated_build_cannot_publish_workspace_path(self, monkeypatch, tmp_path):
        svc = AnalysisService()

        def build_then_switch(*_args, on_project_generated, **_kwargs):
            svc.invalidate()
            on_project_generated(tmp_path, ({}, {}))
            raise ValueError("old project failed")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", build_then_switch)
        with pytest.raises(ValueError, match="old project failed"):
            svc.build(tmp_path, None)

        assert svc.status is AnalysisStatus.IDLE
        assert svc.project_dir is None
        assert not svc.project_is_current
        assert svc.project_tag_to_addr_key == {}

    def test_a_rebuild_failing_after_publishing_names_tags_as_the_workspace_does(
        self, monkeypatch, tmp_path
    ):
        """When nicknames are swapped in CLICK, the workspace on disk already uses the new names."""
        ds1, ds2 = get_addr_key("DS", 1), get_addr_key("DS", 2)

        def rows(first: str, second: str) -> tuple[dict[str, int], dict[int, str]]:
            return {first: ds1, second: ds2}, {ds1: first, ds2: second}

        def build_graph(names: tuple[dict[str, int], dict[int, str]], fails: bool):
            def build(*_args, on_project_generated, **_kwargs):
                on_project_generated(tmp_path, names)
                if fails:
                    raise ValueError("graph failed")
                return MagicMock(), MagicMock(), tmp_path, names

            return build

        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            build_graph(rows("Fill", "Drain"), fails=False),
        )
        svc.build(tmp_path, None, persist_dir=tmp_path)
        assert svc.project_tag_to_addr_key["Fill"] == ds1
        assert svc.project_is_current

        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            build_graph(rows("Drain", "Fill"), fails=True),
        )
        with pytest.raises(ValueError):
            svc.build(tmp_path, None, persist_dir=tmp_path)

        assert svc.project_tag_to_addr_key["Fill"] == ds2
        assert svc.project_addr_key_to_tag[ds2] == "Fill"
        assert svc.tag_to_addr_key["Fill"] == ds1, "the graph's names stay the last good build's"
        assert svc.project_is_current

    def test_a_rebuild_failing_before_publishing_leaves_an_older_workspace(
        self, monkeypatch, tmp_path
    ):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path, ({}, {})),
        )
        svc.build(tmp_path, None, persist_dir=tmp_path)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("conversion broke")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _boom)
        with pytest.raises(RuntimeError):
            svc.build(tmp_path, None, persist_dir=tmp_path)

        assert svc.project_dir == tmp_path
        assert not svc.project_is_current

        serves = svc.mark_building()
        svc.mark_failed("selection unreadable", serves=serves)  # its build never ran
        assert not svc.project_is_current


class TestGeneration:
    """Bumped whenever the generated project folder starts being rewritten."""

    def test_starts_at_zero(self):
        assert AnalysisService().generation == 0

    def test_bumps_on_each_build_attempt(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path, ({}, {})),
        )
        svc.build(tmp_path, None)
        assert svc.generation == 1
        svc.build(tmp_path, None)
        assert svc.generation == 2

    def test_bumps_even_when_the_build_fails(self, monkeypatch, tmp_path):
        """The folder is wiped before the failure, so readers must still notice."""
        svc = AnalysisService()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _boom)
        with pytest.raises(RuntimeError):
            svc.build(tmp_path, None)
        assert svc.generation == 1


class TestProjectExport:
    @staticmethod
    def _ready_service(project_dir):
        svc = AnalysisService()
        svc._result = AnalysisResult(
            dataview=MagicMock(),
            program=MagicMock(),
            project_dir=project_dir,
        )
        svc._status = AnalysisStatus.READY
        return svc

    def test_copies_project_without_disposable_environment(self, tmp_path):
        source = tmp_path / "active"
        (source / "src" / "plc").mkdir(parents=True)
        (source / "src" / "plc" / "main.py").write_text("logic\n", encoding="utf-8")
        (source / "tests").mkdir()
        (source / "tests" / "test_logic.py").write_text("test\n", encoding="utf-8")
        (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (source / ".venv").mkdir()
        (source / ".venv" / "marker").write_text("large\n", encoding="utf-8")
        (source / "tests" / "__pycache__").mkdir()
        (source / "tests" / "__pycache__" / "test.pyc").write_bytes(b"cache")

        destination = tmp_path / "exported"
        count = self._ready_service(source).export_project(destination)

        assert count == 3
        assert (destination / "src" / "plc" / "main.py").is_file()
        assert (destination / "tests" / "test_logic.py").is_file()
        assert (destination / "pyproject.toml").is_file()
        assert not (destination / ".venv").exists()
        assert not (destination / "tests" / "__pycache__").exists()

    def test_requires_new_or_empty_destination(self, tmp_path):
        source = tmp_path / "active"
        source.mkdir()
        (source / "run.py").write_text("run\n", encoding="utf-8")
        destination = tmp_path / "existing"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("keep\n", encoding="utf-8")

        with pytest.raises(FileExistsError, match="already exists and is not empty"):
            self._ready_service(source).export_project(destination)

        assert marker.read_text(encoding="utf-8") == "keep\n"

    def test_discards_staged_copy_if_project_rebuild_starts(self, monkeypatch, tmp_path):
        source = tmp_path / "active"
        source.mkdir()
        (source / "run.py").write_text("run\n", encoding="utf-8")
        destination = tmp_path / "exported"
        svc = self._ready_service(source)
        real_copytree = shutil.copytree

        def copy_and_rebuild(*args, **kwargs):
            result = real_copytree(*args, **kwargs)
            svc._generation += 1
            return result

        monkeypatch.setattr("clicknick.services.analysis_service.shutil.copytree", copy_and_rebuild)

        with pytest.raises(RuntimeError, match="during the export, so nothing was exported"):
            svc.export_project(destination)

        assert not destination.exists()


def test_clean_generated_preserves_entire_tests_directory(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    custom_test = tests_dir / "test_interlock.py"
    custom_test.write_text("def test_interlock(): pass\n", encoding="utf-8")
    (tests_dir / "conftest.py").write_text("old fixture\n", encoding="utf-8")
    (tests_dir / "test_smoke.py").write_text("old smoke\n", encoding="utf-8")
    test_cache = tests_dir / "__pycache__"
    test_cache.mkdir()
    (test_cache / "cached.pyc").write_bytes(b"cache")
    backup_source = tmp_path / "backup" / "src" / "plc"
    backup_source.mkdir(parents=True)
    (backup_source / "main.py").write_text("proposed logic\n", encoding="utf-8")
    generated_source = tmp_path / "src" / "plc"
    generated_source.mkdir(parents=True)
    (generated_source / "main.py").write_text("old logic\n", encoding="utf-8")

    _clean_generated(tmp_path)

    assert custom_test.is_file()
    assert (tests_dir / "conftest.py").read_text(encoding="utf-8") == "old fixture\n"
    assert (tests_dir / "test_smoke.py").read_text(encoding="utf-8") == "old smoke\n"
    assert (test_cache / "cached.pyc").is_file()
    assert (backup_source / "main.py").read_text(encoding="utf-8") == "proposed logic\n"
    assert not (tmp_path / "src").exists()


def _staged_project(root, source_text: str):
    source = root / "src" / "plc"
    source.mkdir(parents=True)
    (source / "main.py").write_text(source_text, encoding="utf-8")
    (root / "project_to_csv.py").write_text("# generated\n", encoding="utf-8")
    return root


def test_dirty_source_is_snapshotted_before_click_regeneration(tmp_path):
    persist = tmp_path / "pyrung_project"
    first = _staged_project(tmp_path / "first", "generated one\n")
    _publish_generated_project(first, persist)
    (persist / "src" / "plc" / "main.py").write_text("unfinished work\n", encoding="utf-8")

    second = _staged_project(tmp_path / "second", "generated two\n")
    _publish_generated_project(second, persist)

    assert (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8") == ("generated two\n")
    assert (persist / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "unfinished work\n"


def test_edits_backed_up_by_one_save_survive_edits_backed_up_by_the_next(tmp_path):
    persist = tmp_path / "pyrung_project"
    _publish_generated_project(_staged_project(tmp_path / "first", "generated one\n"), persist)
    (persist / "src" / "plc" / "main.py").write_text("edits A, half pasted\n", encoding="utf-8")
    _publish_generated_project(_staged_project(tmp_path / "second", "generated two\n"), persist)
    # Edits B on the regenerated source, without restoring A first.
    (persist / "src" / "plc" / "main.py").write_text("edits B\n", encoding="utf-8")

    _publish_generated_project(_staged_project(tmp_path / "third", "generated three\n"), persist)

    assert (persist / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "edits B\n"
    (older,) = older_plc_backups(persist)
    assert (persist / "backup" / "older" / older / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "edits A, half pasted\n"
    assert generated_source_state_path(persist).is_file()


def test_regeneration_preserves_workspace_owned_files(tmp_path):
    persist = tmp_path / "Example Workspace"
    (persist / ".git").mkdir(parents=True)
    (persist / ".git" / "HEAD").write_text("ref: user\n", encoding="utf-8")
    (persist / "tests").mkdir()
    (persist / "tests" / "test_machine.py").write_text("user test\n", encoding="utf-8")
    (persist / "README.md").write_text("user docs\n", encoding="utf-8")
    (persist / "pyproject.toml").write_text("user config\n", encoding="utf-8")

    staged = _staged_project(tmp_path / "staged", "generated\n")
    (staged / "tests").mkdir()
    (staged / "tests" / "test_machine.py").write_text("default test\n", encoding="utf-8")
    (staged / "README.md").write_text("default docs\n", encoding="utf-8")
    (staged / "pyproject.toml").write_text("default config\n", encoding="utf-8")

    _publish_generated_project(staged, persist)

    assert (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8") == ("generated\n")
    assert (persist / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: user\n"
    assert (persist / "tests" / "test_machine.py").read_text(encoding="utf-8") == ("user test\n")
    assert (persist / "README.md").read_text(encoding="utf-8") == "user docs\n"
    assert (persist / "pyproject.toml").read_text(encoding="utf-8") == "user config\n"


_POINTER = "<!-- pyrung:guidance --> Read @AGENTS.pyrung.md first."


def _staged_guidance(path):
    staged = _staged_project(path, "generated\n")
    (staged / "AGENTS.md").write_text(f"# Machine: Line1\n\n{_POINTER}\n", encoding="utf-8")
    (staged / "AGENTS.pyrung.md").write_text("fresh guidance\n", encoding="utf-8")
    return staged


def test_regeneration_rewrites_pyrungs_guidance_and_keeps_the_users(tmp_path):
    persist = tmp_path / "Example Workspace"
    persist.mkdir()
    user = f"# Machine: Line1\n\n{_POINTER}\n\n## Notes\n\nStation 3 prox is flaky.\n"
    (persist / "AGENTS.md").write_text(user, encoding="utf-8")
    (persist / "AGENTS.pyrung.md").write_text("stale guidance\n", encoding="utf-8")

    _publish_generated_project(_staged_guidance(tmp_path / "staged"), persist)

    assert (persist / "AGENTS.md").read_text(encoding="utf-8") == user
    assert (persist / "AGENTS.pyrung.md").read_text(encoding="utf-8") == "fresh guidance\n"


def test_regeneration_puts_a_missing_pointer_back(tmp_path):
    persist = tmp_path / "Example Workspace"
    persist.mkdir()
    (persist / "AGENTS.md").write_text("My own notes.\n", encoding="utf-8")

    _publish_generated_project(_staged_guidance(tmp_path / "staged"), persist)

    assert (persist / "AGENTS.md").read_text(encoding="utf-8") == f"{_POINTER}\n\nMy own notes.\n"

    (persist / "AGENTS.md").write_text("# Line 1\n\nMy own notes.\n", encoding="utf-8")
    _publish_generated_project(_staged_guidance(tmp_path / "staged-again"), persist)
    assert (persist / "AGENTS.md").read_text(encoding="utf-8") == (
        f"# Line 1\n\n{_POINTER}\n\nMy own notes.\n"
    ), "under the user's title"


def test_guidance_written_whole_by_an_older_pyrung_moves_aside(tmp_path):
    persist = tmp_path / "Example Workspace"
    persist.mkdir()
    old = (
        "# Machine: Line1\n\n"
        "<!-- pyrung:workspace-lifecycle:start -->\n"
        "temporary guidance\n"
        "<!-- pyrung:workspace-lifecycle:end -->\n\n"
        "Edited by hand.\n"
    )
    (persist / "AGENTS.md").write_text(old, encoding="utf-8")

    staged = _staged_guidance(tmp_path / "staged")
    _publish_generated_project(staged, persist)

    assert (persist / "AGENTS.previous.md").read_text(encoding="utf-8") == old
    assert (persist / "AGENTS.md").read_text(encoding="utf-8") == (
        (staged / "AGENTS.md").read_text(encoding="utf-8")
    )


def test_an_ansi_guidance_file_does_not_stop_the_build(tmp_path):
    persist = tmp_path / "Example Workspace"
    _publish_generated_project(_staged_project(tmp_path / "first", "generated one\n"), persist)
    ansi = (
        "# Line 1\r\n\r\nOven at 180\N{DEGREE SIGN}C, caf\N{LATIN SMALL LETTER E WITH ACUTE}.\r\n"
    )
    (persist / "AGENTS.md").write_bytes(ansi.encode("cp1252"))
    staged = _staged_guidance(tmp_path / "second")
    (staged / "csv").mkdir()
    (staged / "csv" / "main.csv").write_text("rung\n", encoding="utf-8")
    (staged / "src" / "plc" / "main.py").write_text("generated two\n", encoding="utf-8")

    _publish_generated_project(staged, persist)

    assert (persist / "AGENTS.md").read_bytes() == ansi.encode("cp1252")
    assert (persist / "csv" / "main.csv").is_file()
    assert (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "generated two\n"


def test_a_guidance_file_with_a_bom_gets_the_pointer_under_its_title(tmp_path):
    persist = tmp_path / "Example Workspace"
    persist.mkdir()
    (persist / "AGENTS.md").write_bytes(b"\xef\xbb\xbf# Line 2\r\n\r\nMy own notes.\r\n")

    _publish_generated_project(_staged_guidance(tmp_path / "staged"), persist)

    assert (persist / "AGENTS.md").read_bytes() == (
        b"\xef\xbb\xbf# Line 2\r\n\r\n" + _POINTER.encode() + b"\r\n\r\nMy own notes.\r\n"
    )


def test_a_folder_that_cannot_be_copied_leaves_the_last_one(tmp_path, monkeypatch):
    """A csv/ file open in Excel used to leave the workspace with no csv/ at all."""
    persist = tmp_path / "pyrung_project"
    first = _staged_project(tmp_path / "first", "generated one\n")
    (first / "csv").mkdir()
    (first / "csv" / "main.csv").write_text("first save\n", encoding="utf-8")
    _publish_generated_project(first, persist)
    second = _staged_project(tmp_path / "second", "generated two\n")
    (second / "csv").mkdir()
    (second / "csv" / "main.csv").write_text("second save\n", encoding="utf-8")
    copytree = shutil.copytree

    def refuse_csv(source, *args, **kwargs):
        if Path(source).name == "csv":
            raise PermissionError("main.csv is open in another program")
        return copytree(source, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", refuse_csv)

    with pytest.raises(PermissionError):
        _publish_generated_project(second, persist)

    assert (persist / "csv" / "main.csv").read_text(encoding="utf-8") == "first save\n"
    assert (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8") == "generated one\n"


def _save(root: Path, label: str) -> Path:
    staged = _staged_project(root, f"{label}\n")
    (staged / "csv").mkdir()
    (staged / "csv" / "main.csv").write_text(f"{label}\n", encoding="utf-8")
    (staged / "nicknames.csv").write_text(f"{label}\n", encoding="utf-8")
    return staged


def _assert_workspace_holds(persist: Path, label: str) -> None:
    """csv/ and src/plc come from one save, recorded as its generation."""
    assert (persist / "csv" / "main.csv").read_text(encoding="utf-8") == f"{label}\n"
    assert (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8") == f"{label}\n"
    assert not plc_source_is_modified(persist)


def test_a_locked_nicknames_csv_leaves_csv_and_source_from_one_save(tmp_path, monkeypatch):
    persist = tmp_path / "pyrung_project"
    _publish_generated_project(_save(tmp_path / "first", "save 1"), persist)
    copy2 = shutil.copy2

    def refuse_nicknames(source, *args, **kwargs):
        if Path(source).name == "nicknames.csv":
            raise PermissionError("nicknames.csv is open in another program")
        return copy2(source, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", refuse_nicknames)

    with pytest.raises(PermissionError):
        _publish_generated_project(_save(tmp_path / "second", "save 2"), persist)

    _assert_workspace_holds(persist, "save 1")


def test_a_refused_source_rename_puts_csv_back_too(tmp_path, monkeypatch):
    persist = tmp_path / "pyrung_project"
    _publish_generated_project(_save(tmp_path / "first", "save 1"), persist)
    replace = Path.replace

    def refuse_source(self, target):
        if self.name == ".plc.staging":
            raise PermissionError("src/plc is in use")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", refuse_source)

    with pytest.raises(PermissionError):
        _publish_generated_project(_save(tmp_path / "second", "save 2"), persist)

    _assert_workspace_holds(persist, "save 1")
    assert sorted(path.name for path in persist.iterdir() if path.name.startswith(".")) == []
    assert sorted(path.name for path in (persist / "src").iterdir()) == ["plc"]

    monkeypatch.setattr(Path, "replace", replace)
    _publish_generated_project(_save(tmp_path / "third", "save 3"), persist)
    _assert_workspace_holds(persist, "save 3")


def test_regeneration_removes_outputs_it_no_longer_writes(tmp_path):
    persist = tmp_path / "pyrung_project"
    _publish_generated_project(_staged_project(tmp_path / "first", "generated\n"), persist)
    (persist / "csv_output").mkdir()
    (persist / "csv_output" / "main.csv").write_text("exported\n", encoding="utf-8")
    (persist / "run.py").write_text("# runner\n", encoding="utf-8")

    _publish_generated_project(_staged_project(tmp_path / "second", "generated\n"), persist)

    assert not (persist / "csv_output").exists()
    assert not (persist / "run.py").exists()
    assert (persist / "project_to_csv.py").is_file()


def test_clean_regeneration_does_not_replace_existing_recovery_snapshot(tmp_path):
    persist = tmp_path / "pyrung_project"
    first = _staged_project(tmp_path / "first", "generated one\n")
    _publish_generated_project(first, persist)
    backup_plc_source(persist)

    second = _staged_project(tmp_path / "second", "generated two\n")
    _publish_generated_project(second, persist)

    assert (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8") == ("generated two\n")
    assert (persist / "backup" / "src" / "plc" / "main.py").read_text(
        encoding="utf-8"
    ) == "generated one\n"
    assert generated_source_state_path(persist).is_file()


def test_failed_regeneration_keeps_dirty_source_in_place(tmp_path, monkeypatch):
    persist = tmp_path / "pyrung_project"
    initial = _staged_project(tmp_path / "initial", "generated\n")
    _publish_generated_project(initial, persist)
    active = persist / "src" / "plc" / "main.py"
    active.write_text("unfinished work\n", encoding="utf-8")

    def fake_program_save(_scr_folder, csv_dir, *, index):
        assert index is True
        (csv_dir / "main.csv").write_text("ladder\n", encoding="utf-8")

    def fail_generation(*_args, **_kwargs):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr("clicknick.ladder.program.program_save", fake_program_save)
    monkeypatch.setattr("pyrung.click.ladder_to_pyrung_project", fail_generation)

    with pytest.raises(RuntimeError, match="conversion failed"):
        _regenerate_persisted_project(tmp_path, None, persist, analog_inputs=frozenset())

    assert active.read_text(encoding="utf-8") == "unfinished work\n"
    assert not (persist / "backup" / "src" / "plc").exists()


def test_regeneration_publishes_the_legacy_record_and_removes_it_after_a_clean_save(
    tmp_path, monkeypatch
):
    import warnings

    from laddercodec import LegacyEncodingWarning, Program

    from clicknick.ladder.program import LEGACY_ENCODINGS_FILE, read_legacy_encodings

    stale = [True]

    def decode_program(_data):
        if stale[0]:
            warnings.warn(
                LegacyEncodingWarning(
                    "Math", "H70000", "it is stored as 16-bit and CLICK runs it as 4464.", 0
                ),
                stacklevel=2,
            )
        return Program(name="Main Program", prog_idx=1, rungs=[])

    def generate(_csv_dir, *, output_dir, **_kwargs):
        (output_dir / "src" / "plc").mkdir(parents=True)
        (output_dir / "src" / "plc" / "main.py").write_text("generated\n", encoding="utf-8")

    monkeypatch.setattr("clicknick.ladder.program.decode_program", decode_program)
    monkeypatch.setattr("clicknick.ladder.program.write_csv", lambda *_a, **_k: None)
    monkeypatch.setattr("pyrung.click.ladder_to_pyrung_project", generate)
    scr = tmp_path / "scr"
    scr.mkdir()
    (scr / "Scr1.tmp").write_bytes(b"scr")
    persist = tmp_path / "pyrung_project"

    _regenerate_persisted_project(scr, None, persist, analog_inputs=frozenset())

    record = persist / "csv" / LEGACY_ENCODINGS_FILE
    assert [item.rung for item in read_legacy_encodings(persist / "csv")] == [1]

    stale[0] = False  # CLICK saved a clean copy
    _regenerate_persisted_project(scr, None, persist, analog_inputs=frozenset())

    assert not record.exists()


def test_build_with_a_rung_laddercodec_cannot_read_publishes_the_rest(tmp_path, monkeypatch):
    """The build used to stop when write_csv refused a rung, and the workspace went stale."""
    from laddercodec import Coil, Program, Rung, UnknownCondition

    from clicknick.ladder.program import STAND_IN_COMMENT, read_legacy_encodings

    def _rung(output: str, first: object = "-") -> Rung:
        conditions = [first, *["-"] * 30]
        return Rung([conditions], [Coil(output)], None)

    rungs = [_rung("C1"), _rung("C2", UnknownCondition(raw=b"Compare")), _rung("C3")]
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, rungs),
    )
    monkeypatch.setattr("clicknick.services.analysis_service._channel_inputs", lambda _s: [])
    scr = tmp_path / "scr"
    scr.mkdir()
    (scr / "Scr1.tmp").write_bytes(b"scr")
    persist = tmp_path / "pyrung_project"
    svc = AnalysisService()

    assert svc.build(scr, None, persist_dir=persist)

    assert svc.status is AnalysisStatus.READY
    assert [(item.rung, item.unreadable) for item in read_legacy_encodings(persist / "csv")] == [
        (2, True)
    ]
    main = (persist / "src" / "plc" / "main.py").read_text(encoding="utf-8")
    assert STAND_IN_COMMENT in main
    assert "out(C3)" in main


@pytest.mark.parametrize(
    "row",
    [
        AddressRow("Y", 1, nickname="Motor", comment="Max 50\u00b0C"),
        AddressRow("Y", 1, nickname="Caf\u00e9"),
    ],
    ids=["comment with a degree sign", "nickname with an e-acute"],
)
def test_the_workspace_builds_from_a_nickname_or_comment_outside_ascii(
    tmp_path, monkeypatch, row
) -> None:
    """pyrung reads the workspace's nickname CSV as UTF-8, so ClickNick writes it as UTF-8."""
    import typing

    from laddercodec import Coil, Contact, Rung, write_csv

    contact_type = typing.get_type_hints(Contact)["type"]

    def fake_program_save(_scr_folder, csv_dir, *, index):
        rung = Rung(
            logical_rows=1,
            conditions=[["-"] * 31],
            instructions=[Coil(contact_type.COIL_OUT, "Y001")],
            comment=None,
        )
        write_csv(csv_dir / "main.csv", [rung], index=index)

    monkeypatch.setattr("clicknick.ladder.program.program_save", fake_program_save)
    persist = tmp_path / "workspace"

    _regenerate_persisted_project(tmp_path, {1: row}, persist, analog_inputs=frozenset())

    nicknames = persist / "csv" / "nicknames.csv"
    assert row.nickname in nicknames.read_text(encoding="utf-8")


def test_every_row_click_cannot_hold_is_listed_before_the_nickname_csv_is_written(
    tmp_path,
) -> None:
    rows = {
        1: AddressRow("Y", 1, nickname="Motor", comment="a→b"),
        2: AddressRow("Y", 2, nickname="PumpЖ"),
        3: AddressRow("Y", 3, nickname="Fine"),
    }

    with pytest.raises(ValueError) as caught:
        _write_nicknames_csv(tmp_path, rows)

    assert str(caught.value) == (
        "Y001's comment has '→', which CLICK cannot hold.\n"
        "Y002's nickname has 'Ж', which CLICK cannot hold.\n"
        "Change the characters in the Address Editor and Sync."
    )
    assert not (tmp_path / "nicknames.csv").exists()


def test_the_nickname_csv_error_lists_ten_rows_and_counts_the_rest(tmp_path) -> None:
    rows = {i: AddressRow("DS", i, nickname=f"Tag{i}→") for i in range(1, 14)}

    with pytest.raises(ValueError) as caught:
        _write_nicknames_csv(tmp_path, rows)

    lines = str(caught.value).splitlines()
    assert len(lines) == 12
    assert lines[10] == "and 3 more."
