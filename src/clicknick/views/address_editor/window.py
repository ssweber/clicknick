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

        # Refresh outline if visible (live update)
        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self._refresh_navigation()

        # NOTE: We intentionally do NOT call notify_data_changed here.
        # Other windows already received notification via _handle_data_changed
        # and validated their panels. The validation flags are on shared
        # AddressRow objects, so other windows see the updated state.
        # Calling notify_data_changed again would trigger redundant
        # refresh_from_external calls (~300ms wasted).

    def _schedule_revalidation(self) -> None:
        """Schedule a debounced revalidation of all panels."""
        # Cancel any existing timer
        if self._revalidate_timer is not None:
            self.after_cancel(self._revalidate_timer)

        # Schedule revalidation after 50ms idle
        self._revalidate_timer = self.after(50, self._do_revalidation)

    def _handle_nickname_changed(
        self, memory_type: str, addr_key: int, old_nick: str, new_nick: str
    ) -> None:
        """Handle nickname change from any panel.

        Uses debouncing to batch rapid changes (like Replace All) and avoid
        expensive revalidation for each individual cell change.

        Args:
            memory_type: The memory type of the panel that triggered the change
            addr_key: The address key that changed
            old_nick: The old nickname value
            new_nick: The new nickname value
        """
        # Update shared data registry immediately
        self.shared_data.update_nickname(addr_key, old_nick, new_nick)

        # Track this panel as already validated (in _on_sheet_modified)
        self._recently_validated_panels.add(memory_type)

        # Schedule debounced revalidation
        self._pending_revalidate = True
        self._schedule_revalidation()

    def _handle_data_changed(self) -> None:
        """Handle any data change from any panel (comment, init value, retentive)."""
        self._update_status()

        # Notify other windows (pass self so we skip our own notification)
        self.shared_data.notify_data_changed(sender=self)

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

    def _bind_panel_selection(self, panel: AddressPanel) -> None:
        """Bind selection change events on a panel's sheet.

        Args:
            panel: The AddressPanel to bind events on
        """
        # Bind to selection events to update Add Block button state
        panel.sheet.bind("<<SheetSelect>>", lambda e: self._update_add_block_button_state())

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
        """Refresh all tab panels from the database."""
        if self.shared_data.has_unsaved_changes():
            result = messagebox.askyesno(
                "Unsaved Changes",
                "You have unsaved changes. Refresh will discard them. Continue?",
                parent=self,
            )
            if not result:
                return

        try:
            # Discard shared data - this will notify all windows
            self.shared_data.discard_all_changes()

            # Update local nicknames reference
            self.all_nicknames = self.shared_data.all_nicknames

            # Rebuild unified view and refresh all tabs
            unified_view = build_unified_view(
                self.shared_data.all_rows,
                self.all_nicknames,
            )
            self.shared_data.set_unified_view(unified_view)
            self.shared_data.set_rows("unified", unified_view.rows)

            # Refresh all tab panels
            for _tab_id, (panel, _state) in self._tabs.items():
                panel._all_nicknames = self.all_nicknames
                panel.section_boundaries = unified_view.section_boundaries
                panel.rebuild_from_view(unified_view)

            self._update_status()
            self.status_var.set(f"Refreshed - {len(self.all_nicknames)} nicknames loaded")

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

        # Refresh the panel styling
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

        # Refresh the panel styling
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
        For folder nodes (multiple children): filters by path prefix.

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
                return

        # Folder node - filter by path prefix and scroll to first
        if path:
            panel.filter_var.set(path)
            panel._apply_filters()

        memory_type, address = leaves[0]
        panel.scroll_to_address(address, memory_type)

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
        panel.hide_empty_var.set(state.hide_empty)
        panel.hide_assigned_var.set(state.hide_assigned)
        panel.show_unsaved_only_var.set(state.show_unsaved_only)

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
                on_close=None,
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

    def _save_state_from_panel(self, panel: AddressPanel, state: TabState) -> None:
        """Save the current panel state to a TabState.

        Args:
            panel: The panel to read from
            state: The state to update
        """
        state.filter_enabled = panel.filter_enabled_var.get()
        state.filter_text = panel.filter_var.get()
        state.hide_empty = panel.hide_empty_var.get()
        state.hide_assigned = panel.hide_assigned_var.get()
        state.show_unsaved_only = panel.show_unsaved_only_var.get()
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

        Called when another window modifies the shared data, or when
        external changes are detected in the MDB file.
        Refreshes all tab panels to show the updated data.

        Args:
            sender: The object that triggered the change (if any)
        """
        # Skip if this notification was triggered by our own change
        if sender is self:
            return

        # Update local reference to nicknames
        self.all_nicknames = self.shared_data.all_nicknames

        # Check if unified view was cleared (e.g., after discard_all_changes)
        unified_view = self.shared_data.get_unified_view()

        if unified_view is None:
            # View was cleared - rebuild from fresh data
            unified_view = build_unified_view(
                self.shared_data.all_rows,
                self.all_nicknames,
            )
            self.shared_data.set_unified_view(unified_view)
            self.shared_data.set_rows("unified", unified_view.rows)

        # Update all tab panels
        for _tab_id, (panel, _state) in self._tabs.items():
            panel._all_nicknames = self.all_nicknames

            if panel.rows is not unified_view.rows:
                # Panel has stale rows - rebuild from unified view
                panel.section_boundaries = unified_view.section_boundaries
                panel.rebuild_from_view(unified_view)
            else:
                # Normal refresh - just sync display
                # If sender is another window, skip validation (they already did it)
                # If sender is None (external MDB change), we need to validate
                skip_validation = sender is not None
                panel.refresh_from_external(skip_validation=skip_validation)

        # Refresh outline if visible
        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self._refresh_navigation()

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
        self._create_tooltip(self.add_block_btn, "Click & drag memory addresses to define block")

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
            "1. This tool edits address information in the CLICK Programming Software's scratchpad database.\n"
            "2. Changes only TRULY save when you save in the CLICK Software.\n\n"
            "Quick safety tips:\n"
            "• Back up your `.ckp` file first\n"
            "• Not sure about a change? Close CLICK without saving to undo everything"
        )

        messagebox.showinfo("First-Time Tips", popup_text, parent=self)

        # Mark as shown so we don't bother the user again
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()

    def _get_window_title(self) -> str:
        """Generate window title based on data source."""
        base_title = "ClickNick Address Editor"

        try:
            file_path = self.shared_data._data_source.file_path
            if file_path:
                filename = Path(file_path).name
                # Determine source type from extension
                if file_path.lower().endswith(".mdb"):
                    return f"{base_title} - {filename} - DB"
                elif file_path.lower().endswith(".csv"):
                    return f"{base_title} - {filename} - CSV"
                else:
                    return f"{base_title} - {filename}"
        except Exception:
            pass

        return base_title

    def __init__(
        self,
        parent: tk.Widget,
        shared_data: SharedAddressData,
    ):
        """Initialize the Address Editor window.

        Args:
            parent: Parent widget (main app window)
            shared_data: Shared data store for multi-window support
        """
        super().__init__(parent)

        self.shared_data = shared_data
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
