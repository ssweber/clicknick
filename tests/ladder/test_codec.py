"""Tests for clicknick.ladder.codec — ClickCodec encode/decode."""

from pathlib import Path

import pytest

from clicknick.ladder import codec as codec_module
from clicknick.ladder.codec import BUFFER_SIZE, ClickCodec, _load_scaffold
from clicknick.ladder.model import Coil, Contact, InstructionType, RungGrid
from clicknick.ladder.topology import HEADER_ENTRY_BASE, HEADER_ENTRY_COUNT, HEADER_ENTRY_SIZE

codec = ClickCodec()
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures"


class TestDeterministicEncoding:
    def test_runtime_has_no_template_loader_functions(self):
        assert not hasattr(codec_module, "_load_template")
        assert not hasattr(codec_module, "_load_two_series_template")
        assert not hasattr(codec_module, "_load_two_series_immediate_template")
        assert not hasattr(codec_module, "_load_two_series_second_immediate_template")
        assert not hasattr(codec_module, "_load_two_series_both_immediate_template")

    def test_encode_sets_structural_header_table(self):
        data = codec.encode(RungGrid.from_csv("X001,->,:,out(Y001)"))
        assert len(data) == BUFFER_SIZE
        assert data[:8] == b"CLICK   "
        assert data[HEADER_ENTRY_BASE] == 0x40
        scaffold = _load_scaffold()
        for column in range(HEADER_ENTRY_COUNT):
            entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
            assert data[entry_start : entry_start + HEADER_ENTRY_SIZE] == scaffold[
                entry_start : entry_start + HEADER_ENTRY_SIZE
            ]


class TestEncodeDecodeRoundTrip:
    def test_no_contact_out(self):
        grid = RungGrid.from_csv("X001,->,:,out(Y001)")
        data = codec.encode(grid)
        assert len(data) == BUFFER_SIZE
        decoded = codec.decode(data)
        assert decoded.to_csv() == "X001,->,:,out(Y001)"

    def test_nc_contact_out(self):
        grid = RungGrid.from_csv("~X003,->,:,out(Y002)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.to_csv() == "~X003,->,:,out(Y002)"

    def test_contact_immediate(self):
        grid = RungGrid.from_csv("X001.immediate,->,:,out(Y001)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.contact.immediate is True
        assert decoded.to_csv() == "X001.immediate,->,:,out(Y001)"

    def test_out_variants(self):
        for csv in (
            "X001,->,:,out(Y001)",
            "X001,->,:,out(immediate(Y001))",
            "X001,->,:,out(Y001..Y002)",
            "X001,->,:,out(immediate(Y001..Y002))",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_latch_variants(self):
        for csv in (
            "X001,->,:,latch(Y001)",
            "X001,->,:,latch(immediate(Y001))",
            "X001,->,:,latch(Y001..Y002)",
            "X001,->,:,latch(immediate(Y001..Y002))",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_reset_variants(self):
        for csv in (
            "X001,->,:,reset(Y001)",
            "X001,->,:,reset(immediate(Y001))",
            "X001,->,:,reset(Y001..Y002)",
            "X001,->,:,reset(immediate(Y001..Y002))",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_range_short_and_long_addresses(self):
        for csv in (
            "X001,->,:,out(C1..C2)",
            "X001,->,:,out(C1..C2000)",
            "X001,->,:,out(C1901..C2000)",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_short_operand_contact_variants(self):
        for csv in (
            "C1,->,:,out(Y001)",
            "CT1,->,:,out(Y001)",
            "X1,->,:,out(Y001)",
            "X1.immediate,->,:,out(Y001)",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_two_series_contacts(self):
        csv = "X001,X002,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv

    def test_two_series_contacts_first_immediate(self):
        csv = "X001.immediate,X002,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv

    def test_two_series_contacts_second_immediate(self):
        csv = "X001,X002.immediate,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv

    def test_two_series_contacts_both_immediate(self):
        csv = "X001.immediate,X002.immediate,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv

    def test_two_series_accepts_non_4_char_contacts(self):
        csv = "X1,X002,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv


class TestCaptureBackedDecode:
    def _decode_fixture(self, filename: str) -> RungGrid:
        data = (FIXTURES_DIR / filename).read_bytes()
        return codec.decode(data)

    def test_decode_simple_rung_capture(self):
        g = self._decode_fixture("simple_rung.bin")
        assert g.to_csv() == "X001,->,:,out(Y001)"

    def test_decode_contact_plus_output_capture(self):
        g = self._decode_fixture("no_a_out_af.bin")
        assert g.to_csv() == "X001,->,:,out(Y001)"

    def test_decode_two_series_capture(self):
        g = self._decode_fixture("two_series_rung.bin")
        assert [c.to_csv() for c in g.contacts] == ["X001", "X002"]
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"

    @pytest.mark.parametrize("filename", ["out_af_only.bin", "no_a_only.bin", "totally_empty.bin"])
    def test_decode_invalid_capture_shapes(self, filename: str):
        with pytest.raises(ValueError):
            self._decode_fixture(filename)


class TestNickname:
    def test_encode_with_nickname(self):
        grid = RungGrid(
            contact=Contact(InstructionType.CONTACT_NO, "X001"),
            coil=Coil(InstructionType.COIL_OUT, "Y001"),
            nickname="Start",
        )
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.nickname == "Start"

    def test_encode_without_nickname(self):
        grid = RungGrid(
            contact=Contact(InstructionType.CONTACT_NO, "X001"),
            coil=Coil(InstructionType.COIL_OUT, "Y001"),
        )
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.nickname is None
