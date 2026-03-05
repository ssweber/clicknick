#!/usr/bin/env python3
"""Synthesize wire-only grid payloads from an empty native template.

This tool is intentionally narrow for the empty/horizontal RE lane:
- input template is treated as canonical structure donor;
- row content is wire-only shorthand (`-`, `T`, `|`, blank);
- optional refined header normalization copies selected header entry bytes
  from a donor payload (default: +0x11 and +0x17).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from clicknick.ladder.codec import BUFFER_SIZE
from clicknick.ladder.csv_shorthand import normalize_shorthand_row
from clicknick.ladder.topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    COLS_PER_ROW,
    HEADER_ENTRY_BASE,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    HEADER_ROW_CLASS_OFFSET,
    cell_offset,
)

SUPPORTED_TOKENS = {"", "-", "T", "|"}
HEADER_COPY_DEFAULT_OFFSETS = (0x11, 0x17)
ROW_CLASS_BY_COUNT = {
    1: 0x40,
    2: 0x60,
}


def _first_record(data: bytes, *, label: str) -> bytes:
    if len(data) < BUFFER_SIZE:
        raise ValueError(f"{label} payload too short ({len(data)} bytes); need at least {BUFFER_SIZE}")
    return data[:BUFFER_SIZE]


def _parse_offset(raw: str) -> int:
    offset = int(raw, 0)
    if not (0 <= offset < HEADER_ENTRY_SIZE):
        raise ValueError(
            f"Header entry-relative offset out of range 0..0x{HEADER_ENTRY_SIZE - 1:02X}: {raw!r}"
        )
    return offset


def parse_wire_rows(rows: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    parsed: list[tuple[str, ...]] = []
    for idx, row in enumerate(rows, start=1):
        canonical = normalize_shorthand_row(row)
        if canonical.af:
            raise ValueError(
                f"Row {idx} AF field must be blank for wire-only synthesis, got {canonical.af!r}"
            )
        unsupported = sorted({token for token in canonical.conditions if token not in SUPPORTED_TOKENS})
        if unsupported:
            raise ValueError(
                f"Row {idx} has unsupported condition token(s): {unsupported}. "
                "Allowed: '', '-', 'T', '|'"
            )
        parsed.append(tuple(canonical.conditions))

    if not parsed:
        raise ValueError("At least one --row is required")
    if len(parsed) > 2:
        raise ValueError("This tool supports up to two rows in an 8192-byte payload")
    return tuple(parsed)


def _flags_for_token(token: str) -> tuple[int, int, int]:
    if token == "-":
        return (1, 1, 0)
    if token == "T":
        return (1, 1, 1)
    if token == "|":
        return (0, 0, 1)
    return (0, 0, 0)


def _clear_wire_flags(buf: bytearray, *, rows: int) -> None:
    for row in range(rows):
        for col in range(COLS_PER_ROW - 1):  # A..AE (AF is output cell)
            start = cell_offset(row, col)
            buf[start + CELL_HORIZONTAL_LEFT_OFFSET] = 0
            buf[start + CELL_HORIZONTAL_RIGHT_OFFSET] = 0
            buf[start + CELL_VERTICAL_DOWN_OFFSET] = 0


def _draw_rows(buf: bytearray, parsed_rows: tuple[tuple[str, ...], ...]) -> None:
    for row_idx, condition_tokens in enumerate(parsed_rows):
        for col_idx, token in enumerate(condition_tokens):
            left, right, down = _flags_for_token(token)
            start = cell_offset(row_idx, col_idx)
            buf[start + CELL_HORIZONTAL_LEFT_OFFSET] = left
            buf[start + CELL_HORIZONTAL_RIGHT_OFFSET] = right
            buf[start + CELL_VERTICAL_DOWN_OFFSET] = down


def _apply_header_copy_offsets(
    buf: bytearray,
    *,
    donor: bytes,
    entry_offsets: tuple[int, ...],
) -> None:
    donor_record = _first_record(donor, label="donor")
    for col in range(HEADER_ENTRY_COUNT):
        entry_start = HEADER_ENTRY_BASE + col * HEADER_ENTRY_SIZE
        for rel in entry_offsets:
            buf[entry_start + rel] = donor_record[entry_start + rel]


def synthesize_from_template(
    template: bytes,
    *,
    rows: Iterable[str],
    donor: bytes | None = None,
    header_copy_offsets: tuple[int, ...] = HEADER_COPY_DEFAULT_OFFSETS,
) -> bytes:
    template_record = _first_record(template, label="template")
    parsed_rows = parse_wire_rows(rows)
    row_count = len(parsed_rows)
    row_class = ROW_CLASS_BY_COUNT.get(row_count)
    if row_class is None:
        raise ValueError(f"Unsupported row count for synthesis: {row_count}")

    out_record = bytearray(template_record)
    out_record[HEADER_ENTRY_BASE + HEADER_ROW_CLASS_OFFSET] = row_class

    # Use a deterministic topology surface by clearing both row blocks first.
    _clear_wire_flags(out_record, rows=2)
    _draw_rows(out_record, parsed_rows)

    if donor is not None and header_copy_offsets:
        _apply_header_copy_offsets(out_record, donor=donor, entry_offsets=header_copy_offsets)

    if len(template) == BUFFER_SIZE:
        return bytes(out_record)

    output = bytearray(template)
    output[:BUFFER_SIZE] = out_record
    return bytes(output)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, help="Template payload (.bin)")
    parser.add_argument("--output", required=True, help="Output payload (.bin)")
    parser.add_argument(
        "--row",
        action="append",
        required=True,
        help="Wire-only shorthand row (repeat for row2)",
    )
    parser.add_argument(
        "--donor",
        help="Optional donor payload for header-copy normalization",
    )
    parser.add_argument(
        "--header-copy-offset",
        action="append",
        help=(
            "Header entry-relative byte offset to copy from donor (repeatable). "
            "Defaults to 0x11 and 0x17 when --donor is provided."
        ),
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    template_path = Path(args.template)
    output_path = Path(args.output)
    donor_path = Path(args.donor) if args.donor else None

    template_bytes = template_path.read_bytes()
    donor_bytes = donor_path.read_bytes() if donor_path else None

    if donor_bytes is None and args.header_copy_offset:
        raise ValueError("--header-copy-offset requires --donor")

    if donor_bytes is not None:
        header_copy_offsets = (
            tuple(_parse_offset(raw) for raw in args.header_copy_offset)
            if args.header_copy_offset
            else HEADER_COPY_DEFAULT_OFFSETS
        )
    else:
        header_copy_offsets = tuple()

    synthesized = synthesize_from_template(
        template_bytes,
        rows=args.row,
        donor=donor_bytes,
        header_copy_offsets=header_copy_offsets,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(synthesized)

    before = _first_record(template_bytes, label="template")
    after = _first_record(synthesized, label="output")
    changed = sum(1 for x, y in zip(before, after) if x != y)

    print("=== Grid Template Synthesis Complete ===")
    print(f"template: {template_path}")
    print(f"output:   {output_path}")
    print(f"rows:     {len(args.row)}")
    print(f"changed:  {changed} bytes (first 8192)")
    if donor_path:
        print(f"donor:    {donor_path}")
        copied = ", ".join(f"+0x{offset:02X}" for offset in header_copy_offsets)
        print(f"header-copy offsets: {copied if copied else '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
