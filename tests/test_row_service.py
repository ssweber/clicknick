"""Tests for RowService."""

import pytest
from pyclickplc import get_addr_key

from clicknick.data.address_store import AddressStore
from clicknick.services.row_service import RowService


class MockDataSource:
    """Mock data source for testing."""

    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def load_all_addresses(self):
        return {}

    def save_changes(self, rows):
        return 0


@pytest.fixture
def store():
    """Create an AddressStore instance with skeleton rows."""
    data_source = MockDataSource()
    s = AddressStore(data_source)
    s.load_initial_data()
    return s


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
def test_fill_down_basic(store):
    """Test basic fill down operation."""
    # X1 addr_key
    source_key = get_addr_key("X", 1)

    # Setup source row
    with store.edit_session("Setup") as session:
        session.set_field(source_key, "nickname", "Sensor1")
        session.set_field(source_key, "comment", "Test comment")
        session.set_field(source_key, "initial_value", "0")
        session.set_field(source_key, "retentive", True)

    # Fill down to targets (X2, X3, X4)
    target_keys = [get_addr_key("X", 2), get_addr_key("X", 3), get_addr_key("X", 4)]
    with store.edit_session("Fill down"):
        affected = RowService.fill_down(store, source_key, target_keys)

    # Check affected keys
    assert len(affected) == 4  # source + 3 targets
    assert source_key in affected
    for key in target_keys:
        assert key in affected

    # Check target rows
    assert store.visible_state[get_addr_key("X", 2)].nickname == "Sensor2"
    assert store.visible_state[get_addr_key("X", 3)].nickname == "Sensor3"
    assert store.visible_state[get_addr_key("X", 4)].nickname == "Sensor4"

    # Check comment copied
    assert store.visible_state[get_addr_key("X", 2)].comment == "Test comment"
    assert store.visible_state[get_addr_key("X", 3)].comment == "Test comment"

    # Check retentive copied
    assert store.visible_state[get_addr_key("X", 2)].retentive is True
    assert store.visible_state[get_addr_key("X", 3)].retentive is True


def test_fill_down_increment_initial_value(store):
    """Test fill down with initial value incrementing."""
    source_key = get_addr_key("X", 1)

    # Setup source row with matching initial value
    with store.edit_session("Setup") as session:
        session.set_field(source_key, "nickname", "Array1")
        session.set_field(source_key, "initial_value", "1")  # Matches the "1" in "Array1"

    # Fill down with increment flag
    target_keys = [get_addr_key("X", 2), get_addr_key("X", 3)]
    with store.edit_session("Fill down"):
        RowService.fill_down(store, source_key, target_keys, increment_initial_value=True)

    # Check initial values were incremented
    assert store.visible_state[get_addr_key("X", 2)].initial_value == "2"
    assert store.visible_state[get_addr_key("X", 3)].initial_value == "3"


def test_fill_down_no_increment_when_mismatch(store):
    """Test that initial value is not incremented when it doesn't match nickname."""
    source_key = get_addr_key("X", 1)

    with store.edit_session("Setup") as session:
        session.set_field(source_key, "nickname", "Array1")
        session.set_field(source_key, "initial_value", "5")  # Doesn't match the "1"

    target_keys = [get_addr_key("X", 2)]
    with store.edit_session("Fill down"):
        RowService.fill_down(store, source_key, target_keys, increment_initial_value=True)

    # Check initial value was just copied, not incremented
    assert store.visible_state[get_addr_key("X", 2)].initial_value == "5"


def test_fill_down_nickname_index_updated(store):
    """Test that nickname reverse index is updated during fill down."""
    source_key = get_addr_key("X", 1)

    with store.edit_session("Setup") as session:
        session.set_field(source_key, "nickname", "Test1")

    target_keys = [get_addr_key("X", 2)]
    with store.edit_session("Fill down"):
        RowService.fill_down(store, source_key, target_keys)

    # Check reverse index has both nicknames
    assert store.is_duplicate_nickname("Test1", exclude_addr_key=999)
    assert store.is_duplicate_nickname("Test2", exclude_addr_key=999)


# Test clone_structure
def test_clone_structure_basic(store):
    """Test basic clone structure operation."""
    # Setup template rows (X1, X2)
    template_key1 = get_addr_key("X", 1)
    template_key2 = get_addr_key("X", 2)

    with store.edit_session("Setup") as session:
        session.set_field(template_key1, "nickname", "Motor1")
        session.set_field(template_key1, "comment", "Motor control")
        session.set_field(template_key2, "nickname", "Motor1_Status")
        session.set_field(template_key2, "comment", "Status bit")

    # Clone to destination (2 clones, so 4 destination rows total)
    template_keys = [template_key1, template_key2]
    dest_keys = [
        get_addr_key("X", 3),
        get_addr_key("X", 4),
        get_addr_key("X", 5),
        get_addr_key("X", 6),
    ]
    with store.edit_session("Clone"):
        affected = RowService.clone_structure(store, template_keys, dest_keys, clone_count=2)

    # Check affected keys
    assert len(affected) == 4
    for key in dest_keys:
        assert key in affected

    # Check first clone (clone_num=1)
    assert store.visible_state[get_addr_key("X", 3)].nickname == "Motor2"
    assert store.visible_state[get_addr_key("X", 4)].nickname == "Motor2_Status"

    # Check second clone (clone_num=2)
    assert store.visible_state[get_addr_key("X", 5)].nickname == "Motor3"
    assert store.visible_state[get_addr_key("X", 6)].nickname == "Motor3_Status"

    # Check comments copied
    assert store.visible_state[get_addr_key("X", 3)].comment == "Motor control"
    assert store.visible_state[get_addr_key("X", 4)].comment == "Status bit"


def test_clone_structure_with_increment_initial_value(store):
    """Test clone structure with initial value incrementing."""
    template_key = get_addr_key("X", 1)

    with store.edit_session("Setup") as session:
        session.set_field(template_key, "nickname", "Tank1")
        session.set_field(template_key, "initial_value", "1")

    template_keys = [template_key]
    dest_keys = [get_addr_key("X", 2), get_addr_key("X", 3)]  # 2 clones
    with store.edit_session("Clone"):
        RowService.clone_structure(
            store, template_keys, dest_keys, clone_count=2, increment_initial_value=True
        )

    # Check initial values incremented
    assert store.visible_state[get_addr_key("X", 2)].initial_value == "2"
    assert store.visible_state[get_addr_key("X", 3)].initial_value == "3"


def test_clone_structure_empty_template_row(store):
    """Test cloning with empty row in template."""
    # Template with one populated, one empty
    template_key1 = get_addr_key("X", 1)

    with store.edit_session("Setup") as session:
        session.set_field(template_key1, "nickname", "Sensor1")
        session.set_field(template_key1, "comment", "Active")

    # Row 2 left empty (no nickname) - using default skeleton state

    template_keys = [template_key1, get_addr_key("X", 2)]
    dest_keys = [get_addr_key("X", 3), get_addr_key("X", 4)]  # 1 clone
    with store.edit_session("Clone"):
        RowService.clone_structure(store, template_keys, dest_keys, clone_count=1)

    # Check first row cloned with incremented nickname
    assert store.visible_state[get_addr_key("X", 3)].nickname == "Sensor2"

    # Check second row has no nickname (empty in template)
    assert store.visible_state[get_addr_key("X", 4)].nickname == ""


def test_clone_structure_nickname_index_updated(store):
    """Test that nickname reverse index is updated during clone."""
    template_key = get_addr_key("X", 1)

    with store.edit_session("Setup") as session:
        session.set_field(template_key, "nickname", "Clone1")

    template_keys = [template_key]
    dest_keys = [get_addr_key("X", 2), get_addr_key("X", 3)]
    with store.edit_session("Clone"):
        RowService.clone_structure(store, template_keys, dest_keys, clone_count=2)

    # Check reverse index has all cloned nicknames
    assert store.is_duplicate_nickname("Clone2", exclude_addr_key=999)
    assert store.is_duplicate_nickname("Clone3", exclude_addr_key=999)
