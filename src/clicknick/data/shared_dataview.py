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

from .cdv_file import list_cdv_files

if TYPE_CHECKING:
    from .address_store import AddressStore


class SharedDataviewData:
    """Model behind the Dataview Editor.

    - Looks up nicknames and comments live from the AddressStore
    - Finds CDV files in the DataView folder ``get_folder`` gives now

    Window lifecycle belongs to DataSession; the editor window observes the
    store directly for nickname refreshes.
    """

    def __init__(
        self,
        address_store: AddressStore,
        get_folder: Callable[[], Path | None] = lambda: None,
        filter_func: Callable[[list[str], str], list[str]] | None = None,
    ):
        """Initialize the dataview model.

        Args:
            address_store: AddressStore for nickname lookups
            get_folder: The DataView folder to show now (the connected CLICK
                window's, or the loaded CSV's folder), or None for none
            filter_func: Active filter strategy callback (candidates, search_text) -> filtered
        """
        self._store = address_store
        self._get_folder = get_folder
        self.filter_func = filter_func

    @property
    def dataview_folder(self) -> Path | None:
        """The DataView folder to show now, or None."""
        return self._get_folder()

    @property
    def address_store(self) -> AddressStore:
        """Get the AddressStore for nickname lookups."""
        return self._store

    def get_cdv_files(self) -> list[Path]:
        """Get list of CDV files in the dataview folder.

        Returns:
            List of Path objects for each CDV file.
        """
        folder = self.dataview_folder
        if not folder:
            return []
        return list_cdv_files(folder)

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
