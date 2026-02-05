"""Tests for Dataview model."""

from clicknick.models.dataview_row import (
    MAX_DATAVIEW_ROWS,
    WRITABLE_SC,
    WRITABLE_SD,
    DataviewRow,
    TypeCode,
    create_empty_dataview,
    display_to_storage,
    get_type_code_for_address,
    is_address_writable,
    parse_address,
    storage_to_display,
)


class TestParseAddress:
    """Tests for parse_address function."""

    def test_parse_x_address(self):
        """Test parsing X addresses."""
        assert parse_address("X001") == ("X", "001")
        assert parse_address("X1") == ("X", "1")
        assert parse_address("X816") == ("X", "816")

    def test_parse_y_address(self):
        """Test parsing Y addresses."""
        assert parse_address("Y001") == ("Y", "001")
        assert parse_address("y001") == ("Y", "001")  # Case insensitive

    def test_parse_ds_address(self):
        """Test parsing DS addresses."""
        assert parse_address("DS1") == ("DS", "1")
        assert parse_address("DS4500") == ("DS", "4500")

    def test_parse_dd_address(self):
        """Test parsing DD addresses."""
        assert parse_address("DD1") == ("DD", "1")
        assert parse_address("DD1000") == ("DD", "1000")

    def test_parse_xd_address(self):
        """Test parsing XD addresses with upper byte suffix."""
        assert parse_address("XD0") == ("XD", "0")
        assert parse_address("XD0u") == ("XD", "0u")
        assert parse_address("XD8") == ("XD", "8")

    def test_parse_txt_address(self):
        """Test parsing TXT addresses."""
        assert parse_address("TXT1") == ("TXT", "1")
        assert parse_address("TXT1000") == ("TXT", "1000")

    def test_parse_ctd_address(self):
        """Test parsing CTD addresses."""
        assert parse_address("CTD1") == ("CTD", "1")
        assert parse_address("CTD250") == ("CTD", "250")

    def test_parse_empty(self):
        """Test parsing empty address."""
        assert parse_address("") is None
        assert parse_address("   ") is None

    def test_parse_invalid(self):
        """Test parsing invalid addresses."""
        assert parse_address("123") is None  # No prefix
        assert parse_address("ABC") is None  # No number
        assert parse_address("X") is None  # No number


class TestGetTypeCodeForAddress:
    """Tests for get_type_code_for_address function."""

    def test_bit_addresses(self):
        """Test BIT type addresses."""
        assert get_type_code_for_address("X001") == TypeCode.BIT
        assert get_type_code_for_address("Y001") == TypeCode.BIT
        assert get_type_code_for_address("C1") == TypeCode.BIT
        assert get_type_code_for_address("T1") == TypeCode.BIT
        assert get_type_code_for_address("CT1") == TypeCode.BIT
        assert get_type_code_for_address("SC1") == TypeCode.BIT

    def test_int_addresses(self):
        """Test INT type addresses."""
        assert get_type_code_for_address("DS1") == TypeCode.INT
        assert get_type_code_for_address("TD1") == TypeCode.INT
        assert get_type_code_for_address("SD1") == TypeCode.INT

    def test_int2_addresses(self):
        """Test INT2 type addresses."""
        assert get_type_code_for_address("DD1") == TypeCode.INT2
        assert get_type_code_for_address("CTD1") == TypeCode.INT2

    def test_hex_addresses(self):
        """Test HEX type addresses."""
        assert get_type_code_for_address("DH1") == TypeCode.HEX
        assert get_type_code_for_address("XD0") == TypeCode.HEX
        assert get_type_code_for_address("YD0") == TypeCode.HEX

    def test_float_addresses(self):
        """Test FLOAT type addresses."""
        assert get_type_code_for_address("DF1") == TypeCode.FLOAT

    def test_txt_addresses(self):
        """Test TXT type addresses."""
        assert get_type_code_for_address("TXT1") == TypeCode.TXT

    def test_invalid_address(self):
        """Test invalid address returns None."""
        assert get_type_code_for_address("INVALID") is None
        assert get_type_code_for_address("") is None


class TestIsAddressWritable:
    """Tests for is_address_writable function."""

    def test_regular_addresses_writable(self):
        """Test that regular addresses are writable."""
        assert is_address_writable("X001") is True
        assert is_address_writable("Y001") is True
        assert is_address_writable("C1") is True
        assert is_address_writable("DS1") is True
        assert is_address_writable("DD1") is True
        assert is_address_writable("DF1") is True

    def test_xd_yd_readonly(self):
        """Test that XD and YD are read-only."""
        assert is_address_writable("XD0") is False
        assert is_address_writable("XD0u") is False
        assert is_address_writable("YD0") is False
        assert is_address_writable("YD8") is False

    def test_sc_writable_addresses(self):
        """Test specific SC addresses are writable."""
        for addr in WRITABLE_SC:
            assert is_address_writable(f"SC{addr}") is True

    def test_sc_readonly_addresses(self):
        """Test non-writable SC addresses are read-only."""
        # SC1 is not in WRITABLE_SC
        assert is_address_writable("SC1") is False
        assert is_address_writable("SC100") is False

    def test_sd_writable_addresses(self):
        """Test specific SD addresses are writable."""
        for addr in WRITABLE_SD:
            assert is_address_writable(f"SD{addr}") is True

    def test_sd_readonly_addresses(self):
        """Test non-writable SD addresses are read-only."""
        # SD1 is not in WRITABLE_SD
        assert is_address_writable("SD1") is False
        assert is_address_writable("SD100") is False

    def test_invalid_address(self):
        """Test invalid address returns False."""
        assert is_address_writable("INVALID") is False
        assert is_address_writable("") is False


class TestDataviewRow:
    """Tests for DataviewRow dataclass."""

    def test_default_values(self):
        """Test default values."""
        row = DataviewRow()
        assert row.address == ""
        assert row.type_code == 0
        assert row.new_value == ""
        assert row.nickname == ""
        assert row.comment == ""

    def test_is_empty(self):
        """Test is_empty property."""
        row = DataviewRow()
        assert row.is_empty is True

        row.address = "X001"
        assert row.is_empty is False

        row.address = "   "
        assert row.is_empty is True

    def test_is_writable(self):
        """Test is_writable property."""
        row = DataviewRow(address="X001")
        assert row.is_writable is True

        row.address = "XD0"
        assert row.is_writable is False

    def test_memory_type(self):
        """Test memory_type property."""
        row = DataviewRow(address="DS100")
        assert row.memory_type == "DS"

        row.address = ""
        assert row.memory_type is None

    def test_address_number(self):
        """Test address_number property."""
        row = DataviewRow(address="DS100")
        assert row.address_number == "100"

        row.address = "XD0u"
        assert row.address_number == "0u"

    def test_update_type_code(self):
        """Test update_type_code method."""
        row = DataviewRow(address="DS100")
        assert row.update_type_code() is True
        assert row.type_code == TypeCode.INT

        row.address = "INVALID"
        assert row.update_type_code() is False

    def test_clear(self):
        """Test clear method."""
        row = DataviewRow(
            address="X001",
            type_code=TypeCode.BIT,
            new_value="1",
            nickname="Test",
            comment="Comment",
        )
        row.clear()
        assert row.address == ""
        assert row.type_code == 0
        assert row.new_value == ""
        assert row.nickname == ""
        assert row.comment == ""


class TestCreateEmptyDataview:
    """Tests for create_empty_dataview function."""

    def test_creates_correct_count(self):
        """Test that correct number of rows is created."""
        rows = create_empty_dataview()
        assert len(rows) == MAX_DATAVIEW_ROWS

    def test_all_rows_empty(self):
        """Test that all rows are empty."""
        rows = create_empty_dataview()
        assert all(row.is_empty for row in rows)

    def test_rows_are_independent(self):
        """Test that rows are independent objects."""
        rows = create_empty_dataview()
        rows[0].address = "X001"
        assert rows[1].address == ""


class TestStorageToDisplay:
    """Tests for storage_to_display conversion."""

    def test_bit_values(self):
        """Test BIT type conversion."""
        assert storage_to_display("1", TypeCode.BIT) == "1"
        assert storage_to_display("0", TypeCode.BIT) == "0"

    def test_int_positive(self):
        """Test INT (16-bit signed) positive values."""
        assert storage_to_display("0", TypeCode.INT) == "0"
        assert storage_to_display("100", TypeCode.INT) == "100"
        assert storage_to_display("32767", TypeCode.INT) == "32767"

    def test_int_negative(self):
        """Test INT (16-bit signed) negative values stored as unsigned 32-bit."""
        # -32768 stored as 4294934528 (0xFFFF8000)
        assert storage_to_display("4294934528", TypeCode.INT) == "-32768"
        # -1 stored as 4294967295 (0xFFFFFFFF), but masked to 16-bit = -1
        assert storage_to_display("4294967295", TypeCode.INT) == "-1"
        # Edge case: -1 stored as 16-bit raw unsigned (65535)
        # If your logic interprets 0xFFFF as -1 for TypeCode.INT:
        assert storage_to_display("65535", TypeCode.INT) == "-1"

    def test_int2_positive(self):
        """Test INT2 (32-bit signed) positive values."""
        assert storage_to_display("0", TypeCode.INT2) == "0"
        assert storage_to_display("100", TypeCode.INT2) == "100"
        assert storage_to_display("2147483647", TypeCode.INT2) == "2147483647"

    def test_int2_negative(self):
        """Test INT2 (32-bit signed) negative values stored as unsigned 32-bit."""
        # -2147483648 stored as 2147483648
        assert storage_to_display("2147483648", TypeCode.INT2) == "-2147483648"
        # -2 stored as 4294967294
        assert storage_to_display("4294967294", TypeCode.INT2) == "-2"
        # -1 stored as 4294967295
        assert storage_to_display("4294967295", TypeCode.INT2) == "-1"

    def test_float_values(self):
        """Test FLOAT type (IEEE-754 32-bit)."""
        # DF3 "Pie" from data: 1078523331 -> ~3.14159
        # Note: Float comparisons usually require approx matching, but
        # storage_to_display likely returns a formatted string.
        # Ensure your logic handles the precision formatting used by your app (e.g., 2 decimals? 6?)

        # 0 -> 0 (integer representation)
        assert storage_to_display("0", TypeCode.FLOAT) == "0"

        # 1 -> 0x3F800000 -> 1065353216
        assert storage_to_display("1065353216", TypeCode.FLOAT) == "1"

        # PI from your data block: 1078523331
        # 0x40490F83 = 3.1415927...
        val = storage_to_display("1078523331", TypeCode.FLOAT)
        assert val.startswith("3.14")

        # Negative Float (DF1 from data): 4286578685 -> 0xFF7FFFFD -> -3.4028235E38
        # Ensure it handles scientific notation if your display logic does
        assert "-" in storage_to_display("4286578685", TypeCode.FLOAT)

    def test_hex_values(self):
        """Test HEX type (decimal to 4-digit hex string with leading zeros)."""
        assert storage_to_display("65535", TypeCode.HEX) == "FFFF"
        assert storage_to_display("255", TypeCode.HEX) == "00FF"
        assert storage_to_display("0", TypeCode.HEX) == "0000"
        # Lowercase input
        assert display_to_storage("ffff", TypeCode.HEX) == "65535"
        assert display_to_storage("ff", TypeCode.HEX) == "255"

        # 0x prefix variations
        assert display_to_storage("0XFFFF", TypeCode.HEX) == "65535"

    def test_txt_values(self):
        """Test TXT type (ASCII code to character)."""
        assert storage_to_display("48", TypeCode.TXT) == "0"
        assert storage_to_display("65", TypeCode.TXT) == "A"
        assert storage_to_display("90", TypeCode.TXT) == "Z"
        assert storage_to_display("49", TypeCode.TXT) == "1"

    def test_empty_value(self):
        """Test empty values return empty string."""
        assert storage_to_display("", TypeCode.INT) == ""
        assert storage_to_display("", TypeCode.HEX) == ""

    def test_txt_space(self):
        # Space is ASCII 32
        assert storage_to_display("32", TypeCode.TXT) == " "


class TestDisplayToStorage:
    """Tests for display_to_storage conversion."""

    def test_bit_values(self):
        """Test BIT type conversion."""
        assert display_to_storage("1", TypeCode.BIT) == "1"
        assert display_to_storage("0", TypeCode.BIT) == "0"

    def test_int_positive(self):
        """Test INT (16-bit signed) positive values."""
        assert display_to_storage("0", TypeCode.INT) == "0"
        assert display_to_storage("100", TypeCode.INT) == "100"
        assert display_to_storage("32767", TypeCode.INT) == "32767"

    def test_int_negative(self):
        """Test INT (16-bit signed) negative values to unsigned 32-bit."""
        # -32768 should become 4294934528
        assert display_to_storage("-32768", TypeCode.INT) == "4294934528"
        # -1 should become 4294967295
        assert display_to_storage("-1", TypeCode.INT) == "4294967295"

    def test_int2_positive(self):
        """Test INT2 (32-bit signed) positive values."""
        assert display_to_storage("0", TypeCode.INT2) == "0"
        assert display_to_storage("100", TypeCode.INT2) == "100"

    def test_int2_negative(self):
        """Test INT2 (32-bit signed) negative values to unsigned 32-bit."""
        # -2147483648 should become 2147483648
        assert display_to_storage("-2147483648", TypeCode.INT2) == "2147483648"
        # -2 should become 4294967294
        assert display_to_storage("-2", TypeCode.INT2) == "4294967294"

    def test_float_values(self):
        """Test FLOAT display to storage (String -> IEEE 32-bit int)."""
        # 0.0 -> 0
        assert display_to_storage("0.0", TypeCode.FLOAT) == "0"

        # 1.0 -> 1065353216
        assert display_to_storage("1.0", TypeCode.FLOAT) == "1065353216"

        # -1.0 -> 0xBF800000 -> 3212836864
        assert display_to_storage("-1.0", TypeCode.FLOAT) == "3212836864"

    def test_hex_values(self):
        """Test HEX type (hex string to decimal)."""
        assert display_to_storage("FFFF", TypeCode.HEX) == "65535"
        assert display_to_storage("FF", TypeCode.HEX) == "255"
        assert display_to_storage("0xFF", TypeCode.HEX) == "255"
        assert display_to_storage("0", TypeCode.HEX) == "0"

    def test_txt_values(self):
        """Test TXT type (character to ASCII code)."""
        assert display_to_storage("0", TypeCode.TXT) == "48"
        assert display_to_storage("A", TypeCode.TXT) == "65"
        assert display_to_storage("Z", TypeCode.TXT) == "90"
        assert display_to_storage("1", TypeCode.TXT) == "49"

    def test_empty_value(self):
        """Test empty values return empty string."""
        assert display_to_storage("", TypeCode.INT) == ""
        assert display_to_storage("", TypeCode.HEX) == ""

    def test_txt_space(self):
        # Space is ASCII 32
        assert display_to_storage(" ", TypeCode.TXT) == "32"

    def test_snapshot_data_consistency(self):
        """
        Validates values from the project snapshot.
        Note: We expect clean data (e.g., "FFFF") not view styling ("FFFFh").
        """

        # --- FLOAT (IEEE-754 32-bit) ---
        # DF1: SmallestFloat (-3.402823E+38)
        assert storage_to_display("4286578685", TypeCode.FLOAT) == "-3.402823E+38"

        # DF2: LargestFloat (3.402823E+38)
        assert storage_to_display("2139095037", TypeCode.FLOAT) == "3.402823E+38"

        # DF3: Pie (3.14)
        # Note: Raw 1078523331 is approx 3.141593.
        # If your UI shows exactly "3.14", it is truncating visually.
        # Python .7G will return 3.141593.
        # We check startswith to allow for precision differences.
        assert storage_to_display("1078523331", TypeCode.FLOAT).startswith("3.14")

        # --- HEX (16-bit Hexadecimal) ---
        # DH1: SmallestHex
        assert storage_to_display("0", TypeCode.HEX) == "0000"
        # DH2: LargestHex
        assert storage_to_display("65535", TypeCode.HEX) == "FFFF"
        # DH3: OneHex
        assert storage_to_display("1", TypeCode.HEX) == "0001"
        # YD1: SmallestWord
        assert storage_to_display("0", TypeCode.HEX) == "0000"
        # YD2: LargestWord
        assert storage_to_display("65535", TypeCode.HEX) == "FFFF"

        # --- INT Consistency Checks ---
        assert storage_to_display("4294967295", TypeCode.INT) == "-1"
        assert storage_to_display("4294967295", TypeCode.INT2) == "-1"


class TestRoundTripConversion:
    """Tests for round-trip storage <-> display conversion."""

    def test_int_roundtrip(self):
        """Test INT values round-trip correctly."""
        for val in ["-32768", "-1", "0", "100", "32767"]:
            storage = display_to_storage(val, TypeCode.INT)
            display = storage_to_display(storage, TypeCode.INT)
            assert display == val, f"Round-trip failed for {val}"

    def test_int2_roundtrip(self):
        """Test INT2 values round-trip correctly."""
        for val in ["-2147483648", "-2", "-1", "0", "100", "2147483647"]:
            storage = display_to_storage(val, TypeCode.INT2)
            display = storage_to_display(storage, TypeCode.INT2)
            assert display == val, f"Round-trip failed for {val}"

    def test_hex_roundtrip(self):
        """Test HEX values round-trip correctly (display has 4-digit format)."""
        # Note: display format is always 4 digits with leading zeros
        test_cases = [
            ("0", "0000"),
            ("FF", "00FF"),
            ("FFFF", "FFFF"),
        ]
        for input_val, expected_display in test_cases:
            storage = display_to_storage(input_val, TypeCode.HEX)
            display = storage_to_display(storage, TypeCode.HEX)
            assert display == expected_display, f"Round-trip failed for {input_val}"

    def test_txt_roundtrip(self):
        """Test TXT values round-trip correctly."""
        for val in ["0", "A", "Z", "1"]:
            storage = display_to_storage(val, TypeCode.TXT)
            display = storage_to_display(storage, TypeCode.TXT)
            assert display == val, f"Round-trip failed for {val}"
