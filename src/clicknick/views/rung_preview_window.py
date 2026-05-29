"""Rung preview window — colored diff viewer with per-group Copy to Click."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _build_paste_groups(rung_nums: list[int]) -> list[list[int]]:
    """Split sorted rung numbers into contiguous groups.

    >>> _build_paste_groups([3, 5, 6, 7, 10])
    [[3], [5, 6, 7], [10]]
    """
    if not rung_nums:
        return []
    nums = sorted(set(rung_nums))
    groups: list[list[int]] = [[nums[0]]]
    for n in nums[1:]:
        if n == groups[-1][-1] + 1:
            groups[-1].append(n)
        else:
            groups.append([n])
    return groups


def _format_group(group: list[int] | None) -> str:
    if not group:
        return ""
    if len(group) == 1:
        return f"r{group[0]}"
    return f"r{group[0]}..{group[-1]}"


def _diff_summary(diff_text: str) -> str:
    added = removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    if added == 0 and removed == 0:
        return "(no changes)"
    return f"{added} line(s) added, {removed} line(s) removed"


class RungPreviewWindow(tk.Toplevel):
    """Non-modal diff viewer for agent-proposed rung changes.

    Shows a colored unified diff of pyrung source and lets the engineer
    copy selected rung groups to the Click clipboard one contiguous block
    at a time.
    """

    # ------------------------------------------------------------------
    # Paste groups
    # ------------------------------------------------------------------

    def _current_group(self) -> list[int] | None:
        if not self._groups or self._group_idx >= len(self._groups):
            return None
        return self._groups[self._group_idx]

    def _update_status(self) -> None:
        group = self._current_group()
        if not self._groups or self._pending_dir is None:
            self._status_var.set(_diff_summary(self._diff_text))
            self._copy_btn.configure(state="disabled")
            self._next_btn.pack_forget()
            return

        label = _format_group(group) if group else "done"
        n = len(self._groups)

        if self._group_idx >= n:
            self._status_var.set(f"Done — all {n} group(s) pasted")
            self._copy_btn.configure(state="disabled")
            self._next_btn.configure(state="disabled")
            return

        prefix = f"Group {self._group_idx + 1}/{n}: {label}"
        if self._copied:
            self._status_var.set(f"{prefix} — Copied, paste in Click")
            self._copy_btn.configure(state="disabled")
            if self._group_idx < n - 1:
                self._next_btn.configure(state="normal")
        else:
            self._status_var.set(prefix)
            self._copy_btn.configure(state="normal")
            self._next_btn.configure(state="disabled")

        if n <= 1:
            self._next_btn.pack_forget()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_copy(self) -> None:
        group = self._current_group()
        if group is None or self._pending_dir is None:
            return
        try:
            from laddercodec import encode, read_csv

            from ..ladder.clipboard import copy_to_clipboard

            csv_stem = self._file_stem or "main"
            if csv_stem == "main":
                csv_path = self._pending_dir / "main.csv"
            else:
                csv_path = self._pending_dir / "subroutines" / f"{csv_stem}.csv"

            if not csv_path.is_file():
                self._status_var.set(f"Error: {csv_path.name} not found in pending/")
                return

            all_rungs = read_csv(csv_path)
            selected = [all_rungs[i - 1] for i in group if 1 <= i <= len(all_rungs)]
            if not selected:
                self._status_var.set("Error: selected rungs out of range")
                return

            payload = encode(selected) if len(selected) > 1 else encode(selected[0])

            hwnd = self._get_click_hwnd() if self._get_click_hwnd else None
            copy_to_clipboard(payload, owner_hwnd=hwnd)

            self._copied = True
            self._update_status()
        except RuntimeError as exc:
            self._status_var.set(f"Clipboard error: {exc}")
        except Exception as exc:
            self._status_var.set(f"Error: {exc}")

    def _on_next(self) -> None:
        if self._group_idx < len(self._groups) - 1:
            self._group_idx += 1
            self._copied = False
            self._update_status()

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------

    def _create_widgets(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # --- header ---
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(
            header,
            text=f"Rung Preview — {self._file_stem}",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT)
        if self._selection:
            ttk.Label(header, text=f"Selection: {self._selection}", foreground="gray").pack(
                side=tk.RIGHT
            )

        # --- diff text ---
        diff_frame = tk.Frame(main, relief=tk.SUNKEN, borderwidth=2)
        diff_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self._text = tk.Text(
            diff_frame,
            font=("Consolas", 10),
            wrap=tk.NONE,
            state=tk.DISABLED,
            background="#fafafa",
        )
        scrollbar_y = ttk.Scrollbar(diff_frame, orient=tk.VERTICAL, command=self._text.yview)
        scrollbar_x = ttk.Scrollbar(diff_frame, orient=tk.HORIZONTAL, command=self._text.xview)
        self._text.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._text.tag_configure("added", background="#d4edda")
        self._text.tag_configure("removed", background="#f8d7da")
        self._text.tag_configure("hunk", foreground="#0366d6")
        self._text.tag_configure("file_header", foreground="#6a737d", font=("Consolas", 10, "bold"))

        # --- status ---
        self._status_var = tk.StringVar(value="")
        status_frame = ttk.LabelFrame(main, text="Status", padding=5)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(status_frame, textvariable=self._status_var, foreground="gray").pack(fill=tk.X)

        # --- buttons ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="Close", command=self.destroy, width=10).pack(side=tk.RIGHT)

        self._next_btn = ttk.Button(
            btn_frame, text="Next →", command=self._on_next, width=10, state="disabled"
        )
        self._next_btn.pack(side=tk.RIGHT, padx=(5, 5))

        self._copy_btn = ttk.Button(
            btn_frame,
            text="\U0001f4cb Copy to Click",
            command=self._on_copy,
            width=16,
            state="disabled",
        )
        self._copy_btn.pack(side=tk.RIGHT)

        self.bind("<Escape>", lambda _e: self.destroy())

    def _populate_diff(self) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)

        for line in self._diff_text.splitlines(keepends=True):
            if line.startswith("---") or line.startswith("+++"):
                self._text.insert(tk.END, line, "file_header")
            elif line.startswith("@@"):
                self._text.insert(tk.END, line, "hunk")
            elif line.startswith("+"):
                self._text.insert(tk.END, line, "added")
            elif line.startswith("-"):
                self._text.insert(tk.END, line, "removed")
            else:
                self._text.insert(tk.END, line)

        self._text.configure(state=tk.DISABLED)

    def __init__(
        self,
        parent: tk.Widget,
        diff_text: str,
        *,
        file_stem: str = "main",
        selection: str | None = None,
        rung_nums: list[int] | None = None,
        pending_dir: Path | None = None,
        get_click_hwnd: Callable[[], int | None] | None = None,
        get_mdb_path: Callable[[], Path | None] | None = None,
    ):
        super().__init__(parent)
        self.title(f"Rung Preview — {file_stem}")
        self.geometry("900x600")
        self.minsize(600, 400)

        self._diff_text = diff_text
        self._file_stem = file_stem
        self._selection = selection
        self._pending_dir = pending_dir
        self._get_click_hwnd = get_click_hwnd
        self._get_mdb_path = get_mdb_path

        self._groups = _build_paste_groups(rung_nums or [])
        self._group_idx = 0
        self._copied = False

        self._create_widgets()
        self._populate_diff()
        self._update_status()
