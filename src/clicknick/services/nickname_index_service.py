"""Nickname index service for O(1) nickname lookups.

This service maintains reverse indices for efficient nickname operations:
- Exact case lookup: nickname -> set of addr_keys
- Case-insensitive lookup: lowercase nickname -> set of addr_keys

CLICK software treats nicknames as case-insensitive, so "Pump1" and "pump1"
are considered duplicates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..models.address_row import AddressRow


class NicknameIndexService:
    """Maintains nickname reverse indices for O(1) lookups.

    This service is stateful - it owns the nickname indices and must be
    kept in sync with AddressRow data via rebuild_index() or update().
    """

    def __init__(self) -> None:
        """Initialize empty indices."""
        # Exact case index: nickname -> set of addr_keys
        self._nickname_to_addrs: dict[str, set[int]] = {}
        # Lowercase index for case-insensitive duplicate detection
        self._nickname_lower_to_addrs: dict[str, set[int]] = {}

    def rebuild_index(self, rows: Iterable[AddressRow]) -> None:
        """Rebuild indices from scratch.

        Args:
            rows: Iterable of AddressRow objects (e.g., all_rows.values())
        """
        self._nickname_to_addrs.clear()
        self._nickname_lower_to_addrs.clear()

        for row in rows:
            if row.nickname:
                addr_key = row.addr_key
                nickname = row.nickname

                # Exact case index
                if nickname not in self._nickname_to_addrs:
                    self._nickname_to_addrs[nickname] = set()
                self._nickname_to_addrs[nickname].add(addr_key)

                # Lowercase index
                nick_lower = nickname.lower()
                if nick_lower not in self._nickname_lower_to_addrs:
                    self._nickname_lower_to_addrs[nick_lower] = set()
                self._nickname_lower_to_addrs[nick_lower].add(addr_key)

    def get_addr_keys(self, nickname: str) -> set[int]:
        """Get addr_keys with exact case match.

        Args:
            nickname: The nickname to look up

        Returns:
            Set of addr_keys (copy, empty if not found)
        """
        if not nickname:
            return set()
        return self._nickname_to_addrs.get(nickname, set()).copy()

    def get_addr_keys_insensitive(self, nickname: str) -> set[int]:
        """Get addr_keys with case-insensitive match.

        Args:
            nickname: The nickname to look up (any case)

        Returns:
            Set of addr_keys with any case variation (copy, empty if not found)
        """
        if not nickname:
            return set()
        return self._nickname_lower_to_addrs.get(nickname.lower(), set()).copy()

    def is_duplicate(self, nickname: str, exclude_addr_key: int) -> bool:
        """Check if nickname is used by another address (case-insensitive).

        O(1) lookup using the lowercase reverse index.

        Args:
            nickname: The nickname to check
            exclude_addr_key: The addr_key to exclude from the check

        Returns:
            True if nickname is used by another address
        """
        if not nickname:
            return False

        addr_keys = self._nickname_lower_to_addrs.get(nickname.lower(), set())

        # Duplicate if more than one addr_key, or one that isn't excluded
        if len(addr_keys) > 1:
            return True
        if len(addr_keys) == 1 and exclude_addr_key not in addr_keys:
            return True
        return False

    def update(self, addr_key: int, old_nickname: str, new_nickname: str) -> None:
        """Update indices after a nickname change.

        Args:
            addr_key: The address key
            old_nickname: The old nickname (for removal)
            new_nickname: The new nickname (for addition)
        """
        # Remove from old nickname's sets
        if old_nickname:
            if old_nickname in self._nickname_to_addrs:
                self._nickname_to_addrs[old_nickname].discard(addr_key)
                if not self._nickname_to_addrs[old_nickname]:
                    del self._nickname_to_addrs[old_nickname]

            old_lower = old_nickname.lower()
            if old_lower in self._nickname_lower_to_addrs:
                self._nickname_lower_to_addrs[old_lower].discard(addr_key)
                if not self._nickname_lower_to_addrs[old_lower]:
                    del self._nickname_lower_to_addrs[old_lower]

        # Add to new nickname's sets
        if new_nickname:
            if new_nickname not in self._nickname_to_addrs:
                self._nickname_to_addrs[new_nickname] = set()
            self._nickname_to_addrs[new_nickname].add(addr_key)

            new_lower = new_nickname.lower()
            if new_lower not in self._nickname_lower_to_addrs:
                self._nickname_lower_to_addrs[new_lower] = set()
            self._nickname_lower_to_addrs[new_lower].add(addr_key)
