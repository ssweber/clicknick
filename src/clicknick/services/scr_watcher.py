"""Watch Scr*.tmp files for changes and trigger analysis rebuild."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..utils.scheduling import Scheduler

SCR_WATCH_INTERVAL_MS = 3000


class ScrWatcher:
    """Monitors a folder's Scr*.tmp files and fires a callback on change.

    Uses the same tkinter.after() polling as FileMonitor. Any change to the
    set of Scr*.tmp files, or to one file's mtime or size, counts as a save,
    including an earlier mtime (a copied-back file or a clock step).
    """

    def _snapshot(self) -> frozenset[tuple[str, int, int]]:
        files: set[tuple[str, int, int]] = set()
        for path in self._folder.glob("Scr*.tmp"):
            try:
                stat = path.stat()
            except OSError:
                continue
            files.add((path.name.casefold(), stat.st_mtime_ns, stat.st_size))
        return frozenset(files)

    def __init__(
        self,
        scr_folder: Path,
        on_changed: Callable[[], None],
        on_sync_status_changed: Callable[[int], None] | None = None,
    ) -> None:
        self._folder = scr_folder
        self._on_changed = on_changed
        self._on_sync_status_changed = on_sync_status_changed
        # Addresses synced into CLICK's database since CLICK last saved. A set,
        # so syncing the same tag twice still counts it once.
        self._synced_keys: set[int] = set()
        self._staged_rungs: int = 0
        self._last_snapshot = self._snapshot()
        self._after_id: str | None = None
        self._active = False
        self._tk_root: Scheduler | None = None

    @property
    def synced_pending(self) -> int:
        return len(self._synced_keys)

    @property
    def staged_rungs(self) -> int:
        return self._staged_rungs

    def record_sync(self, addr_keys: Iterable[int]) -> None:
        before = len(self._synced_keys)
        self._synced_keys.update(addr_keys)
        if len(self._synced_keys) != before and self._on_sync_status_changed:
            self._on_sync_status_changed(self.synced_pending)

    def record_rung_stage(self, count: int) -> None:
        """Record how many proposed rungs differ from the saved CLICK project."""
        self._staged_rungs = max(0, count)

    def _schedule(self) -> None:
        if self._active and self._tk_root:
            self._after_id = self._tk_root.after(SCR_WATCH_INTERVAL_MS, self._check)

    def start(self, tk_root: Scheduler) -> None:
        if self._active:
            return
        self._tk_root = tk_root
        self._active = True
        self._schedule()

    def stop(self) -> None:
        self._active = False
        if self._after_id and self._tk_root:
            try:
                self._tk_root.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = None

    def _check(self) -> None:
        if not self._active:
            return
        try:
            current = self._snapshot()
            # No Scr*.tmp left is not a save: there is nothing to read.
            if current and current != self._last_snapshot:
                self._last_snapshot = current
                self._on_changed()
                self._synced_keys.clear()
                self._staged_rungs = 0
                if self._on_sync_status_changed:
                    self._on_sync_status_changed(self.synced_pending)
        except Exception:
            pass
        self._schedule()
