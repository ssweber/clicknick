"""Tests for semantic rung selection in the live preview."""

import json
from pathlib import Path

from laddercodec import Rung, write_csv

from clicknick.live.rung_commands import _canonical_diff, _changed_after_rungs


def _program(*rungs: tuple[str, str, str]) -> str:
    lines = ["from pyrung import Program, comment, copy, rung", "", "with Program() as logic:"]
    for number, label, instruction in rungs:
        lines.extend(
            [
                f"    comment({label!r})",
                f"    with rung(C1):  # R{number}",
                f"        {instruction}",
                "",
            ]
        )
    return "\n".join(lines)


def test_inserted_rung_does_not_select_renumbered_neighbors():
    before = _program(
        ("1", "Top minimum", "copy(DS2, DS101)"),
        ("2", "Bottom minimum", "copy(DS2, DS201)"),
    )
    after = _program(
        ("1", "Top minimum", "copy(DS2, DS101)"),
        ("2", "Bottom shift", "copy(DS201, DS202)"),
        ("3", "Bottom minimum", "copy(DS2, DS201)"),
    )

    assert _changed_after_rungs(before, after) == [2]


def test_two_inserted_rungs_are_both_selected():
    before = _program(("1", "Top minimum", "copy(DS2, DS101)"))
    after = _program(
        ("1", "Top minimum", "copy(DS2, DS101)"),
        ("2", "Bottom shift", "copy(DS201, DS202)"),
        ("3", "Bottom minimum", "copy(DS2, DS201)"),
    )

    assert _changed_after_rungs(before, after) == [2, 3]


def test_modified_rung_is_selected():
    before = _program(("1", "Minimum", "copy(DS2, DS101)"))
    after = _program(("1", "Minimum", "copy(DS3, DS101)"))

    assert _changed_after_rungs(before, after) == [1]


def test_marker_only_renumbering_is_not_a_change():
    before = _program(("7", "Minimum", "copy(DS2, DS201)"))
    after = _program(("8", "Minimum", "copy(DS2, DS201)"))

    assert _changed_after_rungs(before, after) == []


def _write_ladder(path: Path, labels: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(
        path,
        [
            Rung(
                logical_rows=1,
                conditions=[["-"] * 31],
                instructions=[""],
                comment=label,
            )
            for label in labels
        ],
        index=True,
    )


def test_canonical_diff_shows_insert_and_neutral_renumber(tmp_path: Path):
    common = [f"Existing {number}" for number in range(1, 7)]
    before_labels = [*common, "Bottom minimum"]
    after_labels = [*common, "Bottom shift", "Bottom minimum"]
    before = _program(
        *(
            (str(number), label, f"copy(DS{number}, DS{number + 100})")
            for number, label in enumerate(before_labels, start=1)
        )
    )
    after = _program(
        *(
            (str(number), label, f"copy(DS{number}, DS{number + 100})")
            for number, label in enumerate(after_labels, start=1)
        )
    )
    _write_ladder(tmp_path / "csv" / "main.csv", before_labels)
    _write_ladder(tmp_path / "csv_output" / "main.csv", after_labels)

    result = _canonical_diff(
        tmp_path,
        stem="main",
        csv_stem="main",
        before=before,
        after=after,
    )

    assert result is not None
    diff_lines, changed = result
    diff = "".join(diff_lines)
    assert changed == [7]
    assert "+    comment('Bottom shift')" in diff
    assert "+    with rung(C1):  # R7" in diff
    assert "~ R7 -> R8  # Bottom minimum" in diff
    assert "-    comment('Bottom minimum')" not in diff
    assert "+    comment('Bottom minimum')" not in diff


def test_canonical_diff_uses_exporter_manifest_for_source_chunk(tmp_path: Path):
    before = _program(("1", "Existing", "copy(DS1, DS101)"))
    after = _program(
        ("1", "Existing", "copy(DS1, DS101)"),
        ("70", "New rung", "copy(DS2, DS102)"),
    )
    before_labels = ["Existing"]
    after_labels = ["Existing", "New rung"]
    _write_ladder(tmp_path / "csv" / "main.csv", before_labels)
    _write_ladder(tmp_path / "csv_output" / "main.csv", after_labels)
    new_marker_line = next(
        index for index, line in enumerate(after.splitlines(), start=1) if line.endswith("# R70")
    )
    manifest = {
        "version": 1,
        "main": [
            {"rung": 1, "sources": []},
            {
                "rung": 2,
                "sources": [
                    {
                        "source_file": str(tmp_path / "src" / "plc" / "main.py"),
                        "source_line": new_marker_line,
                        "end_line": new_marker_line + 1,
                    }
                ],
            },
        ],
        "subroutines": {},
    }
    (tmp_path / "csv_output" / "rung_sources.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = _canonical_diff(
        tmp_path,
        stem="main",
        csv_stem="main",
        before=before,
        after=after,
    )

    assert result is not None
    diff_lines, changed = result
    diff = "".join(diff_lines)
    assert changed == [2]
    assert "+    with rung(C1):  # R70" in diff
    assert "+R2  # New rung" not in diff


def test_canonical_diff_renders_multiline_rung_replacing_placeholder(tmp_path: Path):
    before = """\
from pyrung import Program, rung

with Program() as logic:
    with rung():  # R9
        pass
"""
    after = """\
from pyrung import Or, Program, comment, out, rung

with Program() as logic:
    comment('Flag bottom thickness outside tolerance while recording')
    with rung(
        C2,
        Or(
            DS201 < DS3,
            DS201 > DS4,
        ),
    ):  # R9
        out(C4)
"""
    _write_ladder(tmp_path / "csv" / "main.csv", [""])
    _write_ladder(
        tmp_path / "csv_output" / "main.csv",
        ["Flag bottom thickness outside tolerance while recording"],
    )
    marker_line = next(
        index for index, line in enumerate(after.splitlines(), start=1) if "with rung(" in line
    )
    manifest = {
        "version": 1,
        "main": [
            {
                "rung": 1,
                "sources": [
                    {
                        "source_file": str(tmp_path / "src" / "plc" / "main.py"),
                        "source_line": marker_line,
                        "end_line": marker_line + 7,
                    }
                ],
            }
        ],
        "subroutines": {},
    }
    (tmp_path / "csv_output" / "rung_sources.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    result = _canonical_diff(
        tmp_path,
        stem="main",
        csv_stem="main",
        before=before,
        after=after,
    )

    assert result is not None
    diff_lines, changed = result
    diff = "".join(diff_lines)
    assert changed == [1]
    assert "+    with rung(" in diff
    assert "+            DS201 < DS3," in diff
    assert "+        out(C4)" in diff
    assert "+R1  # Flag bottom thickness" not in diff
