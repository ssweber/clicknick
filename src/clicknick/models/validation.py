from collections.abc import Callable

from pyclickplc.validation import COMMENT_MAX_LENGTH
from pyclickplc.validation import validate_initial_value as validate_initial_value
from pyclickplc.validation import validate_nickname as _pyclickplc_validate_nickname


def validate_nickname_format(
    nickname: str, *, system_bank: str | None = None
) -> tuple[bool, str]:
    """Validate nickname format (length, characters, etc.) without uniqueness check.

    Args:
        nickname: The nickname to validate
        system_bank: Optional system bank hint (e.g. "SC", "SD", "X") for
            pyclickplc's bank-specific system rules.

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    return _pyclickplc_validate_nickname(nickname, system_bank=system_bank)


def validate_comment(
    comment: str,
    is_block_name_duplicate: Callable[[str, int], bool] | None = None,
    current_addr_key: int = 0,
) -> tuple[bool, str]:
    """Validate comment length and block name uniqueness.

    Args:
        comment: The comment to validate
        is_block_name_duplicate: Optional callback to check if a block name is already
            in use. Signature: (block_name, exclude_addr_key) -> bool
        current_addr_key: The addr_key of the row being validated (excluded from
            duplicate check)

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    if comment == "":
        return True, ""  # Empty is valid

    if len(comment) > COMMENT_MAX_LENGTH:
        return False, f"Too long ({len(comment)}/128)"

    # Check for duplicate block name if checker provided
    if is_block_name_duplicate is not None:
        # Import here to avoid circular dependency
        from pyclickplc.blocks import parse_block_tag

        tag = parse_block_tag(comment)
        if tag.name and is_block_name_duplicate(tag.name, current_addr_key):
            return False, f"Duplicate block: {tag.name}"

    return True, ""


def validate_nickname(
    nickname: str,
    all_nicknames: dict[int, str],
    current_addr_key: int,
    is_duplicate_fn: Callable[[str, int], bool] | None = None,
    *,
    system_bank: str | None = None,
) -> tuple[bool, str]:
    """Validate a nickname against all rules.

    Args:
        nickname: The nickname to validate
        all_nicknames: Dict of addr_key -> nickname for uniqueness check (legacy, used if is_duplicate_fn is None)
        current_addr_key: The addr_key of the row being validated (excluded from uniqueness)
        is_duplicate_fn: Optional O(1) duplicate checker function(nickname, exclude_addr_key) -> bool.
            If provided, uses this instead of O(n) scan of all_nicknames.
        system_bank: Optional system bank hint (e.g. "SC", "SD", "X") for
            pyclickplc's bank-specific system rules.

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    # Check format first
    is_valid, error = validate_nickname_format(nickname, system_bank=system_bank)
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
