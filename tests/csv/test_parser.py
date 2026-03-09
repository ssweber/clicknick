"""Tests for clicknick.csv.parser."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clicknick.csv.ast import (
    AfCall,
    ComparisonCondition,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
)
from clicknick.csv.contract import CONDITION_COLUMNS, CSV_HEADER
from clicknick.csv.parser import parse_csv_file


def _mk_conditions(values: dict[int, str] | None = None) -> list[str]:
    cells = [""] * len(CONDITION_COLUMNS)
    if values:
        for idx, token in values.items():
            cells[idx] = token
    return cells


def _write_canonical(path: Path, rows: list[tuple[str, list[str], str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for marker, conditions, af in rows:
            writer.writerow([marker, *conditions, af])


def test_canonical_parse_and_rung_segmentation(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    _write_canonical(
        csv_path,
        [
            ("R", _mk_conditions({0: "X001", 1: "-"}), "out(Y001)"),
            ("", _mk_conditions({0: "X002", 1: "-"}), ".reset()"),
            ("R", _mk_conditions({0: "~X003"}), "reset(Y002)"),
        ],
    )

    parsed = parse_csv_file(csv_path, syntax="canonical")
    assert len(parsed.rows) == 3
    assert len(parsed.rungs) == 2
    assert len(parsed.rungs[0].rows) == 2
    assert parsed.rungs[0].rows[1].canonical.marker == ""
    assert parsed.rungs[1].rows[0].canonical.marker == "R"


def test_comment_rows_attach_to_following_rung(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    _write_canonical(
        csv_path,
        [
            ("#", ["Initialize the light system.", *[""] * (len(CONDITION_COLUMNS) - 1)], ""),
            ("R", _mk_conditions({0: "X001", 1: "-"}), "out(Y001)"),
            ("#", ["Second rung comment", *[""] * (len(CONDITION_COLUMNS) - 1)], ""),
            ("R", _mk_conditions({0: "X002"}), "reset(Y002)"),
        ],
    )

    parsed = parse_csv_file(csv_path, syntax="canonical")
    assert len(parsed.rows) == 4
    assert len(parsed.rungs) == 2
    assert [row.canonical.comment_text for row in parsed.rungs[0].comment_rows] == [
        "Initialize the light system."
    ]
    assert [row.canonical.comment_text for row in parsed.rungs[1].comment_rows] == [
        "Second rung comment"
    ]


def test_comment_row_without_following_rung_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    _write_canonical(
        csv_path,
        [
            ("#", ["dangling", *[""] * (len(CONDITION_COLUMNS) - 1)], ""),
        ],
    )

    with pytest.raises(ValueError, match="without following 'R' marker"):
        parse_csv_file(csv_path, syntax="canonical")


def test_continuation_before_first_r_rejected_in_strict_mode(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    _write_canonical(
        csv_path,
        [
            ("", _mk_conditions({0: "X001"}), "out(Y001)"),
        ],
    )

    with pytest.raises(ValueError, match="before first 'R' marker"):
        parse_csv_file(csv_path, syntax="canonical", strict=True)


def test_token_typing_and_unknown_fallbacks(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    _write_canonical(
        csv_path,
        [
            (
                "R",
                _mk_conditions(
                    {
                        0: "~immediate(X001)",
                        1: "rise(X002)",
                        2: "DS1!=0",
                        3: "mystery_condition",
                    }
                ),
                "future_call(1,[2,3])",
            ),
        ],
    )

    row = parse_csv_file(csv_path, syntax="canonical").rows[0]

    c0 = row.condition_nodes[0]
    assert isinstance(c0, ContactCondition)
    assert c0.negated is True
    assert c0.immediate is True
    assert c0.operand == "X001"

    c1 = row.condition_nodes[1]
    assert isinstance(c1, EdgeCondition)
    assert c1.kind == "rise"
    assert c1.operand == "X002"

    c2 = row.condition_nodes[2]
    assert isinstance(c2, ComparisonCondition)
    assert c2.op == "!="
    assert c2.left == "DS1"
    assert c2.right == "0"

    c3 = row.condition_nodes[3]
    assert isinstance(c3, GenericCondition)
    assert c3.raw == "mystery_condition"

    af = row.af_node
    assert isinstance(af, AfCall)
    assert af.name == "future_call"
    assert af.known is False
    assert af.args == ("1", "[2,3]")


def test_csv_reader_then_af_parser_decodes_doubled_quotes(tmp_path: Path) -> None:
    csv_path = tmp_path / "main.csv"
    _write_canonical(
        csv_path,
        [
            ("R", _mk_conditions({0: "X001"}), 'call("my""sub")'),
        ],
    )

    row = parse_csv_file(csv_path, syntax="canonical").rows[0]
    af = row.af_node
    assert isinstance(af, AfCall)
    assert af.name == "call"
    assert af.args == ('my"sub',)
