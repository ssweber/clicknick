"""Tests for ladder capture registry/workflow backend."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clicknick.ladder import capture_registry
from clicknick.ladder.capture_workflow import (
    CaptureWorkflow,
    CaptureWorkflowPaths,
    default_verify_status_for_event,
)
from clicknick.ladder.csv_shorthand import normalize_shorthand_row


class _FakeClipboard:
    def __init__(self, read_payload: bytes = b"") -> None:
        self.read_payload = read_payload
        self.copied_payloads: list[bytes] = []
        self.read_calls = 0

    def copy(self, payload: bytes) -> None:
        self.copied_payloads.append(payload)

    def read(self) -> bytes:
        self.read_calls += 1
        return self.read_payload


def _make_workflow(tmp_path: Path, fake: _FakeClipboard) -> CaptureWorkflow:
    paths = CaptureWorkflowPaths.for_repo_root(tmp_path)
    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    workflow = CaptureWorkflow(
        paths=paths,
        copy_to_clipboard_fn=fake.copy,
        read_from_clipboard_fn=fake.read,
        now_fn=lambda: fixed_now,
    )
    workflow.manifest_init(force=True)
    return workflow


def test_manifest_schema_validation_required_fields_and_enums() -> None:
    manifest = capture_registry.default_manifest()
    capture_registry.add_entry(
        manifest,
        capture_label="simple_case",
        capture_type="native",
        scenario="smoke",
        description="desc",
        rung_rows=["R,X001,->,:,out(Y001)"],
    )

    missing = deepcopy(manifest)
    del missing["entries"][0]["scenario"]
    with pytest.raises(ValueError, match="missing required fields"):
        capture_registry.validate_manifest(missing)

    invalid_enum = deepcopy(manifest)
    invalid_enum["entries"][0]["capture_type"] = "bad_type"
    with pytest.raises(ValueError, match="capture_type"):
        capture_registry.validate_manifest(invalid_enum)

    unsupported_version = deepcopy(manifest)
    unsupported_version["version"] = 1
    with pytest.raises(ValueError, match="Manifest version must be 2"):
        capture_registry.validate_manifest(unsupported_version)


def test_label_uniqueness_and_row_canonicalization() -> None:
    manifest = capture_registry.default_manifest()
    entry = capture_registry.add_entry(
        manifest,
        capture_label="row_case",
        capture_type="synthetic",
        scenario="smoke",
        description="desc",
        rung_rows=["R,X001,->,:,out(Y001)"],
    )
    canonical_row = entry["rung_rows"][0]
    normalized = normalize_shorthand_row(canonical_row)
    assert normalized.marker == "R"
    assert normalized.conditions[0] == "X001"
    assert normalized.conditions[1] == "-"
    assert normalized.af == "out(Y001)"

    with pytest.raises(ValueError, match="already exists"):
        capture_registry.add_entry(
            manifest,
            capture_label="row_case",
            capture_type="native",
            scenario="smoke",
            description="dup",
            rung_rows=["R,X001,->,:,out(Y001)"],
        )


def test_verify_status_defaults_by_clipboard_event() -> None:
    assert (
        default_verify_status_for_event(
            current_status="unverified",
            clipboard_event="copied",
            pasted=True,
            expected_match=True,
        )
        == "verified_pass"
    )
    assert (
        default_verify_status_for_event(
            current_status="unverified",
            clipboard_event="copied",
            pasted=True,
            expected_match=False,
        )
        == "verified_fail"
    )
    assert (
        default_verify_status_for_event(
            current_status="unverified",
            clipboard_event="copied",
            pasted=False,
        )
        == "blocked"
    )
    assert (
        default_verify_status_for_event(
            current_status="verified_fail",
            clipboard_event="crash",
        )
        == "blocked"
    )
    assert (
        default_verify_status_for_event(
            current_status="verified_fail",
            clipboard_event="cancelled",
        )
        == "verified_fail"
    )


def test_promote_gate_enforcement_and_native_promotion(tmp_path: Path) -> None:
    fake = _FakeClipboard()
    workflow = _make_workflow(tmp_path, fake)

    payload = tmp_path / "scratchpad" / "captures" / "payload.bin"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(b"abc")

    workflow.entry_add(
        capture_type="synthetic",
        label="not_promotable",
        scenario="smoke",
        description="synthetic",
        rows=["R,X001,->,:,out(Y001)"],
        payload_source_mode="file",
        payload_file="scratchpad/captures/payload.bin",
    )

    with pytest.raises(ValueError, match="require verify_status=verified_pass"):
        workflow.promote(label="not_promotable")

    workflow.entry_add(
        capture_type="native",
        label="native_ok",
        scenario="smoke",
        description="native",
        rows=["R,X001,->,:,out(Y001)"],
        payload_source_mode="file",
        payload_file="scratchpad/captures/payload.bin",
    )

    result = workflow.promote(label="native_ok")
    fixture_path = tmp_path / result["fixture_file"]
    assert fixture_path.exists()
    assert fixture_path.read_bytes() == b"abc"


def test_fixture_manifest_upsert_and_codec_generatable_deterministic(tmp_path: Path) -> None:
    fake = _FakeClipboard()
    workflow = _make_workflow(tmp_path, fake)

    repo_fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "ladder_captures"
        / "smoke_simple_native.bin"
    )
    payload_path = tmp_path / "scratchpad" / "captures" / "smoke_simple_native.bin"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(repo_fixture.read_bytes())

    workflow.entry_add(
        capture_type="native",
        label="smoke_simple_native",
        scenario="smoke_native",
        description="baseline_out",
        rows=["R,X001,->,:,out(Y001)"],
        payload_source_mode="file",
        payload_file="scratchpad/captures/smoke_simple_native.bin",
    )

    first = workflow.promote(label="smoke_simple_native")
    second = workflow.promote(label="smoke_simple_native", overwrite=True)

    fixture_manifest_path = tmp_path / "tests" / "fixtures" / "ladder_captures" / "manifest.json"
    manifest = json.loads(fixture_manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert manifest["entries"]
    promoted = manifest["entries"][0]
    assert set(promoted) == {
        "fixture_file",
        "capture_label",
        "scenario",
        "source",
        "description",
        "rung_rows",
        "verified",
        "codec_generatable",
        "metadata_todo",
    }
    assert promoted["capture_label"] == "smoke_simple_native"
    assert promoted["codec_generatable"] is True
    assert (
        first["fixture_entry"]["codec_generatable"] == second["fixture_entry"]["codec_generatable"]
    )
