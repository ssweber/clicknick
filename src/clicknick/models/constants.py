# ==============================================================================
# Address Memory Map Configuration
# ==============================================================================

# Address ranges by memory type (start, end inclusive) - these are MDB addresses
# For XD/YD: MDB 0=XD0, 1=XD0u, 2=XD1, 4=XD2, 6=XD3, 8=XD4, 10=XD5, 12=XD6, 14=XD7, 16=XD8
# Hidden slots (3,5,7,9,11,13,15) are upper bytes for XD1-8 that aren't displayed
from enum import IntEnum

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
    "XD": (0, 16),  # Input groups: XD0, XD0u, XD1-XD8 (MDB 0-16, skip odd > 1)
    "YD": (0, 16),  # Output groups: YD0, YD0u, YD1-YD8 (MDB 0-16, skip odd > 1)
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

# Hint text for initial value fields by DataType
DATA_TYPE_HINTS: dict[int, str] = {
    DataType.BIT: "0 or 1 (checkbox)",
    DataType.INT: "Range: `-32768` to `32767`",
    DataType.INT2: "Range: `-2147483648` to `2147483647`",
    DataType.FLOAT: "Range: `-3.4028235E+38` to `3.4028235E+38`",
    DataType.HEX: "Range: '0000' to 'FFFF'",
    DataType.TXT: "Single ASCII char: eg 'A'",
}

# Memory types that are exclusively BIT type (no combined types like T/TD)
BIT_ONLY_TYPES: frozenset[str] = frozenset({"X", "Y", "C", "SC"})
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
