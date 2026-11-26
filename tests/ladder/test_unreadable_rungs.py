"""Test rungs that laddercodec cannot read, such as a compare that CLICK's own dialog refuses.

An older laddercodec pasted these rungs into CLICK. The current one decodes the
cell as ``UnknownCondition``, which has no CSV token.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
from laddercodec import (
    Call,
    Coil,
    CompareContact,
    Contact,
    ForLoop,
    LegacyEncodingWarning,
    Next,
    Program,
    RefusedFieldWarning,
    Rung,
    Tee,
    Undecoded,
    UndecodedCommentWarning,
    UndecodedRungWarning,
    UnknownCondition,
    UnknownInstruction,
    decode,
    decode_program,
    encode,
    marker_rung,
    read_csv,
    write_csv,
)

from clicknick.ladder.cli import main
from clicknick.ladder.program import (
    LEGACY_ENCODINGS_FILE,
    STAND_IN_COMMENT,
    UNREAD_COMMENTS_FILE,
    LegacyEncoding,
    UnreadableRungError,
    UnreadComment,
    decode_to_csv,
    describe_legacy_encoding,
    is_marker,
    is_stand_in,
    prepare_bin_load,
    prepare_rungs_load,
    program_save,
    read_legacy_encodings,
    read_unread_comments,
    stand_in_findings,
    stand_in_fix,
)

DETAIL = "ClickNick cannot read this Compare."


def test_the_fix_for_several_rungs_names_the_rungs_in_the_list() -> None:
    """Some listed rungs are ones that ClickNick can read but cannot copy unchanged."""
    found = [
        LegacyEncoding("main.csv", "Main Program", number, "Compare", "", DETAIL, True)
        for number in (2, 4)
    ]

    assert stand_in_fix(found, one=False) == (
        "Do this in CLICK for each rung in the list: click its number to select the rung, and "
        "paste the rung again from your own copy of the program. Or fix them in CLICK."
    )


def _rung(coil: str, first=None, comment: str | None = None) -> Rung:
    conditions: list = ["-"] * 31
    if first is not None:
        conditions[0] = first
    return Rung(
        conditions=[conditions],
        instructions=[Coil(coil)],
        comment=comment,
    )


def _call(name: str) -> Rung:
    return Rung(conditions=[["-"] * 31], instructions=[Call(name)], comment=None)


def _for(first=None) -> Rung:
    conditions: list = ["-"] * 31
    if first is not None:
        conditions[0] = first
    return Rung(conditions=[conditions], instructions=[ForLoop("3")], comment=None)


def _next(first=None) -> Rung:
    conditions: list = ["-"] * 31
    if first is not None:
        conditions[0] = first
    return Rung(conditions=[conditions], instructions=[Next()], comment=None)


# A rung condition that laddercodec could not decode. Its raw bytes name the instruction,
# "Compare". `_instruction_name` in src/clicknick/ladder/program.py reads that name.
_REFUSED = UnknownCondition(raw=b"Compare")


def _build_program(csv_dir: Path):
    """Convert *csv_dir* to pyrung source and run it, as the workspace build does.

    Return the source and the Program that it builds. Raise what the conversion or the source
    raises.
    """
    from pyrung import Program
    from pyrung.click import ladder_to_pyrung

    code = ladder_to_pyrung(csv_dir)
    namespace: dict = {}
    exec(compile(code, "<analysis>", "exec"), namespace)  # noqa: S102
    assert isinstance(namespace["logic"], Program)
    return code, namespace["logic"]


def _build(csv_dir: Path) -> str:
    """Build *csv_dir* as the workspace build does, and return the pyrung source."""
    return _build_program(csv_dir)[0]


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


def test_each_unreadable_rung_becomes_a_marker_so_the_rest_keep_their_numbers(
    scr: Path,
) -> None:
    out = scr / "csv"
    program_save(scr, out, index=True)

    rungs = read_csv(out / "subroutines" / "Conf_Compare.csv")

    assert len(rungs) == 4
    # In a subroutine the marker returns to the caller. Its rung counts from 0, as in
    # laddercodec, so pyrung names the CLICK rung from 1.
    assert [rung.instructions for rung in rungs] == [
        (Coil("C10"),),
        (Undecoded(DETAIL, rung=1, stop="return"),),
        (Undecoded(DETAIL, rung=2, stop="return"),),
        (Coil("C13"),),
    ]
    assert not any(is_stand_in(rung) for rung in rungs)
    # The rung's own comment stays below laddercodec's headline, so the user can tell which
    # rung it was
    assert rungs[1].comment == f"UNDECODED: CLICK rung 2: {DETAIL}\nCase compare/hex_vs_int"


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
    code = _build(out)
    assert "from pyrung.click import ClickBlocks, TagMap, undecoded\n" in code
    assert f'undecoded("{DETAIL}", rung=1, stop="end")' in code
    assert "out(C2)" not in code
    assert "out(C3)" in code
    assert STAND_IN_COMMENT not in code


def test_cli_save_lists_the_rungs_to_paste_again(scr: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["clicknick-cli", "program", "save", str(scr)])

    main()

    out = capsys.readouterr().out
    assert (
        "ClickNick cannot copy these rungs from CLICK as they are. Each program's CSV holds an"
        " UNDECODED marker in place of each of these rungs. Inside a For loop, the CSV holds an"
        " empty rung instead."
    ) in out
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
    assert [is_marker(rung) for rung in read_csv(out / "main.csv")] == [False, True]


def test_readable_clipboard_rung_is_written(tmp_path: Path) -> None:
    path = tmp_path / "copied.csv"

    decode_to_csv(encode(_rung("C1", CompareContact("==", "DH70", "DH71"))), path)

    assert read_csv(path)[0].conditions[0][0] == CompareContact("==", "DH70", "DH71")


# ---------------------------------------------------------------------------
# Copying a stand-in
# ---------------------------------------------------------------------------


def test_a_marker_from_a_save_is_never_copied_over_the_rung_it_stands_for(scr: Path) -> None:
    out = scr / "csv"
    program_save(scr, out, index=True)
    rungs = read_csv(out / "subroutines" / "Conf_Compare.csv")

    with pytest.raises(UnreadableRungError, match=r"^Rungs 2, 3 are UNDECODED markers\. "):
        prepare_rungs_load(rungs, click_v4=True)
    with pytest.raises(UnreadableRungError, match=r"^Rung 6 is an UNDECODED marker\. "):
        prepare_rungs_load(rungs[1:2], click_v4=True, first_rung=6)
    assert prepare_rungs_load(rungs[:1], click_v4=True).rung_count == 1


def test_a_stand_in_in_a_loop_is_never_copied_over_the_rung_it_stands_for(
    tmp_path: Path, monkeypatch
) -> None:
    out, _found = _save_one_program(
        tmp_path, monkeypatch, [_for(), _rung("C2", _REFUSED), _next(), _rung("C4")]
    )
    rungs = read_csv(out / "main.csv")

    with pytest.raises(UnreadableRungError) as refused:
        prepare_rungs_load(rungs, click_v4=True)
    # CLICK replaces a rung with a paste only when the rung is selected, so the click
    # comes before the paste
    assert str(refused.value) == (
        "Rung 2 is an empty rung that stands in for a rung ClickNick cannot read from CLICK. "
        "Click that rung's number in CLICK to select the rung. Then paste the rung again from "
        "your own copy of the program. Or fix it in CLICK."
    )
    with pytest.raises(UnreadableRungError, match=r"^Rung 6 is an empty rung"):
        prepare_rungs_load(rungs[1:2], click_v4=True, first_rung=6)


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
    # Only a rung inside a For loop gets a stand-in
    rungs = [_rung("C1"), _for(), _rung("C3", _REFUSED, comment="Mine"), _next(), _rung("C5")]
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

    assert [is_stand_in(rung) for rung in exported[:5]] == [False, False, True, False, False]
    with pytest.raises(UnreadableRungError, match=r"^Rung 3 is an empty rung"):
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
        "Write each rung's logic in place of its marker. Or do this in CLICK for each rung that "
        "ClickNick cannot read: click its number to select the rung, and paste the rung again. "
        "Then save."
    )
    with pytest.raises(UnreadableRungError) as refused:
        prepare_rungs_load(rungs[1:2], click_v4=True, first_rung=6)
    assert str(refused.value).startswith("Rung 6 is an UNDECODED marker. ")
    assert str(refused.value).endswith(
        "Write the rung's logic in place of its marker. Or click that rung's number in CLICK "
        "to select the rung. Then paste the rung again and save."
    )


# ---------------------------------------------------------------------------
# Rungs that the CSV cannot hold as CLICK holds them
# ---------------------------------------------------------------------------

# A compare whose cell laddercodec reads back two ways, so write_csv writes a marker for it
_TWO_WAYS = CompareContact("==", '"A"=="B"', '"C"')


def _marker_rung(error: str, rung: int, stop: str = "end", *, to_the_end: bool = False) -> Rung:
    """Return the rung that laddercodec's decoder returns for a rung that it cannot read.

    laddercodec's ``marker_rung`` writes the headline. The rung's own comment, "Mine",
    follows it. *stop* is what the marker acts as: "end" in the main program, "return" in a
    subroutine. If *to_the_end* is True, the marker stands for every rung after it too.
    """
    marker = Undecoded(error, rung=rung, stop=stop, to_the_end=to_the_end)
    return marker_rung(marker, "Mine")


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


def _save_one_program(
    tmp_path: Path, monkeypatch, rungs: list[Rung], warned: tuple[Warning, ...] = ()
) -> tuple[Path, list]:
    """Save a project whose one program holds *rungs*. The decoder issues *warned*."""
    (tmp_path / "Scr1.tmp").write_bytes(b"Scr1.tmp")

    def decode_program(_data: bytes) -> Program:
        for warning in warned:
            warnings.warn(warning, stacklevel=1)
        return Program("Main Program", 1, rungs)

    monkeypatch.setattr("clicknick.ladder.program.decode_program", decode_program)
    out = tmp_path / "csv"
    result = program_save(tmp_path, out, index=True)
    return out, result.legacy_encodings


_TWO_WAYS_DETAIL = (
    "laddercodec cannot write this rung to a CSV: no CSV cell reads back as this compare."
)
_SPLIT_DETAIL = (
    "CLICK's Syntax Check splits this rung into 2 rungs. Run Syntax Check in CLICK, "
    "then save the project."
)


@pytest.mark.parametrize(
    ("bad", "detail", "error"),
    [
        (_rung("C2", _TWO_WAYS), _TWO_WAYS_DETAIL, _TWO_WAYS_DETAIL),
        (
            _marker_rung("a wire flag has no token", 1),
            "laddercodec cannot read this rung: a wire flag has no token.",
            "a wire flag has no token",
        ),
        (_split_rung(), _SPLIT_DETAIL, _SPLIT_DETAIL),
    ],
    ids=["compare-two-ways", "decoder-marker", "split"],
)
def test_save_puts_a_marker_for_a_rung_that_the_csv_cannot_hold(
    tmp_path: Path, monkeypatch, recwarn, bad: Rung, detail: str, error: str
) -> None:
    out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), bad, _rung("C3")])

    assert found == [LegacyEncoding("main.csv", "Main Program", 2, "", "", detail, unreadable=True)]
    # laddercodec reads the marker back with no warning. So the save adds no finding for the
    # whole program. Review Changes reads CLICK's copy with the same call.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        rungs = read_csv(out / "main.csv")
    # The rungs keep CLICK's numbers. The decoder's own marker keeps its reason.
    assert [rung.instructions for rung in rungs] == [
        (Coil("C1"),),
        (Undecoded(error, rung=1),),
        (Coil("C3"),),
    ]
    assert rungs[1].comment.split("\n")[0] == f"UNDECODED: CLICK rung 2: {error}"
    assert read_legacy_encodings(out) == tuple(found)
    # ClickNick writes the marker itself, so write_csv has nothing to warn about
    assert not [w for w in recwarn if "undecoded" in str(w.message).lower()]


def test_a_marker_for_the_rest_of_the_program_names_its_rung_from_1(
    tmp_path: Path, monkeypatch
) -> None:
    marker = _marker_rung("bad record", 1, to_the_end=True)
    out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), marker])

    [finding] = found
    assert finding.rung == 2
    assert finding.detail == (
        "laddercodec cannot read this rung, and it stopped reading the program there: bad "
        "record. The rungs after it are missing too."
    )
    # The save writes the decoder's marker as it is: laddercodec's headline, with the rung's
    # own comment below it
    assert read_csv(out / "main.csv")[1].comment == marker.comment


def test_the_workspace_builds_from_a_save_with_a_rung_the_csv_cannot_hold(
    tmp_path: Path, monkeypatch
) -> None:
    out, _found = _save_one_program(
        tmp_path,
        monkeypatch,
        [_rung("C1"), _rung("C2", _TWO_WAYS), _marker_rung("bad record", 2, to_the_end=True)],
    )

    code = _build(out)

    assert "out(C1)" in code
    assert f'undecoded("{_TWO_WAYS_DETAIL}", rung=1, stop="end")' in code


def test_a_marker_in_a_subroutine_returns(tmp_path: Path, monkeypatch) -> None:
    """In a subroutine, the marker that ClickNick writes and the decoder's own both return."""

    (tmp_path / "Scr1.tmp").write_bytes(b"Scr1.tmp")
    (tmp_path / "Scr2.tmp").write_bytes(b"Scr2.tmp")
    programs = {
        b"Scr1.tmp": Program("Main Program", 1, [_rung("C1"), _call("Fill")]),
        b"Scr2.tmp": Program(
            "Fill",
            2,
            [
                _rung("C10"),
                _rung("C11", _REFUSED),
                _marker_rung("bad record", 2, stop="return"),
                _rung("C13"),
            ],
        ),
    }
    monkeypatch.setattr("clicknick.ladder.program.decode_program", programs.__getitem__)
    out = tmp_path / "csv"

    result = program_save(tmp_path, out, index=True)

    assert [(item.file, item.rung) for item in result.legacy_encodings] == [
        ("subroutines/Fill.csv", 2),
        ("subroutines/Fill.csv", 3),
    ]
    assert [rung.instructions for rung in read_csv(out / "subroutines" / "Fill.csv")] == [
        (Coil("C10"),),
        (Undecoded(DETAIL, rung=1, stop="return"),),
        (Undecoded("bad record", rung=2, stop="return"),),
        (Coil("C13"),),
    ]
    code = _build(out)
    assert f'undecoded("{DETAIL}", rung=1, stop="return")' in code


# ---------------------------------------------------------------------------
# For loops
#
# pyrung refuses a marker inside a For loop. It refuses a next() with no for() above it, unless
# a marker stands above that next(). The save writes an empty stand-in inside a loop and for an
# unreadable next(). It writes a marker for an unreadable for() outside a loop. The tests that
# build the workspace pin what pyrung does with each case, so that a change in pyrung fails
# here.
# ---------------------------------------------------------------------------

# pyrung's message for a next() with no for() and no marker above it
_ADD_THE_FOR = (
    r"this next\(\) has no for\(\) above it\. Either the program has no for\(\) rung, or "
    r"laddercodec could not read the rung that held it\. Add the for\(\) rung in CLICK, or "
    r"remove the next\(\), then read the program again\."
)


def _kinds(rungs: list[Rung]) -> str:
    """Return a letter for each rung: M for a marker, S for a stand-in, - for any other rung."""
    return "".join("M" if is_marker(rung) else "S" if is_stand_in(rung) else "-" for rung in rungs)


def test_an_unreadable_rung_in_a_for_loop_gets_a_stand_in_and_the_workspace_builds(
    tmp_path: Path, monkeypatch
) -> None:
    rungs = [_for(), _rung("C2"), _rung("C3", _REFUSED), _next(), _rung("C5")]
    out, found = _save_one_program(tmp_path, monkeypatch, rungs)

    # The finding still names the rung, as it does for a marker
    assert found == [LegacyEncoding("main.csv", "Main Program", 3, "Compare", "", DETAIL, True)]
    assert read_legacy_encodings(out) == tuple(found)
    assert _kinds(read_csv(out / "main.csv")) == "--S--"
    code = _build(out)
    assert "with forloop(3):" in code
    assert STAND_IN_COMMENT in code
    assert "out(C5)" in code
    assert "undecoded" not in code


def test_an_unreadable_for_gets_a_marker_and_the_program_stops_there(
    tmp_path: Path, monkeypatch
) -> None:
    """A next() below the marker builds, and the Program ends at the marker.

    pyrung reads the next() as a placeholder and names its rung in the marker's ``lone_next``.
    With a stand-in in place of the for(), pyrung would refuse the next(). pyrung 0.18.0 refuses
    it too. Its source holds a ``next()`` with no ``for()`` above it, and running that source
    raises ``TypeError``.
    """

    out, found = _save_one_program(
        tmp_path, monkeypatch, [_for(_REFUSED), _rung("C2"), _next(), _rung("C4")]
    )

    assert found == [LegacyEncoding("main.csv", "Main Program", 1, "Compare", "", DETAIL, True)]
    assert _kinds(read_csv(out / "main.csv")) == "M---"
    code, logic = _build_program(out)
    assert 'stop="end", lone_next=[2])' in code
    assert "CLICK rung 3 is a next() with no for() above it." in code
    assert len(logic.rungs) == 1


def test_a_decoder_marker_before_a_next_gets_the_same_placeholder(
    tmp_path: Path, monkeypatch
) -> None:
    out, _found = _save_one_program(
        tmp_path,
        monkeypatch,
        [_marker_rung("bad record", 0), _rung("C2"), _next(), _rung("C4")],
    )

    code, logic = _build_program(out)
    assert 'stop="end", lone_next=[2])' in code
    assert len(logic.rungs) == 1


def test_an_unreadable_next_gets_a_stand_in_and_the_workspace_builds(
    tmp_path: Path, monkeypatch
) -> None:
    """With no next(), pyrung runs the loop to the end of the program."""

    out, found = _save_one_program(
        tmp_path, monkeypatch, [_for(), _rung("C2"), _next(_REFUSED), _rung("C4")]
    )

    assert found == [LegacyEncoding("main.csv", "Main Program", 3, "Compare", "", DETAIL, True)]
    assert _kinds(read_csv(out / "main.csv")) == "--S-"
    code = _build(out)
    assert "with forloop(3):" in code
    assert STAND_IN_COMMENT in code
    assert "out(C4)" in code


@pytest.mark.parametrize(
    ("rungs", "kinds", "refused"),
    [
        # The stand-in for the next() closes nothing, so the loop goes on in pyrung
        pytest.param(
            [_for(), _rung("C2"), _next(_REFUSED), _rung("C4", _REFUSED)],
            "--SS",
            None,
            id="after-an-unreadable-next",
        ),
        pytest.param(
            [_for(), _for(), _next(_REFUSED), _next(), _rung("C5", _REFUSED)],
            "--S-S",
            None,
            id="nested-after-an-unreadable-next",
        ),
        pytest.param(
            [_for(), _for(), _rung("C3", _REFUSED), _next(), _next(), _rung("C6", _REFUSED)],
            "--S--M",
            None,
            id="nested",
        ),
        # The stand-in for the inner for() opens nothing, so the inner next() closes the
        # outer loop in pyrung
        pytest.param(
            [_for(), _for(_REFUSED), _rung("C3"), _next(), _next(), _rung("C6", _REFUSED)],
            "-S---M",
            f"rung 5: {_ADD_THE_FOR}",
            id="unreadable-for-in-a-loop",
        ),
        pytest.param(
            [_rung("C1"), _next(), _rung("C3", _REFUSED)],
            "--M",
            f"rung 2: {_ADD_THE_FOR}",
            id="unpaired-next",
        ),
        pytest.param(
            [_rung("C1"), _next(_REFUSED), _rung("C3", _REFUSED)],
            "-SM",
            None,
            id="unreadable-unpaired-next",
        ),
        pytest.param(
            [_for(), _rung("C2"), _rung("C3", _REFUSED)],
            "--S",
            None,
            id="unclosed-for",
        ),
        # The decoder's marker cannot say whether the rung held a for(), so pyrung accepts the
        # next() below it
        pytest.param(
            [_marker_rung("bad record", 0), _rung("C2"), _next(), _rung("C4")],
            "M---",
            None,
            id="decoder-marker-before-a-next",
        ),
        pytest.param(
            [_for(), _marker_rung("bad record", 1), _next(), _rung("C4")],
            "-S--",
            None,
            id="decoder-marker-in-a-loop",
        ),
    ],
)
def test_the_save_reads_loops_from_the_rungs_that_it_writes(
    tmp_path: Path, monkeypatch, rungs: list[Rung], kinds: str, refused: str | None
) -> None:
    """A for() or a next() opens or closes a loop only if the save writes it unchanged.

    pyrung reads the loops from the CSV that the save writes, so the save reads them the same
    way.
    """

    out, _found = _save_one_program(tmp_path, monkeypatch, rungs)

    assert _kinds(read_csv(out / "main.csv")) == kinds
    if refused is None:
        _build(out)
    else:
        with pytest.raises(ValueError, match=refused):
            _build(out)


def test_a_project_with_a_marker_and_a_stand_in_in_a_loop(tmp_path: Path, monkeypatch) -> None:
    rungs = [
        _rung("C1"),
        _for(),
        _rung("C3", _REFUSED),
        _next(),
        _rung("C5", _REFUSED),
        _rung("C6"),
    ]
    out, found = _save_one_program(tmp_path, monkeypatch, rungs)

    assert [(item.rung, item.detail) for item in found] == [(3, DETAIL), (5, DETAIL)]
    saved = read_csv(out / "main.csv")
    assert [is_stand_in(rung) for rung in saved] == [False, False, True, False, False, False]
    assert [is_marker(rung) for rung in saved] == [False, False, False, False, True, False]
    code = _build(out)
    assert STAND_IN_COMMENT in code
    assert f'undecoded("{DETAIL}", rung=4, stop="end")' in code


def test_stand_in_findings_leave_out_the_rung_held_as_a_marker(tmp_path: Path, monkeypatch) -> None:
    rungs = [_rung("C1"), _for(), _rung("C3", _REFUSED), _next(), _rung("C5", _REFUSED)]
    out, _found = _save_one_program(tmp_path, monkeypatch, rungs)

    assert [item.rung for item in stand_in_findings(out)] == [3]


def test_stand_in_findings_count_a_rung_that_the_csv_does_not_show(
    tmp_path: Path, monkeypatch
) -> None:
    """Refuse as before if the CSV is gone, or if it holds fewer rungs than the finding says."""
    out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), _rung("C2", _REFUSED)])
    assert stand_in_findings(out) == []

    write_csv(out / "main.csv", [_rung("C1")])
    assert stand_in_findings(out) == found

    (out / "main.csv").unlink()
    assert stand_in_findings(out) == found


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
    marker = _marker_rung("bad record", 1, to_the_end=True)
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
    with pytest.warns(RefusedFieldWarning) as caught:
        [refused] = decode(data)
    first = caught[0].message
    # As decode_program warns: the rung is the second of its program
    warning = RefusedFieldWarning(first.instruction, first.errors, 1, "Main Program")

    _out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), refused], (warning,))

    # One finding: the read-back of the CSV would say the same again
    [finding] = found
    assert (finding.rung, finding.unreadable) == (None, True)
    assert finding.detail.startswith(
        "ClickNick cannot read CLICK's copy of this program. CompareContact.left: 'DH70' (hex)"
    )
    assert "(at " not in finding.detail


def test_a_marker_that_the_decoder_warns_about_gets_one_finding(tmp_path: Path, monkeypatch):
    marker = _marker_rung("a wire flag has no token", 1)
    warning = UndecodedRungWarning(marker.instructions[0], "Main Program")

    _out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), marker], (warning,))

    assert [(item.rung, item.detail) for item in found] == [
        (2, "laddercodec cannot read this rung: a wire flag has no token.")
    ]


def test_a_comment_that_laddercodec_cannot_read_is_left_out_of_the_save(
    tmp_path: Path, monkeypatch
) -> None:
    """The rung keeps its logic and loses its comment, with no finding, as in 0.25.0."""
    rung = _rung("C2", comment="UNDECODED comment: bad RTF\nMixer start")
    warning = UndecodedCommentWarning(1, "bad RTF", "Main Program")

    out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1"), rung], (warning,))

    assert found == []
    assert read_csv(out / "main.csv") == [_rung("C1"), _rung("C2")]
    # Review Changes reads the record to ask before a paste erases the comment in CLICK
    assert read_unread_comments(out) == (UnreadComment("main.csv", "Main Program", 2),)


def test_a_comment_with_no_rung_is_recorded_and_the_program_is_pasted_whole(
    tmp_path: Path, monkeypatch
) -> None:
    rung = _rung("C1", comment="UNDECODED comment: bad RTF")
    # laddercodec names a rung that the program does not have
    warning = UndecodedCommentWarning(7, "bad RTF", "Main Program")

    out, found = _save_one_program(tmp_path, monkeypatch, [rung], (warning,))

    assert [(item.rung, item.unreadable) for item in found] == [(None, True)]
    assert read_unread_comments(out) == (UnreadComment("main.csv", "Main Program", None),)


def test_a_save_that_leaves_out_no_comment_removes_the_record(tmp_path: Path, monkeypatch) -> None:
    rung = _rung("C1", comment="UNDECODED comment: bad RTF")
    warning = UndecodedCommentWarning(0, "bad RTF", "Main Program")
    out, _found = _save_one_program(tmp_path, monkeypatch, [rung], (warning,))
    assert (out / UNREAD_COMMENTS_FILE).is_file()

    _save_one_program(tmp_path, monkeypatch, [_rung("C1", comment="Mixer start")])

    assert not (out / UNREAD_COMMENTS_FILE).exists()
    assert read_unread_comments(out) == ()


class _NewWarning(UserWarning):
    """A warning that a later laddercodec might issue, which ClickNick has no rule for."""

    def __init__(self, rung: int | None) -> None:
        self.rung = rung
        super().__init__("something new")


_NewWarning.__module__ = "laddercodec.future"


def test_a_laddercodec_warning_with_no_rule_counts_as_unreadable(tmp_path: Path, monkeypatch):
    on_rung, on_program = _NewWarning(0), _NewWarning(None)

    _out, found = _save_one_program(tmp_path, monkeypatch, [_rung("C1")], (on_rung, on_program))

    detail = "laddercodec warned about this rung: something new."
    assert [(item.rung, item.detail, item.unreadable) for item in found] == [
        (None, f"ClickNick cannot read CLICK's copy of this program. {detail}", True),
        (1, detail, True),
    ]


def test_an_empty_flag_on_the_clipboard_stays_a_warning(tmp_path: Path, monkeypatch) -> None:
    legacy = LegacyEncodingWarning("Coil.oneshot", "", "the flag is stored empty.", 0)

    def decode(_data: bytes) -> list[Rung]:
        warnings.warn(legacy, stacklevel=1)
        return [_rung("C1")]

    monkeypatch.setattr("clicknick.ladder.program.decode", decode)
    path = tmp_path / "copied.csv"

    with pytest.warns(LegacyEncodingWarning, match="Coil.oneshot"):
        decode_to_csv(b"clip", path)

    assert read_csv(path)[0].instructions == (Coil("C1"),)


def test_clipboard_comment_that_laddercodec_cannot_read_writes_no_csv(
    tmp_path: Path, monkeypatch
) -> None:
    def decode(_data: bytes) -> list[Rung]:
        warnings.warn(UndecodedCommentWarning(0, "bad RTF"), stacklevel=1)
        return [_rung("C1", comment="UNDECODED comment: bad RTF")]

    monkeypatch.setattr("clicknick.ladder.program.decode", decode)
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError, match="copied rung 1: laddercodec cannot read this"):
        decode_to_csv(b"clip", path)
    assert not path.exists()


_CAPTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures"


def _partly_readable(name: str) -> bytes:
    """Return laddercodec's capture *name*, with its comment's font made one it reads in part.

    ``simsun.bin`` and ``simsun.scr`` come from laddercodec's ``tests/fixtures/rung_comments``.
    CLICK 4.00 copied and saved one rung, a contact on X001 and ``out(Y001)``, with the comment
    中 in font 0, SimSun, ``\\fcharset134``. The test changes that font to ``\\fcharset136``.
    laddercodec reads no font of that charset, so it reads the comment in part.
    """
    data = (_CAPTURES / name).read_bytes()
    assert data.count(b"\\fcharset134") == 1
    return data.replace(b"\\fcharset134", b"\\fcharset136")


def _comment_warning(decode_bytes) -> UndecodedCommentWarning:
    """Run *decode_bytes*, and return the one warning about a comment that laddercodec issues."""
    with warnings.catch_warnings(record=True) as found:
        warnings.simplefilter("always")
        decode_bytes()
    [warning] = [item.message for item in found]
    assert isinstance(warning, UndecodedCommentWarning)
    assert warning.partial
    return warning


def test_save_clipboard_refuses_a_comment_that_laddercodec_reads_in_part(tmp_path: Path) -> None:
    """The CSV would hold U+FFFD in place of the text, and a paste would write that to CLICK."""
    data = _partly_readable("simsun.bin")
    warning = _comment_warning(lambda: decode(data))
    path = tmp_path / "copied.csv"

    with pytest.raises(UnreadableRungError) as refused:
        decode_to_csv(data, path)

    reason = warning.error.splitlines()[0].rstrip(".")
    assert str(refused.value) == (
        "ClickNick cannot read these rungs, so it wrote no CSV:\n"
        f"  copied rung 1: laddercodec cannot read part of this rung's comment: {reason}.\n"
        "Fix them in CLICK and copy them again."
    )
    assert not path.exists()


def test_a_comment_that_laddercodec_reads_in_part_is_left_out_of_the_save(tmp_path: Path) -> None:
    data = _partly_readable("simsun.scr")
    _comment_warning(lambda: decode_program(data))
    (tmp_path / "Scr1.tmp").write_bytes(data)
    out = tmp_path / "csv"

    result = program_save(tmp_path, out, index=True)

    assert result.legacy_encodings == []
    [rung] = read_csv(out / "main.csv")
    assert rung.comment is None
    assert rung.instructions == (Coil("Y001"),)
    assert [(item.file, item.rung) for item in read_unread_comments(out)] == [("main.csv", 1)]
    assert read_unread_comments(out) == tuple(result.unread_comments)


def test_a_bin_load_passes_on_warnings_other_than_a_marker(monkeypatch) -> None:
    """The payload is CLICK's own bytes, and the operands are known, so the load goes on."""
    data = encode(_rung("C1", CompareContact("==", "DH70", "DH71")))
    data = data.replace("DH71".encode("utf-16-le"), "DS39".encode("utf-16-le"))
    provisioned: list[list[str]] = []

    def provision(addresses, *, mdb_path=None):
        provisioned.append(addresses)
        return 0, None, None

    monkeypatch.setattr("clicknick.ladder.program._provision_mdb_addresses", provision)

    with pytest.warns(RefusedFieldWarning):
        result = prepare_bin_load(data, click_v4=True)

    assert result.payload == data
    assert provisioned == [result.addresses]
    assert {"DH70", "DS39", "C1"} <= set(result.addresses)


def test_a_bin_load_passes_on_a_comment_that_laddercodec_cannot_read(monkeypatch) -> None:
    def decode(_data: bytes) -> list[Rung]:
        warnings.warn(UndecodedCommentWarning(0, "bad RTF"), stacklevel=1)
        return [_rung("C1", comment="UNDECODED comment: bad RTF")]

    monkeypatch.setattr("clicknick.ladder.program.decode", decode)

    with pytest.warns(UndecodedCommentWarning):
        result = prepare_bin_load(b"clip", click_v4=True)

    assert result.payload == b"clip"


def test_paste_refuses_a_comment_that_laddercodec_could_not_read() -> None:
    rungs = [_rung("C1"), _rung("C2", comment="UNDECODED comment: bad RTF\nMixer start")]

    with pytest.raises(UnreadableRungError) as refused:
        prepare_rungs_load(rungs, click_v4=True, first_rung=3)

    assert str(refused.value) == (
        'Rung 4 has a comment that starts with laddercodec\'s "UNDECODED comment:" line.'
        " laddercodec could not read the comment that CLICK held there. Delete that line, or"
        " put back the comment."
    )


def test_paste_refuses_rungs_that_laddercodec_warns_about_as_it_encodes(monkeypatch) -> None:
    def encode(_rungs, **_kwargs) -> bytes:
        warnings.warn(_NewWarning(1), stacklevel=1)
        return b"payload"

    monkeypatch.setattr("clicknick.ladder.program.encode", encode)

    with pytest.raises(UnreadableRungError) as refused:
        prepare_rungs_load([_rung("C1"), _rung("C2")], click_v4=True, first_rung=5)

    assert str(refused.value) == (
        "ClickNick cannot copy these rungs into CLICK as they are:\n"
        "  rung 6: laddercodec warned about this rung: something new."
    )


def test_warnings_from_anything_but_laddercodec_pass_through() -> None:
    from clicknick.ladder.codec_warnings import recording

    with pytest.warns(DeprecationWarning, match="not laddercodec"):
        with recording() as found:
            warnings.warn("not laddercodec", DeprecationWarning, stacklevel=1)

    assert found == []


def test_a_python_warning_raised_inside_laddercodec_passes_through() -> None:
    """Only a UserWarning is laddercodec's by where it was raised, not a DeprecationWarning."""
    import laddercodec

    from clicknick.ladder.codec_warnings import recording

    inside = str(Path(laddercodec.__file__).resolve().parent / "decode.py")
    with pytest.warns(DeprecationWarning, match="old call"):
        with recording() as found:
            warnings.warn_explicit("old call", DeprecationWarning, inside, 1)
            warnings.warn_explicit("lost a row", UserWarning, inside, 1)

    assert [str(warning) for warning in found] == ["lost a row"]


def test_two_threads_never_record_at_once() -> None:
    """The build worker and the Tk thread both call laddercodec. Neither takes the other's
    warning, and the warning filters are as they were afterwards."""
    import threading
    import time

    from clicknick.ladder.codec_warnings import recording

    filters = list(warnings.filters)
    showwarning = warnings.showwarning
    build_in, tk_trying, tk_in = threading.Event(), threading.Event(), threading.Event()
    lists: dict[str, list[Warning]] = {}
    overlap: list[bool] = []

    def build() -> None:
        with recording() as found:
            build_in.set()
            assert tk_trying.wait(5)
            time.sleep(0.05)  # the Tk thread is waiting for the lock by now
            overlap.append(tk_in.is_set())
            warnings.warn(UndecodedCommentWarning(3, "bad RTF", "Main Program"), stacklevel=1)
        lists["build"] = found

    def tk() -> None:
        assert build_in.wait(5)
        tk_trying.set()
        with recording() as found:
            tk_in.set()
        lists["tk"] = found

    threads = [threading.Thread(target=build), threading.Thread(target=tk)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert overlap == [False]
    assert [type(warning) for warning in lists["build"]] == [UndecodedCommentWarning]
    assert lists["tk"] == []
    assert warnings.filters == filters
    assert warnings.showwarning is showwarning


def test_a_rung_summary_passes_on_what_laddercodec_warns(monkeypatch) -> None:
    from clicknick.services.rung_diff import _rung_summary

    def csv_rows(_rungs, **_kwargs):
        warnings.warn(_NewWarning(0), stacklevel=1)
        return [["R", "out(C1)"]]

    monkeypatch.setattr("clicknick.services.rung_diff.csv_rows", csv_rows)

    with pytest.warns(_NewWarning):
        assert _rung_summary(_rung("C1")) == "  out(C1)"


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
    assert (
        "Paste these programs into CLICK again from your own copy, or fix them in CLICK:\n"
        f"  Main Program: {found.detail}\n"
        # A paste replaces at most the selected rung, so CLICK's old rungs must go first
        "To paste a program again, first delete all its rungs. In CLICK, click rung 1's "
        "number and press Shift+Down until the last rung is shaded too. Press Delete. Then "
        "paste the program.\n"
    ) in printed
    assert "ClickNick cannot copy these rungs" not in printed
