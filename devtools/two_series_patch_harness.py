"""Generate targeted patch variants for two-series hypothesis testing.

This tool copies selected byte scopes from a donor payload (typically native)
into a base payload (typically generated), then writes patch variants for
manual pasteback validation.

Examples:
  uv run python devtools/two_series_patch_harness.py --case 02_imm_no

  uv run python devtools/two_series_patch_harness.py \
    --case 04_imm_imm \
    --scope header_seed \
    --scope row1_col1_profile

  uv run python devtools/two_series_patch_harness.py \
    --case 02_imm_no \
    --base-file scratchpad/captures/my_generated.bin \
    --donor-file scratchpad/captures/two_series_first_immediate_native.bin
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clicknick.ladder.codec import BUFFER_SIZE, CELL_SIZE, ClickCodec
from clicknick.ladder.model import RungGrid
from clicknick.ladder.topology import HEADER_ENTRY_BASE, cell_offset


@dataclass(frozen=True)
class MatrixCase:
    row_csv: str
    donor_native_file: str


CASE_DEFS: dict[str, MatrixCase] = {
    "01_no_no": MatrixCase(
        row_csv="X001,X002,->,:,out(Y001)",
        donor_native_file="smoke_two_series_short_native.bin",
    ),
    "02_imm_no": MatrixCase(
        row_csv="X001.immediate,X002,->,:,out(Y001)",
        donor_native_file="two_series_first_immediate_native.bin",
    ),
    "03_no_imm": MatrixCase(
        row_csv="X001,X002.immediate,->,:,out(Y001)",
        donor_native_file="two_series_second_immediate_native.bin",
    ),
    "04_imm_imm": MatrixCase(
        row_csv="X001.immediate,X002.immediate,->,:,out(Y001)",
        donor_native_file="two_series_both_immediate_native.bin",
    ),
}

SCOPE_CHOICES = [
    "header_seed",
    "row1_col0_profile",
    "row1_col1_profile",
    "row1_col3_metadata",
    "row0_tail_profiles",
]


def _read_first_record(path: Path) -> bytearray:
    raw = path.read_bytes()
    if len(raw) < BUFFER_SIZE:
        raise ValueError(f"{path}: payload too short ({len(raw)} bytes)")
    return bytearray(raw[:BUFFER_SIZE])


def _copy(base: bytearray, donor: bytes, offset: int) -> None:
    base[offset] = donor[offset]


def _apply_header_seed(base: bytearray, donor: bytes) -> int:
    count = 0
    for col in range(32):
        entry = HEADER_ENTRY_BASE + col * CELL_SIZE
        for rel in (0x05, 0x11, 0x17, 0x18):
            _copy(base, donor, entry + rel)
            count += 1
    _copy(base, donor, 0x0A59)
    return count + 1


def _apply_row1_col0_profile(base: bytearray, donor: bytes) -> int:
    row1_col0 = cell_offset(1, 0)
    offsets = (0x05, 0x11, 0x1A, 0x1B)
    for rel in offsets:
        _copy(base, donor, row1_col0 + rel)
    return len(offsets)


def _apply_row1_col1_profile(base: bytearray, donor: bytes) -> int:
    row1_col1 = cell_offset(1, 1)
    offsets = (0x05, 0x11, 0x19, 0x1A, 0x1B)
    for rel in offsets:
        _copy(base, donor, row1_col1 + rel)
    return len(offsets)


def _apply_row1_col3_metadata(base: bytearray, donor: bytes) -> int:
    row1_col3 = cell_offset(1, 3)
    count = 0
    for rel in (0x11, 0x15, 0x1E, 0x27, 0x2A):
        for delta in (0, 2, 4):
            _copy(base, donor, row1_col3 + rel + delta)
            count += 1
    _copy(base, donor, row1_col3 + 0x23)
    return count + 1


def _apply_row0_tail_profiles(base: bytearray, donor: bytes) -> int:
    count = 0
    for col in range(4, 32):
        start = cell_offset(0, col)
        for rel in (0x05, 0x11, 0x1A, 0x1B):
            _copy(base, donor, start + rel)
            count += 1
    return count


SCOPE_FUNCS: dict[str, Callable[[bytearray, bytes], int]] = {
    "header_seed": _apply_header_seed,
    "row1_col0_profile": _apply_row1_col0_profile,
    "row1_col1_profile": _apply_row1_col1_profile,
    "row1_col3_metadata": _apply_row1_col3_metadata,
    "row0_tail_profiles": _apply_row0_tail_profiles,
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", required=True, choices=sorted(CASE_DEFS))
    p.add_argument(
        "--scope",
        action="append",
        choices=SCOPE_CHOICES,
        help="Patch scope(s). Default: all scopes.",
    )
    p.add_argument(
        "--base-file",
        help="Optional base payload file. Default: generated from case row with ClickCodec.",
    )
    p.add_argument(
        "--donor-file",
        help="Optional donor payload file. Default: case native capture in scratchpad/captures.",
    )
    p.add_argument(
        "--output-dir",
        default="scratchpad/captures",
        help="Output directory for patch variants (default: scratchpad/captures).",
    )
    p.add_argument(
        "--prefix",
        help="Output prefix. Default: two_series_patch_<case>.",
    )
    p.add_argument(
        "--combined-only",
        action="store_true",
        help="Write only the combined output using all selected scopes.",
    )
    return p


def _load_base(case_name: str, base_file: str | None) -> bytearray:
    if base_file:
        return _read_first_record(Path(base_file))
    case = CASE_DEFS[case_name]
    codec = ClickCodec()
    return bytearray(codec.encode(RungGrid.from_csv(case.row_csv)))


def _load_donor(case_name: str, donor_file: str | None) -> bytes:
    if donor_file:
        return bytes(_read_first_record(Path(donor_file)))
    path = Path("scratchpad/captures") / CASE_DEFS[case_name].donor_native_file
    return bytes(_read_first_record(path))


def main() -> int:
    args = _build_parser().parse_args()
    scopes = args.scope or list(SCOPE_CHOICES)
    base = _load_base(args.case, args.base_file)
    donor = _load_donor(args.case, args.donor_file)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or f"two_series_patch_{args.case}"

    if not args.combined_only:
        for scope in scopes:
            patched = bytearray(base)
            changed = SCOPE_FUNCS[scope](patched, donor)
            out_file = out_dir / f"{prefix}__{scope}.bin"
            out_file.write_bytes(bytes(patched))
            print(f"{out_file}  bytes_copied={changed}  scope={scope}")

    combined = bytearray(base)
    total = 0
    for scope in scopes:
        total += SCOPE_FUNCS[scope](combined, donor)
    combined_file = out_dir / f"{prefix}__combined.bin"
    combined_file.write_bytes(bytes(combined))
    print(f"{combined_file}  bytes_copied={total}  scopes={','.join(scopes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
