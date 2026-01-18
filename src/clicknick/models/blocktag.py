"""Data model for Block tags.

Contains BlockTag dataclass, parsing functions, and block matching utilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    pass


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


def _is_valid_tag_name(name: str) -> bool:
    """Check if a tag name is valid (not a mathematical expression).

    Valid names must contain at least one letter. This prevents expressions
    like '< 5 >' or '< 10 >' from being parsed as tags.

    Args:
        name: The potential tag name to check

    Returns:
        True if the name contains at least one letter
    """
    return any(c.isalpha() for c in name)


def _try_parse_tag_at(comment: str, start_pos: int) -> BlockTag | None:
    """Try to parse a block tag starting at the given position.

    Args:
        comment: The full comment string
        start_pos: Position of the '<' character

    Returns:
        BlockTag if valid tag found, None otherwise
    """
    end = comment.find(">", start_pos)
    if end == -1:
        return None

    tag_content = comment[start_pos + 1 : end]  # content between < and >

    # Empty tag <> is invalid
    if not tag_content or not tag_content.strip():
        return None

    # Calculate remaining text (text before + text after the tag)
    text_before = comment[:start_pos]
    text_after = comment[end + 1 :]
    remaining = text_before + text_after

    # Self-closing: <Name /> or <Name bg="..." />
    if tag_content.rstrip().endswith("/"):
        content_without_slash = tag_content.rstrip()[:-1].strip()
        name_part, bg_color = _extract_bg_attribute(content_without_slash)
        name = name_part.strip()
        if name and _is_valid_tag_name(name):
            return BlockTag(name, "self-closing", remaining, bg_color)
        return None

    # Closing: </Name> (no bg attribute on closing tags)
    if tag_content.startswith("/"):
        name = tag_content[1:].strip()
        if name and _is_valid_tag_name(name):
            return BlockTag(name, "close", remaining, None)
        return None

    # Opening: <Name> or <Name bg="...">
    name_part, bg_color = _extract_bg_attribute(tag_content)
    name = name_part.strip()
    if name and _is_valid_tag_name(name):
        return BlockTag(name, "open", remaining, bg_color)

    return None


def parse_block_tag(comment: str) -> BlockTag:
    """Parse block tag from anywhere in a comment.

    Block tags mark sections in the Address Editor:
    - <BlockName> - opening tag for a range (can have text before/after)
    - </BlockName> - closing tag for a range (can have text before/after)
    - <BlockName /> - self-closing tag for a singular point
    - <BlockName bg="#color"> - opening tag with background color
    - <BlockName bg="#color" /> - self-closing tag with background color

    The function searches for tags anywhere in the comment, not just at the start.
    Mathematical expressions like '< 5 >' are not parsed as tags.

    Args:
        comment: The comment string to parse

    Returns:
        BlockTag with name, tag_type, remaining_text, and bg_color
    """
    if not comment:
        return BlockTag(None, None, "", None)

    # Search for '<' anywhere in the comment
    pos = 0
    while True:
        start_pos = comment.find("<", pos)
        if start_pos == -1:
            break

        result = _try_parse_tag_at(comment, start_pos)
        if result is not None:
            return result

        # Try next '<' character
        pos = start_pos + 1

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


def format_block_tag(
    name: str,
    tag_type: Literal["open", "close", "self-closing"],
    bg_color: str | None = None,
) -> str:
    """Format a block tag string from its components.

    Args:
        name: The block name (e.g., "Motor", "Alarms")
        tag_type: "open", "close", or "self-closing"
        bg_color: Optional background color (e.g., "#FFCDD2", "Red")

    Returns:
        Formatted block tag string:
        - open: "<Name>" or "<Name bg=\"color\">"
        - close: "</Name>"
        - self-closing: "<Name />" or "<Name bg=\"color\" />"
    """
    bg_attr = f' bg="{bg_color}"' if bg_color else ""

    if tag_type == "self-closing":
        return f"<{name}{bg_attr} />"
    elif tag_type == "close":
        return f"</{name}>"
    else:  # open
        return f"<{name}{bg_attr}>"


# =============================================================================
# Multi-Row Block Operations
# =============================================================================
# NOTE: Multi-row block operations (find_paired_tag_index, find_block_range_indices,
# compute_all_block_ranges, validate_block_span) have been moved to
# services/block_service.py to maintain separation of concerns.
# This module now contains only single-comment parsing operations.
