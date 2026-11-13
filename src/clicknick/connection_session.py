"""Connection session: owns the resources bound to a connected CLICK project.

Created on connect, replaced on project-change, closed on disconnect. The
address data itself lives in DataSession.
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
    from .simulation_session import SimulationSession

# A temporary workspace lives in CLICK's folder for the window, so a session opening
# another project there writes where the closed session's last build may still be
# writing. Builds of every session run one at a time.
_BUILD_GATE = threading.Lock()


@dataclass(frozen=True)
class SavedProgram:
    """The program CLICK last saved, as CSVs to compare with, at one moment.

    A value different from the last one means a comparison may be out of date.
    """

    # A different session is a different project; None when nothing is connected.
    session: ConnectionSession | None = None
    generation: int = 0
    # Saves CLICK made in this session, as the ScrWatcher saw them: the one signal
    # that CLICK saved. Nothing ClickNick does (Sync, Reload, a retry) bumps it.
    save_count: int = 0
    building: bool = False
    csv_dir: Path | None = None
    # Why there is no csv_dir to compare with.
    note: str = "Connect to CLICK to see which programs changed"


@dataclass(frozen=True)
class ClickConnection:
    """The CLICK window ClickNick is attached to.

    Immutable: a project change produces a new value rather than editing
    fields, so nothing can hold a half-updated connection.
    """

    pid: str
    hwnd: int
    filename: str

    @property
    def project_name(self) -> str:
        """The project filename without its .ckp extension."""
        return self.filename.removesuffix(".ckp")


@dataclass
class _BuildRequest:
    scr_folder: Path
    db_path: Path
    callbacks: list[tuple[tk.Tk | None, Callable[[bool, str | None], None]]] = field(
        default_factory=list
    )
    # What AnalysisService.mark_building returned for it: the build serves every
    # request made up to this one.
    serves: int = 0


class ConnectionSession:
    """Owns the resources whose lifetime is bounded by a CLICK project connection.

    Resources managed (in teardown order):
    1. Simulator window (with its console)
    2. SimulationSession (pyrung DAP subprocess, its Modbus server and client)
    3. ScrWatcher (file polling)
    4. AnalysisService (stale graph)
    """

    def __init__(
        self,
        click: ClickConnection,
        *,
        workspace_dir: Path | None = None,
        on_sync_status_changed: Callable[[int], None] | None = None,
        on_build_finished: Callable[[], None] | None = None,
    ) -> None:
        self.click = click
        self.workspace_dir = workspace_dir.resolve() if workspace_dir is not None else None

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

        # One build worker: requests made while it runs collapse into the next build.
        self._build_lock = threading.Lock()
        self._build_running = False
        self._next_build: _BuildRequest | None = None
        self._closed = False

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
        persistent_workspace = self.workspace_dir is not None
        persist = self.workspace_dir or (request.scr_folder / "pyrung_project")

        error: str | None = None
        try:
            from .services.program_check_selection import ProgramCheckSelection

            selection = ProgramCheckSelection(self.workspace_dir)
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
            # Failed before build() ran, so nothing else will end the "building" status
            # (unless a build queued since will).
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

        One worker thread runs builds one at a time, so two builds never write
        the same project folder. Requests made while a build runs collapse into
        a single follow-up build of the latest inputs; every caller's
        on_complete hears the result of the build that served it.
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
        """CLICK's Project.ini for the connected window (hardware and PLC name)."""
        from .utils.click_temp import click_temp_dir

        return click_temp_dir(self.click.hwnd) / "Project.ini"

    def _simulation_key(self) -> str:
        """The PLC name simulator settings are remembered under."""
        from .services.workspace_mirror import read_plc_name

        return read_plc_name(self.project_ini) or self.click.project_name

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
        window = self.simulator
        if window is not None:
            try:
                window._on_close()
            except Exception:
                pass
            self.simulator = None

    def use_workspace(self, workspace_dir: Path) -> None:
        """Move future analysis builds (and simulator settings) to a durable workspace.

        A running simulation relaunches from the new workspace once its
        analysis rebuild finishes.
        """
        self.workspace_dir = workspace_dir.resolve()
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
        """Where the program CLICK last saved can be read as CSVs, right now."""
        from .services.analysis_service import AnalysisStatus

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
        """Every legacy encoding in CLICK's last save, when it holds one not reported yet.

        Empty when nothing new turned up, so pasting a fix and saving does not
        report the rest again. Each finding is keyed by its program, instruction
        and token, not its rung number. Pasting rungs above it moves it, and that
        is not news.
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

        A build already under way serves the request. The ScrWatcher is made
        once per session, as it counts what was synced since CLICK last saved.
        """
        from .services.analysis_service import AnalysisStatus
        from .services.scr_watcher import ScrWatcher
        from .utils.click_temp import click_temp_dir

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
        # Watch even with nothing to build yet: CLICK may still be writing the project
        # it is opening, and the build must follow once it has.
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
        """Close the simulation windows and stop simulating, watching and analysing."""
        self._closed = True
        self._close_windows()
        if self.simulation is not None:
            self.simulation.close()
            self.simulation = None
        self._stop_watchers()
