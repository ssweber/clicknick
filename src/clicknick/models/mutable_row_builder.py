"""Mutable row builder for accumulating changes to AddressRow.

MutableRowBuilder provides a mutable interface for building changes to
an AddressRow. Changes are accumulated and then frozen into an immutable
AddressRow via the freeze() method.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .address_row import AddressRow


@dataclass
class MutableRowBuilder:
    """Accumulator for building changes to an AddressRow.

    All fields are optional (None means "no change"). When freeze() is called,
    non-None values are applied to the base row to create a new immutable row.

    Usage:
        builder = MutableRowBuilder()
        builder.nickname = "NewName"
        builder.comment = "Updated comment"
        new_row = builder.freeze(base_row)
    """

    # Content fields (user-editable)
    nickname: str | None = None
    comment: str | None = None
    initial_value: str | None = None
    retentive: bool | None = None

    def has_changes(self) -> bool:
        """Check if any fields have been set.

        Returns:
            True if at least one field has a non-None value.
        """
        return (
            self.nickname is not None
            or self.comment is not None
            or self.initial_value is not None
            or self.retentive is not None
        )

    def freeze(self, base: AddressRow) -> AddressRow:
        """Apply accumulated changes to base row and return new immutable row.

        Uses dataclasses.replace() to create a new row with only the
        fields that were set in this builder.

        Args:
            base: The base AddressRow to apply changes to.

        Returns:
            New AddressRow with changes applied.
        """
        # Build kwargs for only fields that were explicitly set
        changes: dict = {}

        if self.nickname is not None:
            changes["nickname"] = self.nickname
        if self.comment is not None:
            changes["comment"] = self.comment
        if self.initial_value is not None:
            changes["initial_value"] = self.initial_value
        if self.retentive is not None:
            changes["retentive"] = self.retentive

        if not changes:
            return base

        return replace(base, **changes)

    def get_field(self, field_name: str) -> str | bool | None:
        """Get a field value by name.

        Args:
            field_name: One of 'nickname', 'comment', 'initial_value', 'retentive'

        Returns:
            The field value, or None if not set.

        Raises:
            AttributeError: If field_name is not a valid field.
        """
        return getattr(self, field_name)

    def set_field(self, field_name: str, value: str | bool | None) -> None:
        """Set a field value by name.

        Args:
            field_name: One of 'nickname', 'comment', 'initial_value', 'retentive'
            value: The value to set.

        Raises:
            AttributeError: If field_name is not a valid field.
        """
        setattr(self, field_name, value)

    def copy(self) -> MutableRowBuilder:
        """Create a copy of this builder.

        Returns:
            New MutableRowBuilder with same field values.
        """
        return MutableRowBuilder(
            nickname=self.nickname,
            comment=self.comment,
            initial_value=self.initial_value,
            retentive=self.retentive,
        )
