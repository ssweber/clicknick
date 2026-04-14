"""Tests for ladder CLI and program service functions."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
from laddercodec import Coil, CompareContact, Contact, Timer
from laddercodec.csv.contract import CONDITION_COLUMNS
from laddercodec.model import Program

from clicknick.ladder.cli import (
    _append_result,
    _load_bin,
    _read_progress,
    _run_guided,
    main,
)
from clicknick.ladder.program import (
    PrepareResult,
    _collapse_cols,
    _dedupe_filename_stem,
    _describe_row_wires,
    _describe_single_rung,
    _extract_operand_candidates,
    _slugify,
    extract_addresses_from_bin,
    extract_addresses_from_csv,
    program_save,
)

# Resolve the InstructionType enum used by Contact/Coil constructors
_IT = typing.get_type_hints(Contact)["type"]


# ---------------------------------------------------------------------------
# _extract_operand_candidates
# ---------------------------------------------------------------------------


class TestExtractOperandCandidates:
    def test_contact(self):
        assert _extract_operand_candidates(Contact(_IT.CONTACT_NO, "X001")) == ["X001"]

    def test_coil_with_range(self):
        assert _extract_operand_candidates(Coil(_IT.COIL_OUT, "Y001", range_end="Y005")) == [
            "Y001",
            "Y005",
        ]

    def test_coil_without_range(self):
        assert _extract_operand_candidates(Coil(_IT.COIL_OUT, "Y001", range_end=None)) == [
            "Y001",
        ]

    def test_compare_contact(self):
        result = _extract_operand_candidates(CompareContact("==", "DS1", "100"))
        assert result == ["DS1", "100"]

    def test_timer(self):
        assert _extract_operand_candidates(Timer("on_delay", "T1", "TD1", "1000", "ms")) == [
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

        def _write_csv(path: Path, rungs) -> None:
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
            from laddercodec.csv.writer import WriterError

            raise WriterError("unknown instruction")

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
            from laddercodec.csv.writer import WriterError

            raise WriterError("unknown instruction")

        monkeypatch.setattr("clicknick.ladder.cli.decode_to_csv", mock_decode_to_csv)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        main()
        assert out.with_suffix(".bin").read_bytes() == b"\x01\x02\x03"
        assert not out.with_suffix(".csv").exists()
        assert "could not write CSV" in capsys.readouterr().err

    def test_save_clipboard_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        out = tmp_path / "output.bin"

        def _raise():
            raise RuntimeError("No Click rung data on clipboard (format 522 not present).")

        monkeypatch.setattr("clicknick.ladder.cli.read_from_clipboard", _raise)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "save", str(out)])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "No Click rung data" in capsys.readouterr().err

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
        prepare_calls: list[tuple[bytes, Path]] = []

        monkeypatch.setattr("clicknick.ladder.cli.resolve_mdb_path", lambda _mdb_path: resolved_mdb)

        def mock_prepare_bin_load(data: bytes, *, mdb_path: Path) -> PrepareResult:
            prepare_calls.append((data, mdb_path))
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
        assert prepare_calls == [(b"\xaa\xbb", resolved_mdb)]
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

        def _raise_decode_error(_data: bytes, *, mdb_path: Path) -> PrepareResult:
            raise ValueError("bad binary")

        monkeypatch.setattr("clicknick.ladder.cli.prepare_bin_load", _raise_decode_error)
        monkeypatch.setattr(
            "clicknick.ladder.cli.copy_to_clipboard", lambda data: copied.append(data)
        )

        _load_bin(src, None)

        out = capsys.readouterr().out
        assert copied == [b"\xaa"]
        assert "MDB: skipped (could not decode .bin for address extraction: bad binary)" in out
        assert "Copied rung.bin to clipboard (1 bytes)" in out

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
        src = tmp_path / "rung.bin"
        src.write_bytes(b"\xaa")

        def _raise(data):
            raise RuntimeError("Click Programming Software not found. Is it running?")

        monkeypatch.setattr(
            "clicknick.ladder.cli.resolve_mdb_path",
            lambda _mdb_path: (_ for _ in ()).throw(FileNotFoundError("no mdb")),
        )
        monkeypatch.setattr("clicknick.ladder.cli.copy_to_clipboard", _raise)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(src)])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "Click Programming Software not found" in capsys.readouterr().err

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
