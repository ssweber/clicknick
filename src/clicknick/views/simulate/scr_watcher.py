"""Watches Scr*.tmp files for changes and triggers rebuild."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path

POLL_INTERVAL_MS = 2000
DEBOUNCE_MS = 1000


class ScrFileWatcher:
    """Polls ``Scr*.tmp`` mtimes and fires *on_change* when they change.

    Uses ``tk.after`` scheduling — must be started/stopped from the Tk thread.
    """

    def __init__(self, scr_folder: Path, root: tk.Misc, on_change: Callable[[], None]) -> None:
        self._folder = scr_folder
        self._root = root
        self._on_change = on_change
        self._mtimes: dict[str, float] = {}
        self._poll_id: str | None = None
        self._debounce_id: str | None = None

    def _snapshot(self) -> None:
        self._mtimes = {}
        for p in self._folder.glob("Scr*.tmp"):
            try:
                self._mtimes[p.name] = p.stat().st_mtime
            except OSError:
                pass

    def _schedule_poll(self) -> None:
        self._poll_id = self._root.after(POLL_INTERVAL_MS, self._poll)

    def start(self) -> None:
        self._snapshot()
        self._schedule_poll()

    def stop(self) -> None:
        if self._poll_id is not None:
            try:
                self._root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        if self._debounce_id is not None:
            try:
                self._root.after_cancel(self._debounce_id)
            except Exception:
                pass
            self._debounce_id = None

    def _has_changed(self) -> bool:
        current: dict[str, float] = {}
        for p in self._folder.glob("Scr*.tmp"):
            try:
                current[p.name] = p.stat().st_mtime
            except OSError:
                pass
        return current != self._mtimes

    def _fire(self) -> None:
        self._debounce_id = None
        self._snapshot()
        self._on_change()
        self._schedule_poll()

    def _poll(self) -> None:
        if self._has_changed():
            if self._debounce_id is not None:
                try:
                    self._root.after_cancel(self._debounce_id)
                except Exception:
                    pass
            self._debounce_id = self._root.after(DEBOUNCE_MS, self._fire)
        else:
            self._schedule_poll()
