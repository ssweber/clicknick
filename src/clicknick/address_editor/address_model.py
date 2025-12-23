"""Data model for the Address Editor.

Contains AddressRow dataclass, validation functions, and AddrKey calculations.
"""

from dataclasses import dataclass, field
from enum import IntEnum

# ==============================================================================
# Address Memory Map Configuration
# ==============================================================================

# Address ranges by memory type (start, end inclusive)
ADDRESS_RANGES: dict[str, tuple[int, int]] = {
    "X": (1, 816),  # Inputs
    "Y": (1, 816),  # Outputs
    "C": (1, 2000),  # Internal relays
    "T": (1, 500),  # Timers
    "CT": (1, 250),  # Counters
    "SC": (1, 1000),  # Special relays
    "DS": (1, 4500),  # Data registers (16-bit)
    "DD": (1, 1000),  # Double data registers (32-bit)
    "DH": (1, 500),  # Hex data registers
    "DF": (1, 500),  # Float data registers
    "XD": (0, 16),  # Input groups (note: starts at 0)
    "YD": (0, 16),  # Output groups (note: starts at 0)
    "TD": (1, 500),  # Timer data
    "CTD": (1, 250),  # Counter data
    "SD": (1, 1000),  # Special data registers
    "TXT": (1, 1000),  # Text registers
}

# Base values for AddrKey calculation (Primary Key in MDB)
MEMORY_TYPE_BASES: dict[str, int] = {
    "X": 0x0000000,
    "Y": 0x1000000,
    "C": 0x2000000,
    "T": 0x3000000,
    "CT": 0x4000000,
    "SC": 0x5000000,
    "DS": 0x6000000,
    "DD": 0x7000000,
    "DH": 0x8000000,
    "DF": 0x9000000,
    "XD": 0xA000000,
    "YD": 0xB000000,
    "TD": 0xC000000,
    "CTD": 0xD000000,
    "SD": 0xE000000,
    "TXT": 0xF000000,
}

# Reverse mapping: type_index -> memory_type
_INDEX_TO_TYPE: dict[int, str] = {v >> 24: k for k, v in MEMORY_TYPE_BASES.items()}

# ==============================================================================
# Data Type Configuration
# ==============================================================================


class DataType(IntEnum):
    """DataType mapping from MDB database."""

    BIT = 0  # C, CT, SC, T, X, Y - values: "0" or "1"
    INT = 1  # DS, SD, TD - 16-bit signed: -32768 to 32767
    INT2 = 2  # CTD, DD - 32-bit signed: -2147483648 to 2147483647
    FLOAT = 3  # DF - float: -3.4028235E+38 to 3.4028235E+38
    HEX = 4  # DH, XD, YD - hex string: "0000" to "FFFF"
    TXT = 6  # TXT - single ASCII character


# Display names for DataType values
DATA_TYPE_DISPLAY: dict[int, str] = {
    DataType.BIT: "BIT",
    DataType.INT: "INT",
    DataType.INT2: "INT2",
    DataType.FLOAT: "FLOAT",
    DataType.HEX: "HEX",
    DataType.TXT: "TXT",
}

# DataType by memory type
MEMORY_TYPE_TO_DATA_TYPE: dict[str, int] = {
    "X": DataType.BIT,
    "Y": DataType.BIT,
    "C": DataType.BIT,
    "T": DataType.BIT,
    "CT": DataType.BIT,
    "SC": DataType.BIT,
    "DS": DataType.INT,
    "SD": DataType.INT,
    "TD": DataType.INT,
    "DD": DataType.INT2,
    "CTD": DataType.INT2,
    "DF": DataType.FLOAT,
    "DH": DataType.HEX,
    "XD": DataType.HEX,
    "YD": DataType.HEX,
    "TXT": DataType.TXT,
}

# ==============================================================================
# Validation Rules & Constraints
# ==============================================================================

# Validation constants
NICKNAME_MAX_LENGTH = 24
COMMENT_MAX_LENGTH = 128

# Characters forbidden in nicknames
# Note: Space is allowed, hyphen (-) and period (.) are forbidden
FORBIDDEN_CHARS = set("%\"<>!#$&'()*+-./:;=?@[\\]^`{|}~")

# Value ranges for validation
INT_MIN = -32768
INT_MAX = 32767
INT2_MIN = -2147483648
INT2_MAX = 2147483647
FLOAT_MIN = -3.4028235e38
FLOAT_MAX = 3.4028235e38

# Memory types where InitialValue/Retentive cannot be edited
# System types: values are fixed by CLICK software
NON_EDITABLE_TYPES: frozenset[str] = frozenset({"SC", "SD", "XD", "YD"})

# Memory types that share retentive with their paired type (TD↔T, CTD↔CT)
# Retentive edits on these types update the paired type instead
PAIRED_RETENTIVE_TYPES: dict[str, str] = {"TD": "T", "CTD": "CT"}

# Default retentive values by memory type (from CLICK documentation)
DEFAULT_RETENTIVE: dict[str, bool] = {
    "X": False,
    "Y": False,
    "C": False,
    "T": False,
    "CT": True,  # Counters are retentive by default
    "SC": False,  # Can't change
    "DS": True,  # Data registers are retentive by default
    "DD": True,
    "DH": True,
    "DF": True,
    "XD": False,  # Can't change
    "YD": False,  # Can't change
    "TD": False,  # Can't change (stored elsewhere)
    "CTD": True,  # Can't change (stored elsewhere)
    "SD": False,  # Can't change
    "TXT": True,
}

# ==============================================================================
# Helper Functions
# ==============================================================================


def get_addr_key(memory_type: str, address: int) -> int:
    """Calculate AddrKey from memory type and address.

    Args:
        memory_type: The memory type (X, Y, C, etc.)
        address: The address number

    Returns:
        The AddrKey value used as primary key in MDB

    Raises:
        KeyError: If memory_type is not recognized
    """
    return MEMORY_TYPE_BASES[memory_type] + address


def parse_addr_key(addr_key: int) -> tuple[str, int]:
    """Parse an AddrKey back to memory type and address.

    Args:
        addr_key: The AddrKey value from MDB

    Returns:
        Tuple of (memory_type, address)

    Raises:
        KeyError: If the type index is not recognized
    """
    type_index = addr_key >> 24
    address = addr_key & 0xFFFFFF
    return _INDEX_TO_TYPE[type_index], address


def validate_nickname(
    nickname: str,
    all_nicknames: dict[int, str],
    current_addr_key: int,
) -> tuple[bool, str]:
    """Validate a nickname against all rules.

    Args:
        nickname: The nickname to validate
        all_nicknames: Dict of addr_key -> nickname for uniqueness check
        current_addr_key: The addr_key of the row being validated (excluded from uniqueness)

    Returns:
        Tuple of (is_valid, error_message) - error_message is "" if valid
    """
    if nickname == "":
        return True, ""  # Empty is valid (just means unassigned)

    if len(nickname) > NICKNAME_MAX_LENGTH:
        return False, f"Too long ({len(nickname)}/24)"

    if nickname.startswith("_"):
        return False, "Cannot start with _"

    invalid_chars = set(nickname) & FORBIDDEN_CHARS
    if invalid_chars:
        # Show first few invalid chars
        chars_display = "".join(sorted(invalid_chars)[:3])
        return False, f"Invalid: {chars_display}"

    # Check uniqueness (excluding self)
    for addr_key, existing_nick in all_nicknames.items():
        if addr_key != current_addr_key and existing_nick == nickname:
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


# ==============================================================================
# Main Data Model
# ==============================================================================


@dataclass
class AddressRow:
    """Represents a single address row in the editor.

    This is the in-memory model for a single PLC address. It tracks both
    the current values and the original values (for dirty tracking).

    Usage:
        # Create a clean row (originals automatically set to match content)
        row = AddressRow("X", 1, nickname="Input1")

        # Create a dirty row (explicit originals)
        row = AddressRow("X", 1, nickname="Input1", original_nickname="OldName")
    """

    # --- Identity ---
    memory_type: str  # 'X', 'Y', 'C', etc.
    address: int  # 1, 2, 3... (or 0 for XD/YD)

    # --- Content ---
    nickname: str = ""  # Current nickname or ""
    comment: str = ""  # Address comment
    initial_value: str = ""  # Current initial value (stored as string)
    retentive: bool = False  # Current retentive setting

    # --- Metadata ---
    used: bool = False  # Whether address is used in program
    exists_in_mdb: bool = False  # True if row was loaded from database
    data_type: int = DataType.BIT  # DataType from MDB (0=bit, 1=int, etc.)

    # --- Dirty Tracking (Original Values) ---
    # These track the value at load-time to determine if the row is 'dirty'.
    # default=None allows __post_init__ to automatically populate them from Content fields.
    # repr=False keeps debugging output clean.
    original_nickname: str | None = field(default=None, repr=False)
    original_comment: str | None = field(default=None, repr=False)
    original_initial_value: str | None = field(default=None, repr=False)
    original_retentive: bool | None = field(default=None, repr=False)

    # --- Validation State ---
    # Computed state, not stored in comparisons
    is_valid: bool = field(default=True, compare=False)
    validation_error: str = field(default="", compare=False)
    initial_value_valid: bool = field(default=True, compare=False)
    initial_value_error: str = field(default="", compare=False)

    # Track if row was loaded with invalid data (SC/SD often have system-set invalid nicknames)
    loaded_with_error: bool = field(default=False, compare=False)

    def __post_init__(self):
        """Capture initial values if originals were not explicitly provided."""
        if self.original_nickname is None:
            self.original_nickname = self.nickname

        if self.original_comment is None:
            self.original_comment = self.comment

        if self.original_initial_value is None:
            self.original_initial_value = self.initial_value

        if self.original_retentive is None:
            self.original_retentive = self.retentive

    @property
    def addr_key(self) -> int:
        """Get the AddrKey for this row."""
        return get_addr_key(self.memory_type, self.address)

    @property
    def display_address(self) -> str:
        """Get the display string for this address (e.g., 'X001', 'C150')."""
        return f"{self.memory_type}{self.address}"

    @property
    def is_default_retentive(self) -> bool:
        """Return True if retentive matches the default for this memory_type."""
        default = DEFAULT_RETENTIVE.get(self.memory_type, False)
        return self.retentive == default

    @property
    def data_type_display(self) -> str:
        """Get human-readable data type name."""
        return DATA_TYPE_DISPLAY.get(self.data_type, "")

    @property
    def outline_suffix(self) -> str:
        """Get suffix string for outline panel (appended to nickname text).

        Format: : DataType = Value, Retentive=X
        - Value only shown if not 0/False/empty
        - Retentive only shown if not default for memory type
        """
        parts = [f"  : {self.data_type_display}"]

        # only show 'ON' or 'Retentive' for BIT
        if self.data_type == DataType.BIT:
            if not self.is_default_retentive:
                parts.append("= Retentive")
            elif self.initial_value == "1":
                parts.append("= ON")

        elif not self.is_default_retentive:
            parts.append(f"= {self.initial_value}")

        return " ".join(parts)

    # --- Dirty Checking Properties ---

    @property
    def is_dirty(self) -> bool:
        """True if any field has been modified since load."""
        return (
            self.is_nickname_dirty
            or self.is_comment_dirty
            or self.is_initial_value_dirty
            or self.is_retentive_dirty
        )

    @property
    def is_nickname_dirty(self) -> bool:
        """True if just the nickname has been modified."""
        return self.nickname != self.original_nickname

    @property
    def is_comment_dirty(self) -> bool:
        """True if just the comment has been modified."""
        return self.comment != self.original_comment

    @property
    def is_initial_value_dirty(self) -> bool:
        """True if the initial value has been modified."""
        return self.initial_value != self.original_initial_value

    @property
    def is_retentive_dirty(self) -> bool:
        """True if the retentive setting has been modified."""
        return self.retentive != self.original_retentive

    # --- State Helper Properties ---

    @property
    def can_edit_initial_value(self) -> bool:
        """True if initial value can be edited for this memory type."""
        return self.memory_type not in NON_EDITABLE_TYPES

    @property
    def can_edit_retentive(self) -> bool:
        """True if retentive setting can be edited for this memory type."""
        return self.memory_type not in NON_EDITABLE_TYPES

    @property
    def is_virtual(self) -> bool:
        """True if this row doesn't exist in MDB."""
        return not self.exists_in_mdb

    @property
    def is_empty(self) -> bool:
        """True if nickname is empty/unassigned."""
        return self.nickname == ""

    @property
    def should_ignore_validation_error(self) -> bool:
        """True if validation errors should be ignored (SC/SD loaded with invalid data).

        SC/SD addresses often have system-preset nicknames that violate validation rules.
        If the row was loaded with errors and hasn't been modified, we ignore the errors.
        """
        return self.loaded_with_error and not self.is_nickname_dirty

    @property
    def has_reportable_error(self):
        return not (self.is_valid or self.is_empty or self.should_ignore_validation_error)

    @property
    def has_content(self) -> bool:
        """True if row has any user-defined content worth saving."""
        return (
            self.nickname != ""
            or self.comment != ""
            or self.initial_value != ""
            or self.retentive != DEFAULT_RETENTIVE.get(self.memory_type, False)
        )

    # --- CRUD Helper Properties ---

    @property
    def needs_insert(self) -> bool:
        """True if dirty AND has content AND was virtual."""
        return self.is_dirty and self.has_content and self.is_virtual

    @property
    def needs_update(self) -> bool:
        """True if dirty AND has content AND was NOT virtual AND not deleting."""
        return self.is_dirty and self.has_content and not self.is_virtual

    @property
    def needs_nickname_clear_only(self) -> bool:
        """True if should clear nickname (but keep row for comment/used/initial value)."""
        # Nickname was cleared, row existed, but has other content or is used
        has_other_content = (
            self.comment != ""
            or self.used
            or self.initial_value != ""
            or self.retentive != DEFAULT_RETENTIVE.get(self.memory_type, False)
        )
        return (
            self.is_nickname_dirty
            and self.nickname == ""
            and self.original_nickname != ""
            and has_other_content
        )

    @property
    def needs_full_delete(self) -> bool:
        """True if should DELETE the entire row from database."""
        # Row existed, now completely empty and not used
        is_default_retentive = self.retentive == DEFAULT_RETENTIVE.get(self.memory_type, False)
        return (
            self.is_dirty
            and self.nickname == ""
            and self.comment == ""
            and self.initial_value == ""
            and is_default_retentive
            and not self.used
            and not self.is_virtual
        )

    def validate(self, all_nicknames: dict[int, str]) -> None:
        """Validate this row and update validation state.

        Args:
            all_nicknames: Dict of addr_key -> nickname for uniqueness check
        """
        # Validate nickname
        self.is_valid, self.validation_error = validate_nickname(
            self.nickname, all_nicknames, self.addr_key
        )

        # Validate initial value
        self.initial_value_valid, self.initial_value_error = validate_initial_value(
            self.initial_value, self.data_type
        )

        # Overall validity includes both
        if not self.initial_value_valid and self.is_valid:
            self.is_valid = False
            self.validation_error = self.initial_value_error

    def mark_saved(self) -> None:
        """Call after successful save to reset dirty tracking."""
        self.original_nickname = self.nickname
        self.original_comment = self.comment
        self.original_initial_value = self.initial_value
        self.original_retentive = self.retentive
        self.exists_in_mdb = True

    def update_from_db(self, db_data: dict) -> bool:
        """Update non-dirty fields from database data.

        Used when external changes are detected in the mdb file.
        Only updates fields that haven't been modified by the user.

        Args:
            db_data: Dict with keys: nickname, comment, used, data_type,
                    initial_value, retentive

        Returns:
            True if any field was updated
        """
        changed = False

        # Always update 'used' since it's read-only in the editor
        new_used = db_data.get("used", False)
        if self.used != new_used:
            self.used = new_used
            changed = True

        # Helper to check cleanliness and update
        def _update_if_clean(field_name, original_field, new_value):
            current_val = getattr(self, field_name)
            original_val = getattr(self, original_field)

            # If current equals original (user hasn't touched it)
            # AND current doesn't equal new value (there is a change from DB)
            if current_val == original_val and current_val != new_value:
                setattr(self, field_name, new_value)
                setattr(self, original_field, new_value)
                return True
            return False

        # Update nickname only if not dirty
        changed |= _update_if_clean("nickname", "original_nickname", db_data.get("nickname", ""))

        # Update comment only if not dirty
        changed |= _update_if_clean("comment", "original_comment", db_data.get("comment", ""))

        # Update initial_value only if not dirty
        changed |= _update_if_clean(
            "initial_value", "original_initial_value", db_data.get("initial_value", "")
        )

        # Update retentive only if not dirty
        changed |= _update_if_clean(
            "retentive", "original_retentive", db_data.get("retentive", False)
        )

        # Update exists_in_mdb flag
        self.exists_in_mdb = True

        return changed
