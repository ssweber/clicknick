"""Dialog for exporting address data to CSV."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk


class ExportCsvDialog(tk.Toplevel):
    """Dialog for exporting address data to CSV.

    Allows user to choose:
    - Export all rows or only visible/filtered rows
    - Output file location
    """

    def _on_export(self) -> None:
        """Handle export button click."""
        # Ask user for file location
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="Export to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

        if not file_path:
            return

        # Store result
        self.result = (Path(file_path), self.export_mode_var.get())
        self.destroy()

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        self.result = None
        self.destroy()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_label = ttk.Label(
            main_frame,
            text="Export Address Data to CSV",
            font=("TkDefaultFont", 10, "bold"),
        )
        title_label.pack(pady=(0, 15))

        # Export mode selection
        mode_frame = ttk.LabelFrame(main_frame, text="Export Options", padding=10)
        mode_frame.pack(fill=tk.X, pady=(0, 15))

        self.export_mode_var = tk.StringVar(value="all")

        ttk.Radiobutton(
            mode_frame,
            text="Export all rows (entire database)",
            variable=self.export_mode_var,
            value="all",
        ).pack(anchor=tk.W, pady=2)

        ttk.Radiobutton(
            mode_frame,
            text="Export only visible rows (current tab's filtered view)",
            variable=self.export_mode_var,
            value="visible",
        ).pack(anchor=tk.W, pady=2)

        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        ttk.Button(
            button_frame,
            text="Export...",
            command=self._on_export,
            width=12,
        ).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(
            button_frame,
            text="Cancel",
            command=self._on_cancel,
            width=12,
        ).pack(side=tk.LEFT)

    def __init__(self, parent: tk.Widget):
        """Initialize the export dialog.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.title("Export to CSV")
        self.transient(parent)
        self.grab_set()

        # Result
        self.result: tuple[Path, str] | None = None  # (file_path, export_mode)

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
