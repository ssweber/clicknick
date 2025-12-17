"""Address Outline panel for the Address Editor.

Displays a hierarchical treeview of tag nicknames, parsed by underscore segments
with array detection. Allows navigation to addresses via double-click.

Display Rules:
--------------
1. Nicknames are split by underscore into path segments.
   Example: "Admin_Alarm_Reset" -> Admin -> Alarm -> Reset

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
import tkinter as tk
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import ttk

from .address_model import MEMORY_TYPE_BASES

# Reverse mapping: type_index -> memory_type
_INDEX_TO_TYPE: dict[int, str] = {v >> 24: k for k, v in MEMORY_TYPE_BASES.items()}

# Order for processing memory types (SC/SD at end as flat items)
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

# Memory types that should be displayed as flat items (no structure parsing)
FLAT_MEMORY_TYPES = frozenset({"SC", "SD"})

_ARRAY_PATTERN = re.compile(r"^([A-Za-z]+)(\d+)$")


# =============================================================================
# Pure Logic (testable without UI)
# =============================================================================


@dataclass
class TreeNode:
    """A node in the nickname tree."""

    children: dict[str, TreeNode] = field(default_factory=dict)
    child_order: list[str] = field(default_factory=list)  # Tracks insertion order
    leaf: tuple[str, int] | None = None  # (memory_type, address)
    is_array: bool = False


def parse_addr_key(addr_key: int) -> tuple[str, int]:
    """Parse an address key into (memory_type, address)."""
    type_index = addr_key >> 24
    address = addr_key & 0xFFFFFF
    return _INDEX_TO_TYPE.get(type_index, ""), address


def parse_segments(nickname: str) -> list[tuple[str, int | None]]:
    """Parse nickname into segments with optional array indices.

    Returns list of (name, index) tuples. Index is None for non-array segments.
    Example: "Motor1_Speed" -> [("Motor", 1), ("Speed", None)]
    """
    segments = []
    for part in nickname.split("_"):
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
) -> None:
    """Insert a path into the tree, tracking insertion order."""
    for name, index in path:
        # Handle array index: create/navigate to base, then to index
        if index is not None:
            # Get or create base node (e.g., "Motor")
            if name not in node.children:
                node.children[name] = TreeNode(is_array=True)
                node.child_order.append(name)
            node.children[name].is_array = True
            node = node.children[name]
            # Now navigate to index node
            name = str(index)

        if name not in node.children:
            node.children[name] = TreeNode()
            node.child_order.append(name)
        node = node.children[name]

    node.leaf = (memory_type, address)


def _mark_array_nodes(node: TreeNode) -> None:
    """Mark nodes as arrays if they have any numeric children (rule 4)."""
    for child in node.children.values():
        _mark_array_nodes(child)
        if any(k.isdigit() for k in child.children):
            child.is_array = True


def build_tree(entries: list[tuple[str, int, str]]) -> TreeNode:
    """Build tree structure from nickname entries.

    Args:
        entries: List of (memory_type, address, nickname) tuples,
                 in the order they should appear.

    Returns:
        Root TreeNode containing the full tree structure.
    """
    root = TreeNode()

    for memory_type, address, nickname in entries:
        if not nickname:
            continue
        path = parse_segments(nickname)
        if not path:
            continue
        _insert_path(root, path, memory_type, address)

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


def _flatten_node(
    node: TreeNode,
    prefix: str,
    depth: int,
    items: list[dict],
) -> None:
    """Recursively flatten a node and its children."""
    for name in node.child_order:
        child = node.children[name]
        display = f"{name}[#]" if child.is_array else name

        # Rule 3: collapse array index with single leaf child
        if name.isdigit():
            if collapse_info := _get_collapsible_leaf(child):
                child_name, leaf_child = collapse_info
                items.append(
                    {
                        "text": f"• {name} {child_name}",
                        "leaf": leaf_child.leaf,
                        "depth": depth,
                    }
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

        text = " - ".join(current_path)
        is_pure_leaf = collapse_node.leaf is not None and not collapse_node.children

        if is_pure_leaf:
            items.append(
                {
                    "text": f"• {text}",
                    "leaf": collapse_node.leaf,
                    "depth": depth,
                }
            )
        else:
            items.append(
                {
                    "text": text,
                    "leaf": collapse_node.leaf,
                    "depth": depth,
                }
            )
            _flatten_node(collapse_node, text, depth + 1, items)


def flatten_tree(node: TreeNode, prefix: str = "") -> list[dict]:
    """Flatten tree to list of display items for testing.

    Returns list of dicts with keys:
        - 'text': display text
        - 'leaf': (memory_type, address) or None
        - 'depth': nesting level
    """
    items = []
    _flatten_node(node, prefix, 0, items)
    return items


# =============================================================================
# UI Component
# =============================================================================


class OutlinePanel(ttk.Frame):
    """Panel displaying hierarchical treeview of tag nicknames."""

    def _on_double_click(self, event) -> None:
        """Handle double-click on tree item."""
        if selection := self.tree.selection():
            iid = selection[0]
            if leaf_data := self._leaf_data.get(iid):
                memory_type, address = leaf_data
                self.on_address_select(memory_type, address)

    def _create_widgets(self) -> None:
        """Create the treeview widget."""
        header = ttk.Label(self, text="Outline", font=("TkDefaultFont", 9, "bold"))
        header.pack(fill=tk.X, padx=5, pady=(5, 2))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(
            tree_frame,
            show="tree",
            selectmode="browse",
            yscrollcommand=scrollbar.set,
        )
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure tree column width
        self.tree.column("#0", width=180, minwidth=100, stretch=True)

        scrollbar.config(command=self.tree.yview)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

    def __init__(
        self,
        parent: tk.Widget,
        on_address_select: Callable[[str, int], None],
    ):
        """Initialize the outline panel.

        Args:
            parent: Parent widget
            on_address_select: Callback when address is selected (memory_type, address)
        """
        super().__init__(parent, width=200)
        self.pack_propagate(False)

        self.on_address_select = on_address_select
        self._leaf_data: dict[str, tuple[str, int]] = {}

        self._create_widgets()

    def _render_node(self, node: TreeNode, parent_iid: str) -> None:
        """Render a tree node and its children to the treeview."""
        for name in node.child_order:
            child = node.children[name]
            display = f"{name}[#]" if child.is_array else name

            # Rule 3: collapse array index with single leaf child
            if name.isdigit():
                if collapse_info := _get_collapsible_leaf(child):
                    child_name, leaf_child = collapse_info
                    iid = self.tree.insert(parent_iid, tk.END, text=f"• {name} {child_name}")
                    self._leaf_data[iid] = leaf_child.leaf
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

            if is_pure_leaf:
                iid = self.tree.insert(parent_iid, tk.END, text=f"• {text}")
                self._leaf_data[iid] = collapse_node.leaf
            else:
                iid = self.tree.insert(parent_iid, tk.END, text=text)
                if collapse_node.leaf:
                    self._leaf_data[iid] = collapse_node.leaf
                self._render_node(collapse_node, iid)

    def build_tree(self, all_nicknames: dict[int, str]) -> None:
        """Rebuild the tree from nickname data.

        Args:
            all_nicknames: Dict mapping address key to nickname string
        """
        self._leaf_data.clear()

        # Clear existing tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Group nicknames by memory type
        by_type: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for addr_key, nickname in all_nicknames.items():
            memory_type, address = parse_addr_key(addr_key)
            if memory_type:
                by_type[memory_type].append((address, nickname))

        # Build entries list for hierarchical types
        entries: list[tuple[str, int, str]] = []
        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type in FLAT_MEMORY_TYPES:
                continue
            for address, nickname in sorted(by_type.get(memory_type, [])):
                entries.append((memory_type, address, nickname))

        # Build and render tree
        root = build_tree(entries)
        self._render_node(root, parent_iid="")

        # Add flat memory types (SC, SD)
        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type not in FLAT_MEMORY_TYPES:
                continue
            if type_entries := sorted(by_type.get(memory_type, [])):
                parent_iid = self.tree.insert("", tk.END, text=memory_type)
                for address, nickname in type_entries:
                    if nickname:
                        iid = self.tree.insert(parent_iid, tk.END, text=f"• {nickname}")
                        self._leaf_data[iid] = (memory_type, address)

    def refresh(self, all_nicknames: dict[int, str]) -> None:
        """Refresh the tree with updated data."""
        self.build_tree(all_nicknames)
