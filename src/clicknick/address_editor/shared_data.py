"""Shared data model for Address Editor windows.

Allows multiple Address Editor windows to share the same data,
with changes in one window automatically reflected in others.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from .address_model import AddressRow
from .mdb_operations import MdbConnection, load_all_nicknames, load_nicknames_for_type, save_changes

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
        self.all_nicknames: dict[int, str] = {}
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
        """Create a fresh database connection."""
        conn = MdbConnection.from_click_window(self.click_pid, self.click_hwnd)
        # Store the mdb path for file monitoring
        if self._mdb_path is None:
            self._mdb_path = conn.db_path
        conn.connect()
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

    def load_initial_data(self) -> None:
        """Load initial nickname registry from database."""
        with self._get_connection() as conn:
            self.all_nicknames = load_all_nicknames(conn)
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
        if not self.rows_by_type:
            return

        any_changes = False

        try:
            with self._get_connection() as conn:
                # Reload all_nicknames
                new_nicknames = load_all_nicknames(conn)

                # Update each loaded type
                for type_name, rows in self.rows_by_type.items():
                    # Handle combined types (T/TD, CT/CTD)
                    if "/" in type_name:
                        sub_types = type_name.split("/")
                        existing_by_type = {}
                        for sub_type in sub_types:
                            existing_by_type[sub_type] = load_nicknames_for_type(conn, sub_type)

                        # Update rows
                        for row in rows:
                            db_data = existing_by_type.get(row.memory_type, {}).get(row.address)
                            if db_data:
                                if row.update_from_db(db_data):
                                    any_changes = True
                            elif not row.is_dirty:
                                # Row was deleted externally, reset to empty
                                if row.used:
                                    row.used = False
                                    any_changes = True
                    else:
                        # Single type
                        existing = load_nicknames_for_type(conn, type_name)

                        for row in rows:
                            db_data = existing.get(row.address)
                            if db_data:
                                if row.update_from_db(db_data):
                                    any_changes = True
                            elif not row.is_dirty:
                                # Row was deleted externally, reset used flag
                                if row.used:
                                    row.used = False
                                    any_changes = True

                # Update nickname registry (for non-dirty entries)
                for addr_key, new_nick in new_nicknames.items():
                    if addr_key not in self.all_nicknames:
                        self.all_nicknames[addr_key] = new_nick
                        any_changes = True
                    elif self.all_nicknames[addr_key] != new_nick:
                        # Check if this nickname is dirty in any row
                        is_dirty = False
                        for rows in self.rows_by_type.values():
                            for row in rows:
                                if row.addr_key == addr_key and row.is_nickname_dirty:
                                    is_dirty = True
                                    break
                            if is_dirty:
                                break
                        if not is_dirty:
                            self.all_nicknames[addr_key] = new_nick
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

    def get_header_addresses(self, memory_type: str) -> list[tuple[int, int | None, str]]:
        """Get block definitions for a memory type.

        Block tags mark sections for navigation in the Address Editor.
        - Opening tags (<BlockName>) paired with closing tags (</BlockName>) form ranges
        - Self-closing tags (<BlockName />) mark singular points
        - Blocks can be nested

        Args:
            memory_type: The memory type (X, Y, C, etc.)

        Returns:
            List of (start_addr, end_addr, block_name) tuples sorted by start address.
            end_addr is None for self-closing (singular) blocks.
        """
        from .address_model import parse_block_tag

        rows = self.rows_by_type.get(memory_type)
        if not rows:
            return []

        # Collect all block tags
        open_tags: dict[str, list[int]] = {}  # name -> [addresses] (stack for nesting)
        blocks: list[tuple[int, int | None, str]] = []

        for row in rows:
            block_name, tag_type, _ = parse_block_tag(row.comment)
            if not block_name:
                continue

            if tag_type == "self-closing":
                # Singular point - no end address
                blocks.append((row.address, None, block_name))
            elif tag_type == "open":
                # Push to stack for this block name
                if block_name not in open_tags:
                    open_tags[block_name] = []
                open_tags[block_name].append(row.address)
            elif tag_type == "close":
                # Pop from stack and create range
                if block_name in open_tags and open_tags[block_name]:
                    start_addr = open_tags[block_name].pop()
                    blocks.append((start_addr, row.address, block_name))

        # Any unclosed opening tags become singular points
        for block_name, addresses in open_tags.items():
            for addr in addresses:
                blocks.append((addr, None, block_name))

        return sorted(blocks, key=lambda x: x[0])

    def update_nickname(self, addr_key: int, old_nickname: str, new_nickname: str) -> None:
        """Update a nickname in the global registry.

        Args:
            addr_key: The address key
            old_nickname: The old nickname (for removal)
            new_nickname: The new nickname
        """
        if old_nickname and addr_key in self.all_nicknames:
            del self.all_nicknames[addr_key]
        if new_nickname:
            self.all_nicknames[addr_key] = new_nickname

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

        with self._get_connection() as conn:
            count = save_changes(conn, all_dirty_rows)

        # Mark rows as saved
        for row in all_dirty_rows:
            row.mark_saved()

        self.notify_data_changed()
        return count

    def discard_all_changes(self) -> None:
        """Discard all changes and reload from database."""
        # Clear cached data - panels will reload when accessed
        self.rows_by_type.clear()

        # Reload nicknames
        with self._get_connection() as conn:
            self.all_nicknames = load_all_nicknames(conn)

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
