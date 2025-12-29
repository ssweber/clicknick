"""Tests for CDV file I/O."""

import tempfile
from pathlib import Path

import pytest

from clicknick.models.dataview_row import (
    MAX_DATAVIEW_ROWS,
    TypeCode,
    create_empty_dataview,
)
from clicknick.views.dataview_editor.cdv_file import export_cdv, load_cdv, save_cdv

# Test files in the tests directory
TEST_DIR = Path(__file__).parent
DATAVIEW1_PATH = TEST_DIR / "DataView1.cdv"
DATAVIEW1_WITH_NEW_VALUES_PATH = TEST_DIR / "DataView1WithNewValues.cdv"


class TestLoadCdv:
    """Tests for loading CDV files."""

    def test_load_dataview1(self):
        """Test loading DataView1.cdv (no new values)."""
        rows, has_new_values = load_cdv(DATAVIEW1_PATH)

        assert len(rows) == MAX_DATAVIEW_ROWS
        assert has_new_values is False

        # Check first few rows
        assert rows[0].address == "X001"
        assert rows[0].type_code == TypeCode.BIT

        assert rows[1].address == "X002"
        assert rows[1].type_code == TypeCode.BIT

        # Check a DS row
        ds_row = next(r for r in rows if r.address == "DS1")
        assert ds_row.type_code == TypeCode.INT

        # Check a DF row
        df_row = next(r for r in rows if r.address == "DF1")
        assert df_row.type_code == TypeCode.FLOAT

        # Check a TXT row
        txt_row = next(r for r in rows if r.address == "TXT1")
        assert txt_row.type_code == TypeCode.TXT

        # Check empty rows exist
        empty_count = sum(1 for r in rows if r.is_empty)
        assert empty_count > 0

    def test_load_dataview1_with_new_values(self):
        """Test loading DataView1WithNewValues.cdv."""
        rows, has_new_values = load_cdv(DATAVIEW1_WITH_NEW_VALUES_PATH)

        assert len(rows) == MAX_DATAVIEW_ROWS
        assert has_new_values is True

        # Check rows with new values
        assert rows[0].address == "X001"
        assert rows[0].new_value == "1"  # BIT on

        assert rows[1].address == "X002"
        assert rows[1].new_value == "0"  # BIT off

        # DS with new value
        ds1_row = next(r for r in rows if r.address == "DS1")
        assert ds1_row.new_value == "1"

        # DF with new value (float stored as int representation)
        df1_row = next(r for r in rows if r.address == "DF1")
        assert df1_row.new_value  # Should have a value

    def test_load_nonexistent_file(self):
        """Test loading a file that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_cdv(TEST_DIR / "nonexistent.cdv")


class TestSaveCdv:
    """Tests for saving CDV files."""

    def test_save_empty_dataview(self):
        """Test saving an empty dataview."""
        rows = create_empty_dataview()

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_cdv(temp_path, rows, has_new_values=False)

            # Load it back
            loaded_rows, has_new_values = load_cdv(temp_path)

            assert len(loaded_rows) == MAX_DATAVIEW_ROWS
            assert has_new_values is False
            assert all(r.is_empty for r in loaded_rows)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_save_with_addresses(self):
        """Test saving a dataview with addresses."""
        rows = create_empty_dataview()
        rows[0].address = "X001"
        rows[0].type_code = TypeCode.BIT
        rows[1].address = "DS100"
        rows[1].type_code = TypeCode.INT

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_cdv(temp_path, rows, has_new_values=False)

            # Load it back
            loaded_rows, has_new_values = load_cdv(temp_path)

            assert loaded_rows[0].address == "X001"
            assert loaded_rows[0].type_code == TypeCode.BIT
            assert loaded_rows[1].address == "DS100"
            assert loaded_rows[1].type_code == TypeCode.INT
            assert has_new_values is False
        finally:
            temp_path.unlink(missing_ok=True)

    def test_save_with_new_values(self):
        """Test saving a dataview with new values."""
        rows = create_empty_dataview()
        rows[0].address = "X001"
        rows[0].type_code = TypeCode.BIT
        rows[0].new_value = "1"
        rows[1].address = "DS100"
        rows[1].type_code = TypeCode.INT
        rows[1].new_value = "42"

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_cdv(temp_path, rows, has_new_values=True)

            # Load it back
            loaded_rows, has_new_values = load_cdv(temp_path)

            assert loaded_rows[0].address == "X001"
            assert loaded_rows[0].new_value == "1"
            assert loaded_rows[1].address == "DS100"
            assert loaded_rows[1].new_value == "42"
            assert has_new_values is True
        finally:
            temp_path.unlink(missing_ok=True)

    def test_wrong_row_count_raises(self):
        """Test that saving with wrong row count raises ValueError."""
        rows = [create_empty_dataview()[0]]  # Only 1 row

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f:
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Expected 100 rows"):
                save_cdv(temp_path, rows, has_new_values=False)
        finally:
            temp_path.unlink(missing_ok=True)


class TestRoundTrip:
    """Tests for round-trip loading and saving."""

    def test_roundtrip_dataview1(self):
        """Test round-trip load/save of DataView1.cdv."""
        original_rows, original_has_new_values = load_cdv(DATAVIEW1_PATH)

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_cdv(temp_path, original_rows, original_has_new_values)
            loaded_rows, loaded_has_new_values = load_cdv(temp_path)

            assert loaded_has_new_values == original_has_new_values

            for i, (orig, loaded) in enumerate(zip(original_rows, loaded_rows, strict=True)):
                assert orig.address == loaded.address, f"Row {i} address mismatch"
                assert orig.type_code == loaded.type_code, f"Row {i} type_code mismatch"
                assert orig.new_value == loaded.new_value, f"Row {i} new_value mismatch"
        finally:
            temp_path.unlink(missing_ok=True)

    def test_roundtrip_dataview1_with_new_values(self):
        """Test round-trip load/save of DataView1WithNewValues.cdv."""
        original_rows, original_has_new_values = load_cdv(DATAVIEW1_WITH_NEW_VALUES_PATH)

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f:
            temp_path = Path(f.name)

        try:
            save_cdv(temp_path, original_rows, original_has_new_values)
            loaded_rows, loaded_has_new_values = load_cdv(temp_path)

            assert loaded_has_new_values == original_has_new_values

            for i, (orig, loaded) in enumerate(zip(original_rows, loaded_rows, strict=True)):
                assert orig.address == loaded.address, f"Row {i} address mismatch"
                assert orig.type_code == loaded.type_code, f"Row {i} type_code mismatch"
                assert orig.new_value == loaded.new_value, f"Row {i} new_value mismatch"
        finally:
            temp_path.unlink(missing_ok=True)


class TestExportCdv:
    """Tests for exporting CDV files."""

    def test_export_is_same_as_save(self):
        """Test that export produces the same result as save."""
        rows = create_empty_dataview()
        rows[0].address = "Y001"
        rows[0].type_code = TypeCode.BIT

        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f1:
            save_path = Path(f1.name)
        with tempfile.NamedTemporaryFile(suffix=".cdv", delete=False) as f2:
            export_path = Path(f2.name)

        try:
            save_cdv(save_path, rows, has_new_values=False)
            export_cdv(export_path, rows, has_new_values=False)

            save_content = save_path.read_bytes()
            export_content = export_path.read_bytes()

            assert save_content == export_content
        finally:
            save_path.unlink(missing_ok=True)
            export_path.unlink(missing_ok=True)
