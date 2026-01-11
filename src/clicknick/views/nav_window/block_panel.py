"""Blocks panel for the Address Editor.

Groups addresses based on <Block> tags found in comments.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from ...models.address_row import AddressRow
from ...models.blocktag import compute_all_block_ranges
from ...widgets.colors import get_block_color_hex


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


    def _toggle_sort(self) -> None:
        """Toggle alphabetical sorting of blocks."""
        self._sorted = not self._sorted
        # Update button text to show current state
        if self._sorted:
            self.sort_button.config(text="Sort A→Z ✓")
        else:
            self.sort_button.config(text="Sort A→Z")
        # Rebuild tree with current sort state
        if self._cached_rows:
            self.build_tree(self._cached_rows)

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
        # Sort button at bottom
        self.sort_button = ttk.Button(
            self,
            text="Sort A→Z",
            command=self._toggle_sort,
        )
        self.sort_button.pack(fill=tk.X, padx=5, pady=(2, 5))

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
        self._configured_colors: set[str] = set()
        self._sorted = False  # Track sort state
        self._cached_rows: dict[int, AddressRow] | None = None  # Cache for re-sorting

        self._create_widgets()

    def _render_block(self, name: str, color_name: str | None, rows: list[AddressRow]) -> None:
        """Insert a block summary row into the treeview."""
        if not rows:
            return

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

        # Format like Sidebar (Name + Range)
        start_row = rows[0]
        end_row = rows[-1]

        # Single point vs Range
        if len(rows) > 1:
            prefix = "📦"
            display_text = f"{name} ({start_row.display_address}-{end_row.display_address})"
        else:
            prefix = "■"
            display_text = f"{name} ({start_row.display_address})"

        # Insert as a single item
        iid = self.tree.insert("", tk.END, text=f"{prefix} {display_text}", tags=(tag_name,))

        # Store all addresses in the block
        self._block_data[iid] = [(row.memory_type, row.address) for row in rows]

    def build_tree(self, all_rows: dict[int, AddressRow]) -> None:
        """Parse comments and rebuild the blocks tree."""
        # Cache rows for re-sorting
        self._cached_rows = all_rows

        self._block_data.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Convert dict to sorted list for index-based processing
        sorted_keys = sorted(all_rows.keys())
        rows_list = [all_rows[key] for key in sorted_keys]

        # Use centralized block matching
        ranges = compute_all_block_ranges(rows_list)

        # Sort blocks alphabetically if enabled
        if self._sorted:
            ranges = sorted(ranges, key=lambda block: block.name.lower())

        # Render each block
        for block in ranges:
            block_rows = rows_list[block.start_idx : block.end_idx + 1]
            self._render_block(block.name, block.bg_color, block_rows)

    def refresh(self, all_rows: dict[int, AddressRow]) -> None:
        """Refresh the tree with updated data."""
        self.build_tree(all_rows)
