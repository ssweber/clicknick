#!/usr/bin/env python3
"""Summarize row32 max1400 page-17 record structure.

This is a narrow offline RE helper for the March 7, 2026 max1400 lane.
It parses the extra 0x1000 page seen in row32 max1400 captures and emits
stable structural facts about:
  - top-level record boundaries
  - repeated wrapper fields
  - nested CJK fallback slots in the large terminal record
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


TOP_TAG = b"\x74\x76\x00\x08"
NESTED_TAG = b"\x64\x76\x00\x08"
SLOT_TAG_PREFIX = b"\x03\x02\x01"
PAGE_SIZE = 0x1000
DEFAULT_PAGE_INDEX = 17


@dataclass(frozen=True)
class Record:
    start: int
    end: int
    data: bytes

    @property
    def length(self) -> int:
        return self.end - self.start

    def u16(self, offset: int) -> int | None:
        if offset + 2 > len(self.data):
            return None
        return int.from_bytes(self.data[offset : offset + 2], "little")

    def tag(self, offset: int, length: int = 4) -> str | None:
        if offset + length > len(self.data):
            return None
        return self.data[offset : offset + length].hex(" ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path, help="Capture .bin to inspect")
    parser.add_argument(
        "--page-index",
        type=int,
        default=DEFAULT_PAGE_INDEX,
        help=f"0-based page index to inspect (default: {DEFAULT_PAGE_INDEX})",
    )
    return parser.parse_args()


def find_all(data: bytes, needle: bytes) -> list[int]:
    hits: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return hits
        hits.append(offset)
        start = offset + 1


def read_page(capture: Path, page_index: int) -> bytes:
    payload = capture.read_bytes()
    start = page_index * PAGE_SIZE
    end = start + PAGE_SIZE
    if end > len(payload):
        raise ValueError(
            f"{capture} length {len(payload)} does not include page index {page_index}"
        )
    return payload[start:end]


def utf16z(data: bytes, offset: int) -> str | None:
    if offset + 2 > len(data):
        return None
    end = offset
    while end + 1 < len(data) and data[end : end + 2] != b"\x00\x00":
        end += 2
    if end == offset:
        return None
    try:
        return data[offset:end].decode("utf-16le")
    except UnicodeDecodeError:
        return None


def split_records(page: bytes) -> list[Record]:
    starts = find_all(page, TOP_TAG)
    ends = starts[1:] + [len(page)]
    return [Record(start, end, page[start:end]) for start, end in zip(starts, ends)]


def summarize_record(index: int, record: Record) -> None:
    header_size = 0x74
    span = record.u16(0x84)
    payload_span = record.u16(0x88)
    primary_code = record.u16(0x0A)
    repeat_code = record.u16(0x34)
    linked_code = record.u16(0xA0)

    print(
        f"record[{index}] start=0x{record.start:03X} len=0x{record.length:03X}"
        f" tag={record.tag(0)}"
    )
    print(
        "  wrapper"
        f" primary=0x{primary_code:04X}"
        f" repeat=0x{repeat_code:04X}"
        f" linked=0x{linked_code:04X}"
        f" subtype=0x{record.u16(0x54):04X}"
        f" span=0x{span:04X}"
        f" payload=0x{payload_span:04X}"
    )
    print(
        "  checks"
        f" span_matches_len={span == record.length}"
        f" payload_plus_0x74={payload_span + header_size == span}"
    )
    strings = []
    for offset in (0xAC, 0xEC, 0x16C):
        text = utf16z(record.data, offset)
        if text:
            strings.append(f"0x{offset:03X}={text!r}")
    if strings:
        print("  strings", ", ".join(strings))

    nested = find_all(record.data, NESTED_TAG)
    slots = [offset for offset in find_all(record.data, SLOT_TAG_PREFIX) if offset < 0xA8 or offset >= 0xA8]
    if not nested and not slots:
        return

    if nested:
        stride = nested[1] - nested[0] if len(nested) >= 2 else None
        print(
            "  nested"
            f" inner_headers={[f'0x{x:03X}' for x in nested]}"
            + (f" stride=0x{stride:03X}" if stride is not None else "")
        )
    slot_offsets = [offset for offset in find_all(record.data, SLOT_TAG_PREFIX) if offset >= 0xA8]
    if slot_offsets:
        stride = slot_offsets[1] - slot_offsets[0] if len(slot_offsets) >= 2 else None
        print(
            "  slots"
            f" starts={[f'0x{x:03X}' for x in slot_offsets]}"
            + (f" stride=0x{stride:03X}" if stride is not None else "")
        )
        for slot_index, slot_start in enumerate(slot_offsets):
            slot_end = (
                slot_offsets[slot_index + 1]
                if slot_index + 1 < len(slot_offsets)
                else len(record.data)
            )
            slot = record.data[slot_start:slot_end]
            name_a = utf16z(slot, 0x04)
            name_b = utf16z(slot, 0x44)
            style = utf16z(slot, 0xC4)
            print(
                f"    slot[{slot_index}] start=0x{slot_start:03X} len=0x{len(slot):03X}"
                f" tag={slot[:4].hex(' ')}"
                f" name_a={name_a!r}"
                f" name_b={name_b!r}"
                f" style={style!r}"
            )
            inner = slot.find(NESTED_TAG)
            if inner >= 0:
                print(
                    "      inner"
                    f" at=0x{inner:03X}"
                    f" class=0x{slot[inner + 0x47]:02X}"
                    f" metric_164=0x{slot[inner + 0x20]:02X}"
                    f" metric_16C=0x{slot[inner + 0x28]:02X}"
                    f" weight_like=0x{int.from_bytes(slot[inner + 0x2C:inner + 0x2E], 'little'):04X}"
                    f" tail_180=0x{int.from_bytes(slot[inner + 0x3C:inner + 0x40], 'little'):08X}"
                )


def main() -> None:
    args = parse_args()
    page = read_page(args.capture, args.page_index)
    print(f"capture={args.capture}")
    print(f"page_index={args.page_index} page_len=0x{len(page):03X}")
    print(f"top_tags={[f'0x{x:03X}' for x in find_all(page, TOP_TAG)]}")
    records = split_records(page)
    if not records:
        print("no top-level 74 76 00 08 records found")
        return
    for index, record in enumerate(records):
        summarize_record(index, record)


if __name__ == "__main__":
    main()
