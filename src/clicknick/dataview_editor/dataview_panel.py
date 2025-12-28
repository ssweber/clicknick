"""Panel widget for editing a single DataView.

Uses tksheet for table display with 100 fixed rows.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from tksheet import Sheet

from .cdv_file import load_cdv, save_cdv
from .dataview_model import (
    MAX_DATAVIEW_ROWS,
    DataviewRow,
    TypeCode,
    create_empty_dataview,
    display_to_storage,
    storage_to_display,
)

# Column indices
COL_ADDRESS = 0
COL_NICKNAME = 1
COL_COMMENT = 2
COL_NEW_VALUE = 3


class DataviewPanel(ttk.Frame):
    """Panel for editing a single DataView's addresses.

    Displays 100 fixed rows with columns: Address, Nickname, Comment, New Value.
    Supports row reordering, cut/copy/paste, and address autocomplete.
    """

    def _populate_sheet(self) -> None:
        """Populate sheet with current row data."""
        self._suppress_notifications = True
        try:
            data = []
            for row in self.rows:
                # Build display row - convert storage format to display format
                new_value_display = storage_to_display(row.new_value, row.type_code)
                data.append([row.address, row.nickname, row.comment, new_value_display])

            self.sheet.set_sheet_data(data, reset_col_positions=False)

            # Set row index labels (1-100)
            self.sheet.set_index_data([str(i + 1) for i in range(MAX_DATAVIEW_ROWS)])

            # Create checkboxes for BIT type New Values (only if there's a value set)
            for i, row in enumerate(self.rows):
                if row.type_code == TypeCode.BIT and row.address:
                    if row.is_writable and row.new_value:
                        # Has a new value - show checkbox
                        checked = row.new_value == "1"
                        self.sheet.create_checkbox(r=i, c=COL_NEW_VALUE, checked=checked, text="")
                    elif not row.new_value:
                        # No new value - show '-'
                        self.sheet.set_cell_data(i, COL_NEW_VALUE, "-")
        finally:
            self._suppress_notifications = False

    def _update_row_display(self, row_idx: int) -> None:
        """Update display for a single row."""
        row = self.rows[row_idx]

        # Update cells
        self.sheet.set_cell_data(row_idx, COL_ADDRESS, row.address)
        self.sheet.set_cell_data(row_idx, COL_NICKNAME, row.nickname)
        self.sheet.set_cell_data(row_idx, COL_COMMENT, row.comment)

        # Handle New Value - delete any existing checkbox first
        self.sheet.delete_checkbox(row_idx, COL_NEW_VALUE)

        if row.type_code == TypeCode.BIT and row.address:
            if row.is_writable and row.new_value:
                # BIT type with writable address and value set - use checkbox
                checked = row.new_value == "1"
                self.sheet.create_checkbox(r=row_idx, c=COL_NEW_VALUE, checked=checked, text="")
                self.sheet.set_cell_data(row_idx, COL_NEW_VALUE, checked)
            else:
                # BIT with no new value - show '-'
                self.sheet.set_cell_data(row_idx, COL_NEW_VALUE, "-")
        else:
            # Other types - convert storage to display format
            display_value = storage_to_display(row.new_value, row.type_code)
            self.sheet.set_cell_data(row_idx, COL_NEW_VALUE, display_value)

    def _update_status(self) -> None:
        """Update the status label."""
        filled_count = sum(1 for r in self.rows if not r.is_empty)
        dirty_text = " (modified)" if self._is_dirty else ""
        self.status_label.config(text=f"Addresses: {filled_count}/100{dirty_text}")

    def _on_sheet_modified(self, event) -> None:
        """Handle sheet modification events."""
        if self._suppress_notifications:
            return

        cells = getattr(event, "cells", None)
        if not cells:
            return

        table_cells = cells.get("table", {})
        if not table_cells:
            return

        data_changed = False

        for (row_idx, col), _old_value in table_cells.items():
            if row_idx >= len(self.rows):
                continue

            row = self.rows[row_idx]
            new_value = self.sheet.get_cell_data(row_idx, col)

            if col == COL_ADDRESS:
                new_address = (new_value or "").strip().upper()

                if new_address != row.address:
                    row.address = new_address
                    row.update_type_code()

                    # Lookup nickname and comment
                    if new_address and self.nickname_lookup:
                        result = self.nickname_lookup(new_address)
                        if result:
                            row.nickname, row.comment = result
                        else:
                            row.nickname = ""
                            row.comment = ""
                    else:
                        row.nickname = ""
                        row.comment = ""

                    # Clear new value if address changed and not writable
                    if not row.is_writable:
                        row.new_value = ""

                    # Update display for this row
                    self._update_row_display(row_idx)
                    data_changed = True

            elif col == COL_NEW_VALUE:
                # Only process if address is writable
                if not row.is_writable:
                    # Revert to empty
                    self._update_row_display(row_idx)
                    continue

                if row.type_code == TypeCode.BIT:
                    new_val = "1" if bool(new_value) else "0"
                else:
                    # Convert display value to storage format
                    display_val = str(new_value) if new_value else ""
                    new_val = display_to_storage(display_val, row.type_code)

                if new_val != row.new_value:
                    row.new_value = new_val
                    data_changed = True

                    # Update has_new_values flag
                    if new_val:
                        self.has_new_values = True

        if data_changed:
            self._is_dirty = True
            self._update_status()
            if self.on_modified:
                self.on_modified()

    def _create_widgets(self) -> None:
        """Create all panel widgets."""
        # Table (tksheet)
        self.sheet = Sheet(
            self,
            headers=["Address", "Nickname", "Comment", "New Value"],
            show_row_index=True,
            height=400,
            width=700,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Enable standard bindings
        self.sheet.enable_bindings()

        # Enable row drag and drop for reordering
        self.sheet.enable_bindings("row_drag_and_drop")

        # Disable unwanted bindings
        self.sheet.disable_bindings(
            "column_drag_and_drop",
            "rc_select_column",
            "rc_insert_row",  # We have fixed 100 rows
            "rc_delete_row",  # We have fixed 100 rows
            "sort_cells",
            "sort_row",
            "sort_column",
            "sort_rows",
            "sort_columns",
        )

        # Set column widths
        self.sheet.set_column_widths([80, 180, 280, 100])
        self.sheet.row_index(40)  # Row index width (row numbers)

        # Make Nickname and Comment columns read-only (populated from address lookup)
        self.sheet.readonly_columns([COL_NICKNAME, COL_COMMENT])

        # Bind to modification events
        self.sheet.bind("<<SheetModified>>", self._on_sheet_modified)

        # Initialize with empty data
        self._populate_sheet()

        # Footer with status
        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, padx=5, pady=(2, 5))

        self.status_label = ttk.Label(footer, text="")
        self.status_label.pack(side=tk.LEFT)

        self._update_status()

    def _load_file(self) -> None:
        """Load data from file."""
        if not self.file_path or not self.file_path.exists():
            return

        try:
            self.rows, self.has_new_values = load_cdv(self.file_path)

            # Populate nicknames and comments from lookup
            if self.nickname_lookup:
                for row in self.rows:
                    if row.address:
                        result = self.nickname_lookup(row.address)
                        if result:
                            row.nickname, row.comment = result

            self._populate_sheet()
            self._is_dirty = False
            self._update_status()
        except Exception as e:
            # Show error
            self.status_label.config(text=f"Error loading: {e}")

    def __init__(
        self,
        parent: tk.Widget,
        file_path: Path | None = None,
        on_modified: Callable[[], None] | None = None,
        nickname_lookup: Callable[[str], tuple[str, str] | None] | None = None,
    ):
        """Initialize the dataview panel.

        Args:
            parent: Parent widget
            file_path: Path to the CDV file (None for new unsaved dataview)
            on_modified: Callback when data is modified
            nickname_lookup: Callback to lookup (nickname, comment) for an address
        """
        super().__init__(parent)

        self.file_path = file_path
        self.on_modified = on_modified
        self.nickname_lookup = nickname_lookup

        # Data model
        self.rows: list[DataviewRow] = create_empty_dataview()
        self.has_new_values = False
        self._is_dirty = False

        # Suppress notifications during programmatic updates
        self._suppress_notifications = False

        self._create_widgets()

        # Load file if provided
        if file_path and file_path.exists():
            self._load_file()

    def save(self) -> bool:
        """Save data to file.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.file_path:
            return False

        try:
            # Check if any rows have new values
            self.has_new_values = any(r.new_value for r in self.rows if not r.is_empty)
            save_cdv(self.file_path, self.rows, self.has_new_values)
            self._is_dirty = False
            self._update_status()
            return True
        except Exception as e:
            self.status_label.config(text=f"Error saving: {e}")
            return False

    def save_as(self, new_path: Path) -> bool:
        """Save data to a new file path.

        Args:
            new_path: New file path to save to.

        Returns:
            True if saved successfully, False otherwise.
        """
        self.file_path = new_path
        return self.save()

    @property
    def is_dirty(self) -> bool:
        """Check if the dataview has unsaved changes."""
        return self._is_dirty

    @property
    def name(self) -> str:
        """Get the dataview name (filename without extension)."""
        if self.file_path:
            return self.file_path.stem
        return "Untitled"

    def add_address(self, address: str) -> bool:
        """Add an address to the first empty row.

        Args:
            address: The address to add (e.g., "X001", "DS100")

        Returns:
            True if address was added, False if no empty rows.
        """
        # Find first empty row
        for i, row in enumerate(self.rows):
            if row.is_empty:
                row.address = address.strip().upper()
                row.update_type_code()

                # Lookup nickname and comment
                if self.nickname_lookup:
                    result = self.nickname_lookup(row.address)
                    if result:
                        row.nickname, row.comment = result

                self._update_row_display(i)
                self._is_dirty = True
                self._update_status()

                if self.on_modified:
                    self.on_modified()

                # Scroll to the added row
                self.sheet.see(i, COL_ADDRESS)
                self.sheet.select_row(i)
                return True

        return False

    def clear_row(self, row_idx: int) -> None:
        """Clear a specific row.

        Args:
            row_idx: Index of the row to clear (0-99)
        """
        if 0 <= row_idx < len(self.rows):
            self.rows[row_idx].clear()
            self._update_row_display(row_idx)
            self._is_dirty = True
            self._update_status()

            if self.on_modified:
                self.on_modified()

    def get_selected_rows(self) -> list[int]:
        """Get indices of currently selected rows."""
        return list(self.sheet.get_selected_rows())

    def refresh_nicknames(self) -> None:
        """Refresh all nickname and comment lookups."""
        if not self.nickname_lookup:
            return

        for i, row in enumerate(self.rows):
            if row.address:
                result = self.nickname_lookup(row.address)
                if result:
                    row.nickname, row.comment = result
                else:
                    row.nickname = ""
                    row.comment = ""
                self._update_row_display(i)

        self.sheet.set_refresh_timer()
