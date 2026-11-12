"""rung_diff: how a ladder CSV bundle differs from CLICK's saved program, rung by rung."""

from __future__ import annotations

import json
import typing
from pathlib import Path

from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.ladder.program import LegacyEncoding, write_legacy_encodings
from clicknick.services.rung_diff import (
    BundleComparison,
    BundleSources,
    Gap,
    PasteStep,
    RenderedDiff,
    carry_skipped,
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


def _legacy(file: str, rung: int | None) -> LegacyEncoding:
    detail = "it is stored as 16-bit and CLICK runs it as 4464."
    return LegacyEncoding(file, "P", rung, "Math", "H70000", detail)


def test_rung_click_holds_in_a_legacy_encoding_differs_though_its_text_matches(
    tmp_path: Path,
) -> None:
    programs = {"main.csv": _rungs("Y001", "Y002", "Y003"), "subroutines/Fill.csv": _rungs("Y004")}
    current = _bundle(tmp_path / "current", programs, index=True)
    proposed = _bundle(tmp_path / "proposed", programs)
    # Files are matched ignoring case, like program names
    write_legacy_encodings(current, [_legacy("main.csv", 2), _legacy("subroutines/fill.csv", 1)])

    comparison = _compare(proposed, current)

    main = comparison.changes["main.csv"]
    assert main.differs
    assert main.changed == (2,)
    assert main.removed == ()
    assert main.steps() == (PasteStep((2,), over=2),)
    assert main.legacy == (_legacy("main.csv", 2),)
    assert comparison.changes["subroutines/Fill.csv"].changed == (1,)

    # Once CLICK saves a clean copy, the record is gone and nothing differs
    write_legacy_encodings(current, [])
    assert not any(change.differs for change in _compare(proposed, current).changes.values())


def test_legacy_encoding_without_a_rung_number_stands_for_the_whole_program() -> None:
    rungs = _rungs("Y001", "Y002")

    change = compare_rungs(rungs, rungs, [_legacy("main.csv", None)])

    assert change.changed == (1, 2)
    # Pasting both over rung 1 leaves CLICK's old rung 2 below them
    assert change.steps() == (PasteStep((1, 2), over=1), PasteStep(delete=(3,)))


def test_legacy_rung_past_the_end_is_ignored() -> None:
    rungs = _rungs("Y001")

    change = compare_rungs(rungs, rungs, [_legacy("main.csv", 5)])

    assert not change.differs
    assert change.legacy == ()


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


def test_steps_number_rungs_as_click_shows_them_working_down() -> None:
    # CLICK:    A  B  C  D  E  F
    # proposed: A  N1 N2 B  X  E  (C, D -> X; F dropped)
    change = compare_rungs(
        _commented("A", "B", "C", "D", "E", "F"), _commented("A", "N1", "N2", "B", "X", "E")
    )

    assert change.steps() == (
        # New rungs 2..3 go in above CLICK's rung 2 (B)
        PasteStep(rungs=(2, 3), above=2, block=0),
        # With those in, C stands at 5: rung 5 is pasted over it, leaving D at 6
        PasteStep(rungs=(5,), over=5, block=1),
        PasteStep(delete=(6,), block=1),
        # With D gone, F stands at 7
        PasteStep(delete=(7,), block=2),
    )


def test_new_rungs_at_the_bottom_have_no_rung_to_go_above() -> None:
    assert compare_rungs(_commented("A"), _commented("A", "B")).steps() == (
        PasteStep(rungs=(2,), above=None, block=0),
    )
    assert compare_rungs([], _commented("A")).steps() == (
        PasteStep(rungs=(1,), above=None, block=0),
    )


def test_same_rungs_need_no_steps() -> None:
    assert compare_rungs(_commented("A", "B"), _commented("A", "B")).steps() == ()


# ---------------------------------------------------------------------------
# Taking some differences and skipping others
# ---------------------------------------------------------------------------

# CLICK:    A  B  C  D  E  F
# proposed: A  N1 N2 B  X  E  (N1, N2 new; C, D -> X; F dropped)
_CLICK_LABELS = ("A", "B", "C", "D", "E", "F")
_PROPOSED_LABELS = ("A", "N1", "N2", "B", "X", "E")


def _three_differences():
    return compare_rungs(_commented(*_CLICK_LABELS), _commented(*_PROPOSED_LABELS))


def test_skipped_difference_is_left_as_click_has_it_and_rungs_below_count_it() -> None:
    change = _three_differences()
    new_rungs, _replaced, _dropped = change.differences

    assert change.steps(skipped={new_rungs}) == (
        # Without N1, N2, C still stands at 3
        PasteStep(rungs=(5,), over=3, block=1),
        PasteStep(delete=(4,), block=1),
        # A B X E F: F stands at 5
        PasteStep(delete=(5,), block=2),
    )


def test_skipping_a_difference_leaves_the_ones_above_it_alone() -> None:
    change = _three_differences()
    _new_rungs, replaced, _dropped = change.differences

    assert change.steps(skipped={replaced}) == (
        PasteStep(rungs=(2, 3), above=2, block=0),
        # A N1 N2 B C D E F: F stands at 8
        PasteStep(delete=(8,), block=2),
    )


def test_pasted_difference_has_no_steps_and_its_rungs_count_as_in_click() -> None:
    change = _three_differences()
    new_rungs, _replaced, _dropped = change.differences

    assert change.steps(pasted={new_rungs}) == change.steps()[1:]


def test_a_difference_pasted_out_of_order_counts_only_for_the_rungs_below_it() -> None:
    change = _three_differences()
    new_rungs, replaced, dropped = change.differences

    # X was pasted before N1, N2: N1, N2 still go above B, and F stands at 7
    assert change.steps(pasted={replaced}) == (
        PasteStep(rungs=(2, 3), above=2, block=0),
        PasteStep(delete=(7,), block=2),
    )
    assert change.steps(skipped={new_rungs, dropped}, pasted={replaced}) == ()


def test_new_rung_and_removal_each_skipped_in_turn() -> None:
    # CLICK: A B C; proposed: A N B (N new; C dropped)
    change = compare_rungs(_commented("A", "B", "C"), _commented("A", "N", "B"))
    new_rung, dropped = change.differences

    assert change.steps(skipped={dropped}) == (PasteStep(rungs=(2,), above=2, block=0),)
    assert change.steps(skipped={new_rung}) == (PasteStep(delete=(3,), block=1),)


def test_same_change_in_two_places_is_two_differences() -> None:
    change = compare_rungs(_commented("A", "X", "B", "X"), _commented("A", "Y", "B", "Y"))
    first, second = change.differences

    assert first != second
    assert (first.occurrence, second.occurrence) == (0, 1)
    assert change.steps(skipped={first}) == (PasteStep(rungs=(4,), over=4, block=1),)


def test_differences_holding_rungs_asked_for_by_number() -> None:
    change = _three_differences()
    new_rungs, replaced, _dropped = change.differences

    assert change.blocks_holding([3]) == {new_rungs}
    assert change.blocks_holding([1, 5, 6]) == {replaced}
    # A removal pastes nothing, so no rung number holds it
    assert change.blocks_holding([1, 4, 6]) == frozenset()


def test_merged_program_keeps_click_rungs_where_skipped() -> None:
    change = _three_differences()
    new_rungs, _replaced, dropped = change.differences

    merged = change.merged(skipped={new_rungs, dropped})

    assert [rung.comment for rung in merged] == ["A", "B", "X", "E", "F"]
    assert change.merged() == change.after


def test_skips_outlive_a_click_save_of_the_differences_taken() -> None:
    old = _three_differences()
    new_rungs, replaced, dropped = old.differences
    # CLICK pasted and saved the new rungs, skipping the rest
    new = compare_rungs(_commented("A", "N1", "N2", *_CLICK_LABELS[1:]), old.after)

    assert new.differences == (replaced, dropped)
    assert carry_skipped({replaced, dropped}, old, new) == {replaced, dropped}
    assert carry_skipped({replaced}, old, new) == {replaced}


def test_skip_of_a_repeated_change_outlives_pasting_the_other() -> None:
    old = compare_rungs(_commented("A", "X", "B", "X"), _commented("A", "Y", "B", "Y"))
    first, second = old.differences
    # The first was pasted and CLICK saved: what is left is the skipped one
    new = compare_rungs(_commented("A", "Y", "B", "X"), old.after)

    assert carry_skipped({second}, old, new) == set(new.differences)
    # Nothing saved yet: each keeps its own choice
    assert carry_skipped({second}, old, old) == {second}
    assert carry_skipped({first}, old, old) == {first}


def test_diff_records_where_each_difference_starts() -> None:
    change = compare_rungs(_commented("A", "B", "C", "D"), _commented("A1", "B", "C"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines[2:] == ("-R1  # A\n", "+R1  # A1\n", " R2  # B\n", " R3  # C\n", "-R4  # D\n")
    # The second difference starts with the unchanged rung shown above it
    assert diff.blocks == (2, 5)
    assert [step.block for step in change.steps()] == [0, 1]


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
    # The rung below is shown unchanged, as proposed: moved down one
    assert "     comment('Bottom minimum')\n     with rung(C1):  # R8" in diff.text
    assert "-    comment('Bottom minimum')" not in diff.text
    assert "+    comment('Bottom minimum')" not in diff.text
    # The block to paste can be found in the text, after the unchanged rung above it
    assert diff.lines[diff.starts[7]] == "     comment('Existing 6')\n"
    assert diff.lines[diff.starts[7] + 3] == "+    comment('Bottom shift')\n"


def test_unchanged_rungs_beyond_the_one_beside_a_difference_are_a_separator() -> None:
    # One rung inserted near the top moves every rung below it
    change = compare_rungs(_commented("A", "B", "C", "D"), _commented("A", "New", "B", "C", "D"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines[2:] == (
        " R1  # A\n",
        "+R2  # New\n",
        " R3  # B\n",
        "@@ R3..4 unchanged, now R4..5 @@\n",
    )
    assert diff.gaps == {5: Gap(opcode=2, shown=(1, 0), hidden=2, follows=True, precedes=False)}
    assert diff.gaps[5].arrows == "↓"


def test_a_separator_between_differences_expands_from_either_end() -> None:
    labels = [f"Same {number}" for number in range(1, 11)]
    change = compare_rungs(_commented("A", *labels, "B"), _commented("A1", *labels, "B1"))

    def _render(shown: dict[int, tuple[int, int]] | None = None) -> RenderedDiff:
        return render_diff(
            change, "main.csv", before=BundleSources(), after=BundleSources(), shown=shown
        )

    diff = _render()
    ((index, gap),) = diff.gaps.items()
    assert diff.lines[index] == "@@ R3..10 unchanged @@\n"
    assert (gap.shown, gap.hidden, gap.arrows) == ((1, 1), 8, "↓↑")

    # Down shows more below the difference above, up more above the one below
    assert gap.expand("↓") == (4, 1)
    assert gap.expand("↑") == (1, 4)
    diff = _render({gap.opcode: gap.expand("↑")})
    ((index, gap),) = diff.gaps.items()
    assert diff.lines[index] == "@@ R3..7 unchanged @@\n"
    assert diff.lines[index + 1 : index + 5] == tuple(
        f" R{number}  # Same {number - 1}\n" for number in range(8, 12)
    )

    # Once few are left, one arrow shows them all
    diff = _render({gap.opcode: (3, 4)})
    ((index, gap),) = diff.gaps.items()
    assert (gap.hidden, gap.arrows) == (3, "↕")
    assert not _render({gap.opcode: gap.expand("↕")}).gaps


def test_a_separator_above_the_first_difference_expands_up() -> None:
    labels = [f"Same {number}" for number in range(1, 6)]
    change = compare_rungs(_commented(*labels, "A"), _commented(*labels, "A1"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines[2:4] == ("@@ R1..4 unchanged @@\n", " R5  # Same 5\n")
    assert diff.gaps[2].arrows == "↑"
    assert diff.blocks == (3,)


def test_selected_rungs_are_shown_without_unchanged_rungs() -> None:
    change = compare_rungs(_commented("A", "B", "C"), _commented("A", "B1", "C"))

    diff = render_diff(
        change, "main.csv", before=BundleSources(), after=BundleSources(), selected=[2]
    )

    assert diff.lines[2:] == ("-R2  # B\n", "+R2  # B1\n")
    assert not diff.gaps


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


def _marked(diff: RenderedDiff, index: int) -> str:
    """Line *index* of *diff* with its changed words in brackets."""
    line = diff.lines[index].rstrip("\n")
    for start, end in reversed(diff.words.get(index, ())):
        line = f"{line[:start]}[{line[start:end]}]{line[end:]}"
    return line


def test_a_changed_rung_shows_only_its_changed_lines_and_words() -> None:
    before = _program(("1", "Fill tank when level low", "copy(DS1, DS101)"))
    after = _program(("1", "Fill tank when level is low", "copy(DS1, DS101)"))

    change = compare_rungs(
        _commented("Fill tank when level low"), _commented("Fill tank when level is low")
    )
    diff = render_diff(change, "main.csv", before=_sources(before), after=_sources(after))

    assert [_marked(diff, index) for index in range(2, len(diff.lines))] == [
        "-    comment('Fill tank when level low')",
        "+    comment('Fill tank when level [is ]low')",
        "     with rung(C1):  # R1",
        "         copy(DS1, DS101)",
    ]


def test_a_rung_marker_alone_does_not_make_a_line_differ() -> None:
    before = _program(("9", "Pump", "copy(DS1, DS101)"))
    after = _program(("10", "Pump", "copy(DS2, DS101)"))

    change = compare_rungs(_rungs("Y001"), _rungs("Y002"))
    diff = render_diff(
        change, "main.csv", before=_sources(before, {1: [5]}), after=_sources(after, {1: [5]})
    )

    assert [_marked(diff, index) for index in range(2, len(diff.lines))] == [
        "     comment('Pump')",
        "     with rung(C1):  # R10",
        "-        copy([DS1], DS101)",
        "+        copy([DS2], DS101)",
    ]


def test_rungs_whose_source_shows_no_difference_are_shown_whole() -> None:
    source = _program(("1", "Pump", "copy(DS1, DS101)"))

    change = compare_rungs(_rungs("Y001"), _rungs("Y002"))
    diff = render_diff(change, "main.csv", before=_sources(source), after=_sources(source))

    assert [line[0] for line in diff.lines[2:]] == ["-"] * 3 + ["+"] * 3
    assert diff.words == {}


def test_lines_with_little_in_common_are_not_split_into_words() -> None:
    before = _program(("1", "Pump", "copy(DS1, DS101)"))
    after = _program(("1", "Pump", "out(Y001)"))

    change = compare_rungs(_rungs("Y001"), _rungs("Y002"))
    diff = render_diff(change, "main.csv", before=_sources(before), after=_sources(after))

    assert diff.lines[4:] == ("-        copy(DS1, DS101)\n", "+        out(Y001)\n")
    assert diff.words == {}


def test_diff_lists_rungs_by_number_without_source() -> None:
    change = compare_rungs(_commented("Keep"), _commented("Keep", "Start the pump"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines == (
        "--- CLICK/main.csv\n",
        "+++ proposed/main.csv\n",
        " R1  # Keep\n",
        "+R2  # Start the pump\n",
    )


def test_diff_without_source_names_each_rungs_instructions() -> None:
    change = compare_rungs(_rungs("Y001"), _rungs("Y001", "Y002"))

    diff = render_diff(change, "main.csv", before=BundleSources(), after=BundleSources())

    assert diff.lines[2:] == (" R1  out(Y001)\n", "+R2  out(Y002)\n")


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

    assert diff.lines[2:] == (
        "     with rung():  # R1\n",
        "         out(Y001)\n",
        "+    with rung():  # R2\n",
        "+        out(Y002)\n",
    )


def test_round_trip_of_something_pyrung_cannot_convert_is_empty(tmp_path: Path) -> None:
    assert BundleSources.round_trip(tmp_path / "missing") == BundleSources()
