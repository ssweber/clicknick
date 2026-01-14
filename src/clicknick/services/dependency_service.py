"""Dependency service for synchronizing related rows.

This service handles automatic synchronization of interleaved pairs (T/TD, CT/CTD).
When a row in a pair is modified, the paired row is automatically updated to match
certain fields (retentive, block tags).

Called automatically by SharedAddressData during edit_session exit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.blocktag import format_block_tag, parse_block_tag

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..models.address_row import AddressRow

# Paired memory types that share retentive settings
# T (Timer) pairs with TD (Timer Done)
# CT (Counter) pairs with CTD (Counter Done)
INTERLEAVED_PAIRS: dict[str, str] = {
    "T": "TD",
    "TD": "T",
    "CT": "CTD",
    "CTD": "CT",
}


def _sync_block_tag(source_comment: str, target_comment: str) -> str | None:
    """Sync block tag from source comment to target comment.

    Preserves the target's non-block text while updating/adding/removing
    the block tag to match the source.

    Args:
        source_comment: The comment to sync FROM (e.g., T1's comment)
        target_comment: The comment to sync TO (e.g., TD1's comment)

    Returns:
        The updated target comment, or None if no change needed
    """
    source_tag = parse_block_tag(source_comment)
    target_tag = parse_block_tag(target_comment)

    # Check if block tags are already the same
    if (
        source_tag.name == target_tag.name
        and source_tag.tag_type == target_tag.tag_type
        and source_tag.bg_color == target_tag.bg_color
    ):
        return None  # No change needed

    # Get target's non-block text (preserve it)
    target_remaining = target_tag.remaining_text.strip()

    if source_tag.name is None:
        # Source has no block tag - remove from target
        return target_remaining if target_remaining else ""
    else:
        # Source has a block tag - add/update on target
        new_tag = format_block_tag(source_tag.name, source_tag.tag_type, source_tag.bg_color)
        if target_remaining:
            return f"{target_remaining} {new_tag}"
        else:
            return new_tag


class RowDependencyService:
    """Synchronizes related rows in interleaved pairs.

    In unified view, T/TD and CT/CTD rows are interleaved (T1, TD1, T2, TD2...).
    When one row's retentive setting changes, the paired row should match.

    All methods are static as the service is stateless.
    """

    @staticmethod
    def find_paired_row(
        shared_data: SharedAddressData,
        row: AddressRow,
    ) -> AddressRow | None:
        """Find the paired row for an interleaved type.

        Args:
            shared_data: The SharedAddressData instance
            row: The row to find a pair for

        Returns:
            The paired AddressRow, or None if no pair exists
        """
        paired_type = INTERLEAVED_PAIRS.get(row.memory_type)
        if not paired_type:
            return None

        # Build the paired addr_key (same address, different type)
        from ..models.address_row import get_addr_key

        paired_key = get_addr_key(paired_type, row.address)
        return shared_data.all_rows.get(paired_key)

    @staticmethod
    def sync_interleaved_pairs(
        shared_data: SharedAddressData,
        affected_keys: set[int],
    ) -> set[int]:
        """Sync retentive and comment for interleaved pairs.

        When a T/TD or CT/CTD row is modified, the paired row should be
        updated to match. This ensures interleaved pairs stay in sync for:
        - Retentive settings (T1 and TD1 must have same retentive value)
        - Comments/block tags (T1 and TD1 should share block membership)

        Args:
            shared_data: The SharedAddressData instance
            affected_keys: Set of addr_keys that were modified

        Returns:
            Set of additional addr_keys that were synced (may be empty)
        """
        synced_keys: set[int] = set()

        for addr_key in affected_keys:
            row = shared_data.all_rows.get(addr_key)
            if not row:
                continue

            # Only sync if this is an interleaved type
            if row.memory_type not in INTERLEAVED_PAIRS:
                continue

            # Find the paired row
            paired_row = RowDependencyService.find_paired_row(shared_data, row)
            if not paired_row:
                continue

            # Skip if paired row was also edited (user explicitly set both)
            if paired_row.addr_key in affected_keys:
                continue

            # Sync retentive if different
            if paired_row.retentive != row.retentive:
                paired_row.retentive = row.retentive
                synced_keys.add(paired_row.addr_key)

            # Sync block tag (preserves paired row's non-block comment text)
            new_comment = _sync_block_tag(row.comment, paired_row.comment)
            if new_comment is not None:
                paired_row.comment = new_comment
                synced_keys.add(paired_row.addr_key)

        return synced_keys
