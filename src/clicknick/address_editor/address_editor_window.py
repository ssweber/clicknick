"""Main window for the Address Editor.

Multi-panel editor for viewing, creating, and editing PLC address nicknames.
Mimics the Click PLC Address Picker UI with sidebar navigation.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from .add_block_dialog import AddBlockDialog
from .address_model import AddressRow
from .address_panel import AddressPanel
from .block_panel import BlockPanel
from .jump_sidebar import COMBINED_TYPES, JumpSidebar
from .outline_panel import OutlinePanel
from .shared_data import SharedAddressData
from .view_builder import build_type_view


class NavWindow(tk.Toplevel):
    """Floating outline window that docks to the right of the main window."""

    def _dock_to_parent(self) -> None:
        if not self.snap_var.get():
            return

        self.parent_window.update_idletasks()
        px = self.parent_window.winfo_x()
        py = self.parent_window.winfo_y()
        pw = self.parent_window.winfo_width()
        ph = self.parent_window.winfo_height()

        target_x = px + pw + 20
        target_y = py

        current_w = self.winfo_width()
        if current_w < 50:
            current_w = 250

        self.geometry(f"{current_w}x{ph}+{target_x}+{target_y}")

    def _on_parent_configure(self, event) -> None:
        if self.snap_var.get() and event.widget == self.parent_window:
            self.after_idle(self._dock_to_parent)

    def _on_self_configure(self, event) -> None:
        if not self.snap_var.get():
            return
        if not self.parent_window or not self.winfo_exists():
            return

        # Calculate where the Left Edge MUST be
        target_x = self.parent_window.winfo_x() + self.parent_window.winfo_width() + 20
        target_y = self.parent_window.winfo_y()

        # If we have drifted from the dock position (e.g. user dragged left edge)
        # Note: We allow some tolerance (e.g. +/- 1 pixel) or exact match
        if self.winfo_x() != target_x or self.winfo_y() != target_y:
            # Apply position only ("+X+Y"), preserving the current Width/Height
            # This creates the effect that the left edge is locked.
            self.geometry(f"+{target_x}+{target_y}")

    def _toggle_snap(self):
        """
        Update the button icon and perform docking logic.
        Note: The variable and visual relief are handled automatically
        by the ttk.Checkbutton logic.
        """
        # The Checkbutton updates the variable BEFORE calling this command
        if self.snap_var.get():
            # Just became Snapped
            self.snap_btn.configure(text="📌")  # Pin icon
            self._dock_to_parent()
        else:
            # Just became Unsnapped
            self.snap_btn.configure(text="🔗")  # Unlinked icon
            # No need to set relief, 'Toolbutton' style handles it

    def _on_close(self) -> None:
        self.withdraw()
        if hasattr(self.parent_window, "nav_btn"):
            self.parent_window.nav_btn.configure(text="Outline >>")

    def __init__(
        self,
        parent: tk.Toplevel,
        on_address_select: Callable[[str, int], None],
    ):
        """Initialize the navigation window.

        Args:
            parent: Parent window to dock to
            on_address_select: Callback when address is selected (memory_type, address)
        """
        super().__init__(parent)
        self.parent_window = parent
        self.title("Navigation")
        self.resizable(True, True)
        self.transient(parent)

        self.snap_var = tk.BooleanVar(value=True)

        # 1. Notebook for tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # 2. First Tab: Standard Outline
        self.outline_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.outline_frame, text=" Outline ")
        self.outline = OutlinePanel(self.outline_frame, on_address_select)
        self.outline.pack(fill=tk.BOTH, expand=True)

        # 3. Second Tab: Blocks
        self.blocks_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.blocks_frame, text=" Blocks ")
        self.blocks = BlockPanel(self.blocks_frame, on_address_select)
        self.blocks.pack(fill=tk.BOTH, expand=True)

        # 4. Snap Button (Floating on top)
        self.snap_btn = ttk.Checkbutton(
            self,
            text="📌",
            variable=self.snap_var,
            command=self._toggle_snap,
            style="Toolbutton",
            width=2,
        )
        self.snap_btn.place(relx=1.0, y=1, x=-25, anchor="ne")

        self._dock_to_parent()
        parent.bind("<Configure>", self._on_parent_configure, add=True)
        self.bind("<Configure>", self._on_self_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def build_tree(self, all_rows: dict[int, AddressRow]) -> None:
        """Rebuild the tree from address row data.

        Args:
            all_rows: Dict mapping address key to AddressRow
        """
        self.outline.build_tree(all_rows)
        self.blocks.build_tree(all_rows)


class AddressEditorWindow(tk.Toplevel):
    """Main window for the Address Editor."""

    def _update_status(self) -> None:
        """Update the status bar with current state."""
        total_modified = self.shared_data.get_total_modified_count()
        total_errors = self.shared_data.get_total_error_count()

        parts = [f"Panels: {len(self.panels)}"]
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
            self._nav_window.build_tree(self.shared_data.all_rows)

    def _do_revalidation(self) -> None:
        """Perform the actual revalidation (called after debounce delay)."""
        self._revalidate_timer = None

        if not self._pending_revalidate:
            return

        self._pending_revalidate = False

        # Revalidate all local panels
        for panel in self.panels.values():
            panel.revalidate()
        self._update_status()

        # Refresh outline if visible (live update)
        if self._nav_window is not None and self._nav_window.winfo_viewable():
            self._refresh_navigation()

        # Notify other windows (pass self so we skip our own notification)
        self.shared_data.notify_data_changed(sender=self)

    def _schedule_revalidation(self) -> None:
        """Schedule a debounced revalidation of all panels."""
        # Cancel any existing timer
        if self._revalidate_timer is not None:
            self.after_cancel(self._revalidate_timer)

        # Schedule revalidation after 50ms idle
        self._revalidate_timer = self.after(50, self._do_revalidation)

    def _handle_nickname_changed(self, addr_key: int, old_nick: str, new_nick: str) -> None:
        """Handle nickname change from any panel.

        Uses debouncing to batch rapid changes (like Replace All) and avoid
        expensive revalidation for each individual cell change.
        """
        # Update shared data registry immediately
        self.shared_data.update_nickname(addr_key, old_nick, new_nick)

        # Schedule debounced revalidation
        self._pending_revalidate = True
        self._schedule_revalidation()

    def _handle_data_changed(self) -> None:
        """Handle any data change from any panel (comment, init value, retentive)."""
        self._update_status()

        # Notify other windows (pass self so we skip our own notification)
        self.shared_data.notify_data_changed(sender=self)

    def _hide_all_panels(self) -> None:
        """Hide all panels from view."""
        for panel in self.panels.values():
            panel.pack_forget()

    def _get_selected_row_indices(self) -> list[int]:
        """Get selected row indices from the current panel.

        Returns:
            List of display row indices that are selected (sorted).
        """
        if not self.current_type or self.current_type not in self.panels:
            return []

        panel = self.panels[self.current_type]
        sheet = panel.sheet

        # Get selected rows from tksheet (returns set of row indices)
        selected = sheet.get_selected_rows()
        if not selected:
            return []

        return sorted(selected)

    def _update_add_block_button_state(self) -> None:
        """Update the Add Block button enabled state based on row selection."""
        selected = self._get_selected_row_indices()
        if selected:
            self.add_block_btn.configure(state="normal")
        else:
            self.add_block_btn.configure(state="disabled")

    def _bind_panel_selection(self, panel: AddressPanel) -> None:
        """Bind selection change events on a panel's sheet.

        Args:
            panel: The AddressPanel to bind events on
        """
        # Bind to selection events to update Add Block button state
        panel.sheet.bind("<<SheetSelect>>", lambda e: self._update_add_block_button_state())

    def _create_panel(self, type_name: str) -> bool:
        """Create a panel for the given type.

        Returns:
            True if panel was created successfully
        """
        try:
            # Check if this is a combined type
            combined = COMBINED_TYPES.get(type_name)

            panel = AddressPanel(
                self.panel_container,
                type_name,
                combined_types=combined,
                on_nickname_changed=self._handle_nickname_changed,
                on_data_changed=self._handle_data_changed,
                on_close=None,  # No close button in sidebar mode
            )

            # Load from data source if not initialized
            if not self.shared_data.is_initialized():
                self.shared_data.load_initial_data()

            # Get nicknames from shared data
            self.all_nicknames = self.shared_data.all_nicknames

            # Check for existing TypeView (from another window/panel)
            existing_view = self.shared_data.get_view(type_name)

            if existing_view is not None:
                # Use existing shared view - rows are already built
                panel.rows = existing_view.rows
                panel._all_nicknames = self.all_nicknames
                panel._validate_all()
                panel._populate_sheet_data()
                panel._apply_filters()

                # Initialize styler (uses panel's _get_block_colors_for_rows for dynamic updates)
                from .address_row_styler import AddressRowStyler

                panel._styler = AddressRowStyler(
                    sheet=panel.sheet,
                    rows=panel.rows,
                    get_displayed_rows=lambda: panel._displayed_rows,
                    combined_types=panel.combined_types,
                    get_block_colors=panel._get_block_colors_for_rows,
                )
                panel._refresh_display()
            else:
                # Build new view using view_builder
                view = build_type_view(
                    all_rows=self.shared_data.all_rows,
                    type_key=type_name,
                    all_nicknames=self.all_nicknames,
                    combined_types=combined,
                )

                # Store view in shared data for other windows/panels
                self.shared_data.set_view(type_name, view)
                self.shared_data.set_rows(type_name, view.rows)

                # Load panel from view
                panel.rows = view.rows
                panel._all_nicknames = self.all_nicknames
                panel._validate_all()
                panel._populate_sheet_data()
                panel._apply_filters()

                # Initialize styler (uses panel's _get_block_colors_for_rows for dynamic updates)
                from .address_row_styler import AddressRowStyler

                panel._styler = AddressRowStyler(
                    sheet=panel.sheet,
                    rows=panel.rows,
                    get_displayed_rows=lambda: panel._displayed_rows,
                    combined_types=panel.combined_types,
                    get_block_colors=panel._get_block_colors_for_rows,
                )
                panel._refresh_display()

            self.panels[type_name] = panel

            # Bind selection events to update Add Block button state
            self._bind_panel_selection(panel)

            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to create panel: {e}", parent=self)
            import traceback

            traceback.print_exc()
            return False

    def _show_single_panel(self, type_name: str) -> None:
        """Show a single panel, creating it if needed."""
        self._hide_all_panels()

        # Get or create the panel
        if type_name not in self.panels:
            if not self._create_panel(type_name):
                return

        # Show the panel using pack
        self.panels[type_name].pack(fill=tk.BOTH, expand=True)

        self._update_status()

        # Reset Add Block button state (selection cleared on panel switch)
        self._update_add_block_button_state()

    def _on_type_selected(self, type_name: str) -> None:
        """Handle type button click - show/create panel for this type."""
        self.sidebar.set_selected(type_name)
        self.current_type = type_name
        self._show_single_panel(type_name)

    def _on_address_jump(self, type_name: str, address: int) -> None:
        """Handle address jump from submenu."""
        # Panel should already be shown from button click
        if type_name in self.panels:
            # For combined types, figure out which sub-type to scroll to
            if type_name in COMBINED_TYPES:
                # Just scroll to the address, panel will find it
                self.panels[type_name].scroll_to_address(address, align_top=True)
            else:
                self.panels[type_name].scroll_to_address(address, align_top=True)

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

            # Refresh local panels
            for panel in self.panels.values():
                panel._refresh_display()

            self.status_var.set(f"Saved {count} changes")
            messagebox.showinfo("Save", f"Successfully saved {count} changes.", parent=self)

        except Exception as e:
            messagebox.showerror("Save Error", str(e), parent=self)

    def _refresh_all(self) -> None:
        """Refresh all panels from the database."""
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

            # Clear local panels - they'll be recreated when selected
            for panel in self.panels.values():
                panel.destroy()
            self.panels.clear()

            # Update local nicknames reference
            self.all_nicknames = self.shared_data.all_nicknames

            self._update_status()
            self.status_var.set(f"Refreshed - {len(self.all_nicknames)} nicknames loaded")

            # Re-select current type to recreate panel
            if self.current_type:
                self._on_type_selected(self.current_type)

        except Exception as e:
            messagebox.showerror("Refresh Error", str(e), parent=self)

    def _discard_changes(self) -> None:
        """Discard all unsaved changes and reload from database."""
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
            # Discard shared data - this will notify all windows
            self.shared_data.discard_all_changes()

            # Clear local panels - they'll be recreated when selected
            for panel in self.panels.values():
                panel.destroy()
            self.panels.clear()

            # Update local nicknames reference
            self.all_nicknames = self.shared_data.all_nicknames

            self._update_status()
            self.status_var.set("Changes discarded - reloaded from database")

            # Re-select current type to recreate panel
            if self.current_type:
                self._on_type_selected(self.current_type)

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

    def _on_add_block_clicked(self) -> None:
        """Handle Add Block button click."""
        selected_display_rows = self._get_selected_row_indices()
        if not selected_display_rows:
            return

        panel = self.panels[self.current_type]

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

        if first_row_idx == last_row_idx:
            # Single row - self-closing tag
            tag = f"<{block_name}{bg_attr} />"
            existing_comment = first_row.comment
            if existing_comment:
                first_row.comment = f"{tag} {existing_comment}"
            else:
                first_row.comment = tag
        else:
            # Range - opening and closing tags
            open_tag = f"<{block_name}{bg_attr}>"
            close_tag = f"</{block_name}>"

            # Add opening tag to first row
            existing_first = first_row.comment
            if existing_first:
                first_row.comment = f"{open_tag} {existing_first}"
            else:
                first_row.comment = open_tag

            # Add closing tag to last row
            existing_last = last_row.comment
            if existing_last:
                last_row.comment = f"{close_tag} {existing_last}"
            else:
                last_row.comment = close_tag

        # Update the sheet's cell data for modified rows
        panel._update_row_display(first_row_idx)
        if first_row_idx != last_row_idx:
            panel._update_row_display(last_row_idx)

        # Refresh the panel styling
        panel._refresh_display()

        # Notify data changed
        if panel.on_data_changed:
            panel.on_data_changed()

        # Update status
        self._update_status()

    def _on_outline_address_select(self, memory_type: str, address: int) -> None:
        """Handle address selection from outline tree.

        Args:
            memory_type: The memory type (X, Y, C, etc.)
            address: The address number
        """
        # Determine which panel type to show
        # Handle combined types (T/TD, CT/CTD)
        panel_type = memory_type
        for combined, sub_types in COMBINED_TYPES.items():
            if memory_type in sub_types:
                panel_type = combined
                break

        # Switch to the correct panel
        if panel_type != self.current_type:
            self._on_type_selected(panel_type)

        # Scroll to the address
        if panel_type in self.panels:
            self.panels[panel_type].scroll_to_address(address, memory_type)

    def _toggle_nav(self) -> None:
        """Toggle the outline window visibility."""
        if self._nav_window is None:
            # Create outline window
            self._nav_window = NavWindow(
                self,
                on_address_select=self._on_outline_address_select,
            )
            self._refresh_navigation()
            self.nav_btn.configure(text="Navigation <<")
        elif self._nav_window.winfo_viewable():
            # Hide it
            self._nav_window.withdraw()
            self.nav_btn.configure(text="Navigation >>")
        else:
            # Show it
            self._refresh_navigation()
            self._nav_window.deiconify()
            self._nav_window._dock_to_parent()
            self.nav_btn.configure(text="Navigation <<")

    def _create_widgets(self) -> None:
        """Create all window widgets."""
        # Main container
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Status bar at very bottom
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Sidebar on left
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

        # Panel container (where address panels go)
        self.panel_container = ttk.Frame(center_frame)
        self.panel_container.pack(fill=tk.BOTH, expand=True)

        # Footer toolbar at bottom of center
        footer = ttk.Frame(center_frame)
        footer.pack(fill=tk.X, pady=(5, 0))

        # Refresh button
        ttk.Button(footer, text="⟳ Refresh", command=self._refresh_all).pack(side=tk.LEFT)

        # Add Block button (right of Refresh)
        self.add_block_btn = ttk.Button(
            footer,
            text="+ Add Block",
            command=self._on_add_block_clicked,
            state="disabled",
        )
        self.add_block_btn.pack(side=tk.LEFT, padx=(5, 0))
        # Create tooltip for the button
        self._create_tooltip(self.add_block_btn, "Click & drag memory addresses to define block")

        # Outline toggle button
        self.nav_btn = ttk.Button(footer, text="Navigation >>", command=self._toggle_nav)
        self.nav_btn.pack(side=tk.RIGHT, padx=(5, 0))

        # Save button
        self.save_btn = ttk.Button(footer, text="💾 Save All", command=self._save_all)
        self.save_btn.pack(side=tk.RIGHT)

        # Discard button
        ttk.Button(footer, text="🗑 Discard Changes", command=self._discard_changes).pack(
            side=tk.RIGHT, padx=(0, 5)
        )

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

            # Select "X" by default to show a single panel
            self._on_type_selected("X")

        except Exception as e:
            messagebox.showerror("Database Error", str(e))
            self.destroy()

    def _on_shared_data_changed(self, sender: object = None) -> None:
        """Handle notification that shared data has changed.

        Called when another window modifies the shared data, or when
        external changes are detected in the MDB file.
        Refreshes all panels to show the updated data.

        Args:
            sender: The object that triggered the change (if any)
        """
        # Skip if this notification was triggered by our own change
        if sender is self:
            return

        # Update local reference to nicknames
        self.all_nicknames = self.shared_data.all_nicknames

        # Check if views were cleared (e.g., after discard_all_changes)
        # If so, we need to rebuild panel data, not just refresh display
        for type_name, panel in self.panels.items():
            panel._all_nicknames = self.all_nicknames

            if self.shared_data.get_view(type_name) is None:
                # View was cleared - rebuild from fresh data
                from .view_builder import build_type_view

                combined = COMBINED_TYPES.get(type_name)
                view = build_type_view(
                    all_rows=self.shared_data.all_rows,
                    type_key=type_name,
                    all_nicknames=self.all_nicknames,
                    combined_types=combined,
                )
                self.shared_data.set_view(type_name, view)
                self.shared_data.set_rows(type_name, view.rows)

                # Replace panel's rows with fresh ones
                panel.rows = view.rows
                panel._validate_all()
                # Rebuild sheet data from scratch
                panel._populate_sheet_data()
                panel._apply_filters()
                panel._refresh_display()
            else:
                # Normal refresh - just sync display
                panel.refresh_from_external()

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

        self.title("ClickNick Address Editor")
        self.geometry("1025x700")

        self.shared_data = shared_data

        self.panels: dict[str, AddressPanel] = {}  # type_name -> panel
        self.all_nicknames: dict[int, str] = {}
        self.current_type: str = ""
        self._nav_window: NavWindow | None = None

        # Debounce timer for batching nickname changes (e.g., from Replace All)
        self._revalidate_timer: str | None = None
        self._pending_revalidate: bool = False

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

    def _has_errors(self) -> bool:
        """Check if any panel has validation errors."""
        return self.shared_data.has_errors()
