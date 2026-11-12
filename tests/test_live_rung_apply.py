"""``rung apply``: what it reports and what it hands to Preview Changes."""

from __future__ import annotations

import typing
from pathlib import Path
from unittest.mock import Mock

import pytest
from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.live import rung_commands
from clicknick.live.dispatch import DispatchContext, dispatch

_IT = typing.get_type_hints(Contact)["type"]

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
            logical_rows=1,
            conditions=[["-"] * 31],
            instructions=[Coil(_IT.COIL_OUT, coil)],
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
    """A workspace whose export writes whatever ``propose`` was given.

    Returns ``(context, propose, staged)``: the dispatch context with a mock
    Preview Changes, a function setting the next export, and the staged counts.
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


def test_reports_every_program_that_differs_and_opens_preview_changes(
    project, tmp_path: Path
) -> None:
    ctx, propose, staged = project
    propose(
        {
            "main.csv": ["Y001", "Y005", "Y002"],
            "subroutines/Rinse Cycle.csv": ["Y006"],  # new; Fill is gone from the proposal
        }
    )

    reply = dispatch(ctx, "rung apply")

    # In the order Preview Changes walks them: subroutines before main
    assert "changed files:\n  rinse_cycle: new, 1 rung\n  main: R2\n" in reply
    assert "only in CLICK (delete there if no longer used): Fill" in reply
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


def test_one_file_opens_preview_changes_on_that_program(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y006", "Y002"]})

    reply = dispatch(ctx, "rung apply main")

    assert "OK: paste window opened for main (R2..3)" in reply
    assert staged == [2]
    ctx.show_proposal.assert_called_once_with(
        tmp_path / "csv_output", tmp_path / "src" / "plc", "main.csv", None, True
    )


def test_selection_names_the_rungs_to_paste(project, tmp_path: Path) -> None:
    ctx, propose, staged = project
    propose({**CLICK, "main.csv": ["Y001", "Y005", "Y002"]})

    reply = dispatch(ctx, "rung apply main --select r1..2")

    assert "OK: paste window opened for main (2 selected rungs)" in reply
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

    assert "OK: paste window opened for rinse_cycle (new, 2 rungs)" in reply
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
        "--- CLICK/main.csv\n+++ proposed/main.csv\n"
        " R1  out(Y001)\n+R2  out(Y005)\n R3  out(Y002)\n"
    ) in reply


def _earlier_export(project_dir: Path) -> tuple[Path, Path]:
    """An export holding main.csv and a subroutine the source no longer has."""
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
