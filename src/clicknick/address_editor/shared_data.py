"""Shared data model for Address Editor windows.

Allows multiple Address Editor windows to share the same data,
with changes in one window automatically reflected in others.
"""

from __future__ import annotations

from collections.abc import Callable

from .address_model import AddressRow
from .mdb_operations import MdbConnection, load_all_nicknames, save_changes


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

    def _get_connection(self) -> MdbConnection:
        """Create a fresh database connection."""
        conn = MdbConnection.from_click_window(self.click_pid, self.click_hwnd)
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

    def is_initialized(self) -> bool:
        """Check if initial data has been loaded."""
        return self._initialized

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

    def get_header_addresses(self, memory_type: str) -> list[tuple[int, str]]:
        """Get addresses that have header tags for a memory type.

        Header tags are comments formatted as <HeaderName> that act as
        section markers for navigation in the Address Editor.

        Args:
            memory_type: The memory type (X, Y, C, etc.)

        Returns:
            List of (address, header_name) tuples for rows with header tags,
            sorted by address.
        """
        from .address_model import extract_header_name

        rows = self.rows_by_type.get(memory_type)
        if not rows:
            return []

        headers = []
        for row in rows:
            header_name = extract_header_name(row.comment)
            if header_name:
                headers.append((row.address, header_name))

        return sorted(headers, key=lambda x: x[0])

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
