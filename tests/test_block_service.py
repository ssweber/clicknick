"""Tests for BlockService."""

import pytest

from clicknick.data.shared_data import SharedAddressData
from clicknick.models.blocktag import parse_block_tag
from clicknick.services.block_service import BlockService
from clicknick.views.address_editor.view_builder import build_unified_view


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

    # Build and cache unified view (needed for block color updates)
    view = build_unified_view(shared.all_rows, shared.all_nicknames)
    shared.set_unified_view(view)

    return shared


def test_update_colors_single_block(shared_data):
    """Test updating block colors for a single block."""
    # Get first few rows from unified view
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Add block tags to comments (must be in edit_session)
    # Block colors are automatically updated when the session exits
    with shared_data.edit_session():
        rows[0].comment = "<TestBlock bg='Red'>"
        rows[5].comment = "</TestBlock>"

    # Check colors were set on rows in the block (automatic via session)
    assert rows[0].block_color == "Red"
    assert rows[1].block_color == "Red"
    assert rows[2].block_color == "Red"
    assert rows[3].block_color == "Red"
    assert rows[4].block_color == "Red"
    assert rows[5].block_color == "Red"

    # Check rows outside block have no color
    assert rows[6].block_color is None
    assert rows[7].block_color is None


def test_update_colors_nested_blocks(shared_data):
    """Test that inner blocks override outer blocks."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Add block tags (must be in edit_session)
    with shared_data.edit_session():
        # Outer block (Red)
        rows[0].comment = "<Outer bg='Red'>"
        rows[9].comment = "</Outer>"

        # Inner block (Blue)
        rows[3].comment = "<Inner bg='Blue'>"
        rows[6].comment = "</Inner>"

    # Update colors
    BlockService.update_colors(shared_data)

    # Rows before inner block should be Red
    assert rows[1].block_color == "Red"
    assert rows[2].block_color == "Red"

    # Rows in inner block should be Blue (overrides Red)
    assert rows[3].block_color == "Blue"
    assert rows[4].block_color == "Blue"
    assert rows[6].block_color == "Blue"

    # Rows after inner block should be Red again
    assert rows[7].block_color == "Red"
    assert rows[8].block_color == "Red"


def test_update_colors_self_closing_tag(shared_data):
    """Test self-closing block tags."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Self-closing tag colors only that row (must be in edit_session)
    with shared_data.edit_session():
        rows[3].comment = "<SingleRow bg='Green' />"

    # Update colors
    BlockService.update_colors(shared_data)

    # Only row 3 should have color
    assert rows[2].block_color is None
    assert rows[3].block_color == "Green"
    assert rows[4].block_color is None


def test_update_colors_clears_old_colors(shared_data):
    """Test that removing block tags clears colors."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Add block (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<Block bg='Red'>"
        rows[5].comment = "</Block>"
    BlockService.update_colors(shared_data)

    # Verify colors set
    assert rows[2].block_color == "Red"

    # Remove block tags (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = ""
        rows[5].comment = ""
    BlockService.update_colors(shared_data)

    # Colors should be cleared
    assert rows[2].block_color is None


def test_auto_update_matching_block_tag_delete(shared_data):
    """Test auto-deleting paired tag when one is deleted."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Create a block (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<Block>"
        rows[5].comment = "</Block>"

    # Parse old tag
    old_tag = parse_block_tag(rows[0].comment)

    # Delete opening tag and auto-update paired tag (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = ""
        new_tag = parse_block_tag(rows[0].comment)

        # Auto-update paired tag
        paired_idx = BlockService.auto_update_matching_block_tag(rows, 0, old_tag, new_tag)

    # Check paired tag was deleted
    assert paired_idx == 5
    assert rows[5].comment == ""


def test_auto_update_matching_block_tag_rename(shared_data):
    """Test auto-renaming paired tag when one is renamed."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Create a block (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<OldName>"
        rows[5].comment = "</OldName>"

    # Parse old tag
    old_tag = parse_block_tag(rows[0].comment)

    # Rename opening tag and auto-update (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<NewName>"
        new_tag = parse_block_tag(rows[0].comment)

        # Auto-update paired tag
        paired_idx = BlockService.auto_update_matching_block_tag(rows, 0, old_tag, new_tag)

    # Check paired tag was renamed
    assert paired_idx == 5
    assert rows[5].comment == "</NewName>"


def test_auto_update_matching_block_tag_preserve_remaining_text(shared_data):
    """Test that remaining text is preserved when renaming."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Create block with remaining text (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<Block>"
        rows[5].comment = "</Block>Extra text here"

    old_tag = parse_block_tag(rows[0].comment)

    # Rename and auto-update (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<Renamed>"
        new_tag = parse_block_tag(rows[0].comment)

        # Auto-update
        BlockService.auto_update_matching_block_tag(rows, 0, old_tag, new_tag)

    # Check remaining text preserved
    assert "</Renamed> Extra text here" in rows[5].comment


def test_auto_update_matching_block_tag_self_closing_no_pair(shared_data):
    """Test that self-closing tags don't trigger paired updates."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Create self-closing tag (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<Single />"

    old_tag = parse_block_tag(rows[0].comment)

    # Delete it (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = ""
        new_tag = parse_block_tag(rows[0].comment)

        # Try to auto-update (should return None - no pair)
        paired_idx = BlockService.auto_update_matching_block_tag(rows, 0, old_tag, new_tag)

    assert paired_idx is None


def test_compute_block_colors_map(shared_data):
    """Test helper method for computing color map."""
    view = shared_data.get_unified_view()
    rows = view.rows[:10]

    # Add blocks (must be in edit_session)
    with shared_data.edit_session():
        rows[0].comment = "<Block bg='Red'>"
        rows[5].comment = "</Block>"

    # Compute map (without modifying AddressRow objects)
    color_map = BlockService.compute_block_colors_map(rows)

    # Check map has correct colors
    assert color_map[0] == "Red"
    assert color_map[3] == "Red"
    assert color_map[5] == "Red"

    # Rows outside block should not be in map
    assert 6 not in color_map
    assert 7 not in color_map
