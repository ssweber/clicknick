"""Tests for BlockService."""

import pytest

from clicknick.data.address_store import AddressStore
from clicknick.models.blocktag import parse_block_tag
from clicknick.services.block_service import BlockService, compute_all_block_ranges
from clicknick.views.address_editor.view_builder import build_unified_view


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

    # Build and cache unified view (needed for block color updates)
    view = build_unified_view(s.visible_state, s.all_nicknames)
    s.set_unified_view(view)

    return s


def test_update_colors_single_block(store):
    """Test updating block colors for a single block."""
    # Get first few rows from unified view
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Add block tags to comments via edit_session
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<TestBlock bg='Red'>")
        session.set_field(rows[5].addr_key, "comment", "</TestBlock>")

    # Refresh view reference after edit
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Check colors were set on rows in the block
    assert store.visible_state[rows[0].addr_key].block_color == "Red"
    assert store.visible_state[rows[1].addr_key].block_color == "Red"
    assert store.visible_state[rows[2].addr_key].block_color == "Red"
    assert store.visible_state[rows[3].addr_key].block_color == "Red"
    assert store.visible_state[rows[4].addr_key].block_color == "Red"
    assert store.visible_state[rows[5].addr_key].block_color == "Red"

    # Check rows outside block have no color
    assert store.visible_state[rows[6].addr_key].block_color is None
    assert store.visible_state[rows[7].addr_key].block_color is None


def test_update_colors_nested_blocks(store):
    """Test that inner blocks override outer blocks."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Add block tags via edit_session
    with store.edit_session("Add nested blocks") as session:
        # Outer block (Red)
        session.set_field(rows[0].addr_key, "comment", "<Outer bg='Red'>")
        session.set_field(rows[9].addr_key, "comment", "</Outer>")
        # Inner block (Blue)
        session.set_field(rows[3].addr_key, "comment", "<Inner bg='Blue'>")
        session.set_field(rows[6].addr_key, "comment", "</Inner>")

    # Rows before inner block should be Red
    assert store.visible_state[rows[1].addr_key].block_color == "Red"
    assert store.visible_state[rows[2].addr_key].block_color == "Red"

    # Rows in inner block should be Blue (overrides Red)
    assert store.visible_state[rows[3].addr_key].block_color == "Blue"
    assert store.visible_state[rows[4].addr_key].block_color == "Blue"
    assert store.visible_state[rows[6].addr_key].block_color == "Blue"

    # Rows after inner block should be Red again
    assert store.visible_state[rows[7].addr_key].block_color == "Red"
    assert store.visible_state[rows[8].addr_key].block_color == "Red"


def test_update_colors_self_closing_tag(store):
    """Test self-closing block tags."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Self-closing tag colors only that row
    with store.edit_session("Add self-closing") as session:
        session.set_field(rows[3].addr_key, "comment", "<SingleRow bg='Green' />")

    # Only row 3 should have color
    assert store.visible_state[rows[2].addr_key].block_color is None
    assert store.visible_state[rows[3].addr_key].block_color == "Green"
    assert store.visible_state[rows[4].addr_key].block_color is None


def test_update_colors_clears_old_colors(store):
    """Test that removing block tags clears colors."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Add block
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Block bg='Red'>")
        session.set_field(rows[5].addr_key, "comment", "</Block>")

    # Verify colors set
    assert store.visible_state[rows[2].addr_key].block_color == "Red"

    # Remove block tags
    with store.edit_session("Remove block") as session:
        session.set_field(rows[0].addr_key, "comment", "")
        session.set_field(rows[5].addr_key, "comment", "")

    # Colors should be cleared
    assert store.visible_state[rows[2].addr_key].block_color is None


def test_auto_update_matching_block_tag_delete(store):
    """Test auto-deleting paired tag when one is deleted."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Create a block
    with store.edit_session("Create block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Block>")
        session.set_field(rows[5].addr_key, "comment", "</Block>")

    # Refresh view
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Parse old tag
    old_tag = parse_block_tag(store.visible_state[rows[0].addr_key].comment)

    # Delete opening tag - the cascade should auto-update paired tag
    with store.edit_session("Delete opening tag") as session:
        session.set_field(rows[0].addr_key, "comment", "")

    # Check paired tag was deleted by cascade
    assert store.visible_state[rows[5].addr_key].comment == ""


def test_auto_update_matching_block_tag_rename(store):
    """Test auto-renaming paired tag when one is renamed."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Create a block
    with store.edit_session("Create block") as session:
        session.set_field(rows[0].addr_key, "comment", "<OldName>")
        session.set_field(rows[5].addr_key, "comment", "</OldName>")

    # Rename opening tag - cascade should rename closing tag
    with store.edit_session("Rename block") as session:
        session.set_field(rows[0].addr_key, "comment", "<NewName>")

    # Check paired tag was renamed
    assert store.visible_state[rows[5].addr_key].comment == "</NewName>"


def test_compute_block_colors_map(store):
    """Test helper method for computing color map."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Add blocks
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Block bg='Red'>")
        session.set_field(rows[5].addr_key, "comment", "</Block>")

    # Refresh view after edit
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Compute ranges
    ranges = compute_all_block_ranges(rows)

    # Build color map from ranges
    color_map = {}
    for r in ranges:
        if r.bg_color:
            for idx in range(r.start_idx, r.end_idx + 1):
                color_map[idx] = r.bg_color

    # Check map has correct colors
    assert color_map[0] == "Red"
    assert color_map[3] == "Red"
    assert color_map[5] == "Red"

    # Rows outside block should not be in map
    assert 6 not in color_map
    assert 7 not in color_map
