"""compare_csv_folder: which programs in a CSV bundle differ from CLICK's saved program."""

from __future__ import annotations

import typing
from pathlib import Path

from laddercodec import Coil, Contact, Rung, write_csv

from clicknick.ladder.program import compare_csv_folder

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

    assert compare_csv_folder(proposed, current) == {
        "main.csv": False,
        "subroutines/fill.csv": False,
        "subroutines/Drain.csv": True,
        "subroutines/Rinse.csv": True,
    }


def test_folder_without_main_is_not_compared(tmp_path: Path) -> None:
    current = _bundle(tmp_path / "current", {"main.csv": _rungs("Y001")})
    fixtures = _bundle(tmp_path / "fixtures", {"coil.csv": _rungs("Y001")})

    assert compare_csv_folder(fixtures, current) == {}


def test_unreadable_program_is_unknown(tmp_path: Path) -> None:
    current = _bundle(tmp_path / "current", {"main.csv": _rungs("Y001")})
    proposed = _bundle(tmp_path / "proposed", {"main.csv": _rungs("Y001")})
    (proposed / "subroutines").mkdir()
    (proposed / "subroutines" / "Broken.csv").write_text("not,a,ladder\n", encoding="utf-8")

    assert compare_csv_folder(proposed, current) == {"main.csv": False}
