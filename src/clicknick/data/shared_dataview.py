"""Shared data model for Dataview Editor window.

Read-only shim over AddressStore for nickname lookups.
Manages CDV file discovery and the single dataview editor window.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pyclickplc import (
    get_addr_key,
    parse_address_display,
)
from pyclickplc import (
    normalize_address as _normalize_address,
)

from ..views.dataview_editor.cdv_file import get_dataview_folder, list_cdv_files

if TYPE_CHECKING:
    from .data.address_store import AddressStore


class SharedDataviewData:
    """Shared data for the Dataview Editor window.

    This class:
    - Provides nickname lookup via AddressStore (read-only shim)
    - Manages CDV file discovery in the project's DataView folder
    - Tracks the single dataview editor window
    - Observes AddressStore for automatic nickname refresh
    """

    def __init__(
        self,
        project_path: Path | None = None,
        address_store: AddressStore | None = None,
    ):
        """Initialize the shared dataview data.

        Args:
            project_path: Path to the CLICK project folder
            address_store: AddressStore for nickname lookups
        """
        self._project_path = project_path
        self._store: AddressStore | None = None
        self._dataview_folder: Path | None = None

        # Single window tracking (only one dataview editor at a time)
        self._window = None

        # Find dataview folder
        if project_path:
            self._dataview_folder = get_dataview_folder(project_path)

        # Wire up to AddressStore if provided
        if address_store:
            self.set_address_store(address_store)

    @property
    def dataview_folder(self) -> Path | None:
        """Get the DataView folder path."""
        return self._dataview_folder

    @property
    def address_store(self) -> AddressStore | None:
        """Get the AddressStore for nickname lookups."""
        return self._store

    def _on_address_data_changed(self, sender=None) -> None:
        """Observer callback when AddressStore changes.

        Triggers nickname refresh in the dataview editor window.
        """
        if self._window is not None and hasattr(self._window, "refresh_nicknames_from_shared"):
            try:
                self._window.refresh_nicknames_from_shared()
            except Exception:
                pass

    def set_address_store(self, data: AddressStore | None) -> None:
        """Set the AddressStore for nickname lookups.

        Registers as observer to auto-refresh nicknames when address data changes.

        Args:
            data: AddressStore instance or None to disconnect
        """
        # Unregister from old shared data
        if self._store is not None:
            self._store.remove_observer(self._on_address_data_changed)

        self._store = data

        # Register as observer on new shared data
        if self._store is not None:
            self._store.add_observer(self._on_address_data_changed)

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
        if self._store:
            parsed = parse_address_display(address)
            if not parsed:
                return None

            memory_type, mdb_address = parsed
            addr_key = get_addr_key(memory_type, mdb_address)

            if addr_key in self._store.all_rows:
                row = self._store.all_rows[addr_key]
                return (row.nickname, row.comment)

        return None

    def normalize_address(self, address: str) -> str | None:
        """Normalize an address string to its canonical display form.

        Parses the input address and returns the properly formatted display_address
        (e.g., "x1" -> "X001", "xd0u" -> "XD0u").

        Args:
            address: The address string to normalize (e.g., "x1", "XD0U")

        Returns:
            The normalized display_address, or None if address is invalid.
        """
        return _normalize_address(address)

    def register_window(self, window) -> None:
        """Register the dataview editor window."""
        self._window = window

    def unregister_window(self, window) -> None:
        """Unregister the dataview editor window."""
        if self._window == window:
            self._window = None

    def close_window(self, prompt_save: bool = True) -> bool:
        """Close the dataview editor window if open.

        Args:
            prompt_save: If True, prompt to save unsaved changes first.

        Returns:
            True if window was closed (or wasn't open), False if user cancelled.
        """
        if self._window is None:
            return True

        # Check for unsaved changes
        if prompt_save and hasattr(self._window, "has_unsaved_changes"):
            if self._window.has_unsaved_changes():
                from tkinter import messagebox

                result = messagebox.askyesnocancel(
                    "Unsaved Changes",
                    "You have unsaved changes in Dataview Editor. Save before closing?",
                    parent=self._window,
                )
                if result is None:  # Cancel
                    return False
                if result:  # Yes - save
                    if hasattr(self._window, "save_all"):
                        self._window.save_all()

        # Close window
        try:
            self._window.destroy()
        except Exception:
            pass

        self._window = None
        return True

    def force_close_window(self) -> None:
        """Force close the window without saving."""
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    # Backwards compatibility aliases
    def close_all_windows(self, prompt_save: bool = True) -> bool:
        """Close the dataview editor window. Alias for close_window()."""
        return self.close_window(prompt_save)

    def force_close_all_windows(self) -> None:
        """Force close the window. Alias for force_close_window()."""
        self.force_close_window()
