import tkinter as tk
from ctypes import windll
from pathlib import Path
from tkinter import PhotoImage, filedialog, font, messagebox, ttk

from .config import AppSettings
from .data.address_store import AddressStore
from .data.nickname_manager import NicknameManager
from .detection.window_detector import ClickWindowDetector
from .detection.window_mapping import CLICK_PLC_WINDOW_MAPPING
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
        self.click_instances = []  # Will store ClickInstance objects
        self.using_database = False  # Flag to track if database is being used
        self._odbc_warning_shown = False

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

    def _create_options_section(self, parent):
        """Create the options section."""
        options_frame = ttk.LabelFrame(parent, text="Autocomplete Options", padding=10)

        # Search mode widgets
        filter_frame = ttk.Frame(options_frame)
        filter_label = ttk.Label(filter_frame, text="Filter Mode:")
        none_radio = ttk.Radiobutton(
            filter_frame,
            text="None",
            variable=self.settings.search_var,
            value="none",
        )
        prefix_radio = ttk.Radiobutton(
            filter_frame,
            text="Prefix Only",
            variable=self.settings.search_var,
            value="prefix",
        )
        contains_radio = ttk.Radiobutton(
            filter_frame,
            text="Contains",
            variable=self.settings.search_var,
            value="contains",
        )
        contains_plus_radio = ttk.Radiobutton(
            filter_frame,
            text="Abbreviations",
            variable=self.settings.search_var,
            value="containsplus",
        )

        # Layout filter widgets
        filter_label.pack(side=tk.LEFT, padx=(0, 8))
        none_radio.pack(side=tk.LEFT, padx=(0, 8))
        prefix_radio.pack(side=tk.LEFT, padx=(0, 8))
        contains_radio.pack(side=tk.LEFT, padx=(0, 8))
        contains_plus_radio.pack(side=tk.LEFT)
        filter_frame.pack(fill=tk.X, pady=(0, 8))

        # Checkbox row (Sort, Tooltips, SC/SD)
        checkbox_frame = ttk.Frame(options_frame)  # New frame to hold checkboxes in one row
        checkbox_frame.pack(fill=tk.X, pady=(0, 6))

        # Sort A-Z checkbox
        sort_check = ttk.Checkbutton(
            checkbox_frame,
            text="Sort A→Z",
            variable=self.settings.sort_by_nickname_var,
            command=self._on_sort_option_changed,
        )
        sort_check.pack(side=tk.LEFT, padx=(0, 8))

        # Tooltip checkbox
        tooltip_check = ttk.Checkbutton(
            checkbox_frame,
            text="Show Tooltips",
            variable=self.settings.show_info_tooltip_var,
        )
        tooltip_check.pack(side=tk.LEFT, padx=(0, 8))

        # SC/SD exclusion checkbox
        sc_sd_check = ttk.Checkbutton(
            checkbox_frame, text="Exclude SC/SD Addresses", variable=self.settings.exclude_sc_sd_var
        )
        sc_sd_check.pack(side=tk.LEFT)

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
        exclude_frame_entry.pack(fill=tk.X, pady=(0, 6))

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

    def _sync_workspace_mirror(self) -> None:
        """Synchronize ClickNick-owned workspace files in one direction."""
        config = self._workspace_config
        if config is None:
            messagebox.showinfo(
                "Sync Workspace Mirror",
                "Set up a Workspace Mirror first.",
                parent=self.root,
            )
            return
        source = self._workspace_source_dir()
        if source is None:
            messagebox.showerror(
                "Sync Workspace Mirror",
                "The generated workspace is not ready.",
                parent=self.root,
            )
            return

        from .services.workspace_mirror import (
            record_successful_sync,
            sync_workspace_to_mirror,
        )

        try:
            result = sync_workspace_to_mirror(source, config.mirror_path)
            self._workspace_config = record_successful_sync(config, result)
        except (OSError, ValueError) as exc:
            self._workspace_mirror_error = str(exc)
            messagebox.showerror("Sync Workspace Mirror", str(exc), parent=self.root)
            self._update_status(f"Workspace mirror sync failed: {exc}", "error")
            return

        self._workspace_mirror_error = None
        self._update_status(
            f"Workspace mirror synced ({result.copied_files} files): {result.mirror_path}",
            "connected",
        )

    def _setup_workspace_mirror(self) -> None:
        """Pair the connected project with a durable one-way mirror directory."""
        filename = self.connected_click_filename
        if self._session is None or not filename:
            self._update_status("Connect to a CLICK project first", "error")
            return

        project_value = filedialog.askopenfilename(
            title=f"Locate the source CLICK project ({filename})",
            initialfile=filename,
            filetypes=[("CLICK project", "*.ckp"), ("All files", "*.*")],
            parent=self.root,
        )
        if not project_value:
            return
        project_file = Path(project_value)
        if project_file.name.casefold() != filename.casefold():
            messagebox.showerror(
                "Setup Workspace Mirror",
                f"Select the connected project named {filename}.",
                parent=self.root,
            )
            return

        mirror_value = filedialog.askdirectory(
            title=f"Select or create {project_file.stem} Workspace",
            initialdir=project_file.parent,
            mustexist=False,
            parent=self.root,
        )
        if not mirror_value:
            return
        mirror_path = Path(mirror_value)
        try:
            mirror_is_nonempty = mirror_path.exists() and any(mirror_path.iterdir())
        except OSError as exc:
            messagebox.showerror("Setup Workspace Mirror", str(exc), parent=self.root)
            self._update_status(f"Workspace mirror setup failed: {exc}", "error")
            return
        if mirror_is_nonempty:
            confirmed = messagebox.askokcancel(
                "Use Existing Workspace Folder?",
                "ClickNick will update generated files under src/plc and csv, plus "
                "its generation scripts and data. It will not delete unrelated files "
                "or replace existing tests, documentation, or editor settings.",
                parent=self.root,
            )
            if not confirmed:
                return

        from .services.workspace_mirror import (
            ProjectWorkspaceConfig,
            remember_project_sidecar,
            save_project_workspace_config,
            validate_mirror_destination,
        )

        config = ProjectWorkspaceConfig(project_file=project_file, mirror_path=mirror_path)
        try:
            source = self._workspace_source_dir()
            if source is not None:
                validate_mirror_destination(source, mirror_path)
            sidecar = save_project_workspace_config(config)
            remember_project_sidecar(sidecar)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Setup Workspace Mirror", str(exc), parent=self.root)
            self._update_status(f"Workspace mirror setup failed: {exc}", "error")
            return

        self._workspace_config = config
        self._workspace_mirror_error = None
        if source is not None:
            self._sync_workspace_mirror()
        else:
            self._update_status(f"Workspace mirror paired: {mirror_path}", "connected")

    def _open_workspace_folder(self) -> None:
        """Open the paired mirror, or the active generated workspace as fallback."""
        path = (
            self._workspace_config.mirror_path
            if self._workspace_config is not None
            else self._workspace_source_dir()
        )
        if path is None or not path.is_dir():
            self._update_status("Workspace folder is not available", "error")
            return
        try:
            import os

            os.startfile(path)  # noqa: S606 - explicit user action on Windows
        except OSError as exc:
            messagebox.showerror("Open Workspace Folder", str(exc), parent=self.root)

    def _workspace_rung_apply(self) -> None:
        """Run the consolidated reviewed proposal flow for workspace rungs."""
        if self._session is None or self._live_server is None:
            self._update_status("Connect to a CLICK project first", "error")
            return

        try:
            self._live_server.dispatch_now("rung apply")
        except Exception as exc:
            messagebox.showerror("Rung Apply", str(exc), parent=self.root)
            self._update_status(f"Rung Apply failed: {exc}", "error")
            return

        status = self._get_workspace_status()
        if status.changed_rungs:
            self._update_status(f"Rung Apply: reviewing {status.label}", "connected")
        else:
            self._update_status("Workspace clean; no changed rungs to apply", "connected")

    def _workspace_reload_finished(self, success: bool, error: str | None) -> None:
        """Report completion of an explicit CLICK-to-workspace reload."""
        if success:
            if self._session is not None:
                self._session.record_rung_stage(0)
            self._update_status("Workspace reloaded from CLICK", "connected")
            return
        message = error or "Workspace could not be reloaded from CLICK."
        messagebox.showerror("Reload from CLICK", message, parent=self.root)
        self._update_status(f"Workspace reload failed: {message}", "error")

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

    def _create_about_dialog(self):
        """Create and show the About dialog."""
        AboutDialog(self.root, get_version())

    def _show_odbc_warning(self):
        """Show a warning dialog about missing ODBC drivers."""
        OdbcWarningDialog(self.root)

    def _on_editor_synced(self, count: int) -> None:
        if self._session is not None:
            self._session.record_sync(count)

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

    @staticmethod
    def _get_export_popup_flag() -> Path:
        """Get path to the flag indicating the Export beta popup has been seen."""
        import os

        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return base / "ClickNick" / "export_from_click_popup_seen"

    def _show_export_popup(self) -> None:
        """Show first-run info for Export from Click (appears once per user)."""
        flag_path = self._get_export_popup_flag()

        if flag_path.exists():
            return

        popup_text = (
            "Export from Click\n\n"
            "This feature decodes CLICK's internal program files into CSV.\n"
            "Contacts, instructions, or entire rungs may decode incorrectly\n"
            "or be missing. Email, Home, Position, and Velocity instructions\n"
            "are exported as raw(...) placeholders.\n\n"
            "If you encounter errors or unexpected output, please report\n"
            "them — sample programs help us improve the decoder."
        )

        messagebox.showinfo("First-Time Tips", popup_text, parent=self.root)

        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch()

    def _export_from_click(self):
        """Export Scr*.tmp from the connected Click project to a CSV bundle."""
        if not self.connected_click_hwnd:
            messagebox.showwarning(
                "Export from Click",
                "Not connected to a Click project.\n\nStart monitoring first.",
                parent=self.root,
            )
            return

        from pathlib import Path

        from .utils.mdb_shared import find_click_database

        db_path = find_click_database(click_hwnd=self.connected_click_hwnd)
        if not db_path:
            messagebox.showerror(
                "Export from Click",
                "Could not locate the Click project folder.",
                parent=self.root,
            )
            return
        scr_folder = Path(db_path).parent

        self._show_export_popup()

        output = filedialog.askdirectory(
            title="Export from Click — choose output folder",
            parent=self.root,
        )
        if not output:
            return

        from .ladder.program import program_save

        while True:
            try:
                result = program_save(scr_folder, Path(output))
            except (FileNotFoundError, ValueError) as exc:
                messagebox.showerror("Export from Click", str(exc), parent=self.root)
                return
            except PermissionError as exc:
                retry = messagebox.askretrycancel(
                    "Export from Click",
                    f"Cannot write to output folder — a file may be open"
                    f" in another program.\n\n{exc}",
                    parent=self.root,
                )
                if retry:
                    continue
                return
            break

        # Write nicknames.csv from the MDB alongside the ladder CSVs
        nick_count = 0
        try:
            from .data.data_source import CsvDataSource
            from .utils.mdb_operations import MdbConnection, load_all_addresses

            with MdbConnection(str(db_path)) as conn:
                all_rows = load_all_addresses(conn)
            nick_dest = Path(output) / "nicknames.csv"
            nick_count = CsvDataSource(str(nick_dest)).save_changes(list(all_rows.values()))
        except PermissionError:
            messagebox.showwarning(
                "Export from Click",
                "Could not write nicknames.csv — file may be open.\n"
                "Ladder CSVs were exported successfully.",
                parent=self.root,
            )
        except Exception:
            pass  # nicknames export is best-effort

        sub_count = len(result.subroutine_csvs)
        parts = [f"{result.total_rungs} rungs", f"{sub_count} subroutine(s)"]
        if nick_count:
            parts.append(f"{nick_count} tags")
        self._update_status(
            f"Exported {', '.join(parts)} to {output}",
            "connected",
        )

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

    def _analyze_program(self) -> None:
        """Run program validation and display report."""
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

        from .views.analysis_report_window import (
            AnalysisReportData,
            AnalysisReportWindow,
        )

        AnalysisReportWindow(self.root, AnalysisReportData(grouped_findings=grouped))

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
        tools_menu.add_command(label="Console...", command=self._open_console)
        tools_menu.add_command(label="Check Program", command=self._analyze_program)
        if _DEV_MODE:
            tools_menu.add_separator()
            tools_menu.add_command(label="Verify MDB & CDV...", command=self._verify_mdb_and_cdv)
            tools_menu.add_command(label="Clean MDB...", command=self._clean_mdb)

        # Workspace menu. Main-screen placement arrives in the focused UI
        # refresh; these commands own the stable behavior in the meantime.
        workspace_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Workspace", menu=workspace_menu)
        workspace_menu.add_command(label="Rung Apply", command=self._workspace_rung_apply)
        workspace_menu.add_command(
            label="Reload from CLICK...", command=self._workspace_reload_from_click
        )
        workspace_menu.add_separator()
        workspace_menu.add_command(label="Setup Mirror...", command=self._setup_workspace_mirror)
        workspace_menu.add_command(label="Sync Now", command=self._sync_workspace_mirror)
        workspace_menu.add_command(
            label="Open Workspace Folder", command=self._open_workspace_folder
        )
        workspace_menu.add_separator()
        workspace_menu.add_command(label="Export Workspace...", command=self._export_pyrung_project)

        # Ladder menu
        ladder_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Ladder", menu=ladder_menu)
        ladder_menu.add_command(
            label="Load Ladder CSV to Clipboard...", command=self._load_ladder_csv
        )
        ladder_menu.add_command(label="Open in Guided Paste...", command=self._open_guided_paste)
        ladder_menu.add_separator()
        ladder_menu.add_command(label="Save Clipboard to CSV...", command=self._save_clipboard_csv)
        ladder_menu.add_command(label="Export from Click...", command=self._export_from_click)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
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
        # Add menu bar first
        self._create_menu_bar()

        # Main frame to contain everything with consistent padding
        main_frame = ttk.Frame(self.root, padding="15")  # Reduce from 20 to 15

        # Create all widgets
        self._create_click_instances_section(main_frame)
        self._create_options_section(main_frame)

        # Pack the main frame
        main_frame.pack(fill=tk.BOTH, expand=True)

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
            get_click_hwnd=lambda: self.connected_click_hwnd,
            get_mdb_path=self._live_mdb_path,
            get_synced_pending=lambda: self._session.synced_pending if self._session else 0,
            get_staged_rungs=lambda: self._session.staged_rungs if self._session else 0,
            record_staged_rungs=lambda count: (
                self._session.record_rung_stage(count) if self._session else None
            ),
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

        # Create UI components
        self._create_widgets()

        # Show the window after everything is created
        self.root.update_idletasks()
        self.root.deiconify()

    def _load_workspace_pairing(self) -> None:
        """Load the sole known sidecar matching the connected project name."""
        from .services.workspace_mirror import find_project_configs

        self._workspace_config = None
        self._workspace_mirror_error = None
        filename = self.connected_click_filename
        if not filename:
            return
        matches = find_project_configs(filename)
        if len(matches) == 1:
            self._workspace_config = matches[0]

    def _get_workspace_mirror_status(self):
        """Return reusable pairing status for the future Workspace details panel."""
        from .services.workspace_mirror import get_mirror_status

        return get_mirror_status(
            self._workspace_config,
            self._workspace_source_dir(),
            error=self._workspace_mirror_error,
        )

    def _get_workspace_directory_info(self):
        """Return paths and timestamps for the future Workspace details panel."""
        from .services.workspace_mirror import get_workspace_directory_info

        return get_workspace_directory_info(
            self._workspace_config,
            self._workspace_source_dir(),
        )

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
