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

