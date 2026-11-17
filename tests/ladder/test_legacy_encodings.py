"""program_save records the rungs CLICK holds in a legacy encoding, beside the CSVs it writes."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from types import SimpleNamespace

import laddercodec
import pytest
from laddercodec.model import Program

from clicknick.connection_session import ConnectionSession
from clicknick.ladder.cli import main
from clicknick.ladder.program import (
    LEGACY_ENCODINGS_FILE,
    LegacyEncoding,
    program_save,
    read_legacy_encodings,
)

DETAIL = "it is stored as 16-bit and CLICK runs it as 4464."


class FakeLegacyWarning(UserWarning):
    """Stands in for laddercodec.LegacyEncodingWarning, which older laddercodecs lack."""

    def __init__(self, instruction, token, detail, rung=None, program=None) -> None:
        super().__init__(f"{instruction} {token}: {detail}")
        self.instruction, self.token, self.detail = instruction, token, detail
        self.rung, self.program = rung, program


@pytest.fixture
def scr(tmp_path: Path) -> Path:
    folder = tmp_path / "scr"
    folder.mkdir()
    for name in ("Scr1.tmp", "Scr2.tmp"):
        (folder / name).write_bytes(name.encode())
    return folder


@pytest.fixture
def written(monkeypatch) -> list[Path]:
    paths: list[Path] = []
    monkeypatch.setattr(
        "clicknick.ladder.program.write_csv", lambda path, _rungs, **_kw: paths.append(path)
    )
    return paths


def _decoder(monkeypatch, warning_type, warns: dict[bytes, list[tuple]]) -> None:
    """Decode Scr1.tmp as main and Scr2.tmp as "Fill", warning as *warns* says."""
    names = {b"Scr1.tmp": ("Main Program", 1), b"Scr2.tmp": ("Fill", 2)}

    def _decode_program(data: bytes) -> Program:
        name, prog_idx = names[data]
        for args in warns.get(data, ()):
            warnings.warn(warning_type(*args, program=name), stacklevel=2)
        return Program(name=name, prog_idx=prog_idx, rungs=[])

    monkeypatch.setattr("clicknick.ladder.program.decode_program", _decode_program)


def _legacy_type(monkeypatch, warning_type=FakeLegacyWarning) -> type[Warning]:
    monkeypatch.setattr(laddercodec, "LegacyEncodingWarning", warning_type, raising=False)
    return warning_type


def test_records_each_programs_legacy_encodings(monkeypatch, scr: Path, written) -> None:
    warning_type = _legacy_type(monkeypatch)
    _decoder(
        monkeypatch,
        warning_type,
        {
            b"Scr1.tmp": [("Math", "H70000", DETAIL, 11)],
            b"Scr2.tmp": [("Math", "H-40000", DETAIL, 0)],
        },
    )
    out = scr / "csv"

    result = program_save(scr, out)

    assert result.legacy_encodings == [
        LegacyEncoding("main.csv", "Main Program", 12, "Math", "H70000", DETAIL),
        LegacyEncoding("subroutines/Fill.csv", "Fill", 1, "Math", "H-40000", DETAIL),
    ]
    assert json.loads((out / LEGACY_ENCODINGS_FILE).read_text(encoding="utf-8"))[0] == {
        "file": "main.csv",
        "program": "Main Program",
        "rung": 12,
        "instruction": "Math",
        "token": "H70000",
        "detail": DETAIL,
    }
    assert read_legacy_encodings(out) == tuple(result.legacy_encodings)


def test_save_without_legacy_encodings_removes_the_old_record(
    monkeypatch, scr: Path, written
) -> None:
    warning_type = _legacy_type(monkeypatch)
    _decoder(monkeypatch, warning_type, {b"Scr1.tmp": [("Math", "H70000", DETAIL, 0)]})
    out = scr / "csv"
    program_save(scr, out)
    assert (out / LEGACY_ENCODINGS_FILE).is_file()

    _decoder(monkeypatch, warning_type, {})
    result = program_save(scr, out)

    assert result.legacy_encodings == []
    assert not (out / LEGACY_ENCODINGS_FILE).exists()
    assert read_legacy_encodings(out) == ()


def test_other_warnings_still_reach_the_caller(monkeypatch, scr: Path, written) -> None:
    _legacy_type(monkeypatch)

    def _deprecation(*args, program=None) -> Warning:
        return DeprecationWarning(" ".join(args))

    _decoder(monkeypatch, _deprecation, {b"Scr1.tmp": [("old", "form", "here")]})

    with pytest.warns(DeprecationWarning, match="old"):
        result = program_save(scr, scr / "csv")

    assert result.legacy_encodings == []


def test_laddercodec_without_legacy_warnings_saves_as_before(
    monkeypatch, scr: Path, written
) -> None:
    monkeypatch.delattr(laddercodec, "LegacyEncodingWarning", raising=False)
    _decoder(monkeypatch, FakeLegacyWarning, {b"Scr1.tmp": [("Math", "H70000", DETAIL, 0)]})

    # Nothing is caught: the warning goes on like any other
    with pytest.warns(FakeLegacyWarning):
        result = program_save(scr, scr / "csv")

    assert result.legacy_encodings == []
    assert written == [scr / "csv" / "main.csv", scr / "csv" / "subroutines" / "Fill.csv"]
    assert not (scr / "csv" / LEGACY_ENCODINGS_FILE).exists()


@pytest.mark.skipif(
    not hasattr(laddercodec, "LegacyEncodingWarning"),
    reason="this laddercodec does not warn about legacy encodings",
)
def test_reads_laddercodecs_own_warning(monkeypatch, scr: Path, written) -> None:
    _decoder(
        monkeypatch,
        laddercodec.LegacyEncodingWarning,
        {b"Scr2.tmp": [("Math", "H70000", DETAIL, 2)]},
    )

    result = program_save(scr, scr / "csv")

    assert result.legacy_encodings == [
        LegacyEncoding("subroutines/Fill.csv", "Fill", 3, "Math", "H70000", DETAIL)
    ]


@pytest.mark.parametrize(
    "text",
    ["not json", '{"file": "main.csv"}', '[{"file": "main.csv"}]', '[{"file": 1, "rung": "x"}]'],
)
def test_unreadable_record_counts_as_none(tmp_path: Path, text: str) -> None:
    (tmp_path / LEGACY_ENCODINGS_FILE).write_text(text, encoding="utf-8")

    assert read_legacy_encodings(tmp_path) == ()


def test_cli_save_lists_rungs_to_paste_again(monkeypatch, scr: Path, written, capsys) -> None:
    warning_type = _legacy_type(monkeypatch)
    _decoder(monkeypatch, warning_type, {b"Scr1.tmp": [("Math", "H70000", DETAIL, 11)]})
    monkeypatch.setattr("sys.argv", ["clicknick-cli", "program", "save", str(scr)])

    main()

    out = capsys.readouterr().out
    assert "CLICK holds these rungs in an old encoding" in out
    assert f"  Main Program rung 12, Math H70000: {DETAIL}" in out


# ---------------------------------------------------------------------------
# Reporting them once
# ---------------------------------------------------------------------------


def _session(csv_dir: Path) -> ConnectionSession:
    session = ConnectionSession.__new__(ConnectionSession)
    session._legacy_reported = frozenset()
    session.saved_program = lambda: SimpleNamespace(csv_dir=csv_dir)
    return session


def _record(csv_dir: Path, *found: tuple[str, int, str]) -> None:
    from clicknick.ladder.program import write_legacy_encodings

    write_legacy_encodings(
        csv_dir,
        [LegacyEncoding(file, "P", rung, "Math", token, DETAIL) for file, rung, token in found],
    )


def test_legacy_encodings_are_reported_once_per_new_finding(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _record(tmp_path, ("main.csv", 3, "H70000"), ("main.csv", 9, "H80000"))

    assert len(session.legacy_encodings_to_report()) == 2
    assert session.legacy_encodings_to_report() == ()  # The next save finds the same

    # Pasting rungs above moves them, and pasting one fixes it: neither is news
    _record(tmp_path, ("main.csv", 5, "H70000"))
    assert session.legacy_encodings_to_report() == ()

    # One that was not there before is reported, with the rest
    _record(tmp_path, ("main.csv", 5, "H70000"), ("subroutines/Fill.csv", 1, "H90000"))
    assert [item.token for item in session.legacy_encodings_to_report()] == ["H70000", "H90000"]

    # Fixed, then back again: reported again
    _record(tmp_path)
    assert session.legacy_encodings_to_report() == ()
    _record(tmp_path, ("main.csv", 5, "H70000"))
    assert len(session.legacy_encodings_to_report()) == 1


def test_nothing_is_reported_while_clicks_program_is_being_read(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _record(tmp_path, ("main.csv", 3, "H70000"))
    session.saved_program = lambda: SimpleNamespace(csv_dir=None)

    assert session.legacy_encodings_to_report() == ()

    session.saved_program = lambda: SimpleNamespace(csv_dir=tmp_path)
    assert len(session.legacy_encodings_to_report()) == 1
