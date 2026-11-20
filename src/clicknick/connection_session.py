"""Define the session that owns the resources bound to a connected CLICK project.

ClickNick creates the session on connect, before CLICK's database loads. It replaces the
session on a project change and closes it on disconnect. The address data itself lives in
DataSession.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .utils.click_temp import scr_files
from .utils.mdb_shared import database_access_off

if TYPE_CHECKING:
    import tkinter as tk
    from collections.abc import Callable

    from .ladder.program import LegacyEncoding
    from .services.analysis_service import AnalysisService
    from .services.program_check_selection import DroppedChecks
    from .services.scr_watcher import ScrWatcher
    from .services.workspace_mirror import ProjectWorkspaceConfig, WorkspacePairing
    from .simulation_session import SimulationSession

# A temporary workspace lives in CLICK's temporary folder for the window. When that window
# opens another project, the new session builds into the same folder, and the last build of
# the closed session may still be writing there. This lock makes the builds of all sessions
# run one at a time.
_BUILD_GATE = threading.Lock()

# What to do when a command needs a CLICK window and none is connected
CONNECT_FIRST = "Connect to a CLICK window first"


# The advice added when a command needs only nicknames, which a CSV file can also give
_OR_CSV = ", or use File > Load Nicknames from CSV"
_USE_CSV = ". Use File > Load Nicknames from CSV"


def no_database_reason(session: ConnectionSession | None, *, nicknames_needed: bool = False) -> str:
    """Say why ClickNick has not read CLICK's database for *session*, and what to do.

    *session* is the connected window's session, or None when no window is connected. With
    *nicknames_needed*, the command needs only nicknames, so the text also offers a CSV file
    when the database cannot be loaded now. The text has no final period, so that the status
    line can show it as it is.
    """
    if session is None:
        return CONNECT_FIRST
    if session.reading_database:
        return "ClickNick is still reading CLICK's database. Try again when it has finished"
    if database_access_off():
        return (
            "Database access is off, because CLICKNICK_DB_BACKEND is set to none (CSV mode)"
            f"{_USE_CSV if nicknames_needed else ''}"
        )
    # The load failed or was cancelled, or the user loaded a CSV file instead. Picking the
    # window again connects to it and loads its database.
    return (
        "ClickNick has not loaded CLICK's database for this project. Select the window in the "
        f"CLICK Windows list to load it{_OR_CSV if nicknames_needed else ''}"
    )


def no_workspace_reason(session: ConnectionSession | None) -> str:
    """Say why *session* has no workspace that a command can use, and what to do.

    *session* is the connected window's session, or None when no window is connected. The
    text is one or more sentences, for a message box or a reply to ``clicknick-cli``.
    """
    from .services.analysis_service import AnalysisStatus

    if session is None or not session.has_database:
        return f"{no_database_reason(session)}."
    analysis = session.analysis
    status = analysis.status if analysis is not None else None
    if status is AnalysisStatus.FAILED:
        if analysis.error:
            return f"Could not build the workspace: {analysis.error}"
        return "Could not build the workspace."
    if status is AnalysisStatus.BUILDING:
        return "ClickNick is still building the workspace. Try again when it finishes."
    return (
        "ClickNick has not started building the workspace. Save the project in CLICK, "
        "then try again."
    )


# The reason a session builds nothing before ClickNick has read CLICK's database (has_database)
NO_DATABASE = (
    "ClickNick has not read this project's database, SC_.mdb, so it cannot build the "
    "workspace. The build reads the nicknames from that database."
)


@dataclass(frozen=True)
class SavedProgram:
    """Where to read the program that CLICK last saved, as CSVs to compare with, at one moment.

    If this value differs from the one read before, a comparison made earlier may be out of
    date.
    """

    # A different session is a different project. This is None when nothing is connected
    # or ClickNick has not read the connected project's database.
    session: ConnectionSession | None = None
    generation: int = 0
    # The number of saves that CLICK made in this session, as the ScrWatcher saw them. Only a
    # CLICK save raises this count. Nothing that ClickNick does, such as a Sync, a Reload or
    # a retry, raises it.
    save_count: int = 0
    building: bool = False
    csv_dir: Path | None = None
    # The reason there is no csv_dir to compare with.
    note: str = "Connect to CLICK to see which programs changed"


@dataclass(frozen=True)
class ClickConnection:
    """The CLICK window ClickNick is attached to.

    This class is immutable. A project change produces a new value instead of editing
    fields, so nothing can hold a half-updated connection.
    """

    pid: str
    hwnd: int
    filename: str

    @property
    def project_name(self) -> str:
        """Return the project filename without its .ckp extension."""
        return self.filename.removesuffix(".ckp")


@dataclass
class _BuildRequest:
    scr_folder: Path
    db_path: Path
    callbacks: list[tuple[tk.Tk | None, Callable[[bool, str | None], None]]] = field(
        default_factory=list
    )
    # The count that AnalysisService.mark_building returned when this request was made. The
    # build for this request answers every request made up to and including this one.
    serves: int = 0


class ConnectionSession:
    """Owns the resources whose lifetime is bounded by a CLICK project connection.

    Resources managed (in teardown order):
    1. The database load in flight
    2. The connection watch (every 100 ms) and the autocomplete popup
    3. Workspace setup window (with its unapplied choice) and Simulator window
       (with its console)
    4. SimulationSession (pyrung DAP subprocess, its Modbus server and client)
    5. ScrWatcher (file polling)
    6. AnalysisService (its result is invalidated)
    """

    def __init__(
        self,
        click: ClickConnection,
        *,
        has_database: bool = False,
        on_sync_status_changed: Callable[[int], None] | None = None,
        on_build_finished: Callable[[], None] | None = None,
    ) -> None:
        # The connected window, for the session's lifetime. A project change replaces the
        # session.
        self.click = click
        # Whether ClickNick read CLICK's database for this project. A session opens before the
        # database loads. This stays False if there is no database backend or the load fails,
        # and ClickNick then falls back to CSV. The analysis reads SC_.mdb through ODBC or Jet,
        # so nothing is built until the database is read. Nothing that needs a build starts
        # either, such as the simulation or the comparison in Review Changes.
        self.has_database = has_database
        from .services.workspace_mirror import WorkspacePairing

        # The durable workspace that builds write to, if one is paired. load_workspace_pairing
        # and use_workspace set it.
        self.pairing: WorkspacePairing = WorkspacePairing()

        # The autocomplete popup over CLICK's instruction dialog, once one showed
        self.overlay: Any | None = None
        # The Workspace setup window, while it is open, and the workspace chosen
        # in it and not applied yet
        self.setup_window: Any | None = None
        self.pending_workspace: ProjectWorkspaceConfig | None = None
        self.analysis: AnalysisService | None = None
        self.scr_watcher: ScrWatcher | None = None
        self.simulator: Any | None = None
        self.simulation: SimulationSession | None = None

        self._on_sync_status_changed = on_sync_status_changed
        # Called on the build worker's thread, not the Tk thread.
        self._on_build_finished = on_build_finished
        # Legacy encodings in CLICK's last save that the user has been told about
        self._legacy_reported: frozenset[tuple[str, str, str]] = frozenset()
        # Rule names that builds removed from saved check selections, not yet reported
        self._dropped_checks: list[DroppedChecks] = []
        self._save_count = 0

        # One build worker. Requests made while it runs merge into the next build.
        self._build_lock = threading.Lock()
        self._build_running = False
        self._next_build: _BuildRequest | None = None
        self._closed = False
        # The token of the database load in flight, from begin_load. It is None once the load
        # is cancelled.
        self._load_token: object | None = None
        # Whether a database load started and has not returned yet. end_load and cancel_load
        # clear it.
        self._reading = False
        # The scheduler that the connection watch runs on, and the id of its next tick.
        # watch() sets them.
        self._watch_scheduler: tk.Misc | None = None
        self._watch_id: str | None = None

    # -- Database load -----------------------------------------------------

    def begin_load(self) -> object:
        """Record that a database load is starting, and return its token.

        Use the load's result only while ``loads(token)`` returns True.
        """
        self._load_token = token = object()
        self._reading = True
        return token

    def end_load(self) -> None:
        """Record that the database load returned, whether or not it read the database."""
        self._reading = False

    @property
    def reading_database(self) -> bool:
        """Whether ClickNick is still reading CLICK's database for this session."""
        return self._reading and not self._closed

    def loads(self, token: object) -> bool:
        """Return whether the load that *token* names is still wanted.

        A load is wanted if it is not cancelled and the session is open.
        """
        return not self._closed and self._load_token is token

    def cancel_load(self) -> None:
        """Drop the database load in flight. Its result will not be used."""
        self._load_token = None
        self._reading = False

    # -- Connection watch --------------------------------------------------

    def watch(self, scheduler: tk.Misc, tick: Callable[[], None]) -> None:
        """Run *tick* now and every 100 ms after, until the session closes.

        A session has one watch. If you call this again while the watch runs, nothing happens.
        """
        if self._closed or self._watch_scheduler is not None:
            return
        self._watch_scheduler = scheduler
        self._watch_tick(tick)

    def _watch_tick(self, tick: Callable[[], None]) -> None:
        self._watch_id = None
        try:
            tick()
        finally:
            # A tick that closed the session was the last one. That happens when CLICK's
            # window closed or shows another project.
            if not self._closed:
                assert self._watch_scheduler is not None
                self._watch_id = self._watch_scheduler.after(100, lambda: self._watch_tick(tick))

    def _stop_watch(self) -> None:
        if self._watch_id is not None and self._watch_scheduler is not None:
            self._watch_scheduler.after_cancel(self._watch_id)
        self._watch_id = None

    def hide_overlay(self) -> None:
        """Withdraw and destroy the autocomplete popup. The next popup is a new one."""
        overlay, self.overlay = self.overlay, None
        if overlay is not None:
            overlay.withdraw()
            overlay.destroy()

    @property
    def has_unapplied_choice(self) -> bool:
        """True while the open Workspace setup window holds a choice that differs from the pairing.

        The window starts with the paired workspace as its choice, and that one is applied.
        """
        return (
            self.setup_window is not None
            and self.pending_workspace is not None
            and self.pending_workspace != self.pairing.config
        )

    def close_setup_window(self) -> None:
        """Close the Workspace setup window, dropping the choice not applied yet."""
        window, self.setup_window = self.setup_window, None
        self.pending_workspace = None
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    # -- Workspace pairing -------------------------------------------------

    @property
    def workspace_dir(self) -> Path | None:
        """Return the paired durable workspace that builds write to, or None for a temporary one."""
        config = self.pairing.config
        return config.workspace_path.resolve() if config is not None else None

    def plc_name(self) -> str | None:
        """Return CLICK's PLC name for the project from Project.ini.

        Return None when the project has no PLC name, or when Project.ini cannot be read or is
        not valid INI.
        """
        from pyclickplc.project import read_plc_name

        try:
            return read_plc_name(self.project_ini)
        except (OSError, ValueError):
            return None

    def load_workspace_pairing(self) -> None:
        """Pair the user's preferred workspace for the project's PLC name."""
        from .services.workspace_mirror import pair_workspace

        self.pairing = pair_workspace(self.plc_name())

    @property
    def synced_pending(self) -> int:
        return self.scr_watcher.synced_pending if self.scr_watcher else 0

    @property
    def staged_rungs(self) -> int:
        return self.scr_watcher.staged_rungs if self.scr_watcher else 0

    def record_sync(self, addr_keys: set[int]) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.record_sync(addr_keys)

    def record_rung_stage(self, count: int) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.record_rung_stage(count)

    def _run_build(self, request: _BuildRequest) -> None:
        from .services.analysis_service import AnalysisStatus

        analysis = self.analysis
        assert analysis is not None
        # Read the workspace once. Workspace setup may pair another workspace on the Tk thread
        # while this build runs.
        workspace_dir = self.workspace_dir
        persistent_workspace = workspace_dir is not None
        persist = workspace_dir or (request.scr_folder / "pyrung_project")

        error: str | None = None
        try:
            from .services.program_check_selection import ProgramCheckSelection

            selection = ProgramCheckSelection(workspace_dir)
            analysis.check_selection = selection
            with _BUILD_GATE:
                # If the session closed while this build waited for the lock, build nothing.
                # The session that replaced this one owns the folder.
                published = not self._closed and analysis.build(
                    request.scr_folder,
                    request.db_path,
                    persist_dir=persist,
                    workspace_kind="persistent" if persistent_workspace else "temporary",
                    serves=request.serves,
                )
                if published:
                    try:
                        selection.sync(persist)
                    except Exception:
                        # The build has already stored its result and written the
                        # workspace, so it does not fail here. Check Program reports a
                        # pyproject.toml that cannot be read when it runs the checks.
                        traceback.print_exc()
                    # The next build replaces analysis.check_selection, maybe before the
                    # app reports these names. So the session keeps them.
                    with self._build_lock:
                        self._dropped_checks.extend(selection.take_dropped())
            if not published:
                error = (
                    "The project or its workspace changed while ClickNick was building the "
                    "workspace. ClickNick dropped that build."
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            # The build failed before build() ran, so nothing else ends the "building" status.
            # The only exception is a build that was queued after this one.
            if analysis.status is AnalysisStatus.BUILDING:
                analysis.mark_failed(error, traceback.format_exc(), serves=request.serves)

        for root, on_complete in request.callbacks:
            if root is None:
                on_complete(error is None, error)
            else:
                root.after(0, lambda cb=on_complete: cb(error is None, error))
        if self._on_build_finished is not None:
            self._on_build_finished()

    def _run_builds(self) -> None:
        while True:
            with self._build_lock:
                request = self._next_build
                self._next_build = None
                if request is None:
                    self._build_running = False
                    return
            self._run_build(request)

    def _start_analysis_thread(
        self,
        scr_folder: Path,
        db_path: Path,
        *,
        root: tk.Tk | None = None,
        on_complete: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Queue an analysis build and optionally report completion on the Tk thread.

        One worker thread runs builds one at a time, so two builds never write the same
        project folder. Requests made while a build runs merge into a single follow-up build
        of the latest inputs. Every caller's on_complete receives the result of the build
        that served it.
        """
        analysis = self.analysis
        assert analysis is not None
        serves = analysis.mark_building()
        with self._build_lock:
            pending = self._next_build
            callbacks = pending.callbacks if pending is not None else []
            if on_complete is not None:
                callbacks.append((root, on_complete))
            self._next_build = _BuildRequest(scr_folder, db_path, callbacks, serves)
            if self._build_running:
                return
            self._build_running = True
        threading.Thread(target=self._run_builds, daemon=True).start()

    # -- Simulation --------------------------------------------------------

    @property
    def project_ini(self) -> Path:
        """Return CLICK's Project.ini for the connected window (hardware and PLC name)."""
        from .utils.click_temp import click_temp_dir

        return click_temp_dir(self.click.hwnd) / "Project.ini"

    def _simulation_key(self) -> str:
        """Return the PLC name that simulator settings are saved under, else the project's name."""
        return self.plc_name() or self.click.project_name

    def ensure_simulation(
        self, scheduler: tk.Misc, *, on_retry_analysis: Callable[[], None] | None = None
    ) -> SimulationSession:
        """Return the one simulation for this connection, creating it on first use."""
        if self.simulation is None:
            from .simulation_session import SimulationSession

            self.simulation = SimulationSession(
                scheduler=scheduler,
                get_analysis=lambda: self.analysis,
                get_project_ini=lambda: self.project_ini,
                session_name=f"clicknick-{self.click.filename}-{self.click.hwnd}",
                on_retry_analysis=on_retry_analysis,
                get_save_count=lambda: self._save_count,
            )
            self.simulation.set_state_location(self._simulation_key(), self.workspace_dir)
        return self.simulation

    # -- Private helpers ---------------------------------------------------

    def _close_windows(self) -> None:
        self.close_setup_window()
        window = self.simulator
        if window is not None:
            try:
                window._on_close()
            except Exception:
                pass
            self.simulator = None

    def use_workspace(self, config: ProjectWorkspaceConfig) -> None:
        """Pair the durable workspace *config* for future analysis builds and simulator settings.

        A running simulation relaunches from the new workspace once its analysis rebuild
        finishes.
        """
        from .services.workspace_mirror import WorkspacePairing

        known = [
            match for match in self.pairing.matches if match.sidecar_path != config.sidecar_path
        ]
        self.pairing = WorkspacePairing(config, [*known, config])
        if self.analysis is not None:
            self.analysis.invalidate()
        if self.simulation is not None:
            self.simulation.set_state_location(self._simulation_key(), self.workspace_dir)
            self.simulation.relaunch()

    def _analysis_paths(self) -> tuple[Path, Path] | None:
        """Resolve the saved CLICK inputs needed to regenerate the workspace."""
        from .services.analysis_service import AnalysisService
        from .utils.mdb_shared import find_click_database

        if self.analysis is None:
            self.analysis = AnalysisService()

        db_value = find_click_database(click_hwnd=self.click.hwnd)
        if not db_value:
            self.analysis.mark_failed(
                "Could not find the database, SC_.mdb, of the connected CLICK project."
            )
            return None

        db_path = Path(db_value)
        scr_folder = db_path.parent
        if not scr_files(scr_folder):
            self.analysis.mark_failed(
                "The project folder has no Scr*.tmp ladder files. Save the project in CLICK first."
            )
            return None
        return scr_folder, db_path

    def _on_scr_changed(self) -> None:
        """Count a CLICK save and rebuild analysis from it."""
        self._save_count += 1
        paths = self._analysis_paths()
        if paths is not None:
            self._start_analysis_thread(*paths)

    def saved_program(self) -> SavedProgram:
        """Return where the program CLICK last saved can be read as CSVs, right now."""
        from .services.analysis_service import AnalysisStatus

        if not self.has_database:
            return SavedProgram(note=no_database_reason(self))
        reading = "Reading CLICK's program…"
        saves = self._save_count
        analysis = self.analysis
        if analysis is None:
            return SavedProgram(self, save_count=saves, note=reading)
        generation = analysis.generation
        status = analysis.status
        # The status is BUILDING also while a build queued after a save waits for the build
        # before it to finish.
        if status is AnalysisStatus.BUILDING:
            return SavedProgram(self, generation, saves, building=True, note=reading)
        # If a build failed before it stored its result, project_dir still holds the
        # workspace of an earlier save.
        project_dir = analysis.project_dir if analysis.project_is_current else None
        csv_dir = project_dir / "csv" if project_dir is not None else None
        if csv_dir is not None and csv_dir.is_dir():
            return SavedProgram(self, generation, saves, csv_dir=csv_dir, note="")
        if status is AnalysisStatus.FAILED:
            return SavedProgram(
                self,
                generation,
                saves,
                note="Could not build the workspace. Help > About CLICK Project shows why.",
            )
        return SavedProgram(self, generation, saves, note=reading)

    def legacy_encodings_to_report(self) -> tuple[LegacyEncoding, ...]:
        """Return every legacy encoding in CLICK's last save, if it has one not reported yet.

        Return an empty result when nothing new turned up, so pasting a fix and saving does
        not report the rest again. Each finding is keyed by its program, instruction and
        token, not by its rung number. Pasting rungs above a finding changes its rung number,
        and that does not make it a new finding.
        """
        from .ladder.program import read_legacy_encodings

        csv_dir = self.saved_program().csv_dir
        if csv_dir is None:
            return ()
        found = read_legacy_encodings(csv_dir)
        keys = frozenset((item.file.casefold(), item.instruction, item.token) for item in found)
        new = keys - self._legacy_reported
        self._legacy_reported = keys
        return found if new else ()

    def dropped_checks_to_report(self) -> tuple[DroppedChecks, ...]:
        """Return the rule names removed from saved check selections, each one only once.

        A build, Check Program or Choose Checks removes a name that pyrung does not know
        when it reads the selection.
        """
        with self._build_lock:
            found, self._dropped_checks = tuple(self._dropped_checks), []
        selection = self.analysis.check_selection if self.analysis is not None else None
        return found + (selection.take_dropped() if selection is not None else ())

    def reload_workspace_from_click(
        self,
        root: tk.Tk,
        on_complete: Callable[[bool, str | None], None] | None = None,
    ) -> bool:
        """Explicitly regenerate the workspace from the saved CLICK project."""
        if not self.has_database:
            if on_complete is not None:
                root.after(0, lambda: on_complete(False, NO_DATABASE))
            return False
        paths = self._analysis_paths()
        if paths is None:
            if on_complete is not None:
                error = self.analysis.error if self.analysis is not None else None
                root.after(0, lambda: on_complete(False, error))
            return False
        self._start_analysis_thread(*paths, root=root, on_complete=on_complete)
        return True

    # -- Analysis and ScrWatcher -------------------------------------------

    def start_analysis(self, root: tk.Tk) -> None:
        """Build program analysis in the background and watch CLICK's saves.

        If a build is already running, start no other, because that build answers this
        request. The session makes the
        ScrWatcher once, because it counts what was synced since CLICK last saved. Nothing
        starts before ClickNick has read CLICK's database (``has_database``).
        """
        from .services.analysis_service import AnalysisStatus
        from .services.scr_watcher import ScrWatcher
        from .utils.click_temp import click_temp_dir

        if not self.has_database:
            return
        paths = None
        if self.analysis is None or self.analysis.status is not AnalysisStatus.BUILDING:
            paths = self._analysis_paths()
            if paths is not None:
                self._start_analysis_thread(*paths)

        if self.scr_watcher is not None:
            # A ScrWatcher made before CLICK's database was found may watch another folder.
            # Point it at the database's folder.
            if paths is not None:
                self.scr_watcher.watch(paths[0])
            return
        # Watch even with nothing to build yet. CLICK may still be writing the project it is
        # opening, and the build must follow once it has finished.
        self.scr_watcher = ScrWatcher(
            paths[0] if paths is not None else click_temp_dir(self.click.hwnd),
            self._on_scr_changed,
            on_sync_status_changed=self._on_sync_status_changed,
        )
        self.scr_watcher.start(root)

    def _stop_watchers(self) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.stop()
            self.scr_watcher = None
        if self.analysis is not None:
            self.analysis.invalidate()

    # -- Teardown ----------------------------------------------------------

    def close(self) -> None:
        """Drop the database load, stop watching the window, hide the popup,
        close the simulation windows, and stop simulating, watching and analysing."""
        self._closed = True
        self._load_token = None
        self._stop_watch()
        self.hide_overlay()
        self._close_windows()
        if self.simulation is not None:
            self.simulation.close()
            self.simulation = None
        self._stop_watchers()
