"""Dialog for creating a new dataview with name validation."""

import tkinter as tk
from tkinter import ttk

from ..models.name_validation import (
    CLICK_NAME_PATTERN,
    MAX_CLICK_NAME_LENGTH,
    validate_click_name,
)

MAX_NAME_LENGTH = MAX_CLICK_NAME_LENGTH


class NewDataviewDialog(tk.Toplevel):
    """Dialog for entering a new dataview name with validation."""

    def _update_char_count(self, count: int) -> None:
        """Update the character count label."""
        self.char_label.configure(text=f"{count}/{MAX_NAME_LENGTH}")

    def _validate_name(self, new_value: str) -> bool:
        """Validate the entered name.

        Args:
            new_value: The proposed new value for the entry

        Returns:
            True if valid, False to reject the change
        """
        # Allow empty (user might be deleting)
        if not new_value:
            self._update_char_count(0)
            return True

        # Check length
        if len(new_value) > MAX_NAME_LENGTH:
            return False

        # Check for special characters
        if not CLICK_NAME_PATTERN.fullmatch(new_value):
            return False

        self._update_char_count(len(new_value))
        return True

    def _on_ok(self) -> None:
        """Handle OK button click."""
        name = self.name_var.get().strip()

        is_valid, _ = validate_click_name(name)
        if not is_valid:
            self.name_entry.focus_set()
            return

        self.result = name
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle Cancel button click."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Label
        ttk.Label(main_frame, text="Enter the name of the dataview:").pack(anchor=tk.W)

        # Entry with character count
        entry_frame = ttk.Frame(main_frame)
        entry_frame.pack(fill=tk.X, pady=(5, 2))

        self.name_var = tk.StringVar()

        # Register validation command
        vcmd = (self.register(self._validate_name), "%P")

        self.name_entry = ttk.Entry(
            entry_frame,
            textvariable=self.name_var,
            width=30,
            validate="key",
            validatecommand=vcmd,
        )
        self.name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Character count label
        self.char_label = ttk.Label(entry_frame, text=f"0/{MAX_NAME_LENGTH}", width=6)
        self.char_label.pack(side=tk.RIGHT, padx=(5, 0))

        # Info label
        info_label = ttk.Label(
            main_frame,
            text="Max 24 characters, special characters not allowed.",
            font=("TkDefaultFont", 9),
            foreground="gray",
        )
        info_label.pack(anchor=tk.W, pady=(2, 15))

        # Buttons frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="OK", command=self._on_ok, width=10).pack(
            side=tk.RIGHT, padx=(5, 0)
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel, width=10).pack(side=tk.RIGHT)

    def __init__(self, parent: tk.Widget):
        """Initialize the dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.title("New Dataview")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: str | None = None

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Focus on name entry
        self.name_entry.focus_set()

        # Bind Enter key to OK
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())

    def show(self) -> str | None:
        """Show the dialog and return the entered name (or None if cancelled).

        Returns:
            The entered dataview name, or None if cancelled
        """
        self.wait_window()
        return self.result
