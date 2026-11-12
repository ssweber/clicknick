"""Tests for RowService."""

import pytest
from pyclickplc.addresses import get_addr_key

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
    with store.edit_session("Fill down") as session:
        affected = RowService.fill_down(session, store, source_key, target_keys)

    # Check affected keys
    assert len(affected) == 3  # the 3 targets
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
    with store.edit_session("Fill down") as session:
        RowService.fill_down(session, store, source_key, target_keys, increment_initial_value=True)

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
    with store.edit_session("Fill down") as session:
        RowService.fill_down(session, store, source_key, target_keys, increment_initial_value=True)

    # Check initial value was just copied, not incremented
    assert store.visible_state[get_addr_key("X", 2)].initial_value == "5"


def test_fill_down_nickname_index_updated(store):
    """Test that nickname reverse index is updated during fill down."""
    source_key = get_addr_key("X", 1)

    with store.edit_session("Setup") as session:
        session.set_field(source_key, "nickname", "Test1")

    target_keys = [get_addr_key("X", 2)]
    with store.edit_session("Fill down") as session:
        RowService.fill_down(session, store, source_key, target_keys)

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
    with store.edit_session("Clone") as session:
        affected = RowService.clone_structure(
            session, store, template_keys, dest_keys, clone_count=2
        )

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
    with store.edit_session("Clone") as session:
        RowService.clone_structure(
            session, store, template_keys, dest_keys, clone_count=2, increment_initial_value=True
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
    with store.edit_session("Clone") as session:
        RowService.clone_structure(session, store, template_keys, dest_keys, clone_count=1)

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
    with store.edit_session("Clone") as session:
        RowService.clone_structure(session, store, template_keys, dest_keys, clone_count=2)

    # Check reverse index has all cloned nicknames
    assert store.is_duplicate_nickname("Clone2", exclude_addr_key=999)
    assert store.is_duplicate_nickname("Clone3", exclude_addr_key=999)


# Fill Down / Clone over interleaved types, block tags
def _rows(store, *keys):
    return [store.visible_state[k] for k in keys]


def test_fill_down_targets_keep_only_the_source_memory_type(store):
    rows = _rows(
        store,
        get_addr_key("T", 1),
        get_addr_key("TD", 1),
        get_addr_key("T", 2),
        get_addr_key("TD", 2),
    )

    targets = RowService.fill_down_targets(rows)

    assert [r.addr_key for r in targets] == [get_addr_key("T", 2)]


def test_can_fill_down_ignores_other_type_rows_with_nicknames(store):
    with store.edit_session("Setup") as session:
        session.set_field(get_addr_key("T", 1), "nickname", "Delay1")
        session.set_field(get_addr_key("TD", 1), "nickname", "DelayPreset")
    rows = _rows(store, get_addr_key("T", 1), get_addr_key("TD", 1), get_addr_key("T", 2))

    assert RowService.can_fill_down(rows) == (True, "")


def test_can_fill_down_needs_a_target_of_the_source_type(store):
    with store.edit_session("Setup") as session:
        session.set_field(get_addr_key("T", 1), "nickname", "Delay1")
    rows = _rows(store, get_addr_key("T", 1), get_addr_key("TD", 1))

    can_fill, _ = RowService.can_fill_down(rows)

    assert not can_fill


def test_fill_down_does_not_copy_block_tags(store):
    first, last = get_addr_key("DS", 1), get_addr_key("DS", 5)
    with store.edit_session("Setup") as session:
        session.set_field(first, "nickname", "Alarm1")
        session.set_field(first, "comment", "<Alarms> first alarm")
        session.set_field(last, "comment", "</Alarms>")
    targets = [get_addr_key("DS", n) for n in (2, 3, 4)]

    with store.edit_session("Fill down") as session:
        RowService.fill_down(session, store, first, targets)

    assert [store.visible_state[k].comment for k in targets] == ["first alarm"] * 3
    assert store.visible_state[last].comment == "</Alarms>"
    assert not store.has_errors()


def test_clone_structure_does_not_copy_block_tags(store):
    template = [get_addr_key("DS", 1), get_addr_key("DS", 2)]
    with store.edit_session("Setup") as session:
        session.set_field(template[0], "nickname", "Pump1")
        session.set_field(template[0], "comment", "<Pumps>")
        session.set_field(template[1], "nickname", "Pump1_Run")
        session.set_field(template[1], "comment", "</Pumps>")
    destination = [get_addr_key("DS", n) for n in (3, 4)]

    with store.edit_session("Clone") as session:
        RowService.clone_structure(session, store, template, destination, 1)

    assert [store.visible_state[k].comment for k in destination] == ["", ""]
    assert not store.has_errors()


def _tag_block(store, keys, name="Blk"):
    first, last = RowService.block_tag_keys(_rows(store, *keys))
    with store.edit_session("Add block tag") as session:
        session.set_field(first, "comment", f"<{name}>")
        session.set_field(last, "comment", f"</{name}>")


def _interleaved(*span):
    """Display-order keys of a T/TD selection from span[0] to span[1], as (type, number)."""
    order = [(m, n) for n in range(1, 20) for m in ("T", "TD")]
    return [get_addr_key(m, n) for m, n in order[order.index(span[0]) : order.index(span[1]) + 1]]


@pytest.mark.parametrize(
    "span",
    [(("T", 1), ("TD", 5)), (("TD", 1), ("T", 5)), (("T", 1), ("T", 5)), (("T", 11), ("TD", 15))],
)
def test_add_block_over_t_td_selection_writes_a_matched_pair(store, span):
    _tag_block(store, _interleaved(*span))

    first, last = span[0][1], span[1][1]
    comment = lambda mem, n: store.visible_state[get_addr_key(mem, n)].comment  # noqa: E731
    assert comment("T", first).startswith("<Blk")
    assert comment("TD", first).startswith("<Blk_D")
    assert comment("T", last) == "</Blk>"
    assert comment("TD", last) == "</Blk_D>"
    assert not store.has_errors()


def test_fill_down_through_the_closing_row_keeps_its_tag(store):
    first, last = get_addr_key("DS", 1), get_addr_key("DS", 5)
    with store.edit_session("Setup") as session:
        session.set_field(first, "nickname", "Alarm1")
        session.set_field(first, "comment", "<Alarms> x")
        session.set_field(last, "comment", "</Alarms>")
    targets = [get_addr_key("DS", n) for n in (2, 3, 4, 5)]

    with store.edit_session("Fill down") as session:
        RowService.fill_down(session, store, first, targets)

    assert store.visible_state[last].comment == "</Alarms>"
    assert store.visible_state[first].comment == "<Alarms> x"
    assert store.visible_state[get_addr_key("DS", 3)].comment == "x"
    assert not store.has_errors()


def test_clone_through_a_destination_with_a_tag_keeps_its_tag(store):
    template = [get_addr_key("DS", 1), get_addr_key("DS", 2)]
    with store.edit_session("Setup") as session:
        session.set_field(template[0], "nickname", "Pump1")
        session.set_field(template[0], "comment", "<Pumps> a")
        session.set_field(template[1], "nickname", "Pump1_Run")
        session.set_field(get_addr_key("DS", 4), "comment", "</Pumps>")
    destination = [get_addr_key("DS", 3), get_addr_key("DS", 4)]

    with store.edit_session("Clone") as session:
        RowService.clone_structure(session, store, template, destination, 1)

    assert store.visible_state[get_addr_key("DS", 4)].comment == "</Pumps>"
    assert store.visible_state[get_addr_key("DS", 3)].comment == "a"
    assert not store.has_errors()


def test_comment_without_block_tag_collapses_the_gap():
    assert RowService._comment_without_block_tag("a <B> b") == "a b"
    assert RowService._comment_without_block_tag("plain  text") == "plain  text"
