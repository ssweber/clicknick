"""Tests for clicknick.ladder.topology."""

from clicknick.ladder.codec import BUFFER_SIZE, ClickCodec
from clicknick.ladder.topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    HEADER_COLUMN_INDEX_OFFSET,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    HEADER_ROW_CLASS_TO_COUNT,
    CellWireFlags,
    cell_offset,
    header_entry_slice,
    header_structural_equal,
    parse_wire_topology,
)


def _buffer_with_header(*, size: int = BUFFER_SIZE, row_class: int = 0x40) -> bytearray:
    data = bytearray(size)
    for column in range(HEADER_ENTRY_COUNT):
        entry = bytearray(HEADER_ENTRY_SIZE)
        entry[HEADER_COLUMN_INDEX_OFFSET : HEADER_COLUMN_INDEX_OFFSET + 4] = column.to_bytes(
            4, "little"
        )
        if column == 0:
            entry[0] = row_class
        data[header_entry_slice(column)] = entry
    return data


def test_header_structural_equal_masks_volatile_bytes() -> None:
    left = _buffer_with_header()
    right = bytearray(left)

    for column in range(HEADER_ENTRY_COUNT):
        start = header_entry_slice(column).start
        right[start + 0x05] = (column * 7 + 1) & 0xFF
        right[start + 0x11] = (column * 11 + 3) & 0xFF

    assert header_structural_equal(bytes(left), bytes(right))

    # Changing a non-volatile byte should break structural equality.
    start = header_entry_slice(3).start
    right[start + HEADER_COLUMN_INDEX_OFFSET] ^= 0x01
    assert not header_structural_equal(bytes(left), bytes(right))


def test_parse_wire_topology_horizontal_and_vertical_flags() -> None:
    data = _buffer_with_header(row_class=0x60)  # logical 2-row rung

    row0_col0 = cell_offset(0, 0)
    data[row0_col0 + CELL_HORIZONTAL_LEFT_OFFSET] = 0x01
    data[row0_col0 + CELL_HORIZONTAL_RIGHT_OFFSET] = 0x01

    row0_col1 = cell_offset(0, 1)
    data[row0_col1 + CELL_VERTICAL_DOWN_OFFSET] = 0x01

    row1_col1 = cell_offset(1, 1)
    data[row1_col1 + CELL_HORIZONTAL_LEFT_OFFSET] = 0x01
    data[row1_col1 + CELL_HORIZONTAL_RIGHT_OFFSET] = 0x01

    topology = parse_wire_topology(bytes(data))

    assert topology.row_count == 2
    assert topology.column_count == 32
    assert topology.flags_at(0, 0) == CellWireFlags(
        horizontal_left=True,
        horizontal_right=True,
        vertical_down=False,
    )
    assert topology.flags_at(0, 1) == CellWireFlags(
        horizontal_left=False,
        horizontal_right=False,
        vertical_down=True,
    )
    assert topology.flags_at(1, 1) == CellWireFlags(
        horizontal_left=True,
        horizontal_right=True,
        vertical_down=False,
    )
    assert topology.flags_at(0, 2) is None


def test_parse_wire_topology_uses_header_row_class() -> None:
    # 12288 bytes can hold 4 row blocks from GRID_FIRST_ROW_START, but the
    # header row class still advertises a logical 3-row rung.
    data = _buffer_with_header(size=12288, row_class=0x80)
    assert HEADER_ROW_CLASS_TO_COUNT[0x80] == 3

    row2_col1 = cell_offset(2, 1)
    data[row2_col1 + CELL_VERTICAL_DOWN_OFFSET] = 0x01

    topology = parse_wire_topology(bytes(data))
    assert topology.row_count == 3
    assert topology.flags_at(2, 1) == CellWireFlags(
        horizontal_left=False,
        horizontal_right=False,
        vertical_down=True,
    )


def test_codec_decode_wire_topology_helper() -> None:
    data = _buffer_with_header(row_class=0x40)
    row0_col3 = cell_offset(0, 3)
    data[row0_col3 + CELL_VERTICAL_DOWN_OFFSET] = 0x01

    topology = ClickCodec().decode_wire_topology(bytes(data))
    assert topology.row_count == 1
    assert topology.flags_at(0, 3) == CellWireFlags(
        horizontal_left=False,
        horizontal_right=False,
        vertical_down=True,
    )
