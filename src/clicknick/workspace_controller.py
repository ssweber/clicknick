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
    """The parts of the app (``ClickNickApp``) that WorkspaceController uses."""

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

    def _report_no_project_session(self) -> None: ...

    def _update_status(self, message: str, style: str = "normal") -> None: ...

    def _request_ui_refresh(self) -> None: ...

    def _start_analysis_build(self) -> None: ...

    def _close_workspace_reviews(self) -> None: ...


class WorkspaceController:
    """The connected project's workspace, as the main window shows and changes it."""

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

    def refused_for_earlier_save(self, mirror_path: Path) -> str | None:
        """Return the build error that makes `_apply_setup` refuse a move to *mirror_path*.

        Return None when `_apply_setup` does not refuse. It refuses when the build of CLICK's
        last save failed and the workspace would move to another folder.
        """
        source = self.source_dir()
        if source is None or source.resolve() == mirror_path.resolve():
            return None
        return self.earlier_save_build_error()

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
        if app._project_session() is None:
            app._report_no_project_session()
            return
        if app._live_server is None:
            return

        try:
            app._live_server.dispatch_now("rung apply")
        except Exception as exc:
            messagebox.showerror(
                "Review Changes", f"Could not open Review Changes: {exc}", parent=app.root
            )
            app._update_status("Could not open Review Changes", "error")
            return

        status = self.status()
        if status.changed_rungs:
            app._update_status(f"Reviewing {status.label}", "connected")
        else:
            app._update_status("No changed rungs to review", "connected")

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
        message = error or "ClickNick could not reload the workspace from CLICK."
        messagebox.showerror("Reload from CLICK", message, parent=app.root)
        app._update_status("Reload from CLICK failed", "error")
        app._request_ui_refresh()

    def reload_from_click(self) -> None:
        """Explicitly replace active workspace source from the saved CLICK project."""
        app = self._app
        session = app._project_session()
        if session is None:
            app._report_no_project_session()
            return

        from .services.workspace_service import WorkspaceState

        if self.status().state is WorkspaceState.PREPARING:
            app._update_status(
                "ClickNick is still building the workspace. Try again when it finishes.", "error"
            )
            return

        confirmed = messagebox.askokcancel(
            "Reload from CLICK",
            "Reload the workspace from the saved CLICK project?\n\n"
            "This replaces the program in the workspace's src\\plc folder with the program "
            "that CLICK last saved. If you edited src\\plc, ClickNick first copies your "
            "version to backup\\src\\plc in the workspace.",
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
            messagebox.showerror(title, f"Could not open {path}: {exc}", parent=self._app.root)

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
        """Return the project's PLC name.

        If the project has none, prompt for one and write it to Project.ini. If the project
        has a name, also write it where CLICK 4 reads it (``_show_plc_name_in_click``).
        Return None if the user cancels the prompt or the project closes. If the project has
        no name, also return None when ClickNick has not read CLICK's database or cannot
        write the name. The status line then says why.
        """
        plc_name = self.plc_name()
        if plc_name:
            self._show_plc_name_in_click(plc_name)
            return plc_name

        from pyclickplc.project import write_plc_name
        from pyclickplc.validation import validate_click_name

        app = self._app
        session = app._project_session()
        if session is None:
            app._report_no_project_session()
            return None

        window = session.setup_window
        parent = self._setup_parent()
        while True:
            # Check before each prompt too, because the error box before it is a dialog.
            if not self._setup_unchanged(session, window):
                return None
            value = simpledialog.askstring(
                "Name PLC",
                "This project needs a PLC name before ClickNick can set up a workspace "
                "folder for it.\n\nEnter a name of up to 24 characters:",
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
                write_plc_name(session.project_ini, plc_name)
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

    def _show_plc_name_in_click(self, plc_name: str) -> None:
        """Write *plc_name* to Project.ini where CLICK shows it, if it is not there yet.

        ClickNick 0.24.1 wrote the name of a new CLICK 4 project to ``[PLCName]``. CLICK 4
        ignores that section and shows ``[Sec20] Key1``. ``write_plc_name`` writes the name
        to ``[Sec20] Key1`` and leaves ``[PLCName]`` as it was. It leaves the file alone when
        ``[Sec20]`` already holds the name. If the write fails, the status line reports it
        and Workspace setup goes on. ClickNick already has the name that it needs.

        The method writes nothing if ``validate_click_name`` rejects the name. ClickNick
        never wrote such a name, and ``write_plc_name`` would raise ``ValueError`` for it.
        """
        from pyclickplc.project import write_plc_name
        from pyclickplc.validation import validate_click_name

        app = self._app
        session = app._project_session()
        if session is None or not validate_click_name(plc_name)[0]:
            return
        try:
            write_plc_name(session.project_ini, plc_name)
        except (OSError, ValueError) as exc:
            reason = str(exc).rstrip()
            if not reason.endswith("."):
                reason += "."
            app._update_status(
                f"Could not write the PLC name to Project.ini: {reason} CLICK may show no "
                "name. Enter the name in CLICK's System Configuration.",
                "error",
            )

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

    @staticmethod
    def _asks_about_folder(session: ConnectionSession, mirror_path: Path) -> bool:
        """Return True when `_apply_setup` must ask before it uses the files already in *mirror_path*.

        That happens when the folder holds files and is not the paired workspace. Raise
        OSError when the folder cannot be listed.
        """
        if not (mirror_path.exists() and any(mirror_path.iterdir())):
            return False
        current = session.pairing.config
        return current is None or mirror_path.resolve() != current.workspace_path.resolve()

    def _offer_to_apply(
        self, session: ConnectionSession, window, config: ProjectWorkspaceConfig
    ) -> None:
        """Ask whether to apply the choice that a folder picker just returned.

        Yes does what the Create Workspace or Use Workspace button does. No leaves the choice
        in the form. If *config* is the paired workspace and its `.clicknick.toml` still exists,
        this method asks nothing and applies nothing. If the folder already contains files, or
        cannot be listed, or `_apply_setup` will refuse because of the earlier save's build
        error, this method asks nothing and calls `_apply_setup`, which asks about the files or
        shows the refusal or the error.
        """
        if config == session.pairing.config and config.sidecar_path.is_file():
            return
        parent = self._setup_parent()
        mirror_path = config.workspace_path.resolve()
        refused = self.refused_for_earlier_save(mirror_path) is not None
        try:
            asks_about_folder = self._asks_about_folder(session, mirror_path)
        except OSError:
            asks_about_folder = True
        if not (refused or asks_about_folder):
            if config.sidecar_path.is_file():
                question = f"Use the workspace at {config.workspace_path}?"
            else:
                question = f"Create the {config.plc_name} workspace at {config.workspace_path}?"
            if not messagebox.askyesno("Workspace", question, parent=parent):
                return
            if not self._setup_unchanged(session, window):
                return
        self._apply_setup()

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
            messagebox.showerror("Workspace", str(exc), parent=parent)
            return
        if config.plc_name.casefold() != plc_name.casefold():
            messagebox.showerror(
                "Workspace",
                f'The workspace you chose belongs to PLC "{config.plc_name}", not "{plc_name}". '
                f'Choose a workspace for "{plc_name}".',
                parent=parent,
            )
            return
        self._set_pending(session, config)
        self._offer_to_apply(session, window, config)

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
            title=f"Choose a location for the {plc_name} workspace",
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
                messagebox.showerror("Workspace", str(exc), parent=parent)
                return
        else:
            config = ProjectWorkspaceConfig(
                plc_name=plc_name,
                workspace_path=workspace_path,
            )
        self._set_pending(session, config)
        self._offer_to_apply(session, window, config)

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
            app._report_no_project_session()
            return
        window = session.setup_window
        config = session.pending_workspace
        if config is None:
            messagebox.showinfo(
                "Workspace",
                "Choose an existing workspace, or click Choose Location... to create a new one.",
                parent=dialog_parent,
            )
            return
        mirror_path = config.workspace_path.resolve()
        source = self.source_dir()
        changing_location = source is not None and source.resolve() != mirror_path
        # Refuse before asking for a PLC name, because the name is written into CLICK's folder.
        build_error = self.refused_for_earlier_save(mirror_path)
        if build_error is not None:
            messagebox.showerror(
                "Workspace",
                "Could not build the workspace from CLICK's last save. ClickNick will not copy "
                "the workspace of an earlier save into the new folder.\n\n"
                + build_error
                + "\n\nFix the error and save the project in CLICK. Then try again once the "
                "workspace builds.",
                parent=dialog_parent,
            )
            return
        # If _ensure_plc_name returns None, the user cancelled the prompt or the project
        # closed, or the method has already shown why in the status line.
        plc_name = self._ensure_plc_name()
        if plc_name is None:
            return
        if not self._setup_unchanged(session, window):
            return
        if config.plc_name.casefold() != plc_name.casefold():
            messagebox.showerror(
                "Workspace",
                f'The workspace you chose belongs to PLC "{config.plc_name}", not "{plc_name}". '
                f'Choose a workspace for "{plc_name}".',
                parent=dialog_parent,
            )
            return

        try:
            asks_about_folder = self._asks_about_folder(session, mirror_path)
        except OSError as exc:
            messagebox.showerror(
                "Workspace", f"Could not set up the workspace: {exc}", parent=dialog_parent
            )
            app._update_status("Could not set up the workspace", "error")
            return
        if asks_about_folder:
            if config.sidecar_path.is_file():
                heading = f"Use the workspace at {mirror_path}?"
            else:
                heading = f"Use the existing folder?\n\n{mirror_path}"
            confirmed = messagebox.askokcancel(
                "Use Existing Workspace Folder?",
                f"{heading}\n\n"
                "ClickNick will replace the files in src/plc and csv, and the files "
                "nicknames.csv, project_to_csv.py and run.py. It will not delete other files, "
                "and it will not replace your tests, documentation or editor settings. If you "
                "edited src/plc there, ClickNick first copies it to backup/src/plc.",
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
            messagebox.showerror(
                "Workspace", f"Could not set up the workspace: {exc}", parent=dialog_parent
            )
            app._update_status("Could not set up the workspace", "error")
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
