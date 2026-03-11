"""Golden fixture verification against live CLICK software.

Reads golden CSV/BIN pairs from laddercodec, encodes each CSV via
encode_rung(), copies to clipboard, and compares copy-back bytes
against the golden .bin.

Usage:
    clicknick-ladder-verify                         # Verify all golden fixtures
    clicknick-ladder-verify --list                  # List available fixtures
    clicknick-ladder-verify --copy nc-1row-empty    # Encode + copy to clipboard
    clicknick-ladder-verify --read nc-1row-empty    # Read clipboard + compare
    clicknick-ladder-verify --folder path/to/csvs   # Verify arbitrary CSVs
    clicknick-ladder-verify --mdb-path SC_.mdb ...  # Explicit MDB path
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from laddercodec.csv.contract import CSV_HEADER
from laddercodec.encode import encode_rung
from pyclickplc.addresses import format_address_display, get_addr_key, parse_address

from ..utils.mdb_operations import ensure_addresses_exist
from ..utils.mdb_shared import find_click_database
from .clipboard import copy_to_clipboard, find_click_hwnd, read_from_clipboard

# Golden fixtures live in the laddercodec package
_GOLDEN_DIR: Path | None = None

ADDRESS_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])")
ADDRESS_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})\s*\.\.\s*([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])"
)


def golden_dir() -> Path:
    """Locate the golden fixture directory from laddercodec's installed package."""
    global _GOLDEN_DIR
    if _GOLDEN_DIR is None:
        import laddercodec

        pkg_root = Path(laddercodec.__file__).resolve().parent
        # Navigate from src/laddercodec/ up to repo root, then into tests/
        repo_root = pkg_root.parent.parent
        candidate = repo_root / "tests" / "fixtures" / "ladder_captures" / "golden"
        if not candidate.is_dir():
            raise FileNotFoundError(
                f"Golden fixture directory not found at {candidate}. "
                "Ensure laddercodec is installed as editable."
            )
        _GOLDEN_DIR = candidate
    return _GOLDEN_DIR


def list_fixtures() -> list[str]:
    """Return sorted list of golden fixture names (without extension)."""
    return sorted(p.stem for p in golden_dir().glob("*.csv"))


# ---------------------------------------------------------------------------
# CSV reading (standalone, no dependency on laddercodec test utilities)
# ---------------------------------------------------------------------------


def read_golden_csv(
    path: Path,
) -> tuple[int, list[list[str]], list[str], str | None]:
    """Read a golden CSV and return (logical_rows, condition_rows, af_tokens, comment)."""
    import csv as csv_mod

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        header = next(reader)
        if tuple(header) != CSV_HEADER:
            raise ValueError(f"Bad header in {path.name}")

        comment: str | None = None
        condition_rows: list[list[str]] = []
        af_tokens: list[str] = []

        for row in reader:
            marker = row[0]
            if marker == "#":
                comment = row[1]
            elif marker in ("R", ""):
                condition_rows.append(row[1:32])
                af_tokens.append(row[32])

    return len(condition_rows), condition_rows, af_tokens, comment


# ---------------------------------------------------------------------------
# MDB address provisioning
# ---------------------------------------------------------------------------


def _extract_operand_candidates(token: str) -> list[str]:
    text = token.strip().upper()
    if not text:
        return []
    out: list[str] = []
    for match in ADDRESS_RANGE_RE.finditer(text):
        out.append(match.group(1))
        out.append(match.group(2))
    for match in ADDRESS_TOKEN_RE.finditer(text):
        out.append(match.group(1))
    return out


def extract_addresses_from_csv(path: Path) -> list[str]:
    """Parse operand addresses from a golden CSV file."""
    _, condition_rows, af_tokens, _ = read_golden_csv(path)
    seen_keys: set[int] = set()
    parsed: list[str] = []
    for conditions, af in zip(condition_rows, af_tokens, strict=True):
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
# Core verify operations
# ---------------------------------------------------------------------------


def print_csv_shape(csv_path: Path) -> None:
    """Print the CSV data rows (skip header), trimming trailing empty cells."""
    import csv as csv_mod

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        next(reader)  # skip header
        for row in reader:
            # Trim trailing empty cells
            while row and row[-1] == "":
                row.pop()
            print(f"    {','.join(row)}")


def describe_csv(csv_path: Path) -> str:
    """Return a human-readable summary of a CSV fixture's shape."""
    logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)

    parts: list[str] = []
    parts.append(f"{logical_rows} row{'s' if logical_rows > 1 else ''}")

    if comment is not None:
        if len(comment) > 40:
            parts.append(f"comment ({len(comment)} chars)")
        else:
            parts.append(f'comment "{comment}"')

    # Summarize wire pattern
    wire_rows = 0
    for conditions in condition_rows:
        if any(c in ("-", "|", "T") for c in conditions):
            wire_rows += 1
    if wire_rows == logical_rows:
        parts.append("all rows wired")
    elif wire_rows > 0:
        parts.append(f"{wire_rows} row{'s' if wire_rows > 1 else ''} wired")

    # NOP placement
    nop_rows = [i for i, af in enumerate(af_tokens) if af == "NOP"]
    if nop_rows:
        parts.append(f"NOP on row {nop_rows[0]}")

    # Topology tokens
    has_t = any("T" in cond for row in condition_rows for cond in row)
    has_v = any("|" in cond for row in condition_rows for cond in row)
    if has_t and has_v:
        parts.append("T-junction + vertical")
    elif has_t:
        parts.append("T-junction")
    elif has_v:
        parts.append("vertical")

    return ", ".join(parts)


def describe_fixture(name: str) -> str:
    """Return a human-readable summary of a golden fixture's shape."""
    return describe_csv(golden_dir() / f"{name}.csv")


def encode_csv(csv_path: Path) -> bytes:
    """Encode an arbitrary CSV file and return the payload bytes."""
    logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)
    return encode_rung(logical_rows, condition_rows, af_tokens, comment=comment)


def _copy_and_describe(csv_path: Path, mdb_path: str | None) -> bytes:
    """Describe, encode, provision MDB addresses, copy to clipboard. Return payload."""
    print(f"  {describe_csv(csv_path)}")
    print_csv_shape(csv_path)

    payload = encode_csv(csv_path)

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


def copy_fixture(name: str, mdb_path: str | None = None) -> None:
    """Encode a golden fixture, ensure MDB addresses, copy to clipboard."""
    csv_path = golden_dir() / f"{name}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No golden CSV: {name}")
    _copy_and_describe(csv_path, mdb_path)


def _compare_bin(name: str, bin_path: Path) -> bool:
    """Read clipboard, compare against .bin file, return True if match."""
    if not bin_path.exists():
        print(f"  No .bin for {name} - saving clipboard as new fixture")
        data = read_from_clipboard()
        bin_path.write_bytes(data)
        print(f"  Saved {bin_path.name} ({len(data):,} bytes)")
        return True

    expected = bin_path.read_bytes()
    actual = read_from_clipboard()

    if actual == expected:
        print(f"  {name}: PASS ({len(actual):,} bytes)")
        return True

    print(f"  {name}: FAIL (expected {len(expected):,}, got {len(actual):,} bytes)")
    if len(actual) == len(expected):
        diffs = [i for i in range(len(actual)) if actual[i] != expected[i]]
        print(f"  {len(diffs)} byte(s) differ, first at offset 0x{diffs[0]:04X}")
    return False


def read_and_compare(name: str) -> bool:
    """Read clipboard, compare against golden .bin, return True if match."""
    return _compare_bin(name, golden_dir() / f"{name}.bin")


# ---------------------------------------------------------------------------
# Interactive batch verification (shared by golden and folder modes)
# ---------------------------------------------------------------------------


def run_batch(
    items: list[tuple[str, Path]],
    *,
    mdb_path: str | None = None,
    results_dir: Path | None = None,
) -> None:
    """Interactive batch verify. Each item is (name, csv_path).

    For [p]asted: compares against .bin if it exists, otherwise saves new .bin.
    Results summary is printed and optionally written to *results_dir*.
    """
    print()
    print("For each fixture: encodes and copies to clipboard.")
    print("After pasting in Click, enter one of:")
    print("  [p]asted  - paste worked, copy the rung back for comparison/saving")
    print("  [c]rashed - Click crashed or errored")
    print("  [n]ot as expected - pasted but looks wrong")
    print("  [s]kip    - skip this fixture")
    print("  [q]uit    - stop")
    print()

    results: list[tuple[str, str, str]] = []  # (name, status, detail)
    remaining_names = [name for name, _ in items]

    for idx, (name, csv_path) in enumerate(items):
        print(f"--- {name} ---")

        try:
            _copy_and_describe(csv_path, mdb_path)
        except Exception as exc:
            print(f"  Error: {exc}")
            results.append((name, "error", str(exc)))
            print()
            continue

        print("  Paste in Click, then: [p]asted / [c]rashed / [n]ot as expected / [s]kip / [q]uit")
        response = input("  > ").strip().lower()

        if response == "q":
            results.append((name, "skipped", "quit"))
            for later_name in remaining_names[idx + 1 :]:
                results.append((later_name, "skipped", "quit"))
            break

        if response == "s":
            results.append((name, "skipped", "user"))
            print()
            continue

        if response == "n":
            note = input("  What looked wrong? > ").strip()
            note_path = csv_path.with_suffix(".note.txt")
            note_path.write_text(note or "(no description)", encoding="utf-8")
            print(f"  Saved {note_path.name}")
            print("  Copy the rung back if you want to save it, or just press Enter to skip.")
            save = input("  Save .bin? [y/N] > ").strip().lower()
            if save == "y":
                data = read_from_clipboard()
                bin_path = csv_path.with_suffix(".bin")
                bin_path.write_bytes(data)
                print(f"  Saved {bin_path.name} ({len(data):,} bytes)")
            results.append((name, "unexpected", note or "no description"))
            print()
            continue

        if response == "c":
            note = input("  Any details? (Enter to skip) > ").strip()
            if note:
                note_path = csv_path.with_suffix(".note.txt")
                note_path.write_text(note, encoding="utf-8")
                print(f"  Saved {note_path.name}")
            results.append((name, "crashed", note or ""))
            print()
            continue

        # Default: "p" or Enter - pasted OK, read back and compare/save
        bin_path = csv_path.with_suffix(".bin")
        print("  Copy the rung back from Click, then press Enter.")
        input("  > ")
        if _compare_bin(name, bin_path):
            results.append((name, "pasted", "PASS"))
        else:
            results.append((name, "pasted", "FAIL"))
        print()

    # Summary
    print()
    print("=" * 50)
    print("Results:")
    for name, status, detail in results:
        extra = f" ({detail})" if detail else ""
        print(f"  {name}: {status}{extra}")

    counts: dict[str, int] = {}
    for _, status, _ in results:
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    print(f"\nTotal: {summary}")

    if results_dir:
        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        results_path = results_dir / f"results_{ts}.txt"
        with open(results_path, "w", encoding="utf-8") as f:
            f.write(f"Verify: {results_dir}\n")
            f.write(f"Date: {datetime.now(tz=UTC).isoformat()}\n\n")
            for name, status, detail in results:
                extra = f" ({detail})" if detail else ""
                f.write(f"{name}: {status}{extra}\n")
            f.write(f"\nTotal: {summary}\n")
        print(f"Results written to {results_path}")

    has_failures = any(
        s in ("crashed", "unexpected", "encode_error", "error") for _, s, _ in results
    )
    has_fail_compare = any(s == "pasted" and d == "FAIL" for _, s, d in results)
    sys.exit(1 if (has_failures or has_fail_compare) else 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clicknick-ladder-verify",
        description="Verify golden ladder fixtures against live CLICK software.",
    )
    parser.add_argument("--list", action="store_true", help="List available fixtures")
    parser.add_argument("--copy", metavar="NAME", help="Encode fixture and copy to clipboard")
    parser.add_argument("--read", metavar="NAME", help="Read clipboard and compare against fixture")
    parser.add_argument("--folder", metavar="PATH", help="Verify arbitrary CSVs from a folder")
    parser.add_argument("--skip-to", metavar="NAME", help="Skip to named fixture in batch mode")
    parser.add_argument("--mdb-path", metavar="PATH", help="Explicit path to SC_.mdb")

    args = parser.parse_args()

    if args.list:
        for name in list_fixtures():
            desc = describe_fixture(name)
            bin_path = golden_dir() / f"{name}.bin"
            if bin_path.exists():
                size = bin_path.stat().st_size
                tag = f" [verified, {size:,} bytes]"
            else:
                tag = ""
            print(f"  {name}{tag}")
            print(f"    {desc}")
        return

    if args.copy:
        try:
            copy_fixture(args.copy, mdb_path=args.mdb_path)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if args.read:
        try:
            ok = read_and_compare(args.read)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0 if ok else 1)

    if args.folder:
        folder = Path(args.folder)
        if not folder.is_dir():
            print(f"Error: not a directory: {folder}", file=sys.stderr)
            sys.exit(1)
        csvs = sorted(folder.glob("*.csv"))
        if not csvs:
            print(f"No CSV files found in {folder}")
            sys.exit(1)
        items = [(p.stem, p) for p in csvs]
        print(f"Folder: {folder} ({len(items)} CSV files)")
        run_batch(items, mdb_path=args.mdb_path, results_dir=folder)
        return

    # Default: golden batch verify
    gdir = golden_dir()
    fixtures = list_fixtures()

    if args.skip_to:
        if args.skip_to not in fixtures:
            print(f"Error: unknown fixture '{args.skip_to}'", file=sys.stderr)
            sys.exit(1)
        skip_idx = fixtures.index(args.skip_to)
        fixtures = fixtures[skip_idx:]
        print(f"Resuming from {args.skip_to} ({len(fixtures)} remaining)")
    else:
        print(f"Golden fixtures: {len(fixtures)}")

    items = [(name, gdir / f"{name}.csv") for name in fixtures]
    run_batch(items, mdb_path=args.mdb_path)
