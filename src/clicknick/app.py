from __future__ import annotations

import tkinter as tk
from collections import Counter
from ctypes import windll
from dataclasses import replace
from pathlib import Path
from tkinter import PhotoImage, filedialog, font, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

from .config import AppSettings
from .connection_session import ClickConnection, SavedProgram
from .data.address_store import AddressStore
from .data.nickname_manager import NicknameManager
from .detection.window_detector import ClickInstance, ClickWindowDetector
from .detection.window_mapping import CLICK_PLC_WINDOW_MAPPING
from .resources.action_icons import ActionIconCache
from .resources.icon_data import ICON_PNG_BASE64
from .utils.click_temp import scr_files
from .utils.filters import (  # preserve lru_cache
    ContainsFilter,
    ContainsPlusFilter,
    NoneFilter,
    PrefixFilter,
)
from .utils.mdb_shared import find_fallback_csv
from .views.dialogs import AboutDialog, CsvFallbackDialog, OdbcWarningDialog
from .views.overlay import Overlay
from .widgets.tooltip import bind_tooltip

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Self

    from .connection_session import ConnectionSession
    from .data_session import DataSession
    from .services.workspace_mirror import ProjectWorkspaceConfig
    from .views.review_changes_window import ProposalSource

# Set DPI awareness for better UI rendering
windll.shcore.SetProcessDpiAwareness(1)

_MATCH_MODES = ("none", "prefix", "contains", "containsplus")
_MATCH_LABELS = ("None", "Prefix", "Contains", "Fuzzy")
# The popup lists this many legacy-encoded rungs by name and counts the rest
_LEGACY_LISTED = 10


_T = TypeVar("_T")


class _ShownState(Generic[_T]):
    """App attribute the main window displays: assigning it schedules one UI refresh.

    The value lives in the instance ``__dict__`` under the same name; as a data
    descriptor this still takes precedence on lookup.
    """

    @overload
    def __get__(self, app: None, owner: Any = None) -> Self: ...
    @overload
    def __get__(self, app: object, owner: Any = None) -> _T: ...
    def __get__(self, app, owner=None):
        if app is None:
            return self
        try:
            return app.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None

    def __set__(self, app, value: _T) -> None:
        app.__dict__[self._name] = value
        app._request_ui_refresh()

    def __set_name__(self, owner, name: str) -> None:
        self._name = name


def get_version():
    """Get version from package metadata."""
    try:
        from importlib.metadata import version

        return version("clicknick")  # Replace with your actual package name
    except Exception:
        return "Development"


class ClickNickApp:
    """Main application for the ClickNick App."""

    # Everything the window title and Workspace details are computed from;
    # changing any of these refreshes them (see _refresh_ui).
    _click: _ShownState[ClickConnection | None] = _ShownState()
    _data: _ShownState[DataSession | None] = _ShownState()
    _session: _ShownState[ConnectionSession | None] = _ShownState()
    _workspace_config: _ShownState[ProjectWorkspaceConfig | None] = _ShownState()
    _workspace_matches: _ShownState[list[ProjectWorkspaceConfig]] = _ShownState()
    _workspace_mirror_error: _ShownState[str | None] = _ShownState()

    def _get_workspace_status(self):
        """Return reusable status for the current CLICK workspace."""
        from .services.workspace_service import get_workspace_status

        session = self._session
        return get_workspace_status(
            session.analysis if session else None,
            staged_rungs=session.staged_rungs if session else 0,
        )

    def _workspace_source_dir(self) -> Path | None:
        analysis = self._session.analysis if self._session else None
        return analysis.project_dir if analysis else None

    def _configured_workspace_dir(self) -> Path | None:
        config = self._workspace_config
        return config.workspace_path if config is not None else None

    def _workspace_display_dir(self) -> Path | None:
        """Return the active path, or its configured target while rebuilding."""
        return self._workspace_source_dir() or self._configured_workspace_dir()

    def _current_plc_name(self) -> str | None:
        """Return CLICK's configured PLC name from its active temp workspace."""
        click = getattr(self, "_click", None)
        if click is None:
            return None
        from .services.workspace_mirror import read_plc_name
        from .utils.click_temp import click_temp_dir

        return read_plc_name(click_temp_dir(click.hwnd) / "Project.ini")

    @staticmethod
    def _format_workspace_time(value) -> str:
        return value.astimezone().strftime("%x %X") if value is not None else "Not available"

    def _poll_workspace_ui(self) -> None:
        self._workspace_refresh_after_id = None
        self._refresh_ui()

    def _get_workspace_directory_info(self):
        """Return paths and timestamps for the future Workspace details panel."""
        from .services.workspace_mirror import get_workspace_directory_info

        return get_workspace_directory_info(
            self._workspace_config,
            self._workspace_source_dir(),
        )

    def _open_workspace_menu_options(self) -> tuple[str, str]:
        """Return the label and state for opening the active workspace."""
        label = (
            "Open Workspace" if self._workspace_config is not None else "Open Temporary Workspace"
        )
        workspace_dir = self._workspace_display_dir()
        state = tk.NORMAL if workspace_dir is not None and workspace_dir.is_dir() else tk.DISABLED
        return label, state

    def _refresh_workspace_menu_states(self) -> None:
        """Follow the active temporary or durable workspace directory."""
        label, state = self._open_workspace_menu_options()
        for menu_name, index_name in (
            ("workspace_options_menu", "_workspace_options_open_index"),
            ("workspace_menu", "_workspace_menu_open_index"),
        ):
            menu = getattr(self, menu_name, None)
            index = getattr(self, index_name, None)
            if menu is None or index is None:
                continue
            try:
                menu.entryconfigure(index, label=label, state=state)
            except tk.TclError:
                pass

    def _window_title(self) -> str:
        """Return the title for the current connection, data source and sync count."""
        if self._click is None:
            return "ClickNick"

        if self._data is None:
            source = ""
        elif self.using_database:
            source = "DB"
        else:
            source = "CSV"
        title = f"ClickNick - {self._click.filename}"
        if source:
            title += f" - {source}"

        pending = self._session.synced_pending if self._session else 0
        if pending > 0:
            noun = "tag" if pending == 1 else "tags"
            title += f" ({pending} {noun} synced - Save in CLICK)"
        return title

    def _simulation_summary(self) -> tuple[str, str]:
        """The Test group's legend and its simulation button's label."""
        session = self._session
        simulation = session.simulation if session is not None else None
        if simulation is None or not simulation.enabled:
            return "Test - Sim off", "Start"
        return f"Test - Sim {simulation.summary_text}", "Stop"

    def _click_filename(self) -> str:
        """The connected CLICK window's project filename ("" when none is connected)."""
        return self._click.filename if self._click else ""

    def _refresh_ui(self) -> None:
        """Bring the titles and status/details variables up to date (no widget rebuilds)."""
        self.root.title(self._window_title())
        if self._data is not None:
            dataview = self._data.dataview_window
            for window in (*self._data.editors, *([dataview] if dataview else [])):
                # A window being destroyed may still be registered
                try:
                    if window.winfo_exists():
                        window.refresh_title()
                except tk.TclError:
                    pass
        if not hasattr(self, "workspace_status_var"):
            return

        from .services.workspace_service import WorkspaceState

        workspace = self._get_workspace_status()
        self.workspace_status_var.set(workspace.label)
        self.workspace_group_title_var.set(f"Workspace - {workspace.label}")
        self.project_name_var.set(self._click.filename if self._click else "Not connected")
        repairs_menu = getattr(self, "repairs_menu", None)
        repair_index = getattr(self, "_repairs_system_nicknames_index", None)
        if repairs_menu is not None and repair_index is not None:
            session = getattr(self, "_session", None)
            analysis = session.analysis if session else None
            has_repairs = bool(analysis and analysis.system_nickname_repairs)
            repairs_menu.entryconfigure(
                repair_index,
                state=tk.NORMAL if has_repairs else tk.DISABLED,
            )

        if workspace.state is WorkspaceState.PREPARING:
            if self._workspace_refresh_after_id is None:
                self._workspace_refresh_after_id = self.root.after(500, self._poll_workspace_ui)
        elif self._workspace_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._workspace_refresh_after_id)
            except tk.TclError:
                pass
            self._workspace_refresh_after_id = None

        active_dir = self._workspace_display_dir()
        self.mirror_status_var.set("Durable" if self._workspace_config else "Temporary")
        self.mirror_detail_var.set(self._workspace_mirror_error or "")
        self.mirror_path_var.set(str(active_dir) if active_dir else "Not available")
        if self._workspace_config:
            setup_status = "✓ Configured"
        elif len(getattr(self, "_workspace_matches", [])) > 1:
            setup_status = "Choose workspace"
        else:
            setup_status = "Not configured"
        self.mirror_setup_status_var.set(setup_status)

        info = self._get_workspace_directory_info()
        self.plc_name_var.set(self._current_plc_name() or "Not available")
        test_title, simulation_action = self._simulation_summary()
        self.test_group_title_var.set(test_title)
        self.simulation_action_var.set(simulation_action)
        self.generated_dir_var.set(
            str(info.generated_dir) if info.generated_dir else "Not available"
        )
        self.workspace_config_path_var.set(
            str(info.config_path) if info.config_path else "Not configured"
        )
        self.last_regenerated_var.set(self._format_workspace_time(info.last_regenerated_at))
        self.last_backup_var.set(self._format_workspace_time(info.last_backup_at))
        self._refresh_workspace_menu_states()

    def _run_requested_ui_refresh(self) -> None:
        self._ui_refresh_id = None
        self._refresh_ui()

    def _request_ui_refresh(self) -> None:
        """Schedule one _refresh_ui for when Tk is idle; repeated requests coalesce.

        Assigning any _ShownState attribute requests this, so
        a code path that changes what the window shows needs no refresh call.
        Other inputs (sync count, analysis progress, staged rungs) are
        ConnectionSession events, and their handlers request it.
        """
        if self._ui_refresh_id is None:
            self._ui_refresh_id = self.root.after_idle(self._run_requested_ui_refresh)

    def _setup_variables(self):
        """Initialize Tkinter variables."""
        self.status_var = tk.StringVar(value="Not connected")
        self.selected_instance_var = tk.StringVar()  # Add this line
        try:
            match_index = _MATCH_MODES.index(self.settings.search_mode)
        except ValueError:
            match_index = 2
        self.match_mode_index_var = tk.DoubleVar(value=float(match_index))
        self.workspace_status_var = tk.StringVar(value="Unavailable")
        self.workspace_group_title_var = tk.StringVar(value="Workspace - Unavailable")
        self.project_name_var = tk.StringVar(value="Not connected")
        self.mirror_status_var = tk.StringVar(value="Not configured")
        self.mirror_detail_var = tk.StringVar(value="")
        self.mirror_path_var = tk.StringVar(value="Not configured")
        self.mirror_setup_status_var = tk.StringVar(value="Not configured")
        self.mirror_project_selection_var = tk.StringVar(value="")
        self.mirror_location_selection_var = tk.StringVar(value="")
        self.workspace_setup_action_var = tk.StringVar(value="Create Workspace")
        self.generated_dir_var = tk.StringVar(value="Not available")
        self.workspace_config_path_var = tk.StringVar(value="Not configured")
        self.plc_name_var = tk.StringVar(value="Not available")
        self.test_group_title_var = tk.StringVar(value="Test - Sim off")
        self.simulation_action_var = tk.StringVar(value="Start")
        self.last_regenerated_var = tk.StringVar(value="Not available")
        self.last_backup_var = tk.StringVar(value="Not available")
        self.click_instances = []  # Will store ClickInstance objects
        self._odbc_warning_shown = False
        self._workspace_refresh_after_id = None
        self._project_info_window = None
        self._mirror_setup_window = None

    def _setup_styles(self):
        """Configure ttk styles for the application."""
        style = ttk.Style()

        # Configure common styles
        style.configure("TButton", padding=6)
        style.configure("TLabel", padding=2)

        # Status label styles
        bold_font = (self._default_family, self._default_size, "bold")  # Only add 'bold'

        # Configure all label styles with icons and consistent font
        style.configure(
            "Status.TLabel",
            foreground="#64B5F6",  # Blue 300 (lighter than Connected)
            font=bold_font,
        )

        style.configure(
            "Connected.TLabel",
            foreground="#1976D2",  # Blue 700 (standard "connected" in Material)
            font=bold_font,
        )

        style.configure(
            "Error.TLabel",
            foreground="#D32F2F",  # Red 700 (Material error color)
            font=bold_font,
        )

    def _instance_labels(self) -> list[str]:
        """The combobox's label for each CLICK window: its filename, with the PID where
        two windows show the same filename."""
        counts = Counter(instance.filename for instance in self.click_instances)
        return [
            f"{instance.filename} (PID {instance.pid})"
            if counts[instance.filename] > 1
            else instance.filename
            for instance in self.click_instances
        ]

    def _on_instance_selected(self, event=None):
        """Connect to the CLICK window picked in the combobox."""
        labels = self._instance_labels()
        selected_text = self.selected_instance_var.get()
        if selected_text not in labels:
            return
        instance = self.click_instances[labels.index(selected_text)]
        self.connect_to_instance(
            instance.pid, instance.title, instance.filename, instance.hwnd, user_picked=True
        )

    def _create_click_instances_section(self, parent):
        """Create the Click.exe instances section."""
        instances_frame = ttk.LabelFrame(
            parent, text="ClickPLC Windows", padding="10"
        )  # Reduce from 15 to 10

        # Create frame for combobox and refresh button
        selection_frame = ttk.Frame(instances_frame)

        # Instance selection combobox
        instance_label = ttk.Label(selection_frame, text="Select Window:")
        self.instances_combobox = ttk.Combobox(
            selection_frame, textvariable=self.selected_instance_var, state="readonly", width=30
        )

        # Refresh button with icon-like text
        refresh_button = ttk.Button(
            selection_frame, text="⟳", width=3, command=self.refresh_click_instances
        )
        self.start_button = ttk.Button(
            selection_frame,
            text="⏹ Stop" if self.monitoring else "▶ Start",
            command=self.toggle_monitoring,
        )

        # Bind combobox selection to auto-connect
        self.instances_combobox.bind("<<ComboboxSelected>>", self._on_instance_selected)

        # Layout
        instance_label.pack(side=tk.LEFT, padx=(0, 8))  # Reduce from 10 to 8
        self.instances_combobox.pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )  # Reduce from 10 to 8
        refresh_button.pack(side=tk.RIGHT)
        self.start_button.pack(side=tk.RIGHT)

        selection_frame.pack(fill=tk.X)  # Remove pady

        self.status_label = ttk.Label(
            instances_frame, textvariable=self.status_var, style="Status.TLabel"
        )

        # Layout widgets
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Pack the main frame
        instances_frame.pack(fill=tk.X, pady=(0, 12))  # Reduce from 15 to 12

    def _on_sort_option_changed(self):
        """Handle changes to the sort option."""
        self.nickname_manager.invalidate()

    def _on_match_mode_changed(self, value) -> None:
        """Map the four-stop slider onto the existing filter strategies."""
        index = max(0, min(len(_MATCH_MODES) - 1, round(float(value))))
        self.match_mode_index_var.set(float(index))
        self.settings.search_var.set(_MATCH_MODES[index])

    def _populate_autocomplete_options_menu(self, menu: tk.Menu) -> None:
        """Add the compact checkable preferences to the Autocomplete menu."""
        menu.add_checkbutton(
            label="Sort A→Z",
            variable=self.settings.sort_by_nickname_var,
            command=self._on_sort_option_changed,
        )
        menu.add_checkbutton(
            label="Show Tooltips",
            variable=self.settings.show_info_tooltip_var,
        )
        menu.add_checkbutton(
            label="Exclude SC/SD Addresses",
            variable=self.settings.exclude_sc_sd_var,
        )

    def _create_options_section(self, parent):
        """Create the compact, frequently used autocomplete controls."""
        options_frame = ttk.LabelFrame(parent, padding=10)
        options_header = ttk.Frame(options_frame)
        ttk.Label(options_header, text="Autocomplete").pack(side=tk.LEFT)
        options_button = ttk.Menubutton(options_header, text="Options")
        options_menu = tk.Menu(options_button, tearoff=0)
        self._populate_autocomplete_options_menu(options_menu)
        options_button.configure(menu=options_menu)
        options_button.pack(side=tk.LEFT, padx=(8, 0))
        options_frame.configure(labelwidget=options_header)
        self.autocomplete_options_menu = options_menu

        match_frame = ttk.Frame(options_frame)
        for column, label in enumerate(_MATCH_LABELS):
            match_frame.columnconfigure(column, weight=1, uniform="match-mode")
            ttk.Label(match_frame, text=label, anchor=tk.CENTER).grid(
                row=0, column=column, sticky="ew"
            )
        self.match_mode_scale = ttk.Scale(
            match_frame,
            from_=0,
            to=len(_MATCH_MODES) - 1,
            orient=tk.HORIZONTAL,
            variable=self.match_mode_index_var,
            command=self._on_match_mode_changed,
        )
        self.match_mode_scale.grid(row=1, column=0, columnspan=4, sticky="ew")
        match_frame.pack(fill=tk.X, pady=(0, 8))

        # Exclude nicknames containing entry
        exclude_frame_entry = ttk.Frame(options_frame)
        exclude_label = ttk.Label(exclude_frame_entry, text="Exclude nicknames containing:")
        exclude_entry = ttk.Entry(
            exclude_frame_entry, textvariable=self.settings.exclude_nicknames_var
        )

        # Placeholder text logic
        placeholder_text = AppSettings.EXCLUDE_PLACEHOLDER_TEXT

        def on_entry_focus_in(event):
            if exclude_entry.get() == placeholder_text:
                self.settings.exclude_nicknames_var.set("")
                exclude_entry.config(foreground="black")

        def on_entry_focus_out(event):
            if not exclude_entry.get().strip():
                self.settings.exclude_nicknames_var.set(placeholder_text)
                exclude_entry.config(foreground="gray")

        if not self.settings.exclude_nicknames_var.get():
            self.settings.exclude_nicknames_var.set(placeholder_text)
            exclude_entry.config(foreground="gray")

        exclude_entry.bind("<FocusIn>", on_entry_focus_in)
        exclude_entry.bind("<FocusOut>", on_entry_focus_out)

        exclude_label.pack(side=tk.LEFT, padx=(0, 8))
        exclude_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        exclude_frame_entry.pack(fill=tk.X)

        # Pack the main frame
        options_frame.pack(fill=tk.X, pady=(0, 12))

    def _update_status(self, message, style="normal"):
        """Update status message with appropriate style."""
        self.status_var.set(message)
        if style == "error":
            self.status_label.configure(style="Error.TLabel")
        elif style == "connected":
            self.status_label.configure(style="Connected.TLabel")
        else:
            self.status_label.configure(style="Status.TLabel")

    def _get_store(self):
        """Return the current AddressStore regardless of data source."""
        return self._data.store if self._data is not None else None

    def _live_mdb_path(self):
        """Resolve the MDB path from the currently connected Click instance."""
        if self._click is None:
            return None
        from .utils.mdb_shared import find_click_database

        db_path = find_click_database(click_hwnd=self._click.hwnd)
        return Path(db_path) if db_path else None

    def _start_analysis_build(self) -> None:
        """Build program analysis in background if connected to a Click project."""
        if self._session is None:
            return
        self._session.start_analysis(self.root)
        self._request_ui_refresh()

    def _workspace_rung_apply(self) -> None:
        """Review workspace changes through the reviewed proposal flow."""
        if self._session is None or self._live_server is None:
            self._update_status("Connect to a CLICK project first", "error")
            return

        try:
            self._live_server.dispatch_now("rung apply")
        except Exception as exc:
            messagebox.showerror("Review Changes", str(exc), parent=self.root)
            self._update_status(f"Review failed: {exc}", "error")
            return

        status = self._get_workspace_status()
        if status.changed_rungs:
            self._update_status(f"Reviewing {status.label}", "connected")
        else:
            self._update_status("Workspace clean; no changed rungs to review", "connected")

    def _workspace_reload_finished(self, success: bool, error: str | None) -> None:
        """Report completion of an explicit CLICK-to-workspace reload."""
        if success:
            if self._session is not None:
                self._session.record_rung_stage(0)
            # The edits were thrown away: so is the window offering to paste them.
            for window in self._review_changes_windows.values():
                if window.winfo_exists() and window.shows_workspace_proposal:
                    window.destroy()
            self._update_status("Workspace reloaded from CLICK", "connected")
            self._request_ui_refresh()
            return
        message = error or "Workspace could not be reloaded from CLICK."
        messagebox.showerror("Reload from CLICK", message, parent=self.root)
        self._update_status(f"Workspace reload failed: {message}", "error")
        self._request_ui_refresh()

    def _workspace_reload_from_click(self) -> None:
        """Explicitly replace active workspace source from the saved CLICK project."""
        session = self._session
        if session is None:
            self._update_status("Connect to a CLICK project first", "error")
            return

        from .services.workspace_service import WorkspaceState

        if self._get_workspace_status().state is WorkspaceState.PREPARING:
            self._update_status("Workspace regeneration is already in progress", "error")
            return

        confirmed = messagebox.askokcancel(
            "Reload from CLICK",
            "Reload the workspace from the saved CLICK project?\n\n"
            "This replaces the active generated source. Modified workspace source "
            "will be preserved in the recovery snapshot.",
            parent=self.root,
        )
        if not confirmed:
            return

        self._update_status("Reloading workspace from CLICK...", "connected")

        def _finished(success: bool, error: str | None) -> None:
            if self._session is session:
                self._workspace_reload_finished(success, error)

        session.reload_workspace_from_click(self.root, _finished)
        self._request_ui_refresh()

    def _apply_active_filter(self, candidates: list[str], search_text: str) -> list[str]:
        mode = self.settings.search_mode
        strategy = self.filter_strategies.get(mode, self.filter_strategies["contains"])
        return strategy.filter_matches(candidates, search_text)

    def _focus_simulator(self, session: ConnectionSession) -> bool:
        """Raise the session's open Simulator window, if any."""
        window = session.simulator
        if window is None:
            return False
        try:
            window.lift()
            window.focus_force()
            return True
        except tk.TclError:
            session.simulator = None
            return False

    def _on_simulation_event(self, event) -> None:
        if event.kind in ("status", "modbus"):
            self._request_ui_refresh()

    def _simulation_for_window(self, title: str, purpose: str):
        """Check the project can be simulated and return its SimulationSession.

        For the Simulator and the Test group's Start button: the project must be saved,
        and a conversion that already failed will not fix itself by opening
        a window -- say so up front rather than showing an inert one.
        """
        session = self._session
        if session is None:
            self._update_status("Connect to a Click project first", "error")
            return None

        mdb_path = self._live_mdb_path()
        if mdb_path is None or not scr_files(mdb_path.parent):
            self._update_status(
                "Project not saved to disk. Please save in Click Software first.",
                "error",
            )
            return None

        analysis = session.analysis
        if analysis is None or not analysis.is_available:
            self._start_analysis_build()
            analysis = session.analysis

        if analysis is not None and not analysis.is_available:
            from .services.analysis_service import AnalysisStatus

            if analysis.status is AnalysisStatus.FAILED:
                messagebox.showerror(
                    title,
                    f"{analysis.error}\n\n{purpose} needs the project converted to pyrung.",
                    parent=self.root,
                )
                return None

        simulation = session.ensure_simulation(
            self.root, on_retry_analysis=self._start_analysis_build
        )
        simulation.add_listener(self._on_simulation_event)
        return simulation

    def _toggle_simulation(self) -> None:
        """The Test group's Start/Stop: the only control (besides teardown) that stops it."""
        session = self._session
        simulation = session.simulation if session is not None else None
        if simulation is not None and simulation.enabled:
            simulation.turn_off()
            return
        simulation = self._simulation_for_window("Cannot Simulate", "Simulation")
        if simulation is not None:
            simulation.turn_on()

    @property
    def _csv_path(self) -> str | None:
        """The file the loaded CSV data comes from (None for database data or none)."""
        data = self._data
        if data is None or data.store.is_database:
            return None
        return data.store._data_source.file_path

    def _dataview_folder(self) -> Path | None:
        """The DataView folder the Dataview Editor shows: the connected CLICK window's.

        With no window connected, the loaded CSV's folder, unless that is a CLICK
        temp folder or gone; otherwise none. Never another ``CLICK (hwnd)`` folder:
        that one holds another project's .cdv files.
        """
        from .data.cdv_file import click_dataview_folder, csv_dataview_folder

        if self._click is not None:
            return click_dataview_folder(self._click.hwnd)
        csv_path = self._csv_path
        return csv_dataview_folder(csv_path) if csv_path else None

    def _open_dataview_editor(self):
        """Open the Dataview Editor window, or focus if already open.

        The dataview editor allows creating and editing CLICK DataView files (.cdv).
        Only one DataviewEditorWindow can be open at a time.
        """
        data = self._data
        if data is None:
            self._update_status("No data loaded", "error")
            return

        window = data.dataview_window
        if window is not None:
            try:
                window.lift()
                window.focus_force()
                return
            except tk.TclError:
                data.unregister_dataview_window(window)

        try:
            from .data.shared_dataview import SharedDataviewData
            from .views.dataview_editor.window import DataviewEditorWindow

            if data.dataview is None:
                data.dataview = SharedDataviewData(
                    data.store,
                    get_folder=self._dataview_folder,
                    filter_func=self._apply_active_filter,
                )

            DataviewEditorWindow(
                self.root,
                session=data,
                get_title_suffix=self._click_filename,
                get_simulation=lambda: self._session.simulation if self._session else None,
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            self._update_status(f"Error opening dataview editor: {e}", "error")

    def _open_simulator(self):
        """Open the Simulator window, or focus if already open."""
        session = self._session
        if session is not None and self._focus_simulator(session):
            return
        simulation = self._simulation_for_window("Cannot Simulate", "Simulation")
        if session is None or simulation is None:
            return

        from .views.simulator_window import SimulatorWindow

        session.simulator = SimulatorWindow(
            self.root,
            simulation=simulation,
            get_store=self._get_store,
            get_analysis=lambda: session.analysis,
            open_dataview=self._open_dataview_editor,
            filter_func=self._apply_active_filter,
            on_destroy=lambda: setattr(session, "simulator", None),
            title_suffix=session.click.filename,
        )
        simulation.turn_on()

    def _show_odbc_warning(self):
        """Show a database warning unless CSV mode was explicitly selected."""
        from .utils.mdb_shared import get_database_backend

        if get_database_backend() != "none":
            OdbcWarningDialog(self.root)

    def _on_editor_synced(self, addr_keys: set[int]) -> None:
        # Only a database Sync puts tags into CLICK; a CSV save does not.
        if self._session is not None and self.using_database:
            self._session.record_sync(addr_keys)
            analysis = self._session.analysis
            if analysis is not None and (
                analysis.system_nickname_repairs or analysis.needs_comment_upgrade
            ):
                self._start_analysis_build()

    def _open_address_editor(
        self, initial_filter: str | None = None, *, close_after_sync: bool = False
    ):
        """Open the Address Editor window.

        Multiple windows can be opened and they will share the same data.
        Changes made in one window are automatically reflected in others.

        Args:
            initial_filter: If given (e.g. "changed"), the new window's first tab
                is switched to that row filter once its data has loaded.
            close_after_sync: The window is opened to Sync edits staged elsewhere;
                its Sync button reads "Sync and Close".
        """
        # Check for a native or fallback database backend
        if self._data is None and not self.nickname_manager.has_database_backend():
            self._show_odbc_warning()
            return

        data = self._data
        if data is None:
            self._update_status("No data loaded", "error")
            return

        try:
            from .views.address_editor.window import AddressEditorWindow

            window = AddressEditorWindow(
                self.root,
                session=data,
                get_click_filename=self._click_filename,
                get_analysis_service=lambda: self._session.analysis if self._session else None,
                on_synced=self._on_editor_synced,
                get_synced_pending=lambda: self._session.synced_pending if self._session else 0,
                close_after_sync=close_after_sync,
            )
            if initial_filter:
                window.apply_row_filter(initial_filter)

        except Exception as e:
            import traceback

            traceback.print_exc()
            self._update_status(f"Error opening editor: {e}", "error")

    def _repair_system_nicknames(self) -> None:
        """Stage documented system nickname fixes for review and Sync."""

        store = self._get_store()
        if store is None:
            self._update_status("No address data loaded", "error")
            return

        from .services.system_nickname_service import stage_system_nickname_repairs

        repairs = stage_system_nickname_repairs(store)
        if not repairs:
            self._update_status("No documented system nickname repairs needed", "connected")
            return

        self._open_address_editor("changed")
        self._update_status(
            f"Staged {len(repairs)} system nickname repair(s); review Changed, then Sync",
            "connected",
        )

    def _refresh_upgrade_entry(self) -> None:
        """Enable Upgrade Project while a comment holds an old annotation form.

        Runs as the Repairs menu opens, so it sees the comments as they are now.
        """
        from .services.comment_upgrade_service import find_comment_upgrades

        store = self._get_store()
        needed = store is not None and bool(find_comment_upgrades(store))
        self.repairs_menu.entryconfigure(
            self._repairs_upgrade_project_index,
            state=tk.NORMAL if needed else tk.DISABLED,
        )

    def _upgrade_project(self) -> None:
        """Stage pyrung's rewrites of old annotation forms for review and Sync."""
        store = self._get_store()
        if store is None:
            self._update_status("No address data loaded", "error")
            return

        from .services.comment_upgrade_service import stage_comment_upgrades

        upgrades = stage_comment_upgrades(store)
        staged = sum(1 for upgrade in upgrades if upgrade.staged)
        problems = [
            f"{upgrade.display_address}: {upgrade.problem}"
            for upgrade in upgrades
            if upgrade.problem
        ]
        if staged:
            self._open_address_editor("changed")
        if problems:
            messagebox.showwarning(
                "Upgrade Project",
                "pyrung still refuses these comments. Fix them by hand.\n\n" + "\n".join(problems),
                parent=self.root,
            )
        if not staged:
            if problems:
                self._update_status("No comment upgrade staged", "error")
            else:
                self._update_status("Every annotation is already in the current form", "connected")
            return
        self._update_status(
            f"Staged {staged} comment upgrade(s). Review Changed, then Sync.",
            "connected",
        )

    def _run_program_checks(self):
        """Validate the current connection for an initial report or an in-window rerun."""
        analysis = self._session.analysis if self._session else None
        if analysis is None or not analysis.is_available:
            from .services.analysis_service import AnalysisStatus

            status = analysis.status if analysis else None
            if status is AnalysisStatus.FAILED:
                messagebox.showerror(
                    "Analysis Failed",
                    f"{analysis.error}\n\nCheck Program needs the project converted to pyrung.",
                    parent=self.root,
                )
            elif status is AnalysisStatus.BUILDING:
                messagebox.showinfo(
                    "Analysis In Progress",
                    "The program is still being converted for analysis.\n\nTry again in a moment.",
                    parent=self.root,
                )
            else:
                messagebox.showinfo(
                    "Analysis Not Available",
                    "Program analysis requires a connected Click project.\n\n"
                    "Analysis builds automatically when connected to a project "
                    "with ladder files.",
                    parent=self.root,
                )
            return

        try:
            report = analysis.run_validation()
        except Exception as exc:
            messagebox.showerror(
                "Analysis Error",
                f"Validation failed:\n{exc}",
                parent=self.root,
            )
            return

        from .services.program_check import group_validation_findings

        # The GUI and clicknick-cli use the same finding grouping and pyrung
        # presentation model; only their renderers differ.
        grouped = group_validation_findings(report)

        from .views.analysis_report_window import AnalysisReportData

        return AnalysisReportData(
            grouped_findings=grouped,
            project_name=self._click.filename if self._click else "",
            checked_rules=report.checked_rules if report is not None else frozenset(),
        )

    def _choose_program_checks(self, parent, on_saved) -> None:
        from .views.check_selection_window import CheckSelectionWindow

        analysis = self._session.analysis if self._session else None
        selection = analysis.check_selection if analysis is not None else None
        if selection is None:
            messagebox.showinfo(
                "Check Settings", "Connect to a project before choosing checks.", parent=parent
            )
            return
        try:
            CheckSelectionWindow(parent, selection, on_saved)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Check Settings", str(exc), parent=parent)

    def _analyze_program(self) -> None:
        """Run program validation and display a report that can be refreshed in place."""
        from .views.analysis_report_window import AnalysisReportWindow

        data = self._run_program_checks()
        if data is not None:
            AnalysisReportWindow(
                self.root,
                data,
                rerun=self._run_program_checks,
                choose_checks=self._choose_program_checks,
            )

    def _ensure_plc_name_for_workspace(self) -> str | None:
        """Prompt for a missing PLC name only when durable setup is requested."""
        plc_name = self._current_plc_name()
        if plc_name:
            return plc_name

        from .models.name_validation import validate_click_name
        from .services.workspace_mirror import write_plc_name
        from .utils.click_temp import click_temp_dir

        if self._session is None or self._click is None:
            self._update_status("Connect to a CLICK project first", "error")
            return None

        parent = getattr(self, "_mirror_setup_window", None) or self.root
        while True:
            value = simpledialog.askstring(
                "Name PLC",
                "This project needs a PLC name before it can use a durable workspace.\n\n"
                "Enter a name (maximum 24 characters):",
                parent=parent,
            )
            if value is None:
                return None
            plc_name = value.strip()
            is_valid, error = validate_click_name(plc_name)
            if not is_valid:
                messagebox.showerror("Invalid PLC Name", error, parent=parent)
                continue
            try:
                write_plc_name(
                    click_temp_dir(self._click.hwnd) / "Project.ini",
                    plc_name,
                )
            except (OSError, ValueError) as exc:
                messagebox.showerror("Name PLC", str(exc), parent=parent)
                self._update_status(f"PLC name could not be set: {exc}", "error")
                return None
            self.plc_name_var.set(plc_name)
            messagebox.showinfo(
                "PLC Name Added",
                f'CLICK now identifies this PLC as "{plc_name}".\n\n'
                "Save the project in CLICK to preserve the name.",
                parent=parent,
            )
            return plc_name

    def _set_pending_workspace_config(self, config) -> None:
        """Show one candidate configuration in the setup form."""
        self._pending_workspace_config = config
        if all(known.sidecar_path != config.sidecar_path for known in self._workspace_matches):
            self._workspace_matches.append(config)
        if config.sidecar_path.is_file():
            self.mirror_project_selection_var.set(str(config.workspace_path))
            self.mirror_location_selection_var.set("")
            self.workspace_setup_action_var.set("Use Workspace")
        else:
            self.mirror_project_selection_var.set("")
            self.mirror_location_selection_var.set(str(config.workspace_path))
            self.workspace_setup_action_var.set("Create Workspace")
        if hasattr(self, "workspace_config_combobox"):
            self.workspace_config_combobox.configure(
                values=[str(match.workspace_path) for match in self._workspace_matches]
            )

    def _select_existing_workspace_config(self) -> None:
        """Browse an existing workspace folder and verify its PLC identity."""
        plc_name = self._ensure_plc_name_for_workspace()
        if plc_name is None:
            return
        parent = getattr(self, "_mirror_setup_window", None) or self.root
        pending = self._pending_workspace_config
        selected = filedialog.askdirectory(
            title=f"Find an existing workspace for {plc_name}",
            initialdir=pending.workspace_path.parent if pending is not None else None,
            mustexist=True,
            parent=parent,
        )
        if not selected:
            return

        from .services.workspace_mirror import (
            load_project_workspace_config,
            sidecar_path_for,
        )

        try:
            config = load_project_workspace_config(sidecar_path_for(Path(selected)))
        except ValueError as exc:
            messagebox.showerror("Choose Workspace", str(exc), parent=parent)
            return
        if config.plc_name.casefold() != plc_name.casefold():
            messagebox.showerror(
                "Choose Workspace",
                f'This workspace belongs to PLC "{config.plc_name}", not "{plc_name}".',
                parent=parent,
            )
            return
        self._set_pending_workspace_config(config)

    def _select_mirror_location(self) -> None:
        """Choose a home and review the PLC-named workspace destination."""
        plc_name = self._ensure_plc_name_for_workspace()
        if plc_name is None:
            return
        parent = getattr(self, "_mirror_setup_window", None) or self.root
        pending = self._pending_workspace_config
        initial_dir = pending.workspace_path.parent if pending is not None else None
        selected = filedialog.askdirectory(
            title=f"Choose workspace home for {plc_name}",
            initialdir=initial_dir,
            mustexist=True,
            parent=parent,
        )
        if not selected:
            return

        from .services.workspace_mirror import (
            ProjectWorkspaceConfig,
            load_project_workspace_config,
            sidecar_path_for,
            workspace_path_for_selection,
        )

        home = Path(selected)
        workspace_path = workspace_path_for_selection(home, plc_name)
        sidecar = sidecar_path_for(workspace_path)
        if sidecar.is_file():
            try:
                config = load_project_workspace_config(sidecar)
            except ValueError as exc:
                messagebox.showerror("Setup Workspace", str(exc), parent=parent)
                return
        else:
            config = ProjectWorkspaceConfig(
                plc_name=plc_name,
                workspace_path=workspace_path,
            )
        self._set_pending_workspace_config(config)

    def _on_workspace_config_selected(self, _event=None) -> None:
        """Review a known matching workspace selected by the user."""
        selected = self.mirror_project_selection_var.get().strip()
        config = next(
            (match for match in self._workspace_matches if str(match.workspace_path) == selected),
            None,
        )
        if config is not None:
            self._set_pending_workspace_config(config)

    def _earlier_save_build_error(self) -> str | None:
        """The build's error when it failed and the workspace is an earlier save's, else None."""
        from .services.analysis_service import AnalysisStatus

        analysis = self._session.analysis if self._session else None
        if analysis is None or analysis.status is not AnalysisStatus.FAILED:
            return None
        if analysis.project_is_current:
            return None
        return analysis.error or "The build failed."

    def _apply_workspace_mirror_setup(self) -> None:
        """Make the selected durable directory the active project workspace."""
        dialog_parent = getattr(self, "_mirror_setup_window", None) or self.root
        if self._session is None:
            self._update_status("Connect to a CLICK project first", "error")
            return
        config = self._pending_workspace_config
        if config is None:
            messagebox.showinfo(
                "Workspace",
                "Choose an existing workspace or select a home for a new one.",
                parent=dialog_parent,
            )
            return
        mirror_path = config.workspace_path.resolve()
        source = self._workspace_source_dir()
        changing_location = source is not None and source.resolve() != mirror_path
        # Refused before asking for a PLC name, which is written into CLICK's folder
        build_error = self._earlier_save_build_error()
        if build_error is not None and changing_location:
            messagebox.showerror(
                "Setup Workspace",
                "The workspace could not be built from CLICK's last save, so ClickNick "
                "will not copy an earlier save's workspace.\n\n" + build_error,
                parent=dialog_parent,
            )
            return
        plc_name = self._ensure_plc_name_for_workspace()
        if plc_name is None:
            self._update_status("Connect to a CLICK project first", "error")
            return
        if config.plc_name.casefold() != plc_name.casefold():
            messagebox.showerror(
                "Setup Workspace",
                f'This workspace belongs to PLC "{config.plc_name}", not "{plc_name}".',
                parent=dialog_parent,
            )
            return

        try:
            mirror_is_nonempty = mirror_path.exists() and any(mirror_path.iterdir())
        except OSError as exc:
            messagebox.showerror("Setup Workspace", str(exc), parent=dialog_parent)
            self._update_status(f"Workspace setup failed: {exc}", "error")
            return
        current_mirror = self._workspace_config.workspace_path if self._workspace_config else None
        same_mirror = (
            current_mirror is not None and mirror_path.resolve() == current_mirror.resolve()
        )
        if mirror_is_nonempty and not same_mirror:
            confirmed = messagebox.askokcancel(
                "Use Existing Workspace Folder?",
                f"Use the existing folder?\n\n{mirror_path}\n\n"
                "ClickNick will update generated files under src/plc and csv, plus "
                "its generation scripts and data. It will not delete unrelated files "
                "or replace existing tests, documentation, or editor settings.",
                parent=dialog_parent,
            )
            if not confirmed:
                return

        from .services.workspace_mirror import (
            remember_project_sidecar,
            save_project_workspace_config,
            sync_workspace_to_mirror,
            validate_mirror_destination,
        )

        try:
            if changing_location:
                validate_mirror_destination(source, mirror_path)
            mirror_path.mkdir(parents=True, exist_ok=True)
            if changing_location:
                sync_workspace_to_mirror(source, mirror_path)
            sidecar = save_project_workspace_config(config)
            remember_project_sidecar(sidecar, preferred_for=plc_name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Setup Workspace", str(exc), parent=dialog_parent)
            self._update_status(f"Workspace setup failed: {exc}", "error")
            return

        self._workspace_config = config
        self._workspace_matches = [
            match for match in self._workspace_matches if match.sidecar_path != sidecar
        ] + [config]
        self._workspace_mirror_error = None
        self.mirror_project_selection_var.set(str(mirror_path.resolve()))
        self.mirror_location_selection_var.set("")
        self.workspace_setup_action_var.set("Use Workspace")
        self._session.use_workspace(mirror_path)
        self._session.record_rung_stage(0)
        self._update_status(f"Workspace configured: {mirror_path}", "connected")
        self._start_analysis_build()

    def _open_folder(self, path: Path | None, *, title: str, unavailable: str) -> None:
        """Open one explicit workspace location in File Explorer."""
        if path is None or not path.is_dir():
            self._update_status(unavailable, "error")
            return
        try:
            import os

            os.startfile(path)  # noqa: S606 - explicit user action on Windows
        except OSError as exc:
            messagebox.showerror(title, str(exc), parent=self.root)

    def _open_workspace(self) -> None:
        """Open the one active workspace used by Review Changes and the Simulator."""
        self._open_folder(
            self._workspace_display_dir(),
            title="Open Workspace",
            unavailable="Workspace is not available",
        )

    def _details_value(self, parent, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(
            parent,
            textvariable=variable,
            style="Status.TLabel",
            wraplength=440,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X)

    def _close_mirror_setup_window(self) -> None:
        window = self._mirror_setup_window
        self._mirror_setup_window = None
        if window is not None:
            window.destroy()

    def _create_mirror_setup_contents(self, parent) -> None:
        """Create task-oriented controls for using or creating a workspace."""
        summary = ttk.LabelFrame(parent, text="Workspace", padding=8)
        ttk.Label(
            summary,
            textvariable=self.mirror_setup_status_var,
            style="Connected.TLabel",
        ).pack(anchor=tk.W)
        plc_row = ttk.Frame(summary)
        ttk.Label(plc_row, text="PLC name").pack(side=tk.LEFT)
        ttk.Label(plc_row, textvariable=self.plc_name_var, style="Status.TLabel").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        plc_row.pack(fill=tk.X, pady=(6, 0))
        summary.pack(fill=tk.X, pady=(0, 10))

        existing = ttk.LabelFrame(parent, text="Use an existing workspace", padding=8)
        ttk.Label(
            existing,
            text="Choose a known workspace, or find a workspace folder on this computer.",
            style="Status.TLabel",
        ).pack(anchor=tk.W, pady=(0, 6))
        existing_row = ttk.Frame(existing)
        self.workspace_config_combobox = ttk.Combobox(
            existing_row,
            textvariable=self.mirror_project_selection_var,
            state="readonly",
            values=[str(match.workspace_path) for match in self._workspace_matches],
        )
        self.workspace_config_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.workspace_config_combobox.bind(
            "<<ComboboxSelected>>", self._on_workspace_config_selected
        )
        ttk.Button(
            existing_row,
            text="Find Existing...",
            command=self._select_existing_workspace_config,
        ).pack(side=tk.LEFT, padx=(8, 0))
        existing_row.pack(fill=tk.X)
        existing.pack(fill=tk.X, pady=(0, 10))

        new = ttk.LabelFrame(parent, text="Create a new workspace", padding=8)
        ttk.Label(
            new,
            text="Choose a location. ClickNick will create the PLC-named folder shown below.",
            style="Status.TLabel",
        ).pack(anchor=tk.W, pady=(0, 6))
        new_row = ttk.Frame(new)
        ttk.Entry(
            new_row,
            textvariable=self.mirror_location_selection_var,
            state="readonly",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            new_row,
            text="Choose Location...",
            command=self._select_mirror_location,
        ).pack(side=tk.LEFT, padx=(8, 0))
        new_row.pack(fill=tk.X)
        new.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            parent,
            textvariable=self.mirror_detail_var,
            style="Error.TLabel",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        buttons = ttk.Frame(parent)
        ttk.Button(
            buttons,
            textvariable=self.workspace_setup_action_var,
            command=self._apply_workspace_mirror_setup,
        ).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self._close_mirror_setup_window).pack(
            side=tk.RIGHT
        )
        buttons.pack(fill=tk.X)

    def _open_mirror_setup_window(self) -> None:
        """Show workspace details before offering setup or reconfiguration."""
        if self._mirror_setup_window is not None:
            try:
                self._mirror_setup_window.lift()
                self._mirror_setup_window.focus_force()
                return
            except tk.TclError:
                self._mirror_setup_window = None

        if self._ensure_plc_name_for_workspace() is None:
            return

        config = self._workspace_config
        self._pending_workspace_config = config
        self.mirror_project_selection_var.set(str(config.workspace_path) if config else "")
        self.mirror_location_selection_var.set("")
        self.workspace_setup_action_var.set("Use Workspace" if config else "Create Workspace")
        window = tk.Toplevel(self.root)
        window.title("Workspace")
        window.transient(self.root)
        window.minsize(640, 0)
        window.protocol("WM_DELETE_WINDOW", self._close_mirror_setup_window)
        contents = ttk.Frame(window, padding=12)
        self._create_mirror_setup_contents(contents)
        contents.pack(fill=tk.BOTH, expand=True)
        self._mirror_setup_window = window
        self._request_ui_refresh()

    def _populate_workspace_options_menu(self, menu: tk.Menu) -> None:
        """Add active-directory commands to the Workspace options menu."""
        self._workspace_options_open_index = 0
        label, state = self._open_workspace_menu_options()
        menu.add_command(
            label=label,
            command=self._open_workspace,
            state=state,
        )
        menu.add_separator()
        menu.add_command(
            label="View/Setup Workspace...",
            command=self._open_mirror_setup_window,
        )

    def _create_action_section(self, parent) -> None:
        """Create the primary Edit, Test, and Workspace action groups."""
        actions = ttk.Frame(parent)
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="main-actions")

        edit = ttk.LabelFrame(actions, padding=10)
        edit_header = ttk.Frame(edit)
        ttk.Label(edit_header, text="Edit").pack(side=tk.LEFT)
        edit_header_spacer = ttk.Frame(edit_header, width=1, height=1)
        edit_header_spacer.pack(side=tk.LEFT)
        edit.configure(labelwidget=edit_header)
        ttk.Button(
            edit,
            text="Address Editor",
            image=self._action_icons.get("address_editor"),
            compound=tk.LEFT,
            command=self._open_address_editor,
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            edit,
            text="Data View",
            image=self._action_icons.get("data_view"),
            compound=tk.LEFT,
            command=self._open_dataview_editor,
        ).pack(fill=tk.X)

        test = ttk.LabelFrame(actions, padding=10)
        # Like Workspace: the legend carries the state, with its control beside it.
        # The simulation runs headless until stopped here (or the project closes);
        # closing the Simulator leaves it running.
        test_header = ttk.Frame(test)
        ttk.Label(test_header, textvariable=self.test_group_title_var).pack(side=tk.LEFT)
        test_header_spacer = ttk.Frame(test_header, width=1, height=1)
        test_header_spacer.pack(side=tk.LEFT)
        # Flat, like Workspace's Options, so the legends stay the same height.
        simulation_button = ttk.Button(
            test_header,
            textvariable=self.simulation_action_var,
            style="Toolbutton",
            cursor="hand2",
            command=self._toggle_simulation,
        )
        simulation_button.pack(side=tk.LEFT, padx=(8, 0))
        bind_tooltip(
            simulation_button,
            "Start or stop the simulated PLC. It keeps running after the\n"
            "Simulator closes, so a Data View or HMI can stay connected.",
        )
        test.configure(labelwidget=test_header)
        ttk.Button(
            test,
            text="Check Program",
            image=self._action_icons.get("check_program"),
            compound=tk.LEFT,
            command=self._analyze_program,
        ).pack(fill=tk.X, pady=(0, 8))
        # The one door to simulation; the command console is a pane inside it.
        ttk.Button(
            test,
            text="Simulate",
            image=self._action_icons.get("console"),
            compound=tk.LEFT,
            command=self._open_simulator,
        ).pack(fill=tk.X)

        workspace = ttk.LabelFrame(actions, padding=10)
        workspace_header = ttk.Frame(workspace)
        ttk.Label(workspace_header, textvariable=self.workspace_group_title_var).pack(side=tk.LEFT)
        workspace_options_button = ttk.Menubutton(workspace_header, text="Options")
        workspace_options_menu = tk.Menu(workspace_options_button, tearoff=0)
        self._populate_workspace_options_menu(workspace_options_menu)
        workspace_options_button.configure(menu=workspace_options_menu)
        workspace_options_button.pack(side=tk.LEFT, padx=(8, 0))
        workspace.configure(labelwidget=workspace_header)
        self.workspace_options_menu = workspace_options_menu

        # Give all three legends the same theme-derived height.  The invisible
        # spacers make Edit/Test use the Workspace menubutton's height while
        # leaving their visible labels centered on the same baseline.
        workspace_options_button.update_idletasks()
        header_height = workspace_options_button.winfo_reqheight()
        edit_header_spacer.configure(height=header_height)
        test_header_spacer.configure(height=header_height)
        ttk.Button(
            workspace,
            text="Review Changes",
            image=self._action_icons.get("review_changes"),
            compound=tk.LEFT,
            command=self._workspace_rung_apply,
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            workspace,
            text="Reload from CLICK",
            image=self._action_icons.get("reload_from_click"),
            compound=tk.LEFT,
            command=self._workspace_reload_from_click,
        ).pack(fill=tk.X)

        edit.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        test.grid(row=0, column=1, sticky="nsew", padx=5)
        workspace.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        actions.pack(fill=tk.BOTH, expand=True)

    def _close_project_info_window(self) -> None:
        window = self._project_info_window
        self._project_info_window = None
        if window is not None:
            window.destroy()

    def _create_project_info_contents(self, parent) -> None:
        """Create the read-only CLICK project and Workspace summary."""
        project = ttk.LabelFrame(parent, text="CLICK Project", padding=8)
        self._details_value(project, "Project", self.project_name_var)
        self._details_value(project, "PLC name", self.plc_name_var)
        self._details_value(
            project,
            "Workspace file",
            self.workspace_config_path_var,
        )
        project.pack(fill=tk.X, pady=(0, 10))

        mirror = ttk.LabelFrame(parent, text="Workspace", padding=8)
        self._details_value(mirror, "Workspace status", self.workspace_status_var)
        self._details_value(mirror, "Workspace type", self.mirror_status_var)
        self._details_value(mirror, "Workspace folder", self.mirror_path_var)
        mirror_detail_label = ttk.Label(
            mirror,
            textvariable=self.mirror_detail_var,
            style="Error.TLabel",
            wraplength=440,
            justify=tk.LEFT,
        )
        mirror_detail_label.pack(anchor=tk.W, fill=tk.X)
        self._details_value(mirror, "Last regenerated", self.last_regenerated_var)
        self._details_value(mirror, "Last backup", self.last_backup_var)
        mirror.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(parent, text="Close", command=self._close_project_info_window).pack(anchor=tk.E)

    def _open_project_info_window(self) -> None:
        """Open or focus the current CLICK project's information window."""
        if self._project_info_window is not None:
            try:
                self._project_info_window.lift()
                self._project_info_window.focus_force()
                return
            except tk.TclError:
                self._project_info_window = None

        window = tk.Toplevel(self.root)
        window.title("About Click Project")
        window.transient(self.root)
        window.minsize(520, 0)
        window.protocol("WM_DELETE_WINDOW", self._close_project_info_window)
        contents = ttk.Frame(window, padding=12)
        self._create_project_info_contents(contents)
        contents.pack(fill=tk.BOTH, expand=True)
        self._project_info_window = window
        self._request_ui_refresh()

    def _create_about_dialog(self):
        """Create and show the About dialog."""
        AboutDialog(self.root, get_version(), db_path=self._live_mdb_path())

    def _live_open_address_editor(self, initial_filter: str = "changed") -> None:
        """Open or focus the Address Editor filtered to *initial_filter*.

        Callback for ``clicknick-cli tag apply``. Reuses an already-open editor
        (they all share one store) rather than stacking new windows on repeat
        applies. Runs on the Tk main thread (the live server marshals it there).
        """
        if self._data is not None:
            from .views.address_editor.window import AddressEditorWindow

            for win in self._data.editors:
                if isinstance(win, AddressEditorWindow) and win.winfo_exists():
                    win.apply_row_filter(initial_filter)
                    return
        self._open_address_editor(initial_filter=initial_filter)

    def _verify_mdb_and_cdv(self):
        """Verify MDB addresses and CDV entries for validity."""
        if self._click is None:
            self._update_status("Connect to a ClickPLC window first", "error")
            return

        store = self._get_store()
        if store is None:
            self._update_status("No data loaded", "error")
            return

        from tkinter import messagebox, scrolledtext

        from .data.cdv_file import click_dataview_folder
        from .utils.verification import run_verification

        result = run_verification(store, click_dataview_folder(self._click.hwnd))

        if result.passed:
            messagebox.showinfo(
                "Verification Complete",
                f"All checks passed!\n\n"
                f"MDB addresses verified: {result.total_addresses}\n"
                f"CDV files verified: {result.cdv_files_checked}",
                parent=self.root,
            )
        else:
            # Create a dialog with scrollable text
            dialog = tk.Toplevel(self.root)
            dialog.title("Verification Results")
            dialog.geometry("700x500")
            dialog.transient(self.root)

            summary = (
                f"Found {result.total_issues} issue(s)\n"
                f"MDB issues: {len(result.mdb_issues)} (of {result.total_addresses} addresses)\n"
                f"CDV issues: {len(result.cdv_issues)} (in {result.cdv_files_checked} files)"
            )
            ttk.Label(dialog, text=summary, padding=10).pack(fill=tk.X)

            ttk.Button(dialog, text="Close", command=dialog.destroy).pack(
                side=tk.BOTTOM, pady=(0, 10)
            )

            text_area = scrolledtext.ScrolledText(dialog, wrap=tk.WORD, width=80, height=20)
            text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
            text_area.insert(tk.END, "\n".join(result.all_issues))
            text_area.config(state=tk.DISABLED)

            dialog.grab_set()
            dialog.focus_set()

    def _clean_mdb(self):
        """Clean MDB database by removing empty, unused rows.

        Loads rows directly from MDB (no placeholders) and deletes any rows where
        needs_full_delete is True (no content, not used).
        """
        if self._click is None:
            self._update_status("Connect to a ClickPLC window first", "error")
            return

        store = self._get_store()
        if store is None:
            self._update_status("No data loaded", "error")
            return

        from tkinter import messagebox

        from .data.data_source import MdbDataSource

        # Get the MDB path from the current data source
        data_source = store._data_source
        if not hasattr(data_source, "file_path"):
            self._update_status("Current data source has no file path", "error")
            return

        mdb_path = data_source.file_path

        # Create a fresh MdbDataSource to load directly from MDB
        try:
            fresh_source = MdbDataSource(db_path=mdb_path)
            all_rows = fresh_source.load_all_addresses()
        except Exception as e:
            self._update_status(f"Error loading MDB: {e}", "error")
            return

        # Find rows that need deletion (no content, not used)
        rows_to_delete = [row for row in all_rows.values() if row.needs_full_delete(is_dirty=True)]

        if not rows_to_delete:
            messagebox.showinfo(
                "Clean MDB",
                "No empty, unused rows found to clean.",
                parent=self.root,
            )
            return

        # Confirm with user
        if not messagebox.askyesno(
            "Clean MDB",
            f"Found {len(rows_to_delete)} empty, unused rows to delete.\n\n"
            "These are rows in the database that have no nickname, no comment, "
            "default initial value, default retentive, and are not used by the PLC program.\n\n"
            "Proceed with deletion?",
            parent=self.root,
        ):
            return

        # Delete the rows
        try:
            deleted_count = fresh_source.save_changes(rows_to_delete)
            messagebox.showinfo(
                "Clean MDB",
                f"Successfully deleted {deleted_count} rows from the MDB.",
                parent=self.root,
            )
        except Exception as e:
            self._update_status(f"Error cleaning MDB: {e}", "error")

    def _export_pyrung_project(self):
        """Copy the connected project's ready workspace."""
        from .services.analysis_service import AnalysisStatus

        analysis = self._session.analysis if self._session else None
        if analysis is None:
            messagebox.showinfo(
                "Export Workspace",
                "Connect to a CLICK project before exporting its workspace.",
                parent=self.root,
            )
            return
        if analysis.status is AnalysisStatus.BUILDING:
            messagebox.showinfo(
                "Export Workspace",
                "The workspace is still being prepared. Try again in a moment.",
                parent=self.root,
            )
            return
        build_error = self._earlier_save_build_error()
        if build_error is not None:
            messagebox.showerror(
                "Export Workspace",
                "The workspace could not be built from CLICK's last save, so there is "
                "nothing current to export.\n\n" + build_error,
                parent=self.root,
            )
            return
        if analysis.project_dir is None:
            messagebox.showinfo(
                "Export Workspace",
                "Save the project in Click Software, then try again.",
                parent=self.root,
            )
            return

        output = filedialog.askdirectory(
            title="Export Workspace — choose a parent folder",
            parent=self.root,
            mustexist=False,
        )
        if not output:
            return

        destination = Path(output) / "pyrung_project"
        try:
            file_count = analysis.export_project(destination)
        except Exception as exc:
            messagebox.showerror("Export pyrung Project", str(exc), parent=self.root)
            return

        self._update_status(
            f"Exported workspace ({file_count} files) to {destination}",
            "connected",
        )

    def _load_ladder_csv(self):
        """Load a single ladder CSV file to the clipboard, for the connected CLICK window."""
        click = self._click
        if click is None:
            # What is copied depends on the CLICK it goes into, and its version
            messagebox.showinfo(
                "Load Ladder CSV",
                "Not connected to CLICK. Connect to the CLICK window to paste into, "
                "then load the CSV again.",
                parent=self.root,
            )
            return
        csv_file = filedialog.askopenfilename(
            title="Load Ladder CSV to Clipboard",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self.root,
        )
        if not csv_file:
            return

        from .ladder.clipboard import copy_to_clipboard, is_click_v4
        from .ladder.program import prepare_csv_load

        csv_path = Path(csv_file)
        mdb_path = self._live_mdb_path()

        try:
            click_v4 = is_click_v4(click.hwnd)
            result = prepare_csv_load(csv_path, click_v4=click_v4, mdb_path=mdb_path)
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror(
                "Load Ladder CSV",
                str(exc),
                parent=self.root,
            )
            return

        try:
            copy_to_clipboard(result.payload, owner_hwnd=click.hwnd)
        except RuntimeError as exc:
            messagebox.showerror(
                "Load Ladder CSV",
                f"Could not copy to clipboard:\n\n{exc}",
                parent=self.root,
            )
            return

        rungs = f"{result.rung_count} rung{'s' if result.rung_count != 1 else ''}"
        self._update_status(
            f"Copied {rungs} from {csv_path.name} to clipboard",
            "connected",
        )

    def _save_clipboard_csv(self):
        """Save Click clipboard data to a CSV file."""
        csv_file = filedialog.asksaveasfilename(
            title="Save Clipboard to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self.root,
        )
        if not csv_file:
            return

        from pathlib import Path

        from .ladder.clipboard import read_from_clipboard
        from .ladder.program import decode_to_csv

        try:
            data = read_from_clipboard()
        except RuntimeError as exc:
            messagebox.showerror(
                "Save Clipboard to CSV",
                str(exc),
                parent=self.root,
            )
            return

        csv_path = Path(csv_file)
        try:
            decode_to_csv(data, csv_path)
        except Exception as exc:
            messagebox.showerror(
                "Save Clipboard to CSV",
                f"Could not decode clipboard data:\n\n{exc}",
                parent=self.root,
            )
            return

        self._update_status(
            f"Saved clipboard to {csv_path.name}",
            "connected",
        )

    def _show_review_changes(
        self,
        folder: Path,
        source_dir: Path | None = None,
        program: str | None = None,
        rungs: list[int] | None = None,
        create: bool = True,
        *,
        source: ProposalSource | None = None,
        refresh_source: Callable[[], None] | None = None,
    ) -> None:
        """Show *folder* in Review Changes: one window per folder, reloaded when shown again.

        Review Changes (``rung apply``) passes the workspace source the folder
        was exported from, and may name a program to start on and the rungs of
        it to paste. With *create* off, only a window already showing the folder
        is brought up to date. *source* says where the folder comes from: the
        workspace or the folder itself unless given; *refresh_source* copies it
        again from there.
        """
        from .views.review_changes_window import ProposalSource, ReviewChangesWindow

        if source is None:
            source = ProposalSource.of(folder, source_dir)
        self._review_changes_windows = {
            path: window
            for path, window in self._review_changes_windows.items()
            if window.winfo_exists()
        }
        select = (program, rungs) if program else None
        key = folder.resolve()
        window = self._review_changes_windows.get(key)
        if window is not None:
            window.reload(
                source, source_dir=source_dir, refresh_source=refresh_source, select=select
            )
        elif create:
            window = self._review_changes_windows[key] = ReviewChangesWindow(
                self.root,
                folder,
                get_mdb_path=self._live_mdb_path,
                get_click_hwnd=lambda: self._click.hwnd if self._click else None,
                get_saved_program=lambda: (
                    self._session.saved_program() if self._session else SavedProgram()
                ),
                get_project_store=lambda: self._get_store() if self.using_database else None,
                open_staged_nicknames=lambda: self._open_address_editor(
                    "changed", close_after_sync=True
                ),
                source=source,
                source_dir=source_dir,
                refresh_source=refresh_source,
                select=select,
                on_pasted=lambda message: self._update_status(message, "connected"),
            )
        if window is not None and create:
            window.after_idle(window.show)

    def _compare_with_folder(self):
        """Compare CLICK's program with a folder of ladder CSVs, in Review Changes."""
        folder = filedialog.askdirectory(
            title="Compare with — choose a folder of ladder CSVs",
            parent=self.root,
        )
        if folder:
            self._show_review_changes(Path(folder))

    def _compare_with_click_window(self, hwnd: int, filename: str) -> None:
        """Compare CLICK's program with what another CLICK window last saved.

        Its save and nicknames are copied to a ClickNick folder, which Review
        Changes shows as a copy of another PLC; Refresh copies them again, as
        long as that window still has the same project open.
        """
        from .services.click_snapshot import snapshot_click_program, snapshot_dir
        from .utils.click_temp import click_temp_dir
        from .views.review_changes_window import ProposalSource

        open_now = {
            instance.hwnd: instance.filename for instance in self.detector.get_click_instances()
        }
        if open_now.get(hwnd) != filename:
            messagebox.showerror(
                "Compare with",
                f"The CLICK window that had {filename} open is closed, or has another project "
                "open now. Choose a window under Ladder > Compare with > Other CLICK window.",
                parent=self.root,
            )
            return
        project = filename.removesuffix(".ckp")
        dest = snapshot_dir(hwnd)
        self._update_status(f"Reading {filename}'s program…", "status")
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            note = snapshot_click_program(click_temp_dir(hwnd), dest)
        except FileNotFoundError:
            messagebox.showerror(
                "Compare with",
                f"{filename} has no saved program to compare with. Save it in CLICK first.",
                parent=self.root,
            )
            return
        except (OSError, ValueError) as exc:  # A save or copy ClickNick cannot read or replace
            messagebox.showerror(
                "Compare with", f"Could not read {filename}'s program: {exc}", parent=self.root
            )
            return
        finally:
            self.root.configure(cursor="")
        self._update_status(
            f"Compared with {filename}" + (f"; {note}" if note else ""),
            "error" if note else "connected",
        )
        self._show_review_changes(
            dest,
            source=ProposalSource.other_click(project),
            refresh_source=lambda: self._compare_with_click_window(hwnd, filename),
        )

    def _fill_other_click_menu(self, menu: tk.Menu) -> None:
        """List the CLICK windows other than the connected one, to compare with."""
        menu.delete(0, tk.END)
        connected = self._click.hwnd if self._click else None
        others = [
            instance
            for instance in self.detector.get_click_instances()
            if instance.hwnd != connected
        ]
        if not others:
            menu.add_command(label="(no other CLICK window open)", state=tk.DISABLED)
        for instance in others:
            menu.add_command(
                label=instance.filename,
                command=lambda instance=instance: self._compare_with_click_window(
                    instance.hwnd, instance.filename
                ),
            )

    def _create_menu_bar(self):
        """Create the application menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load Nicknames from CSV...", command=self.browse_and_load_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Address Editor...", command=self._open_address_editor)
        tools_menu.add_command(label="Dataview Editor...", command=self._open_dataview_editor)
        tools_menu.add_command(label="Check Program", command=self._analyze_program)
        tools_menu.add_command(label="Simulate...", command=self._open_simulator)
        tools_menu.add_separator()
        repairs_menu = tk.Menu(tools_menu, tearoff=0, postcommand=self._refresh_upgrade_entry)
        tools_menu.add_cascade(label="Repairs", menu=repairs_menu)
        repairs_menu.add_command(
            label="System Nicknames",
            command=self._repair_system_nicknames,
            state=tk.DISABLED,
        )
        repairs_menu.add_command(
            label="Upgrade Project",
            command=self._upgrade_project,
            state=tk.DISABLED,
        )
        self.repairs_menu = repairs_menu
        self._repairs_system_nicknames_index = 0
        self._repairs_upgrade_project_index = 1
        repairs_menu.add_separator()
        repairs_menu.add_command(label="Verify MDB & CDV...", command=self._verify_mdb_and_cdv)
        repairs_menu.add_command(label="Clean MDB...", command=self._clean_mdb)

        # Workspace menu. Main-screen placement arrives in the focused UI
        # refresh; these commands own the stable behavior in the meantime.
        workspace_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Workspace", menu=workspace_menu)
        workspace_menu.add_command(label="Review Changes", command=self._workspace_rung_apply)
        workspace_menu.add_command(
            label="Reload from CLICK...", command=self._workspace_reload_from_click
        )
        workspace_menu.add_separator()
        self.workspace_menu = workspace_menu
        self._workspace_menu_open_index = 3
        open_workspace_label, open_workspace_state = self._open_workspace_menu_options()
        workspace_menu.add_command(
            label=open_workspace_label,
            command=self._open_workspace,
            state=open_workspace_state,
        )
        workspace_menu.add_command(label="Export Workspace...", command=self._export_pyrung_project)
        workspace_menu.add_separator()
        workspace_menu.add_command(
            label="View/Setup Workspace...",
            command=self._open_mirror_setup_window,
        )

        # Ladder menu
        ladder_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Ladder", menu=ladder_menu)
        ladder_menu.add_command(
            label="Load Ladder CSV to Clipboard...", command=self._load_ladder_csv
        )
        compare_menu = tk.Menu(ladder_menu, tearoff=0)
        ladder_menu.add_cascade(label="Compare with", menu=compare_menu)
        compare_menu.add_command(label="Folder...", command=self._compare_with_folder)
        other_click_menu = tk.Menu(compare_menu, tearoff=0)
        other_click_menu.configure(
            postcommand=lambda: self._fill_other_click_menu(other_click_menu)
        )
        compare_menu.add_cascade(label="Other CLICK window", menu=other_click_menu)
        ladder_menu.add_separator()
        ladder_menu.add_command(label="Save Clipboard to CSV...", command=self._save_clipboard_csv)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(
            label="About Click Project...",
            command=self._open_project_info_window,
        )
        help_menu.add_command(label="About ClickNick...", command=self._create_about_dialog)
        help_menu.add_separator()
        help_menu.add_command(
            label="GitHub Repository",
            command=lambda: self.open_url("https://github.com/ssweber/clicknick"),
        )
        help_menu.add_command(
            label="Report Issue",
            command=lambda: self.open_url("https://github.com/ssweber/clicknick/issues"),
        )

    def _create_widgets(self):
        """Create all UI widgets."""
        self._create_menu_bar()

        main_frame = ttk.Frame(self.root, padding="15")
        primary = ttk.Frame(main_frame)
        primary.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._create_click_instances_section(primary)
        self._create_options_section(primary)
        self._create_action_section(primary)

        main_frame.pack(fill=tk.BOTH, expand=True)
        self._request_ui_refresh()

    def _live_session_dir(self):
        """Directory the live server advertises its port file in.

        Co-locate with the connected CLICK instance (next to SC_.mdb) when a
        window is connected; otherwise a ClickNick-owned fallback. A connected
        CLICK window always has a temp folder, even without ODBC/CSV access.
        """
        from .live.session import fallback_dir
        from .utils.click_temp import click_temp_dir

        hwnd = self._click.hwnd if self._click else None
        if hwnd:
            click_dir = click_temp_dir(hwnd)
            if click_dir.is_dir():
                return click_dir
        return fallback_dir()

    def _record_staged_rungs(self, count: int) -> None:
        if self._session is not None:
            self._session.record_rung_stage(count)
        self._request_ui_refresh()

    def _reset_workspace_pairing(self) -> None:
        """Forget the durable workspace paired with the connected project."""
        self._workspace_config = None
        self._workspace_mirror_error = None
        self._workspace_matches = []
        self._pending_workspace_config = None

    def __init__(self):
        # Create main window
        self.root = tk.Tk()
        self.root.title("ClickNick App")

        # Define your base font (family, size, weight)
        self._default_font = font.nametofont("TkDefaultFont")
        self._default_family = self._default_font.cget("family")
        self._default_size = self._default_font.cget("size")

        # Create a style object
        style = ttk.Style(self.root)

        # Set the default font for all ttk widgets
        style.configure(".", font=self._default_font)  # Applies to all widgets

        # Hide the window immediately
        self.root.withdraw()
        self._main_window_shown = False

        # Initialize settings first
        self.settings = AppSettings()

        # Autocomplete popups on or off: only the user's Start/Stop, or a window
        # the user picks, changes it. The connection watch (_monitor_task) runs
        # whenever a CLICK window is connected, whatever this says.
        self.monitoring = True
        self.monitor_task_id = None
        self._watch_running = False
        self._status_after_id = None

        # Pending idle refresh of the title and Workspace details (_request_ui_refresh)
        self._ui_refresh_id = None

        # Connected Click.exe instance (one immutable value; replaced, never edited)
        self._connection_probe_token = None
        self._click = None
        self._reset_workspace_pairing()

        self.filter_strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "containsplus": ContainsPlusFilter(),
        }

        # Initialize core components
        self.nickname_manager = NicknameManager(self.settings, self.filter_strategies)
        self.detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, self)

        # Connection session: owns all resources scoped to a Click project
        # (store, analysis, ScrWatcher, simulation, Simulator).
        self._session = None

        # The loaded address data (CSV or database) and the windows bound to it.
        self._data = None

        # Open Review Changes windows by the folder each shows
        self._review_changes_windows = {}

        # Live editing server: lets `clicknick-cli` push edits into this
        # running instance. Holds getters (not snapshots) so it always targets
        # the current store and advertises in the current session directory,
        # both of which change on reconnect/project-switch.
        from .live import LiveServer

        self._live_server = LiveServer(
            self.root,
            self._get_store,
            self._live_session_dir,
            lambda: self._click.project_name if self._click else None,
            lambda: self._session.analysis if self._session else None,
            get_workspace_dir=self._workspace_source_dir,
            show_proposal=self._show_review_changes,
            get_mdb_path=self._live_mdb_path,
            get_synced_pending=lambda: self._session.synced_pending if self._session else 0,
            get_staged_rungs=lambda: self._session.staged_rungs if self._session else 0,
            record_staged_rungs=self._record_staged_rungs,
            get_pyrung_live_available=lambda: bool(
                self._session and self._session.simulation and self._session.simulation.is_ready
            ),
            open_editor=self._live_open_address_editor,
        )
        try:
            self._live_server.start()
        except Exception as exc:  # noqa: BLE001 - never block app startup
            print(f"Live server failed to start: {exc}")

        # Initialize overlay early (before UI creation)
        self.overlay = None

        # Set the icon
        try:
            icon = PhotoImage(data=ICON_PNG_BASE64)
            self.root.iconphoto(True, icon)
            # Keep a reference to prevent garbage collection
            self.root._icon = icon
        except tk.TclError:
            pass  # Continue without icon if it fails

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Setup variables
        self._setup_variables()

        # Setup UI styles
        self._setup_styles()

        # Tk images must be retained for as long as their buttons exist.
        self._action_icons = ActionIconCache(self.root)

        # Create UI components
        self._create_widgets()

    def _remove_stale_compare_copies(self, open_hwnds: set[int]) -> None:
        """Delete the copies (``_compare_with_click_window``) of CLICK windows not in
        *open_hwnds*, except one an open Review Changes window shows."""
        from .services.click_snapshot import remove_stale_snapshots

        shown = [
            folder
            for folder, window in self._review_changes_windows.items()
            if window.winfo_exists()
        ]
        remove_stale_snapshots(open_hwnds, shown)

    def _select_connected_instance(self) -> None:
        """Select the connected CLICK window in the combobox (nothing when none is)."""
        click = self._click
        label = ""
        if click is not None:
            for instance, text in zip(self.click_instances, self._instance_labels(), strict=True):
                if instance.hwnd == click.hwnd:
                    label = text
                    break
        self.selected_instance_var.set(label)

    def _show_instances(self, connected_title: str | None = None) -> None:
        """List the CLICK windows in the combobox and select the connected one.

        The connected window is always listed, under the project it shows: the
        list is read only now and then and leaves out a window whose title shows
        no project. *connected_title* is its title when the caller knows it.
        """
        click = self._click
        if click is not None:
            listed = next((i for i in self.click_instances if i.hwnd == click.hwnd), None)
            if listed is None or listed.filename != click.filename:
                title = connected_title or self.detector.get_window_title(click.hwnd) or ""
                entry = ClickInstance(click.pid, title, click.filename, click.hwnd)
                if listed is None:
                    self.click_instances = [*self.click_instances, entry]
                else:
                    self.click_instances = [
                        entry if instance is listed else instance
                        for instance in self.click_instances
                    ]
        self.instances_combobox["values"] = self._instance_labels()
        self._select_connected_instance()

    @property
    def using_database(self) -> bool:
        """True when the loaded data is CLICK's project database (derived, never stored)."""
        return self._data is not None and self._data.store.is_database

    def _open_data(self, store: AddressStore) -> bool:
        """Make *store* the current data, closing the previous data first.

        The previous data's windows are closed after offering to save unsaved
        edits. Returns False (and leaves the previous data in place) if the
        user cancels.
        """
        from .data_session import DataSession

        if self._data is not None:
            if not self._data.close(self.root, prompt_save=True):
                return False
            self._data = None
        store.start_file_monitoring(self.root)
        self._data = DataSession(store)
        self.nickname_manager.set_store(store)
        return True

    def _close_data(self, *, prompt_save: bool) -> bool:
        """Close the current data and its windows. Returns False if the user cancels."""
        if self._data is not None:
            if prompt_save:
                if not self._data.close(self.root, prompt_save=True):
                    return False
            else:
                self._data.force_close()
            self._data = None
        self.nickname_manager.set_store(None)
        return True

    def _show_main_window(self) -> None:
        """Reveal the fully initialized root at one stable initial size."""
        if self._main_window_shown:
            return
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.deiconify()
        self._main_window_shown = True

    def _load_workspace_pairing(self) -> None:
        """Load the user's preferred workspace for the connected PLC name."""
        from .services.workspace_mirror import (
            find_project_configs,
            preferred_project_config,
        )

        if getattr(self, "_mirror_setup_window", None) is not None:
            self._close_mirror_setup_window()
        self._reset_workspace_pairing()
        plc_name = self._current_plc_name()
        if not plc_name:
            return
        matches = find_project_configs(plc_name)
        self._workspace_matches = matches
        if len(matches) == 1:
            if matches[0].workspace_path.is_dir():
                self._workspace_config = matches[0]
            else:
                self._workspace_mirror_error = (
                    f"Workspace folder not found: {matches[0].workspace_path}"
                )
        elif len(matches) > 1:
            self._workspace_config = preferred_project_config(plc_name, matches)
            if (
                self._workspace_config is not None
                and not self._workspace_config.workspace_path.is_dir()
            ):
                self._workspace_config = None
            if self._workspace_config is None:
                self._workspace_mirror_error = (
                    "Multiple workspaces are known for this PLC. Choose one in Workspace setup."
                )

    def _report_legacy_encodings(self) -> None:
        """Say once which rungs CLICK holds in an old encoding or ClickNick cannot read.

        An old encoding's text matches, so nothing else would show that CLICK
        runs it differently, and Review Changes pastes it again. The workspace
        holds an empty rung for each rung it cannot read, so those must come
        from the user's own copy. So must a program whose CSV laddercodec cannot read.
        """
        from .ladder.program import describe_legacy_encoding

        found = self._session.legacy_encodings_to_report() if self._session else ()
        if not found:
            return

        def _listed(items: list) -> str:
            lines = [f"  {describe_legacy_encoding(item)}" for item in items[:_LEGACY_LISTED]]
            if len(items) > _LEGACY_LISTED:
                lines.append(f"  ...and {len(items) - _LEGACY_LISTED} more")
            return "\n".join(lines)

        legacy = [item for item in found if not item.unreadable]
        unreadable = [item for item in found if item.unreadable and item.rung is not None]
        copies = [item for item in found if item.unreadable and item.rung is None]
        parts: list[str] = []
        if unreadable:
            parts.append(
                "ClickNick cannot read these rungs in CLICK:\n\n"
                + _listed(unreadable)
                + "\n\nThe workspace holds an empty rung in place of each. Paste them again "
                "from your own copy of the program, or fix them in CLICK. Ladder > Compare with > "
                "Folder on that copy lists them in red."
            )
        if copies:
            parts.append(
                "Paste these programs into CLICK again from your own copy, or fix them in "
                "CLICK:\n\n"
                + _listed(copies)
                + "\n\nLadder > Compare with > Folder on that copy lists them in red."
            )
        if legacy:
            parts.append(
                "CLICK holds these rungs in an old encoding, which an older ClickNick pasted. "
                "CLICK runs them differently from how they read:\n\n"
                + _listed(legacy)
                + "\n\nPaste them into CLICK again. Review Changes lists them in red."
            )
        message = "\n\n".join(parts)
        if not legacy:
            messagebox.showwarning("Paste Again", message, parent=self.root)
            return
        message += "\n\nOpen Review Changes now?"
        if messagebox.askyesno("Paste Again", message, icon=messagebox.WARNING, parent=self.root):
            self._workspace_rung_apply()

    def _on_build_finished(self) -> None:
        """Show the build's result. Runs on the build worker's thread."""
        try:
            self.root.after(0, self._request_ui_refresh)
            self.root.after(0, self._report_legacy_encodings)
        except (RuntimeError, tk.TclError):
            pass  # The window closed while the build ran

    def _on_sync_status_changed(self, _pending: int) -> None:
        self._request_ui_refresh()
        if self._data is not None:
            for window in self._data.editors:
                if hasattr(window, "refresh_sync_status"):
                    window.refresh_sync_status()

    def _check_odbc_drivers_and_warn(self):
        """Check database backend candidates and warn if none are available."""
        if not self.nickname_manager.has_database_backend():
            self._show_odbc_warning()
            return False
        return True

    def _clear_connection_state(self) -> None:
        """Clear the currently connected Click window metadata."""
        self._connection_probe_token = None
        self._click = None
        self._reset_workspace_pairing()

    def _cancel_monitoring_status(self) -> None:
        if self._status_after_id is not None:
            self.root.after_cancel(self._status_after_id)
            self._status_after_id = None

    def _hide_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.withdraw()
            self.overlay = None

    def _handle_window_closed(self):
        """Handle when connected window is no longer available."""
        self._update_status("⚠ Connected ClickPLC window closed", "error")
        self._cancel_monitoring_status()
        self._hide_overlay()

        if self._session is not None:
            self._session.close()
            self._session = None
        # Database data belongs to the closed project; CSV data stays usable.
        if self.using_database:
            self._close_data(prompt_save=False)

        self._clear_connection_state()
        self.selected_instance_var.set("")

        self.root.after(2000, self.refresh_click_instances)

    def refresh_click_instances(self):
        """List the running CLICK windows.

        Connects to the first one only when no window is connected and no data
        is loaded: connecting replaces the loaded data, so otherwise the user
        picks. The list leaves out windows whose title shows no project, so a
        connected window missing from it is closed only if its process is gone.
        """
        try:
            click_instances = self.detector.get_click_instances()
        except Exception as e:
            print(f"Error refreshing Click instances: {e}")
            self.click_instances = []
            self._show_instances()
            self._update_status(f"⚠ Error: {e!s}", "error")
            self.start_button.state(["disabled"])
            return

        self.click_instances = click_instances
        click = self._click
        if (
            click is not None
            and all(instance.hwnd != click.hwnd for instance in click_instances)
            and not self.detector.check_window_exists(click.pid)
        ):
            self._handle_window_closed()
        self._show_instances()
        self._remove_stale_compare_copies({instance.hwnd for instance in self.click_instances})

        if not click_instances:
            self._update_status("⚠ No ClickPLC windows", "error")
            self.start_button.state(["disabled"])
            return
        self.start_button.state(["!disabled"])

        if self._click is None and self._data is None:
            first = click_instances[0]
            self.connect_to_instance(first.pid, first.title, first.filename, first.hwnd)

    def _connect_csv_fallback(self, filename, hwnd):
        """Offer CSV loading after a failed connection or an explicit CSV selection."""
        self._show_main_window()
        fallback_csv = find_fallback_csv(hwnd)
        if fallback_csv:
            default_name = f"{filename.replace('.ckp', '')}_Address.csv"
            dialog = CsvFallbackDialog(self.root, fallback_csv, default_name)
            saved_path = dialog.show()
            if saved_path:
                self.load_csv(saved_path)
                return
        self._update_status("No nicknames loaded - use File → Load Nicknames...", "error")
        if not self._odbc_warning_shown:
            self._show_odbc_warning()
            self._odbc_warning_shown = True

    def _open_connection_session(self, click: ClickConnection) -> None:
        """Start the analysis, Scr watcher and simulation for the connected project."""
        from .connection_session import ConnectionSession

        self._session = ConnectionSession(
            click,
            workspace_dir=self._configured_workspace_dir(),
            on_sync_status_changed=self._on_sync_status_changed,
            on_build_finished=self._on_build_finished,
        )

    def _load_instance_database(self, pid, filename, hwnd):
        """Select a backend and load a private store before attaching it to Tk."""
        import queue
        import threading

        from .data.data_source import MdbDataSource

        token = object()
        self._connection_probe_token = token
        results = queue.Queue()
        self._update_status("Loading database...", "status")

        def load():
            try:
                data_source = MdbDataSource(click_pid=pid, click_hwnd=hwnd)
                store = AddressStore(data_source)
                store.load_initial_data()
                results.put((store, None))
            except Exception as exc:
                results.put((None, str(exc)))

        threading.Thread(target=load, daemon=True).start()

        def finish():
            if self._connection_probe_token is not token:
                return
            try:
                store, error = results.get_nowait()
            except queue.Empty:
                self.root.after(100, finish)
                return
            if error is not None:
                self._show_main_window()
                self._update_status("Database connection failed", "error")
                self._odbc_warning_shown = True
                messagebox.showerror("Database Connection", error, parent=self.root)
                if self._connection_probe_token is token:
                    self._connect_csv_fallback(filename, hwnd)
                return

            if not self._open_data(store):
                self._update_status("Database load cancelled", "status")
                return
            self._open_connection_session(ClickConnection(pid, hwnd, filename))
            self.load_from_database()
            self._start_analysis_build()

        self.root.after(100, finish)

    def _handle_popup_window(self, window_id, window_class, edit_control):
        """Handle the detected popup window by showing or updating the nickname popup."""
        try:
            # Create overlay if it doesn't exist
            if not self.overlay:
                self.overlay = Overlay(
                    self.root,
                    self.nickname_manager,
                )
                self.overlay.set_target_window(window_id, window_class, edit_control)
            else:
                # Update target window info
                self.overlay.set_target_window(window_id, window_class, edit_control)

            # Get allowed types for this window/control
            field_info = self.detector.update_window_info(window_class, edit_control)

            # Show the overlay with filtered nicknames
            self.overlay.show_combobox(field_info.allowed_address_types)

        except Exception as e:
            print(f"Error showing overlay: {e}")

    def _parse_filename_from_title(self, title):
        """Extract filename from window title using centralized parser."""
        return ClickWindowDetector.parse_click_filename(title)

    def _show_monitoring_button(self) -> None:
        self.start_button.configure(text="⏹ Stop" if self.monitoring else "▶ Start")

    def _update_status_monitoring(self):
        """Update Status and Button to reflect Monitoring"""
        self._cancel_monitoring_status()
        if not self.monitoring or self._click is None:
            return
        self._update_status(
            f"⚡ Monitoring {self._click.filename if self._click else ''}", "connected"
        )
        self._show_monitoring_button()

    def _keeps_edits_for(self, old_filename: str, new_filename: str) -> bool:
        """Ask whether unsaved edits stay, for the project CLICK shows now.

        CLICK's Save As keeps the window's temp folder, its database and its
        DataView folder, and so does opening another project in the same
        window; ClickNick cannot tell the two apart, so the user says. The
        question covers address edits on database data, text in a cell that will
        not commit, and Dataview edits (on CSV data too: the Dataview Editor
        shows the window's DataView folder). CSV address edits belong to the CSV
        file and are not asked about. Nothing is saved here. False when there is
        nothing unsaved.
        """
        data = self._data
        if data is None:
            return False
        unsaved = []
        if data.store.is_database:
            # A cell that will not commit (CLICK has the focus) still holds an edit
            committed = data.commit_open_cell_editors()
            if not committed or data.store.has_unsaved_changes():
                unsaved.append("address changes")
        dataview = data.dataview_window
        if dataview is not None:
            committed = dataview.commit_open_cell_editor()
            if not committed or dataview.has_unsaved_changes():
                unsaved.append("Dataview changes")
        if not unsaved:
            return False
        saves = "Sync and Save then write them" if data.store.is_database else "Save writes them"
        return messagebox.askyesno(
            "Project Changed",
            f"The CLICK window now shows {new_filename}. You have unsaved "
            f"{' and '.join(unsaved)} made in {old_filename}.\n\n"
            f"Keep them as unsaved changes for {new_filename}? Choose Yes after a Save As in "
            f"CLICK: {saves} to {new_filename}.\n\n"
            "No discards them and saves nothing.",
            icon=messagebox.WARNING,
            parent=self.root,
        )

    def _reopen_dataview_editor(self, *, kept: bool) -> None:
        """After a project change, show the window's DataView folder as it is now.

        The window keeps its ``CLICK (hwnd)`` folder. When the user kept the
        edits (*kept*) the editor stays as it is, with its tabs and its Modbus
        connection, and lists the folder again. Otherwise it shows the files of
        the project CLICK had open: it is closed without saving and opened again
        on the window's DataView folder.
        """
        data = self._data
        dataview = data.dataview_window if data is not None else None
        if dataview is None:
            return
        if kept:
            dataview.refresh_file_list()
            return
        dataview.close_without_prompt()
        self._open_dataview_editor()

    def _handle_project_change(self, current_title: str, new_filename: str) -> None:
        """The connected CLICK window shows another project: follow it.

        Unsaved address edits on database data, and Dataview edits, are kept
        for the new project or discarded, as the user says (``_keeps_edits_for``).
        Kept, the data and its windows stay open, and the store's file monitor
        reads the base from the database the window now holds. Otherwise
        database data closes with nothing saved, and the new project's database
        is loaded. CSV data stays loaded. A Dataview Editor that stays open
        lists its folder again when the edits were kept, and is otherwise opened
        again on the window's DataView folder (``_reopen_dataview_editor``).
        Monitoring stays as it was.
        """
        click = self._click
        if click is None:
            return
        keep = self._keeps_edits_for(click.filename, new_filename)
        closes_data = self.using_database and not keep
        closing = []
        if closes_data and self._data.has_open_windows:
            closing.append("Editor windows")
        if self._session is not None and self._session.simulator is not None:
            closing.append("the Simulator" if closing else "The Simulator")
        if closing:
            messagebox.showinfo(
                "Project Changed",
                f"The Click project was changed. {' and '.join(closing)} will now close.",
            )

        if self._session is not None:
            self._session.close()
            self._session = None
        if closes_data:
            self._close_data(prompt_save=False)

        self._click = click = replace(click, filename=new_filename)
        self._show_instances(current_title)
        self._load_workspace_pairing()
        self._reopen_dataview_editor(kept=keep)

        if keep and self.using_database:
            self._open_connection_session(click)
            self._update_status(f"Kept unsaved changes for {new_filename}", "connected")
            self._on_data_ready()
            self._start_analysis_build()
        elif self._data is None and self.nickname_manager.has_database_backend():
            # Same off-thread load as connecting, with a token so a result for
            # a project that changed again is dropped.
            self._load_instance_database(click.pid, click.filename, click.hwnd)
        elif self.monitoring:
            self._update_status_monitoring()

    def _handle_popup_detection(self) -> None:
        """Check for Click.exe child popups and show/hide overlay accordingly."""
        child_info = self.detector.detect_child_window(self._click.pid)
        if child_info:
            if not self.detector.field_has_text(child_info.edit_control, child_info.window_id):
                self._handle_popup_window(
                    child_info.window_id, child_info.window_class, child_info.edit_control
                )
        elif self.overlay:
            self.overlay.withdraw()

    def _monitor_task(self):
        """Every 100 ms while a CLICK window is connected: notice it closing or
        changing project and, while monitoring is on, its instruction popups.

        Stop turns off only the popups; the watch ends when the connection does.
        Popups need loaded data.
        """
        self.monitor_task_id = None
        try:
            click = self._click
            if click is None:
                return
            if not self.detector.check_window_exists(click.pid):
                self._handle_window_closed()
                return

            current_title = self.detector.get_window_title(click.hwnd)
            new_filename = self._parse_filename_from_title(current_title)
            if new_filename and new_filename != click.filename:
                self._handle_project_change(current_title, new_filename)

            if self.monitoring and self._data is not None:
                if not (self.overlay and self.overlay.is_active()):
                    self._handle_popup_detection()
            else:
                self._hide_overlay()
        finally:
            if self._click is None:
                self._watch_running = False
            else:
                self.monitor_task_id = self.root.after(100, self._monitor_task)

    def _watch_connection(self) -> None:
        """Start the connection watch (_monitor_task) unless it is running already."""
        if self._watch_running or self._click is None:
            return
        self._watch_running = True
        self._monitor_task()

    def _on_data_ready(self) -> None:
        """Data for the connected window is loaded: watch the window, and while
        monitoring is on say so a second later (after the load's own status)."""
        self._watch_connection()
        if self.monitoring:
            self._cancel_monitoring_status()
            self._status_after_id = self.root.after(1000, self._update_status_monitoring)

    def load_csv(self, csv_path: str) -> bool:
        """Load nicknames from the CSV file at *csv_path*."""
        self._connection_probe_token = None
        try:
            from .data.data_source import CsvDataSource

            data_source = CsvDataSource(csv_path)
            store = AddressStore(data_source)
            store.load_initial_data()
            if not self._open_data(store):
                self._update_status("CSV load cancelled", "status")
                return False

            self._update_status("✓ CSV loaded", "connected")
            has_live_connection = self._click is not None and self.detector.check_window_exists(
                self._click.pid
            )
            if has_live_connection:
                self._on_data_ready()
            else:
                self._hide_overlay()
                if self._click is not None:
                    self._clear_connection_state()
                    self.selected_instance_var.set("")
            return True
        except Exception as e:
            print(f"Error loading CSV: {e}")
            self._update_status("⚠ CSV load failed", "error")
            messagebox.showerror("CSV Load Failed", str(e), parent=self.root)
            return False

    def browse_and_load_csv(self):
        """Browse for and load CSV file from menu."""
        filepath = filedialog.askopenfilename(
            title="Select Nickname CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filepath:
            self.load_csv(filepath)

    def load_from_database(self):
        """Report the loaded database and watch its window."""
        if self._click is None:
            self._update_status("⚠ Not connected", "error")
            return False

        # Check whether a database backend can be attempted
        if not self.nickname_manager.has_database_backend():
            self._update_status("No nicknames loaded - use File → Load Nicknames...", "status")
            if not self._odbc_warning_shown:
                self._show_odbc_warning()
                self._odbc_warning_shown = True
            return False

        if self._get_store() is None:
            self._update_status("⚠ DB load failed", "error")
            return False

        self._update_status("✓ DB loaded", "connected")

        self._on_data_ready()
        return True

    def connect_to_instance(self, pid, title, filename, hwnd, *, user_picked: bool = False):
        """Connect to a specific Click.exe instance.

        A window the user picked turns monitoring on; an automatic connect
        leaves it as it is.
        """
        from .utils.mdb_shared import get_database_backend

        self._connection_probe_token = None

        # Close the current data first: its save prompts are the only step the
        # user can cancel, so nothing irreversible happens before them.
        if not self._close_data(prompt_save=True):
            self._select_connected_instance()
            return
        if self._session is not None:
            self._session.close()
            self._session = None

        self._hide_overlay()
        if user_picked:
            self.monitoring = True
            self._show_monitoring_button()

        # Reset connection state
        self._clear_connection_state()

        # Store the new connection FIRST (including hwnd to avoid lookup issues)
        self._click = ClickConnection(pid, hwnd, filename)
        self._show_instances(title)
        self._load_workspace_pairing()

        if get_database_backend() == "none":
            self._connect_csv_fallback(filename, hwnd)
        else:
            self._load_instance_database(pid, filename, hwnd)
        self._watch_connection()

    def _start_monitoring_internal(self) -> bool:
        """Internal method to start monitoring without status updates.
        Returns True if successful, False otherwise."""
        # Validate connection to Click instance
        if self._click is None:
            self._update_status("⚠ Not connected to ClickPLC window", "error")
            return False

        try:
            self.monitoring = True
            self._watch_connection()
            return True
        except Exception as e:
            self._update_status(f"⚠ Monitoring failed: {str(e)}", "error")
            return False

    def button_start_monitoring(self):
        """Start monitoring with immediate status update."""
        if self._start_monitoring_internal():
            self._update_status_monitoring()

    def stop_monitoring(self):
        """Turn off popup detection; the connection watch keeps running."""
        self.monitoring = False
        self._cancel_monitoring_status()
        self._hide_overlay()
        self._update_status("⏹ Stopped", "status")
        self._show_monitoring_button()

    def toggle_monitoring(self):
        """Start or stop monitoring."""
        if self.monitoring:
            self.stop_monitoring()
        else:
            self.button_start_monitoring()

    def open_url(self, url):
        """Open URL in default browser."""
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception as e:
            self._update_status(f"⚠ Could not open browser: {e}", "error")

    def on_closing(self):
        """Close ClickNick (window X, File > Exit), after offering to save unsaved
        Address Editor and Dataview edits. Cancel, or a failed save, keeps it open."""
        if not self._close_data(prompt_save=True):
            return
        self._connection_probe_token = None
        self._cancel_monitoring_status()
        if self.monitor_task_id is not None:
            self.root.after_cancel(self.monitor_task_id)
            self.monitor_task_id = None
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
        if self._session is not None:
            self._session.close()
            self._session = None
        live_server = getattr(self, "_live_server", None)
        if live_server is not None:
            live_server.stop()
        if self._ui_refresh_id is not None:
            self.root.after_cancel(self._ui_refresh_id)
            self._ui_refresh_id = None
        self.root.destroy()

    def run(self):
        """Run the ClickNick Application"""
        self.refresh_click_instances()
        self._show_main_window()
        self.root.mainloop()


def main(argv: list[str] | None = None) -> None:
    """Entry point for the application."""
    import argparse
    import os

    from .utils.mdb_shared import get_database_backend

    parser = argparse.ArgumentParser(description="CLICK nickname and project tools")
    parser.add_argument(
        "--db-backend",
        choices=("auto", "odbc", "jet", "none"),
        help="Database backend: auto prefers ODBC; odbc or jet forces that backend. "
        "none forces CSV mode. Defaults to CLICKNICK_DB_BACKEND or auto.",
    )
    args = parser.parse_args(argv)
    if args.db_backend is not None:
        os.environ["CLICKNICK_DB_BACKEND"] = args.db_backend
    try:
        get_database_backend()
    except ValueError as exc:
        parser.error(str(exc))
    app = ClickNickApp()
    app.run()


if __name__ == "__main__":
    main()  # Call the main function when run directly
