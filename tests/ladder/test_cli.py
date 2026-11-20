"""Tests for ladder CLI and program service functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from laddercodec import (
    BlockCopy,
    Break,
    Coil,
    CompareContact,
    Contact,
    Program,
    Rung,
    Tee,
    Timer,
    Undecoded,
    write_csv,
)

from clicknick.ladder.cli import (
    _append_result,
    _load_bin,
    _read_progress,
    _run_guided,
    _save_and_compare,
    main,
)
from clicknick.ladder.clipboard import parse_click_major_version
from clicknick.ladder.program import (
    CONDITION_COLUMNS,
    NeedsClickV4Error,
    PrepareResult,
    _collapse_cols,
    _dedupe_filename_stem,
    _describe_row_wires,
    _describe_single_rung,
    _extract_operand_candidates,
    _slugify,
    check_click_version,
    describe_csv,
    encode_csv,
    extract_addresses_from_bin,
    extract_addresses_from_csv,
    extract_addresses_from_rungs,
    prepare_rungs_load,
    program_save,
)

# ---------------------------------------------------------------------------
# _extract_operand_candidates
# ---------------------------------------------------------------------------


class TestExtractOperandCandidates:
    def test_contact(self):
        assert _extract_operand_candidates(Contact("X001")) == ["X001"]

    def test_coil_with_range(self):
        assert _extract_operand_candidates(Coil("Y001", range_end="Y005")) == [
            "Y001",
            "Y005",
        ]

    def test_coil_without_range(self):
        assert _extract_operand_candidates(Coil("Y001", range_end=None)) == [
            "Y001",
        ]

    def test_compare_contact(self):
        result = _extract_operand_candidates(CompareContact("==", "DS1", "100"))
        assert result == ["DS1", "100"]

    @pytest.mark.parametrize(
        ("contact", "expected"),
        [
            (Contact("X001", kind="nc"), ["X001"]),
            (CompareContact("==", "DS1", "DS2"), ["DS1", "DS2"]),
        ],
    )
    def test_contact_with_a_wire_down(self, contact, expected):
        assert _extract_operand_candidates(Tee(contact)) == expected

    def test_addresses_of_a_rung_with_a_wire_down_from_a_contact(self):
        rung = Rung(
            conditions=[[Tee(Contact("X001")), *["-"] * 30], ["|", Contact("X002"), *["-"] * 29]],
            instructions=[Coil("Y001"), Coil("Y002")],
            comment=None,
        )
        assert extract_addresses_from_rungs([rung]) == ["X001", "Y001", "X002", "Y002"]

    def test_undecoded_marker_has_no_address(self):
        marker = Undecoded("bad bytes after DS1 at X001", rung=0)
        assert _extract_operand_candidates(marker) == []

    def test_timer(self):
        assert _extract_operand_candidates(Timer("on_delay", "T1", "TD1", "1000", "Tms")) == [
            "T1",
            "TD1",
        ]

    def test_plain_string(self):
        assert _extract_operand_candidates("X001") == ["X001"]

    def test_plain_string_with_range(self):
        result = _extract_operand_candidates("X001 .. X005")
        # Range regex captures both ends, then token regex also captures both
        assert "X001" in result
        assert "X005" in result

    def test_empty_string(self):
        assert _extract_operand_candidates("") == []


# ---------------------------------------------------------------------------
# Address extraction
# ---------------------------------------------------------------------------


class TestExtractAddresses:
    def test_extract_addresses_from_bin_matches_csv_fixture(self):
        fixture_dir = (
            Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures" / "golden"
        )
        csv_path = fixture_dir / "instr-6row-multi-output.csv"
        bin_path = fixture_dir / "instr-6row-multi-output.bin"
        expected = ["DS181", "C1061", "DS182"]

        assert extract_addresses_from_csv(csv_path) == expected
        assert extract_addresses_from_bin(bin_path.read_bytes()) == expected

    def test_prepare_rungs_load_provisions_blockcopy_range_endpoints(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        rung = Rung(
            conditions=[["-"] * 31, [""] * 31],
            instructions=[BlockCopy("DS201", "DS210", "DS202", "DS211"), ""],
            comment=None,
        )
        provisioned: list[str] = []

        def _ensure(_db_path: str, addresses: list[str]) -> dict[str, int]:
            provisioned.extend(addresses)
            return {"inserted_count": 1}

        monkeypatch.setattr("clicknick.ladder.program.ensure_addresses_exist", _ensure)

        result = prepare_rungs_load([rung], click_v4=False, mdb_path=Path("SC_.mdb"))

        assert result.addresses == ["DS201", "DS210", "DS202", "DS211"]
        assert provisioned == result.addresses
        assert result.addresses_inserted == 1
        assert result.payload


# ---------------------------------------------------------------------------
# CLICK version check
# ---------------------------------------------------------------------------


def _rung(instruction) -> Rung:
    return Rung(conditions=[["-"] * 31], instructions=[instruction], comment=None)


@pytest.mark.parametrize(
    ("title", "major"),
    [
        ("CLICK Programming Software (Version3.71) - P.ckp - [Main Program]", 3),
        ("CLICK Programming Software (Version4.00) - P.ckp - [Main Program]", 4),
        ("CLICK Programming Software (Version4.12) - P.ckp", 4),
        ("CLICK Programming Software (Version10.1) - P.ckp", 10),
        ("CLICK Programming Software", None),
    ],
)
def test_parse_click_major_version(title: str, major: int | None):
    assert parse_click_major_version(title) == major


class TestCheckClickVersion:
    def test_v4_rungs_refused_by_older_click_with_rung_numbers(self):
        rungs = [_rung(Coil("Y001")), _rung(Break())]

        with pytest.raises(NeedsClickV4Error, match=r"rung 2: break\(\)"):
            check_click_version(rungs, click_v4=False)
        with pytest.raises(NeedsClickV4Error, match=r"rung 11: break\(\)"):
            check_click_version(rungs, click_v4=False, first_rung=10)

    def test_v4_rungs_accepted_by_v4(self):
        check_click_version([_rung(Break())], click_v4=True)

    def test_older_rungs_accepted_by_older_click(self):
        check_click_version([_rung(Coil("Y001"))], click_v4=False)

    def test_refused_load_leaves_mdb_untouched(self, monkeypatch: pytest.MonkeyPatch):
        provisioned: list[str] = []
        monkeypatch.setattr(
            "clicknick.ladder.program.ensure_addresses_exist",
            lambda _db, addresses: provisioned.extend(addresses) or {"inserted_count": 0},
        )

        with pytest.raises(NeedsClickV4Error):
            prepare_rungs_load(
                [_rung(Coil("Y001")), _rung(Break())],
                click_v4=False,
                mdb_path=Path("SC_.mdb"),
            )
        assert provisioned == []


# ---------------------------------------------------------------------------
# A CSV that holds no rungs
# ---------------------------------------------------------------------------


def test_no_rungs_are_refused_with_a_value_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    write_csv(empty, [])

    assert describe_csv(empty) == "0 rungs"
    with pytest.raises(ValueError, match="no rungs"):
        encode_csv(empty)
    with pytest.raises(ValueError, match="no rungs"):
        prepare_rungs_load([], click_v4=True)


@pytest.mark.parametrize("text", ["", None])
def test_load_of_a_csv_without_rungs_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, text
) -> None:
    empty = tmp_path / "empty.csv"
    if text is None:
        write_csv(empty, [])  # Only the header
    else:
        empty.write_text(text, encoding="utf-8")
    monkeypatch.setattr("clicknick.ladder.cli.resolve_mdb_path", lambda _path: None)
    monkeypatch.setattr("clicknick.ladder.cli.is_click_v4", lambda *_a: True)
    monkeypatch.setattr("clicknick.ladder.cli.copy_to_clipboard", lambda *_a, **_k: None)
    monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(empty)])

    with pytest.raises(SystemExit, match="1"):
        main()

    assert "Error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Adding the rungs' addresses to SC_.mdb
# ---------------------------------------------------------------------------


class TestDatabaseErrors:
    """Errors about SC_.mdb go to stderr. Under --mdb-path they also stop the command."""

    @pytest.fixture
    def rung_csv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        path = tmp_path / "rung.csv"
        write_csv(path, [_rung(Coil("Y001"))])
        monkeypatch.setattr("clicknick.ladder.cli.is_click_v4", lambda *_a: True)
        monkeypatch.setattr("clicknick.ladder.cli.find_click_hwnd", lambda: 0x1234)
        return path

    @pytest.fixture
    def copied(self, monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
        copied: list[bytes] = []
        monkeypatch.setattr(
            "clicknick.ladder.cli.copy_to_clipboard", lambda data, *_a: copied.append(data)
        )
        return copied

    def _fail_to_add(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _ensure(_db: str, _addresses: list[str]) -> dict[str, int]:
            raise RuntimeError("the database is locked")

        monkeypatch.setattr("clicknick.ladder.program.ensure_addresses_exist", _ensure)

    def test_a_wrong_mdb_path_stops_the_command(
        self,
        tmp_path: Path,
        rung_csv: Path,
        copied: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        missing = tmp_path / "missing" / "SC_.mdb"
        monkeypatch.setattr(
            "sys.argv", ["clicknick-rung", "--mdb-path", str(missing), "load", str(rung_csv)]
        )

        with pytest.raises(SystemExit, match="1"):
            main()

        assert copied == []
        assert capsys.readouterr().err == (
            f"Error: There is no file at {missing}."
            " Give --mdb-path the path of the project's SC_.mdb.\n"
        )

    def test_a_failure_to_add_to_the_mdb_path_stops_the_command(
        self,
        tmp_path: Path,
        rung_csv: Path,
        copied: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        database = tmp_path / "SC_.mdb"
        database.write_bytes(b"")
        self._fail_to_add(monkeypatch)
        monkeypatch.setattr(
            "sys.argv", ["clicknick-rung", "--mdb-path", str(database), "load", str(rung_csv)]
        )

        with pytest.raises(SystemExit, match="1"):
            main()

        assert copied == []
        assert capsys.readouterr().err == (
            f"Error: Could not add the rungs' addresses to {database}: the database is locked\n"
        )

    def test_an_undecodable_bin_stops_the_command_under_mdb_path(
        self,
        tmp_path: Path,
        rung_csv: Path,
        copied: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        database = tmp_path / "SC_.mdb"
        database.write_bytes(b"")
        src = tmp_path / "rung.bin"
        src.write_bytes(b"\xaa")

        def _raise_decode_error(_data: bytes, **_kw) -> PrepareResult:
            raise ValueError("bad binary")

        monkeypatch.setattr("clicknick.ladder.cli.prepare_bin_load", _raise_decode_error)
        monkeypatch.setattr(
            "sys.argv", ["clicknick-rung", "--mdb-path", str(database), "load", str(src)]
        )

        with pytest.raises(SystemExit, match="1"):
            main()

        assert copied == []
        assert capsys.readouterr().err == (
            f"Error: Could not add the addresses in rung.bin to {database}."
            " The file could not be decoded: bad binary\n"
        )

    def test_a_click_window_without_sc_mdb_is_reported(
        self,
        rung_csv: Path,
        copied: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        monkeypatch.setattr("clicknick.ladder.cli.find_click_database", lambda *_a: None)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(rung_csv)])

        main()

        assert len(copied) == 1
        assert capsys.readouterr().err == (
            "  Did not add the rungs' addresses to SC_.mdb. Could not find the SC_.mdb of the"
            " CLICK window. Give its path with --mdb-path.\n"
        )

    def test_a_failure_to_add_to_the_click_windows_mdb_is_reported(
        self,
        tmp_path: Path,
        rung_csv: Path,
        copied: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        database = tmp_path / "SC_.mdb"
        database.write_bytes(b"")
        monkeypatch.setattr("clicknick.ladder.cli.find_click_database", lambda *_a: str(database))
        self._fail_to_add(monkeypatch)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(rung_csv)])

        main()

        assert len(copied) == 1
        assert capsys.readouterr().err == (
            f"  Could not add the rungs' addresses to {database}: the database is locked\n"
        )

    def test_guided_reports_a_wrong_mdb_path_once(
        self,
        tmp_path: Path,
        rung_csv: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        guided: list[tuple] = []
        monkeypatch.setattr("clicknick.ladder.cli._run_guided", lambda *a, **_k: guided.append(a))
        monkeypatch.setattr(
            "sys.argv",
            ["clicknick-rung", "--mdb-path", str(tmp_path / "none.mdb"), "guided", str(tmp_path)],
        )

        with pytest.raises(SystemExit, match="1"):
            main()

        assert guided == []

    @pytest.mark.parametrize("answer", ["s", "q"])
    @pytest.mark.parametrize("command", [["guided"], ["program", "load"]])
    def test_guided_ends_in_an_error_when_the_mdb_path_insert_fails(
        self,
        tmp_path: Path,
        rung_csv: Path,
        copied: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        command: list[str],
        answer: str,
    ):
        # A skip or a quit after the failure leaves the CSV without its addresses.
        rung_csv.rename(tmp_path / "main.csv")
        database = tmp_path / "SC_.mdb"
        database.write_bytes(b"")
        self._fail_to_add(monkeypatch)
        monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
        monkeypatch.setattr(
            "sys.argv",
            ["clicknick-rung", "--mdb-path", str(database), *command, str(tmp_path)],
        )

        with pytest.raises(SystemExit, match="1"):
            main()

        assert copied == []
        message = f"Could not add the rungs' addresses to {database}: the database is locked"
        assert capsys.readouterr().err == f"  {message}\n"
        log = (tmp_path / "verify_progress.log").read_text(encoding="utf-8")
        assert f": error ({message})" in log

    def test_save_does_not_read_the_mdb_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("clicknick.ladder.cli.read_from_clipboard", lambda: b"rung")
        out = tmp_path / "rung.bin"
        monkeypatch.setattr(
            "sys.argv",
            ["clicknick-rung", "--mdb-path", str(tmp_path / "none.mdb"), "save", str(out)],
        )

        main()

        assert out.read_bytes() == b"rung"


# ---------------------------------------------------------------------------
# _collapse_cols
# ---------------------------------------------------------------------------


class TestCollapseCols:
    def test_contiguous_run_of_3(self):
        result = _collapse_cols(["A", "B", "C"], CONDITION_COLUMNS)
        assert result == "A..C"

    def test_short_runs(self):
        result = _collapse_cols(["A", "B"], CONDITION_COLUMNS)
        assert result == "A+B"

    def test_mixed(self):
        # A is isolated, C..E is a run of 3, G is isolated
        result = _collapse_cols(["A", "C", "D", "E", "G"], CONDITION_COLUMNS)
        assert result == "A+C..E+G"

    def test_empty(self):
        assert _collapse_cols([], CONDITION_COLUMNS) == ""

    def test_single(self):
        assert _collapse_cols(["A"], CONDITION_COLUMNS) == "A"

    def test_long_contiguous(self):
        cols = list(CONDITION_COLUMNS)  # all 31
        result = _collapse_cols(cols, CONDITION_COLUMNS)
        assert result == "A..AE"


# ---------------------------------------------------------------------------
# _describe_row_wires
# ---------------------------------------------------------------------------


class TestDescribeRowWires:
    def test_all_dashes(self):
        row = ["-"] * len(CONDITION_COLUMNS)
        assert _describe_row_wires(row, CONDITION_COLUMNS) == "full"

    def test_mixed_tokens(self):
        row = ["-"] * len(CONDITION_COLUMNS)
        row[1] = "T"  # column B
        result = _describe_row_wires(row, CONDITION_COLUMNS)
        assert "T:B" in result
        assert "-:" in result

    def test_no_wire_tokens(self):
        row = ["Contact(X1)"] * len(CONDITION_COLUMNS)
        assert _describe_row_wires(row, CONDITION_COLUMNS) == ""


# ---------------------------------------------------------------------------
# _describe_single_rung
# ---------------------------------------------------------------------------


class TestDescribeSingleRung:
    def test_single_empty_row(self):
        result = _describe_single_rung([["-"] * 31], ["-"], None, CONDITION_COLUMNS)
        assert result.startswith("1 row")

    def test_with_comment(self):
        result = _describe_single_rung([["-"] * 31], ["-"], "my comment", CONDITION_COLUMNS)
        assert 'comment "my comment"' in result

    def test_long_comment(self):
        long = "x" * 60
        result = _describe_single_rung([["-"] * 31], ["-"], long, CONDITION_COLUMNS)
        assert "comment (60 chars)" in result

    def test_with_af_tokens(self):
        result = _describe_single_rung([["-"] * 31], ["Coil(Y001)"], None, CONDITION_COLUMNS)
        assert "AF=Coil(Y001)" in result

    def test_multiple_rows(self):
        result = _describe_single_rung(
            [["-"] * 31, ["-"] * 31], ["-", "-"], None, CONDITION_COLUMNS
        )
        assert "2 rows" in result


# ---------------------------------------------------------------------------
# _read_progress / _append_result
# ---------------------------------------------------------------------------


class TestProgressLog:
    def test_round_trip(self, tmp_path: Path):
        log = tmp_path / "progress.log"
        _append_result(log, "fixture1", "worked")
        _append_result(log, "fixture2", "crashed", "segfault")

        done = _read_progress(log)
        assert "fixture1" in done
        assert "fixture2" in done
        assert "worked" in done["fixture1"]
        assert "crashed" in done["fixture2"]
        assert "segfault" in done["fixture2"]

    def test_skips_comments_and_blanks(self, tmp_path: Path):
        log = tmp_path / "progress.log"
        log.write_text("# header\n\nfixture1: worked\n", encoding="utf-8")

        done = _read_progress(log)
        assert list(done.keys()) == ["fixture1"]

    def test_append_preserves_existing(self, tmp_path: Path):
        log = tmp_path / "progress.log"
        log.write_text("# header\nfixture1: worked\n", encoding="utf-8")
        _append_result(log, "fixture2", "skipped")

        text = log.read_text(encoding="utf-8")
        assert "fixture1: worked" in text
        assert "fixture2: skipped" in text

    def test_nonexistent_log(self, tmp_path: Path):
        log = tmp_path / "no_such_file.log"
        assert _read_progress(log) == {}

    def test_append_adds_newline_if_missing(self, tmp_path: Path):
        log = tmp_path / "progress.log"
        log.write_text("fixture1: worked", encoding="utf-8")  # no trailing newline
        _append_result(log, "fixture2", "crashed", "segfault")

        done = _read_progress(log)
        assert "fixture1" in done
        assert "fixture2" in done


# ---------------------------------------------------------------------------
# Comparing the rung copied back with the saved .bin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("copied_back", "report"),
    [
        (b"\x01\x02\x03", "  case: the rung you copied back matches case.bin (3 bytes)\n"),
        (
            b"\x01\x09\x03",
            "  case: 1 byte differs between the rung you copied back and case.bin."
            " The first is at 0x0001.\n",
        ),
        (
            b"\x01\x09\x09",
            "  case: 2 bytes differ between the rung you copied back and case.bin."
            " The first is at 0x0001.\n",
        ),
        (
            b"\x01\x02",
            "  case: the rung you copied back has 2 bytes, and case.bin has 3.\n",
        ),
    ],
)
def test_copied_back_rung_is_compared_with_the_saved_bin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    copied_back: bytes,
    report: str,
):
    """The comparison is with the .bin saved before, not with the encoder's output."""
    saved = tmp_path / "case.bin"
    saved.write_bytes(b"\x01\x02\x03")
    monkeypatch.setattr("clicknick.ladder.cli.read_from_clipboard", lambda: copied_back)

    _save_and_compare("case", saved)

    assert capsys.readouterr().out == report
    assert saved.read_bytes() == b"\x01\x02\x03"


# ---------------------------------------------------------------------------
# Filename sanitizing
# ---------------------------------------------------------------------------


class TestProgramFilenameSanitizing:
    def test_slugify_preserves_case(self):
        assert _slugify("ModeManualTimers") == "ModeManualTimers"

    def test_slugify_preserves_spaces_and_hyphens(self):
        assert _slugify("Mode Manual-Timers") == "Mode Manual-Timers"

    def test_slugify_removes_windows_unsafe_chars(self):
        assert _slugify('Bad<>:"/\\|?*Name') == "BadName"

    def test_slugify_collapses_repeated_spaces_and_trims_trailing_space_dot(self):
        assert _slugify("Mode   Manual.  ") == "Mode Manual"

    def test_slugify_falls_back_when_name_becomes_empty(self):
        assert _slugify(' <>:"/\\|?*. ') == "Untitled"

    def test_dedupe_filename_stem_appends_windows_style_suffix(self):
        used: set[str] = set()
        assert _dedupe_filename_stem("ModeManualTimers", used) == "ModeManualTimers"
        assert _dedupe_filename_stem("ModeManualTimers", used) == "ModeManualTimers (2)"
        assert _dedupe_filename_stem("ModeManualTimers", used) == "ModeManualTimers (3)"

    def test_dedupe_filename_stem_treats_case_only_difference_as_duplicate(self):
        used: set[str] = set()
        assert _dedupe_filename_stem("ModeManualTimers", used) == "ModeManualTimers"
        assert _dedupe_filename_stem("modemanualtimers", used) == "modemanualtimers (2)"


# ---------------------------------------------------------------------------
# Program save
# ---------------------------------------------------------------------------


class TestProgramSave:
    def test_program_save_preserves_case_spacing_and_dedupes(self, tmp_path: Path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        for name in ("Scr1.tmp", "Scr10.tmp", "Scr11.tmp", "Scr12.tmp", "Scr13.tmp", "Scr14.tmp"):
            (src / name).write_bytes(b"scr")

        programs = iter(
            [
                Program(name="Main Program", prog_idx=1, rungs=[]),
                Program(name="ModeManualTimers", prog_idx=10, rungs=[]),
                Program(name="Mode Manual Timers", prog_idx=11, rungs=[]),
                Program(name="Mode-Manual-Timers", prog_idx=12, rungs=[]),
                Program(name='Mode<>:"/\\|?*ManualTimers', prog_idx=13, rungs=[]),
                Program(name="ModeManualTimers.", prog_idx=14, rungs=[]),
            ]
        )

        monkeypatch.setattr("clicknick.ladder.program.decode_program", lambda data: next(programs))

        written_paths: list[Path] = []

        def _write_csv(path: Path, rungs, **_kwargs) -> None:
            written_paths.append(Path(path))

        monkeypatch.setattr("clicknick.ladder.program.write_csv", _write_csv)

        out = tmp_path / "out"
        result = program_save(src, out)

        assert written_paths == [
            out / "main.csv",
            out / "subroutines" / "ModeManualTimers.csv",
            out / "subroutines" / "Mode Manual Timers.csv",
            out / "subroutines" / "Mode-Manual-Timers.csv",
            out / "subroutines" / "ModeManualTimers (2).csv",
            out / "subroutines" / "ModeManualTimers (3).csv",
        ]

        assert result.main_csv == out / "main.csv"
        assert len(result.subroutine_csvs) == 5
        assert result.total_rungs == 0
        assert len(result.programs) == 6

    def test_a_marker_in_a_subroutine_acts_as_return(self, tmp_path: Path, monkeypatch):
        """write_csv puts a marker in place of a rung it cannot write. In a subroutine, the
        marker must return to the caller, as laddercodec's write_bundle writes it."""
        for name in ("Scr1.tmp", "Scr2.tmp"):
            (tmp_path / name).write_bytes(name.encode())
        programs = {
            b"Scr1.tmp": Program(name="Main Program", prog_idx=1, rungs=[]),
            b"Scr2.tmp": Program(name="Fill", prog_idx=2, rungs=[]),
        }
        monkeypatch.setattr("clicknick.ladder.program.decode_program", programs.__getitem__)
        stops: dict[str, str] = {}

        def _write_csv(path: Path, rungs, **kwargs) -> None:
            stops[Path(path).name] = kwargs.get("stop", "end")

        monkeypatch.setattr("clicknick.ladder.program.write_csv", _write_csv)

        program_save(tmp_path, tmp_path / "out")

        assert stops == {"main.csv": "end", "Fill.csv": "return"}


# ---------------------------------------------------------------------------
# Guided program mode
# ---------------------------------------------------------------------------


class TestGuidedProgramMode:
    def test_run_guided_without_copyback_marks_worked_without_bin_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        csv_path = tmp_path / "sub.csv"
        log_path = tmp_path / "progress.log"

        monkeypatch.setattr("clicknick.ladder.cli._save_and_compare", lambda *args: pytest.fail())
        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: pytest.fail(),
        )

        responses = iter(["w"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

        with pytest.raises(SystemExit) as excinfo:
            _run_guided(
                [("sub", csv_path)],
                log_path=log_path,
                loader=lambda _path, _mdb_path: b"",
                save_copyback_bin=False,
            )

        assert excinfo.value.code == 0
        assert "sub: worked" in log_path.read_text(encoding="utf-8")
        assert not csv_path.with_suffix(".bin").exists()

    def test_run_guided_without_copyback_skips_unexpected_bin_save_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        csv_path = tmp_path / "sub.csv"
        log_path = tmp_path / "progress.log"

        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: pytest.fail(),
        )

        responses = iter(["n", "wrong branch"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

        with pytest.raises(SystemExit) as excinfo:
            _run_guided(
                [("sub", csv_path)],
                log_path=log_path,
                loader=lambda _path, _mdb_path: b"",
                save_copyback_bin=False,
            )

        assert excinfo.value.code == 1
        assert "sub: unexpected (wrong branch)" in log_path.read_text(encoding="utf-8")
        assert not csv_path.with_suffix(".bin").exists()

    def test_program_load_routes_with_copyback_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "main.csv").write_text("dummy", encoding="utf-8")

        captured: dict[str, object] = {}

        def _capture(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        monkeypatch.setattr("clicknick.ladder.cli._run_guided", _capture)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "program", "load", str(tmp_path)])

        main()

        assert captured["kwargs"]["save_copyback_bin"] is False


# ---------------------------------------------------------------------------
# CLI routing (main)
# ---------------------------------------------------------------------------


class TestMainArgparse:
    """Test CLI argument parsing and routing with mocked clipboard."""

    def test_save_writes_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        out = tmp_path / "output.bin"
        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: b"\x01\x02\x03",
        )
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        main()
        assert out.read_bytes() == b"\x01\x02\x03"

    def test_save_csv_decodes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        out = tmp_path / "output.csv"
        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: b"\x01\x02\x03",
        )
        decoded_calls: list[tuple[bytes, Path]] = []

        def mock_decode_to_csv(data, path):
            decoded_calls.append((data, path))
            Path(path).write_text("decoded", encoding="utf-8")

        monkeypatch.setattr("clicknick.ladder.cli.decode_to_csv", mock_decode_to_csv)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        main()
        assert len(decoded_calls) == 1
        assert decoded_calls[0] == (b"\x01\x02\x03", out)
        assert not out.with_suffix(".bin").exists()

    def test_save_csv_decode_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        out = tmp_path / "output.csv"
        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: b"\x01\x02\x03",
        )

        def mock_decode_to_csv(data, path):
            from laddercodec import CsvWriteError

            raise CsvWriteError("rungs[0] needs more than 32 rows")

        monkeypatch.setattr("clicknick.ladder.cli.decode_to_csv", mock_decode_to_csv)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "could not decode to CSV" in capsys.readouterr().err

    def test_save_no_extension_writes_both(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        out = tmp_path / "my_rung"
        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: b"\x01\x02\x03",
        )

        def mock_decode_to_csv(data, path):
            Path(path).write_text("decoded", encoding="utf-8")

        monkeypatch.setattr("clicknick.ladder.cli.decode_to_csv", mock_decode_to_csv)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        main()
        assert out.with_suffix(".bin").read_bytes() == b"\x01\x02\x03"
        assert out.with_suffix(".csv").read_text(encoding="utf-8") == "decoded"

    def test_save_no_extension_csv_failure_still_saves_bin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        out = tmp_path / "my_rung"
        monkeypatch.setattr(
            "clicknick.ladder.cli.read_from_clipboard",
            lambda: b"\x01\x02\x03",
        )

        def mock_decode_to_csv(data, path):
            from laddercodec import CsvWriteError

            raise CsvWriteError("rungs[0] needs more than 32 rows")

        monkeypatch.setattr("clicknick.ladder.cli.decode_to_csv", mock_decode_to_csv)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        main()
        assert out.with_suffix(".bin").read_bytes() == b"\x01\x02\x03"
        assert not out.with_suffix(".csv").exists()
        assert "could not write CSV" in capsys.readouterr().err

    def test_save_clipboard_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        import win32clipboard

        out = tmp_path / "output.bin"

        def _no_rungs(_format):
            raise TypeError("Specified clipboard format is not available")

        # read_from_clipboard runs as it is. Only the Windows clipboard is faked.
        monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda *_a: None)
        monkeypatch.setattr(win32clipboard, "GetClipboardData", _no_rungs)
        monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert capsys.readouterr().err == (
            "Error: The clipboard holds no CLICK rungs. Copy the rungs in CLICK first.\n"
        )
        assert not out.exists()

    def test_load_bin_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        src = tmp_path / "rung.bin"
        src.write_bytes(b"\xaa\xbb")
        called: list[tuple[Path, str | None]] = []

        def mock_load_bin(path: Path, mdb_path: str | None) -> bytes:
            called.append((path, mdb_path))
            return b""

        monkeypatch.setattr("clicknick.ladder.cli._load_bin", mock_load_bin)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(src)])
        main()
        assert called == [(src, None)]

    def test_load_bin_provisions_mdb_addresses(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        src = tmp_path / "rung.bin"
        src.write_bytes(b"\xaa\xbb")
        resolved_mdb = tmp_path / "SC_.mdb"
        copied: list[bytes] = []
        prepare_calls: list[tuple[bytes, bool, Path]] = []

        monkeypatch.setattr("clicknick.ladder.cli.resolve_mdb_path", lambda _mdb_path: resolved_mdb)
        monkeypatch.setattr("clicknick.ladder.cli.is_click_v4", lambda: True)

        def mock_prepare_bin_load(data: bytes, *, click_v4: bool, mdb_path: Path) -> PrepareResult:
            prepare_calls.append((data, click_v4, mdb_path))
            return PrepareResult(
                payload=data,
                rung_count=1,
                addresses=["X001"],
                addresses_inserted=2,
                mdb_path=mdb_path,
                mdb_error=None,
            )

        monkeypatch.setattr("clicknick.ladder.cli.prepare_bin_load", mock_prepare_bin_load)
        monkeypatch.setattr(
            "clicknick.ladder.cli.copy_to_clipboard", lambda data: copied.append(data)
        )

        _load_bin(src, None)

        out = capsys.readouterr().out
        assert prepare_calls == [(b"\xaa\xbb", True, resolved_mdb)]
        assert copied == [b"\xaa\xbb"]
        assert "MDB: inserted 2 address(es) into SC_.mdb" in out
        assert "Copied rung.bin to clipboard (2 bytes)" in out

    def test_load_bin_decode_failure_still_copies_payload(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        src = tmp_path / "rung.bin"
        src.write_bytes(b"\xaa")
        resolved_mdb = tmp_path / "SC_.mdb"
        copied: list[bytes] = []

        monkeypatch.setattr("clicknick.ladder.cli.resolve_mdb_path", lambda _mdb_path: resolved_mdb)
        monkeypatch.setattr("clicknick.ladder.cli.is_click_v4", lambda: True)

        def _raise_decode_error(_data: bytes, *, click_v4: bool, mdb_path: Path) -> PrepareResult:
            raise ValueError("bad binary")

        monkeypatch.setattr("clicknick.ladder.cli.prepare_bin_load", _raise_decode_error)
        monkeypatch.setattr(
            "clicknick.ladder.cli.copy_to_clipboard", lambda data: copied.append(data)
        )

        _load_bin(src, None)

        captured = capsys.readouterr()
        assert copied == [b"\xaa"]
        assert captured.err == (
            "  Could not decode rung.bin: bad binary\n"
            "  clicknick-rung copies it as it is. It did not check the CLICK version"
            " or add the file's addresses to SC_.mdb.\n"
        )
        assert "Copied rung.bin to clipboard (1 bytes)" in captured.out

    def test_load_csv_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        csv_file = tmp_path / "rung.csv"
        csv_file.write_text("dummy", encoding="utf-8")
        called: list[Path] = []

        def mock_load_csv(path, mdb_path, best_effort=False):
            called.append(path)
            return b""

        monkeypatch.setattr("clicknick.ladder.cli._load_csv", mock_load_csv)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(csv_file)])
        main()
        assert called == [csv_file]

    def test_load_clipboard_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        golden = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures" / "golden"
        src = tmp_path / "rung.bin"
        src.write_bytes((golden / "instr-6row-multi-output.bin").read_bytes())

        monkeypatch.setattr("clicknick.ladder.cli.resolve_mdb_path", lambda _mdb_path: None)
        monkeypatch.setattr("clicknick.ladder.cli.is_click_v4", lambda: True)
        # copy_to_clipboard runs as it is and finds no CLICK window.
        monkeypatch.setattr("clicknick.ladder.clipboard.find_click_hwnds", lambda: [])
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(src)])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert capsys.readouterr().err == (
            "Error: Could not find a CLICK Programming Software window."
            " Start CLICK and try again.\n"
        )

    def test_guided_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("dummy", encoding="utf-8")

        monkeypatch.setattr(
            "clicknick.ladder.cli.describe_csv",
            lambda p: "1 row, full",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["clicknick-rung", "guided", str(tmp_path), "--list"],
        )
        main()

    def test_no_subcommand(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("sys.argv", ["clicknick-rung"])
        with pytest.raises(SystemExit, match="1"):
            main()
