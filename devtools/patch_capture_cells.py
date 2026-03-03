"""Patch per-cell control bytes in the first 8KiB record of a capture.

Examples:
  uv run python devtools/patch_capture_cells.py \
    --input scratchpad/captures/two_series_second_immediate_back_split_after_row0_profile.bin \
    --output scratchpad/captures/two_series_second_immediate_back_split_after_row0_profile_patch_1a_ff.bin \
    --set 0x1A=0xFF

  uv run python devtools/patch_capture_cells.py \
    --input scratchpad/captures/two_series_second_immediate_back_split_after_row0_profile.bin \
    --output scratchpad/captures/two_series_second_immediate_back_split_after_row0_profile_patch_1b_01.bin \
    --set 0x1B=0x01
"""

from __future__ import annotations

import argparse
from pathlib import Path

BUFFER_SIZE = 8192
GRID_FIRST_ROW_START = 0x0A60
GRID_ROW_STRIDE = 0x0800
CELL_SIZE = 0x40
COLS = 32
ROWS = 2


def _parse_set(raw: str) -> tuple[int, int]:
    if "=" not in raw:
        raise ValueError(f"Expected OFF=VAL, got: {raw!r}")
    left, right = raw.split("=", 1)
    off = int(left, 0)
    value = int(right, 0)
    if not (0 <= off <= 0x3F):
        raise ValueError(f"Cell offset out of range (0x00..0x3F): 0x{off:02X}")
    if not (0 <= value <= 0xFF):
        raise ValueError(f"Value out of byte range (0x00..0xFF): 0x{value:02X}")
    return off, value


def _cell_start(row: int, col: int) -> int:
    return GRID_FIRST_ROW_START + row * GRID_ROW_STRIDE + col * CELL_SIZE


def _iter_cells() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for row in range(ROWS):
        for col in range(COLS):
            out.append((row, col))
    return out


def _is_occupied(record: bytes, row: int, col: int) -> bool:
    start = _cell_start(row, col)
    end = start + CELL_SIZE
    if end > len(record):
        return False
    return any(record[start:end])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Input capture .bin")
    parser.add_argument("--output", required=True, help="Output capture .bin")
    parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        required=True,
        help="Byte patch in OFF=VAL form (hex allowed), can be repeated.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    src_path = Path(args.input)
    dst_path = Path(args.output)
    patches = [_parse_set(item) for item in args.sets]

    raw = bytearray(src_path.read_bytes())
    if len(raw) < BUFFER_SIZE:
        raise ValueError(f"{src_path}: capture too short ({len(raw)} bytes)")

    record = raw[:BUFFER_SIZE]
    occupied = [(r, c) for (r, c) in _iter_cells() if _is_occupied(record, r, c)]
    for row, col in occupied:
        start = _cell_start(row, col)
        for off, value in patches:
            raw[start + off] = value

    dst_path.write_bytes(raw)

    patch_text = ", ".join(f"+0x{off:02X}=0x{value:02X}" for off, value in patches)
    print("=== Cell Patch Complete ===")
    print(f"input:  {src_path}")
    print(f"output: {dst_path}")
    print(f"length: {len(raw)} bytes")
    print(f"patched record: first {BUFFER_SIZE} bytes")
    print(f"occupied cells patched: {len(occupied)}")
    print(f"patches: {patch_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
