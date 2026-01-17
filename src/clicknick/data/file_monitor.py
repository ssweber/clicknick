"""File monitoring for detecting external changes to data files."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

# File monitoring interval in milliseconds
FILE_MONITOR_INTERVAL_MS = 2000


class FileMonitor:
    """Monitors a file for modifications and calls a callback when changed.

    Uses tkinter's after() for scheduling to stay on the main thread.
    This is important because the callback typically modifies shared state.

    Usage:
        monitor = FileMonitor(
            file_path="/path/to/file.mdb",
            on_modified=self._reload_from_source
        )
        monitor.start(tk_root)
        # ... later ...
        monitor.stop()
    """

    def __init__(self, file_path: str | None, on_modified: Callable[[], None]) -> None:
        """Initialize the file monitor.

        Args:
            file_path: Path to the file to monitor (can be None for no monitoring)
            on_modified: Callback to invoke when file modification is detected
        """
        self._file_path = file_path
        self._on_modified = on_modified
        self._last_mtime: float = 0.0
        self._after_id: str | None = None
        self._active = False
        self._tk_root: tk.Tk | None = None

        # Capture initial mtime if file exists
        if self._file_path and os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

    @property
    def file_path(self) -> str | None:
        """The file path being monitored."""
        return self._file_path

    @property
    def is_active(self) -> bool:
        """Whether monitoring is currently active."""
        return self._active

    def update_mtime(self) -> None:
        """Update the stored mtime to current file mtime.

        Call this after saving changes to prevent false modification detection.
        """
        if self._file_path and os.path.exists(self._file_path):
            self._last_mtime = os.path.getmtime(self._file_path)

    def _schedule_check(self) -> None:
        """Schedule the next file modification check."""
        if not self._active or not self._tk_root:
            return
        self._after_id = self._tk_root.after(FILE_MONITOR_INTERVAL_MS, self._check_modified)

    def start(self, tk_root: tk.Tk) -> None:
        """Start monitoring the file for changes.

        Args:
            tk_root: Tkinter root window (needed for after() scheduling)
        """
        if self._active:
            return

        if not self._file_path:
            return  # Nothing to monitor

        self._tk_root = tk_root
        self._active = True
        self._schedule_check()

    def stop(self) -> None:
        """Stop file monitoring."""
        self._active = False
        if self._after_id and self._tk_root:
            try:
                self._tk_root.after_cancel(self._after_id)
            except Exception:
                pass  # Widget may be destroyed
        self._after_id = None

    def _check_modified(self) -> None:
        """Check if the file has been modified and invoke callback if so."""
        if not self._active:
            return

        try:
            if self._file_path and os.path.exists(self._file_path):
                current_mtime = os.path.getmtime(self._file_path)
                if current_mtime > self._last_mtime:
                    self._last_mtime = current_mtime
                    self._on_modified()
        except Exception:
            # File might be locked during write, skip this check
            pass

        # Schedule next check
        self._schedule_check()
