"""Tests for the scoped ladder codec compatibility shim."""

from __future__ import annotations

import importlib

import pytest

from clicknick.ladder.codec import (
    BUFFER_SIZE,
    CELL_SIZE,
    ClickCodec,
    EncodeResult,
    HeaderSeed,
    V2UnsupportedShapeError,
)
from clicknick.ladder.model import RungGrid
from clicknick.ladder.topology import (
    CELL_HORIZONTAL_RIGHT_OFFSET,
    HEADER_ENTRY_BASE,
    cell_offset,
    parse_wire_topology,
)


def test_package_imports_without_deleted_modules() -> None:
    importlib.import_module("clicknick.ladder")
    importlib.import_module("clicknick.ladder.capture_cli")
    importlib.import_module("clicknick.ladder.capture_workflow")


@pytest.mark.parametrize(
    ("rows", "expected_row_count"),
    [
        (["R,...,:,..."], 1),
        (["R,->,:,..."], 1),
        (["R,->,:,NOP"], 1),
        (["#,Hello", "R,...,:,..."], 1),
        (["R,,T,...,:,...", ",,-,...,:,..."], 2),
    ],
)
def test_encode_rows_strict_supports_scoped_surface(
    rows: list[str],
    expected_row_count: int,
) -> None:
    result = ClickCodec().encode_rows(rows, return_metadata=True)

    assert isinstance(result, EncodeResult)
    assert len(result.payload) == BUFFER_SIZE
    assert parse_wire_topology(result.payload).row_count == expected_row_count


def test_encode_rows_strict_rejects_instruction_shorthand() -> None:
    with pytest.raises(V2UnsupportedShapeError, match="unsupported_condition"):
        ClickCodec().encode_rows(["R,X001,->,:,out(Y001)"], mode="strict")


def test_encode_rows_relaxed_degrades_condition_and_af_tokens() -> None:
    result = ClickCodec().encode_rows(
        ["R,X001,->,:,out(Y001)"],
        mode="relaxed",
        return_metadata=True,
    )

    assert isinstance(result, EncodeResult)
    assert result.report is not None
    assert result.report.degraded is True
    assert [issue.kind for issue in result.report.degradations] == ["condition", "af"]

    topology = parse_wire_topology(result.payload)
    flags = topology.flags_at(0, 0)
    assert flags is not None
    assert flags.horizontal_left is True
    assert flags.horizontal_right is True
    assert flags.vertical_down is False

    af_cell = cell_offset(0, 31)
    assert result.payload[af_cell + CELL_HORIZONTAL_RIGHT_OFFSET] == 1


def test_encode_rows_applies_header_seed_after_scoped_encode() -> None:
    seed = HeaderSeed(profile_05=0x21, profile_11=0x42, family_17=0x58, family_18=0x01)
    payload = ClickCodec().encode_rows(
        ["R,...,:,..."],
        header_seed=seed,
    )

    for column in range(32):
        entry_start = HEADER_ENTRY_BASE + column * CELL_SIZE
        assert payload[entry_start + 0x05] == 0x21
        assert payload[entry_start + 0x11] == 0x42
        assert payload[entry_start + 0x17] == 0x58
        assert payload[entry_start + 0x18] == 0x01
    assert payload[0x0A59] == 0x21


def test_direct_runggrid_encode_still_uses_legacy_codec() -> None:
    codec = ClickCodec()
    grid = RungGrid.from_csv("X001,->,:,out(Y001)")

    payload = codec.encode(grid)
    decoded = codec.decode(payload)

    assert decoded.to_csv() == "X001,->,:,out(Y001)"


def test_decode_wire_topology_matches_parser() -> None:
    payload = ClickCodec().encode_rows(["R,->,:,..."])
    assert ClickCodec().decode_wire_topology(payload) == parse_wire_topology(payload)
