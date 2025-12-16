import random
import tkinter as tk
from tkinter import messagebox, ttk

from .colors import BLOCK_COLOR_NAMES, BLOCK_COLORS


class AddBlockDialog(tk.Toplevel):
    """Dialog for adding a block with name and optional color."""

    def _select_color(self, color: str | None) -> None:
        """Select a color and update button states."""
        self._selected_color = color

        # Update button relief to show selection
        for c, btn in self._color_buttons.items():
            if c == color:
                btn.configure(relief="sunken")
            else:
                btn.configure(relief="raised")

    def _select_random_color(self) -> None:
        """Select a random color from the palette."""
        color_name = random.choice(BLOCK_COLOR_NAMES)
        self._select_color(color_name)

    def _on_ok(self) -> None:
        """Handle OK button click."""
        name = self.name_var.get().strip()

        # Clean up name (remove special characters)
        name = name.replace("<", "").replace(">", "").replace("/", "")

        if not name:
            messagebox.showerror("Error", "Please enter a block name.", parent=self)
            return

        self.result = (name, self._selected_color)
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle Cancel button click."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Block name entry
        ttk.Label(main_frame, text="Block Name:").pack(anchor=tk.W)
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(main_frame, textvariable=self.name_var, width=30)
        self.name_entry.pack(fill=tk.X, pady=(2, 10))

        # Color selection
        ttk.Label(main_frame, text="Background Color (optional):").pack(anchor=tk.W)

        # Color grid frame
        color_frame = ttk.Frame(main_frame)
        color_frame.pack(fill=tk.X, pady=(2, 5))

        # "None" button first
        none_btn = tk.Button(
            color_frame,
            text="None",
            width=6,
            relief="sunken",  # Default selected
            command=lambda: self._select_color(None),
        )
        none_btn.grid(row=0, column=0, padx=1, pady=1)
        self._color_buttons[None] = none_btn

        # Color swatches in grid (6 per row)
        colors_per_row = 6
        for i, color_name in enumerate(BLOCK_COLOR_NAMES):
            row = (i // colors_per_row) + 1
            col = i % colors_per_row
            hex_color = BLOCK_COLORS[color_name]
            btn = tk.Button(
                color_frame,
                bg=hex_color,
                width=3,
                height=1,
                relief="raised",
                command=lambda cn=color_name: self._select_color(cn),
            )
            btn.grid(row=row, column=col, padx=1, pady=1)
            self._color_buttons[color_name] = btn

        # Random color button
        random_btn = ttk.Button(
            main_frame,
            text="🎲 Random Color",
            command=self._select_random_color,
        )
        random_btn.pack(pady=(5, 10))

        # Buttons frame
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="OK", command=self._on_ok, width=10).pack(
            side=tk.RIGHT, padx=(5, 0)
        )
        ttk.Button(btn_frame, text="Cancel", command=self._on_cancel, width=10).pack(side=tk.RIGHT)

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.title("Add Block")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: tuple[str, str | None] | None = None  # (name, color) or None if cancelled
        self._selected_color: str | None = None
        self._color_buttons: dict[str, tk.Button] = {}

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
