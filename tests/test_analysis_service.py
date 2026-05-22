"""Tests for AnalysisService — mapping and query methods.

The full pipeline (Scr*.tmp → pyrung → graph) requires real ladder files,
so these tests focus on the mapping and query layers using a mock graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from clicknick.services.analysis_service import (
    AnalysisResult,
    AnalysisService,
    _build_tag_addr_key_map,
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
