"""Tests for BlockService."""

import pytest

from clicknick.data.address_store import AddressStore
from clicknick.services.block_service import (
    compute_all_block_ranges,
    get_all_block_names,
    is_block_name_available,
)
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
    assert store.get_block_color(rows[0].addr_key) == "Red"
    assert store.get_block_color(rows[1].addr_key) == "Red"
    assert store.get_block_color(rows[2].addr_key) == "Red"
    assert store.get_block_color(rows[3].addr_key) == "Red"
    assert store.get_block_color(rows[4].addr_key) == "Red"
    assert store.get_block_color(rows[5].addr_key) == "Red"

    # Check rows outside block have no color
    assert store.get_block_color(rows[6].addr_key) is None
    assert store.get_block_color(rows[7].addr_key) is None


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
    assert store.get_block_color(rows[1].addr_key) == "Red"
    assert store.get_block_color(rows[2].addr_key) == "Red"

    # Rows in inner block should be Blue (overrides Red)
    assert store.get_block_color(rows[3].addr_key) == "Blue"
    assert store.get_block_color(rows[4].addr_key) == "Blue"
    assert store.get_block_color(rows[6].addr_key) == "Blue"

    # Rows after inner block should be Red again
    assert store.get_block_color(rows[7].addr_key) == "Red"
    assert store.get_block_color(rows[8].addr_key) == "Red"


def test_update_colors_self_closing_tag(store):
    """Test self-closing block tags."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Self-closing tag colors only that row
    with store.edit_session("Add self-closing") as session:
        session.set_field(rows[3].addr_key, "comment", "<SingleRow bg='Green' />")

    # Only row 3 should have color
    assert store.get_block_color(rows[2].addr_key) is None
    assert store.get_block_color(rows[3].addr_key) == "Green"
    assert store.get_block_color(rows[4].addr_key) is None


def test_update_colors_clears_old_colors(store):
    """Test that removing block tags clears colors."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Add block
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Block bg='Red'>")
        session.set_field(rows[5].addr_key, "comment", "</Block>")

    # Verify colors set
    assert store.get_block_color(rows[2].addr_key) == "Red"

    # Remove block tags
    with store.edit_session("Remove block") as session:
        session.set_field(rows[0].addr_key, "comment", "")
        session.set_field(rows[5].addr_key, "comment", "")

    # Colors should be cleared
    assert store.get_block_color(rows[2].addr_key) is None


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


# =============================================================================
# Tests for get_all_block_names and is_block_name_available
# =============================================================================


def test_get_all_block_names_empty(store):
    """Test get_all_block_names returns empty set when no blocks."""
    view = store.get_unified_view()
    names = get_all_block_names(view.rows[:10])
    assert names == set()


def test_get_all_block_names_finds_blocks(store):
    """Test get_all_block_names finds all block names."""
    view = store.get_unified_view()
    rows = view.rows[:20]

    # Add some blocks
    with store.edit_session("Add blocks") as session:
        session.set_field(rows[0].addr_key, "comment", "<BlockA>")
        session.set_field(rows[5].addr_key, "comment", "</BlockA>")
        session.set_field(rows[10].addr_key, "comment", "<BlockB bg='Blue'>")
        session.set_field(rows[15].addr_key, "comment", "</BlockB>")

    # Refresh view
    view = store.get_unified_view()
    names = get_all_block_names(view.rows[:20])

    assert names == {"BlockA", "BlockB"}


def test_get_all_block_names_includes_self_closing(store):
    """Test get_all_block_names includes self-closing blocks."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    with store.edit_session("Add self-closing") as session:
        session.set_field(rows[3].addr_key, "comment", "<SingleBlock />")

    view = store.get_unified_view()
    names = get_all_block_names(view.rows[:10])

    assert "SingleBlock" in names


def test_is_block_name_available_true(store):
    """Test is_block_name_available returns True when name is not in use."""
    view = store.get_unified_view()
    assert is_block_name_available("NewBlock", view.rows[:10])


def test_is_block_name_available_false(store):
    """Test is_block_name_available returns False when name exists."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<ExistingBlock>")
        session.set_field(rows[5].addr_key, "comment", "</ExistingBlock>")

    view = store.get_unified_view()
    assert not is_block_name_available("ExistingBlock", view.rows[:10])


def test_is_block_name_available_with_exclusion(store):
    """Test is_block_name_available respects exclude_addr_keys."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<MyBlock>")
        session.set_field(rows[5].addr_key, "comment", "</MyBlock>")

    view = store.get_unified_view()
    rows = view.rows[:10]

    # Without exclusion, name is not available
    assert not is_block_name_available("MyBlock", rows)

    # With exclusion of the rows containing the tags, name IS available
    # (useful when renaming - exclude the rows being renamed)
    exclude = {rows[0].addr_key, rows[5].addr_key}
    assert is_block_name_available("MyBlock", rows, exclude_addr_keys=exclude)


def test_is_block_name_available_case_sensitive(store):
    """Test that block name check is case-sensitive."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<MyBlock>")

    view = store.get_unified_view()

    # Exact case match should NOT be available
    assert not is_block_name_available("MyBlock", view.rows[:10])

    # Different case should be available (case-sensitive)
    assert is_block_name_available("myblock", view.rows[:10])
    assert is_block_name_available("MYBLOCK", view.rows[:10])


# =============================================================================
# Tests for duplicate block name validation in AddressStore
# =============================================================================


def test_duplicate_block_name_validation_marks_row_invalid(store):
    """Test that creating duplicate block names marks row as invalid."""
    view = store.get_unified_view()
    rows = view.rows[:20]

    # Create first block
    with store.edit_session("Add first block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Pumps>")
        session.set_field(rows[5].addr_key, "comment", "</Pumps>")

    # Try to create second block with same name
    with store.edit_session("Add duplicate block") as session:
        session.set_field(rows[10].addr_key, "comment", "<Pumps>")

    # Check the duplicate row is marked invalid
    row10 = store.visible_state[rows[10].addr_key]
    assert not row10.comment_valid
    assert "Duplicate block" in row10.comment_error


def test_duplicate_block_name_validation_allows_same_block(store):
    """Test that a block's own opening/closing tags don't trigger duplicate error."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Create a block
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Motors>")
        session.set_field(rows[5].addr_key, "comment", "</Motors>")

    # Both tags should be valid (they're the same block, not duplicates)
    row0 = store.visible_state[rows[0].addr_key]

    # Note: The opening and closing tags of the same block should be valid
    # because they ARE the same block - but with current logic they will
    # show as duplicates of each other. This is expected behavior for Phase 0a.
    # The simplification assumes unique names globally, so paired open/close
    # tags are allowed to have the same name.
    assert row0.comment_valid
    # The closing tag will see the opening tag as duplicate - this is expected
    # In a proper block, both use the same name and that's valid
    # The duplicate check excludes the current row, so the opening tag is valid
    # But the closing tag sees the opening tag as existing


def test_is_duplicate_block_name_method(store):
    """Test the is_duplicate_block_name method directly."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Initially, no duplicates
    assert not store.is_duplicate_block_name("NewBlock", rows[0].addr_key)

    # Create a block
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<ExistingBlock>")

    # Now "ExistingBlock" is a duplicate for other rows
    assert store.is_duplicate_block_name("ExistingBlock", rows[5].addr_key)

    # But not for the row that has it (excluded)
    assert not store.is_duplicate_block_name("ExistingBlock", rows[0].addr_key)


def test_closing_tag_not_marked_as_duplicate(store):
    """Test that closing tags are NOT marked as duplicates of their opening tag."""
    view = store.get_unified_view()
    rows = view.rows[:10]

    # Create a block with opening and closing tags
    with store.edit_session("Add block") as session:
        session.set_field(rows[0].addr_key, "comment", "<MyBlock>")
        session.set_field(rows[5].addr_key, "comment", "</MyBlock>")

    # Both opening and closing tags should be valid (not duplicates)
    row0 = store.visible_state[rows[0].addr_key]
    row5 = store.visible_state[rows[5].addr_key]

    assert row0.comment_valid, f"Opening tag should be valid, got error: {row0.comment_error}"
    assert row5.comment_valid, f"Closing tag should be valid, got error: {row5.comment_error}"


def test_multiple_blocks_same_name_marked_duplicate(store):
    """Test that multiple opening tags with same name ARE marked as duplicates."""
    view = store.get_unified_view()
    rows = view.rows[:20]

    # Create two separate blocks with the same name
    with store.edit_session("Add first block") as session:
        session.set_field(rows[0].addr_key, "comment", "<Duplicate>")
        session.set_field(rows[3].addr_key, "comment", "</Duplicate>")

    # Add second block with same name
    with store.edit_session("Add second block") as session:
        session.set_field(rows[10].addr_key, "comment", "<Duplicate>")
        session.set_field(rows[15].addr_key, "comment", "</Duplicate>")

    # First block should be valid
    row0 = store.visible_state[rows[0].addr_key]
    row3 = store.visible_state[rows[3].addr_key]
    assert row0.comment_valid, "First opening tag should be valid"
    assert row3.comment_valid, "First closing tag should be valid"

    # Second block's OPENING tag should be marked as duplicate
    row10 = store.visible_state[rows[10].addr_key]
    assert not row10.comment_valid, "Second opening tag should be invalid (duplicate)"
    assert "Duplicate" in row10.comment_error

    # Second block's closing tag should still be valid (closing tags aren't duplicates)
    row15 = store.visible_state[rows[15].addr_key]
    assert row15.comment_valid, "Second closing tag should be valid"


# =============================================================================
# Tests for _D suffix transformation (Phase 0b)
# =============================================================================


def test_transform_block_name_t_to_td():
    """Test T → TD adds _D suffix."""
    from clicknick.services.block_service import _transform_block_name_for_pair

    # Base name gets _D suffix
    assert _transform_block_name_for_pair("Pumps", "T", "TD") == "Pumps_D"
    assert _transform_block_name_for_pair("Motors", "CT", "CTD") == "Motors_D"

    # Already has _D suffix - keep it
    assert _transform_block_name_for_pair("Pumps_D", "T", "TD") == "Pumps_D"


def test_transform_block_name_td_to_t():
    """Test TD → T removes _D suffix."""
    from clicknick.services.block_service import _transform_block_name_for_pair

    # Remove _D suffix
    assert _transform_block_name_for_pair("Pumps_D", "TD", "T") == "Pumps"
    assert _transform_block_name_for_pair("Motors_D", "CTD", "CT") == "Motors"

    # No _D suffix - keep as is
    assert _transform_block_name_for_pair("Pumps", "TD", "T") == "Pumps"


def test_interleaved_pair_sync_adds_suffix(store):
    """Test that T → TD block sync adds _D suffix."""
    # Find T1 and TD1 rows
    from pyclickplc import get_addr_key

    t1_key = get_addr_key("T", 1)
    td1_key = get_addr_key("TD", 1)

    # Create a block on T1
    with store.edit_session("Add block on T") as session:
        session.set_field(t1_key, "comment", "<Timers>")

    # TD1 should have the block tag with _D suffix
    td1_row = store.visible_state[td1_key]
    assert "<Timers_D>" in td1_row.comment


def test_interleaved_pair_sync_removes_suffix(store):
    """Test that TD → T block sync removes _D suffix."""
    from pyclickplc import get_addr_key

    t1_key = get_addr_key("T", 1)
    td1_key = get_addr_key("TD", 1)

    # Create a block on TD1 with _D suffix
    with store.edit_session("Add block on TD") as session:
        session.set_field(td1_key, "comment", "<Timers_D>")

    # T1 should have the block tag without _D suffix
    t1_row = store.visible_state[t1_key]
    assert "<Timers>" in t1_row.comment


def test_interleaved_pair_sync_closing_tag_with_suffix(store):
    """Test that closing tags also get _D suffix transformation."""
    from pyclickplc import get_addr_key

    t1_key = get_addr_key("T", 1)
    t5_key = get_addr_key("T", 5)
    td1_key = get_addr_key("TD", 1)
    td5_key = get_addr_key("TD", 5)

    # Create a block on T1-T5
    with store.edit_session("Add block on T") as session:
        session.set_field(t1_key, "comment", "<Pumps bg='Blue'>")
        session.set_field(t5_key, "comment", "</Pumps>")

    # TD should have corresponding tags with _D suffix
    td1_row = store.visible_state[td1_key]
    td5_row = store.visible_state[td5_key]

    assert "<Pumps_D" in td1_row.comment  # Opening tag
    assert "</Pumps_D>" in td5_row.comment  # Closing tag


def test_interleaved_pair_sync_ct_ctd(store):
    """Test that CT → CTD block sync works like T → TD."""
    from pyclickplc import get_addr_key

    ct1_key = get_addr_key("CT", 1)
    ctd1_key = get_addr_key("CTD", 1)

    # Create a block on CT1
    with store.edit_session("Add block on CT") as session:
        session.set_field(ct1_key, "comment", "<Counters>")

    # CTD1 should have the block tag with _D suffix
    ctd1_row = store.visible_state[ctd1_key]
    assert "<Counters_D>" in ctd1_row.comment
