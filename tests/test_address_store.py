"""Tests for AddressStore with base/overlay architecture."""

import pytest
from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import DataType

from clicknick.data.address_store import AddressStore
from clicknick.data.undo_frame import MAX_UNDO_DEPTH
from clicknick.models.address_row import AddressRow
from clicknick.views.address_editor.view_builder import build_unified_view


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

    # Create initial rows that simulate being loaded from database
    addr_key_1 = get_addr_key("X", 1)
    addr_key_2 = get_addr_key("X", 2)

    initial_rows = {
        addr_key_1: AddressRow(
            memory_type="X",
            address=1,
            nickname="Input1",
            comment="Button",
        ),
        addr_key_2: AddressRow(
            memory_type="X",
            address=2,
            nickname="Input2",
            comment="Switch",
        ),
    }

    data_source = MockDataSource(initial_rows)
    s = AddressStore(data_source)
    s.load_initial_data()
    return s


def test_loaded_row_count_tracks_source_rows(store, store_with_data):
    assert store.loaded_row_count == 0
    assert store_with_data.loaded_row_count == 2

    store_with_data._data_source._initial_rows = {}
    assert store_with_data._on_database_update() is True
    assert store_with_data.loaded_row_count == 0


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

    def test_separate_sessions_accumulate_fields_on_same_row(self, store):
        """Editing different fields of one row across SEPARATE sessions must
        preserve earlier edits.

        Regression: visible_state rows carry an empty dirty_fields, so freezing
        a later session against visible_state dropped the prior session's dirty
        markers and _merge_base_with_override reverted those fields. (Reachable
        in the UI: edit a nickname in the grid, then edit that row's comment via
        the right-click annotation dialog.)
        """
        addr_key = get_addr_key("X", 1)

        with store.edit_session("Set nickname") as session:
            session.set_field(addr_key, "nickname", "Motor_Run")
        with store.edit_session("Set comment") as session:
            session.set_field(addr_key, "comment", "Main motor")

        row = store.visible_state[addr_key]
        assert row.nickname == "Motor_Run"
        assert row.comment == "Main motor"
        assert store.is_field_dirty(addr_key, "nickname")
        assert store.is_field_dirty(addr_key, "comment")

        # Reverse order behaves the same.
        addr_key_2 = get_addr_key("X", 2)
        with store.edit_session("Set comment") as session:
            session.set_field(addr_key_2, "comment", "Switch")
        with store.edit_session("Set nickname") as session:
            session.set_field(addr_key_2, "nickname", "Pump")

        row2 = store.visible_state[addr_key_2]
        assert row2.nickname == "Pump"
        assert row2.comment == "Switch"

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


class TestNoOpEdits:
    """Writing a row's existing value back must not mark it changed.

    A builder marks a field set whenever it is assigned, even if assigned its
    current value. Since is_dirty() is presence-based, a no-op write used to leave
    an override behind: the row reported as changed, showed under the "Changed"
    filter and was written on save, while every cell compared equal to base so no
    highlight appeared. Dirty fields are recomputed against base_state to prevent it.
    """

    def test_writing_the_same_value_does_not_dirty_the_row(self, store_with_data):
        addr_key = get_addr_key("X", 1)

        # Write back exactly what the row already holds (e.g. importing a CSV
        # whose values already match the project)
        with store_with_data.edit_session("No-op") as session:
            session.set_field(addr_key, "nickname", "Input1")
            session.set_field(addr_key, "comment", "Button")

        assert store_with_data.is_dirty(addr_key) is False
        assert store_with_data.has_unsaved_changes() is False

    def test_no_op_write_agrees_with_per_field_dirty(self, store_with_data):
        """The row-level and cell-level dirty checks must not disagree."""
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("No-op") as session:
            session.set_field(addr_key, "nickname", "Input1")

        # Cells show no diff, so the row must not claim to be changed
        assert not any(
            store_with_data.is_field_dirty(addr_key, field)
            for field in ("nickname", "comment", "initial_value", "retentive")
        )
        assert store_with_data.is_dirty(addr_key) is False

    def test_editing_back_to_the_original_value_clears_dirty(self, store_with_data):
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("Change") as session:
            session.set_field(addr_key, "nickname", "Changed")
        assert store_with_data.is_dirty(addr_key) is True

        with store_with_data.edit_session("Change back") as session:
            session.set_field(addr_key, "nickname", "Input1")

        assert store_with_data.is_dirty(addr_key) is False
        assert store_with_data.get_visible_row(addr_key).nickname == "Input1"

    def test_no_op_field_does_not_dirty_alongside_a_real_change(self, store_with_data):
        """A no-op on one field must not make that field look changed."""
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("Mixed") as session:
            session.set_field(addr_key, "nickname", "Input1")  # no-op
            session.set_field(addr_key, "comment", "Changed")  # real

        assert store_with_data.is_dirty(addr_key) is True
        assert store_with_data.is_field_dirty(addr_key, "nickname") is False
        assert store_with_data.is_field_dirty(addr_key, "comment") is True

    def test_a_real_change_still_dirties_the_row(self, store_with_data):
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("Change") as session:
            session.set_field(addr_key, "nickname", "Changed")

        assert store_with_data.is_dirty(addr_key) is True
        assert store_with_data.is_field_dirty(addr_key, "nickname") is True

    def test_undo_after_edit_back_restores_the_change(self, store_with_data):
        """Dropping the override must not break the undo stack."""
        addr_key = get_addr_key("X", 1)

        with store_with_data.edit_session("Change") as session:
            session.set_field(addr_key, "nickname", "Changed")
        with store_with_data.edit_session("Change back") as session:
            session.set_field(addr_key, "nickname", "Input1")

        store_with_data.undo()

        assert store_with_data.get_visible_row(addr_key).nickname == "Changed"
        assert store_with_data.is_dirty(addr_key) is True


class TestBlankVsZeroInitialValue:
    """ "" and "0" are the same default for a numeric address.

    Click's CSV export writes "0" for every defaulted numeric while a store skeleton
    or baseline row holds "". Comparing the strings raw would report every defaulted
    numeric as changed on import, and rewrite it to the database on save.
    """

    def store_with(self, memory_type, data_type, initial_value):
        addr_key = get_addr_key(memory_type, 1)
        rows = {
            addr_key: AddressRow(
                memory_type=memory_type,
                address=1,
                data_type=data_type,
                nickname="N",
                initial_value=initial_value,
            )
        }
        s = AddressStore(MockDataSource(rows))
        s.load_initial_data()
        return s, addr_key

    @pytest.mark.parametrize(("base_value", "new_value"), [("", "0"), ("0", "")])
    def test_numeric_blank_and_zero_are_not_a_change(self, base_value, new_value):
        store, addr_key = self.store_with("DS", DataType.INT, base_value)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "initial_value", new_value)

        assert store.is_dirty(addr_key) is False
        assert store.is_field_dirty(addr_key, "initial_value") is False

    @pytest.mark.parametrize(("base_value", "new_value"), [("", "5"), ("5", ""), ("0", "5")])
    def test_numeric_real_value_changes_are_still_dirty(self, base_value, new_value):
        store, addr_key = self.store_with("DS", DataType.INT, base_value)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "initial_value", new_value)

        assert store.is_dirty(addr_key) is True
        assert store.is_field_dirty(addr_key, "initial_value") is True

    @pytest.mark.parametrize(("base_value", "new_value"), [("", "0"), ("0", "")])
    def test_txt_treats_zero_as_a_real_value(self, base_value, new_value):
        """For TXT only "" is default, so "0" is genuine content."""
        store, addr_key = self.store_with("TXT", DataType.TXT, base_value)

        with store.edit_session("Edit") as session:
            session.set_field(addr_key, "initial_value", new_value)

        assert store.is_dirty(addr_key) is True
        assert store.is_field_dirty(addr_key, "initial_value") is True


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

    def test_edit_refreshes_cached_unified_view_before_notification(self, store):
        """A newly opened editor must see edits made before it registered."""
        addr_key = get_addr_key("C", 10)
        view = build_unified_view(store.visible_state)
        store.set_unified_view(view)

        with store.edit_session("AI: tag apply") as session:
            session.set_field(addr_key, "nickname", "Idle")

        row_idx = next(i for i, row in enumerate(view.rows) if row.addr_key == addr_key)
        assert view.rows[row_idx].nickname == "Idle"

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


class TestSystemNicknameValidation:
    """Regression tests for system nickname validation behavior."""

    def test_loaded_ordinary_x_nickname_is_not_marked_as_an_error(self):
        addr_key = get_addr_key("X", 1)
        data_source = MockDataSource(
            {
                addr_key: AddressRow(
                    memory_type="X",
                    address=1,
                    nickname="StartButton",
                )
            }
        )
        store = AddressStore(data_source)

        store.load_initial_data()

        row = store.visible_state[addr_key]
        assert row.loaded_with_error is False
        assert row.nickname_valid is True

    @pytest.mark.parametrize(
        ("memory_type", "nickname"),
        (
            ("SC", "Comm/Port_1"),
            ("SD", "_Fixed_Scan_Time(ms)"),
            ("X", "_IO1_Module_Error"),
        ),
    )
    def test_loaded_system_nickname_is_valid(self, memory_type, nickname):
        """System nicknames from DB should not be reported as invalid."""
        addr_key = get_addr_key(memory_type, 1)
        data_source = MockDataSource(
            {
                addr_key: AddressRow(
                    memory_type=memory_type,
                    address=1,
                    nickname=nickname,
                )
            }
        )
        store = AddressStore(data_source)
        store.load_initial_data()

        row = store.visible_state[addr_key]
        assert row.nickname_valid is True
        assert row.nickname_error == ""
        assert row.is_valid is True

    @pytest.mark.parametrize(
        ("memory_type", "nickname"),
        (
            ("SC", "Comm/Port_1"),
            ("SD", "_Fixed_Scan_Time(ms)"),
        ),
    )
    def test_user_entered_sc_sd_system_nickname_is_valid(self, store, memory_type, nickname):
        """SC/SD system-style nicknames should be accepted as edits."""
        addr_key = get_addr_key(memory_type, 1)
        with store.edit_session("Set SC/SD system nickname") as session:
            session.set_field(addr_key, "nickname", nickname)

        row = store.visible_state[addr_key]
        assert row.nickname_valid is True
        assert row.nickname_error == ""
        assert row.is_valid is True

    @pytest.mark.parametrize(
        ("memory_type", "base_nickname", "edited_nickname"),
        (
            ("SC", "Comm/Port_1", "Comm/Port_2"),
            ("SD", "_Fixed_Scan_Time(ms)", "_Scan_Time(ms)"),
        ),
    )
    def test_loaded_sc_sd_system_then_edited_is_valid(
        self, memory_type, base_nickname, edited_nickname
    ):
        """Edited SC/SD system nicknames retain their system-bank context."""
        addr_key = get_addr_key(memory_type, 1)
        data_source = MockDataSource(
            {
                addr_key: AddressRow(
                    memory_type=memory_type,
                    address=1,
                    nickname=base_nickname,
                )
            }
        )
        store = AddressStore(data_source)
        store.load_initial_data()

        with store.edit_session("Edit loaded SC/SD system nickname") as session:
            session.set_field(addr_key, "nickname", edited_nickname)

        row = store.visible_state[addr_key]
        assert row.nickname_valid is True
        assert row.nickname_error == ""
        assert row.is_valid is True

    def test_loaded_x_io_nickname_stays_valid(self):
        """Loaded X _IO nickname should be allowed as PLC-generated."""
        addr_key = get_addr_key("X", 1)
        data_source = MockDataSource(
            {
                addr_key: AddressRow(
                    memory_type="X",
                    address=1,
                    nickname="_IO1_Module_Error",
                )
            }
        )
        store = AddressStore(data_source)
        store.load_initial_data()

        row = store.visible_state[addr_key]
        assert row.nickname_valid is True
        assert row.nickname_error == ""
        assert row.is_valid is True

    def test_user_entered_x_io_nickname_is_invalid(self, store):
        """User-entered X _IO nickname should be rejected."""
        addr_key = get_addr_key("X", 1)
        with store.edit_session("Set X system nickname") as session:
            session.set_field(addr_key, "nickname", "_IO1_Module_Error")

        row = store.visible_state[addr_key]
        assert row.nickname_valid is False
        assert "Cannot start with _" in row.nickname_error
        assert row.is_valid is False

    def test_loaded_x_io_then_user_changes_nickname_is_invalid(self):
        """Changing loaded _IO nickname to another _IO value should be rejected."""
        addr_key = get_addr_key("X", 1)
        data_source = MockDataSource(
            {
                addr_key: AddressRow(
                    memory_type="X",
                    address=1,
                    nickname="_IO1_Module_Error",
                )
            }
        )
        store = AddressStore(data_source)
        store.load_initial_data()

        with store.edit_session("Change loaded _IO nickname") as session:
            session.set_field(addr_key, "nickname", "_IO2_Module_Error")

        row = store.visible_state[addr_key]
        assert row.nickname_valid is False
        assert "Cannot start with _" in row.nickname_error
        assert row.is_valid is False

    def test_user_edit_clears_loaded_error_mask_for_valid_system_nickname(self):
        """A valid SC edit should no longer need the loaded-error mask."""
        addr_key = get_addr_key("SC", 1)
        data_source = MockDataSource(
            {
                addr_key: AddressRow(
                    memory_type="SC",
                    address=1,
                    nickname="log",  # Reserved keyword
                )
            }
        )
        store = AddressStore(data_source)
        store.load_initial_data()

        loaded_row = store.visible_state[addr_key]
        assert loaded_row.loaded_with_error is True
        assert loaded_row.nickname_valid is True

        with store.edit_session("Edit invalid loaded nickname") as session:
            session.set_field(addr_key, "nickname", "_UserTyped")

        edited_row = store.visible_state[addr_key]
        assert edited_row.loaded_with_error is False
        assert edited_row.nickname_valid is True
        assert edited_row.nickname_error == ""


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
        )
        store_with_data._on_database_update()

        # Base should be updated
        assert store_with_data.base_state[addr_key].comment == "ExternallyUpdatedComment"
        # Visible should still have user's override
        assert store_with_data.visible_state[addr_key].comment == "UserComment"

        # Key assertion: row should be in notification so cell notes can update
        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_external_nickname_update_visible_when_user_only_edited_comment(self, store_with_data):
        """External nickname change must propagate even when user has a comment override."""
        from clicknick.models.address_row import AddressRow

        addr_key = get_addr_key("X", 1)

        # User edits only the comment
        with store_with_data.edit_session("Edit") as session:
            session.set_field(addr_key, "comment", "UserComment")

        assert store_with_data.visible_state[addr_key].nickname == "Input1"

        # CLICK writes a new nickname to the MDB
        store_with_data._data_source._initial_rows[addr_key] = AddressRow(
            memory_type="X",
            address=1,
            nickname="RenamedInput",
            comment="Button",
        )
        store_with_data._on_database_update()

        # Nickname should reflect the DB change (user didn't edit it)
        assert store_with_data.visible_state[addr_key].nickname == "RenamedInput"
        # Comment should still be the user's override
        assert store_with_data.visible_state[addr_key].comment == "UserComment"

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
        )
        store_with_data._on_database_update()

        # Both base and visible should be updated
        assert store_with_data.base_state[addr_key].comment == "ExternallyUpdatedComment"
        assert store_with_data.visible_state[addr_key].comment == "ExternallyUpdatedComment"

        # Should be notified
        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_external_update_resets_rows_deleted_from_database(self, store_with_data):
        """External row deletion should reset base/visible state and notify consumers."""
        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store_with_data.add_observer(observer)

        del store_with_data._data_source._initial_rows[addr_key]
        result = store_with_data._on_database_update()

        assert result is True
        assert store_with_data.base_state[addr_key].nickname == ""
        assert store_with_data.base_state[addr_key].comment == ""
        assert store_with_data.visible_state[addr_key].nickname == ""
        assert store_with_data.visible_state[addr_key].comment == ""
        assert "Input1" not in store_with_data.all_nicknames.values()
        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_external_update_preserves_override_when_database_row_deleted(self, store_with_data):
        """External row deletion updates base while preserving local user edits."""
        addr_key = get_addr_key("X", 1)
        notifications = []

        def observer(sender, affected_keys):
            notifications.append(affected_keys)

        store_with_data.add_observer(observer)

        with store_with_data.edit_session("Edit") as session:
            session.set_field(addr_key, "comment", "UserComment")

        notifications.clear()
        del store_with_data._data_source._initial_rows[addr_key]

        result = store_with_data._on_database_update()

        assert result is True
        assert store_with_data.base_state[addr_key].comment == ""
        assert store_with_data.visible_state[addr_key].comment == "UserComment"
        assert len(notifications) == 1
        assert addr_key in notifications[0]

    def test_external_update_returns_false_when_database_load_fails(self, store_with_data):
        """A failed reload should tell FileMonitor to retry the same mtime."""

        def fail_load():
            raise RuntimeError("database locked")

        store_with_data._data_source.load_all_addresses = fail_load

        assert store_with_data._on_database_update() is False


class TestDerivedStateStaysConsistent:
    """Derived state (validation, dirty, block colors) must match a fresh computation.

    Regression tests for bugs A-C from the 2026-10 state review, plus the
    Sync/Discard undo-history rules.
    """

    @pytest.fixture
    def named_store(self):
        """Store with two distinct C nicknames loaded from the database."""
        rows = {
            get_addr_key("C", 1): AddressRow(memory_type="C", address=1, nickname="Alpha"),
            get_addr_key("C", 2): AddressRow(memory_type="C", address=2, nickname="Beta"),
        }
        s = AddressStore(MockDataSource(rows))
        s.load_initial_data()
        return s

    @staticmethod
    def _rename(store, addr_key, nickname):
        with store.edit_session("Rename") as session:
            session.set_field(addr_key, "nickname", nickname)

    def test_duplicate_rename_flags_both_rows(self, named_store):
        c1, c2 = get_addr_key("C", 1), get_addr_key("C", 2)

        self._rename(named_store, c2, "Alpha")

        assert not named_store.visible_state[c1].is_valid
        assert not named_store.visible_state[c2].is_valid

    def test_undo_duplicate_rename_clears_partner_error(self, named_store):
        c1 = get_addr_key("C", 1)
        self._rename(named_store, get_addr_key("C", 2), "Alpha")

        named_store.undo()

        assert named_store.visible_state[c1].is_valid
        assert not named_store.has_errors()

    def test_discard_duplicate_rename_clears_partner_error(self, named_store):
        c1 = get_addr_key("C", 1)
        self._rename(named_store, get_addr_key("C", 2), "Alpha")

        named_store.discard_all_changes()

        assert named_store.visible_state[c1].is_valid
        assert not named_store.has_errors()

    def test_undo_back_into_duplicate_flags_partner(self, named_store):
        c1, c2 = get_addr_key("C", 1), get_addr_key("C", 2)
        self._rename(named_store, c2, "Alpha")
        self._rename(named_store, c2, "Gamma")
        assert named_store.visible_state[c1].is_valid

        named_store.undo()

        assert not named_store.visible_state[c1].is_valid
        assert not named_store.visible_state[c2].is_valid

    def test_sync_clears_undo_and_redo(self, named_store):
        c1, c2 = get_addr_key("C", 1), get_addr_key("C", 2)
        self._rename(named_store, c1, "AlphaNew")
        self._rename(named_store, c2, "BetaNew")
        named_store.undo()
        assert named_store.can_undo() and named_store.can_redo()

        named_store.save_all_changes()

        assert not named_store.can_undo()
        assert not named_store.can_redo()
        assert not named_store.undo()
        assert not named_store.has_unsaved_changes()

    def test_failed_sync_keeps_undo_history(self, named_store):
        self._rename(named_store, get_addr_key("C", 1), "AlphaNew")

        def fail_save(rows):
            raise RuntimeError("database locked")

        named_store._data_source.save_changes = fail_save
        with pytest.raises(RuntimeError):
            named_store.save_all_changes()

        assert named_store.can_undo()
        assert named_store.has_unsaved_changes()

    def test_external_save_keeps_undo_history(self, named_store):
        c1 = get_addr_key("C", 1)
        self._rename(named_store, c1, "AlphaNew")

        named_store._data_source._initial_rows[c1] = AddressRow(
            memory_type="C", address=1, nickname="AlphaFromClick"
        )
        named_store._on_database_update()

        assert named_store.can_undo()
        assert named_store.visible_state[c1].nickname == "AlphaNew"
        assert named_store.is_dirty(c1)

    def test_undo_to_value_click_already_has_is_not_dirty(self, named_store):
        c1 = get_addr_key("C", 1)
        self._rename(named_store, c1, "First")
        self._rename(named_store, c1, "Second")

        # CLICK saves "First", then the user undoes back to "First".
        named_store._data_source._initial_rows[c1] = AddressRow(
            memory_type="C", address=1, nickname="First"
        )
        named_store._on_database_update()
        named_store.undo()

        assert named_store.visible_state[c1].nickname == "First"
        assert not named_store.is_dirty(c1)
        assert not named_store.has_unsaved_changes()

    def test_external_write_of_typed_value_clears_dirty(self, named_store):
        c1 = get_addr_key("C", 1)
        self._rename(named_store, c1, "Typed")
        assert named_store.is_dirty(c1)

        # CLICK saves the same value the user typed.
        named_store._data_source._initial_rows[c1] = AddressRow(
            memory_type="C", address=1, nickname="Typed"
        )
        named_store._on_database_update()

        assert not named_store.is_field_dirty(c1, "nickname")
        assert not named_store.is_dirty(c1)
        assert not named_store.has_unsaved_changes()
        assert named_store.get_dirty_keys() == set()

    def test_discard_clears_undo_and_redo(self, named_store):
        c1 = get_addr_key("C", 1)
        self._rename(named_store, c1, "First")
        self._rename(named_store, c1, "Second")
        named_store.undo()
        assert named_store.can_undo() and named_store.can_redo()

        named_store.discard_all_changes()

        assert not named_store.can_undo()
        assert not named_store.can_redo()
        assert named_store.visible_state[c1].nickname == "Alpha"

    def test_block_colors_after_edit_match_first_load(self):
        """Interleaved T/TD blocks color only their own type, before and after edits."""
        t1, t3 = get_addr_key("T", 1), get_addr_key("T", 3)
        rows = {
            t1: AddressRow(memory_type="T", address=1, comment="<Pumps bg='Red'>"),
            t3: AddressRow(memory_type="T", address=3, comment="</Pumps>"),
        }
        s = AddressStore(MockDataSource(rows))
        s.load_initial_data()
        s.set_unified_view(build_unified_view(s.visible_state))
        at_load = dict(s.block_colors)
        assert at_load.get(t1) == "Red"
        assert get_addr_key("TD", 1) not in at_load

        with s.edit_session("Unrelated comment") as session:
            session.set_field(get_addr_key("C", 1), "comment", "note")

        assert s.block_colors == at_load

    @staticmethod
    def _fresh_comment_validity(store):
        """Comment validity a freshly loaded store computes for the same content."""
        rows = {
            key: AddressRow(memory_type=row.memory_type, address=row.address, comment=row.comment)
            for key, row in store.visible_state.items()
            if row.comment
        }
        fresh = AddressStore(MockDataSource(rows))
        fresh.load_initial_data()
        return {key: fresh.visible_state[key].comment_valid for key in rows}

    def test_duplicate_block_name_first_definition_wins(self):
        c1, c3, c10 = get_addr_key("C", 1), get_addr_key("C", 3), get_addr_key("C", 10)
        rows = {
            c1: AddressRow(memory_type="C", address=1, comment="<Pumps>"),
            c3: AddressRow(memory_type="C", address=3, comment="</Pumps>"),
        }
        s = AddressStore(MockDataSource(rows))
        s.load_initial_data()
        s.set_unified_view(build_unified_view(s.visible_state))

        def comment_validity():
            return {key: s.visible_state[key].comment_valid for key in (c1, c3, c10)}

        with s.edit_session("Duplicate block") as session:
            session.set_field(c10, "comment", "<Pumps />")

        assert comment_validity() == {c1: True, c3: True, c10: False}
        assert self._fresh_comment_validity(s) == {c1: True, c3: True, c10: False}

        # Removing the first definition makes the later one the valid one.
        with s.edit_session("Remove first block") as session:
            session.set_field(c1, "comment", "")
            session.set_field(c3, "comment", "")

        assert s.visible_state[c10].comment_valid
        assert not s.has_errors()

        s.undo()
        assert comment_validity() == {c1: True, c3: True, c10: False}

        s.undo()
        assert comment_validity() == {c1: True, c3: True, c10: True}
        assert not s.has_errors()

    def test_reload_after_sync_changes_nothing(self, named_store):
        """The file monitor reloads after our own Sync; that must be a no-op."""
        c1 = get_addr_key("C", 1)
        source = named_store._data_source

        def save_changes(rows):
            for row in rows:
                source._initial_rows[row.addr_key] = row
            return len(rows)

        source.save_changes = save_changes
        self._rename(named_store, c1, "AlphaSaved")
        named_store.save_all_changes()
        before = dict(named_store.visible_state)
        notified = []
        named_store.add_observer(lambda _store, keys: notified.append(keys))

        assert named_store._on_database_update()

        assert notified == []
        assert named_store.visible_state[c1].nickname == "AlphaSaved"
        assert not named_store.has_unsaved_changes()
        assert named_store.visible_state == before
