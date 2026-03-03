"""Manual pasteback smoke-test helper (non-interactive).

Usage examples:
  uv run python scratchpad/pasteback_smoke.py list
  uv run python scratchpad/pasteback_smoke.py prepare --case smoke_simple
  uv run python scratchpad/pasteback_smoke.py compare --case smoke_simple --native-label smoke_simple_native
  # In Click: paste rung, then copy that same rung back
  uv run python scratchpad/pasteback_smoke.py verify --case smoke_simple
  uv run python scratchpad/pasteback_smoke.py matrix list
  uv run python scratchpad/pasteback_smoke.py matrix prepare --id two_series_first_immediate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from clicknick.ladder import (
    ClickCodec,
    InstructionType,
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
MATRIX_PATH = Path("scratchpad/instruction-matrix.json")


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


def _resolve_native_path(
    *,
    case: str,
    native_file: str | None,
    native_label: str | None,
) -> Path:
    if native_file:
        path = Path(native_file)
        if not path.exists():
            raise FileNotFoundError(f"Native capture not found: {path}")
        return path

    chosen_label = native_label or f"{case}_native"
    candidates = [
        Path("scratchpad/captures") / f"{chosen_label}.bin",
        Path("tests/fixtures/ladder_captures") / f"{chosen_label}.bin",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Native capture not found. Tried: " + ", ".join(str(candidate) for candidate in candidates)
    )


def _load_matrix(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Matrix file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"Matrix file must contain a list at 'cases': {path}")

    seen_ids: set[str] = set()
    normalized: list[dict[str, str]] = []
    for entry in cases:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid matrix entry (not object): {entry!r}")
        case_id = entry.get("id")
        csv = entry.get("csv")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Invalid matrix entry id: {entry!r}")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate matrix id: {case_id!r}")
        if not isinstance(csv, str) or not csv:
            raise ValueError(f"Invalid matrix csv for id {case_id!r}")
        seen_ids.add(case_id)
        normalized.append(entry)
    return normalized


def _matrix_case(cases: list[dict[str, str]], case_id: str) -> dict[str, str]:
    for entry in cases:
        if entry["id"] == case_id:
            return entry
    raise ValueError(f"Unknown matrix id {case_id!r}")


def _is_matrix_known_unsupported(entry: dict[str, str]) -> bool:
    return bool(entry.get("known_unsupported"))


def _type_markers(data: bytes) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in range(0x0A60, min(len(data), 0x1A60) - 1):
        if data[i + 1] == 0x27 and data[i] != 0x00:
            out.append((i, data[i]))
    return out


def _clipboard_block_summary(data: bytes) -> list[dict[str, object]]:
    """Summarize 8KiB clipboard blocks for non-single-rung captures."""
    if len(data) % 8192 != 0:
        return []
    blocks: list[dict[str, object]] = []
    for idx in range(len(data) // 8192):
        chunk = data[idx * 8192 : (idx + 1) * 8192]
        markers = [
            (off, typ)
            for off, typ in _type_markers(chunk)
            if typ in (
                InstructionType.CONTACT_NO.value,
                InstructionType.CONTACT_NC.value,
                InstructionType.CONTACT_EDGE.value,
                InstructionType.COIL_OUT.value,
                InstructionType.COIL_LATCH.value,
                InstructionType.COIL_RESET.value,
            )
        ]
        blocks.append(
            {
                "index": idx,
                "row_class": f"0x{chunk[0x0254]:02X}",
                "marker_count": len(markers),
                "marker_types": [f"0x{typ:02X}" for _, typ in markers],
            }
        )
    return blocks


def cmd_list() -> int:
    for label, csv in DEFAULT_CASES.items():
        print(f"{label}: {csv}")
    return 0


def cmd_matrix_list(matrix_file: str | None) -> int:
    path = Path(matrix_file) if matrix_file else MATRIX_PATH
    cases = _load_matrix(path)
    print(f"Matrix: {path}")
    for entry in cases:
        native = entry.get("native_label", "")
        flags: list[str] = []
        if native:
            flags.append(f"native:{native}")
        if _is_matrix_known_unsupported(entry):
            flags.append("known_unsupported")
        suffix = f" [{' | '.join(flags)}]" if flags else ""
        print(f"{entry['id']}: {entry['csv']}{suffix}")
    return 0


def cmd_matrix_status(matrix_file: str | None) -> int:
    path = Path(matrix_file) if matrix_file else MATRIX_PATH
    cases = _load_matrix(path)
    print(f"Matrix status: {path}")
    for entry in cases:
        case_id = entry["id"]
        if _is_matrix_known_unsupported(entry):
            print(f"{case_id}: known-unsupported")
            continue

        src_path, back_path, result_path = _paths(case_id)
        compare_path = _compare_path(case_id)
        status = "new"
        details: list[str] = []
        if src_path.exists():
            status = "prepared"
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                verify_ok = (
                    result.get("clipboard_len") == 8192
                    and bool(result.get("header_ok"))
                    and bool(result.get("topology_ok"))
                    and bool(result.get("decode_ok"))
                )
                status = "verified-ok" if verify_ok else "verified-fail"
                details.append(f"decode_ok={result.get('decode_ok')}")
            except Exception:
                status = "verified-unknown"
        if compare_path.exists():
            try:
                comp = json.loads(compare_path.read_text(encoding="utf-8"))
                compare_ok = bool(comp.get("header_structural_equal")) and bool(comp.get("topology_equal"))
                status = "compare-ok" if compare_ok else "compare-fail"
                details.append(f"raw_diff={comp.get('raw_diff_count')}")
            except Exception:
                status = "compare-unknown"
        if back_path.exists():
            details.append("has_back_bin=true")
        details_text = f" ({', '.join(details)})" if details else ""
        print(f"{case_id}: {status}{details_text}")
    return 0


def cmd_matrix_prepare(case_id: str, matrix_file: str | None) -> int:
    path = Path(matrix_file) if matrix_file else MATRIX_PATH
    entry = _matrix_case(_load_matrix(path), case_id)
    if _is_matrix_known_unsupported(entry):
        print(f"Matrix id {case_id} is marked known_unsupported; skipping prepare.")
        return 2
    print(f"Preparing matrix id {case_id}: {entry['csv']}")
    return cmd_prepare(case_id, entry["csv"])


def cmd_matrix_verify(case_id: str, matrix_file: str | None) -> int:
    path = Path(matrix_file) if matrix_file else MATRIX_PATH
    entry = _matrix_case(_load_matrix(path), case_id)
    if _is_matrix_known_unsupported(entry):
        print(f"Matrix id {case_id} is marked known_unsupported; skipping verify.")
        return 2
    print(f"Verifying matrix id {case_id}: {entry['csv']}")
    return cmd_verify(case_id, entry["csv"])


def cmd_matrix_compare(case_id: str, matrix_file: str | None) -> int:
    path = Path(matrix_file) if matrix_file else MATRIX_PATH
    entry = _matrix_case(_load_matrix(path), case_id)
    if _is_matrix_known_unsupported(entry):
        print(f"Matrix id {case_id} is marked known_unsupported; skipping compare.")
        return 2
    native_label = entry.get("native_label")
    print(
        f"Comparing matrix id {case_id}: {entry['csv']} "
        f"{f'vs {native_label}' if native_label else '(no native label configured)'}"
    )
    return cmd_compare(case_id, entry["csv"], None, native_label)


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

    single_rung = len(back) == 8192
    header_ok = header_structural_equal(src, back) if single_rung else False
    topo_ok = (parse_wire_topology(src) == parse_wire_topology(back)) if single_rung else False

    decode_ok = False
    decoded_csv: str
    decode_error: str | None = None
    if single_rung:
        try:
            decoded_csv = codec.decode(back).to_csv()
            decode_ok = decoded_csv == expected_csv
        except Exception as exc:  # pragma: no cover - diagnostic path
            decoded_csv = ""
            decode_error = f"{type(exc).__name__}: {exc}"
    else:
        decoded_csv = ""
        decode_error = f"Expected 8192-byte single-rung clipboard payload, got {len(back)} bytes"

    block_summary = _clipboard_block_summary(back) if not single_rung else []

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
    if block_summary:
        result["block_summary"] = block_summary
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2))
    if block_summary:
        print(
            "Note: clipboard contains multiple 8KiB blocks. In Click, copy exactly one rung and rerun verify."
        )
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

    native_path = _resolve_native_path(
        case=case,
        native_file=native_file,
        native_label=native_label,
    )

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

    p_matrix = sub.add_parser("matrix", help="Run smoke actions from instruction matrix")
    p_matrix_sub = p_matrix.add_subparsers(dest="matrix_cmd", required=True)

    p_matrix_list = p_matrix_sub.add_parser("list", help="List matrix cases")
    p_matrix_list.add_argument("--matrix-file", help="Path to matrix JSON file")

    p_matrix_status = p_matrix_sub.add_parser("status", help="Show artifact status for matrix cases")
    p_matrix_status.add_argument("--matrix-file", help="Path to matrix JSON file")

    p_matrix_prepare = p_matrix_sub.add_parser("prepare", help="Prepare one matrix case")
    p_matrix_prepare.add_argument("--id", required=True, help="Matrix case id")
    p_matrix_prepare.add_argument("--matrix-file", help="Path to matrix JSON file")

    p_matrix_verify = p_matrix_sub.add_parser("verify", help="Verify one matrix case")
    p_matrix_verify.add_argument("--id", required=True, help="Matrix case id")
    p_matrix_verify.add_argument("--matrix-file", help="Path to matrix JSON file")

    p_matrix_compare = p_matrix_sub.add_parser("compare", help="Compare one matrix case to native")
    p_matrix_compare.add_argument("--id", required=True, help="Matrix case id")
    p_matrix_compare.add_argument("--matrix-file", help="Path to matrix JSON file")

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
    if args.cmd == "matrix":
        if args.matrix_cmd == "list":
            return cmd_matrix_list(args.matrix_file)
        if args.matrix_cmd == "status":
            return cmd_matrix_status(args.matrix_file)
        if args.matrix_cmd == "prepare":
            return cmd_matrix_prepare(args.id, args.matrix_file)
        if args.matrix_cmd == "verify":
            return cmd_matrix_verify(args.id, args.matrix_file)
        if args.matrix_cmd == "compare":
            return cmd_matrix_compare(args.id, args.matrix_file)
        parser.error(f"Unknown matrix command: {args.matrix_cmd}")
        return 2
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
