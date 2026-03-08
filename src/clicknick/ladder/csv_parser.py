"""CSV row/file parser for Click Ladder contract rows and shorthand rows."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Literal

from .csv_ast import CanonicalRow, ParsedCsvFileAst, RowAst, RungAst
from .csv_contract import CSV_HEADER, TOTAL_COLUMNS, is_valid_marker, validate_header
from .csv_shorthand import normalize_shorthand_row
from .csv_token_parser import parse_af_token, parse_condition_token


def _detect_file_role(path: Path) -> tuple[Literal["main", "subroutine"], str | None]:
    if path.name == "main.csv":
        return "main", None
    if path.name.startswith("sub_") and path.suffix.lower() == ".csv":
        return "subroutine", path.stem[len("sub_") :]
    return "subroutine", None


def _canonical_row_from_fields(fields: list[str], strict: bool = True) -> CanonicalRow:
    if len(fields) != TOTAL_COLUMNS:
        raise ValueError(f"Expected {TOTAL_COLUMNS} columns; got {len(fields)}")

    marker = fields[0].strip()
    if not is_valid_marker(marker):
        raise ValueError(f"Invalid marker {marker!r}; expected 'R', '#', or blank")

    conditions = tuple(cell.strip() for cell in fields[1:-1])
    af = fields[-1].strip()

    if marker == "#":
        if any(cell for cell in conditions[1:]) or af:
            raise ValueError("Comment rows may only populate column A text")
        return CanonicalRow(marker=marker, conditions=conditions, af="")

    if strict:
        forbidden = {"->", "..."}
        if marker in forbidden or af in forbidden or any(cell in forbidden for cell in conditions):
            raise ValueError("Canonical rows must not contain shorthand macros '->' or '...'")

    return CanonicalRow(marker=marker, conditions=conditions, af=af)


def _row_ast(canonical: CanonicalRow) -> RowAst:
    condition_nodes = tuple(parse_condition_token(token) for token in canonical.conditions)
    af_node = parse_af_token(canonical.af)
    return RowAst(canonical=canonical, condition_nodes=condition_nodes, af_node=af_node)


def _segment_rungs(rows: tuple[RowAst, ...], strict: bool = True) -> tuple[RungAst, ...]:
    rungs: list[RungAst] = []
    current: list[RowAst] = []
    current_comments: list[RowAst] = []
    pending_comments: list[RowAst] = []

    for row in rows:
        if row.canonical.is_comment:
            if current:
                rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))
                current = []
                current_comments = []
            pending_comments.append(row)
            continue

        if row.canonical.marker == "R":
            if current:
                rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))
            current = [row]
            current_comments = pending_comments
            pending_comments = []
            continue

        if not current:
            if strict:
                raise ValueError("Continuation row encountered before first 'R' marker")
            current = [row]
            current_comments = pending_comments
            pending_comments = []
            continue

        current.append(row)

    if pending_comments:
        raise ValueError("Comment row encountered without following 'R' marker")

    if current:
        rungs.append(RungAst(comment_rows=tuple(current_comments), rows=tuple(current)))

    return tuple(rungs)


def _load_canonical_rows(path: Path, strict: bool = True) -> tuple[CanonicalRow, ...]:
    rows: list[CanonicalRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header: list[str] | None = None
        for parsed in reader:
            if not parsed:
                continue
            if header is None:
                header = [cell.strip() for cell in parsed]
                validate_header(header)
                continue
            rows.append(_canonical_row_from_fields(parsed, strict=strict))

    if header is None:
        raise ValueError(f"CSV file {path} is empty; expected header row")
    return tuple(rows)


def _load_shorthand_rows(path: Path, strict: bool = True) -> tuple[CanonicalRow, ...]:
    rows: list[CanonicalRow] = []
    text = path.read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        rows.append(normalize_shorthand_row(raw_line, strict=strict))
    return tuple(rows)


def parse_row(
    row: str,
    syntax: Literal["canonical", "shorthand"] = "canonical",
    strict: bool = True,
) -> CanonicalRow:
    if syntax == "canonical":
        fields = next(csv.reader([row]), [])
        return _canonical_row_from_fields(fields, strict=strict)
    if syntax == "shorthand":
        return normalize_shorthand_row(row, strict=strict)
    raise ValueError(f"Unsupported syntax {syntax!r}")


def parse_csv_file(
    path: Path | str,
    syntax: Literal["auto", "canonical", "shorthand"] = "auto",
    strict: bool = True,
) -> ParsedCsvFileAst:
    path_obj = Path(path)

    selected_syntax = syntax
    if selected_syntax == "auto":
        first_nonempty: list[str] | None = None
        with path_obj.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for parsed in reader:
                if not parsed:
                    continue
                if any(cell.strip() for cell in parsed):
                    first_nonempty = [cell.strip() for cell in parsed]
                    break
        selected_syntax = "canonical" if first_nonempty == list(CSV_HEADER) else "shorthand"

    if selected_syntax == "canonical":
        canonical_rows = _load_canonical_rows(path_obj, strict=strict)
    elif selected_syntax == "shorthand":
        canonical_rows = _load_shorthand_rows(path_obj, strict=strict)
    else:
        raise ValueError(f"Unsupported syntax {selected_syntax!r}")

    rows = tuple(_row_ast(canonical) for canonical in canonical_rows)
    rungs = _segment_rungs(rows, strict=strict)
    role, subroutine_slug = _detect_file_role(path_obj)
    return ParsedCsvFileAst(
        path=path_obj,
        role=role,
        subroutine_slug=subroutine_slug,
        rows=rows,
        rungs=rungs,
    )
