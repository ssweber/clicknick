"""Bundle parser for Click Ladder CSV directory exports."""

from __future__ import annotations

from pathlib import Path

from .ast import ProgramBundleAst
from .parser import parse_csv_file


def parse_bundle(directory: Path | str, strict: bool = True) -> ProgramBundleAst:
    dir_path = Path(directory)
    main_path = dir_path / "main.csv"
    if not main_path.exists():
        raise ValueError(f"Bundle directory {dir_path} is missing required main.csv")

    main = parse_csv_file(main_path, syntax="canonical", strict=strict)

    sub_paths = sorted(
        p
        for p in dir_path.iterdir()
        if p.is_file() and p.suffix.lower() == ".csv" and p.name.startswith("sub_")
    )
    subroutines = tuple(
        parse_csv_file(path, syntax="canonical", strict=strict) for path in sub_paths
    )
    return ProgramBundleAst(directory=dir_path, main=main, subroutines=subroutines)
