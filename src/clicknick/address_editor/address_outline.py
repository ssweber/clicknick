"""Address Outline sidebar for the Address Editor.

Displays a hierarchical treeview of tag nicknames, parsed by underscore segments
with array detection. Allows navigation to addresses via double-click.

Display Rules:
--------------
1. Nicknames are split by underscore into path segments.
   Example: "Admin_Alarm_Reset" -> Admin -> Alarm -> Reset

2. Trailing numbers on segments are detected as array indices, shown with [].
   Example: "Motor1_Speed" -> Motor[] -> 1 -> Speed

3. Array indices with a single leaf child are collapsed into "# Name" format.
   Example: "Setpoint1_Reached", "Setpoint2_Reached" -> Setpoint[] -> 1 Reached, 2 Reached

4. If both array items (Motor1_X) and non-array items (Motor_Status) share
   the same base name, they are merged under Base[] with non-array items first.
   Example: Motor_Status, Motor1_Speed, Motor2_Speed -> Motor[] -> Status, 1 Speed, 2 Speed

5. Single-child nodes are collapsed with " - " separator.
   Example: "Timer_Ts" (alone) -> Timer - Ts

6. SC and SD memory types are displayed as flat lists at the bottom of the tree
   without any structure parsing.
"""

from __future__ import annotations

import re
import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

from tksheet import Sheet

from .address_model import MEMORY_TYPE_BASES

if TYPE_CHECKING:
    pass

# Reverse mapping: type_index -> memory_type
_INDEX_TO_TYPE: dict[int, str] = {v >> 24: k for k, v in MEMORY_TYPE_BASES.items()}


def _parse_addr_key(addr_key: int) -> tuple[str, int]:
    """Parse an address key into memory type and address.

    Args:
        addr_key: The address key (combines type and address)

    Returns:
        Tuple of (memory_type, address)
    """
    type_index = addr_key >> 24
    address = addr_key & 0xFFFFFF
    memory_type = _INDEX_TO_TYPE.get(type_index, "")
    return memory_type, address


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


class AddressOutline(ttk.Frame):
    """Sidebar displaying hierarchical treeview of tag nicknames.

    Parses nicknames by underscore to create nested levels.
    Trailing numbers on segments indicate array elements.

    Example:
        Admin_Alm1_id -> Admin -> Alm[] -> 1 -> id
    """

    def _on_double_click(self, event) -> None:
        """Handle double-click on tree item."""
        try:
            # Get currently selected item using treeview property
            iid = self.sheet.tree_selected
            if not iid:
                return

            # Check if this is a leaf with address data
            leaf_data = self._leaf_data.get(iid)
            if leaf_data:
                memory_type, address = leaf_data
                self.on_address_select(memory_type, address)

        except Exception:
            pass  # Ignore errors from clicking empty areas

    def _create_widgets(self) -> None:
        """Create the treeview widget."""
        # Header
        header = ttk.Label(self, text="Outline", font=("TkDefaultFont", 9, "bold"))
        header.pack(fill=tk.X, padx=5, pady=(5, 2))

        # Treeview using tksheet
        self.sheet = Sheet(
            self,
            treeview=True,
            show_x_scrollbar=False,
            show_y_scrollbar=True,
            show_top_left=False,
            show_row_index=True,  # Show row index for tree node text
            show_header=False,
            font=("TkDefaultFont", 9, "normal"),
            index_font=("TkDefaultFont", 9, "normal"),
            header_font=("TkDefaultFont", 9, "normal"),
            index_align="w",  # Required for treeview mode
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Enable selection
        self.sheet.enable_bindings("single_select", "row_select")

        # Bind double-click for navigation
        self.sheet.bind("<Double-Button-1>", self._on_double_click)

    def __init__(
        self,
        parent: tk.Widget,
        on_address_select: Callable[[str, int], None],
    ):
        """Initialize the outline sidebar.

        Args:
            parent: Parent widget
            on_address_select: Callback when address is selected (memory_type, address)
        """
        super().__init__(parent, width=200)
        self.pack_propagate(False)  # Maintain fixed width

        self.on_address_select = on_address_select

        # Map from iid to (memory_type, address) for leaf nodes
        self._leaf_data: dict[str, tuple[str, int]] = {}

        # Counter for generating unique iids
        self._iid_counter = 0

        self._create_widgets()

    def _generate_iid(self) -> str:
        """Generate a unique item ID."""
        self._iid_counter += 1
        return f"item_{self._iid_counter}"

    def _parse_nickname(self, nickname: str) -> list[str]:
        """Parse a nickname into path segments.

        Splits by underscore and detects array patterns (trailing numbers).

        Args:
            nickname: The nickname to parse

        Returns:
            List of path segments. Array patterns become ["Base[]", "index"].

        Example:
            "Admin_Alm1_id" -> ["Admin", "Alm[]", "1", "id"]
            "Command_Start" -> ["Command", "Start"]
        """
        if not nickname:
            return []

        segments = nickname.split("_")
        result = []

        for seg in segments:
            if not seg:
                continue
            # Check for trailing number (array detection)
            # Match: letters followed by digits at end
            match = re.match(r"^([A-Za-z]+)(\d+)$", seg)
            if match:
                base, index = match.groups()
                result.append(f"{base}[]")
                result.append(index)
            else:
                result.append(seg)

        return result

    def _insert_path(
        self,
        tree: OrderedDict,
        path: list[str],
        memory_type: str,
        address: int,
    ) -> None:
        """Insert a path into the tree structure.

        First occurrence of a segment locks its position in the ordered dict.

        Args:
            tree: Current tree level (OrderedDict)
            path: Remaining path segments
            memory_type: Memory type for the leaf
            address: Address number for the leaf
        """
        if not path:
            return

        segment = path[0]
        remaining = path[1:]

        # Get or create node for this segment
        if segment not in tree:
            tree[segment] = {
                "children": OrderedDict(),
                "leaf": None,
                "iid": None,
            }

        node = tree[segment]

        if remaining:
            # Continue down the tree
            self._insert_path(node["children"], remaining, memory_type, address)
        else:
            # This is a leaf node
            node["leaf"] = (memory_type, address)

    def _is_array_index(self, segment: str) -> bool:
        """Check if a segment is a numeric array index."""
        return segment.isdigit()

    def _merge_array_siblings(self, tree: OrderedDict) -> OrderedDict:
        """Merge Base[] nodes with their Base siblings.

        If both 'Setpoint[]' and 'Setpoint' exist, merge them under 'Setpoint[]'
        with non-array children listed first. Keeps [] to indicate array items.
        """
        result: OrderedDict = OrderedDict()

        # Find all array nodes and their potential base matches
        array_nodes = {}  # base_name -> array_node_key
        for key in tree:
            if key.endswith("[]"):
                base = key[:-2]
                array_nodes[base] = key

        processed_keys = set()

        for key, node in tree.items():
            if key in processed_keys:
                continue

            # Recursively process children first
            if node["children"]:
                node["children"] = self._merge_array_siblings(node["children"])

            if key.endswith("[]"):
                base = key[:-2]
                # Check if non-array sibling exists
                if base in tree:
                    # Will be handled when we process the base key
                    processed_keys.add(key)
                    continue
                else:
                    # No sibling, keep as Base[] to indicate array
                    result[key] = node
                    processed_keys.add(key)
            elif key in array_nodes:
                # This is a base with an array sibling - merge them under Base[]
                array_key = array_nodes[key]
                array_node = tree[array_key]

                # Recursively process array node children
                if array_node["children"]:
                    array_node["children"] = self._merge_array_siblings(array_node["children"])

                # Create merged node with non-array children first
                merged_children: OrderedDict = OrderedDict()

                # Add non-array children first
                for child_key, child_node in node["children"].items():
                    merged_children[child_key] = child_node

                # Add array children (indices)
                for child_key, child_node in array_node["children"].items():
                    merged_children[child_key] = child_node

                # Use Base[] as the key to indicate array items present
                result[array_key] = {
                    "children": merged_children,
                    "leaf": node["leaf"],  # Keep leaf from non-array if exists
                    "iid": None,
                }
                processed_keys.add(key)
                processed_keys.add(array_key)
            else:
                result[key] = node
                processed_keys.add(key)

        return result

    def _collapse_array_indices(self, tree: OrderedDict) -> OrderedDict:
        """Collapse array indices that have only one leaf child.

        Transforms: 1 -> Reached (leaf) => "1 Reached" (leaf)
        """
        result: OrderedDict = OrderedDict()

        for key, node in tree.items():
            # Recursively process children first
            if node["children"]:
                node["children"] = self._collapse_array_indices(node["children"])

            # Check if this is an array index with exactly one leaf child
            if self._is_array_index(key) and len(node["children"]) == 1:
                child_key, child_node = next(iter(node["children"].items()))
                # Only collapse if child is a pure leaf (no grandchildren)
                if child_node["leaf"] is not None and not child_node["children"]:
                    # Collapse: "1" with child "Reached" becomes "1 Reached"
                    new_key = f"{key} {child_key}"
                    result[new_key] = {
                        "children": OrderedDict(),
                        "leaf": child_node["leaf"],
                        "iid": None,
                    }
                    continue

            result[key] = node

        return result

    def _collapse_single_children(self, tree: OrderedDict) -> OrderedDict:
        """Collapse nodes that have only one child.

        Transforms: Timer -> Ts (leaf) => "Timer - Ts" (leaf)
        """
        result: OrderedDict = OrderedDict()

        for key, node in tree.items():
            # Recursively process children first
            if node["children"]:
                node["children"] = self._collapse_single_children(node["children"])

            # Check if this node has exactly one child and no leaf data
            if len(node["children"]) == 1 and node["leaf"] is None:
                child_key, child_node = next(iter(node["children"].items()))
                # Collapse: "Timer" with single child "Ts" becomes "Timer - Ts"
                new_key = f"{key} - {child_key}"
                result[new_key] = {
                    "children": child_node["children"],
                    "leaf": child_node["leaf"],
                    "iid": None,
                }
            else:
                result[key] = node

        return result

    def _post_process_tree(self, tree: OrderedDict) -> OrderedDict:
        """Post-process tree to apply display rules.

        Rules applied:
        1. Merge Base[] with Base siblings (non-array items listed first)
        2. Collapse array indices with single leaf children (1 -> Reached => 1 Reached)
        3. Collapse single-child nodes (Timer -> Ts => Timer - Ts)

        Args:
            tree: Tree structure to process

        Returns:
            Processed tree structure
        """
        # First pass: merge Base[] with Base siblings
        tree = self._merge_array_siblings(tree)

        # Second pass: collapse array indices with single leaf children
        tree = self._collapse_array_indices(tree)

        # Third pass: collapse single-child nodes
        tree = self._collapse_single_children(tree)

        return tree

    def _populate_sheet(self, tree: OrderedDict, parent_iid: str = "") -> None:
        """Populate the tksheet treeview from tree structure.

        Args:
            tree: Tree structure to populate from
            parent_iid: Parent item ID (empty string for root)
        """
        for segment, node in tree.items():
            iid = self._generate_iid()
            node["iid"] = iid

            has_children = bool(node["children"])
            is_leaf = node["leaf"] is not None

            # Determine display text
            if is_leaf and not has_children:
                # Pure leaf - show with bullet
                display_text = f"\u2022 {segment}"
            else:
                # Branch node
                display_text = segment

            # Insert item using treeview insert() method
            # text= is displayed in row index, values= are the cell values
            self.sheet.insert(
                parent=parent_iid,
                iid=iid,
                text=display_text,
                values=[],  # No cell values needed, just the tree structure
            )

            # Store leaf data for navigation
            if is_leaf:
                self._leaf_data[iid] = node["leaf"]

            # Recursively add children
            if has_children:
                self._populate_sheet(node["children"], parent_iid=iid)

    def build_tree(self, all_nicknames: dict[int, str]) -> None:
        """Rebuild the tree from nickname data.

        Processes all nicknames in address order (by memory type, then address).
        Uses ordered dict to preserve first-occurrence position.

        Args:
            all_nicknames: Dict mapping address key to nickname string
        """
        # Clear existing data
        self._leaf_data.clear()
        self._iid_counter = 0

        # Reset the treeview
        self.sheet.tree_reset()

        # Build tree structure using ordered dicts
        # Structure: {segment: {"children": OrderedDict, "leaf": (type, addr) or None, "iid": str}}
        tree_root: OrderedDict = OrderedDict()

        # Group nicknames by memory type for ordered processing
        by_type: dict[str, list[tuple[int, str]]] = {}
        for addr_key, nickname in all_nicknames.items():
            memory_type, address = _parse_addr_key(addr_key)
            if not memory_type:
                continue
            if memory_type not in by_type:
                by_type[memory_type] = []
            by_type[memory_type].append((address, nickname))

        # Process types in order (excluding flat types)
        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type in FLAT_MEMORY_TYPES:
                continue

            entries = by_type.get(memory_type, [])
            if not entries:
                continue

            # Process entries in address order
            for address, nickname in sorted(entries, key=lambda x: x[0]):
                if not nickname:
                    continue

                path = self._parse_nickname(nickname)
                if not path:
                    continue

                # Insert path into tree
                self._insert_path(tree_root, path, memory_type, address)

        # Post-process tree (merge arrays, collapse single children)
        tree_root = self._post_process_tree(tree_root)

        # Convert tree structure to tksheet treeview
        self._populate_sheet(tree_root)

        # Add flat memory types at the end (SC, SD) as simple leaf nodes
        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type not in FLAT_MEMORY_TYPES:
                continue

            entries = by_type.get(memory_type, [])
            if not entries:
                continue

            # Create a parent node for this memory type
            parent_iid = self._generate_iid()
            self.sheet.insert(
                parent="",
                iid=parent_iid,
                text=memory_type,
                values=[],
            )

            # Add each nickname as a flat leaf under the parent
            for address, nickname in sorted(entries, key=lambda x: x[0]):
                if not nickname:
                    continue

                iid = self._generate_iid()
                self.sheet.insert(
                    parent=parent_iid,
                    iid=iid,
                    text=f"\u2022 {nickname}",
                    values=[],
                )
                self._leaf_data[iid] = (memory_type, address)

    def refresh(self, all_nicknames: dict[int, str]) -> None:
        """Refresh the tree with updated data.

        Convenience alias for build_tree().

        Args:
            all_nicknames: Dict mapping address key to nickname string
        """
        self.build_tree(all_nicknames)
