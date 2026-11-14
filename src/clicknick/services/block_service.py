"""Block service for coordinating block tag operations and colors.

This service provides editor-level coordination for block tags.
Core block tag operations (parsing, range computation) come from pyclickplc.blocks.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pyclickplc.blocks import (
    compute_all_block_ranges,
    format_block_tag,
    parse_block_tag,
)

if TYPE_CHECKING:
    from pyclickplc.blocks import BlockTag

    from ..models.address_row import AddressRow


__all__ = ["BlockService", "compute_block_colors"]


def compute_block_colors(rows: list[AddressRow]) -> dict[int, str]:
    """Compute block background colors for each row index.

    Parses block tags from row comments to determine which rows
    should have colored row indices. Nested blocks override outer blocks.
    Only colors rows matching the block's memory_type (for interleaved views).

    Args:
        rows: List of AddressRow to process

    Returns:
        Dict mapping row index to bg color string
    """
    # Get all block ranges using centralized function
    ranges = compute_all_block_ranges(rows)

    # Filter to only blocks with colors
    colored_ranges = [r for r in ranges if r.bg_color]

    # Build row_idx -> color map, with inner blocks overriding outer
    # Sort by range size descending (larger ranges first)
    # This ensures inner (smaller) blocks are processed last and override
    colored_ranges.sort(key=lambda r: -(r.end_idx - r.start_idx))

    row_colors: dict[int, str] = {}
    for block in colored_ranges:
        for idx in range(block.start_idx, block.end_idx + 1):
            # Only color rows matching the block's memory_type (for interleaved views)
            if block.memory_type and rows[idx].memory_type != block.memory_type:
                continue
            row_colors[idx] = block.bg_color  # type: ignore[assignment]

    return row_colors


_DOTTED_NAME_WITH_FLAG_RE = re.compile(
    r"^(?P<base>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?P<suffix>\s.+)$"
)


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
    # Structured block metadata keeps everything after ':' intact.
    # Example: "Timer:block" -> "Timer_D:block"
    split_at = name.find(":")
    if split_at != -1:
        base_name = name[:split_at]
        suffix = name[split_at:]
    else:
        base_name = name
        suffix = ""

        # Dotted names may carry trailing flags/metadata after a space.
        # Example: "Custom.TasksStatus READONLY" -> "Custom.TasksStatus_D READONLY"
        dotted_match = _DOTTED_NAME_WITH_FLAG_RE.fullmatch(name)
        if dotted_match is not None:
            base_name = dotted_match.group("base")
            suffix = dotted_match.group("suffix")

    # Determine if source and target are base or data types
    base_types = {"T", "CT"}
    data_types = {"TD", "CTD"}

    source_is_base = source_type in base_types
    target_is_base = target_type in base_types
    source_is_data = source_type in data_types
    target_is_data = target_type in data_types

    if source_is_base and target_is_data:
        # T -> TD or CT -> CTD: add _D suffix if not already present
        if not base_name.endswith("_D"):
            return base_name + "_D" + suffix
        return base_name + suffix

    if source_is_data and target_is_base:
        # TD -> T or CTD -> CT: remove _D suffix if present
        if base_name.endswith("_D"):
            return base_name[:-2] + suffix
        return base_name + suffix

    # Same type category (shouldn't happen in normal use)
    return name


def _block_tag_span(comment: str) -> tuple[int, int] | None:
    """Return where the tag parse_block_tag finds sits in *comment* (start, end exclusive)."""
    pos = 0
    while (start := comment.find("<", pos)) != -1:
        end = comment.find(">", start)
        if end == -1:
            return None
        # The text from this '<' to the next '>' is the tag exactly when it
        # parses on its own with nothing left over; parse_block_tag tries the
        # same '<' positions in the same order.
        candidate = parse_block_tag(comment[start : end + 1])
        if candidate.tag_type is not None and candidate.remaining_text == "":
            return start, end + 1
        pos = start + 1
    return None


def add_block_tag(comment: str, tag_text: str) -> str:
    """Append a block tag to a comment, after one space, as Add Block does."""
    return f"{comment} {tag_text}" if comment else tag_text


def remove_block_tag(comment: str) -> str:
    """Remove the block tag and the one space that set it apart from the text.

    The inverse of add_block_tag; the rest of the comment is kept as it is.
    """
    span = _block_tag_span(comment)
    if span is None:
        return comment
    before, after = comment[: span[0]], comment[span[1] :]
    if after.startswith(" ") and (not before or before.endswith(" ")):
        after = after[1:]
    elif before.endswith(" ") and not after:
        before = before[:-1]
    return before + after


def replace_block_tag(comment: str, tag_text: str) -> str:
    """Put *tag_text* where the comment's block tag is, or append it if there is none."""
    span = _block_tag_span(comment)
    if span is None:
        return add_block_tag(comment, tag_text)
    return comment[: span[0]] + tag_text + comment[span[1] :]


def rename_block_tag(comment: str, new_name: str) -> str:
    """Change only the block tag's name; its colour, spacing and the text around it stay."""
    span = _block_tag_span(comment)
    if span is None:
        return comment
    tag = parse_block_tag(comment)
    tag_text = comment[span[0] : span[1]]
    at = tag_text.find(tag.name)
    if at == -1:
        # The name is split by its bg attribute (`<A bg="x" B>`): write the tag anew.
        renamed = format_block_tag(new_name, tag.tag_type, tag.bg_color)
    else:
        renamed = tag_text[:at] + new_name + tag_text[at + len(tag.name) :]
    return comment[: span[0]] + renamed + comment[span[1] :]


def same_block_tag(a: BlockTag, b: BlockTag) -> bool:
    """True when two parsed tags are the same tag (name, kind and colour)."""
    return a.name == b.name and a.tag_type == b.tag_type and a.bg_color == b.bg_color


class BlockService:
    """Block tag cascades: what a row's tag change means for the rows tied to it.

    Each method takes the tag before and after the edit and returns the other
    row's new comment, or None to leave it alone. Callers decide which rows to
    pass; these never look at more than the one comment they are given.
    """

    @staticmethod
    def matching_tag_comment(
        match_comment: str, old_tag: BlockTag, new_tag: BlockTag
    ) -> str | None:
        """The open/close partner's comment after its block tag went from old to new.

        A deleted tag removes the partner's tag; a renamed one renames it in
        place. A change of colour or kind alone leaves the partner as it is.
        """
        if new_tag.name is None:
            updated = remove_block_tag(match_comment)
        elif new_tag.name != old_tag.name:
            updated = rename_block_tag(match_comment, new_tag.name)
        else:
            return None
        return updated if updated != match_comment else None

    @staticmethod
    def pair_tag_comment(
        pair_comment: str,
        old_tag: BlockTag,
        new_tag: BlockTag,
        source_type: str,
        pair_type: str,
    ) -> str | None:
        """The T/TD (CT/CTD) pair's comment after the source row's tag went from old to new.

        The pair's block name carries the _D suffix on TD/CTD. A pair without a
        tag gets the new one appended when the tag was added or renamed (a colour
        or kind change alone leaves it alone); a pair holding the old block's tag
        has it renamed in place, re-coloured or removed; a pair holding some other
        block's tag is left alone.
        """
        pair_tag = parse_block_tag(pair_comment)
        if pair_tag.name is None:
            if new_tag.name is None or new_tag.name == old_tag.name:
                return None
            new_name = _transform_block_name_for_pair(new_tag.name, source_type, pair_type)
            return add_block_tag(
                pair_comment, format_block_tag(new_name, new_tag.tag_type, new_tag.bg_color)
            )

        if (
            old_tag.name is None
            or pair_tag.name != _transform_block_name_for_pair(old_tag.name, source_type, pair_type)
            or pair_tag.tag_type != old_tag.tag_type
        ):
            return None

        if new_tag.name is None:
            updated = remove_block_tag(pair_comment)
        else:
            new_name = _transform_block_name_for_pair(new_tag.name, source_type, pair_type)
            if new_tag.tag_type == pair_tag.tag_type and new_tag.bg_color == pair_tag.bg_color:
                updated = rename_block_tag(pair_comment, new_name)
            else:
                updated = replace_block_tag(
                    pair_comment, format_block_tag(new_name, new_tag.tag_type, new_tag.bg_color)
                )
        return updated if updated != pair_comment else None
