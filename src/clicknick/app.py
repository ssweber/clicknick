import tkinter as tk
from ctypes import windll
from pathlib import Path
from tkinter import PhotoImage, filedialog, font, messagebox, simpledialog, ttk

from .config import AppSettings
from .data.address_store import AddressStore
from .data.nickname_manager import NicknameManager
from .detection.window_detector import ClickWindowDetector
from .detection.window_mapping import CLICK_PLC_WINDOW_MAPPING
from .resources.action_icons import ActionIconCache
from .resources.icon_data import ICON_PNG_BASE64
from .utils.filters import (  # preserve lru_cache
    ContainsFilter,
    ContainsPlusFilter,
    NoneFilter,
    PrefixFilter,
)
from .utils.mdb_shared import find_fallback_csv, set_csv_only_mode
from .views.dialogs import AboutDialog, CsvFallbackDialog, OdbcWarningDialog
from .views.overlay import Overlay

# Set DPI awareness for better UI rendering
windll.shcore.SetProcessDpiAwareness(1)

# Dev mode flag - enables in-progress features
_DEV_MODE = False

_MATCH_MODES = ("none", "prefix", "contains", "containsplus")
_MATCH_LABELS = ("None", "Prefix", "Contains", "Fuzzy")


def get_version():
    """Get version from package metadata."""
    try:
        from importlib.metadata import version

        return version("clicknick")  # Replace with your actual package name
    except Exception:
        return "Development"


class ClickNickApp:
    """Main application for the ClickNick App."""

    def _setup_variables(self):
        """Initialize Tkinter variables."""
        self.csv_path_var = tk.StringVar()
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
        self.last_regenerated_var = tk.StringVar(value="Not available")
        self.last_backup_var = tk.StringVar(value="Not available")
        self.click_instances = []  # Will store ClickInstance objects
        self.using_database = False  # Flag to track if database is being used
        self._odbc_warning_shown = False
        self._workspace_refresh_after_id = None
        self._project_info_window = None
        self._mirror_setup_window = None
        self._workspace_matches = []
        self._pending_workspace_config = None

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

    def _on_instance_selected(self, event=None):
        """Handle instance selection from combobox."""
        selected_text = self.selected_instance_var.get()
        if not selected_text:
            return

        # Find the matching instance
        for instance in self.click_instances:
            if instance.filename == selected_text:
                self.connect_to_instance(
                    instance.pid, instance.title, instance.filename, instance.hwnd
                )
                break

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
            selection_frame, text="▶ Start", command=self.toggle_monitoring
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
        if self.nickname_manager.is_loaded:
            # Apply the new sorting preference
            self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

            # Regenerate abbreviation tags after sorting
            self.nickname_manager._generate_abbreviation_tags()

    def _on_match_mode_changed(self, value) -> None:
        """Map the four-stop slider onto the existing filter strategies."""
        index = max(0, min(len(_MATCH_MODES) - 1, round(float(value))))
        self.match_mode_index_var.set(float(index))
        self.settings.search_var.set(_MATCH_MODES[index])

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
        return analysis.project_dir if analysis and analysis.is_available else None

    def _configured_workspace_dir(self) -> Path | None:
        config = self._workspace_config
        return config.workspace_path if config is not None else None

    def _workspace_display_dir(self) -> Path | None:
        """Return the active path, or its configured target while rebuilding."""
        return self._workspace_source_dir() or self._configured_workspace_dir()

    def _current_plc_name(self) -> str | None:
        """Return CLICK's configured PLC name from its active temp workspace."""
        if not getattr(self, "connected_click_hwnd", None):
            return None
        from .live.session import click_temp_dir
        from .services.workspace_mirror import read_plc_name

        return read_plc_name(click_temp_dir(self.connected_click_hwnd) / "Project.ini")

    @staticmethod
    def _format_workspace_time(value) -> str:
        return value.astimezone().strftime("%x %X") if value is not None else "Not available"

    def _poll_workspace_ui(self) -> None:
        self._workspace_refresh_after_id = None
        self._refresh_workspace_ui()

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

    def _refresh_workspace_ui(self) -> None:
        """Refresh status/details variables without rebuilding any widgets."""
        if not hasattr(self, "workspace_status_var"):
            return

        from .services.workspace_service import WorkspaceState

        workspace = self._get_workspace_status()
        self.workspace_status_var.set(workspace.label)
        self.workspace_group_title_var.set(f"Workspace - {workspace.label}")
        self.project_name_var.set(self.connected_click_filename or "Not connected")
        repair_button = getattr(self, "repair_system_nicknames_button", None)
        if repair_button is not None:
            session = getattr(self, "_session", None)
            analysis = session.analysis if session else None
            has_repairs = bool(analysis and analysis.system_nickname_repairs)
            repair_button.configure(state=tk.NORMAL if has_repairs else tk.DISABLED)

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
        self.generated_dir_var.set(
            str(info.generated_dir) if info.generated_dir else "Not available"
        )
        self.workspace_config_path_var.set(
            str(info.config_path) if info.config_path else "Not configured"
        )
        self.last_regenerated_var.set(self._format_workspace_time(info.last_regenerated_at))
        self.last_backup_var.set(self._format_workspace_time(info.last_backup_at))
        self._refresh_workspace_menu_states()

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
        if self._session is not None:
            return self._session.store
        return self._csv_only_store

    def _live_mdb_path(self):
        """Resolve the MDB path from the currently connected Click instance."""
        if not self.connected_click_hwnd:
            return None
        from .utils.mdb_shared import find_click_database

        db_path = find_click_database(click_hwnd=self.connected_click_hwnd)
        return Path(db_path) if db_path else None

    def _start_analysis_build(self) -> None:
        """Build program analysis in background if connected to a Click project."""
        if self._session is None:
            return
        self._session.start_analysis(self.root)
        self._refresh_workspace_ui()
        if self._workspace_refresh_after_id is None:
            self._workspace_refresh_after_id = self.root.after(250, self._poll_workspace_ui)

    def _workspace_rung_apply(self) -> None:
        """Preview workspace changes through the reviewed proposal flow."""
        if self._session is None or self._live_server is None:
            self._update_status("Connect to a CLICK project first", "error")
            return

        try:
            self._live_server.dispatch_now("rung apply")
        except Exception as exc:
            messagebox.showerror("Preview Changes", str(exc), parent=self.root)
            self._update_status(f"Preview failed: {exc}", "error")
            return

        status = self._get_workspace_status()
        if status.changed_rungs:
            self._update_status(f"Previewing {status.label}", "connected")
        else:
            self._update_status("Workspace clean; no changed rungs to preview", "connected")

    def _workspace_reload_finished(self, success: bool, error: str | None) -> None:
        """Report completion of an explicit CLICK-to-workspace reload."""
        if success:
            if self._session is not None:
                self._session.record_rung_stage(0)
            self._update_status("Workspace reloaded from CLICK", "connected")
            self._refresh_workspace_ui()
            return
        message = error or "Workspace could not be reloaded from CLICK."
        messagebox.showerror("Reload from CLICK", message, parent=self.root)
        self._update_status(f"Workspace reload failed: {message}", "error")
        self._refresh_workspace_ui()

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
        self._refresh_workspace_ui()

    def _apply_active_filter(self, candidates: list[str], search_text: str) -> list[str]:
        mode = self.settings.search_mode
        strategy = self.filter_strategies.get(mode, self.filter_strategies["contains"])
        return strategy.filter_matches(candidates, search_text)

    def _open_console(self):
        """Open the Console window, or focus if already open."""
        if self._session is None:
            self._update_status("Connect to a Click project first", "error")
            return

        session = self._session
        if session.console is not None:
            try:
                session.console.lift()
                session.console.focus_force()
                return
            except tk.TclError:
                session.console = None

        mdb_path = self._live_mdb_path()
        if mdb_path is None or not list(mdb_path.parent.glob("Scr*.tmp")):
            self._update_status(
                "Project not saved to disk. Please save in Click Software first.",
                "error",
            )
            return

        analysis = session.analysis
        if analysis is None or not analysis.is_available:
            self._start_analysis_build()
            analysis = session.analysis

        # A conversion that already failed will not fix itself by opening a
        # console -- say so up front rather than showing an inert window.
        if analysis is not None and not analysis.is_available:
            from .services.analysis_service import AnalysisStatus

            if analysis.status is AnalysisStatus.FAILED:
                messagebox.showerror(
                    "Cannot Open Console",
                    f"{analysis.error}\n\nThe Console needs the project converted to pyrung.",
                    parent=self.root,
                )
                return

        from .views.console_window import ConsoleWindow

        session.console = ConsoleWindow(
            self.root,
            get_store=lambda: session.store,
            get_analysis=lambda: session.analysis,
            get_click_hwnd=lambda: session.hwnd,
            get_mdb_path=self._live_mdb_path,
            get_synced_pending=lambda: session.synced_pending,
            filter_func=self._apply_active_filter,
            on_destroy=lambda: setattr(session, "console", None),
            on_retry_analysis=self._start_analysis_build,
            title_suffix=session.filename or "",
            session_name=f"clicknick-{session.filename}-{session.hwnd}",
        )

    def _show_odbc_warning(self):
        """Show a warning dialog about missing ODBC drivers."""
        OdbcWarningDialog(self.root)

    def _on_editor_synced(self, count: int) -> None:
        if self._session is not None:
            self._session.record_sync(count)
            analysis = self._session.analysis
            if analysis is not None and analysis.system_nickname_repairs:
                self._start_analysis_build()

    def _open_address_editor(self, initial_filter: str | None = None):
        """Open the Address Editor window.

        Multiple windows can be opened and they will share the same data.
        Changes made in one window are automatically reflected in others.

        Args:
            initial_filter: If given (e.g. "changed"), the new window's first tab
                is switched to that row filter once its data has loaded.
        """
        # Check for ODBC drivers (MDB mode requires them)
        csv_path = self.csv_path_var.get()
        if not csv_path and not self.nickname_manager.has_access_driver():
            self._show_odbc_warning()
            return

        store = self._get_store()
        if store is None:
            self._update_status("No data loaded", "error")
            return

        try:
            from .views.address_editor.window import AddressEditorWindow

            window = AddressEditorWindow(
                self.root,
                address_store=store,
                click_filename=self.connected_click_filename or "",
                analysis_service=self._session.analysis if self._session else None,
                on_synced=self._on_editor_synced,
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
            self._refresh_workspace_ui()
            return

        self._open_address_editor("changed")
        self._update_status(
            f"Staged {len(repairs)} system nickname repair(s); review Changed, then Sync",
            "connected",
        )

    def _open_dataview_editor(self):
        """Open the Dataview Editor window, or focus if already open.

        The dataview editor allows creating and editing CLICK DataView files (.cdv).
        Only one DataviewEditorWindow can be open at a time.
        """
        store = self._get_store()
        if store is None:
            self._update_status("No data loaded", "error")
            return

        try:
            from .data.shared_dataview import SharedDataviewData
            from .utils.mdb_shared import get_project_path_from_hwnd
            from .views.dataview_editor.window import DataviewEditorWindow

            project_path = get_project_path_from_hwnd(self.connected_click_hwnd)

            csv_fallback_folder = None
            if project_path is None:
                csv_path = self.csv_path_var.get()
                if csv_path:
                    from pathlib import Path

                    csv_fallback_folder = Path(csv_path).parent

            # Get or create shared dataview data from session or CSV-only state
            if self._session is not None:
                shared = self._session.dataview
                if shared is None:
                    shared = SharedDataviewData(
                        project_path=project_path,
                        address_store=store,
                        dataview_folder=csv_fallback_folder,
                        filter_func=self._apply_active_filter,
                    )
                    self._session.dataview = shared
            else:
                shared = self._csv_only_dataview
                if shared is None:
                    shared = SharedDataviewData(
                        project_path=project_path,
                        address_store=store,
                        dataview_folder=csv_fallback_folder,
                        filter_func=self._apply_active_filter,
                    )
                    self._csv_only_dataview = shared

            if shared._window is not None:
                try:
                    shared._window.lift()
                    shared._window.focus_force()
                    return
                except Exception:
                    shared._window = None

            DataviewEditorWindow(
                self.root,
                shared_data=shared,
                title_suffix=self.connected_click_filename or "",
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            self._update_status(f"Error opening dataview editor: {e}", "error")

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
            project_name=self.connected_click_filename or "",
        )

    def _analyze_program(self) -> None:
        """Run program validation and display a report that can be refreshed in place."""
        from .views.analysis_report_window import AnalysisReportWindow

        data = self._run_program_checks()
        if data is not None:
            AnalysisReportWindow(self.root, data, rerun=self._run_program_checks)

    def _ensure_plc_name_for_workspace(self) -> str | None:
        """Prompt for a missing PLC name only when durable setup is requested."""
        plc_name = self._current_plc_name()
        if plc_name:
            return plc_name

        from .live.session import click_temp_dir
        from .models.name_validation import validate_click_name
        from .services.workspace_mirror import write_plc_name

        if self._session is None or not self.connected_click_hwnd:
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
                    click_temp_dir(self.connected_click_hwnd) / "Project.ini",
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
        """Choose a home and preview the PLC-named workspace destination."""
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
        """Preview a known matching workspace selected by the user."""
        selected = self.mirror_project_selection_var.get().strip()
        config = next(
            (match for match in self._workspace_matches if str(match.workspace_path) == selected),
            None,
        )
        if config is not None:
            self._set_pending_workspace_config(config)

    def _apply_workspace_mirror_setup(self) -> None:
        """Make the selected durable directory the active project workspace."""
        dialog_parent = getattr(self, "_mirror_setup_window", None) or self.root
        plc_name = self._ensure_plc_name_for_workspace()
        if self._session is None or plc_name is None:
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
        if config.plc_name.casefold() != plc_name.casefold():
            messagebox.showerror(
                "Setup Workspace",
                f'This workspace belongs to PLC "{config.plc_name}", not "{plc_name}".',
                parent=dialog_parent,
            )
            return
        mirror_path = config.workspace_path.resolve()

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

        from .services.project_workspace import (
            plc_source_is_modified,
            record_generated_plc_source,
        )
        from .services.workspace_mirror import (
            remember_project_sidecar,
            save_project_workspace_config,
            sync_workspace_to_mirror,
            validate_mirror_destination,
        )

        try:
            source = self._workspace_source_dir()
            changing_location = source is not None and source.resolve() != mirror_path.resolve()
            if changing_location:
                validate_mirror_destination(source, mirror_path)
            mirror_path.mkdir(parents=True, exist_ok=True)
            if changing_location:
                source_was_modified = plc_source_is_modified(source)
                sync_workspace_to_mirror(source, mirror_path)
                if not source_was_modified:
                    record_generated_plc_source(mirror_path)
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
        """Open the one active workspace used by Preview Changes and Console."""
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
        self._refresh_workspace_ui()

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
        test_header = ttk.Frame(test)
        ttk.Label(test_header, text="Test").pack(side=tk.LEFT)
        test_header_spacer = ttk.Frame(test_header, width=1, height=1)
        test_header_spacer.pack(side=tk.LEFT)
        test.configure(labelwidget=test_header)
        ttk.Button(
            test,
            text="Check Program",
            image=self._action_icons.get("check_program"),
            compound=tk.LEFT,
            command=self._analyze_program,
        ).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(
            test,
            text="Console",
            image=self._action_icons.get("console"),
            compound=tk.LEFT,
            command=self._open_console,
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
            text="Preview Changes",
            image=self._action_icons.get("rung_apply"),
            compound=tk.LEFT,
            command=self._workspace_rung_apply,
        ).pack(fill=tk.X, pady=(0, 8))
        self.repair_system_nicknames_button = ttk.Button(
            workspace,
            text="Repair System Nicknames",
            command=self._repair_system_nicknames,
            state=tk.DISABLED,
        )
        self.repair_system_nicknames_button.pack(fill=tk.X, pady=(0, 8))
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
        self._refresh_workspace_ui()

    def _create_about_dialog(self):
        """Create and show the About dialog."""
        AboutDialog(self.root, get_version())

    def _live_open_address_editor(self, initial_filter: str = "changed") -> None:
        """Open or focus the Address Editor filtered to *initial_filter*.

        Callback for ``clicknick-cli tag apply``. Reuses an already-open editor
        (they all share one store) rather than stacking new windows on repeat
        applies. Runs on the Tk main thread (the live server marshals it there).
        """
        store = self._get_store()
        if store is not None:
            from .views.address_editor.window import AddressEditorWindow

            for win in store._windows:
                if isinstance(win, AddressEditorWindow) and win.winfo_exists():
                    win.apply_row_filter(initial_filter)
                    return
        self._open_address_editor(initial_filter=initial_filter)

    def _verify_mdb_and_cdv(self):
        """Verify MDB addresses and CDV entries for validity.

        Only available in dev mode. See utils/verification.py for full check list.
        """
        if not self.connected_click_pid:
            self._update_status("Connect to a ClickPLC window first", "error")
            return

        store = self._get_store()
        if store is None:
            self._update_status("No data loaded", "error")
            return

        from tkinter import messagebox, scrolledtext

        from .utils.mdb_shared import get_project_path_from_hwnd
        from .utils.verification import run_verification

        project_path = get_project_path_from_hwnd(self.connected_click_hwnd)
        result = run_verification(store, project_path)

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

        Only available in dev mode. Loads rows directly from MDB (no placeholders)
        and deletes any rows where needs_full_delete is True (no content, not used).
        """
        if not self.connected_click_pid:
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
        if analysis.status is AnalysisStatus.FAILED:
            messagebox.showerror(
                "Export Workspace",
                analysis.error or "The workspace could not be built.",
                parent=self.root,
            )
            return
        if not analysis.is_available or analysis.project_dir is None:
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
        """Load a single ladder CSV file to the Click clipboard."""
        csv_file = filedialog.askopenfilename(
            title="Load Ladder CSV to Clipboard",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self.root,
        )
        if not csv_file:
            return

        from pathlib import Path

        from .ladder.clipboard import copy_to_clipboard
        from .ladder.program import prepare_csv_load
        from .utils.mdb_shared import find_click_database

        csv_path = Path(csv_file)

        mdb_path = None
        if self.connected_click_hwnd:
            db_path = find_click_database(click_hwnd=self.connected_click_hwnd)
            if db_path:
                mdb_path = Path(db_path)

        try:
            result = prepare_csv_load(csv_path, mdb_path=mdb_path)
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror(
                "Load Ladder CSV",
                str(exc),
                parent=self.root,
            )
            return

        try:
            copy_to_clipboard(result.payload, owner_hwnd=self.connected_click_hwnd)
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

    def _open_guided_paste(self):
        """Open a folder of ladder CSVs in the guided paste panel."""
        folder = filedialog.askdirectory(
            title="Open in Guided Paste — choose ladder CSV folder",
            parent=self.root,
        )
        if not folder:
            return

        from pathlib import Path

        from .utils.mdb_shared import find_click_database
        from .views.guided_paste_window import GuidedPasteWindow

        folder_path = Path(folder)

        def get_mdb_path() -> Path | None:
            """Resolve MDB from the currently connected Click instance."""
            if not self.connected_click_hwnd:
                return None
            db_path = find_click_database(click_hwnd=self.connected_click_hwnd)
            return Path(db_path) if db_path else None

        GuidedPasteWindow(
            self.root,
            folder_path,
            get_mdb_path=get_mdb_path,
            get_click_hwnd=lambda: self.connected_click_hwnd,
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
        tools_menu.add_command(label="Console...", command=self._open_console)
        if _DEV_MODE:
            tools_menu.add_separator()
            tools_menu.add_command(label="Verify MDB & CDV...", command=self._verify_mdb_and_cdv)
            tools_menu.add_command(label="Clean MDB...", command=self._clean_mdb)

        # Workspace menu. Main-screen placement arrives in the focused UI
        # refresh; these commands own the stable behavior in the meantime.
        workspace_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Workspace", menu=workspace_menu)
        workspace_menu.add_command(label="Preview Changes", command=self._workspace_rung_apply)
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
        ladder_menu.add_command(label="Open in Guided Paste...", command=self._open_guided_paste)
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
        self._refresh_workspace_ui()

    def _live_session_dir(self):
        """Directory the live server advertises its port file in.

        Co-locate with the connected CLICK instance (next to SC_.mdb) when a
        window is connected; otherwise a ClickNick-owned fallback. A connected
        CLICK window always has a temp folder, even without ODBC/CSV access.
        """
        from .live.session import click_temp_dir, fallback_dir

        hwnd = self.connected_click_hwnd
        if hwnd:
            click_dir = click_temp_dir(hwnd)
            if click_dir.is_dir():
                return click_dir
        return fallback_dir()

    def _record_staged_rungs(self, count: int) -> None:
        if self._session is not None:
            self._session.record_rung_stage(count)
        self._refresh_workspace_ui()

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

        # Initialize monitoring state early (before any UI creation)
        self.monitoring = False
        self.monitor_task_id = None

        # Connected Click.exe instance
        self.connected_click_pid = None
        self.connected_click_filename = None
        self.connected_click_hwnd = None
        self._workspace_config = None
        self._workspace_mirror_error = None
        self._workspace_matches = []
        self._pending_workspace_config = None

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
        # (store, analysis, ScrWatcher, console, dataview editor).
        from .connection_session import ConnectionSession

        self._session: ConnectionSession | None = None

        # CSV-only data (used when no Click connection is active)
        self._csv_only_store = None
        self._csv_only_dataview = None

        # Live editing server: lets `clicknick-cli` push edits into this
        # running instance. Holds getters (not snapshots) so it always targets
        # the current store and advertises in the current session directory,
        # both of which change on reconnect/project-switch.
        from .live import LiveServer

        self._live_server = LiveServer(
            self.root,
            self._get_store,
            self._live_session_dir,
            lambda: (
                self.connected_click_filename.removesuffix(".ckp")
                if self.connected_click_filename
                else None
            ),
            lambda: self._session.analysis if self._session else None,
            get_workspace_dir=self._workspace_source_dir,
            get_click_hwnd=lambda: self.connected_click_hwnd,
            get_mdb_path=self._live_mdb_path,
            get_synced_pending=lambda: self._session.synced_pending if self._session else 0,
            get_staged_rungs=lambda: self._session.staged_rungs if self._session else 0,
            record_staged_rungs=self._record_staged_rungs,
            get_pyrung_live_available=lambda: bool(
                self._session
                and self._session.console
                and self._session.console.pyrung_live_available
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
        self._workspace_config = None
        self._workspace_mirror_error = None
        self._workspace_matches = []
        self._pending_workspace_config = None
        plc_name = self._current_plc_name()
        if not plc_name:
            self._refresh_workspace_ui()
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
        self._refresh_workspace_ui()

    def _update_window_title(self):
        """Update window title to reflect current connection and data source."""
        if not self.connected_click_filename:
            self.root.title("ClickNick")
            return

        # Determine source type
        if self.csv_path_var.get():
            source = "CSV"
        elif self.using_database:
            source = "DB"
        else:
            source = ""

        if source:
            title = f"ClickNick - {self.connected_click_filename} - {source}"
        else:
            title = f"ClickNick - {self.connected_click_filename}"

        pending = self._session.synced_pending if self._session else 0
        if pending > 0:
            noun = "tag" if pending == 1 else "tags"
            title += f" ({pending} {noun} synced - Save in CLICK)"

        self.root.title(title)

    def _on_sync_status_changed(self, pending: int) -> None:
        self._update_window_title()
        self._refresh_workspace_ui()
        store = self._get_store()
        if store is not None:
            for window in store._windows:
                if hasattr(window, "_update_sync_indicator"):
                    window._update_sync_indicator(pending)

    def _check_odbc_drivers_and_warn(self):
        """Check for ODBC drivers and show warning if none available."""
        if not self.nickname_manager.has_access_driver():
            self._show_odbc_warning()
            return False
        return True

    def _clear_connection_state(self) -> None:
        """Clear the currently connected Click window metadata."""
        self.connected_click_pid = None
        self.connected_click_filename = None
        self.connected_click_hwnd = None
        self.using_database = False
        self._workspace_config = None
        self._workspace_mirror_error = None
        self._workspace_matches = []
        self._pending_workspace_config = None
        self._refresh_workspace_ui()

    def refresh_click_instances(self):
        """Refresh the list of running Click.exe instances."""
        # Remember currently selected instance
        previously_selected = self.selected_instance_var.get()

        # Clear current data
        self.click_instances = []
        self.instances_combobox["values"] = ()
        self.selected_instance_var.set("")

        try:
            # Get all Click.exe instances from detector
            click_instances = self.detector.get_click_instances()

            if not click_instances:
                self._clear_connection_state()
                self._update_window_title()
                self._update_status("⚠ No ClickPLC windows", "error")
                self.start_button.state(["disabled"])  # Disable when no instances
                return

            # Update instance data
            self.click_instances = click_instances
            filenames = [instance.filename for instance in click_instances]
            self.instances_combobox["values"] = filenames
            self.start_button.state(["!disabled"])  # Enable when instances found

            # Try to restore previous selection
            if previously_selected in filenames:
                self.selected_instance_var.set(previously_selected)
            elif filenames:
                # If previous selection not found, select first item
                self.selected_instance_var.set(filenames[0])
                # Auto-connect to first instance
                self._on_instance_selected()

        except Exception as e:
            print(f"Error refreshing Click instances: {e}")
            self._update_status(f"⚠ Error: {e!s}", "error")
            self.start_button.state(["disabled"])  # Disable on error

    def load_csv(self):
        """Load nicknames from CSV file."""
        csv_path = self.csv_path_var.get()
        if not csv_path:
            self._update_status("⚠ No CSV file selected", "error")
            return False

        try:
            from .data.data_source import CsvDataSource

            data_source = CsvDataSource(csv_path)
            store = AddressStore(data_source)
            store.load_initial_data()
            store.start_file_monitoring(self.root)

            if self._session is not None:
                self._session.replace_store(store, self.root)
            else:
                if self._csv_only_store is not None:
                    self._csv_only_store.stop_file_monitoring()
                self._csv_only_store = store

            self.nickname_manager.set_shared_data(store)
            self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

            self._update_status("✓ CSV loaded", "connected")
            self.using_database = False
            self._update_window_title()
            has_live_connection = bool(self.connected_click_pid and self.connected_click_hwnd) and (
                self.detector.check_window_exists(self.connected_click_pid)
            )
            if has_live_connection:
                self.start_monitoring()
            else:
                if self.monitoring:
                    self.stop_monitoring(update_status=False)
                if self.connected_click_pid or self.connected_click_hwnd:
                    self._clear_connection_state()
                    self.selected_instance_var.set("")
                    self._update_window_title()
            return True
        except Exception as e:
            print(f"Error loading CSV: {e}")
            self._update_status("⚠ CSV load failed", "error")
            return False

    def browse_and_load_csv(self):
        """Browse for and load CSV file from menu."""
        filepath = filedialog.askopenfilename(
            title="Select Nickname CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filepath:
            self.csv_path_var.set(filepath)
            self.load_csv()

    def load_from_database(self):
        """Start monitoring after SharedAddressData is loaded."""
        if not self.connected_click_pid:
            self._update_status("⚠ Not connected", "error")
            return False

        # Check if ODBC drivers are available
        if not self.nickname_manager.has_access_driver():
            self._update_status("⏹ Stopped - Use File → Load Nicknames... to Start", "status")
            if not self._odbc_warning_shown:
                self._show_odbc_warning()
                self._odbc_warning_shown = True
            return False

        if self._get_store() is None:
            self._update_status("⚠ DB load failed", "error")
            self.using_database = False
            return False

        # Apply user's sorting preference
        self.nickname_manager.apply_sorting(self.settings.sort_by_nickname)

        self._update_status("✓ DB loaded", "connected")
        self.using_database = True
        self._update_window_title()

        self.start_monitoring()
        return True

    def connect_to_instance(self, pid, title, filename, hwnd):
        """Connect to a specific Click.exe instance."""
        from .connection_session import ConnectionSession

        # Close existing session (prompt to save)
        if self._session is not None:
            if not self._session.close(prompt_save=True):
                self.selected_instance_var.set(self._session.filename)
                return
            self.nickname_manager.set_shared_data(None)
            self._session = None

        # Close CSV-only data if any
        if self._csv_only_store is not None:
            self._csv_only_store.stop_file_monitoring()
            self._csv_only_store = None
        if self._csv_only_dataview is not None:
            self._csv_only_dataview.set_address_store(None)
            self._csv_only_dataview = None

        # Stop monitoring if currently active
        if self.monitoring:
            self.stop_monitoring()

        # Reset connection state
        self._clear_connection_state()

        # Clear CSV path when switching instances
        self.csv_path_var.set("")

        # Store the new connection FIRST (including hwnd to avoid lookup issues)
        self.connected_click_pid = pid
        self.connected_click_filename = filename
        self.connected_click_hwnd = hwnd
        self._load_workspace_pairing()

        # Check for ODBC drivers - if missing, try CSV fallback
        if not self.nickname_manager.has_access_driver():
            # Modal fallback/warning dialogs need a visible parent even during
            # the otherwise-hidden startup connection pass.
            self._show_main_window()
            fallback_csv = find_fallback_csv(hwnd)
            if fallback_csv:
                default_name = f"{filename.replace('.ckp', '')}_Address.csv"
                dialog = CsvFallbackDialog(self.root, fallback_csv, default_name)
                saved_path = dialog.show()
                if saved_path:
                    self.csv_path_var.set(saved_path)
                    self.load_csv()
                    return
            self._update_status("⏹ Stopped - Use File → Load Nicknames...", "error")
            if not self._odbc_warning_shown:
                self._show_odbc_warning()
                self._odbc_warning_shown = True
            return

        # Create session with MDB-backed store
        from .data.data_source import MdbDataSource

        data_source = MdbDataSource(click_pid=pid, click_hwnd=hwnd)
        store = AddressStore(data_source)
        store.load_initial_data()
        store.start_file_monitoring(self.root)

        self._session = ConnectionSession(
            pid,
            hwnd,
            filename,
            store,
            workspace_dir=self._configured_workspace_dir(),
            on_sync_status_changed=self._on_sync_status_changed,
        )

        self.nickname_manager.set_shared_data(store)
        self.load_from_database()
        self._start_analysis_build()

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

    def _handle_window_closed(self):
        """Handle when connected window is no longer available."""
        self._update_status("⚠ Connected ClickPLC window closed", "error")
        self.stop_monitoring(update_status=False)

        if self._session is not None:
            if self.using_database:
                self._session.force_close()
                self.nickname_manager.set_shared_data(None)
            else:
                # CSV data is still valid — keep the store but close Click resources
                self._session.detach_click_resources()
                self._csv_only_store = self._session.store
                self._csv_only_dataview = self._session.dataview
            self._session = None

        self._clear_connection_state()
        self.selected_instance_var.set("")
        self._update_window_title()

        self.root.after(2000, self.refresh_click_instances)

    def _handle_project_change(self, current_title: str, new_filename: str) -> bool:
        """Handle Click project filename change. Returns False if monitoring stopped."""
        has_open_windows = False
        if self._session is not None:
            has_open_windows = (
                len(self._session.store._windows) > 0
                or (
                    self._session.dataview is not None
                    and self._session.dataview._window is not None
                )
                or self._session.console is not None
            )
        if has_open_windows:
            from tkinter import messagebox

            messagebox.showinfo(
                "Project Changed",
                "The Click project was changed. Editor windows will now close.",
            )

        if self._session is not None:
            self._session.close(prompt_save=False)
            self.nickname_manager.set_shared_data(None)
            self._session = None

        csv_unloaded = False
        if self.csv_path_var.get():
            self.csv_path_var.set("")
            self._update_status("⚠ CSV unloaded - filename changed", "error")
            csv_unloaded = True

        for instance in self.click_instances:
            if instance.pid == self.connected_click_pid:
                instance.title = current_title
                instance.filename = new_filename
                break

        self.instances_combobox["values"] = [inst.filename for inst in self.click_instances]
        self.connected_click_filename = new_filename
        self.selected_instance_var.set(new_filename)
        self._load_workspace_pairing()

        if csv_unloaded:
            self.using_database = False
            self._update_window_title()
            self.stop_monitoring(update_status=False)
            return False

        from .connection_session import ConnectionSession

        if self.nickname_manager.has_access_driver():
            from .data.data_source import MdbDataSource

            data_source = MdbDataSource(
                click_pid=self.connected_click_pid,
                click_hwnd=self.connected_click_hwnd,
            )
            store = AddressStore(data_source)
            store.load_initial_data()
            store.start_file_monitoring(self.root)

            self._session = ConnectionSession(
                self.connected_click_pid,
                self.connected_click_hwnd,
                new_filename,
                store,
                workspace_dir=self._configured_workspace_dir(),
                on_sync_status_changed=self._on_sync_status_changed,
            )
            self.nickname_manager.set_shared_data(store)

            self.using_database = True
            self._update_window_title()
            self._start_analysis_build()

        self._update_status(f"⚡ Monitoring {new_filename}", "connected")
        return True

    def _handle_popup_detection(self) -> None:
        """Check for Click.exe child popups and show/hide overlay accordingly."""
        child_info = self.detector.detect_child_window(self.connected_click_pid)
        if child_info:
            if not self.detector.field_has_text(child_info.edit_control, child_info.window_id):
                self._handle_popup_window(
                    child_info.window_id, child_info.window_class, child_info.edit_control
                )
        elif self.overlay:
            self.overlay.withdraw()

    def _monitor_task(self):
        """Monitor task that runs every 100ms using after."""
        if not self.monitoring:
            return

        window_id = self.connected_click_hwnd
        if not window_id or not self.detector.check_window_exists(self.connected_click_pid):
            self._handle_window_closed()
            return

        current_title = self.detector.get_window_title(window_id)
        new_filename = self._parse_filename_from_title(current_title)

        if new_filename and new_filename != self.connected_click_filename:
            if not self._handle_project_change(current_title, new_filename):
                return

        if not (self.overlay and self.overlay.is_active()):
            self._handle_popup_detection()

        self.monitor_task_id = self.root.after(100, self._monitor_task)

    def _start_monitoring_internal(self) -> bool:
        """Internal method to start monitoring without status updates.
        Returns True if successful, False otherwise."""
        # Validate connection to Click instance
        if not self.connected_click_pid:
            self._update_status("⚠ Not connected to ClickPLC window", "error")
            return False

        # Start monitoring using after
        try:
            self.monitoring = True
            self._monitor_task()
            return True
        except Exception as e:
            self._update_status(f"⚠ Monitoring failed: {str(e)}", "error")
            return False

    def _update_status_monitoring(self):
        """Update Status and Button to reflect Monitoring"""
        self._update_status(f"⚡ Monitoring {self.connected_click_filename}", "connected")
        self.start_button.configure(text="⏹ Stop")

    def start_monitoring(self):
        """Start monitoring with delayed status update."""
        if self._start_monitoring_internal():
            # Only schedule status update if successful
            self.root.after(1000, lambda: self._update_status_monitoring())

    def button_start_monitoring(self):
        """Start monitoring with immediate status update."""
        if self._start_monitoring_internal():
            # Only update UI if successful
            self._update_status_monitoring()

    def stop_monitoring(self, update_status=True):
        """Stop monitoring."""
        self.monitoring = False

        # Cancel scheduled task if it exists
        if self.monitor_task_id:
            self.root.after_cancel(self.monitor_task_id)
            self.monitor_task_id = None

        # Destroy overlay if it exists
        if self.overlay:
            self.overlay.withdraw()
            self.overlay = None

        if update_status:
            self._update_status("⏹ Stopped", "status")
        self.start_button.configure(text="▶ Start")

    def toggle_monitoring(self):
        """Start or stop monitoring."""
        if self.monitoring:
            self.stop_monitoring()
        else:
            # Only update button if start was successful
            if self.button_start_monitoring():
                self.start_button.configure(text="⏹ Stop")

    def open_url(self, url):
        """Open URL in default browser."""
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception as e:
            self._update_status(f"⚠ Could not open browser: {e}", "error")

    def on_closing(self):
        """Handle application shutdown."""
        if self.monitoring:
            self.stop_monitoring()
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
        if self._session is not None:
            self._session.force_close()
            self._session = None
        if self._csv_only_store is not None:
            self._csv_only_store.stop_file_monitoring()
            self._csv_only_store = None
        live_server = getattr(self, "_live_server", None)
        if live_server is not None:
            live_server.stop()
        self.root.destroy()

    def run(self):
        """Run the ClickNick Application"""
        self.refresh_click_instances()
        self._show_main_window()
        self.root.mainloop()


def main() -> None:
    """Entry point for the application."""
    app = ClickNickApp()
    app.run()


def main_dev() -> None:
    """Entry point for development mode with in-progress features enabled.

    Args (via sys.argv):
        -csvonly: Force CSV-only mode (pretend ODBC drivers are unavailable)
    """
    import sys

    global _DEV_MODE
    _DEV_MODE = True

    if "-csvonly" in sys.argv:
        set_csv_only_mode(True)
        print("CSV-only mode enabled (ODBC drivers will appear unavailable)")

    app = ClickNickApp()
    app.run()


if __name__ == "__main__":
    main()  # Call the main function when run directly
