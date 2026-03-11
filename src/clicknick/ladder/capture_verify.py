"""Golden fixture verification against live CLICK software.

Reads golden CSV/BIN pairs from laddercodec, encodes each CSV via
encode_rung(), copies to clipboard, and compares copy-back bytes
against the golden .bin.

Usage:
    clicknick-ladder-verify                         # Verify all golden fixtures
    clicknick-ladder-verify --list                  # List available fixtures
    clicknick-ladder-verify --copy nc-1row-empty    # Encode + copy to clipboard
    clicknick-ladder-verify --read nc-1row-empty    # Read clipboard + compare
    clicknick-ladder-verify --mdb-path SC_.mdb ...  # Explicit MDB path
"""

from __future__ import annotations

import argparse
import re
import sys
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


def encode_fixture(name: str) -> tuple[bytes, Path]:
    """Encode a golden CSV and return (payload_bytes, csv_path)."""
    csv_path = golden_dir() / f"{name}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No golden CSV: {name}")
    logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)
    payload = encode_rung(logical_rows, condition_rows, af_tokens, comment=comment)
    return payload, csv_path


def copy_fixture(name: str, mdb_path: str | None = None) -> None:
    """Encode a golden fixture, ensure MDB addresses, copy to clipboard."""
    payload, csv_path = encode_fixture(name)

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
    print(f"  Copied {name} to clipboard ({len(payload):,} bytes)")


def read_and_compare(name: str) -> bool:
    """Read clipboard, compare against golden .bin, return True if match."""
    bin_path = golden_dir() / f"{name}.bin"
    if not bin_path.exists():
        print(f"  No golden .bin for {name} — saving clipboard as new fixture")
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
    parser.add_argument("--mdb-path", metavar="PATH", help="Explicit path to SC_.mdb")

    args = parser.parse_args()

    if args.list:
        for name in list_fixtures():
            bin_exists = (golden_dir() / f"{name}.bin").exists()
            status = "csv+bin" if bin_exists else "csv only"
            print(f"  {name}  ({status})")
        return

    if args.copy:
        copy_fixture(args.copy, mdb_path=args.mdb_path)
        return

    if args.read:
        ok = read_and_compare(args.read)
        sys.exit(0 if ok else 1)

    # Default: interactive batch verify
    fixtures = list_fixtures()
    print(f"Golden fixtures: {len(fixtures)}")
    print()
    print("For each fixture: copies to clipboard, waits for you to paste in Click")
    print("and copy back, then compares. Press Enter to proceed, 'q' to quit.")
    print()

    passed = 0
    failed = 0

    for name in fixtures:
        print(f"--- {name} ---")
        copy_fixture(name, mdb_path=args.mdb_path)
        print("  Paste in Click, then copy the rung back. Press Enter when ready (q to quit):")

        response = input("  > ").strip().lower()
        if response == "q":
            print(
                f"\nStopped. {passed} passed, {failed} failed, {len(fixtures) - passed - failed} skipped."
            )
            sys.exit(1 if failed else 0)

        if read_and_compare(name):
            passed += 1
        else:
            failed += 1
        print()

    print(f"Done. {passed} passed, {failed} failed.")
    sys.exit(0 if failed == 0 else 1)
