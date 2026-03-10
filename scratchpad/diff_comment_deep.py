"""Deep structural comparison: 1-row and 2-row comment, native vs synthetic.

Focus on phase-A-relative offsets rather than absolute positions, to
factor out RTF prefix length / comment flag session differences.
"""

from pathlib import Path
from clicknick.ladder.encode import (
    encode_rung, PAYLOAD_BYTES_OFFSET, PAYLOAD_LENGTH_OFFSET, PHASE_A_LEN,
    COMMENT_FLAG, _PREFIX, _SUFFIX,
)

def read_structural(data: bytes, label: str):
    """Extract key structural info from a comment rung."""
    print(f"\n=== {label} ({len(data)} bytes) ===")

    # Row count from header entry 0
    row_count = int.from_bytes(data[0x0254:0x0256], 'little')
    print(f"  Header entry0 row-count word: 0x{row_count:04X}")

    # Comment flag
    cf = data[0x0254 + 0x17]
    print(f"  Header entry0 +0x17 (comment flag): 0x{cf:02X}")

    # Payload length
    plen = int.from_bytes(data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], 'little')
    print(f"  Payload length @ 0x0294: {plen}")

    # Phase-A start
    phase_a_start = PAYLOAD_BYTES_OFFSET + plen
    print(f"  Phase-A starts at: 0x{phase_a_start:04X}")
    print(f"  Phase-A ends at:   0x{phase_a_start + PHASE_A_LEN:04X}")

    # Trailer byte
    print(f"  0x0A59 (trailer): 0x{data[0x0A59]:02X}")

    # Check phase-A comment flags (periodic at +0x13, stride 0x40)
    phase_a_flags = set()
    for k in range(63):
        val = data[phase_a_start + 0x13 + 0x40 * k]
        phase_a_flags.add(val)
    print(f"  Phase-A comment flag values: {sorted(hex(v) for v in phase_a_flags)}")

    # Check first few bytes of phase-A
    pa_bytes = data[phase_a_start:phase_a_start+32]
    print(f"  Phase-A first 32 bytes: {pa_bytes.hex()}")

    # Check cell grid region (0x0A60+) for any non-zero (wire flags)
    grid_start = 0x0A60
    grid_nonzero = []
    for i in range(0x800):  # one row worth
        if data[grid_start + i] != 0:
            grid_nonzero.append((grid_start + i, data[grid_start + i]))
    if grid_nonzero:
        print(f"  Cell grid row 0 has {len(grid_nonzero)} non-zero bytes")
        for off, val in grid_nonzero[:20]:
            print(f"    0x{off:04X} = 0x{val:02X}")
    else:
        print(f"  Cell grid row 0: all zero (empty)")

    return phase_a_start


def diff_phase_a_relative(native: bytes, synthetic: bytes, nat_pa: int, syn_pa: int):
    """Diff two captures relative to their phase-A start positions."""
    print("\n=== Phase-A relative diff ===")
    diffs = []
    for i in range(PHASE_A_LEN):
        if native[nat_pa + i] != synthetic[syn_pa + i]:
            diffs.append((i, native[nat_pa + i], synthetic[syn_pa + i]))
    print(f"  Phase-A diffs (relative): {len(diffs)}")
    for off, nat_b, syn_b in diffs[:30]:
        print(f"    +0x{off:04X}  native=0x{nat_b:02X}  synth=0x{syn_b:02X}")


# ---- 1-row comment (empty grid) ----
print("=" * 60)
print("1-ROW COMMENT, EMPTY GRID")
print("=" * 60)

nat1 = Path("scratchpad/captures/native-comment-helloworld.bin").read_bytes()
syn1 = encode_rung(1, [[""] * 31], [""], comment="Hello world")
nat1_pa = read_structural(nat1, "native-comment-helloworld")
syn1_pa = read_structural(syn1, "synthetic 1-row empty")
diff_phase_a_relative(nat1, syn1, nat1_pa, syn1_pa)

# ---- 1-row comment (full wire) ----
print("\n" + "=" * 60)
print("1-ROW COMMENT, FULL WIRE")
print("=" * 60)

nat1fw = Path("scratchpad/captures/native-comment-fullwire.bin").read_bytes()
syn1fw = encode_rung(1, [["-"] * 31], [""], comment="Partial wires")
nat1fw_pa = read_structural(nat1fw, "native-comment-fullwire")
syn1fw_pa = read_structural(syn1fw, "synthetic 1-row fullwire")
diff_phase_a_relative(nat1fw, syn1fw, nat1fw_pa, syn1fw_pa)

# Check wire encoding in phase-A for full-wire case
print("\n=== Wire encoding check (full wire, row 0, comment rung) ===")
print("Phase-A wire slots (col_idx+31, checking +0x21/+0x25/+0x29):")
for col in range(31):
    slot_base_nat = nat1fw_pa + (col + 31) * 0x40
    slot_base_syn = syn1fw_pa + (col + 31) * 0x40
    nat_left = nat1fw[slot_base_nat + 0x21]
    nat_right = nat1fw[slot_base_nat + 0x25]
    nat_down = nat1fw[slot_base_nat + 0x29]
    syn_left = syn1fw[slot_base_syn + 0x21]
    syn_right = syn1fw[slot_base_syn + 0x25]
    syn_down = syn1fw[slot_base_syn + 0x29]
    if (nat_left, nat_right, nat_down) != (syn_left, syn_right, syn_down):
        print(f"  col {col}: native=({nat_left},{nat_right},{nat_down}) synth=({syn_left},{syn_right},{syn_down})")

# ---- 2-row comment (empty, known passing) ----
print("\n" + "=" * 60)
print("2-ROW COMMENT, EMPTY GRID (known passing)")
print("=" * 60)

nat2 = Path("tests/fixtures/ladder_captures/verify-comment-2row-empty.bin").read_bytes()
syn2 = encode_rung(2, [[""] * 31, [""] * 31], ["", ""], comment="Two row test")
nat2_pa = read_structural(nat2, "verify-comment-2row-empty (fixture)")
syn2_pa = read_structural(syn2, "synthetic 2-row empty")
diff_phase_a_relative(nat2, syn2, nat2_pa, syn2_pa)
