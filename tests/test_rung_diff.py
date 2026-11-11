"""rung_diff: how a ladder CSV bundle differs from CLICK's saved program, rung by rung."""

from __future__ import annotations

import json
import typing
from pathlib import Path

from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.services.rung_diff import (
    BundleComparison,
    BundleSources,
    compare_bundle,
    compare_rungs,
    format_group,
    load_bundle,
    paste_groups,
    render_diff,
)

_IT = typing.get_type_hints(Contact)["type"]


def _rungs(*coils: str) -> list[Rung]:
    return [
        Rung(
            logical_rows=1,
            conditions=[["-"] * 31],
            instructions=[Coil(_IT.COIL_OUT, coil)],
            comment=None,
        )
        for coil in coils
    ]


def _commented(*comments: str) -> list[Rung]:
    return [
        Rung(logical_rows=1, conditions=[["-"] * 31], instructions=[""], comment=comment)
        for comment in comments
    ]


def _bundle(root: Path, programs: dict[str, list[Rung]], *, index: bool = False) -> Path:
    """Write {relative name: rungs} like program_save output."""
    for name, rungs in programs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(path, rungs, index=index)
    return root


def _compare(proposed: Path, current: Path) -> BundleComparison:
    return compare_bundle(load_bundle(proposed), current)


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


def _sources(text: str, rung_lines: dict[int, list[int]] | None = None) -> BundleSources:
    return BundleSources({"main.csv": text}, {"main.csv": rung_lines} if rung_lines else {})


# ---------------------------------------------------------------------------
# Loading and comparing a bundle
# ---------------------------------------------------------------------------


def test_reports_changed_unchanged_and_new_programs(tmp_path: Path) -> None:
    # CLICK's copy is written with the rung index column, as the workspace does
    current = _bundle(
        tmp_path / "current",
        {
            "main.csv": _rungs("Y001", "Y002"),
            "subroutines/Fill.csv": _rungs("Y003"),
            "subroutines/Drain.csv": _rungs("Y004"),
        },
        index=True,
    )
    proposed = _bundle(
        tmp_path / "proposed",
        {
            "main.csv": _rungs("Y001", "Y002"),
            "subroutines/fill.csv": _rungs("Y003"),  # names match case-insensitively
            "subroutines/Drain.csv": _rungs("Y004", "Y005"),
            "subroutines/Rinse.csv": _rungs("Y006"),  # not in CLICK yet
        },
    )

    comparison = _compare(proposed, current)

    assert {name: change.differs for name, change in comparison.changes.items()} == {
        "main.csv": False,
        "subroutines/fill.csv": False,
        "subroutines/Drain.csv": True,
        "subroutines/Rinse.csv": True,
    }
    assert comparison.changes["subroutines/Drain.csv"].changed == (2,)
    assert comparison.changes["subroutines/Rinse.csv"].changed == (1,)
    assert comparison.missing_in_click == {"subroutines/Rinse.csv"}


def test_lists_programs_only_in_click(tmp_path: Path) -> None:
    current = _bundle(
        tmp_path / "current",
        {
            "main.csv": _rungs("Y001"),
            "subroutines/Fill.csv": _rungs("Y002"),
            "subroutines/Old Alarm.csv": _rungs("Y003", "Y004"),
        },
    )
    proposed = _bundle(
        tmp_path / "proposed",
        {"main.csv": _rungs("Y001"), "subroutines/FILL.csv": _rungs("Y002")},
    )

    comparison = _compare(proposed, current)

    assert list(comparison.only_in_click) == ["subroutines/Old Alarm.csv"]
    assert comparison.only_in_click["subroutines/Old Alarm.csv"].removed == (1, 2)
    assert "subroutines/Old Alarm.csv" not in comparison.changes


def test_loads_subroutines_before_main(tmp_path: Path) -> None:
    folder = _bundle(
        tmp_path,
        {"main.csv": _rungs("Y001", "Y002"), "subroutines/Fill.csv": _rungs("Y003")},
    )
    (folder / "nicknames.csv").write_text("", encoding="utf-8")

    programs = load_bundle(folder)

    assert [(program.name, program.rung_count) for program in programs] == [
        ("subroutines/Fill.csv", 1),
        ("main.csv", 2),
    ]


def test_folder_without_main_is_not_compared(tmp_path: Path) -> None:
    current = _bundle(
        tmp_path / "current",
        {"main.csv": _rungs("Y001"), "subroutines/Fill.csv": _rungs("Y002")},
    )
    fixtures = _bundle(tmp_path / "fixtures", {"coil.csv": _rungs("Y001")})

    assert _compare(fixtures, current) == BundleComparison()


def test_unreadable_program_is_unknown(tmp_path: Path) -> None:
    current = _bundle(tmp_path / "current", {"main.csv": _rungs("Y001")})
    proposed = _bundle(tmp_path / "proposed", {"main.csv": _rungs("Y001")})
    (proposed / "subroutines").mkdir()
    (proposed / "subroutines" / "Broken.csv").write_text("not,a,ladder\n", encoding="utf-8")

    programs = load_bundle(proposed)
    comparison = compare_bundle(programs, current)

    broken = next(program for program in programs if program.name == "subroutines/Broken.csv")
    assert broken.rungs is None
    assert broken.error
    assert list(comparison.changes) == ["main.csv"]
    assert comparison.missing_in_click == {"subroutines/Broken.csv"}


def test_comparison_outlives_the_folder(tmp_path: Path) -> None:
    # A CLICK save regenerates the workspace and removes csv_output/
    current = _bundle(tmp_path / "current", {"main.csv": _rungs("Y001")})
    proposed = _bundle(tmp_path / "proposed", {"main.csv": _rungs("Y001", "Y002")})
    programs = load_bundle(proposed)
    (proposed / "main.csv").unlink()

    assert compare_bundle(programs, current).changes["main.csv"].changed == (2,)


# ---------------------------------------------------------------------------
# Which rungs differ
# ---------------------------------------------------------------------------


def test_inserted_rung_does_not_select_renumbered_neighbors() -> None:
    change = compare_rungs(_rungs("Y001", "Y002"), _rungs("Y001", "Y009", "Y002"))

    assert change.changed == (2,)
    assert change.removed == ()


def test_two_inserted_rungs_are_both_selected() -> None:
    assert compare_rungs(_rungs("Y001"), _rungs("Y001", "Y002", "Y003")).changed == (2, 3)


def test_modified_rung_is_selected_and_not_counted_as_removed() -> None:
    change = compare_rungs(_rungs("Y001", "Y002"), _rungs("Y001", "Y009"))

    assert change.changed == (2,)
    assert change.removed == ()


def test_dropped_rung_is_removed_with_nothing_to_paste() -> None:
    change = compare_rungs(_rungs("Y001", "Y002", "Y003"), _rungs("Y001", "Y003"))

    assert change.differs
    assert change.changed == ()
    assert change.removed == (2,)


def test_same_rungs_do_not_differ() -> None:
    change = compare_rungs(_rungs("Y001", "Y002"), _rungs("Y001", "Y002"))

    assert not change.differs
    assert change.changed == change.removed == ()


def test_touches_only_selected_rungs_that_need_pasting() -> None:
    change = compare_rungs(_rungs("Y001", "Y002"), _rungs("Y001", "Y009", "Y002"))

    assert change.touches([2, 3])
    assert not change.touches([1, 3])


def test_paste_groups_are_contiguous_runs() -> None:
    assert paste_groups([10, 5, 3, 6, 7, 5]) == [[3], [5, 6, 7], [10]]
    assert paste_groups([]) == []
    assert [format_group(group) for group in ([3], [5, 6, 7])] == ["r3", "r5..7"]


# ---------------------------------------------------------------------------
# Showing the difference as source
# ---------------------------------------------------------------------------


def test_diff_shows_insert_and_neutral_renumber() -> None:
    common = [f"Existing {number}" for number in range(1, 7)]
    before_labels = [*common, "Bottom minimum"]
    after_labels = [*common, "Bottom shift", "Bottom minimum"]

    def _source(labels: list[str]) -> str:
        return _program(
            *(
                (str(number), label, f"copy(DS{number}, DS{number + 100})")
                for number, label in enumerate(labels, start=1)
            )
        )

    change = compare_rungs(_commented(*before_labels), _commented(*after_labels))
    diff = render_diff(
        change,
        "main.csv",
        before=_sources(_source(before_labels)),
        after=_sources(_source(after_labels)),
    )

    assert change.changed == (7,)
    assert "+    comment('Bottom shift')" in diff.text
    assert "+    with rung(C1):  # R7" in diff.text
    assert "~ R7 -> R8  # Bottom minimum" in diff.text
    assert "-    comment('Bottom minimum')" not in diff.text
    assert "+    comment('Bottom minimum')" not in diff.text
    # The block to paste can be found in the text
    assert diff.lines[diff.starts[7]] == "+    comment('Bottom shift')\n"


def test_diff_shows_a_run_of_renumbered_rungs_as_one_line() -> None:
    # One rung inserted near the top moves every rung below it
    change = compare_rungs(_commented("A", "B", "C", "D"), _commented("A", "New", "B", "C", "D"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines[2:] == ("+R2  # New\n", "~ R2..4 -> R3..5\n")


def test_diff_uses_exporter_manifest_for_source_chunk() -> None:
    before = _program(("1", "Existing", "copy(DS1, DS101)"))
    after = _program(
        ("1", "Existing", "copy(DS1, DS101)"),
        ("70", "New rung", "copy(DS2, DS102)"),
    )
    new_marker_line = next(
        index for index, line in enumerate(after.splitlines(), start=1) if line.endswith("# R70")
    )

    change = compare_rungs(_commented("Existing"), _commented("Existing", "New rung"))
    diff = render_diff(
        change,
        "main.csv",
        before=_sources(before),
        after=_sources(after, {1: [], 2: [new_marker_line]}),
    )

    assert change.changed == (2,)
    assert "+    with rung(C1):  # R70" in diff.text
    assert "+R2  # New rung" not in diff.text


def test_diff_renders_multiline_rung_replacing_placeholder() -> None:
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
    marker_line = next(
        index for index, line in enumerate(after.splitlines(), start=1) if "with rung(" in line
    )

    change = compare_rungs(
        _commented(""), _commented("Flag bottom thickness outside tolerance while recording")
    )
    diff = render_diff(
        change,
        "main.csv",
        before=_sources(before, {1: [4]}),
        after=_sources(after, {1: [marker_line]}),
    )

    assert change.changed == (1,)
    assert "-    with rung():  # R9" in diff.text
    assert "+    with rung(" in diff.text
    assert "+            DS201 < DS3," in diff.text
    assert "+        out(C4)" in diff.text
    assert "+R1  # Flag bottom thickness" not in diff.text


def test_diff_lists_rungs_by_number_without_source() -> None:
    change = compare_rungs(_commented("Keep"), _commented("Keep", "Start the pump"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines == (
        "--- CLICK/main.csv\n",
        "+++ proposed/main.csv\n",
        "+R2  # Start the pump\n",
    )


def test_diff_without_source_names_each_rungs_instructions() -> None:
    change = compare_rungs(_rungs("Y001"), _rungs("Y001", "Y002"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines[2:] == ("+R2  out(Y002)\n",)


def test_diff_of_a_new_program_is_all_added_and_of_a_dropped_one_all_removed() -> None:
    source = _program(("1", "First", "copy(DS1, DS2)"), ("2", "Second", "copy(DS3, DS4)"))
    rungs = _commented("First", "Second")

    added = render_diff(
        compare_rungs([], rungs), "main.csv", before=BundleSources(), after=_sources(source)
    )
    removed = render_diff(
        compare_rungs(rungs, []), "main.csv", before=_sources(source), after=BundleSources()
    )

    assert [line[0] for line in added.lines[2:]] == ["+"] * 6
    assert [line[0] for line in removed.lines[2:]] == ["-"] * 6
    assert added.starts == {1: 2, 2: 2}
    assert removed.starts == {}


def test_diff_can_be_limited_to_selected_rungs() -> None:
    change = compare_rungs(_commented("A", "B", "C"), _commented("A1", "B", "C1"))

    diff = render_diff(
        change, "main.csv", before=BundleSources(), after=BundleSources(), selected=[3]
    )

    assert diff.lines[2:] == ("-R3  # C\n", "+R3  # C1\n")
    assert not render_diff(
        change, "main.csv", before=BundleSources(), after=BundleSources(), selected=[2]
    ).lines


def test_no_diff_when_nothing_differs() -> None:
    change = compare_rungs(_commented("A"), _commented("A"))

    assert render_diff(change, "main.csv", before=BundleSources(), after=BundleSources()).text == ""


# ---------------------------------------------------------------------------
# Where the source comes from
# ---------------------------------------------------------------------------


def test_workspace_sources_are_named_by_subroutine_title_and_carry_the_manifest(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "src" / "plc"
    (source_dir / "subroutines").mkdir(parents=True)
    (source_dir / "main.py").write_text("main source\n", encoding="utf-8")
    (source_dir / "tags.py").write_text("tags\n", encoding="utf-8")
    (source_dir / "subroutines" / "__init__.py").write_text("", encoding="utf-8")
    (source_dir / "subroutines" / "fill_tank.py").write_text(
        '@subroutine("Fill Tank")\ndef fill_tank(): ...\n', encoding="utf-8"
    )
    bundle_dir = tmp_path / "csv_output"
    bundle_dir.mkdir()
    manifest = {
        "version": 1,
        "main": [{"rung": 1, "sources": [{"source_line": 7, "end_line": 8}]}],
        "subroutines": {"Fill Tank": [{"rung": 2, "sources": [{"source_line": 3}]}]},
    }
    (bundle_dir / "rung_sources.json").write_text(json.dumps(manifest), encoding="utf-8")

    sources = BundleSources.workspace(source_dir, bundle_dir)

    assert sources.text("main.csv") == "main source\n"
    assert sources.text("subroutines/fill tank.csv").startswith('@subroutine("Fill Tank")')
    assert set(sources.texts) == {"main.csv", "subroutines/fill tank.csv"}
    assert sources.lines("main.csv") == {1: [7]}
    assert sources.lines("subroutines/Fill Tank.csv") == {2: [3]}


def test_workspace_sources_without_a_manifest_still_have_text(tmp_path: Path) -> None:
    source_dir = tmp_path / "src" / "plc"
    source_dir.mkdir(parents=True)
    (source_dir / "main.py").write_text("main source\n", encoding="utf-8")

    sources = BundleSources.workspace(source_dir, tmp_path / "csv_output")

    assert sources.text("main.csv") == "main source\n"
    assert sources.lines("main.csv") == {}


def test_round_trip_generates_numbered_source_for_a_bundle(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "csv", {"main.csv": _rungs("Y001", "Y002")}, index=True)

    sources = BundleSources.round_trip(bundle)
    change = compare_rungs(_rungs("Y001"), _rungs("Y001", "Y002"))
    diff = render_diff(change, "main.csv", before=BundleSources(), after=sources)

    assert diff.lines[2:] == ("+    with rung():  # R2\n", "+        out(Y002)\n")


def test_round_trip_of_something_pyrung_cannot_convert_is_empty(tmp_path: Path) -> None:
    assert BundleSources.round_trip(tmp_path / "missing") == BundleSources()
