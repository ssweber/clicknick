"""Validation for checked-in hermetic ladder capture fixtures."""

from __future__ import annotations

import json
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


def test_manifest_exists_and_matches_fixture_files() -> None:
    assert MANIFEST_PATH.exists()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    manifest_files = {entry["fixture_file"] for entry in entries}
    fixture_files = {p.name for p in FIXTURES_DIR.glob("*.bin")}

    assert manifest_files == fixture_files


def test_manifest_entries_have_capture_mapping() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        assert entry["fixture_file"].endswith(".bin")
        assert entry["capture_label"]
        assert entry["scenario"]
        assert entry["source"] == "scratchpad/captures"

