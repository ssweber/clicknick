"""Dependency service for synchronizing related rows.

This service handles automatic synchronization of interleaved pairs (T/TD, CT/CTD).
When a row in a pair is modified, the paired row is automatically updated to match
certain fields (retentive, block tags).

Called automatically by AddressStore during edit_session exit.
"""

from __future__ import annotations

from ..models.blocktag import format_block_tag, parse_block_tag
from ..models.constants import INTERLEAVED_PAIRS


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
