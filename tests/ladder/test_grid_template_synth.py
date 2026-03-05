import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from devtools.grid_template_synth import synthesize_from_template

from clicknick.ladder.codec import BUFFER_SIZE
from clicknick.ladder.topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    HEADER_ENTRY_BASE,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    cell_offset,
)


def _header_offset(col: int, rel: int) -> int:
    return HEADER_ENTRY_BASE + col * HEADER_ENTRY_SIZE + rel


def _flag_tuple(data: bytes, row: int, col: int) -> tuple[int, int, int]:
    start = cell_offset(row, col)
    return (
        data[start + CELL_HORIZONTAL_LEFT_OFFSET],
        data[start + CELL_HORIZONTAL_RIGHT_OFFSET],
        data[start + CELL_VERTICAL_DOWN_OFFSET],
    )


def test_synthesizes_horizontal_wires_from_single_row() -> None:
    template = bytearray(BUFFER_SIZE)
    # Ensure clear behavior is deterministic.
    stale_cell = cell_offset(0, 5)
    template[stale_cell + CELL_HORIZONTAL_LEFT_OFFSET] = 1
    template[stale_cell + CELL_HORIZONTAL_RIGHT_OFFSET] = 1
    template[stale_cell + CELL_VERTICAL_DOWN_OFFSET] = 1

    out = synthesize_from_template(bytes(template), rows=["R,-,-,...,:,..."])

    assert out[HEADER_ENTRY_BASE] == 0x40
    assert _flag_tuple(out, 0, 0) == (1, 1, 0)
    assert _flag_tuple(out, 0, 1) == (1, 1, 0)
    assert _flag_tuple(out, 0, 2) == (0, 0, 0)
    assert _flag_tuple(out, 0, 5) == (0, 0, 0)
    assert _flag_tuple(out, 1, 0) == (0, 0, 0)


def test_synthesizes_junction_and_vertical_tokens_and_sets_two_row_class() -> None:
    template = bytes(BUFFER_SIZE)
    out = synthesize_from_template(
        template,
        rows=[
            "R,T,|,...,:,...",
            ",...,:,...",
        ],
    )

    assert out[HEADER_ENTRY_BASE] == 0x60
    assert _flag_tuple(out, 0, 0) == (1, 1, 1)
    assert _flag_tuple(out, 0, 1) == (0, 0, 1)
    assert _flag_tuple(out, 0, 2) == (0, 0, 0)
    assert _flag_tuple(out, 1, 0) == (0, 0, 0)


def test_header_copy_only_touches_selected_offsets() -> None:
    template = bytearray(BUFFER_SIZE)
    donor = bytearray(BUFFER_SIZE)
    template[0x0A59] = 0xAA
    donor[0x0A59] = 0x11
    for col in range(HEADER_ENTRY_COUNT):
        template[_header_offset(col, 0x05)] = 0xA0
        template[_header_offset(col, 0x11)] = 0xB1
        template[_header_offset(col, 0x17)] = 0xC2
        template[_header_offset(col, 0x18)] = 0xD3

        donor[_header_offset(col, 0x05)] = 0x10 + col
        donor[_header_offset(col, 0x11)] = 0x20 + col
        donor[_header_offset(col, 0x17)] = 0x30 + col
        donor[_header_offset(col, 0x18)] = 0x40 + col

    out = synthesize_from_template(
        bytes(template),
        rows=["R,...,:,..."],
        donor=bytes(donor),
        header_copy_offsets=(0x11, 0x17),
    )

    for col in range(HEADER_ENTRY_COUNT):
        assert out[_header_offset(col, 0x11)] == donor[_header_offset(col, 0x11)]
        assert out[_header_offset(col, 0x17)] == donor[_header_offset(col, 0x17)]
        assert out[_header_offset(col, 0x05)] == template[_header_offset(col, 0x05)]
        assert out[_header_offset(col, 0x18)] == template[_header_offset(col, 0x18)]
    assert out[0x0A59] == 0xAA


def test_rejects_non_wire_condition_tokens() -> None:
    with pytest.raises(ValueError, match="unsupported condition token"):
        synthesize_from_template(bytes(BUFFER_SIZE), rows=["R,X001,...,:,..."])
