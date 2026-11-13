"""program_save reads CLICK's Scr<N>.tmp files and not its mid-save copies."""

from __future__ import annotations

from pathlib import Path

from laddercodec.model import Program

from clicknick.ladder.program import program_save


def test_a_mid_save_copy_is_not_a_second_program(tmp_path: Path, monkeypatch) -> None:
    """CLICK briefly writes ``Scr2.tmp~RF<hex>.TMP``; it must not become a program of its own."""
    programs = {
        b"main": Program("Main Program", 1, []),
        b"motor": Program("Motor", 2, []),
    }
    monkeypatch.setattr("clicknick.ladder.program.decode_program", programs.__getitem__)
    scr = tmp_path / "scr"
    scr.mkdir()
    (scr / "Scr1.tmp").write_bytes(b"main")
    (scr / "Scr2.tmp").write_bytes(b"motor")
    (scr / "Scr2.tmp~RFcf1eba5.TMP").write_bytes(b"motor")

    result = program_save(scr, tmp_path / "out")

    assert [p.source for p in result.programs] == ["Scr1.tmp", "Scr2.tmp"]
    assert [p.name for p in result.subroutine_csvs] == ["Motor.csv"]
