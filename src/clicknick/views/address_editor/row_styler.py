"""Row styling logic for AddressPanel sheets.

Encapsulates all visual styling: validation errors, dirty tracking,
block tag colors, non-editable cells, and navigation highlights.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ...widgets.colors import get_block_color_hex
from .cell_note import CellNote
from .panel_constants import (
    COL_COMMENT,
    COL_INIT_VALUE,
    COL_NICKNAME,
    COL_RETENTIVE,
    COLOR_COMBINED_TYPE_ALT,
    COLOR_DIRTY_BG,
    COLOR_ERROR_BG,
    COLOR_HIGHLIGHT_TEMP,
    COLOR_NON_EDITABLE_BG,
    COLOR_NON_EDITABLE_FG,
)

if TYPE_CHECKING:
    from tksheet import Sheet

    from ...models.address_row import AddressRow

# Number of data columns in the sheet
NUM_COLUMNS = 5


class AddressRowStyler:
    """Encapsulates ALL styling logic for AddressPanel sheets.

    Responsible for:
    - Validation colors (red bg for errors, notes for error messages)
    - Dirty tracking colors (yellow bg per column)
    - Block tag colors (row index background from comments)
    - Non-editable styling (gray bg for SC/SD/XD/YD)
    - Temporary highlight (green flash on navigation)

    Usage:
        styler = AddressRowStyler(
            sheet=self.sheet,
            get_rows=lambda: self.rows,
            get_displayed_rows=lambda: self._displayed_rows,
        )
        styler.apply_all_styling()  # Full refresh
        styler.update_rows_styling({data_idx})  # Single row update
    """

    def __init__(
        self,
        sheet: Sheet,
        get_rows: Callable[[], list[AddressRow]],
        get_displayed_rows: Callable[[], list[int]],
    ):
        """Initialize the styler.

        Args:
            sheet: The tksheet Sheet instance
            get_rows: Callable returning the current list of AddressRow
            get_displayed_rows: Callable returning current displayed row indices
        """
        self.sheet = sheet
        self._get_rows = get_rows
        self._get_displayed_rows = get_displayed_rows

        # Note cache to prevent redundant tksheet calls
        # Maps (row, col) -> CellNote
        self._note_cache: dict[tuple[int, int], CellNote] = {}

        # Track pending highlight clear callbacks
        self._pending_highlight_clears: dict[int, str] = {}  # data_idx -> after_id

    def _apply_row_highlights(
        self,
        data_idx: int,
    ) -> None:
        """Apply highlights for a single row."""
        row = self._get_rows()[data_idx]

        # 1. Block color on row index (precomputed by BlockService)
        if row.block_color:
            hex_color = get_block_color_hex(row.block_color)
            if hex_color:
                self.sheet.highlight_cells(
                    row=data_idx,
                    bg=hex_color,
                    canvas="row_index",
                )

        # 2. Interleaved secondary type alternation (light blue for TD/CTD rows)
        # In unified view, TD and CTD get alternating color for visual distinction
        if row.is_interleaved_secondary:
            for col in range(NUM_COLUMNS):
                self.sheet.highlight_cells(
                    row=data_idx,
                    column=col,
                    bg=COLOR_COMBINED_TYPE_ALT,
                )

        # 3. Error highlighting (nickname column) - takes priority over dirty
        if row.has_reportable_error:
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_NICKNAME,
                bg=COLOR_ERROR_BG,
                fg="black",
            )
        elif row.is_nickname_dirty:
            # Dirty nickname gets light yellow background
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_NICKNAME,
                bg=COLOR_DIRTY_BG,
                fg="black",
            )

        # 4. Dirty comment gets light yellow background
        if row.is_comment_dirty:
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_COMMENT,
                bg=COLOR_DIRTY_BG,
                fg="black",
            )

        # 5. Dirty initial value gets light yellow background
        if row.is_initial_value_dirty:
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_INIT_VALUE,
                bg=COLOR_DIRTY_BG,
                fg="black",
            )

        # 6. Dirty retentive gets light yellow background
        if row.is_retentive_dirty:
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_RETENTIVE,
                bg=COLOR_DIRTY_BG,
                fg="black",
            )

        # 7. Invalid initial value gets red background
        if not row.initial_value_valid and row.initial_value != "":
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_INIT_VALUE,
                bg=COLOR_ERROR_BG,
                fg="black",
            )

        # 8. Non-editable types get gray background on init/retentive columns
        if not row.can_edit_initial_value:
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_INIT_VALUE,
                bg=COLOR_NON_EDITABLE_BG,
                fg=COLOR_NON_EDITABLE_FG,
            )
            self.sheet.highlight_cells(
                row=data_idx,
                column=COL_RETENTIVE,
                bg=COLOR_NON_EDITABLE_BG,
                fg=COLOR_NON_EDITABLE_FG,
            )

    # --- Internal Methods ---

    def _apply_highlights(self) -> None:
        """Apply all highlight_cells calls for displayed rows."""
        displayed = self._get_displayed_rows()

        for data_idx in displayed:
            self._apply_row_highlights(data_idx)

    def _compute_target_notes(self) -> dict[tuple[int, int], CellNote]:
        """Compute what notes should exist for displayed rows.

        Returns:
            Dict mapping (row, col) -> CellNote
        """
        target: dict[tuple[int, int], CellNote] = {}
        displayed = self._get_displayed_rows()

        rows = self._get_rows()
        for data_idx in displayed:
            row = rows[data_idx]

            # Nickname note (error and/or dirty)
            nick_error = row.validation_error if row.has_reportable_error else None
            nick_dirty = (
                row.original_nickname
                if row.is_nickname_dirty and row.original_nickname is not None
                else None
            )
            if nick_error or nick_dirty:
                target[(data_idx, COL_NICKNAME)] = CellNote(
                    error_note=nick_error, dirty_note=nick_dirty
                )

            # Init value note (error and/or dirty)
            init_error = (
                row.initial_value_error
                if (not row.initial_value_valid and row.initial_value != "")
                else None
            )
            init_dirty = (
                row.original_initial_value
                if (row.is_initial_value_dirty and row.original_initial_value is not None)
                else None
            )
            if init_error or init_dirty:
                target[(data_idx, COL_INIT_VALUE)] = CellNote(
                    error_note=init_error, dirty_note=init_dirty
                )

            # Comment note (dirty only)
            if row.is_comment_dirty and row.original_comment is not None:
                target[(data_idx, COL_COMMENT)] = CellNote(dirty_note=row.original_comment)

            # Retentive note (dirty only)
            if row.is_retentive_dirty and row.original_retentive is not None:
                target[(data_idx, COL_RETENTIVE)] = CellNote(dirty_note=str(row.original_retentive))

        return target

    def _update_notes(self) -> None:
        """Update all cell notes."""
        # Build target state
        target_notes = self._compute_target_notes()

        # Remove notes that are in cache but NOT in target
        for cell_key in list(self._note_cache.keys()):
            if cell_key not in target_notes:
                self.sheet.note(cell_key[0], cell_key[1], note=None)
                del self._note_cache[cell_key]
                # Also remove from sheet's cell_notes cache
                self.sheet.cell_notes.pop(cell_key, None)

        # Add/update notes that are in target
        for cell_key, cell_note in target_notes.items():
            # Compare CellNote objects (using != checks error_note and dirty_note fields)
            if self._note_cache.get(cell_key) != cell_note:
                # Convert to string for tksheet
                self.sheet.note(cell_key[0], cell_key[1], note=str(cell_note))
                # Store CellNote in both caches
                self._note_cache[cell_key] = cell_note
                self.sheet.cell_notes[cell_key] = cell_note

    # --- Public API ---

    def apply_all_styling(self) -> None:
        """Apply full styling refresh (dehighlight all, then apply).

        Call after filter changes or major data changes.
        """
        self.sheet.dehighlight_all()
        self._apply_highlights()
        self._update_notes()

    def _clear_row_highlights(self, data_idx: int) -> None:
        """Clear highlights for a single row."""
        for col in range(NUM_COLUMNS):
            self.sheet.dehighlight_cells(row=data_idx, column=col)
        self.sheet.dehighlight_cells(row=data_idx, canvas="row_index")

    def _update_row_notes(self, data_idx: int) -> None:
        """Update notes for a single row."""
        row = self._get_rows()[data_idx]

        # Helper to update a single cell note
        def update_cell(col: int, error_note: str | None, dirty_note: str | None) -> None:
            cell_key = (data_idx, col)
            if error_note or dirty_note:
                cell_note = CellNote(error_note=error_note, dirty_note=dirty_note)
                if self._note_cache.get(cell_key) != cell_note:
                    self.sheet.note(data_idx, col, note=str(cell_note))
                    self._note_cache[cell_key] = cell_note
                    self.sheet.cell_notes[cell_key] = cell_note
            elif cell_key in self._note_cache:
                self.sheet.note(data_idx, col, note=None)
                del self._note_cache[cell_key]
                self.sheet.cell_notes.pop(cell_key, None)

        # Nickname
        nick_error = row.validation_error if row.has_reportable_error else None
        nick_dirty = (
            row.original_nickname
            if (row.is_nickname_dirty and row.original_nickname is not None)
            else None
        )
        update_cell(COL_NICKNAME, nick_error, nick_dirty)

        # Init value
        init_error = (
            row.initial_value_error
            if (not row.initial_value_valid and row.initial_value != "")
            else None
        )
        init_dirty = (
            row.original_initial_value
            if (row.is_initial_value_dirty and row.original_initial_value is not None)
            else None
        )
        update_cell(COL_INIT_VALUE, init_error, init_dirty)

        # Comment
        comment_dirty = (
            row.original_comment
            if (row.is_comment_dirty and row.original_comment is not None)
            else None
        )
        update_cell(COL_COMMENT, None, comment_dirty)

        # Retentive
        retentive_dirty = (
            str(row.original_retentive)
            if (row.is_retentive_dirty and row.original_retentive is not None)
            else None
        )
        update_cell(COL_RETENTIVE, None, retentive_dirty)

    def update_rows_styling(self, data_indices: set[int]) -> None:
        """Update styling for specific rows only (incremental update).

        Much faster than apply_all_styling() for single-cell edits.

        Args:
            data_indices: Set of data row indices to update
        """
        for data_idx in data_indices:
            # Clear existing highlights for this row
            self._clear_row_highlights(data_idx)
            # Re-apply highlights
            self._apply_row_highlights(data_idx)
            # Update notes for this row
            self._update_row_notes(data_idx)

    def highlight_row_temporary(
        self,
        data_idx: int,
        duration_ms: int = 1500,
        after_func: Callable[[int, Callable], str] | None = None,
    ) -> None:
        """Temporarily highlight a row (for navigation feedback).

        Args:
            data_idx: Row index in self.rows
            duration_ms: How long to show highlight
            after_func: The widget.after() function for scheduling cleanup
        """
        # Apply highlight to all columns
        for col in range(NUM_COLUMNS):
            self.sheet.highlight_cells(
                row=data_idx,
                column=col,
                bg=COLOR_HIGHLIGHT_TEMP,
            )
        # Also highlight row index
        self.sheet.highlight_cells(
            row=data_idx,
            bg=COLOR_HIGHLIGHT_TEMP,
            canvas="row_index",
        )
        self.sheet.set_refresh_timer()

        # Schedule removal of highlight
        if after_func:

            def clear_highlight() -> None:
                self._clear_row_highlights(data_idx)
                # Re-apply normal styling
                self._apply_row_highlights(data_idx)
                self.sheet.set_refresh_timer()
                # Remove from pending
                if data_idx in self._pending_highlight_clears:
                    del self._pending_highlight_clears[data_idx]

            after_id = after_func(duration_ms, clear_highlight)
            self._pending_highlight_clears[data_idx] = after_id
