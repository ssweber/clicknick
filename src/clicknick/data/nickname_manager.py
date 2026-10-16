from __future__ import annotations

from typing import TYPE_CHECKING

from pyclickplc.blocks import strip_block_tag

from ..models.nickname import Nickname
from ..utils.filters import ContainsFilter, ContainsPlusFilter, NoneFilter, PrefixFilter
from ..utils.mdb_shared import has_access_driver, has_database_backend

if TYPE_CHECKING:
    from .address_store import AddressStore


class NicknameManager:
    """Nickname filtering and lookup over an AddressStore.

    Builds a cached list of Nickname objects from the store's visible rows on
    demand, and invalidates the cache whenever the store notifies of changes.
    """

    def __init__(self, settings=None, filter_strategies=None):
        self._store: AddressStore | None = None
        self._nickname_cache: list[Nickname] | None = None
        self.settings = settings

        # Use provided filter strategies or create default ones
        if filter_strategies:
            self.filter_strategies = filter_strategies
        else:
            self.filter_strategies = {
                "none": NoneFilter(),
                "prefix": PrefixFilter(),
                "contains": ContainsFilter(),
                "containsplus": ContainsPlusFilter(),
            }

    def _on_data_changed(self, sender=None, affected_keys=None) -> None:
        """Observer callback when AddressStore changes."""
        self._nickname_cache = None

    def set_store(self, store: AddressStore | None) -> None:
        """Set the AddressStore to delegate to.

        Registers as observer to invalidate cache on changes.
        """
        # Unregister from the old store
        if self._store is not None:
            self._store.remove_observer(self._on_data_changed)

        self._store = store
        self._nickname_cache = None

        # Register as observer on the new store
        if self._store is not None:
            self._store.add_observer(self._on_data_changed)

    def _build_nickname_cache(self) -> list[Nickname]:
        """Build Nickname list from AddressStore.visible_state."""
        if self._store is None:
            return []

        nicknames = []
        for row in self._store.visible_state.values():
            if not row.nickname:
                continue
            nickname_obj = Nickname(
                nickname=row.nickname,
                address=row.display_address,
                data_type_display=row.data_type_display,
                initial_value=row.initial_value,
                retentive=row.retentive,
                comment=strip_block_tag(row.comment),
                address_type=row.memory_type,
                used=row.used,
            )
            nicknames.append(nickname_obj)
        return nicknames

    def _generate_abbreviation_tags(self):
        """Generate abbreviation tags for containsplus filtering."""
        if self._nickname_cache is None:
            return

        containsplus_filter = self.filter_strategies.get("containsplus")
        if not containsplus_filter:
            return

        for nickname_obj in self._nickname_cache:
            nickname_obj.abbr_tags = containsplus_filter.generate_tags(nickname_obj.nickname)

    @property
    def nicknames(self) -> list[Nickname]:
        """Get cached Nickname list, rebuilt on demand.

        Order is derived from settings at build time: alphabetical when
        sort_by_nickname is on, otherwise address order. Any store change
        rebuilds the list, so the order can never drift from the setting.
        """
        if self._nickname_cache is None:
            nicknames = self._build_nickname_cache()
            if self.settings is not None and self.settings.sort_by_nickname:
                nicknames.sort(key=lambda x: x.nickname)
            self._nickname_cache = nicknames
            self._generate_abbreviation_tags()
        return self._nickname_cache

    def invalidate(self) -> None:
        """Drop the cached list so the next read rebuilds it (e.g. after a settings change)."""
        self._nickname_cache = None

    @property
    def is_loaded(self) -> bool:
        """Check if nicknames data is loaded."""
        return len(self.nicknames) > 0

    def get_address_for_nickname(self, nickname: str) -> str | None:
        """Get the address for a given nickname.

        Args:
            nickname: The exact nickname to look up

        Returns:
            The corresponding address or None if not found
        """
        for nickname_obj in self.nicknames:
            if nickname_obj.nickname == nickname:
                return nickname_obj.address
        return None

    def get_nickname_details(self, nickname: str) -> str:
        """Get detailed information for a given nickname.

        Args:
            nickname: The exact nickname to look up

        Returns:
            Detailed string with address, data type, initial value, and comment
        """
        for nickname_obj in self.nicknames:
            if nickname_obj.nickname == nickname:
                return nickname_obj.details()
        return ""

    def get_filtered_nicknames(self, address_types: list[str], search_text: str = "") -> list[str]:
        """Get filtered list of nickname strings using current app settings.

        Args:
            address_types: List of allowed address types (X, Y, C, etc.)
            search_text: Text to search for in nicknames

        Returns:
            List of matching nickname strings
        """
        if not self.nicknames or not address_types:
            return []

        # Get filtering parameters from settings (with fallbacks)
        if self.settings:
            search_mode = self.settings.search_mode
            exclude_sc_sd = self.settings.exclude_sc_sd
            excluded_terms = self.settings.get_exclude_terms_list()
        else:
            search_mode = "none"
            exclude_sc_sd = False
            excluded_terms = []

        # Filter by address type and exclusions
        filtered_objects = []
        for nickname_obj in self.nicknames:
            # Check if address type matches
            if nickname_obj.address_type not in address_types:
                continue

            # Skip SC/SD addresses if requested
            if exclude_sc_sd and (
                nickname_obj.address.startswith("SC") or nickname_obj.address.startswith("SD")
            ):
                continue

            # Skip if it contains any excluded terms
            nickname_lower = nickname_obj.nickname.lower()
            if any(excluded_term in nickname_lower for excluded_term in excluded_terms):
                continue

            filtered_objects.append(nickname_obj)

        # Apply search filtering if search text provided
        if not search_text or search_mode == "none":
            return [obj.nickname for obj in filtered_objects]

        strategy = self.filter_strategies.get(search_mode, self.filter_strategies["none"])
        search_filtered_objects = strategy.filter_matches(filtered_objects, search_text)

        return [obj.nickname for obj in search_filtered_objects]

    def has_access_driver(self) -> bool:
        """Check if any Microsoft Access ODBC driver is available."""
        return has_access_driver()

    def has_database_backend(self) -> bool:
        """Check for native ODBC or the built-in Windows Jet fallback."""
        return has_database_backend()
