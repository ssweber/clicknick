"""Compare header table (32 entries x 0x40 bytes each at 0x0254) between
native and synthetic for 1-row and 2-row comment rungs.

Also check the pre-header region and any bytes in the range 0x0000-0x0253.
"""

from pathlib import Path
from clicknick.ladder.encode import encode_rung

HEADER_BASE = 0x0254
CELL_SIZE = 0x40
NUM_ENTRIES = 32

def diff_header_table(native: bytes, synthetic: bytes, label: str):
    print(f"\n=== Header table diff: {label} ===")
    diffs = 0
    for entry in range(NUM_ENTRIES):
        base = HEADER_BASE + entry * CELL_SIZE
        for off in range(CELL_SIZE):
            addr = base + off
            if native[addr] != synthetic[addr]:
                print(f"  entry[{entry:2d}] +0x{off:02X} (abs 0x{addr:04X}): native=0x{native[addr]:02X} synth=0x{synthetic[addr]:02X}")
                diffs += 1
    print(f"  Total header diffs: {diffs}")


def diff_range(native: bytes, synthetic: bytes, start: int, end: int, label: str):
    print(f"\n=== {label} (0x{start:04X}-0x{end:04X}) ===")
    diffs = []
    for i in range(start, end):
        if native[i] != synthetic[i]:
            diffs.append((i, native[i], synthetic[i]))
    print(f"  Total diffs: {len(diffs)}")
    for off, n, s in diffs[:30]:
        print(f"    0x{off:04X}: native=0x{n:02X} synth=0x{s:02X}")
    if len(diffs) > 30:
        print(f"    ... and {len(diffs) - 30} more")


# ---- 1-row fullwire (same flag, same payload length) ----
nat = Path("scratchpad/captures/native-comment-fullwire.bin").read_bytes()
syn = encode_rung(1, [["-"] * 31], [""], comment="Partial wires")

print("1-ROW FULLWIRE COMMENT (native flag=0x5A, synth flag=0x5A)")
diff_range(nat, syn, 0x0000, 0x0254, "Pre-header region")
diff_header_table(nat, syn, "1-row fullwire")
diff_range(nat, syn, 0x0A54, 0x0A60, "Post-header / trailer region")

# Also compare the fullwire native with the fixture copy
fixture = Path("tests/fixtures/ladder_captures/native-comment-fullwire.bin").read_bytes()
print(f"\n=== Fixture vs scratchpad capture: identical? {fixture == nat} ===")

# ---- 2-row empty (known passing) ----
nat2 = Path("tests/fixtures/ladder_captures/verify-comment-2row-empty.bin").read_bytes()
syn2 = encode_rung(2, [[""] * 31, [""] * 31], ["", ""], comment="Two row test")

print("\n\n2-ROW EMPTY COMMENT (known passing)")
diff_range(nat2, syn2, 0x0000, 0x0254, "Pre-header region")
diff_header_table(nat2, syn2, "2-row empty")
diff_range(nat2, syn2, 0x0A54, 0x0A60, "Post-header / trailer region")

# Summary: total byte diffs
d1 = sum(1 for i in range(len(nat)) if nat[i] != syn[i])
d2 = sum(1 for i in range(len(nat2)) if nat2[i] != syn2[i])
print(f"\n\nTotal byte diffs: 1-row fullwire = {d1}, 2-row empty = {d2}")
