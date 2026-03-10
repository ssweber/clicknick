"""Generate exact byte diff between native fullwire comment capture and
synthetic, excluding known session-variable bytes (pre-header runtime data,
comment flag value).

This establishes the ground truth for what the encoder produces vs a
known-good native capture WITH THE SAME COMMENT FLAG (0x5A).
"""

from pathlib import Path
from clicknick.ladder.encode import encode_rung

# Native fullwire: "Partial wires" text, flag 0x5A, all 31 cols dashed
nat = Path("scratchpad/captures/native-comment-fullwire.bin").read_bytes()

# Same shape from encoder
syn = encode_rung(1, [["-"] * 31], [""], comment="Partial wires")

assert len(nat) == len(syn) == 8192

# Categorize all diffs
pre_header_diffs = []   # 0x0054-0x0253 (runtime session data)
header_diffs = []       # 0x0254-0x0A53 (header table)
trailer_diffs = []      # 0x0A54-0x0A5F
grid_diffs = []         # 0x0A60+ (cell grid / phase-A overlap)

for i in range(len(nat)):
    if nat[i] != syn[i]:
        if i < 0x0054:
            pass  # Skip magic/path (should be none)
        elif i < 0x0254:
            pre_header_diffs.append((i, nat[i], syn[i]))
        elif i < 0x0A54:
            header_diffs.append((i, nat[i], syn[i]))
        elif i < 0x0A60:
            trailer_diffs.append((i, nat[i], syn[i]))
        else:
            grid_diffs.append((i, nat[i], syn[i]))

print("Category             | Count | Notes")
print("---------------------|-------|------")
print(f"Pre-header (runtime) | {len(pre_header_diffs):5d} | Session pointers (0x0054-0x0253)")
print(f"Header table         | {len(header_diffs):5d} | 32 entries x 0x40 (0x0254-0x0A53)")
print(f"Trailer region       | {len(trailer_diffs):5d} | 0x0A54-0x0A5F")
print(f"Grid/Phase-A         | {len(grid_diffs):5d} | Cell grid overlapping phase-A")
print()

if header_diffs:
    print("Header diffs:")
    for off, n, s in header_diffs:
        entry = (off - 0x0254) // 0x40
        field = (off - 0x0254) % 0x40
        print(f"  entry[{entry}] +0x{field:02X} (0x{off:04X}): nat=0x{n:02X} syn=0x{s:02X}")

if grid_diffs:
    print(f"\nGrid/Phase-A diffs ({len(grid_diffs)}):")
    # Classify by phase-A relative position
    payload_len = int.from_bytes(syn[0x0294:0x0298], 'little')
    pa_start = 0x0298 + payload_len
    for off, n, s in grid_diffs:
        pa_rel = off - pa_start
        slot = pa_rel // 0x40
        slot_off = pa_rel % 0x40
        print(f"  0x{off:04X} (phase-A slot {slot} +0x{slot_off:02X}): nat=0x{n:02X} syn=0x{s:02X}")

# Final verdict
total_structural = len(header_diffs) + len(trailer_diffs) + len(grid_diffs)
print(f"\nTotal structural diffs (excluding pre-header runtime): {total_structural}")
if total_structural <= 2:
    print("VERDICT: Synthetic is structurally equivalent to native.")
    print("The 1-row comment regression is likely NOT in the encoder.")
