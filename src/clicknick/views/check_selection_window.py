"""Rule selection backed by pyrung's registry and project configuration."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from pyrung.core.validation.config import CheckConfig
from pyrung.core.validation.registry import default_on_rules, ordered_rules

from ..services.program_check_selection import ProgramCheckSelection, update_selection


class CheckSelectionWindow:
    def __init__(
        self, parent: tk.Misc, selection: ProgramCheckSelection, on_saved: Callable[[], None]
    ) -> None:
        config = selection.load()
        selected = config.resolve()
        self.window = tk.Toplevel(parent)
        self.window.title("Choose Checks")
        self.window.geometry("780x650")
        self.window.transient(parent)
        self.window.bind("<Escape>", lambda _e: self.window.destroy())
        specs = ordered_rules()
        main = ttk.Frame(self.window, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            main,
            text="Choose which checks run. Collapsing results does not change this selection.",
            wraplength=730,
        ).pack(anchor=tk.W)
        save_note = (
            "Changes are saved in this workspace's pyproject.toml."
            if selection.workspace is not None
            else "Changes become your defaults for all programs without a workspace."
        )
        ttk.Label(main, text=save_note, wraplength=730).pack(anchor=tk.W, pady=(4, 10))
        buttons = ttk.Frame(main)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        frame = ttk.Frame(main)
        frame.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(
            frame,
            columns=("enabled", "severity", "default"),
            show="tree headings",
            selectmode="browse",
        )
        for column, title, width in (
            ("#0", "Check", 440),
            ("enabled", "Run", 50),
            ("severity", "Severity", 80),
            ("default", "Core default", 85),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, stretch=column == "#0")
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        states = {spec.code: spec.code in selected for spec in specs}
        use_defaults = False

        def refresh() -> None:
            for spec in specs:
                values = (
                    "[x]" if states[spec.code] else "[ ]",
                    spec.severity,
                    "Yes" if spec.default_on else "",
                )
                if tree.exists(spec.code):
                    tree.item(spec.code, values=values)
                else:
                    tree.insert("", tk.END, iid=spec.code, text=spec.title, values=values)

        def toggle(code: str) -> str:
            nonlocal use_defaults
            if code in states:
                use_defaults = False
                states[code] = not states[code]
                refresh()
            return "break"

        def set_all(codes: frozenset[str], *, defaults: bool = False) -> None:
            nonlocal use_defaults, config
            use_defaults = defaults
            config = CheckConfig() if defaults else CheckConfig(select=("ALL",) if codes else ())
            states.update((code, code in codes) for code in states)
            refresh()

        def save() -> None:
            try:
                updated = (
                    CheckConfig()
                    if use_defaults
                    else update_selection(config, {code for code, value in states.items() if value})
                )
                selection.save(updated)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Check Settings", str(exc), parent=self.window)
                return
            self.window.destroy()
            on_saved()

        tree.bind(
            "<ButtonRelease-1>",
            lambda e: (
                toggle(tree.identify_row(e.y))
                if tree.identify_region(e.x, e.y) in {"cell", "tree"}
                else None
            ),
        )
        tree.bind("<space>", lambda _e: toggle(tree.focus()))
        tree.bind("<Return>", lambda _e: toggle(tree.focus()))
        ttk.Button(
            buttons,
            text="Core Defaults",
            command=lambda: set_all(default_on_rules(), defaults=True),
        ).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Select All", command=lambda: set_all(frozenset(states))).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(buttons, text="Select None", command=lambda: set_all(frozenset())).pack(
            side=tk.LEFT
        )
        ttk.Button(buttons, text="Save and Run", command=save).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel", command=self.window.destroy).pack(side=tk.RIGHT, padx=6)
        refresh()
