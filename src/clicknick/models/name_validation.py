"""Shared validation for names stored by CLICK Programming Software."""

from __future__ import annotations

import re

MAX_CLICK_NAME_LENGTH = 24
CLICK_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\- ]+$")


def validate_click_name(value: str) -> tuple[bool, str]:
    """Validate a PLC/DataView-style name and return its normalized value error."""
    name = value.strip()
    if not name:
        return False, "Name is required."
    if len(name) > MAX_CLICK_NAME_LENGTH:
        return False, f"Name is too long ({len(name)}/{MAX_CLICK_NAME_LENGTH})."
    if not CLICK_NAME_PATTERN.fullmatch(name):
        return False, "Use only letters, numbers, spaces, underscores, and hyphens."
    return True, ""
