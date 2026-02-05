"""DataView model — re-exports from pyclickplc.dataview.

Also provides a legacy parse_address shim for backward compatibility.
"""

from __future__ import annotations

import re

from pyclickplc.dataview import CODE_TO_MEMORY_TYPES as CODE_TO_MEMORY_TYPES
from pyclickplc.dataview import MAX_DATAVIEW_ROWS as MAX_DATAVIEW_ROWS
from pyclickplc.dataview import MEMORY_TYPE_TO_CODE as MEMORY_TYPE_TO_CODE
from pyclickplc.dataview import WRITABLE_SC as WRITABLE_SC
from pyclickplc.dataview import WRITABLE_SD as WRITABLE_SD
from pyclickplc.dataview import DataviewRow as DataviewRow
from pyclickplc.dataview import TypeCode as TypeCode
from pyclickplc.dataview import create_empty_dataview as create_empty_dataview
from pyclickplc.dataview import display_to_storage as display_to_storage
from pyclickplc.dataview import get_type_code_for_address as get_type_code_for_address
from pyclickplc.dataview import is_address_writable as is_address_writable
from pyclickplc.dataview import storage_to_display as storage_to_display

# Legacy shim: returns (memory_type, number_str) preserving "u" suffix
_ADDRESS_PATTERN = re.compile(r"^([A-Z]+)(\d+[uU]?)$", re.IGNORECASE)


def parse_address(address: str) -> tuple[str, str] | None:
    """Parse an address string into memory type and number (legacy shim).

    Returns (memory_type, number_part_str) preserving 'u' suffix.
    New code should use pyclickplc.addresses.parse_address_display instead.
    """
    if not address:
        return None
    match = _ADDRESS_PATTERN.match(address.strip())
    if not match:
        return None
    return (match.group(1).upper(), match.group(2))
