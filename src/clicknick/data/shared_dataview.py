"""Shared data model for Dataview Editor windows.

Manages open dataviews and provides nickname lookup from SharedAddressData.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..models.address_row import get_addr_key, parse_address_display
from ..views.dataview_editor.cdv_file import get_dataview_folder, list_cdv_files

if TYPE_CHECKING:
    from .shared_data import SharedAddressData


class SharedDataviewData:
    """Shared data store for dataview editor windows.

    This class manages the list of available CDV files and provides
    nickname lookup via SharedAddressData.
    """

    def __init__(
        self,
        project_path: Path | None = None,
        address_shared_data: SharedAddressData | None = None,
    ):
        """Initialize the shared dataview data.

        Args:
            project_path: Path to the CLICK project folder
            address_shared_data: SharedAddressData for nickname lookups
        """
        self._project_path = project_path
        self._address_shared_data = address_shared_data
        self._dataview_folder: Path | None = None

        # Observer callbacks
        self._observers: list[Callable[[], None]] = []

        # Registered windows
        self._windows: list = []

        # Find dataview folder
        if project_path:
            self._dataview_folder = get_dataview_folder(project_path)

    @property
    def dataview_folder(self) -> Path | None:
        """Get the DataView folder path."""
        return self._dataview_folder

    @property
    def address_shared_data(self) -> SharedAddressData | None:
        """Get the SharedAddressData for nickname lookups."""
        return self._address_shared_data

    def set_address_shared_data(self, data: SharedAddressData) -> None:
        """Set the SharedAddressData for nickname lookups.

        Args:
            data: SharedAddressData instance
        """
        self._address_shared_data = data

    def get_cdv_files(self) -> list[Path]:
        """Get list of CDV files in the dataview folder.

        Returns:
            List of Path objects for each CDV file.
        """
        if not self._dataview_folder:
            return []
        return list_cdv_files(self._dataview_folder)

    def lookup_nickname(self, address: str) -> tuple[str, str] | None:
        """Look up nickname and comment for an address.

        Args:
            address: The address string (e.g., "X001", "DS100")

        Returns:
            Tuple of (nickname, comment) or None if not found.
        """
        if self._address_shared_data:
            parsed = parse_address_display(address)
            if not parsed:
                return None

            memory_type, mdb_address = parsed
            addr_key = get_addr_key(memory_type, mdb_address)

            if addr_key in self._address_shared_data.all_rows:
                row = self._address_shared_data.all_rows[addr_key]
                return (row.nickname, row.comment)

        return None

    def add_observer(self, callback: Callable[[], None]) -> None:
        """Add an observer callback."""
        if callback not in self._observers:
            self._observers.append(callback)

    def remove_observer(self, callback: Callable[[], None]) -> None:
        """Remove an observer callback."""
        if callback in self._observers:
            self._observers.remove(callback)

    def notify_data_changed(self) -> None:
        """Notify all observers that data has changed."""
        for callback in self._observers:
            try:
                callback()
            except Exception:
                pass

    def register_window(self, window) -> None:
        """Register a dataview editor window."""
        if window not in self._windows:
            self._windows.append(window)

    def unregister_window(self, window) -> None:
        """Unregister a dataview editor window."""
        if window in self._windows:
            self._windows.remove(window)

    def close_all_windows(self, prompt_save: bool = True) -> bool:
        """Close all registered editor windows.

        Args:
            prompt_save: If True, prompt to save unsaved changes first.

        Returns:
            True if all windows were closed, False if user cancelled.
        """
        # Check for unsaved changes
        if prompt_save:
            has_unsaved = any(
                hasattr(w, "has_unsaved_changes") and w.has_unsaved_changes() for w in self._windows
            )
            if has_unsaved:
                from tkinter import messagebox

                parent = self._windows[0] if self._windows else None
                result = messagebox.askyesnocancel(
                    "Unsaved Changes",
                    "You have unsaved changes in Dataview Editor. Save before closing?",
                    parent=parent,
                )
                if result is None:  # Cancel
                    return False
                if result:  # Yes - save
                    for window in self._windows:
                        if hasattr(window, "save_all"):
                            window.save_all()

        # Close all windows
        for window in self._windows[:]:
            try:
                window.destroy()
            except Exception:
                pass

        self._windows.clear()
        return True

    def force_close_all_windows(self) -> None:
        """Force close all windows without saving."""
        for window in self._windows[:]:
            try:
                window.destroy()
            except Exception:
                pass
        self._windows.clear()
