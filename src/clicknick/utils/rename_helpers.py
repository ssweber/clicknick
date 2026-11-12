"""Helper functions for renaming nickname segments in the outline."""

import re


def build_rename_pattern(
    prefix: str, current_text: str, is_array: bool, exact: bool = False
) -> tuple[str, str]:
    """Build regex pattern and replacement template for renaming.

    Args:
        prefix: The full path prefix before the node to rename (e.g., "Tank_Pump_")
        current_text: The current text of the node to rename
        is_array: True if this is an array node (has numeric children)
        exact: True to rename only the nickname ``prefix + current_text``, not the
            nicknames that continue it

    Returns:
        Tuple of (pattern, replacement_template) where the replacement is made with
        `rename_replacement`
    """
    if is_array:
        # Array pattern: ^(prefix)(current)(\d+)(_|$)
        pattern = rf"^({re.escape(prefix)})({re.escape(current_text)})(\d+)(_|$)"
        replacement_template = r"\g<1>{new_text}\g<3>\g<4>"
    else:
        # Non-array pattern: ^(prefix)(current)(_(?!$)|$), or ^(prefix)(current)($) when exact
        tail = "($)" if exact else "(_(?!$)|$)"
        pattern = rf"^({re.escape(prefix)})({re.escape(current_text)}){tail}"
        replacement_template = r"\g<1>{new_text}\g<3>"

    return pattern, replacement_template


def nickname_under(nickname: str, base: str) -> bool:
    """True when *nickname* is *base* or continues it after an underscore.

    The nicknames a non-array Rename changes, and the rows the Outline shows for an
    item that is a nickname itself and has others under it: ``Tank_Pump1`` and
    ``Tank_Pump1_Run``, not ``Tank_Pump10``.
    """
    return nickname == base or (nickname.startswith(base + "_") and len(nickname) > len(base) + 1)


def rename_replacement(template: str, new_text: str) -> str:
    """Fill the template's new text so it is read literally by `re.sub`."""
    return template.format(new_text=new_text.replace("\\", "\\\\"))
