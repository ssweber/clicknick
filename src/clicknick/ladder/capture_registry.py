"""Scratchpad ladder capture manifest registry (schema v2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .csv_shorthand import normalize_shorthand_row

CAPTURE_TYPES = {"native", "synthetic", "patch", "pasteback"}
PAYLOAD_SOURCE_MODES = {"shorthand", "file"}
VERIFY_EVENTS = {"copied", "crash", "cancelled"}
VERIFY_STATUSES = {"unverified", "verified_pass", "verified_fail", "blocked"}

SCRATCHPAD_MANIFEST_VERSION = 2
SCRATCHPAD_MANIFEST_DESCRIPTION = "Iterative working manifest for ladder capture workflows."


@dataclass(frozen=True)
class ScratchpadManifestPaths:
    root: Path
    manifest_path: Path
    captures_dir: Path


def utc_now_iso() -> str:
    """Return a UTC timestamp formatted as ISO-8601 with trailing Z."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_manifest() -> dict[str, object]:
    return {
        "version": SCRATCHPAD_MANIFEST_VERSION,
        "description": SCRATCHPAD_MANIFEST_DESCRIPTION,
        "entries": [],
    }


def _canonicalize_row(row: str, row_index: int) -> str:
    canonical = normalize_shorthand_row(row)
    marker = "R" if row_index == 0 else ""
    af = canonical.af if canonical.af else "..."
    return ",".join([marker, *canonical.conditions, ":", af])


def canonicalize_rows(rows: list[str]) -> list[str]:
    return [_canonicalize_row(row, row_index=i) for i, row in enumerate(rows)]


def _validate_enum(name: str, value: str | None, allowed: set[str]) -> None:
    if value is not None and value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of [{allowed_text}], got {value!r}")


def _validate_optional_path_like(name: str, value: object) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be null or a string path")


def _validate_optional_int(name: str, value: object) -> None:
    if value is not None and not isinstance(value, int):
        raise ValueError(f"{name} must be null or an integer")


def validate_entry(entry: dict[str, Any]) -> None:
    required_fields = {
        "id",
        "capture_label",
        "capture_type",
        "scenario",
        "description",
        "rung_rows",
        "payload_source_mode",
        "payload_source_file",
        "payload_file",
        "verify_clipboard_event",
        "verify_status",
        "verify_notes",
        "verify_expected_rows",
        "verify_observed_rows",
        "verify_result_file",
        "verify_clipboard_len",
        "promoted_fixture_file",
        "created_at",
        "updated_at",
    }
    missing = required_fields - set(entry)
    if missing:
        raise ValueError(f"Scratchpad entry missing required fields: {sorted(missing)}")

    if not isinstance(entry["id"], str) or not entry["id"]:
        raise ValueError("entry.id must be a non-empty string")
    if not isinstance(entry["capture_label"], str) or not entry["capture_label"]:
        raise ValueError("entry.capture_label must be a non-empty string")
    if not isinstance(entry["scenario"], str) or not entry["scenario"]:
        raise ValueError("entry.scenario must be a non-empty string")
    if not isinstance(entry["description"], str):
        raise ValueError("entry.description must be a string")
    if not isinstance(entry["verify_notes"], str):
        raise ValueError("entry.verify_notes must be a string")

    _validate_enum("entry.capture_type", entry.get("capture_type"), CAPTURE_TYPES)
    _validate_enum(
        "entry.payload_source_mode", entry.get("payload_source_mode"), PAYLOAD_SOURCE_MODES
    )
    _validate_enum("entry.verify_status", entry.get("verify_status"), VERIFY_STATUSES)
    _validate_enum(
        "entry.verify_clipboard_event", entry.get("verify_clipboard_event"), VERIFY_EVENTS
    )

    for key in ("rung_rows", "verify_expected_rows", "verify_observed_rows"):
        value = entry.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"entry.{key} must be a list[str]")

    canonicalize_rows(entry["rung_rows"])
    canonicalize_rows(entry["verify_expected_rows"])
    canonicalize_rows(entry["verify_observed_rows"])

    _validate_optional_path_like("entry.payload_source_file", entry.get("payload_source_file"))
    _validate_optional_path_like("entry.payload_file", entry.get("payload_file"))
    _validate_optional_path_like("entry.verify_result_file", entry.get("verify_result_file"))
    _validate_optional_path_like("entry.promoted_fixture_file", entry.get("promoted_fixture_file"))
    _validate_optional_int("entry.verify_clipboard_len", entry.get("verify_clipboard_len"))

    if not isinstance(entry["created_at"], str) or not entry["created_at"]:
        raise ValueError("entry.created_at must be an ISO timestamp string")
    if not isinstance(entry["updated_at"], str) or not entry["updated_at"]:
        raise ValueError("entry.updated_at must be an ISO timestamp string")


def validate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    if manifest.get("version") != SCRATCHPAD_MANIFEST_VERSION:
        raise ValueError(f"Manifest version must be {SCRATCHPAD_MANIFEST_VERSION}")
    if not isinstance(manifest.get("description"), str):
        raise ValueError("Manifest description must be a string")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Manifest entries must be a list")

    seen_labels: set[str] = set()
    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each manifest entry must be a JSON object")
        validate_entry(entry)
        label = entry["capture_label"]
        if label in seen_labels:
            raise ValueError(f"Duplicate capture_label: {label!r}")
        seen_labels.add(label)
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ValueError(f"Duplicate entry id: {entry_id!r}")
        seen_ids.add(entry_id)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Scratchpad manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(payload)
    return payload


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def init_manifest(path: Path, *, force: bool = False) -> dict[str, Any]:
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing manifest: {path}")
    manifest = default_manifest()
    save_manifest(path, manifest)
    return manifest


def find_entry(manifest: dict[str, Any], label: str) -> dict[str, Any]:
    for entry in manifest["entries"]:
        if entry["capture_label"] == label:
            return entry
    raise KeyError(f"Capture label not found: {label}")


def copy_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(entry))


def add_entry(
    manifest: dict[str, Any],
    *,
    capture_label: str,
    capture_type: str,
    scenario: str,
    description: str,
    rung_rows: list[str],
    payload_source_mode: str = "shorthand",
    payload_source_file: str | None = None,
    payload_file: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    _validate_enum("capture_type", capture_type, CAPTURE_TYPES)
    _validate_enum("payload_source_mode", payload_source_mode, PAYLOAD_SOURCE_MODES)
    if not capture_label:
        raise ValueError("capture_label must be non-empty")
    if not scenario:
        raise ValueError("scenario must be non-empty")
    if not rung_rows:
        raise ValueError("At least one --row is required")

    if any(entry["capture_label"] == capture_label for entry in manifest["entries"]):
        raise ValueError(f"capture_label already exists: {capture_label!r}")

    timestamp = now_iso or utc_now_iso()
    canonical_rows = canonicalize_rows(rung_rows)
    entry = {
        "id": str(uuid4()),
        "capture_label": capture_label,
        "capture_type": capture_type,
        "scenario": scenario,
        "description": description,
        "rung_rows": canonical_rows,
        "payload_source_mode": payload_source_mode,
        "payload_source_file": payload_source_file,
        "payload_file": payload_file,
        "verify_clipboard_event": None,
        "verify_status": "unverified",
        "verify_notes": "",
        "verify_expected_rows": canonical_rows,
        "verify_observed_rows": [],
        "verify_result_file": None,
        "verify_clipboard_len": None,
        "promoted_fixture_file": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    validate_entry(entry)
    manifest["entries"].append(entry)
    return copy_entry(entry)


def update_entry(
    manifest: dict[str, Any],
    label: str,
    *,
    now_iso: str | None = None,
    **changes: object,
) -> dict[str, Any]:
    entry = find_entry(manifest, label)
    for key, value in changes.items():
        if (
            key in {"rung_rows", "verify_expected_rows", "verify_observed_rows"}
            and value is not None
        ):
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f"{key} must be list[str]")
            entry[key] = canonicalize_rows(value)
        else:
            entry[key] = value
    entry["updated_at"] = now_iso or utc_now_iso()
    validate_entry(entry)
    return copy_entry(entry)


def list_entries(
    manifest: dict[str, Any],
    *,
    capture_type: str | None = None,
    verify_status: str | None = None,
) -> list[dict[str, Any]]:
    if capture_type is not None:
        _validate_enum("capture_type", capture_type, CAPTURE_TYPES)
    if verify_status is not None:
        _validate_enum("verify_status", verify_status, VERIFY_STATUSES)

    out: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        if capture_type and entry["capture_type"] != capture_type:
            continue
        if verify_status and entry["verify_status"] != verify_status:
            continue
        out.append(copy_entry(entry))
    return out
