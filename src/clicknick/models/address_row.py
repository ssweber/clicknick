"""Data model for the Address Editor.

Contains AddressRow dataclass, validation functions, and AddrKey calculations.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from .constants import (
    _INDEX_TO_TYPE,
    DATA_TYPE_DISPLAY,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_BASES,
    NON_EDITABLE_TYPES,
    DataType,
)
from .validation import validate_initial_value, validate_nickname

# ==============================================================================
# Helper Functions
# ==============================================================================


def get_addr_key(memory_type: str, address: int) -> int:
    """Calculate AddrKey from memory type and MDB address.

    Args:
        memory_type: The memory type (X, Y, C, etc.)
        address: The MDB address number

    Returns:
        The AddrKey value used as primary key in MDB

    Raises:
        KeyError: If memory_type is not recognized
    """
    return MEMORY_TYPE_BASES[memory_type] + address


def parse_addr_key(addr_key: int) -> tuple[str, int]:
    """Parse an AddrKey back to memory type and MDB address.

    Args:
        addr_key: The AddrKey value from MDB

    Returns:
        Tuple of (memory_type, mdb_address)

    Raises:
        KeyError: If the type index is not recognized
    """
    type_index = addr_key >> 24
    address = addr_key & 0xFFFFFF
    return _INDEX_TO_TYPE[type_index], address


def is_xd_yd_upper_byte(memory_type: str, mdb_address: int) -> bool:
    """Check if an XD/YD MDB address is for an upper byte (only XD0u/YD0u at MDB 1).

    XD/YD structure:
    - MDB 0 = XD0 (lower), MDB 1 = XD0u (upper) - only slot 0 has upper byte variant
    - MDB 2 = XD1, MDB 4 = XD2, ... MDB 16 = XD8 (no upper byte variants displayed)

    Args:
        memory_type: The memory type (XD or YD)
        mdb_address: The MDB address number

    Returns:
        True if this is XD0u/YD0u (MDB address 1)
    """
    if memory_type in ("XD", "YD"):
        return mdb_address == 1
    return False


def is_xd_yd_hidden_slot(memory_type: str, mdb_address: int) -> bool:
    """Check if an XD/YD MDB address is a hidden slot (odd addresses > 1).

    These are the upper byte slots for XD1-8/YD1-8 that aren't displayed.

    Args:
        memory_type: The memory type (XD or YD)
        mdb_address: The MDB address number

    Returns:
        True if this slot should be hidden (odd addresses >= 3)
    """
    if memory_type in ("XD", "YD"):
        return mdb_address >= 3 and mdb_address % 2 == 1
    return False


def xd_yd_mdb_to_display(mdb_address: int) -> int:
    """Convert XD/YD MDB address to display address number.

    XD/YD structure:
    - MDB 0 -> 0 (XD0)
    - MDB 1 -> 0 (XD0u)
    - MDB 2 -> 1 (XD1), MDB 4 -> 2 (XD2), ... MDB 16 -> 8 (XD8)

    Args:
        mdb_address: The MDB address (0, 1, 2, 4, 6, ...)

    Returns:
        The display address number (0, 0, 1, 2, 3, ...)
    """
    if mdb_address <= 1:
        return 0
    return mdb_address // 2


def xd_yd_display_to_mdb(display_addr: int, upper_byte: bool = False) -> int:
    """Convert XD/YD display address to MDB address.

    Args:
        display_addr: The display address (0-8)
        upper_byte: True for XD0u/YD0u (only valid for display_addr=0)

    Returns:
        The MDB address
    """
    if display_addr == 0:
        return 1 if upper_byte else 0
    return display_addr * 2


def format_address_display(memory_type: str, mdb_address: int) -> str:
    """Format a memory type and address as a display string.

    For XD/YD:
    - MDB 0 -> "XD0", MDB 1 -> "XD0u"
    - MDB 2 -> "XD1", MDB 4 -> "XD2", ... MDB 16 -> "XD8"
    - Odd addresses >= 3 are hidden slots (returns "XDn?" to indicate)

    For X/Y (bits):
    - 3-digit zero-padded: X001, Y001, X816, Y816

    Args:
        memory_type: The memory type (X, XD, DS, etc.)
        mdb_address: The MDB address number

    Returns:
        Formatted address string (e.g., "X001", "XD0", "XD0u", "DS100")
    """
    if memory_type in ("XD", "YD"):
        if mdb_address == 0:
            return f"{memory_type}0"
        elif mdb_address == 1:
            return f"{memory_type}0u"
        else:
            display_addr = mdb_address // 2
            return f"{memory_type}{display_addr}"
    if memory_type in ("X", "Y"):
        return f"{memory_type}{mdb_address:03d}"
    return f"{memory_type}{mdb_address}"


def parse_address_display(address_str: str) -> tuple[str, int] | None:
    """Parse a display address string to memory type and MDB address.

    Handles XD/YD: "XD0u" -> ("XD", 1), "XD1" -> ("XD", 2), "XD8" -> ("XD", 16)

    Args:
        address_str: Address string like "X001", "XD0", "XD0u", "XD8"

    Returns:
        Tuple of (memory_type, mdb_address) or None if invalid
    """
    import re

    if not address_str:
        return None

    address_str = address_str.strip().upper()

    # Match pattern: letters followed by digits, optionally ending with 'U'
    match = re.match(r"^([A-Z]+)(\d+)(U?)$", address_str)
    if not match:
        return None

    memory_type = match.group(1)
    display_addr = int(match.group(2))
    is_upper = match.group(3) == "U"

    if memory_type not in MEMORY_TYPE_BASES:
        return None

    if memory_type in ("XD", "YD"):
        # Only XD0/YD0 can have 'u' suffix
        if is_upper and display_addr != 0:
            return None  # Invalid: XD1u, XD2u, etc. don't exist
        return memory_type, xd_yd_display_to_mdb(display_addr, is_upper)

    # For non-XD/YD, display address equals MDB address
    return memory_type, display_addr


def normalize_address(address: str) -> str | None:
    """Normalize an address string to its canonical display form.

    Parses the input address and returns the properly formatted display address
    (e.g., "x1" -> "X001", "xd0u" -> "XD0u").

    Args:
        address: The address string to normalize (e.g., "x1", "XD0U")

    Returns:
        The normalized display address, or None if address is invalid.
    """
    parsed = parse_address_display(address)
    if not parsed:
        return None
    memory_type, mdb_address = parsed
    return format_address_display(memory_type, mdb_address)


# ==============================================================================
# Main Data Model
# ==============================================================================


@dataclass
class SectionHeaderRow:
    """Dummy row class for section headers in the Address Editor.

    This is a lightweight placeholder that mimics AddressRow structure
    to allow seamless integration in the editor's row list. It only contains
    the minimal fields needed for display and styling.

    Usage:
        header = SectionHeaderRow(nickname="--- T/TD Section ---")
    """

    # --- Identity (dummy values) ---
    memory_type: str = ""
    address: int = 0

    # --- Content ---
    nickname: str = ""  # The section header text
    comment: str = ""
    initial_value: str = ""
    retentive: bool = False

    # --- Metadata (dummy values) ---
    used: bool = False
    exists_in_mdb: bool = False
    data_type: int = DataType.BIT

    # --- All other properties return safe defaults ---
    @property
    def is_dirty(self) -> bool:
        return False

    @property
    def is_valid(self) -> bool:
        return True

    @property
    def has_reportable_error(self) -> bool:
        return False

    @property
    def can_edit_initial_value(self) -> bool:
        return False

    @property
    def can_edit_retentive(self) -> bool:
        return False


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
        """Get the display string for this address (e.g., 'X001', 'XD0u', 'C150')."""
        return format_address_display(self.memory_type, self.address)

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

    def validate(
        self,
        all_nicknames: dict[int, str],
        is_duplicate_fn: Callable[[str, int], bool] | None = None,
    ) -> None:
        """Validate this row and update validation state.

        Args:
            all_nicknames: Dict of addr_key -> nickname for uniqueness check
            is_duplicate: Optional O(1) duplicate checker function(nickname, exclude_addr_key) -> bool.
                If provided, uses this instead of O(n) scan of all_nicknames.
        """
        # Validate nickname
        self.is_valid, self.validation_error = validate_nickname(
            self.nickname, all_nicknames, self.addr_key, is_duplicate_fn
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

    def discard(self) -> None:
        """Reset to original values, discarding any unsaved changes."""
        self.nickname = self.original_nickname
        self.comment = self.original_comment
        self.initial_value = self.original_initial_value
        self.retentive = self.original_retentive

    def discard_field(self, field_name: str) -> bool:
        """Reset a single field to its original value.

        Args:
            field_name: One of 'nickname', 'comment', 'initial_value', 'retentive'

        Returns:
            True if the field was dirty and has been discarded, False otherwise.
        """
        field_map = {
            "nickname": ("nickname", "original_nickname"),
            "comment": ("comment", "original_comment"),
            "initial_value": ("initial_value", "original_initial_value"),
            "retentive": ("retentive", "original_retentive"),
        }

        if field_name not in field_map:
            return False

        current_field, original_field = field_map[field_name]
        current_val = getattr(self, current_field)
        original_val = getattr(self, original_field)

        if current_val != original_val:
            setattr(self, current_field, original_val)
            return True
        return False

    def update_from_db(self, db_data: dict) -> bool:
        """Update from database data, handling dirty fields gracefully.

        Used when external changes are detected in the mdb file.

        For clean fields: updates both current and original to new value.
        For dirty fields: only updates original (preserves user's edit, updates baseline).

        This means:
        - User edits are never lost due to external changes
        - Discard will revert to the latest external value (not stale data)
        - Save will overwrite the external change with user's edit

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

        def _update_field(field_name: str, original_field: str, new_value) -> bool:
            current_val = getattr(self, field_name)
            original_val = getattr(self, original_field)
            is_dirty = current_val != original_val

            if is_dirty:
                # Dirty: only update baseline (preserves user's edit)
                if original_val != new_value:
                    setattr(self, original_field, new_value)
                    return True
            else:
                # Clean: update both current and original
                if current_val != new_value:
                    setattr(self, field_name, new_value)
                    setattr(self, original_field, new_value)
                    return True
            return False

        changed |= _update_field("nickname", "original_nickname", db_data.get("nickname", ""))
        changed |= _update_field("comment", "original_comment", db_data.get("comment", ""))
        changed |= _update_field(
            "initial_value", "original_initial_value", db_data.get("initial_value", "")
        )
        changed |= _update_field("retentive", "original_retentive", db_data.get("retentive", False))

        self.exists_in_mdb = True
        return changed
