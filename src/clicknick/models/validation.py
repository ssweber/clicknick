from collections.abc import Callable, Mapping

from pyclickplc.banks import DataType
from pyclickplc.validation import COMMENT_MAX_LENGTH
from pyclickplc.validation import validate_comment as _pyclickplc_validate_comment
from pyclickplc.validation import validate_nickname as _pyclickplc_validate_nickname

# The fields that CLICK stores without a space or a tab at either end. A Text initial value
# is the exception. CLICK keeps its edges when the value is quoted. A comment is not in this
# list. CLICK 4.00 stores the spaces at the ends of a comment that you type in CLICK.
TRIMMED_FIELDS = ("nickname", "initial_value")

# The characters that trim_entry strips from either end
EDGE_CHARACTERS = " \t"

# The error for a comment with a line break or another control code at either end
CONTROL_EDGE_ERROR = "Cannot start or end with a line break or a control character"


def control_code_edges(comment: str) -> tuple[bool, bool]:
    """Return whether *comment* starts and whether it ends with a code below 0x20.

    Spaces and tabs at the ends are set aside first. So ``" \\nNote"`` starts with a line
    break, and ``" Note\\t"`` ends with neither. validate_comment reports CONTROL_EDGE_ERROR
    when either value is True.
    """
    inner = comment.strip(EDGE_CHARACTERS)
    if not inner:
        return False, False
    return inner[0] < " ", inner[-1] < " "


def trim_entry(field: str, value: str | bool, data_type: int) -> str | bool:
    """Return *value* as CLICK stores it in *field* of a row of *data_type*.

    A nickname and an initial value of any type but Text lose the spaces and tabs at either
    end. So ``"Pump\\t"`` is stored as ``"Pump"``, and ``" 5"`` as ``"5"``. A comment, a Text
    initial value, every other field, and a value that is not text are returned as they are.
    """
    if field not in TRIMMED_FIELDS or not isinstance(value, str):
        return value
    if field == "initial_value" and data_type == DataType.TXT:
        return value
    return value.strip(EDGE_CHARACTERS)


def validate_comment(
    comment: str,
    is_block_name_duplicate: Callable[[str, int], bool] | None = None,
    current_addr_key: int = 0,
) -> tuple[bool, str]:
    """Validate a comment's format and the uniqueness of its block name.

    A space or a tab at either end of the comment is valid. CLICK 4.00 stores a comment with
    the spaces at its ends. ClickNick treats a tab the same way. A line break or another
    control code below 0x20 at either end is an error (CONTROL_EDGE_ERROR). ClickNick does
    not remove it.

    Args:
        comment: The comment to validate
        is_block_name_duplicate: Optional callback to check if a block name is already
            in use. Signature: (block_name, exclude_addr_key) -> bool
        current_addr_key: The addr_key of the row being validated (excluded from
            duplicate check)

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    if len(comment) > COMMENT_MAX_LENGTH:
        return False, f"Too long ({len(comment)}/{COMMENT_MAX_LENGTH})"
    if any(control_code_edges(comment)):
        return False, CONTROL_EDGE_ERROR
    # pyclickplc refuses a comment with a space or a tab at either end. So this call passes
    # pyclickplc the comment without the spaces and tabs at its ends.
    is_valid, error = _pyclickplc_validate_comment(comment.strip(EDGE_CHARACTERS))
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
