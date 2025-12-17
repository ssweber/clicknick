"""Address Outline panel for the Address Editor.

UI component that renders the tree structure from outline_logic.
"""

from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from collections.abc import Callable
from tkinter import ttk

from .address_model import MEMORY_TYPE_BASES
from .outline_logic import (
    FLAT_MEMORY_TYPES,
    MEMORY_TYPE_ORDER,
    DisplayItem,
    build_tree,
    flatten_tree,
)

# Reverse mapping: type_index -> memory_type
_INDEX_TO_TYPE: dict[int, str] = {v >> 24: k for k, v in MEMORY_TYPE_BASES.items()}


def parse_addr_key(addr_key: int) -> tuple[str, int]:
    """Parse an address key into (memory_type, address)."""
    type_index = addr_key >> 24
    address = addr_key & 0xFFFFFF
    return _INDEX_TO_TYPE.get(type_index, ""), address


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

    def _render_items(self, items: list[DisplayItem]) -> None:
        """Render pre-flattened items to treeview."""
        parent_stack: list[str] = [""]

        for item in items:
            while len(parent_stack) > item.depth + 1:
                parent_stack.pop()
            parent_iid = parent_stack[-1]

            iid = self.tree.insert(parent_iid, tk.END, text=item.text)

            if item.leaf:
                self._leaf_data[iid] = item.leaf

            if item.has_children:
                parent_stack.append(iid)

    def _prepare_entries(self, all_nicknames: dict[int, str]) -> list[tuple[str, int, str]]:
        """Prepare sorted entries for tree building."""
        by_type: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for addr_key, nickname in all_nicknames.items():
            memory_type, address = parse_addr_key(addr_key)
            if memory_type:
                by_type[memory_type].append((address, nickname))

        entries: list[tuple[str, int, str]] = []
        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type in FLAT_MEMORY_TYPES:
                continue
            for address, nickname in sorted(by_type.get(memory_type, [])):
                entries.append((memory_type, address, nickname))

        return entries

    def _render_flat_types(self, all_nicknames: dict[int, str]) -> None:
        """Render SC/SD as flat lists."""
        by_type: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for addr_key, nickname in all_nicknames.items():
            memory_type, address = parse_addr_key(addr_key)
            if memory_type in FLAT_MEMORY_TYPES:
                by_type[memory_type].append((address, nickname))

        for memory_type in MEMORY_TYPE_ORDER:
            if memory_type not in FLAT_MEMORY_TYPES:
                continue
            if type_entries := sorted(by_type.get(memory_type, [])):
                parent_iid = self.tree.insert("", tk.END, text=memory_type)
                for address, nickname in type_entries:
                    if nickname:
                        iid = self.tree.insert(parent_iid, tk.END, text=f"• {nickname}")
                        self._leaf_data[iid] = (memory_type, address)

    def build_tree(self, all_nicknames: dict[int, str]) -> None:
        """Rebuild the tree from nickname data.

        Args:
            all_nicknames: Dict mapping address key to nickname string
        """
        self._leaf_data.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)

        entries = self._prepare_entries(all_nicknames)
        root = build_tree(entries)
        items = flatten_tree(root)
        self._render_items(items)

        self._render_flat_types(all_nicknames)

    def refresh(self, all_nicknames: dict[int, str]) -> None:
        """Refresh the tree with updated data."""
        self.build_tree(all_nicknames)
