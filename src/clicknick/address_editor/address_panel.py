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

    # Column indices (Address is now in row index, not a data column)
    COL_NICKNAME = 0
    COL_USED = 1
    COL_INIT_VALUE = 2
    COL_RETENTIVE = 3
    COL_COMMENT = 4
    COL_VALID = 5
    COL_ISSUE = 6

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

    def _get_block_colors_for_rows(self) -> dict[int, str]:
        """Compute block background colors for each row address.

        Parses block tags from row comments to determine which rows
        should have colored row indices. Nested blocks override outer blocks.

        Returns:
            Dict mapping row index (in self.rows) to bg color string.
        """
        from .address_model import parse_block_tag

        # Build list of colored blocks: (start_idx, end_idx, bg_color)
        # We use row indices not addresses for easier lookup
        colored_blocks: list[tuple[int, int | None, str]] = []

        # Stack for tracking open tags: name -> [(start_idx, bg_color), ...]
        open_tags: dict[str, list[tuple[int, str | None]]] = {}

        for row_idx, row in enumerate(self.rows):
            block_tag = parse_block_tag(row.comment)
            if not block_tag.name:
                continue

            if block_tag.tag_type == "self-closing":
                if block_tag.bg_color:
                    colored_blocks.append((row_idx, row_idx, block_tag.bg_color))
            elif block_tag.tag_type == "open":
                if block_tag.name not in open_tags:
                    open_tags[block_tag.name] = []
                open_tags[block_tag.name].append((row_idx, block_tag.bg_color))
            elif block_tag.tag_type == "close":
                if block_tag.name in open_tags and open_tags[block_tag.name]:
                    start_idx, start_bg_color = open_tags[block_tag.name].pop()
                    if start_bg_color:
                        colored_blocks.append((start_idx, row_idx, start_bg_color))

        # Handle unclosed tags as singular points
        for stack in open_tags.values():
            for start_idx, bg_color in stack:
                if bg_color:
                    colored_blocks.append((start_idx, start_idx, bg_color))

        # Build row_idx -> color map, with inner blocks overriding outer
        # Sort by range size descending (larger ranges first), then by start index
        # This ensures inner (smaller) blocks are processed last and override
        colored_blocks.sort(key=lambda b: (-(b[1] - b[0]) if b[1] else 0, b[0]))

        row_colors: dict[int, str] = {}
        for start_idx, end_idx, bg_color in colored_blocks:
            if end_idx is None:
                end_idx = start_idx
            for idx in range(start_idx, end_idx + 1):
                row_colors[idx] = bg_color

        return row_colors

    def _apply_row_styling(self) -> None:
        """Apply visual styling to rows based on state."""
        # Clear all existing highlights first
        self.sheet.dehighlight_all()

        # Get block colors for row indices
        block_colors = self._get_block_colors_for_rows()

        for display_idx, data_idx in enumerate(self._displayed_rows):
            row = self.rows[data_idx]

            # Apply block color to row index only (not data cells)
            if data_idx in block_colors:
                # Import here to avoid circular imports
                from .address_editor_window import get_block_color_hex

                # Convert color name to hex (supports both names and hex codes)
                hex_color = get_block_color_hex(block_colors[data_idx])
                if hex_color:
                    self.sheet.highlight_cells(
                        row=display_idx,
                        bg=hex_color,
                        canvas="row_index",
                    )

            # Alternate row colors for combined types to distinguish between types
            if self.combined_types and len(self.combined_types) > 1:
                try:
                    type_idx = self.combined_types.index(row.memory_type)
                except ValueError:
                    type_idx = 0

                if type_idx == 1:  # Second type gets slight background tint
                    for col in range(7):  # 7 data columns (address is in row index)
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

            # Empty rows get gray text on validation columns
            if row.is_empty and row.comment == "" and row.initial_value == "":
                for col in [self.COL_VALID, self.COL_ISSUE]:
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
        total_visible = len(self._displayed_rows)
        error_count = sum(
            1
            for idx in self._displayed_rows
            if not self.rows[idx].is_valid
            and not self.rows[idx].is_empty
            and not self.rows[idx].should_ignore_validation_error
        )
        modified_count = sum(1 for idx in self._displayed_rows if self.rows[idx].is_dirty)

        self.status_label.config(
            text=f"Rows: {total_visible} | Errors: {error_count} | Modified: {modified_count}"
        )

    def _update_row_computed_columns(self, data_idx: int) -> None:
        """Update only the computed columns (Ok, Issue) for a single row.

        Args:
            data_idx: Index into self.rows (data index, not display index)
        """
        row = self.rows[data_idx]

        # Determine validity display
        if row.is_empty and row.initial_value == "":
            valid_display = "--"
            issue_display = "(empty)"
        elif row.is_valid and row.initial_value_valid:
            valid_display = "\u2713"  # checkmark
            issue_display = ""
        else:
            valid_display = "\u2717"  # X mark
            if not row.is_valid:
                issue_display = row.validation_error
            else:
                issue_display = row.initial_value_error

        self.sheet.set_cell_data(data_idx, self.COL_VALID, valid_display)
        self.sheet.set_cell_data(data_idx, self.COL_ISSUE, issue_display)

    def _update_computed_columns(self) -> None:
        """Update computed columns (Ok, Issue) for all rows."""
        for data_idx in range(len(self.rows)):
            self._update_row_computed_columns(data_idx)

    def _refresh_display(self) -> None:
        """Refresh styling and status (lightweight, no data rebuild)."""
        self._apply_row_styling()
        self._update_status()
        # Use set_refresh_timer() instead of redraw() to prevent multiple redraws
        # and ensure proper refresh after set_cell_data() calls
        self.sheet.set_refresh_timer()

    def _get_data_index(self, display_idx: int) -> int | None:
        """Convert display row index to data row index.

        Args:
            display_idx: The row index as displayed in the sheet

        Returns:
            The corresponding index in self.rows, or None if invalid
        """
        try:
            return self.sheet.displayed_row_to_data(display_idx)
        except (IndexError, KeyError):
            return None

    def _save_selection(self) -> None:
        """Save the currently selected row index (in self.rows) and its visual position before filter changes."""
        selected = self.sheet.get_selected_rows()
        if selected:
            # Get the first selected display row and map to actual row index
            display_idx = min(selected)
            # Use our _displayed_rows list for consistent conversion
            if display_idx < len(self._displayed_rows):
                self._selected_row_idx = self._displayed_rows[display_idx]
                # Save the visual position (row offset from top of visible area)
                try:
                    start_row, end_row = self.sheet.visible_rows
                    self._selected_row_visual_offset = display_idx - start_row
                except (ValueError, TypeError):
                    self._selected_row_visual_offset = 0
            else:
                self._selected_row_idx = None
                self._selected_row_visual_offset = None
        else:
            self._selected_row_idx = None
            self._selected_row_visual_offset = None

    def _restore_selection(self) -> None:
        """Restore selection to the previously selected row at the same visual position after filter changes."""
        if self._selected_row_idx is None:
            return

        # Find the display index for the saved row in currently displayed rows
        try:
            display_idx = self._displayed_rows.index(self._selected_row_idx)
            # Clear existing selection and select the row
            self.sheet.deselect()
            self.sheet.select_row(display_idx)

            # Calculate the target top row to maintain visual position
            if self._selected_row_visual_offset is not None:
                target_top_row = max(0, display_idx - self._selected_row_visual_offset)
                # Scroll so target_top_row is at the top of visible area
                total_rows = len(self._displayed_rows)
                if total_rows > 0:
                    self.sheet.yview_moveto(target_top_row / total_rows)
                else:
                    self.sheet.see(display_idx, self.COL_NICKNAME)
            else:
                self.sheet.see(display_idx, self.COL_NICKNAME)
        except ValueError:
            # Row is not visible in current filter - clear saved selection
            pass

    def _apply_filters(self) -> None:
        """Apply current filter settings using tksheet's display_rows()."""
        # Save current selection before changing filter
        self._save_selection()

        filter_text = self.filter_var.get().lower()
        hide_empty = self.hide_empty_var.get()
        hide_assigned = self.hide_assigned_var.get()
        show_unsaved_only = self.show_unsaved_only_var.get()

        # Check if any filters are active
        no_filters = (
            not filter_text and not hide_empty and not hide_assigned and not show_unsaved_only
        )

        if no_filters:
            # Show all rows
            self._displayed_rows = list(range(len(self.rows)))
            self.sheet.display_rows("all")
        else:
            # Build list of rows to display
            self._displayed_rows = []
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

                self._displayed_rows.append(i)

            self.sheet.display_rows(rows=self._displayed_rows, all_displayed=False)

        # Refresh styling and status
        self._refresh_display()

        # Restore selection after filter change
        self._restore_selection()

    def _validate_all(self) -> None:
        """Validate all rows against current nickname registry."""
        for row in self.rows:
            row.validate(self._all_nicknames)

    def _fire_batched_notifications(self) -> None:
        """Fire batched notifications for all pending changes."""
        self._notification_timer = None

        # Fire nickname changes (batched)
        if self._pending_nickname_changes and self.on_nickname_changed:
            for addr_key, old_nick, new_nick in self._pending_nickname_changes:
                self.on_nickname_changed(addr_key, old_nick, new_nick)
        self._pending_nickname_changes = []

        # Fire data change notification once
        if self._pending_data_changed and self.on_data_changed:
            self.on_data_changed()
        self._pending_data_changed = False

    def _schedule_notifications(self) -> None:
        """Schedule batched notifications after a short delay.

        This debounces rapid changes (like Replace All) to avoid
        triggering expensive cross-panel validation for each cell.
        """
        # Cancel any existing timer
        if self._notification_timer is not None:
            self.after_cancel(self._notification_timer)

        # Schedule notification after 50ms idle
        self._notification_timer = self.after(50, self._fire_batched_notifications)

    def _bulk_validate(self, event) -> object:
        """Bulk validation handler for paste and multi-cell edits.

        This is called BEFORE changes are applied to the sheet.
        We can modify event.data to filter out invalid changes,
        or return the event to accept all changes.

        Args:
            event: EventDataDict containing proposed changes

        Returns:
            The (possibly modified) event to apply changes, or None to reject all.
        """
        # For now, accept all changes - validation happens after in _on_sheet_modified
        # We could add pre-validation here if needed (e.g., reject non-editable cells)

        # Get the proposed changes
        if not hasattr(event, "data") or not event.data:
            return event

        table_data = event.data.get("table", {})
        if not table_data:
            return event
        # Filter out changes to non-editable cells
        filtered_table = {}
        for (display_row, col), value in table_data.items():
            # Map display row to data row
            data_idx = self._get_data_index(display_row)
            if data_idx is None:
                continue

            address_row = self.rows[data_idx]

            # Check if this column is editable for this row
            if col == self.COL_USED or col == self.COL_VALID or col == self.COL_ISSUE:
                # Read-only columns - skip
                continue
            elif col == self.COL_INIT_VALUE and not address_row.can_edit_initial_value:
                # Non-editable init value - skip
                continue
            elif col == self.COL_RETENTIVE and not address_row.can_edit_retentive:
                # Non-editable retentive - skip
                continue
            else:
                # Accept this change
                filtered_table[(display_row, col)] = value

        # Update event data with filtered changes
        event.data["table"] = filtered_table

        return event

    def _on_sheet_modified(self, event) -> None:
        """Handle sheet modification events (called AFTER changes are applied).

        This handles all types of modifications including single cell edits,
        paste operations, and bulk edits. The changes have already been
        applied to the sheet at this point.
        """
        # Skip processing if notifications are suppressed (e.g., during load)
        if self._suppress_notifications:
            return

        # Get modified cells from event
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

        # Track old nicknames for cross-panel notification
        nickname_changes: list[tuple[int, str, str]] = []  # (addr_key, old, new)

        # Track which data rows were modified for display update
        modified_data_indices: set[int] = set()

        # Process each modified cell
        for (display_row, col), old_value in table_cells.items():
            # Map display row to data row
            data_idx = self._get_data_index(display_row)
            if data_idx is None:
                continue

            address_row = self.rows[data_idx]

            # Get the NEW value from the sheet (event contains old value)
            new_value = self.sheet.get_cell_data(display_row, col)

            if col == self.COL_NICKNAME:
                old_nickname = old_value if old_value else ""
                new_nickname = new_value if new_value else ""

                # Skip if no change
                if new_nickname == address_row.nickname:
                    continue

                # Update the row
                address_row.nickname = new_nickname
                modified_data_indices.add(data_idx)

                # Update global nickname registry
                if old_nickname and address_row.addr_key in self._all_nicknames:
                    del self._all_nicknames[address_row.addr_key]
                if new_nickname:
                    self._all_nicknames[address_row.addr_key] = new_nickname

                nickname_changed = True
                data_changed = True

                # Queue notification for parent
                nickname_changes.append((address_row.addr_key, old_nickname, new_nickname))

            elif col == self.COL_COMMENT:
                new_comment = new_value if new_value else ""

                # Skip if no change
                if new_comment == address_row.comment:
                    continue

                # Update the row
                address_row.comment = new_comment
                modified_data_indices.add(data_idx)
                data_changed = True

            elif col == self.COL_INIT_VALUE:
                # Skip if type doesn't allow editing initial value
                if not address_row.can_edit_initial_value:
                    continue

                # For BIT-type rows, checkbox returns bool - convert to "0"/"1"
                if address_row.data_type == DATA_TYPE_BIT:
                    new_init = "1" if bool(new_value) else "0"
                else:
                    new_init = new_value if new_value else ""

                # Skip if no change
                if new_init == address_row.initial_value:
                    continue

                # Update the row
                address_row.initial_value = new_init
                modified_data_indices.add(data_idx)
                data_changed = True
                needs_revalidate = True

            elif col == self.COL_RETENTIVE:
                # Skip if type doesn't allow editing retentive
                if not address_row.can_edit_retentive:
                    continue

                # Handle retentive checkbox toggle - value is boolean
                new_retentive = bool(new_value)

                # For TD/CTD rows, update the paired T/CT row instead
                paired_row = self._find_paired_row(address_row)
                target_row = paired_row if paired_row else address_row

                # Skip if no change
                if new_retentive == target_row.retentive:
                    continue

                # Update the target row
                target_row.retentive = new_retentive
                modified_data_indices.add(data_idx)
                data_changed = True

        # Revalidate ALL rows if nickname changed (fixing a duplicate affects both rows)
        if nickname_changed or needs_revalidate:
            self._validate_all()
            # Validation can affect any row, so update computed columns for all rows
            self._update_computed_columns()
        elif modified_data_indices:
            # Only update computed columns for modified rows
            for data_idx in modified_data_indices:
                self._update_row_computed_columns(data_idx)

        # Refresh styling and status
        self._refresh_display()

        # Queue notifications for batched delivery (debounced)
        # This prevents expensive cross-panel validation for each cell in bulk operations
        if nickname_changes:
            self._pending_nickname_changes.extend(nickname_changes)

        if data_changed:
            self._pending_data_changed = True

        # Schedule batched notification delivery
        if nickname_changes or data_changed:
            self._schedule_notifications()

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

        self.hide_used_var = tk.BooleanVar(value=False)  # Hidden by default
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

        # Table (tksheet) - Address is shown in row index for row selection
        self.sheet = tksheet.Sheet(
            self,
            headers=["Nickname", "Used", "Init Value", "Ret", "Comment", "Ok", "Issue"],
            show_row_index=True,
            index_align="w",  # Left-align the row index
            height=400,
            width=800,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Enable standard bindings for editing, but disable unwanted ones
        self.sheet.enable_bindings()
        # Change Find/Replace binding from Ctrl+H to Ctrl+R
        self.sheet.set_options(toggle_replace_bindings=["<Control-r>", "<Control-R>"])
        # Disable column header right-click menu and sorting options
        self.sheet.disable_bindings(
            "column_drag_and_drop",
            "rc_select_column",
            "rc_insert_row",
            "rc_delete_row",
            "sort_cells",
            "sort_row",
            "sort_column",
            "sort_rows",
            "sort_columns",
        )

        # Enable checkboxes in retentive column with edit_data=True
        self.sheet[tksheet.num2alpha(self.COL_RETENTIVE)].checkbox(edit_data=True, checked=None)

        # Enable checkboxes in init value column for single-type BIT panels (X, Y, C, SC)
        if self._is_bit_type_panel():
            self.sheet[tksheet.num2alpha(self.COL_INIT_VALUE)].checkbox(
                edit_data=True, checked=None
            )

        # Set column widths (address is in row index now)
        self.sheet.set_column_widths([200, 40, 90, 30, 400, 30, 100])
        self.sheet.row_index(70)  # Set row index width
        self.sheet.readonly_columns([self.COL_USED, self.COL_VALID, self.COL_ISSUE])

        # === KEY CHANGE: Use bulk_table_edit_validation for paste operations ===
        # This ensures the entire paste completes before validation runs
        self.sheet.bulk_table_edit_validation(self._bulk_validate)

        # === KEY CHANGE: Bind to <<SheetModified>> for post-edit processing ===
        # This fires AFTER the sheet has been modified, not during
        self.sheet.bind("<<SheetModified>>", self._on_sheet_modified)

        # Apply initial column visibility
        self._toggle_used_column()
        self._toggle_init_ret_columns()  # hidden by default

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
        self._displayed_rows: list[int] = []  # Data indices of currently displayed rows

        # Flag to suppress change notifications during programmatic updates
        self._suppress_notifications = False

        # Track selected row for filter changes (actual row index in self.rows)
        self._selected_row_idx: int | None = None
        self._selected_row_visual_offset = None

        # Debounce timer for batching notifications
        self._notification_timer: str | None = None
        self._pending_nickname_changes: list[tuple[int, str, str]] = []
        self._pending_data_changed: bool = False

        self._create_widgets()

    def _build_row_display_data(self, row: AddressRow) -> list:
        """Build display data array for a single row.

        Args:
            row: The AddressRow to build display data for

        Returns:
            List of display values for the row's columns
        """
        is_bit_panel = self._is_bit_type_panel()
        is_combined_panel = self.combined_types and len(self.combined_types) > 1

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
        if is_bit_panel or (is_combined_panel and row.data_type == DATA_TYPE_BIT):
            init_value_display = row.initial_value == "1"
        else:
            init_value_display = row.initial_value

        # Retentive: TD/CTD rows share retentive with their paired T/CT row
        paired_row = self._find_paired_row(row)
        retentive_display = paired_row.retentive if paired_row else row.retentive

        return [
            row.nickname,
            used_display,
            init_value_display,
            retentive_display,  # Boolean for checkbox
            row.comment,
            valid_display,
            issue_display,
        ]

    def _populate_sheet_data(self) -> None:
        """Populate sheet with ALL row data (called once at load time).

        This sets up the full dataset. Use display_rows() for filtering.
        """
        is_bit_panel = self._is_bit_type_panel()
        is_combined_panel = self.combined_types and len(self.combined_types) > 1

        # Build data for ALL rows
        data = []
        row_index_values = []
        for row in self.rows:
            row_index_values.append(row.display_address)
            data.append(self._build_row_display_data(row))

        # Set all data at once
        self.sheet.set_sheet_data(data, reset_col_positions=False)
        self.sheet.set_index_data(row_index_values)

        # Set up checkboxes for retentive column (whole column)
        self.sheet[tksheet.num2alpha(self.COL_RETENTIVE)].checkbox(edit_data=True, checked=None)

        # Set up checkboxes for init value column on BIT-type panels
        if is_bit_panel:
            self.sheet[tksheet.num2alpha(self.COL_INIT_VALUE)].checkbox(
                edit_data=True, checked=None
            )

        # For combined panels, create per-row checkboxes for BIT-type rows
        if is_combined_panel:
            for data_idx, row in enumerate(self.rows):
                if row.data_type == DATA_TYPE_BIT:
                    is_checked = row.initial_value == "1"
                    state = "normal" if row.can_edit_initial_value else "disabled"
                    self.sheet.create_checkbox(
                        r=data_idx,
                        c=self.COL_INIT_VALUE,
                        checked=is_checked,
                        state=state,
                        text="",
                    )

    def _update_row_display(self, data_idx: int) -> None:
        """Update display data for a single row after changes.

        Args:
            data_idx: Index into self.rows (data index, not display index)
        """
        row = self.rows[data_idx]
        display_data = self._build_row_display_data(row)

        # Update each cell in the row
        for col, value in enumerate(display_data):
            self.sheet.set_cell_data(data_idx, col, value)

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
        # Suppress notifications during load to avoid triggering sync logic
        self._suppress_notifications = True

        try:
            # Check if this is a combined type panel
            if self.combined_types and len(self.combined_types) > 1:
                self.rows = self._build_interleaved_rows(
                    mdb_conn, self.combined_types, all_nicknames
                )
            else:
                self.rows = self._build_single_type_rows(mdb_conn, self.memory_type, all_nicknames)

            self._all_nicknames = all_nicknames
            self._validate_all()

            # Populate sheet with ALL data once (use display_rows for filtering)
            self._populate_sheet_data()

            # Apply initial filters (uses display_rows internally)
            self._apply_filters()
        finally:
            self._suppress_notifications = False

    def update_from_external(
        self,
        mdb_conn: MdbConnection,
        all_nicknames: dict[int, str],
    ) -> None:
        """Update data from external source (e.g., MDB file changed).

        Only updates non-dirty rows to preserve user edits.

        Args:
            mdb_conn: Active database connection
            all_nicknames: Global dict of all nicknames
        """
        # Suppress notifications during external update
        self._suppress_notifications = True

        try:
            from .mdb_operations import load_nicknames_for_type

            # Load fresh data from database
            if self.combined_types and len(self.combined_types) > 1:
                existing_by_type = {}
                for mem_type in self.combined_types:
                    existing_by_type[mem_type] = load_nicknames_for_type(mdb_conn, mem_type)
            else:
                existing_data = load_nicknames_for_type(mdb_conn, self.memory_type)

            # Update non-dirty rows
            for row in self.rows:
                if row.is_dirty:
                    # Skip dirty rows - preserve user edits
                    continue

                # Get fresh data for this row
                if self.combined_types and len(self.combined_types) > 1:
                    data = existing_by_type.get(row.memory_type, {}).get(row.address)
                else:
                    data = existing_data.get(row.address)

                if data:
                    # Update from database
                    row.nickname = data.get("nickname", "")
                    row.original_nickname = row.nickname
                    row.comment = data.get("comment", "")
                    row.original_comment = row.comment
                    row.used = data.get("used", False)
                    row.initial_value = data.get("initial_value", "")
                    row.original_initial_value = row.initial_value
                    row.retentive = data.get("retentive", row.retentive)
                    row.original_retentive = row.retentive
                    row.exists_in_mdb = True
                else:
                    # Row no longer exists in database - reset to defaults
                    row.nickname = ""
                    row.original_nickname = ""
                    row.comment = ""
                    row.original_comment = ""
                    row.used = False
                    row.initial_value = ""
                    row.original_initial_value = ""
                    row.exists_in_mdb = False

            # Update nickname registry and revalidate
            self._all_nicknames = all_nicknames
            self._validate_all()

            # Update all row displays with new data
            for data_idx in range(len(self.rows)):
                self._update_row_display(data_idx)

            # Refresh styling and status
            self._refresh_display()

        finally:
            self._suppress_notifications = False

    def revalidate(self) -> None:
        """Re-validate all rows (called when global nicknames change)."""
        self._validate_all()
        self._update_computed_columns()
        self._refresh_display()

    def refresh_from_external(self) -> None:
        """Refresh all row displays after external data changes.

        Call this when AddressRow objects have been updated externally
        (e.g., via row.update_from_db()) to sync the sheet's cell data.
        """
        # Update all row displays to sync AddressRow data to sheet cells
        for data_idx in range(len(self.rows)):
            self._update_row_display(data_idx)

        # Revalidate and refresh styling
        self._validate_all()
        self._update_computed_columns()
        self._refresh_display()

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
        if row_idx not in self._displayed_rows:
            self.filter_var.set("")
            self.hide_empty_var.set(False)
            self.hide_assigned_var.set(False)
            self._apply_filters()

        try:
            display_idx = self._displayed_rows.index(row_idx)
            self.sheet.see(display_idx, self.COL_NICKNAME)
            return True
        except ValueError:
            return False
