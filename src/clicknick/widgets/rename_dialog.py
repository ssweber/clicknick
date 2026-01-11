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
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Name entry (pre-filled with current name)
        self.name_var = tk.StringVar(value=self.current_name)
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=35)
        self.name_entry.pack(fill=tk.X, pady=(0, 10))

        # Buttons frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="✓", command=self._on_ok, width=3).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="✗", command=self._on_cancel, width=3).pack(
            side=tk.RIGHT, padx=(0, 5)
        )

    def __init__(self, parent: tk.Widget, current_name: str, is_array: bool = False):
        """Initialize the rename dialog.

        Args:
            parent: Parent widget
            current_name: Current name of the node segment
            is_array: True if this is an array node (has numeric children)
        """
        super().__init__(parent)
        self.title("Rename")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.current_name = current_name
        self.is_array = is_array
        self.result: str | None = None

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Focus on name entry and select all text
        self.name_entry.focus_set()
        self.name_entry.select_range(0, tk.END)

        # Bind keys
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())
