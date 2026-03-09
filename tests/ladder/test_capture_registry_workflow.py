"""Tests for ladder capture registry/workflow backend."""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clicknick.csv.shorthand import normalize_shorthand_row
from clicknick.ladder import capture_registry
from clicknick.ladder.capture_workflow import (
    CaptureWorkflow,
    CaptureWorkflowPaths,
    default_verify_status_for_event,
)


class _FakeClipboard:
    def __init__(self, read_payload: bytes = b"") -> None:
        self.read_payload = read_payload
        self.copied_payloads: list[bytes] = []
        self.copied_owner_hwnds: list[int | None] = []
        self.read_calls = 0

    def copy(self, payload: bytes, owner_hwnd: int | None = None) -> None:
        self.copied_payloads.append(payload)
        self.copied_owner_hwnds.append(owner_hwnd)

    def read(self) -> bytes:
        self.read_calls += 1
        return self.read_payload


def _default_ensure_mdb(db_path: str, addresses: Sequence[str]) -> dict[str, object]:
    return {
        "db_path": db_path,
        "requested_count": len(addresses),
        "inserted_count": 0,
        "existing_count": len(addresses),
        "parsed_addresses": list(addresses),
    }


def _make_workflow(
    tmp_path: Path,
    fake: _FakeClipboard,
    *,
    ensure_mdb_fn=None,
) -> CaptureWorkflow:
    paths = CaptureWorkflowPaths.for_repo_root(tmp_path)
    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    fake_mdb = tmp_path / "SC_.mdb"
    fake_mdb.write_bytes(b"")
    workflow = CaptureWorkflow(
        paths=paths,
        copy_to_clipboard_fn=fake.copy,
        read_from_clipboard_fn=fake.read,
        ensure_mdb_addresses_fn=ensure_mdb_fn or _default_ensure_mdb,
        find_click_hwnd_fn=lambda: 0x1234,
        find_click_database_fn=lambda _pid, _hwnd: str(fake_mdb),
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


def test_comment_rows_are_canonicalized_before_first_rung() -> None:
    manifest = capture_registry.default_manifest()
    entry = capture_registry.add_entry(
        manifest,
        capture_label="comment_case",
        capture_type="synthetic",
        scenario="comment_smoke",
        description="desc",
        rung_rows=['#,"Initialize, then run."', "R,X001,->,:,out(Y001)"],
    )

    assert entry["rung_rows"][0] == '#,"Initialize, then run."'
    comment_row = normalize_shorthand_row(entry["rung_rows"][0])
    rung_row = normalize_shorthand_row(entry["rung_rows"][1])
    assert comment_row.is_comment is True
    assert comment_row.comment_text == "Initialize, then run."
    assert rung_row.marker == "R"


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


def test_verify_prepare_calls_ensure_before_clipboard_copy(tmp_path: Path) -> None:
    fake = _FakeClipboard()
    ensure_calls: list[tuple[str, list[str]]] = []

    def ensure_mdb(db_path: str, addresses: Sequence[str]) -> dict[str, object]:
        assert fake.copied_payloads == []
        ensure_calls.append((db_path, list(addresses)))
        return {
            "db_path": db_path,
            "requested_count": len(addresses),
            "inserted_count": 0,
            "existing_count": len(addresses),
            "parsed_addresses": list(addresses),
        }

    workflow = _make_workflow(tmp_path, fake, ensure_mdb_fn=ensure_mdb)
    payload_path = tmp_path / "scratchpad" / "captures" / "verify_case.bin"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(b"\x00" * 8192)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="verify",
        description="ensure ordering",
        rows=["R,X001,~X002,->,:,out(Y001..Y005)"],
        payload_source_mode="file",
        payload_file="scratchpad/captures/verify_case.bin",
    )

    result = workflow.verify_prepare(label="verify_case")

    assert len(ensure_calls) == 1
    assert len(fake.copied_payloads) == 1
    assert result["mdb_ensure"]["enabled"] is True
    assert result["mdb_ensure"]["parsed_addresses"] == ["X001", "X002", "Y001", "Y005"]


def test_verify_prepare_shorthand_comment_rows_supported_for_plain_empty_rung(
    tmp_path: Path,
) -> None:
    fake = _FakeClipboard()
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="synthetic",
        label="comment_verify_case",
        scenario="verify",
        description="plain comment on empty rung",
        comments=["Hello"],
        rows=["R,...,:,..."],
    )

    result = workflow.verify_prepare(
        label="comment_verify_case",
        ensure_mdb_addresses=False,
    )

    assert result["source_mode"] == "shorthand"
    assert len(fake.copied_payloads) == 1


def test_verify_prepare_skips_ensure_when_disabled(tmp_path: Path) -> None:
    fake = _FakeClipboard()
    ensure_calls = 0

    def ensure_mdb(_db_path: str, _addresses: Sequence[str]) -> dict[str, object]:
        nonlocal ensure_calls
        ensure_calls += 1
        return {}

    workflow = _make_workflow(tmp_path, fake, ensure_mdb_fn=ensure_mdb)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="verify",
        description="skip ensure",
        rows=["R,->,:,NOP"],
    )

    result = workflow.verify_prepare(label="verify_case", ensure_mdb_addresses=False)

    assert ensure_calls == 0
    assert len(fake.copied_payloads) == 1
    assert result["mdb_ensure"]["enabled"] is False


def test_verify_prepare_forwards_owner_hwnd(tmp_path: Path) -> None:
    fake = _FakeClipboard()
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="verify",
        description="owner spoof forwarding",
        rows=["R,->,:,NOP"],
    )

    workflow.verify_prepare(
        label="verify_case",
        owner_hwnd=0x1234,
        ensure_mdb_addresses=False,
    )

    assert len(fake.copied_payloads) == 1
    assert fake.copied_owner_hwnds == [0x1234]


def test_verify_prepare_defaults_native_entries_to_file_after_capture(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x44" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="native_case",
        scenario="verify",
        description="captured native should verify from file by default",
        rows=["R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP"],
    )
    workflow.entry_capture(label="native_case")

    result = workflow.verify_prepare(label="native_case", ensure_mdb_addresses=False)

    assert result["source_mode"] == "file"
    assert fake.copied_payloads[-1] == b"\x44" * 8192


def test_verify_run_interactive_forwards_mdb_path_to_ensure(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x33" * 8192)
    seen_db_paths: list[str] = []

    def ensure_mdb(db_path: str, addresses: Sequence[str]) -> dict[str, object]:
        seen_db_paths.append(db_path)
        return {
            "db_path": db_path,
            "requested_count": len(addresses),
            "inserted_count": 0,
            "existing_count": len(addresses),
            "parsed_addresses": list(addresses),
        }

    workflow = _make_workflow(tmp_path, fake, ensure_mdb_fn=ensure_mdb)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="verify",
        description="forward mdb path",
        rows=["R,->,:,NOP"],
    )
    custom_mdb = tmp_path / "manual.mdb"
    custom_mdb.write_bytes(b"")
    prompts = iter(["q", "", "", ""])

    workflow.verify_run_interactive(
        label="verify_case",
        mdb_path=str(custom_mdb),
        input_fn=lambda _prompt="": next(prompts),
        output_fn=lambda _line="": None,
    )

    assert seen_db_paths == [str(custom_mdb)]


def test_verify_prepare_ensure_failure_is_fail_fast(tmp_path: Path) -> None:
    fake = _FakeClipboard()

    def ensure_fail(_db_path: str, _addresses: Sequence[str]) -> dict[str, object]:
        raise RuntimeError("ensure failed")

    workflow = _make_workflow(tmp_path, fake, ensure_mdb_fn=ensure_fail)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="verify",
        description="fail fast",
        rows=["R,->,:,NOP"],
    )

    with pytest.raises(RuntimeError, match="ensure failed"):
        workflow.verify_prepare(label="verify_case")
    assert fake.copied_payloads == []


def test_entry_delete_dry_run_and_apply(tmp_path: Path) -> None:
    fake = _FakeClipboard()
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="delete_target",
        scenario="delete_scenario",
        description="to be deleted",
        rows=["R,X001,->,:,out(Y001)"],
    )

    dry = workflow.entry_delete(scenario="delete_scenario", yes=False)
    assert dry["dry_run"] is True
    assert dry["matched_count"] == 1
    assert workflow.entry_show(label="delete_target")["capture_label"] == "delete_target"

    applied = workflow.entry_delete(scenario="delete_scenario", yes=True)
    assert applied["dry_run"] is False
    assert applied["deleted_count"] == 1
    with pytest.raises(KeyError):
        workflow.entry_show(label="delete_target")
