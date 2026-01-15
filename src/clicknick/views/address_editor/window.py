"""Main window for the Address Editor.

Tabbed editor for viewing, creating, and editing PLC address nicknames.
Each tab displays all memory types in a unified view.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ...data.data_source import CsvDataSource, MdbDataSource
from ...data.shared_data import SharedAddressData
from ...services import ImportService, RowService

if TYPE_CHECKING:
    from ...models.address_row import AddressRow

from ...models.address_row import get_addr_key
from ...models.blocktag import (
    format_block_tag,
    parse_block_tag,
    strip_block_tag,
    validate_block_span,
)
from ...models.constants import DataType
from ...widgets.add_block_dialog import AddBlockDialog
from ...widgets.custom_notebook import CustomNotebook
from ...widgets.export_csv_dialog import ExportCsvDialog
from ...widgets.import_csv_dialog import ImportCsvDialog
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

    def _can_fill_down(self) -> tuple[bool, list[int], str]:
        """Check if Fill Down can be performed on current selection.

        Returns:
            Tuple of (can_fill, list of display row indices to fill, reason if can't fill).
        """
        selected = self._get_selected_row_indices()
        if len(selected) < 2:
            return False, [], "Select multiple rows"

        panel = self._get_current_panel()
        if not panel:
            return False, [], ""

        # Convert display indices to row objects
        rows = []
        for display_idx in selected:
            if display_idx >= len(panel._displayed_rows):
                return False, [], ""
            row_idx = panel._displayed_rows[display_idx]
            rows.append(panel.rows[row_idx])

        # Delegate business logic to service
        can_fill, reason = RowService.can_fill_down(rows)
        if not can_fill:
            return False, [], reason

        # Return display indices of rows to fill (excludes first row)
        return True, selected[1:], ""

    def _update_fill_down_button_state(self) -> None:
        """Update the Fill Down button state."""
        can_fill, _, _ = self._can_fill_down()
        self.fill_down_btn.configure(state="normal" if can_fill else "disabled")

    def _can_clone_structure(self) -> tuple[bool, str]:
        """Check if Clone Structure can be performed on current selection.

        Returns:
            Tuple of (can_clone, reason if can't clone).
        """
        selected = self._get_selected_row_indices()
        if not selected:
            return False, "Select rows to clone"

        panel = self._get_current_panel()
        if not panel:
            return False, ""

        # Convert display indices to row objects
        rows = []
        for display_idx in selected:
            if display_idx >= len(panel._displayed_rows):
                continue
            row_idx = panel._displayed_rows[display_idx]
            rows.append(panel.rows[row_idx])

        # Delegate business logic to service
        return RowService.can_clone_structure(rows)

    def _update_clone_button_state(self) -> None:
        """Update the Clone Structure button state."""
        can_clone, _ = self._can_clone_structure()
        self.clone_btn.configure(state="normal" if can_clone else "disabled")

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

        # Ask for number of clones (UI concern)
        num_clones = simpledialog.askinteger(
            "Clone Structure",
            f"How many clones of the {block_size}-row structure?",
            parent=self,
            minvalue=1,
            maxvalue=100,
        )
        if not num_clones:
            return

        # Validate destination rows (UI concern)
        last_display_idx = selected[-1]
        dest_start = last_display_idx + 1
        dest_count = block_size * num_clones

        if dest_start + dest_count > len(panel._displayed_rows):
            messagebox.showerror(
                "Clone Error",
                f"Not enough rows below selection. Need {dest_count} empty rows, "
                f"but only {len(panel._displayed_rows) - dest_start} available.",
                parent=self,
            )
            return

        # Get template and destination rows for validation
        template_rows = [panel.rows[panel._displayed_rows[idx]] for idx in selected]
        destination_rows = [
            panel.rows[panel._displayed_rows[dest_start + i]] for i in range(dest_count)
        ]

        # Validate destination rows via service
        is_valid, error_msg = RowService.validate_clone_destination(template_rows, destination_rows)
        if not is_valid:
            messagebox.showerror("Clone Error", error_msg, parent=self)
            return

        # Ask user about incrementing initial values (UI concern)
        increment_initial_value = False
        for display_idx in selected:
            row_idx = panel._displayed_rows[display_idx]
            row = panel.rows[row_idx]
            if row.nickname and row.initial_value and row.data_type != DataType.BIT:
                _, orig_num, _ = RowService.increment_nickname_suffix(row.nickname, 0)
                if orig_num is not None:
                    try:
                        init_val = int(row.initial_value)
                        if init_val == orig_num:
                            result = messagebox.askyesno(
                                "Increment Values?",
                                f"Also increment initial values?\n\n"
                                f"Example: {row.nickname} ({init_val}) → ({init_val + 1})",
                                parent=self,
                            )
                            increment_initial_value = result
                            break
                    except ValueError:
                        pass

        # Get template and destination keys
        template_keys = [panel.rows[panel._displayed_rows[idx]].addr_key for idx in selected]
        destination_keys = [
            panel.rows[panel._displayed_rows[dest_start + i]].addr_key for i in range(dest_count)
        ]

        # Execute clone via service within edit_session
        # edit_session handles validation, notification, and display refresh automatically
        with self.shared_data.edit_session():
            RowService.clone_structure(
                self.shared_data,
                template_keys,
                destination_keys,
                num_clones,
                increment_initial_value,
            )

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

        # Get source row
        selected = self._get_selected_row_indices()
        first_display_idx = selected[0]
        first_row_idx = panel._displayed_rows[first_display_idx]
        first_row = panel.rows[first_row_idx]

        # Ask user about incrementing initial value (UI concern)
        increment_initial_value = False
        if first_row.initial_value and first_row.data_type != DataType.BIT:
            _, orig_num, _ = RowService.increment_nickname_suffix(first_row.nickname, 0)
            if orig_num is not None:
                try:
                    init_val = int(first_row.initial_value)
                    if init_val == orig_num:
                        result = messagebox.askyesno(
                            "Increment Initial Value?",
                            f"Also increment initial value?\n\n"
                            f"Example: {first_row.nickname} ({init_val}) → ({init_val + 1})",
                            parent=self,
                        )
                        increment_initial_value = result
                except ValueError:
                    pass

        # Get target keys (rows_to_fill already excludes the source row)
        target_keys = [panel.rows[panel._displayed_rows[idx]].addr_key for idx in rows_to_fill]

        # Execute fill down via service within edit_session
        # edit_session handles validation, notification, and display refresh automatically
        with self.shared_data.edit_session():
            RowService.fill_down(
                self.shared_data,
                first_row.addr_key,
                target_keys,
                increment_initial_value,
            )

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

    def _is_using_mdb(self) -> bool:
        """Check if the data source is an MDB file (vs CSV).

        Returns:
            True if using MDB, False otherwise
        """
        return isinstance(self.shared_data._data_source, MdbDataSource)

    def _get_save_label(self) -> str:
        """Get the appropriate label for save operation.

        Returns:
            'Sync' for MDB (changes sync to CLICK's temp DB), 'Save' for CSV
        """
        return "Sync" if self._is_using_mdb() else "Save"

    def _save_all(self) -> None:
        """Save all changes to database."""
        save_label = self._get_save_label()
        action_verb = "synced" if self._is_using_mdb() else "saved"

        # Check for validation errors (across all shared data)
        if self.shared_data.has_errors():
            messagebox.showerror(
                "Validation Errors",
                f"Cannot {save_label.lower()}: there are validation errors. Please fix them first.",
                parent=self,
            )
            return

        if not self.shared_data.has_unsaved_changes():
            messagebox.showinfo(save_label, f"No changes to {save_label.lower()}.", parent=self)
            return

        try:
            count = self.shared_data.save_all_changes()

            self.status_var.set(f"{action_verb.capitalize()} {count} changes")
            messagebox.showinfo(
                save_label, f"Successfully {action_verb} {count} changes.", parent=self
            )

        except Exception as e:
            messagebox.showerror(f"{save_label} Error", str(e), parent=self)

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

    def _export_to_csv(self) -> None:
        """Export address data to CSV file."""
        # Show export dialog
        dialog = ExportCsvDialog(self)
        self.wait_window(dialog)

        if dialog.result is None:
            return

        file_path, export_mode = dialog.result

        try:
            if export_mode == "all":
                # Export all rows from shared data using CsvDataSource
                csv_source = CsvDataSource(str(file_path))
                count = csv_source.save_changes(list(self.shared_data.all_rows.values()))
                messagebox.showinfo(
                    "Export Complete",
                    f"Successfully exported {count} rows to:\n{file_path}",
                    parent=self,
                )
            elif export_mode == "visible":
                # Export only visible rows from current panel
                panel = self._get_current_panel()
                if not panel:
                    messagebox.showerror(
                        "Export Error",
                        "No active tab to export from.",
                        parent=self,
                    )
                    return

                # Get visible rows (respects current filters)
                visible_rows = [panel.rows[idx] for idx in panel._displayed_rows]
                csv_source = CsvDataSource(str(file_path))
                count = csv_source.save_changes(visible_rows)
                messagebox.showinfo(
                    "Export Complete",
                    f"Successfully exported {count} visible rows to:\n{file_path}",
                    parent=self,
                )

        except Exception as e:
            messagebox.showerror("Export Error", str(e), parent=self)

    def _import_from_csv(self) -> None:
        """Import address data from CSV file with merge options."""
        # Show import dialog
        dialog = ImportCsvDialog(self)
        self.wait_window(dialog)

        if dialog.result is None:
            return

        csv_path, selected_blocks, import_options_per_block = dialog.result

        try:
            # Apply merge via ImportService within edit_session
            # edit_session handles validation and notification automatically
            with self.shared_data.edit_session():
                updated_count = ImportService.merge_blocks(
                    self.shared_data, selected_blocks, import_options_per_block
                )

            # edit_session exited - validation and notification happened automatically

            self._update_status()

            # Clear filter and switch to "Show: Changed"
            panel = self._get_current_panel()
            if panel:
                panel.filter_enabled_var.set(False)
                panel.filter_var.set("")
                panel.row_filter_var.set("changed")
                panel._apply_filters()

            messagebox.showinfo(
                "Import Complete",
                f"Successfully imported {updated_count} addresses from:\n{csv_path.name}",
                parent=self,
            )

        except Exception as e:
            messagebox.showerror("Import Error", str(e), parent=self)

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

        # Helper to append tag to comment
        def add_tag(row: AddressRow, tag: str) -> None:
            row.comment = f"{row.comment} {tag}" if row.comment else tag

        # Modify comments within edit_session
        # edit_session automatically handles:
        # - Interleaved pair sync (T1→TD1) via RowDependencyService
        # - Validation, block colors, observer notification
        with self.shared_data.edit_session():
            if first_row_idx == last_row_idx:
                # Single row - self-closing tag
                tag = format_block_tag(block_name, "self-closing", color)
                add_tag(first_row, tag)
            else:
                # Range - opening and closing tags
                add_tag(first_row, format_block_tag(block_name, "open", color))
                add_tag(last_row, format_block_tag(block_name, "close"))

        self._update_status()

    def _on_remove_block_clicked(self) -> None:
        """Handle Remove Block button click.

        Removes the block tag from the selected row's comment.
        edit_session automatically handles:
        - Paired tag sync (removing closing tag when opening is removed)
        - Interleaved pair sync (T1→TD1) via RowDependencyService
        - Validation, block colors, observer notification
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

        # Remove the tag - edit_session handles paired tag and interleaved sync
        with self.shared_data.edit_session():
            first_row.comment = strip_block_tag(first_row.comment)

        self._update_add_block_button_state()
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

    def _on_rename(self, prefix: str, old_text: str, new_text: str, is_array: bool) -> None:
        """Handle rename from outline tree.

        Args:
            prefix: Path prefix (e.g., "Tank_" for renaming Pump in Tank_Pump_Speed)
            old_text: Current segment text
            new_text: New segment text
            is_array: True if renaming an array node
        """
        from ...utils.rename_helpers import build_rename_pattern

        # Build the regex pattern and replacement template
        pattern, replacement_template = build_rename_pattern(prefix, old_text, is_array)

        # Format the replacement template with the new text
        replacement = replacement_template.format(new_text=new_text)

        # Get the current panel
        panel = self._get_current_panel()
        if not panel or not panel.is_unified:
            messagebox.showerror(
                "No Active Panel", "Please open a tab to perform the rename.", parent=self
            )
            return

        # Use the direct regex replacement method
        replacements_made = panel.sheet.regex_replace_all_direct(
            pattern, replacement, selection_only=False
        )

        # Clear filter and switch to "Show: Changed"
        if replacements_made > 0:
            panel.filter_enabled_var.set(False)
            panel.filter_var.set("")
            panel.row_filter_var.set("changed")
            panel._apply_filters()

        # Show confirmation
        if replacements_made > 0:
            messagebox.showinfo(
                "Rename Complete",
                f"Renamed {replacements_made} nickname{'s' if replacements_made != 1 else ''}.",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "No Matches", f"No nicknames match the pattern for '{old_text}'.", parent=self
            )

    def _toggle_nav(self) -> None:
        """Toggle the outline window visibility."""
        if self._nav_window is None:
            # Create outline window
            self._nav_window = NavWindow(
                self,
                on_outline_select=self._on_outline_select,
                on_block_select=self._on_block_select,
                on_rename=self._on_rename,
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
                self.shared_data.set_rows("unified", unified_view.rows)
                
                # FIX: Update colors now that the unified view rows are available
                from ...services.block_service import BlockService
                with self.shared_data.edit_session():
                    BlockService.update_colors(self.shared_data)

            # Create unified panel
            panel = AddressPanel(
                self.notebook,
                self.shared_data,
                memory_type="unified",  # Special type for unified view
                combined_types=None,
                on_validate_affected=self.shared_data.validate_affected_rows,
                is_duplicate_fn=self.shared_data.is_duplicate_nickname,
                is_unified=True,
                section_boundaries=unified_view.section_boundaries,
            )

            # Add to notebook
            self.notebook.add(panel, text=tab_name)

            # Track the tab
            tab_id = str(panel)
            self._tabs[tab_id] = (panel, state)

            # Select the new tab
            self.notebook.select(panel)

            # Apply state to panel (filters, column visibility)
            self._apply_state_to_panel(panel, state)
            
            # Initialize panel with unified view data
            panel.initialize_from_view(unified_view.rows)

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

    def _on_shared_data_changed(
        self, sender: object = None, affected_indices: set[int] | None = None
    ) -> None:
        """Handle notification that shared data has changed.

        With skeleton architecture, all panels share the same AddressRow objects.
        When skeleton rows are updated in-place, we just refresh displays.
        No need to rebuild views since row object identity never changes.

        Args:
            sender: The object that triggered the change (if any)
            affected_indices: Set of addr_keys that changed. If None,
                             indicates a full refresh is needed.
        """
        # Skip if this notification was triggered by our own change
        if sender is self:
            return

        # Update local reference to nicknames
        self.all_nicknames = self.shared_data.all_nicknames

        # Update all tab panels - skeleton rows are already updated in-place
        for _tab_id, (panel, _state) in self._tabs.items():
            if affected_indices is not None:
                # Targeted refresh - only update specific rows (validation done by edit_session)
                panel.refresh_targeted(affected_indices)
            else:
                # Full refresh - needed for external MDB changes or unknown scope
                # Validation is handled by edit_session
                panel.refresh_from_external()

        # Refresh outline if visible (deferred until idle)
        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self.after_idle(self._refresh_navigation)

        self._update_status()

    def _on_closing(self) -> None:
        """Handle window close - prompt to save if needed."""
        if self._has_unsaved_changes():
            save_label = self._get_save_label()
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                f"You have unsaved changes. {save_label} before closing?",
                parent=self,
            )
            if result is None:  # Cancel
                return
            if result:  # Yes - save/sync
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

    def _update_save_ui_labels(self) -> None:
        """Update Save/Sync labels in UI based on data source type."""
        save_label = self._get_save_label()

        # Update menu item
        if hasattr(self, "_file_menu") and hasattr(self, "_save_menu_index"):
            try:
                self._file_menu.entryconfig(self._save_menu_index, label=f"{save_label} All")
            except Exception:
                pass

        # Update button
        if hasattr(self, "save_btn"):
            self.save_btn.configure(text=f"💾 {save_label} All")

    def _create_menu(self) -> None:
        """Create the menu bar."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File menu
        self._file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=self._file_menu)

        self._file_menu.add_command(
            label="New Tab", command=self._on_new_tab_clicked, accelerator="Ctrl+T"
        )
        self._file_menu.add_separator()
        self._file_menu.add_command(label="Import from CSV...", command=self._import_from_csv)
        self._file_menu.add_command(label="Export to CSV...", command=self._export_to_csv)
        self._file_menu.add_separator()
        self._file_menu.add_command(label="Refresh", command=self._refresh_all)
        # Save menu item - will be updated after data loads
        self._save_menu_index = self._file_menu.index("end") + 1
        self._file_menu.add_command(label="Save All", command=self._save_all, accelerator="Ctrl+S")
        self._file_menu.add_command(label="Discard Changes", command=self._discard_changes)
        self._file_menu.add_separator()
        self._file_menu.add_command(
            label="Close Tab", command=self._close_current_tab, accelerator="Ctrl+W"
        )
        self._file_menu.add_separator()
        self._file_menu.add_command(label="Close Window", command=self._on_closing)

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

        # Save button (right side) - will be updated after data loads
        self.save_btn = ttk.Button(footer, text="💾 Save All", command=self._save_all)
        self.save_btn.pack(side=tk.RIGHT)

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

            # Update Save/Sync labels based on data source type
            self._update_save_ui_labels()

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
        self._nav_window: NavWindow | None = None

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
