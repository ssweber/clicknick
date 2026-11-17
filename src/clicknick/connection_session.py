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

if TYPE_CHECKING:
    import tkinter as tk
    from collections.abc import Callable

    from .ladder.program import LegacyEncoding
    from .services.analysis_service import AnalysisService
    from .services.scr_watcher import ScrWatcher
    from .services.workspace_mirror import ProjectWorkspaceConfig, WorkspacePairing
    from .simulation_session import SimulationSession

# A temporary workspace lives in CLICK's folder for the window. A session that opens another
# project there writes where the closed session's last build may still be writing. So the
# builds of every session run one at a time.
_BUILD_GATE = threading.Lock()

# The reason a session builds nothing before ClickNick has read CLICK's database (has_database)
NO_DATABASE = (
    "ClickNick has not read this project's database (SC_.mdb, through Access ODBC "
    "or Jet). A build reads CLICK's program from its Scr*.tmp files and the "
    "nicknames from that database."
)


@dataclass(frozen=True)
class SavedProgram:
    """Describe the program CLICK last saved, as CSVs to compare with, at one moment.

    If a value differs from the last one, a comparison may be out of date.
    """

    # A different session is a different project. This is None when nothing is connected
    # or ClickNick has not read the connected project's database.
    session: ConnectionSession | None = None
    generation: int = 0
    # Saves that CLICK made in this session, as the ScrWatcher saw them. This is the only
    # signal that CLICK saved. Nothing ClickNick does (Sync, Reload, a retry) raises it.
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
    # What AnalysisService.mark_building returned for it. The build serves every request
    # made up to this one.
    serves: int = 0


class ConnectionSession:
    """Own the resources whose lifetime is bounded by a CLICK project connection.

    Resources managed (in teardown order):
    1. The database load in flight
    2. The connection watch (every 100 ms) and the autocomplete popup
    3. Workspace setup window (with its unapplied choice) and Simulator window
       (with its console)
    4. SimulationSession (pyrung DAP subprocess, its Modbus server and client)
    5. ScrWatcher (file polling)
    6. AnalysisService (stale graph)
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
        # database loads. It stays without one when there is no database backend or the load
        # fails (the CSV fallback). The analysis reads SC_.mdb through ODBC or Jet, so until
        # the database is read nothing is built. Nothing that needs a build (the simulation,
        # Review Changes' comparison) starts either.
        self.has_database = has_database
        from .services.workspace_mirror import WorkspacePairing

        # The durable workspace builds use, if any (load_workspace_pairing, use_workspace)
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
        self._save_count = 0

        # One build worker. Requests made while it runs merge into the next build.
        self._build_lock = threading.Lock()
        self._build_running = False
        self._next_build: _BuildRequest | None = None
        self._closed = False
        # The database load in flight (begin_load); None once it is cancelled.
        self._load_token: object | None = None
        # The connection watch (watch): the scheduler it runs on, and its next tick
        self._watch_scheduler: tk.Misc | None = None
        self._watch_id: str | None = None

    # -- Database load -----------------------------------------------------

    def begin_load(self) -> object:
        """Record that a database load is starting. Its result counts while ``loads(token)``."""
        self._load_token = token = object()
        return token

    def loads(self, token: object) -> bool:
        """Return whether the load that *token* names is still wanted.

        A load is wanted if it is not cancelled and the session is open.
        """
        return not self._closed and self._load_token is token

    def cancel_load(self) -> None:
        """Drop the database load in flight. Its result will not be used."""
        self._load_token = None

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
        """Return CLICK's PLC name for the project from Project.ini (None without one)."""
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
        # Read once, Workspace setup may pair another workspace on the Tk thread meanwhile.
        workspace_dir = self.workspace_dir
        persistent_workspace = workspace_dir is not None
        persist = workspace_dir or (request.scr_folder / "pyrung_project")

        error: str | None = None
        try:
            from .services.program_check_selection import ProgramCheckSelection

            selection = ProgramCheckSelection(workspace_dir)
            analysis.check_selection = selection
            with _BUILD_GATE:
                # Closed while waiting: the session that replaced this one owns the folder.
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
                        # The workspace is published. A pyproject.toml that cannot be
                        # read is reported when the checks run (Check Program).
                        traceback.print_exc()
            if not published:
                error = "The project changed while converting; conversion was discarded."
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            # Failed before build() ran, so nothing else ends the "building" status. A build
            # queued since then will.
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
                "No Click project database found. Connect to a project in Click Software."
            )
            return None

        db_path = Path(db_value)
        scr_folder = db_path.parent
        if not scr_files(scr_folder):
            self.analysis.mark_failed(
                "No saved ladder files (Scr*.tmp) in the project folder. "
                "Save the project in Click Software first."
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
            return SavedProgram()
        reading = "Reading CLICK's program…"
        saves = self._save_count
        analysis = self.analysis
        if analysis is None:
            return SavedProgram(self, save_count=saves, note=reading)
        generation = analysis.generation
        status = analysis.status
        # Also while a build queued after a save waits for the one before it to finish.
        if status is AnalysisStatus.BUILDING:
            return SavedProgram(self, generation, saves, building=True, note=reading)
        # A build that failed before publishing leaves the workspace of an earlier save.
        project_dir = analysis.project_dir if analysis.project_is_current else None
        csv_dir = project_dir / "csv" if project_dir is not None else None
        if csv_dir is not None and csv_dir.is_dir():
            return SavedProgram(self, generation, saves, csv_dir=csv_dir, note="")
        if status is AnalysisStatus.FAILED:
            return SavedProgram(
                self, generation, saves, note="Could not read CLICK's program; see the main window"
            )
        return SavedProgram(self, generation, saves, note=reading)

    def legacy_encodings_to_report(self) -> tuple[LegacyEncoding, ...]:
        """Return every legacy encoding in CLICK's last save, if it has one not reported yet.

        Return an empty result when nothing new turned up, so pasting a fix and saving does
        not report the rest again. Each finding is keyed by its program, instruction and
        token, not by its rung number. Pasting rungs above it moves it, and that is not news.
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

        A build that is already under way serves the request. The session makes the
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
            # Made before CLICK's database was found, it may watch another folder.
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
