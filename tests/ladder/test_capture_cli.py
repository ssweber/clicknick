"""CLI tests for unified ladder capture workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from laddercodec.topology import HEADER_ENTRY_BASE, cell_offset

from clicknick.ladder.capture_cli import main
from clicknick.ladder.capture_workflow import CaptureWorkflow, CaptureWorkflowPaths


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
    fixed_now = datetime(2026, 1, 2, 9, 30, 0, tzinfo=UTC)
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
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="smoke",
        description="verify path test",
        rows=["R,->,:,NOP"],
        payload_source_mode="shorthand",
    )
    return workflow


def _input_iter(values: list[str]):
    iterator = iter(values)
    return lambda _prompt="": next(iterator)


def _profile_payload(
    *,
    cell_05: int,
    cell_11: int,
    cell_1a: int,
    cell_1b: int,
    header_05: int,
    header_11: int,
    header_17: int,
    header_18: int,
    trailer_0a59: int,
) -> bytes:
    data = bytearray(8192)
    cell = cell_offset(0, 4)
    data[cell + 0x05] = cell_05
    data[cell + 0x11] = cell_11
    data[cell + 0x1A] = cell_1a
    data[cell + 0x1B] = cell_1b
    data[HEADER_ENTRY_BASE + 0x05] = header_05
    data[HEADER_ENTRY_BASE + 0x11] = header_11
    data[HEADER_ENTRY_BASE + 0x17] = header_17
    data[HEADER_ENTRY_BASE + 0x18] = header_18
    data[0x0A59] = trailer_0a59
    return bytes(data)


def _header_seed_tuple(payload: bytes) -> tuple[int, int, int, int, int]:
    return (
        payload[HEADER_ENTRY_BASE + 0x05],
        payload[HEADER_ENTRY_BASE + 0x11],
        payload[HEADER_ENTRY_BASE + 0x17],
        payload[HEADER_ENTRY_BASE + 0x18],
        payload[0x0A59],
    )


def test_verify_run_copied_writes_back_bin_and_updates_manifest(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xab" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        ["verify", "run", "--label", "verify_case"],
        workflow=workflow,
        input_fn=_input_iter(["c", "y", "y", "all good", "", ""]),
        output_fn=output.append,
    )

    assert rc == 0
    entry = workflow.entry_show(label="verify_case")
    assert entry["verify_clipboard_event"] == "copied"
    assert entry["verify_status"] == "verified_pass"
    assert entry["verify_clipboard_len"] == 8192
    assert entry["verify_result_file"] is not None
    result_path = tmp_path / entry["verify_result_file"]
    assert result_path.exists()
    assert result_path.read_bytes() == b"\xab" * 8192
    assert fake.read_calls == 2


def test_verify_run_crash_writes_no_back_bin(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xcd" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        ["verify", "run", "--label", "verify_case"],
        workflow=workflow,
        input_fn=_input_iter(["x", "Click crashed", "n", ""]),
        output_fn=output.append,
    )

    assert rc == 0
    entry = workflow.entry_show(label="verify_case")
    assert entry["verify_clipboard_event"] == "crash"
    assert entry["verify_status"] == "blocked"
    assert entry["verify_result_file"] is None
    assert entry["verify_clipboard_len"] is None
    verify_files = list((tmp_path / "scratchpad" / "captures").glob("*_verify_back_*.bin"))
    assert verify_files == []
    assert fake.read_calls == 1


def test_verify_prepare_no_ensure_flag_succeeds(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x11" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        ["verify", "prepare", "--label", "verify_case", "--no-ensure-mdb-addresses"],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) == 1
    entry = workflow.entry_show(label="verify_case")
    assert entry["verify_expected_rows"] == entry["rung_rows"]


def test_verify_prepare_uid_forwarded_to_clipboard(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x11" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "verify_case",
            "--uid",
            "0x1234",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) == 1
    assert fake.copied_owner_hwnds == [0x1234]


def test_entry_add_comment_lines_are_prepended_to_rows(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        [
            "entry",
            "add",
            "--type",
            "synthetic",
            "--label",
            "comment_case",
            "--scenario",
            "comment_smoke",
            "--description",
            "commented rung",
            "--comment",
            "Initialize the light system.",
            "--comment",
            "Activates when Button is pressed.",
            "--row",
            "R,X001,->,:,out(Y001)",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    entry = workflow.entry_show(label="comment_case")
    assert entry["rung_rows"][:2] == [
        "#,Initialize the light system.",
        "#,Activates when Button is pressed.",
    ]
    assert entry["rung_rows"][2].startswith("R,X001,")


def test_verify_prepare_comment_rows_shorthand_supported_for_plain_empty_rung(
    tmp_path: Path,
) -> None:
    fake = _FakeClipboard(read_payload=b"\x11" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="synthetic",
        label="comment_verify_case",
        scenario="verify",
        description="plain comment on empty rung",
        comments=["Hello"],
        rows=["R,...,:,..."],
    )
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "comment_verify_case",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) == 1


def test_verify_prepare_strict_rejects_unsupported_instruction_shorthand(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x11" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="synthetic",
        label="unsupported_verify_case",
        scenario="verify",
        description="unsupported shorthand instruction path",
        rows=["R,X001,->,:,out(Y001)"],
    )
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "unsupported_verify_case",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 1
    assert fake.copied_payloads == []
    assert any("unsupported_condition" in line for line in output)


def test_verify_prepare_seed_source_clipboard_applies_header_seed(tmp_path: Path) -> None:
    fake = _FakeClipboard(
        read_payload=_profile_payload(
            cell_05=0x00,
            cell_11=0x00,
            cell_1a=0x00,
            cell_1b=0x00,
            header_05=0x21,
            header_11=0x42,
            header_17=0x58,
            header_18=0x01,
            trailer_0a59=0x21,
        )
    )
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "verify_case",
            "--seed-source",
            "clipboard",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) == 1
    assert _header_seed_tuple(fake.copied_payloads[0]) == (0x21, 0x42, 0x58, 0x01, 0x21)
    assert any("Seed:" in line for line in output)


def test_verify_prepare_seed_source_clipboard_falls_back_to_scaffold(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x01\x02\x03")
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "verify_case",
            "--seed-source",
            "clipboard",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) == 1
    # Scaffold defaults: +05/+11/+17/+18/t59 = 00/00/05/01/00.
    assert _header_seed_tuple(fake.copied_payloads[0]) == (0x00, 0x00, 0x05, 0x01, 0x00)
    assert any("Warning:" in line for line in output)


def test_verify_prepare_seed_source_entry_uses_seed_entry_payload(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x00" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="seed_entry",
        scenario="seed",
        description="seed source entry",
        rows=["R,X001,->,:,out(Y001)"],
    )
    fake.read_payload = _profile_payload(
        cell_05=0x00,
        cell_11=0x00,
        cell_1a=0x00,
        cell_1b=0x00,
        header_05=0x31,
        header_11=0x62,
        header_17=0x20,
        header_18=0x01,
        trailer_0a59=0x31,
    )
    workflow.entry_capture(label="seed_entry")
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "verify_case",
            "--seed-source",
            "entry",
            "--seed-entry-label",
            "seed_entry",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) >= 1
    assert _header_seed_tuple(fake.copied_payloads[-1]) == (0x31, 0x62, 0x20, 0x01, 0x31)
    assert any("Seed:" in line for line in output)


def test_verify_prepare_seed_source_entry_requires_label(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\x00" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        [
            "verify",
            "prepare",
            "--label",
            "verify_case",
            "--seed-source",
            "entry",
            "--no-ensure-mdb-addresses",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 1
    assert any("seed_source=entry requires --seed-entry-label" in line for line in output)


def test_verify_run_mdb_path_forwarded(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xaa" * 8192)
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
    custom_mdb = tmp_path / "custom_verify.mdb"
    custom_mdb.write_bytes(b"mdb")
    output: list[str] = []

    rc = main(
        ["verify", "run", "--label", "verify_case", "--mdb-path", str(custom_mdb)],
        workflow=workflow,
        input_fn=_input_iter(["c", "y", "y", "", "", ""]),
        output_fn=output.append,
    )

    assert rc == 0
    assert seen_db_paths == [str(custom_mdb)]


def test_verify_run_uid_forwarded_to_clipboard(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xaa" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        ["verify", "run", "--label", "verify_case", "--uid", "4660"],
        workflow=workflow,
        input_fn=_input_iter(["q", "", "", ""]),
        output_fn=output.append,
    )

    assert rc == 0
    assert len(fake.copied_payloads) == 1
    assert fake.copied_owner_hwnds == [4660]


def test_entry_delete_dry_run_then_apply(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="synthetic",
        label="delete_case_a",
        scenario="to_delete",
        description="delete me a",
        rows=["R,X001,->,:,out(Y001)"],
    )
    workflow.entry_add(
        capture_type="synthetic",
        label="delete_case_b",
        scenario="to_delete",
        description="delete me b",
        rows=["R,X001,~X002,->,:,out(Y001)"],
    )
    output: list[str] = []

    rc_dry = main(
        ["entry", "delete", "--scenario", "to_delete"],
        workflow=workflow,
        output_fn=output.append,
    )
    assert rc_dry == 0
    assert any("Dry-run delete" in line for line in output)
    assert workflow.entry_show(label="delete_case_a")["capture_label"] == "delete_case_a"

    output.clear()
    rc_apply = main(
        ["entry", "delete", "--scenario", "to_delete", "--yes"],
        workflow=workflow,
        output_fn=output.append,
    )
    assert rc_apply == 0
    assert any("Deleted entries" in line for line in output)
    with pytest.raises(KeyError):
        workflow.entry_show(label="delete_case_a")
    with pytest.raises(KeyError):
        workflow.entry_show(label="delete_case_b")


def test_entry_add_patch_batch_from_files(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    captures_dir = tmp_path / "scratchpad" / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    payload_a = captures_dir / "two_series_patch_02_imm_no__header_seed.bin"
    payload_b = captures_dir / "two_series_patch_02_imm_no__combined.bin"
    payload_a.write_bytes(b"\x01" * 8192)
    payload_b.write_bytes(b"\x02" * 8192)
    output: list[str] = []

    rc = main(
        [
            "entry",
            "add-patch-batch",
            "--scenario",
            "two_series_hardening_matrix_20260304",
            "--row",
            "R,X001.immediate,X002,->,:,out(Y001)",
            "--file",
            str(payload_a),
            "--file",
            str(payload_b),
            "--label-prefix",
            "patch_",
            "--description-prefix",
            "matrix patch",
            "--json",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    payload = json.loads(output[-1])
    assert payload["ok"] is True
    assert payload["action"] == "entry.add-patch-batch"
    data = payload["data"]
    assert data["created_count"] == 2
    assert data["skipped_count"] == 0
    assert sorted(data["created_labels"]) == [
        "patch_two_series_patch_02_imm_no__combined",
        "patch_two_series_patch_02_imm_no__header_seed",
    ]

    entry = workflow.entry_show(label="patch_two_series_patch_02_imm_no__combined")
    assert entry["capture_type"] == "patch"
    assert entry["payload_source_mode"] == "file"
    assert (
        entry["payload_source_file"]
        == "scratchpad/captures/two_series_patch_02_imm_no__combined.bin"
    )
    assert entry["payload_file"] == "scratchpad/captures/two_series_patch_02_imm_no__combined.bin"


def test_entry_add_patch_batch_skip_existing_with_glob(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    captures_dir = tmp_path / "scratchpad" / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    payload = captures_dir / "two_series_patch_04_imm_imm__combined.bin"
    payload.write_bytes(b"\x03" * 8192)
    output: list[str] = []

    rc_first = main(
        [
            "entry",
            "add-patch-batch",
            "--scenario",
            "two_series_hardening_matrix_20260304",
            "--row",
            "R,X001.immediate,X002.immediate,->,:,out(Y001)",
            "--glob",
            "scratchpad/captures/two_series_patch_04_imm_imm__*.bin",
            "--label-prefix",
            "patch_",
            "--json",
        ],
        workflow=workflow,
        output_fn=output.append,
    )
    assert rc_first == 0

    output.clear()
    rc_second = main(
        [
            "entry",
            "add-patch-batch",
            "--scenario",
            "two_series_hardening_matrix_20260304",
            "--row",
            "R,X001.immediate,X002.immediate,->,:,out(Y001)",
            "--glob",
            "scratchpad/captures/two_series_patch_04_imm_imm__*.bin",
            "--label-prefix",
            "patch_",
            "--skip-existing",
            "--json",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc_second == 0
    payload_json = json.loads(output[-1])
    data = payload_json["data"]
    assert data["created_count"] == 0
    assert data["skipped_count"] == 1
    assert data["skipped_labels"] == ["patch_two_series_patch_04_imm_imm__combined"]


def test_verify_prepare_ensure_failure_returns_error_without_clipboard_write(
    tmp_path: Path,
) -> None:
    fake = _FakeClipboard(read_payload=b"\x11" * 8192)

    def ensure_fail(_db_path: str, _addresses: Sequence[str]) -> dict[str, object]:
        raise RuntimeError("mdb ensure exploded")

    workflow = _make_workflow(tmp_path, fake, ensure_mdb_fn=ensure_fail)
    output: list[str] = []

    rc = main(
        ["verify", "prepare", "--label", "verify_case"],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 1
    assert fake.copied_payloads == []
    assert any("mdb ensure exploded" in line for line in output)


def test_verify_complete_crash_persists_state(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xee" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        [
            "verify",
            "complete",
            "--label",
            "verify_case",
            "--status",
            "blocked",
            "--clipboard-event",
            "crash",
            "--note",
            "manual crash record",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    entry = workflow.entry_show(label="verify_case")
    assert entry["verify_clipboard_event"] == "crash"
    assert entry["verify_status"] == "blocked"
    assert entry["verify_notes"] == "manual crash record"
    assert entry["verify_result_file"] is None
    assert fake.read_calls == 0


def test_json_output_shape_stability(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xaa" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    output: list[str] = []

    rc = main(
        ["entry", "list", "--json"],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    payload = json.loads(output[-1])
    assert set(payload.keys()) == {"ok", "action", "status", "errors", "data"}
    assert payload["ok"] is True
    assert payload["action"] == "entry.list"
    assert payload["status"] == "success"
    assert payload["errors"] == []
    assert isinstance(payload["data"], list)


def test_tui_native_capture_queue_walks_pending_entries_without_label_input(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xbe" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="native_case_1",
        scenario="native_queue",
        description="first pending native case",
        rows=["R,X001,->,:,out(Y001)"],
    )
    workflow.entry_add(
        capture_type="native",
        label="native_case_2",
        scenario="native_queue",
        description="second pending native case",
        rows=["R,X001,~X002,->,:,out(Y001)"],
    )
    output: list[str] = []

    rc = main(
        ["tui"],
        workflow=workflow,
        input_fn=_input_iter(["2", "", "", "s", "6"]),
        output_fn=output.append,
    )

    assert rc == 0
    first = workflow.entry_show(label="native_case_1")
    second = workflow.entry_show(label="native_case_2")
    assert first["payload_file"] == "scratchpad/captures/native_case_1.bin"
    assert second["payload_file"] is None
    assert (tmp_path / first["payload_file"]).read_bytes() == b"\xbe" * 8192
    assert fake.read_calls == 1
    assert any("Pending native captures: 2" in line for line in output)


def test_tui_verify_guided_queue_walks_unverified_entries_without_label_input(
    tmp_path: Path,
) -> None:
    fake = _FakeClipboard(read_payload=b"\xad" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case_2",
        scenario="guided_verify",
        description="second guided verify case",
        rows=["R,->,:,NOP"],
        payload_source_mode="shorthand",
    )
    output: list[str] = []

    rc = main(
        ["tui"],
        workflow=workflow,
        input_fn=_input_iter(
            [
                "3",  # verify
                "g",  # guided queue mode
                "",  # source override (default)
                "",  # scenario filter (all)
                "",  # first item action: verify
                "c",  # copied
                "y",  # pasted
                "y",  # expected match
                "",  # note
                "",  # keep expected rows
                "",  # keep default status
                "q",  # second item action: stop queue
                "6",  # exit
            ]
        ),
        output_fn=output.append,
    )

    assert rc == 0
    first = workflow.entry_show(label="verify_case")
    second = workflow.entry_show(label="verify_case_2")
    assert first["verify_status"] == "verified_pass"
    assert first["verify_clipboard_event"] == "copied"
    assert first["verify_result_file"] is not None
    assert second["verify_status"] == "unverified"
    assert any("Pending verify entries: 2" in line for line in output)
    assert any("Verify queue stopped." in line for line in output)
    assert fake.read_calls == 2


def test_tui_verify_label_mode_can_force_file_source(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xad" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_capture(label="verify_case")
    output: list[str] = []

    rc = main(
        ["tui"],
        workflow=workflow,
        input_fn=_input_iter(
            [
                "3",  # verify
                "",  # label mode (default)
                "f",  # source override = file
                "verify_case",  # label
                "c",  # copied
                "y",  # pasted
                "y",  # expected match
                "",  # note
                "",  # keep expected rows
                "",  # keep default status
                "6",  # exit
            ]
        ),
        output_fn=output.append,
    )

    assert rc == 0
    entry = workflow.entry_show(label="verify_case")
    assert entry["verify_status"] == "verified_pass"
    assert entry["verify_clipboard_event"] == "copied"
    assert any("Payload source: file" in line for line in output)


def test_tui_verify_label_mode_defaults_captured_native_to_file(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"\xad" * 8192)
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="native_case",
        scenario="native_verify",
        description="captured native defaults to file source",
        rows=["R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP"],
    )
    workflow.entry_capture(label="native_case")
    output: list[str] = []

    rc = main(
        ["tui"],
        workflow=workflow,
        input_fn=_input_iter(
            [
                "3",  # verify
                "",  # label mode (default)
                "",  # source override = default
                "native_case",  # label
                "q",  # cancel verification after prepare
                "",  # note
                "",  # keep status as-is instead of blocked
                "",  # keep current status
                "6",  # exit
            ]
        ),
        output_fn=output.append,
    )

    assert rc == 0
    assert any("Payload source: file" in line for line in output)


def test_report_profile_single_label_json(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    fake.read_payload = _profile_payload(
        cell_05=0x04,
        cell_11=0x0C,
        cell_1a=0xFF,
        cell_1b=0xFF,
        header_05=0x0D,
        header_11=0x0B,
        header_17=0x15,
        header_18=0x01,
        trailer_0a59=0x04,
    )
    workflow.entry_capture(label="verify_case")
    output: list[str] = []

    rc = main(
        ["report", "profile", "--label", "verify_case", "--json"],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    payload = json.loads(output[-1])
    assert payload["ok"] is True
    assert payload["action"] == "report.profile"
    rows = payload["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["capture_label"] == "verify_case"
    assert row["cell_05"] == "0x04"
    assert row["cell_11"] == "0x0C"
    assert row["cell_1a"] == "0xFF"
    assert row["cell_1b"] == "0xFF"
    assert row["header_05"] == "0x0D"
    assert row["header_11"] == "0x0B"
    assert row["header_17"] == "0x15"
    assert row["header_18"] == "0x01"
    assert row["trailer_0a59"] == "0x04"


def test_report_profile_all_csv(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="native_case",
        scenario="report",
        description="extra payload for report",
        rows=["R,X001,->,:,out(Y001)"],
    )

    fake.read_payload = _profile_payload(
        cell_05=0x04,
        cell_11=0x0C,
        cell_1a=0xFF,
        cell_1b=0xFF,
        header_05=0x0D,
        header_11=0x0B,
        header_17=0x15,
        header_18=0x01,
        trailer_0a59=0x04,
    )
    workflow.entry_capture(label="verify_case")

    fake.read_payload = _profile_payload(
        cell_05=0x00,
        cell_11=0x00,
        cell_1a=0xFF,
        cell_1b=0x01,
        header_05=0x05,
        header_11=0x00,
        header_17=0x4E,
        header_18=0x01,
        trailer_0a59=0x00,
    )
    workflow.entry_capture(label="native_case")

    output: list[str] = []
    rc = main(
        ["report", "profile", "--all", "--csv"],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    csv_text = output[-1]
    lines = csv_text.splitlines()
    assert lines[0].startswith("capture_label,capture_type,scenario,payload_file,record_len")
    assert any(line.startswith("native_case,") for line in lines[1:])
    assert any(line.startswith("verify_case,") for line in lines[1:])


def test_report_profile_columns_single_label_json(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    payload = bytearray(
        _profile_payload(
            cell_05=0x04,
            cell_11=0x0C,
            cell_1a=0xFF,
            cell_1b=0xFF,
            header_05=0x0D,
            header_11=0x0B,
            header_17=0x15,
            header_18=0x01,
            trailer_0a59=0x04,
        )
    )
    row0_col0 = cell_offset(0, 0)
    payload[row0_col0 + 0x05] = 0xAA
    payload[row0_col0 + 0x11] = 0xBB
    fake.read_payload = bytes(payload)
    workflow.entry_capture(label="verify_case")
    output: list[str] = []

    rc = main(
        [
            "report",
            "profile-columns",
            "--label",
            "verify_case",
            "--rows",
            "0",
            "--cols",
            "0,4",
            "--offsets",
            "0x05,0x11",
            "--json",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    payload_json = json.loads(output[-1])
    assert payload_json["ok"] is True
    assert payload_json["action"] == "report.profile-columns"
    rows = payload_json["data"]
    assert len(rows) == 2
    assert rows[0]["row"] == 0
    assert rows[0]["column"] == 0
    assert rows[0]["cell_05"] == "0xAA"
    assert rows[0]["cell_11"] == "0xBB"
    assert rows[1]["row"] == 0
    assert rows[1]["column"] == 4
    assert rows[1]["cell_05"] == "0x04"
    assert rows[1]["cell_11"] == "0x0C"


def test_report_profile_columns_all_csv(tmp_path: Path) -> None:
    fake = _FakeClipboard(read_payload=b"")
    workflow = _make_workflow(tmp_path, fake)
    workflow.entry_add(
        capture_type="native",
        label="native_case",
        scenario="report",
        description="extra payload for profile-columns report",
        rows=["R,X001,->,:,out(Y001)"],
    )

    fake.read_payload = _profile_payload(
        cell_05=0x04,
        cell_11=0x0C,
        cell_1a=0xFF,
        cell_1b=0xFF,
        header_05=0x0D,
        header_11=0x0B,
        header_17=0x15,
        header_18=0x01,
        trailer_0a59=0x04,
    )
    workflow.entry_capture(label="verify_case")

    fake.read_payload = _profile_payload(
        cell_05=0x09,
        cell_11=0x10,
        cell_1a=0x00,
        cell_1b=0x01,
        header_05=0x11,
        header_11=0x22,
        header_17=0x4E,
        header_18=0x01,
        trailer_0a59=0x11,
    )
    workflow.entry_capture(label="native_case")

    output: list[str] = []
    rc = main(
        [
            "report",
            "profile-columns",
            "--all",
            "--rows",
            "0",
            "--cols",
            "4",
            "--offsets",
            "0x05,0x11",
            "--csv",
        ],
        workflow=workflow,
        output_fn=output.append,
    )

    assert rc == 0
    csv_text = output[-1]
    lines = csv_text.splitlines()
    assert (
        lines[0]
        == "capture_label,capture_type,scenario,payload_file,record_len,row,column,cell_05,cell_11"
    )
    assert any(line.startswith("native_case,") and ",0,4,0x09,0x10" in line for line in lines[1:])
    assert any(line.startswith("verify_case,") and ",0,4,0x04,0x0C" in line for line in lines[1:])
