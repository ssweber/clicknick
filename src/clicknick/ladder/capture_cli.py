"""Direct CLI frontend for ladder capture workflow."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from typing import Any

from .capture_workflow import CaptureWorkflow, run_tui


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clicknick-ladder-capture",
        description="Unified ladder capture workflow (manifest, capture, verify, promote).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_manifest = sub.add_parser("manifest", help="Manifest operations")
    manifest_sub = p_manifest.add_subparsers(dest="manifest_cmd", required=True)
    p_manifest_init = manifest_sub.add_parser("init", help="Create scratchpad manifest")
    p_manifest_init.add_argument("--force", action="store_true", help="Overwrite existing manifest")

    p_entry = sub.add_parser("entry", help="Entry CRUD and capture")
    entry_sub = p_entry.add_subparsers(dest="entry_cmd", required=True)

    p_entry_add = entry_sub.add_parser("add", help="Add a capture entry")
    p_entry_add.add_argument("--type", required=True, choices=["native", "synthetic", "patch", "pasteback"])
    p_entry_add.add_argument("--label", required=True)
    p_entry_add.add_argument("--scenario", required=True)
    p_entry_add.add_argument("--description", required=True)
    p_entry_add.add_argument("--row", action="append", required=True)
    p_entry_add.add_argument("--payload-source", choices=["shorthand", "file"], default="shorthand")
    p_entry_add.add_argument("--payload-file")
    _add_json_flag(p_entry_add)

    p_entry_list = entry_sub.add_parser("list", help="List capture entries")
    p_entry_list.add_argument("--type", choices=["native", "synthetic", "patch", "pasteback"])
    p_entry_list.add_argument("--status", choices=["unverified", "verified_pass", "verified_fail", "blocked"])
    _add_json_flag(p_entry_list)

    p_entry_show = entry_sub.add_parser("show", help="Show one capture entry")
    p_entry_show.add_argument("--label", required=True)
    _add_json_flag(p_entry_show)

    p_entry_capture = entry_sub.add_parser("capture", help="Capture current clipboard bytes for an entry")
    p_entry_capture.add_argument("--label", required=True)
    p_entry_capture.add_argument("--output-file")
    _add_json_flag(p_entry_capture)

    p_verify = sub.add_parser("verify", help="Verification operations")
    verify_sub = p_verify.add_subparsers(dest="verify_cmd", required=True)

    p_verify_prepare = verify_sub.add_parser("prepare", help="Load entry payload to clipboard")
    p_verify_prepare.add_argument("--label", required=True)
    p_verify_prepare.add_argument("--source", choices=["shorthand", "file"])
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
    p_verify_run.add_argument(
        "--status-default",
        choices=["unverified", "verified_pass", "verified_fail", "blocked"],
    )
    _add_json_flag(p_verify_run)

    p_promote = sub.add_parser("promote", help="Promote entry payload to fixture + fixture manifest v2")
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
    output_fn(json.dumps(data, indent=2))


def _action_name(args: argparse.Namespace) -> str:
    if args.command == "manifest" and args.manifest_cmd == "init":
        return "manifest.init"
    if args.command == "entry":
        return f"entry.{args.entry_cmd}"
    if args.command == "verify":
        return f"verify.{args.verify_cmd}"
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
        return workflow.verify_prepare(label=args.label, source=args.source)
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
            status_default=args.status_default,
            input_fn=input_fn,
            output_fn=output_fn,
        )

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
