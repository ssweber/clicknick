"""Queue all 25 golden fixtures as file-backed verify entries."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests/fixtures/ladder_captures/golden"

SCENARIO = "golden-regression-20260310"

# Map fixture name -> (description, rows shorthand)
# Each entry needs at least one --row and a --comment if applicable.
ENTRIES = [
    # Non-comment
    ("encode-1row-empty", "1-row empty", None, ["R,...,:,"]),
    ("encode-1row-fullwire-nop", "1-row full wire + NOP", None, ["R,->,:,NOP"]),
    ("encode-1row-partial-wire", "1-row wire at B+D", None, ["R,,-,,-,...,:,"]),
    ("encode-2row-empty", "2-row empty", None, ["R,...,:,", ",...,:,"]),
    ("encode-2row-wire-bd", "2-row wire B+D both rows", None, ["R,,-,,-,...,:,", ",-,,-,...,:,"]),
    ("encode-3row-t-junction", "3-row T-junction at B", None, ["R,,T,->,:,", ",-,...,:,", ",...,:,"]),
    ("encode-4row-vertical-b", "4-row vertical B", None, ["R,,T,...,:,", ",,|,...,:,", ",,|,...,:,", ",-,...,:,"]),
    ("encode-2row-nop-row1", "2-row NOP on row 1", None, ["R,...,:,", ",...,:,NOP"]),
    ("encode-32row-empty", "32-row empty", None, ["R,...,:,"] + [",...,:,"] * 31),

    # Comment 1-row
    ("encode-cmt-1row-empty", "cmt 1-row empty", "Hello", ["R,...,:,"]),
    ("encode-cmt-1row-fullwire-nop", "cmt 1-row full wire + NOP", "Hello", ["R,->,:,NOP"]),
    ("encode-cmt-1row-partial-wire", "cmt 1-row wire B+D", "Hello", ["R,,-,,-,...,:,"]),
    ("encode-cmt-1row-max1400", "cmt 1-row max 1400", "Max length comment test. " * 56, ["R,->,:,NOP"]),

    # Comment 2-row
    ("encode-cmt-2row-empty", "cmt 2-row empty", "Test comment", ["R,...,:,", ",...,:,"]),
    ("encode-cmt-2row-wire-bd", "cmt 2-row wire B+D", "Test comment", ["R,,-,,-,...,:,", ",-,,-,...,:,"]),
    ("encode-cmt-2row-colA-wire", "cmt 2-row col A wire", "Col A test", ["R,-,...,:,", ",-,...,:,"]),
    ("encode-cmt-2row-nop-row1", "cmt 2-row NOP row 1", "Test comment", ["R,...,:,", ",...,:,NOP"]),
    ("encode-cmt-2row-max1324-nop", "cmt 2-row max 1324 + NOP", ("Max comment for two row rung test. " * (1324 // 35))[:1324], ["R,,-,,-,...,:,", ",-,,-,...,:,NOP"]),

    # Comment 3-row
    ("encode-cmt-3row-empty", "cmt 3-row empty", "Three rows", ["R,...,:,", ",...,:,", ",...,:,"]),
    ("encode-cmt-3row-mixed-wire", "cmt 3-row mixed wire", "Three row mixed", ["R,->,:,", ",-,,-,...,:,", ",-,,-,...,:,"]),
    ("encode-cmt-3row-max1400", "cmt 3-row max 1400", "Max length comment test. " * 56, ["R,->,:,", ",-,,-,...,:,", ",...,:,"]),

    # Comment 4+ rows
    ("encode-cmt-4row-wire", "cmt 4-row wire rows 0-2", "Four row wire", ["R,->,:,", ",->,:,", ",->,:,", ",...,:,"]),
    ("encode-cmt-5row-partial", "cmt 5-row partial wire", "Five row wire", ["R,->,:,", ",-,,-,...,:,", ",-,,-,...,:,", ",-,,-,...,:,", ",...,:,"]),
    ("encode-cmt-9row-partial", "cmt 9-row partial wire", "Nine row wire", ["R,->,:,"] + [",-,,-,...,:,"] * 7 + [",...,:,"]),
    ("encode-cmt-32row-partial", "cmt 32-row partial wire", "Max row wire", ["R,->,:,"] + [",-,,-,...,:,"] * 30 + [",...,:,"]),
]

def main():
    ok = 0
    skip = 0
    for label, desc, comment, rows in ENTRIES:
        bin_path = GOLDEN / f"{label}.bin"
        if not bin_path.exists():
            print(f"  SKIP {label}: fixture not found")
            skip += 1
            continue

        cmd = [
            sys.executable, "-m", "clicknick.ladder.capture_cli",
            "entry", "add",
            "--type", "synthetic",
            "--label", f"golden-{label}",
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
            if "already exists" in err:
                print(f"  EXISTS {label}")
                skip += 1
            else:
                print(f"  FAIL {label}: {err[:100]}")

    print(f"\nQueued {ok}, skipped {skip}")


if __name__ == "__main__":
    main()
