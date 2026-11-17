from __future__ import annotations

import tkinter as tk
from ctypes import windll
from pathlib import Path
from tkinter import PhotoImage, filedialog, font, messagebox, ttk
from typing import TYPE_CHECKING, Any, overload

from .config import AppSettings
from .connection_controller import (
    NOT_CONNECTED,
    REDRAW_COMMAND,
    REDRAW_ON_SYNC,
    ConnectionController,
)
from .connection_session import ClickConnection, SavedProgram
from .data.address_store import AddressStore
from .data.nickname_manager import NicknameManager
from .detection.window_detector import ClickWindowDetector
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
from .views.dialogs import AboutDialog, OdbcWarningDialog
from .widgets.tooltip import bind_tooltip
from .workspace_controller import WorkspaceController

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Self

    from .connection_session import ConnectionSession
    from .data_session import DataSession
    from .views.review_changes_window import ProposalSource

# Set DPI awareness for better UI rendering
windll.shcore.SetProcessDpiAwareness(1)

_MATCH_MODES = ("none", "prefix", "contains", "containsplus")
_MATCH_LABELS = ("None", "Prefix", "Contains", "Fuzzy")
# The status line when a command needs nicknames and none are loaded
_NO_NICKNAMES = (
    "No nicknames loaded. Connect to a CLICK window, or use File > Load Nicknames from CSV"
)
# The popup names this many legacy-encoded rungs and only counts the rest
_LEGACY_LISTED = 10


class _ShownState[T]:
    """An App attribute that the main window displays. Assigning it schedules one UI refresh.

    The value lives in the instance ``__dict__`` under the same name. This class is a data
    descriptor, so it still takes precedence when Python looks the attribute up.
    """

    @overload
    def __get__(self, app: None, owner: Any = None) -> Self: ...
    @overload
    def __get__(self, app: object, owner: Any = None) -> T: ...
    def __get__(self, app, owner=None):
        if app is None:
            return self
        try:
            return app.__dict__[self._name]
        except KeyError:
            raise AttributeError(self._name) from None

    def __set__(self, app, value: T) -> None:
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

    # The window title and the Workspace details are computed from these attributes.
    # Changing any of them refreshes both (see _refresh_ui).
    _data: _ShownState[DataSession | None] = _ShownState()
    _session: _ShownState[ConnectionSession | None] = _ShownState()

    @property
    def _click(self) -> ClickConnection | None:
        """Return the connected CLICK window from its session, or None when none is connected."""
        session = self._session
        return session.click if session is not None else None

    def _project_session(self) -> ConnectionSession | None:
        """Return the session once ClickNick has read CLICK's database for it, else None.

        Building the workspace, simulating, Review Changes and Workspace setup all need that
        session. When this returns None, they call ``_report_no_project_session``.
        """
        session = self._session
        return session if session is not None and session.has_database else None

    def _report_no_project_session(self) -> None:
        """Show in the status line why ``_project_session`` returned None, and what to do."""
        session = self._session
        if session is None:
            message = NOT_CONNECTED
        elif session.reading_database:
            message = (
                "⚠ ClickNick is still reading CLICK's database. Try again when it has finished"
            )
        else:
            # The load failed or was cancelled, or the user loaded a CSV file instead.
            # Picking the window again connects to it and loads its database.
            message = (
                "⚠ ClickNick has not loaded CLICK's database for this project. Select the "
                "window in the CLICK Windows list to load it"
            )
        self._update_status(message, "error")

    @staticmethod
    def _format_workspace_time(value) -> str:
        return value.astimezone().strftime("%x %X") if value is not None else "Not available"

    def _poll_workspace_ui(self) -> None:
        self._workspace_refresh_after_id = None
        self._refresh_ui()

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
        """Return the Test group's legend and its simulation button's label."""
        session = self._session
        simulation = session.simulation if session is not None else None
        if simulation is None or not simulation.enabled:
            return "Test - Sim off", "Start"
        return f"Test - Sim {simulation.summary_text}", "Stop"

    def _click_filename(self) -> str:
        """Return the connected CLICK window's project filename ("" when none is connected)."""
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
        tools_menu = getattr(self, "tools_menu", None)
        if tools_menu is not None:
            tools_menu.entryconfigure(
                self._tools_redraw_index,
                state=tk.NORMAL if self._click is not None else tk.DISABLED,
            )
        if not hasattr(self, "workspace_status_var"):
            return

        from .services.workspace_service import WorkspaceState

        workspace = self._workspace.status()
        self.workspace_status_var.set(workspace.label)
        self.workspace_detail_var.set(workspace.detail or "")
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

        active_dir = self._workspace.display_dir()
        pairing = self._workspace.pairing
        self.mirror_status_var.set("Durable" if pairing.config else "Temporary")
        self.mirror_detail_var.set(pairing.error or "")
        self.mirror_path_var.set(str(active_dir) if active_dir else "Not available")
        if pairing.config:
            setup_status = "✓ Configured"
        elif len(pairing.matches) > 1:
            setup_status = "Choose workspace"
        else:
            setup_status = "Not configured"
        self.mirror_setup_status_var.set(setup_status)

        info = self._workspace.directory_info()
        self.plc_name_var.set(self._workspace.plc_name() or "Not available")
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
        self._workspace.refresh_menu_states()

    def _run_requested_ui_refresh(self) -> None:
        self._ui_refresh_id = None
        self._refresh_ui()

    def _request_ui_refresh(self) -> None:
        """Schedule one _refresh_ui for when Tk is idle. Repeated requests merge into one.

        Assigning any _ShownState attribute makes this request, so code that changes what the
        window shows needs no refresh call. The other inputs (sync count, analysis progress,
        staged rungs) are ConnectionSession events, and their handlers make the request.
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
        # Why the workspace status is what it is, such as the reason a build failed
        self.workspace_detail_var = tk.StringVar(value="")
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
        self._workspace_refresh_after_id = None
        self._project_info_window = None

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

    def _create_click_instances_section(self, parent):
        """Create the Click.exe instances section."""
        instances_frame = ttk.LabelFrame(
            parent, text="CLICK Windows", padding="10"
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
            selection_frame, text="⟳", width=3, command=self._connection.refresh_click_instances
        )
        self.start_button = ttk.Button(
            selection_frame,
            text="⏹ Stop" if self._connection.monitoring else "▶ Start",
            command=self._connection.toggle_monitoring,
        )

        # Bind combobox selection to auto-connect
        self.instances_combobox.bind("<<ComboboxSelected>>", self._connection.on_instance_selected)

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

        The Simulator and the Test group's Start button call this. The project must be saved.
        A conversion that already failed will not fix itself when a window opens, so this
        says so up front instead of showing a window that does nothing.
        """
        session = self._project_session()
        if session is None:
            self._report_no_project_session()
            return None

        mdb_path = self._live_mdb_path()
        if mdb_path is None or not scr_files(mdb_path.parent):
            self._update_status(
                "The project has no saved program. Save it in CLICK first.",
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
                    f"Could not build the workspace: {analysis.error}\n\n"
                    f"{purpose} needs the workspace.",
                    parent=self.root,
                )
                return None

        simulation = session.ensure_simulation(
            self.root, on_retry_analysis=self._start_analysis_build
        )
        simulation.add_listener(self._on_simulation_event)
        return simulation

    def _toggle_simulation(self) -> None:
        """Start or stop the simulation when the user clicks Start/Stop in the Test group.

        Only this button and closing the connection (``ConnectionController.close_session``)
        stop the simulation. Closing a window does not.
        """
        session = self._session
        simulation = session.simulation if session is not None else None
        if simulation is not None and simulation.enabled:
            simulation.turn_off()
            return
        simulation = self._simulation_for_window("Cannot Simulate", "The simulation")
        if simulation is not None:
            simulation.turn_on()

    @property
    def _csv_path(self) -> str | None:
        """Return the file the loaded CSV data comes from (None for database data or no data)."""
        data = self._data
        if data is None or data.store.is_database:
            return None
        return data.store._data_source.file_path

    def _dataview_folder(self) -> Path | None:
        """Return the DataView folder that the Data View Editor shows.

        That is the connected CLICK window's folder. With no window connected, it is the
        loaded CSV's folder, unless that folder is a CLICK temp folder or is gone. In that
        case it returns None. It never returns another ``CLICK (hwnd)`` folder, because that
        one holds another project's .cdv files.
        """
        from .data.cdv_file import click_dataview_folder, csv_dataview_folder

        if self._click is not None:
            return click_dataview_folder(self._click.hwnd)
        csv_path = self._csv_path
        return csv_dataview_folder(csv_path) if csv_path else None

    def _open_dataview_editor(self):
        """Open the Data View Editor window, or focus it if it is already open.

        The Data View Editor creates and edits CLICK DataView files (.cdv). Only one
        DataviewEditorWindow can be open at a time.
        """
        data = self._data
        if data is None:
            self._update_status(_NO_NICKNAMES, "error")
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
            self._update_status(f"Could not open the Data View Editor: {e}", "error")

    def _open_simulator(self):
        """Open the Simulator window, or focus if already open."""
        session = self._session
        if session is not None and self._focus_simulator(session):
            return
        simulation = self._simulation_for_window("Cannot Simulate", "The simulation")
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

    def _on_database_synced(self, _addr_keys: set[int]) -> None:
        """Tell CLICK to redraw the nicknames that a Sync wrote into its database (issue #36).

        Every Sync goes through ``AddressStore.save_all_changes``, which calls this. That
        covers the Address Editor's Sync and Sync and Close, and Yes to a save prompt.
        If the user turned Tools > Redraw Ladder on Sync off, ``ConnectionController.after_sync``
        redraws nothing.
        """
        if self._click is not None:
            self._connection.after_sync()

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
            self._update_status(_NO_NICKNAMES, "error")
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
            self._update_status(f"Could not open the Address Editor: {e}", "error")

    def _repair_system_nicknames(self) -> None:
        """Stage documented system nickname fixes for review and Sync."""

        store = self._get_store()
        if store is None:
            self._update_status(_NO_NICKNAMES, "error")
            return

        from .services.system_nickname_service import stage_system_nickname_repairs

        repairs = stage_system_nickname_repairs(store)
        if not repairs:
            self._update_status("No system nickname needs a known repair", "connected")
            return

        self._open_address_editor("changed")
        staged = (
            "1 system nickname repair. Review it"
            if len(repairs) == 1
            else f"{len(repairs)} system nickname repairs. Review them"
        )
        self._update_status(
            f"Staged {staged} in the Address Editor, then Sync.",
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
            self._update_status(_NO_NICKNAMES, "error")
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
                "Upgrade Project left these comments unchanged, because pyrung would still "
                "refuse them. Edit them in the Address Editor.\n\n" + "\n".join(problems),
                parent=self.root,
            )
        if not staged:
            if problems:
                self._update_status("No comment upgrade staged", "error")
            else:
                self._update_status("Every annotation is already in the current form", "connected")
            return
        what = (
            "1 comment upgrade. Review it"
            if staged == 1
            else f"{staged} comment upgrades. Review them"
        )
        self._update_status(
            f"Staged {what} in the Address Editor, then Sync.",
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
                    "Check Program",
                    f"Could not build the workspace: {analysis.error}\n\n"
                    "Check Program needs the workspace.",
                    parent=self.root,
                )
            elif status is AnalysisStatus.BUILDING:
                messagebox.showinfo(
                    "Check Program",
                    "ClickNick is still building the workspace. Try again when it finishes.",
                    parent=self.root,
                )
            else:
                messagebox.showinfo(
                    "Check Program",
                    "Check Program needs the workspace, and ClickNick has not built it.\n\n"
                    "Connect to a CLICK window whose project has a saved program. ClickNick "
                    "builds the workspace once it has read CLICK's database.",
                    parent=self.root,
                )
            return

        try:
            report = analysis.run_validation()
        except Exception as exc:
            messagebox.showerror(
                "Check Program",
                f"Could not run the checks: {exc}",
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
            messagebox.showinfo("Check Settings", "Connect to a CLICK window first.", parent=parent)
            return
        try:
            CheckSelectionWindow(parent, selection, on_saved)
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Check Settings", f"Could not open the check settings: {exc}", parent=parent
            )

    def _analyze_program(self) -> None:
        """Run program validation and show a report that you can refresh in place."""
        from .views.analysis_report_window import AnalysisReportWindow

        data = self._run_program_checks()
        if data is not None:
            AnalysisReportWindow(
                self.root,
                data,
                rerun=self._run_program_checks,
                choose_checks=self._choose_program_checks,
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
            text="Data View Editor",
            image=self._action_icons.get("data_view"),
            compound=tk.LEFT,
            command=self._open_dataview_editor,
        ).pack(fill=tk.X)

        test = ttk.LabelFrame(actions, padding=10)
        # Like Workspace: the legend carries the state, with its control beside it.
        # The simulation runs headless until you stop it here or the project closes.
        # Closing the Simulator leaves it running.
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
            "Simulator closes, so the Data View Editor or an HMI can stay connected.",
        )
        test.configure(labelwidget=test_header)
        ttk.Button(
            test,
            text="Check Program",
            image=self._action_icons.get("check_program"),
            compound=tk.LEFT,
            command=self._analyze_program,
        ).pack(fill=tk.X, pady=(0, 8))
        # Simulate opens the Simulator window and starts the simulation, as Tools > Simulate...
        # does. The Start/Stop button in this group's header starts the simulation without the
        # window. The Console is a pane inside the Simulator window.
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
        self._workspace.populate_options_menu(workspace_options_menu)
        workspace_options_button.configure(menu=workspace_options_menu)
        workspace_options_button.pack(side=tk.LEFT, padx=(8, 0))
        workspace.configure(labelwidget=workspace_header)

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
            command=self._workspace.review_changes,
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            workspace,
            text="Reload from CLICK",
            image=self._action_icons.get("reload_from_click"),
            compound=tk.LEFT,
            command=self._workspace.reload_from_click,
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
        ttk.Label(
            mirror,
            textvariable=self.workspace_detail_var,
            style="Error.TLabel",
            wraplength=440,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X)
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
        window.title("About CLICK Project")
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

    def _database_store(self, command: str) -> AddressStore | None:
        """Return the store of the connected CLICK window's database, for *command*.

        If no database is loaded, show why in the status line and return None. *command* is
        the menu entry's name.
        """
        data = self._data
        if data is not None and data.store.is_database:
            return data.store
        if data is not None and self._session is not None:
            self._update_status(
                f"⚠ {command} needs CLICK's database, and the nicknames loaded come from a "
                "CSV file. Select the window in the CLICK Windows list to load the database",
                "error",
            )
        else:
            self._report_no_project_session()
        return None

    def _verify_mdb_and_cdv(self):
        """Check the addresses in CLICK's database and the entries in its .cdv files."""
        store = self._database_store("Verify MDB & CDV")
        if store is None or self._click is None:
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
        store = self._database_store("Clean MDB")
        if store is None:
            return

        from tkinter import messagebox

        from .data.data_source import MdbDataSource

        mdb_path = store._data_source.file_path

        # Create a fresh MdbDataSource to load directly from MDB
        try:
            fresh_source = MdbDataSource(db_path=mdb_path)
            all_rows = fresh_source.load_all_addresses()
        except Exception as e:
            self._update_status(f"⚠ Could not read CLICK's database: {e}", "error")
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
            noun = "row" if deleted_count == 1 else "rows"
            messagebox.showinfo(
                "Clean MDB",
                f"Deleted {deleted_count} {noun} from CLICK's database.",
                parent=self.root,
            )
        except Exception as e:
            self._update_status(f"⚠ Could not delete the rows from CLICK's database: {e}", "error")

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
        build_error = self._workspace.earlier_save_build_error()
        if build_error is not None:
            messagebox.showerror(
                "Export Workspace",
                "Could not build the workspace from CLICK's last save. There is no current "
                "workspace to export.\n\n" + build_error,
                parent=self.root,
            )
            return
        if analysis.project_dir is None:
            messagebox.showinfo(
                "Export Workspace",
                "Save the project in CLICK, then try again.",
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
            messagebox.showerror(
                "Export Workspace",
                f"Could not export the workspace to {destination}: {exc}",
                parent=self.root,
            )
            return

        self._update_status(
            f"Exported workspace ({file_count} files) to {destination}",
            "connected",
        )

    def _load_ladder_csv(self):
        """Load a single ladder CSV file onto the clipboard, for the connected CLICK window."""
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
                str(exc),
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

    def _close_workspace_reviews(self) -> None:
        """Close the Review Changes windows offering the workspace's edits."""
        for window in self._review_changes_windows.values():
            if window.winfo_exists() and window.shows_workspace_proposal:
                window.destroy()

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
        """Show *folder* in Review Changes. There is one window per folder.

        Showing a folder again reloads its window. Review Changes (``rung apply``) passes the
        workspace source that the folder was exported from. It may also name a program to
        start on and the rungs of that program to paste. With *create* off, this only brings
        up to date a window that already shows the folder. *source* says where the folder
        comes from. If you do not give it, the source is the workspace or the folder itself.
        *refresh_source* copies the folder again from that source.
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

        ClickNick copies that window's save and nicknames to a ClickNick folder. Review
        Changes shows the folder as a copy of another PLC. Refresh copies them again, as
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
        """List the CLICK windows other than the connected one, so you can compare with them."""
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
        tools_menu.add_command(label="Data View Editor...", command=self._open_dataview_editor)
        tools_menu.add_command(label="Check Program", command=self._analyze_program)
        tools_menu.add_command(label="Simulate...", command=self._open_simulator)
        tools_menu.add_separator()
        tools_menu.add_command(
            label=REDRAW_COMMAND,
            command=lambda: self._connection.redraw_nicknames(after_sync=False),
            state=tk.DISABLED,  # _refresh_ui enables it while a CLICK window is connected
        )
        self.tools_menu = tools_menu
        self._tools_redraw_index = tools_menu.index(tk.END)
        tools_menu.add_checkbutton(label=REDRAW_ON_SYNC, variable=self.settings.redraw_on_sync_var)
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
        workspace_menu.add_command(label="Review Changes", command=self._workspace.review_changes)
        workspace_menu.add_command(
            label="Reload from CLICK...", command=self._workspace.reload_from_click
        )
        workspace_menu.add_separator()
        self._workspace.add_open_entry(workspace_menu)
        workspace_menu.add_command(label="Export Workspace...", command=self._export_pyrung_project)
        workspace_menu.add_separator()
        workspace_menu.add_command(
            label="View/Setup Workspace...",
            command=self._workspace.open_setup_window,
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
            label="About CLICK Project...",
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

        # Pending idle refresh of the title and Workspace details (_request_ui_refresh)
        self._ui_refresh_id = None

        self.filter_strategies = {
            "none": NoneFilter(),
            "prefix": PrefixFilter(),
            "contains": ContainsFilter(),
            "containsplus": ContainsPlusFilter(),
        }

        # Initialize core components
        self.nickname_manager = NicknameManager(self.settings, self.filter_strategies)
        self.detector = ClickWindowDetector(CLICK_PLC_WINDOW_MAPPING, self)

        # Connection session: the connected CLICK window and everything scoped to
        # its project (analysis, ScrWatcher, simulation, Simulator). Made on
        # connect, replaced on a project change, closed when the window goes.
        self._session = None

        # The loaded address data (CSV or database) and the windows bound to it.
        self._data = None

        # Open Review Changes windows by the folder each shows
        self._review_changes_windows = {}

        # The Workspace group, its menu entries and Workspace setup
        self._workspace = WorkspaceController(self)

        # The CLICK window list, connecting, the connection watch and monitoring
        self._connection = ConnectionController(self)

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
            get_workspace_dir=self._workspace.source_dir,
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
            print(f"The server for clicknick-cli did not start: {exc}")

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
        *open_hwnds*. Keep a copy that an open Review Changes window shows."""
        from .services.click_snapshot import remove_stale_snapshots

        shown = [
            folder
            for folder, window in self._review_changes_windows.items()
            if window.winfo_exists()
        ]
        remove_stale_snapshots(open_hwnds, shown)

    @property
    def using_database(self) -> bool:
        """Return True when the loaded data is CLICK's project database (derived, never stored)."""
        return self._data is not None and self._data.store.is_database

    def _open_data(
        self, store: AddressStore, *, still_wanted: Callable[[], bool] | None = None
    ) -> bool:
        """Make *store* the current data, closing the previous data first.

        This offers to save unsaved edits, then closes the previous data's windows. If the
        user cancels, it returns False and leaves the previous data in place. It also
        returns False, without opening *store*, when *still_wanted* says after that prompt
        that the store is no longer wanted.
        """
        from .data_session import DataSession

        if self._data is not None:
            if not self._data.close(self.root, prompt_save=True):
                return False
            self._data = None
        if still_wanted is not None and not still_wanted():
            # The previous data closed: autocomplete must not keep offering it
            self.nickname_manager.set_store(None)
            return False
        store.start_file_monitoring(self.root)
        store.add_sync_listener(self._on_database_synced)
        self._data = DataSession(store)
        self.nickname_manager.set_store(store)
        return True

    def _close_data(self, *, prompt_save: bool) -> bool:
        """Close the current data and its windows. Return False if the user cancels."""
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
        """Show the main window at the size that its widgets ask for. Later calls do nothing."""
        if self._main_window_shown:
            return
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.deiconify()
        self._main_window_shown = True

    def _report_legacy_encodings(self) -> None:
        """Tell the user which rungs and programs in CLICK's last save to paste again or fix.

        The message lists three kinds of finding:

        - A rung that ClickNick cannot read. The workspace holds an empty rung in its place.
          The user must paste the rung from their own copy of the program.
        - A program whose CSV laddercodec cannot read. The user must paste it from their own
          copy.
        - A rung that an older ClickNick pasted in an old encoding. It reads the same as the
          workspace rung, so no other check shows that CLICK runs it differently. The
          message offers Review Changes, which pastes the rung again.

        ``ConnectionSession.legacy_encodings_to_report`` returns nothing unless a finding is
        new. So the message shows once for each set of findings.
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
                "ClickNick cannot read these programs in CLICK:\n\n"
                + _listed(copies)
                + "\n\nPaste them into CLICK again from your own copy, or fix them in CLICK. "
                "Ladder > Compare with > Folder on that copy lists them in red."
            )
        if legacy:
            parts.append(
                "An older ClickNick pasted these rungs into CLICK in an old encoding. "
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
            self._workspace.review_changes()

    def _on_build_finished(self) -> None:
        """Show the build's result. This runs on the build worker's thread."""
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

    def browse_and_load_csv(self):
        """Browse for and load CSV file from menu."""
        filepath = filedialog.askopenfilename(
            title="Select Nickname CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filepath:
            self._connection.load_csv(filepath)

    def open_url(self, url):
        """Open URL in default browser."""
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception as e:
            self._update_status(f"⚠ Could not open browser: {e}", "error")

    def on_closing(self):
        """Close ClickNick (window X, File > Exit), after offering to save unsaved
        Address Editor and Data View edits. Cancel, or a failed save, keeps it open."""
        if not self._close_data(prompt_save=True):
            return
        self._connection.cancel_monitoring_status()
        # Ends the connection watch and hides the popup; root.destroy() destroys it
        self._connection.close_session()
        live_server = getattr(self, "_live_server", None)
        if live_server is not None:
            live_server.stop()
        if self._ui_refresh_id is not None:
            self.root.after_cancel(self._ui_refresh_id)
            self._ui_refresh_id = None
        self.root.destroy()

    def run(self):
        """Run the ClickNick Application"""
        self._connection.refresh_click_instances()
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
        help="Database backend. auto prefers ODBC. odbc or jet forces that backend. "
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
