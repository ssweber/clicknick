"""Analyze col-A left-wire in continuation stream records.

Compare native captures against synthetic encode_rung() output for
multi-row comment rungs with wire topology. Focus on whether col 0
(column A) has +0x19 (left wire) set in continuation stream records.
"""

import struct
import sys
from pathlib import Path

# Add src to path
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


def dump_cont_record(data: bytes, set_idx: int, col_idx: int, label: str = "") -> dict:
    """Extract key fields from a continuation stream record."""
    cont_start = get_cont_start(data)
    rec_base = cont_start + set_idx * COLS_PER_ROW * CELL_SIZE + col_idx * CELL_SIZE
    rec = data[rec_base : rec_base + CELL_SIZE]
    return {
        "label": label,
        "set": set_idx,
        "col": col_idx,
        "col_idx_byte": rec[0x01],
        "row_sentinel": rec[0x05],
        "left_wire_0x19": rec[0x19],
        "right_wire_0x1D": rec[0x1D],
        "down_0x21": rec[0x21],
        "nop_row_enable_0x15": rec[0x15],
    }


def diff_buffers(native: bytes, synthetic: bytes, label: str, skip_ranges: list[tuple[int, int]] | None = None):
    """Diff two buffers, reporting offset differences."""
    skip = skip_ranges or []
    min_len = min(len(native), len(synthetic))
    max_len = max(len(native), len(synthetic))

    diffs = []
    for i in range(max_len):
        # Check if in skip range
        in_skip = any(start <= i < end for start, end in skip)
        if in_skip:
            continue

        n = native[i] if i < len(native) else None
        s = synthetic[i] if i < len(synthetic) else None
        if n != s:
            diffs.append((i, n, s))

    return diffs


def analyze_capture(native_path: Path, comment_text: str, condition_rows, af_tokens, logical_rows: int, label: str):
    """Analyze a single native capture vs synthetic."""
    print(f"\n{'='*80}")
    print(f"CAPTURE: {label}")
    print(f"File: {native_path.relative_to(REPO)}")
    print(f"Comment: {comment_text!r}")
    print(f"Rows: {logical_rows}")
    print(f"{'='*80}")

    native = native_path.read_bytes()
    synthetic = encode_rung(logical_rows, condition_rows, af_tokens, comment=comment_text)

    print(f"Native size:    {len(native)}")
    print(f"Synthetic size: {len(synthetic)}")

    # Phase-A and cont stream locations
    native_payload_len = get_payload_len(native)
    synth_payload_len = get_payload_len(bytes(synthetic))
    print(f"Native payload len:    {native_payload_len} (0x{native_payload_len:04X})")
    print(f"Synthetic payload len: {synth_payload_len} (0x{synth_payload_len:04X})")

    native_cont_start = get_cont_start(native)
    synth_cont_start = get_cont_start(bytes(synthetic))
    print(f"Native cont start:    0x{native_cont_start:04X}")
    print(f"Synthetic cont start: 0x{synth_cont_start:04X}")

    # Dump continuation stream records for col 0 (column A) from each set
    print(f"\n--- Continuation stream col 0 (Column A) records ---")
    for set_idx in range(logical_rows - 1):
        n_rec = dump_cont_record(native, set_idx, 0, "native")
        s_rec = dump_cont_record(bytes(synthetic), set_idx, 0, "synthetic")
        print(f"\n  Set {set_idx} (row {set_idx + 1}), Col 0 (A):")
        print(f"    Native:    left=0x{n_rec['left_wire_0x19']:02X}  right=0x{n_rec['right_wire_0x1D']:02X}  down=0x{n_rec['down_0x21']:02X}")
        print(f"    Synthetic: left=0x{s_rec['left_wire_0x19']:02X}  right=0x{s_rec['right_wire_0x1D']:02X}  down=0x{s_rec['down_0x21']:02X}")
        if n_rec['left_wire_0x19'] != s_rec['left_wire_0x19']:
            print(f"    *** MISMATCH at col 0 left wire (+0x19): native=0x{n_rec['left_wire_0x19']:02X} vs synthetic=0x{s_rec['left_wire_0x19']:02X} ***")

    # Dump ALL wire-bearing cont records for reference
    print(f"\n--- All wire-bearing continuation stream records ---")
    for set_idx in range(logical_rows - 1):
        for col_idx in range(COLS_PER_ROW):
            n_rec = dump_cont_record(native, set_idx, col_idx)
            if n_rec['left_wire_0x19'] or n_rec['right_wire_0x1D'] or n_rec['down_0x21']:
                s_rec = dump_cont_record(bytes(synthetic), set_idx, col_idx)
                match = "OK" if (n_rec['left_wire_0x19'] == s_rec['left_wire_0x19'] and
                                  n_rec['right_wire_0x1D'] == s_rec['right_wire_0x1D'] and
                                  n_rec['down_0x21'] == s_rec['down_0x21']) else "MISMATCH"
                print(f"  Set {set_idx} Col {col_idx:2d}: native L={n_rec['left_wire_0x19']} R={n_rec['right_wire_0x1D']} D={n_rec['down_0x21']}  |  synth L={s_rec['left_wire_0x19']} R={s_rec['right_wire_0x1D']} D={s_rec['down_0x21']}  [{match}]")

    # Also check if synthetic has wire records that native doesn't
    for set_idx in range(logical_rows - 1):
        for col_idx in range(COLS_PER_ROW):
            s_rec = dump_cont_record(bytes(synthetic), set_idx, col_idx)
            if s_rec['left_wire_0x19'] or s_rec['right_wire_0x1D'] or s_rec['down_0x21']:
                n_rec = dump_cont_record(native, set_idx, col_idx)
                if not (n_rec['left_wire_0x19'] or n_rec['right_wire_0x1D'] or n_rec['down_0x21']):
                    print(f"  Set {set_idx} Col {col_idx:2d}: SYNTHETIC-ONLY L={s_rec['left_wire_0x19']} R={s_rec['right_wire_0x1D']} D={s_rec['down_0x21']}")

    # Full diff (excluding pre-header 0x0054-0x0253 and comment flag value diffs)
    # Skip ranges: pre-header (0x0054-0x0253)
    skip_ranges = [(0x0054, 0x0254)]

    # Also identify comment flag offsets to skip
    # Header entry0 +0x17 = 0x0254 + 0x17 = 0x026B (comment flag byte)
    # Phase-A periodic: phase_a_start + 0x13 + 0x40*k for k in 0..62
    # Cont records +0x0B
    flag_offsets = set()
    flag_offsets.add(0x026B)  # header entry0 +0x17

    native_pa_start = get_phase_a_start(native)
    for k in range(63):
        flag_offsets.add(native_pa_start + 0x13 + 0x40 * k)

    for set_idx in range(logical_rows - 1):
        for col_idx in range(COLS_PER_ROW):
            rec_base = native_cont_start + set_idx * COLS_PER_ROW * CELL_SIZE + col_idx * CELL_SIZE
            flag_offsets.add(rec_base + 0x0B)

    # Add volatile header bytes (+0x05, +0x11 on all 32 entries)
    for entry_idx in range(32):
        base = 0x0254 + entry_idx * 0x40
        flag_offsets.add(base + 0x05)
        flag_offsets.add(base + 0x11)

    diffs = diff_buffers(native, bytes(synthetic), label, skip_ranges)

    # Filter out comment flag diffs
    structural_diffs = [(off, n, s) for off, n, s in diffs if off not in flag_offsets]

    print(f"\n--- Structural diff summary (excl. pre-header 0x0054-0x0253, comment flag, volatile) ---")
    print(f"Total raw diffs: {len(diffs)}")
    print(f"Structural diffs: {len(structural_diffs)}")
    if structural_diffs:
        for off, n, s in structural_diffs[:50]:
            n_str = f"0x{n:02X}" if n is not None else "N/A"
            s_str = f"0x{s:02X}" if s is not None else "N/A"
            # Identify region
            region = "unknown"
            if off < 0x0054:
                region = "pre-header-early"
            elif off < 0x0254:
                region = "pre-header"
            elif off < 0x0254 + 32 * 0x40:
                entry = (off - 0x0254) // 0x40
                local = (off - 0x0254) % 0x40
                region = f"header[{entry}]+0x{local:02X}"
            elif off < PAYLOAD_LENGTH_OFFSET:
                region = f"between-header-payload"
            elif off < native_pa_start:
                region = f"payload"
            elif off < native_cont_start:
                slot = (off - native_pa_start) // 0x40
                local = (off - native_pa_start) % 0x40
                region = f"phase-A slot[{slot}]+0x{local:02X}"
            elif off < native_cont_start + (logical_rows - 1) * COLS_PER_ROW * CELL_SIZE:
                rel = off - native_cont_start
                set_idx = rel // (COLS_PER_ROW * CELL_SIZE)
                col_idx = (rel % (COLS_PER_ROW * CELL_SIZE)) // CELL_SIZE
                local = rel % CELL_SIZE
                region = f"cont[set{set_idx}][col{col_idx}]+0x{local:02X}"
            else:
                region = f"post-cont"
            print(f"  0x{off:04X}: native={n_str} synth={s_str}  ({region})")
        if len(structural_diffs) > 50:
            print(f"  ... and {len(structural_diffs) - 50} more")

    return len(structural_diffs)


# ============================================================================
# Capture 1: verify-comment-2row-sparse-wire.bin
# 2-row, wire at B and D on both rows
# ============================================================================

# Row 0: wire at B and D -> ",-, ,-,..." (col 0 empty, col 1 wire, col 2 empty, col 3 wire, rest empty)
# Row 1: wire at B and D -> same pattern
sparse_row = [""] * 31
sparse_row[1] = "-"  # B
sparse_row[3] = "-"  # D
condition_rows_sparse = [sparse_row[:], sparse_row[:]]

analyze_capture(
    REPO / "tests/fixtures/ladder_captures/verify-comment-2row-sparse-wire.bin",
    "Test comment",  # From the entry - need to check actual comment
    condition_rows_sparse,
    ["", ""],
    2,
    "verify-comment-2row-sparse-wire",
)

# ============================================================================
# Capture 2: native-comment-2row-wire.bin
# 2-row, full wire row 0, sparse row 1
# ============================================================================

# Row 0: full wire (all 31 cols have "-")
# Row 1: sparse wire (based on the capture name, need to check)
full_wire_row = ["-"] * 31
# Row 1: we need to figure out the actual topology from the capture

# Let's just read the native capture and figure out what wires are set
native_2row = (REPO / "scratchpad/captures/native-comment-2row-wire.bin").read_bytes()

# Check phase-A wire flags for row 0
pa_start = get_phase_a_start(native_2row)
print(f"\n{'='*80}")
print("PROBING native-comment-2row-wire.bin row 0 phase-A wire topology")
print(f"{'='*80}")
print(f"Phase-A start: 0x{pa_start:04X}")

row0_wires = []
for col_idx in range(31):
    slot_base = pa_start + (col_idx + 31) * 0x40
    left = native_2row[slot_base + 0x21]
    right = native_2row[slot_base + 0x25]
    down = native_2row[slot_base + 0x29]
    if left or right or down:
        row0_wires.append((col_idx, left, right, down))
        if col_idx < 10:
            print(f"  Row 0 Col {col_idx}: L={left} R={right} D={down}")

print(f"  Row 0: {len(row0_wires)} cols with wire flags")

# Check cont stream for row 1
cont_start = get_cont_start(native_2row)
print(f"Cont start: 0x{cont_start:04X}")

row1_wires = []
for col_idx in range(32):
    rec_base = cont_start + col_idx * CELL_SIZE
    left = native_2row[rec_base + 0x19]
    right = native_2row[rec_base + 0x1D]
    down = native_2row[rec_base + 0x21]
    if left or right or down:
        row1_wires.append((col_idx, left, right, down))
        print(f"  Row 1 Col {col_idx}: L={left} R={right} D={down}")

print(f"  Row 1: {len(row1_wires)} cols with wire flags")

# Now build matching condition rows
row0 = [""] * 31
for col_idx, left, right, down in row0_wires:
    if left and right and down:
        row0[col_idx] = "T"
    elif left and right:
        row0[col_idx] = "-"
    elif down:
        row0[col_idx] = "|"

row1 = [""] * 31
for col_idx, left, right, down in row1_wires:
    if col_idx >= 31:
        continue  # AF column
    if left and right and down:
        row1[col_idx] = "T"
    elif left and right:
        row1[col_idx] = "-"
    elif down:
        row1[col_idx] = "|"
    elif right:
        # right-only at col 0? that means wire but no left
        row1[col_idx] = "-"  # We'll check

# Check what comment text is in the native capture
payload_len = get_payload_len(native_2row)
payload = native_2row[PAYLOAD_BYTES_OFFSET : PAYLOAD_BYTES_OFFSET + payload_len]
# Extract text between prefix and suffix
# The prefix ends with "\\fs20 " and suffix starts with "\r\n\\par"
prefix_end = payload.find(b"\\fs20 ") + len(b"\\fs20 ")
suffix_start = payload.find(b"\r\n\\par ")
if prefix_end > 0 and suffix_start > 0:
    comment_text = payload[prefix_end:suffix_start].decode("cp1252")
    print(f"Comment text: {comment_text!r}")
else:
    comment_text = "Test comment"
    print(f"Could not extract comment, using default: {comment_text!r}")

# Check NOP on AF
# Phase-A slot 62 for row 0 NOP
af_slot_base = pa_start + (31 + 31) * 0x40
row0_nop = native_2row[af_slot_base + 0x25]
print(f"Row 0 NOP (phase-A slot 62 +0x25): {row0_nop}")

# Cont record col 31 for row 1 NOP
af_rec_base = cont_start + 31 * CELL_SIZE
row1_nop_left = native_2row[af_rec_base + 0x19]
row1_nop_right = native_2row[af_rec_base + 0x1D]
print(f"Row 1 NOP (cont col31 +0x19={row1_nop_left}, +0x1D={row1_nop_right})")

af_tokens_2row = ["", ""]
if row0_nop:
    af_tokens_2row[0] = "NOP"
if row1_nop_left and row1_nop_right:
    af_tokens_2row[1] = "NOP"

analyze_capture(
    REPO / "scratchpad/captures/native-comment-2row-wire.bin",
    comment_text,
    [row0, row1],
    af_tokens_2row,
    2,
    "native-comment-2row-wire",
)


# ============================================================================
# Also check the promoted fixture for sparse wire
# ============================================================================

# Check what comment text the promoted fixture has
promoted = (REPO / "tests/fixtures/ladder_captures/verify-comment-2row-sparse-wire.bin").read_bytes()
payload_len_p = get_payload_len(promoted)
payload_p = promoted[PAYLOAD_BYTES_OFFSET : PAYLOAD_BYTES_OFFSET + payload_len_p]
prefix_end_p = payload_p.find(b"\\fs20 ") + len(b"\\fs20 ")
suffix_start_p = payload_p.find(b"\r\n\\par ")
if prefix_end_p > 0 and suffix_start_p > 0:
    comment_p = payload_p[prefix_end_p:suffix_start_p].decode("cp1252")
    print(f"\nPromoted sparse-wire comment: {comment_p!r}")

    # Re-run with correct comment text
    analyze_capture(
        REPO / "tests/fixtures/ladder_captures/verify-comment-2row-sparse-wire.bin",
        comment_p,
        condition_rows_sparse,
        ["", ""],
        2,
        "verify-comment-2row-sparse-wire (correct comment)",
    )
