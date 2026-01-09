"""View building functions for Address Editor.

Extracted from AddressPanel to enable shared view construction.
These functions build TypeView data that can be shared across
multiple panels and windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...data.shared_data import TypeView
from ...models.address_row import AddressRow, is_xd_yd_hidden_slot
from ...models.blocktag import compute_all_block_ranges
from ...models.constants import (
    ADDRESS_RANGES,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_TO_DATA_TYPE,
    PAIRED_RETENTIVE_TYPES,
)
from ...models.validation import validate_nickname
from ...utils.mdb_operations import get_data_for_type

if TYPE_CHECKING:
    from ...data.shared_data import TypeView

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


def create_row_from_data(
    mem_type: str,
    addr: int,
    data: dict | None,
    all_nicknames: dict[int, str],
) -> AddressRow:
    """Create an AddressRow from database data or defaults.

    Args:
        mem_type: Memory type (X, Y, T, TD, etc.)
        addr: Address number
        data: Data dict from database, or None for virtual row
        all_nicknames: Global nicknames for validation

    Returns:
        Configured AddressRow
    """
    default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, 0)
    default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)

    if data:
        nickname = data.get("nickname", "")
        comment = data.get("comment", "")
        used = data.get("used", False)
        data_type = data.get("data_type", default_data_type)
        initial_value = data.get("initial_value", "")
        retentive = data.get("retentive", default_retentive)

        row = AddressRow(
            memory_type=mem_type,
            address=addr,
            nickname=nickname,
            original_nickname=nickname,
            comment=comment,
            original_comment=comment,
            used=used,
            exists_in_mdb=True,
            data_type=data_type,
            initial_value=initial_value,
            original_initial_value=initial_value,
            retentive=retentive,
            original_retentive=retentive,
        )

        # Mark X/SC/SD rows that load with invalid nicknames
        if mem_type in ("X", "SC", "SD") and nickname:
            is_valid, _ = validate_nickname(nickname, all_nicknames, row.addr_key)
            if not is_valid:
                row.loaded_with_error = True
    else:
        row = AddressRow(
            memory_type=mem_type,
            address=addr,
            exists_in_mdb=False,
            data_type=default_data_type,
            retentive=default_retentive,
            original_retentive=default_retentive,
        )

    return row


def build_single_type_rows(
    all_rows: dict[int, AddressRow],
    mem_type: str,
    all_nicknames: dict[int, str],
) -> list[AddressRow]:
    """Build rows for a single memory type.

    Args:
        all_rows: Dict mapping AddrKey to AddressRow (preloaded data)
        mem_type: Memory type (X, Y, C, etc.)
        all_nicknames: Global dict of all nicknames for validation

    Returns:
        List of AddressRow for all addresses in the range
    """

    start, end = ADDRESS_RANGES[mem_type]
    existing = get_data_for_type(all_rows, mem_type)

    rows = []
    for addr in range(start, end + 1):
        # Skip hidden XD/YD slots (odd addresses >= 3 are upper bytes not displayed)
        if is_xd_yd_hidden_slot(mem_type, addr):
            continue
        data = existing.get(addr)
        row = create_row_from_data(mem_type, addr, data, all_nicknames)
        rows.append(row)

    return rows


def build_interleaved_rows(
    all_rows: dict[int, AddressRow],
    types: list[str],
    all_nicknames: dict[int, str],
) -> list[AddressRow]:
    """Build interleaved rows for combined types.

    For T+TD: T1, TD1, T2, TD2, ...
    For CT+CTD: CT1, CTD1, CT2, CTD2, ...

    Args:
        all_rows: Dict mapping AddrKey to AddressRow (preloaded data)
        types: List of memory types to interleave (e.g., ["T", "TD"])
        all_nicknames: Global dict of all nicknames for validation

    Returns:
        List of interleaved AddressRow
    """

    # Get existing data for all types from preloaded data
    existing_by_type = {}
    for mem_type in types:
        existing_by_type[mem_type] = get_data_for_type(all_rows, mem_type)

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
            data = existing_by_type[mem_type].get(addr)
            row = create_row_from_data(mem_type, addr, data, all_nicknames)
            rows.append(row)

    return rows


def compute_block_colors(rows: list[AddressRow]) -> dict[int, str]:
    """Compute block background colors for each row index.

    Parses block tags from row comments to determine which rows
    should have colored row indices. Nested blocks override outer blocks.

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


def build_type_view(
    all_rows: dict[int, AddressRow],
    type_key: str,
    all_nicknames: dict[int, str],
    combined_types: list[str] | None = None,
) -> TypeView:
    """Build a complete TypeView for a memory type.

    Args:
        all_rows: Dict mapping AddrKey to AddressRow (preloaded data)
        type_key: The type key (e.g., "X", "T/TD")
        all_nicknames: Global dict of all nicknames for validation
        combined_types: List of types to interleave (e.g., ["T", "TD"]), or None

    Returns:
        Populated TypeView
    """

    # Build rows
    if combined_types and len(combined_types) > 1:
        rows = build_interleaved_rows(all_rows, combined_types, all_nicknames)
    else:
        # Single type - extract from type_key
        mem_type = type_key.split("/")[0]  # Handle "T/TD" -> "T"
        rows = build_single_type_rows(all_rows, mem_type, all_nicknames)

    # Compute cached data
    block_colors = compute_block_colors(rows)
    index_labels = compute_index_labels(rows)

    return TypeView(
        type_key=type_key,
        rows=rows,
        display_data=[],  # Display data computed by panel (has UI-specific logic)
        index_labels=index_labels,
        block_colors=block_colors,
        combined_types=combined_types,
    )


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
