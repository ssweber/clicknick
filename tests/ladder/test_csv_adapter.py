"""Tests for clicknick.ladder.csv_adapter."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clicknick.ladder.csv_adapter import UnsupportedComplexRungError, to_runggrid_if_simple
from clicknick.ladder.csv_contract import CONDITION_COLUMNS, CSV_HEADER
from clicknick.ladder.csv_parser import parse_csv_file


def _write_canonical(path: Path, rows: list[tuple[str, list[str], str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for marker, conditions, af in rows:
            writer.writerow([marker, *conditions, af])


def _blank_conditions() -> list[str]:
    return [""] * len(CONDITION_COLUMNS)


def test_simple_rung_adapts_to_runggrid(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    conditions = _blank_conditions()
    conditions[0] = "immediate(X001)"
    conditions[1] = "-"
    conditions[2] = "~X002"
    conditions[3] = "-"
    _write_canonical(csv_path, [("R", conditions, "out(immediate(Y001))")])

    rung = parse_csv_file(csv_path, syntax="canonical").rungs[0]
    grid = to_runggrid_if_simple(rung)
    assert grid.contact.operand == "X001"
    assert grid.contact.immediate is True
    assert [c.to_csv() for c in grid.series_contacts or []] == ["~X002"]
    assert grid.coil.to_csv() == "out(immediate(Y001))"


def test_edge_contact_rung_adapts_to_runggrid(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    conditions = _blank_conditions()
    conditions[0] = "rise(X001)"
    conditions[1] = "-"
    conditions[2] = "X002"
    _write_canonical(csv_path, [("R", conditions, "out(Y001)")])

    rung = parse_csv_file(csv_path, syntax="canonical").rungs[0]
    grid = to_runggrid_if_simple(rung)
    assert grid.contact.to_csv() == "rise(X001)"
    assert [c.to_csv() for c in grid.series_contacts or []] == ["X002"]
    assert grid.coil.to_csv() == "out(Y001)"


def test_multi_row_rung_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    c1 = _blank_conditions()
    c1[0] = "X001"
    c2 = _blank_conditions()
    c2[0] = "X002"
    _write_canonical(
        csv_path,
        [
            ("R", c1, "out(Y001)"),
            ("", c2, ".reset()"),
        ],
    )
    rung = parse_csv_file(csv_path, syntax="canonical").rungs[0]

    with pytest.raises(UnsupportedComplexRungError) as exc:
        to_runggrid_if_simple(rung)
    assert exc.value.reason == "row_count"


def test_comment_rows_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    conditions = _blank_conditions()
    conditions[0] = "X001"
    _write_canonical(
        csv_path,
        [
            ("#", ["comment", *[""] * (len(CONDITION_COLUMNS) - 1)], ""),
            ("R", conditions, "out(Y001)"),
        ],
    )

    rung = parse_csv_file(csv_path, syntax="canonical").rungs[0]
    with pytest.raises(UnsupportedComplexRungError) as exc:
        to_runggrid_if_simple(rung)
    assert exc.value.reason == "comment_rows"


def test_complex_condition_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    conditions = _blank_conditions()
    conditions[0] = "T"
    _write_canonical(csv_path, [("R", conditions, "out(Y001)")])
    rung = parse_csv_file(csv_path, syntax="canonical").rungs[0]

    with pytest.raises(UnsupportedComplexRungError) as exc:
        to_runggrid_if_simple(rung)
    assert exc.value.reason == "complex_condition"
