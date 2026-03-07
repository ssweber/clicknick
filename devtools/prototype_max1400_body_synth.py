#!/usr/bin/env python3
"""Offline prototype for row32 max1400 body-page synthesis.

This is a RE helper only. It patches the repeated body pages and terminal
page-16 body form on top of a row32 no-comment native capture, then reports
byte-level parity against a native max1400 capture.
"""

from __future__ import annotations

import argparse
from pathlib import Path


PAGE_SIZE = 0x1000
CELL_SIZE = 0x40
SLOTS_PER_PAGE = PAGE_SIZE // CELL_SIZE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_capture", type=Path, help="Row32 no-comment native capture")
    parser.add_argument(
        "target_capture", type=Path, help="Row32 max1400 native capture used for parity checks"
    )
    parser.add_argument(
        "--lane",
        choices=("empty", "fullwire"),
        required=True,
        help="Which row32 lane rule set to apply",
    )
    return parser.parse_args()


def write_common_slot(data: bytearray, offset: int, lane: str, ord09: int, ord11: int, col: int) -> None:
    data[offset + 0x04] = 0x01
    data[offset + 0x05] = 0x01 if lane == "fullwire" else 0x00
    data[offset + 0x09] = ord09 & 0xFF
    data[offset + 0x0D] = (col - 1) & 0x1F
    data[offset + 0x11] = ord11 & 0xFF
    data[offset + 0x15] = 0x01
    data[offset + 0x16] = 0x01
    data[offset + 0x17] = 0xFC
    data[offset + 0x18] = 0x00
    data[offset + 0x19 : offset + 0x1D] = b"\xFF\xFF\xFF\xFF"
    data[offset + 0x1D] = 0x01
    data[offset + 0x21] = 0x00
    data[offset + 0x25] = 0x00
    data[offset + 0x29] = 0x00
    for rel in (0x2A, 0x2B, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x39, 0x3D):
        data[offset + rel] = 0x00

    if lane == "fullwire":
        data[offset + 0x25] = 0x00 if col in (0, 1) else 0x01
        data[offset + 0x29] = 0x00 if col == 0 else 0x01


def apply_repeated_body_pages(data: bytearray, lane: str) -> None:
    for page in range(2, 17):
        page_base = 2 * page - 2
        page_offset = page * PAGE_SIZE
        for slot in range(SLOTS_PER_PAGE):
            rowband = slot // 32
            col = slot % 32
            ord09 = page_base + rowband + (1 if col != 0 else 0)
            ord11 = ord09 + (0x21 if lane == "fullwire" else 0x00)
            write_common_slot(
                data,
                page_offset + slot * CELL_SIZE,
                lane,
                ord09,
                ord11,
                col,
            )


def apply_page16_terminal_overrides(data: bytearray, lane: str) -> None:
    page_offset = 16 * PAGE_SIZE

    # Empty-lane page 16 has two small byte deviations from the repeated rule.
    if lane == "empty":
        data[page_offset + 9 * CELL_SIZE + 0x35] = 0x00
        data[page_offset + 33 * CELL_SIZE + 0x21] = 0x01

    # Slots 41..63 collapse into a short terminal descriptor form.
    for slot in range(41, 64):
        slot_offset = page_offset + slot * CELL_SIZE
        col = slot % 32
        data[slot_offset : slot_offset + CELL_SIZE] = b"\x00" * CELL_SIZE
        write_common_slot(
            data,
            slot_offset,
            lane,
            0x20,
            0x41 if lane == "fullwire" else 0x20,
            col,
        )
        if lane == "fullwire":
            data[slot_offset + 0x25] = 0x01
            data[slot_offset + 0x29] = 0x01


def diff_count(a: bytes, b: bytes, start: int, end: int) -> int:
    return sum(1 for x, y in zip(a[start:end], b[start:end]) if x != y)


def main() -> None:
    args = parse_args()
    base = bytearray(args.base_capture.read_bytes())
    target = args.target_capture.read_bytes()

    apply_repeated_body_pages(base, args.lane)
    apply_page16_terminal_overrides(base, args.lane)

    start = 2 * PAGE_SIZE
    end = 17 * PAGE_SIZE
    print(f"lane={args.lane}")
    print(f"body_pages_2_16_diff_count={diff_count(base, target, start, end)}")
    for page in (2, 3, 15, 16):
        page_start = page * PAGE_SIZE
        page_end = page_start + PAGE_SIZE
        print(
            f"page_{page:02d}_diff_count="
            f"{diff_count(base, target, page_start, page_end)}"
        )


if __name__ == "__main__":
    main()
