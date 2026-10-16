"""Model behind the Dataview Editor: CDV file discovery and nickname lookup."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pyclickplc.addresses import (
    get_addr_key,
    parse_address,
)
from pyclickplc.addresses import (
    normalize_address as _normalize_address,
)

from .cdv_file import get_dataview_folder, list_cdv_files

if TYPE_CHECKING:
    from .address_store import AddressStore


class SharedDataviewData:
    """Model behind the Dataview Editor.

    - Looks up nicknames and comments live from the AddressStore
    - Finds CDV files in the project's DataView folder

    Window lifecycle belongs to DataSession; the editor window observes the
    store directly for nickname refreshes.
    """

    def __init__(
        self,
        address_store: AddressStore,
        project_path: Path | None = None,
        dataview_folder: Path | None = None,
        filter_func: Callable[[list[str], str], list[str]] | None = None,
    ):
        """Initialize the dataview model.

        Args:
            address_store: AddressStore for nickname lookups
            project_path: Path to the CLICK project folder
            dataview_folder: Explicit DataView folder override (e.g., CSV directory)
            filter_func: Active filter strategy callback (candidates, search_text) -> filtered
        """
        self._store = address_store
        self._dataview_folder: Path | None = dataview_folder
        self.filter_func = filter_func

        # Find dataview folder from project if not explicitly provided
        if self._dataview_folder is None and project_path:
            self._dataview_folder = get_dataview_folder(project_path)

    @property
    def dataview_folder(self) -> Path | None:
        """Get the DataView folder path."""
        return self._dataview_folder

    @property
    def address_store(self) -> AddressStore:
        """Get the AddressStore for nickname lookups."""
        return self._store

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
        try:
            memory_type, mdb_address = parse_address(address)
        except ValueError:
            return None
        row = self._store.visible_state.get(get_addr_key(memory_type, mdb_address))
        if row is None:
            return None
        return (row.nickname, row.comment)

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
