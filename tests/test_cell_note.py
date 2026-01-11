"""Tests for CellNote dataclass."""

from clicknick.views.address_editor.cell_note import CellNote


def test_cell_note_error_only():
    """Test CellNote with only error."""
    note = CellNote(error_note="Invalid value")
    assert note.symbol == "⚠"
    assert str(note) == "Invalid value"
    assert bool(note) is True


def test_cell_note_dirty_only():
    """Test CellNote with only dirty."""
    note = CellNote(dirty_note="old_value")
    assert note.symbol == "✱"
    assert str(note) == "Original: old_value"
    assert bool(note) is True


def test_cell_note_both():
    """Test CellNote with both error and dirty."""
    note = CellNote(error_note="Invalid value", dirty_note="old_value")
    assert note.symbol == "⚠"  # Error takes priority
    assert str(note) == "Invalid value\n\nOriginal: old_value"
    assert bool(note) is True


def test_cell_note_empty():
    """Test empty CellNote."""
    note = CellNote()
    assert note.symbol == "ℹ"  # fallback
    assert str(note) == ""
    assert bool(note) is False


def test_cell_note_equality():
    """Test CellNote equality comparison."""
    note1 = CellNote(error_note="error", dirty_note="dirty")
    note2 = CellNote(error_note="error", dirty_note="dirty")
    note3 = CellNote(error_note="error")

    assert note1 == note2
    assert note1 != note3
