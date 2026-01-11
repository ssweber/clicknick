"""Dialog for renaming nickname segments in the outline tree."""

import tkinter as tk
from tkinter import messagebox, ttk


class RenameDialog(tk.Toplevel):
    """Dialog for renaming a node segment in the outline."""

    def _on_ok(self) -> None:
        """Handle OK button click."""
        new_name = self.name_var.get().strip()

        if not new_name:
            messagebox.showerror("Error", "Please enter a new name.", parent=self)
            return

        # Don't allow single underscore as a name (reserved for double-underscore nodes)
        if new_name == "_":
            messagebox.showerror(
                "Error", "Single underscore is reserved for internal use.", parent=self
            )
            return

        self.result = new_name
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle Cancel button click."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        # Subtle border frame (the only visible "edge")
        border_frame = ttk.Frame(self, borderwidth=1, relief="solid")
        border_frame.pack(fill=tk.BOTH, expand=True)

        # Compact main container
        main_frame = ttk.Frame(border_frame, padding=6)  # Tight padding for minimal footprint
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Single horizontal row: entry + buttons
        entry_row = ttk.Frame(main_frame)
        entry_row.pack(fill=tk.X)

        # Entry field (slightly smaller width for compactness)
        self.name_var = tk.StringVar(value=self.current_name)
        self.name_entry = ttk.Entry(entry_row, textvariable=self.name_var, width=25)
        self.name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Button container (tight spacing)
        btn_frame = ttk.Frame(entry_row)
        btn_frame.pack(side=tk.LEFT, padx=(4, 0))

        # Compact action buttons
        ttk.Button(btn_frame, text="✓", command=self._on_ok, width=2).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="✗", command=self._on_cancel, width=2).pack(side=tk.LEFT, padx=(2, 0))

    def __init__(self, parent: tk.Widget, current_name: str, is_array: bool = False):
        """Initialize the rename dialog.

        Args:
            parent: Parent widget
            current_name: Current name of the node segment
            is_array: True if this is an array node (has numeric children)
        """
        super().__init__(parent)
        
        # KEY: Remove all window decorations (title bar, borders, etc.)
        self.overrideredirect(True)
        
        # Make it modal (blocks interaction with parent)
        self.transient(parent)
        self.grab_set()

        self.current_name = current_name
        self.is_array = is_array
        self.result: str | None = None

        self._create_widgets()

        # Position at mouse cursor with slight offset
        x = parent.winfo_pointerx() + 8
        y = parent.winfo_pointery() + 8
        self.geometry(f"+{x}+{y}")

        # KEY: Raise to front and force focus
        self.lift()
        self.focus_force()

        # Prepare entry widget
        self.name_entry.focus_set()
        self.name_entry.select_range(0, tk.END)

        # Keyboard shortcuts
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())