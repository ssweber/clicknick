"""Custom Sheet subclass for Address Editor with regex find/replace."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox

from tksheet import Sheet

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

    def _compile_pattern(self, pattern: str) -> re.Pattern | None:
        """Compile a regex pattern, returning None on error.

        Shows an error message to the user if the pattern is invalid.
        """
        if not pattern:
            return None
        try:
            return re.compile(pattern)
        except re.error as e:
            messagebox.showerror("Regex Error", f"Invalid regex pattern: {e}")
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
        """
        if not find_str:
            return False

        # Only search in allowed columns
        if c not in self._SEARCHABLE_COLS:
            return False

        # Get the cell value using row and column indices
        cell_value = self.MT.get_cell_data(r, c)
        cell_str = str(cell_value) if cell_value is not None else ""

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
            messagebox.showerror("Regex Error", f"Invalid replacement pattern: {e}")
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
        if value is not None:
            self.MT.set_cell_data_undo(
                r=datarn, c=datacn, datarn=datarn, datacn=datacn, value=value, redraw=False
            )
            # Trigger end edit callback if exists
            if self.MT.extra_end_edit_cell_func:
                self.MT.extra_end_edit_cell_func(event_data)

        # Move to next match
        self.MT.find_next()

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
        if find_in_selection and self.MT.selection_boxes:
            from itertools import chain

            from tksheet.functions import box_gen_coords

            iterable = chain.from_iterable(
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

        # Iterate through cells and collect replacements
        for r, c in iterable:
            # Check if this cell matches the pattern
            if not self._regex_find_match(pattern, r, c):
                continue

            # Get current cell value
            current = str(self.MT.get_cell_data(r, c, True) or "")

            # Perform regex replacement
            try:
                new_value = compiled.sub(replace_str, current)
            except re.error as e:
                messagebox.showerror("Regex Error", f"Invalid replacement pattern: {e}")
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

            # Trigger callbacks
            if self.MT.extra_end_replace_all_func:
                self.MT.extra_end_replace_all_func(event_data)

            self.MT.sheet_modified(event_data)
            self.emit_event("<<SheetModified>>", event_data)

            replacements_made = len(event_data["cells"]["table"])
            messagebox.showinfo("Replace All", f"Replaced {replacements_made} occurrence(s).")
        else:
            messagebox.showinfo("Replace All", "No matches found.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Override the internal main table's redraw_corner method
        self.MT.redraw_corner = self.custom_redraw_corner

        # Override find/replace methods with regex-enabled versions
        self.MT.find_next = self._regex_find_next
        self.MT.find_match = self._regex_find_match
        self.MT.replace_next = self._regex_replace_next
        self.MT.replace_all = self._regex_replace_all

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
