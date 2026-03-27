"""Clipboard bridge for CLICK PLC ladder rungs.

Encodes CSV fixtures, copies to/from Click's private clipboard format,
and provides interactive batch verification against live CLICK software.

Usage:
    clicknick-rung guided FOLDER                # Interactive batch verify
    clicknick-rung guided FOLDER --list         # List CSVs with descriptions
    clicknick-rung guided FOLDER --restart      # Clear progress, start fresh
    clicknick-rung program load FOLDER          # Verify a program bundle (main.csv + subroutines/)
    clicknick-rung program save FOLDER          # Decode Scr*.tmp → main.csv + subroutines/
    clicknick-rung load FILE                    # Encode .csv/.bin → clipboard
    clicknick-rung save FILE                    # Clipboard → .bin/.csv/both
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    Timer,
    decode,
    decode_program,
    encode,
    read_csv,
    write_csv,
)
from laddercodec.csv import CONDITION_COLUMNS
from laddercodec.csv.writer import WriterError
from laddercodec.encode import AfToken, ConditionToken
from pyclickplc.addresses import format_address_display, get_addr_key, parse_address

from ..utils.mdb_operations import ensure_addresses_exist
from ..utils.mdb_shared import find_click_database
from .clipboard import copy_to_clipboard, find_click_hwnd, read_from_clipboard

ADDRESS_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])")
ADDRESS_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})\s*\.\.\s*([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])"
)


# ---------------------------------------------------------------------------
# MDB address provisioning
# ---------------------------------------------------------------------------


def _extract_operand_candidates(token: ConditionToken | AfToken) -> list[str]:
    def _append(value: str | None, *, address_only: bool = False) -> None:
        if not value:
            return
        candidate = value.strip().upper()
        if not candidate:
            return
        if address_only and not ADDRESS_TOKEN_RE.fullmatch(candidate):
            return
        out.append(candidate)

    out: list[str] = []

    # Prefer structured fields for core instruction types so we don't duplicate
    # range endpoints or lose literal operands when laddercodec's CSV formatting changes.
    if isinstance(token, Contact):
        _append(token.operand)
        return out
    if isinstance(token, Coil):
        _append(token.operand)
        _append(token.range_end)
        return out
    if isinstance(token, CompareContact):
        _append(token.left)
        _append(token.right)
        return out
    if isinstance(token, Timer):
        _append(token.done_bit)
        _append(token.current)
        _append(token.setpoint, address_only=True)
        return out

    # Use to_csv() for any other instruction object — future-proof against new types.
    if isinstance(token, str):
        text = token.strip().upper()
    elif hasattr(token, "to_csv"):
        text = token.to_csv().upper()
    else:
        return []
    if not text:
        return []
    for match in ADDRESS_RANGE_RE.finditer(text):
        _append(match.group(1))
        _append(match.group(2))
    for match in ADDRESS_TOKEN_RE.finditer(text):
        _append(match.group(1))
    return list(dict.fromkeys(out))


def extract_addresses_from_csv(path: Path, *, best_effort: bool = False) -> list[str]:
    """Parse operand addresses from a CSV file (single or multi-rung)."""
    rungs = read_csv(path, strict=not best_effort)
    seen_keys: set[int] = set()
    parsed: list[str] = []
    for rung in rungs:
        for conditions, af in zip(rung.conditions, rung.instructions, strict=True):
            for token in [*conditions, af]:
                for candidate in _extract_operand_candidates(token):
                    try:
                        memory_type, address = parse_address(candidate)
                    except ValueError:
                        continue
                    addr_key = get_addr_key(memory_type, address)
                    if addr_key in seen_keys:
                        continue
                    seen_keys.add(addr_key)
                    parsed.append(format_address_display(memory_type, address))
    return parsed


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


def ensure_mdb_addresses(mdb_path: str | None, csv_path: Path) -> dict[str, Any]:
    """Parse operand addresses from CSV and ensure they exist in SC_.mdb."""
    addresses = extract_addresses_from_csv(csv_path)
    if not addresses:
        return {"addresses": [], "inserted": 0}
    resolved = resolve_mdb_path(mdb_path)
    summary = ensure_addresses_exist(str(resolved), addresses)
    return {"db_path": str(resolved), "addresses": addresses, **summary}


# ---------------------------------------------------------------------------
# CSV description helpers
# ---------------------------------------------------------------------------


def print_csv_shape(csv_path: Path) -> None:
    """Print the CSV data rows (skip header) as-is."""
    import csv as csv_mod

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        next(reader)  # skip header
        for row in reader:
            print(f"    {','.join(row)}")


def _collapse_cols(cols: list[str], all_col_names: tuple[str, ...]) -> str:
    """Collapse column lists into ranges: A+C..AE or just A+C."""
    if not cols:
        return ""
    # Convert to indices for contiguous-run detection
    name_to_idx = {name: i for i, name in enumerate(all_col_names)}
    indices = [name_to_idx[c] for c in cols]

    # Group into contiguous runs
    runs: list[list[int]] = []
    for idx in indices:
        if runs and idx == runs[-1][-1] + 1:
            runs[-1].append(idx)
        else:
            runs.append([idx])

    parts: list[str] = []
    for run in runs:
        if len(run) >= 3:
            parts.append(f"{all_col_names[run[0]]}..{all_col_names[run[-1]]}")
        else:
            parts.extend(all_col_names[i] for i in run)
    return "+".join(parts)


def _describe_row_wires(conditions: list[str], col_names: tuple[str, ...]) -> str:
    """Describe wire tokens on a single row, e.g. '-:A+C..AE T:B' or 'full'."""
    by_token: dict[str, list[str]] = {}
    for i, tok in enumerate(conditions):
        if tok in ("-", "|", "T"):
            by_token.setdefault(tok, []).append(col_names[i])

    if not by_token:
        return ""

    # Check for full horizontal wire (all 31 columns are '-')
    dash_cols = by_token.get("-", [])
    if len(dash_cols) == len(col_names):
        return "full"

    parts: list[str] = []
    for tok in ("-", "T", "|"):
        cols = by_token.get(tok, [])
        if not cols:
            continue
        col_str = _collapse_cols(cols, col_names)
        parts.append(f"{tok}:{col_str}")
    return " ".join(parts)


def _describe_single_rung(
    condition_rows: list[list[str]],
    af_tokens: list[str],
    comment: str | None,
    col_names: tuple[str, ...],
) -> str:
    """Return a human-readable summary of a single rung's shape."""
    logical_rows = len(condition_rows)
    parts: list[str] = []
    parts.append(f"{logical_rows} row{'s' if logical_rows > 1 else ''}")

    if comment is not None:
        if len(comment) > 40:
            parts.append(f"comment ({len(comment)} chars)")
        else:
            parts.append(f'comment "{comment}"')

    raw_descs: list[tuple[int, str]] = []
    for i, conditions in enumerate(condition_rows):
        wire_desc = _describe_row_wires(conditions, col_names)
        af = af_tokens[i] if i < len(af_tokens) else ""
        if af and wire_desc:
            raw_descs.append((i, f"{wire_desc} AF={af}"))
        elif af:
            raw_descs.append((i, f"AF={af}"))
        elif wire_desc:
            raw_descs.append((i, wire_desc))

    row_descs: list[str] = []
    j = 0
    while j < len(raw_descs):
        start_idx, desc = raw_descs[j]
        end_idx = start_idx
        while (
            j + 1 < len(raw_descs)
            and raw_descs[j + 1][1] == desc
            and raw_descs[j + 1][0] == end_idx + 1
        ):
            j += 1
            end_idx = raw_descs[j][0]
        if end_idx > start_idx:
            row_descs.append(f"[{start_idx}..{end_idx}] {desc}")
        else:
            row_descs.append(f"[{start_idx}] {desc}")
        j += 1
    if row_descs:
        parts.append("; ".join(row_descs))

    return ", ".join(parts)


def describe_csv(csv_path: Path, *, best_effort: bool = False) -> str:
    """Return a human-readable summary of a CSV fixture's shape."""
    rungs = read_csv(csv_path, strict=not best_effort)
    if len(rungs) > 1:
        rung_descs = [
            _describe_single_rung(r.conditions, r.instructions, r.comment, CONDITION_COLUMNS)
            for r in rungs
        ]
        return f"{len(rungs)} rungs: " + " | ".join(rung_descs)

    r = rungs[0]
    return _describe_single_rung(r.conditions, r.instructions, r.comment, CONDITION_COLUMNS)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def encode_csv(csv_path: Path, *, best_effort: bool = False) -> bytes:
    """Encode a CSV file and return the payload bytes."""
    rungs = read_csv(csv_path, strict=not best_effort)
    if len(rungs) > 1:
        return encode(rungs)
    return encode(rungs[0])


def decode_to_csv(data: bytes, path: Path) -> None:
    """Decode clipboard/program bytes and write canonical CSV."""
    result = decode(data)
    rungs = result if isinstance(result, list) else [result]
    write_csv(path, rungs)


def _load_csv(csv_path: Path, mdb_path: str | None, *, best_effort: bool = False) -> bytes:
    """Describe, encode, provision MDB addresses, copy to clipboard. Return payload."""
    print(f"  {describe_csv(csv_path, best_effort=best_effort)}")
    print_csv_shape(csv_path)

    payload = encode_csv(csv_path, best_effort=best_effort)

    addresses = extract_addresses_from_csv(csv_path, best_effort=best_effort)
    if addresses:
        try:
            mdb = resolve_mdb_path(mdb_path)
            result = ensure_addresses_exist(str(mdb), addresses)
            inserted = result.get("inserted_count", 0)
            if inserted:
                print(f"  MDB: inserted {inserted} address(es) into {mdb.name}")
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"  MDB: skipped ({exc})")

    copy_to_clipboard(payload)
    print(f"  Copied to clipboard ({len(payload):,} bytes)")
    return payload


def _load_program_csv(csv_path: Path, mdb_path: str | None) -> bytes:
    """Encode a program/subroutine CSV and copy to clipboard. Minimal output."""
    rungs = read_csv(csv_path, strict=True)
    print(f"  {len(rungs)} rung{'s' if len(rungs) != 1 else ''}")

    if len(rungs) > 1:
        payload = encode(rungs)
    else:
        payload = encode(rungs[0])

    addresses = extract_addresses_from_csv(csv_path)
    if addresses:
        try:
            mdb = resolve_mdb_path(mdb_path)
            result = ensure_addresses_exist(str(mdb), addresses)
            inserted = result.get("inserted_count", 0)
            if inserted:
                print(f"  MDB: inserted {inserted} address(es) into {mdb.name}")
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"  MDB: skipped ({exc})")

    copy_to_clipboard(payload)
    print(f"  Copied to clipboard ({len(payload):,} bytes)")
    return payload


def _save_and_compare(name: str, bin_path: Path) -> None:
    """Read clipboard, save as .bin, and report byte diff if .bin already exists.

    The comparison is informational only — Click re-encodes on copy-back,
    so byte-exact match is not expected.
    """
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


def _slugify(name: str) -> str:
    """Convert a program name to a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", name.strip()).strip()
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug.lower()


def _program_save(folder: Path, output: Path | None = None) -> None:
    """Decode all Scr*.tmp files in *folder* into a CSV bundle.

    Writes main.csv for prog_idx 1 (main program) and subroutines/{slug}.csv
    for prog_idx 2+.  Output defaults to *folder* unless *output* is given.
    """
    scr_files = sorted(folder.glob("Scr*.tmp"))
    if not scr_files:
        print(f"Error: no Scr*.tmp files found in {folder}", file=sys.stderr)
        sys.exit(1)

    dest = output or folder
    dest.mkdir(parents=True, exist_ok=True)

    from laddercodec.model import Program

    programs: list[Program] = []
    for scr_path in scr_files:
        data = scr_path.read_bytes()
        prog = decode_program(data)
        programs.append(prog)
        print(f"  {scr_path.name} → {prog.name!r} (idx={prog.prog_idx}, {len(prog.rungs)} rungs)")

    programs.sort(key=lambda p: p.prog_idx)

    main_progs = [p for p in programs if p.prog_idx == 1]
    sub_progs = [p for p in programs if p.prog_idx > 1]

    if not main_progs:
        print("Error: no main program (prog_idx=1) found", file=sys.stderr)
        sys.exit(1)

    # Write main.csv
    main_csv = dest / "main.csv"
    write_csv(main_csv, main_progs[0].rungs)
    print(f"  Saved {main_csv}")

    # Write subroutines
    if sub_progs:
        sub_dir = dest / "subroutines"
        sub_dir.mkdir(exist_ok=True)
        for prog in sub_progs:
            slug = _slugify(prog.name)
            csv_path = sub_dir / f"{slug}.csv"
            write_csv(csv_path, prog.rungs)
            print(f"  Saved {csv_path}")

    total_rungs = sum(len(p.rungs) for p in programs)
    print(
        f"\nProgram bundle: {len(main_progs)} main + {len(sub_progs)} subroutine(s),"
        f" {total_rungs} total rungs"
    )


# ---------------------------------------------------------------------------
# Interactive batch verification
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
        # Format: "name: status" or "name: status (detail)"
        if ": " in line:
            name = line.split(": ", 1)[0]
            done[name] = line
    return done


def _append_result(log_path: Path, name: str, status: str, detail: str = "") -> None:
    """Append one result line to the progress log."""
    extra = f" ({detail})" if detail else ""
    line = f"{name}: {status}{extra}\n"
    with open(log_path, "a+", encoding="utf-8") as f:
        # Ensure we start on a new line even if a trailing newline was removed
        f.seek(0, 2)  # seek to end
        if f.tell() > 0:
            f.seek(f.tell() - 1)
            if f.read(1) != "\n":
                f.write("\n")
        f.write(line)


_Loader = Any  # Callable[[Path, str | None], bytes]


def _run_guided(
    items: list[tuple[str, Path]],
    *,
    mdb_path: str | None = None,
    log_path: Path,
    loader: _Loader = None,
) -> None:
    """Interactive batch verify. Each item is (name, csv_path).

    Progress is appended one line at a time to *log_path*. On resume,
    already-completed fixtures are skipped automatically.
    """
    if loader is None:
        loader = _load_csv
    # Load prior progress
    done = _read_progress(log_path)
    if done:
        print(f"Resuming: {len(done)} already done, {len(items) - len(done)} remaining")
    else:
        # Start fresh log with timestamp header
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Verify {datetime.now(tz=UTC).isoformat()}\n")

    print()
    print("For each fixture: encodes and copies to clipboard.")
    print("After pasting in Click, enter one of:")
    print("  [w]orked  - paste worked, copy the rung back for comparison/saving")
    print("  [c]rashed - Click crashed or errored")
    print("  [n]ot as expected - pasted but looks wrong")
    print("  [s]kip    - skip this fixture")
    print("  [q]uit    - stop")
    print()

    results: list[tuple[str, str, str]] = []  # (name, status, detail)

    for idx, (name, csv_path) in enumerate(items):
        if name in done:
            continue

        print(f"--- {name} ({idx + 1}/{len(items)}) ---")

        try:
            loader(csv_path, mdb_path)
        except RuntimeError as exc:
            # Clipboard / Click-not-running — prompt to retry
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

        # Default: "w" or Enter - worked OK, read back and compare/save
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

    # Summary — combine prior progress + this session
    all_results: list[tuple[str, str, str]] = []
    for name, _ in items:
        if name in done:
            # Parse status and detail from log line "name: status (detail)"
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
            _program_save(folder, output)
            return

        # program load
        main_csv = folder / "main.csv"
        if not main_csv.exists():
            print(f"Error: {folder} is missing required main.csv", file=sys.stderr)
            sys.exit(1)

        # Subroutines first so user can create them in Click before pasting main
        items: list[tuple[str, Path]] = []
        sub_dir = folder / "subroutines"
        if sub_dir.is_dir():
            for p in sorted(sub_dir.glob("*.csv")):
                items.append((p.stem, p))
        items.append(("Main Program", main_csv))

        print(f"Program bundle: {folder}")
        for name, _ in items:
            print(f"  {name}")
        print()

        log = folder / "verify_progress.log"
        if args.restart and log.exists():
            log.unlink()
        _run_guided(items, mdb_path=args.mdb_path, log_path=log, loader=_load_program_csv)
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
            # No recognized extension → save both .bin and .csv
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
