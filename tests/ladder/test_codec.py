"""Tests for clicknick.ladder.codec — ClickCodec encode/decode."""

from pathlib import Path

import pytest

from clicknick.ladder.codec import BUFFER_SIZE, ClickCodec, _load_template
from clicknick.ladder.model import Coil, Contact, InstructionType, RungGrid

codec = ClickCodec()
CAPTURES_DIR = Path(__file__).resolve().parents[2] / "scratchpad" / "captures"


class TestTemplateRoundTrip:
    def test_template_encodes_to_itself(self):
        """Encoding template content (X002 NO -> out(Y001)) must reproduce the template."""
        grid = RungGrid(
            contact=Contact(InstructionType.CONTACT_NO, "X002"),
            coil=Coil(InstructionType.COIL_OUT, "Y001"),
        )
        generated = codec.encode(grid)
        template = _load_template()
        assert generated == template


class TestEncodeDecodeRoundTrip:
    def test_no_contact_out(self):
        grid = RungGrid.from_csv("X001,->,:out(Y001)")
        data = codec.encode(grid)
        assert len(data) == BUFFER_SIZE
        decoded = codec.decode(data)
        assert decoded.to_csv() == "X001,->,:out(Y001)"

    def test_nc_contact_out(self):
        grid = RungGrid.from_csv("~X003,->,:out(Y002)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.to_csv() == "~X003,->,:out(Y002)"

    def test_contact_immediate(self):
        grid = RungGrid.from_csv("X001.immediate,->,:out(Y001)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.contact.immediate is True
        assert decoded.to_csv() == "X001.immediate,->,:out(Y001)"

    def test_out_variants(self):
        for csv in (
            "X001,->,:out(Y001)",
            "X001,->,:out(immediate(Y001))",
            "X001,->,:out(Y001..Y002)",
            "X001,->,:out(immediate(Y001..Y002))",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_latch_variants(self):
        for csv in (
            "X001,->,:latch(Y001)",
            "X001,->,:latch(immediate(Y001))",
            "X001,->,:latch(Y001..Y002)",
            "X001,->,:latch(immediate(Y001..Y002))",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_reset_variants(self):
        for csv in (
            "X001,->,:reset(Y001)",
            "X001,->,:reset(immediate(Y001))",
            "X001,->,:reset(Y001..Y002)",
            "X001,->,:reset(immediate(Y001..Y002))",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_range_short_and_long_addresses(self):
        for csv in (
            "X001,->,:out(C1..C2)",
            "X001,->,:out(C1..C2000)",
            "X001,->,:out(C1901..C2000)",
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == csv

    def test_two_series_contacts(self):
        csv = "X001,X002,->,:out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv

    def test_two_series_rejects_immediate_contact(self):
        with pytest.raises(ValueError, match="Immediate contacts in two-series"):
            codec.encode(RungGrid.from_csv("X001.immediate,X002,->,:out(Y001)"))

    def test_two_series_rejects_non_4_char_contacts(self):
        with pytest.raises(ValueError, match="must be 4 chars"):
            codec.encode(RungGrid.from_csv("X1,X002,->,:out(Y001)"))


class TestCaptureBackedDecode:
    def _decode_capture(self, filename: str) -> RungGrid:
        data = (CAPTURES_DIR / filename).read_bytes()
        return codec.decode(data)

    def test_decode_contact_immediate_captures(self):
        g = self._decode_capture("NO_X001_immediate_coil_Y001.bin")
        assert g.contact.type == InstructionType.CONTACT_NO
        assert g.contact.operand == "X001"
        assert g.contact.immediate is True
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"

        g = self._decode_capture("NC_X001_immediate_coil_Y001.bin")
        assert g.contact.type == InstructionType.CONTACT_NC
        assert g.contact.operand == "X001"
        assert g.contact.immediate is True
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"

    def test_decode_out_captures(self):
        g = self._decode_capture("out_Y001_immediate_v2.bin")
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"
        assert g.coil.range_end is None
        assert g.coil.immediate is True

        g = self._decode_capture("out_Y001_Y002_v3.bin")
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"
        assert g.coil.range_end == "Y002"
        assert g.coil.immediate is False

        g = self._decode_capture("out_Y001_Y002_immediate_v1.bin")
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"
        assert g.coil.range_end == "Y002"
        assert g.coil.immediate is True

    def test_decode_latch_captures(self):
        g = self._decode_capture("latch_Y001_v1.bin")
        assert g.coil.type == InstructionType.COIL_LATCH
        assert g.coil.operand == "Y001"
        assert g.coil.range_end is None
        assert g.coil.immediate is False

        g = self._decode_capture("set_Y1_immediate_v1.bin")
        assert g.coil.type == InstructionType.COIL_LATCH
        assert g.coil.operand == "Y001"
        assert g.coil.range_end is None
        assert g.coil.immediate is True

        g = self._decode_capture("set_Y1_Y2_v1.bin")
        assert g.coil.type == InstructionType.COIL_LATCH
        assert g.coil.operand == "Y001"
        assert g.coil.range_end == "Y002"
        assert g.coil.immediate is False

        g = self._decode_capture("set_Y1_Y2_immediate_v1.bin")
        assert g.coil.type == InstructionType.COIL_LATCH
        assert g.coil.operand == "Y001"
        assert g.coil.range_end == "Y002"
        assert g.coil.immediate is True

    def test_decode_reset_captures(self):
        g = self._decode_capture("reset_Y001_v1.bin")
        assert g.coil.type == InstructionType.COIL_RESET
        assert g.coil.operand == "Y001"
        assert g.coil.range_end is None
        assert g.coil.immediate is False

        g = self._decode_capture("reset_Y1_immediate_v1.bin")
        assert g.coil.type == InstructionType.COIL_RESET
        assert g.coil.operand == "Y001"
        assert g.coil.range_end is None
        assert g.coil.immediate is True

        g = self._decode_capture("reset_Y1_Y2_v1.bin")
        assert g.coil.type == InstructionType.COIL_RESET
        assert g.coil.operand == "Y001"
        assert g.coil.range_end == "Y002"
        assert g.coil.immediate is False

        g = self._decode_capture("reset_Y1_Y2_immediate_v1.bin")
        assert g.coil.type == InstructionType.COIL_RESET
        assert g.coil.operand == "Y001"
        assert g.coil.range_end == "Y002"
        assert g.coil.immediate is True

    def test_decode_short_long_range_captures(self):
        g = self._decode_capture("out_C1_C2_v3.bin")
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "C1"
        assert g.coil.range_end == "C2"

        g = self._decode_capture("out_C1_C2000_v1.bin")
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "C1"
        assert g.coil.range_end == "C2000"

        g = self._decode_capture("out_C1901_C2000_v1.bin")
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "C1901"
        assert g.coil.range_end == "C2000"

    def test_decode_two_series_capture(self):
        g = self._decode_capture("two_series.bin")
        assert [c.to_csv() for c in g.contacts] == ["X001", "X002"]
        assert g.coil.type == InstructionType.COIL_OUT
        assert g.coil.operand == "Y001"


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
