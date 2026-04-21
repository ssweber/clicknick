"""Panel widget for editing a single DataView.

Uses tksheet for table display with dynamic rows and overflow handling.
Target is 100 rows, but overflow (rows 100+) is supported with visual indication.
"""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable, Mapping
from pathlib import Path
from tkinter import messagebox, ttk

from pyclickplc.addresses import normalize_address
from pyclickplc.dataview import (
    MAX_DATAVIEW_ROWS,
    DataViewFile,
    create_empty_dataview,
    get_data_type_for_address,
)
from pyclickplc.dataview import (
    DataViewRecord as DataViewRecord,
)
from tksheet import Sheet

from .cdv_file import export_cdv, load_cdv, save_cdv

# Column indices
COL_ADDRESS = 0
COL_NICKNAME = 1
COL_COMMENT = 2
COL_NEW_VALUE = 3
COL_WRITE = 4
COL_LIVE = 5

NUM_COLUMNS = 6

PlcValue = bool | int | float | str

# Color for overflow rows (index >= 100)
COLOR_OVERFLOW_BG = "#e0e0e0"

# Highlight for live value changes
COLOR_LIVE_FLASH = "#90EE90"  # Light green
LIVE_FLASH_DURATION_MS = 1500

# File monitoring interval in milliseconds
FILE_MONITOR_INTERVAL_MS = 2000


class DataviewPanel(ttk.Frame):
    """Panel for editing a single DataView's addresses.

    Displays rows with columns:
    Address, Nickname, Comment, New Value, Write, Live.
    Target is 100 rows, but supports overflow (rows 100+) with grey background.
    Overflow rows are excluded from saves.
    Supports row reordering, insert/delete, cut/copy/paste, and address autocomplete.
    New Value data is preserved internally and shown using DataViewFile helpers.
    """

    def _canonical_address(self, address: str) -> str | None:
        """Normalize an address for poll/write payloads."""
        candidate = (address or "").strip()
        if not candidate:
            return None
        normalized = self.address_normalizer(candidate) if self.address_normalizer else None
        if not normalized:
            normalized = normalize_address(candidate)
        if not normalized:
            return None
        return normalized.upper()

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

    def _populate_sheet(self) -> None:
        """Populate sheet with current row data."""
        self._suppress_notifications = True
        try:
            data = []
            for i, row in enumerate(self.rows):
                is_enabled = self._is_row_write_enabled(row)
                checked = bool(self._write_checks[i]) if is_enabled else ""
                data.append(
                    [
                        row.address,
                        row.nickname,
                        row.comment,
                        self._new_value_display(row),
                        checked,
                        self._live_value_display(row),
                    ]
                )

            self.sheet.set_sheet_data(data, reset_col_positions=False)
            for i in range(len(self.rows)):
                self._sync_write_checkbox(i)

            # Set row index labels (1 to N)
            self._refresh_row_indices()

            # Apply overflow styling if needed
            self._apply_overflow_styling()
        finally:
            self._suppress_notifications = False

    def _update_row_display(self, row_idx: int) -> None:
        """Update display for a single row."""
        row = self.rows[row_idx]

        self.sheet.set_cell_data(row_idx, COL_ADDRESS, row.address)
        self.sheet.set_cell_data(row_idx, COL_NICKNAME, row.nickname)
        self.sheet.set_cell_data(row_idx, COL_COMMENT, row.comment)
        self.sheet.set_cell_data(row_idx, COL_NEW_VALUE, self._new_value_display(row))
        self.sheet.set_cell_data(row_idx, COL_LIVE, self._live_value_display(row))
        self._sync_write_checkbox(row_idx)

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

            elif col == COL_WRITE:
                if self._is_row_write_enabled(row):
                    self._write_checks[row_idx] = bool(new_value)
                else:
                    self._write_checks[row_idx] = False
                self._sync_write_checkbox(row_idx)

        if data_changed:
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

        data_idx = added.get("data_index", 0)
        num_added = added.get("num", 1)

        # Insert new DataViewRecord objects at the insertion point
        for i in range(num_added):
            self.rows.insert(data_idx + i, DataViewRecord())
            self._write_checks.insert(data_idx + i, False)

        # Sync data model with sheet data (for paste operations with data)
        for i in range(num_added):
            row_idx = data_idx + i
            if row_idx < len(self.rows):
                address = self.sheet.get_cell_data(row_idx, COL_ADDRESS) or ""
                if address:
                    self.rows[row_idx].address = address.strip().upper()
                    self.rows[row_idx].update_data_type()
                    if self.nickname_lookup:
                        result = self.nickname_lookup(self.rows[row_idx].address)
                        if result:
                            self.rows[row_idx].nickname, self.rows[row_idx].comment = result

        # Auto-pad: remove empty rows from bottom if over 100
        self._trim_empty_rows_from_bottom()

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

        # Remove DataViewRecord objects that were deleted
        # The 'deleted' dict maps old indices to row data
        deleted_indices = sorted((int(idx) for idx in deleted.keys()), reverse=True)
        for idx in deleted_indices:
            if 0 <= idx < len(self.rows):
                del self.rows[idx]
                del self._write_checks[idx]

        # Auto-pad: add empty rows if under 100
        self._pad_to_target()

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

            # Empty is valid (clearing the cell)
            if not value:
                return ""

            # Try to normalize via lookup (handles "x1" -> "X001", "xd0u" -> "XD0u")
            if self.address_normalizer:
                normalized = self.address_normalizer(value)
                if normalized:
                    return normalized

            # Fallback: basic validation without normalization
            normalized = value.upper()
            if get_data_type_for_address(normalized) is None:
                return ""
            return normalized

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

    def _create_widgets(self) -> None:
        """Create all panel widgets."""
        # Table (tksheet)
        self.sheet = Sheet(
            self,
            headers=["Address", "Nickname", "Comment", "New Value", "Write", "Live"],
            show_row_index=True,
            height=400,
            width=700,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Enable standard bindings
        self.sheet.enable_bindings()

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
        self.sheet.set_column_widths([90, 170, 220, 120, 70, 120])
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
            self.rows, self.has_new_values, self._header = load_cdv(self.file_path)
            self._write_checks = [False] * len(self.rows)
            self._live_values.clear()

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
        """
        super().__init__(parent)

        self.file_path = file_path
        self.on_modified = on_modified
        self.on_addresses_changed = on_addresses_changed
        self._custom_name = name
        self.nickname_lookup = nickname_lookup
        self.address_normalizer = address_normalizer

        # Data model
        self.rows: list[DataViewRecord] = create_empty_dataview()
        self.has_new_values = False
        self._header: str | None = None  # Original header from file
        self._is_dirty = False
        self._write_checks: list[bool] = [False] * len(self.rows)
        self._live_values: dict[str, PlcValue] = {}

        # Suppress notifications during programmatic updates
        self._suppress_notifications = False

        # Live value flash highlight tracking: row_idx -> after_id
        self._live_flash_pending: dict[int, str] = {}

        # File monitoring state
        self._last_mtime: float = 0.0
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

    def save(self) -> bool:
        """Save data to file.

        Note: Only the first 100 rows are saved. Overflow rows are not persisted.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.file_path:
            return False

        try:
            # Check if any rows in the saveable range have new values
            saveable_rows = self.rows[:MAX_DATAVIEW_ROWS]
            self.has_new_values = any(
                r.new_value is not None for r in saveable_rows if not r.is_empty
            )
            save_cdv(self.file_path, self.rows, self.has_new_values, self._header)
            self._is_dirty = False
            self._update_status()

            # Update mtime so we don't prompt to reload our own save
            if self.file_path.exists():
                self._last_mtime = os.path.getmtime(self.file_path)

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
        old_path = self.file_path
        self.file_path = new_path
        if self.save():
            # Restart monitoring for new file
            if old_path != new_path:
                self.stop_file_monitoring()
                self.start_file_monitoring()
            return True
        return False

    def export(self, path: Path) -> bool:
        """Export a copy to ``path`` without changing panel file binding.

        Unlike ``save_as()``, this does not change ``self.file_path``, does not
        restart monitoring, and does not clear modified state.
        """
        try:
            # Match save semantics: header reflects whether any saveable row has
            # a New Value.
            saveable_rows = self.rows[:MAX_DATAVIEW_ROWS]
            has_new_values = any(r.new_value is not None for r in saveable_rows if not r.is_empty)
            export_cdv(path, self.rows, has_new_values, self._header)
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

        # Store initial modification time
        if self.file_path.exists():
            self._last_mtime = os.path.getmtime(self.file_path)

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

    def _reload_file(self) -> None:
        """Reload the file from disk."""
        if not self.file_path or not self.file_path.exists():
            return

        try:
            self.rows, self.has_new_values, self._header = load_cdv(self.file_path)
            self._write_checks = [False] * len(self.rows)
            self._live_values.clear()

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

            # Update mtime to prevent immediate re-prompt
            self._last_mtime = os.path.getmtime(self.file_path)
        except Exception as e:
            self.status_label.config(text=f"Error reloading: {e}")

    def _prompt_reload(self) -> None:
        """Prompt user to reload the file after external modification."""
        self._reload_prompt_shown = True

        result = messagebox.askyesno(
            "Reload",
            "This file has been modified by another program.\n\nDo you want to reload it?",
            parent=self,
        )

        if result:
            self._reload_file()

        # Allow future prompts
        self._reload_prompt_shown = False

    def _check_file_modified(self) -> None:
        """Check if the CDV file has been modified externally."""
        if not self._monitoring_active:
            return

        try:
            if self.file_path and self.file_path.exists():
                current_mtime = os.path.getmtime(self.file_path)
                if current_mtime > self._last_mtime and not self._reload_prompt_shown:
                    self._last_mtime = current_mtime
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

            # Lookup nickname and comment
            if self.nickname_lookup:
                result = self.nickname_lookup(address)
                if result:
                    new_row.nickname, new_row.comment = result

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

        # Lookup nickname and comment
        if self.nickname_lookup:
            result = self.nickname_lookup(address)
            if result:
                row.nickname, row.comment = result

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

    def add_address(self, address: str) -> bool:
        """Add an address using smart insertion placement.

        Placement rules:
        - If a row is selected AND empty: Fill it in place
        - If a row is selected AND has data: INSERT new row immediately AFTER
        - If no selection: Find first empty row followed by another empty (gap >= 2)
        - Fallback: Fill first existing empty row (no insertion)
        - Last resort: Append at end (creates overflow)

        Args:
            address: The address to add (e.g., "X001", "DS100")

        Returns:
            True if address was added (always True unless address is invalid).
        """
        normalized = address.strip().upper()
        if not normalized:
            return False

        # Get selection (checks both row and cell selection)
        selected_idx = self._get_selected_row_index()

        if selected_idx is not None:
            # If selected row is empty, fill it in place
            if selected_idx < len(self.rows) and self.rows[selected_idx].is_empty:
                self._fill_row_at(normalized, selected_idx)
                return True
            # Otherwise insert AFTER the selected row
            insert_idx = selected_idx + 1
            self._insert_address_at(normalized, insert_idx)
            return True

        # Find first empty row followed by another empty row (gap >= 2)
        target_idx = self._find_insertion_gap()

        if target_idx is not None:
            # Insert at the gap
            self._insert_address_at(normalized, target_idx)
            return True

        # No gap found - find first empty row to FILL (not insert)
        for i, row in enumerate(self.rows):
            if row.is_empty:
                self._fill_row_at(normalized, i)
                return True

        # No empty rows - append at end (creates overflow)
        self._insert_address_at(normalized, len(self.rows))
        return True

    def clear_row(self, row_idx: int) -> None:
        """Clear a specific row.

        Args:
            row_idx: Index of the row to clear (0-99)
        """
        if 0 <= row_idx < len(self.rows):
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
        columns = {COL_NEW_VALUE, COL_WRITE, COL_LIVE}
        if visible:
            self.sheet.show_columns(columns=columns)
        else:
            self.sheet.hide_columns(columns=columns, data_indexes=True)

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
