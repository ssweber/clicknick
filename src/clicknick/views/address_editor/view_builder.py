"""View building functions for Address Editor.

Extracted from AddressPanel to enable shared view construction.
These functions build TypeView data that can be shared across
multiple panels and windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...models.address_row import AddressRow, get_addr_key, is_xd_yd_hidden_slot
from ...models.constants import (
    ADDRESS_RANGES,
    PAIRED_RETENTIVE_TYPES,
)
from ...services.block_service import compute_all_block_ranges

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

    # Block colors computed from comments (row_idx -> color_name)
    block_colors: dict[int, str] = field(default_factory=dict)


def build_single_type_rows(
    all_rows: dict[int, AddressRow],
    mem_type: str,
    all_nicknames: dict[int, str],
) -> list[AddressRow]:
    """Build row list by referencing skeleton rows.

    With skeleton architecture, all_rows contains the pre-created skeleton
    AddressRow objects. We simply reference them directly, never creating
    new row objects.

    Args:
        all_rows: Dict mapping AddrKey to skeleton AddressRow objects
        mem_type: Memory type (X, Y, C, etc.)
        all_nicknames: Global dict of all nicknames (kept for API compatibility)

    Returns:
        List of AddressRow references from the skeleton
    """
    start, end = ADDRESS_RANGES[mem_type]
    rows = []

    for addr in range(start, end + 1):
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
    all_nicknames: dict[int, str],
) -> list[AddressRow]:
    """Build interleaved row list by referencing skeleton rows.

    With skeleton architecture, all_rows contains the pre-created skeleton
    AddressRow objects. We simply reference them in interleaved order.

    For T+TD: T1, TD1, T2, TD2, ...
    For CT+CTD: CT1, CTD1, CT2, CTD2, ...

    Args:
        all_rows: Dict mapping AddrKey to skeleton AddressRow objects
        types: List of memory types to interleave (e.g., ["T", "TD"])
        all_nicknames: Global dict of all nicknames (kept for API compatibility)

    Returns:
        List of interleaved AddressRow references from skeleton
    """
    # Find the common address range
    all_starts = []
    all_ends = []
    for mem_type in types:
        if mem_type in ADDRESS_RANGES:
            start, end = ADDRESS_RANGES[mem_type]
            all_starts.append(start)
            all_ends.append(end)

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


def compute_block_colors(rows: list[AddressRow]) -> dict[int, str]:
    """Compute block background colors for each row index.

    Parses block tags from row comments to determine which rows
    should have colored row indices. Nested blocks override outer blocks.
    Only colors rows matching the block's memory_type (for interleaved views).

    Args:
        rows: List of AddressRow to process

    Returns:
        Dict mapping row index to bg color string
    """
    # Get all block ranges using centralized function
    ranges = compute_all_block_ranges(rows)

    # Filter to only blocks with colors
    colored_ranges = [r for r in ranges if r.bg_color]

    # Build row_idx -> color map, with inner blocks overriding outer
    # Sort by range size descending (larger ranges first)
    # This ensures inner (smaller) blocks are processed last and override
    colored_ranges.sort(key=lambda r: -(r.end_idx - r.start_idx))

    row_colors: dict[int, str] = {}
    for block in colored_ranges:
        for idx in range(block.start_idx, block.end_idx + 1):
            # Only color rows matching the block's memory_type (for interleaved views)
            if block.memory_type and rows[idx].memory_type != block.memory_type:
                continue
            row_colors[idx] = block.bg_color  # type: ignore[assignment]

    return row_colors


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
    all_nicknames: dict[int, str],
) -> UnifiedView:
    """Build a unified view containing ALL memory types.

    Creates a single row list containing all addresses in UNIFIED_TYPE_ORDER,
    with T/TD and CT/CTD interleaved. Tracks section boundaries for navigation.

    Args:
        all_rows: Dict mapping AddrKey to AddressRow (preloaded data)
        all_nicknames: Global dict of all nicknames for validation

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
            rows = build_interleaved_rows(all_rows, combined, all_nicknames)
        else:
            # Build single type rows
            rows = build_single_type_rows(all_rows, type_key, all_nicknames)

        unified_rows.extend(rows)

    # Compute block colors and index labels for the unified view
    block_colors = compute_block_colors(unified_rows)
    index_labels = compute_index_labels(unified_rows)

    return UnifiedView(
        rows=unified_rows,
        section_boundaries=section_boundaries,
        index_labels=index_labels,
        block_colors=block_colors,
    )
