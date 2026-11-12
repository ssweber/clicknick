"""Address Outline panel for the Address Editor.

UI component that renders the tree structure from outline_logic.
"""

from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from collections.abc import Callable
from tkinter import ttk

from ...models.address_row import AddressRow, with_pair_retentive
from ...widgets.rename_dialog import RenameDialog
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
        if not (selection := self.tree.selection()):
            return

        iid = selection[0]
        item = self._item_data.get(iid)
        if item is None:
            return

        # Always emit with path and all leaves
        if self.on_select:
            leaves = item.get_all_leaves()
            if leaves:
                self.on_select(item.full_path, leaves)

    def _on_right_click(self, event) -> None:
        """Handle right-click on tree item."""
        if self.on_rename is None:
            return

        # Select the item under the cursor
        iid = self.tree.identify_row(event.y)
        if not iid:
            return

        self.tree.selection_set(iid)
        self._selected_iid = iid
        # Only a nickname segment can be renamed: not an SC/SD entry or a "_" node
        item = self._item_data.get(iid)
        self._context_menu.entryconfigure(
            0, state=tk.NORMAL if item is not None and item.rename_text else tk.DISABLED
        )

        # Show context menu
        self._context_menu.post(event.x_root, event.y_root)

    def _show_rename_dialog(self) -> None:
        """Show rename dialog for the selected item."""
        if not hasattr(self, "_selected_iid") or not self._selected_iid:
            return

        item = self._item_data.get(self._selected_iid)
        if item is None:
            return

        # The item knows which nickname segment it renames and what precedes it
        if not item.rename_text:
            return
        current_text = item.rename_text
        is_array = item.rename_is_array
        prefix = item.rename_prefix

        # Show dialog
        dialog = RenameDialog(self, current_text, is_array)
        self.wait_window(dialog)

        if dialog.result:
            new_text = dialog.result
            # Trigger rename callback
            if self.on_rename:
                self.on_rename(prefix, current_text, new_text, is_array, item.rename_exact)

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
        self.tree.bind("<Button-3>", self._on_right_click)  # Right-click

        # Create context menu
        self._context_menu = tk.Menu(self.tree, tearoff=0)
        self._context_menu.add_command(label="Rename", command=self._show_rename_dialog)

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Callable[[str, list[tuple[str, int]]], None],
        on_rename: Callable[[str, str, str, bool, bool], None] | None = None,
    ):
        """Initialize the outline panel.

        Args:
            parent: Parent widget
            on_select: Callback when item is selected (path, list of (memory_type, address))
                       Path is the filter prefix for folders or exact name for leaves.
            on_rename: Callback when rename is performed (prefix, old_text, new_text, is_array, exact)
        """
        super().__init__(parent, width=275)
        self.pack_propagate(False)

        self.on_select = on_select
        self.on_rename = on_rename
        self._item_data: dict[str, DisplayItem] = {}  # iid -> DisplayItem

        self._create_widgets()

    def _insert_item(
        self, item: DisplayItem, parent_iid: str, all_rows: dict[int, AddressRow]
    ) -> None:
        """Recursively insert a DisplayItem and its children into the treeview."""
        # Build display text with outline_suffix for leaves
        display_text = item.text
        if item.addr_key is not None and item.addr_key in all_rows:
            row = with_pair_retentive(all_rows[item.addr_key], all_rows)
            display_text = f"{item.text} {row.outline_suffix}"

        iid = self.tree.insert(parent_iid, tk.END, text=display_text)
        self._item_data[iid] = item

        # Recursively insert children
        for child in item.children:
            self._insert_item(child, iid, all_rows)

    def _render_items(self, items: list[DisplayItem], all_rows: dict[int, AddressRow]) -> None:
        """Render DisplayItem tree to treeview."""
        for item in items:
            self._insert_item(item, "", all_rows)

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
                self._item_data[parent_iid] = DisplayItem(
                    text=memory_type
                )  # no path: keyed by text
                for address, row in type_entries:
                    # Flat entries are leaves whose path is the exact nickname
                    item = DisplayItem(
                        text=f"• {row.nickname} {row.outline_suffix}",
                        full_path=row.nickname,
                        leaf=(memory_type, address),
                        addr_key=row.addr_key,
                    )
                    iid = self.tree.insert(parent_iid, tk.END, text=item.text)
                    self._item_data[iid] = item

    def build_tree(self, all_rows: dict[int, AddressRow]) -> None:
        """Rebuild the tree from address row data.

        Args:
            all_rows: Dict mapping address key to AddressRow
        """
        self._item_data.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)

        entries = self._prepare_entries(all_rows)
        root = build_tree(entries)
        items = flatten_tree(root)
        self._render_items(items, all_rows)

        self._render_flat_types(all_rows)

    @staticmethod
    def _state_key(item: DisplayItem) -> str:
        """Key an item's expanded state: its path, or for an SC/SD group its type.

        A group has no path; the prefix keeps its key from a folder of that name.
        """
        return item.full_path or f"\x00{item.text}"

    def _get_expanded_paths(self) -> set[str]:
        """Get the state key of all currently expanded nodes."""
        return {
            self._state_key(item)
            for iid, item in self._item_data.items()
            if self.tree.item(iid, "open")
        }

    def _restore_expanded_paths(self, expanded_paths: set[str]) -> None:
        """Restore expanded state for nodes matching the given state keys."""
        for iid, item in self._item_data.items():
            if self._state_key(item) in expanded_paths:
                self.tree.item(iid, open=True)

    def refresh(self, all_rows: dict[int, AddressRow]) -> None:
        """Refresh the tree with updated data, preserving expanded state and scroll."""
        # Capture current state
        expanded_paths = self._get_expanded_paths()
        scroll_position = self.tree.yview()

        # Rebuild tree
        self.build_tree(all_rows)

        # Restore expanded state
        if expanded_paths:
            self._restore_expanded_paths(expanded_paths)

        # Restore scroll position after tree is updated
        if scroll_position != (0.0, 1.0):  # Only restore if not at default
            self.tree.yview_moveto(scroll_position[0])
