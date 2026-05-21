"""Main window for the Dataview Editor.

Provides a file list sidebar and tabbed interface for editing DataViews.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from pyclickplc import ConnectionState, ModbusService, ReconnectConfig
from pyclickplc.addresses import get_addr_key
from pyclickplc.banks import INTERLEAVED_PAIRS

from ...data.shared_dataview import SharedDataviewData
from ...widgets.custom_notebook import CustomNotebook
from ...widgets.new_dataview_dialog import NewDataviewDialog
from ...widgets.nickname_combobox import NicknameCombobox
from ..nav_window.window import NavWindow
from .panel import DataviewPanel

if TYPE_CHECKING:
    from ...services.dap_service import DapService, SimState, TagValues
    from ...services.simulate_service import SimulateResult
    from ..simulate.history_window import HistoryWindow
    from ..simulate.scr_watcher import ScrFileWatcher


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

        self.geometry("800x600")
        self.minsize(800, 400)

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

    def _set_modbus_error_text(self, text: str = "") -> None:
        if text:
            messagebox.showerror("Modbus Error", text, parent=self)

    def _update_modbus_controls(self) -> None:
        """Refresh connection/write control state."""
        connected = self._is_modbus_connected()
        connecting = self._connection_state == ConnectionState.CONNECTING
        busy = self._modbus_busy
        write_busy = self._modbus_write_busy
        action_busy = busy or write_busy

        if connecting:
            self._modbus_toggle_var.set("Connecting…")
        elif connected and busy:
            self._modbus_toggle_var.set("Disconnecting…")
        elif connected:
            self._modbus_toggle_var.set("Disconnect")
        else:
            self._modbus_toggle_var.set("Connect")
        # The Modbus toolbar's Write/Write All only act over Modbus; the
        # Simulation toolbar carries its own copies for DAP patches.
        write_enabled = connected and not action_busy
        self.modbus_write_button.config(state=(tk.NORMAL if write_enabled else tk.DISABLED))
        self.modbus_write_all_button.config(state=(tk.NORMAL if write_enabled else tk.DISABLED))
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
                reconnect=ReconnectConfig(delay_s=0.5, max_delay_s=5.0),
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

    def _sim_address_for_tag(self, tag: str) -> str | None:
        """Resolve a DAP tag name to a Click display address.

        pyrung names each tag after its Click nickname, or after the raw
        address operand when the address has no nickname — so a tag that is not
        a known nickname is resolved by interpreting it as an address.
        """
        if self._sim_result is None:
            return None
        address = self._sim_result.tag_to_address.get(tag)
        if address:
            return address
        normalized = self.shared_data.normalize_address(tag)
        return normalized.upper() if normalized else None

    def _sim_tag_for_address(self, address: str) -> str | None:
        """Resolve a Click address to its DAP tag name.

        A nicknamed address maps to its nickname; an address with no nickname
        is its own tag (pyrung names the tag after the raw operand).
        """
        if self._sim_result is None:
            return None
        canonical = (address or "").strip().upper()
        if not canonical:
            return None
        tag = self._sim_result.address_to_tag.get(canonical)
        if tag:
            return tag
        normalized = self.shared_data.normalize_address(canonical)
        return normalized.upper() if normalized else None

    def _sim_push_live_values(self, tag_values: TagValues | None = None) -> None:
        panel = self._get_current_panel()
        if panel is None or self._sim_result is None:
            return

        if self._dap is not None and tag_values is None:
            tag_values = self._dap.tag_values

        if not tag_values:
            return

        plc_values: dict[str, PlcValue] = {}
        for tag_name, value in tag_values.items():
            address = self._sim_address_for_tag(tag_name)
            if address:
                plc_values[address] = value

        if plc_values:
            panel.update_live_values(plc_values)

    def _on_panel_addresses_changed(self, panel: DataviewPanel) -> None:
        """Refresh poll list when active tab addresses change."""
        if panel is not self._get_current_panel():
            return
        self._sync_poll_addresses_from_active_tab()
        if self.is_simulating:
            self._sim_push_live_values()

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

            self._set_modbus_error_text(str(error))
            self._update_modbus_controls()
            return

        self._connection_state = ConnectionState.CONNECTED
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
        self._set_modbus_error_text("")
        self._update_modbus_controls()

        self._run_modbus_action(
            lambda: service.connect(host, port, timeout=3),
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
            # Transport-level failure — assume connection is lost.
            self._connection_state = ConnectionState.DISCONNECTED
            self._clear_live_values_all_panels()
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

    def _sim_dap_async(self, fn: Callable[[], None]) -> None:
        """Run a blocking DAP call off the Tk thread."""
        threading.Thread(target=fn, daemon=True).start()

    def _sim_clear_panel_checks(self, panel: DataviewPanel | None) -> None:
        if panel is not None and panel in self._iter_open_panels():
            panel.clear_write_checks()

    def _sim_patch_rows(self, rows: list[tuple[str, PlcValue]]) -> None:
        """Apply a one-scan DAP patch for the given (address, value) rows."""
        dap = self._dap
        if dap is None or self._sim_result is None:
            return
        patches: dict[str, PlcValue] = {}
        for address, value in rows:
            tag = self._sim_tag_for_address(address)
            if tag:
                patches[tag] = value
        if not patches:
            return
        panel = self._get_current_panel()

        def _do() -> None:
            resp = dap.patch(patches)
            if resp and resp.get("success") and panel is not None:
                self._schedule_ui(lambda: self._sim_clear_panel_checks(panel))

        self._sim_dap_async(_do)

    def _write_payload(self, rows: list[tuple[str, PlcValue]]) -> None:
        if not rows:
            return

        # In simulation mode a "write" is a one-scan DAP patch.
        if self.is_simulating:
            self._sim_patch_rows(rows)
            return

        panel = self._get_current_panel()
        if (
            panel is None
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

    # -- History watch list --

    def _sim_label_for_tag(self, tag: str) -> str:
        """Resolve a dap tag to its nickname, falling back to address then tag."""
        if self._sim_result is not None:
            address = self._sim_result.tag_to_address.get(tag, "")
            if address:
                result = self.shared_data.lookup_nickname(address)
                if result and result[0]:
                    return result[0]
                return address
        return tag

    def _sim_refresh_watch_chips(self) -> None:
        if self._sim_history is not None:
            items = sorted(self._sim_watched.items(), key=lambda kv: kv[1].lower())
            self._sim_history.panel.set_watch_chips(items)

    def _sim_watch_tag(self, tag: str, label: str) -> None:
        if not tag or tag in self._sim_watched:
            return
        self._sim_watched[tag] = label
        self._sim_refresh_watch_chips()

    def _sim_unwatch_tag(self, tag: str) -> None:
        self._sim_watched.pop(tag, None)
        self._sim_history_last.pop(tag, None)
        self._sim_refresh_watch_chips()

    def _sim_history_on_nickname(self, nickname: str) -> None:
        """History panel nickname picker: resolve and start watching a tag."""
        nickname = (nickname or "").strip()
        if not nickname or self._sim_result is None:
            return
        address: str | None = None
        store = self.shared_data._store
        if store is not None:
            for row in store.all_rows.values():
                if row.nickname == nickname:
                    address = row.display_address
                    break
        if address is None:
            # The user may have typed an address directly.
            tag = self._sim_tag_for_address(nickname)
            if tag:
                self._sim_watch_tag(tag, self._sim_label_for_tag(tag))
            return
        tag = self._sim_tag_for_address(address)
        if tag:
            self._sim_watch_tag(tag, nickname)

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

    def _toggle_sim_history(self) -> None:
        if self._sim_history is None:
            from ..simulate.history_window import HistoryWindow

            self._sim_history = HistoryWindow(
                self,
                nickname_provider=self._provide_filtered_nicknames,
                on_watch_add=self._sim_history_on_nickname,
                on_watch_remove=self._sim_unwatch_tag,
            )
            self._sim_history_var.set(True)
            self._sim_refresh_watch_chips()
        elif self._sim_history.winfo_viewable():
            self._sim_history.withdraw()
            self._sim_history_var.set(False)
        else:
            self._sim_history.deiconify()
            self._sim_history._dock_to_parent()
            self._sim_history_var.set(True)

    def _overlay_columns_visible(self) -> bool:
        """The New Value / Write / Live columns light up while a transport is active."""
        return self._modbus_toolbar_var.get() or self._sim_toolbar_var.get()

    def _sync_overlay_columns(self) -> None:
        """Show the overlay columns on every panel iff a transport toolbar is open."""
        visible = self._overlay_columns_visible()
        for panel in self._iter_open_panels():
            panel.set_overlay_columns_visible(visible)
        # Grow the window once so the extra columns fit; never auto-shrink, so a
        # user's own resizing is preserved.
        if visible and self.winfo_width() < 1100:
            self.geometry(f"1100x{self.winfo_height()}")

    def _apply_panel_overlay(self, panel: DataviewPanel) -> None:
        """Apply the current overlay state to a newly opened panel."""
        panel.set_overlay_columns_visible(self._overlay_columns_visible())
        if self.is_simulating:
            panel.set_live_bool_onoff(True)
            panel.set_forced_addresses(self._sim_forced_addresses)
            self._sim_push_live_values()

    def _on_watch_history_request(self, address: str) -> None:
        """Panel right-click handler: watch the row's tag in the history panel."""
        if not self.is_simulating or self._sim_result is None:
            return
        tag = self._sim_tag_for_address(address)
        if not tag:
            return
        if self._sim_history is None:
            self._toggle_sim_history()
        if self._sim_history is not None:
            self._sim_history.deiconify()
            self._sim_history._dock_to_parent()
            self._sim_watch_tag(tag, self._sim_label_for_tag(tag))

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
            on_watch_history=self._on_watch_history_request,
        )

        # Add tab
        self.notebook.add(panel, text=file_path.stem)
        self.notebook.select(panel)

        self._open_panels[file_path] = panel
        self._apply_panel_overlay(panel)

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
            on_watch_history=self._on_watch_history_request,
            name=name,
        )

        self.notebook.add(panel, text=name)
        self.notebook.select(panel)

        self._open_panels[None] = panel  # Track with None key
        self._apply_panel_overlay(panel)

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
        panel = self._get_current_panel()
        if not panel:
            return

        initial_dir = self.shared_data.dataview_folder or Path.cwd()

        # Use folder selection dialog
        folder_path = filedialog.askdirectory(
            parent=self,
            title="Select Folder to Export DataView",
            initialdir=initial_dir,
        )

        if not folder_path:
            return

        export_path = Path(folder_path) / f"{panel.name}.cdv"

        # Exporting to the same bound path is equivalent to Save.
        if panel.file_path and export_path == panel.file_path:
            panel.save()
            self._update_tab_title(panel)
            return

        if export_path.exists():
            result = messagebox.askyesno(
                "File Exists",
                f"'{export_path.name}' already exists. Overwrite?",
                parent=self,
            )
            if not result:
                return

        panel.export(export_path)

        # Refresh file list if exported to dataview folder
        if (
            self.shared_data.dataview_folder
            and export_path.parent == self.shared_data.dataview_folder
        ):
            self._refresh_file_list()

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

        # Stop simulation if active
        if self.is_simulating:
            self.stop_simulation()

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

    @staticmethod
    def _get_paired_prompt_type(leaves: list[tuple[str, int]]) -> tuple[str, str] | None:
        """Return (source_type, paired_type) when paired insert prompt should be shown."""
        memory_types = {memory_type for memory_type, _address in leaves}
        if len(memory_types) != 1:
            return None

        source_type = next(iter(memory_types))
        if source_type not in ("T", "CT"):
            return None

        return source_type, INTERLEAVED_PAIRS[source_type]

    def _on_block_select(self, leaves: list[tuple[str, int]]) -> None:
        """Handle block selection from NavWindow - insert all block addresses.

        For T/CT blocks, offers to include paired TD/CTD addresses (interleaved).

        Args:
            leaves: List of (memory_type, address) tuples for all addresses in the block
        """
        if not leaves:
            return

        include_paired = False
        paired_type = None
        pair_prompt = self._get_paired_prompt_type(leaves)
        if pair_prompt is not None:
            source_type, paired_type = pair_prompt
            include_paired = messagebox.askyesno(
                "Include Paired Type",
                f"Also insert {paired_type} addresses with this {source_type} block?",
                parent=self,
            )

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
        """Show or hide the Modbus connect toolbar row."""
        if self._modbus_toolbar_var.get():
            self.modbus_toolbar.pack(fill=tk.X, padx=5, pady=(2, 0), before=self.notebook)
        else:
            self.modbus_toolbar.pack_forget()
        self._sync_overlay_columns()

    # ------------------------------------------------------------------
    # Simulation integration
    # ------------------------------------------------------------------

    def _toggle_sim_toolbar(self) -> None:
        if self._sim_toolbar_var.get():
            self._sim_toolbar.pack(fill=tk.X, padx=5, pady=(2, 0), before=self.notebook)
        else:
            self._sim_toolbar.pack_forget()
        self._sync_overlay_columns()

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
        self.view_menu = view_menu
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
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label="Simulation Toolbar",
            variable=self._sim_toolbar_var,
            command=self._toggle_sim_toolbar,
        )
        self._sim_history_var = tk.BooleanVar(value=False)
        view_menu.add_checkbutton(
            label="Simulation History",
            variable=self._sim_history_var,
            command=self._toggle_sim_history,
        )

        # Connection menu (secondary entry points for toolbar connection actions)
        self.connection_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Connection", menu=self.connection_menu)
        self.connection_menu.add_command(label="Connect", command=self._connect_modbus)
        self.connection_menu.add_command(label="Disconnect", command=self._disconnect_modbus)

    def _sim_selected_tags(self) -> list[tuple[str, PlcValue]]:
        """Checked writable rows of the active panel as (dap_tag, value) pairs."""
        panel = self._get_current_panel()
        if panel is None or self._sim_result is None:
            return []
        pairs: list[tuple[str, PlcValue]] = []
        for address, value in panel.get_write_rows():
            tag = self._sim_tag_for_address(address)
            if tag:
                pairs.append((tag, value))
        return pairs

    def _sim_apply_forces(self, forces: dict[str, PlcValue]) -> None:
        """Translate forced tags to addresses and mark the rows in all panels."""
        if self._sim_result is None:
            return
        addresses: set[str] = set()
        for tag in forces:
            address = self._sim_address_for_tag(tag)
            if address:
                addresses.add(address.upper())
        if addresses == self._sim_forced_addresses:
            return
        self._sim_forced_addresses = addresses
        for panel in self._iter_open_panels():
            panel.set_forced_addresses(addresses)

    def _sim_on_run(self) -> None:
        if self._dap:
            self._dap.continue_()

    def _sim_on_pause(self) -> None:
        if self._dap:
            self._dap.pause()

    def _sim_on_step(self) -> None:
        if self._dap:
            self._dap.step_scan()

    def _sim_on_force(self) -> None:
        tags = self._sim_selected_tags()
        dap = self._dap
        if not tags or dap is None:
            return

        def _do() -> None:
            for tag, value in tags:
                dap.force(tag, value)
            forces = dap.list_forces()
            self._schedule_ui(lambda: self._sim_apply_forces(forces))

        self._sim_dap_async(_do)

    def _sim_on_unforce(self) -> None:
        tags = self._sim_selected_tags()
        dap = self._dap
        if not tags or dap is None:
            return

        def _do() -> None:
            for tag, _value in tags:
                dap.unforce(tag)
            forces = dap.list_forces()
            self._schedule_ui(lambda: self._sim_apply_forces(forces))

        self._sim_dap_async(_do)

    def _sim_on_clear_forces(self) -> None:
        dap = self._dap
        if dap is None:
            return

        def _do() -> None:
            dap.clear_forces()
            self._schedule_ui(lambda: self._sim_apply_forces({}))

        self._sim_dap_async(_do)

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

        if self.is_simulating:
            self._sim_push_live_values()

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

    def _init_sash_position(self, event: object = None) -> None:
        """Pin the sidebar width once, after the paned window is mapped.

        ttk.PanedWindow can otherwise place the initial sash at ~0 and
        collapse the file-list sidebar.
        """
        if self._sash_initialized:
            return
        self._sash_initialized = True
        # Flush any pending (possibly collapsed) layout, then override it.
        self.update_idletasks()
        try:
            self.paned.sashpos(0, 180)
        except tk.TclError:
            pass

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

        # Modbus toggle (right side of toolbar) — a button that reveals the
        # Modbus connect row.  Styled as a Toolbutton so it visibly depresses
        # while the toolbar is open; the shared variable keeps it in sync with
        # the View menu's "Modbus Toolbar" entry.
        self._modbus_toggle_button = ttk.Checkbutton(
            toolbar,
            text="⚡ Modbus",
            variable=self._modbus_toolbar_var,
            command=self._toggle_modbus_toolbar,
            style="Toolbutton",
        )
        self._modbus_toggle_button.pack(side=tk.RIGHT, padx=(5, 0))

        # Modbus toolbar (separate row, hidden by default)
        self.modbus_toolbar = ttk.Frame(self.content)

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

        self.modbus_write_button = ttk.Button(
            self.modbus_toolbar,
            text="💾 Write",
            command=self._write_checked,
        )
        self.modbus_write_button.pack(side=tk.LEFT, padx=(0, 4))

        self.modbus_write_all_button = ttk.Button(
            self.modbus_toolbar,
            text="💾 Write All",
            command=self._write_all,
        )
        self.modbus_write_all_button.pack(side=tk.LEFT)

        # Simulation toolbar (separate row, hidden by default)
        self._sim_toolbar = ttk.Frame(self.content)

        self._sim_run_btn = ttk.Button(
            self._sim_toolbar, text="Run", command=self._sim_on_run, width=6
        )
        self._sim_run_btn.pack(side=tk.LEFT, padx=(0, 2))

        self._sim_pause_btn = ttk.Button(
            self._sim_toolbar, text="Pause", command=self._sim_on_pause, width=6
        )
        self._sim_pause_btn.pack(side=tk.LEFT, padx=(0, 2))

        ttk.Separator(self._sim_toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        self._sim_step_btn = ttk.Button(
            self._sim_toolbar, text="Step Scan", command=self._sim_on_step, width=9
        )
        self._sim_step_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Separator(self._sim_toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        self._sim_state_var = tk.StringVar(value="IDLE")
        ttk.Label(self._sim_toolbar, textvariable=self._sim_state_var, width=10).pack(
            side=tk.LEFT, padx=(0, 10)
        )

        ttk.Label(self._sim_toolbar, text="Scan:").pack(side=tk.LEFT)
        self._sim_scan_var = tk.StringVar(value="—")
        ttk.Label(self._sim_toolbar, textvariable=self._sim_scan_var, width=8).pack(side=tk.LEFT)

        ttk.Separator(self._sim_toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        self._sim_force_btn = ttk.Button(
            self._sim_toolbar, text="Force Selected", command=self._sim_on_force, width=13
        )
        self._sim_force_btn.pack(side=tk.LEFT, padx=(0, 2))

        self._sim_unforce_btn = ttk.Button(
            self._sim_toolbar, text="Unforce Selected", command=self._sim_on_unforce, width=15
        )
        self._sim_unforce_btn.pack(side=tk.LEFT, padx=(0, 2))

        self._sim_clear_btn = ttk.Button(
            self._sim_toolbar, text="Clear Forces", command=self._sim_on_clear_forces, width=11
        )
        self._sim_clear_btn.pack(side=tk.LEFT)

        ttk.Separator(self._sim_toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)

        # Write/Write All issue one-scan DAP patches while simulating; the
        # Modbus toolbar carries its own copies for Modbus writes.
        self.sim_write_button = ttk.Button(
            self._sim_toolbar, text="💾 Write", command=self._write_checked
        )
        self.sim_write_button.pack(side=tk.LEFT, padx=(0, 4))

        self.sim_write_all_button = ttk.Button(
            self._sim_toolbar, text="💾 Write All", command=self._write_all
        )
        self.sim_write_all_button.pack(side=tk.LEFT)

        # Notebook for tabs (with close buttons)
        self.notebook = CustomNotebook(self.content, on_close_callback=self._on_tab_close_request)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Bind tab change and close events
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook.bind("<<NotebookTabClosed>>", self._on_tab_closed)
        self.notebook.bind("<Button-3>", self._on_tab_right_click)

        # Pin the sidebar width once the paned window is realized.  A fixed
        # delay races the PanedWindow's own initial layout and intermittently
        # leaves the sidebar collapsed to ~0 width.
        self._sash_initialized = False
        self.paned.bind("<Map>", self._init_sash_position, add=True)

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
        self._modbus_toolbar_var = tk.BooleanVar(value=False)

        # Simulation state (activated via start_simulation)
        self._dap: DapService | None = None
        self._sim_result: SimulateResult | None = None
        self._sim_scr_folder: Path | None = None
        self._sim_db_path: Path | None = None
        self._sim_watcher: ScrFileWatcher | None = None
        self._sim_history: HistoryWindow | None = None
        self._sim_scan_id: int | None = None
        self._sim_was_running = False
        self._sim_forced_addresses: set[str] = set()
        self._sim_toolbar_var = tk.BooleanVar(value=False)

        # Simulation History watch state.  The window owns the watch list and
        # synthesizes the change stream by diffing watched tags between scans.
        self._sim_watched: dict[str, str] = {}  # dap_tag -> display label
        self._sim_history_last: dict[str, PlcValue] = {}  # dap_tag -> last value
        self._cause_queue: queue.Queue[tuple[int, str, int | None]] | None = None
        self._cause_worker: threading.Thread | None = None
        self._cause_stop: threading.Event | None = None

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

    def _sim_set_row_cause(self, row_id: int, text: str) -> None:
        if self._sim_history is not None:
            self._sim_history.panel.set_row_cause(row_id, text)

    def _sim_cause_loop(self) -> None:
        """Drain queued cause requests serially so the DAP pipe is not flooded."""
        q = self._cause_queue
        stop = self._cause_stop
        if q is None or stop is None:
            return
        while not stop.is_set():
            try:
                row_id, tag, scan = q.get(timeout=0.3)
            except queue.Empty:
                continue
            dap = self._dap
            if dap is None:
                continue
            try:
                result = dap.cause(tag, scan=scan)
            except Exception:
                result = None
            text = ""
            if result:
                text = result.get("text", str(result))
            self._schedule_ui(lambda rid=row_id, t=text: self._sim_set_row_cause(rid, t))

    # -- Causal chain --

    # -- Causal chain auto-population --

    def _sim_start_cause_worker(self) -> None:
        """Start the background worker that fills in each history row's cause."""
        if self._cause_worker is not None:
            return
        self._cause_queue = queue.Queue(maxsize=256)
        self._cause_stop = threading.Event()
        self._cause_worker = threading.Thread(
            target=self._sim_cause_loop, daemon=True, name="dap-cause"
        )
        self._cause_worker.start()

    def _sim_stop_cause_worker(self) -> None:
        if self._cause_stop is not None:
            self._cause_stop.set()
        self._cause_queue = None
        self._cause_worker = None
        self._cause_stop = None

    def _sim_enqueue_cause(self, row_id: int, tag: str, scan: int | None) -> None:
        q = self._cause_queue
        if q is None:
            return
        try:
            q.put_nowait((row_id, tag, scan))
        except queue.Full:
            # Backlogged (very fast Run) — drop; this row's cause stays blank.
            pass

    def _sim_update_controls(self) -> None:
        from ...services.dap_service import SimState

        if self._dap is None:
            state = SimState.IDLE
        else:
            state = self._dap.state

        can_run = state in (SimState.STOPPED, SimState.PAUSED)
        can_pause = state == SimState.RUNNING
        can_step = state in (SimState.STOPPED, SimState.PAUSED)
        can_force = state not in (SimState.IDLE, SimState.LAUNCHING)

        self._sim_run_btn.config(state=tk.NORMAL if can_run else tk.DISABLED)
        self._sim_pause_btn.config(state=tk.NORMAL if can_pause else tk.DISABLED)
        self._sim_step_btn.config(state=tk.NORMAL if can_step else tk.DISABLED)
        self._sim_force_btn.config(state=tk.NORMAL if can_force else tk.DISABLED)
        self._sim_unforce_btn.config(state=tk.NORMAL if can_force else tk.DISABLED)
        self._sim_clear_btn.config(state=tk.NORMAL if can_force else tk.DISABLED)

        # Write/Write All issue one-scan DAP patches while the sim is alive.
        self.sim_write_button.config(state=tk.NORMAL if can_force else tk.DISABLED)
        self.sim_write_all_button.config(state=tk.NORMAL if can_force else tk.DISABLED)

        # Modbus and Simulation are mutually exclusive transports — block the
        # Modbus toggle (button and menu entry) for the duration of the sim.
        modbus_state = tk.DISABLED if self.is_simulating else tk.NORMAL
        self._modbus_toggle_button.config(state=modbus_state)
        self.view_menu.entryconfig("Modbus Toolbar", state=modbus_state)

    def _sim_apply_state(self, state: SimState, error: Exception | None) -> None:
        self._sim_state_var.set(state.value.upper())
        self._sim_update_controls()
        if error:
            messagebox.showerror("Simulation Error", str(error), parent=self)

    # -- DapService callbacks (reader thread → Tk thread) --

    def _sim_on_dap_state(self, state: SimState, error: Exception | None) -> None:
        try:
            self.after(0, lambda: self._sim_apply_state(state, error))
        except tk.TclError:
            pass

    @staticmethod
    def _sim_fmt_value(value: PlcValue) -> str:
        """Render a tag value for the History table (ON/OFF for booleans)."""
        if isinstance(value, bool):
            return "ON" if value else "OFF"
        return str(value)

    def _sim_record_history(self, values: TagValues, scan: int | None) -> None:
        """Diff watched tags against their last values and log any changes."""
        if self._sim_history is None or not self._sim_watched:
            return
        panel = self._sim_history.panel
        for tag, label in self._sim_watched.items():
            if tag not in values:
                continue
            current = values[tag]
            if tag not in self._sim_history_last:
                # First sighting — baseline only, no row.
                self._sim_history_last[tag] = current
                continue
            previous = self._sim_history_last[tag]
            if current == previous:
                continue
            self._sim_history_last[tag] = current
            row_id = panel.append_row(
                scan,
                label,
                self._sim_fmt_value(previous),
                self._sim_fmt_value(current),
            )
            self._sim_enqueue_cause(row_id, tag, scan)

    def _sim_apply_tags(self, values: TagValues, scan: int | None) -> None:
        self._sim_push_live_values(values)
        self._sim_record_history(values, scan)

    def _sim_on_dap_tags(self, values: TagValues) -> None:
        # Capture the scan id on the reader thread, where DapService has just
        # set it for this frame — reading it later on the Tk thread could race
        # a newer frame.
        scan = self._dap.scan_id if self._dap is not None else None
        try:
            self.after(0, lambda: self._sim_apply_tags(values, scan))
        except tk.TclError:
            pass

    def _sim_apply_scan(self, scan_id: int | None) -> None:
        self._sim_scan_id = scan_id
        self._sim_scan_var.set(str(scan_id) if scan_id is not None else "—")

    def _sim_on_dap_scan(self, scan_id: int | None) -> None:
        try:
            self.after(0, lambda: self._sim_apply_scan(scan_id))
        except tk.TclError:
            pass

    def _sim_ensure_dap(self) -> DapService:
        if self._dap is None:
            from ...services.dap_service import DapService

            self._dap = DapService(
                on_state=self._sim_on_dap_state,
                on_tags=self._sim_on_dap_tags,
                on_scan=self._sim_on_dap_scan,
            )
        return self._dap

    def _sim_on_rebuild_complete(self, result: SimulateResult) -> None:
        self._sim_result = result
        # Re-baseline watched tags against the rebuilt sim.
        self._sim_history_last.clear()
        if self._sim_history is not None:
            self._sim_history.panel.clear()

        if self._dap is not None:
            resp = self._dap.reload()
            if resp is None or not resp.get("success"):
                error_msg = (resp or {}).get("body", {}).get("result", "unknown error")
                messagebox.showerror("Simulation Error", f"Reload failed: {error_msg}", parent=self)
                return

            if self._sim_was_running:
                self._dap.continue_()

    def _sim_build_nickname_map(self) -> dict[str, str] | None:
        store = self.shared_data._store
        if store is None:
            return None
        nickname_map: dict[str, str] = {}
        for row in store.all_rows.values():
            if row.nickname:
                nickname_map[row.display_address] = row.nickname
        return nickname_map or None

    # -- Scr file watcher --

    def _sim_on_scr_changed(self) -> None:
        from ...services.dap_service import SimState

        if self._dap is None:
            return
        self._sim_was_running = self._dap.state == SimState.RUNNING
        if self._dap.state != SimState.IDLE:
            self._dap.pause()

        self._sim_state_var.set("REBUILDING")
        self._sim_update_controls()

        def _rebuild() -> None:
            from ...services.simulate_service import rebuild

            nickname_map = self._sim_build_nickname_map()
            try:
                result = rebuild(self._sim_scr_folder, self._sim_db_path, nickname_map=nickname_map)
                self.after(0, lambda: self._sim_on_rebuild_complete(result))
            except Exception as exc:
                msg = str(exc)
                self.after(
                    0,
                    lambda: messagebox.showerror("Rebuild Error", msg, parent=self),
                )

        threading.Thread(target=_rebuild, daemon=True).start()

    def _sim_on_launch_failed(self, msg: str) -> None:
        messagebox.showerror("Simulation Error", msg, parent=self)
        self._sim_update_controls()

    def _sim_on_launch_complete(self) -> None:
        """Finish simulation startup once the DAP subprocess is ready."""
        from ..simulate.scr_watcher import ScrFileWatcher

        if self._sim_scr_folder is not None and self._sim_watcher is None:
            self._sim_watcher = ScrFileWatcher(self._sim_scr_folder, self, self._sim_on_scr_changed)
            self._sim_watcher.start()

        self._sim_update_controls()

    # -- Public API for simulation lifecycle --

    def start_simulation(
        self,
        sim_result: SimulateResult,
        scr_folder: Path,
        db_path: Path | None = None,
    ) -> None:
        """Activate simulation mode with the given preparation result."""
        self._sim_result = sim_result
        self._sim_scr_folder = scr_folder
        self._sim_db_path = db_path

        # Modbus is not a valid transport during simulation — collapse its
        # toolbar so it is fully unavailable (its toggle is also disabled by
        # _sim_update_controls).
        if self._modbus_toolbar_var.get():
            self._modbus_toolbar_var.set(False)
            self.modbus_toolbar.pack_forget()

        # Show the simulation toolbar; this also lights up the overlay columns
        # (New Value / Write / Live) via _sync_overlay_columns.
        self._sim_toolbar_var.set(True)
        self._toggle_sim_toolbar()

        # Enable ON/OFF rendering of BIT values in the Live column.
        for panel in self._iter_open_panels():
            panel.set_live_bool_onoff(True)

        # Show history window
        if self._sim_history is None:
            self._toggle_sim_history()

        # Start DAP on a background thread.  Launching the subprocess and
        # completing the DAP handshake can take several seconds; doing it
        # synchronously would block the Tk event loop and freeze the window
        # before it finishes its first layout pass.
        dap = self._sim_ensure_dap()
        self._sim_start_cause_worker()
        self._sim_state_var.set("LAUNCHING")
        self._sim_update_controls()

        project_dir = sim_result.project_dir

        def _launch() -> None:
            try:
                dap.launch(project_dir)
            except Exception as exc:
                msg = str(exc)
                self._schedule_ui(lambda: self._sim_on_launch_failed(msg))
                return
            self._schedule_ui(self._sim_on_launch_complete)

        threading.Thread(target=_launch, daemon=True).start()

    def stop_simulation(self) -> None:
        """Deactivate simulation mode and clean up."""
        if self._sim_watcher is not None:
            self._sim_watcher.stop()
            self._sim_watcher = None

        self._sim_stop_cause_worker()

        if self._dap is not None:
            self._dap.terminate()
            self._dap = None

        if self._sim_history is not None:
            self._sim_history.destroy()
            self._sim_history = None

        self._sim_result = None
        self._sim_scr_folder = None
        self._sim_db_path = None
        self._sim_scan_id = None
        self._sim_forced_addresses = set()
        self._sim_watched.clear()
        self._sim_history_last.clear()

        for panel in self._iter_open_panels():
            panel.set_live_bool_onoff(False)
            panel.set_forced_addresses(set())

        self._sim_state_var.set("IDLE")
        self._sim_scan_var.set("—")
        self._sim_toolbar_var.set(False)
        self._toggle_sim_toolbar()
        self._sim_update_controls()

        self._clear_live_values_all_panels()

    @property
    def is_simulating(self) -> bool:
        return self._dap is not None and self._sim_result is not None

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
