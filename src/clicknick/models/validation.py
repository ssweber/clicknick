from collections.abc import Callable, Mapping

from pyclickplc.validation import validate_comment as _pyclickplc_validate_comment
from pyclickplc.validation import validate_nickname as _pyclickplc_validate_nickname

# The fields CLICK stores without a space at either end: its editor strips them.
TRIMMED_FIELDS = ("nickname", "comment")


def trim_entry(field: str, value: str | bool) -> str | bool:
    """Return *value* as CLICK stores it in *field*.

    A nickname or comment loses the spaces at either end, so ``"Pump "`` is stored as
    ``"Pump"``. Every other field, and a value that is not text, is returned as it is.
    """
    if field in TRIMMED_FIELDS and isinstance(value, str):
        return value.strip(" ")
    return value


def validate_comment(
    comment: str,
    is_block_name_duplicate: Callable[[str, int], bool] | None = None,
    current_addr_key: int = 0,
) -> tuple[bool, str]:
    """Validate a comment's format (length, no space at either end) and block name uniqueness.

    Args:
        comment: The comment to validate
        is_block_name_duplicate: Optional callback to check if a block name is already
            in use. Signature: (block_name, exclude_addr_key) -> bool
        current_addr_key: The addr_key of the row being validated (excluded from
            duplicate check)

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    is_valid, error = _pyclickplc_validate_comment(comment)
    if not is_valid or comment == "":
        return is_valid, error

    # Check for duplicate block name if checker provided
    if is_block_name_duplicate is not None:
        # Import here to avoid circular dependency
        from pyclickplc.blocks import parse_block_tag

        tag = parse_block_tag(comment)
        if tag.name and is_block_name_duplicate(tag.name, current_addr_key):
            return False, f"Duplicate block: {tag.name}"

    return True, ""


def nickname_duplicate_checker(nicknames: Mapping[int, str]) -> Callable[[str, int], bool]:
    """Build a case-insensitive duplicate check over an addr_key -> nickname mapping.

    Use this when you have no nickname index, such as for one-off verification. CLICK treats
    nicknames as case-insensitive.
    """
    owners: dict[str, set[int]] = {}
    for addr_key, nickname in nicknames.items():
        if nickname:
            owners.setdefault(nickname.lower(), set()).add(addr_key)

    def is_duplicate(nickname: str, exclude_addr_key: int) -> bool:
        return bool(owners.get(nickname.lower(), set()) - {exclude_addr_key})

    return is_duplicate


def validate_nickname(
    nickname: str,
    current_addr_key: int,
    is_duplicate: Callable[[str, int], bool],
    *,
    system_bank: str | None = None,
) -> tuple[bool, str]:
    """Validate a nickname against all rules.

    Args:
        nickname: The nickname to validate
        current_addr_key: The addr_key of the row being validated (excluded from uniqueness)
        is_duplicate: Duplicate check function(nickname, exclude_addr_key) -> bool,
            case-insensitive (CLICK treats nicknames as case-insensitive)
        system_bank: Optional system bank hint (e.g. "SC", "SD", "X") for
            pyclickplc's bank-specific system rules.

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    # Check format first
    is_valid, error = _pyclickplc_validate_nickname(nickname, system_bank=system_bank)
    if not is_valid:
        return is_valid, error

    if nickname == "":
        return True, ""

    if is_duplicate(nickname, current_addr_key):
        return False, "Duplicate"

    return True, ""
