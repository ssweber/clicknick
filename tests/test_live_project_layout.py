"""Contracts for the generated ``src/plc`` project layout."""

from __future__ import annotations

import os
from pathlib import Path

from clicknick.live.rung_commands import (
    _all_file_stems,
    _extract_rungs,
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


def test_rung_list_metadata_uses_preceding_click_comments():
    source = '''\
with Program() as logic:
    comment("""\
        # ====================
        # Battery handling
        More detail that should not fill the listing.""")
    with rung():  # R1
        out(BatteryOk)

    with rung():  # R2
        comment("This belongs inside R2, not to R3")

    with rung():  # R3
        """Manual rung description"""
        out(Ready)
'''

    rungs = _extract_rungs(source)

    assert [rung[0] for rung in rungs] == [1, 2, 3]
    assert rungs[0][3] == "Battery handling"
    assert rungs[1][3] == ""
    assert rungs[2][3] == "Manual rung description"


def test_rung_comment_summary_is_compact():
    source = f'''\
with Program() as logic:
    comment("{"description " * 20}")
    with rung():  # R1
        pass
'''

    summary = _extract_rungs(source)[0][3]

    assert len(summary) == 88
    assert summary.endswith("...")
