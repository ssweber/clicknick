"""compare_csv_folder: which programs in a CSV bundle differ from CLICK's saved program."""

from __future__ import annotations

import typing
from pathlib import Path

from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.ladder.program import FolderComparison, compare_csv_folder

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


def _bundle(root: Path, programs: dict[str, list[Rung]], *, index: bool = False) -> Path:
    """Write {relative name: rungs} like program_save output."""
    for name, rungs in programs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(path, rungs, index=index)
    return root


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

    assert compare_csv_folder(proposed, current).differs == {
        "main.csv": False,
        "subroutines/fill.csv": False,
        "subroutines/Drain.csv": True,
        "subroutines/Rinse.csv": True,
    }


def test_lists_programs_only_in_click(tmp_path: Path) -> None:
    current = _bundle(
        tmp_path / "current",
        {
            "main.csv": _rungs("Y001"),
            "subroutines/Fill.csv": _rungs("Y002"),
            "subroutines/Old Alarm.csv": _rungs("Y003"),
        },
    )
    proposed = _bundle(
        tmp_path / "proposed",
        {"main.csv": _rungs("Y001"), "subroutines/FILL.csv": _rungs("Y002")},
    )

    comparison = compare_csv_folder(proposed, current)

    assert comparison.only_in_click == {
        "subroutines/Old Alarm.csv": current / "subroutines" / "Old Alarm.csv"
    }
    assert "subroutines/Old Alarm.csv" not in comparison.differs


def test_folder_without_main_is_not_compared(tmp_path: Path) -> None:
    current = _bundle(
        tmp_path / "current",
        {"main.csv": _rungs("Y001"), "subroutines/Fill.csv": _rungs("Y002")},
    )
    fixtures = _bundle(tmp_path / "fixtures", {"coil.csv": _rungs("Y001")})

    assert compare_csv_folder(fixtures, current) == FolderComparison()


def test_unreadable_program_is_unknown(tmp_path: Path) -> None:
    current = _bundle(tmp_path / "current", {"main.csv": _rungs("Y001")})
    proposed = _bundle(tmp_path / "proposed", {"main.csv": _rungs("Y001")})
    (proposed / "subroutines").mkdir()
    (proposed / "subroutines" / "Broken.csv").write_text("not,a,ladder\n", encoding="utf-8")

    assert compare_csv_folder(proposed, current).differs == {"main.csv": False}
