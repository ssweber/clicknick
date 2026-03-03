"""Analyze per-cell control-byte differences across Click clipboard captures.

This tool is intentionally focused on row0/row1 cell metadata. It compares
selected cells across one or more captures and reports offsets whose byte values
differ across captures.

Examples:
  uv run python devtools/control_byte_diff.py \\
    --labels smoke_two_series_short_native two_series_second_immediate_native

  uv run python devtools/control_byte_diff.py \\
    --labels two_series_second_immediate_native \\
             two_series_second_immediate_back_split_after_row0_profile \\
    --rows 0,1 --cols 0-6
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from clicknick.ladder.topology import cell_offset

CAPTURE_DIR = Path("scratchpad/captures")
BUFFER_SIZE = 8192


def _parse_index_spec(spec: str, *, minimum: int, maximum: int) -> list[int]:
    out: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            a_raw, b_raw = part.split("-", 1)
            a = int(a_raw, 0)
            b = int(b_raw, 0)
            lo, hi = sorted((a, b))
            for idx in range(lo, hi + 1):
                if minimum <= idx <= maximum:
                    out.add(idx)
            continue
        idx = int(part, 0)
        if minimum <= idx <= maximum:
            out.add(idx)
    return sorted(out)


def _parse_offset_spec(spec: str) -> list[int]:
    return _parse_index_spec(spec, minimum=0, maximum=0x3F)


def _resolve_capture(ref: str) -> Path:
    direct = Path(ref)
    if direct.exists():
        return direct
    with_ext = CAPTURE_DIR / (ref if ref.endswith(".bin") else f"{ref}.bin")
    if with_ext.exists():
        return with_ext
    raise FileNotFoundError(f"Capture not found: {ref!r}")


def _load_capture(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    if len(raw) == BUFFER_SIZE:
        return raw, ""
    if len(raw) < BUFFER_SIZE:
        raise ValueError(f"{path}: capture is too short ({len(raw)} bytes)")
    note = (
        f"non-standard length {len(raw)} bytes; using first {BUFFER_SIZE} bytes "
        "(likely split/multi-object clipboard payload)"
    )
    return raw[:BUFFER_SIZE], note


def _hex_byte(v: int) -> str:
    return f"0x{v:02X}"


def _build_diff_offsets(
    captures: dict[str, bytes],
    *,
    row: int,
    col: int,
    explicit_offsets: list[int] | None,
) -> list[int]:
    if explicit_offsets is not None:
        return explicit_offsets

    start = cell_offset(row, col)
    offsets: list[int] = []
    for rel in range(0x40):
        values = {data[start + rel] for data in captures.values()}
        if len(values) <= 1:
            continue
        if max(values) == 0:
            continue
        offsets.append(rel)
    return offsets


def _iter_cells(rows: Iterable[int], cols: Iterable[int]) -> Iterable[tuple[int, int]]:
    for row in rows:
        for col in cols:
            yield row, col


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--labels",
        nargs="+",
        required=True,
        help="Capture labels (from scratchpad/captures) or explicit .bin paths.",
    )
    p.add_argument(
        "--rows",
        default="0,1",
        help="Row indices/ranges (default: 0,1). Example: 0,1 or 0-2",
    )
    p.add_argument(
        "--cols",
        default="0-7",
        help="Column indices/ranges (default: 0-7). Example: 0-6",
    )
    p.add_argument(
        "--offsets",
        help="Optional fixed cell offsets (0x00-0x3F). Example: 0x05,0x11,0x19",
    )
    p.add_argument(
        "--show-all-cells",
        action="store_true",
        help="Show cells even when no differing offsets are found.",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()
    rows = _parse_index_spec(args.rows, minimum=0, maximum=31)
    cols = _parse_index_spec(args.cols, minimum=0, maximum=31)
    explicit_offsets = _parse_offset_spec(args.offsets) if args.offsets else None

    if not rows:
        raise ValueError("No valid rows selected")
    if not cols:
        raise ValueError("No valid cols selected")

    captures: dict[str, bytes] = {}
    notes: list[str] = []
    for label in args.labels:
        path = _resolve_capture(label)
        data, note = _load_capture(path)
        captures[label] = data
        if note:
            notes.append(f"{label}: {note}")

    print("=== Control Byte Diff ===")
    print("Captures:")
    for label in args.labels:
        path = _resolve_capture(label)
        print(f"  - {label} -> {path}")
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  - {note}")

    any_cell_output = False
    for row, col in _iter_cells(rows, cols):
        diff_offsets = _build_diff_offsets(
            captures,
            row=row,
            col=col,
            explicit_offsets=explicit_offsets,
        )

        if not diff_offsets and not args.show_all_cells:
            continue

        any_cell_output = True
        print(f"\n[r{row} c{col}]")
        if not diff_offsets:
            print("  (no differing offsets)")
            continue

        start = cell_offset(row, col)
        for rel in diff_offsets:
            values = {label: data[start + rel] for label, data in captures.items()}
            as_text = " ".join(f"{label}={_hex_byte(values[label])}" for label in args.labels)
            print(f"  +0x{rel:02X}: {as_text}")

    if not any_cell_output:
        print("\nNo selected cells produced output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
