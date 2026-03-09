#!/usr/bin/env python3
"""Summarize verify outcomes, focusing on copied-but-mismatched rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST_PATH = Path("scratchpad/ladder_capture_manifest.json")


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _expected_rows(entry: dict[str, Any]) -> list[str]:
    expected = entry.get("verify_expected_rows")
    if isinstance(expected, list) and expected:
        return expected
    fallback = entry.get("rung_rows")
    if isinstance(fallback, list):
        return fallback
    return []


def _observed_rows(entry: dict[str, Any]) -> list[str]:
    observed = entry.get("verify_observed_rows")
    if isinstance(observed, list):
        return observed
    return []


def build_mismatch_report(
    manifest: dict[str, Any], *, capture_type: str = "synthetic"
) -> dict[str, Any]:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Manifest entries must be a list")

    if capture_type != "all":
        scoped = [entry for entry in entries if entry.get("capture_type") == capture_type]
    else:
        scoped = list(entries)

    status_counts = Counter(str(entry.get("verify_status")) for entry in scoped)
    event_counts = Counter(str(entry.get("verify_clipboard_event")) for entry in scoped)

    copied_entries = [entry for entry in scoped if entry.get("verify_clipboard_event") == "copied"]
    copied_mismatch: list[dict[str, Any]] = []
    for entry in copied_entries:
        expected_rows = _expected_rows(entry)
        observed_rows = _observed_rows(entry)
        if expected_rows == observed_rows:
            continue
        copied_mismatch.append(
            {
                "capture_label": entry.get("capture_label"),
                "capture_type": entry.get("capture_type"),
                "scenario": entry.get("scenario"),
                "verify_status": entry.get("verify_status"),
                "verify_notes": entry.get("verify_notes") or "",
                "verify_result_file": entry.get("verify_result_file"),
                "verify_clipboard_len": entry.get("verify_clipboard_len"),
                "expected_rows": expected_rows,
                "observed_rows": observed_rows,
            }
        )

    copied_mismatch.sort(key=lambda row: str(row.get("capture_label")))
    copied_mismatch_labels = [str(row.get("capture_label")) for row in copied_mismatch]

    return {
        "capture_type_filter": capture_type,
        "entry_count": len(scoped),
        "status_counts": dict(status_counts),
        "event_counts": dict(event_counts),
        "copied_count": len(copied_entries),
        "copied_mismatch_count": len(copied_mismatch),
        "copied_mismatch_labels": copied_mismatch_labels,
        "copied_mismatches": copied_mismatch,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument(
        "--type",
        choices=("native", "synthetic", "patch", "pasteback", "all"),
        default="synthetic",
        help="Capture type filter (default: synthetic)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--output", help="Optional output file path")
    return parser


def _render_human(report: dict[str, Any]) -> str:
    lines = [
        "=== Verify Mismatch Report ===",
        f"type_filter: {report['capture_type_filter']}",
        f"entries: {report['entry_count']}",
        f"copied: {report['copied_count']}",
        f"copied_mismatch: {report['copied_mismatch_count']}",
        f"status_counts: {report['status_counts']}",
        f"event_counts: {report['event_counts']}",
    ]
    mismatches = report["copied_mismatches"]
    if not mismatches:
        lines.append("mismatch_labels: (none)")
        return "\n".join(lines)

    lines.append("mismatch_labels:")
    for row in mismatches:
        label = row["capture_label"]
        status = row["verify_status"]
        scenario = row["scenario"]
        notes = row["verify_notes"]
        lines.append(f"  - {label} status={status} scenario={scenario}")
        if notes:
            lines.append(f"    notes: {notes}")
        lines.append(f"    expected: {row['expected_rows']}")
        lines.append(f"    observed: {row['observed_rows']}")
    return "\n".join(lines)


def main() -> int:
    args = _build_parser().parse_args()
    manifest = _load_manifest(Path(args.manifest))
    report = build_mismatch_report(manifest, capture_type=args.type)

    text = json.dumps(report, indent=2) if args.json else _render_human(report)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = "\n" if not text.endswith("\n") else ""
        output_path.write_text(text + suffix, encoding="utf-8")
        print(f"Wrote report: {output_path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
