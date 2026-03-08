#!/usr/bin/env python3
"""Probe whether the March 8 max1400 native can serve as a shorter-comment template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REGIONS = {
    "payload_window": (0x0294, 0x08FD),
    "metadata_post_payload_window": (0x08FD, 0x0A54),
    "gap_band": (0x0A54, 0x0A60),
    "row0_band": (0x0A60, 0x1260),
    "row1_band": (0x1260, 0x1A60),
    "tail_band": (0x1A60, 0x2000),
}

TARGETS = {
    "short": "grcecr_short_native_20260308.bin",
    "medium": "grcecr_medium_native_20260308.bin",
}

MAX1400 = "grcecr_max1400_native_20260308.bin"


def _diff_counts(left: bytes, right: bytes) -> dict[str, int]:
    counts = {
        name: sum(left[i] != right[i] for i in range(start, stop))
        for name, (start, stop) in REGIONS.items()
    }
    counts["full"] = sum(x != y for x, y in zip(left, right))
    return counts


def _probe_len_payload_only(max1400: bytes, target: bytes) -> bytes:
    out = bytearray(max1400)
    payload_len = int.from_bytes(target[0x0294:0x0298], "little")
    end = 0x0298 + payload_len
    out[0x0294:end] = target[0x0294:end]
    return bytes(out)


def _probe_through_gap(max1400: bytes, target: bytes) -> bytes:
    out = bytearray(max1400)
    out[0x0294:0x0A60] = target[0x0294:0x0A60]
    return bytes(out)


def _probe_through_row0(max1400: bytes, target: bytes) -> bytes:
    out = bytearray(max1400)
    out[0x0294:0x1260] = target[0x0294:0x1260]
    return bytes(out)


def _probe_through_row1(max1400: bytes, target: bytes) -> bytes:
    out = bytearray(max1400)
    out[0x0294:0x1A60] = target[0x0294:0x1A60]
    return bytes(out)


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
    max1400 = (args.capture_dir / MAX1400).read_bytes()

    results = []
    for name, filename in TARGETS.items():
        target = (args.capture_dir / filename).read_bytes()
        len_payload_only = _probe_len_payload_only(max1400, target)
        through_gap = _probe_through_gap(max1400, target)
        through_row0 = _probe_through_row0(max1400, target)
        through_row1 = _probe_through_row1(max1400, target)
        results.append(
            {
                "target": name,
                "target_file": filename,
                "max1400_vs_target": _diff_counts(max1400, target),
                "probe_len_payload_only_vs_target": _diff_counts(len_payload_only, target),
                "probe_through_gap_vs_target": _diff_counts(through_gap, target),
                "probe_through_row0_vs_target": _diff_counts(through_row0, target),
                "probe_through_row1_vs_target": _diff_counts(through_row1, target),
            }
        )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f"target={result['target']}")
            for bucket in (
                "max1400_vs_target",
                "probe_len_payload_only_vs_target",
                "probe_through_gap_vs_target",
                "probe_through_row0_vs_target",
                "probe_through_row1_vs_target",
            ):
                print(bucket)
                for name, value in result[bucket].items():
                    print(f"{name}={value}")
                print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
