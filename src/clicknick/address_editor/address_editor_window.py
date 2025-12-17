"""Main window for the Address Editor.

Multi-panel editor for viewing, creating, and editing PLC address nicknames.
Mimics the Click PLC Address Picker UI with sidebar navigation.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from .add_block_dialog import AddBlockDialog
from .address_model import AddressRow
from .address_panel import AddressPanel
from .jump_sidebar import COMBINED_TYPES, JumpSidebar
from .mdb_operations import MdbConnection, load_all_addresses
from .outline_panel import OutlinePanel
from .shared_data import SharedAddressData


class OutlineWindow(tk.Toplevel):
    """Floating outline window that docks to the right of the main window."""

    def _dock_to_parent(self) -> None:
        """Position this window to the right of the parent."""
        self.parent_window.update_idletasks()
        px = self.parent_window.winfo_x()
        py = self.parent_window.winfo_y()
        pw = self.parent_window.winfo_width()
        ph = self.parent_window.winfo_height()
        self.geometry(f"250x{ph}+{px + pw + 5}+{py}")

    def _on_parent_configure(self, event) -> None:
        """Re-dock when parent moves or resizes."""
        if event.widget == self.parent_window:
            self.after_idle(self._dock_to_parent)

    def _on_close(self) -> None:
        """Handle close - just hide, don't destroy."""
        self.withdraw()
        if hasattr(self.parent_window, "outline_btn"):
            self.parent_window.outline_btn.configure(text="Outline >>")

    def __init__(
        self,
        parent: tk.Toplevel,
        on_address_select: Callable[[str, int], None],
    ):
        """Initialize the outline window.

        Args:
            parent: Parent window to dock to
            on_address_select: Callback when address is selected (memory_type, address)
        """
        super().__init__(parent)
        self.parent_window = parent

        self.title("Outline")
        self.resizable(True, True)
        self.transient(parent)

        # Embed the OutlinePanel
        self.outline = OutlinePanel(self, on_address_select)
        self.outline.pack_propagate(True)  # Allow resizing in window
        self.outline.pack(fill=tk.BOTH, expand=True)

        self._dock_to_parent()
        parent.bind("<Configure>", self._on_parent_configure, add=True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def build_tree(self, all_rows: dict[int, AddressRow]) -> None:
        """Rebuild the tree from address row data.

        Args:
            all_rows: Dict mapping address key to AddressRow
        """
        self.outline.build_tree(all_rows)


class AddressEditorWindow(tk.Toplevel):
    """Main window for the Address Editor."""

    def _get_connection(self) -> MdbConnection:
        """Create a database connection (use as context manager).

        Returns:
            MdbConnection instance (connects when entering context)

        Raises:
            Exception: If connection fails
        """
        return MdbConnection.from_click_window(self.click_pid, self.click_hwnd)

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

    def _refresh_outline(self) -> None:
        """Refresh the outline tree with current data."""
        if self._outline_window is not None:
            self._outline_window.build_tree(self.shared_data.all_rows)

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
        if self._outline_window is not None and self._outline_window.winfo_viewable():
            self._refresh_outline()

        # Notify other windows
        # Set flag to avoid double-processing when we get notified back
        self._ignore_next_notification = True
        self.shared_data.notify_data_changed()

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

        # Notify other windows
        self._ignore_next_notification = True
        self.shared_data.notify_data_changed()

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

            # Check if shared data already has rows for this type
            # (from another window that already loaded this type)
            existing_rows = self.shared_data.get_rows(type_name)

            if existing_rows is not None:
                # Use existing shared rows
                panel.rows = existing_rows
                panel._all_nicknames = self.shared_data.all_nicknames
                panel._validate_all()
                panel._populate_sheet_data()
                panel._apply_filters()
            else:
                # Load from database if not initialized
                if not self.shared_data.is_initialized():
                    with self._get_connection() as conn:
                        self.shared_data.all_rows = load_all_addresses(conn)
                    self.shared_data._initialized = True

                # Get nicknames from shared data (derived property)
                self.all_nicknames = self.shared_data.all_nicknames

                # Load panel data from preloaded all_rows
                panel.load_data(self.shared_data.all_rows, self.all_nicknames)

                # Store rows in shared data for other windows
                self.shared_data.set_rows(type_name, panel.rows)

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
                self.panels[type_name].scroll_to_address(address)
            else:
                self.panels[type_name].scroll_to_address(address)

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

    def _toggle_outline(self) -> None:
        """Toggle the outline window visibility."""
        if self._outline_window is None:
            # Create outline window
            self._outline_window = OutlineWindow(
                self,
                on_address_select=self._on_outline_address_select,
            )
            self._refresh_outline()
            self.outline_btn.configure(text="Outline <<")
        elif self._outline_window.winfo_viewable():
            # Hide it
            self._outline_window.withdraw()
            self.outline_btn.configure(text="Outline >>")
        else:
            # Show it
            self._refresh_outline()
            self._outline_window.deiconify()
            self._outline_window._dock_to_parent()
            self.outline_btn.configure(text="Outline <<")

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
        self.outline_btn = ttk.Button(footer, text="Outline >>", command=self._toggle_outline)
        self.outline_btn.pack(side=tk.RIGHT, padx=(5, 0))

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

    def _on_shared_data_changed(self) -> None:
        """Handle notification that shared data has changed.

        Called when another window modifies the shared data, or when
        external changes are detected in the MDB file.
        Refreshes all panels to show the updated data.
        """
        # Skip if this notification was triggered by our own change
        if getattr(self, "_ignore_next_notification", False):
            self._ignore_next_notification = False
            return

        # Update local reference to nicknames
        self.all_nicknames = self.shared_data.all_nicknames

        # Refresh all panels - use refresh_from_external to sync sheet cell data
        for panel in self.panels.values():
            panel._all_nicknames = self.all_nicknames
            panel.refresh_from_external()

        # Refresh outline if visible
        if self._outline_window is not None and self._outline_window.winfo_viewable():
            self._refresh_outline()

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
        if self._outline_window is not None:
            self._outline_window.destroy()
            self._outline_window = None

        # Unregister from shared data
        self.shared_data.remove_observer(self._on_shared_data_changed)
        self.shared_data.unregister_window(self)

        self.destroy()

    def __init__(
        self,
        parent: tk.Widget,
        click_pid: int,
        click_hwnd: int,
        shared_data: SharedAddressData | None = None,
    ):
        """Initialize the Address Editor window.

        Args:
            parent: Parent widget (main app window)
            click_pid: Process ID of the CLICK software
            click_hwnd: Window handle of the CLICK software
            shared_data: Optional shared data store for multi-window support.
                         If None, creates its own data store.
        """
        super().__init__(parent)

        self.title("ClickNick Address Editor")
        self.geometry("1025x700")

        self.click_pid = click_pid
        self.click_hwnd = click_hwnd

        # Use shared data if provided, otherwise create our own
        if shared_data is not None:
            self.shared_data = shared_data
            self._owns_shared_data = False
        else:
            self.shared_data = SharedAddressData(click_pid, click_hwnd)
            self._owns_shared_data = True

        self.panels: dict[str, AddressPanel] = {}  # type_name -> panel
        self.all_nicknames: dict[int, str] = {}
        self.current_type: str = ""
        self._ignore_next_notification = False  # Flag to prevent double-processing
        self._outline_window: OutlineWindow | None = None

        # Debounce timer for batching nickname changes (e.g., from Replace All)
        self._revalidate_timer: str | None = None
        self._pending_revalidate: bool = False

        self._create_widgets()
        self._load_initial_data()

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
