"""Data model for Block tags.

Contains BlockTag dataclass, parsing functions, and block matching utilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from .address_row import AddressRow


class HasComment(Protocol):
    """Protocol for objects that have a comment and optional memory_type attribute."""

    comment: str
    memory_type: str | None


@dataclass
class BlockRange:
    """A matched block range with start/end indices and metadata.

    Represents a complete block from opening to closing tag (or self-closing).
    """

    start_idx: int
    end_idx: int  # Same as start_idx for self-closing tags
    name: str
    bg_color: str | None
    memory_type: str | None = None  # Memory type for filtering in interleaved views


@dataclass
class BlockTag:
    """Result of parsing a block tag from a comment.

    Block tags mark sections in the Address Editor:
    - <BlockName> - opening tag for a range
    - </BlockName> - closing tag for a range
    - <BlockName /> - self-closing tag for a singular point
    - <BlockName bg="#color"> - opening tag with background color
    """

    name: str | None
    tag_type: Literal["open", "close", "self-closing"] | None
    remaining_text: str
    bg_color: str | None


def _extract_bg_attribute(tag_content: str) -> tuple[str, str | None]:
    """Extract bg attribute from tag content.

    Args:
        tag_content: The content between < and > (e.g., 'Name bg="#FFCDD2"')

    Returns:
        Tuple of (name_part, bg_color)
        - name_part: Tag content with bg attribute removed
        - bg_color: The color value, or None if not present
    """
    import re

    # Look for bg="..." or bg='...'
    match = re.search(r'\s+bg=["\']([^"\']+)["\']', tag_content)
    if match:
        bg_color = match.group(1)
        # Remove the bg attribute from the tag content
        name_part = tag_content[: match.start()] + tag_content[match.end() :]
        return name_part.strip(), bg_color
    return tag_content, None


def parse_block_tag(comment: str) -> BlockTag:
    """Parse block tag from the start of a comment.

    Block tags mark sections in the Address Editor:
    - <BlockName> - opening tag for a range (can have text after)
    - </BlockName> - closing tag for a range (can have text after)
    - <BlockName /> - self-closing tag for a singular point
    - <BlockName bg="#color"> - opening tag with background color
    - <BlockName bg="#color" /> - self-closing tag with background color

    Args:
        comment: The comment string to parse

    Returns:
        BlockTag with name, tag_type, remaining_text, and bg_color
    """
    if not comment:
        return BlockTag(None, None, "", None)

    s = comment.strip()
    if not s.startswith("<"):
        return BlockTag(None, None, comment, None)

    end = s.find(">")
    if end == -1:
        return BlockTag(None, None, comment, None)

    tag_content = s[1:end]  # content between < and >
    remaining = s[end + 1 :].strip()

    # Empty tag <> is invalid
    if not tag_content or not tag_content.strip():
        return BlockTag(None, None, comment, None)

    # Self-closing: <Name /> or <Name bg="..." />
    if tag_content.rstrip().endswith("/"):
        content_without_slash = tag_content.rstrip()[:-1].strip()
        name_part, bg_color = _extract_bg_attribute(content_without_slash)
        name = name_part.strip()
        if name:
            return BlockTag(name, "self-closing", remaining, bg_color)
        return BlockTag(None, None, comment, None)

    # Closing: </Name> (no bg attribute on closing tags)
    if tag_content.startswith("/"):
        name = tag_content[1:].strip()
        if name:
            return BlockTag(name, "close", remaining, None)
        return BlockTag(None, None, comment, None)

    # Opening: <Name> or <Name bg="...">
    name_part, bg_color = _extract_bg_attribute(tag_content)
    name = name_part.strip()
    if name:
        return BlockTag(name, "open", remaining, bg_color)

    return BlockTag(None, None, comment, None)


def get_block_type(comment: str) -> str | None:
    """Determine the type of block tag in a comment.

    Args:
        comment: The comment string to check

    Returns:
        'open' for <BlockName>, 'close' for </BlockName>,
        'self-closing' for <BlockName />, or None if not a block tag
    """
    return parse_block_tag(comment).tag_type


def is_block_tag(comment: str) -> bool:
    """Check if a comment starts with a block tag (any type).

    Block tags mark sections in the Address Editor:
    - <BlockName> - opening tag for a range
    - </BlockName> - closing tag for a range
    - <BlockName /> - self-closing tag for a singular point

    Args:
        comment: The comment string to check

    Returns:
        True if the comment starts with any type of block tag
    """
    return get_block_type(comment) is not None


def extract_block_name(comment: str) -> str | None:
    """Extract block name from a comment that starts with a block tag.

    Args:
        comment: The comment string (e.g., "<Motor>Valve info", "</Motor>", "<Spare />")

    Returns:
        The block name (e.g., "Motor", "Spare"), or None if no tag
    """
    return parse_block_tag(comment).name


def strip_block_tag(comment: str) -> str:
    """Strip block tag from a comment, returning any text after the tag.

    Args:
        comment: The comment string (e.g., "<Motor>Valve info")

    Returns:
        Text after the tag (e.g., "Valve info"), or original if no tag
    """
    if not comment:
        return ""
    block_tag = parse_block_tag(comment)
    if block_tag.tag_type is not None:
        return block_tag.remaining_text
    return comment


# Paired memory types that can be in the same block (interleaved in unified view)
PAIRED_BLOCK_TYPES = {
    frozenset({"T", "TD"}),
    frozenset({"CT", "CTD"}),
}


# =============================================================================
# Block Matching Utilities
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
    if memory_types in PAIRED_BLOCK_TYPES:
        return True, None

    types_str = ", ".join(sorted(memory_types))
    return False, f"Blocks cannot span multiple memory types ({types_str})"
