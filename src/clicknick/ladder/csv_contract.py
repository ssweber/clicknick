"""Click Ladder CSV contract constants and validators."""

from __future__ import annotations

MARKER_COLUMN = "marker"
OUTPUT_COLUMN = "AF"


def _excel_column_name(index_1_based: int) -> str:
    value = index_1_based
    chars: list[str] = []
    while value > 0:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


CONDITION_COLUMNS = tuple(_excel_column_name(i) for i in range(1, 32))
CSV_HEADER = (MARKER_COLUMN, *CONDITION_COLUMNS, OUTPUT_COLUMN)
TOTAL_COLUMNS = len(CSV_HEADER)


def is_valid_marker(value: str) -> bool:
    return value in {"R", ""}


def validate_header(fields: list[str]) -> None:
    if tuple(fields) != CSV_HEADER:
        raise ValueError(
            f"Invalid CSV header. Expected: {','.join(CSV_HEADER)}; got: {','.join(fields)}"
        )
