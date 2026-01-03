"""Dialog for creating a new Address Editor tab.

Allows user to choose between cloning the current tab or starting fresh.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class NewTabDialog(tk.Toplevel):
    """Dialog for creating a new Address Editor tab.

    Presents two options:
    - Clone current tab (copies filter state, scroll position)
    - Start fresh (default filters, top of list)

    Returns:
        True for clone, False for fresh start, None if cancelled.
    """

    def _on_clone(self) -> None:
        """Handle clone button click."""
        self.result = True
        self.destroy()

    def _on_fresh(self) -> None:
        """Handle fresh button click."""
        self.result = False
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle cancel/close."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # Question label
        ttk.Label(
            frame,
            text="How would you like to create the new tab?",
            font=("TkDefaultFont", 10),
        ).pack(pady=(0, 15))

        # Button frame
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        # Clone button
        clone_btn = ttk.Button(
            btn_frame,
            text="Clone Current Tab",
            command=self._on_clone,
            width=18,
        )
        clone_btn.pack(side=tk.LEFT, padx=(0, 10))

        # Fresh button
        fresh_btn = ttk.Button(
            btn_frame,
            text="Start Fresh",
            command=self._on_fresh,
            width=18,
        )
        fresh_btn.pack(side=tk.LEFT)

        # Cancel button
        cancel_btn = ttk.Button(
            btn_frame,
            text="Cancel",
            command=self._on_cancel,
            width=10,
        )
        cancel_btn.pack(side=tk.RIGHT)

    def __init__(self, parent: tk.Widget):
        """Initialize the dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)

        self.title("New Tab")
        self.resizable(False, False)
        self.result: bool | None = None

        # Make dialog modal
        self.transient(parent)
        self.grab_set()

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

        # Handle escape key
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)


def ask_new_tab(parent: tk.Widget) -> bool | None:
    """Show the new tab dialog and return user's choice.

    Args:
        parent: Parent widget

    Returns:
        True for clone, False for fresh start, None if cancelled.
    """
    dialog = NewTabDialog(parent)
    dialog.wait_window()
    return dialog.result
