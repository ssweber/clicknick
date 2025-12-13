"""Main window for the Address Editor.

Multi-panel editor for viewing, creating, and editing PLC address nicknames.
Mimics the Click PLC Address Picker UI with sidebar navigation.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .address_panel import AddressPanel
from .mdb_operations import MdbConnection, load_all_nicknames
from .shared_data import SharedAddressData

# Define panel types available in sidebar
SIDEBAR_TYPES = [
    "X",
    "Y",
    "C",
    "T/TD",  # Combined T + TD
    "CT/CTD",  # Combined CT + CTD
    "SC",
    "DS",
    "DD",
    "DH",
    "DF",
    "XD",
    "YD",
    "SD",
    "TXT",
]

# Types that show combined/interleaved data
COMBINED_TYPES = {
    "T/TD": ["T", "TD"],  # Timer panel shows T and TD interleaved
    "CT/CTD": ["CT", "CTD"],  # Counter panel shows CT and CTD interleaved
}

# Address range jump points for types with large ranges
ADDRESS_JUMPS = {
    "X": [1, 101, 201, 301, 401, 501, 601, 701, 801],
    "Y": [1, 101, 201, 301, 401, 501, 601, 701, 801],
    "C": [1, 501, 1001, 1501],
    "T/TD": [1, 101, 201, 301, 401],
    "CT/CTD": [1, 101, 201, 301, 401],
    "SC": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
    "DS": [1, 501, 1001, 1501, 2001, 2501, 3001, 3501, 4001],
    "DD": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
    "DH": [1, 101, 201, 301, 401],
    "DF": [1, 101, 201, 301, 401],
    "SD": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
    "TXT": [1, 101, 201, 301, 401, 501, 601, 701, 801, 901],
}


class TypeButton(ttk.Frame):
    """A button for selecting a memory type, with optional submenu for address jumps."""

    def _on_jump_selected(self, address: int) -> None:
        """Handle jump address selection."""
        # Panel is already selected, just jump to address
        if self.on_jump:
            self.on_jump(self.type_name, address)

    def _build_nested_submenu(
        self,
        menu: tk.Menu,
        display_type: str,
        start_addr: int,
        end_addr: int,
    ) -> None:
        """Build submenu with 100-increment entries between start and end.

        Args:
            menu: Parent menu to add cascade to
            display_type: Type prefix for labels (e.g., "DS", "C")
            start_addr: Starting address for this submenu
            end_addr: End address (exclusive)
        """
        submenu = tk.Menu(menu, tearoff=0)

        # Add 100-increment addresses
        addr = start_addr
        while addr < end_addr:
            label = f"{display_type}{addr}"
            submenu.add_command(
                label=label,
                command=lambda a=addr: self._on_jump_selected(a),
            )
            addr += 100

        menu.add_cascade(label=f"{display_type}{start_addr}", menu=submenu)

    def _add_blocks_menu(self, menu: tk.Menu, display_type: str) -> None:
        """Add Blocks entry to menu if there are headers.

        Args:
            menu: Menu to add blocks to
            display_type: Type prefix for labels (e.g., "DS", "C")
        """
        if not self.get_headers_callback:
            return

        headers = self.get_headers_callback()
        if not headers:
            return

        # Sort headers by address
        headers = sorted(headers, key=lambda x: x[0])

        menu.add_separator()

        if len(headers) <= 5:
            # Add directly to menu
            menu.add_command(label="Blocks", state="disabled")
            for addr, header_name in headers:
                label = f"  {header_name} ({display_type}{addr})"
                menu.add_command(
                    label=label,
                    command=lambda a=addr: self._on_jump_selected(a),
                )
        else:
            # Use submenu for >5 blocks
            blocks_submenu = tk.Menu(menu, tearoff=0)
            for addr, header_name in headers:
                label = f"{header_name} ({display_type}{addr})"
                blocks_submenu.add_command(
                    label=label,
                    command=lambda a=addr: self._on_jump_selected(a),
                )
            menu.add_cascade(label="Blocks", menu=blocks_submenu)

    def _show_jump_menu(self) -> None:
        """Show submenu for address jumps, including headers."""
        menu = tk.Menu(self, tearoff=0)

        display_type = self.type_name.split("/")[0]

        # Types that use nested submenus with 100-increments
        nested_types = {"DS", "C"}

        if self.type_name in nested_types:
            for i, start_addr in enumerate(self.jump_addresses):
                # Determine end address (next jump point or end of range)
                if i + 1 < len(self.jump_addresses):
                    end_addr = self.jump_addresses[i + 1]
                else:
                    end_addr = start_addr + 500  # Last segment gets 500 more

                self._build_nested_submenu(menu, display_type, start_addr, end_addr)

            # Add blocks at the bottom
            self._add_blocks_menu(menu, display_type)
        else:
            # Standard handling for other types - flat list
            for addr in self.jump_addresses:
                label = f"{display_type}{addr}"
                menu.add_command(
                    label=label,
                    command=lambda a=addr: self._on_jump_selected(a),
                )

            # Add blocks at the bottom
            self._add_blocks_menu(menu, display_type)

        # Position menu next to the button
        x = self.button.winfo_rootx() + self.button.winfo_width()
        y = self.button.winfo_rooty()
        menu.post(x, y)

    def _on_click(self) -> None:
        """Handle main button click - select panel and show jump menu if applicable."""
        # Always select this type first
        self.on_select(self.type_name)

        # Show jump menu if this type has jumps (XD and YD don't)
        if self.jump_addresses or self.get_headers_callback:
            self._show_jump_menu()

    def __init__(
        self,
        parent: tk.Widget,
        type_name: str,
        on_select: callable,
        on_jump: callable | None = None,
        jump_addresses: list[int] | None = None,
        get_headers_callback: callable | None = None,
    ):
        super().__init__(parent)

        self.type_name = type_name
        self.on_select = on_select
        self.on_jump = on_jump
        self.jump_addresses = jump_addresses or []
        self.get_headers_callback = get_headers_callback

        self._selected = False
        self._status_indicator = ""  # Current status indicator text

        # Main button - clicking opens panel AND shows jump menu (if applicable)
        self.button = ttk.Button(
            self,
            text=type_name,
            width=11,  # Full width since no arrow button
            command=self._on_click,
        )
        self.button.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _update_button_text(self) -> None:
        """Update button text to include status indicator."""
        if self._status_indicator:
            self.button.configure(text=f"{self.type_name} {self._status_indicator}")
        else:
            self.button.configure(text=self.type_name)

    def set_selected(self, selected: bool) -> None:
        """Set the visual selected state."""
        self._selected = selected
        # Use a different style or relief to show selection
        if selected:
            self.button.configure(style="Selected.TButton")
        else:
            self.button.configure(style="TButton")

    def update_status(self, modified_count: int, error_count: int) -> None:
        """Update the status indicator based on modified/error counts.

        Args:
            modified_count: Number of unsaved changes for this type
            error_count: Number of validation errors for this type
        """
        if error_count > 0:
            self._status_indicator = "⚠"
        elif modified_count > 0:
            self._status_indicator = "💾"
        else:
            self._status_indicator = ""
        self._update_button_text()


class TypeSidebar(ttk.Frame):
    """Sidebar with type selection buttons."""

    def _get_headers_for_type(self, type_name: str) -> list[tuple[int, str]]:
        """Get header addresses for a type from shared data.

        Args:
            type_name: The type name (may be combined like "T/TD")

        Returns:
            List of (address, header_name) tuples
        """
        if not self.shared_data:
            return []

        # Handle combined types (T/TD, CT/CTD)
        if type_name in COMBINED_TYPES:
            headers = []
            for sub_type in COMBINED_TYPES[type_name]:
                headers.extend(self.shared_data.get_header_addresses(sub_type))
            return sorted(headers, key=lambda x: x[0])

        return self.shared_data.get_header_addresses(type_name)

    def _create_buttons(self) -> None:
        """Create all type buttons."""
        # Create a custom style for selected buttons
        style = ttk.Style()
        style.configure("Selected.TButton", background="#4a90d9")

        for type_name in SIDEBAR_TYPES:
            jump_addrs = ADDRESS_JUMPS.get(type_name)

            # Create callback for getting headers for this type
            # Use default argument to capture type_name in closure
            def make_header_callback(t=type_name):
                return lambda: self._get_headers_for_type(t)

            btn = TypeButton(
                self,
                type_name,
                on_select=self.on_type_select,
                on_jump=self.on_address_jump,
                jump_addresses=jump_addrs,
                get_headers_callback=make_header_callback(),
            )
            btn.pack(fill=tk.X, padx=2, pady=1)
            self.buttons[type_name] = btn

    def __init__(
        self,
        parent: tk.Widget,
        on_type_select: callable,
        on_address_jump: callable,
        shared_data=None,
    ):
        super().__init__(parent, width=140)
        self.pack_propagate(False)  # Maintain fixed width

        self.on_type_select = on_type_select
        self.on_address_jump = on_address_jump
        self.shared_data = shared_data
        self.buttons: dict[str, TypeButton] = {}

        self._create_buttons()

    def set_selected(self, type_name: str) -> None:
        """Update which button appears selected."""
        for name, btn in self.buttons.items():
            btn.set_selected(name == type_name)

    def update_all_indicators(self) -> None:
        """Update status indicators on all buttons from shared data."""
        if not self.shared_data:
            return

        for type_name, btn in self.buttons.items():
            modified = self.shared_data.get_modified_count_for_type(type_name)
            errors = self.shared_data.get_error_count_for_type(type_name)
            btn.update_status(modified, errors)


class AddressEditorWindow(tk.Toplevel):
    """Main window for the Address Editor."""

    def _get_connection(self) -> MdbConnection:
        """Create a fresh database connection.

        Returns:
            Connected MdbConnection instance

        Raises:
            Exception: If connection fails
        """
        conn = MdbConnection.from_click_window(self.click_pid, self.click_hwnd)
        conn.connect()
        return conn

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

    def _handle_nickname_changed(self, addr_key: int, old_nick: str, new_nick: str) -> None:
        """Handle nickname change from any panel."""
        # Update shared data registry
        self.shared_data.update_nickname(addr_key, old_nick, new_nick)

        # Revalidate all local panels
        for panel in self.panels.values():
            panel.revalidate()
        self._update_status()

        # Notify other windows
        # Set flag to avoid double-processing when we get notified back
        self._ignore_next_notification = True
        self.shared_data.notify_data_changed()

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
                panel._apply_filters()
            else:
                # Load from database and store in shared data
                with self._get_connection() as conn:
                    # Refresh nicknames
                    self.all_nicknames = load_all_nicknames(conn)
                    self.shared_data.all_nicknames = self.all_nicknames

                    panel.load_data(conn, self.all_nicknames)

                # Store rows in shared data for other windows
                self.shared_data.set_rows(type_name, panel.rows)

            self.panels[type_name] = panel
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
                panel._refresh_sheet()

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
        self.sidebar = TypeSidebar(
            main_frame,
            on_type_select=self._on_type_selected,
            on_address_jump=self._on_address_jump,
            shared_data=self.shared_data,
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 0), pady=5)

        # Right side container
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Panel container (where address panels go) - now at top
        self.panel_container = ttk.Frame(right_frame)
        self.panel_container.pack(fill=tk.BOTH, expand=True)

        # Footer toolbar at bottom of right side
        footer = ttk.Frame(right_frame)
        footer.pack(fill=tk.X, pady=(5, 0))

        # Refresh button
        ttk.Button(footer, text="⟳ Refresh", command=self._refresh_all).pack(side=tk.LEFT)

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

        Called when another window modifies the shared data.
        Refreshes all panels to show the updated data.
        """
        # Skip if this notification was triggered by our own change
        if getattr(self, "_ignore_next_notification", False):
            self._ignore_next_notification = False
            return

        # Update local reference to nicknames
        self.all_nicknames = self.shared_data.all_nicknames

        # Refresh all panels
        for panel in self.panels.values():
            panel._all_nicknames = self.all_nicknames
            panel.revalidate()

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
        self.geometry("1000x700")

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
