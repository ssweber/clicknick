#!/usr/bin/env python3
"""Analyze header/session-counter-like bytes across ladder capture binaries.

Usage examples:

  uv run python devtools/analyze_session_counter.py \
      --source payload \
      --label smoke_simple_native --label smoke_immediate_native

  uv run python devtools/analyze_session_counter.py \
      --file scratchpad/captures/smoke_simple_native.bin \
      --file scratchpad/captures/smoke_immediate_native.bin

The tool resolves labels through scratchpad/ladder_capture_manifest.json,
extracts header bytes, and reports pairwise structural comparisons with
different volatile-byte masks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clicknick.ladder.codec import ClickCodec
from clicknick.ladder.topology import (
    HEADER_ENTRY_BASE,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    HEADER_ROW_CLASS_OFFSET,
    header_structural_equal,
    parse_wire_topology,
)

MANIFEST_PATH = Path("scratchpad/ladder_capture_manifest.json")
TRAILER_OFFSET = 0x0A59
HEADER_OFF_05 = 0x05
HEADER_OFF_11 = 0x11
HEADER_OFF_17 = 0x17
HEADER_OFF_18 = 0x18


@dataclass(frozen=True)
class CaptureSummary:
    name: str
    source_kind: str
    source_path: Path
    record_len: int
    data: bytes
    row_class: int
    h05: int
    h11: int
    h17: int
    h18: int
    t59: int
    h11_bias: int
    uniform_05: bool
    uniform_11: bool
    uniform_17: bool
    uniform_18: bool
    decode_csv: str
    topology_rows_full: int
    topology_nonempty_cells_full: int
    topology_hash: str
    header_hash_mask_0511: str
    header_hash_mask_05111718: str


def _masked_header_hash(data: bytes, offsets: Iterable[int]) -> str:
    header_start = HEADER_ENTRY_BASE
    header_end = HEADER_ENTRY_BASE + HEADER_ENTRY_COUNT * HEADER_ENTRY_SIZE
    masked = bytearray(data[header_start:header_end])
    for column in range(HEADER_ENTRY_COUNT):
        entry = column * HEADER_ENTRY_SIZE
        for off in offsets:
            masked[entry + off] = 0
    return hashlib.sha1(bytes(masked)).hexdigest()


def _is_uniform_per_entry(data: bytes, offset: int) -> bool:
    header_start = HEADER_ENTRY_BASE
    first = data[header_start + offset]
    for column in range(1, HEADER_ENTRY_COUNT):
        entry = header_start + column * HEADER_ENTRY_SIZE
        if data[entry + offset] != first:
            return False
    return True


def _decode_csv(data: bytes) -> str:
    codec = ClickCodec()
    try:
        return codec.decode(data).to_csv()
    except Exception as exc:  # pragma: no cover - diagnostics only
        return f"__DECODE_ERROR__:{type(exc).__name__}:{exc}"


def _summarize(name: str, source_path: Path, source_kind: str) -> CaptureSummary:
    raw = source_path.read_bytes()
    if len(raw) < 8192:
        raise ValueError(f"{source_path} is too short ({len(raw)} bytes)")
    data = raw[:8192]

    h05 = data[HEADER_ENTRY_BASE + HEADER_OFF_05]
    h11 = data[HEADER_ENTRY_BASE + HEADER_OFF_11]
    h17 = data[HEADER_ENTRY_BASE + HEADER_OFF_17]
    h18 = data[HEADER_ENTRY_BASE + HEADER_OFF_18]
    row_class = data[HEADER_ENTRY_BASE + HEADER_ROW_CLASS_OFFSET]
    t59 = data[TRAILER_OFFSET]

    topology = parse_wire_topology(raw)
    topology_hash = hashlib.sha1(repr(topology).encode("utf-8")).hexdigest()

    return CaptureSummary(
        name=name,
        source_kind=source_kind,
        source_path=source_path,
        record_len=len(raw),
        data=data,
        row_class=row_class,
        h05=h05,
        h11=h11,
        h17=h17,
        h18=h18,
        t59=t59,
        h11_bias=(h11 - ((2 * h05) & 0xFF)) & 0xFF,
        uniform_05=_is_uniform_per_entry(data, HEADER_OFF_05),
        uniform_11=_is_uniform_per_entry(data, HEADER_OFF_11),
        uniform_17=_is_uniform_per_entry(data, HEADER_OFF_17),
        uniform_18=_is_uniform_per_entry(data, HEADER_OFF_18),
        decode_csv=_decode_csv(data),
        topology_rows_full=topology.row_count,
        topology_nonempty_cells_full=len(topology.cells),
        topology_hash=topology_hash,
        header_hash_mask_0511=_masked_header_hash(data, (0x05, 0x11)),
        header_hash_mask_05111718=_masked_header_hash(data, (0x05, 0x11, 0x17, 0x18)),
    )


def _resolve_label_paths(
    labels: list[str],
    *,
    source_mode: Literal["auto", "payload", "verify"],
) -> list[tuple[str, str, Path]]:
    if not labels:
        return []
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_label = {entry["capture_label"]: entry for entry in manifest.get("entries", [])}
    out: list[tuple[str, str, Path]] = []
    for label in labels:
        entry = by_label.get(label)
        if not entry:
            raise KeyError(f"Label not found in manifest: {label}")
        payload_file = entry.get("payload_file")
        verify_result_file = entry.get("verify_result_file")

        source_kind: str | None = None
        payload_text: str | None = None
        if source_mode == "payload":
            source_kind = "payload_file"
            payload_text = payload_file
        elif source_mode == "verify":
            source_kind = "verify_result_file"
            payload_text = verify_result_file
        else:
            if verify_result_file:
                source_kind = "verify_result_file"
                payload_text = verify_result_file
            else:
                source_kind = "payload_file"
                payload_text = payload_file

        if not payload_text or source_kind is None:
            raise ValueError(f"Label has no payload path: {label}")
        path = Path(payload_text)
        if not path.exists():
            raise FileNotFoundError(f"Payload file not found for {label}: {path}")
        out.append((label, source_kind, path))
    return out


def _delta_u8(old: int, new: int) -> int:
    """Return signed 8-bit modular delta (new - old)."""
    return ((new - old + 128) % 256) - 128


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", action="append", default=[], help="Capture label from manifest")
    p.add_argument("--file", action="append", default=[], help="Explicit .bin path")
    p.add_argument(
        "--source",
        choices=("auto", "payload", "verify"),
        default="auto",
        help=(
            "For --label resolution: auto uses verify_result_file first, then payload_file; "
            "payload forces payload_file; verify forces verify_result_file."
        ),
    )
    return p


def _entry_local_offset_values(s: CaptureSummary, off: int) -> tuple[int, ...]:
    values: list[int] = []
    for column in range(HEADER_ENTRY_COUNT):
        entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
        values.append(s.data[entry_start + off])
    return tuple(values)


def main() -> int:
    args = build_parser().parse_args()
    targets: list[tuple[str, str, Path]] = []
    targets.extend(_resolve_label_paths(args.label, source_mode=args.source))
    for file_text in args.file:
        path = Path(file_text)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        targets.append((path.stem, "file", path))
    if not targets:
        raise SystemExit("Provide at least one --label or --file")

    summaries = [_summarize(name, path, source_kind) for name, source_kind, path in targets]

    print("Capture summaries")
    for s in summaries:
        print(f"- {s.name} [{s.source_kind}] -> {s.source_path}")
        print(
            f"  len={s.record_len} row_class=0x{s.row_class:02X} "
            f"h05=0x{s.h05:02X} h11=0x{s.h11:02X} h17=0x{s.h17:02X} h18=0x{s.h18:02X} "
            f"t59=0x{s.t59:02X} bias=(h11-2*h05)=0x{s.h11_bias:02X}"
        )
        print(
            "  uniform-entry bytes: "
            f"+05={s.uniform_05} +11={s.uniform_11} +17={s.uniform_17} +18={s.uniform_18}"
        )
        print(
            f"  topology(full-record): rows={s.topology_rows_full} "
            f"nonempty_cells={s.topology_nonempty_cells_full}"
        )
        print(f"  csv={s.decode_csv}")

    if len(summaries) > 1:
        varying_offsets: list[int] = []
        for off in range(HEADER_ENTRY_SIZE):
            entry0_values = {s.data[HEADER_ENTRY_BASE + off] for s in summaries}
            if len(entry0_values) <= 1:
                continue
            varying_offsets.append(off)

        print("\nVarying header entry offsets (across selected captures)")
        if not varying_offsets:
            print("- none")
        else:
            for off in varying_offsets:
                values = " ".join(
                    f"{s.name}=0x{s.data[HEADER_ENTRY_BASE + off]:02X}" for s in summaries
                )
                column_uniform = all(
                    len(set(_entry_local_offset_values(s, off))) == 1 for s in summaries
                )
                print(f"- +0x{off:02X}: {values} (column_uniform={column_uniform})")

    if len(summaries) > 1:
        baseline = summaries[0]
        print("\nPairwise vs first capture")
        for s in summaries[1:]:
            print(f"- {baseline.name} -> {s.name}")
            print(
                f"  delta h05={_delta_u8(baseline.h05, s.h05):+d} "
                f"h11={_delta_u8(baseline.h11, s.h11):+d} "
                f"h17={_delta_u8(baseline.h17, s.h17):+d} "
                f"t59={_delta_u8(baseline.t59, s.t59):+d}"
            )
            print(f"  topology_equal={baseline.topology_hash == s.topology_hash}")
            print(f"  header_eq(mask+05+11)={header_structural_equal(baseline.data, s.data)}")
            print(
                "  header_eq(mask+05+11+17+18)="
                f"{baseline.header_hash_mask_05111718 == s.header_hash_mask_05111718}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
