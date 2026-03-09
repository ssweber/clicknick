#!/usr/bin/env python3
"""Derive stable/volatile offset masks from native/synthetic ladder captures.

The tool compares first-record bytes (0..8191) across selected captures, groups
records by scenario/expected rows/custom key, and emits:

- JSON: global stable/volatile offsets, grouped volatility stats, and
  classification candidates (session tuple / width / structure).
- CSV: offset-level value frequency table.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from clicknick.ladder.topology import (
    HEADER_ENTRY_BASE,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    parse_wire_topology,
)

BUFFER_SIZE = 8192
TRAILER_MIRROR_OFFSET = 0x0A59
SESSION_HEADER_ENTRY_OFFSETS = (0x05, 0x11, 0x17, 0x18)
DEFAULT_MANIFEST_PATH = Path("scratchpad/ladder_capture_manifest.json")
WIDTH_VARIANT_RE = re.compile(r"(.+)_width_(default|narrow|wide)(_native)?$", re.IGNORECASE)


@dataclass(frozen=True)
class CaptureRecord:
    name: str
    source_kind: str
    source_field: str
    source_path: Path
    scenario: str | None
    expected_rows: tuple[str, ...]
    group: str
    record_len: int
    data: bytes
    topology_hash: str


def session_tuple_offsets() -> list[int]:
    offsets: list[int] = [TRAILER_MIRROR_OFFSET]
    for column in range(HEADER_ENTRY_COUNT):
        entry = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
        for rel in SESSION_HEADER_ENTRY_OFFSETS:
            offsets.append(entry + rel)
    return sorted(set(offsets))


def _parse_uint(raw: str) -> int:
    return int(raw, 0)


def _parse_custom_group(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"Invalid --custom-group {raw!r}; expected <target>=<group>")
    target_raw, group_raw = raw.split("=", 1)
    target = target_raw.strip()
    group = group_raw.strip()
    if not target:
        raise ValueError(f"Invalid --custom-group {raw!r}; target is empty")
    if not group:
        raise ValueError(f"Invalid --custom-group {raw!r}; group is empty")
    return target, group


def _resolve_path(path_text: str, *, root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _load_first_record(path: Path) -> tuple[bytes, int]:
    raw = path.read_bytes()
    if len(raw) < BUFFER_SIZE:
        raise ValueError(
            f"{path}: payload too short ({len(raw)} bytes); need at least {BUFFER_SIZE}"
        )
    return raw[:BUFFER_SIZE], len(raw)


def _topology_hash(data: bytes) -> str:
    try:
        topology = parse_wire_topology(data)
    except Exception:
        return "__topology_parse_error__"
    return hashlib.sha1(repr(topology).encode("utf-8")).hexdigest()


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _entry_path(entry: dict[str, Any], *, source: str) -> tuple[str, str]:
    if source == "payload":
        path_text = entry.get("payload_file")
        if not path_text:
            raise ValueError(f"Entry {entry['capture_label']!r} has no payload_file")
        return "payload_file", path_text
    path_text = entry.get("verify_result_file")
    if not path_text:
        raise ValueError(f"Entry {entry['capture_label']!r} has no verify_result_file")
    return "verify_result_file", path_text


def _group_from_expected_rows(rows: tuple[str, ...]) -> str:
    if not rows:
        return "__no_expected_rows__"
    return " || ".join(rows)


def _lookup_custom_group(
    record_name: str, record_path: Path, mapping: dict[str, str]
) -> str | None:
    probes = (
        record_name,
        str(record_path),
        record_path.as_posix(),
        record_path.name,
        record_path.stem,
    )
    for probe in probes:
        if probe in mapping:
            return mapping[probe]
    return None


def _group_key_for_record(
    *,
    group_key: str,
    scenario: str | None,
    expected_rows: tuple[str, ...],
    record_name: str,
    record_path: Path,
    custom_groups: dict[str, str],
) -> str:
    if group_key == "scenario":
        return scenario or "__files__"
    if group_key == "expected_rows":
        return _group_from_expected_rows(expected_rows)
    resolved = _lookup_custom_group(record_name, record_path, custom_groups)
    if resolved is None:
        raise ValueError(
            "Missing custom group mapping for "
            f"{record_name!r}. Provide --custom-group {record_name}=<group>."
        )
    return resolved


def load_records(
    *,
    manifest_path: Path,
    labels: list[str],
    files: list[str],
    source: str,
    group_key: str,
    custom_groups: dict[str, str],
    cwd: Path | None = None,
) -> list[CaptureRecord]:
    if not labels and not files:
        raise ValueError("Provide at least one --label or --file")

    records: list[CaptureRecord] = []
    cwd = cwd or Path.cwd()
    manifest_root = manifest_path.resolve().parents[1]

    if labels:
        manifest = _load_manifest(manifest_path)
        by_label = {entry["capture_label"]: entry for entry in manifest.get("entries", [])}
        for label in labels:
            entry = by_label.get(label)
            if entry is None:
                raise KeyError(f"Label not found in manifest: {label}")
            source_field, path_text = _entry_path(entry, source=source)
            path = _resolve_path(path_text, root=manifest_root)
            if not path.exists():
                raise FileNotFoundError(f"{label}: source file not found: {path}")
            data, record_len = _load_first_record(path)
            expected_rows = tuple(entry.get("verify_expected_rows") or entry.get("rung_rows") or [])
            group = _group_key_for_record(
                group_key=group_key,
                scenario=entry.get("scenario"),
                expected_rows=expected_rows,
                record_name=label,
                record_path=path,
                custom_groups=custom_groups,
            )
            records.append(
                CaptureRecord(
                    name=label,
                    source_kind="label",
                    source_field=source_field,
                    source_path=path,
                    scenario=entry.get("scenario"),
                    expected_rows=expected_rows,
                    group=group,
                    record_len=record_len,
                    data=data,
                    topology_hash=_topology_hash(data),
                )
            )

    for file_text in files:
        path = _resolve_path(file_text, root=cwd)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        data, record_len = _load_first_record(path)
        name = path.stem
        expected_rows: tuple[str, ...] = ()
        group = _group_key_for_record(
            group_key=group_key,
            scenario=None,
            expected_rows=expected_rows,
            record_name=name,
            record_path=path,
            custom_groups=custom_groups,
        )
        records.append(
            CaptureRecord(
                name=name,
                source_kind="file",
                source_field="file",
                source_path=path,
                scenario=None,
                expected_rows=expected_rows,
                group=group,
                record_len=record_len,
                data=data,
                topology_hash=_topology_hash(data),
            )
        )

    return records


def _volatile_offsets(records: list[CaptureRecord]) -> tuple[list[int], list[int]]:
    volatile: list[int] = []
    stable: list[int] = []
    for offset in range(BUFFER_SIZE):
        values = {record.data[offset] for record in records}
        if len(values) > 1:
            volatile.append(offset)
        else:
            stable.append(offset)
    return volatile, stable


def _records_by_group(records: list[CaptureRecord]) -> dict[str, list[CaptureRecord]]:
    out: dict[str, list[CaptureRecord]] = defaultdict(list)
    for record in records:
        out[record.group].append(record)
    return dict(sorted(out.items()))


def _is_width_record(name: str) -> bool:
    return "width_" in name.lower()


def _width_family_key(name: str) -> str | None:
    match = WIDTH_VARIANT_RE.fullmatch(name)
    if not match:
        return None
    return f"{match.group(1).lower()}_width"


def _is_wire_geometry_record(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("wire_a", "wire_ab", "wire_full_row"))


def _width_candidate_offsets(records: list[CaptureRecord], varying_offsets: set[int]) -> set[int]:
    width_records = [record for record in records if _is_width_record(record.name)]
    if len(width_records) < 2:
        return set()

    families: dict[str, list[CaptureRecord]] = defaultdict(list)
    for record in width_records:
        family = _width_family_key(record.name)
        if family is None:
            continue
        families[family].append(record)
    if not families:
        return set()

    candidates: set[int] = set()
    for family_records in families.values():
        if len(family_records) < 2:
            continue
        family_candidates = {
            offset
            for offset in varying_offsets
            if len({record.data[offset] for record in family_records}) > 1
        }
        candidates.update(family_candidates)
    if not candidates:
        return set()

    non_width_records = [record for record in records if not _is_width_record(record.name)]
    non_width_groups: dict[str, list[CaptureRecord]] = defaultdict(list)
    for record in non_width_records:
        non_width_groups[record.topology_hash].append(record)

    filtered: set[int] = set()
    for offset in candidates:
        volatile_elsewhere = False
        for group_records in non_width_groups.values():
            if len(group_records) < 2:
                continue
            if len({record.data[offset] for record in group_records}) > 1:
                volatile_elsewhere = True
                break
        if not volatile_elsewhere:
            filtered.add(offset)
    return filtered


def _structure_candidate_offsets(
    records: list[CaptureRecord], varying_offsets: set[int]
) -> set[int]:
    structure_records = [record for record in records if _is_wire_geometry_record(record.name)]
    if len(structure_records) < 2:
        return set()
    return {
        offset
        for offset in varying_offsets
        if len({record.data[offset] for record in structure_records}) > 1
    }


def build_overlay(records: list[CaptureRecord]) -> dict[str, Any]:
    if not records:
        raise ValueError("No records provided")

    global_volatile, global_stable = _volatile_offsets(records)
    varying_set = set(global_volatile)

    by_group = _records_by_group(records)
    groups: dict[str, Any] = {}
    for group_name, group_records in by_group.items():
        volatile, stable = _volatile_offsets(group_records)
        groups[group_name] = {
            "record_count": len(group_records),
            "volatile_offset_count": len(volatile),
            "stable_offset_count": len(stable),
            "volatile_offsets": volatile,
        }

    session_offsets = set(session_tuple_offsets()) & varying_set
    width_offsets = _width_candidate_offsets(records, varying_set) - session_offsets
    structure_offsets = (
        _structure_candidate_offsets(records, varying_set) - session_offsets - width_offsets
    )
    unclassified = varying_set - session_offsets - width_offsets - structure_offsets

    return {
        "buffer_size": BUFFER_SIZE,
        "record_count": len(records),
        "records": [
            {
                "name": record.name,
                "source_kind": record.source_kind,
                "source_field": record.source_field,
                "source_path": str(record.source_path),
                "scenario": record.scenario,
                "expected_rows": list(record.expected_rows),
                "group": record.group,
                "record_len": record.record_len,
                "topology_hash": record.topology_hash,
            }
            for record in records
        ],
        "global": {
            "volatile_offset_count": len(global_volatile),
            "stable_offset_count": len(global_stable),
            "volatile_offsets": global_volatile,
            "stable_offsets": global_stable,
        },
        "groups": groups,
        "classification": {
            "session_tuple_offsets_full": session_tuple_offsets(),
            "session_tuple_candidates": sorted(session_offsets),
            "width_candidates": sorted(width_offsets),
            "structure_candidates": sorted(structure_offsets),
            "unclassified_varying": sorted(unclassified),
        },
    }


def build_frequency_csv(records: list[CaptureRecord], *, include_stable: bool = False) -> str:
    by_group = _records_by_group(records)
    out = StringIO()
    writer = csv.DictWriter(
        out,
        fieldnames=[
            "offset",
            "offset_hex",
            "value",
            "value_hex",
            "count",
            "frequency",
            "varying_global",
            "group_counts",
        ],
    )
    writer.writeheader()
    for offset in range(BUFFER_SIZE):
        global_counter = Counter(record.data[offset] for record in records)
        varying = len(global_counter) > 1
        if not include_stable and not varying:
            continue
        for value, count in sorted(global_counter.items()):
            group_parts: list[str] = []
            for group_name, group_records in by_group.items():
                in_group = sum(1 for record in group_records if record.data[offset] == value)
                if in_group:
                    group_parts.append(f"{group_name}:{in_group}")
            writer.writerow(
                {
                    "offset": offset,
                    "offset_hex": f"0x{offset:04X}",
                    "value": value,
                    "value_hex": f"0x{value:02X}",
                    "count": count,
                    "frequency": f"{count / len(records):.6f}",
                    "varying_global": str(varying).lower(),
                    "group_counts": ";".join(group_parts),
                }
            )
    return out.getvalue()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--label", action="append", default=[], help="Manifest label (repeatable)")
    parser.add_argument(
        "--file", action="append", default=[], help="Direct .bin file path (repeatable)"
    )
    parser.add_argument(
        "--source",
        choices=("payload", "verify"),
        default="payload",
        help="Label source field: payload_file or verify_result_file",
    )
    parser.add_argument(
        "--group-key",
        choices=("expected_rows", "scenario", "custom"),
        default="scenario",
        help="Grouping mode for volatility stats",
    )
    parser.add_argument(
        "--custom-group",
        action="append",
        default=[],
        help="Custom mapping <target>=<group>; target can be label, file name, or path",
    )
    parser.add_argument("--json-out", help="Optional JSON output file")
    parser.add_argument("--csv-out", help="Optional CSV output file")
    parser.add_argument(
        "--csv-all",
        action="store_true",
        help="Include stable offsets in CSV output (default: varying offsets only)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    custom_groups = dict(_parse_custom_group(item) for item in args.custom_group)
    manifest_path = Path(args.manifest).resolve()
    records = load_records(
        manifest_path=manifest_path,
        labels=args.label,
        files=args.file,
        source=args.source,
        group_key=args.group_key,
        custom_groups=custom_groups,
    )
    overlay = build_overlay(records)
    overlay["group_key"] = args.group_key
    overlay["source"] = args.source

    csv_text = build_frequency_csv(records, include_stable=args.csv_all)

    json_text = json.dumps(overlay, indent=2)
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_text + "\n", encoding="utf-8")
        print(f"Wrote JSON: {out_path}")
    else:
        print(json_text)

    if args.csv_out:
        out_path = Path(args.csv_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(csv_text, encoding="utf-8")
        print(f"Wrote CSV: {out_path}")
    elif not args.json_out:
        print()
        print(csv_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
