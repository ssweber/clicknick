"""Manual pasteback smoke-test helper (non-interactive).

Usage examples:
  uv run python scratchpad/pasteback_smoke.py list
  uv run python scratchpad/pasteback_smoke.py prepare --case smoke_simple
  uv run python scratchpad/pasteback_smoke.py compare --case smoke_simple --native-label smoke_simple_native
  # In Click: paste rung, then copy that same rung back
  uv run python scratchpad/pasteback_smoke.py verify --case smoke_simple
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clicknick.ladder import (
    ClickCodec,
    RungGrid,
    copy_to_clipboard,
    header_structural_equal,
    parse_wire_topology,
    read_from_clipboard,
)
from clicknick.ladder.topology import HEADER_ENTRY_BASE, HEADER_ENTRY_COUNT, HEADER_ENTRY_SIZE

DEFAULT_CASES: dict[str, str] = {
    "smoke_simple": "X001,->,:,out(Y001)",
    "smoke_immediate": "X001.immediate,->,:,out(Y001)",
    "smoke_two_series_short": "X1,X2,->,:,out(Y001)",
    "smoke_range": "X001,->,:,out(C1..C2)",
}

ARTIFACT_DIR = Path("scratchpad/pasteback_smoke")


def _csv_for_case(case: str, csv_override: str | None) -> str:
    if csv_override:
        return csv_override
    if case not in DEFAULT_CASES:
        raise ValueError(
            f"Unknown case {case!r}. Use --csv to provide a custom rung or run with 'list'."
        )
    return DEFAULT_CASES[case]


def _paths(case: str) -> tuple[Path, Path, Path]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    src_path = ARTIFACT_DIR / f"{case}.src.bin"
    back_path = ARTIFACT_DIR / f"{case}.back.bin"
    result_path = ARTIFACT_DIR / f"{case}.result.json"
    return src_path, back_path, result_path


def _compare_path(case: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACT_DIR / f"{case}.compare.json"


def _type_markers(data: bytes) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in range(0x0A60, min(len(data), 0x1A60) - 1):
        if data[i + 1] == 0x27 and data[i] != 0x00:
            out.append((i, data[i]))
    return out


def cmd_list() -> int:
    for label, csv in DEFAULT_CASES.items():
        print(f"{label}: {csv}")
    return 0


def cmd_prepare(case: str, csv_override: str | None) -> int:
    csv = _csv_for_case(case, csv_override)
    codec = ClickCodec()
    src = codec.encode(RungGrid.from_csv(csv))
    src_path, _, result_path = _paths(case)
    src_path.write_bytes(src)
    copy_to_clipboard(src)

    # Clear stale result file for this case.
    if result_path.exists():
        result_path.unlink()

    print(f"[{case}] Prepared: {csv}")
    print(f"Saved source bytes: {src_path}")
    print("Next in Click: paste into rung, then copy that same rung back.")
    print(f"Then run: uv run python scratchpad/pasteback_smoke.py verify --case {case!s}")
    return 0


def cmd_verify(case: str, csv_override: str | None) -> int:
    csv = _csv_for_case(case, csv_override)
    codec = ClickCodec()
    expected_csv = RungGrid.from_csv(csv).to_csv()
    src_path, back_path, result_path = _paths(case)
    if not src_path.exists():
        raise FileNotFoundError(
            f"Missing source file for case {case!r}: {src_path}. Run prepare first."
        )

    src = src_path.read_bytes()
    back = read_from_clipboard()
    back_path.write_bytes(back)

    header_ok = header_structural_equal(src, back)
    topo_ok = parse_wire_topology(src) == parse_wire_topology(back)

    decode_ok = False
    decoded_csv: str
    decode_error: str | None = None
    try:
        decoded_csv = codec.decode(back).to_csv()
        decode_ok = decoded_csv == expected_csv
    except Exception as exc:  # pragma: no cover - diagnostic path
        decoded_csv = ""
        decode_error = f"{type(exc).__name__}: {exc}"

    result = {
        "case": case,
        "csv": csv,
        "expected_csv": expected_csv,
        "clipboard_len": len(back),
        "header_ok": header_ok,
        "topology_ok": topo_ok,
        "decode_ok": decode_ok,
        "decoded_csv": decoded_csv,
        "decode_error": decode_error,
        "source_file": str(src_path),
        "pasteback_file": str(back_path),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2))
    print(f"Saved result: {result_path}")
    return 0 if (len(back) == 8192 and header_ok and topo_ok and decode_ok) else 1


def cmd_compare(
    case: str,
    csv_override: str | None,
    native_file: str | None,
    native_label: str | None,
) -> int:
    csv = _csv_for_case(case, csv_override)
    codec = ClickCodec()
    src_path, _, _ = _paths(case)
    src = codec.encode(RungGrid.from_csv(csv))
    src_path.write_bytes(src)

    if native_file:
        native_path = Path(native_file)
    else:
        chosen_label = native_label or f"{case}_native"
        native_path = Path("scratchpad/captures") / f"{chosen_label}.bin"
    if not native_path.exists():
        raise FileNotFoundError(f"Native capture not found: {native_path}")

    native = native_path.read_bytes()
    raw_diff_count = sum(1 for a, b in zip(src, native) if a != b)
    header_end = HEADER_ENTRY_BASE + HEADER_ENTRY_COUNT * HEADER_ENTRY_SIZE
    header_raw_diff_count = sum(
        1 for i in range(HEADER_ENTRY_BASE, min(header_end, len(src), len(native))) if src[i] != native[i]
    )
    header_ok = header_structural_equal(src, native)
    topo_src = parse_wire_topology(src)
    topo_native = parse_wire_topology(native)
    topology_ok = topo_src == topo_native
    type_src = _type_markers(src)
    type_native = _type_markers(native)

    result = {
        "case": case,
        "csv": csv,
        "source_file": str(src_path),
        "native_file": str(native_path),
        "source_len": len(src),
        "native_len": len(native),
        "raw_diff_count": raw_diff_count,
        "header_raw_diff_count": header_raw_diff_count,
        "header_structural_equal": header_ok,
        "topology_equal": topology_ok,
        "source_topology_cells": len(topo_src.cells),
        "native_topology_cells": len(topo_native.cells),
        "source_type_markers": [(hex(off), hex(t)) for off, t in type_src],
        "native_type_markers": [(hex(off), hex(t)) for off, t in type_native],
    }
    compare_path = _compare_path(case)
    compare_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2))
    print(f"Saved result: {compare_path}")
    return 0 if header_ok and topology_ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List default smoke cases")

    p_prepare = sub.add_parser("prepare", help="Encode a case and put it on clipboard")
    p_prepare.add_argument("--case", required=True, help="Case label")
    p_prepare.add_argument("--csv", help="Optional CSV override for this run")

    p_verify = sub.add_parser("verify", help="Read copied-back bytes and compare")
    p_verify.add_argument("--case", required=True, help="Case label")
    p_verify.add_argument("--csv", help="Optional CSV override for this run")

    p_compare = sub.add_parser("compare", help="Compare generated bytes to a native capture")
    p_compare.add_argument("--case", required=True, help="Case label")
    p_compare.add_argument("--csv", help="Optional CSV override for this run")
    p_compare.add_argument("--native-file", help="Path to native capture .bin")
    p_compare.add_argument("--native-label", help="Capture label under scratchpad/captures")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "prepare":
        return cmd_prepare(args.case, args.csv)
    if args.cmd == "verify":
        return cmd_verify(args.case, args.csv)
    if args.cmd == "compare":
        return cmd_compare(args.case, args.csv, args.native_file, args.native_label)
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
