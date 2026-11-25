"""Tests of reading where the workspace's src/plc stops, in a process of its own."""

from __future__ import annotations

from pathlib import Path

import pytest

from clicknick.services.analysis_service import UndecodedRung
from clicknick.services.program_stops import read_program_stops

_MAIN = """from pyrung import Program, rung, out, subroutine, call, Bool
from pyrung.click import undecoded

C1 = Bool("C1")


@subroutine("Fill Tank")
def fill():
    with rung():
        out(C1)

    with rung():
        undecoded("bad", rung=1, stop="return")


with Program() as logic:
    with rung():
        call(fill)

    with rung():
        undecoded("bad", rung=1, stop="end")

# The source prints a line that looks like an answer, and leaves its last line open
print('[["Main Program", 9]]')
print("the source may print", end="")
"""


def _workspace(tmp_path: Path, main: str) -> Path:
    plc = tmp_path / "src" / "plc"
    plc.mkdir(parents=True)
    (plc / "__init__.py").write_text("", encoding="utf-8")
    (plc / "main.py").write_text(main, encoding="utf-8")
    return tmp_path


def test_the_markers_in_src_plc_name_their_click_rungs_whatever_it_prints(
    tmp_path: Path,
) -> None:
    assert read_program_stops(_workspace(tmp_path, _MAIN)) == (
        UndecodedRung("Main Program", 2),
        UndecodedRung("Fill Tank", 2),
    )


def test_a_workspace_without_src_plc_has_no_stops(tmp_path: Path) -> None:
    assert read_program_stops(tmp_path) == ()


def test_a_source_that_cannot_be_imported_raises_its_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"^NameError: name 'nope' is not defined"):
        read_program_stops(_workspace(tmp_path, "nope\n"))


def test_a_source_that_ends_the_worker_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ended the worker before it could answer"):
        read_program_stops(_workspace(tmp_path, "import sys\nsys.exit(0)\n"))


def test_a_read_that_takes_too_long_raises(tmp_path: Path, monkeypatch) -> None:
    from clicknick.services import program_stops

    monkeypatch.setattr(program_stops, "READ_TIMEOUT", 0.5)
    with pytest.raises(ValueError, match=r"took longer than 0\.5 seconds"):
        read_program_stops(_workspace(tmp_path, "import time\ntime.sleep(30)\n"))
