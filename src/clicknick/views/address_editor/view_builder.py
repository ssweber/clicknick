"""View building functions for Address Editor.

Extracted from AddressPanel to enable shared view construction.
These functions build TypeView data that can be shared across
multiple panels and windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key, is_xd_yd_hidden_slot
from pyclickplc.banks import BANKS, PAIRED_RETENTIVE_TYPES

from ...models.address_row import AddressRow

if TYPE_CHECKING:
    pass

# Memory types in display order (matches SIDEBAR_TYPES from jump_sidebar.py)
UNIFIED_TYPE_ORDER = [
    "X",
    "Y",
    "C",
    "T/TD",  # Combined T + TD interleaved
    "CT/CTD",  # Combined CT + CTD interleaved
    "SC",
    "DS",
    "DD",
    "DH",
    "DF",
    "XD",
    "YD",
    "SD",
    "TXT",
]

# Types that show combined/interleaved data
COMBINED_TYPES = {
    "T/TD": ["T", "TD"],
    "CT/CTD": ["CT", "CTD"],
}


@dataclass
class UnifiedView:
    """Unified view containing ALL memory types in a single row list.

    This enables a single panel to display all addresses, with section
    boundaries marking where each memory type starts.
    """

    # All rows for all memory types in order
    rows: list[AddressRow] = field(default_factory=list)

    # Maps type_key (e.g., "X", "T/TD") to starting row index
    section_boundaries: dict[str, int] = field(default_factory=dict)

    # Row index labels (e.g., "X001", "T1", "TD1")
    index_labels: list[str] = field(default_factory=list)


def build_single_type_rows(
    all_rows: dict[int, AddressRow],
    mem_type: str,
) -> list[AddressRow]:
    """Build row list by referencing skeleton rows.

    With skeleton architecture, all_rows contains the pre-created skeleton
    AddressRow objects. We simply reference them directly, never creating
    new row objects.

    Args:
        all_rows: Dict mapping AddrKey to skeleton AddressRow objects
        mem_type: Memory type (X, Y, C, etc.)

    Returns:
        List of AddressRow references from the skeleton
    """
    bank = BANKS[mem_type]
    rows = []

    # Use valid_ranges for sparse banks (X/Y), full range for contiguous
    if bank.valid_ranges is not None:
        ranges = bank.valid_ranges
    else:
        ranges = ((bank.min_addr, bank.max_addr),)

    for lo, hi in ranges:
        for addr in range(lo, hi + 1):
            # Skip hidden XD/YD slots (odd addresses >= 3 are upper bytes not displayed)
            if is_xd_yd_hidden_slot(mem_type, addr):
                continue

            addr_key = get_addr_key(mem_type, addr)
            if addr_key in all_rows:
                rows.append(all_rows[addr_key])  # Reference, not copy

    return rows


def build_interleaved_rows(
    all_rows: dict[int, AddressRow],
    types: list[str],
) -> list[AddressRow]:
    """Build interleaved row list by referencing skeleton rows.

    With skeleton architecture, all_rows contains the pre-created skeleton
    AddressRow objects. We simply reference them in interleaved order.

    For T+TD: T1, TD1, T2, TD2, ...
    For CT+CTD: CT1, CTD1, CT2, CTD2, ...

    Args:
        all_rows: Dict mapping AddrKey to skeleton AddressRow objects
        types: List of memory types to interleave (e.g., ["T", "TD"])

    Returns:
        List of interleaved AddressRow references from skeleton
    """
    # Find the common address range
    all_starts = []
    all_ends = []
    for mem_type in types:
        if mem_type in BANKS:
            bank = BANKS[mem_type]
            all_starts.append(bank.min_addr)
            all_ends.append(bank.max_addr)

    if not all_starts:
        return []

    # Use the overlapping range
    range_start = max(all_starts)
    range_end = min(all_ends)

    rows = []
    for addr in range(range_start, range_end + 1):
        # Add a row for each type at this address (interleaved)
        for mem_type in types:
            addr_key = get_addr_key(mem_type, addr)
            if addr_key in all_rows:
                rows.append(all_rows[addr_key])  # Reference, not copy

    return rows


def compute_index_labels(rows: list[AddressRow]) -> list[str]:
    """Compute display labels for row indices.

    Args:
        rows: List of AddressRow

    Returns:
        List of display address strings (e.g., "X001", "T1", "TD1")
    """
    return [row.display_address for row in rows]


def find_paired_row(row: AddressRow, rows: list[AddressRow]) -> AddressRow | None:
    """Find the paired T/CT row for a TD/CTD row.

    TD rows share retentive with T rows at the same address.
    CTD rows share retentive with CT rows at the same address.

    Args:
        row: The row to find a pair for
        rows: List of all rows to search

    Returns:
        The paired row, or None if not found or not a paired type
    """
    paired_type = PAIRED_RETENTIVE_TYPES.get(row.memory_type)
    if not paired_type:
        return None

    # Find the row with the same address and the paired type
    for other_row in rows:
        if other_row.memory_type == paired_type and other_row.address == row.address:
            return other_row

    return None


def build_unified_view(
    all_rows: dict[int, AddressRow],
) -> UnifiedView:
    """Build a unified view containing ALL memory types.

    Creates a single row list containing all addresses in UNIFIED_TYPE_ORDER,
    with T/TD and CT/CTD interleaved. Tracks section boundaries for navigation.

    Args:
        all_rows: Dict mapping AddrKey to AddressRow (preloaded data)

    Returns:
        UnifiedView with all rows and section boundaries
    """
    unified_rows: list[AddressRow] = []
    section_boundaries: dict[str, int] = {}

    for type_key in UNIFIED_TYPE_ORDER:
        # Record where this section starts
        section_boundaries[type_key] = len(unified_rows)

        if type_key in COMBINED_TYPES:
            # Build interleaved rows for combined types (T/TD, CT/CTD)
            combined = COMBINED_TYPES[type_key]
            rows = build_interleaved_rows(all_rows, combined)
        else:
            # Build single type rows
            rows = build_single_type_rows(all_rows, type_key)

        unified_rows.extend(rows)

    # Compute index labels for the unified view
    index_labels = compute_index_labels(unified_rows)

    return UnifiedView(
        rows=unified_rows,
        section_boundaries=section_boundaries,
        index_labels=index_labels,
    )
