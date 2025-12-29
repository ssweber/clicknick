"""Data model for Block tags.

Contains BlockTag dataclass and parsing functions.
"""

from dataclasses import dataclass
from typing import Literal


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
