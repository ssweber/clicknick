"""Tests for AddressStore with base/overlay architecture."""

import pytest

from clicknick.data.address_store import AddressStore
from clicknick.data.undo_frame import MAX_UNDO_DEPTH
from clicknick.models.address_row import get_addr_key


class MockDataSource:
    """Mock data source for testing."""

    supports_used_field = True
    file_path = "test.mdb"
    is_read_only = False

    def __init__(self, initial_rows=None):
        self._initial_rows = initial_rows or {}

    def load_all_addresses(self):
        return self._initial_rows

    def save_changes(self, rows):
        return len(rows)


@pytest.fixture
def store():
    """Create an AddressStore instance with skeleton rows."""
    data_source = MockDataSource()
    s = AddressStore(data_source)
    s.load_initial_data()
    return s


@pytest.fixture
def store_with_data():
    """Create a store with pre-loaded data in base_state."""

    from clicknick.models.address_row import AddressRow

    # Create initial rows that simulate being loaded from database
    addr_key_1 = get_addr_key("X", 1)
    addr_key_2 = get_addr_key("X", 2)

    initial_rows = {
        addr_key_1: AddressRow(
            memory_type="X",
            address=1,
            nickname="Input1",
            comment="Button",
            exists_in_mdb=True,
        ),
        addr_key_2: AddressRow(
            memory_type="X",
            address=2,
            nickname="Input2",
            comment="Switch",
            exists_in_mdb=True,
        ),
    }

    data_source = MockDataSource(initial_rows)
    s = AddressStore(data_source)
    s.load_initial_data()
    return s


class TestEditSession:
    """Tests for edit_session context manager."""

    def test_edit_session_creates_override(self, store):
        """Edit session should create user_override entry."""
        addr_key = get_addr_key("X", 1)

        with store.edit_session("Test edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert addr_key in store.user_overrides
        assert store.visible_state[addr_key].nickname == "NewName"

    def test_edit_session_pushes_undo_frame(self, store):
        """Edit session should push undo frame."""
        addr_key = get_addr_key("X", 1)

        assert len(store.undo_stack) == 0

        with store.edit_session("Test edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert len(store.undo_stack) == 1
        assert store.undo_stack[0].description == "Test edit"

    def test_edit_session_no_changes_no_undo(self, store):
        """Edit session with no changes should not push undo frame."""
        with store.edit_session("Empty edit"):
            pass  # No changes

        assert len(store.undo_stack) == 0

    def test_multiple_edits_single_undo_frame(self, store):
        """Multiple edits in one session = single undo frame."""
        addr_key_1 = get_addr_key("X", 1)
        addr_key_2 = get_addr_key("X", 2)
        addr_key_3 = get_addr_key("X", 3)

        with store.edit_session("Batch edit") as session:
            session.set_field(addr_key_1, "nickname", "Name1")
            session.set_field(addr_key_2, "nickname", "Name2")
            session.set_field(addr_key_3, "nickname", "Name3")

        # All three edits in one undo frame
        assert len(store.undo_stack) == 1
        assert len(store.user_overrides) == 3

    def test_nested_edit_session_raises(self, store):
        """Nested edit sessions should raise RuntimeError."""
        addr_key = get_addr_key("X", 1)

        with pytest.raises(RuntimeError):
            with store.edit_session("Outer") as outer:
                outer.set_field(addr_key, "nickname", "Outer")
                with store.edit_session("Inner") as inner:
                    inner.set_field(addr_key, "nickname", "Inner")


class TestUndoRedo:
    """Tests for undo/redo functionality."""

    def test_undo_restores_previous_state(self, store):
        """Undo should restore previous state."""
        addr_key = get_addr_key("X", 1)

        # Make an edit
        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert store.visible_state[addr_key].nickname == "NewName"

        # Undo
        result = store.undo()

        assert result is True
        assert store.visible_state[addr_key].nickname == ""  # Back to default

    def test_redo_reapplies_changes(self, store):
        """Redo should re-apply undone changes."""
        addr_key = get_addr_key("X", 1)

        # Make an edit
        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        # Undo
        store.undo()
        assert store.visible_state[addr_key].nickname == ""

        # Redo
        result = store.redo()

        assert result is True
        assert store.visible_state[addr_key].nickname == "NewName"

    def test_undo_empty_stack_returns_false(self, store):
        """Undo with empty stack should return False."""
        result = store.undo()
        assert result is False

    def test_redo_empty_stack_returns_false(self, store):
        """Redo with empty stack should return False."""
        result = store.redo()
        assert result is False

    def test_new_edit_clears_redo_stack(self, store):
        """New edit after undo should clear redo stack."""
        addr_key = get_addr_key("X", 1)

        # Make edit, undo
        with store.edit_session("Edit 1") as session:
            session.set_field(addr_key, "nickname", "Name1")
        store.undo()

        assert len(store.redo_stack) == 1

        # New edit should clear redo
        with store.edit_session("Edit 2") as session:
            session.set_field(addr_key, "nickname", "Name2")

        assert len(store.redo_stack) == 0

    def test_max_undo_depth_enforced(self, store):
        """Undo stack should not exceed MAX_UNDO_DEPTH."""
        addr_key = get_addr_key("X", 1)

        # Make more edits than MAX_UNDO_DEPTH
        for i in range(MAX_UNDO_DEPTH + 10):
            with store.edit_session(f"Edit {i}") as session:
                session.set_field(addr_key, "nickname", f"Name{i}")

        assert len(store.undo_stack) == MAX_UNDO_DEPTH


class TestDirtyState:
    """Tests for dirty state detection."""

    def test_is_dirty_after_edit(self, store):
        """Row should be dirty after edit."""
        addr_key = get_addr_key("X", 1)

        assert store.is_dirty(addr_key) is False

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert store.is_dirty(addr_key) is True

    def test_is_field_dirty(self, store_with_data):
        """is_field_dirty should detect specific field changes."""
        addr_key = get_addr_key("X", 1)

        # Initial state - nothing dirty
        assert store_with_data.is_field_dirty(addr_key, "nickname") is False
        assert store_with_data.is_field_dirty(addr_key, "comment") is False

        # Edit only nickname
        with store_with_data.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "ChangedName")

        assert store_with_data.is_field_dirty(addr_key, "nickname") is True
        assert store_with_data.is_field_dirty(addr_key, "comment") is False

    def test_has_unsaved_changes(self, store):
        """has_unsaved_changes should reflect override state."""
        addr_key = get_addr_key("X", 1)

        assert store.has_unsaved_changes() is False

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert store.has_unsaved_changes() is True

    def test_get_dirty_keys(self, store):
        """get_dirty_keys should return all modified keys."""
        addr_key_1 = get_addr_key("X", 1)
        addr_key_2 = get_addr_key("X", 2)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key_1, "nickname", "Name1")
            session.set_field(addr_key_2, "nickname", "Name2")

        dirty = store.get_dirty_keys()
        assert addr_key_1 in dirty
        assert addr_key_2 in dirty
        assert len(dirty) == 2


class TestBaseOverlayMerge:
    """Tests for base/overlay visible state computation."""

    def test_visible_equals_base_when_no_overlay(self, store_with_data):
        """Visible state should equal base when no overlay."""
        addr_key = get_addr_key("X", 1)

        base = store_with_data.base_state[addr_key]
        visible = store_with_data.visible_state[addr_key]

        assert visible.nickname == base.nickname
        assert visible.comment == base.comment

    def test_visible_reflects_overlay(self, store_with_data):
        """Visible state should reflect overlay edits."""
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "OverlayName")

        # Base unchanged
        assert store_with_data.base_state[addr_key].nickname == "Input1"
        # Visible reflects overlay
        assert store_with_data.visible_state[addr_key].nickname == "OverlayName"

    def test_undo_removes_overlay(self, store_with_data):
        """Undo should remove overlay, visible returns to base."""
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "OverlayName")

        store_with_data.undo()

        # Overlay cleared
        assert addr_key not in store_with_data.user_overrides
        # Visible equals base
        assert store_with_data.visible_state[addr_key].nickname == "Input1"


class TestDiscardChanges:
    """Tests for discard_all_changes."""

    def test_discard_clears_overrides(self, store):
        """discard_all_changes should clear all overrides."""
        addr_key_1 = get_addr_key("X", 1)
        addr_key_2 = get_addr_key("X", 2)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key_1, "nickname", "Name1")
            session.set_field(addr_key_2, "nickname", "Name2")

        assert len(store.user_overrides) == 2

        store.discard_all_changes()

        assert len(store.user_overrides) == 0
        assert store.visible_state[addr_key_1].nickname == ""
        assert store.visible_state[addr_key_2].nickname == ""


class TestObservers:
    """Tests for observer pattern."""

    def test_observer_notified_on_edit(self, store):
        """Observer should be notified when data changes."""
        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store.add_observer(observer)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_observer_notified_on_undo(self, store):
        """Observer should be notified on undo."""
        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store.add_observer(observer)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        notifications.clear()  # Clear notification from edit

        store.undo()

        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_remove_observer(self, store):
        """Removed observer should not be notified."""
        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store.add_observer(observer)
        store.remove_observer(observer)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "nickname", "NewName")

        assert len(notifications) == 0


class TestExternalDatabaseUpdate:
    """Tests for external database update handling."""

    def test_external_update_notifies_rows_with_overrides(self, store_with_data):
        """External DB update should notify rows with overrides even if visible unchanged.

        This ensures cell notes can update to show new base values when the
        external database changes but the user has local edits.
        """
        from clicknick.models.address_row import AddressRow

        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store_with_data.add_observer(observer)

        # User makes a local edit (creates override)
        with store_with_data.edit_session("Edit") as session:
            session.set_field(addr_key, "comment", "UserComment")

        notifications.clear()

        # Verify state before external update
        assert store_with_data.base_state[addr_key].comment == "Button"
        assert store_with_data.visible_state[addr_key].comment == "UserComment"

        # Simulate external database update - base changes but visible stays same
        # because user override takes precedence
        store_with_data._data_source._initial_rows[addr_key] = AddressRow(
            memory_type="X",
            address=1,
            nickname="Input1",
            comment="ExternallyUpdatedComment",  # Changed externally
            exists_in_mdb=True,
        )
        store_with_data._on_database_update()

        # Base should be updated
        assert store_with_data.base_state[addr_key].comment == "ExternallyUpdatedComment"
        # Visible should still have user's override
        assert store_with_data.visible_state[addr_key].comment == "UserComment"

        # Key assertion: row should be in notification so cell notes can update
        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_external_update_no_notification_when_no_change(self, store_with_data):
        """External update with no actual changes should not notify."""
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store_with_data.add_observer(observer)

        # Call update without changing any data
        store_with_data._on_database_update()

        # No notification because nothing changed
        assert len(notifications) == 0

    def test_external_update_notifies_changed_rows_without_overrides(self, store_with_data):
        """External update should notify rows without overrides when visible changes."""
        from clicknick.models.address_row import AddressRow

        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store_with_data.add_observer(observer)

        # No user edits - external change should propagate to visible
        store_with_data._data_source._initial_rows[addr_key] = AddressRow(
            memory_type="X",
            address=1,
            nickname="Input1",
            comment="ExternallyUpdatedComment",
            exists_in_mdb=True,
        )
        store_with_data._on_database_update()

        # Both base and visible should be updated
        assert store_with_data.base_state[addr_key].comment == "ExternallyUpdatedComment"
        assert store_with_data.visible_state[addr_key].comment == "ExternallyUpdatedComment"

        # Should be notified
        assert len(notifications) == 1
        assert addr_key in notifications[0]
