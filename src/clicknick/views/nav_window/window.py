from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

from .block_panel import BlockPanel
from .outline_panel import OutlinePanel

if TYPE_CHECKING:
    from ...models.address_row import AddressRow


class NavWindow(tk.Toplevel):
    """Floating outline window that docks to the right of the main window."""

    def _dock_to_parent(self) -> None:
        if not self.snap_var.get():
            return

        self.parent_window.update_idletasks()
        px = self.parent_window.winfo_x()
        py = self.parent_window.winfo_y()
        pw = self.parent_window.winfo_width()
        ph = self.parent_window.winfo_height()

        target_x = px + pw + 20
        target_y = py

        current_w = self.winfo_width()
        if current_w < 50:
            current_w = 250

        self.geometry(f"{current_w}x{ph}+{target_x}+{target_y}")

    def _on_parent_configure(self, event) -> None:
        if self.snap_var.get() and event.widget == self.parent_window:
            self.after_idle(self._dock_to_parent)

    def _on_self_configure(self, event) -> None:
        if not self.snap_var.get():
            return
        if not self.parent_window or not self.winfo_exists():
            return

        # Calculate where the Left Edge MUST be
        target_x = self.parent_window.winfo_x() + self.parent_window.winfo_width() + 20
        target_y = self.parent_window.winfo_y()

        # If we have drifted from the dock position (e.g. user dragged left edge)
        # Note: We allow some tolerance (e.g. +/- 1 pixel) or exact match
        if self.winfo_x() != target_x or self.winfo_y() != target_y:
            # Apply position only ("+X+Y"), preserving the current Width/Height
            # This creates the effect that the left edge is locked.
            self.geometry(f"+{target_x}+{target_y}")

    def _toggle_snap(self):
        """
        Update the button icon and perform docking logic.
        Note: The variable and visual relief are handled automatically
        by the ttk.Checkbutton logic.
        """
        # The Checkbutton updates the variable BEFORE calling this command
        if self.snap_var.get():
            # Just became Snapped
            self.snap_btn.configure(text="📌")  # Pin icon
            self._dock_to_parent()
        else:
            # Just became Unsnapped
            self.snap_btn.configure(text="🔗")  # Unlinked icon
            # No need to set relief, 'Toolbutton' style handles it

    def _on_close(self) -> None:
        self.withdraw()
        if hasattr(self.parent_window, "nav_btn"):
            self.parent_window.nav_btn.configure(text="Tag Browser >>")

    def __init__(
        self,
        parent: tk.Toplevel,
        on_outline_select: Callable[[str, list[tuple[str, int]]], None],
        on_block_select: Callable[[list[tuple[str, int]]], None],
    ):
        """Initialize the navigation window.

        Args:
            parent: Parent window to dock to
            on_outline_select: Callback when outline item is selected (path, leaves).
                               Path is filter prefix for folders or exact nickname for leaves.
            on_block_select: Callback when block is selected (list of (memory_type, address)).
        """
        super().__init__(parent)
        self.parent_window = parent
        self.title("Tag Browser")
        self.resizable(True, True)
        self.transient(parent)

        self.snap_var = tk.BooleanVar(value=True)

        # 1. Notebook for tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # 2. First Tab: Standard Outline
        self.outline_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.outline_frame, text=" Outline ")
        self.outline = OutlinePanel(self.outline_frame, on_outline_select)
        self.outline.pack(fill=tk.BOTH, expand=True)

        # 3. Second Tab: Blocks
        self.blocks_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.blocks_frame, text=" Blocks ")
        self.blocks = BlockPanel(self.blocks_frame, on_block_select)
        self.blocks.pack(fill=tk.BOTH, expand=True)

        # 4. Snap Button (Floating on top)
        self.snap_btn = ttk.Checkbutton(
            self,
            text="📌",
            variable=self.snap_var,
            command=self._toggle_snap,
            style="Toolbutton",
            width=2,
        )
        self.snap_btn.place(relx=1.0, y=1, x=-25, anchor="ne")

        self._dock_to_parent()
        parent.bind("<Configure>", self._on_parent_configure, add=True)
        self.bind("<Configure>", self._on_self_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def refresh(self, all_rows: dict[int, AddressRow]) -> None:
        """Refresh the tree with updated data.

        Args:
            all_rows: Dict mapping address key to AddressRow
        """
        self.outline.refresh(all_rows)
        self.blocks.refresh(all_rows)
