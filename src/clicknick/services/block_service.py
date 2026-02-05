"""Block service for coordinating block tag operations and colors.

This service provides editor-level coordination for block tags.
Core block tag model operations (parsing, range computation) are in models/blocktag.py.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pyclickplc.blocks import (
    BlockRange,
    HasComment,
    compute_all_block_ranges,
    find_block_range_indices,
    find_paired_tag_index,
    format_block_tag,
    get_all_block_names,
    is_block_name_available,
    parse_block_tag,
    strip_block_tag,
    validate_block_span,
)

if TYPE_CHECKING:
    from pyclickplc.blocks import BlockTag

    from ..data.address_store import AddressStore
    from ..models.address_row import AddressRow


# Re-export functions from blocktag for backwards compatibility
__all__ = [
    "BlockRange",
    "BlockService",
    "HasComment",
    "compute_all_block_ranges",
    "find_block_range_indices",
    "find_paired_tag_index",
    "get_all_block_names",
    "is_block_name_available",
    "validate_block_span",
]


def _transform_block_name_for_pair(name: str, source_type: str, target_type: str) -> str:
    """Transform block name for interleaved pair sync.

    Convention:
    - T/CT (base types) use plain names: "Pumps"
    - TD/CTD (data types) use "_D" suffix: "Pumps_D"

    Args:
        name: Original block name
        source_type: Memory type of source ("T", "TD", "CT", "CTD")
        target_type: Memory type of target

    Returns:
        Transformed block name for the target type
    """
    # Determine if source and target are base or data types
    base_types = {"T", "CT"}
    data_types = {"TD", "CTD"}

    source_is_base = source_type in base_types
    target_is_base = target_type in base_types
    source_is_data = source_type in data_types
    target_is_data = target_type in data_types

    if source_is_base and target_is_data:
        # T -> TD or CT -> CTD: add _D suffix if not already present
        if not name.endswith("_D"):
            return name + "_D"
        return name

    if source_is_data and target_is_base:
        # TD -> T or CTD -> CT: remove _D suffix if present
        if name.endswith("_D"):
            return name[:-2]
        return name

    # Same type category (shouldn't happen in normal use)
    return name


class BlockService:
    """Coordinates block tag operations and precomputes block colors.

    Provides editor-level coordination for block tags. Core parsing and
    range computation is delegated to models/blocktag.py.
    """

    @staticmethod
    def update_colors(
        store: AddressStore,
        affected_keys: set[int] | None = None,
    ) -> set[int]:
        """Update block_color on visible rows after comment changes.

        When comments change, re-scan blocks and update precomputed colors
        on ALL rows in affected block ranges. This may affect more rows
        than just those with comment changes.

        Args:
            store: The AddressStore instance
            affected_keys: Optional set of addr_keys with comment changes.
                          If None, updates all rows (used on initial load).

        Returns:
            Set of ALL addr_keys affected (may be larger due to block ranges)
        """
        # Get unified view (all rows in order)
        view = store.get_unified_view()
        if not view:
            return affected_keys or set()

        # Compute all block ranges from current comments
        ranges = compute_all_block_ranges(view.rows)

        # Build row_idx -> color map (inner blocks override outer)
        color_map: dict[int, str | None] = {}
        for r in ranges:
            if r.bg_color:
                for row_idx in range(r.start_idx, r.end_idx + 1):
                    color_map[row_idx] = r.bg_color

        # Update block_color on visible rows
        all_affected = set()
        for row_idx, row in enumerate(view.rows):
            new_color = color_map.get(row_idx)
            if row.block_color != new_color:
                updated = replace(row, block_color=new_color)
                store.visible_state[row.addr_key] = updated
                if row.addr_key in store.user_overrides:
                    store.user_overrides[row.addr_key] = updated
                all_affected.add(row.addr_key)

        if affected_keys:
            all_affected.update(affected_keys)

        return all_affected

    @staticmethod
    def auto_update_matching_block_tag(
        rows: list[AddressRow],
        row_idx: int,
        old_tag: BlockTag,
        new_tag: BlockTag | None,
    ) -> tuple[int, str] | None:
        """Auto-update or delete the matching open/close block tag.

        When a user renames or deletes an opening tag (<Block>), automatically
        update the matching closing tag (</Block>) to match, and vice versa.
        This keeps block tag pairs synchronized.

        Args:
            rows: List of AddressRow objects
            row_idx: Index of row with changed tag
            old_tag: The old block tag
            new_tag: The new block tag (or None if deleted)

        Returns:
            Tuple of (paired_row_index, new_comment) if updated, None otherwise
        """
        if old_tag.tag_type not in ("open", "close"):
            return None

        paired_idx = find_paired_tag_index(rows, row_idx, old_tag)
        if paired_idx is None:
            return None

        paired_row = rows[paired_idx]

        if new_tag is None or not new_tag.name:
            # Tag was deleted - delete paired tag too
            new_comment = strip_block_tag(paired_row.comment)
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
            else:
                return None
        else:
            return None

        return (paired_idx, new_comment)

    @staticmethod
    def apply_block_tag(source_comment: str, target_comment: str) -> str | None:
        """Apply block tag from source comment to target comment.

        Preserves the target's non-block text while updating/adding/removing
        the block tag to match the source.

        Args:
            source_comment: The comment to apply FROM (e.g., T1's comment)
            target_comment: The comment to apply TO (e.g., TD1's comment)

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

    @staticmethod
    def apply_block_tag_for_interleaved_pair(
        source_comment: str,
        target_comment: str,
        source_type: str,
        target_type: str,
    ) -> str | None:
        """Apply block tag from source to target with _D suffix transformation.

        For T/TD and CT/CTD pairs, block names use a naming convention:
        - T/CT blocks use base name (e.g., "Pumps")
        - TD/CTD blocks use "_D" suffix (e.g., "Pumps_D")

        This ensures unique block names across all memory types while
        maintaining the logical pairing between timer/counter pairs.

        Args:
            source_comment: The comment to apply FROM
            target_comment: The comment to apply TO
            source_type: Memory type of source (e.g., "T", "TD")
            target_type: Memory type of target (e.g., "TD", "T")

        Returns:
            The updated target comment, or None if no change needed
        """
        source_tag = parse_block_tag(source_comment)
        target_tag = parse_block_tag(target_comment)

        # Get target's non-block text (preserve it)
        target_remaining = target_tag.remaining_text.strip()

        if source_tag.name is None:
            # Source has no block tag - remove from target
            if target_tag.name is None:
                return None  # No change needed
            return target_remaining if target_remaining else ""

        # Transform the block name based on direction
        transformed_name = _transform_block_name_for_pair(source_tag.name, source_type, target_type)

        # Check if block tags are already the same after transformation
        if (
            transformed_name == target_tag.name
            and source_tag.tag_type == target_tag.tag_type
            and source_tag.bg_color == target_tag.bg_color
        ):
            return None  # No change needed

        # Build new tag with transformed name
        new_tag = format_block_tag(transformed_name, source_tag.tag_type, source_tag.bg_color)
        if target_remaining:
            return f"{target_remaining} {new_tag}"
        else:
            return new_tag
