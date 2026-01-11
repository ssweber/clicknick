"""Helper functions for renaming nickname segments in the outline."""

import re


def build_rename_pattern(prefix: str, current_text: str, is_array: bool) -> tuple[str, str]:
    """Build regex pattern and replacement template for renaming.

    Args:
        prefix: The full path prefix before the node to rename (e.g., "Tank_Pump_")
        current_text: The current text of the node to rename
        is_array: True if this is an array node (has numeric children)

    Returns:
        Tuple of (pattern, replacement_template) where replacement needs .format(new_text=...)
    """
    if is_array:
        # Array pattern: ^(prefix)(current)(\d+)(_|$)
        # Replacement: \1{new_text}\3\4
        pattern = rf"^({re.escape(prefix)})({re.escape(current_text)})(\d+)(_|$)"
        replacement_template = r"\1{new_text}\3\4"
    else:
        # Non-array pattern: ^(prefix)(current)(_|$)
        # Replacement: \1{new_text}\3
        pattern = rf"^({re.escape(prefix)})({re.escape(current_text)})(_|$)"
        replacement_template = r"\1{new_text}\3"

    return pattern, replacement_template


def apply_rename(
    nickname: str, prefix: str, current_text: str, new_text: str, is_array: bool
) -> str:
    """Apply a rename operation to a nickname.

    Args:
        nickname: The nickname to potentially rename
        prefix: The path prefix (e.g., "Tank_" for renaming Pump in Tank_Pump_Speed)
        current_text: The current segment text to replace
        new_text: The new text to replace it with
        is_array: True if renaming an array node

    Returns:
        The renamed nickname, or the original if no match
    """
    pattern, replacement_template = build_rename_pattern(prefix, current_text, is_array)
    replacement = replacement_template.format(new_text=new_text)
    return re.sub(pattern, replacement, nickname)
