"""Test rungs that laddercodec cannot read, such as a compare that CLICK's own dialog refuses.

An older laddercodec pasted these rungs into CLICK. The current one decodes the
cell as ``UnknownCondition``, which has no CSV token.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    Program,
    Rung,
    Tee,
    Undecoded,
    UnknownCondition,
    UnknownInstruction,
    decode,
    encode,
    read_csv,
    write_csv,
)

from clicknick.ladder.cli import main
from clicknick.ladder.program import (
    LEGACY_ENCODINGS_FILE,
    STAND_IN_COMMENT,
    LegacyEncoding,
    UnreadableRungError,
    decode_to_csv,
    describe_legacy_encoding,
    is_stand_in,
    prepare_bin_load,
    prepare_rungs_load,
    program_save,
    read_legacy_encodings,
)

DETAIL = "ClickNick cannot read this Compare."


def _rung(coil: str, first=None, comment: str | None = None) -> Rung:
    conditions: list = ["-"] * 31
    if first is not None:
        conditions[0] = first
    return Rung(
        conditions=[conditions],
        instructions=[Coil(coil)],
        comment=comment,
    )


# A rung condition that laddercodec could not decode. Its raw bytes name the instruction,
# "Compare". `_instruction_name` in src/clicknick/ladder/program.py reads that name.
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
        (Coil("C10"),),
        ("",),
        ("",),
        (Coil("C13"),),
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


def _unknown_payload() -> bytes:
    """Return a clipboard rung whose compare is of a class that laddercodec does not know.

    This encodes ``DH70 == DH71`` and renames its class from ``Compare`` to ``Comparx``.
    laddercodec decodes the renamed cell as an unknown condition.
    """
    data = encode(_rung("C1", CompareContact("==", "DH70", "DH71")))
    old, new = "Compare".encode("utf-16-le"), "Comparx".encode("utf-16-le")
    assert data.count(old) == 1
    return data.replace(old, new)


def test_clipboard_rung_laddercodec_cannot_read_is_named_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError) as caught:
        decode_to_csv(_unknown_payload(), path)

    assert "  copied rung 1, Comparx: ClickNick cannot read this Comparx." in str(caught.value)
    assert not path.exists()


def test_clipboard_output_laddercodec_cannot_read_is_named_too(tmp_path: Path, monkeypatch) -> None:
    # When laddercodec cannot find the end of an output instruction, it keeps the whole thing.
    copy = Rung(
        conditions=[["-"] * 31],
        instructions=[UnknownInstruction(raw="Copy".encode("utf-16-le") + b"\0\0\x07")],
        comment=None,
    )
    monkeypatch.setattr("clicknick.ladder.program.decode", lambda _data: [copy])
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError) as caught:
        decode_to_csv(b"", path)

    assert "  copied rung 1, Copy: ClickNick cannot read this Copy." in str(caught.value)
    assert not path.exists()


def test_save_finds_an_unreadable_contact_with_a_wire_down(tmp_path: Path, monkeypatch) -> None:
    # laddercodec decodes a cell that it cannot read, with a wire down from it, as a Tee
    scr = tmp_path / "scr"
    scr.mkdir()
    (scr / "Scr1.tmp").write_bytes(b"Scr1.tmp")
    tee = Rung(
        conditions=[
            [Tee(UnknownCondition(raw=b"Compare")), *["-"] * 30],
            ["|", *["-"] * 30],
        ],
        instructions=[Coil("C2"), Coil("C3")],
        comment=None,
    )
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, [_rung("C1"), tee]),
    )
    out = scr / "csv"

    result = program_save(scr, out, index=True)

    assert [(item.rung, item.instruction) for item in result.legacy_encodings] == [(2, "Compare")]
    assert [is_stand_in(rung) for rung in read_csv(out / "main.csv")] == [False, True]


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
        return Rung(conditions=[empty], instructions=[instruction], comment=comment)

    assert is_stand_in(rung(f"{STAND_IN_COMMENT}\nmore"))
    assert is_stand_in(rung(old))
    assert not is_stand_in(rung("A comment rung"))
    # A rung that does something is not a stand-in, even when its comment is the note.
    assert not is_stand_in(rung(STAND_IN_COMMENT, Coil("C1")))


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


def test_an_undecoded_marker_in_a_csv_is_never_copied(tmp_path: Path) -> None:
    def marker(rung: int, error: str) -> Rung:
        return Rung([["-"] * 31], [Undecoded(error, rung=rung, row=0)], None)

    path = tmp_path / "main.csv"
    write_csv(path, [_rung("C1"), marker(1, "bad bytes"), _rung("C3"), marker(3, "no end")])
    rungs = read_csv(path)

    with pytest.raises(UnreadableRungError) as refused:
        prepare_rungs_load(rungs, click_v4=True)
    assert str(refused.value) == (
        "Rungs 2, 4 are UNDECODED markers. CLICK cannot hold a marker.\n"
        "  rung 2: laddercodec cannot read this rung: bad bytes.\n"
        "  rung 4: laddercodec cannot read this rung: no end.\n"
        "Put the rung's logic in place of its marker, or remove the marker."
    )
    with pytest.raises(UnreadableRungError, match=r"^Rung 6 is an UNDECODED marker\. "):
        prepare_rungs_load(rungs[1:2], click_v4=True, first_rung=6)


# ---------------------------------------------------------------------------
# Rungs that the CSV cannot hold as CLICK holds them
# ---------------------------------------------------------------------------

# A compare whose cell laddercodec reads back two ways, so write_csv writes a marker for it
_TWO_WAYS = CompareContact("==", '"A"=="B"', '"C"')
_TO_THE_END = "bad record; decoding stopped, so this marker stands for rung 1 to the end"


def _marker_rung(error: str, rung: int) -> Rung:
    """Return the rung that laddercodec's decoder returns for a rung that it cannot read."""
    headline = f"UNDECODED: rung {rung}: {error}"
    return Rung([["-"] * 31], [Undecoded(error, rung=rung)], f"{headline}\nMine")


def _split_rung() -> Rung:
    """Return a rung with a NOP fed from the rail beside two outputs.

    CLICK keeps this rung whole after a paste, and after a save before Syntax Check. Only
    Syntax Check splits it. write_csv writes it as two rungs.
    """
    return Rung(
        [[Contact("X001"), *["-"] * 30], [Contact("X002"), *["-"] * 30], ["-"] * 31],
        [Coil("Y003"), Coil("Y004"), "NOP"],
        None,
    )


def _save_one_program(tmp_path: Path, monkeypatch, rungs: list[Rung]) -> tuple[Path, list]:
    (tmp_path / "Scr1.tmp").write_bytes(b"Scr1.tmp")
    monkeypatch.setattr(
        "clicknick.ladder.program.decode_program",
        lambda _data: Program("Main Program", 1, rungs),
    )
    out = tmp_path / "csv"
    result = program_save(tmp_path, out, index=True)
    return out, result.legacy_encodings


@pytest.mark.parametrize(
    ("bad", "detail"),
    [
        (
            _rung("C2", _TWO_WAYS),
            "laddercodec cannot write this rung to a CSV: no CSV cell reads back as this compare.",
        ),
        (
            _marker_rung("a wire flag has no token", 1),
            "laddercodec cannot read this rung: a wire flag has no token.",
        ),
        (
            _split_rung(),
            "CLICK's Syntax Check splits this rung into 2 rungs. Run Syntax Check in CLICK, "
            "then save the project.",
        ),
    ],
    ids=["compare-two-ways", "decoder-marker", "split"],
)
def test_save_puts_a_stand_in_for_a_rung_that_the_csv_cannot_hold(
    tmp_path: Path, monkeypatch, recwarn, bad: Rung, detail: str
) -> None:
    out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), bad, _rung("C3")])

    assert found == [LegacyEncoding("main.csv", "Main Program", 2, "", "", detail, unreadable=True)]
    rungs = read_csv(out / "main.csv")
    # The rungs keep CLICK's numbers, and nothing in the CSV is a marker
    assert [is_stand_in(rung) for rung in rungs] == [False, True, False]
    assert rungs[1].comment.split("\n")[:2] == [STAND_IN_COMMENT, detail]
    assert read_legacy_encodings(out) == tuple(found)
    assert not [w for w in recwarn if "undecoded" in str(w.message).lower()]


def test_a_marker_for_the_rest_of_the_program_names_its_rung_from_1(
    tmp_path: Path, monkeypatch
) -> None:
    out, found = _save_one_program(
        tmp_path, monkeypatch, [_rung("C1"), _marker_rung(_TO_THE_END, 1)]
    )

    [finding] = found
    assert finding.rung == 2
    assert finding.detail == (
        "laddercodec cannot read this rung, and it stopped reading the program there: bad "
        "record. The rungs after it are missing too."
    )
    # The stand-in keeps the rung's own comment, without laddercodec's headline
    assert read_csv(out / "main.csv")[1].comment.split("\n")[-1] == "Mine"


def test_the_workspace_builds_from_a_save_with_a_rung_the_csv_cannot_hold(
    tmp_path: Path, monkeypatch
) -> None:
    from pyrung.click import ladder_to_pyrung

    out, _found = _save_one_program(
        tmp_path, monkeypatch, [_rung("C1"), _rung("C2", _TWO_WAYS), _marker_rung(_TO_THE_END, 2)]
    )

    code = ladder_to_pyrung(out)

    assert "out(C1)" in code
    assert "undecoded" not in code.lower()


@pytest.mark.parametrize(
    ("bad", "line"),
    [
        (
            _rung("C2", _TWO_WAYS),
            "  copied rung 2: laddercodec cannot write this rung to a CSV: no CSV cell reads "
            "back as this compare.",
        ),
        (_split_rung(), "  copied rung 2: CLICK's Syntax Check splits this rung into 2 rungs."),
    ],
    ids=["compare-two-ways", "split"],
)
def test_clipboard_rung_that_the_csv_cannot_hold_writes_no_csv(
    tmp_path: Path, bad: Rung, line: str
) -> None:
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError) as refused:
        decode_to_csv(encode([_rung("C1"), bad]), path)

    assert line in str(refused.value)
    assert not path.exists()


def test_clipboard_marker_is_refused_before_the_csv_or_the_mdb(tmp_path: Path, monkeypatch):
    marker = _marker_rung(_TO_THE_END, 1)
    monkeypatch.setattr("clicknick.ladder.program.decode", lambda _data: [_rung("C1"), marker])
    detail = (
        "laddercodec cannot read this rung, and it stopped reading the program there: bad "
        "record. The rungs after it are missing too."
    )

    with pytest.raises(UnreadableRungError, match=f"  copied rung 2: {detail}"):
        decode_to_csv(b"clip", tmp_path / "copied.csv")
    # clicknick-rung load takes its "could not decode" branch on this ValueError
    with pytest.raises(ValueError, match=f"^rung 2: {detail}$"):
        prepare_bin_load(b"clip", click_v4=True)


def test_clipboard_value_that_clicks_editor_refuses_writes_no_csv(tmp_path: Path) -> None:
    """laddercodec decodes DH70 == DS39 as a compare and warns that CLICK's editor refuses it.

    A CSV of it would not read back, so ClickNick writes none, as 0.25.0 did.
    """
    data = encode(_rung("C1", CompareContact("==", "DH70", "DH71")))
    data = data.replace("DH71".encode("utf-16-le"), "DS39".encode("utf-16-le"))
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError, match=r"copied rung 1: CompareContact\.left: 'DH70'"):
        decode_to_csv(data, path)

    assert not path.exists()


def test_save_with_a_value_that_clicks_editor_refuses_pastes_the_program_whole(
    tmp_path: Path, monkeypatch
) -> None:
    """The save writes the compare, which laddercodec cannot read back from the CSV.

    So the finding is about the whole copy, and Review Changes pastes the program whole.
    """
    data = encode(_rung("C2", CompareContact("==", "DH70", "DH71")))
    data = data.replace("DH71".encode("utf-16-le"), "DS39".encode("utf-16-le"))
    with pytest.warns(UserWarning):
        [refused] = decode(data)

    _out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), refused])

    [finding] = found
    assert (finding.rung, finding.unreadable) == (None, True)
    assert finding.detail.startswith(
        "ClickNick cannot read CLICK's copy of this program. CompareContact.left: 'DH70' (hex)"
    )
    assert "(at " not in finding.detail


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
    # laddercodec's reason ends with the path of the CSV, and this save writes into tmp_path
    [again] = read_legacy_encodings(tmp_path)
    assert (
        "Paste these programs into CLICK again from your own copy, or fix them in CLICK:\n"
        f"  Main Program: {again.detail}"
    ) in printed
    assert "ClickNick cannot read these rungs" not in printed
