"""Floating history window that docks to the right of the dataview editor."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

from .history_panel import HistoryPanel


class HistoryWindow(tk.Toplevel):
    """Dockable window wrapping HistoryPanel, following the NavWindow pattern."""

    def _dock_to_parent(self) -> None:
        if not self._snap_var.get():
            return

        self._parent_window.update_idletasks()
        px = self._parent_window.winfo_x()
        py = self._parent_window.winfo_y()
        pw = self._parent_window.winfo_width()
        ph = self._parent_window.winfo_height()

        target_x = px + pw + 20
        target_y = py

        current_w = self.winfo_width()
        if current_w < 50:
            current_w = 420

        self.geometry(f"{current_w}x{ph}+{target_x}+{target_y}")

    def _on_parent_configure(self, event: Any) -> None:
        if self._snap_var.get() and event.widget == self._parent_window:
            self.after_idle(self._dock_to_parent)

    def _on_self_configure(self, event: Any) -> None:
        if not self._snap_var.get():
            return
        if not self._parent_window or not self.winfo_exists():
            return

        target_x = self._parent_window.winfo_x() + self._parent_window.winfo_width() + 20
        target_y = self._parent_window.winfo_y()

        if self.winfo_x() != target_x or self.winfo_y() != target_y:
            self.geometry(f"+{target_x}+{target_y}")

    def _toggle_snap(self) -> None:
        if self._snap_var.get():
            self._snap_btn.configure(text="\U0001f4cc")
            self._dock_to_parent()
        else:
            self._snap_btn.configure(text="\U0001f517")

    def _on_close(self) -> None:
        self.withdraw()

    def __init__(
        self,
        parent: tk.Toplevel,
        *,
        nickname_provider: Callable[[str], Any],
        on_watch_add: Callable[[str], None],
        on_watch_remove: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self._parent_window = parent
        self.title("Simulation History")
        self.resizable(True, True)
        self.transient(parent)

        self._snap_var = tk.BooleanVar(value=True)

        self.panel = HistoryPanel(
            self,
            nickname_provider=nickname_provider,
            on_watch_add=on_watch_add,
            on_watch_remove=on_watch_remove,
        )
        self.panel.pack(fill=tk.BOTH, expand=True)

        from tkinter import ttk

        self._snap_btn = ttk.Checkbutton(
            self,
            text="\U0001f4cc",
            variable=self._snap_var,
            command=self._toggle_snap,
            style="Toolbutton",
            width=2,
        )
        self._snap_btn.place(relx=1.0, y=1, x=-25, anchor="ne")

        self._dock_to_parent()
        parent.bind("<Configure>", self._on_parent_configure, add=True)
        self.bind("<Configure>", self._on_self_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
