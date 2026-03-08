#!/usr/bin/env python3
"""Analyze payload-end-anchored continuation streams in the March 8 plain-comment captures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

COMMENT_CASES = {
    "short": "grcecr_short_native_20260308.bin",
    "medium": "grcecr_medium_native_20260308.bin",
    "max1400": "grcecr_max1400_native_20260308.bin",
}

EMPTY_CAPTURE = "grcecr_empty_native_20260308.bin"

BANDS = {
    "post_payload_start": 0x08FD,
    "row0_start": 0x0A60,
    "row1_start": 0x1260,
    "tail_start": 0x1A60,
}


def _payload_end(data: bytes) -> int:
    return 0x0298 + int.from_bytes(data[0x0294:0x0298], "little")


def _common_prefix_len(buffers: list[bytes]) -> int:
    limit = min(len(buf) for buf in buffers)
    idx = 0
    while idx < limit and len({buf[idx] for buf in buffers}) == 1:
        idx += 1
    return idx


def _aligned_stream(data: bytes) -> bytes:
    end = _payload_end(data)
    return data[end:]


def _diff_positions(left: bytes, right: bytes) -> list[int]:
    return [idx for idx, (a, b) in enumerate(zip(left, right)) if a != b]


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

    captures = {
        name: (args.capture_dir / filename).read_bytes()
        for name, filename in COMMENT_CASES.items()
    }
    empty_capture = (args.capture_dir / EMPTY_CAPTURE).read_bytes()

    aligned = {name: _aligned_stream(data) for name, data in captures.items()}
    common_prefix_len = _common_prefix_len(list(aligned.values()))

    band_rel_positions = {
        case_name: {
            band_name: abs_pos - _payload_end(capture)
            for band_name, abs_pos in BANDS.items()
        }
        for case_name, capture in captures.items()
    }

    transplant_results = []
    for donor_name, donor_capture in captures.items():
        donor_stream = aligned[donor_name]
        for target_name, target_capture in captures.items():
            if donor_name == target_name:
                continue
            out = bytearray(empty_capture)
            target_end = _payload_end(target_capture)
            out[0x0294:target_end] = target_capture[0x0294:target_end]
            copy_len = min(len(donor_stream), len(out) - target_end)
            out[target_end : target_end + copy_len] = donor_stream[:copy_len]
            transplant_results.append(
                {
                    "donor": donor_name,
                    "target": target_name,
                    "post_payload_diffs": sum(out[i] != target_capture[i] for i in range(0x08FD, 0x0A60)),
                    "row0_diffs": sum(out[i] != target_capture[i] for i in range(0x0A60, 0x1260)),
                    "row1_diffs": sum(out[i] != target_capture[i] for i in range(0x1260, 0x1A60)),
                    "tail_diffs": sum(out[i] != target_capture[i] for i in range(0x1A60, 0x2000)),
                    "full_diffs": sum(out[i] != target_capture[i] for i in range(len(out))),
                }
            )

    pairwise = []
    case_names = list(captures)
    for idx, left_name in enumerate(case_names):
        for right_name in case_names[idx + 1 :]:
            diffs = _diff_positions(aligned[left_name], aligned[right_name])
            pairwise.append(
                {
                    "left": left_name,
                    "right": right_name,
                    "common_prefix_len": _common_prefix_len([aligned[left_name], aligned[right_name]]),
                    "diff_count": len(diffs),
                    "first_diffs": diffs[:32],
                    "last_diffs": diffs[-32:],
                }
            )

    result = {
        "common_prefix_len_all_cases": common_prefix_len,
        "common_prefix_hex_all_cases": hex(common_prefix_len),
        "band_relative_positions": band_rel_positions,
        "transplant_results": transplant_results,
        "pairwise_aligned_diffs": pairwise,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"common_prefix_len_all_cases={common_prefix_len}")
        print(f"common_prefix_hex_all_cases={hex(common_prefix_len)}")
        print()
        for case_name, positions in band_rel_positions.items():
            print(f"case={case_name}")
            for band_name, rel in positions.items():
                print(f"{band_name}_rel={hex(rel)}")
            print()
        for row in transplant_results:
            print(f"donor={row['donor']} target={row['target']}")
            print(f"post_payload_diffs={row['post_payload_diffs']}")
            print(f"row0_diffs={row['row0_diffs']}")
            print(f"row1_diffs={row['row1_diffs']}")
            print(f"tail_diffs={row['tail_diffs']}")
            print(f"full_diffs={row['full_diffs']}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
