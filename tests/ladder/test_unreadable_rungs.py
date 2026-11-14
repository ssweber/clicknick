"""Rungs laddercodec cannot read, such as a compare CLICK's own dialog refuses.

An older laddercodec pasted them into CLICK, and the current one decodes the
cell as ``UnknownCondition``, which has no CSV token.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest
from laddercodec import Coil, CompareContact, Contact, Rung, encode, read_csv
from laddercodec.instructions import UnknownCondition, UnknownInstruction
from laddercodec.model import Program

from clicknick.ladder.cli import main
from clicknick.ladder.program import (
    LEGACY_ENCODINGS_FILE,
    STAND_IN_COMMENT,
    LegacyEncoding,
    UnreadableRungError,
    decode_to_csv,
    describe_legacy_encoding,
    is_stand_in,
    prepare_rungs_load,
    program_save,
    read_legacy_encodings,
)

_IT = typing.get_type_hints(Contact)["type"]
DETAIL = "ClickNick cannot read this Compare."


def _rung(coil: str, first=None, comment: str | None = None) -> Rung:
    conditions: list = ["-"] * 31
    if first is not None:
        conditions[0] = first
    return Rung(
        logical_rows=1,
        conditions=[conditions],
        instructions=[Coil(_IT.COIL_OUT, coil)],
        comment=comment,
    )


# A Scr*.tmp names the instruction laddercodec could not read, as decode_program.py does
_REFUSED = UnknownCondition(raw=b"Compare")


@pytest.fixture
def scr(tmp_path: Path, monkeypatch) -> Path:
    """Scr1.tmp is main, Scr2.tmp is "Conf_Compare" with its rungs 2 and 3 unreadable."""
    folder = tmp_path / "scr"
    folder.mkdir()
    programs = {
        b"Scr1.tmp": Program("Main Program", 1, [_rung("C1")]),
        b"Scr2.tmp": Program(
            "Conf_Compare",
            2,
            [
                _rung("C10"),
                _rung("C11", _REFUSED, comment="Case compare/hex_vs_int"),
                _rung("C12", _REFUSED),
                _rung("C13"),
            ],
        ),
    }
    for name in programs:
        (folder / name.decode()).write_bytes(name)
    monkeypatch.setattr("clicknick.ladder.program.decode_program", programs.__getitem__)
    return folder


def test_save_writes_every_program_and_names_each_unreadable_rung(scr: Path) -> None:
    out = scr / "csv"

    result = program_save(scr, out, index=True)

    assert result.legacy_encodings == [
        LegacyEncoding(
            "subroutines/Conf_Compare.csv", "Conf_Compare", 2, "Compare", "", DETAIL, True
        ),
        LegacyEncoding(
            "subroutines/Conf_Compare.csv", "Conf_Compare", 3, "Compare", "", DETAIL, True
        ),
    ]
    assert read_legacy_encodings(out) == tuple(result.legacy_encodings)
    assert json.loads((out / LEGACY_ENCODINGS_FILE).read_text(encoding="utf-8"))[0] == {
        "file": "subroutines/Conf_Compare.csv",
        "program": "Conf_Compare",
        "rung": 2,
        "instruction": "Compare",
        "token": "",
        "detail": DETAIL,
        "unreadable": True,
    }
    assert len(read_csv(out / "main.csv")) == 1


def test_each_unreadable_rung_becomes_an_empty_rung_so_the_rest_keep_their_numbers(
    scr: Path,
) -> None:
    out = scr / "csv"
    program_save(scr, out, index=True)

    rungs = read_csv(out / "subroutines" / "Conf_Compare.csv")

    assert len(rungs) == 4
    assert [is_stand_in(rung) for rung in rungs] == [False, True, True, False]
    assert [rung.instructions for rung in rungs] == [
        [Coil(_IT.COIL_OUT, "C10")],
        [""],
        [""],
        [Coil(_IT.COIL_OUT, "C13")],
    ]
    # The rung's own comment stays below the note, so the user can tell which rung it was
    assert rungs[1].comment == (
        f"{STAND_IN_COMMENT}\nClickNick cannot read its Compare. Paste it again.\n\n"
        "Case compare/hex_vs_int"
    )


def test_a_save_after_the_paste_removes_the_record(scr: Path, monkeypatch) -> None:
    out = scr / "csv"
    program_save(scr, out, index=True)
    assert (out / LEGACY_ENCODINGS_FILE).is_file()

    fixed = {
        b"Scr1.tmp": Program("Main Program", 1, [_rung("C1")]),
        b"Scr2.tmp": Program("Conf_Compare", 2, [_rung("C10")]),
    }
    monkeypatch.setattr("clicknick.ladder.program.decode_program", fixed.__getitem__)
    result = program_save(scr, out, index=True)

    assert result.legacy_encodings == []
    assert not (out / LEGACY_ENCODINGS_FILE).exists()


def test_an_unreadable_rung_in_main_is_named_and_the_rest_converts_to_pyrung(
    tmp_path: Path, monkeypatch
) -> None:
    from pyrung.click import ladder_to_pyrung

    (tmp_path / "Scr1.tmp").write_bytes(b"Scr1.tmp")
    rungs = [_rung("C1"), _rung("C2", _REFUSED), _rung("C3")]
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, rungs),
    )
    out = tmp_path / "csv"

    result = program_save(tmp_path, out, index=True)

    assert [(item.file, item.rung) for item in result.legacy_encodings] == [("main.csv", 2)]
    assert describe_legacy_encoding(result.legacy_encodings[0]) == (
        f"Main Program rung 2, Compare: {DETAIL}"
    )
    code = ladder_to_pyrung(out)
    assert STAND_IN_COMMENT in code
    assert "out(C2)" not in code
    assert "out(C3)" in code


def test_cli_save_lists_the_rungs_to_paste_again(scr: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["clicknick-cli", "program", "save", str(scr)])

    main()

    out = capsys.readouterr().out
    assert "ClickNick cannot read these rungs" in out
    assert f"  Conf_Compare rung 2, Compare: {DETAIL}" in out
    assert "old encoding" not in out


# ---------------------------------------------------------------------------
# The clipboard
# ---------------------------------------------------------------------------


def _refused_payload() -> bytes:
    """A clipboard rung holding ``DH70 == DS39``, which CLICK's Compare dialog refuses.

    laddercodec will not encode it, so this encodes ``DH70 == DH71`` and swaps
    the operand for one of the same length.
    """
    data = encode(_rung("C1", CompareContact("==", "DH70", "DH71")))
    old, new = "DH71".encode("utf-16-le"), "DS39".encode("utf-16-le")
    assert data.count(old) == 1
    return data.replace(old, new)


def test_clipboard_rung_laddercodec_cannot_read_is_named_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError) as caught:
        decode_to_csv(_refused_payload(), path)

    assert f"  copied rung 1, Compare: {DETAIL}" in str(caught.value)
    assert not path.exists()


def test_clipboard_output_laddercodec_cannot_read_is_named_too(tmp_path: Path, monkeypatch) -> None:
    # laddercodec keeps an output instruction it cannot find the end of whole, name and all
    copy = Rung(
        logical_rows=1,
        conditions=[["-"] * 31],
        instructions=[UnknownInstruction(raw="Copy".encode("utf-16-le") + b"\0\0\x07")],
        comment=None,
    )
    monkeypatch.setattr("clicknick.ladder.program._decode_to_rungs", lambda _data: [copy])
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError) as caught:
        decode_to_csv(b"", path)

    assert "  copied rung 1, Copy: ClickNick cannot read this Copy." in str(caught.value)
    assert not path.exists()


def test_readable_clipboard_rung_is_written(tmp_path: Path) -> None:
    path = tmp_path / "copied.csv"

    decode_to_csv(encode(_rung("C1", CompareContact("==", "DH70", "DH71"))), path)

    assert read_csv(path)[0].conditions[0][0] == CompareContact("==", "DH70", "DH71")


# ---------------------------------------------------------------------------
# Copying a stand-in
# ---------------------------------------------------------------------------


def test_a_stand_in_is_never_copied_over_the_rung_it_stands_for(scr: Path) -> None:
    out = scr / "csv"
    program_save(scr, out, index=True)
    rungs = read_csv(out / "subroutines" / "Conf_Compare.csv")

    with pytest.raises(UnreadableRungError, match=r"^Rungs 2, 3 are empty rungs"):
        prepare_rungs_load(rungs, click_v4=True)
    with pytest.raises(UnreadableRungError, match=r"^Rung 6 is an empty rung"):
        prepare_rungs_load(rungs[1:2], click_v4=True, first_rung=6)
    assert prepare_rungs_load(rungs[:1], click_v4=True).rung_count == 1


def test_a_stand_in_is_an_empty_rung_with_the_note_old_or_new() -> None:
    old = "ClickNick could not read this rung from CLICK. This empty rung stands in for it."
    empty = ["-"] * 31

    def rung(comment: str, instruction="NOP") -> Rung:
        return Rung(logical_rows=1, conditions=[empty], instructions=[instruction], comment=comment)

    assert is_stand_in(rung(f"{STAND_IN_COMMENT}\nmore"))
    assert is_stand_in(rung(old))
    assert not is_stand_in(rung("A comment rung"))
    # The note copied onto a rung that does something is only a comment
    assert not is_stand_in(rung(STAND_IN_COMMENT, Coil(_IT.COIL_OUT, "C1")))


def test_a_stand_in_survives_pyrung_and_back_and_is_still_refused(
    tmp_path: Path, monkeypatch
) -> None:
    import linecache

    from pyrung.click import ladder_to_pyrung, pyrung_to_ladder

    (tmp_path / "Scr1.tmp").write_bytes(b"Scr1.tmp")
    rungs = [_rung("C1"), _rung("C2", _REFUSED, comment="Mine"), _rung("C3")]
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, rungs),
    )
    csv_dir = tmp_path / "csv"
    program_save(tmp_path, csv_dir, index=True)
    code = ladder_to_pyrung(csv_dir)
    filename = "<stand-in round trip>"
    linecache.cache[filename] = (len(code), None, code.splitlines(keepends=True), filename)
    namespace: dict = {}
    exec(compile(code, filename, "exec"), namespace)  # noqa: S102
    out = tmp_path / "csv_output"

    pyrung_to_ladder(namespace["logic"], namespace["mapping"], index=True).write(out)
    exported = read_csv(out / "main.csv")

    assert [is_stand_in(rung) for rung in exported[:3]] == [False, True, False]
    with pytest.raises(UnreadableRungError, match=r"^Rung 2 is an empty rung"):
        prepare_rungs_load(exported, click_v4=True)


# ---------------------------------------------------------------------------
# A CSV laddercodec cannot read back
# ---------------------------------------------------------------------------


def test_save_names_a_program_whose_csv_laddercodec_cannot_read_back(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """An older laddercodec decodes ``DH70 == DS3920`` and writes it, but cannot read it."""
    import clicknick.ladder.program as program

    (tmp_path / "Scr1.tmp").write_bytes(b"Scr1.tmp")
    rungs = [_rung("C1", CompareContact("==", "DH70", "DH71"))]
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, rungs),
    )
    write_csv = program.write_csv

    def write_refused(path: Path, written, **kwargs) -> None:
        write_csv(path, written, **kwargs)
        path.write_text(path.read_text(encoding="utf-8").replace("DH71", "DS3920"), "utf-8")

    monkeypatch.setattr("clicknick.ladder.program.write_csv", write_refused)
    out = tmp_path / "csv"

    result = program_save(tmp_path, out, index=True)

    [found] = result.legacy_encodings
    assert (found.file, found.program, found.rung, found.unreadable) == (
        "main.csv",
        "Main Program",
        None,
        True,
    )
    assert found.detail.startswith("ClickNick cannot read CLICK's copy of this program. ")
    assert "'DS3920'" in found.detail
    assert read_legacy_encodings(out) == (found,)
    assert describe_legacy_encoding(found) == f"Main Program: {found.detail}"

    monkeypatch.setattr("sys.argv", ["clicknick-cli", "program", "save", str(tmp_path)])
    main()
    printed = capsys.readouterr().out
    assert f"Paste these programs into CLICK again:\n  Main Program: {found.detail}" in printed
    assert "ClickNick cannot read these rungs" not in printed
