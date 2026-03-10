"""Byte-exact golden-file tests for encode_rung().

Each test case calls encode_rung() with specific inputs and compares the
output byte-for-byte against a golden .bin fixture.  The fixtures are
deterministic encoder outputs whose corresponding verify-back captures
have been confirmed to round-trip cleanly through Click.

Regenerate fixtures:  uv run python scratchpad/generate_golden_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clicknick.ladder.encode import encode_rung

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures" / "golden"

# -- helpers --
E = ""
D = "-"
T_ = "T"
V = "|"


def _empty(n: int = 31) -> list[str]:
    return [E] * n


def _full_wire(n: int = 31) -> list[str]:
    return [D] * n


def _sparse_ac() -> list[str]:
    """Wire at A (col 0) and C (col 2) — connects to power rail."""
    row = [E] * 31
    row[0] = D
    row[2] = D
    return row


def _col_a_wire() -> list[str]:
    row = [E] * 31
    row[0] = D
    return row


# -----------------------------------------------------------------------
# Non-comment shapes
# -----------------------------------------------------------------------

_NON_COMMENT_CASES: list[tuple[str, int, list[list[str]], list[str]]] = [
    ("encode-1row-empty", 1, [_empty()], [E]),
    ("encode-1row-fullwire-nop", 1, [_full_wire()], ["NOP"]),
    ("encode-1row-partial-wire", 1, [_sparse_ac()], [E]),  # wire at A, C
    ("encode-2row-empty", 2, [_empty(), _empty()], [E, E]),
    ("encode-2row-wire-ac", 2, [_sparse_ac(), _sparse_ac()], [E, E]),
    (
        "encode-3row-t-junction",
        3,
        [
            [D, T_] + [D] * 29,  # wire from rail, T at B, wire continues
            [E, D] + [E] * 29,   # wire at B (receiving vertical)
            _empty(),
        ],
        [E, E, E],
    ),
    (
        "encode-4row-vertical-b",
        4,
        [
            [D, T_] + [E] * 29,  # wire from rail, T at B
            [E, V] + [E] * 29,   # vertical pass-through at B
            [E, V] + [E] * 29,   # vertical pass-through at B
            [E, D] + [E] * 29,   # wire at B (terminal)
        ],
        [E, E, E, E],
    ),
    ("encode-2row-nop-row1", 2, [_empty(), _empty()], [E, "NOP"]),
    ("encode-32row-empty", 32, [_empty() for _ in range(32)], [E] * 32),
]


@pytest.mark.parametrize(
    "fixture,logical_rows,condition_rows,af_tokens",
    _NON_COMMENT_CASES,
    ids=[c[0] for c in _NON_COMMENT_CASES],
)
def test_encode_rung_no_comment(
    fixture: str,
    logical_rows: int,
    condition_rows: list[list[str]],
    af_tokens: list[str],
) -> None:
    result = encode_rung(logical_rows, condition_rows, af_tokens)
    expected = (FIXTURES / f"{fixture}.bin").read_bytes()
    assert result == expected, f"Golden file mismatch: {fixture}"


# -----------------------------------------------------------------------
# Comment shapes
# -----------------------------------------------------------------------

_COMMENT_CASES: list[tuple[str, int, list[list[str]], list[str], str]] = [
    # 1-row
    ("encode-cmt-1row-empty", 1, [_empty()], [E], "Hello"),
    ("encode-cmt-1row-fullwire-nop", 1, [_full_wire()], ["NOP"], "Hello"),
    ("encode-cmt-1row-partial-wire", 1, [_sparse_ac()], [E], "Hello"),
    ("encode-cmt-1row-max1400", 1, [_full_wire()], ["NOP"], "Max length comment test. " * 56),
    # 2-row
    ("encode-cmt-2row-empty", 2, [_empty(), _empty()], [E, E], "Test comment"),
    ("encode-cmt-2row-wire-ac", 2, [_sparse_ac(), _sparse_ac()], [E, E], "Test comment"),
    ("encode-cmt-2row-colA-wire", 2, [_col_a_wire(), _col_a_wire()], [E, E], "Col A test"),
    ("encode-cmt-2row-nop-row1", 2, [_empty(), _empty()], [E, "NOP"], "Test comment"),
    (
        "encode-cmt-2row-max1324-nop",
        2,
        [_sparse_ac(), _sparse_ac()],
        [E, "NOP"],
        ("Max comment for two row rung test. " * (1324 // 35))[:1324],
    ),
    # 3-row
    ("encode-cmt-3row-empty", 3, [_empty(), _empty(), _empty()], [E, E, E], "Three rows"),
    (
        "encode-cmt-3row-mixed-wire",
        3,
        [_full_wire(), _sparse_ac(), _sparse_ac()],
        [E, E, E],
        "Three row mixed",
    ),
    (
        "encode-cmt-3row-max1400",
        3,
        [_full_wire(), _sparse_ac(), _empty()],
        [E, E, E],
        "Max length comment test. " * 56,
    ),
    # 4+ rows
    (
        "encode-cmt-4row-wire",
        4,
        [_full_wire(), _full_wire(), _full_wire(), _empty()],
        [E, E, E, E],
        "Four row wire",
    ),
    (
        "encode-cmt-5row-partial",
        5,
        [_full_wire()] + [_sparse_ac()] * 3 + [_empty()],
        [E] * 5,
        "Five row wire",
    ),
    (
        "encode-cmt-9row-partial",
        9,
        [_full_wire()] + [_sparse_ac()] * 7 + [_empty()],
        [E] * 9,
        "Nine row wire",
    ),
    (
        "encode-cmt-32row-partial",
        32,
        [_full_wire()] + [_sparse_ac()] * 30 + [_empty()],
        [E] * 32,
        "Max row wire",
    ),
]


@pytest.mark.parametrize(
    "fixture,logical_rows,condition_rows,af_tokens,comment",
    _COMMENT_CASES,
    ids=[c[0] for c in _COMMENT_CASES],
)
def test_encode_rung_comment(
    fixture: str,
    logical_rows: int,
    condition_rows: list[list[str]],
    af_tokens: list[str],
    comment: str,
) -> None:
    result = encode_rung(logical_rows, condition_rows, af_tokens, comment=comment)
    expected = (FIXTURES / f"{fixture}.bin").read_bytes()
    assert result == expected, f"Golden file mismatch: {fixture}"


# -----------------------------------------------------------------------
# Validation edge cases
# -----------------------------------------------------------------------


def test_encode_rung_rejects_multiple_nops() -> None:
    with pytest.raises(ValueError, match="Only one NOP"):
        encode_rung(2, [_empty(), _empty()], ["NOP", "NOP"])


def test_encode_rung_rejects_vertical_col_a() -> None:
    row = _empty()
    row[0] = "|"
    with pytest.raises(ValueError, match="column A"):
        encode_rung(2, [row, _empty()], [E, E])


def test_encode_rung_rejects_vertical_last_row() -> None:
    row = _empty()
    row[1] = "|"
    with pytest.raises(ValueError, match="last row"):
        encode_rung(1, [row], [E])


def test_encode_rung_rejects_comment_overflow_2row() -> None:
    with pytest.raises(ValueError, match="too long"):
        encode_rung(2, [_empty(), _empty()], [E, E], comment="X" * 1400)


def test_encode_rung_rejects_out_of_range_rows() -> None:
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rung(0, [], [])
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rung(33, [_empty() for _ in range(33)], [E] * 33)


def test_encode_rung_buffer_sizes() -> None:
    """Verify buffer sizing formula across key row counts."""
    cases = [
        (1, 0x2000),
        (2, 0x2000),
        (3, 0x3000),
        (4, 0x3000),
        (5, 0x4000),
        (9, 0x6000),
        (17, 0xA000),
        (32, 0x11000),
    ]
    for rows, expected_size in cases:
        result = encode_rung(rows, [_empty() for _ in range(rows)], [E] * rows)
        assert len(result) == expected_size, f"rows={rows}: expected {expected_size}, got {len(result)}"
