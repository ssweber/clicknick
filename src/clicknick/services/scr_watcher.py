"""Watch Scr*.tmp files for changes and trigger analysis rebuild."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from ..utils.click_temp import scr_files

if TYPE_CHECKING:
    from ..utils.scheduling import Scheduler

SCR_WATCH_INTERVAL_MS = 3000
# After a change, the watcher checks this often until the files stop changing.
SCR_SETTLE_MS = 500
# A save counts once this many settle checks in a row find the files unchanged (about 1 s).
# A pause that CLICK makes between two Scr*.tmp writes is then not a save.
SCR_QUIET_CHECKS = 2


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


class ScrWatcher:
    """Monitors a folder's Scr*.tmp files and fires a callback on change.

    Uses the same tkinter.after() polling as FileMonitor. A save is any change to the set of
    Scr*.tmp files, or to one file's mtime or size. An earlier mtime counts too, for example
    a copied-back file or a clock step. After a change, the watcher checks again every
    SCR_SETTLE_MS. It fires once SCR_QUIET_CHECKS of those checks in a row find the files
    the same. A save that was caught half written is therefore one save, not two.
    """

    def _snapshot(self) -> frozenset[tuple[str, int, int]]:
        files: set[tuple[str, int, int]] = set()
        for path in scr_files(self._folder):
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
        # Addresses synced into CLICK's database since CLICK last saved. This is a set, so syncing
        # the same tag twice counts it once.
        self._synced_keys: set[int] = set()
        self._staged_rungs: int = 0
        self._last_snapshot = self._snapshot()
        # A change seen at the last check. It does not count until it holds for one more check.
        self._settling: frozenset[tuple[str, int, int]] | None = None
        # The number of checks in a row that found _settling unchanged.
        self._quiet_checks = 0
        self._after_id: str | None = None
        self._active = False
        self._tk_root: Scheduler | None = None

    @property
    def synced_pending(self) -> int:
        return len(self._synced_keys)

    @property
    def staged_rungs(self) -> int:
        return self._staged_rungs

    @property
    def folder(self) -> Path:
        return self._folder

    def watch(self, scr_folder: Path) -> None:
        """Watch another folder from now on, keeping the synced and staged counts.

        If you pass the same folder spelled another way, such as a short 8.3 name or `..`,
        the watcher keeps its snapshot. A save that CLICK made since the last check then
        still counts.
        """
        if _resolved(scr_folder) != _resolved(self._folder):
            self._folder = scr_folder
            self._last_snapshot = self._snapshot()
            self._settling = None

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
            delay = SCR_WATCH_INTERVAL_MS if self._settling is None else SCR_SETTLE_MS
            self._after_id = self._tk_root.after(delay, self._check)

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
            if not current or current == self._last_snapshot:
                self._settling = None
            elif current != self._settling:
                self._settling = current  # CLICK may still be writing
                self._quiet_checks = 0
            elif self._quiet_checks + 1 < SCR_QUIET_CHECKS:
                self._quiet_checks += 1
            else:
                self._last_snapshot = current
                self._settling = None
                self._on_changed()
                self._synced_keys.clear()
                self._staged_rungs = 0
                if self._on_sync_status_changed:
                    self._on_sync_status_changed(self.synced_pending)
        except Exception:
            pass
        self._schedule()
