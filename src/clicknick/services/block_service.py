"""Block service for coordinating block tag operations and colors.

Contains multi-row block operations extracted from models/blocktag.py.
Single-comment parsing remains in blocktag.py; this service handles
operations that span multiple rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.blocktag import BlockRange, HasComment, parse_block_tag
from ..models.constants import INTERLEAVED_TYPE_PAIRS

if TYPE_CHECKING:
    from ..data.shared_data import SharedAddressData
    from ..models.address_row import AddressRow
    from ..models.blocktag import BlockTag


# =============================================================================
# Multi-Row Block Operations (extracted from blocktag.py)
# =============================================================================


def find_paired_tag_index(
    rows: list[HasComment], row_idx: int, tag: BlockTag | None = None
) -> int | None:
    """Find the row index of the paired open/close block tag.

    Uses nesting depth to correctly match tags when there are multiple
    blocks with the same name (nested or separate sections).

    Only matches tags within the same memory_type (if available) to correctly
    handle interleaved views like T/TD where each type has its own tags.

    Args:
        rows: List of objects with .comment and optional .memory_type attributes
        row_idx: Index of the row containing the tag
        tag: Parsed BlockTag, or None to parse from rows[row_idx].comment

    Returns:
        Row index of the paired tag, or None if not found
    """
    if tag is None:
        tag = parse_block_tag(rows[row_idx].comment)

    if not tag.name or tag.tag_type == "self-closing":
        return None

    # Get memory type of source row (if available) for filtering
    source_type = getattr(rows[row_idx], "memory_type", None)

    if tag.tag_type == "open":
        # Search forward for matching close tag, respecting nesting
        depth = 1
        for i in range(row_idx + 1, len(rows)):
            # Skip rows with different memory type
            if source_type and getattr(rows[i], "memory_type", None) != source_type:
                continue
            other_tag = parse_block_tag(rows[i].comment)
            if other_tag.name == tag.name:
                if other_tag.tag_type == "open":
                    depth += 1
                elif other_tag.tag_type == "close":
                    depth -= 1
                    if depth == 0:
                        return i
    elif tag.tag_type == "close":
        # Search backward for matching open tag, respecting nesting
        depth = 1
        for i in range(row_idx - 1, -1, -1):
            # Skip rows with different memory type
            if source_type and getattr(rows[i], "memory_type", None) != source_type:
                continue
            other_tag = parse_block_tag(rows[i].comment)
            if other_tag.name == tag.name:
                if other_tag.tag_type == "close":
                    depth += 1
                elif other_tag.tag_type == "open":
                    depth -= 1
                    if depth == 0:
                        return i
    return None


def find_block_range_indices(
    rows: list[HasComment], row_idx: int, tag: BlockTag | None = None
) -> tuple[int, int] | None:
    """Find the (start_idx, end_idx) range for a block tag.

    Uses nesting depth to correctly match tags when there are multiple
    blocks with the same name.

    Args:
        rows: List of objects with a .comment attribute
        row_idx: Index of the row containing the tag
        tag: Parsed BlockTag, or None to parse from rows[row_idx].comment

    Returns:
        Tuple of (start_idx, end_idx) inclusive, or None if tag is invalid
    """
    if tag is None:
        tag = parse_block_tag(rows[row_idx].comment)

    if not tag.name or not tag.tag_type:
        return None

    if tag.tag_type == "self-closing":
        return (row_idx, row_idx)

    if tag.tag_type == "open":
        paired_idx = find_paired_tag_index(rows, row_idx, tag)
        if paired_idx is not None:
            return (row_idx, paired_idx)
        # No close found - just the opening row
        return (row_idx, row_idx)

    if tag.tag_type == "close":
        paired_idx = find_paired_tag_index(rows, row_idx, tag)
        if paired_idx is not None:
            return (paired_idx, row_idx)
        # No open found - just the closing row
        return (row_idx, row_idx)

    return None


def compute_all_block_ranges(rows: list[HasComment]) -> list[BlockRange]:
    """Compute all block ranges from a list of rows using stack-based matching.

    Correctly handles nested blocks and multiple blocks with the same name.
    Only matches open/close tags within the same memory_type to handle
    interleaved views like T/TD correctly.

    Args:
        rows: List of objects with .comment and optional .memory_type attributes

    Returns:
        List of BlockRange objects, sorted by start_idx
    """
    ranges: list[BlockRange] = []

    # Stack for tracking open tags: (memory_type, name) -> [(start_idx, bg_color), ...]
    # Using (memory_type, name) as key ensures T's <Timers> and TD's <Timers> are separate
    open_tags: dict[tuple[str | None, str], list[tuple[int, str | None]]] = {}

    for row_idx, row in enumerate(rows):
        tag = parse_block_tag(row.comment)
        if not tag.name:
            continue

        memory_type = getattr(row, "memory_type", None)
        stack_key = (memory_type, tag.name)

        if tag.tag_type == "self-closing":
            ranges.append(BlockRange(row_idx, row_idx, tag.name, tag.bg_color, memory_type))
        elif tag.tag_type == "open":
            if stack_key not in open_tags:
                open_tags[stack_key] = []
            open_tags[stack_key].append((row_idx, tag.bg_color))
        elif tag.tag_type == "close":
            if stack_key in open_tags and open_tags[stack_key]:
                start_idx, bg_color = open_tags[stack_key].pop()
                ranges.append(BlockRange(start_idx, row_idx, tag.name, bg_color, memory_type))

    # Handle unclosed tags as singular points
    for (mem_type, name), stack in open_tags.items():
        for start_idx, bg_color in stack:
            ranges.append(BlockRange(start_idx, start_idx, name, bg_color, mem_type))

    # Sort by start index
    ranges.sort(key=lambda r: r.start_idx)
    return ranges


def validate_block_span(rows: list[AddressRow]) -> tuple[bool, str | None]:
    """Validate that a block span doesn't cross memory type boundaries.

    Blocks should only contain addresses of the same memory type,
    with the exception of paired types (T+TD, CT+CTD) which are
    interleaved and can share blocks.

    Args:
        rows: List of AddressRow objects that would be in the block

    Returns:
        Tuple of (is_valid, error_message).
        - (True, None) if all rows have compatible memory types
        - (False, error_message) if rows span incompatible memory types
    """
    if not rows:
        return True, None

    # Get unique memory types in the selection
    memory_types = {row.memory_type for row in rows}

    if len(memory_types) == 1:
        return True, None

    # Check if it's a valid paired type combination
    if frozenset(memory_types) in INTERLEAVED_TYPE_PAIRS:
        return True, None

    types_str = ", ".join(sorted(memory_types))
    return False, f"Blocks cannot span multiple memory types ({types_str})"


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
    def auto_update_matching_block_tag(
        rows: list[AddressRow],
        row_idx: int,
        old_tag: BlockTag,
        new_tag: BlockTag | None,
    ) -> int | None:
        """Auto-update or delete the matching open/close block tag.

        When a user renames or deletes an opening tag (<Block>), automatically
        update the matching closing tag (</Block>) to match, and vice versa.
        This keeps block tag pairs synchronized.

        Note: This handles block tag pairing (open↔close), NOT interleaved
        type pairing (T↔TD). For interleaved pairs, see RowDependencyService.

        Args:
            rows: List of AddressRow objects
            row_idx: Index of row with changed tag
            old_tag: The old block tag
            new_tag: The new block tag (or None if deleted)

        Returns:
            Index of matching row if updated, None otherwise
        """
        from ..models.blocktag import strip_block_tag

        if old_tag.tag_type not in ("open", "close"):
            return None

        paired_idx = find_paired_tag_index(rows, row_idx, old_tag)  # Use module-level function
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
    def compute_block_colors_map(rows: list[AddressRow]) -> dict[int, str]:
        """Compute block color map for a list of rows.

        This is a helper method for UI components that need to display
        block colors without modifying AddressRow objects.

        Args:
            rows: List of AddressRow objects

        Returns:
            Dict mapping row index (in rows list) to bg color string
        """
        ranges = compute_all_block_ranges(rows)  # Use module-level function

        # Filter to only blocks with colors
        colored_ranges = [r for r in ranges if r.bg_color]

        # Build row_idx -> color map, with inner blocks overriding outer
        color_map: dict[int, str] = {}
        for r in colored_ranges:
            for row_idx in range(r.start_idx, r.end_idx + 1):
                color_map[row_idx] = r.bg_color

        return color_map
