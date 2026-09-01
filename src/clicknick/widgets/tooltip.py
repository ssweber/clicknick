"""Reusable hover-tooltip binding for tkinter widgets."""

from __future__ import annotations

import tkinter as tk


def bind_tooltip(widget: tk.Widget, text: str) -> None:
    """Bind a hover tooltip to a widget."""
    tip: tk.Toplevel | None = None

    def show(event: tk.Event) -> None:
        nonlocal tip
        if tip is not None:
            return
        tip = tk.Toplevel(widget)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.attributes("-disabled", True)
        label = tk.Label(
            tip,
            text=text,
            bg="#ffffe0",
            fg="black",
            font=("Segoe UI", 9),
            justify="left",
            wraplength=350,
            padx=6,
            pady=3,
        )
        label.pack()
        tip.update_idletasks()
        x = event.x_root + 12
        y = event.y_root + 12
        screen_w = widget.winfo_screenwidth()
        screen_h = widget.winfo_screenheight()
        if x + tip.winfo_reqwidth() > screen_w:
            x = screen_w - tip.winfo_reqwidth() - 4
        if y + tip.winfo_reqheight() > screen_h:
            y = event.y_root - tip.winfo_reqheight() - 4
        tip.geometry(f"+{x}+{y}")

    def hide(_: tk.Event) -> None:
        nonlocal tip
        if tip is not None:
            tip.destroy()
            tip = None

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")
