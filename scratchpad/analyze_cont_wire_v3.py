"""Quick check: native-comment-2row-vert-c col 0 phase-A left wire detail."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clicknick.ladder.encode import PAYLOAD_BYTES_OFFSET, PAYLOAD_LENGTH_OFFSET, PHASE_A_LEN

REPO = Path(__file__).resolve().parents[1]

# Compare col 0 left wire (+0x21) across both 2-row captures
for name in ["native-comment-2row-wire", "native-comment-2row-vert-c"]:
    path = REPO / f"scratchpad/captures/{name}.bin"
    data = path.read_bytes()
    payload_len = struct.unpack_from("<I", data, PAYLOAD_LENGTH_OFFSET)[0]
    pa_start = PAYLOAD_BYTES_OFFSET + payload_len

    print(f"\n{name} (payload_len=0x{payload_len:04X}, pa_start=0x{pa_start:04X})")

    # Col 0 phase-A slot = 31
    slot_base = pa_start + 31 * 0x40
    print(f"  Col 0 (slot 31): left(+0x21)={data[slot_base + 0x21]} right(+0x25)={data[slot_base + 0x25]} down(+0x29)={data[slot_base + 0x29]}")

    # Also check if there's a T junction on row 0
    for col_idx in range(31):
        sb = pa_start + (col_idx + 31) * 0x40
        down = data[sb + 0x29]
        if down:
            left = data[sb + 0x21]
            right = data[sb + 0x25]
            print(f"  Col {col_idx} has DOWN: left={left} right={right} down={down} -> {'T' if (left or right) else '|'}")

    # AF slot (62)
    af_sb = pa_start + 62 * 0x40
    print(f"  AF (slot 62): left(+0x21)={data[af_sb + 0x21]} right(+0x25)={data[af_sb + 0x25]}")
