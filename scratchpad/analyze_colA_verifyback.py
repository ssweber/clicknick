"""Analyze verify-back of 2-row comment with wire at col A on both rows."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clicknick.ladder.encode import encode_rung, PAYLOAD_BYTES_OFFSET, PAYLOAD_LENGTH_OFFSET, PHASE_A_LEN
from clicknick.ladder.topology import CELL_SIZE, COLS_PER_ROW

REPO = Path(__file__).resolve().parents[1]

vb = (REPO / "scratchpad/captures/verify-comment-2row-colA-wire_verify_back_20260310_203216.bin").read_bytes()

payload_len = struct.unpack_from("<I", vb, PAYLOAD_LENGTH_OFFSET)[0]
pa_start = PAYLOAD_BYTES_OFFSET + payload_len
cont_start = pa_start + PHASE_A_LEN

print(f"Verify-back size: {len(vb)}")
print(f"Payload len: 0x{payload_len:04X}")
print(f"Phase-A start: 0x{pa_start:04X}")
print(f"Cont start: 0x{cont_start:04X}")

# Extract comment
payload = vb[PAYLOAD_BYTES_OFFSET : PAYLOAD_BYTES_OFFSET + payload_len]
pe = payload.find(b"\\fs20 ") + len(b"\\fs20 ")
se = payload.find(b"\r\n\\par ")
if pe > 0 and se > 0:
    print(f"Comment: {payload[pe:se].decode('cp1252')!r}")

# Row 0 phase-A wire at col 0
print(f"\n--- Row 0 (phase-A stride) ---")
for col_idx in range(5):
    sb = pa_start + (col_idx + 31) * 0x40
    left = vb[sb + 0x21]
    right = vb[sb + 0x25]
    down = vb[sb + 0x29]
    print(f"  Col {col_idx}: left={left} right={right} down={down}")

# Row 1 continuation stream at col 0
print(f"\n--- Row 1 (continuation stream) ---")
for col_idx in range(5):
    rb = cont_start + col_idx * CELL_SIZE
    left = vb[rb + 0x19]
    right = vb[rb + 0x1D]
    down = vb[rb + 0x21]
    print(f"  Col {col_idx}: left(+0x19)={left} right(+0x1D)={right} down(+0x21)={down}")

# Generate synthetic for comparison
# Row 0: wire at col A only -> "-" at col 0, empty rest
# Row 1: wire at col A only -> "-" at col 0, empty rest
row0 = [""] * 31
row0[0] = "-"
row1 = [""] * 31
row1[0] = "-"

synth = encode_rung(2, [row0, row1], ["", ""], comment="Col A test")

synth_pa_start = PAYLOAD_BYTES_OFFSET + struct.unpack_from("<I", synth, PAYLOAD_LENGTH_OFFSET)[0]
synth_cont_start = synth_pa_start + PHASE_A_LEN

print(f"\n--- Synthetic Row 1 (continuation stream) ---")
for col_idx in range(5):
    rb = synth_cont_start + col_idx * CELL_SIZE
    left = synth[rb + 0x19]
    right = synth[rb + 0x1D]
    down = synth[rb + 0x21]
    print(f"  Col {col_idx}: left(+0x19)={left} right(+0x1D)={right} down(+0x21)={down}")

# Key question: does verify-back col 0 cont record have left=0 or left=1?
vb_col0_left = vb[cont_start + 0x19]
synth_col0_left = synth[synth_cont_start + 0x19]
print(f"\n=== ANSWER ===")
print(f"Verify-back col 0 cont left(+0x19): {vb_col0_left}")
print(f"Synthetic   col 0 cont left(+0x19): {synth_col0_left}")
if vb_col0_left == 0 and synth_col0_left == 1:
    print("-> col_idx > 0 guard IS NEEDED in continuation stream path")
elif vb_col0_left == 1 and synth_col0_left == 1:
    print("-> col_idx > 0 guard is NOT needed (both have left=1)")
elif vb_col0_left == 0 and synth_col0_left == 0:
    print("-> col_idx > 0 guard is NOT needed (both already 0 — encoder may not be writing wire at col 0?)")
else:
    print(f"-> Unexpected: vb={vb_col0_left} synth={synth_col0_left}")

# Full structural diff
print(f"\n--- Full structural diff (verify-back vs synthetic) ---")
# Skip pre-header and comment flag offsets
skip = set()
for i in range(0x0054, 0x0254):
    skip.add(i)
skip.add(0x026B)  # header entry0 +0x17
for k in range(63):
    skip.add(pa_start + 0x13 + 0x40 * k)
for col_idx in range(32):
    skip.add(cont_start + col_idx * CELL_SIZE + 0x0B)
for entry_idx in range(32):
    base = 0x0254 + entry_idx * 0x40
    skip.add(base + 0x05)
    skip.add(base + 0x11)

diffs = []
for i in range(max(len(vb), len(synth))):
    if i in skip:
        continue
    v = vb[i] if i < len(vb) else None
    s = synth[i] if i < len(synth) else None
    if v != s:
        region = "?"
        if i < pa_start:
            if i >= 0x0254 and i < 0x0254 + 32 * 0x40:
                entry = (i - 0x0254) // 0x40
                local = (i - 0x0254) % 0x40
                region = f"hdr[{entry}]+0x{local:02X}"
            else:
                region = f"pre-phA"
        elif i < cont_start:
            slot = (i - pa_start) // 0x40
            local = (i - pa_start) % 0x40
            region = f"phA[{slot}]+0x{local:02X}"
        elif i < cont_start + COLS_PER_ROW * CELL_SIZE:
            col = (i - cont_start) // CELL_SIZE
            local = (i - cont_start) % CELL_SIZE
            region = f"cont[c{col}]+0x{local:02X}"
        else:
            region = "tail"
        v_str = f"0x{v:02X}" if v is not None else "N/A"
        s_str = f"0x{s:02X}" if s is not None else "N/A"
        diffs.append(f"  0x{i:04X}: vb={v_str} synth={s_str}  ({region})")

print(f"Total structural diffs: {len(diffs)}")
for d in diffs:
    print(d)
