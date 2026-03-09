import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clicknick.ladder import capture_registry
from devtools.verify_mismatch_report import build_mismatch_report


def _base_manifest() -> dict:
    manifest = capture_registry.default_manifest()
    capture_registry.add_entry(
        manifest,
        capture_label="synthetic_ok",
        capture_type="synthetic",
        scenario="matrix",
        description="ok case",
        rung_rows=["R,X001,X002,->,:,out(Y001)"],
        now_iso="2026-03-05T12:00:00Z",
    )
    capture_registry.add_entry(
        manifest,
        capture_label="synthetic_mismatch",
        capture_type="synthetic",
        scenario="matrix",
        description="mismatch case",
        rung_rows=["R,X001,X002,->,:,out(Y001)"],
        now_iso="2026-03-05T12:00:00Z",
    )
    capture_registry.add_entry(
        manifest,
        capture_label="native_mismatch",
        capture_type="native",
        scenario="native",
        description="native mismatch",
        rung_rows=["R,X001,->,:,out(Y001)"],
        now_iso="2026-03-05T12:00:00Z",
    )
    capture_registry.update_entry(
        manifest,
        "synthetic_ok",
        verify_clipboard_event="copied",
        verify_status="verified_pass",
        verify_observed_rows=["R,X001,X002,->,:,out(Y001)"],
        now_iso="2026-03-05T12:01:00Z",
    )
    capture_registry.update_entry(
        manifest,
        "synthetic_mismatch",
        verify_clipboard_event="copied",
        verify_status="verified_fail",
        verify_notes="only first contact pasted",
        verify_observed_rows=[
            "R,X001,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,:,NOP"
        ],
        now_iso="2026-03-05T12:01:00Z",
    )
    capture_registry.update_entry(
        manifest,
        "native_mismatch",
        verify_clipboard_event="copied",
        verify_status="verified_fail",
        verify_observed_rows=[
            "R,X001,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,:,NOP"
        ],
        now_iso="2026-03-05T12:01:00Z",
    )
    return manifest


def test_report_filters_to_synthetic_and_lists_copied_row_mismatches() -> None:
    report = build_mismatch_report(_base_manifest(), capture_type="synthetic")

    assert report["entry_count"] == 2
    assert report["copied_count"] == 2
    assert report["copied_mismatch_count"] == 1
    assert report["copied_mismatch_labels"] == ["synthetic_mismatch"]
    mismatch = report["copied_mismatches"][0]
    assert mismatch["verify_status"] == "verified_fail"
    assert mismatch["expected_rows"] != mismatch["observed_rows"]


def test_report_all_types_includes_native_mismatch() -> None:
    report = build_mismatch_report(_base_manifest(), capture_type="all")
    assert report["copied_mismatch_count"] == 2
    assert sorted(report["copied_mismatch_labels"]) == ["native_mismatch", "synthetic_mismatch"]
