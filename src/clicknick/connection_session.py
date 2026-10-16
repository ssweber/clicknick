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

if TYPE_CHECKING:
    import tkinter as tk
    from collections.abc import Callable

    from .services.analysis_service import AnalysisService
    from .services.scr_watcher import ScrWatcher


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


class ConnectionSession:
    """Owns the resources whose lifetime is bounded by a CLICK project connection.

    Resources managed (in teardown order):
    1. Console window (DAP subprocess)
    2. ScrWatcher (file polling)
    3. AnalysisService (stale graph)
    """

    def __init__(
        self,
        click: ClickConnection,
        *,
        workspace_dir: Path | None = None,
        on_sync_status_changed: Callable[[int], None] | None = None,
    ) -> None:
        self.click = click
        self.workspace_dir = workspace_dir.resolve() if workspace_dir is not None else None

        self.analysis: AnalysisService | None = None
        self.scr_watcher: ScrWatcher | None = None
        self.console: Any | None = None

        self._on_sync_status_changed = on_sync_status_changed

        # One build worker: requests made while it runs collapse into the next build.
        self._build_lock = threading.Lock()
        self._build_running = False
        self._next_build: _BuildRequest | None = None

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
        from .services.program_check_selection import ProgramCheckSelection

        analysis = self.analysis
        assert analysis is not None
        persistent_workspace = self.workspace_dir is not None
        persist = self.workspace_dir or (request.scr_folder / "pyrung_project")
        selection = ProgramCheckSelection(self.workspace_dir)
        analysis.check_selection = selection

        error: str | None = None
        try:
            published = analysis.build(
                request.scr_folder,
                request.db_path,
                persist_dir=persist,
                workspace_kind="persistent" if persistent_workspace else "temporary",
            )
            if published:
                selection.sync(persist)
            else:
                error = "The project changed while converting; conversion was discarded."
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        for root, on_complete in request.callbacks:
            if root is None:
                on_complete(error is None, error)
            else:
                root.after(0, lambda cb=on_complete: cb(error is None, error))

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
        with self._build_lock:
            pending = self._next_build
            callbacks = pending.callbacks if pending is not None else []
            if on_complete is not None:
                callbacks.append((root, on_complete))
            self._next_build = _BuildRequest(scr_folder, db_path, callbacks)
            if self._build_running:
                return
            self._build_running = True
        threading.Thread(target=self._run_builds, daemon=True).start()

    # -- Private helpers ---------------------------------------------------

    def _close_console(self) -> None:
        if self.console is not None:
            try:
                self.console._on_close()
            except Exception:
                pass
            self.console = None

    def use_workspace(self, workspace_dir: Path) -> None:
        """Move future analysis builds to one configured durable workspace."""
        self._close_console()
        self.workspace_dir = workspace_dir.resolve()
        if self.analysis is not None:
            self.analysis.invalidate()

    def _on_scr_changed(self, scr_folder: Path, db_path: str) -> None:
        """Rebuild analysis when Scr*.tmp files change."""
        if self.analysis is None:
            return
        self._start_analysis_thread(scr_folder, Path(db_path))

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
        if not list(scr_folder.glob("Scr*.tmp")):
            self.analysis.mark_failed(
                "No saved ladder files (Scr*.tmp) in the project folder. "
                "Save the project in Click Software first."
            )
            return None
        return scr_folder, db_path

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
        """Build program analysis in background and start ScrWatcher."""
        from .services.scr_watcher import ScrWatcher

        paths = self._analysis_paths()
        if paths is None:
            return
        scr_folder, db_path = paths
        self._start_analysis_thread(scr_folder, db_path)

        if self.scr_watcher is not None:
            self.scr_watcher.stop()
        self.scr_watcher = ScrWatcher(
            scr_folder,
            lambda: self._on_scr_changed(scr_folder, str(db_path)),
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
        """Close the console and stop watching and analysing the project."""
        self._close_console()
        self._stop_watchers()
