"""Tree building logic for address outline.

Displays a hierarchical treeview of tag nicknames, parsed by underscore segments
with array detection. Allows navigation to addresses via double-click.

Display Rules:
--------------
1. Nicknames are split by single underscore into path segments.
   Double underscores create an intermediate "_" node for grouping related items.
   Example: "Admin_Alarm_Reset" -> Admin -> Alarm -> Reset
   Example: "Mtr1__Debounce" -> Mtr[1] -> 1 -> _ -> Debounce

2. Trailing numbers on segments are detected as array indices, shown with [min-max].
   Single-element arrays (only one number, no siblings) collapse the number into the name.
   Example: "Motor1_Speed", "Motor2_Speed" -> Motor[1-2] -> 1 -> Speed
   Example: "Prod1_Count" (alone) -> Prod1_Count (no brackets)

3. Array indices with a single leaf child are collapsed into "#_Name" format.
   Example: "Setpoint1_Reached", "Setpoint2_Reached" -> Setpoint[1-2] -> 1_Reached, 2_Reached

4. If both array items (Motor1_X) and non-array items (Motor_Status) share
   the same base name, they are pulled together under the same parent node
   but kept as separate entries, ordered by first occurrence of each type.
   Example: Command_Alarm, Admin_Tag1, Command_Alarm1_id, Command_Alarm2_id, Admin_Tag2, Command_Alarm_Status ->
   + Command
       - Alarm
       + Alarm[1-2]
           - 1_id
           - 2_id
       - Alarm_Status

5. Single-child nodes are collapsed with underscore "_".
   Example: "Timer_Ts" (alone) -> Timer_Ts

6. Underscore nodes (from double underscores) appear last among siblings.
   Example: Mtr1_Speed, Mtr1_Run, Mtr1__Debug -> Speed, Run, then __Debug

7. T/TD and CT/CTD entries are interleaved by address number.
   Example: T1, T2, TD1, TD2 -> T1, TD1, T2, TD2 (in tree insertion order)

8. SC and SD memory types are displayed as flat lists at the bottom of the tree
   without any structure parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ARRAY_PATTERN = re.compile(r"^([A-Za-z]+)(\d+)$")

MEMORY_TYPE_ORDER = [
    "X",
    "Y",
    "C",
    "T",
    "TD",
    "CT",
    "CTD",
    "DS",
    "DD",
    "DH",
    "DF",
    "XD",
    "YD",
    "TXT",
    "SC",
    "SD",
]

FLAT_MEMORY_TYPES = frozenset({"SC", "SD"})


@dataclass
class TreeNode:
    """A node in the nickname tree."""

    children: dict[str, TreeNode] = field(default_factory=dict)
    child_order: list[str] = field(default_factory=list)
    leaf: tuple[str, int, int] | None = None  # (memory_type, address, addr_key)
    is_array: bool = False


@dataclass
class DisplayItem:
    """A flattened item ready for display."""

    text: str
    depth: int
    leaf: tuple[str, int] | None  # (memory_type, address) for leaf nodes
    has_children: bool
    addr_key: int | None = None  # AddrKey for leaf nodes, for looking up full row data


def parse_segments(nickname: str) -> list[tuple[str, int | None]]:
    """Parse nickname into segments with optional array indices.

    Returns list of (name, index) tuples. Index is None for non-array segments.

    Single underscores split segments. Double underscores create an intermediate
    "_" node, grouping items that follow under a special underscore branch.
    Example: "Motor1_Speed" -> [("Motor", 1), ("Speed", None)]
    Example: "Mtr1__Debounce" -> [("Mtr", 1), ("_", None), ("Debounce", None)]
    """
    # Replace __ with placeholder to mark where _ nodes should be inserted
    placeholder = "\x00"
    temp = nickname.replace("__", placeholder)

    segments = []
    for part in temp.split("_"):
        if not part:
            continue
        # Each placeholder in the part represents a _ segment
        subparts = part.split(placeholder)
        for i, subpart in enumerate(subparts):
            if i > 0:
                # This was preceded by __, so insert _ segment
                segments.append(("_", None))
            if not subpart:
                continue
            if match := _ARRAY_PATTERN.match(subpart):
                segments.append((match.group(1), int(match.group(2))))
            else:
                segments.append((subpart, None))
    return segments


def _insert_path(
    node: TreeNode,
    path: list[tuple[str, int | None]],
    memory_type: str,
    address: int,
    addr_key: int,
) -> None:
    """Insert a path into the tree, tracking insertion order."""
    for name, index in path:
        if index is not None:
            if name not in node.children:
                node.children[name] = TreeNode(is_array=True)
                node.child_order.append(name)
            node.children[name].is_array = True
            node = node.children[name]
            name = str(index)

        if name not in node.children:
            node.children[name] = TreeNode()
            node.child_order.append(name)
        node = node.children[name]

    node.leaf = (memory_type, address, addr_key)


def _mark_array_nodes(node: TreeNode) -> None:
    """Mark nodes as arrays if they have any numeric children (rule 4)."""
    for child in node.children.values():
        _mark_array_nodes(child)
        if any(k.isdigit() for k in child.children):
            child.is_array = True


def _interleave_timer_entries(
    entries: list[tuple[str, int, str, int]],
) -> list[tuple[str, int, str, int]]:
    """Reorder entries to interleave T/TD and CT/CTD pairs by address.

    For each T address, the corresponding TD address follows immediately.
    Same for CT/CTD pairs. Other memory types are unaffected.

    Example: T1, T2, TD1, TD2 -> T1, TD1, T2, TD2
    """
    # Build lookup for TD and CTD entries by address
    td_by_addr: dict[int, tuple[str, int, str, int]] = {}
    ctd_by_addr: dict[int, tuple[str, int, str, int]] = {}

    result: list[tuple[str, int, str, int]] = []
    deferred_td: list[tuple[str, int, str, int]] = []
    deferred_ctd: list[tuple[str, int, str, int]] = []

    # First pass: collect TD and CTD entries
    for entry in entries:
        memory_type = entry[0]
        address = entry[1]
        if memory_type == "TD":
            td_by_addr[address] = entry
        elif memory_type == "CTD":
            ctd_by_addr[address] = entry

    # Second pass: build interleaved result
    seen_td: set[int] = set()
    seen_ctd: set[int] = set()

    for entry in entries:
        memory_type = entry[0]
        address = entry[1]

        if memory_type == "TD":
            # Will be inserted after corresponding T, or at end if no T
            if address not in seen_td:
                deferred_td.append(entry)
            continue
        elif memory_type == "CTD":
            # Will be inserted after corresponding CT, or at end if no CT
            if address not in seen_ctd:
                deferred_ctd.append(entry)
            continue

        result.append(entry)

        # If this is T, insert corresponding TD right after
        if memory_type == "T" and address in td_by_addr:
            result.append(td_by_addr[address])
            seen_td.add(address)
        # If this is CT, insert corresponding CTD right after
        elif memory_type == "CT" and address in ctd_by_addr:
            result.append(ctd_by_addr[address])
            seen_ctd.add(address)

    # Append any TD/CTD entries that didn't have a corresponding T/CT
    result.extend(deferred_td)
    result.extend(deferred_ctd)

    return result


def build_tree(entries: list[tuple[str, int, str, int]]) -> TreeNode:
    """Build tree structure from nickname entries.

    Args:
        entries: List of (memory_type, address, nickname, addr_key) tuples,
                 in the order they should appear.

    Returns:
        Root TreeNode containing the full tree structure.
    """
    # Interleave T/TD and CT/CTD pairs so related timers are adjacent
    entries = _interleave_timer_entries(entries)

    root = TreeNode()

    for memory_type, address, nickname, addr_key in entries:
        if not nickname:
            continue
        path = parse_segments(nickname)
        if not path:
            continue
        _insert_path(root, path, memory_type, address, addr_key)

    _mark_array_nodes(root)
    return root


def _get_array_range(node: TreeNode) -> str:
    """Get the array range string for an array node's numeric children.

    Returns format like '[1-3]' for ranges or '[5]' for single items.
    """
    indices = sorted(int(k) for k in node.children if k.isdigit())
    if not indices:
        return "[#]"  # fallback
    if len(indices) == 1:
        return f"[{indices[0]}]"
    return f"[{indices[0]}-{indices[-1]}]"


def _get_collapsible_leaf(node: TreeNode) -> tuple[str, TreeNode] | None:
    """Check if an array index node should collapse with its single leaf child.

    Returns (child_name, child_node) if collapsible, None otherwise.
    """
    if len(node.children) != 1:
        return None
    child_name = node.child_order[0]
    child_node = node.children[child_name]
    if child_node.leaf is not None and not child_node.children:
        return child_name, child_node
    return None


def _extract_leaf_info(
    leaf: tuple[str, int, int] | None,
) -> tuple[tuple[str, int] | None, int | None]:
    """Extract (memory_type, address) tuple and addr_key from leaf data."""
    if leaf is None:
        return None, None
    memory_type, address, addr_key = leaf
    return (memory_type, address), addr_key


def _sort_children_underscore_last(child_order: list[str]) -> list[str]:
    """Sort children so underscore nodes come last, preserving order otherwise."""
    regular = [name for name in child_order if name != "_"]
    underscores = [name for name in child_order if name == "_"]
    return regular + underscores


def _is_single_element_array(node: TreeNode) -> tuple[str, TreeNode] | None:
    """Check if node is an array with exactly one numeric child and no others.

    Returns (number, grandchild) if it should be collapsed, None otherwise.
    """
    if not node.is_array:
        return None
    # Must have exactly one child, and it must be numeric
    if len(node.children) != 1:
        return None
    only_child_name = node.child_order[0]
    if not only_child_name.isdigit():
        return None
    return only_child_name, node.children[only_child_name]


def _flatten_node(node: TreeNode, depth: int, items: list[DisplayItem]) -> None:
    """Recursively flatten a node and its children."""
    sorted_children = _sort_children_underscore_last(node.child_order)
    for name in sorted_children:
        child = node.children[name]

        # Rule 3: collapse array index with single leaf child
        if name.isdigit():
            if collapse_info := _get_collapsible_leaf(child):
                child_name, leaf_child = collapse_info
                leaf_tuple, addr_key = _extract_leaf_info(leaf_child.leaf)
                items.append(
                    DisplayItem(
                        text=f"{name}_{child_name}",
                        depth=depth,
                        leaf=leaf_tuple,
                        has_children=False,
                        addr_key=addr_key,
                    )
                )
                continue

        # Rule 4: Handle array nodes with mixed content (leaf + numeric + non-numeric children)
        if child.is_array:
            numeric_children = [k for k in child.child_order if k.isdigit()]
            non_numeric_children = [k for k in child.child_order if not k.isdigit()]

            # If the array node itself is also a leaf, emit that first as separate item
            if child.leaf is not None:
                leaf_tuple, addr_key = _extract_leaf_info(child.leaf)
                items.append(
                    DisplayItem(
                        text=name,
                        depth=depth,
                        leaf=leaf_tuple,
                        has_children=False,
                        addr_key=addr_key,
                    )
                )

            # Emit the array portion with numeric children
            if numeric_children:
                # Check for single-element array
                if len(numeric_children) == 1 and not non_numeric_children and child.leaf is None:
                    # Single element, no other content - collapse
                    num = numeric_children[0]
                    _flatten_child_with_prefix(f"{name}{num}", child.children[num], depth, items)
                else:
                    # Multi-element or mixed - show array brackets
                    array_range = _get_array_range(child)
                    items.append(
                        DisplayItem(
                            text=f"{name}{array_range}",
                            depth=depth,
                            leaf=None,
                            has_children=True,
                            addr_key=None,
                        )
                    )
                    # Flatten only numeric children under the array
                    for num_name in numeric_children:
                        num_child = child.children[num_name]
                        _flatten_array_index(num_name, num_child, depth + 1, items)

            # Emit non-numeric children separately, collapsed with parent name
            for non_num_name in _sort_children_underscore_last(non_numeric_children):
                non_num_child = child.children[non_num_name]
                _flatten_child_with_prefix(f"{name}_{non_num_name}", non_num_child, depth, items)
            continue

        # Non-array nodes: use standard collapse logic
        _flatten_child_with_prefix(name, child, depth, items)


def _flatten_array_index(name: str, child: TreeNode, depth: int, items: list[DisplayItem]) -> None:
    """Flatten an array index (numeric child) with its content."""
    if collapse_info := _get_collapsible_leaf(child):
        child_name, leaf_child = collapse_info
        leaf_tuple, addr_key = _extract_leaf_info(leaf_child.leaf)
        items.append(
            DisplayItem(
                text=f"{name}_{child_name}",
                depth=depth,
                leaf=leaf_tuple,
                has_children=False,
                addr_key=addr_key,
            )
        )
    elif child.leaf is not None and not child.children:
        # Pure leaf
        leaf_tuple, addr_key = _extract_leaf_info(child.leaf)
        items.append(
            DisplayItem(
                text=name,
                depth=depth,
                leaf=leaf_tuple,
                has_children=False,
                addr_key=addr_key,
            )
        )
    else:
        # Has children, recurse
        items.append(
            DisplayItem(
                text=name,
                depth=depth,
                leaf=None,
                has_children=True,
                addr_key=None,
            )
        )
        _flatten_node(child, depth + 1, items)


def _has_mixed_array_content(node: TreeNode) -> bool:
    """Check if an array node has content that requires separate handling.

    Returns True if the node is an array AND has any of:
    - A leaf value (the base name is itself an address)
    - Non-numeric children (siblings to the array indices)
    """
    if not node.is_array:
        return False
    if node.leaf is not None:
        return True
    return any(not k.isdigit() for k in node.children)


def _flatten_child_with_prefix(
    prefix: str, node: TreeNode, depth: int, items: list[DisplayItem]
) -> None:
    """Flatten a node, collapsing single-child chains into the prefix."""
    current_path = [prefix]
    collapse_node = node

    while len(collapse_node.children) == 1 and collapse_node.leaf is None:
        only_name = collapse_node.child_order[0]
        only_child = collapse_node.children[only_name]
        if only_name.isdigit():
            break
        # Stop collapsing if we hit an array with mixed content - needs special handling
        if _has_mixed_array_content(only_child):
            current_path.append(only_name)
            collapse_node = only_child
            break
        # Check for single-element array within collapse chain
        if single_elem := _is_single_element_array(only_child):
            num, grandchild = single_elem
            segment = f"{only_name}{num}"
            current_path.append(segment)
            collapse_node = grandchild
        elif only_child.is_array:
            segment = f"{only_name}{_get_array_range(only_child)}"
            current_path.append(segment)
            collapse_node = only_child
        else:
            current_path.append(only_name)
            collapse_node = only_child

    text = "_".join(current_path)

    # If we stopped at an array with mixed content, handle it specially
    if _has_mixed_array_content(collapse_node):
        _flatten_mixed_array(text, collapse_node, depth, items)
        return

    is_pure_leaf = collapse_node.leaf is not None and not collapse_node.children
    leaf_tuple, addr_key = _extract_leaf_info(collapse_node.leaf)

    if is_pure_leaf:
        items.append(
            DisplayItem(
                text=text,
                depth=depth,
                leaf=leaf_tuple,
                has_children=False,
                addr_key=addr_key,
            )
        )
    else:
        items.append(
            DisplayItem(
                text=text,
                depth=depth,
                leaf=leaf_tuple,
                has_children=True,
                addr_key=addr_key,
            )
        )
        _flatten_node(collapse_node, depth + 1, items)


def _flatten_mixed_array(name: str, node: TreeNode, depth: int, items: list[DisplayItem]) -> None:
    """Flatten an array node with mixed content (leaf, numeric, non-numeric children)."""
    numeric_children = [k for k in node.child_order if k.isdigit()]
    non_numeric_children = [k for k in node.child_order if not k.isdigit()]

    # If the array node itself is also a leaf, emit that first
    if node.leaf is not None:
        leaf_tuple, addr_key = _extract_leaf_info(node.leaf)
        items.append(
            DisplayItem(
                text=name,
                depth=depth,
                leaf=leaf_tuple,
                has_children=False,
                addr_key=addr_key,
            )
        )

    # Emit the array portion with numeric children
    if numeric_children:
        array_range = _get_array_range(node)
        items.append(
            DisplayItem(
                text=f"{name}{array_range}",
                depth=depth,
                leaf=None,
                has_children=True,
                addr_key=None,
            )
        )
        for num_name in numeric_children:
            num_child = node.children[num_name]
            _flatten_array_index(num_name, num_child, depth + 1, items)

    # Emit non-numeric children separately, collapsed with parent name
    for non_num_name in _sort_children_underscore_last(non_numeric_children):
        non_num_child = node.children[non_num_name]
        _flatten_child_with_prefix(f"{name}_{non_num_name}", non_num_child, depth, items)


def flatten_tree(node: TreeNode) -> list[DisplayItem]:
    """Flatten tree to list of display items.

    Returns list of DisplayItem objects ready for rendering.
    """
    items: list[DisplayItem] = []
    _flatten_node(node, 0, items)
    return items
