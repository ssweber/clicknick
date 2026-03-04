"""Tests for clicknick.ladder.codec — ClickCodec encode/decode."""

from pathlib import Path

import pytest

from clicknick.ladder import codec as codec_module
from clicknick.ladder.codec import BUFFER_SIZE, ClickCodec, HeaderSeed, _load_scaffold
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
            assert (
                data[entry_start : entry_start + HEADER_ENTRY_SIZE]
                == scaffold[entry_start : entry_start + HEADER_ENTRY_SIZE]
            )

    def test_second_immediate_header_compat_applies_without_explicit_seed(self):
        data = codec.encode(RungGrid.from_csv("X001,X002.immediate,->,:,out(Y001)"))
        for column in range(HEADER_ENTRY_COUNT):
            entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
            assert data[entry_start + 0x05] == 0x04
            assert data[entry_start + 0x11] == 0x0B
        assert data[0x0A59] == 0x04

    def test_encode_applies_explicit_header_seed(self):
        seed = HeaderSeed(profile_05=0x31, profile_11=0x62, family_17=0x58, family_18=0x01)
        data = codec.encode(RungGrid.from_csv("X001,X002,->,:,out(Y001)"), header_seed=seed)
        for column in range(HEADER_ENTRY_COUNT):
            entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
            assert data[entry_start + 0x05] == 0x31
            assert data[entry_start + 0x11] == 0x62
            assert data[entry_start + 0x17] == 0x58
            assert data[entry_start + 0x18] == 0x01
        assert data[0x0A59] == 0x31

    def test_explicit_header_seed_disables_second_immediate_compat_override(self):
        seed = HeaderSeed(profile_05=0x21, profile_11=0x42, family_17=0x20, family_18=0x01)
        data = codec.encode(
            RungGrid.from_csv("X001,X002.immediate,->,:,out(Y001)"),
            header_seed=seed,
        )
        for column in range(HEADER_ENTRY_COUNT):
            entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
            assert data[entry_start + 0x05] == 0x21
            assert data[entry_start + 0x11] == 0x42
            assert data[entry_start + 0x17] == 0x20
            assert data[entry_start + 0x18] == 0x01
        assert data[0x0A59] == 0x21

    def test_header_seed_from_payload_apply_roundtrip(self):
        payload = bytearray(_load_scaffold())
        for column in range(HEADER_ENTRY_COUNT):
            entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
            payload[entry_start + 0x05] = 0x12
            payload[entry_start + 0x11] = 0x27
            payload[entry_start + 0x17] = 0x58
            payload[entry_start + 0x18] = 0x01
        payload[0x0A59] = 0x12

        seed = HeaderSeed.from_payload(bytes(payload))
        assert seed == HeaderSeed(profile_05=0x12, profile_11=0x27, family_17=0x58, family_18=0x01)

        buf = bytearray(_load_scaffold())
        seed.apply_to_buffer(buf)
        for column in range(HEADER_ENTRY_COUNT):
            entry_start = HEADER_ENTRY_BASE + column * HEADER_ENTRY_SIZE
            assert buf[entry_start + 0x05] == 0x12
            assert buf[entry_start + 0x11] == 0x27
            assert buf[entry_start + 0x17] == 0x58
            assert buf[entry_start + 0x18] == 0x01
        assert buf[0x0A59] == 0x12


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

    def test_contact_rise(self):
        grid = RungGrid.from_csv("rise(X001),->,:,out(Y001)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.contact.type == InstructionType.CONTACT_EDGE
        assert decoded.contact.edge_kind == "rise"
        assert decoded.to_csv() == "rise(X001),->,:,out(Y001)"

    def test_contact_fall(self):
        grid = RungGrid.from_csv("fall(X001),->,:,out(Y001)")
        data = codec.encode(grid)
        decoded = codec.decode(data)
        assert decoded.contact.type == InstructionType.CONTACT_EDGE
        assert decoded.contact.edge_kind == "fall"
        assert decoded.to_csv() == "fall(X001),->,:,out(Y001)"

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
        for csv, expected in (
            ("C1,->,:,out(Y001)", "C1,->,:,out(Y001)"),
            ("CT1,->,:,out(Y001)", "CT1,->,:,out(Y001)"),
            ("X1,->,:,out(Y001)", "X001,->,:,out(Y001)"),
            ("X1.immediate,->,:,out(Y001)", "X001.immediate,->,:,out(Y001)"),
        ):
            decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
            assert decoded.to_csv() == expected

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

    def test_two_series_rise_then_no(self):
        csv = "rise(X001),X002,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == csv

    def test_two_series_accepts_non_4_char_contacts(self):
        csv = "X1,X002,->,:,out(Y001)"
        decoded = codec.decode(codec.encode(RungGrid.from_csv(csv)))
        assert decoded.to_csv() == "X001,X002,->,:,out(Y001)"

    def test_same_rung_with_different_seed_family_bytes_keeps_decode_and_topology(self):
        csv = "~X001,X002,->,:,out(Y001)"
        grid = RungGrid.from_csv(csv)
        payload_a = codec.encode(
            grid,
            header_seed=HeaderSeed(profile_05=0x00, profile_11=0x00, family_17=0x58, family_18=0x01),
        )
        payload_b = codec.encode(
            grid,
            header_seed=HeaderSeed(profile_05=0x00, profile_11=0x00, family_17=0x20, family_18=0x01),
        )
        assert codec.decode(payload_a).to_csv() == csv
        assert codec.decode(payload_b).to_csv() == csv
        assert codec.decode_wire_topology(payload_a) == codec.decode_wire_topology(payload_b)

    @pytest.mark.parametrize(
        "csv",
        [
            "X001,X002,X003,->,:,out(Y001)",
            "X001,X002,X003,X004,X005,->,:,out(Y001)",
            "X001,X002,X003,X004,X005,X006,X007,X008,->,:,out(Y001)",
        ],
    )
    def test_more_than_two_series_is_blocked_for_click_safe_encoding(self, csv: str):
        with pytest.raises(ValueError, match="Only 1 or 2 series contacts"):
            codec.encode(RungGrid.from_csv(csv))

    @pytest.mark.parametrize(
        ("csv", "meta_shift"),
        [
            ("X001,X002,->,:,out(Y001)", 0),
            ("X001.immediate,X002,->,:,out(Y001)", 2),
            ("X001,X002.immediate,->,:,out(Y001)", 2),
            ("X001.immediate,X002.immediate,->,:,out(Y001)", 4),
        ],
    )
    def test_two_series_injects_second_contact_label_and_row1_metadata(
        self, csv: str, meta_shift: int
    ):
        data = codec.encode(RungGrid.from_csv(csv))
        label = "ContactNO\0".encode("utf-16-le")
        contact_offsets = [
            i
            for i in range(0x0A60, 0x1A60 - 1)
            if data[i + 1] == 0x27 and data[i] in (0x11, 0x12, 0x13)
        ]
        assert len(contact_offsets) >= 2
        second_offset = contact_offsets[1]
        assert data[second_offset - len(label) : second_offset] == label
        assert data[0x1331 + meta_shift] == 0x03
        assert data[0x1335 + meta_shift] == 0x02
        assert data[0x133E + meta_shift] == 0x01
        assert data[0x1347 + meta_shift] == 0x01
        assert data[0x134A + meta_shift] == 0x01

    @pytest.mark.parametrize(
        ("csv", "expected_col4_flags"),
        [
            ("X001,X002,->,:,out(Y001)", (True, False, False)),
            ("X001.immediate,X002,->,:,out(Y001)", (True, True, False)),
            ("X001,X002.immediate,->,:,out(Y001)", (True, True, False)),
            ("X001.immediate,X002.immediate,->,:,out(Y001)", (False, True, False)),
            ("rise(X001),X002,->,:,out(Y001)", (True, True, False)),
        ],
    )
    def test_two_series_col4_topology_flags_by_contact_variant(
        self,
        csv: str,
        expected_col4_flags: tuple[bool, bool, bool],
    ):
        data = codec.encode(RungGrid.from_csv(csv))
        topo = codec.decode_wire_topology(data)
        flags = topo.flags_at(0, 4)
        assert flags is not None
        assert (
            flags.horizontal_left,
            flags.horizontal_right,
            flags.vertical_down,
        ) == expected_col4_flags

    @pytest.mark.parametrize(
        ("csv", "expected_control"),
        [
            ("X001,X002,->,:,out(Y001)", (0xFF, 0x01)),
            ("X001.immediate,X002,->,:,out(Y001)", (0xFF, 0xFF)),
            ("X001,X002.immediate,->,:,out(Y001)", (0xFF, 0xFF)),
            ("X001.immediate,X002.immediate,->,:,out(Y001)", (0x00, 0xFF)),
            ("rise(X001),X002,->,:,out(Y001)", (0x00, 0x00)),
            ("fall(X001),X002,->,:,out(Y001)", (0x00, 0x00)),
            ("C1,X002,->,:,out(Y001)", (0x00, 0x00)),
            ("X001,C2,->,:,out(Y001)", (0x00, 0x00)),
        ],
    )
    def test_two_series_control_profile_bytes_by_contact_variant(
        self,
        csv: str,
        expected_control: tuple[int, int],
    ):
        data = codec.encode(RungGrid.from_csv(csv))
        row0_col4 = 0x0A60 + 4 * 0x40
        row1_col0 = 0x1260
        expected_1a, expected_1b = expected_control

        assert data[row0_col4 + 0x1A] == expected_1a
        assert data[row0_col4 + 0x1B] == expected_1b
        assert data[row1_col0 + 0x1A] == expected_1a
        assert data[row1_col0 + 0x1B] == expected_1b

    @pytest.mark.parametrize(
        ("csv", "expected_profile"),
        [
            ("X001,X002,->,:,out(Y001)", (0x00, 0x00)),
            ("X001.immediate,X002,->,:,out(Y001)", (0x00, 0x01)),
            ("X001,X002.immediate,->,:,out(Y001)", (0x04, 0x0C)),
            ("X001.immediate,X002.immediate,->,:,out(Y001)", (0x00, 0x00)),
            ("~X001,X002,->,:,out(Y001)", (0x00, 0x00)),
            ("~X001,~X002,->,:,out(Y001)", (0x00, 0x00)),
            ("rise(X001),X002,->,:,out(Y001)", (0x01, 0x01)),
            ("fall(X001),X002,->,:,out(Y001)", (0x01, 0x01)),
            ("X001,rise(X002),->,:,out(Y001)", (0x01, 0x01)),
            ("rise(X001),rise(X002),->,:,out(Y001)", (0xFF, 0x00)),
        ],
    )
    def test_two_series_profile_05_11_bytes_by_contact_variant(
        self,
        csv: str,
        expected_profile: tuple[int, int],
    ):
        data = codec.encode(RungGrid.from_csv(csv))
        row0_col4 = 0x0A60 + 4 * 0x40
        row1_col0 = 0x1260
        expected_05, expected_11 = expected_profile

        assert data[row0_col4 + 0x05] == expected_05
        assert data[row0_col4 + 0x11] == expected_11
        assert data[row1_col0 + 0x05] == expected_05
        assert data[row1_col0 + 0x11] == expected_11

    @pytest.mark.parametrize(
        ("csv", "expected_row1_col1_hleft"),
        [
            ("X001,X002,->,:,out(Y001)", 0x00),
            ("X001.immediate,X002,->,:,out(Y001)", 0x02),
            ("X001,X002.immediate,->,:,out(Y001)", 0x02),
            ("X001.immediate,X002.immediate,->,:,out(Y001)", 0x00),
            ("X001,~X002,->,:,out(Y001)", 0x00),
        ],
    )
    def test_two_series_row1_col1_profile_tracks_row1_col0(
        self,
        csv: str,
        expected_row1_col1_hleft: int,
    ):
        data = codec.encode(RungGrid.from_csv(csv))
        row1_col0 = 0x1260
        row1_col1 = 0x12A0
        assert data[row1_col1 + 0x05] == data[row1_col0 + 0x05]
        assert data[row1_col1 + 0x11] == data[row1_col0 + 0x11]
        assert data[row1_col1 + 0x1A] == data[row1_col0 + 0x1A]
        assert data[row1_col1 + 0x1B] == data[row1_col0 + 0x1B]
        assert data[row1_col1 + 0x19] == expected_row1_col1_hleft


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

    @pytest.mark.parametrize(
        ("filename", "expected_csv"),
        [
            ("smoke_simple_native.bin", "X001,->,:,out(Y001)"),
            ("smoke_immediate_native.bin", "X001.immediate,->,:,out(Y001)"),
            ("smoke_range_native.bin", "X001,->,:,out(C1..C2)"),
            ("smoke_two_series_short_native.bin", "X001,X002,->,:,out(Y001)"),
        ],
    )
    def test_decode_smoke_native_fixtures(self, filename: str, expected_csv: str):
        g = self._decode_fixture(filename)
        assert g.to_csv() == expected_csv

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
