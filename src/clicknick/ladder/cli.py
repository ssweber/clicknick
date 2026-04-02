"""Clipboard bridge for CLICK PLC ladder rungs.

Thin CLI wrapper around service functions in ``program.py``.

Usage:
    clicknick-rung guided FOLDER                # Interactive batch verify
    clicknick-rung guided FOLDER --list         # List CSVs with descriptions
    clicknick-rung guided FOLDER --restart      # Clear progress, start fresh
    clicknick-rung program load FOLDER          # Load a program bundle (guided paste)
    clicknick-rung program save FOLDER          # Decode Scr*.tmp → main.csv + subroutines/
    clicknick-rung load FILE                    # Encode .csv/.bin → clipboard
    clicknick-rung save FILE                    # Clipboard → .bin/.csv/both
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from laddercodec.csv.writer import WriterError

from ..utils.mdb_shared import find_click_database
from .clipboard import copy_to_clipboard, find_click_hwnd, read_from_clipboard
from .program import (
    decode_to_csv,
    describe_csv,
    list_program_bundle,
    prepare_csv_load,
    program_save,
)

# ---------------------------------------------------------------------------
# MDB path resolution (CLI convenience — auto-detect from running Click)
# ---------------------------------------------------------------------------


def resolve_mdb_path(mdb_path: str | None = None) -> Path:
    """Find SC_.mdb from explicit path or auto-detect from running Click."""
    if mdb_path:
        resolved = Path(mdb_path)
        if not resolved.exists():
            raise FileNotFoundError(f"MDB path not found: {resolved}")
        return resolved

    click_hwnd = find_click_hwnd()
    db_path = find_click_database(None, click_hwnd)
    if not db_path:
        raise FileNotFoundError("Could not locate SC_.mdb. Pass --mdb-path <path-to-SC_.mdb>.")
    resolved = Path(db_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Auto-detected SC_.mdb not found: {resolved}")
    return resolved


# ---------------------------------------------------------------------------
# CSV description (CLI-only presentation)
# ---------------------------------------------------------------------------


def print_csv_shape(csv_path: Path) -> None:
    """Print the CSV data rows (skip header) as-is."""
    import csv as csv_mod

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        next(reader)  # skip header
        for row in reader:
            print(f"    {','.join(row)}")


# ---------------------------------------------------------------------------
# Loaders (encode → provision MDB → clipboard, with CLI output)
# ---------------------------------------------------------------------------


def _load_csv(csv_path: Path, mdb_path: str | None, *, best_effort: bool = False) -> bytes:
    """Describe, encode, provision MDB addresses, copy to clipboard. Return payload."""
    print(f"  {describe_csv(csv_path, best_effort=best_effort)}")
    print_csv_shape(csv_path)

    try:
        resolved_mdb = resolve_mdb_path(mdb_path)
    except (FileNotFoundError, RuntimeError):
        resolved_mdb = None

    result = prepare_csv_load(csv_path, mdb_path=resolved_mdb, best_effort=best_effort)

    if result.addresses_inserted:
        print(
            f"  MDB: inserted {result.addresses_inserted} address(es) into {result.mdb_path.name}"
        )
    elif result.mdb_error:
        print(f"  MDB: skipped ({result.mdb_error})")

    copy_to_clipboard(result.payload)
    print(f"  Copied to clipboard ({len(result.payload):,} bytes)")
    return result.payload


def _load_program_csv(csv_path: Path, mdb_path: str | None) -> bytes:
    """Encode a program/subroutine CSV and copy to clipboard. Minimal output."""
    try:
        resolved_mdb = resolve_mdb_path(mdb_path)
    except (FileNotFoundError, RuntimeError):
        resolved_mdb = None

    result = prepare_csv_load(csv_path, mdb_path=resolved_mdb)

    print(f"  {result.rung_count} rung{'s' if result.rung_count != 1 else ''}")
    if result.addresses_inserted:
        print(
            f"  MDB: inserted {result.addresses_inserted} address(es) into {result.mdb_path.name}"
        )
    elif result.mdb_error:
        print(f"  MDB: skipped ({result.mdb_error})")

    copy_to_clipboard(result.payload)
    print(f"  Copied to clipboard ({len(result.payload):,} bytes)")
    return result.payload


# ---------------------------------------------------------------------------
# Clipboard save + compare (verification)
# ---------------------------------------------------------------------------


def _save_and_compare(name: str, bin_path: Path) -> None:
    """Read clipboard, save as .bin, and report byte diff if .bin already exists."""
    actual = read_from_clipboard()

    if not bin_path.exists():
        bin_path.write_bytes(actual)
        print(f"  Saved {bin_path.name} ({len(actual):,} bytes)")
        return

    expected = bin_path.read_bytes()
    if actual == expected:
        print(f"  {name}: exact match ({len(actual):,} bytes)")
    elif len(actual) == len(expected):
        diffs = [i for i in range(len(actual)) if actual[i] != expected[i]]
        print(f"  {name}: {len(diffs)} byte(s) differ from encoder, first at 0x{diffs[0]:04X}")
    else:
        print(f"  {name}: size differs (encoder {len(expected):,}, Click {len(actual):,} bytes)")


# ---------------------------------------------------------------------------
# Progress log
# ---------------------------------------------------------------------------


def _read_progress(log_path: Path) -> dict[str, str]:
    """Read progress log, return {name: status_line}."""
    done: dict[str, str] = {}
    if not log_path.exists():
        return done
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ": " in line:
            name = line.split(": ", 1)[0]
            done[name] = line
    return done


def _append_result(log_path: Path, name: str, status: str, detail: str = "") -> None:
    """Append one result line to the progress log."""
    extra = f" ({detail})" if detail else ""
    line = f"{name}: {status}{extra}\n"
    with open(log_path, "a+", encoding="utf-8") as f:
        f.seek(0, 2)  # seek to end
        if f.tell() > 0:
            f.seek(f.tell() - 1)
            if f.read(1) != "\n":
                f.write("\n")
        f.write(line)


# ---------------------------------------------------------------------------
# Interactive batch verification
# ---------------------------------------------------------------------------

_Loader = Any  # Callable[[Path, str | None], bytes]


def _run_guided(
    items: list[tuple[str, Path]],
    *,
    mdb_path: str | None = None,
    log_path: Path,
    loader: _Loader = None,
    save_copyback_bin: bool = True,
) -> None:
    """Interactive batch verify. Each item is (name, csv_path).

    Progress is appended one line at a time to *log_path*. On resume,
    already-completed fixtures are skipped automatically.
    """
    if loader is None:
        loader = _load_csv
    done = _read_progress(log_path)
    if done:
        print(f"Resuming: {len(done)} already done, {len(items) - len(done)} remaining")
    else:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Verify {datetime.now(tz=UTC).isoformat()}\n")

    print()
    print("For each fixture: encodes and copies to clipboard.")
    print("After pasting in Click, enter one of:")
    if save_copyback_bin:
        print("  [w]orked  - paste worked, copy the rung back for comparison/saving")
    else:
        print("  [w]orked  - paste worked")
    print("  [c]rashed - Click crashed or errored")
    print("  [n]ot as expected - pasted but looks wrong")
    print("  [s]kip    - skip this fixture")
    print("  [q]uit    - stop")
    print()

    results: list[tuple[str, str, str]] = []

    for idx, (name, csv_path) in enumerate(items):
        if name in done:
            continue

        print(f"--- {name} ({idx + 1}/{len(items)}) ---")

        try:
            loader(csv_path, mdb_path)
        except RuntimeError as exc:
            loaded = False
            while not loaded:
                print(f"  Clipboard error: {exc}")
                print("  Open Click and press Enter to retry, or [s]kip / [q]uit")
                choice = input("  > ").strip().lower()
                if choice == "q":
                    print()
                    return
                if choice == "s":
                    results.append((name, "skipped", str(exc)))
                    _append_result(log_path, name, "skipped", str(exc))
                    break
                try:
                    loader(csv_path, mdb_path)
                    loaded = True
                except RuntimeError as exc2:
                    exc = exc2
            if not loaded:
                print()
                continue
        except Exception as exc:
            print(f"  Error: {exc}")
            results.append((name, "error", str(exc)))
            _append_result(log_path, name, "error", str(exc))
            print()
            continue

        print("  Paste in Click, then: [w]orked / [c]rashed / [n]ot as expected / [s]kip / [q]uit")
        response = input("  > ").strip().lower()

        if response == "q":
            print()
            break

        if response == "s":
            results.append((name, "skipped", ""))
            _append_result(log_path, name, "skipped")
            print()
            continue

        if response == "n":
            note = input("  What looked wrong? > ").strip()
            if save_copyback_bin:
                print("  Copy the rung back if you want to save it, or just press Enter to skip.")
                save = input("  Save .bin? [y/N] > ").strip().lower()
                if save == "y":
                    try:
                        data = read_from_clipboard()
                    except RuntimeError as exc:
                        print(f"  Clipboard error: {exc}")
                    else:
                        bin_path = csv_path.with_suffix(".bin")
                        bin_path.write_bytes(data)
                        print(f"  Saved {bin_path.name} ({len(data):,} bytes)")
            results.append((name, "unexpected", note or "no description"))
            _append_result(log_path, name, "unexpected", note or "no description")
            print()
            continue

        if response == "c":
            note = input("  Any details? (Enter to skip) > ").strip()
            results.append((name, "crashed", note or ""))
            _append_result(log_path, name, "crashed", note or "")
            print()
            continue

        # Default: "w" or Enter — worked OK.
        if save_copyback_bin:
            bin_path = csv_path.with_suffix(".bin")
            print("  Copy the rung back from Click, then press Enter.")
            input("  > ")
            while True:
                try:
                    _save_and_compare(name, bin_path)
                    break
                except RuntimeError as exc:
                    print(f"  Clipboard error: {exc}")
                    print("  Copy the rung back and press Enter to retry, or [s]kip")
                    if input("  > ").strip().lower() == "s":
                        break
        results.append((name, "worked", ""))
        _append_result(log_path, name, "worked")
        print()

    # Summary
    all_results: list[tuple[str, str, str]] = []
    for name, _ in items:
        if name in done:
            rest = done[name].split(": ", 1)[1]
            if " (" in rest and rest.endswith(")"):
                status, detail = rest.split(" (", 1)
                detail = detail[:-1]
            else:
                status, detail = rest, ""
            all_results.append((name, status, detail))
        else:
            for rname, rstatus, rdetail in results:
                if rname == name:
                    all_results.append((name, rstatus, rdetail))
                    break

    print()
    print("=" * 50)
    print("Results:")
    for name, status, detail in all_results:
        if detail:
            print(f"  {name}: {status} — {detail}")
        else:
            print(f"  {name}: {status}")

    counts: dict[str, int] = {}
    for _, status, _ in all_results:
        counts[status] = counts.get(status, 0) + 1
    remaining = len(items) - len(all_results)
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    if remaining:
        summary += f", {remaining} remaining"
    print(f"\nTotal: {summary}")
    print(f"Progress log: {log_path}")

    has_failures = any(s in ("crashed", "unexpected", "error") for _, s, _ in all_results)
    sys.exit(1 if has_failures else 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clicknick-rung",
        description="Clipboard bridge for CLICK PLC ladder rungs.",
    )
    parser.add_argument("--mdb-path", metavar="PATH", help="Explicit path to SC_.mdb")
    subparsers = parser.add_subparsers(dest="command")

    # --- guided ---
    guided = subparsers.add_parser(
        "guided",
        help="Interactive batch verify CSVs in a folder",
    )
    guided.add_argument("folder", metavar="FOLDER", help="Directory containing CSV fixtures")
    guided.add_argument("--list", action="store_true", help="List fixtures with descriptions")
    guided.add_argument("--restart", action="store_true", help="Clear progress and start fresh")

    # --- program (with load/save subcommands) ---
    program = subparsers.add_parser(
        "program",
        help="Program bundle operations (load into Click or save from Scr*.tmp)",
    )
    prog_sub = program.add_subparsers(dest="program_command")

    prog_load = prog_sub.add_parser(
        "load",
        help="Load a CSV bundle into Click via guided clipboard paste",
    )
    prog_load.add_argument(
        "folder", metavar="FOLDER", help="Directory with main.csv and subroutines/"
    )
    prog_load.add_argument("--restart", action="store_true", help="Clear progress and start fresh")

    prog_save = prog_sub.add_parser(
        "save",
        help="Decode Scr*.tmp files into a CSV bundle (main.csv + subroutines/)",
    )
    prog_save.add_argument("folder", metavar="FOLDER", help="Directory containing Scr*.tmp files")
    prog_save.add_argument(
        "--output", "-o", metavar="DIR", help="Output directory for CSV bundle (default: FOLDER)"
    )

    # --- load ---
    load = subparsers.add_parser(
        "load",
        help="Encode a .csv or .bin file and copy to clipboard",
    )
    load.add_argument("file", metavar="FILE", help="Path to .csv or .bin file")
    load.add_argument(
        "--best-effort",
        action="store_true",
        help="Skip unsupported AF instructions instead of failing",
    )

    # --- save ---
    save = subparsers.add_parser(
        "save",
        help="Save clipboard to file (.bin, .csv, or both)",
    )
    save.add_argument(
        "file",
        metavar="FILE",
        help="Output path: .bin for binary, .csv for decoded CSV, no extension for both",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "guided":
        folder = Path(args.folder)
        if not folder.is_dir():
            print(f"Error: not a directory: {folder}", file=sys.stderr)
            sys.exit(1)
        csvs = sorted(folder.glob("*.csv"))
        if not csvs:
            print(f"No CSV files found in {folder}")
            sys.exit(1)

        if args.list:
            for csv_path in csvs:
                name = csv_path.stem
                try:
                    desc = describe_csv(csv_path)
                except ValueError as exc:
                    desc = f"<parse error: {exc}>"
                bin_path = csv_path.with_suffix(".bin")
                if bin_path.exists():
                    size = bin_path.stat().st_size
                    tag = f" [verified, {size:,} bytes]"
                else:
                    tag = ""
                print(f"  {name}{tag}")
                print(f"    {desc}")
            return

        items = [(p.stem, p) for p in csvs]
        log = folder / "verify_progress.log"
        if args.restart and log.exists():
            log.unlink()
        print(f"Folder: {folder} ({len(items)} CSV files)")
        _run_guided(items, mdb_path=args.mdb_path, log_path=log)
        return

    if args.command == "program":
        if not args.program_command:
            program.print_help()
            sys.exit(1)

        folder = Path(args.folder)
        if not folder.is_dir():
            print(f"Error: not a directory: {folder}", file=sys.stderr)
            sys.exit(1)

        if args.program_command == "save":
            output = Path(args.output) if args.output else None
            try:
                result = program_save(folder, output)
            except (FileNotFoundError, ValueError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)

            for info in result.programs:
                print(
                    f"  {info.source} → {info.name!r}"
                    f" (idx={info.prog_idx}, {info.rung_count} rungs)"
                )
            print(f"  Saved {result.main_csv}")
            for csv_path in result.subroutine_csvs:
                print(f"  Saved {csv_path}")
            print(
                f"\nProgram bundle: 1 main + {len(result.subroutine_csvs)} subroutine(s),"
                f" {result.total_rungs} total rungs"
            )
            return

        # program load
        try:
            items = list_program_bundle(folder)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"Program bundle: {folder}")
        for name, _ in items:
            print(f"  {name}")
        print()

        log = folder / "verify_progress.log"
        if args.restart and log.exists():
            log.unlink()
        _run_guided(
            items,
            mdb_path=args.mdb_path,
            log_path=log,
            loader=_load_program_csv,
            save_copyback_bin=False,
        )
        return

    if args.command == "load":
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: file not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        try:
            if file_path.suffix.lower() == ".csv":
                _load_csv(file_path, args.mdb_path, best_effort=args.best_effort)
            else:
                data = file_path.read_bytes()
                copy_to_clipboard(data)
                print(f"Copied {file_path.name} to clipboard ({len(data):,} bytes)")
        except (RuntimeError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if args.command == "save":
        file_path = Path(args.file)
        try:
            data = read_from_clipboard()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        suffix = file_path.suffix.lower()

        if suffix == ".bin":
            file_path.write_bytes(data)
            print(f"Saved {file_path} ({len(data):,} bytes)")
        elif suffix == ".csv":
            try:
                decode_to_csv(data, file_path)
            except (WriterError, Exception) as exc:
                print(f"Error: could not decode to CSV: {exc}", file=sys.stderr)
                sys.exit(1)
            print(f"Saved {file_path}")
        else:
            bin_path = file_path.with_suffix(".bin")
            csv_path = file_path.with_suffix(".csv")
            bin_path.write_bytes(data)
            print(f"Saved {bin_path} ({len(data):,} bytes)")
            try:
                decode_to_csv(data, csv_path)
                print(f"Saved {csv_path}")
            except (WriterError, Exception) as exc:
                print(
                    f"Warning: could not write CSV: {exc}",
                    file=sys.stderr,
                )
        return
