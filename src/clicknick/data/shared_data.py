"""Shared data model for Address Editor windows.

Allows multiple Address Editor windows to share the same data,
with changes in one window automatically reflected in others.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..models.address_row import AddressRow, get_addr_key, is_xd_yd_hidden_slot
from ..models.blocktag import compute_all_block_ranges
from ..models.constants import (
    ADDRESS_RANGES,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_TO_DATA_TYPE,
    DataType,
)
from ..models.validation import validate_nickname
from .data_source import DataSource

if TYPE_CHECKING:
    from ..views.address_editor.view_builder import UnifiedView

# File monitoring interval in milliseconds
FILE_MONITOR_INTERVAL_MS = 2000


class SharedAddressData:
    """Shared data store for address editor windows.

    This class holds the loaded data for all memory types and provides
    methods for loading, modifying, and saving data. Multiple windows
    can observe changes through registered callbacks.

    Usage:
        # Create shared data (usually once in main app)
        from .data_source import MdbDataSource
        data_source = MdbDataSource(click_pid=pid, click_hwnd=hwnd)
        shared = SharedAddressData(data_source)
        shared.load_initial_data()

        # Each window registers as observer
        shared.add_observer(window1.on_data_changed)
        shared.add_observer(window2.on_data_changed)

        # When data changes in any window, all observers are notified
    """

    # --- Skeleton Architecture ---

    def _create_skeleton(self) -> dict[int, AddressRow]:
        """Create static skeleton of all possible AddressRow objects.

        Creates one AddressRow per valid address slot across all memory types.
        These objects are created once and reused for the lifetime of the app.
        All tabs and windows reference these same objects.

        Returns:
            Dict mapping addr_key to skeleton AddressRow objects
        """
        skeleton: dict[int, AddressRow] = {}

        for mem_type, (start, end) in ADDRESS_RANGES.items():
            default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, DataType.BIT)
            default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)

            for addr in range(start, end + 1):
                # Skip hidden XD/YD slots (odd addresses >= 3)
                if is_xd_yd_hidden_slot(mem_type, addr):
                    continue

                addr_key = get_addr_key(mem_type, addr)
                row = AddressRow(
                    memory_type=mem_type,
                    address=addr,
                    exists_in_mdb=False,
                    data_type=default_data_type,
                    retentive=default_retentive,
                    original_retentive=default_retentive,
                )
                # Wire up parent reference for edit session enforcement
                row._parent = self
                skeleton[addr_key] = row

        return skeleton

    def __init__(self, data_source: DataSource):
        """Initialize the shared data store.

        Args:
            data_source: DataSource implementation for loading/saving data
        """
        self._data_source = data_source

        # Edit session state - must be set BEFORE skeleton creation
        self._is_editing: bool = False
        self._initializing: bool = True  # Allow skeleton creation without edit_session
        self._current_changes: set[int] = set()  # addr_keys modified in current session
        self._nickname_old_values: dict[int, str] = {}  # addr_key -> old nickname for index updates
        self._comment_old_values: dict[int, str] = {}  # addr_key -> old comment for paired tag sync

        # Data storage - shared across all windows
        # Create skeleton of ALL possible addresses at startup
        self.all_rows: dict[int, AddressRow] = self._create_skeleton()
        self.rows_by_type: dict[str, list[AddressRow]] = {}

        # Mark initialization complete - now edits require edit_session
        self._initializing = False

        # Reverse index: nickname -> set of addr_keys that have this nickname
        # Used for O(1) duplicate detection instead of O(n) scan
        self._nickname_to_addrs: dict[str, set[int]] = {}

        # Lowercase reverse index for case-insensitive duplicate detection
        # CLICK software treats nicknames as case-insensitive
        self._nickname_lower_to_addrs: dict[str, set[int]] = {}

        # Observer callbacks - called when data changes
        self._observers: list[Callable[[], None]] = []

        # Track registered windows for close operations
        self._windows: list = []  # list of AddressEditorWindow

        # Track if initial data has been loaded
        self._initialized = False

        # File monitoring state
        self._file_path: str | None = None
        self._last_mtime: float = 0.0
        self._monitor_after_id: str | None = None
        self._monitoring_active = False

        # Cached unified view (all memory types in one view)
        self._unified_view: UnifiedView | None = None

    @property
    def supports_used_field(self) -> bool:
        """Check if the data source supports the 'Used' field."""
        return self._data_source.supports_used_field

    # --- Edit Session Management ---

    @property
    def is_editing(self) -> bool:
        """Check if currently in an edit session or initializing.

        Returns True if modifications to AddressRow content fields are allowed.
        """
        return self._is_editing or self._initializing

    def mark_changed(self, addr_key: int) -> None:
        """Record that a row was modified during this edit session.

        Called automatically by AddressRow.__setattr__ when a locked field changes.

        Args:
            addr_key: The address key of the modified row
        """
        if self._is_editing:
            self._current_changes.add(addr_key)

    def _record_nickname_change(self, addr_key: int, old_nickname: str) -> None:
        """Record a nickname change for index updates on session exit.

        Only records the first old value if nickname is changed multiple times
        in the same session, since we need to update from the original index state.

        Args:
            addr_key: The address key
            old_nickname: The nickname value before the change
        """
        if self._is_editing and addr_key not in self._nickname_old_values:
            self._nickname_old_values[addr_key] = old_nickname

    def _record_comment_change(self, addr_key: int, old_comment: str) -> None:
        """Record a comment change for paired tag sync on session exit.

        Only records the first old value if comment is changed multiple times
        in the same session, since we need the original value to detect tag renames.

        Args:
            addr_key: The address key
            old_comment: The comment value before the change
        """
        if self._is_editing and addr_key not in self._comment_old_values:
            self._comment_old_values[addr_key] = old_comment

    def _update_nickname_indices(
        self, affected: set[int], nickname_changes: dict[int, str]
    ) -> None:
        """Update nickname reverse indices after modifications.

        Args:
            affected: Set of addr_keys that were modified
            nickname_changes: Map of addr_key -> old_nickname for rows with nickname changes
        """
        for addr_key, old_nickname in nickname_changes.items():
            if addr_key in self.all_rows:
                new_nickname = self.all_rows[addr_key].nickname
                if old_nickname != new_nickname:
                    self.update_nickname(addr_key, old_nickname, new_nickname)

    def _validate_affected_rows(self, affected: set[int], nickname_changes: dict[int, str]) -> None:
        """Validate rows affected by changes.

        Also validates rows that share nicknames with changed rows
        (to detect/clear duplicate errors).

        Args:
            affected: Set of addr_keys that were modified
            nickname_changes: Map of addr_key -> old_nickname for rows with nickname changes
        """
        # Collect all nicknames involved for duplicate detection cascade
        nicknames_to_check: set[str] = set()

        for addr_key, old_nickname in nickname_changes.items():
            if old_nickname:
                nicknames_to_check.add(old_nickname.lower())
            if addr_key in self.all_rows:
                new_nick = self.all_rows[addr_key].nickname
                if new_nick:
                    nicknames_to_check.add(new_nick.lower())

        # Find all rows with these nicknames (for duplicate detection)
        keys_to_validate = affected.copy()
        for nickname in nicknames_to_check:
            keys_to_validate.update(self._nickname_lower_to_addrs.get(nickname, set()))

        # Validate all affected rows
        all_nicknames = self.all_nicknames
        for addr_key in keys_to_validate:
            if addr_key in self.all_rows:
                self.all_rows[addr_key].validate(
                    all_nicknames, is_duplicate_fn=self.is_duplicate_nickname
                )

    def _update_block_colors_if_needed(
        self, affected: set[int], comment_changes: dict[int, str]
    ) -> None:
        """Update block colors if any comments were modified.

        Args:
            affected: Set of addr_keys that were modified
            comment_changes: Dict of addr_key -> old_comment for rows with changes
        """
        from ..services.block_service import BlockService

        if comment_changes:
            # BlockService.update_colors returns additional affected keys
            # Pass only the keys (set of addr_keys that changed)
            additional = BlockService.update_colors(self, set(comment_changes.keys()))
            affected.update(additional)

    def _sync_dependencies(self) -> None:
        """Sync interleaved pairs (T/TD, CT/CTD) during edit session exit.

        When a T or CT row's retentive changes, the paired TD or CTD row
        should be updated to match. This is called while still in editing
        mode so modifications are allowed.

        Any synced rows are automatically tracked via mark_changed().
        """
        from ..services.dependency_service import RowDependencyService

        if not self._current_changes:
            return

        # Get snapshot of current changes (sync may add more)
        keys_to_check = self._current_changes.copy()
        RowDependencyService.sync_interleaved_pairs(self, keys_to_check)

    def _sync_paired_block_tags(self) -> None:
        """Sync paired block tags (opening/closing) during edit session exit.

        When a user renames or deletes a block tag, the paired tag should
        be updated to match. For example, renaming <Foo> to <Bar> also
        renames </Foo> to </Bar>.

        This is called while still in editing mode so modifications are allowed.
        Any synced rows are automatically tracked via mark_changed().
        """
        from ..models.blocktag import parse_block_tag
        from ..services.block_service import BlockService

        if not self._comment_old_values:
            return

        # Get unified view for searching paired tags
        view = self.get_unified_view()
        if not view:
            return

        # Build addr_key -> row_idx map for the unified view
        key_to_idx = {row.addr_key: idx for idx, row in enumerate(view.rows)}

        # Copy to avoid modification during iteration (paired tag sync may add entries)
        comment_changes = self._comment_old_values.copy()
        for addr_key, old_comment in comment_changes.items():
            row = self.all_rows.get(addr_key)
            if not row:
                continue

            row_idx = key_to_idx.get(addr_key)
            if row_idx is None:
                continue

            # Parse old and new block tags
            old_tag = parse_block_tag(old_comment)
            new_tag = parse_block_tag(row.comment)

            # Check if block tag changed
            if old_tag.name or new_tag.name:
                BlockService.auto_update_paired_tag(view.rows, row_idx, old_tag, new_tag)

    @contextmanager
    def edit_session(self) -> Generator[SharedAddressData, None, None]:
        """Context manager for modifying AddressRow objects.

        All modifications to AddressRow content fields (nickname, comment,
        initial_value, retentive) must happen within an edit_session.
        On exit, the session automatically:
        1. Syncs interleaved pairs (T/TD, CT/CTD retentive settings)
        2. Updates nickname reverse indices for changed nicknames
        3. Validates all affected rows
        4. Updates block colors if comments changed
        5. Broadcasts changes to all observers with specific indices

        Usage:
            with shared_data.edit_session():
                row = shared_data.all_rows[addr_key]
                row.nickname = "NewName"
                row.comment = "New comment"
            # Validation and notification happen automatically on exit

        Yields:
            Self (SharedAddressData instance)

        Raises:
            RuntimeError: If edit_session is nested (sessions cannot be nested)
        """
        if self._is_editing:
            raise RuntimeError("Cannot nest edit_session calls")

        self._is_editing = True
        self._current_changes.clear()
        self._nickname_old_values.clear()
        self._comment_old_values.clear()

        try:
            yield self
        finally:
            # Phase 1: Sync dependencies (while still in editing mode)
            # This may modify additional rows (paired T/TD, CT/CTD)
            self._sync_dependencies()

            # Phase 2: Sync paired block tags (while still in editing mode)
            # When user renames <Foo> to <Bar>, also rename </Foo> to </Bar>
            self._sync_paired_block_tags()

            # Capture final state after sync
            affected = self._current_changes.copy()
            nickname_changes = self._nickname_old_values.copy()
            comment_changes = self._comment_old_values.copy()

            # Now lock editing - no more modifications allowed
            self._is_editing = False
            self._current_changes.clear()
            self._nickname_old_values.clear()
            self._comment_old_values.clear()

            if affected:
                # Phase 3: Update nickname reverse indices
                self._update_nickname_indices(affected, nickname_changes)

                # Phase 4: Validate affected rows (and rows sharing nicknames)
                self._validate_affected_rows(affected, nickname_changes)

                # Phase 5: Update block colors if any comments changed
                self._update_block_colors_if_needed(affected, comment_changes)

                # Phase 6: Broadcast changes with specific indices
                self.notify_data_changed(affected_indices=affected)

    def add_observer(self, callback: Callable[[], None]) -> None:
        """Add an observer callback that will be called when data changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[], None]) -> None:
        """Remove an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    # --- Unified View Management ---

    def get_unified_view(self) -> UnifiedView | None:
        """Get the cached unified view (all memory types).

        Returns:
            UnifiedView if cached, None otherwise
        """
        return self._unified_view

    def set_unified_view(self, view: UnifiedView) -> None:
        """Store the unified view.

        Args:
            view: The UnifiedView to cache
        """
        self._unified_view = view

    def _hydrate_from_db_data(self, db_rows: dict[int, AddressRow]) -> None:
        """Update skeleton rows in-place with database data.

        Transfers data from loaded AddressRow objects into existing skeleton
        rows. This preserves object identity so all tabs share the same rows.

        Args:
            db_rows: AddressRow objects loaded from database
        """
        for addr_key, db_row in db_rows.items():
            if addr_key in self.all_rows:
                row = self.all_rows[addr_key]
                # Transfer content fields
                row.nickname = db_row.nickname
                row.comment = db_row.comment
                row.used = db_row.used
                row.data_type = db_row.data_type
                row.initial_value = db_row.initial_value
                row.retentive = db_row.retentive
                row.exists_in_mdb = True
                # Set originals to match (row is "clean")
                row.original_nickname = db_row.nickname
                row.original_comment = db_row.comment
                row.original_initial_value = db_row.initial_value
                row.original_retentive = db_row.retentive
                # Preserve loaded_with_error state from data source
                if db_row.loaded_with_error:
                    row.loaded_with_error = True

    def _mark_loaded_with_errors(self) -> None:
        """Mark X/SC/SD rows that loaded with invalid nicknames.

        These memory types allow nicknames that start with numbers in CLICK,
        but we still want to flag them so users know they have non-standard names.
        Called after hydration when all_nicknames is available.
        """
        all_nicks = self.all_nicknames
        for row in self.all_rows.values():
            if row.memory_type in ("X", "SC", "SD") and row.nickname:
                is_valid, _ = validate_nickname(row.nickname, all_nicks, row.addr_key)
                if not is_valid:
                    row.loaded_with_error = True

    def _reset_skeleton_row(self, row: AddressRow) -> None:
        """Reset a skeleton row to empty state.

        Used when a row is deleted externally or after full delete save.

        Args:
            row: The skeleton row to reset
        """
        row.nickname = ""
        row.comment = ""
        row.used = False
        row.initial_value = ""
        row.exists_in_mdb = False
        # Reset originals
        row.original_nickname = ""
        row.original_comment = ""
        row.original_initial_value = ""
        # Keep original_retentive at default for memory type
        row.loaded_with_error = False
        # Reset validation state
        row.is_valid = True
        row.validation_error = ""
        row.initial_value_valid = True
        row.initial_value_error = ""

    def register_window(self, window) -> None:
        """Register an editor window for tracking.

        Args:
            window: AddressEditorWindow instance
        """
        if window not in self._windows:
            self._windows.append(window)

    def unregister_window(self, window) -> None:
        """Unregister an editor window.

        Args:
            window: AddressEditorWindow instance
        """
        if window in self._windows:
            self._windows.remove(window)

    def close_all_windows(self, prompt_save: bool = True) -> bool:
        """Close all registered editor windows.

        Args:
            prompt_save: If True, prompt to save unsaved changes first.
                        If False, discard changes without prompting.

        Returns:
            True if all windows were closed, False if user cancelled.
        """
        if prompt_save and self.has_unsaved_changes():
            # Import here to avoid circular imports
            from tkinter import messagebox

            # Use first window as parent for dialog, or None
            parent = self._windows[0] if self._windows else None
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=parent,
            )
            if result is None:  # Cancel
                return False
            if result:  # Yes - save
                try:
                    self.save_all_changes()
                except Exception:
                    messagebox.showerror(
                        "Save Error",
                        "Failed to save changes. Windows will remain open.",
                        parent=parent,
                    )
                    return False

        # Stop file monitoring
        self.stop_file_monitoring()

        # Close all windows (make a copy since list will be modified)
        for window in self._windows[:]:
            try:
                window.destroy()
            except Exception:
                pass  # Window may already be destroyed

        self._windows.clear()
        return True

    def force_close_all_windows(self) -> None:
        """Force close all registered editor windows without saving.

        Use this when the database is no longer available (e.g., Click software closed).
        """
        # Stop file monitoring
        self.stop_file_monitoring()

        for window in self._windows[:]:
            try:
                window.destroy()
            except Exception:
                pass  # Window may already be destroyed

        self._windows.clear()
        self.rows_by_type.clear()  # Clear cached data since DB is gone

    def notify_data_changed(
        self, sender: object = None, affected_indices: set[int] | None = None
    ) -> None:
        """Notify all observers that data has changed.

        Call this after modifying shared data to update all windows.

        Args:
            sender: The object that triggered the change (allows observers
                    to skip processing if they are the sender)
            affected_indices: Set of addr_keys that changed. If None,
                             indicates a full refresh is needed.
        """
        for callback in self._observers:
            try:
                # Try calling with affected_indices parameter
                callback(sender, affected_indices)
            except TypeError:
                # Legacy callbacks that don't accept affected_indices
                try:
                    callback(sender)
                except TypeError:
                    callback()
            except Exception:
                pass  # Don't let one observer's error break others

    @property
    def all_nicknames(self) -> dict[int, str]:
        """Get dict mapping AddrKey to nickname (derived from all_rows)."""
        return {addr_key: row.nickname for addr_key, row in self.all_rows.items() if row.nickname}

    def _rebuild_nickname_index(self) -> None:
        """Rebuild the nickname -> addr_keys reverse index from all_rows."""
        self._nickname_to_addrs.clear()
        self._nickname_lower_to_addrs.clear()
        for addr_key, row in self.all_rows.items():
            if row.nickname:
                # Exact case index
                if row.nickname not in self._nickname_to_addrs:
                    self._nickname_to_addrs[row.nickname] = set()
                self._nickname_to_addrs[row.nickname].add(addr_key)
                # Lowercase index for case-insensitive duplicate detection
                nick_lower = row.nickname.lower()
                if nick_lower not in self._nickname_lower_to_addrs:
                    self._nickname_lower_to_addrs[nick_lower] = set()
                self._nickname_lower_to_addrs[nick_lower].add(addr_key)

    def load_initial_data(self) -> None:
        """Load all address data from data source into skeleton rows.

        Hydrates the pre-created skeleton with database data. This preserves
        object identity so all tabs share the same AddressRow instances.
        """
        # Load from data source (creates temporary AddressRow objects)
        db_rows = self._data_source.load_all_addresses()

        # Hydrate skeleton with loaded data using edit_session
        # This handles change tracking, index updates, validation, and notification
        with self.edit_session():
            self._hydrate_from_db_data(db_rows)

        self._initialized = True

        # Mark X/SC/SD rows with invalid nicknames (needs all_nicknames)
        self._mark_loaded_with_errors()

        # Store file path and initial modification time for monitoring
        self._file_path = self._data_source.file_path
        if self._file_path and os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

    def get_addr_keys_for_nickname(self, nickname: str) -> set[int]:
        """Get all addr_keys that have a specific nickname (exact case match).

        Args:
            nickname: The nickname to look up

        Returns:
            Set of addr_keys (empty if nickname not found)
        """
        if not nickname:
            return set()
        return self._nickname_to_addrs.get(nickname, set()).copy()

    def get_addr_keys_for_nickname_insensitive(self, nickname: str) -> set[int]:
        """Get all addr_keys that have a nickname matching case-insensitively.

        Args:
            nickname: The nickname to look up (any case)

        Returns:
            Set of addr_keys with any case variation of the nickname
        """
        if not nickname:
            return set()
        return self._nickname_lower_to_addrs.get(nickname.lower(), set()).copy()

    def is_duplicate_nickname(self, nickname: str, exclude_addr_key: int) -> bool:
        """Check if a nickname is used by any other address (case-insensitive).

        O(1) lookup using the lowercase reverse index.
        CLICK software treats nicknames as case-insensitive, so "Pump1" and "pump1"
        are considered duplicates.

        Args:
            nickname: The nickname to check
            exclude_addr_key: The addr_key to exclude from the check

        Returns:
            True if nickname is used by another address (case-insensitive match)
        """
        if not nickname:
            return False
        nick_lower = nickname.lower()
        addr_keys = self._nickname_lower_to_addrs.get(nick_lower, set())
        # Duplicate if more than one addr_key, or one that isn't the excluded one
        if len(addr_keys) > 1:
            return True
        if len(addr_keys) == 1 and exclude_addr_key not in addr_keys:
            return True
        return False

    def validate_affected_rows(self, old_nickname: str, new_nickname: str) -> set[int]:
        """Validate only the rows affected by a nickname change.

        Instead of validating all 4500+ rows, this only validates:
        - Rows that had the old nickname (may no longer be duplicates)
        - Rows that have the new nickname (may now be duplicates)

        Uses case-insensitive lookup since CLICK treats nicknames as case-insensitive.
        Uses O(1) duplicate checking via the reverse index.

        Args:
            old_nickname: The previous nickname value
            new_nickname: The new nickname value

        Returns:
            Set of addr_keys that were validated
        """
        # Collect affected addr_keys (case-insensitive to catch all case variations)
        affected_keys: set[int] = set()

        if old_nickname:
            affected_keys.update(self.get_addr_keys_for_nickname_insensitive(old_nickname))
        if new_nickname:
            affected_keys.update(self.get_addr_keys_for_nickname_insensitive(new_nickname))

        if not affected_keys:
            return set()

        # Build all_nicknames dict for validation (needed by row.validate() for format checks)
        all_nicknames = self.all_nicknames

        # Validate affected rows using O(1) duplicate check
        for addr_key in affected_keys:
            if addr_key in self.all_rows:
                self.all_rows[addr_key].validate(
                    all_nicknames, is_duplicate_fn=self.is_duplicate_nickname
                )

        return affected_keys

    def is_initialized(self) -> bool:
        """Check if initial data has been loaded."""
        return self._initialized

    def _schedule_file_check(self) -> None:
        """Schedule the next file modification check."""
        if not self._monitoring_active or not hasattr(self, "_tk_root"):
            return
        self._monitor_after_id = self._tk_root.after(
            FILE_MONITOR_INTERVAL_MS, self._check_file_modified
        )

    def start_file_monitoring(self, tk_root) -> None:
        """Start monitoring the mdb file for external changes.

        Args:
            tk_root: Tkinter root window (needed for after() scheduling)
        """
        if self._monitoring_active:
            return

        self._tk_root = tk_root
        self._monitoring_active = True
        self._schedule_file_check()

    def stop_file_monitoring(self) -> None:
        """Stop file monitoring."""
        self._monitoring_active = False
        if self._monitor_after_id and hasattr(self, "_tk_root"):
            try:
                self._tk_root.after_cancel(self._monitor_after_id)
            except Exception:
                pass
        self._monitor_after_id = None

    def _reload_from_source(self) -> None:
        """Reload data from source, updating skeleton rows in-place.

        With skeleton architecture, we never create/delete row objects.
        We only update the data fields of existing skeleton rows.
        """
        try:
            # Reload all addresses (creates temporary AddressRow objects)
            new_rows = self._data_source.load_all_addresses()
        except Exception:
            # Load error, skip this reload
            return

        # Use edit_session for proper change tracking and notification
        with self.edit_session():
            # Update existing skeleton rows from new data
            for addr_key, new_row in new_rows.items():
                if addr_key in self.all_rows:
                    skeleton_row = self.all_rows[addr_key]
                    # Use update_from_db for proper dirty field handling
                    db_data = {
                        "nickname": new_row.nickname,
                        "comment": new_row.comment,
                        "used": new_row.used,
                        "data_type": new_row.data_type,
                        "initial_value": new_row.initial_value,
                        "retentive": new_row.retentive,
                    }
                    skeleton_row.update_from_db(db_data)
                    # Mark as existing in MDB
                    skeleton_row.exists_in_mdb = True

            # Reset rows no longer in DB (if not dirty)
            for addr_key, skeleton_row in self.all_rows.items():
                if addr_key not in new_rows and skeleton_row.exists_in_mdb:
                    if not skeleton_row.is_dirty:
                        self._reset_skeleton_row(skeleton_row)

    def _check_file_modified(self) -> None:
        """Check if the data file has been modified and reload if so."""
        if not self._monitoring_active:
            return

        try:
            if self._file_path and os.path.exists(self._file_path):
                current_mtime = os.path.getmtime(self._file_path)
                if current_mtime > self._last_mtime:
                    self._last_mtime = current_mtime
                    self._reload_from_source()
        except Exception:
            # File might be locked during write, skip this check
            pass

        # Schedule next check
        self._schedule_file_check()

    def get_rows(self, memory_type: str) -> list[AddressRow] | None:
        """Get rows for a memory type if already loaded.

        Args:
            memory_type: The memory type (X, Y, C, etc.)

        Returns:
            List of rows or None if not loaded
        """
        return self.rows_by_type.get(memory_type)

    def set_rows(self, memory_type: str, rows: list[AddressRow]) -> None:
        """Store rows for a memory type.

        Args:
            memory_type: The memory type
            rows: List of AddressRow objects
        """
        self.rows_by_type[memory_type] = rows

    def get_block_addresses(
        self, memory_type: str
    ) -> list[tuple[int, int | None, str, str | None]]:
        """Get block definitions for a memory type.

        Block tags mark sections for navigation in the Address Editor.
        - Opening tags (<BlockName>) paired with closing tags (</BlockName>) form ranges
        - Self-closing tags (<BlockName />) mark singular points
        - Blocks can be nested
        - Tags can have bg attribute for background color: <BlockName bg="#color">

        Args:
            memory_type: The memory type (X, Y, C, etc.)

        Returns:
            List of (start_addr, end_addr, block_name, bg_color) tuples sorted by start address.
            end_addr is None for self-closing (singular) blocks.
            bg_color is None if not specified in the tag.
        """
        # Filter unified view rows by memory_type
        unified_rows = self.rows_by_type.get("unified", [])
        rows = [r for r in unified_rows if r.memory_type == memory_type]
        if not rows:
            return []

        # Use centralized block matching
        ranges = compute_all_block_ranges(rows)

        # Convert row indices to addresses
        blocks: list[tuple[int, int | None, str, str | None]] = []
        for block in ranges:
            start_addr = rows[block.start_idx].address
            # Self-closing or unclosed tags have same start/end index
            if block.start_idx == block.end_idx:
                end_addr = None
            else:
                end_addr = rows[block.end_idx].address
            blocks.append((start_addr, end_addr, block.name, block.bg_color))

        return sorted(blocks, key=lambda x: x[0])

    def update_nickname(self, addr_key: int, old_nickname: str, new_nickname: str) -> None:
        """Update a nickname in the global registry.

        Args:
            addr_key: The address key
            old_nickname: The old nickname (for removal)
            new_nickname: The new nickname
        """
        # Update reverse index: remove from old nickname's set
        if old_nickname and old_nickname in self._nickname_to_addrs:
            self._nickname_to_addrs[old_nickname].discard(addr_key)
            # Clean up empty sets
            if not self._nickname_to_addrs[old_nickname]:
                del self._nickname_to_addrs[old_nickname]

        # Update lowercase reverse index: remove from old nickname's set
        if old_nickname:
            old_lower = old_nickname.lower()
            if old_lower in self._nickname_lower_to_addrs:
                self._nickname_lower_to_addrs[old_lower].discard(addr_key)
                if not self._nickname_lower_to_addrs[old_lower]:
                    del self._nickname_lower_to_addrs[old_lower]

        # Update reverse index: add to new nickname's set
        if new_nickname:
            if new_nickname not in self._nickname_to_addrs:
                self._nickname_to_addrs[new_nickname] = set()
            self._nickname_to_addrs[new_nickname].add(addr_key)

            # Update lowercase reverse index
            new_lower = new_nickname.lower()
            if new_lower not in self._nickname_lower_to_addrs:
                self._nickname_lower_to_addrs[new_lower] = set()
            self._nickname_lower_to_addrs[new_lower].add(addr_key)

        # Note: We don't set row.nickname here - the caller already did that
        # within an edit_session. This method only updates the reverse indices.

    def save_all_changes(self) -> int:
        """Save changes to data source.

        With skeleton architecture, all rows are in all_rows (skeleton).
        We save dirty rows and reset fully-deleted rows to empty state.

        Returns:
            Number of changes saved

        Raises:
            Exception: If save fails
            RuntimeError: If data source is read-only
        """
        if self._data_source.is_read_only:
            raise RuntimeError("Data source is read-only")

        # Collect dirty skeleton rows
        dirty_rows = [row for row in self.all_rows.values() if row.is_dirty]

        if not dirty_rows:
            return 0

        # Capture rows that will be fully deleted (before mark_saved resets dirty state)
        rows_to_reset = [row for row in dirty_rows if row.needs_full_delete]

        # Pass all skeleton rows - data source decides what to save
        # (MDB saves only dirty rows, CSV rewrites all rows with content)
        count = self._data_source.save_changes(list(self.all_rows.values()))

        # Mark dirty rows as saved (sets original_* fields, which are unlocked)
        with self.edit_session():
            for row in dirty_rows:
                row.mark_saved()
                # MANUALLY MARK AS CHANGED:
                # This ensures addr_key is added to self._current_changes
                self.mark_changed(row.addr_key) 

            # Reset fully-deleted rows to skeleton state using edit_session
            if rows_to_reset:
                    for row in rows_to_reset:
                        self._reset_skeleton_row(row)

        # Update modified time to prevent immediate reload
        if self._file_path and os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

        return count

    def discard_all_changes(self) -> None:
        """Discard all changes by resetting skeleton rows to original values.

        With skeleton architecture, we just iterate over all_rows and
        call discard() on dirty rows. Much faster than DB reload.
        """
        # Use edit_session for proper change tracking and notification
        with self.edit_session():
            for row in self.all_rows.values():
                if row.is_dirty:
                    row.discard()

    def has_unsaved_changes(self) -> bool:
        """Check if any loaded type has unsaved changes."""
        return any(row.is_dirty for rows in self.rows_by_type.values() for row in rows)

    def has_errors(self) -> bool:
        """Check if any loaded type has validation errors."""
        return any(
            not row.is_valid and not row.is_empty and not row.should_ignore_validation_error
            for rows in self.rows_by_type.values()
            for row in rows
        )

    def get_total_modified_count(self) -> int:
        """Get total count of modified rows across all types."""
        return sum(1 for rows in self.rows_by_type.values() for row in rows if row.is_dirty)

    def get_total_error_count(self) -> int:
        """Get total count of rows with errors across all types."""
        return sum(
            1
            for rows in self.rows_by_type.values()
            for row in rows
            if not row.is_valid and not row.is_empty and not row.should_ignore_validation_error
        )

    def get_modified_count_for_type(self, memory_type: str) -> int:
        """Get count of modified rows for a specific memory type.

        Args:
            memory_type: The memory type (X, Y, C, etc.)

        Returns:
            Count of dirty rows for this type
        """
        # Use unified view rows (the actual rows being edited), not all_rows
        rows = self.rows_by_type.get("unified", [])
        return sum(1 for row in rows if row.memory_type == memory_type and row.is_dirty)

    def get_error_count_for_type(self, memory_type: str) -> int:
        """Get count of rows with errors for a specific memory type.

        Args:
            memory_type: The memory type (X, Y, C, etc.)

        Returns:
            Count of rows with validation errors for this type
        """
        # Use unified view rows (the actual rows being edited), not all_rows
        rows = self.rows_by_type.get("unified", [])
        return sum(
            1
            for row in rows
            if row.memory_type == memory_type
            and not row.is_valid
            and not row.is_empty
            and not row.should_ignore_validation_error
        )
