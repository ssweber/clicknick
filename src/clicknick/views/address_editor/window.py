"""Main window for the Address Editor.

Tabbed editor for viewing, creating, and editing PLC address nicknames.
Each tab displays all memory types in a unified view.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ...data.shared_data import SharedAddressData

if TYPE_CHECKING:
    from ...models.address_row import AddressRow

from ...models.address_row import get_addr_key
from ...models.blocktag import (
    PAIRED_BLOCK_TYPES,
    parse_block_tag,
    strip_block_tag,
    validate_block_span,
)
from ...widgets.add_block_dialog import AddBlockDialog
from ...widgets.custom_notebook import CustomNotebook
from ...widgets.new_tab_dialog import ask_new_tab
from ..nav_window.window import NavWindow
from .jump_sidebar import COMBINED_TYPES, JumpSidebar
from .panel import AddressPanel
from .tab_state import TabState
from .view_builder import build_unified_view


class AddressEditorWindow(tk.Toplevel):
    """Main window for the Address Editor."""

    def _update_status(self) -> None:
        """Update the status bar with current state."""
        total_modified = self.shared_data.get_total_modified_count()
        total_errors = self.shared_data.get_total_error_count()

        parts = [f"Tabs: {len(self._tabs)}"]
        if total_modified > 0:
            parts.append(f"Modified: {total_modified}")
        if total_errors > 0:
            parts.append(f"Errors: {total_errors}")

        self.status_var.set(" | ".join(parts))

        # Update sidebar button indicators
        self.sidebar.update_all_indicators()

    def _refresh_navigation(self) -> None:
        """Refresh the navigation dock with current data."""
        if self._nav_window is not None:
            self._nav_window.refresh(self.shared_data.all_rows)

    def _do_revalidation(self) -> None:
        """Perform the actual revalidation (called after debounce delay)."""
        self._revalidate_timer = None

        if not self._pending_revalidate:
            return

        self._pending_revalidate = False

        # Revalidate all tab panels that weren't already validated
        for tab_id, (panel, _state) in self._tabs.items():
            if tab_id not in self._recently_validated_panels:
                panel.revalidate()

        # Clear the tracking set for next edit cycle
        self._recently_validated_panels.clear()

        self._update_status()

        # Refresh outline if visible (live update, deferred until idle)
        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self.after_idle(self._refresh_navigation)

        # NOTE: We do NOT call notify_data_changed here.
        # Other windows were already notified via _handle_nickname_changed.
        # Calling it again would trigger redundant refresh_from_external calls.

    def _schedule_revalidation(self) -> None:
        """Schedule a debounced revalidation of all panels."""
        # Cancel any existing timer
        if self._revalidate_timer is not None:
            self.after_cancel(self._revalidate_timer)

        # Schedule revalidation after 50ms idle
        self._revalidate_timer = self.after(50, self._do_revalidation)

    # --- Tab Management Methods ---

    def _get_current_panel(self) -> AddressPanel | None:
        """Get the panel in the currently selected tab.

        Returns:
            AddressPanel or None if no tabs exist.
        """
        try:
            current = self.notebook.select()
            if current and current in self._tabs:
                return self._tabs[current][0]
        except Exception:
            pass
        return None

    def _handle_nickname_changed(
        self, memory_type: str, addr_key: int, old_nick: str, new_nick: str
    ) -> None:
        """Handle nickname change from any panel.

        Updates the shared nickname registry immediately. Tab refresh and
        window notification happen via _handle_data_changed which is called
        right after this by the panel.

        Uses debouncing to batch rapid changes (like Replace All) and avoid
        expensive revalidation for each individual cell change.

        Args:
            memory_type: The memory type of the panel that triggered the change
            addr_key: The address key that changed
            old_nick: The old nickname value
            new_nick: The new nickname value
        """
        # Update shared data registry immediately (updates skeleton row + nickname index)
        self.shared_data.update_nickname(addr_key, old_nick, new_nick)

        # Track this panel as already validated (in _on_sheet_modified)
        self._recently_validated_panels.add(memory_type)

        # Schedule debounced revalidation
        self._pending_revalidate = True
        self._schedule_revalidation()

    def _handle_data_changed(self) -> None:
        """Handle any data change from any panel (comment, init value, retentive).

        With skeleton architecture, all tabs share the same row objects.
        When one tab edits a row, we need to refresh displays in other tabs
        of THIS window (not just other windows).

        Performance optimization: instead of immediately refreshing all tabs,
        mark non-visible tabs for deferred refresh. They'll refresh when selected.
        """
        # Mark all OTHER tabs for deferred refresh instead of refreshing immediately
        current_panel = self._get_current_panel()
        for _tab_id, (panel, _state) in self._tabs.items():
            if panel is not current_panel:
                # Defer refresh until tab is selected (performance optimization)
                panel.deferred_refresh = True

        self._update_status()

        # Notify other windows (pass self so they refresh too)
        self.shared_data.notify_data_changed(sender=self)

    def _get_selected_row_indices(self) -> list[int]:
        """Get selected row indices from the current panel.

        Returns:
            List of display row indices that are selected (sorted).
        """
        panel = self._get_current_panel()
        if not panel:
            return []

        sheet = panel.sheet

        # Get selected rows from tksheet (returns set of row indices)
        selected = sheet.get_selected_rows()
        if not selected:
            return []

        return sorted(selected)

    def _update_add_block_button_state(self) -> None:
        """Update the Add Block button state and text based on row selection.

        If the selected row has an opening or self-closing block tag,
        shows "Remove Block". Otherwise shows "Add Block".
        """
        selected = self._get_selected_row_indices()
        if not selected:
            self.add_block_btn.configure(state="disabled", text="+ Add Block")
            return

        panel = self._get_current_panel()
        if not panel:
            self.add_block_btn.configure(state="disabled", text="+ Add Block")
            return

        first_display_idx = selected[0]
        if first_display_idx >= len(panel._displayed_rows):
            self.add_block_btn.configure(state="disabled", text="+ Add Block")
            return

        first_row_idx = panel._displayed_rows[first_display_idx]
        first_row = panel.rows[first_row_idx]

        block_tag = parse_block_tag(first_row.comment)

        if block_tag.tag_type in ("open", "self-closing"):
            self.add_block_btn.configure(state="normal", text="- Remove Block")
        else:
            self.add_block_btn.configure(state="normal", text="+ Add Block")

    def _can_fill_down(self) -> tuple[bool, list[int], str]:
        """Check if Fill Down can be performed on current selection.

        Returns:
            Tuple of (can_fill, list of display row indices to fill, reason if can't fill).
            can_fill is True if:
            - Multiple rows are selected
            - First row has a non-empty nickname containing a number
            - All other rows have empty nicknames
        """
        import re

        selected = self._get_selected_row_indices()
        if len(selected) < 2:
            return False, [], "Select multiple rows"

        panel = self._get_current_panel()
        if not panel:
            return False, [], ""

        # Get the first row's nickname
        first_display_idx = selected[0]
        if first_display_idx >= len(panel._displayed_rows):
            return False, [], ""

        first_row_idx = panel._displayed_rows[first_display_idx]
        first_row = panel.rows[first_row_idx]
        first_nickname = first_row.nickname

        # First nickname must be non-empty
        if not first_nickname:
            return False, [], "First row must have a nickname"

        # Check if nickname contains a number (rightmost will be incremented)
        if not re.search(r"\d+", first_nickname):
            return False, [], "First nickname must contain a number"

        # Check that all other rows have empty nicknames
        rows_to_fill = []
        for display_idx in selected[1:]:
            if display_idx >= len(panel._displayed_rows):
                return False, [], ""
            row_idx = panel._displayed_rows[display_idx]
            row = panel.rows[row_idx]
            if row.nickname:  # Must be empty
                return False, [], "Other selected rows must be empty"
            rows_to_fill.append(display_idx)

        return True, rows_to_fill, ""

    def _update_fill_down_button_state(self) -> None:
        """Update the Fill Down button state."""
        can_fill, _, _ = self._can_fill_down()
        self.fill_down_btn.configure(state="normal" if can_fill else "disabled")

    def _can_clone_structure(self) -> tuple[bool, str]:
        """Check if Clone Structure can be performed on current selection.

        Returns:
            Tuple of (can_clone, reason if can't clone).
            can_clone is True if:
            - At least one row is selected
            - At least one selected row has a nickname with a number
        """
        import re

        selected = self._get_selected_row_indices()
        if not selected:
            return False, "Select rows to clone"

        panel = self._get_current_panel()
        if not panel:
            return False, ""

        # Check if at least one selected row has a nickname with a number
        has_number = False
        for display_idx in selected:
            if display_idx >= len(panel._displayed_rows):
                continue
            row_idx = panel._displayed_rows[display_idx]
            row = panel.rows[row_idx]
            if row.nickname and re.search(r"\d+", row.nickname):
                has_number = True
                break

        if not has_number:
            return False, "At least one nickname must contain a number"

        return True, ""

    def _update_clone_button_state(self) -> None:
        """Update the Clone Structure button state."""
        can_clone, _ = self._can_clone_structure()
        self.clone_btn.configure(state="normal" if can_clone else "disabled")

    def _increment_nickname_suffix(
        self, nickname: str, increment: int
    ) -> tuple[str, int | None, int | None]:
        """Increment the rightmost number in a nickname.

        E.g., "Building1_Alm1" with increment=1 -> ("Building1_Alm2", 1, 2)
              "Building1_Alm" with increment=1 -> ("Building2_Alm", 1, 2)
              "Tank_Level10" with increment=2 -> ("Tank_Level12", 10, 12)
              "NoNumber" with increment=1 -> ("NoNumber", None, None)

        Args:
            nickname: The base nickname to increment
            increment: How much to add to the number

        Returns:
            Tuple of (new_nickname, original_number, new_number).
            Numbers are None if no number was found in the nickname.
        """
        import re

        # Find all numbers in the nickname, use the rightmost one
        matches = list(re.finditer(r"\d+", nickname))
        if not matches:
            return nickname, None, None

        match = matches[-1]  # Rightmost number
        num_str = match.group()
        num = int(num_str)
        new_num = num + increment

        # Preserve leading zeros if any
        new_num_str = str(new_num).zfill(len(num_str))

        # Replace the rightmost number
        new_nickname = nickname[: match.start()] + new_num_str + nickname[match.end() :]
        return new_nickname, num, new_num

    def _on_clone_structure_clicked(self) -> None:
        """Handle Clone Structure button click."""
        from tkinter import simpledialog

        can_clone, _ = self._can_clone_structure()
        if not can_clone:
            return

        panel = self._get_current_panel()
        if not panel:
            return

        selected = self._get_selected_row_indices()
        block_size = len(selected)

        # Ask for number of clones
        num_clones = simpledialog.askinteger(
            "Clone Structure",
            f"How many clones of the {block_size}-row structure?",
            parent=self,
            minvalue=1,
            maxvalue=100,
        )

        if not num_clones:
            return

        # Get the last selected display index
        last_display_idx = selected[-1]

        # Check that destination rows exist and are empty
        dest_start = last_display_idx + 1
        dest_count = block_size * num_clones

        # Check if we have enough rows
        if dest_start + dest_count > len(panel._displayed_rows):
            messagebox.showerror(
                "Clone Error",
                f"Not enough rows below selection. Need {dest_count} empty rows, "
                f"but only {len(panel._displayed_rows) - dest_start} available.",
                parent=self,
            )
            return

        # Get memory types from selected rows to validate against
        selected_memory_types = set()
        for display_idx in selected:
            row_idx = panel._displayed_rows[display_idx]
            row = panel.rows[row_idx]
            selected_memory_types.add(row.memory_type)

        # Check that all destination rows are empty and same memory type
        for i in range(dest_count):
            dest_display_idx = dest_start + i
            row_idx = panel._displayed_rows[dest_display_idx]
            row = panel.rows[row_idx]
            if row.nickname:
                messagebox.showerror(
                    "Clone Error",
                    f"Destination row {row.display_address} is not empty. "
                    "All destination rows must be empty.",
                    parent=self,
                )
                return
            if row.memory_type not in selected_memory_types:
                messagebox.showerror(
                    "Clone Error",
                    f"Destination row {row.display_address} is a different memory type "
                    f"({row.memory_type}). Clone cannot cross memory type boundaries.",
                    parent=self,
                )
                return

        # Build the template from selected rows (all attributes)
        template = []
        for display_idx in selected:
            row_idx = panel._displayed_rows[display_idx]
            row = panel.rows[row_idx]
            template.append(
                {
                    "nickname": row.nickname,
                    "comment": row.comment,
                    "initial_value": row.initial_value,
                    "retentive": row.retentive,
                }
            )

        # Check if we should ask about incrementing initial values
        increment_initial_value = None
        for tmpl in template:
            if tmpl["nickname"] and tmpl["initial_value"]:
                _, orig_num, _ = self._increment_nickname_suffix(tmpl["nickname"], 0)
                if orig_num is not None:
                    try:
                        init_val = int(tmpl["initial_value"])
                        if init_val == orig_num:
                            # At least one initial value matches its array number - ask user
                            result = messagebox.askyesno(
                                "Increment Initial Values?",
                                f"One or more initial values match their array numbers.\n\n"
                                f"Do you want to increment them along with the nicknames?\n\n"
                                f"Example: {tmpl['nickname']} with init={init_val} → "
                                f"next clone gets init={init_val + 1}",
                                parent=self,
                            )
                            increment_initial_value = result
                            break  # Only ask once
                    except ValueError:
                        pass  # Non-integer initial value, skip

        # Perform the cloning
        for clone_num in range(1, num_clones + 1):
            for template_idx, tmpl in enumerate(template):
                dest_display_idx = dest_start + (clone_num - 1) * block_size + template_idx
                row_idx = panel._displayed_rows[dest_display_idx]
                row = panel.rows[row_idx]

                base_nickname = tmpl["nickname"]
                if not base_nickname:
                    # Empty row in template - still copy comment/initial_value/retentive
                    if tmpl["comment"]:
                        row.comment = tmpl["comment"]
                    if tmpl["initial_value"]:
                        row.initial_value = tmpl["initial_value"]
                    # Always copy retentive (it's a boolean, so check is not None)
                    row.retentive = tmpl["retentive"]
                    panel._update_row_display(row_idx)
                    continue

                # Increment the rightmost number in nickname
                new_nickname, orig_num, new_num = self._increment_nickname_suffix(
                    base_nickname, clone_num
                )

                # Update the row nickname
                old_nickname = row.nickname
                row.nickname = new_nickname

                # Copy comment
                if tmpl["comment"]:
                    row.comment = tmpl["comment"]

                # Copy/increment initial_value based on user's choice
                if tmpl["initial_value"] and orig_num is not None and increment_initial_value is True:
                    # User chose to increment - check if it matches
                    try:
                        init_val = int(tmpl["initial_value"])
                        if init_val == orig_num:
                            # Increment initial_value to match the new number
                            row.initial_value = str(new_num)
                        else:
                            row.initial_value = tmpl["initial_value"]
                    except ValueError:
                        row.initial_value = tmpl["initial_value"]
                elif tmpl["initial_value"]:
                    # Just copy as-is (user chose not to increment or no match)
                    row.initial_value = tmpl["initial_value"]

                # Always copy retentive (it's a boolean)
                row.retentive = tmpl["retentive"]

                # Update global nickname registry
                panel._all_nicknames[row.addr_key] = new_nickname

                # Update display
                panel._update_row_display(row_idx)

                # Notify parent of nickname change
                if panel.on_nickname_changed:
                    panel.on_nickname_changed(
                        panel.memory_type, row.addr_key, old_nickname, new_nickname
                    )

        # Validate all affected rows
        for clone_num in range(1, num_clones + 1):
            for template_idx in range(block_size):
                dest_display_idx = dest_start + (clone_num - 1) * block_size + template_idx
                row_idx = panel._displayed_rows[dest_display_idx]
                panel.rows[row_idx].validate(panel._all_nicknames, panel.is_duplicate_fn)

        # Refresh display
        panel._refresh_display()

        if panel.on_data_changed:
            panel.on_data_changed()

        # Update status
        self._update_status()
        self.status_var.set(f"Cloned {block_size}-row structure {num_clones} times")

    def _on_fill_down_clicked(self) -> None:
        """Handle Fill Down button click."""
        can_fill, rows_to_fill, _ = self._can_fill_down()
        if not can_fill:
            return

        panel = self._get_current_panel()
        if not panel:
            return

        selected = self._get_selected_row_indices()
        first_display_idx = selected[0]
        first_row_idx = panel._displayed_rows[first_display_idx]
        first_row = panel.rows[first_row_idx]
        base_nickname = first_row.nickname

        # Check if we should ask about incrementing initial value
        increment_initial_value = None
        if first_row.initial_value:
            # Get the number from the nickname to compare with initial value
            _, orig_num, _ = self._increment_nickname_suffix(base_nickname, 0)
            if orig_num is not None:
                try:
                    init_val = int(first_row.initial_value)
                    if init_val == orig_num:
                        # Initial value matches the array number - ask user
                        result = messagebox.askyesno(
                            "Increment Initial Value?",
                            f"The initial value ({init_val}) matches the array number.\n\n"
                            f"Do you want to increment it along with the nickname?\n\n"
                            f"Example: {base_nickname} with init={init_val} → "
                            f"next row gets init={init_val + 1}",
                            parent=self,
                        )
                        increment_initial_value = result
                except ValueError:
                    pass  # Non-integer initial value, don't ask

        # Fill each row with incremented nickname, comment, initial_value, and retentive
        for i, display_idx in enumerate(rows_to_fill, start=1):
            row_idx = panel._displayed_rows[display_idx]
            row = panel.rows[row_idx]

            new_nickname, orig_num, new_num = self._increment_nickname_suffix(base_nickname, i)

            # Update the row nickname
            old_nickname = row.nickname
            row.nickname = new_nickname

            # Copy comment from first row
            if first_row.comment:
                row.comment = first_row.comment

            # Copy/increment initial_value based on user's choice
            if first_row.initial_value and orig_num is not None and increment_initial_value is True:
                # User chose to increment - check if it matches
                try:
                    init_val = int(first_row.initial_value)
                    if init_val == orig_num:
                        row.initial_value = str(new_num)
                    else:
                        row.initial_value = first_row.initial_value
                except ValueError:
                    row.initial_value = first_row.initial_value
            elif first_row.initial_value:
                # Just copy as-is (user chose not to increment or no match)
                row.initial_value = first_row.initial_value

            # Always copy retentive (it's a boolean)
            row.retentive = first_row.retentive

            # Update global nickname registry
            if new_nickname:
                panel._all_nicknames[row.addr_key] = new_nickname

            # Update display
            panel._update_row_display(row_idx)

            # Notify parent of nickname change
            if panel.on_nickname_changed:
                panel.on_nickname_changed(
                    panel.memory_type, row.addr_key, old_nickname, new_nickname
                )

        # Validate affected rows
        if panel.on_validate_affected:
            panel.on_validate_affected("", base_nickname)

        # Validate all filled rows
        for display_idx in rows_to_fill:
            row_idx = panel._displayed_rows[display_idx]
            panel.rows[row_idx].validate(panel._all_nicknames, panel.is_duplicate_fn)

        # Refresh display
        panel._refresh_display()

        if panel.on_data_changed:
            panel.on_data_changed()

        # Update button states
        self._update_fill_down_button_state()
        self._update_status()

    def _update_button_states(self, event=None) -> None:
        """Update all footer button states based on current selection."""
        self._update_add_block_button_state()
        self._update_fill_down_button_state()
        self._update_clone_button_state()

    def _bind_panel_selection(self, panel: AddressPanel) -> None:
        """Bind selection change events on a panel's sheet.

        Args:
            panel: The AddressPanel to bind events on
        """
        # Bind to selection events to update button states
        panel.sheet.bind("<<SheetSelect>>", self._update_button_states)

    def _on_type_selected(self, type_name: str) -> None:
        """Handle type button click - scroll to section in current tab."""
        # Scroll current panel to the selected memory type section
        panel = self._get_current_panel()
        if panel and panel.is_unified:
            panel.scroll_to_section(type_name)

    def _on_address_jump(self, type_name: str, address: int) -> None:
        """Handle address jump from submenu."""
        panel = self._get_current_panel()
        if panel and panel.is_unified:
            # For combined types (T/TD, CT/CTD), use the first sub-type
            if type_name in COMBINED_TYPES:
                mem_type = COMBINED_TYPES[type_name][0]
            else:
                mem_type = type_name
            panel.scroll_to_address(address, mem_type)

    def _has_unsaved_changes(self) -> bool:
        """Check if any panel has unsaved changes."""
        return self.shared_data.has_unsaved_changes()

    def _save_all(self) -> None:
        """Save all changes to database."""
        # Check for validation errors (across all shared data)
        if self.shared_data.has_errors():
            messagebox.showerror(
                "Validation Errors",
                "Cannot save: there are validation errors. Please fix them first.",
                parent=self,
            )
            return

        if not self.shared_data.has_unsaved_changes():
            messagebox.showinfo("Save", "No changes to save.", parent=self)
            return

        try:
            count = self.shared_data.save_all_changes()

            # Refresh all tab panels
            for _tab_id, (panel, _state) in self._tabs.items():
                panel._refresh_display()

            self.status_var.set(f"Saved {count} changes")
            messagebox.showinfo("Save", f"Successfully saved {count} changes.", parent=self)

        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)

    def _refresh_all(self) -> None:
        """Refresh all tab panels by discarding changes.

        With skeleton architecture, discard_all_changes() resets skeleton rows
        in-place and notifies all observers. Panels refresh automatically via
        _on_shared_data_changed().
        """
        if self.shared_data.has_unsaved_changes():
            result = messagebox.askyesno(
                "Unsaved Changes",
                "You have unsaved changes. Refresh will discard them. Continue?",
                parent=self,
            )
            if not result:
                return

        try:
            # Discard shared data - resets skeleton rows and notifies all windows
            # _on_shared_data_changed() will refresh all panels automatically
            self.shared_data.discard_all_changes()
            self.status_var.set(
                f"Refreshed - {len(self.shared_data.all_nicknames)} nicknames loaded"
            )

        except Exception as e:
            messagebox.showerror("Refresh Error", str(e), parent=self)

    def _discard_changes(self) -> None:
        """Discard all unsaved changes by resetting to original values."""
        if not self.shared_data.has_unsaved_changes():
            messagebox.showinfo("Discard", "No changes to discard.", parent=self)
            return

        result = messagebox.askyesno(
            "Discard Changes",
            "Are you sure you want to discard all unsaved changes?",
            parent=self,
        )
        if not result:
            return

        try:
            # Discard shared data - resets rows in-place and notifies all windows
            # The notification triggers _on_shared_data_changed which refreshes panels
            self.shared_data.discard_all_changes()

            # Update local nicknames reference
            self.all_nicknames = self.shared_data.all_nicknames

            self._update_status()
            self.status_var.set("Changes discarded")

        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _create_tooltip(self, widget: tk.Widget, text: str) -> None:
        """Create a simple tooltip for a widget.

        Args:
            widget: The widget to attach the tooltip to
            text: The tooltip text
        """
        tooltip = None

        def show_tooltip(event):
            nonlocal tooltip
            # Only show when disabled
            if str(widget.cget("state")) == "disabled":
                x = widget.winfo_rootx() + 20
                y = widget.winfo_rooty() + widget.winfo_height() + 5
                tooltip = tk.Toplevel(widget)
                tooltip.wm_overrideredirect(True)
                tooltip.wm_geometry(f"+{x}+{y}")
                label = ttk.Label(
                    tooltip,
                    text=text,
                    background="#ffffe0",
                    relief="solid",
                    borderwidth=1,
                )
                label.pack()

        def hide_tooltip(event):
            nonlocal tooltip
            if tooltip:
                tooltip.destroy()
                tooltip = None

        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def _find_paired_row_idx(
        self, panel: AddressPanel, row: AddressRow, row_idx: int
    ) -> int | None:
        """Find the index of the paired row for interleaved types (T+TD, CT+CTD).

        For interleaved types, rows at the same address should share block tags.
        This finds the partner row (e.g., TD1 for T1, or T1 for TD1).

        Args:
            panel: The panel containing the rows
            row: The row to find a pair for
            row_idx: Index of the row in panel.rows

        Returns:
            Index of the paired row, or None if no pair exists
        """
        # Check if this is a paired type
        paired_type = None
        for pair in PAIRED_BLOCK_TYPES:
            if row.memory_type in pair:
                # Find the other type in the pair
                for t in pair:
                    if t != row.memory_type:
                        paired_type = t
                        break
                break

        if not paired_type:
            return None

        # Search nearby for the paired row (interleaved, so should be adjacent)
        # Check the row before and after
        for offset in [-1, 1]:
            check_idx = row_idx + offset
            if 0 <= check_idx < len(panel.rows):
                check_row = panel.rows[check_idx]
                if check_row.memory_type == paired_type and check_row.address == row.address:
                    return check_idx

        return None

    def _add_tag_to_row(self, row: AddressRow, tag: str) -> None:
        """Add a block tag to a row's comment.

        Args:
            row: The row to modify
            tag: The tag to add
        """
        if row.comment:
            row.comment = f"{row.comment} {tag}"
        else:
            row.comment = tag

    def _on_add_block_clicked(self) -> None:
        """Handle Add Block button click."""
        selected_display_rows = self._get_selected_row_indices()
        if not selected_display_rows:
            return

        panel = self._get_current_panel()
        if not panel:
            return

        # Get the actual rows for validation
        selected_rows = []
        for display_idx in selected_display_rows:
            if display_idx < len(panel._displayed_rows):
                row_idx = panel._displayed_rows[display_idx]
                selected_rows.append(panel.rows[row_idx])

        # Validate that block doesn't span multiple memory types
        is_valid, error_msg = validate_block_span(selected_rows)
        if not is_valid:
            messagebox.showerror(
                "Invalid Block Selection",
                error_msg,
                parent=self,
            )
            return

        # Show the Add Block dialog
        dialog = AddBlockDialog(self)
        self.wait_window(dialog)

        if dialog.result is None:
            return

        block_name, color = dialog.result

        # Map display rows to actual rows
        first_display_idx = selected_display_rows[0]
        last_display_idx = selected_display_rows[-1]

        if first_display_idx >= len(panel._displayed_rows):
            return
        if last_display_idx >= len(panel._displayed_rows):
            return

        first_row_idx = panel._displayed_rows[first_display_idx]
        last_row_idx = panel._displayed_rows[last_display_idx]

        first_row = panel.rows[first_row_idx]
        last_row = panel.rows[last_row_idx]

        # Format tags with optional bg attribute
        if color:
            bg_attr = f' bg="{color}"'
        else:
            bg_attr = ""

        # Track all rows that need display updates
        rows_to_update = set()

        if first_row_idx == last_row_idx:
            # Single row - self-closing tag
            tag = f"<{block_name}{bg_attr} />"
            self._add_tag_to_row(first_row, tag)
            rows_to_update.add(first_row_idx)

            # Also add to paired row if interleaved type
            paired_idx = self._find_paired_row_idx(panel, first_row, first_row_idx)
            if paired_idx is not None:
                self._add_tag_to_row(panel.rows[paired_idx], tag)
                rows_to_update.add(paired_idx)
        else:
            # Range - opening and closing tags
            open_tag = f"<{block_name}{bg_attr}>"
            close_tag = f"</{block_name}>"

            # Add opening tag to first row
            self._add_tag_to_row(first_row, open_tag)
            rows_to_update.add(first_row_idx)

            # Also add opening tag to paired row at start address
            first_paired_idx = self._find_paired_row_idx(panel, first_row, first_row_idx)
            if first_paired_idx is not None:
                self._add_tag_to_row(panel.rows[first_paired_idx], open_tag)
                rows_to_update.add(first_paired_idx)

            # Add closing tag to last row
            self._add_tag_to_row(last_row, close_tag)
            rows_to_update.add(last_row_idx)

            # Also add closing tag to paired row at end address
            last_paired_idx = self._find_paired_row_idx(panel, last_row, last_row_idx)
            if last_paired_idx is not None:
                self._add_tag_to_row(panel.rows[last_paired_idx], close_tag)
                rows_to_update.add(last_paired_idx)

        # Update the sheet's cell data for all modified rows
        for row_idx in rows_to_update:
            panel._update_row_display(row_idx)

        # Invalidate block colors cache and refresh styling
        panel._invalidate_block_colors_cache()
        panel._refresh_display()

        # Notify data changed
        if panel.on_data_changed:
            panel.on_data_changed()

        # Update status
        self._update_status()

    def _on_remove_block_clicked(self) -> None:
        """Handle Remove Block button click.

        Removes the block tag from the selected row's comment.
        If it's an opening tag, also removes the corresponding closing tag.
        For interleaved types (T+TD, CT+CTD), also removes from paired rows.
        """
        selected_display_rows = self._get_selected_row_indices()
        if not selected_display_rows:
            return

        panel = self._get_current_panel()
        if not panel:
            return

        first_display_idx = selected_display_rows[0]
        if first_display_idx >= len(panel._displayed_rows):
            return

        first_row_idx = panel._displayed_rows[first_display_idx]
        first_row = panel.rows[first_row_idx]

        block_tag = parse_block_tag(first_row.comment)

        if block_tag.tag_type not in ("open", "self-closing"):
            return

        block_name = block_tag.name

        # Track all rows that need display updates
        rows_to_update = set()

        # Remove the tag from the first row, keep remaining text
        first_row.comment = strip_block_tag(first_row.comment)
        rows_to_update.add(first_row_idx)

        # Also remove from paired row at start address
        first_paired_idx = self._find_paired_row_idx(panel, first_row, first_row_idx)
        if first_paired_idx is not None:
            paired_row = panel.rows[first_paired_idx]
            paired_tag = parse_block_tag(paired_row.comment)
            if paired_tag.name == block_name:
                paired_row.comment = strip_block_tag(paired_row.comment)
                rows_to_update.add(first_paired_idx)

        # If it's an opening tag, find and remove the closing tag
        if block_tag.tag_type == "open" and block_name:
            # Search forward through rows for the matching closing tag
            for search_idx in range(first_row_idx + 1, len(panel.rows)):
                search_row = panel.rows[search_idx]
                search_tag = parse_block_tag(search_row.comment)

                if search_tag.tag_type == "close" and search_tag.name == block_name:
                    # Found the matching closing tag - remove it
                    search_row.comment = strip_block_tag(search_row.comment)
                    rows_to_update.add(search_idx)

                    # Also remove from paired row at end address
                    end_paired_idx = self._find_paired_row_idx(panel, search_row, search_idx)
                    if end_paired_idx is not None:
                        end_paired_row = panel.rows[end_paired_idx]
                        end_paired_tag = parse_block_tag(end_paired_row.comment)
                        if end_paired_tag.name == block_name:
                            end_paired_row.comment = strip_block_tag(end_paired_row.comment)
                            rows_to_update.add(end_paired_idx)
                    break

        # Update the sheet's cell data for all modified rows
        for row_idx in rows_to_update:
            panel._update_row_display(row_idx)

        # Invalidate block colors cache and refresh styling
        panel._invalidate_block_colors_cache()
        panel._refresh_display()

        # Notify data changed
        if panel.on_data_changed:
            panel.on_data_changed()

        # Update button state (will switch back to "Add Block")
        self._update_add_block_button_state()

        # Update status
        self._update_status()

    def _on_block_button_clicked(self) -> None:
        """Handle block button click - routes to add or remove based on state."""
        button_text = str(self.add_block_btn.cget("text"))
        if "Remove" in button_text:
            self._on_remove_block_clicked()
        else:
            self._on_add_block_clicked()

    def _on_outline_select(self, path: str, leaves: list[tuple[str, int]]) -> None:
        """Handle selection from outline tree.

        For single leaf nodes (exact nickname match): scrolls to address.
        For folder nodes (multiple children): filters by path prefix using ^ anchor.

        Args:
            path: Filter prefix for folders or exact nickname for leaves
            leaves: List of (memory_type, address) tuples for all addresses under this node
        """
        if not leaves:
            return

        panel = self._get_current_panel()
        if not panel or not panel.is_unified:
            return

        # Check if this is a single leaf (exact nickname match)
        if len(leaves) == 1:
            memory_type, address = leaves[0]
            addr_key = get_addr_key(memory_type, address)
            nickname = self.all_nicknames.get(addr_key, "")
            # If path matches the nickname exactly, just scroll (don't filter)
            if path == nickname:
                panel.scroll_to_address(address, memory_type)
                panel.sheet.focus_set()
                return

        # Folder node - clear row filters and apply prefix filter
        panel.row_filter_var.set("all")

        # Enable text filter and set prefix pattern with ^ anchor
        panel.filter_enabled_var.set(True)
        if path:
            panel.filter_var.set(f"^{path}")
        panel._apply_filters()

        memory_type, address = leaves[0]
        panel.scroll_to_address(address, memory_type)

        # Focus the sheet for immediate keyboard navigation/editing
        panel.sheet.focus_set()

    def _on_block_select(self, leaves: list[tuple[str, int]]) -> None:
        """Handle selection from block panel.

        Always jumps to the first address in the block (no filtering).

        Args:
            leaves: List of (memory_type, address) tuples for all addresses in the block
        """
        if not leaves:
            return

        panel = self._get_current_panel()
        if not panel or not panel.is_unified:
            return

        # Jump to first address in the block
        memory_type, address = leaves[0]
        panel.scroll_to_address(address, memory_type)

        # Focus the sheet for immediate keyboard navigation/editing
        panel.sheet.focus_set()

    def _toggle_nav(self) -> None:
        """Toggle the outline window visibility."""
        if self._nav_window is None:
            # Create outline window
            self._nav_window = NavWindow(
                self,
                on_outline_select=self._on_outline_select,
                on_block_select=self._on_block_select,
            )
            self._refresh_navigation()
            self._tag_browser_var.set(True)
        elif self._nav_window.winfo_viewable():
            # Hide it
            self._nav_window.withdraw()
            self._tag_browser_var.set(False)
        else:
            # Show it
            self._refresh_navigation()
            self._nav_window.deiconify()
            self._nav_window._dock_to_parent()
            self._tag_browser_var.set(True)

    def _get_current_state(self) -> TabState | None:
        """Get the state of the currently selected tab.

        Returns:
            TabState or None if no tabs exist.
        """
        try:
            current = self.notebook.select()
            if current and current in self._tabs:
                return self._tabs[current][1]
        except Exception:
            pass
        return None

    def _apply_state_to_panel(self, panel: AddressPanel, state: TabState) -> None:
        """Apply a TabState to a panel's UI controls.

        Args:
            panel: The panel to configure
            state: The state to apply
        """
        # Apply filter settings
        panel.filter_enabled_var.set(state.filter_enabled)
        panel.filter_var.set(state.filter_text)
        panel.row_filter_var.set(state.row_filter)

        # Apply column visibility
        panel.hide_used_var.set(state.hide_used_column)
        panel.hide_init_ret_var.set(state.hide_init_ret_columns)
        panel._toggle_used_column()
        panel._toggle_init_ret_columns()

        # Apply filters
        panel._apply_filters()

        # Scroll to saved position if any
        if state.scroll_row_index > 0:
            panel._scroll_to_row(min(state.scroll_row_index, len(panel._displayed_rows) - 1))

    def _create_new_tab(self, clone_from: TabState | None) -> bool:
        """Create a new tab with a unified panel.

        Args:
            clone_from: TabState to clone, or None for fresh start.

        Returns:
            True if tab was created successfully.
        """
        try:
            # Generate tab name
            self._tab_counter += 1
            tab_name = f"Tab {self._tab_counter}"

            # Create state (clone or fresh)
            if clone_from is not None:
                state = clone_from.clone()
                state.name = tab_name
            else:
                state = TabState.fresh()
                state.name = tab_name

            # Get or build unified view
            unified_view = self.shared_data.get_unified_view()
            if unified_view is None:
                unified_view = build_unified_view(
                    self.shared_data.all_rows,
                    self.all_nicknames,
                )
                self.shared_data.set_unified_view(unified_view)

            # Create unified panel
            panel = AddressPanel(
                self.notebook,
                memory_type="unified",  # Special type for unified view
                combined_types=None,
                on_nickname_changed=self._handle_nickname_changed,
                on_data_changed=self._handle_data_changed,
                on_validate_affected=self.shared_data.validate_affected_rows,
                is_duplicate_fn=self.shared_data.is_duplicate_nickname,
                is_unified=True,
                section_boundaries=unified_view.section_boundaries,
            )

            # Initialize panel with unified view data
            panel.initialize_from_view(unified_view.rows, self.all_nicknames)

            # Store rows in shared_data for compatibility
            self.shared_data.set_rows("unified", unified_view.rows)

            # Add to notebook
            self.notebook.add(panel, text=tab_name)

            # Track the tab
            tab_id = str(panel)
            self._tabs[tab_id] = (panel, state)

            # Select the new tab
            self.notebook.select(panel)

            # Apply state to panel (filters, column visibility)
            self._apply_state_to_panel(panel, state)

            # Bind selection events for Add Block button
            self._bind_panel_selection(panel)

            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to create tab: {e}", parent=self)
            import traceback

            traceback.print_exc()
            return False

    def _on_tab_close_request(self, tab_index: int) -> bool:
        """Handle tab close request.

        Args:
            tab_index: Index of tab being closed.

        Returns:
            True to allow close, False to prevent.
        """
        # Don't allow closing the last tab
        if self.notebook.index("end") <= 1:
            return False

        # Get the tab widget name
        tab_id = self.notebook.tabs()[tab_index]

        # Remove from tracking
        if tab_id in self._tabs:
            del self._tabs[tab_id]

        return True

    def _close_current_tab(self) -> None:
        """Close the currently selected tab (via keyboard shortcut)."""
        # Don't allow closing the last tab
        if self.notebook.index("end") <= 1:
            return

        try:
            current = self.notebook.select()
            if current:
                # Get the tab index
                tab_index = self.notebook.index(current)

                # Remove from tracking
                if current in self._tabs:
                    del self._tabs[current]

                # Remove the tab
                self.notebook.forget(tab_index)

                # Update status
                self._update_status()
        except Exception:
            pass

    def _on_tab_changed(self, event=None) -> None:
        """Handle tab selection change."""
        # Update Add Block button state for new tab
        self._update_add_block_button_state()
        self._update_status()

        # Sync menu filter enabled state with current panel
        panel = self._get_current_panel()
        if panel:
            self._filter_enabled_var.set(panel.filter_enabled_var.get())

            # Execute deferred refresh if needed (performance optimization)
            if panel.deferred_refresh:
                panel.refresh_from_external(skip_validation=True)
                panel.deferred_refresh = False
    def _save_state_from_panel(self, panel: AddressPanel, state: TabState) -> None:
        """Save the current panel state to a TabState.

        Args:
            panel: The panel to read from
            state: The state to update
        """
        state.filter_enabled = panel.filter_enabled_var.get()
        state.filter_text = panel.filter_var.get()
        state.row_filter = panel.row_filter_var.get()
        state.hide_used_column = panel.hide_used_var.get()
        state.hide_init_ret_columns = panel.hide_init_ret_var.get()

        # Save scroll position
        try:
            start_row, _end_row = panel.sheet.visible_rows
            state.scroll_row_index = start_row
        except Exception:
            state.scroll_row_index = 0

    def _on_new_tab_clicked(self) -> None:
        """Handle New Tab button click."""
        # Get current panel and state for potential cloning
        current_panel = self._get_current_panel()
        current_state = self._get_current_state()

        # Save current panel state BEFORE asking user (so clone has current values)
        if current_panel and current_state:
            self._save_state_from_panel(current_panel, current_state)

        # Ask user how to create the tab
        result = ask_new_tab(self)

        if result is None:
            # User cancelled
            return
        elif result:
            # Clone current tab
            self._create_new_tab(clone_from=current_state)
        else:
            # Start fresh
            self._create_new_tab(clone_from=None)

    def _on_filter_toggle(self, event=None) -> None:
        """Toggle filter enabled state for current panel."""
        panel = self._get_current_panel()
        if panel:
            panel.toggle_filter_enabled(self._filter_enabled_var.get())

    def _on_shared_data_changed(self, sender: object = None) -> None:
        """Handle notification that shared data has changed.

        With skeleton architecture, all panels share the same AddressRow objects.
        When skeleton rows are updated in-place, we just refresh displays.
        No need to rebuild views since row object identity never changes.

        Args:
            sender: The object that triggered the change (if any)
        """
        # Skip if this notification was triggered by our own change
        if sender is self:
            return

        # Update local reference to nicknames
        self.all_nicknames = self.shared_data.all_nicknames

        # Update all tab panels - skeleton rows are already updated in-place
        for _tab_id, (panel, _state) in self._tabs.items():
            panel._all_nicknames = self.all_nicknames
            # Simple refresh - skeleton rows are shared, just sync display
            # If sender is another window, skip validation (they already did it)
            # If sender is None (external MDB change), we need to validate
            skip_validation = sender is not None
            panel.refresh_from_external(skip_validation=skip_validation)

        # Refresh outline if visible (deferred until idle)
        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self.after_idle(self._refresh_navigation)

        self._update_status()

    def _on_closing(self) -> None:
        """Handle window close - prompt to save if needed."""
        if self._has_unsaved_changes():
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=self,
            )
            if result is None:  # Cancel
                return
            if result:  # Yes - save
                self._save_all()
                # Check if save was successful (no more dirty rows)
                if self._has_unsaved_changes():
                    return  # Save failed, don't close

        # Close outline window if open
        if self._nav_window is not None:
            self._nav_window.destroy()
            self._nav_window = None

        # Unregister from shared data
        self.shared_data.remove_observer(self._on_shared_data_changed)
        self.shared_data.unregister_window(self)

        self.destroy()

    def _create_menu(self) -> None:
        """Create the menu bar."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)

        file_menu.add_command(
            label="New Tab", command=self._on_new_tab_clicked, accelerator="Ctrl+T"
        )
        file_menu.add_separator()
        file_menu.add_command(label="Refresh", command=self._refresh_all)
        file_menu.add_command(label="Save All", command=self._save_all, accelerator="Ctrl+S")
        file_menu.add_command(label="Discard Changes", command=self._discard_changes)
        file_menu.add_separator()
        file_menu.add_command(
            label="Close Tab", command=self._close_current_tab, accelerator="Ctrl+W"
        )
        file_menu.add_separator()
        file_menu.add_command(label="Close Window", command=self._on_closing)

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        edit_menu.add_command(label="Fill Down", command=self._on_fill_down_clicked)
        edit_menu.add_command(label="Clone Structure...", command=self._on_clone_structure_clicked)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)

        # Filter enabled toggle (checkbutton)
        self._filter_enabled_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(
            label="Filter Enabled",
            variable=self._filter_enabled_var,
            command=self._on_filter_toggle,
            accelerator="Ctrl+Space",
        )
        view_menu.add_separator()

        # Tag Browser toggle (checkbutton)
        self._tag_browser_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(
            label="Tag Browser",
            variable=self._tag_browser_var,
            command=self._toggle_nav,
        )

    def _on_filter_toggle_key(self, event=None) -> str:
        """Handle Ctrl+Space keyboard shortcut to toggle filter."""
        # Toggle the variable (menu checkbutton will update automatically)
        self._filter_enabled_var.set(not self._filter_enabled_var.get())
        self._on_filter_toggle()
        return "break"  # Prevent event propagation

    def _create_widgets(self) -> None:
        """Create all window widgets."""
        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Status bar at very bottom
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Sidebar on left - buttons now scroll to sections instead of switching panels
        self.sidebar = JumpSidebar(
            main_frame,
            on_type_select=self._on_type_selected,
            on_address_jump=self._on_address_jump,
            shared_data=self.shared_data,
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0), pady=5)

        # Center container (full remaining space - outline is external)
        center_frame = ttk.Frame(main_frame)
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tabbed notebook for address panels (each tab shows ALL memory types)
        self.notebook = CustomNotebook(
            center_frame,
            on_close_callback=self._on_tab_close_request,
        )
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Bind tab change event
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Footer toolbar at bottom of center
        footer = ttk.Frame(center_frame)
        footer.pack(fill=tk.X, pady=(5, 0))

        # Add Block button
        self.add_block_btn = ttk.Button(
            footer,
            text="+ Add Block",
            command=self._on_block_button_clicked,
            state="disabled",
        )
        self.add_block_btn.pack(side=tk.LEFT)
        # Create tooltip for the button
        self._create_tooltip(self.add_block_btn, "Select rows to define block")

        # Fill Down button
        self.fill_down_btn = ttk.Button(
            footer,
            text="↓ Fill Down",
            command=self._on_fill_down_clicked,
            state="disabled",
        )
        self.fill_down_btn.pack(side=tk.LEFT, padx=(5, 0))
        # Create tooltip for the button
        self._create_tooltip(
            self.fill_down_btn,
            "Fill empty rows with incrementing nicknames (e.g., Alm1 → Alm2, Alm3...)",
        )

        # Clone Structure button
        self.clone_btn = ttk.Button(
            footer,
            text="⧉ Clone",
            command=self._on_clone_structure_clicked,
            state="disabled",
        )
        self.clone_btn.pack(side=tk.LEFT, padx=(5, 0))
        # Create tooltip for the button
        self._create_tooltip(
            self.clone_btn,
            "Clone selected row pattern into empty rows below",
        )

        # Save button (right side)
        ttk.Button(footer, text="💾 Save All", command=self._save_all).pack(side=tk.RIGHT)

    def _load_initial_data(self) -> None:
        """Load initial data from the database."""
        try:
            # Load initial data if not already loaded
            if not self.shared_data.is_initialized():
                self.shared_data.load_initial_data()

            # Start file monitoring (uses master window for after() calls)
            self.shared_data.start_file_monitoring(self.master)

            # Get reference to shared nicknames
            self.all_nicknames = self.shared_data.all_nicknames

            self.status_var.set(f"Connected - {len(self.all_nicknames)} nicknames loaded")

            # Create first tab with fresh state
            self._create_new_tab(clone_from=None)

        except Exception as e:
            messagebox.showerror("Database Error", str(e))
            self.destroy()

    @staticmethod
    def _get_address_editor_popup_flag() -> Path:
        """Get path to the flag indicating the Address Editor popup has been seen."""
        import os

        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "ClickNick" / "address_editor_popup_seen"

    def _show_address_editor_popup(self) -> None:
        """Show first-run tips for the Address Editor (appears once per user)."""
        flag_path = self._get_address_editor_popup_flag()

        if flag_path.exists():
            return

        # Content
        popup_text = (
            "Address Editor (Beta)\n\n"
            "This tool edits address information in CLICK's temporary database.\n"
            "Changes are temporary until you save in CLICK Software.\n\n"
            "Tip: Close CLICK without saving to undo all changes."
        )

        messagebox.showinfo("First-Time Tips", popup_text, parent=self)

        # Mark as shown so we don't bother the user again
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()

    def _get_window_title(self) -> str:
        """Generate window title based on Click project and data source."""
        base_title = "ClickNick Address Editor"

        parts = [base_title]

        # Add Click project filename if available
        if self.click_filename:
            parts.append(self.click_filename)

        # Add data source info
        try:
            file_path = self.shared_data._data_source.file_path
            if file_path:
                filename = Path(file_path).name
                parts.append(filename)
                # Add source type indicator
                if file_path.lower().endswith(".mdb"):
                    parts.append("DB")
                elif file_path.lower().endswith(".csv"):
                    parts.append("CSV")
        except Exception:
            pass

        return " - ".join(parts)

    def __init__(
        self,
        parent: tk.Widget,
        shared_data: SharedAddressData,
        click_filename: str = "",
    ):
        """Initialize the Address Editor window.

        Args:
            parent: Parent widget (main app window)
            shared_data: Shared data store for multi-window support
            click_filename: The connected Click project filename (e.g., "MyProject.ckp")
        """
        super().__init__(parent)

        self.shared_data = shared_data
        self.click_filename = click_filename
        self.title(self._get_window_title())
        self.geometry("1025x700")

        # Tab tracking: maps tab widget name to (panel, state) tuple
        self._tabs: dict[str, tuple[AddressPanel, TabState]] = {}
        self._tab_counter = 0  # For generating unique tab names
        self.all_nicknames: dict[int, str] = {}
        self._nav_window: NavWindow | None = None

        # Debounce timer for batching nickname changes (e.g., from Replace All)
        self._revalidate_timer: str | None = None
        self._pending_revalidate: bool = False
        # Track panels that were already validated in _on_sheet_modified
        # so _do_revalidation can skip them (they don't need re-validation)
        self._recently_validated_panels: set[str] = set()

        self._create_menu()
        self._create_widgets()
        self._load_initial_data()
        self._show_address_editor_popup()

        # Register as observer for shared data changes
        self.shared_data.add_observer(self._on_shared_data_changed)

        # Register window for tracking (allows parent to close all windows)
        self.shared_data.register_window(self)

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Keyboard shortcuts
        self.bind("<Control-s>", lambda e: self._save_all())
        self.bind("<Control-S>", lambda e: self._save_all())
        self.bind("<Control-t>", lambda e: self._on_new_tab_clicked())
        self.bind("<Control-T>", lambda e: self._on_new_tab_clicked())
        self.bind("<Control-w>", lambda e: self._close_current_tab())
        self.bind("<Control-W>", lambda e: self._close_current_tab())
        self.bind("<Control-space>", self._on_filter_toggle_key)

        # Open Tag Browser by default
        self.after(100, self._toggle_nav)
