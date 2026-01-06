"""Single panel widget for editing addresses of one memory type.

Uses tksheet for high-performance table display with virtual rows.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

from tksheet import num2alpha

from ...models.address_row import AddressRow
from ...models.blocktag import parse_block_tag
from ...models.constants import (
    FLOAT_MAX,
    FLOAT_MIN,
    INT2_MAX,
    INT2_MIN,
    INT_MAX,
    INT_MIN,
    MEMORY_TYPE_TO_DATA_TYPE,
    NON_EDITABLE_TYPES,
    DataType,
)
from ...widgets.char_limit_tooltip import CharLimitTooltip
from .panel_constants import (
    COL_COMMENT,
    COL_INIT_VALUE,
    COL_NICKNAME,
    COL_RETENTIVE,
    COL_USED,
)
from .row_styler import AddressRowStyler
from .sheet import AddressEditorSheet
from .view_builder import find_paired_row

# Mapping from column index to AddressRow field name for discard operations
COL_TO_FIELD = {
    COL_NICKNAME: "nickname",
    COL_COMMENT: "comment",
    COL_INIT_VALUE: "initial_value",
    COL_RETENTIVE: "retentive",
}

if TYPE_CHECKING:
    pass


class AddressPanel(ttk.Frame):
    """Single panel for editing one memory type's addresses.

    Displays ALL possible addresses for the memory type (virtual rows),
    with existing nicknames from the database pre-filled.

    Supports combined types (e.g., T+TD interleaved) via combined_types parameter.
    """

    # Column indices imported from panel_constants
    COL_USED = COL_USED
    COL_NICKNAME = COL_NICKNAME
    COL_COMMENT = COL_COMMENT
    COL_INIT_VALUE = COL_INIT_VALUE
    COL_RETENTIVE = COL_RETENTIVE

    def _is_bit_type_panel(self) -> bool:
        """Check if this panel displays a single BIT-type memory (X, Y, C, SC).

        Returns False for combined panels (T/TD, CT/CTD) since they mix BIT and non-BIT rows.
        """
        if self.combined_types and len(self.combined_types) > 1:
            return False
        return MEMORY_TYPE_TO_DATA_TYPE.get(self.memory_type, 0) == DataType.BIT

    def _on_close_clicked(self) -> None:
        """Handle close button click."""
        if self.on_close:
            self.on_close(self)

    def _get_init_value_hint(self, data_type: int) -> str:
        """Get the hint text for initial value based on data type.

        Args:
            data_type: The data type code

        Returns:
            Hint string describing valid range/values
        """
        if data_type == DataType.BIT:
            return "0 or 1"
        elif data_type == DataType.INT:
            return f"Range: {INT_MIN} to {INT_MAX}"
        elif data_type == DataType.INT2:
            return f"Range: {INT2_MIN} to {INT2_MAX}"
        elif data_type == DataType.FLOAT:
            return f"Range: {FLOAT_MIN:.2e} to {FLOAT_MAX:.2e}"
        elif data_type == DataType.HEX:
            return "Hex value (e.g., FF or 0xFF)"
        elif data_type == DataType.TXT:
            return "Text string"
        else:
            return "Enter initial value"

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
        error_count = self.get_error_count()
        modified_count = sum(1 for idx in self._displayed_rows if self.rows[idx].is_dirty)

        self.status_label.config(
            text=f"Rows: {total_visible} | Errors: {error_count} | Modified: {modified_count}"
        )

    def _refresh_display(self) -> None:
        """Refresh styling and status (lightweight, no data rebuild)."""
        if self._styler:
            self._styler.apply_all_styling()
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

    def _scroll_to_row(
        self, display_idx: int, align_top: bool = False, offset: int | None = None
    ) -> None:
        """Scroll to a specific row in the displayed rows.

        Args:
            display_idx: Index of the row in _displayed_rows
            align_top: If True, ensure the row is at the top of the viewport.
                       If False, just ensure it's visible somewhere in the viewport.
            offset: Optional visual offset from the top (if align_top=True).
                    None means row is at the very top, 0 means row is at the top,
                    >0 means row is that many lines down from the top.
        """
        if align_top:
            # Calculate scroll position
            total_rows = len(self._displayed_rows)
            if total_rows > 0:
                if offset is not None:
                    # Scroll so that the row at 'offset' lines from top is at the top
                    target_top_row = max(0, display_idx - offset)
                    self.sheet.yview_moveto(target_top_row / total_rows)
                else:
                    # Put target row at the top
                    self.sheet.yview_moveto(display_idx / total_rows)

                self.sheet.see(display_idx, self.COL_NICKNAME)
            # Select the row after scrolling
            self.sheet.select_row(display_idx)
        else:
            # Original behavior: just ensure it's visible
            self.sheet.see(display_idx, self.COL_NICKNAME)
            self.sheet.select_row(display_idx)

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

            # Use helper function for scrolling with offset
            self._scroll_to_row(
                display_idx, align_top=True, offset=self._selected_row_visual_offset
            )
        except ValueError:
            # Row is not visible in current filter - clear saved selection
            pass

    def _apply_filters(self) -> None:
        """Apply current filter settings using tksheet's display_rows()."""
        # Save current selection before changing filter
        self._save_selection()

        # Check if filtering is enabled
        filter_enabled = self.filter_enabled_var.get()

        filter_text = self.filter_var.get().lower() if filter_enabled else ""
        hide_empty = self.hide_empty_var.get() if filter_enabled else False
        hide_assigned = self.hide_assigned_var.get() if filter_enabled else False
        show_unsaved_only = self.show_unsaved_only_var.get() if filter_enabled else False

        # Check if any filters are active
        no_filters = (
            not filter_text and not hide_empty and not hide_assigned and not show_unsaved_only
        )

        if no_filters:
            # Show all rows
            self._displayed_rows = list(range(len(self.rows)))
            self.sheet.display_rows("all", redraw=True)
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

            self.sheet.display_rows(rows=self._displayed_rows, all_displayed=False, redraw=True)

        # Restore selection after filter change
        self._restore_selection()

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
            if col == self.COL_USED:
                # Read-only column - skip
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

    def _build_row_display_data(self, row: AddressRow) -> list:
        """Build display data array for a single row.

        Args:
            row: The AddressRow to build display data for

        Returns:
            List of display values for the row's columns
        """

        # Used column display
        used_display = "\u2713" if row.used else ""

        # Init value: logic to determine if we show "-", Checkbox (bool), or Text
        paired_row = find_paired_row(row, self.rows)
        effective_retentive = paired_row.retentive if paired_row else row.retentive

        # If Retentive is ON and not exempt, force display to "-"
        if effective_retentive and row.memory_type not in NON_EDITABLE_TYPES:
            init_value_display = "-"
        else:
            # Otherwise show the underlying value
            # For BIT types, return bool so tksheet knows to check/uncheck the checkbox
            if row.data_type == DataType.BIT:
                init_value_display = row.initial_value == "1"
            else:
                init_value_display = row.initial_value

        # Retentive: TD/CTD rows share retentive with their paired T/CT row
        retentive_display = effective_retentive

        return [
            used_display,
            row.nickname,
            row.comment,
            init_value_display,
            retentive_display,  # Boolean for checkbox
        ]

    def _update_row_display(self, data_idx: int) -> None:
        """Update display data for a single row after changes.

        Args:
            data_idx: Index into self.rows (data index, not display index)
        """
        row = self.rows[data_idx]
        display_data = self._build_row_display_data(row)

        # Update each cell in the row
        for col, value in enumerate(display_data):
            # Special handling for Init Value to switch between Checkbox and Text
            if col == self.COL_INIT_VALUE:
                # Always attempt to delete existing checkbox in this cell to ensure clean state
                self.sheet.delete_checkbox(data_idx, col)

                if value == "-":
                    # Just set the text "-"
                    self.sheet.set_cell_data(data_idx, col, value)
                elif row.data_type == DataType.BIT:
                    # It's a BIT type and not masked -> Create Checkbox
                    is_checked = value is True
                    state = "normal" if row.can_edit_initial_value else "readonly"
                    self.sheet.create_checkbox(
                        r=data_idx,
                        c=col,
                        checked=is_checked,
                        state=state,
                        text="",
                    )
                    # Also set the data model to the boolean value
                    self.sheet.set_cell_data(data_idx, col, is_checked)
                else:
                    # Standard value (Word/Float/Text) -> Just set data
                    self.sheet.set_cell_data(data_idx, col, value)
            else:
                self.sheet.set_cell_data(data_idx, col, value)

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
        for (event_row, col), old_value in table_cells.items():
            data_idx = event_row

            if data_idx is None or data_idx >= len(self.rows):
                continue

            address_row = self.rows[data_idx]

            # Get the NEW value from the sheet using data index
            new_value = self.sheet.get_cell_data(data_idx, col)

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

                # Check if row is currently masked by Retentive (showing "-")
                # If so, revert any edit attempts immediately
                paired_row = find_paired_row(address_row, self.rows)
                effective_retentive = paired_row.retentive if paired_row else address_row.retentive

                if effective_retentive and address_row.memory_type not in NON_EDITABLE_TYPES:
                    # User tried to edit a masked value. Revert visual to "-"
                    # We add to modified_indices so _update_row_display restores the "-"
                    modified_data_indices.add(data_idx)
                    continue

                # Standard update logic
                if address_row.data_type == DataType.BIT:
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
                paired_row = find_paired_row(address_row, self.rows)
                target_row = paired_row if paired_row else address_row

                # Skip if no change
                if new_retentive == target_row.retentive:
                    continue

                # Update the target row
                target_row.retentive = new_retentive
                modified_data_indices.add(data_idx)

                # If we toggled retentive, we might need to update the paired row's display too
                # (e.g. Toggled T retentive -> TD init value needs to show/hide "-")
                if paired_row:
                    # We need to find the data index of the paired row to refresh it
                    # Simple linear search (optimization: map could be cached)
                    for i, r in enumerate(self.rows):
                        if r is paired_row:
                            modified_data_indices.add(i)
                            break

                # Also if there is a pair that uses the same address but isn't the current row
                # (e.g. We are on TD, we toggled Ret (which maps to T). We need to refresh T row too)
                if self.combined_types and len(self.combined_types) > 1:
                    for i, r in enumerate(self.rows):
                        if r.address == address_row.address and r is not address_row:
                            modified_data_indices.add(i)

                data_changed = True

        # Refresh display for all modified rows (handles toggling "-" vs Checkbox/Value)
        for idx in modified_data_indices:
            self._update_row_display(idx)

        # IMPORTANT: Notify parent FIRST to update shared_data reverse index
        # This must happen before validation so duplicate detection works correctly
        if nickname_changes and self.on_nickname_changed:
            for addr_key, old_nick, new_nick in nickname_changes:
                self.on_nickname_changed(self.memory_type, addr_key, old_nick, new_nick)

        # Targeted validation using the updated reverse index
        if nickname_changed and self.on_validate_affected:
            # Use O(1) targeted validation via shared_data reverse index
            # This validates other affected rows (e.g., rows that had old nickname)
            for _addr_key, old_nick, new_nick in nickname_changes:
                self.on_validate_affected(old_nick, new_nick)

        # Always validate the locally modified rows in THIS panel
        # (on_validate_affected validates shared_data.all_rows, which may be different objects)
        if nickname_changed or needs_revalidate:
            for idx in modified_data_indices:
                self.rows[idx].validate(self._all_nicknames, self.is_duplicate_fn)

        # Refresh styling and status
        self._refresh_display()

        if data_changed and self.on_data_changed:
            self.on_data_changed()

    def _discard_cell_changes(self) -> None:
        """Discard changes for the currently selected cell(s)."""
        selected = self.sheet.get_selected_cells()
        if not selected:
            return

        modified_indices: set[int] = set()
        nickname_changes: list[tuple[int, str, str]] = []

        for display_row, col in selected:
            data_idx = self._get_data_index(display_row)
            if data_idx is None:
                continue

            field_name = COL_TO_FIELD.get(col)
            if not field_name:
                continue

            row = self.rows[data_idx]

            # Track nickname changes for reverse index update
            if field_name == "nickname" and row.is_nickname_dirty:
                old_nick = row.nickname
                new_nick = row.original_nickname
                nickname_changes.append((row.addr_key, old_nick, new_nick))

            if row.discard_field(field_name):
                modified_indices.add(data_idx)

        if not modified_indices:
            return

        # Update displays
        for idx in modified_indices:
            self._update_row_display(idx)

        # Notify parent of nickname changes (for reverse index update)
        if nickname_changes and self.on_nickname_changed:
            for addr_key, old_nick, new_nick in nickname_changes:
                self.on_nickname_changed(self.memory_type, addr_key, old_nick, new_nick)

        # Re-validate affected rows
        for idx in modified_indices:
            self.rows[idx].validate(self._all_nicknames, self.is_duplicate_fn)

        self._refresh_display()

        if self.on_data_changed:
            self.on_data_changed()

    def _discard_row_changes(self) -> None:
        """Discard all changes for the currently selected row(s)."""
        selected = self.sheet.get_selected_rows()
        if not selected:
            return

        modified_indices: set[int] = set()
        nickname_changes: list[tuple[int, str, str]] = []

        for display_row in selected:
            data_idx = self._get_data_index(display_row)
            if data_idx is None:
                continue

            row = self.rows[data_idx]
            if not row.is_dirty:
                continue

            # Track nickname changes for reverse index update
            if row.is_nickname_dirty:
                old_nick = row.nickname
                new_nick = row.original_nickname
                nickname_changes.append((row.addr_key, old_nick, new_nick))

            row.discard()
            modified_indices.add(data_idx)

        if not modified_indices:
            return

        # Update displays
        for idx in modified_indices:
            self._update_row_display(idx)

        # Notify parent of nickname changes (for reverse index update)
        if nickname_changes and self.on_nickname_changed:
            for addr_key, old_nick, new_nick in nickname_changes:
                self.on_nickname_changed(self.memory_type, addr_key, old_nick, new_nick)

        # Re-validate affected rows
        for idx in modified_indices:
            self.rows[idx].validate(self._all_nicknames, self.is_duplicate_fn)

        self._refresh_display()

        if self.on_data_changed:
            self.on_data_changed()

    def _update_discard_menu(
        self, region: str, clicked_row: int | None, clicked_col: int | None
    ) -> None:
        """Update the popup menu based on what was right-clicked."""
        # Remove any existing discard menu items first
        self.sheet.popup_menu_del_command(label="↩ Discard changes")

        if region == "table" and clicked_row is not None and clicked_col is not None:
            # Check if the clicked cell is dirty
            data_idx = self._get_data_index(clicked_row)
            if data_idx is None:
                return

            field_name = COL_TO_FIELD.get(clicked_col)
            if not field_name:
                return

            row = self.rows[data_idx]
            # Check if this specific field is dirty
            is_dirty = False
            if field_name == "nickname" and row.is_nickname_dirty:
                is_dirty = True
            elif field_name == "comment" and row.is_comment_dirty:
                is_dirty = True
            elif field_name == "initial_value" and row.is_initial_value_dirty:
                is_dirty = True
            elif field_name == "retentive" and row.is_retentive_dirty:
                is_dirty = True

            if is_dirty:
                self.sheet.popup_menu_add_command(
                    label="↩ Discard changes",
                    func=self._discard_cell_changes,
                    table_menu=True,
                    index_menu=False,
                    header_menu=False,
                    empty_space_menu=False,
                )

        elif region == "index" and clicked_row is not None:
            # Check if the clicked row is dirty
            data_idx = self._get_data_index(clicked_row)
            if data_idx is None:
                return

            if self.rows[data_idx].is_dirty:
                self.sheet.popup_menu_add_command(
                    label="↩ Discard changes",
                    func=self._discard_row_changes,
                    table_menu=False,
                    index_menu=True,
                    header_menu=False,
                    empty_space_menu=False,
                )

    def _on_right_click(self, event) -> None:
        """Handle right-click to conditionally show 'Discard changes' menu item.

        Runs BEFORE tksheet's handler (via bindtag ordering) so the menu
        is updated before tksheet builds and shows the popup.
        """
        region = self.sheet.identify_region(event)
        clicked_row = self.sheet.identify_row(event)
        clicked_col = self.sheet.identify_column(event)
        self._update_discard_menu(region, clicked_row, clicked_col)

    def _setup_header_notes(self) -> None:
        """Set up tooltip notes on column headers with hints."""

        # Used column
        self.sheet.note(
            self.sheet.span(num2alpha(self.COL_USED), header=True, table=False),
            note="Used in PLC program",
        )

        # Nickname column
        self.sheet.note(
            self.sheet.span(num2alpha(self.COL_NICKNAME), header=True, table=False),
            note="Nickname (≤24 chars, unique)",
        )

        # Init Value column - hint depends on panel type
        if self._is_bit_type_panel():
            init_hint = "Initial value: 0 or 1 (checkbox)"
        elif self.combined_types and len(self.combined_types) > 1:
            primary_type = self.combined_types[0]
            data_type = MEMORY_TYPE_TO_DATA_TYPE.get(primary_type, 0)
            init_hint = f"Initial value\n{self._get_init_value_hint(data_type)}"
        else:
            data_type = MEMORY_TYPE_TO_DATA_TYPE.get(self.memory_type, 0)
            init_hint = f"Initial value\n{self._get_init_value_hint(data_type)}"

        self.sheet.note(
            self.sheet.span(num2alpha(self.COL_INIT_VALUE), header=True, table=False),
            note=init_hint,
        )

        # Retentive column
        self.sheet.note(
            self.sheet.span(num2alpha(self.COL_RETENTIVE), header=True, table=False),
            note="Retains value across power cycles",
        )

        # Comment column
        self.sheet.note(
            self.sheet.span(num2alpha(self.COL_COMMENT), header=True, table=False),
            note="Comment (max 128 chars)",
        )

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

        # Filter enabled checkbutton (replaces "Filter:" label)
        self.filter_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            filter_frame,
            text="Filter:",
            variable=self.filter_enabled_var,
            command=self._apply_filters,
        ).pack(side=tk.LEFT)

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

        ttk.Label(filter_frame, text="Columns:", font=("TkDefaultFont", 10, "bold")).pack(
            side=tk.LEFT, padx=(20, 0)
        )

        self.hide_used_var = tk.BooleanVar(value=False)  # shown by default
        ttk.Checkbutton(
            filter_frame,
            text="Hide Used",
            variable=self.hide_used_var,
            command=self._toggle_used_column,
        ).pack(side=tk.LEFT, padx=(5, 0))

        self.hide_init_ret_var = tk.BooleanVar(value=True)  # Hidden by default
        ttk.Checkbutton(
            filter_frame,
            text="Hide Initial Value/Retentive",
            variable=self.hide_init_ret_var,
            command=self._toggle_init_ret_columns,
        ).pack(side=tk.LEFT, padx=(5, 0))

        # Table (tksheet) - Address is shown in row index for row selection
        self.sheet = AddressEditorSheet(
            self,
            headers=["Used", "Nickname", "Comment", "Init Value", "Ret"],
            show_row_index=True,
            index_align="w",  # Left-align the row index
            height=400,
            width=800,
            note_corners=True,  # Enable note indicators
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        CharLimitTooltip(
            sheet=self.sheet, char_limits={self.COL_NICKNAME: 24, self.COL_COMMENT: 128}
        )

        # Configure notes to behave like tooltips
        self.sheet.set_options(
            tooltip_hover_delay=300,  # Appears in 300ms instead of 1200ms
            tooltip_width=300,  # Wider to prevent horizontal scrolling
            tooltip_height=100,  # Height to fit a few lines without scrolling
        )

        # Enable standard bindings for editing, but disable unwanted ones
        self.sheet.enable_bindings()
        # Change Find/Replace binding from Ctrl+H to Ctrl+R
        self.sheet.set_options(toggle_replace_bindings=["<Control-r>", "<Control-R>"])
        # Disable column header right-click menu and sorting options
        self.sheet.disable_bindings(
            "column_drag_and_drop",
            "row_drag_and_drop",
            "rc_select_column",
            "rc_insert_column",
            "rc_delete_column",
            "rc_insert_row",
            "rc_delete_row",
            "sort_cells",
            "sort_row",
            "sort_column",
            "sort_rows",
            "sort_columns",
            "undo",
        )

        # Bind right-click to dynamically show/hide "Discard changes" menu item
        self.sheet.add_begin_right_click(self._on_right_click)

        # Set column widths (address is in row index now)
        self.sheet.set_column_widths([40, 200, 400, 90, 30])
        self.sheet.row_index(70)  # Set row index width
        self.sheet.readonly_columns([self.COL_USED])

        # Set up header notes with hints
        self._setup_header_notes()

        # Use bulk_table_edit_validation for paste operations ===
        # This ensures the entire paste completes before validation runs
        self.sheet.bulk_table_edit_validation(self._bulk_validate)

        # Bind to <<SheetModified>> for post-edit processing ===
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
        on_nickname_changed: Callable[[str, int, str, str], None] | None = None,
        on_data_changed: Callable[[], None] | None = None,
        on_close: Callable[[AddressPanel], None] | None = None,
        on_validate_affected: Callable[[str, str], set[int]] | None = None,
        is_duplicate_fn: Callable[[str, int], bool] | None = None,
        is_unified: bool = False,
        section_boundaries: dict[str, int] | None = None,
    ):
        """Initialize the address panel.

        Args:
            parent: Parent widget
            memory_type: The memory type to edit (X, Y, C, etc.)
            combined_types: List of types to show interleaved (e.g., ["T", "TD"])
            on_nickname_changed: Callback when a nickname changes (memory_type, addr_key, old, new).
            on_data_changed: Callback when any data changes (for multi-window sync).
            on_close: Callback when panel close button is clicked.
            on_validate_affected: Callback to validate rows affected by nickname change (old, new).
                Returns set of validated addr_keys. Used for O(1) targeted validation.
            is_duplicate_fn: O(1) duplicate checker function(nickname, exclude_addr_key) -> bool.
            is_unified: If True, panel displays ALL memory types in one view.
            section_boundaries: Maps type_key to starting row index (for unified mode).
        """
        super().__init__(parent)

        self.memory_type = memory_type
        self.combined_types = combined_types  # None means single type
        self.on_nickname_changed = on_nickname_changed
        self.on_data_changed = on_data_changed
        self.on_close = on_close
        self.on_validate_affected = on_validate_affected
        self.is_duplicate_fn = is_duplicate_fn
        self.is_unified = is_unified
        self.section_boundaries = section_boundaries or {}

        self.rows: list[AddressRow] = []
        self._all_nicknames: dict[int, str] = {}
        self._displayed_rows: list[int] = []  # Data indices of currently displayed rows

        # Flag to suppress change notifications during programmatic updates
        self._suppress_notifications = False

        # Track selected row for filter changes (actual row index in self.rows)
        self._selected_row_idx: int | None = None
        self._selected_row_visual_offset = None

        # Styler will be initialized after load_data() populates self.rows
        self._styler: AddressRowStyler | None = None

        self._create_widgets()

    def toggle_filter_enabled(self, enabled: bool) -> None:
        """Toggle filter enabled state.

        Args:
            enabled: True to enable filtering, False to disable (show all rows)
        """
        self.filter_enabled_var.set(enabled)
        self._apply_filters()

    def scroll_to_section(self, type_key: str) -> bool:
        """Scroll to the start of a memory type section (unified mode only).

        Args:
            type_key: The memory type key (e.g., "X", "T/TD", "DS")

        Returns:
            True if section was found and scrolled to, False otherwise
        """
        if not self.is_unified or type_key not in self.section_boundaries:
            return False

        # Get the row index where this section starts
        row_idx = self.section_boundaries[type_key]

        # Find the display index for this row
        if row_idx in self._displayed_rows:
            display_idx = self._displayed_rows.index(row_idx)
        else:
            # Row is filtered out - find the first visible row in this section
            # by checking which displayed rows fall in this section's range
            next_section_start = None
            for _other_key, other_idx in self.section_boundaries.items():
                if other_idx > row_idx and (
                    next_section_start is None or other_idx < next_section_start
                ):
                    next_section_start = other_idx

            # Find first displayed row in range [row_idx, next_section_start)
            for i, disp_row_idx in enumerate(self._displayed_rows):
                if disp_row_idx >= row_idx:
                    if next_section_start is None or disp_row_idx < next_section_start:
                        display_idx = i
                        break
            else:
                # No visible rows in this section
                return False

        self._scroll_to_row(display_idx, align_top=True)
        return True

    def _validate_all(self) -> None:
        """Validate all rows against current nickname registry."""
        for row in self.rows:
            row.validate(self._all_nicknames)

    def _get_block_colors_for_rows(self) -> dict[int, str]:
        """Compute block background colors for each row address.

        Parses block tags from row comments to determine which rows
        should have colored row indices. Nested blocks override outer blocks.

        Returns:
            Dict mapping row index (in self.rows) to bg color string.
        """

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

    def _populate_sheet_data(self) -> None:
        """Populate sheet with ALL row data (called once at load time).

        This sets up the full dataset and creates cell-specific checkboxes.
        """
        # Build and set all data at once
        data = [self._build_row_display_data(row) for row in self.rows]

        self.sheet.set_sheet_data(data, reset_col_positions=False)
        self.sheet.set_index_data([row.display_address for row in self.rows])

        # Create checkboxes
        for data_idx, row in enumerate(self.rows):
            # Retentive checkbox
            self.sheet.create_checkbox(
                r=data_idx,
                c=self.COL_RETENTIVE,
                checked=row.retentive,
                text="",
            )
            # Initial value checkbox
            if row.data_type == DataType.BIT:
                init_val = data[data_idx][self.COL_INIT_VALUE]
                if init_val != "-":
                    self.sheet.create_checkbox(
                        r=data_idx,
                        c=self.COL_INIT_VALUE,
                        checked=(init_val is True),
                        text="",
                    )

    def initialize_from_view(self, rows: list, nicknames: dict):
        """Initializes the panel with row data, performs validation, and sets up styling."""
        self.rows = rows
        self._all_nicknames = nicknames

        self._validate_all()
        self._populate_sheet_data()
        self._apply_filters()

        # Initialize styler
        self._styler = AddressRowStyler(
            sheet=self.sheet,
            get_rows=lambda: self.rows,
            get_displayed_rows=lambda: self._displayed_rows,
            get_block_colors=self._get_block_colors_for_rows,
        )

        self._refresh_display()

    def revalidate(self) -> None:
        """Re-validate all rows (called when global nicknames change)."""
        self._validate_all()
        self._refresh_display()

    def refresh_from_external(self, skip_validation: bool = False) -> None:
        """Refresh all row displays after external data changes.

        Call this when AddressRow objects have been updated externally
        (e.g., via row.update_from_db()) to sync the sheet's cell data.

        Args:
            skip_validation: If True, skip _validate_all() because the sender
                already validated the shared rows. Use when syncing from another
                window's edit (not from external DB changes).
        """
        # Update all row displays to sync AddressRow data to sheet cells
        for data_idx in range(len(self.rows)):
            self._update_row_display(data_idx)

        # Revalidate only if needed (external DB changes, not window sync)
        if not skip_validation:
            self._validate_all()

        self._refresh_display()

    def rebuild_from_view(self, view):
        """Rebuild panel data from a view object."""
        self.rows = view.rows
        self._validate_all()
        self._populate_sheet_data()
        self._apply_filters()
        self._refresh_display()

    def get_dirty_rows(self) -> list[AddressRow]:
        """Get all rows that have been modified."""
        return [row for row in self.rows if row.is_dirty]

    def has_errors(self) -> bool:
        """Check if any rows have validation errors."""
        return any(row.has_reportable_error for row in self.rows)

    def get_error_count(self) -> int:
        """Get count of rows with validation errors."""
        return sum(1 for row in self.rows if row.has_reportable_error)

    def _highlight_row(self, data_idx: int, duration_ms: int = 1500) -> None:
        """Temporarily highlight a row to draw user attention.

        Args:
            data_idx: The data index of the row to highlight
            duration_ms: How long to show the highlight in milliseconds
        """
        if self._styler:
            self._styler.highlight_row_temporary(
                data_idx=data_idx,
                duration_ms=duration_ms,
                after_func=self.after,
            )

    def scroll_to_address(
        self, address: int, memory_type: str | None = None, align_top: bool = False
    ) -> bool:
        """Scroll to show a specific address.

        Args:
            address: The address number to scroll to
            memory_type: Optional memory type for combined panels
            align_top: If True, ensure the address is at the top of the viewport.
                       If False (default), just ensure it's visible somewhere in the viewport.

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

            # Use helper function for scrolling
            self._scroll_to_row(display_idx, align_top=align_top)

            # Highlight the row briefly to show the user where it is
            self._highlight_row(row_idx)
            return True
        except ValueError:
            return False
