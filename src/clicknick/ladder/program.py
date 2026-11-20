"""Service functions for ladder program operations.

Pure logic — no print(), no input(), no sys.exit().
Returns structured data; callers decide presentation.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from laddercodec import (
    CSV_HEADER,
    Coil,
    CompareContact,
    ConditionToken,
    Contact,
    CsvWriteError,
    InstructionToken,
    Rung,
    Tee,
    Timer,
    Undecoded,
    UndecodedCommentWarning,
    UndecodedStop,
    UnknownCondition,
    UnknownInstruction,
    csv_rows,
    decode,
    decode_program,
    encode,
    find_v4_only,
    read_csv,
    write_csv,
)
from pyclickplc.addresses import format_address_display, get_addr_key, parse_address

from ..utils.click_temp import scr_files
from ..utils.mdb_operations import ensure_addresses_exist
from .codec_warnings import Note, Rule, marker_detail, pass_on_legacy, recording, sort_warnings

if TYPE_CHECKING:
    from laddercodec import Program

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
# The condition columns A to AE. The header row starts with the marker column and ends with AF.
CONDITION_COLUMNS = CSV_HEADER[1:-1]
# How laddercodec ends the message of an error that it raised at a place in a CSV
_CSV_LOCATION_RE = re.compile(r" \(at .*?, line [0-9]+.*\)$")
# How a CsvWriteError message starts: the index of the rung in the list that it was given
_ROWS_INDEX_RE = re.compile(r"^rungs\[[0-9]+\]:? *")

# Written beside a CSV bundle when CLICK holds rungs in a form an older laddercodec wrote
LEGACY_ENCODINGS_FILE = "legacy_encodings.json"
# First line of the comment on the empty rung that program_save writes for a rung that it
# cannot copy as it is. prepare_rungs_load refuses to copy such a rung, so pasting it cannot
# replace the real one.
STAND_IN_COMMENT = (
    "ClickNick cannot copy this rung from CLICK as it is. This empty rung stands in for it."
)
# Workspaces saved before the wording changed start the comment in one of these ways
_OLD_STAND_IN_COMMENTS = (
    "ClickNick cannot read this rung from CLICK. This empty rung stands in for it.",
    "ClickNick could not read this rung from CLICK. This empty rung stands in for it.",
)
# The end of a finding's detail that already tells the user what to do
_SYNTAX_CHECK_FIX = "Run Syntax Check in CLICK, then save the project."


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
    """A rung that CLICK holds in a form an older laddercodec wrote.

    The rung must be pasted again. Either CLICK runs it differently from how its CSV text
    reads, or (if *unreadable* is set) laddercodec cannot read one of its instructions.
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
    """Raised when the rungs use CLICK v4 instructions but the target CLICK is older."""


class UnreadableRungError(ValueError):
    """Raised when decoded rungs hold an instruction that laddercodec cannot read."""


# ---------------------------------------------------------------------------
# CLICK version
# ---------------------------------------------------------------------------

_V4_ONLY_LISTED = 5


def check_click_version(rungs: list[Rung], *, click_v4: bool, first_rung: int = 1) -> None:
    """Raise NeedsClickV4Error if *rungs* need CLICK v4 and the target is older.

    An older CLICK accepts a v4 rung on paste without complaint and silently changes it.
    So this raises before anything reaches the clipboard. *first_rung* numbers the rungs in
    the message.
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
        "These rungs need CLICK v4. The CLICK window runs an older version, and it would "
        "change them on paste without a warning. Paste them into CLICK v4 instead:\n"
        + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# Address extraction
# ---------------------------------------------------------------------------


def _extract_operand_candidates(token: ConditionToken | InstructionToken) -> list[str]:
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

    if isinstance(token, Tee):  # A contact with a wire down from its cell
        token = token.contact
    if isinstance(token, Undecoded):
        # The marker's text is laddercodec's reason. The reason may name an address that no
        # instruction reads.
        return out
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
        _append(token.done)
        _append(token.accumulator)
        _append(token.preset, address_only=True)
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


def extract_addresses_from_bin(data: bytes) -> list[str]:
    """Parse operand addresses from a clipboard-format binary payload."""
    return extract_addresses_from_rungs(decode(data))


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

    Raise ValueError if the CSV holds no rungs, because there is nothing to paste.
    """
    rungs = read_csv(csv_path, strict=not best_effort)
    if not rungs:
        raise ValueError(f"{csv_path.name} holds no rungs")
    if len(rungs) > 1:
        return encode(rungs)
    return encode(rungs[0])


def _instruction_name(raw: bytes) -> str:
    """Return the name of the instruction that an ``UnknownCondition`` holds, e.g. "Compare".

    A Scr*.tmp stores only the name, in ASCII. The clipboard stores the whole instruction,
    which starts with its name in UTF-16, ended by a null.
    """
    end = next((i for i in range(0, len(raw) - 1, 2) if raw[i : i + 2] == b"\0\0"), None)
    try:
        name = raw[:end].decode("utf-16-le") if end is not None else raw.decode("ascii")
    except UnicodeDecodeError:
        return "instruction"
    return name if name.isidentifier() else "instruction"


def _unreadable_instructions(rung: Rung) -> list[str]:
    """Return the name of each instruction of *rung* that laddercodec cannot read, once each."""
    # A Tee is a contact with a wire down from its cell
    cells = [
        cell.contact if isinstance(cell, Tee) else cell for row in rung.conditions for cell in row
    ]
    names = (
        _instruction_name(cell.raw)
        for cell in [*cells, *rung.instructions]
        if isinstance(cell, (UnknownCondition, UnknownInstruction))
    )
    return list(dict.fromkeys(names))


def _unreadable_detail(name: str) -> str:
    return f"ClickNick cannot read this {name}."


def _rung_problems(rung: Rung, *, stop: UndecodedStop = "end") -> list[tuple[str, str]]:
    """Return why the CSV cannot hold *rung* as CLICK holds it, as (instruction, detail) pairs.

    The instruction is empty when the reason is about the whole rung. Return an empty list
    if the CSV holds the rung as it is. These are the reasons:

    - The rung holds an instruction that laddercodec cannot read.
    - The rung is an UNDECODED marker, which laddercodec decodes for a rung it cannot read.
    - ``csv_rows`` refuses to write the rung, or warns about it (``codec_warnings``). It
      warns when it writes a marker in place of the rung.
    - ``csv_rows`` writes the rung as more than one rung. CLICK's Syntax Check would split it.
      A paste, or a save before Syntax Check, keeps the rung whole in CLICK. So the CSV
      would hold more rungs than CLICK, and each rung after it would get the wrong number.
    """
    names = _unreadable_instructions(rung)
    if names:
        return [(name, _unreadable_detail(name)) for name in names]
    for af in rung.instructions:
        if isinstance(af, Undecoded):
            return [("", marker_detail(af))]
    try:
        with recording() as found:
            rows = csv_rows([rung], stop=stop)
    except CsvWriteError as exc:
        reason = _ROWS_INDEX_RE.sub("", str(exc)).rstrip(".")
        return [("", f"laddercodec cannot write this rung to a CSV: {reason}.")]
    noted = pass_on_legacy(sort_warnings(found, writing=True))
    if any(note.reported for note in noted):
        return [("", note.detail) for note in noted if note.reported]
    starts = sum(1 for row in rows if row and row[0] == "R")
    if starts > 1:
        return [
            (
                "",
                f"CLICK's Syntax Check splits this rung into {starts} rungs. {_SYNTAX_CHECK_FIX}",
            )
        ]
    return []


def _decode_clipboard(data: bytes) -> tuple[list[Rung], list[Note]]:
    """Decode clipboard bytes, and return the notes that the user must hear about.

    A legacy encoding stays a warning, because a clipboard copy has no record to list it in.
    """
    with recording() as found:
        rungs = decode(data)
    return rungs, pass_on_legacy(sort_warnings(found))


def _clipboard_problems(rungs: list[Rung], notes: list[Note]) -> list[str]:
    """Return a line for each reason in *notes*, and for each marker rung in *rungs*."""
    lines = []
    for note in notes:
        where = "a copied rung" if note.rung is None else f"copied rung {note.rung + 1}"
        lines.append(f"  {where}: {note.detail}")
    for number, rung in enumerate(rungs, start=1):
        lines.extend(
            f"  copied rung {number}: {marker_detail(af)}"
            for af in rung.instructions
            if isinstance(af, Undecoded)
        )
    return list(dict.fromkeys(lines))


def decode_to_csv(data: bytes, path: Path) -> None:
    """Decode clipboard/program bytes and write canonical CSV.

    Raise UnreadableRungError, before writing anything, if laddercodec warns about a rung
    that the user must hear about (``codec_warnings``), or if the CSV cannot hold a rung as
    CLICK holds it (``_rung_problems``).
    """
    rungs, notes = _decode_clipboard(data)
    found = _clipboard_problems(rungs, notes)
    found.extend(
        f"  copied rung {number}, {name}: {detail}" if name else f"  copied rung {number}: {detail}"
        for number, rung in enumerate(rungs, start=1)
        for name, detail in _rung_problems(rung)
    )
    found = list(dict.fromkeys(found))
    if found:
        raise UnreadableRungError(
            "ClickNick cannot read these rungs, so it wrote no CSV:\n"
            + "\n".join(found)
            + "\nFix them in CLICK and copy them again."
        )
    with recording() as written:
        write_csv(path, rungs, index=True)
    late = [note for note in pass_on_legacy(sort_warnings(written, writing=True)) if note.reported]
    if late:
        path.unlink(missing_ok=True)
        raise UnreadableRungError(
            "ClickNick cannot write these rungs to a CSV, so it wrote none:\n"
            + "\n".join(f"  {note.detail}" for note in late)
        )


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


def _decode_scr(data: bytes) -> tuple[Program, list[Note]]:
    """Decode one Scr*.tmp, with a note for each warning that laddercodec issues."""
    with recording() as found:
        prog = decode_program(data)
    return prog, sort_warnings(found)


def _legacy_encoding(file: str, prog: Program, warning: Warning) -> LegacyEncoding:
    """Return a LegacyEncoding for *warning*, naming its rung the way CLICK and the bundle do."""
    rung = getattr(warning, "rung", None)
    return LegacyEncoding(
        file=file,
        program=str(getattr(warning, "program", None) or prog.name),
        rung=rung + 1 if isinstance(rung, int) else None,
        instruction=str(getattr(warning, "instruction", "")),
        token=str(getattr(warning, "token", "")),
        detail=str(getattr(warning, "detail", "")),
    )


def _program_findings(file: str, prog: Program, notes: Sequence[Note]) -> list[LegacyEncoding]:
    """Return a finding for each legacy encoding that laddercodec warned about in *prog*."""
    return [
        _legacy_encoding(file, prog, note.warning) for note in notes if note.rule is Rule.LEGACY
    ]


def empty_rung(comment: str) -> Rung:
    """Return a one-row rung with no instructions, holding only *comment*."""
    return Rung(
        conditions=[[""] * len(CONDITION_COLUMNS)],
        instructions=[""],
        comment=comment,
    )


def is_empty_rung(rung: Rung) -> bool:
    """Return True if *rung* holds only wires and no instruction, as a stand-in does."""
    return all(isinstance(cell, str) for row in rung.conditions for cell in row) and all(
        token in ("", "NOP") for token in rung.instructions
    )


def _stand_in(rung: Rung, problems: Sequence[tuple[str, str]], *, headline: bool) -> Rung:
    """Return an empty rung that says which rung it replaces, so the rung numbers below it stay.

    *headline* is True if the rung's comment starts with a line that laddercodec wrote.
    """
    names = [name for name, _detail in problems if name]
    if names:
        why = f"ClickNick cannot read its {', '.join(names)}. Paste it again."
    else:
        why = " ".join(detail for _name, detail in problems)
    lines = [STAND_IN_COMMENT, why]
    comment = rung.comment or ""
    if headline:
        # laddercodec's first line repeats the reason, and it may count rungs from 0
        comment = comment.split("\n", 1)[1] if "\n" in comment else ""
    if comment:
        lines += ["", comment]
    return empty_rung("\n".join(lines))


def _replace_unreadable(
    file: str, prog: Program, notes: Sequence[Note], *, stop: UndecodedStop
) -> tuple[list[Rung], list[LegacyEncoding]]:
    """Return the program's rungs, with a stand-in for each rung that the CSV cannot hold.

    Also return a finding for each reason. A reason comes from a note about the rung
    (``Rule.RUNG``), or from ``_rung_problems``. A note about the whole program
    (``Rule.PROGRAM``) leaves the rungs as they are. It gives a finding with no rung number,
    and Review Changes pastes that program whole.
    """
    noted: dict[int, list[tuple[str, str]]] = {}
    comments: set[int] = set()
    found: list[LegacyEncoding] = []
    for note in notes:
        if note.rule is Rule.RUNG and note.rung is not None and 0 <= note.rung < len(prog.rungs):
            noted.setdefault(note.rung, []).append(("", note.detail))
            if isinstance(note.warning, UndecodedCommentWarning):
                comments.add(note.rung)
        elif note.reported:
            found.append(_whole_program(file, prog.name, note.detail))
    rungs: list[Rung] = []
    for index, rung in enumerate(prog.rungs):
        problems = list(dict.fromkeys([*noted.get(index, []), *_rung_problems(rung, stop=stop)]))
        if not problems:
            rungs.append(rung)
            continue
        headline = index in comments or any(isinstance(af, Undecoded) for af in rung.instructions)
        rungs.append(_stand_in(rung, problems, headline=headline))
        found.extend(
            LegacyEncoding(file, prog.name, index + 1, name, "", detail, unreadable=True)
            for name, detail in problems
        )
    return rungs, found


def is_stand_in(rung: Rung) -> bool:
    """Return True if *rung* is the empty rung that program_save wrote for an unreadable rung."""
    first = (rung.comment or "").split("\n", 1)[0]
    return first in (STAND_IN_COMMENT, *_OLD_STAND_IN_COMMENTS) and is_empty_rung(rung)


def unreadable_copy(file: str, program: str, exc: Exception) -> LegacyEncoding:
    """Return a finding that laddercodec cannot read a whole CSV. *exc* says why.

    The finding leaves out laddercodec's location in the CSV. It names a file that the
    build wrote and may since have removed.
    """
    lines = str(exc).strip().splitlines()
    reason = lines[0] if lines else type(exc).__name__
    if getattr(exc, "location", None) is not None:
        reason = _CSV_LOCATION_RE.sub("", reason)
    return _whole_program(file, program, reason)


def _whole_program(file: str, program: str, reason: str) -> LegacyEncoding:
    """Return a finding that the whole program must be pasted again, because of *reason*."""
    detail = f"ClickNick cannot read CLICK's copy of this program. {reason}"
    return LegacyEncoding(file, program, None, "", "", detail, unreadable=True)


def _read_back(path: Path, file: str, program: str) -> list[LegacyEncoding]:
    """Return a finding if laddercodec cannot read the CSV just written at *path*.

    pyrung reads CSVs on its own, so the build would not notice. Review Changes would
    notice, and then it pastes the whole program again.
    """
    try:
        with recording() as found:
            read_csv(path)
    except OSError:
        return []  # Nothing to say about its text
    except Exception as exc:
        return [unreadable_copy(file, program, exc)]
    notes = pass_on_legacy(sort_warnings(found))
    return [_whole_program(file, program, note.detail) for note in notes if note.reported]


def _write_program(
    path: Path,
    file: str,
    prog: Program,
    rungs: list[Rung],
    found: Sequence[LegacyEncoding],
    *,
    index: bool,
    stop: UndecodedStop,
) -> list[LegacyEncoding]:
    """Write *rungs* to *path*, and return a finding if laddercodec warns or cannot read it back.

    ``_replace_unreadable`` already wrote a stand-in for each rung that laddercodec warns
    about. So a warning here is one that it did not see, and the whole program is reported.
    *found* holds the findings for the program so far. If one of them reports the whole
    program, a finding from the read-back would only say so again.
    """
    with recording() as warned:
        write_csv(path, rungs, index=index, stop=stop)
    notes = pass_on_legacy(sort_warnings(warned, writing=True))
    written = [_whole_program(file, prog.name, note.detail) for note in notes if note.reported]
    if written or any(item.rung is None and item.unreadable for item in found):
        return written
    return _read_back(path, file, prog.name)


def write_legacy_encodings(csv_dir: Path, found: Sequence[LegacyEncoding]) -> None:
    """Record *found* beside the bundle in *csv_dir*, or remove the record if *found* is empty."""
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


def stand_in_fix(found: Sequence[LegacyEncoding], *, one: bool) -> str:
    """Return the sentence that tells the user what to do about the stand-in rungs in *found*.

    Return an empty string if the detail of every finding says what to do. *one* is True
    if *found* is about one rung.
    """
    told = sum(item.detail.endswith(_SYNTAX_CHECK_FIX) for item in found)
    if told == len(found):
        return ""
    if told:
        return (
            "Where a line does not say what to do, paste the rung again from your own copy "
            "of the program, or fix it in CLICK."
        )
    if one:
        return "Paste it again from your own copy of the program, or fix it in CLICK."
    return "Paste them again from your own copy of the program, or fix them in CLICK."


def describe_legacy_encoding(item: LegacyEncoding, *, program: bool = True) -> str:
    """Say which rung holds a legacy encoding and what CLICK runs instead.

    ``Main Program rung 12, Math H70000: it is stored as 16-bit and CLICK runs
    it as 4464.`` Without *program*, the line starts at ``rung 12``.
    """
    what = " ".join(part for part in (item.instruction, item.token) if part)
    if item.rung is None and not what:
        # A finding about the whole copy, such as a CSV Review Changes cannot read
        return f"{item.program or item.file}: {item.detail}" if program else item.detail
    where = "an unknown rung" if item.rung is None else f"rung {item.rung}"
    if program:
        where = f"{item.program or item.file} {where}"
    return f"{where}, {what}: {item.detail}" if what else f"{where}: {item.detail}"


def read_legacy_encodings(csv_dir: Path) -> tuple[LegacyEncoding, ...]:
    """Read the legacy encodings that ``program_save`` recorded beside *csv_dir*'s bundle.

    Return an empty tuple if it found none, or if the record cannot be read.
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
    programs_found = scr_files(scr_folder)
    if not programs_found:
        raise FileNotFoundError(f"No Scr*.tmp files found in {scr_folder}")

    dest = output or scr_folder
    dest.mkdir(parents=True, exist_ok=True)

    decoded: list[tuple[Program, list[Note]]] = []
    infos: list[ProgramInfo] = []
    for scr_path in programs_found:
        data = scr_path.read_bytes()
        prog, notes = _decode_scr(data)
        decoded.append((prog, notes))
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
        raise ValueError(f"None of the Scr*.tmp files in {scr_folder} holds the main program.")

    main_prog, main_notes = main_progs[0]
    main_csv = dest / "main.csv"
    legacy_encodings = _program_findings("main.csv", main_prog, main_notes)
    main_rungs, unreadable = _replace_unreadable("main.csv", main_prog, main_notes, stop="end")
    legacy_encodings.extend(unreadable)
    legacy_encodings.extend(
        _write_program(
            main_csv, "main.csv", main_prog, main_rungs, unreadable, index=index, stop="end"
        )
    )

    subroutine_csvs: list[Path] = []
    if sub_progs:
        sub_dir = dest / "subroutines"
        sub_dir.mkdir(exist_ok=True)
        used_stems: set[str] = set()
        for prog, notes in sub_progs:
            stem = _dedupe_filename_stem(_slugify(prog.name), used_stems)
            csv_path = sub_dir / f"{stem}.csv"
            file = f"subroutines/{stem}.csv"
            legacy_encodings.extend(_program_findings(file, prog, notes))
            # In a subroutine, an UNDECODED marker returns to the caller
            rungs, unreadable = _replace_unreadable(file, prog, notes, stop="return")
            legacy_encodings.extend(unreadable)
            legacy_encodings.extend(
                _write_program(csv_path, file, prog, rungs, unreadable, index=index, stop="return")
            )
            subroutine_csvs.append(csv_path)

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

    Raise NeedsClickV4Error, before touching the MDB, if the rungs need a newer CLICK than
    the target (*click_v4*). Raise UnreadableRungError for a stand-in rung, because pasting
    it would replace the rung in CLICK with an empty one. Also raise it for laddercodec's
    UNDECODED marker rung, because CLICK cannot hold the marker. Raise ValueError if there
    are no rungs, because there is nothing to paste.
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
    marked = [
        (number, af)
        for number, rung in enumerate(rungs, start=first_rung)
        for af in rung.instructions
        if isinstance(af, Undecoded)
    ]
    if marked:
        numbers = ", ".join(str(number) for number, _af in marked)
        if len(marked) == 1:
            head = f"Rung {numbers} is an UNDECODED marker. CLICK cannot hold a marker."
        else:
            head = f"Rungs {numbers} are UNDECODED markers. CLICK cannot hold a marker."
        lines = [f"  rung {number}: {marker_detail(af)}" for number, af in marked]
        raise UnreadableRungError(
            "\n".join(
                [
                    head,
                    *lines,
                    "Put the rung's logic in place of its marker, or remove the marker.",
                ]
            )
        )
    check_click_version(rungs, click_v4=click_v4, first_rung=first_rung)
    with recording() as found:
        payload = (
            encode(rungs, show_nicknames=show_nicknames)
            if len(rungs) > 1
            else encode(rungs[0], show_nicknames=show_nicknames)
        )
    notes = [note for note in pass_on_legacy(sort_warnings(found)) if note.reported]
    if notes:
        lines = [
            f"  rung {note.rung + first_rung}: {note.detail}"
            if note.rung is not None
            else f"  {note.detail}"
            for note in notes
        ]
        raise UnreadableRungError(
            "ClickNick cannot copy these rungs into CLICK as they are:\n" + "\n".join(lines)
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
    """Decode a binary payload and provision MDB addresses.

    Raise ValueError if laddercodec warns about a rung that the user must hear about
    (``codec_warnings``). The decoder may have put a placeholder in place of the rung, so
    the payload's operands are not known for sure. Then ClickNick cannot add them to the MDB.
    """
    rungs, notes = _decode_clipboard(data)
    found = _clipboard_problems(rungs, notes)
    if found:
        raise ValueError(found[0].strip().removeprefix("copied "))
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

    The rows do not depend on how the CSV was written (rung index column, header comment).
    """
    return tuple(tuple(row) for row in csv_rows([rung]))


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
    """Count the rungs in a ladder CSV, or return 0 if it cannot be opened.

    For a CSV that laddercodec cannot read, count the rows that start a rung.
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
