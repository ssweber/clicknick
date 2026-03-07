#!/usr/bin/env python3
"""Offline splice prototype for row32 max1400 payload reconstruction.

This helper is intentionally non-production. It starts from a row32
no-comment native base capture, synthesizes body pages 2..16 using the
current inferred rules, then copies selected donor pages (normally 0, 1,
and 17) from a native max1400 capture.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from prototype_max1400_body_synth import (
    PAGE_SIZE,
    apply_page16_terminal_overrides,
    apply_repeated_body_pages,
    diff_count,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_capture", type=Path, help="Row32 no-comment native capture")
    parser.add_argument("donor_capture", type=Path, help="Capture used as the donor for copied pages")
    parser.add_argument(
        "target_capture",
        type=Path,
        help="Capture used for byte-level parity checks",
    )
    parser.add_argument(
        "--lane",
        choices=("empty", "fullwire"),
        required=True,
        help="Which row32 lane rule set to apply",
    )
    parser.add_argument(
        "--copy-page",
        type=int,
        action="append",
        default=[],
        help="0-based donor pages to copy verbatim (default: 0, 1, 17)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional path to write the spliced payload",
    )
    return parser.parse_args()


def copy_page(dst: bytearray, src: bytes, page_index: int) -> None:
    start = page_index * PAGE_SIZE
    end = start + PAGE_SIZE
    dst[start:end] = src[start:end]


def main() -> None:
    args = parse_args()
    copy_pages = args.copy_page or [0, 1, 17]

    base = bytearray(args.base_capture.read_bytes())
    donor = args.donor_capture.read_bytes()
    target = args.target_capture.read_bytes()

    apply_repeated_body_pages(base, args.lane)
    apply_page16_terminal_overrides(base, args.lane)
    for page_index in copy_pages:
        copy_page(base, donor, page_index)

    if args.output_file is not None:
        args.output_file.write_bytes(base)

    print(f"lane={args.lane}")
    print(f"copied_pages={copy_pages}")
    print(f"full_diff_count={diff_count(base, target, 0, min(len(base), len(target)))}")
    for page in range(min(len(base), len(target)) // PAGE_SIZE):
        page_start = page * PAGE_SIZE
        page_end = page_start + PAGE_SIZE
        print(
            f"page_{page:02d}_diff_count="
            f"{diff_count(base, target, page_start, page_end)}"
        )


if __name__ == "__main__":
    main()
