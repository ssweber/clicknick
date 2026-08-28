"""Connection session: owns all resources scoped to a Click project connection.

Created on connect, replaced on project-change, destroyed on disconnect.
Provides orderly teardown in the correct dependency order.
"""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tkinter as tk
    from collections.abc import Callable

    from .data.address_store import AddressStore
    from .data.shared_dataview import SharedDataviewData
    from .services.analysis_service import AnalysisService
    from .services.scr_watcher import ScrWatcher


class ConnectionSession:
    """Owns all resources whose lifetime is bounded by a Click project connection.

    Resources managed (in teardown order):
    1. Console window (DAP subprocess)
    2. Dataview editor (Modbus service)
    3. Address editor windows (observers, nav windows)
    4. ScrWatcher (file polling)
    5. AnalysisService (stale graph)
    6. AddressStore FileMonitor
    """

    def __init__(
        self,
        pid: int,
        hwnd: int,
        filename: str,
        store: AddressStore,
        *,
        workspace_dir: Path | None = None,
        on_sync_status_changed: Callable[[int], None] | None = None,
    ) -> None:
        self.pid = pid
        self.hwnd = hwnd
        self.filename = filename
        self.store = store
        self.workspace_dir = workspace_dir.resolve() if workspace_dir is not None else None

        self.analysis: AnalysisService | None = None
        self.scr_watcher: ScrWatcher | None = None
        self.dataview: SharedDataviewData | None = None
        self.console: Any | None = None

        self._on_sync_status_changed = on_sync_status_changed

    @property
    def synced_pending(self) -> int:
        return self.scr_watcher.synced_pending if self.scr_watcher else 0

    @property
    def staged_rungs(self) -> int:
        return self.scr_watcher.staged_rungs if self.scr_watcher else 0

    def record_sync(self, count: int) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.record_sync(count)

    def record_rung_stage(self, count: int) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.record_rung_stage(count)

    def _start_analysis_thread(
        self,
        scr_folder: Path,
        db_path: Path,
        *,
        root: tk.Tk | None = None,
        on_complete: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Build analysis and optionally report completion on the Tk thread."""
        store = self.store
        analysis = self.analysis
        assert analysis is not None
        persist = self.workspace_dir or (scr_folder / "pyrung_project")

        def _rebuild() -> None:
            error: str | None = None
            try:
                analysis.build(scr_folder, db_path, store.base_state, persist_dir=persist)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            if on_complete is not None:
                if root is None:
                    on_complete(error is None, error)
                else:
                    root.after(0, lambda: on_complete(error is None, error))

        threading.Thread(target=_rebuild, daemon=True).start()

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

        db_value = find_click_database(click_hwnd=self.hwnd)
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

    # -- Store replacement -------------------------------------------------

    def replace_store(self, new_store: AddressStore, root: tk.Tk) -> None:
        """Swap the data store (e.g., CSV load while connected)."""
        self.store.stop_file_monitoring()
        self.store = new_store
        self.store.start_file_monitoring(root)

    def _stop_watchers(self) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.stop()
            self.scr_watcher = None
        if self.analysis is not None:
            self.analysis.invalidate()

    def _disconnect_dataview(self) -> None:
        if self.dataview is not None:
            self.dataview.set_address_store(None)
            self.dataview = None

    # -- Teardown ----------------------------------------------------------

    def close(self, prompt_save: bool = True) -> bool:
        """Orderly teardown. Returns False if user cancelled a save prompt.

        Closes cancellable windows first (save prompts), then irreversible
        resources. If the user cancels a save prompt, no irreversible
        teardown has occurred yet.
        """
        if prompt_save:
            if self.dataview is not None:
                if not self.dataview.close_window(prompt_save=True):
                    return False
            if not self.store.close_all_windows(prompt_save=True):
                return False
        else:
            if self.dataview is not None:
                self.dataview.force_close_window()
            self.store.force_close_all_windows()

        self._close_console()
        self._stop_watchers()
        self._disconnect_dataview()
        return True

    def force_close(self) -> None:
        """Unconditional teardown (Click window died). No save prompts."""
        self._close_console()

        if self.dataview is not None:
            self.dataview.force_close_window()
        self.store.force_close_all_windows()

        self._stop_watchers()
        self._disconnect_dataview()

    def detach_click_resources(self) -> None:
        """Close Click-specific resources but keep data and editor windows.

        Used when the Click window dies but data is CSV-backed and still valid.
        The caller should extract session.store and session.dataview before
        discarding the session.
        """
        self._close_console()
        self._stop_watchers()
