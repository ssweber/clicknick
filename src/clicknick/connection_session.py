"""Connection session: owns all resources scoped to a Click project connection.

Created on connect, replaced on project-change, destroyed on disconnect.
Provides orderly teardown in the correct dependency order.
"""

from __future__ import annotations

import threading
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
        on_sync_status_changed: Callable[[int], None] | None = None,
    ) -> None:
        self.pid = pid
        self.hwnd = hwnd
        self.filename = filename
        self.store = store

        self.analysis: AnalysisService | None = None
        self.scr_watcher: ScrWatcher | None = None
        self.dataview: SharedDataviewData | None = None
        self.console: Any | None = None

        self._on_sync_status_changed = on_sync_status_changed

    @property
    def synced_pending(self) -> int:
        return self.scr_watcher.synced_pending if self.scr_watcher else 0

    def record_sync(self, count: int) -> None:
        if self.scr_watcher is not None:
            self.scr_watcher.record_sync(count)

    def _on_scr_changed(self, scr_folder: Path, db_path: str) -> None:
        """Rebuild analysis when Scr*.tmp files change."""
        if self.analysis is None:
            return
        store = self.store
        analysis = self.analysis

        def _rebuild() -> None:
            try:
                persist = scr_folder / "pyrung_project"
                analysis.build(scr_folder, Path(db_path), store.base_state, persist_dir=persist)
            except Exception:
                pass

        threading.Thread(target=_rebuild, daemon=True).start()

    # -- Analysis and ScrWatcher -------------------------------------------

    def start_analysis(self, root: tk.Tk) -> None:
        """Build program analysis in background and start ScrWatcher."""
        from .services.analysis_service import AnalysisService
        from .services.scr_watcher import ScrWatcher
        from .utils.mdb_shared import find_click_database

        db_path = find_click_database(click_hwnd=self.hwnd)
        if not db_path:
            return
        scr_folder = Path(db_path).parent

        if not list(scr_folder.glob("Scr*.tmp")):
            return

        if self.analysis is None:
            self.analysis = AnalysisService()

        store = self.store
        analysis = self.analysis

        def _build() -> None:
            try:
                persist = scr_folder / "pyrung_project"
                analysis.build(scr_folder, Path(db_path), store.base_state, persist_dir=persist)
            except Exception:
                pass

        threading.Thread(target=_build, daemon=True).start()

        if self.scr_watcher is not None:
            self.scr_watcher.stop()
        self.scr_watcher = ScrWatcher(
            scr_folder,
            lambda: self._on_scr_changed(scr_folder, db_path),
            on_sync_status_changed=self._on_sync_status_changed,
        )
        self.scr_watcher.start(root)

    # -- Store replacement -------------------------------------------------

    def replace_store(self, new_store: AddressStore, root: tk.Tk) -> None:
        """Swap the data store (e.g., CSV load while connected)."""
        self.store.stop_file_monitoring()
        self.store = new_store
        self.store.start_file_monitoring(root)

    # -- Private helpers ---------------------------------------------------

    def _close_console(self) -> None:
        if self.console is not None:
            try:
                self.console._on_close()
            except Exception:
                pass
            self.console = None

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
