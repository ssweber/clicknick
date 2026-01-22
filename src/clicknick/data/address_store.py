"""Address store with base/overlay architecture and undo/redo support.

The store maintains three layers:
- base_state: Latest snapshot from the database (the truth)
- user_overrides: Sparse dict of user modifications (the intent)
- visible_state: Computed projection of base + overrides (the view)

Key behaviors:
- Undo/Redo tracks only the overlay layer (user intent)
- External DB updates preserve user edits automatically
- Immutable rows eliminate complex locking logic
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING

from ..models.address_row import AddressRow, get_addr_key, is_xd_yd_hidden_slot
from ..models.blocktag import parse_block_tag
from ..models.constants import (
    ADDRESS_RANGES,
    DEFAULT_RETENTIVE,
    INTERLEAVED_PAIRS,
    MEMORY_TYPE_TO_DATA_TYPE,
    DataType,
)
from ..models.validation import validate_initial_value, validate_nickname
from ..services.block_service import BlockService, compute_all_block_ranges
from ..services.nickname_index_service import NicknameIndexService
from .data_source import DataSource
from .edit_session_new import EditSession
from .file_monitor import FileMonitor
from .undo_frame import MAX_UNDO_DEPTH, UndoFrame

if TYPE_CHECKING:
    from ..views.address_editor.view_builder import UnifiedView


class AddressStore:
    """Central data store with base/overlay architecture.

    Manages all address data with support for:
    - Undo/Redo (Ctrl+Z/Y) with configurable depth
    - External database updates that preserve user edits
    - Efficient dirty detection via reference equality
    - Observer pattern for view updates

    Usage:
        store = AddressStore(data_source)
        store.load_initial_data()

        # Edit with undo support
        with store.edit_session("Update nickname") as session:
            session.set_field(addr_key, "nickname", "NewName")

        # Undo/Redo
        store.undo()
        store.redo()
    """

    def __init__(self, data_source: DataSource):
        """Initialize the address store.

        Args:
            data_source: DataSource implementation for loading/saving data
        """
        self._data_source = data_source

        # The three layers
        self.base_state: dict[int, AddressRow] = {}
        self.user_overrides: dict[int, AddressRow] = {}
        self.visible_state: dict[int, AddressRow] = {}

        # Display order (addr_keys in the order they should appear)
        self.row_order: list[int] = []

        # Undo/Redo stacks
        self.undo_stack: list[UndoFrame] = []
        self.redo_stack: list[UndoFrame] = []

        # Nickname index service for O(1) lookups
        self._nickname_service = NicknameIndexService()

        # Observer callbacks - called with set of affected addr_keys
        self._observers: list[Callable[[object, set[int] | None], None]] = []

        # Track registered windows for close operations
        self._windows: list = []

        # Track if initial data has been loaded
        self._initialized = False

        # File monitoring
        self._file_monitor: FileMonitor | None = None

        # Cached unified view
        self._unified_view: UnifiedView | None = None

        # Rows by type cache (for compatibility)
        self.rows_by_type: dict[str, list[AddressRow]] = {}

        # Current edit session (for nested check)
        self._current_session: EditSession | None = None

        # Block colors (separate from AddressRow to avoid row recreation)
        self.block_colors: dict[int, str] = {}  # addr_key -> color_name

    @property
    def supports_used_field(self) -> bool:
        """Check if the data source supports the 'Used' field."""
        return self._data_source.supports_used_field

    # --- Skeleton Creation ---

    def _create_base_skeleton(self) -> dict[int, AddressRow]:
        """Create base skeleton of all possible AddressRow objects.

        Creates one immutable AddressRow per valid address slot.
        These form the initial base_state before database hydration.

        Returns:
            Dict mapping addr_key to skeleton AddressRow objects
        """
        skeleton: dict[int, AddressRow] = {}

        for mem_type, (start, end) in ADDRESS_RANGES.items():
            default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, DataType.BIT)
            default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)

            for addr in range(start, end + 1):
                # Skip hidden XD/YD slots
                if is_xd_yd_hidden_slot(mem_type, addr):
                    continue

                addr_key = get_addr_key(mem_type, addr)
                row = AddressRow(
                    memory_type=mem_type,
                    address=addr,
                    data_type=default_data_type,
                    retentive=default_retentive,
                )
                skeleton[addr_key] = row
                self.row_order.append(addr_key)

        return skeleton

    def _mark_loaded_with_errors(self) -> None:
        """Mark X/SC/SD rows that loaded with invalid nicknames."""
        all_nicks = self.all_nicknames
        for addr_key, row in self.visible_state.items():
            if row.memory_type in ("X", "SC", "SD") and row.nickname:
                is_valid, _ = validate_nickname(row.nickname, all_nicks, addr_key)
                if not is_valid:
                    # Update both base and visible
                    updated = replace(row, loaded_with_error=True)
                    self.base_state[addr_key] = updated
                    self.visible_state[addr_key] = updated

    def _validate_row(self, addr_key: int, all_nicknames: dict[int, str] | None = None) -> None:
        """Validate a single row and update its validation state."""
        if all_nicknames is None:
            all_nicknames = self.all_nicknames

        row = self.visible_state.get(addr_key)
        if not row:
            return

        is_valid, error = validate_nickname(
            row.nickname, all_nicknames, addr_key, self.is_duplicate_nickname
        )
        init_valid, init_error = validate_initial_value(row.initial_value, row.data_type)

        # Combine validation results
        if not init_valid and is_valid:
            is_valid = False
            error = init_error

        # Only update if validation state changed
        if row.is_valid != is_valid or row.validation_error != error:
            updated = replace(
                row,
                is_valid=is_valid,
                validation_error=error,
                initial_value_valid=init_valid,
                initial_value_error=init_error,
            )
            self.visible_state[addr_key] = updated
            if addr_key in self.user_overrides:
                self.user_overrides[addr_key] = updated

    def _validate_all_rows(self) -> None:
        """Validate all rows and update validation state."""
        all_nicks = self.all_nicknames
        for addr_key in self.visible_state:
            self._validate_row(addr_key, all_nicks)

    def _validate_affected_rows(self, affected: set[int], nickname_changes: dict[int, str]) -> None:
        """Validate rows affected by changes."""
        # Collect all nicknames involved for duplicate detection cascade
        nicknames_to_check: set[str] = set()

        for addr_key, old_nickname in nickname_changes.items():
            if old_nickname:
                nicknames_to_check.add(old_nickname.lower())
            if addr_key in self.visible_state:
                new_nick = self.visible_state[addr_key].nickname
                if new_nick:
                    nicknames_to_check.add(new_nick.lower())

        # Find all rows with these nicknames
        keys_to_validate = affected.copy()
        for nickname in nicknames_to_check:
            keys_to_validate.update(self._nickname_service.get_addr_keys_insensitive(nickname))

        # Validate
        all_nicks = self.all_nicknames
        for addr_key in keys_to_validate:
            self._validate_row(addr_key, all_nicks)

    # --- Nickname Index ---

    def _rebuild_nickname_index(self) -> None:
        """Rebuild the nickname reverse index."""
        self._nickname_service.rebuild_index(self.visible_state.values())

    def _notify_observers(self, affected_keys: set[int] | None = None) -> None:
        """Notify all observers of data changes."""
        for callback in self._observers:
            try:
                callback(self, affected_keys)
            except Exception:
                pass  # Don't let one observer's error break others

    def _on_database_update(self) -> None:
        """Handle external database changes."""
        try:
            new_rows = self._data_source.load_all_addresses()
        except Exception:
            return

        affected_keys: set[int] = set()

        for addr_key, new_row in new_rows.items():
            old_base = self.base_state.get(addr_key)

            # Update base layer
            if old_base:
                updated_base = replace(
                    old_base,
                    nickname=new_row.nickname,
                    comment=new_row.comment,
                    used=new_row.used,
                    data_type=new_row.data_type,
                    initial_value=new_row.initial_value,
                    retentive=new_row.retentive,
                )

                # Check if base changed for rows with overrides
                # (need to notify so cell notes update even if visible doesn't change)
                base_changed = updated_base != old_base
                self.base_state[addr_key] = updated_base

                # Recompute visible
                if addr_key in self.user_overrides:
                    # User has edits: merge with override
                    override = self.user_overrides[addr_key]
                    new_visible = replace(
                        updated_base,
                        nickname=override.nickname,
                        comment=override.comment,
                        initial_value=override.initial_value,
                        retentive=override.retentive,
                    )
                    # If base changed for a row with override, notify so cell notes update
                    if base_changed:
                        affected_keys.add(addr_key)
                else:
                    new_visible = updated_base

                old_visible = self.visible_state.get(addr_key)
                if new_visible != old_visible:
                    self.visible_state[addr_key] = new_visible
                    affected_keys.add(addr_key)

        if affected_keys:
            self._rebuild_nickname_index()
            self._validate_affected_rows(affected_keys, {})
            self._notify_observers(affected_keys)

    # --- Data Loading ---

    def load_initial_data(self) -> None:
        """Load all address data from data source.

        Creates base skeleton, then hydrates with database values.
        """
        # Create base skeleton
        self.base_state = self._create_base_skeleton()

        # visible_state starts as copy of base_state references
        self.visible_state = dict(self.base_state)

        # Load from data source
        db_rows = self._data_source.load_all_addresses()

        # Hydrate base_state with loaded data
        for addr_key, db_row in db_rows.items():
            if addr_key in self.base_state:
                # Create new immutable row with DB values
                base = self.base_state[addr_key]
                hydrated = replace(
                    base,
                    nickname=db_row.nickname,
                    comment=db_row.comment,
                    used=db_row.used,
                    data_type=db_row.data_type,
                    initial_value=db_row.initial_value,
                    retentive=db_row.retentive,
                    loaded_with_error=db_row.loaded_with_error,
                )
                self.base_state[addr_key] = hydrated
                self.visible_state[addr_key] = hydrated

        # Rebuild nickname index
        self._rebuild_nickname_index()

        # Mark X/SC/SD rows with invalid nicknames
        self._mark_loaded_with_errors()

        # Validate all rows
        self._validate_all_rows()

        self._initialized = True

        # Create file monitor
        self._file_monitor = FileMonitor(
            file_path=self._data_source.file_path,
            on_modified=self._on_database_update,
        )

    def _apply_cascades(self, session: EditSession) -> None:
        """Apply automatic syncs (T/TD, block tags) to pending changes."""

        def _sync_interleaved_pair(src_row: AddressRow, comment: str) -> None:
            """Sync comment to the interleaved pair (e.g. T -> TD)."""
            if src_row.memory_type not in INTERLEAVED_PAIRS:
                return

            paired_type = INTERLEAVED_PAIRS[src_row.memory_type]
            paired_key = get_addr_key(paired_type, src_row.address)

            # Only sync if the pair hasn't been modified in this session
            if paired_key in session.pending:
                return

            paired_row = self.visible_state.get(paired_key)
            if paired_row:
                synced = BlockService.apply_block_tag(comment, paired_row.comment)
                if synced is not None:
                    session.get_builder(paired_key).comment = synced

        # Process snapshot of pending keys (cascades may add new keys to pending)
        pending_keys = list(session.pending.keys())

        for addr_key in pending_keys:
            builder = session.pending[addr_key]
            row = self.visible_state.get(addr_key)
            if not row:
                continue

            # 1. Retentive sync for T/TD pairs
            if row.memory_type in INTERLEAVED_PAIRS and builder.retentive is not None:
                paired_type = INTERLEAVED_PAIRS[row.memory_type]
                paired_key = get_addr_key(paired_type, row.address)

                if paired_key not in session.pending:
                    session.get_builder(paired_key).retentive = builder.retentive

            # 2. Comment cascades (Block tags and T/TD sync)
            if builder.comment is not None:
                new_comment = builder.comment

                # Check for vertical block tag updates (Start/End tag consistency)
                old_comment = session.comment_old_values.get(addr_key, row.comment)
                old_tag = parse_block_tag(old_comment)
                new_tag = parse_block_tag(new_comment)

                if old_tag.name or new_tag.name:
                    # Get unified view for searching paired tags
                    view = self.get_unified_view()
                    if view:
                        key_to_idx = {r.addr_key: i for i, r in enumerate(view.rows)}
                        row_idx = key_to_idx.get(addr_key)

                        if row_idx is not None:
                            result = BlockService.auto_update_matching_block_tag(
                                view.rows, row_idx, old_tag, new_tag
                            )
                            if result:
                                match_idx, match_comment = result
                                match_row = view.rows[match_idx]

                                # Update the vertical match (the closing tag)
                                session.get_builder(match_row.addr_key).comment = match_comment

                                # Sync the vertical match to *its* interleaved pair
                                _sync_interleaved_pair(match_row, match_comment)

                # Sync the current row to its interleaved pair
                _sync_interleaved_pair(row, new_comment)

    def _freeze_session(self, session: EditSession) -> set[int]:
        """Freeze session builders into user_overrides.

        Returns:
            Set of affected addr_keys
        """
        affected = set()

        for addr_key, builder in session.pending.items():
            if not builder.has_changes():
                continue

            # Get current visible row as base for freeze
            base = self.visible_state.get(addr_key)
            if not base:
                continue

            # Freeze builder into new immutable row
            new_row = builder.freeze(base)
            self.user_overrides[addr_key] = new_row
            affected.add(addr_key)

        return affected

    def _recompute_visible(self, affected_keys: set[int]) -> None:
        """Recompute visible_state for affected keys."""
        for addr_key in affected_keys:
            if addr_key in self.user_overrides:
                # User has edits: visible = base merged with override
                base = self.base_state.get(addr_key)
                override = self.user_overrides[addr_key]
                if base:
                    # Merge: take user-editable fields from override, rest from base
                    self.visible_state[addr_key] = replace(
                        base,
                        nickname=override.nickname,
                        comment=override.comment,
                        initial_value=override.initial_value,
                        retentive=override.retentive,
                        is_valid=override.is_valid,
                        validation_error=override.validation_error,
                        initial_value_valid=override.initial_value_valid,
                        initial_value_error=override.initial_value_error,
                    )
                else:
                    self.visible_state[addr_key] = override
            else:
                # No user edits: visible = base
                if addr_key in self.base_state:
                    self.visible_state[addr_key] = self.base_state[addr_key]

    def _update_nickname_index(self, nickname_changes: dict[int, str]) -> None:
        """Update nickname reverse index after changes."""
        for addr_key, old_nickname in nickname_changes.items():
            new_nickname = (
                self.visible_state[addr_key].nickname if addr_key in self.visible_state else ""
            )
            if old_nickname != new_nickname:
                self._nickname_service.update(addr_key, old_nickname, new_nickname)

    def _update_block_colors(self, affected: set[int], comment_changes: dict[int, str]) -> set[int]:
        """Update block colors if comments changed.

        Returns:
            Updated set of affected keys (may be larger due to block ranges)
        """
        if not comment_changes:
            return affected

        view = self.get_unified_view()
        if not view:
            return affected

        # Refresh unified view rows from visible_state
        # (immutable architecture creates new row objects on edit, so view.rows becomes stale)
        for idx, row in enumerate(view.rows):
            current = self.visible_state.get(row.addr_key)
            if current is not None and current is not row:
                view.rows[idx] = current

        # Compute all block ranges
        ranges = compute_all_block_ranges(view.rows)

        # Build row_idx -> color map
        color_map: dict[int, str | None] = {}
        for r in ranges:
            if r.bg_color:
                for row_idx in range(r.start_idx, r.end_idx + 1):
                    color_map[row_idx] = r.bg_color

        # Update block_colors dict
        all_affected = set(affected)
        for row_idx, row in enumerate(view.rows):
            new_color = color_map.get(row_idx)
            old_color = self.block_colors.get(row.addr_key)
            if old_color != new_color:
                if new_color:
                    self.block_colors[row.addr_key] = new_color
                else:
                    self.block_colors.pop(row.addr_key, None)
                all_affected.add(row.addr_key)

        return all_affected

    def _commit_session(self, session: EditSession, description: str) -> None:
        """Commit pending changes from an edit session.

        This method handles all the steps to finalize an edit session:
        1. Push undo frame (before changes)
        2. Apply cascades (T/TD sync, block tags)
        3. Freeze builders into user_overrides
        4. Recompute visible_state
        5. Update nickname index
        6. Validate affected rows
        7. Update block colors
        8. Notify observers
        """
        # 1. Push undo frame BEFORE making changes
        self.undo_stack.append(
            UndoFrame(
                overrides=dict(self.user_overrides),
                description=description,
            )
        )
        # Limit undo stack depth
        while len(self.undo_stack) > MAX_UNDO_DEPTH:
            self.undo_stack.pop(0)

        # Clear redo stack (new edit invalidates redo history)
        self.redo_stack.clear()

        # 2. Apply cascades (T/TD sync, block tag sync)
        self._apply_cascades(session)

        # 3. Freeze builders into user_overrides
        affected_keys = self._freeze_session(session)

        # 4. Recompute visible_state for affected keys
        self._recompute_visible(affected_keys)

        # 5. Update nickname index
        self._update_nickname_index(session.nickname_old_values)

        # 6. Validate affected rows
        self._validate_affected_rows(affected_keys, session.nickname_old_values)

        # 7. Update block colors
        affected_keys = self._update_block_colors(affected_keys, session.comment_old_values)

        # 8. Notify observers
        self._notify_observers(affected_keys)

    # --- Edit Session ---

    @contextmanager
    def edit_session(self, description: str = "") -> Generator[EditSession, None, None]:
        """Context manager for making changes with undo support.

        All modifications should happen within an edit_session. On exit:
        1. Pushes undo frame (before changes)
        2. Applies cascades (T/TD sync, block tags)
        3. Freezes builders into user_overrides
        4. Recomputes visible_state
        5. Validates affected rows
        6. Updates block colors
        7. Notifies observers

        Args:
            description: Human-readable description for undo menu

        Yields:
            EditSession for accumulating changes
        """
        if self._current_session is not None:
            raise RuntimeError("Cannot nest edit_session calls")

        session = EditSession(self, description)
        self._current_session = session

        try:
            yield session
        finally:
            self._current_session = None

            if session.has_pending_changes():
                self._commit_session(session, description)

    def _recompute_all_block_colors(self, affected: set[int]) -> set[int]:
        """Recompute block colors for entire unified view.

        Used after discard/undo to ensure all block colors are correct.

        Returns:
            Updated set of affected keys
        """
        view = self.get_unified_view()
        if not view:
            return affected

        # Refresh view rows from visible_state first
        for idx, row in enumerate(view.rows):
            current = self.visible_state.get(row.addr_key)
            if current is not None and current is not row:
                view.rows[idx] = current

        # Compute all block ranges from current state
        ranges = compute_all_block_ranges(view.rows)

        # Build row_idx -> color map
        color_map: dict[int, str | None] = {}
        for r in ranges:
            if r.bg_color:
                for row_idx in range(r.start_idx, r.end_idx + 1):
                    color_map[row_idx] = r.bg_color

        # Update block_colors dict
        all_affected = set(affected)
        for row_idx, row in enumerate(view.rows):
            new_color = color_map.get(row_idx)
            old_color = self.block_colors.get(row.addr_key)
            if old_color != new_color:
                if new_color:
                    self.block_colors[row.addr_key] = new_color
                else:
                    self.block_colors.pop(row.addr_key, None)
                all_affected.add(row.addr_key)

        return all_affected

    # --- Undo/Redo ---

    def undo(self) -> bool:
        """Restore previous override state.

        Returns:
            True if undo was performed
        """
        if not self.undo_stack:
            return False

        # Save current state to redo
        self.redo_stack.append(
            UndoFrame(
                overrides=dict(self.user_overrides),
                description="",
            )
        )

        # Restore previous state
        frame = self.undo_stack.pop()
        old_overrides = self.user_overrides
        self.user_overrides = frame.overrides

        # Find all keys that changed
        affected_keys = set(old_overrides.keys()) | set(self.user_overrides.keys())

        # Recompute visible for affected keys
        self._recompute_visible(affected_keys)

        # Re-validate
        self._validate_affected_rows(affected_keys, {})

        # Rebuild nickname index
        self._rebuild_nickname_index()

        # Recompute block colors (undo may have added/removed block tags)
        affected_keys = self._recompute_all_block_colors(affected_keys)

        # Notify
        self._notify_observers(affected_keys)
        return True

    def redo(self) -> bool:
        """Re-apply undone changes.

        Returns:
            True if redo was performed
        """
        if not self.redo_stack:
            return False

        # Save current to undo
        self.undo_stack.append(
            UndoFrame(
                overrides=dict(self.user_overrides),
                description="",
            )
        )

        # Restore redo state
        frame = self.redo_stack.pop()
        old_overrides = self.user_overrides
        self.user_overrides = frame.overrides

        affected_keys = set(old_overrides.keys()) | set(self.user_overrides.keys())
        self._recompute_visible(affected_keys)
        self._validate_affected_rows(affected_keys, {})
        self._rebuild_nickname_index()

        # Recompute block colors (redo may have added/removed block tags)
        affected_keys = self._recompute_all_block_colors(affected_keys)

        self._notify_observers(affected_keys)
        return True

    def get_undo_description(self) -> str | None:
        """Get description of next undo action."""
        if self.undo_stack:
            return self.undo_stack[-1].description
        return None

    def get_redo_description(self) -> str | None:
        """Get description of next redo action."""
        if self.redo_stack:
            return self.redo_stack[-1].description
        return None

    def can_undo(self) -> bool:
        """Check if undo is available."""
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        """Check if redo is available."""
        return len(self.redo_stack) > 0

    # --- Block Color Access ---

    def get_block_color(self, addr_key: int) -> str | None:
        """Get block color for an address.

        Args:
            addr_key: The address key

        Returns:
            Color name (e.g., 'Red', 'Blue') or None if no color
        """
        return self.block_colors.get(addr_key)

    # --- Dirty State Queries ---

    def is_dirty(self, addr_key: int) -> bool:
        """Check if a row has user modifications."""
        return addr_key in self.user_overrides

    def is_field_dirty(self, addr_key: int, field: str) -> bool:
        """Check if a specific field differs from base."""
        if addr_key not in self.user_overrides:
            return False
        visible = self.visible_state.get(addr_key)
        base = self.base_state.get(addr_key)
        if not visible or not base:
            return False
        return getattr(visible, field) != getattr(base, field)

    def get_dirty_keys(self) -> set[int]:
        """Get all keys with user modifications."""
        return set(self.user_overrides.keys())

    def has_unsaved_changes(self) -> bool:
        """Check if there are any unsaved changes."""
        return len(self.user_overrides) > 0

    def has_errors(self) -> bool:
        """Check if any visible rows have validation errors."""
        return any(
            not row.is_valid and row.nickname and not row.should_ignore_validation_error
            for row in self.visible_state.values()
        )

    # --- Row Access ---

    def get_visible_row(self, addr_key: int) -> AddressRow | None:
        """Get visible row by addr_key."""
        return self.visible_state.get(addr_key)

    def get_base_row(self, addr_key: int) -> AddressRow | None:
        """Get base row by addr_key."""
        return self.base_state.get(addr_key)

    @property
    def all_rows(self) -> dict[int, AddressRow]:
        """Get all visible rows (for compatibility)."""
        return self.visible_state

    @property
    def all_nicknames(self) -> dict[int, str]:
        """Get dict mapping addr_key to nickname."""
        return {
            addr_key: row.nickname for addr_key, row in self.visible_state.items() if row.nickname
        }

    def get_addr_keys_for_nickname(self, nickname: str) -> set[int]:
        """Get addr_keys with exact nickname match."""
        return self._nickname_service.get_addr_keys(nickname)

    def get_addr_keys_for_nickname_insensitive(self, nickname: str) -> set[int]:
        """Get addr_keys with case-insensitive nickname match."""
        return self._nickname_service.get_addr_keys_insensitive(nickname)

    def is_duplicate_nickname(self, nickname: str, exclude_addr_key: int) -> bool:
        """Check if nickname is used by another address."""
        return self._nickname_service.is_duplicate(nickname, exclude_addr_key)

    def update_nickname(self, addr_key: int, old_nickname: str, new_nickname: str) -> None:
        """Update nickname in the index."""
        self._nickname_service.update(addr_key, old_nickname, new_nickname)

    def validate_affected_rows(self, old_nickname: str, new_nickname: str) -> set[int]:
        """Validate rows affected by a nickname change."""
        affected_keys: set[int] = set()

        if old_nickname:
            affected_keys.update(self.get_addr_keys_for_nickname_insensitive(old_nickname))
        if new_nickname:
            affected_keys.update(self.get_addr_keys_for_nickname_insensitive(new_nickname))

        all_nicks = self.all_nicknames
        for addr_key in affected_keys:
            self._validate_row(addr_key, all_nicks)

        return affected_keys

    # --- Observers ---

    def add_observer(self, callback: Callable[[object, set[int] | None], None]) -> None:
        """Add observer callback."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[object, set[int] | None], None]) -> None:
        """Remove observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    # --- Window Management ---

    def register_window(self, window) -> None:
        """Register an editor window."""
        if window not in self._windows:
            self._windows.append(window)

    def unregister_window(self, window) -> None:
        """Unregister an editor window."""
        if window in self._windows:
            self._windows.remove(window)

    def close_all_windows(self, prompt_save: bool = True) -> bool:
        """Close all registered editor windows."""
        if prompt_save and self.has_unsaved_changes():
            from tkinter import messagebox

            parent = self._windows[0] if self._windows else None
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=parent,
            )
            if result is None:
                return False
            if result:
                try:
                    self.save_all_changes()
                except Exception:
                    messagebox.showerror(
                        "Save Error",
                        "Failed to save changes. Windows will remain open.",
                        parent=parent,
                    )
                    return False

        self.stop_file_monitoring()

        for window in self._windows[:]:
            try:
                window.destroy()
            except Exception:
                pass

        self._windows.clear()
        return True

    def force_close_all_windows(self) -> None:
        """Force close all windows without saving."""
        self.stop_file_monitoring()

        for window in self._windows[:]:
            try:
                window.destroy()
            except Exception:
                pass

        self._windows.clear()

    # --- File Monitoring ---

    def start_file_monitoring(self, tk_root) -> None:
        """Start monitoring the database file."""
        if self._file_monitor:
            self._file_monitor.start(tk_root)

    def stop_file_monitoring(self) -> None:
        """Stop file monitoring."""
        if self._file_monitor:
            self._file_monitor.stop()

    # --- Unified View ---

    def get_unified_view(self) -> UnifiedView | None:
        """Get the cached unified view."""
        return self._unified_view

    def _apply_initial_block_colors(self, view: UnifiedView) -> None:
        """Apply block colors from unified view to block_colors dict.

        Called once when unified view is first created to set initial colors.
        """
        if not view.block_colors:
            return

        for row_idx, color in view.block_colors.items():
            if row_idx < len(view.rows):
                row = view.rows[row_idx]
                if color:
                    self.block_colors[row.addr_key] = color

    def set_unified_view(self, view: UnifiedView) -> None:
        """Store the unified view and apply initial block colors."""
        self._unified_view = view
        # Apply block colors computed during view building to visible_state
        self._apply_initial_block_colors(view)

    def get_rows(self, memory_type: str) -> list[AddressRow] | None:
        """Get rows for a memory type (compatibility)."""
        return self.rows_by_type.get(memory_type)

    def set_rows(self, memory_type: str, rows: list[AddressRow]) -> None:
        """Store rows for a memory type (compatibility)."""
        self.rows_by_type[memory_type] = rows

    # --- Save/Discard ---

    def save_all_changes(self) -> int:
        """Save changes to data source.

        Returns:
            Number of changes saved
        """
        if self._data_source.is_read_only:
            raise RuntimeError("Data source is read-only")

        if not self.user_overrides:
            return 0

        # Get dirty visible rows
        dirty_rows = [self.visible_state[key] for key in self.user_overrides]

        # Save - for MDB pass only dirty rows, for CSV pass all (it rewrites entire file)
        if self._data_source.supports_used_field:
            # MDB: save only dirty rows
            count = self._data_source.save_changes(dirty_rows)
        else:
            # CSV: needs all rows with content (rewrites entire file)
            count = self._data_source.save_changes(list(self.visible_state.values()))

        # After save: base_state = visible_state for saved rows
        for key in list(self.user_overrides.keys()):
            self.base_state[key] = self.visible_state[key]

        # Clear overrides
        affected_keys = set(self.user_overrides.keys())
        self.user_overrides.clear()

        # Update file monitor
        if self._file_monitor:
            self._file_monitor.update_mtime()

        # Notify observers
        self._notify_observers(affected_keys)

        return count

    def discard_all_changes(self) -> None:
        """Discard all unsaved changes."""
        if not self.user_overrides:
            return

        affected_keys = set(self.user_overrides.keys())

        # Clear overrides
        self.user_overrides.clear()

        # Recompute visible (now equals base)
        self._recompute_visible(affected_keys)

        # Rebuild index and validate
        self._rebuild_nickname_index()
        self._validate_affected_rows(affected_keys, {})

        # Recompute all block colors (discarding may have removed block tags)
        affected_keys = self._recompute_all_block_colors(affected_keys)

        # Notify
        self._notify_observers(affected_keys)

    # --- Statistics ---

    def is_initialized(self) -> bool:
        """Check if initial data has been loaded."""
        return self._initialized

    def get_total_modified_count(self) -> int:
        """Get total count of modified rows."""
        return len(self.user_overrides)

    def get_total_error_count(self) -> int:
        """Get total count of rows with errors."""
        return sum(
            1
            for row in self.visible_state.values()
            if not row.is_valid and row.nickname and not row.should_ignore_validation_error
        )

    def get_modified_count_for_type(self, memory_type: str) -> int:
        """Get count of modified rows for a memory type."""
        return sum(
            1 for key in self.user_overrides if self.visible_state[key].memory_type == memory_type
        )

    def get_error_count_for_type(self, memory_type: str) -> int:
        """Get count of rows with errors for a memory type."""
        return sum(
            1
            for row in self.visible_state.values()
            if row.memory_type == memory_type
            and not row.is_valid
            and row.nickname
            and not row.should_ignore_validation_error
        )

    # --- Block Addresses (compatibility) ---

    def get_block_addresses(
        self, memory_type: str
    ) -> list[tuple[int, int | None, str, str | None]]:
        """Get block definitions for a memory type."""
        unified_rows = self.rows_by_type.get("unified", [])
        rows = [r for r in unified_rows if r.memory_type == memory_type]
        if not rows:
            return []

        ranges = compute_all_block_ranges(rows)

        blocks: list[tuple[int, int | None, str, str | None]] = []
        for block in ranges:
            start_addr = rows[block.start_idx].address
            if block.start_idx == block.end_idx:
                end_addr = None
            else:
                end_addr = rows[block.end_idx].address
            blocks.append((start_addr, end_addr, block.name, block.bg_color))

        return sorted(blocks, key=lambda x: x[0])
