"""Validation for checked-in hermetic ladder capture fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clicknick.ladder.csv_shorthand import normalize_shorthand_row

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"
TODO_LABELS = {
    "nc_a_immediate_only",
    "no_a_immediate_only",
    "no_c_immediate_only",
    "pasteback_vert_b_with_horiz",
}


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_exists_and_matches_fixture_files() -> None:
    assert MANIFEST_PATH.exists()

    manifest = _load_manifest()
    assert manifest["version"] == 2
    entries = manifest["entries"]
    manifest_files = {entry["fixture_file"] for entry in entries}
    fixture_files = {p.name for p in FIXTURES_DIR.glob("*.bin")}

    assert manifest_files == fixture_files


def test_manifest_entries_have_capture_mapping_and_schema_fields() -> None:
    manifest = _load_manifest()
    for entry in manifest["entries"]:
        assert entry["fixture_file"].endswith(".bin")
        assert entry["capture_label"]
        assert entry["scenario"]
        assert entry["source"] == "scratchpad/captures"
        assert isinstance(entry["description"], str)
        assert isinstance(entry["rung_rows"], list)
        assert isinstance(entry["verified"], bool)
        assert isinstance(entry["codec_generatable"], bool)
        assert isinstance(entry["metadata_todo"], bool)


def test_manifest_metadata_todo_contract() -> None:
    manifest = _load_manifest()
    todo_labels = {
        entry["capture_label"] for entry in manifest["entries"] if entry["metadata_todo"] is True
    }
    assert todo_labels == TODO_LABELS

    for entry in manifest["entries"]:
        if entry["capture_label"] in TODO_LABELS:
            assert entry["description"] == ""
            assert entry["rung_rows"] == []
            continue
        assert entry["description"]
        assert entry["rung_rows"]


def test_manifest_rung_rows_parse_and_marker_contract() -> None:
    manifest = _load_manifest()
    for entry in manifest["entries"]:
        if entry["metadata_todo"]:
            continue

        rows = entry["rung_rows"]
        for row_index, row in enumerate(rows):
            canonical = normalize_shorthand_row(row)
            assert canonical.marker == ("R" if row_index == 0 else "")
            assert "+" not in canonical.conditions
            assert "t" not in canonical.conditions
            assert "r" not in canonical.conditions


def test_manifest_regression_examples_for_column_placement() -> None:
    manifest = _load_manifest()
    entries_by_label = {entry["capture_label"]: entry for entry in manifest["entries"]}

    assert entries_by_label["no_c_only"]["rung_rows"] == ["R,,,X001,...,:,..."]
    assert entries_by_label["vert_b_3rows"]["rung_rows"] == [
        "R,,|,...,:,...",
        ",,|,...,:,...",
        ",,|,...,:,...",
    ]
