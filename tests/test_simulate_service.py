"""Tests for SimulateService address mapping."""

from __future__ import annotations

from clicknick.services.simulate_service import (
    SimulateResult,
    _build_address_map,
)


class TestBuildAddressMap:
    def test_builds_bidirectional_map(self):
        nickname_map = {
            "X001": "Motor_Start",
            "DS100": "Counter_1",
        }
        tag_to_addr, addr_to_tag = _build_address_map(nickname_map)

        assert tag_to_addr["Motor_Start"] == "X001"
        assert tag_to_addr["Counter_1"] == "DS100"
        assert addr_to_tag["X001"] == "Motor_Start"
        assert addr_to_tag["DS100"] == "Counter_1"

    def test_addresses_uppercased(self):
        nickname_map = {"x001": "Motor"}
        tag_to_addr, addr_to_tag = _build_address_map(nickname_map)

        assert tag_to_addr["Motor"] == "X001"
        assert addr_to_tag["X001"] == "Motor"

    def test_empty_nickname_map(self):
        tag_to_addr, addr_to_tag = _build_address_map(None)
        assert tag_to_addr == {}
        assert addr_to_tag == {}

    def test_empty_nicknames_skipped(self):
        nickname_map = {"X001": "", "X002": "Motor"}
        tag_to_addr, addr_to_tag = _build_address_map(nickname_map)

        assert "Motor" in tag_to_addr
        assert len(tag_to_addr) == 1

    def test_nicknames_mapped_verbatim(self):
        """pyrung keys DAP tags by the raw nickname, spaces and all."""
        nickname_map = {"X001": "Motor Start!", "DS100": "1st Pump"}
        tag_to_addr, addr_to_tag = _build_address_map(nickname_map)

        assert tag_to_addr["Motor Start!"] == "X001"
        assert tag_to_addr["1st Pump"] == "DS100"
        assert addr_to_tag["X001"] == "Motor Start!"
        assert addr_to_tag["DS100"] == "1st Pump"


class TestSimulateResult:
    def test_dataclass_fields(self):
        from pathlib import Path

        result = SimulateResult(
            project_dir=Path("test/project"),
            csv_dir=Path("test/csv"),
            file_count=5,
            tag_to_address={"Motor": "X001"},
            address_to_tag={"X001": "Motor"},
        )
        assert result.file_count == 5
        assert result.tag_to_address["Motor"] == "X001"
