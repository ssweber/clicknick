"""Main window for the Dataview Editor.

Provides a file list sidebar and tabbed interface for editing DataViews.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from pyclickplc import ConnectionState, ModbusService
from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import INTERLEAVED_PAIRS

from ...data.shared_dataview import SharedDataviewData
from ...widgets.custom_notebook import CustomNotebook
from ...widgets.new_dataview_dialog import NewDataviewDialog
from ...widgets.nickname_combobox import NicknameCombobox
from ..nav_window.window import NavWindow
from .panel import DataviewPanel

if TYPE_CHECKING:
    pass


PlcValue = bool | int | float | str


class DataviewEditorWindow(tk.Toplevel):
    """Main window for the Dataview Editor.

    Features:
    - Left sidebar: List of CDV files in the project's DataView folder
    - Right panel: Notebook with tabs for open dataviews
    - Menu bar: File operations (New, Open, Save, Export)
    """

    def _setup_window(self) -> None:
        """Configure window properties."""
        base_title = "ClickNick Dataview Editor"
        if self.title_suffix:
            self.title(f"{base_title} - {self.title_suffix}")
        else:
            self.title(base_title)

        self.geometry("900x600")
        self.minsize(600, 400)

    def _refresh_file_list(self) -> None:
        """Refresh the file list from the dataview folder."""
        self.file_listbox.delete(0, tk.END)

        files = self.shared_data.get_cdv_files()
        for file_path in files:
            self.file_listbox.insert(tk.END, file_path.stem)

        # Store paths for lookup
        self._file_paths = files

    def _get_current_panel(self) -> DataviewPanel | None:
        """Get the currently active panel."""
        try:
            current = self.notebook.select()
            if current:
                return self.notebook.nametowidget(current)
        except tk.TclError:
            pass
        return None

    def _update_tab_title(self, panel: DataviewPanel) -> None:
        """Update the tab title for a panel."""
        for i in range(self.notebook.index("end")):
            if self.notebook.nametowidget(self.notebook.tabs()[i]) == panel:
                title = panel.name
                if panel.is_dirty:
                    title = f"*{title}"
                self.notebook.tab(i, text=title)
                break

    def _on_panel_modified(self) -> None:
        """Handle panel modification event."""
        panel = self._get_current_panel()
        if panel:
            self._update_tab_title(panel)

    def _iter_open_panels(self) -> list[DataviewPanel]:
        """Return panel widgets currently attached to notebook tabs."""
        panels: list[DataviewPanel] = []
        try:
            for tab_id in self.notebook.tabs():
                panel = self.notebook.nametowidget(tab_id)
                if isinstance(panel, DataviewPanel):
                    panels.append(panel)
        except tk.TclError:
            pass
        return panels

    def _is_modbus_connected(self) -> bool:
        return self._connection_state == ConnectionState.CONNECTED

    def _set_modbus_state_text(self, text: str) -> None:
        self._modbus_state_var.set(text)

    def _set_modbus_error_text(self, text: str = "") -> None:
        self._modbus_error_var.set(text)

    def _update_modbus_controls(self) -> None:
        """Refresh connection/write control state."""
        connected = self._is_modbus_connected()
        connecting = self._connection_state == ConnectionState.CONNECTING
        busy = self._modbus_busy
        write_busy = self._modbus_write_busy
        action_busy = busy or write_busy

        self._modbus_toggle_var.set("Disconnect" if connected else "Connect")
        self.write_checked_button.config(
            state=(tk.NORMAL if connected and not action_busy else tk.DISABLED)
        )
        self.write_all_button.config(
            state=(tk.NORMAL if connected and not action_busy else tk.DISABLED)
        )
        self.modbus_connect_button.config(
            state=(tk.DISABLED if connecting or action_busy else tk.NORMAL)
        )
        self.host_entry.config(
            state=(tk.DISABLED if connected or connecting or action_busy else tk.NORMAL)
        )
        self.port_entry.config(
            state=(tk.DISABLED if connected or connecting or action_busy else tk.NORMAL)
        )

        if hasattr(self, "connection_menu"):
            self.connection_menu.entryconfig(
                "Connect", state=(tk.DISABLED if connected or action_busy else tk.NORMAL)
            )
            self.connection_menu.entryconfig(
                "Disconnect", state=(tk.NORMAL if connected and not action_busy else tk.DISABLED)
            )

    @staticmethod
    def _run_background(target, *args) -> None:
        """Run a Modbus action in a daemon worker thread."""
        threading.Thread(target=target, args=args, daemon=True).start()

    def _schedule_ui(self, callback: Callable[[], None]) -> None:
        """Schedule callback on Tk thread; ignore if window is already destroyed."""
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _run_modbus_action(
        self,
        action: Callable[[], object | None],
        on_complete: Callable[[object | None, Exception | None], None],
    ) -> None:
        """Execute blocking Modbus action off UI thread and marshal completion to Tk."""

        def _worker() -> None:
            result: object | None = None
            error: Exception | None = None
            try:
                result = action()
            except Exception as exc:
                error = exc
            self._schedule_ui(lambda: on_complete(result, error))

        self._run_background(_worker)

    def _apply_modbus_state(self, state: ConnectionState, error: Exception | None) -> None:
        self._connection_state = state

        if state == ConnectionState.CONNECTING:
            self._set_modbus_state_text("Connecting...")
        elif state == ConnectionState.CONNECTED:
            self._set_modbus_state_text("Connected")
            self._set_modbus_error_text("")
        elif state == ConnectionState.ERROR:
            self._set_modbus_state_text("Error")
        else:
            self._set_modbus_state_text("Disconnected")

        if error is not None:
            self._set_modbus_error_text(str(error))

        self._update_modbus_controls()

    def _on_modbus_state_callback(self, state: ConnectionState, error: Exception | None) -> None:
        """Background thread callback from ModbusService."""
        self._schedule_ui(lambda: self._apply_modbus_state(state, error))

    def _apply_modbus_values(self, values: Mapping[str, PlcValue]) -> None:
        panel = self._get_current_panel()
        if panel is not None:
            panel.update_live_values(values)

    def _on_modbus_values_callback(self, values: Mapping[str, PlcValue]) -> None:
        """Background thread callback from ModbusService."""
        self._schedule_ui(lambda: self._apply_modbus_values(values))

    def _ensure_modbus_service(self) -> ModbusService:
        """Create ModbusService on first use."""
        if self._modbus is None:
            self._modbus = ModbusService(
                on_state=self._on_modbus_state_callback,
                on_values=self._on_modbus_values_callback,
            )
        return self._modbus

    def _sync_poll_addresses_from_active_tab(self, *, force: bool = False) -> None:
        """Replace service poll list from the currently active tab."""
        if self._modbus is None:
            return
        if not force and not self._is_modbus_connected():
            return

        panel = self._get_current_panel()
        self._active_panel = panel

        if panel is None:
            self._modbus.clear_poll_addresses()
            return

        addresses = panel.get_poll_addresses()
        if addresses:
            self._modbus.set_poll_addresses(addresses)
        else:
            self._modbus.clear_poll_addresses()

    def _clear_live_values_all_panels(self) -> None:
        for panel in self._iter_open_panels():
            panel.clear_live_values()

    def _on_panel_addresses_changed(self, panel: DataviewPanel) -> None:
        """Refresh poll list when active tab addresses change."""
        if panel is not self._get_current_panel():
            return
        self._sync_poll_addresses_from_active_tab()

    def _parse_host_port(self) -> tuple[str, int] | None:
        host = self._modbus_host_var.get().strip()
        port_text = self._modbus_port_var.get().strip()

        if not host:
            self._set_modbus_error_text("Host is required.")
            return None

        try:
            port = int(port_text)
        except ValueError:
            self._set_modbus_error_text("Port must be an integer.")
            return None

        if not 1 <= port <= 65535:
            self._set_modbus_error_text("Port must be between 1 and 65535.")
            return None

        return host, port

    def _on_connect_modbus_complete(self, error: Exception | None) -> None:
        self._modbus_busy = False
        if error is not None:
            self._connection_state = ConnectionState.ERROR
            self._set_modbus_state_text("Error")
            self._set_modbus_error_text(str(error))
            self._update_modbus_controls()
            return

        self._connection_state = ConnectionState.CONNECTED
        self._set_modbus_state_text("Connected")
        self._set_modbus_error_text("")
        self._sync_poll_addresses_from_active_tab(force=True)
        self._update_modbus_controls()

    def _connect_modbus(self) -> None:
        if self._modbus_busy:
            return

        endpoint = self._parse_host_port()
        if endpoint is None:
            return

        host, port = endpoint
        service = self._ensure_modbus_service()
        self._modbus_busy = True
        self._connection_state = ConnectionState.CONNECTING
        self._set_modbus_state_text("Connecting...")
        self._set_modbus_error_text("")
        self._update_modbus_controls()

        self._run_modbus_action(
            lambda: service.connect(host, port),
            lambda _result, error: self._on_connect_modbus_complete(error),
        )

    @staticmethod
    def _disconnect_modbus_service(service: ModbusService) -> Exception | None:
        error: Exception | None = None
        try:
            service.clear_poll_addresses()
        except Exception as exc:
            error = exc
        try:
            service.disconnect()
        except Exception as exc:
            if error is None:
                error = exc
        return error

    def _on_disconnect_modbus_complete(self, error: Exception | None) -> None:
        self._modbus_busy = False
        self._connection_state = ConnectionState.DISCONNECTED
        self._set_modbus_state_text("Disconnected")
        self._set_modbus_error_text("" if error is None else str(error))
        self._update_modbus_controls()

    def _on_disconnect_modbus_action_complete(
        self,
        result: object | None,
        error: Exception | None,
    ) -> None:
        final_error = error
        if final_error is None and isinstance(result, Exception):
            final_error = result
        self._on_disconnect_modbus_complete(final_error)

    def _disconnect_modbus(self) -> None:
        if self._modbus_busy:
            return
        if self._modbus_write_busy:
            return

        service = self._modbus
        self._modbus_busy = True
        self._set_modbus_state_text("Disconnecting...")
        self._set_modbus_error_text("")
        self._clear_live_values_all_panels()
        self._update_modbus_controls()

        if service is None:
            self._on_disconnect_modbus_complete(None)
            return

        self._run_modbus_action(
            lambda: self._disconnect_modbus_service(service),
            self._on_disconnect_modbus_action_complete,
        )

    def _toggle_modbus_connection(self) -> None:
        if self._is_modbus_connected():
            self._disconnect_modbus()
        else:
            self._connect_modbus()

    def _execute_write_payload(self, rows: list[tuple[str, PlcValue]]):
        if self._modbus is None:
            raise OSError("Not connected")
        return self._modbus.write(rows)

    def _on_write_payload_complete(
        self,
        panel: DataviewPanel,
        results,
        error: Exception | None,
    ) -> None:
        self._modbus_write_busy = False
        if error is not None:
            self._set_modbus_error_text(str(error))
            self._update_modbus_controls()
            return

        results = results or []
        if results and all(result.get("ok") for result in results):
            if panel in self._iter_open_panels():
                panel.clear_write_checks()
            self._set_modbus_error_text("")
        else:
            first_error = next(
                (result.get("error") for result in results if not result.get("ok")), None
            )
            if first_error:
                self._set_modbus_error_text(str(first_error))
        self._update_modbus_controls()

    def _write_payload(self, rows: list[tuple[str, PlcValue]]) -> None:
        panel = self._get_current_panel()
        if (
            panel is None
            or not rows
            or self._modbus is None
            or not self._is_modbus_connected()
            or self._modbus_busy
            or self._modbus_write_busy
        ):
            return

        self._modbus_write_busy = True
        self._set_modbus_error_text("")
        self._update_modbus_controls()
        self._run_modbus_action(
            lambda: self._execute_write_payload(rows),
            lambda result, error: self._on_write_payload_complete(panel, result, error),
        )

    def _write_checked(self) -> None:
        panel = self._get_current_panel()
        if panel is None:
            return
        self._write_payload(panel.get_write_rows())

    def _write_all(self) -> None:
        panel = self._get_current_panel()
        if panel is None:
            return
        self._write_payload(panel.get_write_all_rows())

    def _open_dataview(self, file_path: Path) -> None:
        """Open a dataview file in a new tab.

        Args:
            file_path: Path to the CDV file
        """
        # Check if already open
        if file_path in self._open_panels:
            # Switch to existing tab
            panel = self._open_panels[file_path]
            for i in range(self.notebook.index("end")):
                if self.notebook.nametowidget(self.notebook.tabs()[i]) == panel:
                    self.notebook.select(i)
                    return
            return

        # Create new panel
        panel = DataviewPanel(
            self.notebook,
            file_path=file_path,
            on_modified=self._on_panel_modified,
            on_addresses_changed=self._on_panel_addresses_changed,
            nickname_lookup=self.shared_data.lookup_nickname,
            address_normalizer=self.shared_data.normalize_address,
        )

        # Add tab
        self.notebook.add(panel, text=file_path.stem)
        self.notebook.select(panel)

        self._open_panels[file_path] = panel

    def _new_dataview(self) -> None:
        """Create a new unsaved dataview."""
        # Show dialog to get name
        dialog = NewDataviewDialog(self)
        name = dialog.show()

        if not name:
            return  # User cancelled

        panel = DataviewPanel(
            self.notebook,
            file_path=None,
            on_modified=self._on_panel_modified,
            on_addresses_changed=self._on_panel_addresses_changed,
            nickname_lookup=self.shared_data.lookup_nickname,
            address_normalizer=self.shared_data.normalize_address,
            name=name,
        )

        self.notebook.add(panel, text=name)
        self.notebook.select(panel)

        self._open_panels[None] = panel  # Track with None key

    def _open_file(self) -> None:
        """Open a CDV file via file dialog."""
        initial_dir = self.shared_data.dataview_folder or Path.cwd()

        file_path = filedialog.askopenfilename(
            parent=self,
            title="Open DataView",
            initialdir=initial_dir,
            filetypes=[("DataView files", "*.cdv"), ("All files", "*.*")],
        )

        if file_path:
            self._open_dataview(Path(file_path))

    def _save_as(self) -> None:
        """Save the current dataview to a selected folder."""
        panel = self._get_current_panel()
        if not panel:
            return

        initial_dir = self.shared_data.dataview_folder or Path.cwd()

        # Use folder selection dialog
        folder_path = filedialog.askdirectory(
            parent=self,
            title="Select Folder to Save DataView",
            initialdir=initial_dir,
        )

        if folder_path:
            # Use the panel's name for the filename
            new_path = Path(folder_path) / f"{panel.name}.cdv"

            # Check if file already exists
            if new_path.exists() and new_path != panel.file_path:
                result = messagebox.askyesno(
                    "File Exists",
                    f"'{new_path.name}' already exists. Overwrite?",
                    parent=self,
                )
                if not result:
                    return

            # Update tracking
            old_path = panel.file_path
            if old_path in self._open_panels:
                del self._open_panels[old_path]

            panel.save_as(new_path)
            self._open_panels[new_path] = panel
            self._update_tab_title(panel)

            # Refresh file list if saved to dataview folder
            if (
                self.shared_data.dataview_folder
                and new_path.parent == self.shared_data.dataview_folder
            ):
                self._refresh_file_list()

    def _save_current(self) -> None:
        """Save the current dataview."""
        panel = self._get_current_panel()
        if not panel:
            return

        if panel.file_path:
            panel.save()
            self._update_tab_title(panel)
        else:
            self._save_as()

    def _export(self) -> None:
        """Export the current dataview to a new location."""
        # Same as Save As for now
        self._save_as()

    def _close_tab_at_index(self, tab_index: int) -> None:
        """Close the tab at the given index.

        Args:
            tab_index: Index of the tab to close
        """
        try:
            self.notebook._try_close_tab(tab_index)  # pyright: ignore[reportAttributeAccessIssue]
        except (AttributeError, tk.TclError, IndexError):
            pass

    def _close_current_tab(self) -> None:
        """Close the current tab."""
        try:
            tab_id = self.notebook.select()
            if not tab_id:
                return
            tab_index = self.notebook.index(tab_id)
        except tk.TclError:
            return
        self._close_tab_at_index(tab_index)

    def _clear_selected_rows(self) -> None:
        """Clear selected rows in the current panel."""
        panel = self._get_current_panel()
        if not panel:
            return

        selected = panel.get_selected_rows()
        for row_idx in selected:
            panel.clear_row(row_idx)

    def _refresh_nicknames(self) -> None:
        """Refresh nicknames in all open panels."""
        for panel in self._open_panels.values():
            panel.refresh_nicknames()

    def _on_close(self) -> None:
        """Handle window close."""
        # Check for unsaved changes
        if self.has_unsaved_changes():
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                parent=self,
            )
            if result is None:  # Cancel
                return
            if result:  # Yes - save
                self.save_all()

        # Close navigation window if open
        if self._nav_window is not None:
            self._nav_window.destroy()
            self._nav_window = None

        # Detach Modbus service and clean up on a daemon thread to avoid
        # deadlocking the Tcl interpreter (service callbacks use self.after).
        service = self._modbus
        self._modbus = None
        self._clear_live_values_all_panels()
        if service is not None:
            self._run_background(self._disconnect_modbus_service, service)

        # Unregister from shared data
        self.shared_data.unregister_window(self)

        # Destroy window
        self.destroy()

    def _refresh_navigation(self) -> None:
        """Refresh the navigation window with current data."""
        if self._nav_window is None:
            return

        address_shared = self.shared_data._store
        if address_shared:
            self._nav_window.refresh(address_shared.all_rows)

    def _insert_addresses(self, addresses: list[tuple[str, int]]) -> None:
        """Insert addresses into the current dataview.

        Args:
            addresses: List of (memory_type, address) tuples to insert
        """
        address_shared = self.shared_data._store
        if not address_shared:
            return

        for memory_type, address in addresses:
            addr_key = get_addr_key(memory_type, address)
            row = address_shared.all_rows.get(addr_key)
            if row:
                if not self.add_address_to_current(row.display_address):
                    # No more empty rows available
                    break

    def _on_outline_select(self, path: str, leaves: list[tuple[str, int]]) -> None:
        """Handle outline selection from NavWindow - insert addresses into current dataview.

        For single leaf nodes: inserts one address.
        For folder nodes: inserts all child addresses.

        Args:
            path: Filter prefix (unused for dataview - we always insert)
            leaves: List of (memory_type, address) tuples
        """
        self._insert_addresses(leaves)

    def _on_block_select(self, leaves: list[tuple[str, int]]) -> None:
        """Handle block selection from NavWindow - insert all block addresses.

        For T/CT blocks, offers to include paired TD/CTD addresses (interleaved).

        Args:
            leaves: List of (memory_type, address) tuples for all addresses in the block
        """
        if not leaves:
            return

        # Check if this is a T or CT block (all addresses same type for a block)
        memory_types = {mem_type for mem_type, _ in leaves}

        # If it's a T or CT block, offer to include paired data type (TD/CTD)
        include_paired = False
        paired_type = None
        for mem_type in memory_types:
            # Only prompt for bit types (T, CT), not data types (TD, CTD)
            if mem_type in ("T", "CT"):
                paired_type = INTERLEAVED_PAIRS[mem_type]
                include_paired = messagebox.askyesno(
                    "Include Paired Type",
                    f"Also insert {paired_type} addresses with this {mem_type} block?",
                    parent=self,
                )
                break  # Only one type per block

        # Build address list, interleaving if paired type requested
        if include_paired and paired_type:
            addresses_to_insert = []
            for orig_type, address in leaves:
                addresses_to_insert.append((orig_type, address))
                addresses_to_insert.append((paired_type, address))
        else:
            addresses_to_insert = list(leaves)

        self._insert_addresses(addresses_to_insert)

    def _toggle_nav(self) -> None:
        """Toggle the navigation window visibility."""
        if self._nav_window is None:
            # Create navigation window with double-click insert behavior
            self._nav_window = NavWindow(
                self,
                on_outline_select=self._on_outline_select,
                on_block_select=self._on_block_select,
                on_rename=None,
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

    def _toggle_modbus_toolbar(self) -> None:
        """Toggle Modbus toolbar visibility."""
        if self._modbus_toolbar_var.get():
            self.modbus_toolbar.pack(fill=tk.X, padx=5, pady=(2, 0), before=self.notebook)
        else:
            self.modbus_toolbar.pack_forget()

    def _create_menu(self) -> None:
        """Create the menu bar."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)

        file_menu.add_command(
            label="New Dataview", command=self._new_dataview, accelerator="Ctrl+N"
        )
        file_menu.add_command(label="Open...", command=self._open_file, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self._save_current, accelerator="Ctrl+S")
        file_menu.add_command(label="Export...", command=self._export)
        file_menu.add_separator()
        file_menu.add_command(
            label="Close Tab", command=self._close_current_tab, accelerator="Ctrl+W"
        )
        file_menu.add_separator()
        file_menu.add_command(label="Close Window", command=self._on_close)

        # Bind keyboard shortcuts
        self.bind("<Control-n>", lambda e: self._new_dataview())
        self.bind("<Control-o>", lambda e: self._open_file())
        self.bind("<Control-s>", lambda e: self._save_current())
        self.bind("<Control-w>", lambda e: self._close_current_tab())

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Clear Selected Rows", command=self._clear_selected_rows)
        edit_menu.add_separator()
        edit_menu.add_command(label="Refresh Nicknames", command=self._refresh_nicknames)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Refresh File List", command=self._refresh_file_list)
        view_menu.add_separator()

        # Tag Browser toggle (checkbutton)
        self._tag_browser_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(
            label="Tag Browser",
            variable=self._tag_browser_var,
            command=self._toggle_nav,
        )
        view_menu.add_checkbutton(
            label="Modbus Toolbar",
            variable=self._modbus_toolbar_var,
            command=self._toggle_modbus_toolbar,
        )

        # Connection menu (secondary entry points for toolbar connection actions)
        self.connection_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Connection", menu=self.connection_menu)
        self.connection_menu.add_command(label="Connect", command=self._connect_modbus)
        self.connection_menu.add_command(label="Disconnect", command=self._disconnect_modbus)

    def _open_selected(self) -> None:
        """Open the selected file from the list."""
        selection = self.file_listbox.curselection()
        if not selection:
            return

        idx = selection[0]
        if idx < len(self._file_paths):
            self._open_dataview(self._file_paths[idx])

    def _on_file_double_click(self, event) -> None:
        """Handle double-click on file list."""
        self._open_selected()

    def _on_tab_changed(self, event) -> None:
        """Handle tab change event."""
        current_panel = self._get_current_panel()
        if self._active_panel is not None and self._active_panel is not current_panel:
            self._active_panel.clear_live_values()

        self._active_panel = current_panel
        self._sync_poll_addresses_from_active_tab()

    def _on_tab_close_request(self, tab_index: int) -> bool:
        """Handle close button click on a tab.

        Args:
            tab_index: Index of the tab being closed

        Returns:
            True to allow close, False to cancel
        """
        try:
            tab_id = self.notebook.tabs()[tab_index]
            panel = self.notebook.nametowidget(tab_id)

            # Check for unsaved changes
            if panel.is_dirty:
                result = messagebox.askyesnocancel(
                    "Unsaved Changes",
                    f"'{panel.name}' has unsaved changes. Save before closing?",
                    parent=self,
                )
                if result is None:  # Cancel
                    return False
                if result:  # Yes - save
                    if panel.file_path:
                        panel.save()
                    else:
                        # Need to save as
                        self.notebook.select(tab_index)
                        self._save_as()
                        if panel.is_dirty:  # User cancelled save dialog
                            return False

            # Remove from tracking (cleanup before notebook.forget is called)
            if panel.file_path in self._open_panels:
                del self._open_panels[panel.file_path]
            elif None in self._open_panels and self._open_panels[None] == panel:
                del self._open_panels[None]

            self._pending_closed_panel = panel

            return True

        except (tk.TclError, IndexError):
            return True

    def _on_tab_closed(self, event) -> None:
        """Handle tab closed event (after the tab is removed)."""
        if self._pending_closed_panel is not None:
            self._pending_closed_panel.clear_live_values()
            try:
                self._pending_closed_panel.destroy()
            except Exception:
                pass
            self._pending_closed_panel = None

        self._active_panel = self._get_current_panel()
        self._sync_poll_addresses_from_active_tab()

    def _on_tab_right_click(self, event) -> None:
        """Handle right-click on notebook tab - show close menu."""
        # Identify which tab was clicked
        try:
            clicked_tab = self.notebook.identify(event.x, event.y)
            if clicked_tab != "label":
                return

            # Get the tab index at the click position
            tab_index = self.notebook.index(f"@{event.x},{event.y}")
            if tab_index is None:
                return

            # Create context menu
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label="Close", command=lambda: self._close_tab_at_index(tab_index))
            menu.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def _provide_filtered_nicknames(self, search_text: str) -> list[str]:
        """Data provider for the NicknameCombobox.

        Args:
            search_text: The current search text from the combobox

        Returns:
            List of matching nickname strings
        """
        address_shared = self.shared_data._store
        if not address_shared:
            return []

        search_upper = search_text.strip().upper()

        # Build list of matching nicknames
        matches = []
        for row in address_shared.all_rows.values():
            nickname = row.nickname
            if not nickname:
                continue

            # Match against nickname (contains search)
            if search_upper:
                if search_upper in nickname.upper():
                    matches.append(nickname)
            else:
                matches.append(nickname)

        # Sort and return
        matches.sort()
        return matches

    def _on_nickname_selected(self, nickname: str) -> None:
        """Handle nickname selection from combobox.

        Looks up the address for the nickname and inserts it into the dataview.

        Args:
            nickname: The selected nickname string
        """
        if not nickname:
            return

        address_shared = self.shared_data._store
        if not address_shared:
            return

        # Find the address for this nickname
        for row in address_shared.all_rows.values():
            if row.nickname == nickname:
                self.add_address_to_current(row.display_address)
                self.nickname_combo.reset()
                return

        # Nickname not found - maybe user typed an address directly?
        # Try to add it as-is (will be validated by the panel)
        self.add_address_to_current(nickname)
        self.nickname_combo.reset()

    def _on_insert_button_clicked(self) -> None:
        """Handle Insert button click - finalize current combobox entry."""
        self.nickname_combo.finalize_entry()

    def _create_widgets(self) -> None:
        """Create the main UI widgets."""
        # Main paned window for sidebar + content
        self.paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left sidebar: File list
        sidebar = ttk.Frame(self.paned)
        self.paned.add(sidebar, weight=0)

        ttk.Label(sidebar, text="Project DataViews", font=("TkDefaultFont", 10, "bold")).pack(
            pady=(5, 2), padx=5, anchor=tk.W
        )

        # File listbox with scrollbar
        list_frame = ttk.Frame(sidebar)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.file_listbox = tk.Listbox(list_frame, width=20)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=scrollbar.set)

        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Double-click to open
        self.file_listbox.bind("<Double-1>", self._on_file_double_click)

        # Buttons below file list
        btn_frame = ttk.Frame(sidebar)
        btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))

        ttk.Button(btn_frame, text="New", command=self._new_dataview, width=7).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Open", command=self._open_selected, width=7).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="⟳", command=self._refresh_file_list, width=2).pack(
            side=tk.LEFT, padx=2
        )

        # Right panel: Notebook with tabs
        self.content = ttk.Frame(self.paned)
        self.paned.add(self.content, weight=1)

        # Top toolbar with nickname combobox and insert button
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 0))

        # Nickname entry with NicknameCombobox
        ttk.Label(toolbar, text="Nickname:").pack(side=tk.LEFT, padx=(0, 5))

        # Frame to hold combobox (NicknameCombobox calls master.withdraw())
        self.combobox_frame = ttk.Frame(toolbar)
        self.combobox_frame.pack(side=tk.LEFT, padx=(0, 5))
        # Add dummy withdraw method since Frame doesn't have one
        self.combobox_frame.withdraw = lambda: None

        self.nickname_combo = NicknameCombobox(self.combobox_frame, width=30)
        self.nickname_combo.pack()

        # Configure the combobox callbacks
        self.nickname_combo.set_data_provider(self._provide_filtered_nicknames)
        self.nickname_combo.set_selection_callback(self._on_nickname_selected)

        # Insert button
        ttk.Button(toolbar, text="Insert", command=self._on_insert_button_clicked, width=8).pack(
            side=tk.LEFT, padx=(0, 5)
        )

        # Modbus toolbar (separate row, toggle-able via View menu)
        self.modbus_toolbar = ttk.Frame(self.content)
        self.modbus_toolbar.pack(fill=tk.X, padx=5, pady=(2, 0))

        ttk.Label(self.modbus_toolbar, text="Host:").pack(side=tk.LEFT)
        self.host_entry = ttk.Entry(
            self.modbus_toolbar, textvariable=self._modbus_host_var, width=16
        )
        self.host_entry.pack(side=tk.LEFT, padx=(3, 6))

        ttk.Label(self.modbus_toolbar, text="Port:").pack(side=tk.LEFT)
        self.port_entry = ttk.Entry(
            self.modbus_toolbar, textvariable=self._modbus_port_var, width=6
        )
        self.port_entry.pack(side=tk.LEFT, padx=(3, 6))

        self.modbus_connect_button = ttk.Button(
            self.modbus_toolbar,
            textvariable=self._modbus_toggle_var,
            command=self._toggle_modbus_connection,
            width=10,
        )
        self.modbus_connect_button.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(self.modbus_toolbar, textvariable=self._modbus_state_var).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Label(
            self.modbus_toolbar, textvariable=self._modbus_error_var, foreground="#aa3333"
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.write_checked_button = ttk.Button(
            self.modbus_toolbar,
            text="Write Checked",
            command=self._write_checked,
            width=12,
        )
        self.write_checked_button.pack(side=tk.LEFT, padx=(0, 4))

        self.write_all_button = ttk.Button(
            self.modbus_toolbar,
            text="Write All",
            command=self._write_all,
            width=9,
        )
        self.write_all_button.pack(side=tk.LEFT)

        # Notebook for tabs (with close buttons)
        self.notebook = CustomNotebook(self.content, on_close_callback=self._on_tab_close_request)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Bind tab change and close events
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook.bind("<<NotebookTabClosed>>", self._on_tab_closed)
        self.notebook.bind("<Button-3>", self._on_tab_right_click)

        # Initial sash position (sidebar width)
        self.after(100, lambda: self.paned.sashpos(0, 180))

    @staticmethod
    def _get_dataview_editor_popup_flag() -> Path:
        """Get path to the flag indicating the Dataview Editor popup has been seen."""
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "ClickNick" / "dataview_editor_popup_seen"

    def _show_dataview_editor_popup(self) -> None:
        """Show first-run tips for the Dataview Editor (appears once per user)."""
        flag_path = self._get_dataview_editor_popup_flag()

        if flag_path.exists():
            return

        # Content
        popup_text = (
            "Dataview Editor (Beta)\n\n"
            "This tool edits .cdv files in CLICK's temporary project folder.\n"
            "Changes are temporary until you save in CLICK Software.\n\n"
            "Note: New Dataviews created here must be imported manually in CLICK.\n"
            "Tip: Close CLICK without saving to undo all changes."
        )

        messagebox.showinfo("First-Time Tips", popup_text, parent=self)

        # Mark as shown so we don't bother the user again
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()

    def __init__(
        self,
        parent: tk.Widget,
        shared_data: SharedDataviewData,
        title_suffix: str = "",
    ):
        """Initialize the Dataview Editor window.

        Args:
            parent: Parent widget (usually the main app window)
            shared_data: SharedDataviewData for managing dataviews
            title_suffix: Optional suffix for window title (e.g., project name)
        """
        super().__init__(parent)

        self.shared_data = shared_data
        self.title_suffix = title_suffix

        # Track open panels by file path
        self._open_panels: dict[Path | None, DataviewPanel] = {}
        self._untitled_counter = 0

        # Navigation window
        self._nav_window: NavWindow | None = None
        self._active_panel: DataviewPanel | None = None
        self._pending_closed_panel: DataviewPanel | None = None

        # Modbus integration state
        self._modbus: ModbusService | None = None
        self._modbus_busy = False
        self._modbus_write_busy = False
        self._connection_state = ConnectionState.DISCONNECTED
        self._modbus_host_var = tk.StringVar(value="127.0.0.1")
        self._modbus_port_var = tk.StringVar(value="502")
        self._modbus_toggle_var = tk.StringVar(value="Connect")
        self._modbus_state_var = tk.StringVar(value="Disconnected")
        self._modbus_error_var = tk.StringVar(value="")
        self._modbus_toolbar_var = tk.BooleanVar(value=True)

        # Configure window
        self._setup_window()
        self._create_menu()
        self._create_widgets()

        # Register with shared data
        shared_data.register_window(self)

        # Refresh file list
        self._refresh_file_list()

        # Show first-run popup
        self._show_dataview_editor_popup()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Open Tag Browser by default
        self.after(100, self._toggle_nav)

        self._update_modbus_controls()

    def refresh_nicknames_from_shared(self) -> None:
        """Called by SharedDataviewData when SharedAddressData changes.

        Auto-refreshes nicknames in all open panels when address data is modified.
        """
        self._refresh_nicknames()
        self._refresh_navigation()

    def has_unsaved_changes(self) -> bool:
        """Check if any open dataviews have unsaved changes."""
        return any(panel.is_dirty for panel in self._open_panels.values())

    def save_all(self) -> None:
        """Save all open dataviews that have file paths."""
        for panel in self._open_panels.values():
            if panel.file_path and panel.is_dirty:
                panel.save()
                self._update_tab_title(panel)

    def add_address_to_current(self, address: str) -> bool:
        """Add an address to the currently active dataview.

        Args:
            address: The address to add

        Returns:
            True if added successfully
        """
        panel = self._get_current_panel()
        if panel:
            return panel.add_address(address)
        return False
