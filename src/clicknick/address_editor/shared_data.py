"""Shared data model for Address Editor windows.

Allows multiple Address Editor windows to share the same data,
with changes in one window automatically reflected in others.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from .address_model import AddressRow
from .blocktag_model import parse_block_tag
from .mdb_operations import MdbConnection, load_all_addresses, save_changes

# File monitoring interval in milliseconds
FILE_MONITOR_INTERVAL_MS = 2000


class SharedAddressData:
    """Shared data store for address editor windows.

    This class holds the loaded data for all memory types and provides
    methods for loading, modifying, and saving data. Multiple windows
    can observe changes through registered callbacks.

    Usage:
        # Create shared data (usually once in main app)
        shared = SharedAddressData(click_pid, click_hwnd)
        shared.load_initial_data()

        # Each window registers as observer
        shared.add_observer(window1.on_data_changed)
        shared.add_observer(window2.on_data_changed)

        # When data changes in any window, all observers are notified
    """

    def __init__(self, click_pid: int, click_hwnd: int):
        """Initialize the shared data store.

        Args:
            click_pid: Process ID of the CLICK software
            click_hwnd: Window handle of the CLICK software
        """
        self.click_pid = click_pid
        self.click_hwnd = click_hwnd

        # Data storage - shared across all windows
        self.all_rows: dict[int, AddressRow] = {}  # AddrKey -> AddressRow
        self.rows_by_type: dict[str, list[AddressRow]] = {}

        # Observer callbacks - called when data changes
        self._observers: list[Callable[[], None]] = []

        # Track registered windows for close operations
        self._windows: list = []  # list of AddressEditorWindow

        # Track if initial data has been loaded
        self._initialized = False

        # File monitoring state
        self._mdb_path: str | None = None
        self._last_mtime: float = 0.0
        self._monitor_after_id: str | None = None
        self._monitoring_active = False

    def _get_connection(self) -> MdbConnection:
        """Create a database connection (use as context manager)."""
        conn = MdbConnection.from_click_window(self.click_pid, self.click_hwnd)
        # Store the mdb path for file monitoring
        if self._mdb_path is None:
            self._mdb_path = conn.db_path
        return conn

    def add_observer(self, callback: Callable[[], None]) -> None:
        """Add an observer callback that will be called when data changes."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[], None]) -> None:
        """Remove an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

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

    def notify_data_changed(self) -> None:
        """Notify all observers that data has changed.

        Call this after modifying shared data to update all windows.
        """
        for callback in self._observers:
            try:
                callback()
            except Exception:
                pass  # Don't let one observer's error break others

    @property
    def all_nicknames(self) -> dict[int, str]:
        """Get dict mapping AddrKey to nickname (derived from all_rows)."""
        return {addr_key: row.nickname for addr_key, row in self.all_rows.items() if row.nickname}

    def load_initial_data(self) -> None:
        """Load all address data from database."""
        with self._get_connection() as conn:
            self.all_rows = load_all_addresses(conn)
        self._initialized = True

        # Store initial file modification time for monitoring
        if self._mdb_path and os.path.exists(self._mdb_path):
            self._last_mtime = os.path.getmtime(self._mdb_path)

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

    def _reload_from_db(self) -> None:
        """Reload data from database, updating non-dirty cells."""
        any_changes = False

        try:
            with self._get_connection() as conn:
                # Reload all addresses
                new_rows = load_all_addresses(conn)

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
            # Connection error, skip this reload
            return

        if any_changes:
            self.notify_data_changed()

    def _check_file_modified(self) -> None:
        """Check if the mdb file has been modified and reload if so."""
        if not self._monitoring_active:
            return

        try:
            if self._mdb_path and os.path.exists(self._mdb_path):
                current_mtime = os.path.getmtime(self._mdb_path)
                if current_mtime > self._last_mtime:
                    self._last_mtime = current_mtime
                    self._reload_from_db()
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
        # Update the nickname in all_rows if it exists
        if addr_key in self.all_rows:
            self.all_rows[addr_key].nickname = new_nickname

    def save_all_changes(self) -> int:
        """Save all dirty rows to database.

        Returns:
            Number of changes saved

        Raises:
            Exception: If save fails
        """
        all_dirty_rows = []
        for rows in self.rows_by_type.values():
            for row in rows:
                if row.is_dirty:
                    all_dirty_rows.append(row)

        if not all_dirty_rows:
            return 0

        # Capture rows that will be fully deleted (before mark_saved resets dirty state)
        rows_to_remove = [row for row in all_dirty_rows if row.needs_full_delete]

        with self._get_connection() as conn:
            count = save_changes(conn, all_dirty_rows)

        # Mark rows as saved
        for row in all_dirty_rows:
            row.mark_saved()

        # Remove fully-deleted rows from all_rows
        for row in rows_to_remove:
            if row.addr_key in self.all_rows:
                del self.all_rows[row.addr_key]

        self.notify_data_changed()
        return count

    def discard_all_changes(self) -> None:
        """Discard all changes and reload from database."""
        # Clear cached data - panels will reload when accessed
        self.rows_by_type.clear()

        # Reload all addresses
        with self._get_connection() as conn:
            self.all_rows = load_all_addresses(conn)

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
