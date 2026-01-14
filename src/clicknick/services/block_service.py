"""Block service for coordinating block tag operations and colors.

This service wraps existing block tag parsing logic from models/blocktag.py
and provides methods to update precomputed block colors on AddressRow objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..models.address_row import AddressRow
    from ..models.blocktag import BlockTag


class BlockService:
    """Coordinates block tag operations and precomputes block colors.

    Wraps existing block tag parsing logic from models/blocktag.py.
    Updates AddressRow.block_color in-place for affected rows.

    All methods are static as the service is stateless.
    """

    @staticmethod
    def update_colors(
        shared_data: SharedAddressData,
        affected_keys: set[int] | None = None,
    ) -> set[int]:
        """Update block_color on AddressRow objects after comment changes.

        When comments change, re-scan blocks and update precomputed colors
        on ALL rows in affected block ranges. This may affect more rows
        than just those with comment changes (e.g., closing tag affects
        all rows in the block).

        Args:
            shared_data: The SharedAddressData instance
            affected_keys: Optional set of addr_keys with comment changes.
                          If None, updates all rows (used on initial load).

        Returns:
            Set of ALL addr_keys affected (may be larger due to block ranges)
        """
        from ..models.blocktag import compute_all_block_ranges

        # Get unified view (all rows in order)
        view = shared_data.get_unified_view()
        if not view:
            # No unified view yet - return affected keys as-is
            return affected_keys or set()

        # Compute all block ranges from current comments
        ranges = compute_all_block_ranges(view.rows)

        # Build row_idx -> color map (inner blocks override outer)
        color_map: dict[int, str] = {}
        for r in ranges:
            if r.bg_color:
                for row_idx in range(r.start_idx, r.end_idx + 1):
                    # Inner blocks override outer blocks
                    color_map[row_idx] = r.bg_color

        # Update AddressRow.block_color for ALL rows
        all_affected = set()
        for row_idx, row in enumerate(view.rows):
            new_color = color_map.get(row_idx)
            if row.block_color != new_color:
                row.block_color = new_color
                all_affected.add(row.addr_key)

        # If affected_keys was provided, include them (comment changes)
        if affected_keys:
            all_affected.update(affected_keys)

        return all_affected

    @staticmethod
    def auto_update_paired_tag(
        rows: list[AddressRow],
        row_idx: int,
        old_tag: BlockTag,
        new_tag: BlockTag | None,
    ) -> int | None:
        """Auto-update or delete paired block tag.

        When a user renames or deletes an opening/closing tag, automatically
        update the paired tag to match. This keeps blocks synchronized.

        Args:
            rows: List of AddressRow objects
            row_idx: Index of row with changed tag
            old_tag: The old block tag
            new_tag: The new block tag (or None if deleted)

        Returns:
            Index of paired row if updated, None otherwise
        """
        from ..models.blocktag import find_paired_tag_index, parse_block_tag, strip_block_tag

        if old_tag.tag_type not in ("open", "close"):
            return None

        paired_idx = find_paired_tag_index(rows, row_idx, old_tag)
        if paired_idx is None:
            return None

        paired_row = rows[paired_idx]

        if new_tag is None or not new_tag.name:
            # Tag was deleted - delete paired tag too
            paired_row.comment = strip_block_tag(paired_row.comment)
        elif new_tag.name != old_tag.name:
            # Tag was renamed - rename paired tag too
            paired_tag = parse_block_tag(paired_row.comment)
            if paired_tag.name == old_tag.name:
                # Replace tag name, keep remaining text
                prefix = "</" if paired_tag.tag_type == "close" else "<"
                # Preserve bg attribute from old tag if opening tag
                bg_attr = ""
                if paired_tag.tag_type == "open" and paired_tag.bg_color:
                    bg_attr = f' bg="{paired_tag.bg_color}"'
                suffix = ">"
                new_comment = prefix + new_tag.name + bg_attr + suffix
                if paired_tag.remaining_text:
                    new_comment += " " + paired_tag.remaining_text
                paired_row.comment = new_comment

        return paired_idx

    @staticmethod
    def find_interleaved_pair_idx(
        rows: list[AddressRow],
        row_idx: int,
    ) -> int | None:
        """Find the index of the paired row for interleaved types (T+TD, CT+CTD).

        For interleaved types, rows at the same address should share block tags.
        This finds the partner row (e.g., TD1 for T1, or T1 for TD1).

        Args:
            rows: List of AddressRow objects
            row_idx: Index of the row in the list

        Returns:
            Index of the paired row, or None if no pair exists
        """
        from ..models.blocktag import PAIRED_BLOCK_TYPES

        if row_idx < 0 or row_idx >= len(rows):
            return None

        row = rows[row_idx]

        # Check if this is a paired type
        paired_type = None
        for pair in PAIRED_BLOCK_TYPES:
            if row.memory_type in pair:
                # Find the other type in the pair
                for t in pair:
                    if t != row.memory_type:
                        paired_type = t
                        break
                break

        if not paired_type:
            return None

        # Search nearby for the paired row (interleaved, so should be adjacent)
        # Check the row before and after
        for offset in [-1, 1]:
            check_idx = row_idx + offset
            if 0 <= check_idx < len(rows):
                check_row = rows[check_idx]
                if check_row.memory_type == paired_type and check_row.address == row.address:
                    return check_idx

        return None

    @staticmethod
    def compute_block_colors_map(rows: list[AddressRow]) -> dict[int, str]:
        """Compute block color map for a list of rows.

        This is a helper method for UI components that need to display
        block colors without modifying AddressRow objects.

        Args:
            rows: List of AddressRow objects

        Returns:
            Dict mapping row index (in rows list) to bg color string
        """
        from ..models.blocktag import compute_all_block_ranges

        ranges = compute_all_block_ranges(rows)

        # Filter to only blocks with colors
        colored_ranges = [r for r in ranges if r.bg_color]

        # Build row_idx -> color map, with inner blocks overriding outer
        color_map: dict[int, str] = {}
        for r in colored_ranges:
            for row_idx in range(r.start_idx, r.end_idx + 1):
                color_map[row_idx] = r.bg_color

        return color_map
