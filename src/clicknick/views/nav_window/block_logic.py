"""Tree-building helpers for the Blocks panel.

Converts flat BlockRange results into a renderable tree model:
- Flat blocks remain top-level actionable rows.
- UDT-style names (Base.field) become Base parent nodes with field children.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pyclickplc.blocks import BlockRange, parse_structured_block_name

from ...models.address_row import AddressRow


@dataclass(frozen=True)
class BlockTreeNode:
    """Renderable block tree node for the Blocks panel."""

    node_id: str
    text: str
    addresses: tuple[tuple[str, int], ...]
    bg_color: str | None = None
    children: tuple[BlockTreeNode, ...] = ()
    is_group: bool = False
    start_idx: int = 0


@dataclass(frozen=True)
class _BlockEntry:
    """Internal normalized block entry used for grouping/sorting."""

    idx: int
    name: str
    base: str
    field: str | None
    kind: str
    start_idx: int
    bg_color: str | None
    addresses: tuple[tuple[str, int], ...]
    start_display: str
    end_display: str


_UDT_WITH_METADATA_RE = re.compile(
    r"^(?P<base>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)(?P<meta>(?::.+|\s.+)?)$"
)


def _format_with_range(label: str, start: str, end: str) -> str:
    """Format block text with single-point or range display."""
    if start == end:
        return f"{label} ({start})"
    return f"{label} ({start}-{end})"


def _dedupe_addresses(
    addresses: list[tuple[str, int]] | tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    """Deduplicate addresses preserving first occurrence order."""
    seen: set[tuple[str, int]] = set()
    result: list[tuple[str, int]] = []
    for item in addresses:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)


def _parse_grouping_name(name: str) -> tuple[str, str | None, str]:
    """Parse block name for tree grouping, preserving child metadata after ':' or space."""
    parsed = parse_structured_block_name(name)
    if parsed.kind == "udt" and parsed.field is not None:
        return parsed.base, parsed.field, parsed.kind

    metadata_match = _UDT_WITH_METADATA_RE.fullmatch(name)
    if metadata_match is not None:
        field = metadata_match.group("field")
        metadata = metadata_match.group("meta") or ""
        return metadata_match.group("base"), field + metadata, "udt"

    return parsed.base, None, parsed.kind


def _build_entries(ranges: list[BlockRange], rows: Sequence[AddressRow]) -> list[_BlockEntry]:
    """Build normalized entries from matched block ranges."""
    entries: list[_BlockEntry] = []
    for idx, block in enumerate(ranges):
        block_rows = rows[block.start_idx : block.end_idx + 1]
        if not block_rows:
            continue

        base, field, kind = _parse_grouping_name(block.name)
        addresses = tuple((row.memory_type, row.address) for row in block_rows)

        entries.append(
            _BlockEntry(
                idx=idx,
                name=block.name,
                base=base,
                field=field,
                kind=kind,
                start_idx=block.start_idx,
                bg_color=block.bg_color,
                addresses=addresses,
                start_display=block_rows[0].display_address,
                end_display=block_rows[-1].display_address,
            )
        )
    return entries


def _build_flat_node(entry: _BlockEntry) -> BlockTreeNode:
    """Create a top-level actionable node for non-UDT names."""
    text = _format_with_range(entry.name, entry.start_display, entry.end_display)
    return BlockTreeNode(
        node_id=f"flat:{entry.idx}",
        text=text,
        addresses=entry.addresses,
        bg_color=entry.bg_color,
        start_idx=entry.start_idx,
    )


def _build_udt_node(
    base: str, entries: list[_BlockEntry], *, sort_alphabetically: bool
) -> BlockTreeNode:
    """Create one UDT parent node and its field children."""
    by_field: dict[str, list[_BlockEntry]] = {}
    field_order: list[str] = []
    for entry in entries:
        if entry.field is None:
            continue
        by_field.setdefault(entry.field, []).append(entry)
        if entry.field not in field_order:
            field_order.append(entry.field)

    if sort_alphabetically:
        ordered_fields = sorted(by_field.keys(), key=str.lower)
    else:
        ordered_fields = field_order

    children: list[BlockTreeNode] = []
    for field in ordered_fields:
        field_entries = by_field.get(field, [])
        if sort_alphabetically:
            field_entries = sorted(field_entries, key=lambda item: item.start_idx)

        for entry in field_entries:
            child_text = _format_with_range(field, entry.start_display, entry.end_display)
            children.append(
                BlockTreeNode(
                    node_id=f"udt:{base}:{field}:{entry.start_idx}:{entry.idx}",
                    text=child_text,
                    addresses=entry.addresses,
                    bg_color=entry.bg_color,
                    start_idx=entry.start_idx,
                )
            )

    parent_addresses: list[tuple[str, int]] = []
    for child in children:
        parent_addresses.extend(child.addresses)

    first_start_idx = min((entry.start_idx for entry in entries), default=0)
    return BlockTreeNode(
        node_id=f"udt:{base}",
        text=base,
        addresses=_dedupe_addresses(parent_addresses),
        children=tuple(children),
        is_group=True,
        start_idx=first_start_idx,
    )


def build_block_tree(
    ranges: list[BlockRange],
    rows: Sequence[AddressRow],
    *,
    sort_alphabetically: bool,
) -> list[BlockTreeNode]:
    """Build display tree nodes from block ranges and row data."""
    entries = _build_entries(ranges, rows)

    flat_entries: list[_BlockEntry] = []
    udt_entries_by_base: dict[str, list[_BlockEntry]] = {}
    top_level_order: list[tuple[str, str | int]] = []
    seen_bases: set[str] = set()

    for entry in entries:
        if entry.kind == "udt" and entry.field is not None:
            udt_entries_by_base.setdefault(entry.base, []).append(entry)
            if entry.base not in seen_bases:
                top_level_order.append(("udt", entry.base))
                seen_bases.add(entry.base)
            continue

        flat_entries.append(entry)
        top_level_order.append(("flat", entry.idx))

    flat_nodes = {entry.idx: _build_flat_node(entry) for entry in flat_entries}
    udt_nodes = {
        base: _build_udt_node(base, base_entries, sort_alphabetically=sort_alphabetically)
        for base, base_entries in udt_entries_by_base.items()
    }

    if sort_alphabetically:
        nodes = list(udt_nodes.values()) + list(flat_nodes.values())
        return sorted(nodes, key=lambda node: (node.text.lower(), node.start_idx))

    result: list[BlockTreeNode] = []
    for kind, key in top_level_order:
        if kind == "udt":
            node = udt_nodes.get(key)  # type: ignore[arg-type]
        else:
            node = flat_nodes.get(key)  # type: ignore[arg-type]
        if node is not None:
            result.append(node)
    return result
