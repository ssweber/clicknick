"""Data model for the Dataview Editor.

Defines the DataviewRow dataclass and type code mappings for CLICK PLC DataView files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Type codes used in CDV files to identify address types
class TypeCode:
    """Type codes for CDV file format."""

    BIT = 768
    INT = 0
    INT2 = 256
    HEX = 3
    FLOAT = 257
    TXT = 1024


# Map memory type prefixes to their type codes
MEMORY_TYPE_TO_CODE: dict[str, int] = {
    "X": TypeCode.BIT,
    "Y": TypeCode.BIT,
    "C": TypeCode.BIT,
    "T": TypeCode.BIT,
    "CT": TypeCode.BIT,
    "SC": TypeCode.BIT,
    "DS": TypeCode.INT,
    "TD": TypeCode.INT,
    "SD": TypeCode.INT,
    "DD": TypeCode.INT2,
    "CTD": TypeCode.INT2,
    "DH": TypeCode.HEX,
    "XD": TypeCode.HEX,
    "YD": TypeCode.HEX,
    "DF": TypeCode.FLOAT,
    "TXT": TypeCode.TXT,
}

# Reverse mapping: type code to list of memory types
CODE_TO_MEMORY_TYPES: dict[int, list[str]] = {
    TypeCode.BIT: ["X", "Y", "C", "T", "CT", "SC"],
    TypeCode.INT: ["DS", "TD", "SD"],
    TypeCode.INT2: ["DD", "CTD"],
    TypeCode.HEX: ["DH", "XD", "YD"],
    TypeCode.FLOAT: ["DF"],
    TypeCode.TXT: ["TXT"],
}

# SC addresses that are writable (most SC are read-only system controls)
WRITABLE_SC: frozenset[int] = frozenset({50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121})

# SD addresses that are writable (most SD are read-only system data)
WRITABLE_SD: frozenset[int] = frozenset(
    {
        29,
        31,
        32,
        34,
        35,
        36,
        40,
        41,
        42,
        50,
        51,
        60,
        61,
        106,
        107,
        108,
        112,
        113,
        114,
        140,
        141,
        142,
        143,
        144,
        145,
        146,
        147,
        214,
        215,
    }
)

# Max rows in a dataview
MAX_DATAVIEW_ROWS = 100

# Regex to parse address strings like "X001", "DS1", "CTD250"
ADDRESS_PATTERN = re.compile(r"^([A-Z]+)(\d+[uU]?)$", re.IGNORECASE)


def parse_address(address: str) -> tuple[str, str] | None:
    """Parse an address string into memory type and number.

    Args:
        address: Address string like "X001", "DS1", "XD0u"

    Returns:
        Tuple of (memory_type, number_part) or None if invalid.
        Number part includes 'u' suffix for upper byte if present.
    """
    if not address:
        return None
    match = ADDRESS_PATTERN.match(address.strip())
    if not match:
        return None
    return (match.group(1).upper(), match.group(2))


def get_type_code_for_address(address: str) -> int | None:
    """Get the type code for an address.

    Args:
        address: Address string like "X001", "DS1"

    Returns:
        Type code or None if address is invalid.
    """
    parsed = parse_address(address)
    if not parsed:
        return None
    memory_type, _ = parsed
    return MEMORY_TYPE_TO_CODE.get(memory_type)


def is_address_writable(address: str) -> bool:
    """Check if an address is writable (can have a New Value set).

    Most addresses are writable, but SC and SD have specific writable addresses.
    XD and YD are read-only.

    Args:
        address: Address string like "X001", "SC50"

    Returns:
        True if the address can have a New Value written to it.
    """
    parsed = parse_address(address)
    if not parsed:
        return False

    memory_type, number_part = parsed

    # XD and YD are read-only
    if memory_type in ("XD", "YD"):
        return False

    # SC has specific writable addresses
    if memory_type == "SC":
        try:
            addr_num = int(number_part)
            return addr_num in WRITABLE_SC
        except ValueError:
            return False

    # SD has specific writable addresses
    if memory_type == "SD":
        try:
            addr_num = int(number_part)
            return addr_num in WRITABLE_SD
        except ValueError:
            return False

    # All other addresses are writable
    return True


@dataclass
class DataviewRow:
    """Represents a single row in a CLICK DataView.

    A dataview row contains an address to monitor and optionally a new value
    to write to that address. The nickname and comment are display-only
    fields populated from SharedAddressData.
    """

    # Core data (stored in CDV file)
    address: str = ""  # e.g., "X001", "DS1", "CTD250"
    type_code: int = 0  # Type code for the address
    new_value: str = ""  # Optional new value to write

    # Display-only fields (populated from SharedAddressData)
    nickname: str = field(default="", compare=False)
    comment: str = field(default="", compare=False)

    @property
    def is_empty(self) -> bool:
        """Check if this row is empty (no address set)."""
        return not self.address.strip()

    @property
    def is_writable(self) -> bool:
        """Check if this address can have a New Value written to it."""
        return is_address_writable(self.address)

    @property
    def memory_type(self) -> str | None:
        """Get the memory type prefix (X, Y, DS, etc.) or None if invalid."""
        parsed = parse_address(self.address)
        return parsed[0] if parsed else None

    @property
    def address_number(self) -> str | None:
        """Get the address number part or None if invalid."""
        parsed = parse_address(self.address)
        return parsed[1] if parsed else None

    def update_type_code(self) -> bool:
        """Update the type code based on the current address.

        Returns:
            True if type code was updated, False if address is invalid.
        """
        code = get_type_code_for_address(self.address)
        if code is not None:
            self.type_code = code
            return True
        return False

    def clear(self) -> None:
        """Clear all fields in this row."""
        self.address = ""
        self.type_code = 0
        self.new_value = ""
        self.nickname = ""
        self.comment = ""


def create_empty_dataview(count: int = MAX_DATAVIEW_ROWS) -> list[DataviewRow]:
    """Create a new empty dataview with the specified number of rows.

    Args:
        count: Number of rows to create (default MAX_DATAVIEW_ROWS).

    Returns:
        List of empty DataviewRow objects.
    """
    return [DataviewRow() for _ in range(count)]


# --- New Value Conversion Functions ---
# CDV files store values in specific formats that need conversion for display


def storage_to_display(value: str, type_code: int) -> str:
    """Convert a stored CDV value to display format.

    Args:
        value: The raw value from the CDV file
        type_code: The type code (TypeCode.BIT, TypeCode.INT, etc.)

    Returns:
        Human-readable display value
    """
    if not value:
        return ""

    try:
        if type_code == TypeCode.BIT:
            # BIT: 0 or 1
            return "1" if value == "1" else "0"

        elif type_code == TypeCode.INT:
            # INT (16-bit signed): Stored as unsigned 32-bit with sign extension
            # Convert back to signed 16-bit
            unsigned_val = int(value)
            # Mask to 16 bits and convert to signed
            val_16bit = unsigned_val & 0xFFFF
            if val_16bit >= 0x8000:
                val_16bit -= 0x10000
            return str(val_16bit)

        elif type_code == TypeCode.INT2:
            # INT2 (32-bit signed): Stored as unsigned 32-bit
            # Convert back to signed 32-bit
            unsigned_val = int(value)
            if unsigned_val >= 0x80000000:
                unsigned_val -= 0x100000000
            return str(unsigned_val)

        elif type_code == TypeCode.HEX:
            # HEX: Display as 4-digit hex, uppercase, NO suffix.
            decimal_val = int(value)
            return format(decimal_val, "04X")

        elif type_code == TypeCode.FLOAT:
            # FLOAT: Stored as IEEE 754 32-bit integer representation
            import struct

            int_val = int(value)
            # Convert integer to bytes (unsigned 32-bit)
            bytes_val = struct.pack(">I", int_val & 0xFFFFFFFF)
            # Interpret as big-endian float
            float_val = struct.unpack(">f", bytes_val)[0]
            
            # Use 'G' for general format:
            # 1. Automatically uses Scientific notation for large numbers
            # 2. Automatically trims trailing zeros for small numbers
            # 3. Uppercase 'E'
            return f"{float_val:.7G}"

        elif type_code == TypeCode.TXT:
            # TXT: Stored as ASCII code, display as character
            ascii_code = int(value)
            if 32 <= ascii_code <= 126:  # Printable ASCII
                return chr(ascii_code)
            return str(ascii_code)  # Non-printable: show as number

        else:
            return value

    except (ValueError, struct.error):
        return value


def display_to_storage(value: str, type_code: int) -> str:
    """Convert a display value to CDV storage format.

    Args:
        value: The human-readable display value
        type_code: The type code (TypeCode.BIT, TypeCode.INT, etc.)

    Returns:
        Value formatted for CDV file storage
    """
    if not value:
        return ""

    try:
        if type_code == TypeCode.BIT:
            # BIT: 0 or 1
            return "1" if value in ("1", "True", "true", "ON", "on") else "0"

        elif type_code == TypeCode.INT:
            # INT (16-bit signed): Convert to unsigned 32-bit with sign extension
            signed_val = int(value)
            # Clamp to 16-bit signed range
            signed_val = max(-32768, min(32767, signed_val))
            # Convert to unsigned 32-bit representation
            if signed_val < 0:
                unsigned_val = signed_val + 0x100000000
            else:
                unsigned_val = signed_val
            return str(unsigned_val)

        elif type_code == TypeCode.INT2:
            # INT2 (32-bit signed): Convert to unsigned 32-bit
            signed_val = int(value)
            # Clamp to 32-bit signed range
            signed_val = max(-2147483648, min(2147483647, signed_val))
            if signed_val < 0:
                unsigned_val = signed_val + 0x100000000
            else:
                unsigned_val = signed_val
            return str(unsigned_val)

        elif type_code == TypeCode.HEX:
            # HEX: Convert hex string to decimal
            # Support with or without 0x prefix
            hex_val = value.strip()
            if hex_val.lower().startswith("0x"):
                hex_val = hex_val[2:]
            decimal_val = int(hex_val, 16)
            return str(decimal_val)

        elif type_code == TypeCode.FLOAT:
            # Display (String) -> Float -> IEEE 754 Bytes -> Int -> Storage (String)
            import struct

            float_val = float(value)
            # Convert float to bytes
            bytes_val = struct.pack(">f", float_val)
            # Interpret as unsigned 32-bit integer
            int_val = struct.unpack(">I", bytes_val)[0]
            return str(int_val)

        elif type_code == TypeCode.TXT:
            # TXT: Convert character to ASCII code
            if len(value) == 1:
                return str(ord(value))
            # If it's already a number, keep it
            return str(int(value))

        else:
            return value

    except (ValueError, struct.error):
        return value


# Import struct at module level for efficiency
