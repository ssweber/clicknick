#!/usr/bin/env python3
"""Analyze the later continuation-stream branch in the March 8 plain-comment captures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PAYLOAD_LENGTH_OFFSET = 0x0294
PAYLOAD_BYTES_OFFSET = 0x0298
PHASE_A_LEN = 0xFC8

EMPTY_CAPTURE = "grcecr_empty_native_20260308.bin"
FULLWIRE_CAPTURE = "grcecr_fullwire_native_20260308.bin"

COMMENT_CASES = {
    "short": "grcecr_short_native_20260308.bin",
    "medium": "grcecr_medium_native_20260308.bin",
    "max1400": "grcecr_max1400_native_20260308.bin",
}

REGIONS = {
    "post_payload": (0x08FD, 0x0A60),
    "row0": (0x0A60, 0x1260),
    "row1": (0x1260, 0x1A60),
    "tail": (0x1A60, 0x2000),
}

BLOCK_SIGNATURES = {
    (0, 2, 12, 20, 24, 26, 36, 44, 48, 50, 60): "A",
    (4, 8, 10, 20, 28, 32, 34, 44, 52, 56, 58): "B",
    (4, 12, 16, 18, 28, 36, 40, 42, 52, 60): "C",
}


def _payload_end(data: bytes) -> int:
    return PAYLOAD_BYTES_OFFSET + int.from_bytes(
        data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET],
        "little",
    )


def _phase_a_synth(empty_capture: bytes, target: bytes) -> bytes:
    out = bytearray(empty_capture)
    end = _payload_end(target)
    out[PAYLOAD_LENGTH_OFFSET:end] = target[PAYLOAD_LENGTH_OFFSET:end]
    out[end : end + PHASE_A_LEN] = target[end : end + PHASE_A_LEN]
    return bytes(out)


def _phase_a_plus_fullwire_tail(empty_capture: bytes, fullwire: bytes, target: bytes) -> bytes:
    out = bytearray(_phase_a_synth(empty_capture, target))
    out[0x1260:0x2000] = fullwire[0x1260:0x2000]
    return bytes(out)


def _diff_counts(left: bytes, right: bytes) -> dict[str, int]:
    counts = {
        name: sum(left[i] != right[i] for i in range(start, stop))
        for name, (start, stop) in REGIONS.items()
    }
    counts["full"] = sum(a != b for a, b in zip(left, right))
    return counts


def _diff_count_from(left: bytes, right: bytes, start: int) -> int:
    return sum(left[i] != right[i] for i in range(start, min(len(left), len(right))))


def _classify_block(block: bytes) -> dict[str, object]:
    sig = tuple(idx for idx, value in enumerate(block) if value)
    block_type = BLOCK_SIGNATURES.get(sig, "?")
    values = {idx: block[idx] for idx in sig}
    return {
        "type": block_type,
        "nonzero_offsets": list(sig),
        "values": values,
    }


def _phase_b_blocks(data: bytes) -> list[dict[str, object]]:
    start = _payload_end(data) + PHASE_A_LEN
    blocks = []
    for block_index, off in enumerate(range(start, 0x2000, 0x40)):
        block = data[off : off + 0x40]
        info = _classify_block(block)
        info["block_index"] = block_index
        info["abs_offset"] = off
        blocks.append(info)
    return blocks


def _non_partial_blocks(blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        block
        for block in blocks
        if block["type"] != "?" and block["abs_offset"] + 0x40 <= 0x2000
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=Path("scratchpad/captures"),
        help="Directory containing March 8 canonical captures",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    empty_capture = (args.capture_dir / EMPTY_CAPTURE).read_bytes()
    fullwire_capture = (args.capture_dir / FULLWIRE_CAPTURE).read_bytes()
    captures = {
        name: (args.capture_dir / filename).read_bytes()
        for name, filename in COMMENT_CASES.items()
    }

    synthesis_results = []
    for case_name, target in captures.items():
        phase_a = _phase_a_synth(empty_capture, target)
        phase_a_plus_fullwire = _phase_a_plus_fullwire_tail(empty_capture, fullwire_capture, target)
        synthesis_results.append(
            {
                "case": case_name,
                "payload_end": _payload_end(target),
                "phase_b_start": _payload_end(target) + PHASE_A_LEN,
                "fullwire_window_diffs_from_phase_b_start": _diff_count_from(
                    fullwire_capture,
                    target,
                    _payload_end(target) + PHASE_A_LEN,
                ),
                "phase_a_only_diffs": _diff_counts(phase_a, target),
                "phase_a_plus_fullwire_row1_tail_diffs": _diff_counts(phase_a_plus_fullwire, target),
            }
        )

    phase_b_results = []
    for case_name in ("medium", "max1400"):
        blocks = _phase_b_blocks(captures[case_name])
        full_blocks = _non_partial_blocks(blocks)
        phase_b_results.append(
            {
                "case": case_name,
                "phase_b_start": _payload_end(captures[case_name]) + PHASE_A_LEN,
                "full_block_count": len(full_blocks),
                "type_sequence": "".join(block["type"] for block in full_blocks),
                "first_blocks": full_blocks[:18],
            }
        )

    result = {
        "phase_a_len": PHASE_A_LEN,
        "synthesis_results": synthesis_results,
        "phase_b_results": phase_b_results,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"phase_a_len={PHASE_A_LEN}")
        print()
        for row in synthesis_results:
            print(f"case={row['case']}")
            print(f"payload_end={hex(row['payload_end'])}")
            print(f"phase_b_start={hex(row['phase_b_start'])}")
            print(
                "fullwire_window_diffs_from_phase_b_start="
                f"{row['fullwire_window_diffs_from_phase_b_start']}"
            )
            for label in ("phase_a_only_diffs", "phase_a_plus_fullwire_row1_tail_diffs"):
                print(label)
                for name, value in row[label].items():
                    print(f"{name}={value}")
            print()
        for row in phase_b_results:
            print(f"case={row['case']}")
            print(f"phase_b_start={hex(row['phase_b_start'])}")
            print(f"full_block_count={row['full_block_count']}")
            print(f"type_sequence={row['type_sequence']}")
            for block in row["first_blocks"]:
                print(
                    f"block_index={block['block_index']} "
                    f"abs_offset={hex(block['abs_offset'])} "
                    f"type={block['type']} "
                    f"values={block['values']}"
                )
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
