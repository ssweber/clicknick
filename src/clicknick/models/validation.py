from collections.abc import Callable

from .constants import (
    COMMENT_MAX_LENGTH,
    FLOAT_MAX,
    FLOAT_MIN,
    FORBIDDEN_CHARS,
    INT2_MAX,
    INT2_MIN,
    INT_MAX,
    INT_MIN,
    NICKNAME_MAX_LENGTH,
    DataType,
    RESERVED_NICKNAMES,
)


def validate_nickname_format(nickname: str) -> tuple[bool, str]:
    """Validate nickname format (length, characters, etc.) without uniqueness check.

    Args:
        nickname: The nickname to validate

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    if nickname == "":
        return True, ""  # Empty is valid (just means unassigned)

    if len(nickname) > NICKNAME_MAX_LENGTH:
        return False, f"Too long ({len(nickname)}/24)"

    if nickname.startswith("_"):
        return False, "Cannot start with _"

    if nickname.lower() in RESERVED_NICKNAMES:
        return False, "Reserved keyword"

    invalid_chars = set(nickname) & FORBIDDEN_CHARS
    if invalid_chars:
        # Show first few invalid chars
        chars_display = "".join(sorted(invalid_chars)[:3])
        return False, f"Invalid: {chars_display}"

    return True, ""


def validate_comment(comment: str) -> tuple[bool, str]:
    """Validate comment length.

    Args:
        comment: The comment to validate

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    if comment == "":
        return True, ""  # Empty is valid

    if len(comment) > COMMENT_MAX_LENGTH:
        return False, f"Too long ({len(comment)}/128)"

    return True, ""


def validate_nickname(
    nickname: str,
    all_nicknames: dict[int, str],
    current_addr_key: int,
    is_duplicate_fn: Callable[[str, int], bool] | None = None,
) -> tuple[bool, str]:
    """Validate a nickname against all rules.

    Args:
        nickname: The nickname to validate
        all_nicknames: Dict of addr_key -> nickname for uniqueness check (legacy, used if is_duplicate_fn is None)
        current_addr_key: The addr_key of the row being validated (excluded from uniqueness)
        is_duplicate_fn: Optional O(1) duplicate checker function(nickname, exclude_addr_key) -> bool.
            If provided, uses this instead of O(n) scan of all_nicknames.

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    # Check format first
    is_valid, error = validate_nickname_format(nickname)
    if not is_valid:
        return is_valid, error

    if nickname == "":
        return True, ""

    # Check uniqueness (case-insensitive - CLICK treats nicknames as case-insensitive)
    if is_duplicate_fn is not None:
        # O(1) check via reverse index
        if is_duplicate_fn(nickname, current_addr_key):
            return False, "Duplicate"
    else:
        # Legacy O(n) fallback (case-insensitive)
        nickname_lower = nickname.lower()
        for addr_key, existing_nick in all_nicknames.items():
            if addr_key != current_addr_key and existing_nick.lower() == nickname_lower:
                return False, "Duplicate"

    return True, ""


def validate_initial_value(
    initial_value: str,
    data_type: int,
) -> tuple[bool, str]:
    """Validate an initial value against the data type rules.

    Args:
        initial_value: The initial value string to validate
        data_type: The DataType number (0=bit, 1=int, 2=int2, 3=float, 4=hex, 6=txt)

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    if initial_value == "":
        return True, ""  # Empty is valid (means no initial value set)

    if data_type == DataType.BIT:
        if initial_value not in ("0", "1"):
            return False, "Must be 0 or 1"
        return True, ""

    elif data_type == DataType.INT:
        try:
            val = int(initial_value)
            if val < INT_MIN or val > INT_MAX:
                return False, f"Range: {INT_MIN} to {INT_MAX}"
            return True, ""
        except ValueError:
            return False, "Must be integer"

    elif data_type == DataType.INT2:
        try:
            val = int(initial_value)
            if val < INT2_MIN or val > INT2_MAX:
                return False, f"Range: {INT2_MIN} to {INT2_MAX}"
            return True, ""
        except ValueError:
            return False, "Must be integer"

    elif data_type == DataType.FLOAT:
        try:
            val = float(initial_value)
            # Allow scientific notation like -3.4028235E+38
            if val < FLOAT_MIN or val > FLOAT_MAX:
                return False, "Out of float range"
            return True, ""
        except ValueError:
            return False, "Must be number"

    elif data_type == DataType.HEX:
        # Hex values should be 4 hex digits (0000 to FFFF)
        if len(initial_value) > 4:
            return False, "Max 4 hex digits"
        try:
            val = int(initial_value, 16)
            if val < 0 or val > 0xFFFF:
                return False, "Range: 0000 to FFFF"
            return True, ""
        except ValueError:
            return False, "Must be hex (0-9, A-F)"

    elif data_type == DataType.TXT:
        # Single ASCII character (7-bit)
        if len(initial_value) != 1:
            return False, "Must be single char"
        if ord(initial_value) > 127:
            return False, "Must be ASCII"
        return True, ""

    # Unknown data type
    return True, ""
