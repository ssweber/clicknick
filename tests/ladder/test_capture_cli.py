"""CLI tests for unified ladder capture workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from clicknick.ladder.capture_cli import main
from clicknick.ladder.capture_workflow import CaptureWorkflow, CaptureWorkflowPaths
from clicknick.ladder.topology import HEADER_ENTRY_BASE, cell_offset


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
    fixed_now = datetime(2026, 1, 2, 9, 30, 0, tzinfo=UTC)
    workflow = CaptureWorkflow(
        paths=paths,
        copy_to_clipboard_fn=fake.copy,
        read_from_clipboard_fn=fake.read,
        now_fn=lambda: fixed_now,
    )
    workflow.manifest_init(force=True)
    workflow.entry_add(
        capture_type="synthetic",
        label="verify_case",
        scenario="smoke",
        description="verify path test",
        rows=["R,X001,->,:,out(Y001)"],
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
    assert fake.read_calls == 1


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
    assert fake.read_calls == 0


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
        input_fn=_input_iter(["2", "", "", "s", "5"]),
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
