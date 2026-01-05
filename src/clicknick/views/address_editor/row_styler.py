"""Row styling logic for AddressPanel sheets.

Encapsulates all visual styling: validation errors, dirty tracking,
block tag colors, non-editable cells, and navigation highlights.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ...widgets.colors import get_block_color_hex
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

# Memory types that get secondary (light blue) background tint
SECONDARY_TYPES = {"TD", "CTD"}


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
            rows=self.rows,
            get_displayed_rows=lambda: self._displayed_rows,
            get_block_colors=self._get_block_colors_for_rows,
        )
        styler.apply_all_styling()  # Full refresh
        styler.update_row_styling(data_idx)  # Single row update
    """

    def __init__(
        self,
        sheet: Sheet,
        get_rows: Callable[[], list[AddressRow]],
        get_displayed_rows: Callable[[], list[int]],
        get_block_colors: Callable[[], dict[int, str]] | None = None,
    ):
        """Initialize the styler.

        Args:
            sheet: The tksheet Sheet instance
            get_rows: Callable returning the current list of AddressRow
            get_displayed_rows: Callable returning current displayed row indices
            get_block_colors: Optional callable returning row_idx -> color map
        """
        self.sheet = sheet
        self._get_rows = get_rows
        self._get_displayed_rows = get_displayed_rows
        self._get_block_colors = get_block_colors

        # Note cache to prevent redundant tksheet calls
        self._note_cache: dict[tuple[int, int], str] = {}

        # Track pending highlight clear callbacks
        self._pending_highlight_clears: dict[int, str] = {}  # data_idx -> after_id

    def _apply_row_highlights(
        self,
        data_idx: int,
        block_colors: dict[int, str] | None = None,
    ) -> None:
        """Apply highlights for a single row."""
        row = self._get_rows()[data_idx]
        block_colors = block_colors or {}

        # 1. Block color on row index
        if data_idx in block_colors:
            hex_color = get_block_color_hex(block_colors[data_idx])
            if hex_color:
                self.sheet.highlight_cells(
                    row=data_idx,
                    bg=hex_color,
                    canvas="row_index",
                )

        # 3. Secondary type tinting (light blue for TD/CTD rows)
        if row.memory_type in SECONDARY_TYPES:
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
        block_colors = self._get_block_colors() if self._get_block_colors else {}

        for data_idx in displayed:
            self._apply_row_highlights(data_idx, block_colors)

    def _compute_target_notes(self) -> dict[tuple[int, int], str]:
        """Compute what notes should exist for displayed rows."""
        target: dict[tuple[int, int], str] = {}
        displayed = self._get_displayed_rows()

        rows = self._get_rows()
        for data_idx in displayed:
            row = rows[data_idx]
            if row.has_reportable_error:
                target[(data_idx, COL_NICKNAME)] = row.validation_error
            if not row.initial_value_valid and row.initial_value != "":
                target[(data_idx, COL_INIT_VALUE)] = row.initial_value_error

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

        # Add/update notes that are in target
        for cell_key, note_text in target_notes.items():
            if self._note_cache.get(cell_key) != note_text:
                self.sheet.note(cell_key[0], cell_key[1], note=note_text)
                self._note_cache[cell_key] = note_text

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

        # Nickname note
        nick_key = (data_idx, COL_NICKNAME)
        if row.has_reportable_error:
            note = row.validation_error
            if self._note_cache.get(nick_key) != note:
                self.sheet.note(data_idx, COL_NICKNAME, note=note)
                self._note_cache[nick_key] = note
        elif nick_key in self._note_cache:
            self.sheet.note(data_idx, COL_NICKNAME, note=None)
            del self._note_cache[nick_key]

        # Init value note
        init_key = (data_idx, COL_INIT_VALUE)
        if not row.initial_value_valid and row.initial_value != "":
            note = row.initial_value_error
            if self._note_cache.get(init_key) != note:
                self.sheet.note(data_idx, COL_INIT_VALUE, note=note)
                self._note_cache[init_key] = note
        elif init_key in self._note_cache:
            self.sheet.note(data_idx, COL_INIT_VALUE, note=None)
            del self._note_cache[init_key]

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
                block_colors = self._get_block_colors() if self._get_block_colors else {}
                self._apply_row_highlights(data_idx, block_colors)
                self.sheet.set_refresh_timer()
                # Remove from pending
                if data_idx in self._pending_highlight_clears:
                    del self._pending_highlight_clears[data_idx]

            after_id = after_func(duration_ms, clear_highlight)
            self._pending_highlight_clears[data_idx] = after_id
