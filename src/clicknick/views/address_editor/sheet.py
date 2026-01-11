"""Custom Sheet subclass for Address Editor with regex find/replace."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox

from tksheet import Sheet
from tksheet.formatters import data_to_str
from tksheet.functions import bisect_in, try_binding

from .panel_constants import COL_COMMENT, COL_NICKNAME


class AddressEditorSheet(Sheet):
    """Custom Sheet subclass with additional features for Address Editor.

    Customizations:
    - Warning symbol in cell corners (for notes)
    - add_begin_right_click() for handlers that run before popup menu builds
    - Regex-enabled find and replace functionality
    """

    # Columns where find/replace is allowed (Nickname and Comment only)
    _SEARCHABLE_COLS = {COL_NICKNAME, COL_COMMENT}

    # Find window width in characters (default tksheet is 23)
    _FIND_WINDOW_CHAR_WIDTH = 36

    def _compile_pattern(self, pattern: str) -> re.Pattern | None:
        """Compile a regex pattern, returning None on error.

        Shows an error message to the user if the pattern is invalid.
        """
        if not pattern:
            return None
        try:
            return re.compile(pattern)
        except re.error as e:
            messagebox.showerror("Regex Error", f"Invalid regex pattern: {e}", parent=self)
            return None

    def _regex_find_next(
        self,
        event: tk.Misc | None = None,
        within: bool | None = None,
        find: str | None = None,
        reverse: bool = False,
    ) -> str:
        """Override find_next to preserve case (tksheet lowercases by default).

        This enables proper case-sensitive regex matching.
        """
        MT = self.MT
        if find is None:
            # Don't lowercase - preserve original case for regex
            find = MT.find_window.get()
        if find is None and not MT.find_window.open:
            MT.open_find_window(focus=False)
        if within or (MT.find_window.window and MT.find_window.window.find_in_selection):
            MT.find_see_and_set(MT.find_within(find, reverse=reverse), within=within)
        else:
            MT.find_see_and_set(MT.find_all_cells(find, reverse=reverse), within=within)
        return "break"

    def _regex_find_match(self, find_str: str, r: int, c: int) -> bool:
        """Check if cell at (r, c) matches the regex pattern find_str.

        This replaces the default find_match which uses 'in' operator.
        Falls back to substring match if regex is invalid.
        Only searches in Nickname and Comment columns.
        Handles formatters like the original tksheet implementation.
        """
        # Only search in allowed columns
        if c not in self._SEARCHABLE_COLS:
            return False

        # Get raw value from data
        try:
            value = self.MT.data[r][c]
        except Exception:
            value = ""

        # Handle formatters
        kwargs = self.MT.get_cell_kwargs(r, c, key="format")
        if kwargs:
            value = data_to_str(value, **kwargs) if kwargs["formatter"] is None else str(value)

        # Handle None/empty cases
        if value is None:
            return find_str == ""
        elif not find_str:
            return str(value) == ""

        # Regex search instead of substring
        cell_str = str(value)

        # Don't match empty cells with non-empty regex patterns (e.g., .*)
        if not cell_str and find_str:
            return False

        try:
            return bool(re.search(find_str, cell_str))
        except re.error:
            # If regex is invalid, fall back to simple substring match
            return find_str in cell_str

    def _regex_replace_next(self, event: tk.Misc | None = None) -> None:
        """Replace the next match using regex substitution.

        Supports backreferences like \\1, \\2, etc. in the replacement string.
        """
        find_window = getattr(self.MT, "find_window", None)
        if not find_window:
            return

        pattern = find_window.get()
        if not pattern:
            return

        # Compile and validate the pattern
        compiled = self._compile_pattern(pattern)
        if compiled is None:
            return

        replace_str = ""
        if hasattr(find_window, "window") and find_window.window:
            replace_str = find_window.window.get_replace()

        # Get current selection
        sel = self.MT.selected
        if not sel:
            # Check if "find in selection" is enabled but nothing is selected
            find_in_selection = False
            if hasattr(find_window, "window") and find_window.window:
                find_in_selection = getattr(find_window.window, "find_in_selection", False)

            if find_in_selection:
                messagebox.showwarning(
                    "Nothing Selected",
                    "Please select a range of cells to search within.",
                    parent=self,
                )
                return

            # No selection, find first match
            self.MT.find_next()
            return

        # Convert display indices to data indices
        datarn = self.MT.datarn(sel.row)
        datacn = self.MT.datacn(sel.column)

        # Check if current cell matches
        if not self._regex_find_match(pattern, datarn, datacn):
            # Current cell doesn't match, find next
            self.MT.find_next()
            return

        # Get current cell value
        current = str(self.MT.get_cell_data(datarn, datacn, True) or "")

        # Perform regex replacement
        try:
            new_value = compiled.sub(replace_str, current, count=1)
        except re.error as e:
            messagebox.showerror("Regex Error", f"Invalid replacement pattern: {e}", parent=self)
            return

        # Create event for validation
        event_data = self.MT.new_single_edit_event(
            sel.row,
            sel.column,
            datarn,
            datacn,
            "replace_next",
            self.MT.get_cell_data(datarn, datacn),
            new_value,
        )

        # Run validation
        value, event_data = self.MT.single_edit_run_validation(datarn, datacn, event_data)

        # Apply if validation passed
        if value is not None and (
            self.MT.set_cell_data_undo(
                r=datarn, c=datacn, datarn=datarn, datacn=datacn, value=value, redraw=False
            )
        ):
            # Trigger end edit callback with try_binding wrapper
            try_binding(self.MT.extra_end_edit_cell_func, event_data)

        # Move to next match
        if self.MT.find_window.window.find_in_selection:
            found_next = self.MT.find_see_and_set(self.MT.find_within(pattern))
        else:
            found_next = self.MT.find_see_and_set(self.MT.find_all_cells(pattern))
        if not found_next and not self.MT.find_window.window.find_in_selection:
            self.MT.deselect()

    def _regex_replace_all(self, event: tk.Misc | None = None) -> None:
        """Replace all matches using regex substitution.

        Supports backreferences in the replacement string.
        """
        find_window = getattr(self.MT, "find_window", None)
        if not find_window:
            return

        pattern = find_window.get()
        if not pattern:
            return

        # Compile and validate the pattern
        compiled = self._compile_pattern(pattern)
        if compiled is None:
            return

        replace_str = ""
        if hasattr(find_window, "window") and find_window.window:
            replace_str = find_window.window.get_replace()

        # Check if we should only search in selection
        find_in_selection = False
        if hasattr(find_window, "window") and find_window.window:
            find_in_selection = getattr(find_window.window, "find_in_selection", False)

        # Initialize event data for batch changes
        event_data = self.MT.new_event_dict("edit_table")
        event_data["selection_boxes"] = self.MT.get_boxes()

        # Get the range of cells to search
        # Selection boxes store DISPLAY indices, so we need to convert to data indices
        if find_in_selection and self.MT.selection_boxes:
            from itertools import chain

            from tksheet.functions import box_gen_coords

            # Selection box coordinates are display indices
            display_iterable = chain.from_iterable(
                box_gen_coords(
                    from_r=box.coords.from_r,
                    from_c=box.coords.from_c,
                    upto_r=box.coords.upto_r,
                    upto_c=box.coords.upto_c,
                    start_r=box.coords.from_r,
                    start_c=box.coords.from_c,
                    reverse=False,
                )
                for box in self.MT.selection_boxes.values()
            )
            # Convert display indices to data indices
            iterable = (
                (self.MT.datarn(disp_r), self.MT.datacn(disp_c))
                for disp_r, disp_c in display_iterable
            )
            # No visibility check needed - selection is already visible
            check_visibility = False
        else:
            from tksheet.functions import box_gen_coords

            total_rows = self.MT.total_data_rows(include_index=False)
            total_cols = self.MT.total_data_cols(include_header=False)
            iterable = box_gen_coords(
                from_r=0,
                from_c=0,
                upto_r=total_rows,
                upto_c=total_cols,
                start_r=0,
                start_c=0,
                reverse=False,
            )
            # Need to check visibility when iterating all data rows
            check_visibility = True

        # Iterate through cells and collect replacements
        tree = self.MT.PAR.ops.treeview
        for r, c in iterable:
            # Check visibility only when iterating all data (not selection)
            if check_visibility and not (
                (tree or self.MT.all_rows_displayed or bisect_in(self.MT.displayed_rows, r))
                and (self.MT.all_columns_displayed or bisect_in(self.MT.displayed_columns, c))
            ):
                continue

            # Check if this cell matches the pattern
            if not self._regex_find_match(pattern, r, c):
                continue

            # Get current cell value
            current = str(self.MT.get_cell_data(r, c, True) or "")

            # Perform regex replacement (count=1 to avoid double-match on patterns like .*)
            try:
                new_value = compiled.sub(replace_str, current, count=1)
            except re.error as e:
                messagebox.showerror(
                    "Regex Error", f"Invalid replacement pattern: {e}", parent=self
                )
                return

            # Skip if no change
            if new_value == current:
                continue

            # Run individual cell validation if configured
            if self.MT.edit_validation_func:
                validated = self.MT.edit_validation_func(
                    self.MT.mod_event_val(event_data, new_value, (r, c))
                )
                if validated is None:
                    continue
                new_value = validated

            # Collect this change in event_data
            event_data = self.MT.event_data_set_cell(r, c, new_value, event_data)

        # Run bulk validation
        event_data = self.MT.bulk_edit_validation(event_data)

        # Apply changes if any were made
        if event_data["cells"]["table"]:
            self.refresh()
            if self.MT.undo_enabled:
                from tksheet.functions import stored_event_dict

                self.MT.undo_stack.append(stored_event_dict(event_data))

            # Trigger callbacks with try_binding wrapper
            try_binding(self.MT.extra_end_replace_all_func, event_data, "end_edit_table")

            self.MT.sheet_modified(event_data)
            self.emit_event("<<SheetModified>>", event_data)

            replacements_made = len(event_data["cells"]["table"])
            messagebox.showinfo(
                "Replace All", f"Replaced {replacements_made} occurrence(s).", parent=self
            )
        else:
            messagebox.showinfo("Replace All", "No matches found.", parent=self)

    def _get_find_window_dimensions_coords_wider(
        self, w_width: int | None = None
    ) -> tuple[int, int, int, int]:
        """Return find window dimensions with wider width for regex patterns."""
        MT = self.MT
        if w_width is None:
            w_width = MT.winfo_width()
        # Use wider character count than default (23 -> _FIND_WINDOW_CHAR_WIDTH)
        width = min(MT.char_width_fn("X") * self._FIND_WINDOW_CHAR_WIDTH, w_width - 7)
        height = MT.min_row_height
        if MT.find_window.window and MT.find_window.window.replace_visible:
            height *= 2
        xpos = w_width * MT.find_window_left_x_pc
        xpos = min(xpos, w_width - width - 7)
        xpos = max(0, xpos)
        return width, height, MT.canvasx(xpos), MT.canvasy(7)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Override the internal main table's redraw_corner method
        self.MT.redraw_corner = self.custom_redraw_corner

        # Override find/replace methods with regex-enabled versions
        self.MT.find_next = self._regex_find_next
        self.MT.find_match = self._regex_find_match
        self.MT.replace_next = self._regex_replace_next
        self.MT.replace_all = self._regex_replace_all

        # Override find window dimensions for wider search box
        self.MT.get_find_window_dimensions_coords = self._get_find_window_dimensions_coords_wider

    def add_begin_right_click(self, callback) -> None:
        """Add a right-click handler that runs BEFORE the popup menu is built.

        Uses bindtag ordering to insert a custom tag at the start, ensuring
        the callback runs before tksheet's internal handlers build the menu.

        Args:
            callback: Function to call on right-click, receives the event.
        """
        custom_tag = f"BeginRC_{id(self)}"
        for widget in (self.MT, self.RI):
            current_tags = widget.bindtags()
            if custom_tag not in current_tags:
                widget.bindtags((custom_tag,) + current_tags)
        self.MT.bind_class(custom_tag, "<Button-3>", callback)

    def custom_redraw_corner(self, x: float, y: float, tags: str | tuple[str]) -> None:
        """Draw a warning symbol in cell corners instead of the default triangle."""
        # Position the symbol slightly offset from the top-right corner
        text_x = x - 7
        text_y = y + 7

        if self.MT.hidd_corners:
            iid = self.MT.hidd_corners.pop()
            # Update position and properties for the symbol
            self.MT.coords(iid, text_x, text_y)
            self.MT.itemconfig(
                iid, text="⚠", fill="black", font=("Arial", 10, "bold"), state="normal", tags=tags
            )
            self.MT.disp_corners.add(iid)
        else:
            # Create a new text object instead of a polygon
            iid = self.MT.create_text(
                text_x, text_y, text="⚠", fill="black", font=("Arial", 10, "bold"), tags=tags
            )
            self.MT.disp_corners.add(iid)
