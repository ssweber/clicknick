"""Tests for Dataview model."""

from clicknick.models.dataview_row import (
    MAX_DATAVIEW_ROWS,
    WRITABLE_SC,
    WRITABLE_SD,
    DataviewRow,
    TypeCode,
    create_empty_dataview,
    get_type_code_for_address,
    is_address_writable,
)


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
