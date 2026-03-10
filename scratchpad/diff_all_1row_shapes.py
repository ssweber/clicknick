"""Diff all 1-row comment shapes: empty, NOP, fullwire, partial-wire.
Report ONLY structural diffs (exclude pre-header runtime bytes 0x0054-0x0253).
"""

from pathlib import Path
from clicknick.ladder.encode import encode_rung, PAYLOAD_BYTES_OFFSET, PAYLOAD_LENGTH_OFFSET

shapes = [
    (
        "1-row EMPTY (Hello world)",
        "scratchpad/captures/native-comment-helloworld.bin",
        1, [[""] * 31], [""], "Hello world",
    ),
    (
        "1-row NOP-only (Hello NOP)",
        "scratchpad/captures/native-comment-nop.bin",
        1, [[""] * 31], ["NOP"], "Hello NOP",
    ),
    (
        "1-row FULLWIRE (Partial wires)",
        "scratchpad/captures/native-comment-fullwire.bin",
        1, [["-"] * 31], [""], "Partial wires",
    ),
    (
        "1-row NOP+FULLWIRE (Wires and NOP)",
        "scratchpad/captures/native-comment-wire-nop.bin",
        1, [["-"] * 31], ["NOP"], "Wires and NOP",
    ),
    (
        "1-row PARTIAL (dash B, D)",
        "scratchpad/captures/native-comment-partial-wire-v2.bin",
        1, [["", "-", "", "-"] + [""] * 27], [""], "Partial wires",
    ),
    (
        "1-row NOP-only (native-comment-nop-only)",
        "tests/fixtures/ladder_captures/native-comment-nop-only.bin",
        1, [[""] * 31], ["NOP"], "Partial wires",
    ),
]

for label, nat_path, rows, cond, af, comment in shapes:
    path = Path(nat_path)
    if not path.exists():
        print(f"\n{label}: FILE NOT FOUND ({nat_path})")
        continue

    nat = path.read_bytes()
    syn = encode_rung(rows, cond, af, comment=comment)

    if len(nat) != len(syn):
        print(f"\n{label}: SIZE MISMATCH nat={len(nat)} syn={len(syn)}")
        continue

    # Compare payload lengths
    nat_plen = int.from_bytes(nat[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], 'little')
    syn_plen = int.from_bytes(syn[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], 'little')

    # Structural diffs (exclude 0x0054-0x0253 pre-header runtime)
    structural_diffs = []
    for i in range(len(nat)):
        if 0x0054 <= i < 0x0254:
            continue  # Skip pre-header runtime
        if nat[i] != syn[i]:
            structural_diffs.append((i, nat[i], syn[i]))

    print(f"\n{label}:")
    print(f"  Payload len: nat={nat_plen} syn={syn_plen} (diff={syn_plen - nat_plen})")
    print(f"  Comment flag: nat=0x{nat[0x0254+0x17]:02X} syn=0x{syn[0x0254+0x17]:02X}")
    print(f"  Structural diffs: {len(structural_diffs)}")

    if nat_plen != syn_plen:
        print(f"  *** PAYLOAD LENGTH MISMATCH — skipping byte-level comparison")
        print(f"  (Different RTF prefix used in this native capture)")
        continue

    for off, n, s in structural_diffs:
        region = "unknown"
        detail = ""
        if off < 0x0054:
            region = "magic/path"
        elif off < 0x0254:
            region = "pre-header"
        elif off < 0x0A54:
            entry = (off - 0x0254) // 0x40
            field = (off - 0x0254) % 0x40
            region = f"header[{entry}]+0x{field:02X}"
        elif off < 0x0A60:
            region = "trailer"
        else:
            pa_start = PAYLOAD_BYTES_OFFSET + syn_plen
            pa_rel = off - pa_start
            slot = pa_rel // 0x40
            slot_off = pa_rel % 0x40
            region = f"phaseA slot {slot} +0x{slot_off:02X}"
        print(f"    0x{off:04X} [{region}]: nat=0x{n:02X} syn=0x{s:02X}")
