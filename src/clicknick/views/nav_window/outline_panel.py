"""Address Outline panel for the Address Editor.

UI component that renders the tree structure from outline_logic.
"""

from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from collections.abc import Callable
from tkinter import ttk

from ...models.address_row import AddressRow
from .outline_logic import (
    FLAT_MEMORY_TYPES,
    MEMORY_TYPE_ORDER,
    DisplayItem,
    build_tree,
    flatten_tree,
)


class OutlinePanel(ttk.Frame):
    """Panel displaying hierarchical treeview of tag nicknames."""

    def _on_double_click(self, event) -> None:
        """Handle double-click on tree item."""
        if selection := self.tree.selection():
            iid = selection[0]
            if leaf_data := self._leaf_data.get(iid):
                # Single leaf node - use normal callback
                memory_type, address = leaf_data
                self.on_address_select(memory_type, address)
            elif self.on_batch_select:
                # Parent node - collect all leaves and use batch callback
                leaves = self._get_all_leaves_under(iid)
                if leaves:
                    self.on_batch_select(leaves)

    def _get_all_leaves_under(self, iid: str) -> list[tuple[str, int]]:
        """Get all leaf addresses under a parent node.

        Args:
            iid: The tree item id

        Returns:
            List of (memory_type, address) tuples for all leaves
        """
        leaves = []
        self._collect_leaves(iid, leaves)
        return leaves

    def _collect_leaves(self, iid: str, leaves: list[tuple[str, int]]) -> None:
        """Recursively collect all leaf addresses under a node."""
        # Check if this node is a leaf
        if leaf_data := self._leaf_data.get(iid):
            leaves.append(leaf_data)

        # Recurse into children
        for child_iid in self.tree.get_children(iid):
            self._collect_leaves(child_iid, leaves)

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

        self.tree.column("#0", width=200, minwidth=100, stretch=True)

        scrollbar.config(command=self.tree.yview)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

    def __init__(
        self,
        parent: tk.Widget,
        on_address_select: Callable[[str, int], None],
        on_batch_select: Callable[[list[tuple[str, int]]], None] | None = None,
    ):
        """Initialize the outline panel.

        Args:
            parent: Parent widget
            on_address_select: Callback when single address is selected (memory_type, address)
            on_batch_select: Callback when parent node is selected (list of (memory_type, address))
        """
        super().__init__(parent, width=275)
        self.pack_propagate(False)

        self.on_address_select = on_address_select
        self.on_batch_select = on_batch_select
        self._leaf_data: dict[str, tuple[str, int]] = {}

        self._create_widgets()

    def _render_items(self, items: list[DisplayItem], all_rows: dict[int, AddressRow]) -> None:
        """Render pre-flattened items to treeview."""
        parent_stack: list[str] = [""]

        for item in items:
            while len(parent_stack) > item.depth + 1:
                parent_stack.pop()
            parent_iid = parent_stack[-1]

            # For leaf items with addr_key, append outline_suffix from the AddressRow
            display_text = item.text
            if item.addr_key is not None and item.addr_key in all_rows:
                row = all_rows[item.addr_key]
                # Append type/init/retentive suffix to the nickname text
                display_text = f"{item.text} {row.outline_suffix}"

            iid = self.tree.insert(parent_iid, tk.END, text=display_text)

            if item.leaf:
                self._leaf_data[iid] = item.leaf

            if item.has_children:
                parent_stack.append(iid)

    def _prepare_entries(self, all_rows: dict[int, AddressRow]) -> list[tuple[str, int, str, int]]:
        """Prepare sorted entries for tree building."""
        by_type: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
        for addr_key, row in all_rows.items():
            if row.nickname and row.memory_type not in FLAT_MEMORY_TYPES:
                by_type[row.memory_type].append((row.address, row.nickname, addr_key))

        entries: list[tuple[str, int, str, int]] = []
        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type in FLAT_MEMORY_TYPES:
                continue
            for address, nickname, addr_key in sorted(by_type.get(memory_type, [])):
                entries.append((memory_type, address, nickname, addr_key))

        return entries

    def _render_flat_types(self, all_rows: dict[int, AddressRow]) -> None:
        """Render SC/SD as flat lists."""
        by_type: dict[str, list[tuple[int, AddressRow]]] = defaultdict(list)
        for row in all_rows.values():
            if row.memory_type in FLAT_MEMORY_TYPES and row.nickname:
                by_type[row.memory_type].append((row.address, row))

        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type not in FLAT_MEMORY_TYPES:
                continue
            if type_entries := sorted(by_type.get(memory_type, []), key=lambda x: x[0]):
                parent_iid = self.tree.insert("", tk.END, text=memory_type)
                for address, row in type_entries:
                    iid = self.tree.insert(
                        parent_iid, tk.END, text=f"• {row.nickname} {row.outline_suffix}"
                    )
                    self._leaf_data[iid] = (memory_type, address)

    def build_tree(self, all_rows: dict[int, AddressRow]) -> None:
        """Rebuild the tree from address row data.

        Args:
            all_rows: Dict mapping address key to AddressRow
        """
        self._leaf_data.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)

        entries = self._prepare_entries(all_rows)
        root = build_tree(entries)
        items = flatten_tree(root)
        self._render_items(items, all_rows)

        self._render_flat_types(all_rows)

    def refresh(self, all_rows: dict[int, AddressRow]) -> None:
        """Refresh the tree with updated data."""
        self.build_tree(all_rows)
