"""Header and wire-topology helpers for Click clipboard buffers.

This module captures reverse-engineered offsets for the fixed-size 64-byte
cell layout and the 0x0254 header entry table.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Header table (32 entries x 64 bytes) ---
HEADER_ENTRY_BASE = 0x0254
HEADER_ENTRY_SIZE = 0x40
HEADER_ENTRY_COUNT = 32

# Entry-local offsets
HEADER_COLUMN_INDEX_OFFSET = 0x0C  # little-endian dword: column index
HEADER_VOLATILE_BYTE_OFFSETS = (0x05, 0x11)  # capture-volatile, non-structural

# First header entry word (+0x00/+0x01, little-endian) carries logical row count.
# Historical 1-byte classes 0x40/0x60/0x80 remain for 1..3 rows.
HEADER_ROW_CLASS_OFFSET = 0x00
HEADER_ROW_WORD_OFFSET = 0x00
HEADER_ROW_CLASS_TO_COUNT = {
    0x40: 1,
    0x60: 2,
    0x80: 3,
}
HEADER_ROW_WORD_STRIDE = 0x20

# --- Grid/cell layout ---
GRID_FIRST_ROW_START = 0x0A60
CELL_SIZE = 0x40
COLS_PER_ROW = 32
GRID_ROW_STRIDE = CELL_SIZE * COLS_PER_ROW  # 0x800

# Cell-local topology flag offsets
CELL_HORIZONTAL_LEFT_OFFSET = 0x19
CELL_HORIZONTAL_RIGHT_OFFSET = 0x1D
CELL_VERTICAL_DOWN_OFFSET = 0x21


@dataclass(frozen=True)
class CellWireFlags:
    horizontal_left: bool
    horizontal_right: bool
    vertical_down: bool

    @property
    def any(self) -> bool:
        return self.horizontal_left or self.horizontal_right or self.vertical_down


@dataclass(frozen=True)
class WireCellTopology:
    row: int
    column: int
    flags: CellWireFlags


@dataclass(frozen=True)
class WireTopology:
    row_count: int
    column_count: int
    cells: tuple[WireCellTopology, ...]

    def flags_at(self, row: int, column: int) -> CellWireFlags | None:
        for cell in self.cells:
            if cell.row == row and cell.column == column:
                return cell.flags
        return None


def header_entry_slice(column: int) -> slice:
    if not (0 <= column < HEADER_ENTRY_COUNT):
        raise ValueError(f"Column out of range: {column}")
    start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
    return slice(start, start + HEADER_ENTRY_SIZE)


def extract_header_entries(data: bytes) -> tuple[bytes, ...]:
    entries: list[bytes] = []
    for column in range(HEADER_ENTRY_COUNT):
        s = header_entry_slice(column)
        if s.stop > len(data):
            break
        entries.append(data[s])
    return tuple(entries)


def normalize_header_entry(entry: bytes) -> bytes:
    if len(entry) != HEADER_ENTRY_SIZE:
        raise ValueError(f"Header entry must be {HEADER_ENTRY_SIZE} bytes; got {len(entry)}")
    out = bytearray(entry)
    for off in HEADER_VOLATILE_BYTE_OFFSETS:
        out[off] = 0
    return bytes(out)


def normalized_header_entries(data: bytes) -> tuple[bytes, ...]:
    return tuple(normalize_header_entry(entry) for entry in extract_header_entries(data))


def header_structural_equal(left: bytes, right: bytes) -> bool:
    return normalized_header_entries(left) == normalized_header_entries(right)


def header_row_class(data: bytes) -> int | None:
    if HEADER_ENTRY_BASE + HEADER_ROW_CLASS_OFFSET >= len(data):
        return None
    return data[HEADER_ENTRY_BASE + HEADER_ROW_CLASS_OFFSET]


def header_row_word(data: bytes) -> int | None:
    start = HEADER_ENTRY_BASE + HEADER_ROW_WORD_OFFSET
    if start + 1 >= len(data):
        return None
    return data[start] | (data[start + 1] << 8)


def logical_row_count_from_header_word(data: bytes) -> int | None:
    row_word = header_row_word(data)
    if row_word is None:
        return None
    if row_word < 0x40 or row_word % HEADER_ROW_WORD_STRIDE != 0:
        return None
    logical_rows = row_word // HEADER_ROW_WORD_STRIDE - 1
    if logical_rows <= 0:
        return None
    return logical_rows


def logical_row_count_from_header(data: bytes) -> int | None:
    from_word = logical_row_count_from_header_word(data)
    if from_word is not None:
        return from_word
    row_class = header_row_class(data)
    if row_class is None:
        return None
    return HEADER_ROW_CLASS_TO_COUNT.get(row_class)


def available_row_count(data: bytes) -> int:
    if len(data) < GRID_FIRST_ROW_START + GRID_ROW_STRIDE:
        return 0
    return (len(data) - GRID_FIRST_ROW_START) // GRID_ROW_STRIDE


def logical_row_count(data: bytes) -> int:
    available = available_row_count(data)
    if available == 0:
        return 0

    inferred = logical_row_count_from_header(data)
    if inferred is None:
        return available
    return min(inferred, available)


def cell_offset(row: int, column: int) -> int:
    if row < 0:
        raise ValueError(f"Row must be >= 0; got {row}")
    if not (0 <= column < COLS_PER_ROW):
        raise ValueError(f"Column out of range: {column}")
    return GRID_FIRST_ROW_START + row * GRID_ROW_STRIDE + column * CELL_SIZE


def read_cell(data: bytes, row: int, column: int) -> bytes:
    start = cell_offset(row, column)
    end = start + CELL_SIZE
    if end > len(data):
        raise IndexError(f"Cell row={row} col={column} is outside buffer (len={len(data)})")
    return data[start:end]


def parse_cell_flags(cell: bytes) -> CellWireFlags:
    if len(cell) != CELL_SIZE:
        raise ValueError(f"Cell must be {CELL_SIZE} bytes; got {len(cell)}")
    return CellWireFlags(
        horizontal_left=cell[CELL_HORIZONTAL_LEFT_OFFSET] != 0,
        horizontal_right=cell[CELL_HORIZONTAL_RIGHT_OFFSET] != 0,
        vertical_down=cell[CELL_VERTICAL_DOWN_OFFSET] != 0,
    )


def parse_wire_topology(
    data: bytes,
    *,
    include_empty: bool = False,
    row_count: int | None = None,
) -> WireTopology:
    rows = logical_row_count(data) if row_count is None else row_count
    if rows < 0:
        raise ValueError(f"row_count must be >= 0; got {rows}")

    cells: list[WireCellTopology] = []
    for row in range(rows):
        for column in range(COLS_PER_ROW):
            cell = read_cell(data, row, column)
            flags = parse_cell_flags(cell)
            if include_empty or flags.any:
                cells.append(WireCellTopology(row=row, column=column, flags=flags))

    return WireTopology(
        row_count=rows,
        column_count=COLS_PER_ROW,
        cells=tuple(cells),
    )
