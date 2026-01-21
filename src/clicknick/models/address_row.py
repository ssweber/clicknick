"""Data model for the Address Editor.

Contains AddressRow frozen dataclass, validation functions, and AddrKey calculations.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class AddressRow:
    """Immutable address row in the editor.

    This is the in-memory model for a single PLC address. Being frozen,
    new instances must be created for any changes using dataclasses.replace().

    Usage:
        # Create a row
        row = AddressRow(memory_type="X", address=1, nickname="Input1")

        # Modify by creating new instance
        from dataclasses import replace
        new_row = replace(row, nickname="NewName", comment="Updated")
    """

    # --- Identity ---
    memory_type: str  # 'X', 'Y', 'C', etc.
    address: int  # 1, 2, 3... (or 0 for XD/YD)

    # --- Content (user-editable) ---
    nickname: str = ""
    comment: str = ""
    initial_value: str = ""
    retentive: bool = False

    # --- Metadata (from DB, not user-editable) ---
    used: bool = False
    exists_in_mdb: bool = False
    data_type: int = DataType.BIT

    # --- Validation State (computed) ---
    is_valid: bool = field(default=True, compare=False)
    validation_error: str = field(default="", compare=False)
    initial_value_valid: bool = field(default=True, compare=False)
    initial_value_error: str = field(default="", compare=False)

    # Track if row was loaded with invalid data
    loaded_with_error: bool = field(default=False, compare=False)

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

    # --- State Helper Properties ---

    @property
    def is_interleaved_secondary(self) -> bool:
        """True if this is a secondary type in an interleaved pair (TD, CTD).

        In unified view, T/TD and CT/CTD rows are interleaved (T1, TD1, T2, TD2...).
        The secondary types (TD, CTD) get alternating background color for visual
        distinction. This property abstracts that logic from the view layer.
        """
        return self.memory_type in ("TD", "CTD")

    @property
    def can_edit_initial_value(self) -> bool:
        """True if initial value can be edited for this memory type."""
        return self.memory_type not in NON_EDITABLE_TYPES

    def is_initial_value_masked(self, effective_retentive: bool) -> bool:
        """Check if initial value is masked (shows '-' and is read-only).

        Initial value is masked when:
        - Memory type allows editing (not in NON_EDITABLE_TYPES), AND
        - Retentive is enabled (either on this row or its paired T/CT row)

        For T/TD and CT/CTD pairs, retentive is stored on T/CT but affects
        both rows' initial value editability. The caller must pass the
        effective retentive value (from the paired row if applicable).

        Args:
            effective_retentive: The retentive value to check (from self or paired row)

        Returns:
            True if initial value should show '-' and reject edits
        """
        # NON_EDITABLE_TYPES (SC, SD, XD, YD) are never masked - they just can't be edited
        if self.memory_type in NON_EDITABLE_TYPES:
            return False
        return effective_retentive

    @property
    def can_edit_retentive(self) -> bool:
        """True if retentive setting can be edited for this memory type."""
        return self.memory_type not in NON_EDITABLE_TYPES

    @property
    def is_empty(self) -> bool:
        """True if nickname is empty/unassigned."""
        return self.nickname == ""

    @property
    def should_ignore_validation_error(self) -> bool:
        """True if validation errors should be ignored (SC/SD loaded with invalid data).

        SC/SD addresses often have system-preset nicknames that violate validation rules.
        If the row was loaded with errors, we ignore the errors for display purposes.
        """
        return self.loaded_with_error

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

    # --- CRUD Helper Properties (for save logic) ---

    def needs_full_delete(self, is_dirty: bool) -> bool:
        """True if should DELETE the entire row from database."""
        is_default_retentive = self.retentive == DEFAULT_RETENTIVE.get(self.memory_type, False)
        return (
            is_dirty
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
    ) -> tuple[bool, str, bool, str]:
        """Validate this row and return validation state.

        Args:
            all_nicknames: Dict of addr_key -> nickname for uniqueness check
            is_duplicate_fn: Optional O(1) duplicate checker function

        Returns:
            Tuple of (is_valid, validation_error, initial_value_valid, initial_value_error)
        """
        # Validate nickname
        is_valid, validation_error = validate_nickname(
            self.nickname, all_nicknames, self.addr_key, is_duplicate_fn
        )

        # Validate initial value
        initial_value_valid, initial_value_error = validate_initial_value(
            self.initial_value, self.data_type
        )

        # Overall validity includes both
        if not initial_value_valid and is_valid:
            is_valid = False
            validation_error = initial_value_error

        return is_valid, validation_error, initial_value_valid, initial_value_error
