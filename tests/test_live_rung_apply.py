"""Tests of what ``rung apply`` reports and what it passes to Review Changes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, Mock

import pytest
from laddercodec import Coil, Rung, write_csv

from clicknick.live import rung_commands
from clicknick.live.dispatch import DispatchContext, dispatch

CLICK = {
    "main.csv": ["Y001", "Y002"],
    "subroutines/Fill.csv": ["Y003"],
}


class _Store:
    def get_dirty_keys(self) -> set[int]:
        return set()


class _Analysis:
    is_available = True

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir


def _rungs(coils: list[str]) -> list[Rung]:
    return [
        Rung(
            conditions=[["-"] * 31],
            instructions=[Coil(coil)],
            comment=None,
        )
        for coil in coils
    ]


def _write_bundle(root: Path, programs: dict[str, list[str]]) -> None:
    for name, coils in programs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(path, _rungs(coils), index=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    """Return a workspace whose export writes whatever ``propose`` was given.

    The fixture returns ``(context, propose, staged)``. The context is the dispatch context
    with a mock Review Changes. ``propose`` sets the next export. ``staged`` holds the
    staged counts.
    """
    _write_bundle(tmp_path / "csv", CLICK)
    source = tmp_path / "src" / "plc"
    (source / "subroutines").mkdir(parents=True)
    (source / "main.py").write_text("main\n", encoding="utf-8")
    (source / "subroutines" / "__init__.py").write_text("", encoding="utf-8")
    for stem, title in (("fill", "Fill"), ("rinse_cycle", "Rinse Cycle")):
        (source / "subroutines" / f"{stem}.py").write_text(
            f'@subroutine("{title}")\ndef {stem}(): ...\n', encoding="utf-8"
        )

    proposal: dict[str, list[str]] = {}

    def _export(project_dir: Path) -> Path:
        _write_bundle(project_dir / "csv_output", proposal)
        return project_dir / "csv_output"

    monkeypatch.setattr(rung_commands, "_run_export", _export)
    staged: list[int] = []
    ctx = DispatchContext(
        store=_Store(),
        analysis=_Analysis(tmp_path),
        show_proposal=Mock(),
        record_staged_rungs=staged.append,
    )
    return ctx, proposal.update, staged


def test_reports_every_program_that_differs_and_opens_review_changes(
    project, tmp_path: Path
) -> None:
    ctx, propose, staged = project
    propose(
        {
            "main.csv": ["Y001", "Y005", "Y002"],
            "subroutines/Rinse Cycle.csv": ["Y006"],  # New. The proposal has no Fill.
        }
    )

    reply = dispatch(ctx, "rung apply")

    # The files come in the order Review Changes walks them: subroutines before main.
    assert "changed files:\n  rinse_cycle: new, 1 rung\n  main: R2\n" in reply
    assert "only in CLICK: Fill. Delete a program in CLICK if you no longer use it." in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", None, None, True
    )


def test_unchanged_proposal_only_refreshes_an_open_window(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose(CLICK)

    reply = dispatch(ctx, "rung apply")

    assert "(no changes)" in reply
    assert staged == [0]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", None, None, False
    )


def test_removed_rungs_are_reported_and_counted(project) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001"]})

    reply = dispatch(ctx, "rung apply")

    assert "  main: removes CLICK's R2" in reply
    assert staged == [1]


def test_one_file_opens_review_changes_on_that_program(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y006", "Y002"]})

    reply = dispatch(ctx, "rung apply main")

    assert "OK: opened Review Changes for main (R2..3)" in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", "main.csv", None, True
    )


def test_selection_names_the_rungs_to_paste(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main --select r1..2")

    assert "OK: opened Review Changes for main (2 selected rungs)" in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", "main.csv", [1, 2], True
    )


def test_selection_of_rungs_click_already_has_is_no_change(project) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main --select r1,r3")

    assert "(no changes)" in reply
    assert staged == [0]
    assert ctx.show_proposal.call_args.args[-1] is False


def test_new_subroutine_file_is_found_by_its_title(project) -> None:
    ctx, propose, _staged = project
    propose({**CLICK, "subroutines/Rinse Cycle.csv": ["Y006", "Y007"]})

    reply = dispatch(ctx, "rung apply rinse_cycle")

    assert "OK: opened Review Changes for rinse_cycle (new, 2 rungs)" in reply
    assert ctx.show_proposal.call_args.args[2] == "subroutines/Rinse Cycle.csv"


def test_file_the_export_left_out_is_an_error(project) -> None:
    ctx, propose, _staged = project
    propose(CLICK)

    with pytest.raises(ValueError, match="rinse_cycle was not exported"):
        dispatch(ctx, "rung apply rinse_cycle")


def test_without_a_window_one_file_replies_with_its_diff(project) -> None:
    ctx, propose, _staged = project
    ctx.show_proposal = None
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main")

    assert (
        "--- CLICK/main.csv\n+++ workspace/main.csv\n"
        " R1  out(Y001)\n+R2  out(Y005)\n R3  out(Y002)\n"
    ) in reply


def _earlier_export(project_dir: Path) -> tuple[Path, Path]:
    """Write an export that holds main.csv and a subroutine the source no longer has."""
    main = project_dir / "csv_output" / "main.csv"
    stale = project_dir / "csv_output" / "subroutines" / "Deleted.csv"
    stale.parent.mkdir(parents=True)
    main.write_text("earlier", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    return main, stale


def test_export_drops_csvs_it_did_not_write_again(tmp_path: Path) -> None:
    main, stale = _earlier_export(tmp_path)
    (tmp_path / "project_to_csv.py").write_text(
        "from pathlib import Path\n"
        "out = Path(__file__).parent / 'csv_output'\n"
        "(out / 'main.csv').write_text('fresh', encoding='utf-8')\n",
        encoding="utf-8",
    )

    rung_commands._run_export(tmp_path)

    assert main.read_text(encoding="utf-8") == "fresh"
    assert not stale.exists()


def test_failed_export_leaves_the_earlier_one_alone(tmp_path: Path) -> None:
    main, stale = _earlier_export(tmp_path)
    (tmp_path / "project_to_csv.py").write_text("raise SystemExit('broken')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="broken"):
        rung_commands._run_export(tmp_path)

    assert main.read_text(encoding="utf-8") == "earlier"
    assert stale.exists()


def test_summary_names_rungs_in_an_old_encoding_and_rungs_that_cannot_be_read() -> None:
    from clicknick.ladder.program import LegacyEncoding
    from clicknick.services.rung_diff import compare_rungs

    rungs = _rungs(["Y001", "Y002", "Y003"])
    found = [
        LegacyEncoding("main.csv", "Main Program", 1, "Math", "H70000", "it is stored..."),
        LegacyEncoding("main.csv", "Main Program", 3, "Compare", "", "it is refused.", True),
    ]

    summary = rung_commands._describe_change(compare_rungs(rungs, rungs, found), new=False)

    assert summary == (
        "R1, R3; CLICK's R1 in an old encoding; CLICK's R3 unreadable; paste it whole"
    )


def test_a_program_click_holds_unreadable_is_never_no_change(project, tmp_path: Path) -> None:
    """Report main as changed although its text matches, because CLICK's R2 is unreadable.

    The user must paste the whole program again.
    """
    from clicknick.ladder.program import LegacyEncoding, write_legacy_encodings

    ctx, propose, _staged = project
    propose(CLICK)
    found = LegacyEncoding("main.csv", "Main Program", 2, "Compare", "", "x", unreadable=True)
    write_legacy_encodings(tmp_path / "csv", [found])

    reply = dispatch(ctx, "rung apply")

    assert "  main: R2; CLICK's R2 unreadable; paste it whole" in reply
    assert "(no changes)" not in reply
    selected = dispatch(ctx, "rung apply main --select r1")
    # Selecting rung 1 does not paste it alone. CLICK's R2 is unreadable, so the whole program
    # is pasted.
    assert "OK: opened Review Changes for main (R2; CLICK's R2 unreadable; paste it whole)" in (
        selected
    )
    ctx.show_proposal.assert_called_with(ANY, ANY, "main.csv", None, True)


class _Status:
    def __init__(self, value: str) -> None:
        self.value = value


class _UnbuiltAnalysis:
    is_available = False
    project_dir = None

    def __init__(self, status: str, error: str | None = None) -> None:
        self.status = _Status(status)
        self.error = error


def test_a_failed_build_gives_its_reason() -> None:
    ctx = DispatchContext(store=_Store(), analysis=_UnbuiltAnalysis("failed", "no Scr*.tmp files"))

    with pytest.raises(ValueError) as caught:
        dispatch(ctx, "rung list")

    assert str(caught.value) == "Could not build the workspace: no Scr*.tmp files"


def test_an_unknown_program_is_named(tmp_path: Path) -> None:
    (tmp_path / "src" / "plc").mkdir(parents=True)
    ctx = DispatchContext(store=_Store(), analysis=_Analysis(tmp_path))

    with pytest.raises(ValueError) as caught:
        dispatch(ctx, "rung list nosuch")

    assert str(caught.value) == (
        "There is no program named 'nosuch'. Run 'rung list' to see the names."
    )
