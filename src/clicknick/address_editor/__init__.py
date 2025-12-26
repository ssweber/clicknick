"""Address Editor package for viewing, creating, and editing PLC address nicknames."""

from .address_editor_window import AddressEditorWindow
from .address_model import (
    ADDRESS_RANGES,
    COMMENT_MAX_LENGTH,
    FORBIDDEN_CHARS,
    MEMORY_TYPE_BASES,
    NICKNAME_MAX_LENGTH,
    AddressRow,
    get_addr_key,
    parse_addr_key,
    validate_nickname,
)
from .address_panel import AddressPanel
from .data_source import CsvDataSource, DataSource, MdbDataSource
from .mdb_operations import MdbConnection, get_data_for_type, load_all_addresses, save_changes
from .shared_data import SharedAddressData

__all__ = [
    # Constants
    "ADDRESS_RANGES",
    "MEMORY_TYPE_BASES",
    "NICKNAME_MAX_LENGTH",
    "COMMENT_MAX_LENGTH",
    "FORBIDDEN_CHARS",
    # Functions
    "get_addr_key",
    "parse_addr_key",
    "validate_nickname",
    # Classes
    "AddressRow",
    "AddressPanel",
    "AddressEditorWindow",
    "SharedAddressData",
    "MdbConnection",
    # Data sources
    "DataSource",
    "MdbDataSource",
    "CsvDataSource",
    # Database operations
    "load_all_addresses",
    "get_data_for_type",
    "save_changes",
]
