"""Panel widget for editing a single DataView.

Uses tksheet for table display with dynamic rows and overflow handling.
Target is 100 rows, but overflow (rows 100+) is supported with visual indication.
"""

from __future__ import annotations

import dataclasses
import os
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from tkinter import messagebox, ttk

from pyclickplc.addresses import normalize_address
from pyclickplc.dataview import (
    MAX_DATAVIEW_ROWS,
    DataViewFile,
    DataViewRecord,
)
from tksheet import Sheet

from ..sim_palette import FORCED_BG

# Column indices
COL_ADDRESS = 0
COL_NICKNAME = 1
COL_COMMENT = 2
COL_NEW_VALUE = 3
COL_WRITE = 4
COL_LIVE = 5
#: Shown only while the editor is attached to the simulator.
COL_FORCE = 6

NUM_COLUMNS = 7

PlcValue = bool | int | float | str

# Color for overflow rows (index >= 100)
COLOR_OVERFLOW_BG = "#e0e0e0"

# Highlight for live value changes
COLOR_LIVE_FLASH = "#90EE90"  # Light green
LIVE_FLASH_DURATION_MS = 1500

# File monitoring interval in milliseconds
FILE_MONITOR_INTERVAL_MS = 2000

#: Undo levels kept per dataview.
MAX_UNDO_DEPTH = 50

#: The rows and their Write checks, as one undo step restores them.
_UndoFrame = tuple[list[DataViewRecord], list[bool]]


class DataviewPanel(ttk.Frame):
    """Panel for editing a single DataView's addresses.

    Displays rows with columns:
    Address, Nickname, Comment, New Value, Write, Live, and (attached to the
    simulator) Force.
    Target is 100 rows, but supports overflow (rows 100+) with grey background.
    Overflow rows are excluded from saves.
    Supports row reordering, insert/delete, cut/copy/paste, and address autocomplete.
    New Value data is preserved internally and shown using DataViewFile helpers.
    """

    def _display_address(self, text: str) -> str | None:
        """CLICK's form of an address (``x1`` -> ``X001``, ``xd0u`` -> ``XD0u``), or None."""
        candidate = (text or "").strip()
        if not candidate:
            return None
        if self.address_normalizer is not None:
            normalized = self.address_normalizer(candidate)
            if normalized:
                return normalized
        return normalize_address(candidate)

    def _canonical_address(self, address: str) -> str | None:
        """Normalize an address for poll/write payloads."""
        normalized = self._display_address(address)
        return normalized.upper() if normalized else None

    @staticmethod
    def _display_text(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _is_row_write_enabled(self, row: DataViewRecord) -> bool:
        """True when write controls should be interactive for a row."""
        return bool(row.address.strip()) and row.is_writable

    def _new_value_display(self, row: DataViewRecord) -> str:
        return DataViewFile.value_to_display(row.new_value, row.data_type)

    def _live_value_display(self, row: DataViewRecord) -> str:
        address = self._canonical_address(row.address)
        if not address:
            return ""
        value = self._live_values.get(address)
        return DataViewFile.value_to_display(value, row.data_type)

    def _force_display(self, row: DataViewRecord) -> str:
        address = self._canonical_address(row.address)
        if not address or address not in self._forces:
            return ""
        return DataViewFile.value_to_display(self._forces[address], row.data_type)

    def _sync_force_cell(self, row_idx: int) -> None:
        """Show a row's force and mark forced rows the way the Simulator does."""
        row = self.rows[row_idx]
        text = self._force_display(row)
        self.sheet.set_cell_data(row_idx, COL_FORCE, text, redraw=False)
        for column in (COL_ADDRESS, COL_FORCE):
            if text:
                self.sheet.highlight_cells(row=row_idx, column=column, bg=FORCED_BG, redraw=False)
            elif row_idx < MAX_DATAVIEW_ROWS:
                self.sheet.dehighlight_cells(row=row_idx, column=column, redraw=False)

    def _sync_write_checkbox(self, row_idx: int) -> None:
        """Refresh write checkbox cell for a row."""
        row = self.rows[row_idx]
        is_enabled = self._is_row_write_enabled(row)

        # Keep checked state only when writes are allowed.
        if not is_enabled:
            self._write_checks[row_idx] = False

        try:
            self.sheet.delete_checkbox(row_idx, COL_WRITE)
        except Exception:
            pass

        if is_enabled:
            checked = bool(self._write_checks[row_idx])
            self.sheet.create_checkbox(r=row_idx, c=COL_WRITE, checked=checked, text="")
            self.sheet.set_cell_data(row_idx, COL_WRITE, checked)
        else:
            self.sheet.set_cell_data(row_idx, COL_WRITE, "")

    def _notify_addresses_changed(self) -> None:
        if self.on_addresses_changed:
            self.on_addresses_changed(self)

    def _refresh_row_indices(self) -> None:
        """Refresh row index labels (1, 2, 3, ...)."""
        self.sheet.set_index_data([str(i + 1) for i in range(len(self.rows))])

    def _apply_overflow_styling(self) -> None:
        """Apply grey background to overflow rows (index >= MAX_DATAVIEW_ROWS)."""
        # Clear existing highlights first for overflow rows
        for i in range(len(self.rows)):
            if i >= MAX_DATAVIEW_ROWS:
                # Apply grey background to all columns
                for col in range(NUM_COLUMNS):
                    self.sheet.highlight_cells(
                        row=i,
                        column=col,
                        bg=COLOR_OVERFLOW_BG,
                    )
                # Also highlight row index
                self.sheet.highlight_cells(
                    row=i,
                    bg=COLOR_OVERFLOW_BG,
                    canvas="row_index",
                )

    def _names_for(self, address: str) -> tuple[str, str]:
        """Nickname and comment for an address, read live from the address data.

        Never stored on the row, so the sheet cannot show a stale name.
        """
        if not address or self.nickname_lookup is None:
            return "", ""
        return self.nickname_lookup(address) or ("", "")

    def _populate_sheet(self) -> None:
        """Populate sheet with current row data."""
        self._suppress_notifications = True
        try:
            data = []
            for i, row in enumerate(self.rows):
                is_enabled = self._is_row_write_enabled(row)
                checked = bool(self._write_checks[i]) if is_enabled else ""
                nickname, comment = self._names_for(row.address)
                data.append(
                    [
                        row.address,
                        nickname,
                        comment,
                        self._new_value_display(row),
                        checked,
                        self._live_value_display(row),
                        self._force_display(row),
                    ]
                )

            self.sheet.set_sheet_data(data, reset_col_positions=False)
            for i in range(len(self.rows)):
                self._sync_write_checkbox(i)
                self._sync_force_cell(i)

            # Set row index labels (1 to N)
            self._refresh_row_indices()

            # Apply overflow styling if needed
            self._apply_overflow_styling()
        finally:
            self._suppress_notifications = False

    def _update_row_display(self, row_idx: int) -> None:
        """Update display for a single row."""
        row = self.rows[row_idx]

        nickname, comment = self._names_for(row.address)
        self.sheet.set_cell_data(row_idx, COL_ADDRESS, row.address)
        self.sheet.set_cell_data(row_idx, COL_NICKNAME, nickname)
        self.sheet.set_cell_data(row_idx, COL_COMMENT, comment)
        self.sheet.set_cell_data(row_idx, COL_NEW_VALUE, self._new_value_display(row))
        self.sheet.set_cell_data(row_idx, COL_LIVE, self._live_value_display(row))
        self._sync_write_checkbox(row_idx)
        self._sync_force_cell(row_idx)

    def _update_status(self) -> None:
        """Update the status label."""
        filled_count = sum(1 for r in self.rows if not r.is_empty)
        total_count = len(self.rows)
        dirty_text = " (modified)" if self._is_dirty else ""

        if total_count > MAX_DATAVIEW_ROWS:
            overflow_count = total_count - MAX_DATAVIEW_ROWS
            self.status_label.config(
                text=f"Addresses: {filled_count}/{total_count} "
                f"({overflow_count} overflow, not saved){dirty_text}"
            )
        else:
            self.status_label.config(
                text=f"Addresses: {filled_count}/{MAX_DATAVIEW_ROWS}{dirty_text}"
            )

    def _apply_force_edit(self, row_idx: int, text: str) -> None:
        """Force (or, when cleared, release) the row's address through the simulator.

        The cell then shows the simulator's forces again; a refused force never
        appears, and the simulator reports why.
        """
        row = self.rows[row_idx]
        address = self._canonical_address(row.address)
        if address and self.on_force is not None:
            if not text:
                if address in self._forces:
                    self.on_force(address, None)
            else:
                parsed = DataViewFile.try_parse_display(text, row.data_type)
                if parsed.ok and parsed.value is not None:
                    self.on_force(address, parsed.value)
        self._sync_force_cell(row_idx)

    def _row_values(self) -> list[tuple[object, ...]]:
        """What a save writes for each row."""
        return [(row.address, row.data_type, row.new_value) for row in self.rows]

    def _snapshot(self) -> _UndoFrame:
        return [dataclasses.replace(row) for row in self.rows], list(self._write_checks)

    def _push_undo(self, before: _UndoFrame) -> None:
        """Record the state an edit started from; a new edit drops Redo."""
        self._undo_stack.append(before)
        del self._undo_stack[:-MAX_UNDO_DEPTH]
        self._redo_stack.clear()

    def _mark_saved(self) -> None:
        """The rows now match the file."""
        self._saved_values = self._row_values()
        self._is_dirty = False
        self._unloaded_change = False

    def _on_undo_key(self, _event=None) -> str:
        self.undo()
        return "break"

    def _on_redo_key(self, _event=None) -> str:
        self.redo()
        return "break"

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

        before = self._snapshot()
        data_changed = False
        addresses_changed = False

        for (row_idx, col), _old_value in table_cells.items():
            if row_idx >= len(self.rows):
                continue

            row = self.rows[row_idx]
            new_value = self.sheet.get_cell_data(row_idx, col)

            if col == COL_ADDRESS:
                old_address = row.address
                new_address = (new_value or "").strip()

                if new_address != row.address:
                    row.address = new_address
                    row.update_data_type()

                    # Clear stale runtime state when writability/address changes.
                    if old_address != row.address:
                        old_canonical = self._canonical_address(old_address)
                        if old_canonical:
                            self._live_values.pop(old_canonical, None)

                    row.new_value = None
                    self._write_checks[row_idx] = False
                    if not self._is_row_write_enabled(row):
                        row.new_value = None

                    # Update display for this row
                    self._update_row_display(row_idx)
                    data_changed = True
                    addresses_changed = True

            elif col == COL_NEW_VALUE:
                if not self._is_row_write_enabled(row):
                    self._update_row_display(row_idx)
                    continue

                display_text = self._display_text(new_value)
                old_native = row.new_value
                try:
                    DataViewFile.set_row_new_value_from_display(row, display_text)
                except ValueError:
                    self._update_row_display(row_idx)
                    continue

                normalized = self._new_value_display(row)
                if self.sheet.get_cell_data(row_idx, COL_NEW_VALUE) != normalized:
                    self.sheet.set_cell_data(row_idx, COL_NEW_VALUE, normalized)
                if row.new_value != old_native:
                    data_changed = True

            elif col == COL_FORCE:
                self._apply_force_edit(row_idx, self._display_text(new_value))

            elif col == COL_WRITE:
                if self._is_row_write_enabled(row):
                    self._write_checks[row_idx] = bool(new_value)
                else:
                    self._write_checks[row_idx] = False
                self._sync_write_checkbox(row_idx)

        if data_changed:
            self._push_undo(before)
            self._is_dirty = True
            self._update_status()
            if self.on_modified:
                self.on_modified()
        if addresses_changed:
            self._notify_addresses_changed()

    def _on_rows_moved(self, event) -> None:
        """Handle row drag-and-drop reordering.

        Updates self.rows to match the new order in the sheet.
        """
        if self._suppress_notifications:
            return

        # 1. Extract mapping
        moved = event.get("moved", {})
        rows_data = moved.get("rows", {}).get("data", {})

        if not rows_data:
            return
        before = self._snapshot()

        # Ensure keys are integers (JSON often sends "0": 5)
        mapping = {int(k): int(v) for k, v in rows_data.items()}

        # 2. Create the "Skeleton" List
        # Place the moved items exactly where they belong.
        new_rows = [None] * len(self.rows)
        new_checks: list[bool | None] = [None] * len(self._write_checks)
        for old_idx, new_idx in mapping.items():
            new_rows[new_idx] = self.rows[old_idx]
            new_checks[new_idx] = self._write_checks[old_idx]

        # 3. Collect the Unmoved Rows
        # Identify rows that weren't moved and reverse them so we can .pop() efficiently.
        remaining = [row for i, row in enumerate(self.rows) if i not in mapping]
        remaining.reverse()
        remaining_checks = [check for i, check in enumerate(self._write_checks) if i not in mapping]
        remaining_checks.reverse()

        # 4. Fill the Gaps
        # List comprehension: If the slot has a moved row, keep it.
        # If it's None, pop the next available unmoved row into it.
        self.rows = [row if row is not None else remaining.pop() for row in new_rows]
        self._write_checks = [
            check if check is not None else remaining_checks.pop() for check in new_checks
        ]

        self._push_undo(before)
        self._is_dirty = True
        self._update_status()
        self._refresh_row_indices()
        self._apply_overflow_styling()
        for i in range(len(self.rows)):
            self._sync_write_checkbox(i)
        self.sheet.refresh(redraw_header=False, redraw_row_index=True)

        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def _trim_empty_rows_from_bottom(self) -> None:
        """Remove empty rows from bottom until total <= MAX_DATAVIEW_ROWS or no more empty.

        Cardinal rule: Never delete data-containing rows.
        """
        while len(self.rows) > MAX_DATAVIEW_ROWS:
            # Find last empty row (starting from end, moving up)
            found_empty = False
            for i in range(len(self.rows) - 1, -1, -1):
                if self.rows[i].is_empty:
                    # Delete from data model only (sheet already has the row)
                    del self.rows[i]
                    del self._write_checks[i]
                    # Delete from sheet
                    self.sheet.delete_rows([i], emit_event=False)
                    found_empty = True
                    break

            if not found_empty:
                # No empty rows to remove - accept overflow
                break

    def _on_rows_added(self, event) -> None:
        """Handle row insertion events.

        Auto-padding logic:
        - If total > 100: Remove empty rows from bottom until total = 100 or no more empty
        - If still > 100: Accept overflow (grey zone expands)
        """
        if self._suppress_notifications:
            return

        # Get info about added rows from the event
        added = event.get("added", {}).get("rows", {})
        if not added:
            return
        before = self._snapshot()

        table_rows = added.get("table", {})
        if isinstance(table_rows, Mapping) and table_rows:
            inserted_rows = sorted((int(idx), row_data) for idx, row_data in table_rows.items())
        else:
            data_idx = int(added.get("data_index", 0))
            num_added = int(added.get("num", 1))
            inserted_rows = [(data_idx + i, None) for i in range(num_added)]

        # Insert new DataViewRecord objects at the row indexes reported by tksheet.
        for row_idx, row_data in inserted_rows:
            insert_idx = max(0, min(row_idx, len(self.rows)))
            row = DataViewRecord()

            address = ""
            if isinstance(row_data, (list, tuple)) and len(row_data) > COL_ADDRESS:
                address = row_data[COL_ADDRESS] or ""
            if not address:
                address = self.sheet.get_cell_data(row_idx, COL_ADDRESS) or ""

            row.address = self._display_address(address) or ""
            row.update_data_type()

            self.rows.insert(insert_idx, row)
            self._write_checks.insert(insert_idx, False)

        # Auto-pad: remove empty rows from bottom if over 100
        self._trim_empty_rows_from_bottom()
        self._push_undo(before)

        # Update display
        self._populate_sheet()
        self._is_dirty = True
        self._update_status()

        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def _pad_to_target(self) -> None:
        """Add empty rows at bottom until exactly MAX_DATAVIEW_ROWS rows exist."""
        while len(self.rows) < MAX_DATAVIEW_ROWS:
            self.rows.append(DataViewRecord())
            self._write_checks.append(False)

    def _on_rows_deleted(self, event) -> None:
        """Handle row deletion events.

        Auto-padding logic:
        - If total < 100: Add empty rows at bottom until exactly 100
        """
        if self._suppress_notifications:
            return

        # Get info about deleted rows
        deleted = event.get("deleted", {}).get("rows", {})
        if not deleted:
            return
        before = self._snapshot()

        # Remove DataViewRecord objects that were deleted
        # The 'deleted' dict maps old indices to row data
        deleted_indices = sorted((int(idx) for idx in deleted.keys()), reverse=True)
        for idx in deleted_indices:
            if 0 <= idx < len(self.rows):
                del self.rows[idx]
                del self._write_checks[idx]

        # Auto-pad: add empty rows if under 100
        self._pad_to_target()
        self._push_undo(before)

        # Update display
        self._populate_sheet()
        self._is_dirty = True
        self._update_status()

        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def _validate_edit(self, event) -> str:
        """Validate and normalize cell edits.

        Args:
            event: The edit validation event from tksheet

        Returns:
            The validated/normalized value, or empty string if invalid
        """
        # Only validate Address column
        if hasattr(event, "column") and event.column == COL_ADDRESS:
            value = (event.value or "").strip()

            # Empty is valid (clearing the cell); an invalid address clears it too
            if not value:
                return ""
            return self._display_address(value) or ""

        if hasattr(event, "column") and event.column == COL_FORCE:
            row_idx = getattr(event, "row", None)
            if row_idx is None or row_idx >= len(self.rows):
                return event.value
            row = self.rows[row_idx]
            display_text = self._display_text(event.value)
            if not display_text:
                return ""
            parsed = DataViewFile.try_parse_display(display_text, row.data_type)
            if not parsed.ok:
                return self._force_display(row)
            return DataViewFile.value_to_display(parsed.value, row.data_type)

        if hasattr(event, "column") and event.column == COL_NEW_VALUE:
            row_idx = getattr(event, "row", None)
            if row_idx is None or row_idx >= len(self.rows):
                return event.value

            row = self.rows[row_idx]
            if not self._is_row_write_enabled(row):
                return self._new_value_display(row)

            display_text = self._display_text(event.value)
            ok, _error = DataViewFile.validate_row_display(row, display_text)
            if not ok:
                return self._new_value_display(row)

            parsed = DataViewFile.try_parse_display(display_text, row.data_type)
            if not parsed.ok:
                return self._new_value_display(row)
            return DataViewFile.value_to_display(parsed.value, row.data_type)

        return event.value

    def _apply_column_visibility(self) -> None:
        hidden: set[int] = set()
        if not self._modbus_columns_visible:
            hidden |= {COL_NEW_VALUE, COL_WRITE, COL_LIVE}
        if not self._force_column_visible:
            hidden.add(COL_FORCE)
        shown = set(range(NUM_COLUMNS)) - hidden
        self.sheet.show_columns(columns=iter(sorted(shown)))
        if hidden:
            self.sheet.hide_columns(columns=hidden, data_indexes=True)

    def _create_widgets(self) -> None:
        """Create all panel widgets."""
        # Table (tksheet)
        self.sheet = Sheet(
            self,
            headers=["Address", "Nickname", "Comment", "New Value", "Write", "Live", "Force"],
            show_row_index=True,
            height=400,
            width=700,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Enable standard bindings. Undo is the panel's own: tksheet's undo would
        # change the sheet without the rows behind it.
        self.sheet.enable_bindings()
        self.sheet.disable_bindings("undo")
        for sequence in ("<Control-z>", "<Control-Z>"):
            self.sheet.bind(sequence, self._on_undo_key)
        for sequence in ("<Control-y>", "<Control-Y>", "<Control-Shift-z>", "<Control-Shift-Z>"):
            self.sheet.bind(sequence, self._on_redo_key)

        # Enable row drag and drop for reordering
        self.sheet.enable_bindings("row_drag_and_drop")

        # Disable unwanted bindings (row insert/delete enabled for dynamic rows)
        self.sheet.disable_bindings(
            "column_drag_and_drop",
            "rc_select_column",
            "rc_insert_column",
            "rc_delete_column",
            "sort_cells",
            "sort_row",
            "sort_column",
            "sort_rows",
            "sort_columns",
            "find",
            "replace",
        )

        # Set column widths
        self.sheet.set_column_widths([90, 170, 220, 120, 70, 120, 90])
        self.sheet.row_index(40)  # Row index width (row numbers)

        # Read-only display columns.
        self.sheet.readonly_columns([COL_NICKNAME, COL_COMMENT, COL_LIVE])

        # Set up edit validation and bind to modification events
        self.sheet.edit_validation(self._validate_edit)
        self.sheet.bind("<<SheetModified>>", self._on_sheet_modified)

        # Handle row drag-and-drop reordering
        self.sheet.extra_bindings("end_move_rows", self._on_rows_moved)

        # Handle row insert/delete for dynamic row management
        self.sheet.extra_bindings("end_add_rows", self._on_rows_added)
        self.sheet.extra_bindings("end_delete_rows", self._on_rows_deleted)

        # Initialize with empty data
        self._populate_sheet()
        self._apply_column_visibility()

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
            self._file = DataViewFile.load(self.file_path)
        except Exception as e:
            # Stay bound to the path, but never save the empty rows over the file.
            self.load_error = str(e)
            self.status_label.config(text=f"Error loading: {e}")
            return
        self.load_error = None
        self._write_checks = [False] * len(self.rows)
        self._live_values.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._populate_sheet()
        self._mark_saved()
        self._update_status()

    # --- File Monitoring ---

    def _on_destroy(self, event) -> None:
        """Handle panel destruction."""
        # Only handle destruction of this widget, not children
        if event.widget == self:
            self.stop_file_monitoring()

    def __init__(
        self,
        parent: tk.Widget,
        file_path: Path | None = None,
        on_modified: Callable[[], None] | None = None,
        on_addresses_changed: Callable[[DataviewPanel], None] | None = None,
        nickname_lookup: Callable[[str], tuple[str, str] | None] | None = None,
        address_normalizer: Callable[[str], str | None] | None = None,
        name: str | None = None,
        on_force: Callable[[str, PlcValue | None], None] | None = None,
    ):
        """Initialize the dataview panel.

        Args:
            parent: Parent widget
            file_path: Path to the CDV file (None for new unsaved dataview)
            on_modified: Callback when data is modified
            on_addresses_changed: Callback when row addresses change
            nickname_lookup: Callback to lookup (nickname, comment) for an address
            address_normalizer: Callback to normalize address to canonical form (e.g., "x1" -> "X001")
            name: Custom name for new unsaved dataviews (used instead of "Untitled")
            on_force: Force an address to a value, or release it (None), in the simulator
        """
        super().__init__(parent)

        self.file_path = file_path
        self.on_modified = on_modified
        self.on_addresses_changed = on_addresses_changed
        self._custom_name = name
        self.nickname_lookup = nickname_lookup
        self.address_normalizer = address_normalizer
        self.on_force = on_force

        # Simulator forces by CLICK address, and which optional columns show
        self._forces: dict[str, PlcValue] = {}
        self._modbus_columns_visible = True
        self._force_column_visible = False

        # Data model: the CDV file itself (rows, header, and the original bytes
        # pyclickplc uses to write an unchanged file back byte-for-byte)
        self._file = DataViewFile()
        self._is_dirty = False
        self._saved_values = self._row_values()
        self._undo_stack: list[_UndoFrame] = []
        self._redo_stack: list[_UndoFrame] = []
        #: Why file_path could not be read; while set, Save refuses to write over it.
        self.load_error: str | None = None
        #: The file changed on disk and the user chose not to reload it.
        self._unloaded_change = False
        self._write_checks: list[bool] = [False] * len(self.rows)
        self._live_values: dict[str, PlcValue] = {}

        # Suppress notifications during programmatic updates
        self._suppress_notifications = False

        # Live value flash highlight tracking: row_idx -> after_id
        self._live_flash_pending: dict[int, str] = {}

        # File monitoring state: (mtime, size) of the file as last loaded or saved
        self._file_stamp: tuple[float, int] | None = None
        self._monitor_after_id: str | None = None
        self._monitoring_active = False
        self._reload_prompt_shown = False  # Prevent duplicate prompts

        self._create_widgets()

        # Load file if provided
        if file_path and file_path.exists():
            self._load_file()
            self.start_file_monitoring()

        # Stop monitoring when panel is destroyed
        self.bind("<Destroy>", self._on_destroy)

    def _restore(self, frame: _UndoFrame) -> None:
        """Put the rows back as a frame holds them and redraw the whole sheet from them."""
        rows, checks = frame
        self.rows = [dataclasses.replace(row) for row in rows]
        self._write_checks = list(checks)
        self._populate_sheet()
        self._is_dirty = self._row_values() != self._saved_values
        self._update_status()
        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def undo(self) -> bool:
        """Undo the last edit to the rows. Returns False when there is none."""
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())
        return True

    def redo(self) -> bool:
        """Redo the last undone edit. Returns False when there is none."""
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
        return True

    def _show_save_error(self, text: str) -> None:
        self.status_label.config(text=text)
        messagebox.showerror("Save Error", text, parent=self)

    @staticmethod
    def _stamp(path: Path) -> tuple[float, int] | None:
        """The file's (mtime, size), or None when it can't be read."""
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return stat.st_mtime, stat.st_size

    def _changed_on_disk(self) -> bool:
        """True when the file holds a change (CLICK writes .cdv files) this panel has not loaded.

        Any other mtime or size counts, not only a later one: a restored older copy is a change.
        """
        if self._unloaded_change:
            return True
        if self.file_path is None:
            return False
        stamp = self._stamp(self.file_path)
        return stamp is not None and stamp != self._file_stamp

    def _reload_file(self) -> None:
        """Reload the file from disk, as an undo step: Ctrl+Z brings the replaced rows back."""
        if not self.file_path or not self.file_path.exists():
            return

        before = self._snapshot()
        try:
            self._file = DataViewFile.load(self.file_path)
        except Exception as e:
            self.status_label.config(text=f"Error reloading: {e}")
            return
        self.load_error = None
        if [(r.address, r.data_type, r.new_value) for r in before[0]] != self._row_values():
            self._push_undo(before)
        self._write_checks = [False] * len(self.rows)
        self._live_values.clear()
        self._populate_sheet()
        self._mark_saved()
        self._update_status()

        # What was loaded, so it does not prompt again
        self._file_stamp = self._stamp(self.file_path)
        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def _confirm_overwrite(self, path: Path) -> bool:
        """Ask before saving over a change another program made; True to save."""
        # The file monitor keeps running while the dialog is up; it must not ask too.
        self._reload_prompt_shown = True
        try:
            answer = messagebox.askyesnocancel(
                "File Changed",
                f"'{path.name}' was changed by another program, such as CLICK, "
                "since ClickNick loaded it.\n\n"
                "Yes: save this dataview over it.\n"
                "No: reload it (Ctrl+Z brings your edits back).\n"
                "Cancel: do neither.",
                parent=self,
            )
        finally:
            self._reload_prompt_shown = False
        if answer is False:
            self._reload_file()
            return False
        # This change has been asked about; the monitor does not ask again. A save
        # that then fails, or Cancel, still asks before the next save.
        self._file_stamp = self._stamp(path)
        self._unloaded_change = True
        return bool(answer)

    def _save_to(self, path: Path) -> bool:
        """Write the rows to path; on failure say why and change nothing."""
        if self.load_error is not None and path == self.file_path:
            self._show_save_error(
                f"Could not read '{path.name}' when it was opened ({self.load_error}), "
                "so it is not saved over."
            )
            return False
        if path == self.file_path and self._changed_on_disk() and not self._confirm_overwrite(path):
            return False
        try:
            self._file.save(path)
        except Exception as e:
            self._show_save_error(f"Could not save '{self.name}': {e}")
            return False
        self._mark_saved()
        self._update_status()

        # What was saved, so our own save does not prompt a reload
        self._file_stamp = self._stamp(path)
        return True

    def save(self) -> bool:
        """Save data to file.

        Note: Only the first 100 rows are saved. Overflow rows are not persisted.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.file_path:
            return False
        return self._save_to(self.file_path)

    def save_as(self, new_path: Path) -> bool:
        """Save data to a new file path and bind the panel to it.

        Args:
            new_path: New file path to save to.

        Returns:
            True if saved successfully; on failure the panel keeps its old path.
        """
        if new_path == self.file_path:
            return self.save()
        if not self._save_to(new_path):
            return False
        self.file_path = new_path
        self.load_error = None
        self.stop_file_monitoring()
        self.start_file_monitoring()
        return True

    def export(self, path: Path) -> bool:
        """Export a copy to ``path`` without changing panel file binding.

        Unlike ``save_as()``, this does not change ``self.file_path``, does not
        restart monitoring, and does not clear modified state.
        """
        try:
            # A separate file object, so this panel's file stays bound to its path.
            DataViewFile(rows=self.rows, header=self._file.header).save(path)
            return True
        except Exception as e:
            self.status_label.config(text=f"Error exporting: {e}")
            return False

    def _schedule_file_check(self) -> None:
        """Schedule the next file modification check."""
        if not self._monitoring_active:
            return
        self._monitor_after_id = self.after(FILE_MONITOR_INTERVAL_MS, self._check_file_modified)

    def start_file_monitoring(self) -> None:
        """Start monitoring the CDV file for external changes."""
        if self._monitoring_active or not self.file_path:
            return

        # The file as it is now: loaded or just saved
        self._file_stamp = self._stamp(self.file_path)

        self._monitoring_active = True
        self._reload_prompt_shown = False
        self._schedule_file_check()

    def stop_file_monitoring(self) -> None:
        """Stop file monitoring."""
        self._monitoring_active = False
        if self._monitor_after_id:
            try:
                self.after_cancel(self._monitor_after_id)
            except Exception:
                pass
        self._monitor_after_id = None

    def _prompt_reload(self) -> None:
        """Prompt user to reload the file after external modification."""
        self._reload_prompt_shown = True

        message = (
            f"'{self.name}' has been modified by another program.\n\nDo you want to reload it?"
        )
        if self._is_dirty:
            message += " It replaces your unsaved edits; Ctrl+Z brings them back."
        if messagebox.askyesno("Reload", message, parent=self):
            self._reload_file()
        else:
            self._unloaded_change = True

        # Allow future prompts
        self._reload_prompt_shown = False

    def _check_file_modified(self) -> None:
        """Check if the CDV file has been modified externally."""
        if not self._monitoring_active:
            return

        try:
            if self.file_path and not self._reload_prompt_shown:
                stamp = self._stamp(self.file_path)
                if stamp is not None and stamp != self._file_stamp:
                    self._file_stamp = stamp
                    self._prompt_reload()
        except Exception:
            # File might be locked during write, skip this check
            pass

        # Schedule next check
        self._schedule_file_check()

    @property
    def is_dirty(self) -> bool:
        """Check if the dataview has unsaved changes."""
        return self._is_dirty

    @property
    def name(self) -> str:
        """Get the dataview name (filename without extension)."""
        if self.file_path:
            return self.file_path.stem
        if self._custom_name:
            return self._custom_name
        return "Untitled"

    def _find_insertion_gap(self) -> int | None:
        """Find the first index where there are 2+ consecutive empty rows.

        Returns:
            Index of first empty row in gap, or None if no gap exists.
        """
        consecutive_empty = 0
        first_empty_idx = None

        for i, row in enumerate(self.rows):
            if row.is_empty:
                if first_empty_idx is None:
                    first_empty_idx = i
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    return first_empty_idx
            else:
                consecutive_empty = 0
                first_empty_idx = None

        return None

    def _insert_address_at(self, address: str, idx: int) -> None:
        """Insert a new row with the given address at the specified index.

        This shifts existing rows down and triggers auto-padding.
        """
        # Suppress notifications to prevent event handlers from double-inserting
        self._suppress_notifications = True
        try:
            # Create new row
            new_row = DataViewRecord(address=address)
            new_row.update_data_type()

            # Insert into data model
            self.rows.insert(idx, new_row)
            self._write_checks.insert(idx, False)

            # Insert into sheet
            self.sheet.insert_rows(rows=1, idx=idx, emit_event=False)

            # Auto-pad: trim empty rows from bottom if over 100
            self._trim_empty_rows_from_bottom()

            # Update display
            self._populate_sheet()
            self._is_dirty = True
            self._update_status()

            # Refresh sheet to update internal row positions before see()
            self.sheet.refresh()

            # Force Tk to process pending events so row_positions is updated
            self.update_idletasks()

            # Scroll to and select the new row (may fail if idx shifted during trim)
            try:
                if idx < len(self.rows):
                    self.sheet.see(idx, COL_ADDRESS)
                    self.sheet.select_row(idx)
            except (IndexError, Exception):
                # Sheet internal state not yet synced - skip scroll
                pass
        finally:
            self._suppress_notifications = False

        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def _fill_row_at(self, address: str, idx: int) -> None:
        """Fill an existing empty row with the given address (no insertion)."""
        row = self.rows[idx]
        row.address = address
        row.update_data_type()

        # Update sheet
        self._update_row_display(idx)
        self._is_dirty = True
        self._update_status()

        # Scroll to and select
        self.sheet.see(idx, COL_ADDRESS)
        self.sheet.select_row(idx)

        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def _get_selected_row_index(self) -> int | None:
        """Get the index of the currently selected row, if any.

        Checks both row selection and cell selection to handle cases
        where focus might be on another widget (e.g., Navigator).
        """
        # Try row selection first
        selected_rows = list(self.sheet.get_selected_rows())
        if selected_rows:
            return selected_rows[0]

        # Fall back to cell selection
        selected_cells = list(self.sheet.get_selected_cells())
        if selected_cells:
            return selected_cells[0][0]  # (row, col) tuple

        return None

    def _place_address(self, address: str) -> None:
        """Put an address (already in CLICK's form) where the placement rules say."""
        # Get selection (checks both row and cell selection)
        selected_idx = self._get_selected_row_index()

        if selected_idx is not None:
            # If selected row is empty, fill it in place
            if selected_idx < len(self.rows) and self.rows[selected_idx].is_empty:
                self._fill_row_at(address, selected_idx)
                return
            # Otherwise insert AFTER the selected row
            self._insert_address_at(address, selected_idx + 1)
            return

        # Find first empty row followed by another empty row (gap >= 2)
        target_idx = self._find_insertion_gap()

        if target_idx is not None:
            # Insert at the gap
            self._insert_address_at(address, target_idx)
            return

        # No gap found - find first empty row to FILL (not insert)
        for i, row in enumerate(self.rows):
            if row.is_empty:
                self._fill_row_at(address, i)
                return

        # No empty rows - append at end (creates overflow)
        self._insert_address_at(address, len(self.rows))

    def add_addresses(self, addresses: Iterable[str]) -> int:
        """Add addresses in order using smart insertion placement, as one undo step.

        Placement rules, for each address:
        - If a row is selected AND empty: Fill it in place
        - If a row is selected AND has data: INSERT new row immediately AFTER
        - If no selection: Find first empty row followed by another empty (gap >= 2)
        - Fallback: Fill first existing empty row (no insertion)
        - Last resort: Append at end (creates overflow)

        Addresses are stored in CLICK's form (``x1`` -> ``X001``).

        Args:
            addresses: The addresses to add (e.g., "X001", "DS100")

        Returns:
            How many were added; text that is not a CLICK address is skipped.
        """
        normalized = [
            address
            for address in (self._display_address(text) for text in addresses)
            if address is not None
        ]
        if not normalized:
            return 0
        self._push_undo(self._snapshot())
        for address in normalized:
            self._place_address(address)
        return len(normalized)

    def add_address(self, address: str) -> bool:
        """Add one address (see add_addresses).

        Returns:
            True if the address was added, False if it is not a CLICK address.
        """
        return self.add_addresses([address]) == 1

    def clear_rows(self, row_indices: Iterable[int]) -> None:
        """Clear rows, as one undo step.

        Args:
            row_indices: Indexes of the rows to clear
        """
        indices = sorted(
            {i for i in row_indices if 0 <= i < len(self.rows) and not self.rows[i].is_empty}
        )
        if not indices:
            return
        self._push_undo(self._snapshot())
        for row_idx in indices:
            old_canonical = self._canonical_address(self.rows[row_idx].address)
            self.rows[row_idx].clear()
            self._write_checks[row_idx] = False
            if old_canonical:
                self._live_values.pop(old_canonical, None)
            self._update_row_display(row_idx)
        self._is_dirty = True
        self._update_status()

        if self.on_modified:
            self.on_modified()
        self._notify_addresses_changed()

    def get_selected_rows(self) -> list[int]:
        """Get indices of currently selected rows."""
        return list(self.sheet.get_selected_rows())

    def get_poll_addresses(self) -> list[str]:
        """Return valid unique poll addresses in table order."""
        seen: set[str] = set()
        addresses: list[str] = []
        for row in self.rows:
            canonical = self._canonical_address(row.address)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            addresses.append(canonical)
        return addresses

    def _flash_live_cell(self, row_idx: int) -> None:
        """Briefly highlight a Live cell to indicate a value change."""
        # Cancel any existing pending clear for this row
        if row_idx in self._live_flash_pending:
            try:
                self.after_cancel(self._live_flash_pending[row_idx])
            except Exception:
                pass

        self.sheet.highlight_cells(row=row_idx, column=COL_LIVE, bg=COLOR_LIVE_FLASH)

        def _clear(idx: int = row_idx) -> None:
            self._live_flash_pending.pop(idx, None)
            try:
                self.sheet.dehighlight_cells(row=idx, column=COL_LIVE)
            except Exception:
                pass

        after_id = self.after(LIVE_FLASH_DURATION_MS, _clear)
        self._live_flash_pending[row_idx] = after_id

    def update_live_values(self, values: Mapping[str, PlcValue]) -> None:
        """Update the Live column from a service callback payload."""
        normalized: dict[str, PlcValue] = {}
        for address, value in values.items():
            canonical = self._canonical_address(address)
            if canonical:
                normalized[canonical] = value
        self._live_values = normalized

        for row_idx, row in enumerate(self.rows):
            new_display = self._live_value_display(row)
            old_display = self.sheet.get_cell_data(row_idx, COL_LIVE)
            self.sheet.set_cell_data(row_idx, COL_LIVE, new_display)

            # Flash cell if value actually changed and is non-empty
            if new_display and new_display != old_display:
                self._flash_live_cell(row_idx)

    def clear_live_values(self) -> None:
        """Clear the Live column for all rows."""
        self._live_values.clear()
        # Cancel all pending flash clears
        for after_id in self._live_flash_pending.values():
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._live_flash_pending.clear()
        for row_idx in range(len(self.rows)):
            self.sheet.set_cell_data(row_idx, COL_LIVE, "")
            try:
                self.sheet.dehighlight_cells(row=row_idx, column=COL_LIVE)
            except Exception:
                pass

    def get_write_rows(self) -> list[tuple[str, PlcValue]]:
        """Return checked writable rows with values."""
        payload: list[tuple[str, PlcValue]] = []
        for row_idx, row in enumerate(self.rows):
            if not self._write_checks[row_idx]:
                continue
            if not self._is_row_write_enabled(row):
                continue
            if row.new_value is None:
                continue
            canonical = self._canonical_address(row.address)
            if not canonical:
                continue
            payload.append((canonical, row.new_value))
        return payload

    def get_write_all_rows(self) -> list[tuple[str, PlcValue]]:
        """Return all writable rows with non-empty values."""
        payload: list[tuple[str, PlcValue]] = []
        for row in self.rows:
            if not self._is_row_write_enabled(row) or row.new_value is None:
                continue
            canonical = self._canonical_address(row.address)
            if not canonical:
                continue
            payload.append((canonical, row.new_value))
        return payload

    def clear_write_checks(self) -> None:
        """Clear all Write checkbox states."""
        for row_idx in range(len(self._write_checks)):
            self._write_checks[row_idx] = False
            self._sync_write_checkbox(row_idx)

    def set_modbus_columns_visible(self, visible: bool) -> None:
        """Show or hide the Modbus-related columns (New Value, Write, Live)."""
        self._modbus_columns_visible = visible
        self._apply_column_visibility()

    def set_force_column_visible(self, visible: bool) -> None:
        """Show or hide the simulator's Force column (hidden against a real PLC)."""
        if visible == self._force_column_visible:
            return
        self._force_column_visible = visible
        self._apply_column_visibility()

    def update_forces(self, forces: Mapping[str, PlcValue]) -> None:
        """Show the simulator's current forces (empty when detached)."""
        forces = dict(forces)
        if forces == self._forces:
            return
        self._forces = forces
        for row_idx in range(len(self.rows)):
            self._sync_force_cell(row_idx)
        self.sheet.set_refresh_timer()

    def refresh_nicknames(self) -> None:
        """Redraw nicknames and comments after the address data changed."""
        for i, row in enumerate(self.rows):
            nickname, comment = self._names_for(row.address)
            self.sheet.set_cell_data(i, COL_NICKNAME, nickname)
            self.sheet.set_cell_data(i, COL_COMMENT, comment)

        self.sheet.set_refresh_timer()

    @property
    def rows(self) -> list[DataViewRecord]:
        """Rows of the open CDV file."""
        return self._file.rows

    @rows.setter
    def rows(self, rows: list[DataViewRecord]) -> None:
        self._file.rows = rows
