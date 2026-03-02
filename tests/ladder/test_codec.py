"""Tests for clicknick.ladder.codec — ClickCodec encode/decode."""

from clicknick.ladder.codec import BUFFER_SIZE, ClickCodec, _load_template
from clicknick.ladder.model import Coil, Contact, InstructionType, RungGrid

codec = ClickCodec()
off = ClickCodec.Offsets


class TestTemplateRoundTrip:
    def test_template_encodes_to_itself(self):
        """Encoding the template's own content (X002 NO -> out(Y001)) must reproduce it exactly."""
        grid = RungGrid(
            contact=Contact(InstructionType.CONTACT_NO, "X002"),
            coil=Coil(InstructionType.COIL_OUT, "Y001"),
        )
        generated = codec.encode(grid)
        template = _load_template()
        assert generated == template


class TestEncodeDecodeRoundTrip:
    def test_no_contact(self):
        grid = RungGrid.from_csv("X001,->,:out(Y001)")
        data = codec.encode(grid)
        assert len(data) == BUFFER_SIZE
        decoded = codec.decode(data)
        assert decoded.contact.type == InstructionType.CONTACT_NO
        assert decoded.contact.operand == "X001"
        assert decoded.coil.operand == "Y001"

    def test_nc_contact(self):
        grid = RungGrid.from_csv("~X003,->,:out(Y002)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.contact.type == InstructionType.CONTACT_NC
        assert decoded.contact.operand == "X003"
        assert decoded.coil.operand == "Y002"

    def test_csv_round_trip(self):
        """encode -> decode -> to_csv should reproduce the original CSV."""
        csv = "X010,->,:out(Y100)"
        grid = RungGrid.from_csv(csv)
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.to_csv() == csv


class TestNCByteDiffs:
    def test_nc_differs_from_no_at_type_id(self):
        """NC contact should differ from NO template at the contact type ID byte."""
        no_grid = RungGrid(
            contact=Contact(InstructionType.CONTACT_NO, "X002"),
            coil=Coil(InstructionType.COIL_OUT, "Y001"),
        )
        nc_grid = RungGrid(
            contact=Contact(InstructionType.CONTACT_NC, "X002"),
            coil=Coil(InstructionType.COIL_OUT, "Y001"),
        )
        no_data = codec.encode(no_grid)
        nc_data = codec.encode(nc_grid)

        # Type ID byte should differ
        assert no_data[off.CONTACT_TYPE_ID] == InstructionType.CONTACT_NO
        assert nc_data[off.CONTACT_TYPE_ID] == InstructionType.CONTACT_NC

        # Function code should differ (4097 vs 4098)
        fc_start = off.CONTACT_FUNC_CODE
        fc_end = fc_start + 8  # 4 chars * 2 bytes UTF-16LE
        assert no_data[fc_start:fc_end] == "4097".encode("utf-16-le")
        assert nc_data[fc_start:fc_end] == "4098".encode("utf-16-le")


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
