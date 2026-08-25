"""Tests for AnalysisService — mapping and query methods.

The full pipeline (Scr*.tmp → pyrung → graph) requires real ladder files,
so these tests focus on the mapping and query layers using a mock graph.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from clicknick.services.analysis_service import (
    AnalysisResult,
    AnalysisService,
    AnalysisStatus,
    _build_tag_addr_key_map,
    _clean_generated,
)


@dataclass(frozen=True)
class FakeRow:
    nickname: str = ""
    display_address: str = ""


class TestBuildTagAddrKeyMap:
    def test_maps_nicknames(self):
        base = {
            100: FakeRow(nickname="MotorOut", display_address="Y001"),
            200: FakeRow(nickname="PumpRun", display_address="Y002"),
        }
        tag_to_key, key_to_tag = _build_tag_addr_key_map(base)
        assert tag_to_key == {"MotorOut": 100, "PumpRun": 200}
        assert key_to_tag == {100: "MotorOut", 200: "PumpRun"}

    def test_empty_nickname_falls_back_to_display_address(self):
        base = {100: FakeRow(nickname="", display_address="X001")}
        tag_to_key, key_to_tag = _build_tag_addr_key_map(base)
        assert tag_to_key == {"X001": 100}
        assert key_to_tag == {100: "X001"}

    def test_whitespace_nickname_treated_as_empty(self):
        base = {100: FakeRow(nickname="  ", display_address="X001")}
        tag_to_key, key_to_tag = _build_tag_addr_key_map(base)
        assert tag_to_key == {"X001": 100}

    def test_empty_state(self):
        tag_to_key, key_to_tag = _build_tag_addr_key_map({})
        assert tag_to_key == {}
        assert key_to_tag == {}


def _make_service_with_mock_graph(
    tag_roles: dict[str, str],
    tag_to_addr_key: dict[str, int],
    upstream: dict[str, frozenset[str]] | None = None,
    downstream: dict[str, frozenset[str]] | None = None,
) -> AnalysisService:
    """Create an AnalysisService with a mock ProgramGraph."""
    from pyrung.core.analysis.pdg import TagRole

    role_map = {
        "input": TagRole.INPUT,
        "terminal": TagRole.TERMINAL,
        "pivot": TagRole.PIVOT,
        "isolated": TagRole.ISOLATED,
    }

    graph = MagicMock()
    graph.tag_roles = {tag: role_map[role] for tag, role in tag_roles.items()}
    graph.upstream_slice = lambda t: (upstream or {}).get(t, frozenset())
    graph.downstream_slice = lambda t: (downstream or {}).get(t, frozenset())

    addr_key_to_tag = {v: k for k, v in tag_to_addr_key.items()}

    svc = AnalysisService()
    svc._result = AnalysisResult(
        graph=graph,
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

    def test_rebuild_mapping(self):
        svc = _make_service_with_mock_graph(
            tag_roles={"OldName": "input"},
            tag_to_addr_key={"OldName": 100},
        )
        assert svc.get_role_keys("input") == {100}

        svc.rebuild_mapping({100: FakeRow(nickname="NewName", display_address="X001")})
        assert svc._result.tag_to_addr_key == {"NewName": 100}
        assert svc._result.role_cache == {}


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
            svc.build(tmp_path, None, {})

        assert svc.status is AnalysisStatus.FAILED
        assert svc.error == "ValueError: bad rung"
        assert "bad rung" in (svc.error_detail or "")
        assert not svc.is_available

    def test_build_success_is_ready(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path),
        )
        svc.build(tmp_path, None, {100: FakeRow(nickname="A", display_address="X001")})
        assert svc.status is AnalysisStatus.READY
        assert svc.error is None
        assert svc.is_available

    def test_failed_rebuild_keeps_previous_result(self, monkeypatch, tmp_path):
        """A failed rebuild must not take working analysis away from open windows."""
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path),
        )
        svc.build(tmp_path, None, {100: FakeRow(nickname="A", display_address="X001")})
        assert svc.is_available

        def _boom(*_args, **_kwargs):
            raise RuntimeError("conversion broke")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _boom)
        with pytest.raises(RuntimeError):
            svc.build(tmp_path, None, {})

        assert svc.status is AnalysisStatus.FAILED
        assert svc.is_available, "previous good result was discarded"

    def test_invalidate_clears_error(self):
        svc = AnalysisService()
        svc.mark_failed("nope")
        svc.invalidate()
        assert svc.status is AnalysisStatus.IDLE
        assert svc.error is None


class TestGeneration:
    """Bumped whenever the generated project folder starts being rewritten."""

    def test_starts_at_zero(self):
        assert AnalysisService().generation == 0

    def test_bumps_on_each_build_attempt(self, monkeypatch, tmp_path):
        svc = AnalysisService()
        monkeypatch.setattr(
            "clicknick.services.analysis_service._build_graph",
            lambda *_a, **_k: (MagicMock(), MagicMock(), tmp_path),
        )
        svc.build(tmp_path, None, {})
        assert svc.generation == 1
        svc.build(tmp_path, None, {})
        assert svc.generation == 2

    def test_bumps_even_when_the_build_fails(self, monkeypatch, tmp_path):
        """The folder is wiped before the failure, so readers must still notice."""
        svc = AnalysisService()

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("clicknick.services.analysis_service._build_graph", _boom)
        with pytest.raises(RuntimeError):
            svc.build(tmp_path, None, {})
        assert svc.generation == 1


class TestProjectExport:
    @staticmethod
    def _ready_service(project_dir):
        svc = AnalysisService()
        svc._result = AnalysisResult(
            graph=MagicMock(),
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

        with pytest.raises(FileExistsError, match="must be empty"):
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

        with pytest.raises(RuntimeError, match="changed during export"):
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
    generated_source = tmp_path / "src" / "plc"
    generated_source.mkdir(parents=True)
    (generated_source / "main.py").write_text("old logic\n", encoding="utf-8")

    _clean_generated(tmp_path)

    assert custom_test.is_file()
    assert (tests_dir / "conftest.py").read_text(encoding="utf-8") == "old fixture\n"
    assert (tests_dir / "test_smoke.py").read_text(encoding="utf-8") == "old smoke\n"
    assert (test_cache / "cached.pyc").is_file()
    assert not (tmp_path / "src").exists()
