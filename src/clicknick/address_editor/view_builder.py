"""View building functions for Address Editor.

Extracted from AddressPanel to enable shared view construction.
These functions build TypeView data that can be shared across
multiple panels and windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .address_model import (
    ADDRESS_RANGES,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_TO_DATA_TYPE,
    PAIRED_RETENTIVE_TYPES,
    is_xd_yd_hidden_slot,
    AddressRow,
    validate_nickname,
)
from .blocktag_model import parse_block_tag

if TYPE_CHECKING:
    from .shared_data import TypeView


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
    from .mdb_operations import get_data_for_type

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
    from .mdb_operations import get_data_for_type

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
    # Build list of colored blocks: (start_idx, end_idx, bg_color)
    colored_blocks: list[tuple[int, int | None, str]] = []

    # Stack for tracking open tags: name -> [(start_idx, bg_color), ...]
    open_tags: dict[str, list[tuple[int, str | None]]] = {}

    for row_idx, row in enumerate(rows):
        block_tag = parse_block_tag(row.comment)
        if not block_tag.name:
            continue

        if block_tag.tag_type == "self-closing":
            if block_tag.bg_color:
                colored_blocks.append((row_idx, row_idx, block_tag.bg_color))
        elif block_tag.tag_type == "open":
            if block_tag.name not in open_tags:
                open_tags[block_tag.name] = []
            open_tags[block_tag.name].append((row_idx, block_tag.bg_color))
        elif block_tag.tag_type == "close":
            if block_tag.name in open_tags and open_tags[block_tag.name]:
                start_idx, start_bg_color = open_tags[block_tag.name].pop()
                if start_bg_color:
                    colored_blocks.append((start_idx, row_idx, start_bg_color))

    # Handle unclosed tags as singular points
    for stack in open_tags.values():
        for start_idx, bg_color in stack:
            if bg_color:
                colored_blocks.append((start_idx, start_idx, bg_color))

    # Build row_idx -> color map, with inner blocks overriding outer
    # Sort by range size descending (larger ranges first), then by start index
    # This ensures inner (smaller) blocks are processed last and override
    colored_blocks.sort(key=lambda b: (-(b[1] - b[0]) if b[1] else 0, b[0]))

    row_colors: dict[int, str] = {}
    for start_idx, end_idx, bg_color in colored_blocks:
        if end_idx is None:
            end_idx = start_idx
        for idx in range(start_idx, end_idx + 1):
            row_colors[idx] = bg_color

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
    from .shared_data import TypeView

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
