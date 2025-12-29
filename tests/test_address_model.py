"""Unit tests for address_editor.address_model module."""

import pytest

from clicknick.models.address_row import AddressRow, get_addr_key, parse_addr_key
from clicknick.models.blocktag import (
    BlockTag,
    extract_block_name,
    get_block_type,
    is_block_tag,
    parse_block_tag,
    strip_block_tag,
)
from clicknick.models.constants import (
    ADDRESS_RANGES,
    DEFAULT_RETENTIVE,
    FORBIDDEN_CHARS,
    MEMORY_TYPE_BASES,
    MEMORY_TYPE_TO_DATA_TYPE,
    NICKNAME_MAX_LENGTH,
    NON_EDITABLE_TYPES,
    PAIRED_RETENTIVE_TYPES,
    DataType,
)
from clicknick.models.validation import validate_initial_value, validate_nickname


class TestAddrKeyCalculation:
    """Tests for AddrKey calculation and parsing."""

    def test_get_addr_key_basic(self):
        """Test basic AddrKey calculation for common types."""
        assert get_addr_key("X", 1) == 0x0000001
        assert get_addr_key("Y", 1) == 0x1000001
        assert get_addr_key("C", 100) == 0x2000064
        assert get_addr_key("DS", 1) == 0x6000001

    def test_get_addr_key_all_types(self):
        """Test AddrKey calculation for all 16 memory types."""
        expected_bases = {
            "X": 0x0000000,
            "Y": 0x1000000,
            "C": 0x2000000,
            "T": 0x3000000,
            "CT": 0x4000000,
            "SC": 0x5000000,
            "DS": 0x6000000,
            "DD": 0x7000000,
            "DH": 0x8000000,
            "DF": 0x9000000,
            "XD": 0xA000000,
            "YD": 0xB000000,
            "TD": 0xC000000,
            "CTD": 0xD000000,
            "SD": 0xE000000,
            "TXT": 0xF000000,
        }
        for memory_type, base in expected_bases.items():
            assert get_addr_key(memory_type, 0) == base
            assert get_addr_key(memory_type, 1) == base + 1
            assert get_addr_key(memory_type, 999) == base + 999

    def test_get_addr_key_invalid_type(self):
        """Test that invalid memory type raises KeyError."""
        with pytest.raises(KeyError):
            get_addr_key("INVALID", 1)

    def test_parse_addr_key_basic(self):
        """Test basic AddrKey parsing."""
        assert parse_addr_key(0x0000001) == ("X", 1)
        assert parse_addr_key(0x1000001) == ("Y", 1)
        assert parse_addr_key(0x2000064) == ("C", 100)
        assert parse_addr_key(0x6000001) == ("DS", 1)

    def test_parse_addr_key_all_types(self):
        """Test AddrKey parsing for all 16 memory types."""
        for memory_type in MEMORY_TYPE_BASES:
            for address in [0, 1, 100, 999, 4500]:
                addr_key = get_addr_key(memory_type, address)
                parsed_type, parsed_addr = parse_addr_key(addr_key)
                assert parsed_type == memory_type
                assert parsed_addr == address

    def test_parse_addr_key_roundtrip(self):
        """Test that get_addr_key and parse_addr_key are inverses."""
        test_cases = [
            ("X", 1),
            ("Y", 816),
            ("C", 2000),
            ("DS", 4500),
            ("XD", 0),
            ("TXT", 1000),
        ]
        for memory_type, address in test_cases:
            addr_key = get_addr_key(memory_type, address)
            parsed = parse_addr_key(addr_key)
            assert parsed == (memory_type, address)

    def test_xd_yd_display_functions(self):
        """Test XD/YD display address formatting and parsing."""
        from clicknick.models.address_row import (
            format_address_display,
            is_xd_yd_hidden_slot,
            is_xd_yd_upper_byte,
            parse_address_display,
            xd_yd_display_to_mdb,
            xd_yd_mdb_to_display,
        )

        # XD/YD structure:
        # MDB 0 = XD0, MDB 1 = XD0u (only slot 0 has upper byte variant)
        # MDB 2 = XD1, MDB 4 = XD2, ... MDB 16 = XD8
        # MDB 3, 5, 7, ... 15 are hidden upper byte slots

        # Test xd_yd_mdb_to_display
        assert xd_yd_mdb_to_display(0) == 0  # XD0
        assert xd_yd_mdb_to_display(1) == 0  # XD0u
        assert xd_yd_mdb_to_display(2) == 1  # XD1
        assert xd_yd_mdb_to_display(4) == 2  # XD2
        assert xd_yd_mdb_to_display(16) == 8  # XD8

        # Test xd_yd_display_to_mdb
        assert xd_yd_display_to_mdb(0) == 0  # XD0
        assert xd_yd_display_to_mdb(0, upper_byte=True) == 1  # XD0u
        assert xd_yd_display_to_mdb(1) == 2  # XD1
        assert xd_yd_display_to_mdb(8) == 16  # XD8

        # Test is_xd_yd_upper_byte (only MDB 1 is upper byte)
        assert is_xd_yd_upper_byte("XD", 0) is False
        assert is_xd_yd_upper_byte("XD", 1) is True
        assert is_xd_yd_upper_byte("XD", 2) is False
        assert is_xd_yd_upper_byte("XD", 3) is False  # Hidden, but not displayed as upper
        assert is_xd_yd_upper_byte("YD", 1) is True
        assert is_xd_yd_upper_byte("DS", 1) is False  # Non-XD/YD

        # Test is_xd_yd_hidden_slot
        assert is_xd_yd_hidden_slot("XD", 0) is False  # XD0
        assert is_xd_yd_hidden_slot("XD", 1) is False  # XD0u (displayed)
        assert is_xd_yd_hidden_slot("XD", 2) is False  # XD1
        assert is_xd_yd_hidden_slot("XD", 3) is True  # Hidden
        assert is_xd_yd_hidden_slot("XD", 5) is True  # Hidden
        assert is_xd_yd_hidden_slot("XD", 16) is False  # XD8
        assert is_xd_yd_hidden_slot("DS", 3) is False  # Non-XD/YD

        # Test format_address_display
        assert format_address_display("XD", 0) == "XD0"
        assert format_address_display("XD", 1) == "XD0u"
        assert format_address_display("XD", 2) == "XD1"
        assert format_address_display("XD", 4) == "XD2"
        assert format_address_display("XD", 16) == "XD8"
        assert format_address_display("YD", 0) == "YD0"
        assert format_address_display("YD", 1) == "YD0u"
        assert format_address_display("DS", 100) == "DS100"  # Non-XD/YD unchanged

        # Test parse_address_display
        assert parse_address_display("XD0") == ("XD", 0)
        assert parse_address_display("XD0u") == ("XD", 1)
        assert parse_address_display("XD1") == ("XD", 2)
        assert parse_address_display("XD2") == ("XD", 4)
        assert parse_address_display("XD8") == ("XD", 16)
        assert parse_address_display("YD0u") == ("YD", 1)
        assert parse_address_display("YD8") == ("YD", 16)
        assert parse_address_display("DS100") == ("DS", 100)
        assert parse_address_display("X001") == ("X", 1)
        assert parse_address_display("XD1u") is None  # Invalid: only XD0 has u variant
        assert parse_address_display("INVALID") is None
        assert parse_address_display("") is None

    def test_parse_addr_key_invalid_type_index(self):
        """Test that invalid type index raises KeyError."""
        # 0x10000001 would have type index 16, which doesn't exist
        with pytest.raises(KeyError):
            parse_addr_key(0x10000001)


class TestValidateNickname:
    """Tests for nickname validation."""

    def test_empty_nickname_is_valid(self):
        """Empty nickname is valid (means unassigned)."""
        is_valid, error = validate_nickname("", {}, 0)
        assert is_valid is True
        assert error == ""

    def test_valid_simple_nickname(self):
        """Simple alphanumeric nicknames are valid."""
        is_valid, error = validate_nickname("StartButton", {}, 0)
        assert is_valid is True
        assert error == ""

    def test_valid_nickname_with_space(self):
        """Nicknames with spaces are valid."""
        is_valid, error = validate_nickname("Start Button", {}, 0)
        assert is_valid is True
        assert error == ""

    def test_valid_nickname_with_underscore(self):
        """Nicknames with underscores (not at start) are valid."""
        is_valid, error = validate_nickname("Start_Button", {}, 0)
        assert is_valid is True
        assert error == ""

    def test_max_length_exactly_24(self):
        """Nickname of exactly 24 characters is valid."""
        nickname = "A" * NICKNAME_MAX_LENGTH
        is_valid, error = validate_nickname(nickname, {}, 0)
        assert is_valid is True
        assert error == ""

    def test_too_long_25_chars(self):
        """Nickname of 25 characters is too long."""
        nickname = "A" * 25
        is_valid, error = validate_nickname(nickname, {}, 0)
        assert is_valid is False
        assert "Too long" in error
        assert "25/24" in error

    def test_leading_underscore_invalid(self):
        """Nicknames starting with underscore are invalid."""
        is_valid, error = validate_nickname("_StartButton", {}, 0)
        assert is_valid is False
        assert "Cannot start with _" in error

    def test_forbidden_characters(self):
        """Test all forbidden characters are detected."""
        for char in FORBIDDEN_CHARS:
            nickname = f"Test{char}Name"
            is_valid, error = validate_nickname(nickname, {}, 0)
            assert is_valid is False, f"Character '{char}' should be forbidden"
            assert "Invalid:" in error

    def test_hyphen_forbidden(self):
        """Hyphen is explicitly forbidden."""
        is_valid, error = validate_nickname("Start-Button", {}, 0)
        assert is_valid is False
        assert "Invalid:" in error
        assert "-" in error

    def test_period_forbidden(self):
        """Period is explicitly forbidden."""
        is_valid, error = validate_nickname("Start.Button", {}, 0)
        assert is_valid is False
        assert "Invalid:" in error
        assert "." in error

    def test_duplicate_detection(self):
        """Duplicate nicknames are detected."""
        all_nicknames = {
            0x0000001: "StartButton",
            0x0000002: "StopButton",
        }
        # Try to use "StartButton" at a different address
        is_valid, error = validate_nickname("StartButton", all_nicknames, 0x0000003)
        assert is_valid is False
        assert "Duplicate" in error

    def test_same_address_not_duplicate(self):
        """Same nickname at same address is not a duplicate."""
        all_nicknames = {
            0x0000001: "StartButton",
        }
        # Same nickname at same address should be valid
        is_valid, error = validate_nickname("StartButton", all_nicknames, 0x0000001)
        assert is_valid is True
        assert error == ""

    def test_multiple_invalid_chars_shows_first_few(self):
        """Multiple invalid chars shows first 3 sorted."""
        nickname = "Test%$#Name"  # Has %, $, #
        is_valid, error = validate_nickname(nickname, {}, 0)
        assert is_valid is False
        assert "Invalid:" in error


class TestAddressRow:
    """Tests for AddressRow dataclass."""

    def test_basic_creation(self):
        """Test basic AddressRow creation."""
        row = AddressRow(memory_type="X", address=1, nickname="StartButton")
        assert row.memory_type == "X"
        assert row.address == 1
        assert row.nickname == "StartButton"
        assert row.original_nickname == "StartButton"

    def test_display_address(self):
        """Test display_address property."""
        row = AddressRow(memory_type="X", address=1)
        assert row.display_address == "X1"

        row = AddressRow(memory_type="DS", address=100)
        assert row.display_address == "DS100"

    def test_addr_key_property(self):
        """Test addr_key property."""
        row = AddressRow(memory_type="X", address=1)
        assert row.addr_key == 0x0000001

        row = AddressRow(memory_type="DS", address=100)
        assert row.addr_key == 0x6000064

    def test_is_dirty_when_modified(self):
        """Test is_dirty when nickname differs from original."""
        row = AddressRow(
            memory_type="X", address=1, nickname="NewName", original_nickname="OldName"
        )
        assert row.is_dirty is True

    def test_is_dirty_when_unchanged(self):
        """Test is_dirty when nickname matches original."""
        row = AddressRow(
            memory_type="X", address=1, nickname="SameName", original_nickname="SameName"
        )
        assert row.is_dirty is False

    def test_is_virtual_no_original(self):
        """Test is_virtual when there's no original nickname."""
        row = AddressRow(memory_type="X", address=1, nickname="", original_nickname="")
        assert row.is_virtual is True

    def test_is_virtual_has_original(self):
        """Test is_virtual when row exists in MDB."""
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="Name",
            original_nickname="Name",
            exists_in_mdb=True,
        )
        assert row.is_virtual is False

    def test_is_empty(self):
        """Test is_empty property."""
        row = AddressRow(memory_type="X", address=1, nickname="")
        assert row.is_empty is True

        row = AddressRow(memory_type="X", address=1, nickname="Name")
        assert row.is_empty is False

    def test_needs_insert(self):
        """Test needs_insert: dirty, has nickname, was virtual."""
        # Virtual row (not in MDB) with new nickname
        row = AddressRow(memory_type="X", address=1, nickname="NewName", original_nickname="")
        assert row.needs_insert is True

        # Exists in MDB, so not virtual - needs update instead
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="NewName",
            original_nickname="OldName",
            exists_in_mdb=True,
        )
        assert row.needs_insert is False

    def test_needs_update(self):
        """Test needs_update: dirty, has nickname, was NOT virtual."""
        # Exists in MDB (not virtual), nickname changed
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="NewName",
            original_nickname="OldName",
            exists_in_mdb=True,
        )
        assert row.needs_update is True

        # Virtual row doesn't need update (needs insert instead)
        row = AddressRow(memory_type="X", address=1, nickname="NewName", original_nickname="")
        assert row.needs_update is False

    def test_needs_nickname_clear_only(self):
        """Test needs_nickname_clear_only: nickname cleared but has comment or is used (keep row)."""
        # Exists in MDB, nickname cleared, but has comment - needs_nickname_clear_only (clear nickname, keep row)
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="",
            original_nickname="OldName",
            comment="Keep me",
            exists_in_mdb=True,
        )
        assert row.needs_nickname_clear_only is True

        # Exists in MDB, nickname cleared, address is used - needs_nickname_clear_only (clear nickname, keep row)
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="",
            original_nickname="OldName",
            used=True,
            exists_in_mdb=True,
        )
        assert row.needs_nickname_clear_only is True

        # Exists in MDB, nickname cleared, no comment, not used - needs_full_delete instead
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="",
            original_nickname="OldName",
            exists_in_mdb=True,
        )
        assert row.needs_nickname_clear_only is False
        assert row.needs_full_delete is True

        # Virtual row with no nickname - no delete needed
        row = AddressRow(memory_type="X", address=1, nickname="", original_nickname="")
        assert row.needs_nickname_clear_only is False
        assert row.needs_full_delete is False

    def test_mark_saved(self):
        """Test mark_saved updates original_nickname."""
        row = AddressRow(
            memory_type="X", address=1, nickname="NewName", original_nickname="OldName"
        )
        assert row.is_dirty is True

        row.mark_saved()

        assert row.original_nickname == "NewName"
        assert row.is_dirty is False

    def test_validate_method(self):
        """Test validate method updates validation state."""
        row = AddressRow(memory_type="X", address=1, nickname="ValidName")
        row.validate({})
        assert row.is_valid is True
        assert row.validation_error == ""

        row = AddressRow(memory_type="X", address=1, nickname="_InvalidName")
        row.validate({})
        assert row.is_valid is False
        assert "Cannot start with _" in row.validation_error


class TestAddressRanges:
    """Tests for ADDRESS_RANGES constant."""

    def test_all_types_have_ranges(self):
        """All memory types should have defined ranges."""
        assert len(ADDRESS_RANGES) == 16
        for memory_type in MEMORY_TYPE_BASES:
            assert memory_type in ADDRESS_RANGES

    def test_xd_yd_start_at_zero(self):
        """XD and YD should start at 0."""
        assert ADDRESS_RANGES["XD"][0] == 0
        assert ADDRESS_RANGES["YD"][0] == 0

    def test_other_types_start_at_one(self):
        """Most types should start at 1."""
        for memory_type, (start, _) in ADDRESS_RANGES.items():
            if memory_type not in ("XD", "YD"):
                assert start == 1, f"{memory_type} should start at 1"

    def test_specific_ranges(self):
        """Test specific expected ranges."""
        assert ADDRESS_RANGES["X"] == (1, 816)
        assert ADDRESS_RANGES["Y"] == (1, 816)
        assert ADDRESS_RANGES["C"] == (1, 2000)
        assert ADDRESS_RANGES["DS"] == (1, 4500)
        assert ADDRESS_RANGES["T"] == (1, 500)
        assert ADDRESS_RANGES["CT"] == (1, 250)


class TestValidateInitialValue:
    """Tests for initial value validation."""

    def test_empty_initial_value_valid(self):
        """Empty initial value is always valid."""
        is_valid, error = validate_initial_value("", DataType.BIT)
        assert is_valid is True
        assert error == ""

    # Bit type tests
    def test_bit_value_zero_valid(self):
        """Bit value 0 is valid."""
        is_valid, error = validate_initial_value("0", DataType.BIT)
        assert is_valid is True
        assert error == ""

    def test_bit_value_one_valid(self):
        """Bit value 1 is valid."""
        is_valid, error = validate_initial_value("1", DataType.BIT)
        assert is_valid is True
        assert error == ""

    def test_bit_value_two_invalid(self):
        """Bit value 2 is invalid."""
        is_valid, error = validate_initial_value("2", DataType.BIT)
        assert is_valid is False
        assert "0 or 1" in error

    def test_bit_value_text_invalid(self):
        """Bit value text is invalid."""
        is_valid, error = validate_initial_value("yes", DataType.BIT)
        assert is_valid is False

    # Int (16-bit) type tests
    def test_int_value_zero_valid(self):
        """Int value 0 is valid."""
        is_valid, error = validate_initial_value("0", DataType.INT)
        assert is_valid is True

    def test_int_value_min_valid(self):
        """Int minimum value -32768 is valid."""
        is_valid, error = validate_initial_value("-32768", DataType.INT)
        assert is_valid is True

    def test_int_value_max_valid(self):
        """Int maximum value 32767 is valid."""
        is_valid, error = validate_initial_value("32767", DataType.INT)
        assert is_valid is True

    def test_int_value_too_low_invalid(self):
        """Int value below minimum is invalid."""
        is_valid, error = validate_initial_value("-32769", DataType.INT)
        assert is_valid is False
        assert "Range" in error

    def test_int_value_too_high_invalid(self):
        """Int value above maximum is invalid."""
        is_valid, error = validate_initial_value("32768", DataType.INT)
        assert is_valid is False
        assert "Range" in error

    def test_int_value_text_invalid(self):
        """Int value text is invalid."""
        is_valid, error = validate_initial_value("abc", DataType.INT)
        assert is_valid is False
        assert "integer" in error

    # Int2 (32-bit) type tests
    def test_int2_value_zero_valid(self):
        """Int2 value 0 is valid."""
        is_valid, error = validate_initial_value("0", DataType.INT2)
        assert is_valid is True

    def test_int2_value_min_valid(self):
        """Int2 minimum value is valid."""
        is_valid, error = validate_initial_value("-2147483648", DataType.INT2)
        assert is_valid is True

    def test_int2_value_max_valid(self):
        """Int2 maximum value is valid."""
        is_valid, error = validate_initial_value("2147483647", DataType.INT2)
        assert is_valid is True

    def test_int2_value_too_low_invalid(self):
        """Int2 value below minimum is invalid."""
        is_valid, error = validate_initial_value("-2147483649", DataType.INT2)
        assert is_valid is False

    def test_int2_value_too_high_invalid(self):
        """Int2 value above maximum is invalid."""
        is_valid, error = validate_initial_value("2147483648", DataType.INT2)
        assert is_valid is False

    # Float type tests
    def test_float_value_zero_valid(self):
        """Float value 0 is valid."""
        is_valid, error = validate_initial_value("0", DataType.FLOAT)
        assert is_valid is True

    def test_float_value_decimal_valid(self):
        """Float decimal value is valid."""
        is_valid, error = validate_initial_value("3.14159", DataType.FLOAT)
        assert is_valid is True

    def test_float_value_scientific_valid(self):
        """Float scientific notation is valid."""
        is_valid, error = validate_initial_value("-3.4028235E+38", DataType.FLOAT)
        assert is_valid is True

    def test_float_value_text_invalid(self):
        """Float text value is invalid."""
        is_valid, error = validate_initial_value("abc", DataType.FLOAT)
        assert is_valid is False
        assert "number" in error

    # Hex type tests
    def test_hex_value_zero_valid(self):
        """Hex value 0 is valid."""
        is_valid, error = validate_initial_value("0", DataType.HEX)
        assert is_valid is True

    def test_hex_value_0000_valid(self):
        """Hex value 0000 is valid."""
        is_valid, error = validate_initial_value("0000", DataType.HEX)
        assert is_valid is True

    def test_hex_value_FFFF_valid(self):
        """Hex value FFFF is valid."""
        is_valid, error = validate_initial_value("FFFF", DataType.HEX)
        assert is_valid is True

    def test_hex_value_lowercase_valid(self):
        """Hex lowercase value is valid."""
        is_valid, error = validate_initial_value("abcd", DataType.HEX)
        assert is_valid is True

    def test_hex_value_too_long_invalid(self):
        """Hex value longer than 4 digits is invalid."""
        is_valid, error = validate_initial_value("12345", DataType.HEX)
        assert is_valid is False
        assert "4 hex" in error

    def test_hex_value_invalid_chars(self):
        """Hex value with invalid characters is invalid."""
        is_valid, error = validate_initial_value("GHIJ", DataType.HEX)
        assert is_valid is False
        assert "hex" in error

    # TXT type tests
    def test_txt_value_single_char_valid(self):
        """TXT single character is valid."""
        is_valid, error = validate_initial_value("A", DataType.TXT)
        assert is_valid is True

    def test_txt_value_space_valid(self):
        """TXT space character is valid."""
        is_valid, error = validate_initial_value(" ", DataType.TXT)
        assert is_valid is True

    def test_txt_value_too_long_invalid(self):
        """TXT multiple characters is invalid."""
        is_valid, error = validate_initial_value("AB", DataType.TXT)
        assert is_valid is False
        assert "single char" in error

    def test_txt_value_non_ascii_invalid(self):
        """TXT non-ASCII character is invalid."""
        is_valid, error = validate_initial_value("\x80", DataType.TXT)
        assert is_valid is False
        assert "ASCII" in error


class TestDataTypeConstants:
    """Tests for data type constants and mappings."""

    def test_memory_type_to_data_type_complete(self):
        """All memory types have a data type mapping."""
        for memory_type in MEMORY_TYPE_BASES:
            assert memory_type in MEMORY_TYPE_TO_DATA_TYPE

    def test_default_retentive_complete(self):
        """All memory types have a default retentive value."""
        for memory_type in MEMORY_TYPE_BASES:
            assert memory_type in DEFAULT_RETENTIVE

    def test_non_editable_types(self):
        """Non-editable types are correct."""
        # System types that can't be edited
        assert "SC" in NON_EDITABLE_TYPES
        assert "SD" in NON_EDITABLE_TYPES
        assert "XD" in NON_EDITABLE_TYPES
        assert "YD" in NON_EDITABLE_TYPES
        # Editable types should NOT be in the set
        assert "X" not in NON_EDITABLE_TYPES
        assert "DS" not in NON_EDITABLE_TYPES
        assert "C" not in NON_EDITABLE_TYPES
        # TD/CTD are editable (via paired T/CT row)
        assert "TD" not in NON_EDITABLE_TYPES
        assert "CTD" not in NON_EDITABLE_TYPES

    def test_paired_retentive_types(self):
        """Paired retentive types map TD->T and CTD->CT."""
        assert PAIRED_RETENTIVE_TYPES["TD"] == "T"
        assert PAIRED_RETENTIVE_TYPES["CTD"] == "CT"
        # Only TD and CTD should be paired
        assert len(PAIRED_RETENTIVE_TYPES) == 2

    def test_data_type_bit_types(self):
        """Bit types have correct data type."""
        bit_types = ["X", "Y", "C", "T", "CT", "SC"]
        for mem_type in bit_types:
            assert MEMORY_TYPE_TO_DATA_TYPE[mem_type] == DataType.BIT

    def test_data_type_int_types(self):
        """Int types have correct data type."""
        int_types = ["DS", "SD", "TD"]
        for mem_type in int_types:
            assert MEMORY_TYPE_TO_DATA_TYPE[mem_type] == DataType.INT

    def test_data_type_int2_types(self):
        """Int2 types have correct data type."""
        int2_types = ["DD", "CTD"]
        for mem_type in int2_types:
            assert MEMORY_TYPE_TO_DATA_TYPE[mem_type] == DataType.INT2

    def test_data_type_float_type(self):
        """Float type has correct data type."""
        assert MEMORY_TYPE_TO_DATA_TYPE["DF"] == DataType.FLOAT

    def test_data_type_hex_types(self):
        """Hex types have correct data type."""
        hex_types = ["DH", "XD", "YD"]
        for mem_type in hex_types:
            assert MEMORY_TYPE_TO_DATA_TYPE[mem_type] == DataType.HEX

    def test_data_type_txt_type(self):
        """TXT type has correct data type."""
        assert MEMORY_TYPE_TO_DATA_TYPE["TXT"] == DataType.TXT


class TestAddressRowInitialValueRetentive:
    """Tests for AddressRow initial value and retentive fields."""

    def test_row_with_initial_value(self):
        """Test AddressRow with initial value."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            data_type=DataType.INT,
            initial_value="100",
            original_initial_value="100",
        )
        assert row.initial_value == "100"
        assert row.is_initial_value_dirty is False

    def test_row_initial_value_dirty(self):
        """Test AddressRow detects dirty initial value."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            data_type=DataType.INT,
            initial_value="200",
            original_initial_value="100",
        )
        assert row.is_initial_value_dirty is True
        assert row.is_dirty is True

    def test_row_with_retentive(self):
        """Test AddressRow with retentive."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            retentive=True,
            original_retentive=True,
        )
        assert row.retentive is True
        assert row.is_retentive_dirty is False

    def test_row_retentive_dirty(self):
        """Test AddressRow detects dirty retentive."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            retentive=False,
            original_retentive=True,
        )
        assert row.is_retentive_dirty is True
        assert row.is_dirty is True

    def test_can_edit_initial_value_editable_type(self):
        """Test can_edit_initial_value for editable types."""
        row = AddressRow(memory_type="DS", address=1)
        assert row.can_edit_initial_value is True

        row = AddressRow(memory_type="X", address=1)
        assert row.can_edit_initial_value is True

    def test_can_edit_initial_value_non_editable_type(self):
        """Test can_edit_initial_value for non-editable types."""
        row = AddressRow(memory_type="SC", address=1)
        assert row.can_edit_initial_value is False

        row = AddressRow(memory_type="SD", address=1)
        assert row.can_edit_initial_value is False

    def test_can_edit_initial_value_paired_type(self):
        """Test can_edit_initial_value for paired types (TD/CTD are editable)."""
        row = AddressRow(memory_type="TD", address=1)
        assert row.can_edit_initial_value is True

        row = AddressRow(memory_type="CTD", address=1)
        assert row.can_edit_initial_value is True

    def test_can_edit_retentive_editable_type(self):
        """Test can_edit_retentive for editable types."""
        row = AddressRow(memory_type="DS", address=1)
        assert row.can_edit_retentive is True

    def test_can_edit_retentive_non_editable_type(self):
        """Test can_edit_retentive for non-editable types."""
        row = AddressRow(memory_type="SD", address=1)
        assert row.can_edit_retentive is False

    def test_validate_initial_value(self):
        """Test validate updates initial value validation state."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            data_type=DataType.INT,
            initial_value="100",
        )
        row.validate({})
        assert row.initial_value_valid is True
        assert row.initial_value_error == ""

    def test_validate_invalid_initial_value(self):
        """Test validate catches invalid initial value."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            data_type=DataType.INT,
            initial_value="abc",  # Invalid for int
        )
        row.validate({})
        assert row.initial_value_valid is False
        assert row.is_valid is False  # Overall validity includes initial value
        assert "integer" in row.initial_value_error

    def test_mark_saved_includes_new_fields(self):
        """Test mark_saved resets initial value and retentive dirty tracking."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            initial_value="200",
            original_initial_value="100",
            retentive=True,
            original_retentive=False,
        )
        assert row.is_dirty is True

        row.mark_saved()

        assert row.original_initial_value == "200"
        assert row.original_retentive is True
        assert row.is_dirty is False

    def test_has_content_with_initial_value(self):
        """Test has_content includes initial value."""
        row = AddressRow(
            memory_type="X",  # Default retentive is False
            address=1,
            initial_value="1",
        )
        assert row.has_content is True

    def test_has_content_with_non_default_retentive(self):
        """Test has_content includes non-default retentive."""
        row = AddressRow(
            memory_type="X",  # Default retentive is False
            address=1,
            retentive=True,  # Non-default
        )
        assert row.has_content is True

    def test_needs_full_delete_checks_initial_value(self):
        """Test needs_full_delete considers initial value."""
        # Row with initial value should not be fully deleted
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="",
            original_nickname="Name",
            initial_value="1",
            exists_in_mdb=True,
        )
        assert row.needs_full_delete is False

    def test_needs_full_delete_checks_retentive(self):
        """Test needs_full_delete considers non-default retentive."""
        # Row with non-default retentive should not be fully deleted
        row = AddressRow(
            memory_type="X",  # Default is False
            address=1,
            nickname="",
            original_nickname="Name",
            retentive=True,  # Non-default
            exists_in_mdb=True,
        )
        assert row.needs_full_delete is False


class TestUpdateFromDb:
    """Tests for AddressRow.update_from_db() method."""

    def test_update_from_db_updates_non_dirty_nickname(self):
        """Non-dirty nickname should be updated from db."""
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="OldName",
            original_nickname="OldName",
            exists_in_mdb=True,
        )
        assert row.is_nickname_dirty is False

        changed = row.update_from_db({"nickname": "NewName", "comment": "", "used": False})

        assert changed is True
        assert row.nickname == "NewName"
        assert row.original_nickname == "NewName"

    def test_update_from_db_preserves_dirty_nickname(self):
        """Dirty nickname should NOT be overwritten from db."""
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="UserEdit",
            original_nickname="OldName",
            exists_in_mdb=True,
        )
        assert row.is_nickname_dirty is True

        changed = row.update_from_db({"nickname": "DbChange", "comment": "", "used": False})

        # Nickname should NOT be changed since it was dirty
        assert changed is False
        assert row.nickname == "UserEdit"
        assert row.original_nickname == "OldName"

    def test_update_from_db_updates_non_dirty_comment(self):
        """Non-dirty comment should be updated from db."""
        row = AddressRow(
            memory_type="X",
            address=1,
            comment="Old comment",
            original_comment="Old comment",
            exists_in_mdb=True,
        )
        assert row.is_comment_dirty is False

        changed = row.update_from_db({"nickname": "", "comment": "New comment", "used": False})

        assert changed is True
        assert row.comment == "New comment"
        assert row.original_comment == "New comment"

    def test_update_from_db_preserves_dirty_comment(self):
        """Dirty comment should NOT be overwritten from db."""
        row = AddressRow(
            memory_type="X",
            address=1,
            comment="User edit",
            original_comment="Old comment",
            exists_in_mdb=True,
        )
        assert row.is_comment_dirty is True

        row.update_from_db({"nickname": "", "comment": "Db change", "used": False})

        # Comment should NOT be changed since it was dirty
        assert row.comment == "User edit"
        assert row.original_comment == "Old comment"

    def test_update_from_db_always_updates_used(self):
        """Used flag is read-only in editor, so always update from db."""
        row = AddressRow(
            memory_type="X",
            address=1,
            used=False,
            exists_in_mdb=True,
        )

        changed = row.update_from_db({"nickname": "", "comment": "", "used": True})

        assert changed is True
        assert row.used is True

    def test_update_from_db_updates_initial_value_when_not_dirty(self):
        """Non-dirty initial value should be updated from db."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            initial_value="100",
            original_initial_value="100",
            exists_in_mdb=True,
        )
        assert row.is_initial_value_dirty is False

        changed = row.update_from_db(
            {
                "nickname": "",
                "comment": "",
                "used": False,
                "initial_value": "200",
            }
        )

        assert changed is True
        assert row.initial_value == "200"
        assert row.original_initial_value == "200"

    def test_update_from_db_preserves_dirty_initial_value(self):
        """Dirty initial value should NOT be overwritten from db."""
        row = AddressRow(
            memory_type="DS",
            address=1,
            initial_value="999",
            original_initial_value="100",
            exists_in_mdb=True,
        )
        assert row.is_initial_value_dirty is True

        row.update_from_db(
            {
                "nickname": "",
                "comment": "",
                "used": False,
                "initial_value": "200",
            }
        )

        # Initial value should NOT be changed since it was dirty
        assert row.initial_value == "999"

    def test_update_from_db_returns_false_when_no_changes(self):
        """Should return False when db data matches current data."""
        row = AddressRow(
            memory_type="X",
            address=1,
            nickname="SameName",
            original_nickname="SameName",
            comment="Same comment",
            original_comment="Same comment",
            used=True,
            exists_in_mdb=True,
        )

        changed = row.update_from_db(
            {
                "nickname": "SameName",
                "comment": "Same comment",
                "used": True,
            }
        )

        assert changed is False


class TestBlockTags:
    """Tests for block tag detection functions.

    Block tags support three formats:
    - Opening tag: <BlockName> - marks start of a range block (can have text after)
    - Closing tag: </BlockName> - marks end of a range block (can have text after)
    - Self-closing tag: <BlockName /> - marks a singular point
    """

    def test_is_block_tag_opening(self):
        """Test is_block_tag with opening block tags."""
        assert is_block_tag("<Motor Control>") is True
        assert is_block_tag("<A>") is True
        assert is_block_tag("<Section 1>") is True
        assert is_block_tag("<Custom Coils>") is True
        assert is_block_tag("  <Header>  ") is True  # Whitespace trimmed
        # Opening tags can have text after
        assert is_block_tag("<Header>Some additional text") is True
        assert is_block_tag("<Start>Valve info") is True

    def test_is_block_tag_closing(self):
        """Test is_block_tag with closing block tags."""
        assert is_block_tag("</Motor Control>") is True
        assert is_block_tag("</A>") is True
        assert is_block_tag("</Section 1>") is True
        assert is_block_tag("  </Header>  ") is True  # Whitespace trimmed
        # Closing tags can have text after
        assert is_block_tag("</Header>End of section") is True

    def test_is_block_tag_self_closing(self):
        """Test is_block_tag with self-closing block tags."""
        assert is_block_tag("<Motor Control />") is True
        assert is_block_tag("<A />") is True
        assert is_block_tag("<Spare />") is True
        assert is_block_tag("  <Header />  ") is True  # Whitespace trimmed

    def test_is_block_tag_invalid(self):
        """Test is_block_tag with invalid inputs."""
        assert is_block_tag("") is False
        assert is_block_tag(None) is False
        assert is_block_tag("<>") is False  # Empty header name
        assert is_block_tag("text <header>") is False  # Text before (must start with <)
        assert is_block_tag("<partial") is False  # Missing close bracket
        assert is_block_tag("partial>") is False  # Missing open bracket
        assert is_block_tag("no brackets") is False  # No brackets

    def test_extract_block_name_opening(self):
        """Test extract_block_name with opening block tags."""
        assert extract_block_name("<Motor Control>") == "Motor Control"
        assert extract_block_name("<A>") == "A"
        assert extract_block_name("<Section 1>") == "Section 1"
        assert extract_block_name("  <Header>  ") == "Header"  # Whitespace trimmed
        # Opening tags with text after - extracts just the name
        assert extract_block_name("<Header>Some text") == "Header"
        assert extract_block_name("<Start Custom Coils>Valve info") == "Start Custom Coils"

    def test_extract_block_name_closing(self):
        """Test extract_block_name with closing block tags."""
        assert extract_block_name("</Motor Control>") == "Motor Control"
        assert extract_block_name("</A>") == "A"
        assert extract_block_name("</Section 1>") == "Section 1"
        # Closing tags with text after
        assert extract_block_name("</Header>End note") == "Header"

    def test_extract_block_name_self_closing(self):
        """Test extract_block_name with self-closing block tags."""
        assert extract_block_name("<Motor Control />") == "Motor Control"
        assert extract_block_name("<A />") == "A"
        assert extract_block_name("<Spare />") == "Spare"

    def test_extract_block_name_invalid(self):
        """Test extract_block_name with invalid inputs."""
        assert extract_block_name("") is None
        assert extract_block_name(None) is None
        assert extract_block_name("<>") is None
        assert extract_block_name("not a header") is None
        assert extract_block_name("<partial") is None

    def test_strip_block_tag_with_block_tags(self):
        """Test strip_block_tag with block tags."""
        # Block tags only - returns empty string
        assert strip_block_tag("<Motor Control>") == ""
        assert strip_block_tag("  <Header>  ") == ""
        assert strip_block_tag("</Motor Control>") == ""
        assert strip_block_tag("<Spare />") == ""
        # Block tags with text after - returns the text
        assert strip_block_tag("<Header>Some additional text") == "Some additional text"
        assert strip_block_tag("<Start Custom Coils>Valve 1 is located") == "Valve 1 is located"
        assert strip_block_tag("</Section>End of section") == "End of section"

    def test_strip_block_tag_without_header(self):
        """Test strip_block_tag with comments that don't have block tags."""
        # No header - returns original comment
        assert strip_block_tag("Regular comment") == "Regular comment"
        assert strip_block_tag("text <header>") == "text <header>"  # Tag not at start
        assert strip_block_tag("") == ""
        assert strip_block_tag(None) == ""

    def test_get_block_type(self):
        """Test get_block_type function."""

        # Opening tags
        assert get_block_type("<Motor Control>") == "open"
        assert get_block_type("<A>") == "open"
        assert get_block_type("<Header>with text") == "open"

        # Closing tags
        assert get_block_type("</Motor Control>") == "close"
        assert get_block_type("</A>") == "close"
        assert get_block_type("</Header>with text") == "close"

        # Self-closing tags
        assert get_block_type("<Motor Control />") == "self-closing"
        assert get_block_type("<Spare />") == "self-closing"

        # Invalid
        assert get_block_type("") is None
        assert get_block_type("Regular text") is None

    def test_parse_block_tag(self):
        """Test parse_block_tag function directly."""

        # Opening tags (bg_color is None when not specified)
        assert parse_block_tag("<Motor>") == BlockTag("Motor", "open", "", None)
        assert parse_block_tag("<Motor>Valve 1") == BlockTag("Motor", "open", "Valve 1", None)
        assert parse_block_tag("<Section 1>Details here") == BlockTag(
            "Section 1",
            "open",
            "Details here",
            None,
        )

        # Closing tags (no bg attribute on closing tags)
        assert parse_block_tag("</Motor>") == BlockTag("Motor", "close", "", None)
        assert parse_block_tag("</Motor>End section") == BlockTag(
            "Motor", "close", "End section", None
        )

        # Self-closing tags
        assert parse_block_tag("<Spare />") == BlockTag("Spare", "self-closing", "", None)
        assert parse_block_tag("<Reserved />") == BlockTag("Reserved", "self-closing", "", None)

        # Invalid - returns original comment
        assert parse_block_tag("Regular text") == BlockTag(None, None, "Regular text", None)
        assert parse_block_tag("<>") == BlockTag(None, None, "<>", None)
        assert parse_block_tag("") == BlockTag(None, None, "", None)
        assert parse_block_tag("<partial") == BlockTag(None, None, "<partial", None)

    def test_parse_block_tag_with_bg_attribute(self):
        """Test parse_block_tag with bg attribute for colors."""
        # Opening tags with bg attribute
        assert parse_block_tag('<Motor bg="#FFCDD2">') == BlockTag("Motor", "open", "", "#FFCDD2")
        assert parse_block_tag('<Motor bg="#FFCDD2">Valve 1') == BlockTag(
            "Motor",
            "open",
            "Valve 1",
            "#FFCDD2",
        )
        assert parse_block_tag("<Section bg='#B3E5FC'>Details") == BlockTag(
            "Section",
            "open",
            "Details",
            "#B3E5FC",
        )

        # Self-closing tags with bg attribute
        assert parse_block_tag('<Spare bg="#C8E6C9" />') == BlockTag(
            "Spare", "self-closing", "", "#C8E6C9"
        )
        assert parse_block_tag('<Reserved bg="#FFF9C4" />') == BlockTag(
            "Reserved",
            "self-closing",
            "",
            "#FFF9C4",
        )

        # Closing tags never have bg attribute (color is on opening tag)
        assert parse_block_tag("</Motor>") == BlockTag("Motor", "close", "", None)

        # Mixed case - bg attribute should be extracted regardless of position
        assert parse_block_tag('<Name With Spaces bg="#FFCCBC">') == BlockTag(
            "Name With Spaces",
            "open",
            "",
            "#FFCCBC",
        )
