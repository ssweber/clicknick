"""Tests for ladder/cli.py — pure-logic functions and CLI routing."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest
from laddercodec import Coil, CompareContact, Contact, Timer
from laddercodec.csv.contract import CONDITION_COLUMNS

from clicknick.ladder.cli import (
    _append_result,
    _collapse_cols,
    _describe_row_wires,
    _describe_single_rung,
    _extract_operand_candidates,
    _read_progress,
    main,
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
        copied: list[bytes] = []
        monkeypatch.setattr(
            "clicknick.ladder.cli.copy_to_clipboard",
            lambda data: copied.append(data),
        )
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(src)])
        main()
        assert copied == [b"\xaa\xbb"]

    def test_load_csv_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        csv_file = tmp_path / "rung.csv"
        csv_file.write_text("dummy", encoding="utf-8")
        called: list[Path] = []

        def mock_load_csv(path, mdb_path):
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

        monkeypatch.setattr("clicknick.ladder.cli.copy_to_clipboard", _raise)
        monkeypatch.setattr("sys.argv", ["clicknick-rung", "load", str(src)])
        with pytest.raises(SystemExit, match="1"):
            main()
        assert "Click Programming Software not found" in capsys.readouterr().err

    def test_guided_list(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create a minimal valid CSV
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("dummy", encoding="utf-8")

        # Mock describe_csv to avoid needing a real CSV
        monkeypatch.setattr(
            "clicknick.ladder.cli.describe_csv",
            lambda p: "1 row, full",
        )
        monkeypatch.setattr(
            "sys.argv",
            ["clicknick-rung", "guided", str(tmp_path), "--list"],
        )
        main()  # should print listing and return without error

    def test_no_subcommand(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("sys.argv", ["clicknick-rung"])
        with pytest.raises(SystemExit, match="1"):
            main()
