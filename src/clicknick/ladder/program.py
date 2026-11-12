"""Service functions for ladder program operations.

Pure logic — no print(), no input(), no sys.exit().
Returns structured data; callers decide presentation.
"""

from __future__ import annotations

import csv
import json
import re
import warnings
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import laddercodec
from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    Rung,
    Timer,
    decode,
    decode_program,
    encode,
    find_v4_only,
    read_csv,
    write_csv,
)
from laddercodec.csv import CONDITION_COLUMNS
from laddercodec.encode import AfToken, ConditionToken
from laddercodec.instructions import UnknownCondition, UnknownInstruction
from pyclickplc.addresses import format_address_display, get_addr_key, parse_address

from ..utils.mdb_operations import ensure_addresses_exist

if TYPE_CHECKING:
    from laddercodec.model import Program

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADDRESS_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])")
ADDRESS_RANGE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}\d{1,5})\s*\.\.\s*([A-Za-z]{1,3}\d{1,5})(?![A-Za-z0-9_])"
)
_WINDOWS_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')
# The marker field of a ladder CSV row that starts a rung: R, or R and its number
_RUNG_MARKER_RE = re.compile(r"R[0-9]*")

# Written beside a CSV bundle when CLICK holds rungs in a form an older laddercodec wrote
LEGACY_ENCODINGS_FILE = "legacy_encodings.json"
# First line of the comment on the empty rung program_save writes for a rung it cannot read.
# prepare_rungs_load refuses to copy such a rung, so pasting it cannot replace the real one.
STAND_IN_COMMENT = "ClickNick cannot read this rung from CLICK. This empty rung stands in for it."
# Workspaces saved before the wording changed start the comment this way
_OLD_STAND_IN_COMMENT = (
    "ClickNick could not read this rung from CLICK. This empty rung stands in for it."
)


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


@dataclass(frozen=True)
class LegacyEncoding:
    """A rung CLICK holds in a form an older laddercodec wrote, so it must be pasted again.

    Either CLICK runs it differently from how its CSV text reads, or (*unreadable*)
    laddercodec cannot read one of its instructions.
    """

    # The bundle names the program main.csv or subroutines/<stem>.csv
    file: str
    program: str
    # CLICK numbers rungs from 1. None means the decoder could not say which rung.
    rung: int | None
    instruction: str
    token: str
    # What CLICK runs instead, e.g. "it is stored as 16-bit and CLICK runs it as 4464."
    detail: str
    # With a rung number, the bundle holds an empty rung in its place (STAND_IN_COMMENT).
    # With none, laddercodec cannot read the program's CSV back, so it is pasted whole.
    unreadable: bool = False


@dataclass
class SaveResult:
    """Result of program_save(): decoded Scr*.tmp files into a CSV bundle."""

    main_csv: Path
    subroutine_csvs: list[Path]
    programs: list[ProgramInfo]
    total_rungs: int
    # Also written to LEGACY_ENCODINGS_FILE beside the CSVs
    legacy_encodings: list[LegacyEncoding] = field(default_factory=list)


@dataclass
class PrepareResult:
    """Result of preparing a ladder payload plus MDB provisioning info."""

    payload: bytes
    rung_count: int
    addresses: list[str]
    addresses_inserted: int
    mdb_path: Path | None
    mdb_error: str | None


class NeedsClickV4Error(ValueError):
    """The rungs use CLICK v4 instructions, but the target CLICK is older."""


class UnreadableRungError(ValueError):
    """Decoded rungs hold an instruction laddercodec cannot read, so they have no CSV."""


# ---------------------------------------------------------------------------
# CLICK version
# ---------------------------------------------------------------------------

_V4_ONLY_LISTED = 5


def check_click_version(rungs: list[Rung], *, click_v4: bool, first_rung: int = 1) -> None:
    """Raise NeedsClickV4Error if *rungs* need CLICK v4 and the target is older.

    An older CLICK takes a v4 rung on paste without complaint and silently
    changes it, so this refuses before anything reaches the clipboard.
    *first_rung* numbers the rungs in the message.
    """
    if click_v4:
        return
    found = find_v4_only(rungs)
    if not found:
        return
    lines = [f"  rung {first_rung + index}: {ins.to_csv()}" for index, ins in found]
    if len(lines) > _V4_ONLY_LISTED:
        lines[_V4_ONLY_LISTED:] = [f"  ...and {len(lines) - _V4_ONLY_LISTED} more"]
    raise NeedsClickV4Error(
        "These rungs need CLICK v4, but the CLICK window is an older version, "
        "which would silently change them on paste:\n" + "\n".join(lines)
    )


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


def extract_addresses_from_rungs(rungs: list[Rung]) -> list[str]:
    """Parse operand addresses from already-parsed rung objects."""
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


def extract_addresses_from_csv(path: Path, *, best_effort: bool = False) -> list[str]:
    """Parse operand addresses from a CSV file (single or multi-rung)."""
    rungs = read_csv(path, strict=not best_effort)
    return extract_addresses_from_rungs(rungs)


def _decode_to_rungs(data: bytes) -> list[Rung]:
    """Decode clipboard/program bytes into a normalized rung list."""
    result = decode(data)
    return result if isinstance(result, list) else [result]


def extract_addresses_from_bin(data: bytes) -> list[str]:
    """Parse operand addresses from a clipboard-format binary payload."""
    return extract_addresses_from_rungs(_decode_to_rungs(data))


def _provision_mdb_addresses(
    addresses: list[str], *, mdb_path: Path | None = None
) -> tuple[int, Path | None, str | None]:
    """Insert missing addresses into the MDB when one is available."""
    addresses_inserted = 0
    mdb_error = None

    if addresses and mdb_path:
        try:
            result = ensure_addresses_exist(str(mdb_path), addresses)
            addresses_inserted = result.get("inserted_count", 0)
        except (FileNotFoundError, RuntimeError) as exc:
            mdb_error = str(exc)

    return addresses_inserted, (mdb_path if not mdb_error else None), mdb_error


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
    if not rungs:
        return "0 rungs"
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
    """Encode a CSV file and return the payload bytes.

    Raises ValueError when the CSV holds no rungs: there is nothing to paste.
    """
    rungs = read_csv(csv_path, strict=not best_effort)
    if not rungs:
        raise ValueError(f"{csv_path.name} holds no rungs")
    if len(rungs) > 1:
        return encode(rungs)
    return encode(rungs[0])


def _instruction_name(raw: bytes) -> str:
    """Name the instruction an ``UnknownCondition`` holds, e.g. "Compare".

    A Scr*.tmp gives only the name, in ASCII. The clipboard gives the whole
    instruction, which starts with its name in UTF-16 ended by a null.
    """
    end = next((i for i in range(0, len(raw) - 1, 2) if raw[i : i + 2] == b"\0\0"), None)
    try:
        name = raw[:end].decode("utf-16-le") if end is not None else raw.decode("ascii")
    except UnicodeDecodeError:
        return "instruction"
    return name if name.isidentifier() else "instruction"


def _unreadable_instructions(rung: Rung) -> list[str]:
    """Name each instruction of *rung* that laddercodec cannot read, once each."""
    cells = [cell for row in rung.conditions for cell in row]
    names = (
        _instruction_name(cell.raw)
        for cell in [*cells, *rung.instructions]
        if isinstance(cell, (UnknownCondition, UnknownInstruction))
    )
    return list(dict.fromkeys(names))


def _unreadable_detail(name: str) -> str:
    return f"ClickNick cannot read this {name}."


def decode_to_csv(data: bytes, path: Path) -> None:
    """Decode clipboard/program bytes and write canonical CSV.

    Raises UnreadableRungError, before writing anything, when a rung holds an
    instruction laddercodec cannot read.
    """
    rungs = _decode_to_rungs(data)
    found = [
        f"  copied rung {number}, {name}: {_unreadable_detail(name)}"
        for number, rung in enumerate(rungs, start=1)
        for name in _unreadable_instructions(rung)
    ]
    if found:
        raise UnreadableRungError(
            "ClickNick cannot read these rungs, so it wrote no CSV:\n"
            + "\n".join(found)
            + "\nFix them in CLICK and copy them again."
        )
    write_csv(path, rungs, index=True)


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


def _decode_program_recording_legacy(data: bytes) -> tuple[Program, list[Warning]]:
    """Decode one Scr*.tmp, collecting the legacy encodings laddercodec warns about.

    Other warnings are passed on once decoding is done. A laddercodec too old
    to warn about legacy encodings decodes as before and reports none.
    """
    legacy_type = getattr(laddercodec, "LegacyEncodingWarning", None)
    if legacy_type is None:
        return decode_program(data), []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", legacy_type)
        prog = decode_program(data)
    found: list[Warning] = []
    for record in caught:
        if isinstance(record.message, legacy_type):
            found.append(record.message)
        else:
            warnings.warn_explicit(record.message, record.category, record.filename, record.lineno)
    return prog, found


def _legacy_encoding(file: str, prog: Program, warning: Warning) -> LegacyEncoding:
    """Name a legacy-encoding warning's rung the way CLICK and the bundle name it."""
    rung = getattr(warning, "rung", None)
    return LegacyEncoding(
        file=file,
        program=str(getattr(warning, "program", None) or prog.name),
        rung=rung + 1 if isinstance(rung, int) else None,
        instruction=str(getattr(warning, "instruction", "")),
        token=str(getattr(warning, "token", "")),
        detail=str(getattr(warning, "detail", "")),
    )


def empty_rung(comment: str) -> Rung:
    """A one-row rung with no instructions, holding only *comment*."""
    return Rung(
        logical_rows=1,
        conditions=[[""] * len(CONDITION_COLUMNS)],
        instructions=[""],
        comment=comment,
    )


def is_empty_rung(rung: Rung) -> bool:
    """Whether *rung* holds only wires and no instruction, as a stand-in does."""
    return all(isinstance(cell, str) for row in rung.conditions for cell in row) and all(
        token in ("", "NOP") for token in rung.instructions
    )


def _stand_in(rung: Rung, names: Sequence[str]) -> Rung:
    """An empty rung, keeping the rung numbers below it, that says which rung it replaces."""
    lines = [STAND_IN_COMMENT, f"ClickNick cannot read its {', '.join(names)}. Paste it again."]
    if rung.comment:
        lines += ["", rung.comment]
    return empty_rung("\n".join(lines))


def _replace_unreadable(file: str, prog: Program) -> tuple[list[Rung], list[LegacyEncoding]]:
    """The program's rungs, each one laddercodec cannot read swapped for a stand-in.

    Also returns a finding for each instruction it cannot read.
    """
    rungs: list[Rung] = []
    found: list[LegacyEncoding] = []
    for number, rung in enumerate(prog.rungs, start=1):
        names = _unreadable_instructions(rung)
        if not names:
            rungs.append(rung)
            continue
        rungs.append(_stand_in(rung, names))
        found.extend(
            LegacyEncoding(
                file, prog.name, number, name, "", _unreadable_detail(name), unreadable=True
            )
            for name in names
        )
    return rungs, found


def is_stand_in(rung: Rung) -> bool:
    """Whether *rung* is the empty rung program_save wrote for a rung it cannot read."""
    first = (rung.comment or "").split("\n", 1)[0]
    return first in (STAND_IN_COMMENT, _OLD_STAND_IN_COMMENT) and is_empty_rung(rung)


def unreadable_copy(file: str, program: str, exc: Exception) -> LegacyEncoding:
    """A finding that laddercodec cannot read a whole CSV. *exc* says why."""
    lines = str(exc).strip().splitlines()
    reason = lines[0] if lines else type(exc).__name__
    detail = f"ClickNick cannot read CLICK's copy of this program. {reason}"
    return LegacyEncoding(file, program, None, "", "", detail, unreadable=True)


def _read_back(path: Path, file: str, program: str) -> list[LegacyEncoding]:
    """A finding when laddercodec cannot read the CSV just written at *path*.

    pyrung reads CSVs on its own, so the build would not notice. Preview Changes
    would, and then it pastes the whole program again.
    """
    try:
        read_csv(path)
    except OSError:
        return []  # Nothing to say about its text
    except Exception as exc:
        return [unreadable_copy(file, program, exc)]
    return []


def write_legacy_encodings(csv_dir: Path, found: Sequence[LegacyEncoding]) -> None:
    """Record *found* beside the bundle in *csv_dir*, or remove the record when none."""
    path = csv_dir / LEGACY_ENCODINGS_FILE
    if not found:
        path.unlink(missing_ok=True)
        return
    entries = [asdict(item) for item in found]
    for entry in entries:
        if not entry["unreadable"]:
            del entry["unreadable"]  # A legacy entry keeps the six keys it always had
    text = json.dumps(entries, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def describe_legacy_encoding(item: LegacyEncoding, *, program: bool = True) -> str:
    """Say which rung holds a legacy encoding and what CLICK runs instead.

    ``Main Program rung 12, Math H70000: it is stored as 16-bit and CLICK runs
    it as 4464.`` Without *program* the line starts at ``rung 12``.
    """
    what = " ".join(part for part in (item.instruction, item.token) if part)
    if item.rung is None and not what:
        # A finding about the whole copy, such as a CSV Preview Changes cannot read
        return f"{item.program or item.file}: {item.detail}" if program else item.detail
    where = "an unknown rung" if item.rung is None else f"rung {item.rung}"
    if program:
        where = f"{item.program or item.file} {where}"
    return f"{where}, {what}: {item.detail}" if what else f"{where}: {item.detail}"


def read_legacy_encodings(csv_dir: Path) -> tuple[LegacyEncoding, ...]:
    """Read the legacy encodings ``program_save`` recorded beside *csv_dir*'s bundle.

    Empty when it found none, or when the record cannot be read.
    """
    try:
        payload = json.loads((csv_dir / LEGACY_ENCODINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    found: list[LegacyEncoding] = []
    for item in payload if isinstance(payload, list) else ():
        try:
            entry = LegacyEncoding(**item)
        except TypeError:
            continue
        if (
            isinstance(entry.file, str)
            and (entry.rung is None or isinstance(entry.rung, int))
            and isinstance(entry.unreadable, bool)
        ):
            found.append(entry)
    return tuple(found)


def program_save(
    scr_folder: Path, output: Path | None = None, *, index: bool = False
) -> SaveResult:
    """Decode all Scr*.tmp files into a CSV bundle.

    Writes main.csv for prog_idx 1 and subroutines/{name}.csv for prog_idx 2+.
    Output defaults to *scr_folder* unless *output* is given. Rungs held in a
    legacy encoding are listed in LEGACY_ENCODINGS_FILE beside the CSVs, and a
    save that finds none removes that file. A rung laddercodec cannot read is
    listed there too. Its CSV holds an empty rung in its place (STAND_IN_COMMENT),
    so every other rung keeps CLICK's number. So is a CSV laddercodec cannot read back.

    Raises FileNotFoundError if no Scr*.tmp files found.
    Raises ValueError if no main program (prog_idx=1) found.
    """
    scr_files = sorted(scr_folder.glob("Scr*.tmp"))
    if not scr_files:
        raise FileNotFoundError(f"No Scr*.tmp files found in {scr_folder}")

    dest = output or scr_folder
    dest.mkdir(parents=True, exist_ok=True)

    decoded: list[tuple[Program, list[Warning]]] = []
    infos: list[ProgramInfo] = []
    for scr_path in scr_files:
        data = scr_path.read_bytes()
        prog, legacy = _decode_program_recording_legacy(data)
        decoded.append((prog, legacy))
        infos.append(
            ProgramInfo(
                source=scr_path.name,
                name=prog.name,
                prog_idx=prog.prog_idx,
                rung_count=len(prog.rungs),
            )
        )

    decoded.sort(key=lambda item: item[0].prog_idx)
    infos.sort(key=lambda i: i.prog_idx)

    main_progs = [item for item in decoded if item[0].prog_idx == 1]
    sub_progs = [item for item in decoded if item[0].prog_idx > 1]

    if not main_progs:
        raise ValueError("No main program (prog_idx=1) found")

    main_prog, main_legacy = main_progs[0]
    main_csv = dest / "main.csv"
    main_rungs, unreadable = _replace_unreadable("main.csv", main_prog)
    write_csv(main_csv, main_rungs, index=index)
    legacy_encodings = [_legacy_encoding("main.csv", main_prog, w) for w in main_legacy]
    legacy_encodings.extend(unreadable)
    legacy_encodings.extend(_read_back(main_csv, "main.csv", main_prog.name))

    subroutine_csvs: list[Path] = []
    if sub_progs:
        sub_dir = dest / "subroutines"
        sub_dir.mkdir(exist_ok=True)
        used_stems: set[str] = set()
        for prog, legacy in sub_progs:
            stem = _dedupe_filename_stem(_slugify(prog.name), used_stems)
            csv_path = sub_dir / f"{stem}.csv"
            file = f"subroutines/{stem}.csv"
            rungs, unreadable = _replace_unreadable(file, prog)
            write_csv(csv_path, rungs, index=index)
            subroutine_csvs.append(csv_path)
            legacy_encodings.extend(_legacy_encoding(file, prog, w) for w in legacy)
            legacy_encodings.extend(unreadable)
            legacy_encodings.extend(_read_back(csv_path, file, prog.name))

    write_legacy_encodings(dest, legacy_encodings)
    total_rungs = sum(len(prog.rungs) for prog, _ in decoded)

    return SaveResult(
        main_csv=main_csv,
        subroutine_csvs=subroutine_csvs,
        programs=infos,
        total_rungs=total_rungs,
        legacy_encodings=legacy_encodings,
    )


def prepare_rungs_load(
    rungs: list[Rung],
    *,
    click_v4: bool,
    mdb_path: Path | None = None,
    show_nicknames: bool = False,
    first_rung: int = 1,
) -> PrepareResult:
    """Encode parsed rungs and provision every referenced MDB address.

    Raises NeedsClickV4Error, before touching the MDB, if the rungs need a
    newer CLICK than the target (*click_v4*). Raises UnreadableRungError for a
    stand-in rung, whose paste would replace the rung in CLICK with an empty one.
    Raises ValueError when there are no rungs: there is nothing to paste.
    """
    if not rungs:
        raise ValueError("there are no rungs to copy")
    stand_ins = [number for number, rung in enumerate(rungs, start=first_rung) if is_stand_in(rung)]
    if stand_ins:
        numbers = ", ".join(str(number) for number in stand_ins)
        if len(stand_ins) == 1:
            what = f"Rung {numbers} is an empty rung that stands in for a rung"
            fix = "Paste that rung from your own copy of the program, or fix it in CLICK."
        else:
            what = f"Rungs {numbers} are empty rungs that stand in for rungs"
            fix = "Paste those rungs from your own copy of the program, or fix them in CLICK."
        raise UnreadableRungError(f"{what} ClickNick cannot read from CLICK. {fix}")
    check_click_version(rungs, click_v4=click_v4, first_rung=first_rung)
    payload = (
        encode(rungs, show_nicknames=show_nicknames)
        if len(rungs) > 1
        else encode(rungs[0], show_nicknames=show_nicknames)
    )

    addresses = extract_addresses_from_rungs(rungs)
    addresses_inserted, resolved_mdb_path, mdb_error = _provision_mdb_addresses(
        addresses,
        mdb_path=mdb_path,
    )

    return PrepareResult(
        payload=payload,
        rung_count=len(rungs),
        addresses=addresses,
        addresses_inserted=addresses_inserted,
        mdb_path=resolved_mdb_path,
        mdb_error=mdb_error,
    )


def prepare_csv_load(
    csv_path: Path,
    *,
    click_v4: bool,
    mdb_path: Path | None = None,
    best_effort: bool = False,
    show_nicknames: bool = False,
) -> PrepareResult:
    """Encode a CSV file and provision MDB addresses.

    Does NOT copy to clipboard — the caller handles that so it can choose
    the owner HWND (GUI passes its tracked Click window, CLI auto-detects).
    """
    rungs = read_csv(csv_path, strict=not best_effort)
    return prepare_rungs_load(
        rungs,
        click_v4=click_v4,
        mdb_path=mdb_path,
        show_nicknames=show_nicknames,
    )


def prepare_bin_load(data: bytes, *, click_v4: bool, mdb_path: Path | None = None) -> PrepareResult:
    """Decode a binary payload and provision MDB addresses."""
    rungs = _decode_to_rungs(data)
    check_click_version(rungs, click_v4=click_v4)
    addresses = extract_addresses_from_rungs(rungs)
    addresses_inserted, resolved_mdb_path, mdb_error = _provision_mdb_addresses(
        addresses,
        mdb_path=mdb_path,
    )

    return PrepareResult(
        payload=data,
        rung_count=len(rungs),
        addresses=addresses,
        addresses_inserted=addresses_inserted,
        mdb_path=resolved_mdb_path,
        mdb_error=mdb_error,
    )


def list_csv_folder(folder: Path) -> list[tuple[str, Path]]:
    """List CSV files in a folder for guided paste.

    Excludes ``nicknames.csv``.  ``subroutines/*.csv`` come first (sorted),
    then main-level CSVs such as ``main.csv`` (sorted), so the subroutines
    exist in CLICK before main's Call instructions are pasted.
    """
    items: list[tuple[str, Path]] = []
    sub_dir = folder / "subroutines"
    if sub_dir.is_dir():
        for p in sorted(sub_dir.glob("*.csv")):
            items.append((f"subroutines/{p.name}", p))
    for p in sorted(folder.glob("*.csv")):
        if p.name.lower() == "nicknames.csv":
            continue
        items.append((p.name, p))
    return items


def rung_fingerprint(rung: Rung) -> tuple[tuple[str, ...], ...]:
    """Serialize a rung into laddercodec's canonical CSV rows, for comparison.

    Independent of how the CSV was written (rung index column, header comment).
    """
    from laddercodec.csv.writer import decoded_rung_to_rows

    return tuple(tuple(row) for row in decoded_rung_to_rows(rung))


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
    """Count rungs in a ladder CSV.  Returns 0 when it cannot be opened.

    A CSV laddercodec cannot read is counted by its rows that start a rung.
    """
    try:
        return len(read_csv(csv_path, strict=False))
    except Exception:
        pass
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = csv.reader(handle)
            return sum(1 for row in rows if row and _RUNG_MARKER_RE.fullmatch(row[0].strip()))
    except (OSError, UnicodeDecodeError, csv.Error):
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
