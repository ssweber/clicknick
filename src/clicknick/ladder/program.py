"""Service functions for ladder program operations.

Pure logic — no print(), no input(), no sys.exit().
Returns structured data; callers decide presentation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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
from laddercodec.encode import AfToken, ConditionToken
from pyclickplc.addresses import format_address_display, get_addr_key, parse_address

from ..utils.mdb_operations import ensure_addresses_exist

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADDRESS_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])")
ADDRESS_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})\s*\.\.\s*([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])"
)
_WINDOWS_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ProgramInfo:
    """Metadata about a decoded Scr*.tmp program."""

    source: str
    name: str
    prog_idx: int
    rung_count: int


@dataclass
class SaveResult:
    """Result of program_save(): decoded Scr*.tmp files into a CSV bundle."""

    main_csv: Path
    subroutine_csvs: list[Path]
    programs: list[ProgramInfo]
    total_rungs: int


@dataclass
class PrepareResult:
    """Result of prepare_csv_load(): encoded payload + MDB provisioning info."""

    payload: bytes
    rung_count: int
    addresses: list[str]
    addresses_inserted: int
    mdb_path: Path | None
    mdb_error: str | None


# ---------------------------------------------------------------------------
# Address extraction
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


# ---------------------------------------------------------------------------
# CSV description helpers
# ---------------------------------------------------------------------------


def _collapse_cols(cols: list[str], all_col_names: tuple[str, ...]) -> str:
    """Collapse column lists into ranges: A+C..AE or just A+C."""
    if not cols:
        return ""
    name_to_idx = {name: i for i, name in enumerate(all_col_names)}
    indices = [name_to_idx[c] for c in cols]

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
# Encoding / decoding
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


# ---------------------------------------------------------------------------
# Filename utilities
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert a program name to a filesystem-safe stem while preserving case."""
    stem = _WINDOWS_UNSAFE_FILENAME_RE.sub("", name.strip())
    stem = re.sub(r" {2,}", " ", stem)
    stem = stem.rstrip(" .")
    return stem or "Untitled"


def _dedupe_filename_stem(stem: str, used_stems: set[str]) -> str:
    """Return a unique filename stem using a Windows-style ``(N)`` suffix."""
    candidate = stem
    next_suffix = 2
    while candidate.casefold() in used_stems:
        candidate = f"{stem} ({next_suffix})"
        next_suffix += 1
    used_stems.add(candidate.casefold())
    return candidate


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def program_save(scr_folder: Path, output: Path | None = None) -> SaveResult:
    """Decode all Scr*.tmp files into a CSV bundle.

    Writes main.csv for prog_idx 1 and subroutines/{name}.csv for prog_idx 2+.
    Output defaults to *scr_folder* unless *output* is given.

    Raises FileNotFoundError if no Scr*.tmp files found.
    Raises ValueError if no main program (prog_idx=1) found.
    """
    scr_files = sorted(scr_folder.glob("Scr*.tmp"))
    if not scr_files:
        raise FileNotFoundError(f"No Scr*.tmp files found in {scr_folder}")

    dest = output or scr_folder
    dest.mkdir(parents=True, exist_ok=True)

    from laddercodec.model import Program

    raw_programs: list[Program] = []
    infos: list[ProgramInfo] = []
    for scr_path in scr_files:
        data = scr_path.read_bytes()
        prog = decode_program(data)
        raw_programs.append(prog)
        infos.append(
            ProgramInfo(
                source=scr_path.name,
                name=prog.name,
                prog_idx=prog.prog_idx,
                rung_count=len(prog.rungs),
            )
        )

    raw_programs.sort(key=lambda p: p.prog_idx)
    infos.sort(key=lambda i: i.prog_idx)

    main_progs = [p for p in raw_programs if p.prog_idx == 1]
    sub_progs = [p for p in raw_programs if p.prog_idx > 1]

    if not main_progs:
        raise ValueError("No main program (prog_idx=1) found")

    main_csv = dest / "main.csv"
    write_csv(main_csv, main_progs[0].rungs)

    subroutine_csvs: list[Path] = []
    if sub_progs:
        sub_dir = dest / "subroutines"
        sub_dir.mkdir(exist_ok=True)
        used_stems: set[str] = set()
        for prog in sub_progs:
            stem = _dedupe_filename_stem(_slugify(prog.name), used_stems)
            csv_path = sub_dir / f"{stem}.csv"
            write_csv(csv_path, prog.rungs)
            subroutine_csvs.append(csv_path)

    total_rungs = sum(len(p.rungs) for p in raw_programs)

    return SaveResult(
        main_csv=main_csv,
        subroutine_csvs=subroutine_csvs,
        programs=infos,
        total_rungs=total_rungs,
    )


def prepare_csv_load(
    csv_path: Path,
    *,
    mdb_path: Path | None = None,
    best_effort: bool = False,
) -> PrepareResult:
    """Encode a CSV file and provision MDB addresses.

    Does NOT copy to clipboard — the caller handles that so it can choose
    the owner HWND (GUI passes its tracked Click window, CLI auto-detects).
    """
    rungs = read_csv(csv_path, strict=not best_effort)
    payload = encode(rungs) if len(rungs) > 1 else encode(rungs[0])

    addresses = extract_addresses_from_csv(csv_path, best_effort=best_effort)
    addresses_inserted = 0
    mdb_error = None

    if addresses and mdb_path:
        try:
            result = ensure_addresses_exist(str(mdb_path), addresses)
            addresses_inserted = result.get("inserted_count", 0)
        except (FileNotFoundError, RuntimeError) as exc:
            mdb_error = str(exc)

    return PrepareResult(
        payload=payload,
        rung_count=len(rungs),
        addresses=addresses,
        addresses_inserted=addresses_inserted,
        mdb_path=mdb_path if not mdb_error else None,
        mdb_error=mdb_error,
    )


def list_csv_folder(folder: Path) -> list[tuple[str, Path]]:
    """List CSV files in a folder for guided paste.

    Excludes ``nicknames.csv``.  Main-level CSVs come first (sorted),
    then ``subroutines/*.csv`` (sorted).
    """
    items: list[tuple[str, Path]] = []
    for p in sorted(folder.glob("*.csv")):
        if p.name.lower() == "nicknames.csv":
            continue
        items.append((p.name, p))
    sub_dir = folder / "subroutines"
    if sub_dir.is_dir():
        for p in sorted(sub_dir.glob("*.csv")):
            items.append((f"subroutines/{p.name}", p))
    return items


def read_csv_comment(csv_path: Path) -> str:
    """Return the first ``# …`` comment line from a CSV, or ``''``."""
    try:
        with open(csv_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line.startswith("#"):
                return first_line.lstrip("#").strip()
    except OSError:
        pass
    return ""


def count_csv_rungs(csv_path: Path) -> int:
    """Count rungs in a ladder CSV.  Returns 0 on parse error."""
    try:
        return len(read_csv(csv_path, strict=False))
    except Exception:
        return 0


def list_program_bundle(folder: Path) -> list[tuple[str, Path]]:
    """List CSV items in a program bundle (subroutines first, then main).

    Raises FileNotFoundError if main.csv is missing.
    """
    main_csv = folder / "main.csv"
    if not main_csv.exists():
        raise FileNotFoundError(f"{folder} is missing required main.csv")

    items: list[tuple[str, Path]] = []
    sub_dir = folder / "subroutines"
    if sub_dir.is_dir():
        for p in sorted(sub_dir.glob("*.csv")):
            items.append((p.stem, p))
    items.append(("Main Program", main_csv))
    return items
