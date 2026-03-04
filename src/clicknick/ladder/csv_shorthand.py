"""Strict shorthand normalization for Click Ladder CSV rows."""

from __future__ import annotations

import csv
from io import StringIO

from .csv_ast import CanonicalRow
from .csv_contract import CONDITION_COLUMNS, is_valid_marker

_MACRO_WIRE_FILL = "->"
_MACRO_BLANK_FILL = "..."


def _parse_csv_row(row: str) -> list[str]:
    reader = csv.reader(StringIO(row))
    return next(reader, [])


def normalize_shorthand_row(row: str, strict: bool = True) -> CanonicalRow:
    fields = _parse_csv_row(row)
    if not fields:
        raise ValueError("Empty shorthand row")

    marker = fields[0].strip()
    if not is_valid_marker(marker):
        raise ValueError(f"Invalid marker {marker!r}; expected 'R' or blank")

    if len(fields) < 2:
        raise ValueError("Shorthand row is missing ':' separator and AF field")

    colon_positions = [idx for idx, value in enumerate(fields) if value.strip() == ":"]
    if len(colon_positions) != 1:
        raise ValueError("Shorthand row must contain exactly one ':' separator")

    colon_idx = colon_positions[0]
    if colon_idx < 1:
        raise ValueError("':' separator must appear after marker and conditions")
    if colon_idx != len(fields) - 2:
        raise ValueError("':' separator must be followed by exactly one AF field")

    af_raw = fields[-1].strip()
    if marker in {_MACRO_WIRE_FILL, _MACRO_BLANK_FILL} or af_raw == _MACRO_WIRE_FILL:
        raise ValueError("Macros are only allowed in condition cells A..AE")
    if af_raw == _MACRO_BLANK_FILL:
        af_raw = ""

    condition_tokens = [token.strip() for token in fields[1:colon_idx]]
    macro_positions = [
        (idx, token)
        for idx, token in enumerate(condition_tokens)
        if token in {_MACRO_WIRE_FILL, _MACRO_BLANK_FILL}
    ]
    if len(macro_positions) > 1:
        raise ValueError("At most one shorthand macro (-> or ...) is allowed in a row")

    conditions: list[str]
    if macro_positions:
        macro_idx, macro_token = macro_positions[0]
        if macro_idx != len(condition_tokens) - 1:
            raise ValueError("Shorthand macro must be the last explicit condition token")
        prefix = condition_tokens[:macro_idx]
        if len(prefix) > len(CONDITION_COLUMNS):
            raise ValueError("Too many explicit condition cells before shorthand macro")

        fill_value = "-" if macro_token == _MACRO_WIRE_FILL else ""
        conditions = prefix + [fill_value] * (len(CONDITION_COLUMNS) - len(prefix))
    else:
        if len(condition_tokens) > len(CONDITION_COLUMNS):
            raise ValueError("Too many explicit condition cells in shorthand row")
        conditions = condition_tokens + [""] * (len(CONDITION_COLUMNS) - len(condition_tokens))

    if strict and len(conditions) != len(CONDITION_COLUMNS):
        raise ValueError("Internal normalization error: condition count is not 31")

    return CanonicalRow(marker=marker, conditions=tuple(conditions), af=af_raw)
