"""Load a binary payload into Click's private clipboard format (522).

Examples:
  uv run python devtools/clipboard_load.py scratchpad/captures/two_series_second_immediate_back_split_after_row0_profile_patch_profile_1a_ff_1b_ff.bin
  uv run python devtools/clipboard_load.py scratchpad/captures/smoke_simple_native.bin --first-record
"""

from __future__ import annotations

import argparse
from pathlib import Path

from clicknick.ladder import copy_to_clipboard

BUFFER_SIZE = 8192


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Path to .bin payload")
    parser.add_argument(
        "--first-record",
        action="store_true",
        help="Copy only the first 8192-byte record.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    path = Path(args.path)
    data = path.read_bytes()
    if args.first_record:
        if len(data) < BUFFER_SIZE:
            raise ValueError(f"{path}: payload too short for first record ({len(data)} bytes)")
        data = data[:BUFFER_SIZE]
    copy_to_clipboard(data)
    print(f"Loaded {len(data)} bytes to Click clipboard from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
