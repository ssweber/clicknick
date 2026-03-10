"""Queue golden fixtures — v3. Fixed ALL continuation row shorthand.

Continuation row shorthand reminder:
  ,-,...    → marker="", colA="-", rest blank  (wire at A)
  ,,-,...   → marker="", colA="", colB="-"     (wire at B)
  ,-,,-,... → marker="", colA="-", colB="", colC="-" (wire at A,C)
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests/fixtures/ladder_captures/golden"
SCENARIO = "golden-v3-20260310"

# Fixture → (description, comment, rows)
# Double-checked every continuation row against the encode test cases:
#   _sparse_ac() = cols 0,2 = A,C  → continuation: ,-,,-,...,:,
#   wire at B only                  → continuation: ,,-,...,:,
#   vertical at B                   → continuation: ,,|,...,:,
#   full wire                       → continuation: ,->,:,
#   empty                           → continuation: ,...,:,
ENTRIES = [
    # --- Non-comment ---
    # encode test: [_empty()], [E]
    ("encode-1row-empty", "1-row empty", None,
     ["R,...,:,"]),

    # encode test: [_full_wire()], ["NOP"]
    ("encode-1row-fullwire-nop", "1-row full wire + NOP", None,
     ["R,->,:,NOP"]),

    # encode test: [_sparse_ac()], [E]  — wire at A(0), C(2)
    ("encode-1row-partial-wire", "1-row wire A+C", None,
     ["R,-,,-,...,:,"]),

    # encode test: [_empty(), _empty()], [E, E]
    ("encode-2row-empty", "2-row empty", None,
     ["R,...,:,", ",...,:,"]),

    # encode test: [_sparse_ac(), _sparse_ac()], [E, E]  — wire at A,C both rows
    ("encode-2row-wire-ac", "2-row wire A+C both rows", None,
     ["R,-,,-,...,:,", ",-,,-,...,:,"]),

    # encode test: [D,T_]+[D]*29, [E,D]+[E]*29, empty  — rail→T at B→wire, B on row1
    ("encode-3row-t-junction", "3-row rail to T at B", None,
     ["R,-,T,->,:,", ",,-,...,:,", ",...,:,"]),

    # encode test: [D,T_]+[E]*29, [E,V]+[E]*29, [E,V]+[E]*29, [E,D]+[E]*29
    ("encode-4row-vertical-b", "4-row rail to T at B, vertical down", None,
     ["R,-,T,...,:,", ",,|,...,:,", ",,|,...,:,", ",,-,...,:,"]),

    # encode test: [_empty(), _empty()], [E, "NOP"]
    ("encode-2row-nop-row1", "2-row NOP on row 1", None,
     ["R,...,:,", ",...,:,NOP"]),

    # encode test: 32 × [_empty()], 32 × [E]
    ("encode-32row-empty", "32-row empty", None,
     ["R,...,:,"] + [",...,:,"] * 31),

    # --- Comment, 1-row ---
    ("encode-cmt-1row-empty", "cmt 1-row empty", "Hello",
     ["R,...,:,"]),
    ("encode-cmt-1row-fullwire-nop", "cmt 1-row full wire + NOP", "Hello",
     ["R,->,:,NOP"]),
    ("encode-cmt-1row-partial-wire", "cmt 1-row wire A+C", "Hello",
     ["R,-,,-,...,:,"]),
    ("encode-cmt-1row-max1400", "cmt 1-row max 1400", "Max length comment test. " * 56,
     ["R,->,:,NOP"]),

    # --- Comment, 2-row ---
    ("encode-cmt-2row-empty", "cmt 2-row empty", "Test comment",
     ["R,...,:,", ",...,:,"]),

    # encode test: [_sparse_ac(), _sparse_ac()] — wire at A,C both rows
    ("encode-cmt-2row-wire-ac", "cmt 2-row wire A+C", "Test comment",
     ["R,-,,-,...,:,", ",-,,-,...,:,"]),

    ("encode-cmt-2row-colA-wire", "cmt 2-row col A wire", "Col A test",
     ["R,-,...,:,", ",-,...,:,"]),

    ("encode-cmt-2row-nop-row1", "cmt 2-row NOP row 1", "Test comment",
     ["R,...,:,", ",...,:,NOP"]),

    # encode test: [_sparse_ac(), _sparse_ac()], [E, "NOP"] — wire at A,C
    ("encode-cmt-2row-max1324-nop", "cmt 2-row max 1324 + NOP",
     ("Max comment for two row rung test. " * (1324 // 35))[:1324],
     ["R,-,,-,...,:,", ",-,,-,...,:,NOP"]),

    # --- Comment, 3-row ---
    ("encode-cmt-3row-empty", "cmt 3-row empty", "Three rows",
     ["R,...,:,", ",...,:,", ",...,:,"]),

    # encode test: [full_wire, sparse_ac, sparse_ac] — full row 0, A+C rows 1+2
    ("encode-cmt-3row-mixed-wire", "cmt 3-row mixed wire", "Three row mixed",
     ["R,->,:,", ",-,,-,...,:,", ",-,,-,...,:,"]),

    # encode test: [full_wire, sparse_ac, empty]
    ("encode-cmt-3row-max1400", "cmt 3-row max 1400", "Max length comment test. " * 56,
     ["R,->,:,", ",-,,-,...,:,", ",...,:,"]),

    # --- Comment, 4+ rows ---
    # encode test: [full]*3 + [empty]
    ("encode-cmt-4row-wire", "cmt 4-row wire rows 0-2", "Four row wire",
     ["R,->,:,", ",->,:,", ",->,:,", ",...,:,"]),

    # encode test: [full] + [sparse_ac]*3 + [empty]
    ("encode-cmt-5row-partial", "cmt 5-row partial wire A+C", "Five row wire",
     ["R,->,:,"] + [",-,,-,...,:,"] * 3 + [",...,:,"]),

    # encode test: [full] + [sparse_ac]*7 + [empty]
    ("encode-cmt-9row-partial", "cmt 9-row partial wire A+C", "Nine row wire",
     ["R,->,:,"] + [",-,,-,...,:,"] * 7 + [",...,:,"]),

    # encode test: [full] + [sparse_ac]*30 + [empty]
    ("encode-cmt-32row-partial", "cmt 32-row partial wire A+C", "Max row wire",
     ["R,->,:,"] + [",-,,-,...,:,"] * 30 + [",...,:,"]),
]


def main():
    ok = 0
    for label, desc, comment, rows in ENTRIES:
        bin_path = GOLDEN / f"{label}.bin"
        if not bin_path.exists():
            print(f"  SKIP {label}: not found")
            continue

        cmd = [
            sys.executable, "-m", "clicknick.ladder.capture_cli",
            "entry", "add",
            "--type", "synthetic",
            "--label", f"golden3-{label}",
            "--scenario", SCENARIO,
            "--description", desc,
            "--payload-source", "file",
            "--payload-file", str(bin_path),
        ]
        if comment:
            cmd.extend(["--comment", comment])
        for r in rows:
            cmd.extend(["--row", r])
        cmd.append("--json")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  OK {label}")
            ok += 1
        else:
            err = result.stderr.strip() or result.stdout.strip()
            print(f"  {'EXISTS' if 'already exists' in err else 'FAIL'} {label}")

    print(f"\nQueued {ok}")


if __name__ == "__main__":
    main()
