"""Tests for RowService."""

import pytest

from clicknick.data.shared_data import SharedAddressData
from clicknick.services.row_service import RowService


class MockDataSource:
    """Mock data source for testing."""

    supports_used_field = True

    def load_all(self):
        return {}


@pytest.fixture
def shared_data():
    """Create a SharedAddressData instance with skeleton rows."""
    data_source = MockDataSource()
    shared = SharedAddressData(data_source)
    return shared


# Test increment_nickname_suffix
def test_increment_nickname_suffix_simple():
    """Test incrementing a simple numbered nickname."""
    result, orig, new = RowService.increment_nickname_suffix("Tank1", 1)
    assert result == "Tank2"
    assert orig == 1
    assert new == 2


def test_increment_nickname_suffix_multiple_numbers():
    """Test incrementing with multiple numbers (uses rightmost)."""
    result, orig, new = RowService.increment_nickname_suffix("Building1_Alm1", 1)
    assert result == "Building1_Alm2"
    assert orig == 1
    assert new == 2


def test_increment_nickname_suffix_no_number():
    """Test incrementing nickname with no numbers."""
    result, orig, new = RowService.increment_nickname_suffix("NoNumber", 1)
    assert result == "NoNumber"
    assert orig is None
    assert new is None


def test_increment_nickname_suffix_with_zeros():
    """Test preserving leading zeros."""
    result, orig, new = RowService.increment_nickname_suffix("Valve001", 2)
    assert result == "Valve003"
    assert orig == 1
    assert new == 3


def test_increment_nickname_suffix_large_increment():
    """Test large increment."""
    result, orig, new = RowService.increment_nickname_suffix("Tank_Level10", 2)
    assert result == "Tank_Level12"
    assert orig == 10
    assert new == 12


# Test fill_down
def test_fill_down_basic(shared_data):
    """Test basic fill down operation."""
    # Setup source row
    source_row = shared_data.all_rows[1]  # X1
    with shared_data.edit_session():
        source_row.nickname = "Sensor1"
        source_row.comment = "Test comment"
        source_row.initial_value = "0"
        source_row.retentive = True

    # Fill down to targets
    target_keys = [2, 3, 4]  # X2, X3, X4
    with shared_data.edit_session():
        affected = RowService.fill_down(shared_data, source_row.addr_key, target_keys)

    # Check affected keys
    assert len(affected) == 4  # source + 3 targets
    assert source_row.addr_key in affected
    for key in target_keys:
        assert key in affected

    # Check target rows
    assert shared_data.all_rows[2].nickname == "Sensor2"
    assert shared_data.all_rows[3].nickname == "Sensor3"
    assert shared_data.all_rows[4].nickname == "Sensor4"

    # Check comment copied
    assert shared_data.all_rows[2].comment == "Test comment"
    assert shared_data.all_rows[3].comment == "Test comment"

    # Check retentive copied
    assert shared_data.all_rows[2].retentive is True
    assert shared_data.all_rows[3].retentive is True


def test_fill_down_increment_initial_value(shared_data):
    """Test fill down with initial value incrementing."""
    # Setup source row with matching initial value
    source_row = shared_data.all_rows[1]
    with shared_data.edit_session():
        source_row.nickname = "Array1"
        source_row.initial_value = "1"  # Matches the "1" in "Array1"

    # Fill down with increment flag
    target_keys = [2, 3]
    with shared_data.edit_session():
        RowService.fill_down(
            shared_data, source_row.addr_key, target_keys, increment_initial_value=True
        )

    # Check initial values were incremented
    assert shared_data.all_rows[2].initial_value == "2"
    assert shared_data.all_rows[3].initial_value == "3"


def test_fill_down_no_increment_when_mismatch(shared_data):
    """Test that initial value is not incremented when it doesn't match nickname."""
    source_row = shared_data.all_rows[1]
    with shared_data.edit_session():
        source_row.nickname = "Array1"
        source_row.initial_value = "5"  # Doesn't match the "1"

    target_keys = [2]
    with shared_data.edit_session():
        RowService.fill_down(
            shared_data, source_row.addr_key, target_keys, increment_initial_value=True
        )

    # Check initial value was just copied, not incremented
    assert shared_data.all_rows[2].initial_value == "5"


def test_fill_down_nickname_index_updated(shared_data):
    """Test that nickname reverse index is updated during fill down."""
    source_row = shared_data.all_rows[1]
    with shared_data.edit_session():
        source_row.nickname = "Test1"
        shared_data.update_nickname(source_row.addr_key, "", "Test1")

    target_keys = [2]
    with shared_data.edit_session():
        RowService.fill_down(shared_data, source_row.addr_key, target_keys)

    # Check reverse index has both nicknames
    assert shared_data.is_duplicate_nickname("Test1", exclude_addr_key=999)
    assert shared_data.is_duplicate_nickname("Test2", exclude_addr_key=999)


# Test clone_structure
def test_clone_structure_basic(shared_data):
    """Test basic clone structure operation."""
    # Setup template rows
    template_row1 = shared_data.all_rows[1]  # X1
    template_row2 = shared_data.all_rows[2]  # X2

    with shared_data.edit_session():
        template_row1.nickname = "Motor1"
        template_row1.comment = "Motor control"
        template_row2.nickname = "Motor1_Status"
        template_row2.comment = "Status bit"

    # Clone to destination (2 clones, so 4 destination rows total)
    template_keys = [1, 2]
    dest_keys = [3, 4, 5, 6]  # X3, X4, X5, X6
    with shared_data.edit_session():
        affected = RowService.clone_structure(shared_data, template_keys, dest_keys, clone_count=2)

    # Check affected keys
    assert len(affected) == 4
    for key in dest_keys:
        assert key in affected

    # Check first clone (clone_num=1)
    assert shared_data.all_rows[3].nickname == "Motor2"
    assert shared_data.all_rows[4].nickname == "Motor2_Status"

    # Check second clone (clone_num=2)
    assert shared_data.all_rows[5].nickname == "Motor3"
    assert shared_data.all_rows[6].nickname == "Motor3_Status"

    # Check comments copied
    assert shared_data.all_rows[3].comment == "Motor control"
    assert shared_data.all_rows[4].comment == "Status bit"


def test_clone_structure_with_increment_initial_value(shared_data):
    """Test clone structure with initial value incrementing."""
    template_row = shared_data.all_rows[1]
    with shared_data.edit_session():
        template_row.nickname = "Tank1"
        template_row.initial_value = "1"

    template_keys = [1]
    dest_keys = [2, 3]  # 2 clones
    with shared_data.edit_session():
        RowService.clone_structure(
            shared_data, template_keys, dest_keys, clone_count=2, increment_initial_value=True
        )

    # Check initial values incremented
    assert shared_data.all_rows[2].initial_value == "2"
    assert shared_data.all_rows[3].initial_value == "3"


def test_clone_structure_empty_template_row(shared_data):
    """Test cloning with empty row in template."""
    # Template with one populated, one empty
    template_row1 = shared_data.all_rows[1]
    with shared_data.edit_session():
        template_row1.nickname = "Sensor1"
        template_row1.comment = "Active"

    # Row 2 (key=2) left empty (no nickname) - using default skeleton state

    template_keys = [1, 2]
    dest_keys = [3, 4]  # 1 clone
    with shared_data.edit_session():
        RowService.clone_structure(shared_data, template_keys, dest_keys, clone_count=1)

    # Check first row cloned with incremented nickname
    assert shared_data.all_rows[3].nickname == "Sensor2"

    # Check second row has no nickname (empty in template)
    assert shared_data.all_rows[4].nickname == ""


def test_clone_structure_nickname_index_updated(shared_data):
    """Test that nickname reverse index is updated during clone."""
    template_row = shared_data.all_rows[1]
    with shared_data.edit_session():
        template_row.nickname = "Clone1"

    template_keys = [1]
    dest_keys = [2, 3]
    with shared_data.edit_session():
        RowService.clone_structure(shared_data, template_keys, dest_keys, clone_count=2)

    # Check reverse index has all cloned nicknames
    assert shared_data.is_duplicate_nickname("Clone2", exclude_addr_key=999)
    assert shared_data.is_duplicate_nickname("Clone3", exclude_addr_key=999)
