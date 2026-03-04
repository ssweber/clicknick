"""Direct CLI frontend for ladder capture workflow."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from typing import Any

from .capture_workflow import CaptureWorkflow, run_tui


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")


def _parse_index_spec(spec: str, *, minimum: int, maximum: int) -> list[int]:
    selected: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            left_raw, right_raw = part.split("-", 1)
            left = int(left_raw, 0)
            right = int(right_raw, 0)
            lo, hi = sorted((left, right))
            for idx in range(lo, hi + 1):
                if minimum <= idx <= maximum:
                    selected.add(idx)
            continue
        idx = int(part, 0)
        if minimum <= idx <= maximum:
            selected.add(idx)
    return sorted(selected)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clicknick-ladder-capture",
        description="Unified ladder capture workflow (manifest, capture, verify, promote, report).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser("manifest", help="Manifest operations")
    manifest_sub = p_manifest.add_subparsers(dest="manifest_cmd", required=True)
    p_manifest_init = manifest_sub.add_parser("init", help="Create scratchpad manifest")
    p_manifest_init.add_argument("--force", action="store_true", help="Overwrite existing manifest")

    p_entry = sub.add_parser("entry", help="Entry CRUD and capture")
    entry_sub = p_entry.add_subparsers(dest="entry_cmd", required=True)

    p_entry_add = entry_sub.add_parser("add", help="Add a capture entry")
    p_entry_add.add_argument(
        "--type", required=True, choices=["native", "synthetic", "patch", "pasteback"]
    )
    p_entry_add.add_argument("--label", required=True)
    p_entry_add.add_argument("--scenario", required=True)
    p_entry_add.add_argument("--description", required=True)
    p_entry_add.add_argument("--row", action="append", required=True)
    p_entry_add.add_argument("--payload-source", choices=["shorthand", "file"], default="shorthand")
    p_entry_add.add_argument("--payload-file")
    _add_json_flag(p_entry_add)

    p_entry_list = entry_sub.add_parser("list", help="List capture entries")
    p_entry_list.add_argument("--type", choices=["native", "synthetic", "patch", "pasteback"])
    p_entry_list.add_argument(
        "--status", choices=["unverified", "verified_pass", "verified_fail", "blocked"]
    )
    _add_json_flag(p_entry_list)

    p_entry_show = entry_sub.add_parser("show", help="Show one capture entry")
    p_entry_show.add_argument("--label", required=True)
    _add_json_flag(p_entry_show)

    p_entry_capture = entry_sub.add_parser(
        "capture", help="Capture current clipboard bytes for an entry"
    )
    p_entry_capture.add_argument("--label", required=True)
    p_entry_capture.add_argument("--output-file")
    _add_json_flag(p_entry_capture)

    p_verify = sub.add_parser("verify", help="Verification operations")
    verify_sub = p_verify.add_subparsers(dest="verify_cmd", required=True)

    p_verify_prepare = verify_sub.add_parser("prepare", help="Load entry payload to clipboard")
    p_verify_prepare.add_argument("--label", required=True)
    p_verify_prepare.add_argument("--source", choices=["shorthand", "file"])
    p_verify_prepare.add_argument("--mdb-path")
    p_verify_prepare.add_argument(
        "--no-ensure-mdb-addresses",
        action="store_true",
        help="Skip auto-inserting parsed rung operands into SC_.mdb before clipboard load",
    )
    _add_json_flag(p_verify_prepare)

    p_verify_complete = verify_sub.add_parser("complete", help="Persist verify result state")
    p_verify_complete.add_argument("--label", required=True)
    p_verify_complete.add_argument(
        "--status",
        required=True,
        choices=["unverified", "verified_pass", "verified_fail", "blocked"],
    )
    p_verify_complete.add_argument(
        "--clipboard-event",
        required=True,
        choices=["copied", "crash", "cancelled"],
    )
    p_verify_complete.add_argument("--note", default="")
    p_verify_complete.add_argument("--row", action="append")
    p_verify_complete.add_argument("--result-file")
    _add_json_flag(p_verify_complete)

    p_verify_run = verify_sub.add_parser("run", help="Interactive verify workflow")
    p_verify_run.add_argument("--label", required=True)
    p_verify_run.add_argument("--source", choices=["shorthand", "file"])
    p_verify_run.add_argument("--mdb-path")
    p_verify_run.add_argument(
        "--no-ensure-mdb-addresses",
        action="store_true",
        help="Skip auto-inserting parsed rung operands into SC_.mdb before clipboard load",
    )
    p_verify_run.add_argument(
        "--status-default",
        choices=["unverified", "verified_pass", "verified_fail", "blocked"],
    )
    _add_json_flag(p_verify_run)

    p_report = sub.add_parser("report", help="Read-only reporting helpers")
    report_sub = p_report.add_subparsers(dest="report_cmd", required=True)

    p_report_profile = report_sub.add_parser(
        "profile",
        help="Extract profile/header bytes for one label or all captured entries",
    )
    target_group = p_report_profile.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--label", help="Capture label to inspect")
    target_group.add_argument("--all", action="store_true", help="Inspect all entries with payloads")
    format_group = p_report_profile.add_mutually_exclusive_group()
    format_group.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    format_group.add_argument("--csv", action="store_true", help="Emit CSV output")

    p_report_profile_columns = report_sub.add_parser(
        "profile-columns",
        help="Extract selected per-cell profile bytes across rows/columns",
    )
    target_group = p_report_profile_columns.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--label", help="Capture label to inspect")
    target_group.add_argument("--all", action="store_true", help="Inspect all entries with payloads")
    p_report_profile_columns.add_argument(
        "--rows",
        default="0,1",
        help="Row indices/ranges (default: 0,1). Example: 0-1",
    )
    p_report_profile_columns.add_argument(
        "--cols",
        default="0-31",
        help="Column indices/ranges (default: 0-31). Example: 4-31",
    )
    p_report_profile_columns.add_argument(
        "--offsets",
        default="0x05,0x11,0x1A,0x1B",
        help="Cell byte offsets (0x00-0x3F). Example: 0x05,0x11,0x1A,0x1B",
    )
    format_group = p_report_profile_columns.add_mutually_exclusive_group()
    format_group.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    format_group.add_argument("--csv", action="store_true", help="Emit CSV output")

    p_promote = sub.add_parser(
        "promote", help="Promote entry payload to fixture + fixture manifest v2"
    )
    p_promote.add_argument("--label", required=True)
    p_promote.add_argument("--fixture-file")
    p_promote.add_argument("--overwrite", action="store_true")
    _add_json_flag(p_promote)

    sub.add_parser("tui", help="Launch terminal wizard TUI")
    return parser


def _json_envelope(
    *,
    ok: bool,
    action: str,
    status: str,
    errors: list[str] | None = None,
    data: object | None = None,
) -> dict[str, object]:
    return {
        "ok": ok,
        "action": action,
        "status": status,
        "errors": errors or [],
        "data": data,
    }


def _print_human(action: str, data: Any, output_fn: Callable[[str], None]) -> None:
    if action == "entry.list":
        entries = data
        if not entries:
            output_fn("No entries.")
            return
        for entry in entries:
            output_fn(
                f"{entry['capture_label']}: type={entry['capture_type']} status={entry['verify_status']}"
            )
        return
    if action == "report.profile":
        if isinstance(data, str):
            output_fn(data.rstrip("\n"))
            return
        rows = data
        if not rows:
            output_fn("No rows.")
            return
        for row in rows:
            output_fn(
                f"{row['capture_label']}: cell_05={row['cell_05']} cell_11={row['cell_11']} "
                f"header_17={row['header_17']} header_18={row['header_18']} "
                f"trailer_0a59={row['trailer_0a59']}"
            )
        return
    if action == "report.profile-columns":
        if isinstance(data, str):
            output_fn(data.rstrip("\n"))
            return
        rows = data
        if not rows:
            output_fn("No rows.")
            return
        sample = rows[0]
        cell_fields = sorted(key for key in sample.keys() if key.startswith("cell_"))
        for row in rows:
            rendered = " ".join(f"{key}={row[key]}" for key in cell_fields)
            output_fn(
                f"{row['capture_label']} r{row['row']} c{row['column']}: {rendered}"
            )
        return
    output_fn(json.dumps(data, indent=2))


def _action_name(args: argparse.Namespace) -> str:
    if args.command == "manifest" and args.manifest_cmd == "init":
        return "manifest.init"
    if args.command == "entry":
        return f"entry.{args.entry_cmd}"
    if args.command == "verify":
        return f"verify.{args.verify_cmd}"
    if args.command == "report":
        return f"report.{args.report_cmd}"
    if args.command == "promote":
        return "promote"
    if args.command == "tui":
        return "tui"
    return "unknown"


def _dispatch(
    args: argparse.Namespace,
    *,
    workflow: CaptureWorkflow,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> Any:
    if args.command == "manifest" and args.manifest_cmd == "init":
        return workflow.manifest_init(force=args.force)

    if args.command == "entry" and args.entry_cmd == "add":
        return workflow.entry_add(
            capture_type=args.type,
            label=args.label,
            scenario=args.scenario,
            description=args.description,
            rows=args.row,
            payload_source_mode=args.payload_source,
            payload_file=args.payload_file,
        )
    if args.command == "entry" and args.entry_cmd == "list":
        return workflow.entry_list(capture_type=args.type, status=args.status)
    if args.command == "entry" and args.entry_cmd == "show":
        return workflow.entry_show(label=args.label)
    if args.command == "entry" and args.entry_cmd == "capture":
        return workflow.entry_capture(label=args.label, output_file=args.output_file)

    if args.command == "verify" and args.verify_cmd == "prepare":
        return workflow.verify_prepare(
            label=args.label,
            source=args.source,
            ensure_mdb_addresses=(not args.no_ensure_mdb_addresses),
            mdb_path=args.mdb_path,
        )
    if args.command == "verify" and args.verify_cmd == "complete":
        return workflow.verify_complete(
            label=args.label,
            status=args.status,
            clipboard_event=args.clipboard_event,
            note=args.note,
            rows=args.row,
            result_file=args.result_file,
        )
    if args.command == "verify" and args.verify_cmd == "run":
        return workflow.verify_run_interactive(
            label=args.label,
            source=args.source,
            ensure_mdb_addresses=(not args.no_ensure_mdb_addresses),
            mdb_path=args.mdb_path,
            status_default=args.status_default,
            input_fn=input_fn,
            output_fn=output_fn,
        )

    if args.command == "report" and args.report_cmd == "profile":
        rows = workflow.report_profile(label=args.label, all_entries=args.all)
        if args.csv:
            return workflow.report_profile_csv(rows)
        return rows
    if args.command == "report" and args.report_cmd == "profile-columns":
        rows = _parse_index_spec(args.rows, minimum=0, maximum=31)
        cols = _parse_index_spec(args.cols, minimum=0, maximum=31)
        offsets = _parse_index_spec(args.offsets, minimum=0, maximum=0x3F)
        if not rows:
            raise ValueError("No valid rows selected")
        if not cols:
            raise ValueError("No valid columns selected")
        if not offsets:
            raise ValueError("No valid offsets selected")
        table = workflow.report_profile_columns(
            label=args.label,
            all_entries=args.all,
            rows=rows,
            cols=cols,
            offsets=offsets,
        )
        if args.csv:
            return workflow.report_profile_columns_csv(table, offsets=offsets)
        return table

    if args.command == "promote":
        return workflow.promote(
            label=args.label,
            fixture_file=args.fixture_file,
            overwrite=args.overwrite,
        )

    if args.command == "tui":
        run_tui(workflow, input_fn=input_fn, output_fn=output_fn)
        return {"ok": True}

    raise ValueError("Unhandled command")


def main(
    argv: Sequence[str] | None = None,
    *,
    workflow: CaptureWorkflow | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    action = _action_name(args)
    as_json = bool(getattr(args, "json", False))

    engine = workflow or CaptureWorkflow()
    try:
        data = _dispatch(args, workflow=engine, input_fn=input_fn, output_fn=output_fn)
    except Exception as exc:
        if as_json:
            output_fn(
                json.dumps(
                    _json_envelope(
                        ok=False,
                        action=action,
                        status="error",
                        errors=[str(exc)],
                        data=None,
                    ),
                    indent=2,
                )
            )
        else:
            output_fn(f"Error ({action}): {exc}")
        return 1

    if as_json:
        output_fn(
            json.dumps(
                _json_envelope(
                    ok=True,
                    action=action,
                    status="success",
                    errors=[],
                    data=data,
                ),
                indent=2,
            )
        )
    elif action != "tui":
        _print_human(action, data, output_fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
