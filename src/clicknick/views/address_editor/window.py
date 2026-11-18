"""Main window for the Address Editor.

Tabbed editor for viewing, creating, and editing PLC address nicknames.
Each tab shows every memory type in one table.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import DataType
from pyclickplc.blocks import (
    format_block_tag,
    is_block_name_available,
    parse_block_tag,
    validate_block_span,
)

from ...data.data_source import CsvDataSource
from ...services import ImportService, RowService
from ...services.block_service import add_block_tag, remove_block_tag
from ...utils.rename_helpers import build_rename_pattern, rename_replacement
from ...widgets.add_block_dialog import AddBlockDialog
from ...widgets.custom_notebook import CustomNotebook
from ...widgets.export_csv_dialog import ExportCsvDialog
from ...widgets.import_csv_dialog import ImportCsvDialog
from ...widgets.new_tab_dialog import ask_new_tab
from ..nav_window.outline_logic import outline_filter
from ..nav_window.window import NavWindow
from .jump_sidebar import COMBINED_TYPES, JumpSidebar
from .panel import AddressPanel
from .panel_constants import COL_NICKNAME
from .tab_state import TabState
from .view_builder import build_unified_view

if TYPE_CHECKING:
    from ...data_session import DataSession


class AddressEditorWindow(tk.Toplevel):
    """Main window for the Address Editor."""

    def _update_undo_redo_menu_states(self) -> None:
        """Update Undo/Redo menu items enabled state based on undo/redo stacks."""
        if not hasattr(self, "_edit_menu"):
            return

        undo_state = "normal" if self._store.can_undo() else "disabled"
        self._edit_menu.entryconfig(0, state=undo_state)

        redo_state = "normal" if self._store.can_redo() else "disabled"
        self._edit_menu.entryconfig(1, state=redo_state)

    def _update_status(self) -> None:
        """Update the status bar with current state."""
        total_modified = self._store.get_total_modified_count()
        total_errors = self._store.get_total_error_count()

        # The panel's footer counts the rows that its filter shows. These count every row.
        parts = [f"Tabs: {len(self._tabs)}"]
        if total_modified > 0:
            noun = "row" if total_modified == 1 else "rows"
            parts.append(f"{total_modified} {noun} changed")
        if total_errors > 0:
            noun = "row" if total_errors == 1 else "rows"
            parts.append(f"{total_errors} {noun} with errors")
        synced_pending = self._get_synced_pending()
        if synced_pending > 0:
            noun = "tag" if synced_pending == 1 else "tags"
            parts.append(f"{synced_pending} {noun} synced - Save in CLICK")

        self.status_var.set(" | ".join(parts))

        self.sidebar.update_all_indicators()

        self._update_undo_redo_menu_states()

    def _refresh_navigation(self) -> None:
        """Refresh the navigation dock with current data."""
        if self._nav_window is not None:
            self._nav_window.refresh(self._store.visible_state)

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

        # tksheet returns the selected rows as a set of row indices.
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

        rows = []
        for display_idx in selected:
            if display_idx >= len(panel._displayed_rows):
                return False, [], ""
            row_idx = panel._displayed_rows[display_idx]
            rows.append(panel.rows[row_idx])

        can_fill, reason = RowService.can_fill_down(rows)
        if not can_fill:
            return False, [], reason

        # Collect the display indices of the rows that Fill Down writes. The service picks them.
        targets = {row.addr_key for row in RowService.fill_down_targets(rows)}
        return (
            True,
            [idx for idx, row in zip(selected, rows, strict=True) if row.addr_key in targets],
            "",
        )

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

        rows = []
        for display_idx in selected:
            if display_idx >= len(panel._displayed_rows):
                continue
            row_idx = panel._displayed_rows[display_idx]
            rows.append(panel.rows[row_idx])

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

        num_clones = simpledialog.askinteger(
            "Clone Structure",
            f"How many clones of the {block_size}-row structure?",
            parent=self,
            minvalue=1,
            maxvalue=100,
        )
        if not num_clones:
            return

        last_display_idx = selected[-1]
        dest_start = last_display_idx + 1
        dest_count = block_size * num_clones

        if dest_start + dest_count > len(panel._displayed_rows):
            messagebox.showerror(
                "Clone Error",
                f"Clone needs {dest_count} rows below the selection, and only "
                f"{len(panel._displayed_rows) - dest_start} are shown. Ask for fewer clones, "
                "or clear the filter.",
                parent=self,
            )
            return

        template_rows = [panel.rows[panel._displayed_rows[idx]] for idx in selected]
        destination_rows = [
            panel.rows[panel._displayed_rows[dest_start + i]] for i in range(dest_count)
        ]

        is_valid, error_msg = RowService.validate_clone_destination(template_rows, destination_rows)
        if not is_valid:
            messagebox.showerror("Clone Error", error_msg, parent=self)
            return

        # Ask whether to increment initial values too. Ask only if a non-bit row's initial
        # value equals the last number in its nickname.
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
                                "Increment Initial Values?",
                                f"Also increment initial values?\n\n"
                                f"Example: {row.nickname} ({init_val}) → ({init_val + 1})",
                                parent=self,
                            )
                            increment_initial_value = result
                            break
                    except ValueError:
                        pass

        template_keys = [panel.rows[panel._displayed_rows[idx]].addr_key for idx in selected]
        destination_keys = [
            panel.rows[panel._displayed_rows[dest_start + i]].addr_key for i in range(dest_count)
        ]

        # When the edit session closes, the store validates the rows and notifies this window.
        # The window then redraws its panels.
        with self._store.edit_session("Clone structure") as session:
            RowService.clone_structure(
                session,
                self._store,
                template_keys,
                destination_keys,
                num_clones,
                increment_initial_value,
            )

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

        # The first selected row is the source.
        selected = self._get_selected_row_indices()
        first_display_idx = selected[0]
        first_row_idx = panel._displayed_rows[first_display_idx]
        first_row = panel.rows[first_row_idx]

        # Ask whether to increment the initial value too. Ask only if the source is not a bit
        # and its initial value equals the last number in its nickname.
        increment_initial_value = False
        if first_row.initial_value and first_row.data_type != DataType.BIT:
            _, orig_num, _ = RowService.increment_nickname_suffix(first_row.nickname, 0)
            if orig_num is not None:
                try:
                    init_val = int(first_row.initial_value)
                    if init_val == orig_num:
                        result = messagebox.askyesno(
                            "Increment Initial Values?",
                            f"Also increment initial values?\n\n"
                            f"Example: {first_row.nickname} ({init_val}) → ({init_val + 1})",
                            parent=self,
                        )
                        increment_initial_value = result
                except ValueError:
                    pass

        # rows_to_fill does not include the source row.
        target_keys = [panel.rows[panel._displayed_rows[idx]].addr_key for idx in rows_to_fill]

        # When the edit session closes, the store validates the rows and notifies this window.
        # The window then redraws its panels.
        with self._store.edit_session("Fill down") as session:
            RowService.fill_down(
                session,
                self._store,
                first_row.addr_key,
                target_keys,
                increment_initial_value,
            )

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
        panel.sheet.bind("<<SheetSelect>>", self._update_button_states)

    def _on_type_selected(self, type_name: str) -> None:
        """Handle type button click - scroll to section in current tab."""
        panel = self._get_current_panel()
        if panel:
            panel.scroll_to_section(type_name)

    def _on_address_jump(self, type_name: str, address: int) -> None:
        """Handle address jump from submenu."""
        panel = self._get_current_panel()
        if panel:
            # For combined types (T/TD, CT/CTD), use the first sub-type
            if type_name in COMBINED_TYPES:
                mem_type = COMBINED_TYPES[type_name][0]
            else:
                mem_type = type_name
            panel.scroll_to_address(address, mem_type)

    def _has_unsaved_changes(self) -> bool:
        """Return True if the store has unsaved changes. Every tab shares the one store."""
        return self._store.has_unsaved_changes()

    def _is_using_mdb(self) -> bool:
        """Check if the data source is an MDB file (vs CSV).

        Returns:
            True if using MDB, False otherwise
        """
        return self._store.is_database

    def _get_save_label(self) -> str:
        """Get the appropriate label for save operation.

        Returns:
            'Sync' for MDB (changes sync to CLICK's temp DB), 'Save' for CSV
        """
        return "Sync" if self._is_using_mdb() else "Save"

    def _cell_editor_is_open(self) -> bool:
        """Return True while a cell editor is open in any tab."""
        return any(panel.sheet.MT.text_editor.open for panel, *_ in self._tabs.values())

    def _save_all(self) -> None:
        """Write every unsaved edit to CLICK's database or to the CSV file."""
        if not self.commit_open_cell_editor():
            return
        save_label = self._get_save_label()
        action_verb = "synced" if self._is_using_mdb() else "saved"

        if self._store.has_errors():
            messagebox.showerror(
                "Validation Errors",
                f"Cannot {save_label.lower()}, because some rows have errors. To list "
                f"them, choose Show: Errors. Fix them, then {save_label} again.",
                parent=self,
            )
            return

        if not self._store.has_unsaved_changes():
            messagebox.showinfo(save_label, f"No changes to {save_label.lower()}.", parent=self)
            return

        try:
            synced_keys = self._store.save_all_changes()
            count = len(synced_keys)

            if self._on_synced is not None:
                self._on_synced(synced_keys)

            # The status line says what was written. A Sync that succeeds shows no box.
            if count:
                rows = "row" if count == 1 else "rows"
                self.status_var.set(f"{action_verb.capitalize()} {count} {rows}")
            elif self._is_using_mdb():
                self.status_var.set("CLICK already has these changes. Nothing was written.")
            else:
                self.status_var.set("The file already has these changes. Nothing was written.")
            if self._close_after_sync:
                self.close_without_prompt()

        except Exception as e:
            messagebox.showerror(
                f"{save_label} Error",
                f"Could not {save_label.lower()} the changes.\n\n{e}",
                parent=self,
            )

    def _discard_changes(self) -> None:
        """Discard all unsaved changes by resetting to original values."""
        if not self.commit_open_cell_editor():
            return
        if not self._store.has_unsaved_changes():
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
            # The store notifies this window, and _on_address_store_changed() redraws the panels.
            self._store.discard_all_changes()

            self._update_status()
            self.status_var.set("Changes discarded")

        except Exception as e:
            messagebox.showerror(
                "Discard Changes", f"Could not discard the changes.\n\n{e}", parent=self
            )

    def _export_to_csv(self) -> None:
        """Export address data to CSV file."""
        dialog = ExportCsvDialog(self)
        self.wait_window(dialog)

        if dialog.result is None:
            return

        file_path, export_mode = dialog.result

        try:
            if export_mode == "all":
                csv_source = CsvDataSource(str(file_path))
                count = csv_source.save_changes(list(self._store.visible_state.values()))
                messagebox.showinfo(
                    "Export Complete",
                    f"Exported {count} rows to\n{file_path}",
                    parent=self,
                )
            elif export_mode == "visible":
                panel = self._get_current_panel()
                if not panel:
                    messagebox.showerror(
                        "Export Error",
                        "No active tab to export from.",
                        parent=self,
                    )
                    return

                # The displayed rows are the ones that pass the tab's filters.
                visible_rows = [panel.rows[idx] for idx in panel._displayed_rows]
                csv_source = CsvDataSource(str(file_path))
                count = csv_source.save_changes(visible_rows)
                messagebox.showinfo(
                    "Export Complete",
                    f"Exported the {count} rows that the filter shows to\n{file_path}",
                    parent=self,
                )

        except Exception as e:
            messagebox.showerror(
                "Export Error", f"Could not export to {file_path}.\n\n{e}", parent=self
            )

    def _import_from_csv(self) -> None:
        """Import address data from CSV file with merge options."""
        dialog = ImportCsvDialog(self)
        self.wait_window(dialog)

        if dialog.result is None:
            return

        csv_path, selected_blocks, import_options_per_block = dialog.result

        try:
            # When the edit session closes, the store validates the rows and notifies this
            # window. The window then redraws its panels.
            with self._store.edit_session("Import from CSV") as session:
                updated_count = ImportService.merge_blocks(
                    self._store, session, selected_blocks, import_options_per_block
                )

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
                f"Read {updated_count} addresses from {csv_path.name}. "
                "The table now shows the rows that changed.",
                parent=self,
            )

        except Exception as e:
            messagebox.showerror(
                "Import Error", f"Could not import {csv_path.name}.\n\n{e}", parent=self
            )

    def _create_tooltip(self, widget: tk.Widget, text: str) -> None:
        """Attach a tooltip to a widget. The tooltip shows only while the widget is disabled.

        Args:
            widget: The widget to attach the tooltip to
            text: The tooltip text
        """
        tooltip = None

        def show_tooltip(event):
            nonlocal tooltip
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

        def validate_block_name(name: str) -> tuple[bool, str]:
            view = self._store.get_unified_view()
            if view is None:
                return True, ""
            if is_block_name_available(name, view.rows):
                return True, ""
            return False, f"Block name '{name}' already exists.\nBlock names must be unique."

        dialog = AddBlockDialog(
            self, validate_name=validate_block_name, row_count=len(selected_rows)
        )
        self.wait_window(dialog)

        if dialog.result is None:
            return

        block_name, color = dialog.result

        # If the selection holds both T and TD rows (or CT and CTD), tag the T or CT rows. The
        # store then adds the same tags to the TD or CTD rows, with _D after the block name.
        first_key, last_key = RowService.block_tag_keys(selected_rows)
        visible = self._store.visible_state
        first_row = visible[first_key]
        last_row = visible[last_key]

        # When the edit session closes, the store adds a matching tag to the other row of each
        # tagged T/TD or CT/CTD pair (T1 and TD1). It then validates the rows, recomputes the
        # block colors and notifies its observers.
        with self._store.edit_session("Add block tag") as session:
            if first_key == last_key:
                # Single row - self-closing tag
                tag = format_block_tag(block_name, "self-closing", color)
                new_comment = add_block_tag(first_row.comment, tag)
                session.set_field(first_key, "comment", new_comment)
            else:
                # Range - opening and closing tags
                open_comment = add_block_tag(
                    first_row.comment, format_block_tag(block_name, "open", color)
                )
                close_comment = add_block_tag(
                    last_row.comment, format_block_tag(block_name, "close")
                )
                session.set_field(first_key, "comment", open_comment)
                session.set_field(last_key, "comment", close_comment)

        self._update_status()

    def _on_remove_block_clicked(self) -> None:
        """Handle Remove Block button click.

        Remove the block tag from the comment of the first selected row, if that tag opens a
        block or closes itself. When the edit session closes, the store removes the block's
        closing tag, if it has one. It also removes the matching tags from the other rows of
        any T/TD or CT/CTD pairs (T1 and TD1). It then validates the rows, recomputes the block
        colors and notifies its observers.
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

        with self._store.edit_session("Remove block tag") as session:
            new_comment = remove_block_tag(first_row.comment)
            session.set_field(first_row.addr_key, "comment", new_comment)

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

        If the item has one address and *path* is that address's nickname, scroll to its row.
        Otherwise show all rows and filter the nicknames by *path* as a prefix, using the ^
        anchor. If the item is a nickname that has others under it, the filter is `tree:`
        and the nickname. That filter shows the item's own row and the rows under it.

        Args:
            path: Filter prefix for folders or exact nickname for leaves
            leaves: List of (memory_type, address) tuples for all addresses under this node
        """
        if not leaves:
            return

        panel = self._get_current_panel()
        if not panel:
            return

        if len(leaves) == 1:
            memory_type, address = leaves[0]
            addr_key = get_addr_key(memory_type, address)
            row = self._store.visible_state.get(addr_key)
            nickname = row.nickname if row else ""
            if path == nickname:
                panel.scroll_to_address(address, memory_type)
                panel.sheet.focus_set()
                return

        panel.row_filter_var.set("all")

        panel.filter_enabled_var.set(True)
        if path:
            rows = (self._store.visible_state.get(get_addr_key(mt, a)) for mt, a in leaves)
            nicknames = [row.nickname for row in rows if row is not None]
            panel.filter_var.set(outline_filter(path, nicknames))
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
        if not panel:
            return

        memory_type, address = leaves[0]
        panel.scroll_to_address(address, memory_type)

        # Focus the sheet for immediate keyboard navigation/editing
        panel.sheet.focus_set()

    def _on_rename(
        self, prefix: str, old_text: str, new_text: str, is_array: bool, exact: bool
    ) -> None:
        """Handle rename from outline tree.

        Args:
            prefix: Path prefix (e.g., "Tank_" for renaming Pump in Tank_Pump_Speed)
            old_text: Current segment text
            new_text: New segment text
            is_array: True if renaming an array node
            exact: True to rename only the nickname prefix + old_text, and not the nicknames
                that continue it
        """
        pattern, replacement_template = build_rename_pattern(prefix, old_text, is_array, exact)

        replacement = rename_replacement(replacement_template, new_text)

        panel = self._get_current_panel()
        if not panel:
            messagebox.showerror("No Tab Open", "Open a tab, then rename again.", parent=self)
            return

        replacements_made = panel.sheet.regex_replace_all_direct(
            pattern,
            replacement,
            selection_only=False,
            visible_rows_only=False,
            columns={COL_NICKNAME},
        )
        if replacements_made is None:
            return  # The sheet has shown the error.

        # Clear filter and switch to "Show: Changed"
        if replacements_made > 0:
            panel.filter_enabled_var.set(False)
            panel.filter_var.set("")
            panel.row_filter_var.set("changed")
            panel._apply_filters()

        if replacements_made > 0:
            messagebox.showinfo(
                "Rename Complete",
                f"Renamed {replacements_made} nickname{'s' if replacements_made != 1 else ''}.",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Rename", f"No nickname under '{prefix}{old_text}' changed.", parent=self
            )

    def _toggle_nav(self) -> None:
        """Toggle the outline window visibility."""
        if self._nav_window is None:
            self._nav_window = NavWindow(
                self,
                on_outline_select=self._on_outline_select,
                on_block_select=self._on_block_select,
                on_rename=self._on_rename,
            )
            self._refresh_navigation()
            self._tag_browser_var.set(True)
        elif self._nav_window.winfo_viewable():
            self._nav_window.withdraw()
            self._tag_browser_var.set(False)
        else:
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
        panel.filter_enabled_var.set(state.filter_enabled)
        panel.filter_var.set(state.filter_text)
        panel.row_filter_var.set(state.row_filter)

        # Apply column visibility
        panel.hide_used_var.set(state.hide_used_column)
        panel.hide_init_ret_var.set(state.hide_init_ret_columns)
        panel._toggle_used_column()
        panel._toggle_init_ret_columns()

        panel._apply_filters()

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
            self._tab_counter += 1
            tab_name = f"Tab {self._tab_counter}"

            if clone_from is not None:
                state = clone_from.clone()
                state.name = tab_name
            else:
                state = TabState.fresh()
                state.name = tab_name

            unified_view = self._store.get_unified_view()
            if unified_view is None:
                unified_view = build_unified_view(self._store.visible_state)
                self._store.set_unified_view(unified_view)

            panel = AddressPanel(
                self.notebook,
                self._store,
                section_boundaries=unified_view.section_boundaries,
                get_analysis_service=self._get_analysis_service,
            )

            self.notebook.add(panel, text=tab_name)

            tab_id = str(panel)
            self._tabs[tab_id] = (panel, state)

            self.notebook.select(panel)

            panel.initialize_from_view(unified_view.rows)

            # Apply the tab's filters, column visibility and scroll position after the rows
            # are loaded.
            self._apply_state_to_panel(panel, state)

            self._bind_panel_selection(panel)

            return True

        except Exception as e:
            messagebox.showerror("New Tab", f"Could not open a new tab.\n\n{e}", parent=self)
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
                tab_index = self.notebook.index(current)

                if current in self._tabs:
                    del self._tabs[current]

                self.notebook.forget(tab_index)

                self._update_status()
        except Exception:
            pass

    def _on_tab_changed(self, event=None) -> None:
        """Handle tab selection change."""
        self._update_add_block_button_state()
        self._update_status()

        # Make the View menu's Filter Enabled check mark match the newly selected tab.
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

        try:
            start_row, _end_row = panel.sheet.visible_rows
            state.scroll_row_index = start_row
        except Exception:
            state.scroll_row_index = 0

    def _on_new_tab_clicked(self) -> None:
        """Handle New Tab button click."""
        current_panel = self._get_current_panel()
        current_state = self._get_current_state()

        # Save the tab's settings before asking, so that a clone copies its current filters and
        # scroll position.
        if current_panel and current_state:
            self._save_state_from_panel(current_panel, current_state)

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

    def _on_address_store_changed(
        self, sender: object = None, affected_indices: set[int] | None = None
    ) -> None:
        """Handle notification that the store has changed.

        The store replaces changed rows in the unified view, which every panel shares, before
        it notifies. Panels then only need to redraw.

        Args:
            sender: The store that changed
            affected_indices: Set of addr_keys that changed. If None,
                             indicates a full refresh is needed.
        """
        for _tab_id, (panel, _state) in self._tabs.items():
            if affected_indices is not None:
                panel.refresh_targeted(affected_indices)
            else:
                # No keys means the sender does not say which rows changed, so redraw them all.
                panel.refresh_from_external()

        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self.after_idle(self._refresh_navigation)

        self._update_status()

    def _on_closing(self) -> None:
        """Handle window close - prompt to save if needed."""
        if not self.commit_open_cell_editor():
            return
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

        self.close_without_prompt()

    def _update_save_ui_labels(self) -> None:
        """Update Save/Sync labels in UI based on data source type."""
        save_label = self._get_save_label()
        # The window was opened to Sync something staged elsewhere, so the button closes it too.
        what = f"{save_label} and Close" if self._close_after_sync else f"{save_label} All"

        if hasattr(self, "_file_menu") and hasattr(self, "_save_menu_index"):
            try:
                self._file_menu.entryconfig(self._save_menu_index, label=what)
            except Exception:
                pass

        if hasattr(self, "save_btn"):
            self.save_btn.configure(text=f"💾 {what}")

    def _on_undo(self) -> None:
        """Handle Ctrl+Z - undo last change (not while a cell is being edited)."""
        if self._cell_editor_is_open():
            return
        if self._store.undo():
            desc = self._store.get_redo_description()
            self.status_var.set(f"Undid: {desc}" if desc else "Undone")
            self._update_status()

    def _on_redo(self) -> None:
        """Handle Ctrl+Y - redo last undone change (not while a cell is being edited)."""
        if self._cell_editor_is_open():
            return
        if self._store.redo():
            desc = self._store.get_undo_description()
            self.status_var.set(f"Redid: {desc}" if desc else "Redone")
            self._update_status()

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
        # _update_save_ui_labels() relabels this item once the data has loaded.
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
        self._edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=self._edit_menu)

        self._edit_menu.add_command(label="Undo", command=self._on_undo, accelerator="Ctrl+Z")
        self._edit_menu.add_command(label="Redo", command=self._on_redo, accelerator="Ctrl+Y")
        self._edit_menu.add_separator()
        self._edit_menu.add_command(label="Fill Down", command=self._on_fill_down_clicked)
        self._edit_menu.add_command(
            label="Clone Structure...", command=self._on_clone_structure_clicked
        )

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)

        self._filter_enabled_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(
            label="Filter Enabled",
            variable=self._filter_enabled_var,
            command=self._on_filter_toggle,
            accelerator="Ctrl+Space",
        )
        view_menu.add_separator()

        self._tag_browser_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(
            label="Tag Browser",
            variable=self._tag_browser_var,
            command=self._toggle_nav,
        )

    def _on_filter_toggle_key(self, event=None) -> str:
        """Handle Ctrl+Space keyboard shortcut to toggle filter."""
        # The View menu's check mark follows the variable.
        self._filter_enabled_var.set(not self._filter_enabled_var.get())
        self._on_filter_toggle()
        return "break"  # Prevent event propagation

    def _create_widgets(self) -> None:
        """Create all window widgets."""
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # The sidebar's buttons scroll the current tab to a memory type's section.
        self.sidebar = JumpSidebar(
            main_frame,
            on_type_select=self._on_type_selected,
            on_address_jump=self._on_address_jump,
            address_store=self._store,
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0), pady=5)

        # The Tag Browser is a separate window, so this frame fills the rest of the window.
        center_frame = ttk.Frame(main_frame)
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.notebook = CustomNotebook(
            center_frame,
            on_close_callback=self._on_tab_close_request,
        )
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        footer = ttk.Frame(center_frame)
        footer.pack(fill=tk.X, pady=(5, 0))

        self.add_block_btn = ttk.Button(
            footer,
            text="+ Add Block",
            command=self._on_block_button_clicked,
            state="disabled",
        )
        self.add_block_btn.pack(side=tk.LEFT)
        self._create_tooltip(self.add_block_btn, "Select rows to define block")

        self.fill_down_btn = ttk.Button(
            footer,
            text="↓ Fill Down",
            command=self._on_fill_down_clicked,
            state="disabled",
        )
        self.fill_down_btn.pack(side=tk.LEFT, padx=(5, 0))
        self._create_tooltip(
            self.fill_down_btn,
            "Select a row whose nickname has a number, and the empty rows of the same\n"
            "type below it. Fill Down numbers them: Alm1 → Alm2, Alm3.",
        )

        self.clone_btn = ttk.Button(
            footer,
            text="⧉ Clone",
            command=self._on_clone_structure_clicked,
            state="disabled",
        )
        self.clone_btn.pack(side=tk.LEFT, padx=(5, 0))
        self._create_tooltip(
            self.clone_btn,
            "Select rows where at least one nickname has a number.\n"
            "Clone copies them into the empty rows below.",
        )

        # _update_save_ui_labels() relabels this button once the data has loaded.
        self.save_btn = ttk.Button(footer, text="💾 Save All", command=self._save_all)
        self.save_btn.pack(side=tk.RIGHT)

    def _load_initial_data(self) -> None:
        """Load initial data from the database."""
        try:
            if not self._store.is_initialized():
                self._store.load_initial_data()

            # Start file monitoring (uses master window for after() calls)
            self._store.start_file_monitoring(self.master)

            self.status_var.set(f"Connected - {len(self._store.all_nicknames)} nicknames loaded")

            self._update_save_ui_labels()

            self._create_new_tab(clone_from=None)

        except Exception as e:
            messagebox.showerror(
                "Address Editor",
                f"Could not read the addresses. The Address Editor will close.\n\n{e}",
            )
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

        # The tips are about CLICK's database. They wait until an editor opens on it.
        if flag_path.exists() or not self._is_using_mdb():
            return

        popup_text = (
            "Address Editor\n\n"
            "Sync writes your edits to CLICK's temporary database. "
            "Save the project in CLICK to keep them.\n\n"
            "To undo every synced edit, close CLICK without saving."
        )

        messagebox.showinfo("First-Time Tips", popup_text, parent=self)

        # Mark as shown so we don't bother the user again
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()

    def _get_window_title(self) -> str:
        """Generate window title based on Click project and data source."""
        base_title = "ClickNick Address Editor"

        parts = [base_title]

        click_filename = self._get_click_filename()
        if click_filename:
            parts.append(click_filename)

        try:
            file_path = self._store._data_source.file_path
            if file_path:
                filename = Path(file_path).name
                parts.append(filename)
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
        session: DataSession,
        get_click_filename: Callable[[], str] = lambda: "",
        get_analysis_service: Callable[[], object | None] = lambda: None,
        on_synced: Callable[[set[int]], None] | None = None,
        get_synced_pending: Callable[[], int] = lambda: 0,
        close_after_sync: bool = False,
    ):
        """Initialize the Address Editor window.

        Args:
            parent: Parent widget (main app window)
            session: DataSession holding the AddressStore this window edits
            get_click_filename: Returns the filename of the project that CLICK has open
                (e.g., "MyProject.ckp").
            get_analysis_service: Returns the connection's AnalysisService, or None if there
                is none. The filter prefixes that read the program, such as `input:` and
                `upstream:`, need it.
            on_synced: Called with the saved addr_keys after a successful save.
            get_synced_pending: Count of tags synced to CLICK but not yet saved there.
            close_after_sync: True if the window was opened to Sync edits staged elsewhere.
                Its Sync button then reads "Sync and Close" and closes the window after a
                successful Sync.
        """
        super().__init__(parent)

        self._session = session
        self._store = session.store
        self._get_click_filename = get_click_filename
        self._get_analysis_service = get_analysis_service
        self._on_synced = on_synced
        self._get_synced_pending = get_synced_pending
        self._close_after_sync = close_after_sync
        self.title(self._get_window_title())
        self.geometry("1025x700")

        # Maps each tab's widget name to its panel and state.
        self._tabs: dict[str, tuple[AddressPanel, TabState]] = {}
        self._tab_counter = 0  # For generating unique tab names
        self._nav_window: NavWindow | None = None

        self._create_menu()
        self._create_widgets()
        self._load_initial_data()
        self._show_address_editor_popup()

        self._store.add_observer(self._on_address_store_changed)

        # Register with the session, which closes all windows when data is replaced.
        session.register_editor(self)

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Keyboard shortcuts
        self.bind("<Control-s>", lambda e: self._save_all())
        self.bind("<Control-S>", lambda e: self._save_all())
        self.bind("<Control-t>", lambda e: self._on_new_tab_clicked())
        self.bind("<Control-T>", lambda e: self._on_new_tab_clicked())
        self.bind("<Control-w>", lambda e: self._close_current_tab())
        self.bind("<Control-W>", lambda e: self._close_current_tab())
        self.bind("<Control-space>", self._on_filter_toggle_key)
        self.bind("<Control-z>", lambda e: self._on_undo())
        self.bind("<Control-Z>", lambda e: self._on_undo())
        self.bind("<Control-y>", lambda e: self._on_redo())
        self.bind("<Control-Y>", lambda e: self._on_redo())

        # Open Tag Browser by default
        self._init_after_id = self.after(100, self._toggle_nav)

    def refresh_title(self) -> None:
        """Update the window title. The app calls this when CLICK opens a different project."""
        self.title(self._get_window_title())

    def commit_open_cell_editor(self) -> bool:
        """Commit the text typed in any open cell editor, as an ordinary edit.

        DataSession calls this before it closes the window or replaces its data.

        If an editor is still open afterwards, warn the user and return False. Otherwise
        return True. tksheet commits nothing while the application does not have focus, so
        this method takes focus and tries a second time.
        """
        for panel, *_ in self._tabs.values():
            mt = panel.sheet.MT
            if not mt.text_editor.open:
                continue
            mt.mouseclick_outside_editor_or_dropdown_all_canvases()
            if mt.text_editor.open:
                self.focus_force()
                mt.mouseclick_outside_editor_or_dropdown_all_canvases()
            if mt.text_editor.open:
                messagebox.showwarning(
                    "Cell Being Edited",
                    "A cell is still being edited. Press Enter to keep the edit or Esc to "
                    "cancel it, then try again.",
                    parent=self,
                )
                return False
        return True

    def close_without_prompt(self) -> None:
        """Clean up resources and destroy window without save prompts."""
        if self._init_after_id is not None:
            self.after_cancel(self._init_after_id)
            self._init_after_id = None

        if self._nav_window is not None:
            self._nav_window.destroy()
            self._nav_window = None

        self._store.remove_observer(self._on_address_store_changed)
        self._session.unregister_editor(self)

        self.destroy()

    def _raise_and_focus(self) -> None:
        """Show the editor window, raise it above other windows and give it keyboard focus."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def apply_row_filter(self, row_filter: str) -> None:
        """Set the current tab's row filter (e.g. 'changed') and bring the window to the front.

        ``clicknick-cli tag apply`` calls this to show the user the rows that it changed.
        This method also clears the text filter, so that the text filter hides none of them.
        """
        panel = self._get_current_panel()
        if panel is None:
            return
        panel.filter_enabled_var.set(False)
        panel.filter_var.set("")
        panel.row_filter_var.set(row_filter)
        panel._apply_filters()

        # Tk may not map a new Toplevel until it is idle. Windows can ignore a request to
        # activate the window before then.
        self.after_idle(self._raise_and_focus)

    def refresh_sync_status(self) -> None:
        """Redraw the status bar after the synced-tags count changed."""
        self._update_status()
