"""Generate golden .bin fixtures from encode_rung() for regression tests.

These fixtures are deterministic outputs of the encoder. The corresponding
verify-back captures confirm Click accepted them. Together they provide
both regression protection and Click parity confidence.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clicknick.ladder.encode import encode_rung

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/ladder_captures/golden"

# -- helpers --
E = ""
D = "-"
T_ = "T"
V = "|"

def empty_row():
    return [E] * 31

def full_wire_row():
    return [D] * 31

def sparse_ac_row():
    """Wire at A (col 0) and C (col 2) — connects to power rail."""
    row = [E] * 31
    row[0] = D
    row[2] = D
    return row

def col_a_wire_row():
    """Wire at A (col 0) only."""
    row = [E] * 31
    row[0] = D
    return row

# -----------------------------------------------------------------------
# Fixture definitions: (label, logical_rows, condition_rows, af_tokens, comment)
# -----------------------------------------------------------------------
FIXTURES_DEF = [
    # --- Non-comment ---
    ("encode-1row-empty", 1, [empty_row()], [E], None),
    ("encode-1row-fullwire-nop", 1, [full_wire_row()], ["NOP"], None),
    ("encode-1row-partial-wire", 1, [sparse_ac_row()], [E], None),
    ("encode-2row-empty", 2, [empty_row(), empty_row()], [E, E], None),
    ("encode-2row-wire-ac", 2, [sparse_ac_row(), sparse_ac_row()], [E, E], None),
    ("encode-3row-t-junction", 3, [
        [D, T_] + [D] * 29,   # wire from rail, T at B, wire continues
        [E, D] + [E] * 29,    # wire at B (receiving vertical)
        empty_row(),
    ], [E, E, E], None),
    ("encode-4row-vertical-b", 4, [
        [D, T_] + [E] * 29,   # wire from rail, T at B
        [E, V] + [E] * 29,    # vertical pass-through at B
        [E, V] + [E] * 29,    # vertical pass-through at B
        [E, D] + [E] * 29,    # wire at B (terminal)
    ], [E, E, E, E], None),
    ("encode-2row-nop-row1", 2, [empty_row(), empty_row()], [E, "NOP"], None),
    ("encode-32row-empty", 32, [empty_row() for _ in range(32)], [E] * 32, None),

    # --- Comment, 1-row ---
    ("encode-cmt-1row-empty", 1, [empty_row()], [E], "Hello"),
    ("encode-cmt-1row-fullwire-nop", 1, [full_wire_row()], ["NOP"], "Hello"),
    ("encode-cmt-1row-partial-wire", 1, [sparse_ac_row()], [E], "Hello"),
    ("encode-cmt-1row-max1400", 1, [full_wire_row()], ["NOP"],
     "Max length comment test. " * 56),

    # --- Comment, 2-row ---
    ("encode-cmt-2row-empty", 2, [empty_row(), empty_row()], [E, E], "Test comment"),
    ("encode-cmt-2row-wire-ac", 2, [sparse_ac_row(), sparse_ac_row()], [E, E], "Test comment"),
    ("encode-cmt-2row-colA-wire", 2, [col_a_wire_row(), col_a_wire_row()], [E, E], "Col A test"),
    ("encode-cmt-2row-nop-row1", 2, [empty_row(), empty_row()], [E, "NOP"], "Test comment"),
    ("encode-cmt-2row-max1324-nop", 2, [sparse_ac_row(), sparse_ac_row()], [E, "NOP"],
     ("Max comment for two row rung test. " * (1324 // 35))[:1324]),

    # --- Comment, 3-row ---
    ("encode-cmt-3row-empty", 3, [empty_row(), empty_row(), empty_row()], [E, E, E], "Three rows"),
    ("encode-cmt-3row-mixed-wire", 3,
     [full_wire_row(), sparse_ac_row(), sparse_ac_row()], [E, E, E], "Three row mixed"),
    ("encode-cmt-3row-max1400", 3,
     [full_wire_row(), sparse_ac_row(), empty_row()], [E, E, E],
     "Max length comment test. " * 56),

    # --- Comment, 4+ rows ---
    ("encode-cmt-4row-wire", 4,
     [full_wire_row(), full_wire_row(), full_wire_row(), empty_row()],
     [E, E, E, E], "Four row wire"),
    ("encode-cmt-5row-partial", 5,
     [full_wire_row()] + [sparse_ac_row()] * 3 + [empty_row()],
     [E] * 5, "Five row wire"),
    ("encode-cmt-9row-partial", 9,
     [full_wire_row()] + [sparse_ac_row()] * 7 + [empty_row()],
     [E] * 9, "Nine row wire"),
    ("encode-cmt-32row-partial", 32,
     [full_wire_row()] + [sparse_ac_row()] * 30 + [empty_row()],
     [E] * 32, "Max row wire"),
]


def main():
    for label, rows, cond, af, comment in FIXTURES_DEF:
        result = encode_rung(rows, cond, af, comment=comment)
        out_path = FIXTURES / f"{label}.bin"
        out_path.write_bytes(result)
        print(f"  {label}.bin  ({len(result)} bytes)")

    print(f"\nGenerated {len(FIXTURES_DEF)} golden fixtures")


if __name__ == "__main__":
    main()
