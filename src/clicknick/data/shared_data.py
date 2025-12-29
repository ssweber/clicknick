"""Shared data model for Address Editor windows.

Allows multiple Address Editor windows to share the same data,
with changes in one window automatically reflected in others.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..models.address_row import AddressRow
from ..models.blocktag import parse_block_tag
from .data_source import DataSource

# File monitoring interval in milliseconds
FILE_MONITOR_INTERVAL_MS = 2000


@dataclass
class TypeView:
    """Cached view data for a memory type (built once, shared by all panels).

    This contains pre-computed display data that would otherwise be
    recalculated by each AddressPanel independently.
    """

    # The type key (e.g., "X", "T/TD")
    type_key: str

    # Ordered list of AddressRow references (shared with SharedAddressData)
    rows: list[AddressRow]

    # Display data arrays (parallel to rows)
    # Each inner list = [used_display, nickname, comment, init_value_display, retentive_display]
    display_data: list[list[Any]] = field(default_factory=list)

    # Row index labels (e.g., "X001", "T1", "TD1")
    index_labels: list[str] = field(default_factory=list)

    # Block colors computed from comments (row_idx -> hex_color)
    block_colors: dict[int, str] = field(default_factory=dict)

    # Combined types if this is an interleaved view (e.g., ["T", "TD"])
    combined_types: list[str] | None = None


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

    def __init__(self, data_source: DataSource):
        """Initialize the shared data store.

        Args:
            data_source: DataSource implementation for loading/saving data
        """
        self._data_source = data_source

        # Data storage - shared across all windows
        self.all_rows: dict[int, AddressRow] = {}  # AddrKey -> AddressRow
        self.rows_by_type: dict[str, list[AddressRow]] = {}

        # Reverse index: nickname -> set of addr_keys that have this nickname
        # Used for O(1) duplicate detection instead of O(n) scan
        self._nickname_to_addrs: dict[str, set[int]] = {}

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

        # Cached views by type key (e.g., "X", "T/TD")
        self._views: dict[str, TypeView] = {}

    @property
    def supports_used_field(self) -> bool:
        """Check if the data source supports the 'Used' field."""
        return self._data_source.supports_used_field

    def add_observer(self, callback: Callable[[], None]) -> None:
        """Add an observer callback that will be called when data changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[], None]) -> None:
        """Remove an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    # --- View Management ---

    def get_view(self, type_key: str) -> TypeView | None:
        """Get the cached view for a memory type.

        Args:
            type_key: The memory type key (e.g., "X", "T/TD")

        Returns:
            TypeView if cached, None otherwise
        """
        return self._views.get(type_key)

    def set_view(self, type_key: str, view: TypeView) -> None:
        """Store a view for a memory type.

        Args:
            type_key: The memory type key
            view: The TypeView to cache
        """
        self._views[type_key] = view

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

    def notify_data_changed(self, sender: object = None) -> None:
        """Notify all observers that data has changed.

        Call this after modifying shared data to update all windows.

        Args:
            sender: The object that triggered the change (allows observers
                    to skip processing if they are the sender)
        """
        for callback in self._observers:
            try:
                callback(sender)
            except Exception:
                pass  # Don't let one observer's error break others

    @property
    def all_nicknames(self) -> dict[int, str]:
        """Get dict mapping AddrKey to nickname (derived from all_rows)."""
        return {addr_key: row.nickname for addr_key, row in self.all_rows.items() if row.nickname}

    def _rebuild_nickname_index(self) -> None:
        """Rebuild the nickname -> addr_keys reverse index from all_rows."""
        self._nickname_to_addrs.clear()
        for addr_key, row in self.all_rows.items():
            if row.nickname:
                if row.nickname not in self._nickname_to_addrs:
                    self._nickname_to_addrs[row.nickname] = set()
                self._nickname_to_addrs[row.nickname].add(addr_key)

    def load_initial_data(self) -> None:
        """Load all address data from data source."""
        self.all_rows = self._data_source.load_all_addresses()
        self._initialized = True

        # Build reverse index for O(1) duplicate detection
        self._rebuild_nickname_index()

        # Store file path and initial modification time for monitoring
        self._file_path = self._data_source.file_path
        if self._file_path and os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

    def get_addr_keys_for_nickname(self, nickname: str) -> set[int]:
        """Get all addr_keys that have a specific nickname.

        Args:
            nickname: The nickname to look up

        Returns:
            Set of addr_keys (empty if nickname not found)
        """
        if not nickname:
            return set()
        return self._nickname_to_addrs.get(nickname, set()).copy()

    def is_duplicate_nickname(self, nickname: str, exclude_addr_key: int) -> bool:
        """Check if a nickname is used by any other address.

        O(1) lookup using the reverse index.

        Args:
            nickname: The nickname to check
            exclude_addr_key: The addr_key to exclude from the check

        Returns:
            True if nickname is used by another address
        """
        if not nickname:
            return False
        addr_keys = self._nickname_to_addrs.get(nickname, set())
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

        Uses O(1) duplicate checking via the reverse index.

        Args:
            old_nickname: The previous nickname value
            new_nickname: The new nickname value

        Returns:
            Set of addr_keys that were validated
        """
        # Collect affected addr_keys
        affected_keys: set[int] = set()

        if old_nickname:
            affected_keys.update(self.get_addr_keys_for_nickname(old_nickname))
        if new_nickname:
            affected_keys.update(self.get_addr_keys_for_nickname(new_nickname))

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
        """Reload data from data source, updating non-dirty cells."""
        any_changes = False

        try:
            # Reload all addresses
            new_rows = self._data_source.load_all_addresses()

            # Update existing rows from new data
            for addr_key, new_row in new_rows.items():
                if addr_key in self.all_rows:
                    existing_row = self.all_rows[addr_key]
                    # Convert new_row to dict format for update_from_db
                    db_data = {
                        "nickname": new_row.nickname,
                        "comment": new_row.comment,
                        "used": new_row.used,
                        "data_type": new_row.data_type,
                        "initial_value": new_row.initial_value,
                        "retentive": new_row.retentive,
                    }
                    if existing_row.update_from_db(db_data):
                        any_changes = True
                else:
                    # New row added externally
                    self.all_rows[addr_key] = new_row
                    any_changes = True

            # Check for rows deleted externally
            for addr_key in list(self.all_rows.keys()):
                if addr_key not in new_rows:
                    row = self.all_rows[addr_key]
                    if not row.is_dirty:
                        del self.all_rows[addr_key]
                        any_changes = True

            # Also update rows_by_type if loaded
            for _type_name, rows in self.rows_by_type.items():
                for row in rows:
                    if row.addr_key in new_rows:
                        new_row = new_rows[row.addr_key]
                        db_data = {
                            "nickname": new_row.nickname,
                            "comment": new_row.comment,
                            "used": new_row.used,
                            "data_type": new_row.data_type,
                            "initial_value": new_row.initial_value,
                            "retentive": new_row.retentive,
                        }
                        if row.update_from_db(db_data):
                            any_changes = True

        except Exception:
            # Load error, skip this reload
            return

        if any_changes:
            self.notify_data_changed()

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

        rows = self.rows_by_type.get(memory_type)
        if not rows:
            return []

        # Collect all block tags
        # Stack stores (address, bg_color) tuples for each block name
        open_tags: dict[str, list[tuple[int, str | None]]] = {}
        blocks: list[tuple[int, int | None, str, str | None]] = []

        for row in rows:
            block_tag = parse_block_tag(row.comment)
            if not block_tag.name:
                continue

            if block_tag.tag_type == "self-closing":
                # Singular point - no end address
                blocks.append((row.address, None, block_tag.name, block_tag.bg_color))
            elif block_tag.tag_type == "open":
                # Push to stack for this block name (with bg color)
                if block_tag.name not in open_tags:
                    open_tags[block_tag.name] = []
                open_tags[block_tag.name].append((row.address, block_tag.bg_color))
            elif block_tag.tag_type == "close":
                # Pop from stack and create range
                if block_tag.name in open_tags and open_tags[block_tag.name]:
                    start_addr, start_bg_color = open_tags[block_tag.name].pop()
                    blocks.append((start_addr, row.address, block_tag.name, start_bg_color))

        # Any unclosed opening tags become singular points
        for block_name, addr_color_pairs in open_tags.items():
            for addr, bg_color in addr_color_pairs:
                blocks.append((addr, None, block_name, bg_color))

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

        # Update reverse index: add to new nickname's set
        if new_nickname:
            if new_nickname not in self._nickname_to_addrs:
                self._nickname_to_addrs[new_nickname] = set()
            self._nickname_to_addrs[new_nickname].add(addr_key)

        # Update the nickname in all_rows if it exists
        if addr_key in self.all_rows:
            self.all_rows[addr_key].nickname = new_nickname

    def save_all_changes(self) -> int:
        """Save changes to data source.

        Returns:
            Number of changes saved

        Raises:
            Exception: If save fails
            RuntimeError: If data source is read-only
        """
        if self._data_source.is_read_only:
            raise RuntimeError("Data source is read-only")

        # Build complete row set: start with all_rows, overlay with panel rows
        # (Panel rows may have edits that aren't in all_rows)
        rows_to_save: dict[int, AddressRow] = {}
        all_dirty_rows: list[AddressRow] = []

        # First, add all original rows
        for addr_key, row in self.all_rows.items():
            rows_to_save[addr_key] = row

        # Then overlay with panel rows (which have any edits)
        for rows in self.rows_by_type.values():
            for row in rows:
                rows_to_save[row.addr_key] = row
                if row.is_dirty:
                    all_dirty_rows.append(row)

        if not all_dirty_rows:
            return 0

        # Capture rows that will be fully deleted (before mark_saved resets dirty state)
        rows_to_remove = [row for row in all_dirty_rows if row.needs_full_delete]

        # Pass all rows - data source decides what to save
        # (MDB saves only dirty rows, CSV rewrites all rows with content)
        count = self._data_source.save_changes(list(rows_to_save.values()))

        # Mark dirty rows as saved
        for row in all_dirty_rows:
            row.mark_saved()

        # Remove fully-deleted rows from all_rows
        for row in rows_to_remove:
            if row.addr_key in self.all_rows:
                del self.all_rows[row.addr_key]

        self.notify_data_changed()
        return count

    def discard_all_changes(self) -> None:
        """Discard all changes by resetting rows to original values.

        This is much faster than reloading from database since we just
        reset the in-memory rows using their stored original values.
        """
        # Reset all dirty rows in-place
        for rows in self.rows_by_type.values():
            for row in rows:
                if row.is_dirty:
                    row.discard()
                    # Sync all_rows to match (for all_nicknames property)
                    if row.addr_key in self.all_rows:
                        self.all_rows[row.addr_key].nickname = row.nickname

        self.notify_data_changed()

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
            memory_type: The memory type (X, Y, C, etc.) or combined type (T/TD, CT/CTD)

        Returns:
            Count of dirty rows for this type
        """
        # Rows are stored under the exact key (including combined types like "T/TD")
        rows = self.rows_by_type.get(memory_type, [])
        return sum(1 for row in rows if row.is_dirty)

    def get_error_count_for_type(self, memory_type: str) -> int:
        """Get count of rows with errors for a specific memory type.

        Args:
            memory_type: The memory type (X, Y, C, etc.) or combined type (T/TD, CT/CTD)

        Returns:
            Count of rows with validation errors for this type
        """
        # Rows are stored under the exact key (including combined types like "T/TD")
        rows = self.rows_by_type.get(memory_type, [])
        return sum(
            1
            for row in rows
            if not row.is_valid and not row.is_empty and not row.should_ignore_validation_error
        )
