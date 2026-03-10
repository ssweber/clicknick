"""Analyze col-A left-wire in continuation stream records — v2.

Fixed reconstruction: at col 0, right-only means "-" (left is suppressed
by phase-A model, but token is still "-").
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clicknick.ladder.encode import encode_rung, PAYLOAD_BYTES_OFFSET, PAYLOAD_LENGTH_OFFSET, PHASE_A_LEN
from clicknick.ladder.topology import CELL_SIZE, COLS_PER_ROW

REPO = Path(__file__).resolve().parents[1]


def get_payload_len(data: bytes) -> int:
    return struct.unpack_from("<I", data, PAYLOAD_LENGTH_OFFSET)[0]


def get_phase_a_start(data: bytes) -> int:
    return PAYLOAD_BYTES_OFFSET + get_payload_len(data)


def get_cont_start(data: bytes) -> int:
    return get_phase_a_start(data) + PHASE_A_LEN


def extract_comment(data: bytes) -> str:
    payload_len = get_payload_len(data)
    payload = data[PAYLOAD_BYTES_OFFSET : PAYLOAD_BYTES_OFFSET + payload_len]
    prefix_end = payload.find(b"\\fs20 ") + len(b"\\fs20 ")
    suffix_start = payload.find(b"\r\n\\par ")
    if prefix_end > 0 and suffix_start > 0:
        return payload[prefix_end:suffix_start].decode("cp1252")
    return ""


def probe_row0_phase_a(data: bytes) -> list[str]:
    """Reconstruct row 0 condition tokens from phase-A wire flags."""
    pa_start = get_phase_a_start(data)
    tokens = []
    for col_idx in range(31):
        slot_base = pa_start + (col_idx + 31) * 0x40
        left = data[slot_base + 0x21]
        right = data[slot_base + 0x25]
        down = data[slot_base + 0x29]
        if down and (left or right):
            tokens.append("T")
        elif down:
            tokens.append("|")
        elif left or right:
            # At col 0, native only has right (no left); still means "-"
            tokens.append("-")
        else:
            tokens.append("")
    return tokens


def probe_row1_cont(data: bytes, set_idx: int = 0) -> tuple[list[str], bool]:
    """Reconstruct row 1+ tokens and NOP from continuation stream records."""
    cont_start = get_cont_start(data)
    tokens = []
    for col_idx in range(31):
        rec_base = cont_start + set_idx * COLS_PER_ROW * CELL_SIZE + col_idx * CELL_SIZE
        left = data[rec_base + 0x19]
        right = data[rec_base + 0x1D]
        down = data[rec_base + 0x21]
        if down and (left or right):
            tokens.append("T")
        elif down:
            tokens.append("|")
        elif left or right:
            tokens.append("-")
        else:
            tokens.append("")
    # NOP
    af_base = cont_start + set_idx * COLS_PER_ROW * CELL_SIZE + 31 * CELL_SIZE
    has_nop = data[af_base + 0x19] == 1 and data[af_base + 0x1D] == 1
    return tokens, has_nop


def probe_row0_nop(data: bytes) -> bool:
    pa_start = get_phase_a_start(data)
    slot_base = pa_start + (31 + 31) * 0x40  # slot 62 = AF column
    return data[slot_base + 0x25] == 1


def diff_structural(native: bytes, synthetic: bytes, logical_rows: int, label: str):
    """Full structural diff excluding pre-header, comment flags, volatile."""
    pa_start_n = get_phase_a_start(native)
    cont_start_n = get_cont_start(native)

    # Skip ranges: pre-header
    skip_ranges = [(0x0054, 0x0254)]

    # Comment flag offsets to skip
    flag_offsets = set()
    flag_offsets.add(0x026B)  # header entry0 +0x17
    for k in range(63):
        flag_offsets.add(pa_start_n + 0x13 + 0x40 * k)
    for set_idx in range(logical_rows - 1):
        for col_idx in range(COLS_PER_ROW):
            rec_base = cont_start_n + set_idx * COLS_PER_ROW * CELL_SIZE + col_idx * CELL_SIZE
            flag_offsets.add(rec_base + 0x0B)
    # Volatile header bytes
    for entry_idx in range(32):
        base = 0x0254 + entry_idx * 0x40
        flag_offsets.add(base + 0x05)
        flag_offsets.add(base + 0x11)

    max_len = max(len(native), len(synthetic))
    diffs = []
    for i in range(max_len):
        if any(s <= i < e for s, e in skip_ranges):
            continue
        if i in flag_offsets:
            continue
        n = native[i] if i < len(native) else None
        s = synthetic[i] if i < len(synthetic) else None
        if n != s:
            # Identify region
            region = "?"
            if i < 0x0254:
                region = "early"
            elif i < 0x0254 + 32 * 0x40:
                entry = (i - 0x0254) // 0x40
                local = (i - 0x0254) % 0x40
                region = f"hdr[{entry}]+0x{local:02X}"
            elif i < pa_start_n:
                region = "payload"
            elif i < cont_start_n:
                slot = (i - pa_start_n) // 0x40
                local = (i - pa_start_n) % 0x40
                region = f"phA[{slot}]+0x{local:02X}"
            elif i < cont_start_n + (logical_rows - 1) * COLS_PER_ROW * CELL_SIZE:
                rel = i - cont_start_n
                set_idx = rel // (COLS_PER_ROW * CELL_SIZE)
                col_idx = (rel % (COLS_PER_ROW * CELL_SIZE)) // CELL_SIZE
                local = rel % CELL_SIZE
                region = f"cont[s{set_idx}c{col_idx}]+0x{local:02X}"
            else:
                region = "tail"
            n_str = f"0x{n:02X}" if n is not None else "N/A"
            s_str = f"0x{s:02X}" if s is not None else "N/A"
            diffs.append((i, n_str, s_str, region))

    return diffs


def analyze(native_path: Path, label: str):
    native = native_path.read_bytes()
    comment = extract_comment(native)
    logical_rows = 2  # All our targets are 2-row

    row0_tokens = probe_row0_phase_a(native)
    row1_tokens, row1_nop = probe_row1_cont(native)
    row0_nop = probe_row0_nop(native)

    af_tokens = ["NOP" if row0_nop else "", "NOP" if row1_nop else ""]

    print(f"\n{'='*80}")
    print(f"{label}")
    print(f"File: {native_path.relative_to(REPO)}")
    print(f"Comment: {comment!r}")
    print(f"Row 0 wire cols: {[i for i, t in enumerate(row0_tokens) if t]} ({sum(1 for t in row0_tokens if t)} wired)")
    print(f"Row 1 wire cols: {[i for i, t in enumerate(row1_tokens) if t]} ({sum(1 for t in row1_tokens if t)} wired)")
    print(f"AF: row0={'NOP' if row0_nop else 'empty'}, row1={'NOP' if row1_nop else 'empty'}")

    # Check col 0 specifically in cont records
    cont_start = get_cont_start(native)
    col0_left = native[cont_start + 0x19]
    col0_right = native[cont_start + 0x1D]
    col0_down = native[cont_start + 0x21]
    print(f"\nCont col 0 wire: L={col0_left} R={col0_right} D={col0_down}")

    synthetic = encode_rung(logical_rows, [row0_tokens, row1_tokens], af_tokens, comment=comment)

    print(f"Size: native={len(native)} synth={len(synthetic)}")
    print(f"Payload len: native=0x{get_payload_len(native):04X} synth=0x{get_payload_len(bytes(synthetic)):04X}")

    # Structural diff
    diffs = diff_structural(native, bytes(synthetic), logical_rows, label)
    print(f"\nStructural diffs: {len(diffs)}")
    for off, n, s, region in diffs:
        print(f"  0x{off:04X}: native={n} synth={s}  ({region})")

    return len(diffs)


# ============================================================================
# Analyze all 2-row comment captures with wire
# ============================================================================

total = {}
for name in [
    "tests/fixtures/ladder_captures/verify-comment-2row-sparse-wire.bin",
    "scratchpad/captures/native-comment-2row-wire.bin",
    "scratchpad/captures/native-comment-2row-vert-c.bin",
]:
    path = REPO / name
    if path.exists():
        total[name] = analyze(path, name)

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")
for name, count in total.items():
    print(f"  {name}: {count} structural diffs")

print(f"\n--- Col-A left-wire analysis ---")
print("Neither 2-row capture has wire at col 0 on continuation rows.")
print("The col_idx > 0 guard question remains UNTESTED from native data.")
print("Verify entries with col-A wire are needed to resolve this.")
