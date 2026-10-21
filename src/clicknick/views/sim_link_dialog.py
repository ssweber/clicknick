"""Link dialog: wire a simulator input to the tag that drives it, on the bench.

A bool input (X) follows its enable after an on/off delay, or pulses while it
is on. An analog input (DF) ramps or approaches a target while it is on. A bit
enable (Y, C...) drives the link while it is ON or while it is OFF; a word
enable (DS...) while it equals a value. The result is a BenchLink; the
Simulator window hands it to the session.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import messagebox, ttk

from pyclickplc.addresses import normalize_address

from ..services.link_annotation import (
    PROFILE_PARAMS,
    bit_enable,
    profile_token,
    split_profile,
)
from ..services.sim_state import BenchLink

#: Responses offered for each kind of input: (value, label, first field, second field).
_BOOL_RESPONSES = (
    ("delay", "Delay", "On delay", "Off delay"),
    ("pulse", "Pulse while on", "On for", "Off for"),
)
_ANALOG_RESPONSES = (
    ("ramp", "Ramp", "Up per second", "Down per second"),
    ("approach", "Approach", "Toward (value or tag)", "Rate per second"),
)
_DEFAULTS = {
    "delay": ("500ms", "200ms"),
    "pulse": ("500ms", "500ms"),
    "ramp": ("1.0", "-0.5"),
    "approach": ("100", "0.3"),
}


def _trigger(text: str) -> int | str | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


class LinkDialog(tk.Toplevel):
    """Asks which tag drives *feedback* and how it responds."""

    def _labels(self) -> tuple[str, str]:
        for value, _label, first, second in self._responses:
            if value == self._kind_var.get():
                return first, second
        return "", ""

    def _on_kind_changed(self, *, reset: bool = True) -> None:
        first, second = self._labels()
        self._first_label.configure(text=first)
        self._second_label.configure(text=second)
        if reset:
            self._first_var.set(_DEFAULTS[self._kind_var.get()][0])
            self._second_var.set(_DEFAULTS[self._kind_var.get()][1])

    def _on_enable_changed(self) -> None:
        """ON / OFF for a bit enable, a value to match for a word."""
        bit = bit_enable(self._enable_var.get().strip())
        shown, hidden = (
            (self._when_bit, self._when_word) if bit else (self._when_word, self._when_bit)
        )
        hidden.grid_forget()
        shown.grid(row=1, column=1, sticky="w", pady=2)
        self._when_label.configure(text="When it is" if bit else "When it equals")

    def _accept(self) -> None:
        try:
            link = self.build()
        except ValueError as exc:
            messagebox.showerror("Link", str(exc), parent=self)
            return
        self.destroy()
        self._on_ok(link)

    def __init__(
        self,
        parent: tk.Misc,
        *,
        feedback: str,
        analog: bool,
        current: BenchLink | None,
        enables: Sequence[str],
        on_ok: Callable[[BenchLink], None],
        enable: str | None = None,
    ) -> None:
        """*enable* pre-fills the driver (an output dragged onto the input)."""
        super().__init__(parent)
        self.title(f"Link {feedback}")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self._on_ok = on_ok
        self._responses = _ANALOG_RESPONSES if analog else _BOOL_RESPONSES

        kind = "delay"
        first, second = "", ""
        if current is not None and current.profile is not None:
            kind, values = split_profile(current.profile)
            if kind:
                a, b = PROFILE_PARAMS[kind]
                first, second = values.get(a, ""), values.get(b, "")
        elif current is not None:
            first, second = current.on_delay or "", current.off_delay or ""
        if kind not in {value for value, *_ in self._responses}:
            kind = self._responses[0][0]
            first, second = _DEFAULTS[kind]
        if current is None:
            first, second = _DEFAULTS[kind]

        self._enable_var = tk.StringVar(value=enable or (current.enable or "" if current else ""))
        trigger = current.trigger if current is not None else None
        self._trigger_var = tk.StringVar(value="" if trigger is None else str(trigger))
        # A bit enable is only ON or OFF: trigger 0 drives the link while it is OFF.
        self._when_on = tk.BooleanVar(value=trigger != 0)
        self._kind_var = tk.StringVar(value=kind)
        self._first_var = tk.StringVar(value=first)
        self._second_var = tk.StringVar(value=second)

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Driven by").grid(row=0, column=0, sticky="w", pady=2)
        enable_box = ttk.Combobox(
            body, textvariable=self._enable_var, values=list(enables), width=14
        )
        enable_box.grid(row=0, column=1, sticky="we", pady=2)
        self._when_label = ttk.Label(body)
        self._when_label.grid(row=1, column=0, sticky="w", pady=2)
        # Two forms of the same row; _on_enable_changed shows the one that fits.
        self._when_bit = ttk.Frame(body)
        for text, value in (("ON", True), ("OFF", False)):
            ttk.Radiobutton(self._when_bit, text=text, value=value, variable=self._when_on).pack(
                side=tk.LEFT, padx=(0, 12)
            )
        self._when_word = ttk.Frame(body)
        ttk.Entry(self._when_word, textvariable=self._trigger_var, width=10).pack(side=tk.LEFT)
        ttk.Label(self._when_word, text="(blank: whenever it is not 0)", foreground="gray").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self._enable_var.trace_add("write", lambda *_a: self._on_enable_changed())
        self._on_enable_changed()

        kinds = ttk.Frame(body)
        kinds.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 2))
        for value, label, *_ in self._responses:
            ttk.Radiobutton(
                kinds, text=label, value=value, variable=self._kind_var,
                command=self._on_kind_changed,
            ).pack(side=tk.LEFT, padx=(0, 12))  # fmt: skip

        self._first_label = ttk.Label(body)
        self._first_label.grid(row=3, column=0, sticky="w", pady=2)
        first_entry = ttk.Entry(body, textvariable=self._first_var, width=12)
        first_entry.grid(row=3, column=1, sticky="w", pady=2)
        self._second_label = ttk.Label(body)
        self._second_label.grid(row=4, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=self._second_var, width=12).grid(
            row=4, column=1, sticky="w", pady=2
        )
        ttk.Label(
            body,
            text="This changes the simulation only. Save it to the project from the right-click menu.",
            foreground="gray",
            wraplength=280,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Link", command=self._accept).pack(side=tk.RIGHT, padx=(0, 6))
        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())

        self._on_kind_changed(reset=False)
        if enable:
            first_entry.focus_set()
            first_entry.select_range(0, tk.END)
        else:
            enable_box.focus_set()
        self.grab_set()

    def build(self) -> BenchLink:
        """The link the form describes; ValueError explains what is missing."""
        enable = normalize_address(self._enable_var.get().strip())
        if enable is None:
            raise ValueError("Enter the CLICK address that drives this input, such as Y001.")
        kind = self._kind_var.get()
        first, second = self._first_var.get().strip(), self._second_var.get().strip()
        if bit_enable(enable):
            trigger = None if self._when_on.get() else 0
        else:
            trigger = _trigger(self._trigger_var.get())
        if kind == "delay":
            if not first and not second:
                raise ValueError("Enter an on delay, an off delay, or both.")
            return BenchLink(enable, trigger, on_delay=first or None, off_delay=second or None)
        if not first or not second:
            raise ValueError("Enter both values.")
        if kind in ("ramp", "approach"):
            numbers = (second,) if kind == "approach" else (first, second)
            try:
                for number in numbers:
                    float(number)
            except ValueError:
                raise ValueError("Rates must be numbers.") from None
        return BenchLink(enable, trigger, profile=profile_token(kind, first, second))
