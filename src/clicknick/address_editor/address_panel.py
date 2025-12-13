"""Single panel widget for editing addresses of one memory type.

Uses tksheet for high-performance table display with virtual rows.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

import tksheet

from .address_model import (
    ADDRESS_RANGES,
    DATA_TYPE_BIT,
    DEFAULT_RETENTIVE,
    MEMORY_TYPE_TO_DATA_TYPE,
    PAIRED_RETENTIVE_TYPES,
    AddressRow,
    validate_nickname,
)

if TYPE_CHECKING:
    from .mdb_operations import MdbConnection


class AddressPanel(ttk.Frame):
    """Single panel for editing one memory type's addresses.

    Displays ALL possible addresses for the memory type (virtual rows),
    with existing nicknames from the database pre-filled.

    Supports combined types (e.g., T+TD interleaved) via combined_types parameter.
    """

    # Column indices
    COL_ADDRESS = 0
    COL_NICKNAME = 1
    COL_USED = 2
    COL_INIT_VALUE = 3
    COL_RETENTIVE = 4
    COL_COMMENT = 5
    COL_VALID = 6
    COL_ISSUE = 7

    def _is_bit_type_panel(self) -> bool:
        """Check if this panel displays a single BIT-type memory (X, Y, C, SC).

        Returns False for combined panels (T/TD, CT/CTD) since they mix BIT and non-BIT rows.
        """
        if self.combined_types and len(self.combined_types) > 1:
            return False
        return MEMORY_TYPE_TO_DATA_TYPE.get(self.memory_type, 0) == DATA_TYPE_BIT

    def _find_paired_row(self, row: AddressRow) -> AddressRow | None:
        """Find the paired T/CT row for a TD/CTD row.

        TD rows share retentive with T rows at the same address.
        CTD rows share retentive with CT rows at the same address.

        Returns None if row is not a paired type or paired row not found.
        """
        paired_type = PAIRED_RETENTIVE_TYPES.get(row.memory_type)
        if not paired_type:
            return None

        # Find the row with the same address and the paired type
        for other_row in self.rows:
            if other_row.memory_type == paired_type and other_row.address == row.address:
                return other_row

        return None

    def _on_close_clicked(self) -> None:
        """Handle close button click."""
        if self.on_close:
            self.on_close(self)

    def _apply_row_styling(self) -> None:
        """Apply visual styling to rows based on state."""
        # Clear all existing highlights first
        self.sheet.dehighlight_all()

        for display_idx, row_idx in enumerate(self._filtered_indices):
            row = self.rows[row_idx]

            # Alternate row colors for combined types to distinguish between types
            if self.combined_types and len(self.combined_types) > 1:
                try:
                    type_idx = self.combined_types.index(row.memory_type)
                except ValueError:
                    type_idx = 0

                if type_idx == 1:  # Second type gets slight background tint
                    for col in range(8):
                        self.sheet.highlight_cells(
                            row=display_idx,
                            column=col,
                            bg="#f0f8ff",  # Light blue tint for TD/CTD rows
                        )

            # Invalid rows get red background on nickname cell (or orange if ignored)
            if not row.is_valid and not row.is_empty:
                if row.should_ignore_validation_error:
                    # Light orange for ignored SC/SD system preset errors
                    self.sheet.highlight_cells(
                        row=display_idx,
                        column=self.COL_NICKNAME,
                        bg="#ffe4b3",  # Light orange
                        fg="#666666",  # Gray text
                    )
                else:
                    # Red for real errors
                    self.sheet.highlight_cells(
                        row=display_idx,
                        column=self.COL_NICKNAME,
                        bg="#ffcccc",
                        fg="black",
                    )
            # Dirty nickname gets light yellow background
            elif row.is_nickname_dirty:
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_NICKNAME,
                    bg="#ffffcc",
                    fg="black",
                )

            # Dirty comment gets light yellow background
            if row.is_comment_dirty:
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_COMMENT,
                    bg="#ffffcc",
                    fg="black",
                )

            # Dirty initial value gets light yellow background
            if row.is_initial_value_dirty:
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_INIT_VALUE,
                    bg="#ffffcc",
                    fg="black",
                )

            # Dirty retentive gets light yellow background
            if row.is_retentive_dirty:
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_RETENTIVE,
                    bg="#ffffcc",
                    fg="black",
                )

            # Invalid initial value gets red background
            if not row.initial_value_valid and row.initial_value != "":
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_INIT_VALUE,
                    bg="#ffcccc",
                    fg="black",
                )

            # Non-editable types get gray background on init/retentive columns
            if not row.can_edit_initial_value:
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_INIT_VALUE,
                    bg="#e0e0e0",
                    fg="#666666",
                )
                self.sheet.highlight_cells(
                    row=display_idx,
                    column=self.COL_RETENTIVE,
                    bg="#e0e0e0",
                    fg="#666666",
                )

            # Empty rows get gray text (except editable columns)
            if row.is_empty and row.comment == "" and row.initial_value == "":
                for col in [self.COL_ADDRESS, self.COL_VALID, self.COL_ISSUE]:
                    self.sheet.highlight_cells(
                        row=display_idx,
                        column=col,
                        fg="#999999",
                    )

    def _toggle_init_ret_columns(self) -> None:
        """Toggle visibility of Init Value and Retentive columns."""
        hide = self.hide_init_ret_var.get()
        columns_to_toggle = {self.COL_INIT_VALUE, self.COL_RETENTIVE}
        if hide:
            self.sheet.hide_columns(columns=columns_to_toggle, data_indexes=True)
        else:
            self.sheet.show_columns(columns=columns_to_toggle)

    def _toggle_used_column(self) -> None:
        """Toggle visibility of Used column."""
        hide = self.hide_used_var.get()
        if hide:
            self.sheet.hide_columns(columns={self.COL_USED}, data_indexes=True)
        else:
            self.sheet.show_columns(columns={self.COL_USED})

    def _update_status(self) -> None:
        """Update the status label with current counts."""
        total_visible = len(self._filtered_indices)
        error_count = sum(
            1
            for idx in self._filtered_indices
            if not self.rows[idx].is_valid
            and not self.rows[idx].is_empty
            and not self.rows[idx].should_ignore_validation_error
        )
        modified_count = sum(1 for idx in self._filtered_indices if self.rows[idx].is_dirty)

        self.status_label.config(
            text=f"Rows: {total_visible} | Errors: {error_count} | Modified: {modified_count}"
        )

    def _refresh_sheet(self) -> None:
        """Refresh the sheet display with current filtered data."""
        # Check if this is a BIT-type panel for init value checkbox handling
        is_bit_panel = self._is_bit_type_panel()
        is_combined_panel = self.combined_types and len(self.combined_types) > 1

        # Build display data
        data = []
        for idx in self._filtered_indices:
            row = self.rows[idx]

            # Determine validity display
            if row.is_empty and row.initial_value == "":
                valid_display = "--"
                issue_display = "(empty)"
            elif row.is_valid and row.initial_value_valid:
                valid_display = "\u2713"  # checkmark
                issue_display = ""
            else:
                valid_display = "\u2717"  # X mark
                # Show nickname error first, then initial value error
                if not row.is_valid:
                    issue_display = row.validation_error
                else:
                    issue_display = row.initial_value_error

            # Used column display
            used_display = "\u2713" if row.used else ""

            # Init value: convert "0"/"1" to bool for BIT-type rows (checkbox)
            # For single-type BIT panels: all rows are BIT
            # For combined panels: check each row's data_type
            if is_bit_panel or (is_combined_panel and row.data_type == DATA_TYPE_BIT):
                init_value_display = row.initial_value == "1"
            else:
                init_value_display = row.initial_value

            # Retentive: TD/CTD rows share retentive with their paired T/CT row
            paired_row = self._find_paired_row(row)
            retentive_display = paired_row.retentive if paired_row else row.retentive

            data.append(
                [
                    row.display_address,
                    row.nickname,
                    used_display,
                    init_value_display,
                    retentive_display,  # Boolean for checkbox
                    row.comment,
                    valid_display,
                    issue_display,
                ]
            )

        # Update sheet
        self.sheet.set_sheet_data(data, reset_col_positions=False)

        # Re-enable checkboxes for retentive column after data update
        # Using edit_data=True ensures the checkbox updates cell data to True/False
        self.sheet[tksheet.num2alpha(self.COL_RETENTIVE)].checkbox(edit_data=True, checked=None)

        # Re-enable checkboxes for init value column on BIT-type panels
        if is_bit_panel:
            self.sheet[tksheet.num2alpha(self.COL_INIT_VALUE)].checkbox(
                edit_data=True, checked=None
            )

        # For combined panels (T/TD, CT/CTD), create per-row checkboxes for BIT-type rows
        if is_combined_panel:
            for display_idx, row_idx in enumerate(self._filtered_indices):
                row = self.rows[row_idx]
                if row.data_type == DATA_TYPE_BIT:
                    is_checked = row.initial_value == "1"
                    # Use "normal" for editable, "disabled" for non-editable
                    state = "normal" if row.can_edit_initial_value else "disabled"
                    self.sheet.create_checkbox(
                        r=display_idx,
                        c=self.COL_INIT_VALUE,
                        checked=is_checked,
                        state=state,
                        text="",
                    )

        # Apply styling for invalid/dirty rows
        self._apply_row_styling()

        # Update status
        self._update_status()

    def _apply_filters(self) -> None:
        """Apply current filter settings and refresh display."""
        filter_text = self.filter_var.get().lower()
        hide_empty = self.hide_empty_var.get()
        hide_assigned = self.hide_assigned_var.get()
        show_unsaved_only = self.show_unsaved_only_var.get()

        self._filtered_indices = []
        for i, row in enumerate(self.rows):
            # Filter by text (matches address, nickname, or comment)
            if filter_text:
                if (
                    filter_text not in row.display_address.lower()
                    and filter_text not in row.nickname.lower()
                    and filter_text not in row.comment.lower()
                ):
                    continue

            # Hide empty rows (no nickname)
            if hide_empty and row.is_empty:
                continue

            # Hide assigned rows (has nickname)
            if hide_assigned and not row.is_empty:
                continue

            # Show only unsaved (dirty) rows
            if show_unsaved_only and not row.is_dirty:
                continue

            self._filtered_indices.append(i)

        self._refresh_sheet()

    def _validate_all(self) -> None:
        """Validate all rows against current nickname registry."""
        for row in self.rows:
            row.validate(self._all_nicknames)

    def _on_sheet_modified(self, event) -> None:
        """Handle cell edit completion."""
        # Get edit info from event - tksheet v7 uses EventDataDict
        cells = getattr(event, "cells", None)
        if not cells:
            return

        # tksheet v7 structure: {'table': {(row, col): value}, 'header': {}, 'index': {}}
        table_cells = cells.get("table", {})
        if not table_cells:
            return

        nickname_changed = False
        data_changed = False
        needs_revalidate = False

        # Process each modified cell
        for (display_row, col), _old_value in table_cells.items():
            # Map display row to actual row
            if display_row >= len(self._filtered_indices):
                continue

            row_idx = self._filtered_indices[display_row]
            address_row = self.rows[row_idx]

            # Get the NEW value from the sheet (event contains old value)
            new_value = self.sheet.get_cell_data(display_row, col)

            if col == self.COL_NICKNAME:
                old_nickname = address_row.nickname

                # Skip if no change
                if new_value == old_nickname:
                    continue

                # Update the row
                address_row.nickname = new_value

                # Update global nickname registry
                if old_nickname and address_row.addr_key in self._all_nicknames:
                    del self._all_nicknames[address_row.addr_key]
                if new_value:
                    self._all_nicknames[address_row.addr_key] = new_value

                nickname_changed = True
                data_changed = True

                # Notify parent for cross-panel validation
                if self.on_nickname_changed:
                    self.on_nickname_changed(
                        address_row.addr_key,
                        old_nickname,
                        new_value,
                    )

            elif col == self.COL_COMMENT:
                old_comment = address_row.comment

                # Skip if no change
                if new_value == old_comment:
                    continue

                # Update the row
                address_row.comment = new_value
                data_changed = True

            elif col == self.COL_INIT_VALUE:
                # Skip if type doesn't allow editing initial value
                if not address_row.can_edit_initial_value:
                    continue

                # For BIT-type rows, checkbox returns bool - convert to "0"/"1"
                # This applies to both single-type BIT panels and BIT rows in combined panels
                if address_row.data_type == DATA_TYPE_BIT:
                    new_value = "1" if bool(new_value) else "0"

                old_init_value = address_row.initial_value

                # Skip if no change
                if new_value == old_init_value:
                    continue

                # Update the row
                address_row.initial_value = new_value
                data_changed = True
                needs_revalidate = True

            elif col == self.COL_RETENTIVE:
                # Skip if type doesn't allow editing retentive
                if not address_row.can_edit_retentive:
                    continue

                # Handle retentive checkbox toggle - value is boolean
                new_retentive = bool(new_value)

                # For TD/CTD rows, update the paired T/CT row instead
                # (TD/CTD retentive mirrors T/CT and isn't stored separately in MDB)
                paired_row = self._find_paired_row(address_row)
                target_row = paired_row if paired_row else address_row

                # Skip if no change
                if new_retentive == target_row.retentive:
                    continue

                # Update the target row (T/CT for paired, or the row itself)
                target_row.retentive = new_retentive
                data_changed = True

        # Revalidate ALL rows if nickname changed (fixing a duplicate affects both rows)
        if nickname_changed or needs_revalidate:
            self._validate_all()

        # Refresh display
        self._refresh_sheet()

        # Notify parent of data change (for multi-window sync)
        if data_changed and self.on_data_changed:
            self.on_data_changed()

    def _create_widgets(self) -> None:
        """Create all panel widgets."""
        # Header frame with title and optional close button
        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=5, pady=(5, 2))

        # Title shows combined types if applicable
        if self.combined_types and len(self.combined_types) > 1:
            title_text = "/".join(self.combined_types) + " Addresses"
        else:
            title_text = f"{self.memory_type} Addresses"

        ttk.Label(
            header,
            text=title_text,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT)

        # Close button (X) - only if callback provided
        if self.on_close:
            close_btn = ttk.Button(header, text="X", width=2, command=self._on_close_clicked)
            close_btn.pack(side=tk.RIGHT)

        # Filter controls frame
        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT)
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(filter_frame, textvariable=self.filter_var, width=15)
        self.filter_entry.pack(side=tk.LEFT, padx=(5, 10))
        self.filter_var.trace_add("write", lambda *_: self._apply_filters())

        self.hide_empty_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_frame,
            text="Hide empty",
            variable=self.hide_empty_var,
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=(0, 5))

        self.hide_assigned_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_frame,
            text="Hide assigned",
            variable=self.hide_assigned_var,
            command=self._apply_filters,
        ).pack(side=tk.LEFT)

        self.show_unsaved_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_frame,
            text="Unsaved only",
            variable=self.show_unsaved_only_var,
            command=self._apply_filters,
        ).pack(side=tk.LEFT, padx=(5, 0))

        self.hide_used_var = tk.BooleanVar(value=True)  # Hidden by default
        ttk.Checkbutton(
            filter_frame,
            text="Hide Used",
            variable=self.hide_used_var,
            command=self._toggle_used_column,
        ).pack(side=tk.LEFT, padx=(10, 0))

        self.hide_init_ret_var = tk.BooleanVar(value=True)  # Hidden by default
        ttk.Checkbutton(
            filter_frame,
            text="Hide Init/Ret",
            variable=self.hide_init_ret_var,
            command=self._toggle_init_ret_columns,
        ).pack(side=tk.LEFT, padx=(5, 0))

        # Table (tksheet)
        self.sheet = tksheet.Sheet(
            self,
            headers=["Address", "Nickname", "Used", "Init Value", "Ret", "Comment", "Ok", "Issue"],
            show_row_index=False,
            height=400,
            width=800,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Enable standard bindings for editing, but disable unwanted ones
        self.sheet.enable_bindings()
        # Disable column header right-click menu and sorting options
        self.sheet.disable_bindings(
            # "column_select",
            "column_drag_and_drop",
            # "column_width_resize",
            "rc_select_column",
            "sort",
        )

        # Enable checkboxes in retentive column with edit_data=True
        # This ensures clicking the checkbox updates the cell's actual data to True/False
        self.sheet[tksheet.num2alpha(self.COL_RETENTIVE)].checkbox(edit_data=True, checked=None)

        # Enable checkboxes in init value column for single-type BIT panels (X, Y, C, SC)
        if self._is_bit_type_panel():
            self.sheet[tksheet.num2alpha(self.COL_INIT_VALUE)].checkbox(
                edit_data=True, checked=None
            )

        self.sheet.set_column_widths([70, 200, 40, 90, 30, 400, 30, 100])
        self.sheet.readonly_columns(
            [self.COL_ADDRESS, self.COL_USED, self.COL_VALID, self.COL_ISSUE]
        )

        # Bind edit events
        self.sheet.bind("<<SheetModified>>", self._on_sheet_modified)

        # Apply initial column visibility (hidden by default)
        self._toggle_used_column()
        self._toggle_init_ret_columns()

        # Footer with status
        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, padx=5, pady=(2, 5))

        self.status_label = ttk.Label(footer, text="Rows: 0 | Errors: 0 | Modified: 0")
        self.status_label.pack(side=tk.LEFT)

    def __init__(
        self,
        parent: tk.Widget,
        memory_type: str,
        combined_types: list[str] | None = None,
        on_nickname_changed: Callable[[int, str, str], None] | None = None,
        on_data_changed: Callable[[], None] | None = None,
        on_close: Callable[[AddressPanel], None] | None = None,
    ):
        """Initialize the address panel.

        Args:
            parent: Parent widget
            memory_type: The memory type to edit (X, Y, C, etc.)
            combined_types: List of types to show interleaved (e.g., ["T", "TD"])
            on_nickname_changed: Callback when a nickname changes (for cross-panel validation).
            on_data_changed: Callback when any data changes (for multi-window sync).
            on_close: Callback when panel close button is clicked.
        """
        super().__init__(parent)

        self.memory_type = memory_type
        self.combined_types = combined_types  # None means single type
        self.on_nickname_changed = on_nickname_changed
        self.on_data_changed = on_data_changed
        self.on_close = on_close

        self.rows: list[AddressRow] = []
        self._all_nicknames: dict[int, str] = {}
        self._filtered_indices: list[int] = []

        self._create_widgets()

    def _validate_row(self, row: AddressRow) -> None:
        """Validate a single row."""
        row.validate(self._all_nicknames)

    def _create_row_from_data(
        self,
        mem_type: str,
        addr: int,
        data: dict | None,
        all_nicknames: dict[int, str],
    ) -> AddressRow:
        """Create an AddressRow from database data or defaults.

        Args:
            mem_type: Memory type (X, Y, T, TD, etc.)
            addr: Address number
            data: Data dict from database, or None for virtual row
            all_nicknames: Global nicknames for validation

        Returns:
            Configured AddressRow
        """
        default_data_type = MEMORY_TYPE_TO_DATA_TYPE.get(mem_type, 0)
        default_retentive = DEFAULT_RETENTIVE.get(mem_type, False)

        if data:
            nickname = data.get("nickname", "")
            comment = data.get("comment", "")
            used = data.get("used", False)
            data_type = data.get("data_type", default_data_type)
            initial_value = data.get("initial_value", "")
            retentive = data.get("retentive", default_retentive)

            row = AddressRow(
                memory_type=mem_type,
                address=addr,
                nickname=nickname,
                original_nickname=nickname,
                comment=comment,
                original_comment=comment,
                used=used,
                exists_in_mdb=True,
                data_type=data_type,
                initial_value=initial_value,
                original_initial_value=initial_value,
                retentive=retentive,
                original_retentive=retentive,
            )

            # Mark X/SC/SD rows that load with invalid nicknames
            if mem_type in ("X", "SC", "SD") and nickname:
                is_valid, _ = validate_nickname(nickname, all_nicknames, row.addr_key)
                if not is_valid:
                    row.loaded_with_error = True
        else:
            row = AddressRow(
                memory_type=mem_type,
                address=addr,
                exists_in_mdb=False,
                data_type=default_data_type,
                retentive=default_retentive,
                original_retentive=default_retentive,
            )

        return row

    def _build_interleaved_rows(
        self,
        mdb_conn: MdbConnection,
        types: list[str],
        all_nicknames: dict[int, str],
    ) -> list[AddressRow]:
        """Build interleaved rows for combined types.

        For T+TD: T1, TD1, T2, TD2, ...
        For CT+CTD: CT1, CTD1, CT2, CTD2, ...
        """
        from .mdb_operations import load_nicknames_for_type

        # Load existing data for all types
        existing_by_type = {}
        for mem_type in types:
            existing_by_type[mem_type] = load_nicknames_for_type(mdb_conn, mem_type)

        # Find the common address range
        # T and TD both go 1-250, CT and CTD both go 1-250
        all_starts = []
        all_ends = []
        for mem_type in types:
            if mem_type in ADDRESS_RANGES:
                start, end = ADDRESS_RANGES[mem_type]
                all_starts.append(start)
                all_ends.append(end)

        if not all_starts:
            return []

        # Use the overlapping range
        range_start = max(all_starts)
        range_end = min(all_ends)

        rows = []
        for addr in range(range_start, range_end + 1):
            # Add a row for each type at this address (interleaved)
            for mem_type in types:
                data = existing_by_type[mem_type].get(addr)
                row = self._create_row_from_data(mem_type, addr, data, all_nicknames)
                rows.append(row)

        return rows

    def _build_single_type_rows(
        self,
        mdb_conn: MdbConnection,
        mem_type: str,
        all_nicknames: dict[int, str],
    ) -> list[AddressRow]:
        """Build rows for a single memory type."""
        from .mdb_operations import load_nicknames_for_type

        start, end = ADDRESS_RANGES[mem_type]
        existing = load_nicknames_for_type(mdb_conn, mem_type)

        rows = []
        for addr in range(start, end + 1):
            data = existing.get(addr)
            row = self._create_row_from_data(mem_type, addr, data, all_nicknames)
            rows.append(row)

        return rows

    def load_data(
        self,
        mdb_conn: MdbConnection,
        all_nicknames: dict[int, str],
    ) -> None:
        """Load all addresses for this memory type.

        Args:
            mdb_conn: Active database connection
            all_nicknames: Global dict of all nicknames for validation
        """
        # Check if this is a combined type panel
        if self.combined_types and len(self.combined_types) > 1:
            self.rows = self._build_interleaved_rows(mdb_conn, self.combined_types, all_nicknames)
        else:
            self.rows = self._build_single_type_rows(mdb_conn, self.memory_type, all_nicknames)

        self._all_nicknames = all_nicknames
        self._validate_all()
        self._apply_filters()

    def revalidate(self) -> None:
        """Re-validate all rows (called when global nicknames change)."""
        self._validate_all()
        self._refresh_sheet()

    def get_dirty_rows(self) -> list[AddressRow]:
        """Get all rows that have been modified."""
        return [row for row in self.rows if row.is_dirty]

    def has_errors(self) -> bool:
        """Check if any rows have validation errors."""
        return any(
            not row.is_valid and not row.is_empty and not row.should_ignore_validation_error
            for row in self.rows
        )

    def get_error_count(self) -> int:
        """Get count of rows with validation errors."""
        return sum(
            1
            for row in self.rows
            if not row.is_valid and not row.is_empty and not row.should_ignore_validation_error
        )

    def scroll_to_address(self, address: int, memory_type: str | None = None) -> bool:
        """Scroll to show a specific address.

        Args:
            address: The address number to scroll to
            memory_type: Optional memory type for combined panels

        Returns:
            True if address was found and scrolled to
        """
        # Find the row index for this address
        target_type = memory_type or self.memory_type

        row_idx = None
        for i, row in enumerate(self.rows):
            if row.address == address and row.memory_type == target_type:
                row_idx = i
                break

        if row_idx is None:
            # Try without type match (for single-type panels)
            for i, row in enumerate(self.rows):
                if row.address == address:
                    row_idx = i
                    break

        if row_idx is None:
            return False

        # Check if it's visible in current filter
        if row_idx not in self._filtered_indices:
            self.filter_var.set("")
            self.hide_empty_var.set(False)
            self.hide_assigned_var.set(False)
            self._apply_filters()

        try:
            display_idx = self._filtered_indices.index(row_idx)
            self.sheet.see(display_idx, self.COL_ADDRESS)
            return True
        except ValueError:
            return False
