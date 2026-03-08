#!/usr/bin/env python3
"""Summarize the explicit March 8 no-comment wireframe band templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_TEMPLATE_FILE = Path("scratchpad/phase3_wireframe_band_templates_20260308.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template-file",
        type=Path,
        default=DEFAULT_TEMPLATE_FILE,
        help="JSON file containing explicit March 8 band templates",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    raw = json.loads(args.template_file.read_text())

    rows = []
    total_changed = 0
    for band_name, spec in raw["bands"].items():
        row = {
            "band_name": band_name,
            "start": spec["start"],
            "stop": spec["stop"],
            "length": spec["length"],
            "changed_byte_count_vs_empty_1row": spec["changed_byte_count_vs_empty_1row"],
        }
        rows.append(row)
        total_changed += spec["changed_byte_count_vs_empty_1row"]

    summary = {
        "base_file": raw["base_file"],
        "band_count": len(rows),
        "total_changed_byte_count_vs_empty_1row": total_changed,
        "bands": rows,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"base_file={summary['base_file']}")
        print(f"band_count={summary['band_count']}")
        print(f"total_changed_byte_count_vs_empty_1row={summary['total_changed_byte_count_vs_empty_1row']}")
        print()
        for row in rows:
            print(f"band_name={row['band_name']}")
            print(f"range=0x{row['start']:04X}..0x{row['stop'] - 1:04X}")
            print(f"length={row['length']}")
            print(f"changed_byte_count_vs_empty_1row={row['changed_byte_count_vs_empty_1row']}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
