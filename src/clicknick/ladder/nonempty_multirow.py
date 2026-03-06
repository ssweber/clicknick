"""Deterministic non-empty multi-row wire-topology synthesis.

This module encodes the validated non-empty wire lane (March 2026):
- logical rows 2..32;
- token support per condition cell: "", "-", "|", "T";
- vertical continuity uses cell +0x21;
- horizontal continuity uses paired +0x19/+0x1D writes (never +0x19-only).
"""

from __future__ import annotations

from collections.abc import Sequence

from .empty_multirow import empty_multirow_payload_length, empty_multirow_row_word, synthesize_empty_multirow
from .topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    COLS_PER_ROW,
    cell_offset,
)

NONEMPTY_MULTIROW_MIN_ROWS = 2
NONEMPTY_MULTIROW_MAX_ROWS = 32
NONEMPTY_MULTIROW_CONDITION_COLUMNS = COLS_PER_ROW - 1  # A..AE
NONEMPTY_MULTIROW_SUPPORTED_TOKENS = frozenset({"", "-", "|", "T"})
NONEMPTY_MULTIROW_COL_A_VERTICAL_POLICIES = frozenset({"reject", "blank"})

_TOKEN_TO_FLAGS: dict[str, tuple[int, int, int]] = {
    "": (0, 0, 0),
    "-": (1, 1, 0),
    "|": (0, 0, 1),
    "T": (1, 1, 1),
}


def _validate_rows(logical_rows: int) -> None:
    if not isinstance(logical_rows, int):
        raise TypeError(f"logical_rows must be int; got {type(logical_rows).__name__}")
    if not (NONEMPTY_MULTIROW_MIN_ROWS <= logical_rows <= NONEMPTY_MULTIROW_MAX_ROWS):
        raise ValueError(
            f"logical_rows must be in [{NONEMPTY_MULTIROW_MIN_ROWS}, {NONEMPTY_MULTIROW_MAX_ROWS}], "
            f"got {logical_rows}"
        )


def _validate_col_a_vertical_policy(policy: str) -> None:
    if policy not in NONEMPTY_MULTIROW_COL_A_VERTICAL_POLICIES:
        allowed = ", ".join(sorted(NONEMPTY_MULTIROW_COL_A_VERTICAL_POLICIES))
        raise ValueError(f"col_a_vertical_policy must be one of: {allowed}; got {policy!r}")


def _validate_wire_rows(
    logical_rows: int,
    wire_rows: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    if len(wire_rows) != logical_rows:
        raise ValueError(
            f"wire_rows count must equal logical_rows ({logical_rows}); got {len(wire_rows)}"
        )

    normalized_rows: list[tuple[str, ...]] = []
    for row_idx, row in enumerate(wire_rows):
        if len(row) != NONEMPTY_MULTIROW_CONDITION_COLUMNS:
            raise ValueError(
                f"wire row {row_idx} must have {NONEMPTY_MULTIROW_CONDITION_COLUMNS} condition cells; "
                f"got {len(row)}"
            )
        normalized_rows.append(tuple(token.strip() for token in row))
    return tuple(normalized_rows)


def nonempty_multirow_payload_length(logical_rows: int) -> int:
    """Return payload length for non-empty multi-row wire synthesis."""
    _validate_rows(logical_rows)
    return empty_multirow_payload_length(logical_rows)


def nonempty_multirow_row_word(logical_rows: int) -> int:
    """Return header row word for non-empty multi-row wire synthesis."""
    _validate_rows(logical_rows)
    return empty_multirow_row_word(logical_rows)


def synthesize_nonempty_multirow(
    logical_rows: int,
    *,
    wire_rows: Sequence[Sequence[str]],
    template: bytes | None = None,
    col_a_vertical_policy: str = "reject",
) -> bytes:
    """Build a deterministic non-empty multi-row wire payload.

    `wire_rows` is row-major token data for columns A..AE (`31` columns).
    Column AF is output/instruction space and is not wire-token writable here.
    """
    _validate_rows(logical_rows)
    _validate_col_a_vertical_policy(col_a_vertical_policy)
    rows = _validate_wire_rows(logical_rows, wire_rows)

    # Reuse proven empty-lane row-word/length/cell structural formulas as baseline.
    out = bytearray(synthesize_empty_multirow(logical_rows, template=template))

    # Asymmetry guard: clear all wire flags first so stale template bytes cannot leak
    # one-sided +0x19-only cells.
    for row_idx in range(logical_rows):
        for col_idx in range(NONEMPTY_MULTIROW_CONDITION_COLUMNS):
            start = cell_offset(row_idx, col_idx)
            out[start + CELL_HORIZONTAL_LEFT_OFFSET] = 0
            out[start + CELL_HORIZONTAL_RIGHT_OFFSET] = 0
            out[start + CELL_VERTICAL_DOWN_OFFSET] = 0

    for row_idx, tokens in enumerate(rows):
        for col_idx, token in enumerate(tokens):
            if token not in NONEMPTY_MULTIROW_SUPPORTED_TOKENS:
                allowed = ", ".join(repr(value) for value in sorted(NONEMPTY_MULTIROW_SUPPORTED_TOKENS))
                raise ValueError(
                    f"Unsupported wire token {token!r} at row={row_idx}, col={col_idx}; "
                    f"allowed: {allowed}"
                )

            if col_idx == 0 and token == "|":
                if col_a_vertical_policy == "reject":
                    raise ValueError("Vertical '|' token is not allowed in column A")
                token = ""

            left, right, down = _TOKEN_TO_FLAGS[token]
            start = cell_offset(row_idx, col_idx)
            out[start + CELL_HORIZONTAL_LEFT_OFFSET] = left
            out[start + CELL_HORIZONTAL_RIGHT_OFFSET] = right
            out[start + CELL_VERTICAL_DOWN_OFFSET] = down

    return bytes(out)
