"""Blocks panel for the Address Editor.

Groups addresses based on <Block> tags found in comments.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from ...models.address_row import AddressRow
from ...services.block_service import compute_all_block_ranges
from ...widgets.colors import get_block_color_hex
from .block_logic import BlockTreeNode, build_block_tree


class BlockPanel(ttk.Frame):
    """Panel displaying addresses grouped by logical blocks defined in comments."""

    def _on_double_click(self, event) -> None:
        """Handle double-click on tree item."""
        if selection := self.tree.selection():
            iid = selection[0]
            # Emit block data (all addresses in the block)
            if block_data := self._block_data.get(iid):
                if self.on_select:
                    self.on_select(block_data)

    def _on_sort_changed(self) -> None:
        """Handle sort order change."""
        # Rebuild tree with current data if we have it cached
        if self._all_rows_cache is not None:
            self.build_tree(self._all_rows_cache)

    def _get_expanded_node_ids(self) -> set[str]:
        """Get currently expanded node ids (for restoring tree state)."""
        expanded: set[str] = set()
        for iid, node in self._node_data.items():
            if node.children and self.tree.item(iid, "open"):
                expanded.add(node.node_id)
        return expanded

    def _restore_expanded_node_ids(self, expanded_node_ids: set[str]) -> None:
        """Restore expanded state for matching nodes."""
        if not expanded_node_ids:
            return
        for iid, node in self._node_data.items():
            if node.children and node.node_id in expanded_node_ids:
                self.tree.item(iid, open=True)

    def _create_widgets(self) -> None:
        header = ttk.Label(self, text="Memory Blocks", font=("TkDefaultFont", 9, "bold"))
        header.pack(fill=tk.X, padx=5, pady=(5, 2))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Simplified column
        self.tree = ttk.Treeview(
            tree_frame,
            show="tree",  # Hide headers as we are formatting like a list
            selectmode="browse",
            yscrollcommand=scrollbar.set,
        )

        self.tree.column("#0", width=200, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar.config(command=self.tree.yview)
        self.tree.bind("<Double-Button-1>", self._on_double_click)

        # Add sort checkbox at the bottom
        sort_frame = ttk.Frame(self)
        sort_frame.pack(fill=tk.X, padx=5, pady=2)

        self._sort_check = ttk.Checkbutton(
            sort_frame,
            text="A→Z",
            variable=self._sort_alphabetically,
            command=self._on_sort_changed,
        )
        self._sort_check.pack(side=tk.LEFT)

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Callable[[list[tuple[str, int]]], None],
    ):
        """Initialize the block panel.

        Args:
            parent: Parent widget
            on_select: Callback when block is selected (list of (memory_type, address))
        """
        super().__init__(parent)
        self.on_select = on_select
        self._block_data: dict[str, list[tuple[str, int]]] = {}
        self._node_data: dict[str, BlockTreeNode] = {}
        self._configured_colors: set[str] = set()
        self._sort_alphabetically = tk.BooleanVar(value=False)
        self._all_rows_cache: dict[int, AddressRow] | None = None

        self._create_widgets()

    def _ensure_color_tag(self, color_name: str | None) -> str:
        """Create/get a tree tag for a block background color."""
        # Convert color name to hex
        hex_color = None
        if color_name:
            hex_color = get_block_color_hex(color_name)

        # Configure tag with hex color
        tag_name = "default"
        if hex_color:
            tag_name = f"bg_{hex_color.replace('#', '')}"
            if tag_name not in self._configured_colors:
                self.tree.tag_configure(tag_name, background=hex_color)
                self._configured_colors.add(tag_name)
        return tag_name

    @staticmethod
    def _format_node_text(node: BlockTreeNode) -> str:
        """Format node text for display in treeview."""
        if node.is_group:
            return node.text
        prefix = "📦" if len(node.addresses) > 1 else "■"
        return f"{prefix} {node.text}"

    def _insert_node(self, node: BlockTreeNode, parent_iid: str = "") -> None:
        """Insert node and children recursively into the treeview."""
        tag_name = self._ensure_color_tag(node.bg_color)
        iid = self.tree.insert(
            parent_iid,
            tk.END,
            text=self._format_node_text(node),
            tags=(tag_name,),
        )
        self._node_data[iid] = node

        if node.addresses:
            self._block_data[iid] = list(node.addresses)

        for child in node.children:
            self._insert_node(child, iid)

    def build_tree(self, all_rows: dict[int, AddressRow]) -> None:
        """Parse comments and rebuild the blocks tree."""
        expanded_node_ids = self._get_expanded_node_ids()

        # Cache the data for re-sorting
        self._all_rows_cache = all_rows

        self._block_data.clear()
        self._node_data.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Convert dict to sorted list for index-based processing
        sorted_keys = sorted(all_rows.keys())
        rows_list = [all_rows[key] for key in sorted_keys]

        # Use centralized block matching
        ranges = compute_all_block_ranges(rows_list)
        nodes = build_block_tree(
            ranges,
            rows_list,
            sort_alphabetically=self._sort_alphabetically.get(),
        )
        for node in nodes:
            self._insert_node(node)

        self._restore_expanded_node_ids(expanded_node_ids)

    def refresh(self, all_rows: dict[int, AddressRow]) -> None:
        """Refresh the tree with updated data."""
        self.build_tree(all_rows)
