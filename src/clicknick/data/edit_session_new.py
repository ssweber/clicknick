"""Edit session helper for accumulating changes to AddressRows.

EditSession provides a high-level API for modifying rows. Changes are
accumulated as MutableRowBuilder instances and applied atomically
when the session exits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.mutable_row_builder import MutableRowBuilder

if TYPE_CHECKING:
    from .address_store import AddressStore


class EditSession:
    """Context manager for accumulating changes to AddressRows.

    Provides builder objects for each row being edited. Changes are
    accumulated during the session and applied atomically on exit.

    Usage:
        with store.edit_session("Update nicknames") as session:
            session.set_field(addr_key, "nickname", "NewName")
            session.set_field(addr_key, "comment", "Updated comment")
        # Changes are applied and undo frame pushed on exit

    Or with direct builder access:
        with store.edit_session("Fill down") as session:
            builder = session.get_builder(addr_key)
            builder.nickname = "Motor1"
            builder.comment = "Main motor"
    """

    def __init__(self, store: AddressStore, description: str):
        """Initialize an edit session.

        Args:
            store: The AddressStore being edited.
            description: Human-readable description for undo menu.
        """
        self._store = store
        self._description = description
        self._pending: dict[int, MutableRowBuilder] = {}
        self._nickname_old_values: dict[int, str] = {}
        self._comment_old_values: dict[int, str] = {}

    @property
    def description(self) -> str:
        """Get the description for this edit session."""
        return self._description

    @property
    def pending(self) -> dict[int, MutableRowBuilder]:
        """Get the pending builders dict (for AddressStore to access)."""
        return self._pending

    @property
    def nickname_old_values(self) -> dict[int, str]:
        """Get dict of addr_key -> old_nickname for index updates."""
        return self._nickname_old_values

    @property
    def comment_old_values(self) -> dict[int, str]:
        """Get dict of addr_key -> old_comment for block tag sync."""
        return self._comment_old_values

    def get_builder(self, addr_key: int) -> MutableRowBuilder:
        """Get or create a builder for the given address key.

        Args:
            addr_key: The address key to edit.

        Returns:
            MutableRowBuilder for accumulating changes.
        """
        if addr_key not in self._pending:
            self._pending[addr_key] = MutableRowBuilder()
        return self._pending[addr_key]

    def set_field(self, addr_key: int, field_name: str, value: str | bool) -> None:
        """Set a single field on a row.

        Convenience method that handles old value tracking for nickname/comment.

        Args:
            addr_key: The address key to edit.
            field_name: Field name ('nickname', 'comment', 'initial_value', 'retentive').
            value: The new value.
        """
        # Track old values before first change (for index updates and tag sync)
        if field_name == "nickname" and addr_key not in self._nickname_old_values:
            current = self._store.get_visible_row(addr_key)
            if current:
                self._nickname_old_values[addr_key] = current.nickname
        elif field_name == "comment" and addr_key not in self._comment_old_values:
            current = self._store.get_visible_row(addr_key)
            if current:
                self._comment_old_values[addr_key] = current.comment

        builder = self.get_builder(addr_key)
        builder.set_field(field_name, value)

    def get_field(self, addr_key: int, field_name: str) -> str | bool | None:
        """Get a pending field value, or None if not set.

        Args:
            addr_key: The address key.
            field_name: Field name.

        Returns:
            The pending value, or None if not changed in this session.
        """
        if addr_key not in self._pending:
            return None
        return self._pending[addr_key].get_field(field_name)

    def get_effective_value(self, addr_key: int, field_name: str) -> str | bool | None:
        """Get the effective value: pending if set, else current visible value.

        Args:
            addr_key: The address key.
            field_name: Field name.

        Returns:
            The pending value if set, else current visible value, else None.
        """
        # Check pending first
        pending_value = self.get_field(addr_key, field_name)
        if pending_value is not None:
            return pending_value

        # Fall back to current visible state
        current = self._store.get_visible_row(addr_key)
        if current:
            return getattr(current, field_name, None)

        return None

    def has_pending_changes(self) -> bool:
        """Check if any changes have been made in this session.

        Returns:
            True if at least one builder has changes.
        """
        return any(builder.has_changes() for builder in self._pending.values())

    def affected_keys(self) -> set[int]:
        """Get set of address keys that have pending changes.

        Returns:
            Set of addr_keys with pending modifications.
        """
        return {key for key, builder in self._pending.items() if builder.has_changes()}
