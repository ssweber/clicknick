"""Contracts for the generated ``src/plc`` project layout."""

from __future__ import annotations

import os
from pathlib import Path

from clicknick.live.rung_commands import (
    _all_file_stems,
    _get_csv_stem,
    _resolve_file,
)
from clicknick.services.project_workspace import project_environment


def _write_project(project_dir: Path) -> None:
    package_dir = project_dir / "src" / "plc"
    subroutines = package_dir / "subroutines"
    subroutines.mkdir(parents=True)
    (package_dir / "main.py").write_text("logic = object()\n", encoding="utf-8")
    (subroutines / "__init__.py").write_text("", encoding="utf-8")
    (subroutines / "startup.py").write_text(
        '@subroutine("Startup Sequence")\ndef startup():\n    pass\n',
        encoding="utf-8",
    )


def test_rung_paths_resolve_inside_src_plc(tmp_path: Path):
    _write_project(tmp_path)

    assert _resolve_file(tmp_path, "main") == tmp_path / "src" / "plc" / "main.py"
    assert _resolve_file(tmp_path, "startup") == (
        tmp_path / "src" / "plc" / "subroutines" / "startup.py"
    )
    assert _all_file_stems(tmp_path) == ["main", "startup"]
    assert _get_csv_stem(tmp_path, "startup") == "Startup Sequence"


def test_project_environment_prepends_src_to_pythonpath(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "existing")

    env = project_environment(tmp_path)

    assert env["PYTHONPATH"] == os.pathsep.join((str(tmp_path / "src"), "existing"))
