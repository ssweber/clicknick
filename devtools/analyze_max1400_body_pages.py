#!/usr/bin/env python3
"""Summarize row32 max1400 body-page structure on the 0x40 cell lattice."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path


PAGE_SIZE = 0x1000
CELL_SIZE = 0x40
SLOTS_PER_PAGE = PAGE_SIZE // CELL_SIZE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path, help="Capture .bin to inspect")
    parser.add_argument("--page", type=int, default=2, help="0-based page index")
    parser.add_argument(
        "--compare",
        type=Path,
        help="Optional peer capture used to classify per-slot diff families",
    )
    return parser.parse_args()


def load_page(path: Path, page: int) -> bytes:
    payload = path.read_bytes()
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    if end > len(payload):
        raise ValueError(f"{path} does not contain page {page}")
    return payload[start:end]


def main() -> None:
    args = parse_args()
    page = load_page(args.capture, args.page)
    print(f"capture={args.capture}")
    print(f"page={args.page} nonzero={sum(1 for b in page if b)}")

    vals_09 = [page[slot * CELL_SIZE + 0x09] for slot in range(SLOTS_PER_PAGE)]
    vals_11 = [page[slot * CELL_SIZE + 0x11] for slot in range(SLOTS_PER_PAGE)]
    print("slot+0x09 row0", vals_09[:32])
    print("slot+0x09 row1", vals_09[32:])
    print("slot+0x11 row0", vals_11[:32])
    print("slot+0x11 row1", vals_11[32:])

    if args.compare is None:
        return

    peer = load_page(args.compare, args.page)
    families: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for slot in range(SLOTS_PER_PAGE):
        ours = page[slot * CELL_SIZE : (slot + 1) * CELL_SIZE]
        theirs = peer[slot * CELL_SIZE : (slot + 1) * CELL_SIZE]
        diff_offsets = tuple(
            offset for offset, (a, b) in enumerate(zip(ours, theirs)) if a != b
        )
        families[diff_offsets].append(slot)

    print(f"compare={args.compare}")
    for diff_offsets, slots in sorted(families.items(), key=lambda item: item[1][0]):
        print(
            "family"
            f" slots={slots}"
            f" diff_offsets={[hex(offset) for offset in diff_offsets]}"
        )


if __name__ == "__main__":
    main()
