"""Unified panel widget for editing all PLC addresses.

Uses tksheet for high-performance table display with virtual rows.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

from tksheet import num2alpha

from ...models.address_row import AddressRow
from ...models.constants import (
    DATA_TYPE_HINTS,
    NON_EDITABLE_TYPES,
    DataType,
)
from ...utils.filters import text_matches_filter
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

if TYPE_CHECKING:
    from ...data.address_store import AddressStore

# Mapping from column index to AddressRow field name for discard operations
COL_TO_FIELD = {
    COL_NICKNAME: "nickname",
    COL_COMMENT: "comment",
    COL_INIT_VALUE: "initial_value",
    COL_RETENTIVE: "retentive",
}


class AddressPanel(ttk.Frame):
    """Unified panel for editing all PLC addresses.

    Displays ALL possible addresses across all memory types in a single
    scrollable view, with section boundaries for navigation.
    """

    # Column indices imported from panel_constants
    COL_USED = COL_USED
    COL_NICKNAME = COL_NICKNAME
    COL_COMMENT = COL_COMMENT
    COL_INIT_VALUE = COL_INIT_VALUE
    COL_RETENTIVE = COL_RETENTIVE

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
        """Apply current filter settings using tksheet's display_rows().

        Supports anchor patterns:
        - ^pattern - matches at start of field
        - pattern$ - matches at end of field
        - ^pattern$ - exact match
        """
        # Save current selection before changing filter
        self._save_selection()

        # Text filter only applies when "Filter:" checkbox is enabled
        filter_enabled = self.filter_enabled_var.get()
        raw_filter = self.filter_var.get() if filter_enabled else ""

        # Parse anchors from filter text
        anchor_start = raw_filter.startswith("^")
        anchor_end = raw_filter.endswith("$")
        filter_text = raw_filter.lower()
        if anchor_start:
            filter_text = filter_text[1:]
        if anchor_end:
            filter_text = filter_text[:-1]

        # Row filter: all, content, changed, errors
        row_filter = self.row_filter_var.get()

        # Check if any filters are active
        no_filters = not filter_text and row_filter == "all"

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
                    addr_match = text_matches_filter(
                        row.display_address.lower(), filter_text, anchor_start, anchor_end
                    )
                    nick_match = text_matches_filter(
                        row.nickname.lower(), filter_text, anchor_start, anchor_end
                    )
                    comment_match = text_matches_filter(
                        row.comment.lower(), filter_text, anchor_start, anchor_end
                    )
                    if not (addr_match or nick_match or comment_match):
                        continue

                # Row filter modes
                if row_filter == "content" and row.is_empty:
                    continue
                if row_filter == "changed" and not self._store.is_dirty(row.addr_key):
                    continue
                if row_filter == "errors" and not row.has_reportable_error:
                    continue

                self._displayed_rows.append(i)

            self.sheet.display_rows(rows=self._displayed_rows, all_displayed=False, redraw=True)

        # Restore selection after filter change
        self._restore_selection()

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

        # Use edit_session for proper change tracking, validation, and notification
        with self._store.edit_session("Edit cells"):
            for (event_row, col), _old_value in table_cells.items():
                data_idx = event_row

                if data_idx is None or data_idx >= len(self.rows):
                    continue

                address_row = self.rows[data_idx]
                addr_key = address_row.addr_key

                # Get the NEW value from the sheet using data index
                new_value = self.sheet.get_cell_data(data_idx, col)

                if col == self.COL_NICKNAME:
                    new_nickname = new_value if new_value else ""

                    # Skip if no change
                    if new_nickname == address_row.nickname:
                        continue

                    # Use session to set the field
                    self._store._current_session.set_field(addr_key, "nickname", new_nickname)

                elif col == self.COL_COMMENT:
                    new_comment = new_value if new_value else ""

                    # Skip if no change
                    if new_comment == address_row.comment:
                        continue

                    # Use session to set the field
                    self._store._current_session.set_field(addr_key, "comment", new_comment)

                elif col == self.COL_INIT_VALUE:
                    # Skip if type doesn't allow editing initial value
                    if not address_row.can_edit_initial_value:
                        continue

                    # Check if row is masked by Retentive (showing "-")
                    paired_row = find_paired_row(address_row, self.rows)
                    effective_retentive = (
                        paired_row.retentive if paired_row else address_row.retentive
                    )
                    if address_row.is_initial_value_masked(effective_retentive):
                        # Revert the cell display back to "-"
                        self.sheet.set_cell_data(data_idx, col, "-")
                        continue

                    # Standard update logic
                    if address_row.data_type == DataType.BIT:
                        new_init = "1" if bool(new_value) else "0"
                    else:
                        new_init = new_value if new_value else ""

                    # Skip if no change
                    if new_init == address_row.initial_value:
                        continue

                    # Use session to set the field
                    self._store._current_session.set_field(addr_key, "initial_value", new_init)

                elif col == self.COL_RETENTIVE:
                    # Skip if type doesn't allow editing retentive
                    if not address_row.can_edit_retentive:
                        continue

                    # Handle retentive checkbox toggle - value is boolean
                    new_retentive = bool(new_value)

                    # For TD/CTD rows, update the paired T/CT row instead
                    paired_row = find_paired_row(address_row, self.rows)
                    target_row = paired_row if paired_row else address_row
                    target_key = target_row.addr_key

                    # Skip if no change
                    if new_retentive == target_row.retentive:
                        continue

                    # Use session to set the field on the target row
                    self._store._current_session.set_field(target_key, "retentive", new_retentive)

        # edit_session exited - validation and notification happened automatically

    def _discard_cell_changes(self) -> None:
        """Discard changes for the currently selected cell(s).

        Note: With the new architecture, discarding restores the base_state value.
        """
        selected = self.sheet.get_selected_cells()
        if not selected:
            return

        # Collect cells to discard
        cells_to_discard: list[tuple[int, str]] = []
        for display_row, col in selected:
            data_idx = self._get_data_index(display_row)
            if data_idx is None:
                continue

            field_name = COL_TO_FIELD.get(col)
            if not field_name:
                continue

            row = self.rows[data_idx]
            if self._store.is_field_dirty(row.addr_key, field_name):
                cells_to_discard.append((data_idx, field_name))

        if not cells_to_discard:
            return

        # Use edit_session to restore base values
        with self._store.edit_session("Discard cell changes"):
            for data_idx, field_name in cells_to_discard:
                row = self.rows[data_idx]
                addr_key = row.addr_key
                base_row = self._store.base_state.get(addr_key)
                if base_row:
                    base_value = getattr(base_row, field_name)
                    self._store._current_session.set_field(addr_key, field_name, base_value)

    def _discard_row_changes(self) -> None:
        """Discard all changes for the currently selected row(s)."""
        selected = self.sheet.get_selected_rows()
        if not selected:
            return

        # Collect rows to discard
        rows_to_discard: list[int] = []
        for display_row in selected:
            data_idx = self._get_data_index(display_row)
            if data_idx is None:
                continue

            row = self.rows[data_idx]
            if self._store.is_dirty(row.addr_key):
                rows_to_discard.append(data_idx)

        if not rows_to_discard:
            return

        # Use edit_session to restore base values
        with self._store.edit_session("Discard row changes"):
            for data_idx in rows_to_discard:
                row = self.rows[data_idx]
                addr_key = row.addr_key
                base_row = self._store.base_state.get(addr_key)
                if base_row:
                    for field in ["nickname", "comment", "initial_value", "retentive"]:
                        base_value = getattr(base_row, field)
                        self._store._current_session.set_field(addr_key, field, base_value)

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
            is_dirty = self._store.is_field_dirty(row.addr_key, field_name)

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

            row = self.rows[data_idx]
            if self._store.is_dirty(row.addr_key):
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

        # Init Value column - show all type hints
        init_hints = [
            f"BIT: {DATA_TYPE_HINTS[DataType.BIT]}",
            f"INT: {DATA_TYPE_HINTS[DataType.INT]}",
            f"INT2: {DATA_TYPE_HINTS[DataType.INT2]}",
            f"FLOAT: {DATA_TYPE_HINTS[DataType.FLOAT]}",
            f"HEX: {DATA_TYPE_HINTS[DataType.HEX]}",
            f"TXT: {DATA_TYPE_HINTS[DataType.TXT]}",
        ]
        self.sheet.note(
            self.sheet.span(num2alpha(self.COL_INIT_VALUE), header=True, table=False),
            note="Initial value\n" + "\n".join(init_hints),
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
        self.filter_entry.pack(side=tk.LEFT, padx=(5, 0))
        self.filter_var.trace_add("write", lambda *_: self._apply_filters())

        # Vertical separator between text filter and checkbox filters
        ttk.Separator(filter_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # Row filter radio buttons: All, Content, Changed, Errors
        ttk.Label(filter_frame, text="Show:").pack(side=tk.LEFT)
        self.row_filter_var = tk.StringVar(value="all")
        for value, text in [
            ("all", "All"),
            ("content", "Content"),
            ("changed", "Changed"),
            ("errors", "Errors"),
        ]:
            ttk.Radiobutton(
                filter_frame,
                text=text,
                value=value,
                variable=self.row_filter_var,
                command=self._apply_filters,
            ).pack(side=tk.LEFT, padx=(3, 0))

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
        # Unbind Ctrl+Space from sheet - we use it for filter toggle at window level
        self.sheet.unbind("<Control-space>")

        # Bind right-click to dynamically show/hide "Discard changes" menu item
        self.sheet.add_begin_right_click(self._on_right_click)

        # Set column widths (address is in row index now)
        self.sheet.set_column_widths([40, 200, 400, 90, 50])
        self.sheet.row_index(70)  # Set row index width
        self.sheet.readonly_columns([self.COL_USED])

        # Set up header notes with hints
        self._setup_header_notes()

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
        store: AddressStore,
        on_validate_affected: Callable[[str, str], set[int]] | None = None,
        is_duplicate_fn: Callable[[str, int], bool] | None = None,
        section_boundaries: dict[str, int] | None = None,
    ):
        """Initialize the unified address panel.

        Args:
            parent: Parent widget
            store: AddressStore instance for data management
            on_validate_affected: Callback to validate rows affected by nickname change (old, new).
                Returns set of validated addr_keys. Used for O(1) targeted validation.
            is_duplicate_fn: O(1) duplicate checker function(nickname, exclude_addr_key) -> bool.
            section_boundaries: Maps type_key to starting row index for navigation.
        """
        super().__init__(parent)

        self._store = store
        self.on_validate_affected = on_validate_affected
        self.is_duplicate_fn = is_duplicate_fn
        self.section_boundaries = section_boundaries or {}

        self.rows: list[AddressRow] = []
        self._displayed_rows: list[int] = []  # Data indices of currently displayed rows

        # Flag to suppress change notifications during programmatic updates
        self._suppress_notifications = False

        # Track selected row for filter changes (actual row index in self.rows)
        self._selected_row_idx: int | None = None
        self._selected_row_visual_offset = None

        # Styler will be initialized after load_data() populates self.rows
        self._styler: AddressRowStyler | None = None

        self._create_widgets()

    def _update_status(self) -> None:
        """Update the status label with current counts."""
        total_visible = len(self._displayed_rows)
        error_count = self.get_error_count()
        modified_count = sum(
            1 for idx in self._displayed_rows if self._store.is_dirty(self.rows[idx].addr_key)
        )

        self.status_label.config(
            text=f"Rows: {total_visible} | Errors: {error_count} | Modified: {modified_count}"
        )

    def _refresh_display(self, modified_rows: set[int] | None = None) -> None:
        """Refresh styling and status.

        Args:
            modified_rows: If provided, only refresh styling for these data indices.
                           If None, performs full refresh (dehighlight_all + re-apply all).
        """
        if self._styler:
            if modified_rows is not None:
                # Incremental update - only refresh modified rows
                self._styler.update_rows_styling(modified_rows)
            else:
                # Full refresh (for filter changes, etc.)
                self._styler.apply_all_styling()
        # Defer status update to avoid blocking the edit (iterates all rows)
        self.after_idle(self._update_status)
        # Use set_refresh_timer() instead of redraw() to prevent multiple redraws
        # and ensure proper refresh after set_cell_data() calls
        self.sheet.set_refresh_timer()

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

    def _keys_to_indices(self, addr_keys: set[int]) -> set[int]:
        """Convert address keys to row indices in this panel.

        Args:
            addr_keys: Set of address keys

        Returns:
            Set of row indices in self.rows
        """
        indices = set()
        for i, row in enumerate(self.rows):
            if row.addr_key in addr_keys:
                indices.add(i)
        return indices

    def toggle_filter_enabled(self, enabled: bool) -> None:
        """Toggle filter enabled state.

        Args:
            enabled: True to enable filtering, False to disable (show all rows)
        """
        self.filter_enabled_var.set(enabled)
        self._apply_filters()

    def scroll_to_section(self, type_key: str) -> bool:
        """Scroll to the start of a memory type section.

        Args:
            type_key: The memory type key (e.g., "X", "T/TD", "DS")

        Returns:
            True if section was found and scrolled to, False otherwise
        """
        if type_key not in self.section_boundaries:
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

    def initialize_from_view(self, rows: list):
        """Initializes the panel with row data and sets up styling.

        Note: Validation is handled by edit_session during data loading,
        so rows are already validated when this is called.
        """
        self.rows = rows

        self._populate_sheet_data()
        self._apply_filters()

        # Initialize styler with store reference
        self._styler = AddressRowStyler(
            sheet=self.sheet,
            store=self._store,
            get_rows=lambda: self.rows,
            get_displayed_rows=lambda: self._displayed_rows,
        )

        self._refresh_display()

    def refresh_from_external(self) -> None:
        """Refresh all row displays after external data changes.

        Call this when AddressRow objects have been updated externally
        to sync the sheet's cell data.

        Note: Validation is handled by edit_session, so this only refreshes
        the display without re-validating.
        """
        # Update all row displays to sync AddressRow data to sheet cells
        for data_idx in range(len(self.rows)):
            self._update_row_display(data_idx)

        self._refresh_display()

    def refresh_targeted(self, addr_keys: set[int]) -> None:
        """Refresh only specific rows after external data changes.

        More efficient than refresh_from_external() when only a few rows changed.
        Used by observer callbacks to handle targeted updates from edit_session.

        Args:
            addr_keys: Set of address keys that changed
        """
        if not addr_keys:
            return

        # Update the rows list from the store's visible_state
        for i, row in enumerate(self.rows):
            if row.addr_key in addr_keys:
                # Get the updated row from the store
                updated_row = self._store.visible_state.get(row.addr_key)
                if updated_row:
                    self.rows[i] = updated_row

        # Convert addr_keys to row indices in this panel
        row_indices = self._keys_to_indices(addr_keys)

        if not row_indices:
            return

        # Update display for affected rows only
        for data_idx in row_indices:
            self._update_row_display(data_idx)

        # Refresh styling for affected rows only (validation already done by edit_session)
        self._refresh_display(modified_rows=row_indices)

    def get_dirty_rows(self) -> list[AddressRow]:
        """Get all rows that have been modified."""
        return [row for row in self.rows if self._store.is_dirty(row.addr_key)]

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
            memory_type: Memory type to match (e.g., "X", "DS"). If None, matches first row.
            align_top: If True, ensure the address is at the top of the viewport.
                       If False (default), just ensure it's visible somewhere in the viewport.

        Returns:
            True if address was found and scrolled to
        """
        # Find the row index for this address
        row_idx = None
        if memory_type:
            for i, row in enumerate(self.rows):
                if row.address == address and row.memory_type == memory_type:
                    row_idx = i
                    break

        if row_idx is None:
            # Try without type match (search all rows)
            for i, row in enumerate(self.rows):
                if row.address == address:
                    row_idx = i
                    break

        if row_idx is None:
            return False

        # Check if it's visible in current filter
        if row_idx not in self._displayed_rows:
            self.filter_var.set("")
            self.row_filter_var.set("all")
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
