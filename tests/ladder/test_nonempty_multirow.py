"""Tests for deterministic non-empty multi-row wire synthesis."""

import pytest

from clicknick.ladder.empty_multirow import synthesize_empty_multirow
from clicknick.ladder.nonempty_multirow import (
    NONEMPTY_MULTIROW_CONDITION_COLUMNS,
    nonempty_multirow_payload_length,
    nonempty_multirow_row_word,
    synthesize_nonempty_multirow,
)
from clicknick.ladder.topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    cell_offset,
    logical_row_count_from_header,
    parse_wire_topology,
)


def _blank_rows(rows: int) -> list[list[str]]:
    return [[""] * NONEMPTY_MULTIROW_CONDITION_COLUMNS for _ in range(rows)]


def _flag_tuple(data: bytes, row: int, col: int) -> tuple[int, int, int]:
    start = cell_offset(row, col)
    return (
        data[start + CELL_HORIZONTAL_LEFT_OFFSET],
        data[start + CELL_HORIZONTAL_RIGHT_OFFSET],
        data[start + CELL_VERTICAL_DOWN_OFFSET],
    )


@pytest.mark.parametrize(
    ("rows", "expected_len", "expected_word"),
    [
        (2, 8192, 0x0060),
        (3, 12288, 0x0080),
        (4, 12288, 0x00A0),
        (9, 24576, 0x0140),
        (17, 40960, 0x0240),
        (32, 69632, 0x0420),
    ],
)
def test_nonempty_multirow_length_and_row_word_formula(
    rows: int, expected_len: int, expected_word: int
) -> None:
    assert nonempty_multirow_payload_length(rows) == expected_len
    assert nonempty_multirow_row_word(rows) == expected_word


@pytest.mark.parametrize("rows", [1, 33])
def test_nonempty_multirow_rejects_out_of_range_rows(rows: int) -> None:
    with pytest.raises(ValueError, match="logical_rows must be in"):
        _ = nonempty_multirow_payload_length(rows)
    with pytest.raises(ValueError, match="logical_rows must be in"):
        _ = synthesize_nonempty_multirow(rows, wire_rows=_blank_rows(max(rows, 2)))


def test_synthesize_nonempty_multirow_maps_tokens_to_wire_flags() -> None:
    rows = 4
    wire_rows = _blank_rows(rows)
    wire_rows[0][0] = "-"
    wire_rows[0][1] = "|"
    wire_rows[0][2] = "T"
    wire_rows[1][5] = "-"
    wire_rows[2][7] = "|"
    wire_rows[3][10] = "T"

    payload = synthesize_nonempty_multirow(rows, wire_rows=wire_rows)

    assert len(payload) == nonempty_multirow_payload_length(rows)
    assert logical_row_count_from_header(payload) == rows
    assert parse_wire_topology(payload).row_count == rows

    assert _flag_tuple(payload, 0, 0) == (1, 1, 0)
    assert _flag_tuple(payload, 0, 1) == (0, 0, 1)
    assert _flag_tuple(payload, 0, 2) == (1, 1, 1)
    assert _flag_tuple(payload, 1, 5) == (1, 1, 0)
    assert _flag_tuple(payload, 2, 7) == (0, 0, 1)
    assert _flag_tuple(payload, 3, 10) == (1, 1, 1)
    assert _flag_tuple(payload, 0, 3) == (0, 0, 0)


def test_synthesize_nonempty_multirow_rejects_unsupported_token() -> None:
    wire_rows = _blank_rows(2)
    wire_rows[0][0] = "X001"
    with pytest.raises(ValueError, match="Unsupported wire token"):
        _ = synthesize_nonempty_multirow(2, wire_rows=wire_rows)


def test_synthesize_nonempty_multirow_rejects_pipe_in_column_a_by_default() -> None:
    wire_rows = _blank_rows(2)
    wire_rows[0][0] = "|"
    with pytest.raises(ValueError, match="column A"):
        _ = synthesize_nonempty_multirow(2, wire_rows=wire_rows)


def test_synthesize_nonempty_multirow_can_blank_pipe_in_column_a() -> None:
    wire_rows = _blank_rows(2)
    wire_rows[0][0] = "|"
    payload = synthesize_nonempty_multirow(
        2,
        wire_rows=wire_rows,
        col_a_vertical_policy="blank",
    )
    assert _flag_tuple(payload, 0, 0) == (0, 0, 0)


def test_synthesize_nonempty_multirow_validates_wire_rows_shape() -> None:
    with pytest.raises(ValueError, match="wire_rows count must equal logical_rows"):
        _ = synthesize_nonempty_multirow(3, wire_rows=_blank_rows(2))

    too_wide = _blank_rows(2)
    too_wide[0].append("")
    with pytest.raises(ValueError, match="must have 31 condition cells"):
        _ = synthesize_nonempty_multirow(2, wire_rows=too_wide)


def test_synthesize_nonempty_multirow_validates_col_a_vertical_policy() -> None:
    with pytest.raises(ValueError, match="col_a_vertical_policy"):
        _ = synthesize_nonempty_multirow(
            2,
            wire_rows=_blank_rows(2),
            col_a_vertical_policy="normalize",
        )


def test_synthesize_nonempty_multirow_clears_stale_template_wire_flags() -> None:
    rows = 2
    template = bytearray(synthesize_empty_multirow(rows))
    stale = cell_offset(0, 5)
    template[stale + CELL_HORIZONTAL_LEFT_OFFSET] = 1
    template[stale + CELL_HORIZONTAL_RIGHT_OFFSET] = 0
    template[stale + CELL_VERTICAL_DOWN_OFFSET] = 0

    payload = synthesize_nonempty_multirow(rows, wire_rows=_blank_rows(rows), template=bytes(template))
    assert _flag_tuple(payload, 0, 5) == (0, 0, 0)
