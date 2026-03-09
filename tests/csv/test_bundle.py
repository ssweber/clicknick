"""Tests for clicknick.csv.bundle."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clicknick.csv.bundle import parse_bundle
from clicknick.csv.contract import CONDITION_COLUMNS, CSV_HEADER


def _write_one_row_file(path: Path, marker: str = "R", af: str = "out(Y001)") -> None:
    conditions = [""] * len(CONDITION_COLUMNS)
    conditions[0] = "X001"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerow([marker, *conditions, af])


def test_main_csv_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing required main.csv"):
        parse_bundle(tmp_path)


def test_subroutines_parsed_in_lexical_order(tmp_path: Path) -> None:
    _write_one_row_file(tmp_path / "main.csv")
    _write_one_row_file(tmp_path / "sub_zeta.csv", af="return()")
    _write_one_row_file(tmp_path / "sub_alpha.csv", af="return()")

    bundle = parse_bundle(tmp_path)
    assert bundle.main.path.name == "main.csv"
    assert [sub.path.name for sub in bundle.subroutines] == ["sub_alpha.csv", "sub_zeta.csv"]
    assert [sub.subroutine_slug for sub in bundle.subroutines] == ["alpha", "zeta"]
