"""The main window's Workspace: its status, its folder, Workspace setup and its commands.

The facts live elsewhere. The connected session (``ClickNickApp._session``) holds the
workspace pairing, the setup window and the choice that is not applied yet. Its analysis
holds the build. ``WorkspaceController`` reads them through the app each time, so it
follows a project change. It keeps only the Open Workspace menu entries that it updates and
the setup window's list of workspaces (``_config_combobox``).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .connection_session import ConnectionSession
    from .live import LiveServer
    from .services.workspace_mirror import (
        ProjectWorkspaceConfig,
        WorkspaceDirectoryInfo,
        WorkspacePairing,
    )
    from .services.workspace_service import WorkspaceStatus


class WorkspaceHost(Protocol):
    """Name the parts of the app (``ClickNickApp``) that WorkspaceController uses."""

    root: tk.Tk
    _live_server: LiveServer | None
    # The details that Workspace setup shows. The main window shows them too.
    plc_name_var: tk.StringVar
    mirror_setup_status_var: tk.StringVar
    mirror_detail_var: tk.StringVar
    # Workspace setup's form: the workspace that was chosen and the action that applies it
    mirror_project_selection_var: tk.StringVar
    mirror_location_selection_var: tk.StringVar
    workspace_setup_action_var: tk.StringVar

    @property
    def _session(self) -> ConnectionSession | None: ...

    def _project_session(self) -> ConnectionSession | None: ...

    def _update_status(self, message: str, style: str = "normal") -> None: ...

    def _request_ui_refresh(self) -> None: ...

    def _start_analysis_build(self) -> None: ...

    def _close_workspace_reviews(self) -> None: ...


class WorkspaceController:
    """Show and change the connected project's workspace for the main window."""

    def __init__(self, app: WorkspaceHost) -> None:
        self._app = app
        # Each menu's Open Workspace entry, as (menu, index). Each entry follows the workspace.
        self._open_entries: list[tuple[tk.Menu, int]] = []
        # Workspace setup's list of known workspaces, set once the window has been built
        self._config_combobox: ttk.Combobox | None = None

    # -- Status and folders --------------------------------------------------

    @property
    def pairing(self) -> WorkspacePairing:
        """Return the connected project's durable workspace, as its session holds it."""
        from .services.workspace_mirror import WorkspacePairing

        session = self._app._session
        return session.pairing if session is not None else WorkspacePairing()

    def status(self) -> WorkspaceStatus:
        """Return reusable status for the current CLICK workspace."""
        from .services.workspace_service import get_workspace_status

        session = self._app._session
        return get_workspace_status(
            session.analysis if session else None,
            staged_rungs=session.staged_rungs if session else 0,
        )

    def source_dir(self) -> Path | None:
        """Return the workspace that the last build published, or None."""
        session = self._app._session
        analysis = session.analysis if session else None
        return analysis.project_dir if analysis else None

    def configured_dir(self) -> Path | None:
        """Return the paired durable workspace's folder, or None if none is paired."""
        config = self.pairing.config
        return config.workspace_path if config is not None else None

    def display_dir(self) -> Path | None:
        """Return the active path, or the configured target while a rebuild runs."""
        return self.source_dir() or self.configured_dir()

    def plc_name(self) -> str | None:
        """Return CLICK's configured PLC name from its active temp workspace.

        Return None when the project has no name or its Project.ini cannot be read.
        """
        session = self._app._session
        return session.plc_name() if session is not None else None

    def directory_info(self) -> WorkspaceDirectoryInfo:
        """Return paths and timestamps for the Workspace details."""
        from .services.workspace_mirror import get_workspace_directory_info

        return get_workspace_directory_info(self.pairing.config, self.source_dir())

    def earlier_save_build_error(self) -> str | None:
        """Return the build's error if it failed and the workspace is an old save's, else None."""
        from .services.analysis_service import AnalysisStatus

        session = self._app._session
        analysis = session.analysis if session else None
        if analysis is None or analysis.status is not AnalysisStatus.FAILED:
            return None
        if analysis.project_is_current:
            return None
        return analysis.error or "The build failed."

    # -- Menus ---------------------------------------------------------------

    def open_entry_options(self) -> tuple[str, str]:
        """Return the label and state for opening the active workspace."""
        label = "Open Workspace" if self.pairing.config is not None else "Open Temporary Workspace"
        workspace_dir = self.display_dir()
        state = tk.NORMAL if workspace_dir is not None and workspace_dir.is_dir() else tk.DISABLED
        return label, state

    def add_open_entry(self, menu: tk.Menu) -> None:
        """Add Open Workspace to *menu*; ``refresh_menu_states`` keeps it current."""
        label, state = self.open_entry_options()
        menu.add_command(label=label, command=self.open_workspace, state=state)
        self._open_entries.append((menu, menu.index(tk.END)))

    def refresh_menu_states(self) -> None:
        """Follow the active temporary or durable workspace directory."""
        label, state = self.open_entry_options()
        for menu, index in self._open_entries:
            try:
                menu.entryconfigure(index, label=label, state=state)
            except tk.TclError:
                pass

    def populate_options_menu(self, menu: tk.Menu) -> None:
        """Add active-directory commands to the Workspace options menu."""
        self.add_open_entry(menu)
        menu.add_separator()
        menu.add_command(label="View/Setup Workspace...", command=self.open_setup_window)

    # -- Commands ------------------------------------------------------------

    def review_changes(self) -> None:
        """Review workspace changes through the reviewed proposal flow."""
        app = self._app
        if app._project_session() is None or app._live_server is None:
            app._update_status("Connect to a CLICK project first", "error")
            return

        try:
            app._live_server.dispatch_now("rung apply")
        except Exception as exc:
            messagebox.showerror("Review Changes", str(exc), parent=app.root)
            app._update_status(f"Review failed: {exc}", "error")
            return

        status = self.status()
        if status.changed_rungs:
            app._update_status(f"Reviewing {status.label}", "connected")
        else:
            app._update_status("Workspace clean; no changed rungs to review", "connected")

    def _reload_finished(self, success: bool, error: str | None) -> None:
        """Report completion of an explicit CLICK-to-workspace reload."""
        app = self._app
        if success:
            if app._session is not None:
                app._session.record_rung_stage(0)
            # The edits were thrown away, so close the window that offers to paste them.
            app._close_workspace_reviews()
            app._update_status("Workspace reloaded from CLICK", "connected")
            app._request_ui_refresh()
            return
        message = error or "Workspace could not be reloaded from CLICK."
        messagebox.showerror("Reload from CLICK", message, parent=app.root)
        app._update_status(f"Workspace reload failed: {message}", "error")
        app._request_ui_refresh()

    def reload_from_click(self) -> None:
        """Explicitly replace active workspace source from the saved CLICK project."""
        app = self._app
        session = app._project_session()
        if session is None:
            app._update_status("Connect to a CLICK project first", "error")
            return

        from .services.workspace_service import WorkspaceState

        if self.status().state is WorkspaceState.PREPARING:
            app._update_status("Workspace regeneration is already in progress", "error")
            return

        confirmed = messagebox.askokcancel(
            "Reload from CLICK",
            "Reload the workspace from the saved CLICK project?\n\n"
            "This replaces the active generated source. Modified workspace source "
            "will be preserved in the recovery snapshot.",
            parent=app.root,
        )
        if not confirmed:
            return

        app._update_status("Reloading workspace from CLICK...", "connected")

        def _finished(success: bool, error: str | None) -> None:
            if app._session is session:
                self._reload_finished(success, error)

        session.reload_workspace_from_click(app.root, _finished)
        app._request_ui_refresh()

    def _open_folder(self, path: Path | None, *, title: str, unavailable: str) -> None:
        """Open one explicit workspace location in File Explorer."""
        if path is None or not path.is_dir():
            self._app._update_status(unavailable, "error")
            return
        try:
            import os

            os.startfile(path)  # noqa: S606 - explicit user action on Windows
        except OSError as exc:
            messagebox.showerror(title, str(exc), parent=self._app.root)

    def open_workspace(self) -> None:
        """Open the one active workspace used by Review Changes and the Simulator."""
        self._open_folder(
            self.display_dir(),
            title="Open Workspace",
            unavailable="Workspace is not available",
        )

    # -- Workspace setup -----------------------------------------------------

    def _setup_parent(self):
        """Return Workspace setup's window while it is open, else the main window.

        The returned window is the parent of the setup dialogs.
        """
        session = self._app._session
        window = session.setup_window if session is not None else None
        return window or self._app.root

    def _setup_unchanged(self, session: ConnectionSession, window) -> bool:
        """Return True when *session* is still the connected one and *window* is its setup window.

        A dialog runs Tk's loop. While it runs, CLICK's window can close or show another
        project, which closes the session and its setup window. Workspace setup acts after a
        dialog only when this check passes. It therefore never writes one project's choice
        into another project's session, and never parents a dialog to a closed window.
        """
        return session is self._app._session and session.setup_window is window

    def _ensure_plc_name(self) -> str | None:
        """Prompt for a missing PLC name only when durable setup is requested."""
        plc_name = self.plc_name()
        if plc_name:
            return plc_name

        from pyclickplc.project import write_plc_name
        from pyclickplc.validation import validate_click_name

        from .utils.click_temp import click_temp_dir

        app = self._app
        session = app._project_session()
        if session is None:
            app._update_status("Connect to a CLICK project first", "error")
            return None

        window = session.setup_window
        parent = self._setup_parent()
        while True:
            # Check before each prompt too, because the error box before it is a dialog.
            if not self._setup_unchanged(session, window):
                return None
            value = simpledialog.askstring(
                "Name PLC",
                "This project needs a PLC name before it can use a durable workspace.\n\n"
                "Enter a name (maximum 24 characters):",
                parent=parent,
            )
            if value is None or not self._setup_unchanged(session, window):
                return None
            plc_name = value.strip()
            is_valid, error = validate_click_name(plc_name)
            if not is_valid:
                messagebox.showerror("Invalid PLC Name", error, parent=parent)
                continue
            try:
                write_plc_name(
                    click_temp_dir(session.click.hwnd) / "Project.ini",
                    plc_name,
                )
            except (OSError, ValueError) as exc:
                messagebox.showerror("Name PLC", str(exc), parent=parent)
                app._update_status(f"PLC name could not be set: {exc}", "error")
                return None
            app.plc_name_var.set(plc_name)
            messagebox.showinfo(
                "PLC Name Added",
                f'CLICK now identifies this PLC as "{plc_name}".\n\n'
                "Save the project in CLICK to preserve the name.",
                parent=parent,
            )
            return plc_name

    def _set_pending(self, session: ConnectionSession, config: ProjectWorkspaceConfig) -> None:
        """Show one candidate configuration in *session*'s setup form."""
        app = self._app
        session.pending_workspace = config
        matches = session.pairing.matches
        if all(known.sidecar_path != config.sidecar_path for known in matches):
            matches.append(config)
        if config.sidecar_path.is_file():
            app.mirror_project_selection_var.set(str(config.workspace_path))
            app.mirror_location_selection_var.set("")
            app.workspace_setup_action_var.set("Use Workspace")
        else:
            app.mirror_project_selection_var.set("")
            app.mirror_location_selection_var.set(str(config.workspace_path))
            app.workspace_setup_action_var.set("Create Workspace")
        if self._config_combobox is not None:
            self._config_combobox.configure(values=[str(match.workspace_path) for match in matches])

    def _select_existing(self) -> None:
        """Browse an existing workspace folder and verify its PLC identity."""
        session = self._app._session
        if session is None:
            return
        window = session.setup_window
        plc_name = self._ensure_plc_name()
        if plc_name is None or not self._setup_unchanged(session, window):
            return
        parent = self._setup_parent()
        pending = session.pending_workspace
        selected = filedialog.askdirectory(
            title=f"Find an existing workspace for {plc_name}",
            initialdir=pending.workspace_path.parent if pending is not None else None,
            mustexist=True,
            parent=parent,
        )
        if not selected or not self._setup_unchanged(session, window):
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
        self._set_pending(session, config)

    def _select_location(self) -> None:
        """Choose a home and preview the PLC-named workspace destination."""
        session = self._app._session
        if session is None:
            return
        window = session.setup_window
        plc_name = self._ensure_plc_name()
        if plc_name is None or not self._setup_unchanged(session, window):
            return
        parent = self._setup_parent()
        pending = session.pending_workspace
        initial_dir = pending.workspace_path.parent if pending is not None else None
        selected = filedialog.askdirectory(
            title=f"Choose workspace home for {plc_name}",
            initialdir=initial_dir,
            mustexist=True,
            parent=parent,
        )
        if not selected or not self._setup_unchanged(session, window):
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
        self._set_pending(session, config)

    def _on_config_selected(self, _event=None) -> None:
        """Preview a known matching workspace selected by the user."""
        session = self._app._session
        if session is None:
            return
        selected = self._app.mirror_project_selection_var.get().strip()
        config = next(
            (match for match in session.pairing.matches if str(match.workspace_path) == selected),
            None,
        )
        if config is not None:
            self._set_pending(session, config)

    def _apply_setup(self) -> None:
        """Make the selected durable directory the active project workspace."""
        app = self._app
        dialog_parent = self._setup_parent()
        session = app._project_session()
        if session is None:
            app._update_status("Connect to a CLICK project first", "error")
            return
        window = session.setup_window
        config = session.pending_workspace
        if config is None:
            messagebox.showinfo(
                "Workspace",
                "Choose an existing workspace or select a home for a new one.",
                parent=dialog_parent,
            )
            return
        mirror_path = config.workspace_path.resolve()
        source = self.source_dir()
        changing_location = source is not None and source.resolve() != mirror_path
        # Refuse before asking for a PLC name, because the name is written into CLICK's folder.
        build_error = self.earlier_save_build_error()
        if build_error is not None and changing_location:
            messagebox.showerror(
                "Setup Workspace",
                "The workspace could not be built from CLICK's last save, so ClickNick "
                "will not copy an earlier save's workspace.\n\n" + build_error,
                parent=dialog_parent,
            )
            return
        plc_name = self._ensure_plc_name()
        if plc_name is None:
            app._update_status("Connect to a CLICK project first", "error")
            return
        if not self._setup_unchanged(session, window):
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
            app._update_status(f"Workspace setup failed: {exc}", "error")
            return
        current_mirror = session.pairing.config.workspace_path if session.pairing.config else None
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
            if not confirmed or not self._setup_unchanged(session, window):
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
            remember_project_sidecar(save_project_workspace_config(config), preferred_for=plc_name)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Setup Workspace", str(exc), parent=dialog_parent)
            app._update_status(f"Workspace setup failed: {exc}", "error")
            return

        app.mirror_project_selection_var.set(str(mirror_path.resolve()))
        app.mirror_location_selection_var.set("")
        app.workspace_setup_action_var.set("Use Workspace")
        session.use_workspace(config)
        session.record_rung_stage(0)
        app._request_ui_refresh()
        app._update_status(f"Workspace configured: {mirror_path}", "connected")
        app._start_analysis_build()

    def close_setup_window(self) -> None:
        """Close Workspace setup, dropping the choice not applied yet."""
        session = self._app._session
        if session is not None:
            session.close_setup_window()

    def _create_setup_contents(self, parent) -> None:
        """Create task-oriented controls for using or creating a workspace."""
        app = self._app
        summary = ttk.LabelFrame(parent, text="Workspace", padding=8)
        ttk.Label(
            summary,
            textvariable=app.mirror_setup_status_var,
            style="Connected.TLabel",
        ).pack(anchor=tk.W)
        plc_row = ttk.Frame(summary)
        ttk.Label(plc_row, text="PLC name").pack(side=tk.LEFT)
        ttk.Label(plc_row, textvariable=app.plc_name_var, style="Status.TLabel").pack(
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
        self._config_combobox = ttk.Combobox(
            existing_row,
            textvariable=app.mirror_project_selection_var,
            state="readonly",
            values=[str(match.workspace_path) for match in self.pairing.matches],
        )
        self._config_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._config_combobox.bind("<<ComboboxSelected>>", self._on_config_selected)
        ttk.Button(
            existing_row,
            text="Find Existing...",
            command=self._select_existing,
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
            textvariable=app.mirror_location_selection_var,
            state="readonly",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            new_row,
            text="Choose Location...",
            command=self._select_location,
        ).pack(side=tk.LEFT, padx=(8, 0))
        new_row.pack(fill=tk.X)
        new.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(
            parent,
            textvariable=app.mirror_detail_var,
            style="Error.TLabel",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, fill=tk.X, pady=(0, 8))

        buttons = ttk.Frame(parent)
        ttk.Button(
            buttons,
            textvariable=app.workspace_setup_action_var,
            command=self._apply_setup,
        ).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.close_setup_window).pack(side=tk.RIGHT)
        buttons.pack(fill=tk.X)

    def open_setup_window(self) -> None:
        """Show workspace details before offering setup or reconfiguration.

        The window belongs to the connected session and closes with it.
        """
        app = self._app
        session = app._session
        if session is not None and session.setup_window is not None:
            try:
                session.setup_window.lift()
                session.setup_window.focus_force()
                return
            except tk.TclError:
                session.setup_window = None

        if self._ensure_plc_name() is None:
            return
        # A PLC name comes from the connected window's Project.ini
        session = app._session
        if session is None:
            return

        config = session.pairing.config
        session.pending_workspace = config
        app.mirror_project_selection_var.set(str(config.workspace_path) if config else "")
        app.mirror_location_selection_var.set("")
        app.workspace_setup_action_var.set("Use Workspace" if config else "Create Workspace")
        window = tk.Toplevel(app.root)
        window.title("Workspace")
        window.transient(app.root)
        window.minsize(640, 0)
        window.protocol("WM_DELETE_WINDOW", self.close_setup_window)
        contents = ttk.Frame(window, padding=12)
        self._create_setup_contents(contents)
        contents.pack(fill=tk.BOTH, expand=True)
        session.setup_window = window
        app._request_ui_refresh()
