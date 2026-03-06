"""Deterministic empty multi-row payload synthesis for the validated empty lane.

This encoder targets the empty-rung family validated in March 2026:
- header row word at entry0 (+0x00/+0x01) follows (rows + 1) * 0x20;
- payload length scales by 0x1000 pages;
- header +0x05 and trailer 0x0A59 are zeroed for this lane;
- active-cell offsets follow deterministic row/column formulas.
"""

from __future__ import annotations

from importlib import resources

from .topology import (
    CELL_SIZE,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    GRID_ROW_STRIDE,
    HEADER_ENTRY_BASE,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    cell_offset,
)

EMPTY_MULTIROW_MIN_ROWS = 1
EMPTY_MULTIROW_MAX_ROWS = 32
EMPTY_MULTIROW_PAGE_SIZE = 0x1000
EMPTY_MULTIROW_TRAILER_OFFSET = 0x0A59
EMPTY_MULTIROW_HEADER_PROFILE_05_OFFSET = 0x05
EMPTY_MULTIROW_ROW_WORD_STRIDE = 0x20
EMPTY_MULTIROW_TEMPLATE_RESOURCE = "resources/empty_multirow_rule_minimal.scaffold.bin"


def _validate_rows(logical_rows: int) -> None:
    if not isinstance(logical_rows, int):
        raise TypeError(f"logical_rows must be int; got {type(logical_rows).__name__}")
    if not (EMPTY_MULTIROW_MIN_ROWS <= logical_rows <= EMPTY_MULTIROW_MAX_ROWS):
        raise ValueError(
            f"logical_rows must be in [{EMPTY_MULTIROW_MIN_ROWS}, {EMPTY_MULTIROW_MAX_ROWS}], "
            f"got {logical_rows}"
        )


def _validate_u8(name: str, value: int) -> None:
    if not isinstance(value, int) or not (0x00 <= value <= 0xFF):
        raise ValueError(f"{name} must be an 8-bit integer, got {value!r}")


def _load_template() -> bytes:
    data = (
        resources.files("clicknick.ladder")
        .joinpath(EMPTY_MULTIROW_TEMPLATE_RESOURCE)
        .read_bytes()
    )
    if len(data) < GRID_FIRST_ROW_START + GRID_ROW_STRIDE:
        raise ValueError(f"Empty multi-row template is too short: {len(data)} bytes")
    return data


def empty_multirow_payload_length(logical_rows: int) -> int:
    """Return lane-validated payload length for a logical empty row count."""
    _validate_rows(logical_rows)
    return EMPTY_MULTIROW_PAGE_SIZE * (((logical_rows + 1) // 2) + 1)


def empty_multirow_row_word(logical_rows: int) -> int:
    """Return header row word (entry0 +0x00/+0x01, little-endian)."""
    _validate_rows(logical_rows)
    return (logical_rows + 1) * EMPTY_MULTIROW_ROW_WORD_STRIDE


def synthesize_empty_multirow(
    logical_rows: int,
    *,
    template: bytes | None = None,
    set_cell_0b: bool = False,
    cell_0b_value: int = 0x40,
    set_terminal_15: bool = False,
    terminal_15_value: int = 0x01,
) -> bytes:
    """Build a deterministic empty multi-row payload for the validated empty family.

    Optional toggles `set_cell_0b` and `set_terminal_15` are provided for controlled
    family probing. The default rule-minimal path leaves those bytes zeroed.
    """
    _validate_rows(logical_rows)
    _validate_u8("cell_0b_value", cell_0b_value)
    _validate_u8("terminal_15_value", terminal_15_value)

    template_bytes = template if template is not None else _load_template()
    if len(template_bytes) < GRID_FIRST_ROW_START + GRID_ROW_STRIDE:
        raise ValueError(f"template payload too short ({len(template_bytes)} bytes)")

    payload_len = empty_multirow_payload_length(logical_rows)
    out = bytearray(payload_len)
    copy_len = min(len(template_bytes), payload_len)
    out[:copy_len] = template_bytes[:copy_len]
    out[:8] = b"CLICK   "

    # Keep header table deterministic for this lane.
    row_word = empty_multirow_row_word(logical_rows)
    out[HEADER_ENTRY_BASE + 0x00] = row_word & 0xFF
    out[HEADER_ENTRY_BASE + 0x01] = (row_word >> 8) & 0xFF
    for column in range(HEADER_ENTRY_COUNT):
        entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
        out[entry_start + EMPTY_MULTIROW_HEADER_PROFILE_05_OFFSET] = 0x00
    if EMPTY_MULTIROW_TRAILER_OFFSET < len(out):
        out[EMPTY_MULTIROW_TRAILER_OFFSET] = 0x00

    # Clear all available row blocks first, then write active rows only.
    available_rows = max(0, (len(out) - GRID_FIRST_ROW_START) // GRID_ROW_STRIDE)
    for row in range(available_rows):
        row_start = cell_offset(row, 0)
        row_end = row_start + COLS_PER_ROW * CELL_SIZE
        out[row_start:row_end] = b"\x00" * (row_end - row_start)

    for row in range(logical_rows):
        is_terminal = row == logical_rows - 1
        for column in range(COLS_PER_ROW):
            start = cell_offset(row, column)
            out[start + 0x01] = column & 0xFF
            out[start + 0x05] = (row + 1) & 0xFF
            out[start + 0x09] = 0x01
            out[start + 0x0A] = 0x01
            out[start + 0x0C] = 0x01
            out[start + 0x0D] = 0xFF
            out[start + 0x0E] = 0xFF
            out[start + 0x0F] = 0xFF
            out[start + 0x10] = 0xFF
            out[start + 0x11] = 0x01

            if set_cell_0b:
                out[start + 0x0B] = cell_0b_value

            out[start + 0x38] = 0x00 if (is_terminal and column == 31) else 0x01
            if is_terminal and column == 31:
                out[start + 0x3D] = 0x00
            elif column == 31:
                out[start + 0x3D] = (row + 2) & 0xFF
            else:
                out[start + 0x3D] = (row + 1) & 0xFF

    if set_terminal_15:
        terminal_row_col0 = cell_offset(logical_rows - 1, 0)
        out[terminal_row_col0 + 0x15] = terminal_15_value

    return bytes(out)
