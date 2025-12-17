"""Tree building logic for address outline.

Displays a hierarchical treeview of tag nicknames, parsed by underscore segments
with array detection. Allows navigation to addresses via double-click.

Display Rules:
--------------
1. Nicknames are split by single underscore into path segments.
   Double underscores escape a literal underscore in the segment name.
   Example: "Admin_Alarm_Reset" -> Admin -> Alarm -> Reset
   Example: "Modbus__x" -> Modbus -> _x (double underscore preserves literal _)

2. Trailing numbers on segments are detected as array indices, shown with [].
   Example: "Motor1_Speed" -> Motor[#] -> 1 -> Speed

3. Array indices with a single leaf child are collapsed into "# Name" format.
   Example: "Setpoint1_Reached", "Setpoint2_Reached" -> Setpoint[#] -> 1 Reached, 2 Reached

4. If both array items (Motor1_X) and non-array items (Motor_Status) share
   the same base name, they are pulled together under the same parent node
   but kept as separate entries, ordered by first occurrence of each type.
   Example: Command_Alarm, Admin_Tag1, Command_Alarm1_id, Command_Alarm2_id, Admin_Tag2, Command_Alarm_Status ->
   + Command
       - Alarm
       + Alarm[#]
           - 1 id
           - 2 id
       - Alarm Status

5. Single-child nodes are collapsed with space " ".
   Example: "Timer_Ts" (alone) -> Timer Ts

6. SC and SD memory types are displayed as flat lists at the bottom of the tree
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
    "CT",
    "DS",
    "DD",
    "DH",
    "DF",
    "XD",
    "YD",
    "TD",
    "CTD",
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

    Single underscores split segments. Double underscores also split, but preserve
    a leading underscore on the following segment.
    Example: "Motor1_Speed" -> [("Motor", 1), ("Speed", None)]
    Example: "Modbus__x" -> [("Modbus", None), ("_x", None)]
    """
    # Replace __ with _<placeholder> so it splits but preserves _ on next segment
    placeholder = "\x00"
    escaped = nickname.replace("__", "_" + placeholder)

    segments = []
    for part in escaped.split("_"):
        # Restore underscores from placeholder
        part = part.replace(placeholder, "_")
        if not part:
            continue
        if match := _ARRAY_PATTERN.match(part):
            segments.append((match.group(1), int(match.group(2))))
        else:
            segments.append((part, None))
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


def build_tree(entries: list[tuple[str, int, str, int]]) -> TreeNode:
    """Build tree structure from nickname entries.

    Args:
        entries: List of (memory_type, address, nickname, addr_key) tuples,
                 in the order they should appear.

    Returns:
        Root TreeNode containing the full tree structure.
    """
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


def _flatten_node(node: TreeNode, depth: int, items: list[DisplayItem]) -> None:
    """Recursively flatten a node and its children."""
    for name in node.child_order:
        child = node.children[name]
        display = f"{name}[#]" if child.is_array else name

        # Rule 3: collapse array index with single leaf child
        if name.isdigit():
            if collapse_info := _get_collapsible_leaf(child):
                child_name, leaf_child = collapse_info
                leaf_tuple, addr_key = _extract_leaf_info(leaf_child.leaf)
                items.append(
                    DisplayItem(
                        text=f"• {name} {child_name}",
                        depth=depth,
                        leaf=leaf_tuple,
                        has_children=False,
                        addr_key=addr_key,
                    )
                )
                continue

        # Rule 5: collapse single-child chains
        current_path = [display]
        collapse_node = child

        while len(collapse_node.children) == 1 and collapse_node.leaf is None:
            only_name = collapse_node.child_order[0]
            only_child = collapse_node.children[only_name]
            if only_name.isdigit():
                break
            segment = f"{only_name}[#]" if only_child.is_array else only_name
            current_path.append(segment)
            collapse_node = only_child

        text = " ".join(current_path)
        is_pure_leaf = collapse_node.leaf is not None and not collapse_node.children
        leaf_tuple, addr_key = _extract_leaf_info(collapse_node.leaf)

        if is_pure_leaf:
            items.append(
                DisplayItem(
                    text=f"• {text}",
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


def flatten_tree(node: TreeNode) -> list[DisplayItem]:
    """Flatten tree to list of display items.

    Returns list of DisplayItem objects ready for rendering.
    """
    items: list[DisplayItem] = []
    _flatten_node(node, 0, items)
    return items
