"""Link dialog: wire a simulator input to the tag that drives it, on the bench.

An input (X) gets pyrung's bool kinds of response, and an analog input (DF) its
analog kinds. Each kind's fields, labels, hints and checks come from pyrung's
table. A bit enable (Y, C...) is a contact beside the driver: normally open [O] drives the
link while it is ON, normally closed [/] while it is OFF (``link=~Y001``). A
word enable (DS...) drives it while it equals a value. The result is a BenchLink; the
Simulator window hands it to the session.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import messagebox, ttk

from pyclickplc.addresses import normalize_address

from ..services.link_annotation import bit_enable
from ..services.physical_response import (
    PhysicalKind,
    kinds_for,
    physical_kind,
    response_kind,
    response_of,
    shown_keys,
)
from ..services.sim_state import BenchLink
from ..widgets.tooltip import bind_tooltip

#: The first grid row of the chosen kind's fields, and the row of the note below them.
_FIELDS_ROW = 3
_NOTE_ROW = 20


def _contact_style(widget: tk.Misc) -> str:
    """A ttk style for the [O][/] contact: native push buttons, the chosen one pressed in.

    Under the Windows ``vista`` theme a radio button gets the push-button
    element, drawn pressed while selected; other themes use ``Toolbutton``.
    """
    style = ttk.Style(widget)
    if style.theme_use() != "vista":
        return "Toolbutton"
    if "Contact.button" not in style.element_names():
        # Windows BUTTON part 1 states: 1 normal, 2 hot, 3 pressed, 4 disabled.
        style.element_create(
            "Contact.button", "vsapi", "BUTTON", 1,
            [("disabled", 4), ("pressed", 3), ("selected", 3), ("active", 2), ("", 1)],
        )  # fmt: skip
        style.layout(
            "Contact.TRadiobutton",
            [("Contact.button", {"sticky": "nswe", "children": style.layout("TButton")[0][1]["children"]})],
        )  # fmt: skip
        style.configure("Contact.TRadiobutton", anchor="center", padding=(6, 1))
    return "Contact.TRadiobutton"


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

    def _kind(self) -> PhysicalKind:
        return physical_kind(self._kind_var.get())

    def _on_kind_changed(self) -> None:
        """Show the chosen kind's fields. Each key keeps its own value across kinds."""
        for widget in self._field_widgets:
            widget.destroy()
        self._field_widgets = []
        self._first_entry = None
        body = self._body
        for row, key in enumerate(shown_keys(self._kind()), start=_FIELDS_ROW):
            var = self._key_vars[key.name]
            if key.is_flag:
                check = ttk.Checkbutton(body, text=key.label, variable=var)
                check.grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
                bind_tooltip(check, key.help)
                self._field_widgets.append(check)
                continue
            label = ttk.Label(body, text=key.label)
            label.grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(body, textvariable=var, width=12)
            entry.grid(row=row, column=1, sticky="w", pady=2)
            unit = ttk.Label(body, text=key.unit, foreground="gray")
            unit.grid(row=row, column=2, sticky="w", padx=(6, 0), pady=2)
            for widget in (label, entry, unit):
                bind_tooltip(widget, key.help)
            self._field_widgets += [label, entry, unit]
            if self._first_entry is None:
                self._first_entry = entry

    def _on_enable_changed(self) -> None:
        """The [O][/] contact beside a bit enable, a value to match below a word."""
        if bit_enable(self._enable_var.get().strip()):
            self._when_label.grid_remove()
            self._when_word.grid_remove()
            self._when_bit.grid(row=0, column=2, sticky="w", padx=(6, 0), pady=2)
        else:
            self._when_bit.grid_remove()
            self._when_label.grid(row=1, column=0, sticky="w", pady=2)
            self._when_word.grid(row=1, column=1, columnspan=2, sticky="w", pady=2)

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
        self._kinds = kinds_for("analog" if analog else "bool")

        # The current link's kind starts with its own values, every other kind with
        # pyrung's suggested ones.
        values = dict(current.response) if current is not None else {}
        current_kind = response_kind(current.response) if current is not None else None
        if current_kind not in self._kinds:
            current_kind, values = None, {}
        kind = current_kind or self._kinds[0]
        self._key_vars: dict[str, tk.Variable] = {}
        for each in self._kinds:
            for key in each.keys:
                if key.is_flag:
                    self._key_vars[key.name] = tk.BooleanVar(value=bool(values.get(key.name)))
                elif each is current_kind:
                    self._key_vars[key.name] = tk.StringVar(value=str(values.get(key.name, "")))
                else:
                    self._key_vars[key.name] = tk.StringVar(value=key.suggested or "")

        self._enable_var = tk.StringVar(value=enable or (current.enable or "" if current else ""))
        trigger = current.trigger if current is not None else None
        self._trigger_var = tk.StringVar(value="" if trigger is None else str(trigger))
        # A bit enable is a contact: normally open (the default) or normally closed,
        # which is trigger 0 and drives the link while the bit is OFF.
        self._when_on = tk.BooleanVar(value=trigger != 0)
        self._kind_var = tk.StringVar(value=kind.name)

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, pad=12)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Driven by").grid(row=0, column=0, sticky="w", pady=2)
        enable_box = ttk.Combobox(
            body, textvariable=self._enable_var, values=list(enables), width=14
        )
        enable_box.grid(row=0, column=1, sticky="we", pady=2)
        # _on_enable_changed shows the contact for a bit, the value row for a word.
        self._when_bit = ttk.Frame(body)
        contact_style = _contact_style(self)
        for text, value, tip in (
            ("O", True, "Normally open: drives this input while the output is ON"),
            ("/", False, "Normally closed: drives this input while the output is OFF"),
        ):
            contact = ttk.Radiobutton(
                self._when_bit, text=text, value=value, variable=self._when_on,
                style=contact_style, width=2, cursor="hand2",
            )  # fmt: skip
            contact.pack(side=tk.LEFT)
            bind_tooltip(contact, tip)
        self._when_label = ttk.Label(body, text="When it equals")
        self._when_word = ttk.Frame(body)
        ttk.Entry(self._when_word, textvariable=self._trigger_var, width=10).pack(side=tk.LEFT)
        ttk.Label(self._when_word, text="(blank: whenever it is not 0)", foreground="gray").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self._enable_var.trace_add("write", lambda *_a: self._on_enable_changed())
        self._on_enable_changed()

        kinds = ttk.Frame(body)
        kinds.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 2))
        for each in self._kinds:
            radio = ttk.Radiobutton(
                kinds, text=each.label, value=each.name, variable=self._kind_var,
                command=self._on_kind_changed,
            )  # fmt: skip
            radio.pack(side=tk.LEFT, padx=(0, 12))
            bind_tooltip(radio, each.description)

        # _on_kind_changed puts the chosen kind's fields in the rows from _FIELDS_ROW.
        self._body = body
        self._field_widgets: list[ttk.Widget] = []
        self._first_entry: ttk.Entry | None = None
        ttk.Label(
            body,
            text="This changes the simulation only. Save it to the project from the right-click menu.",
            foreground="gray",
            wraplength=280,
        ).grid(row=_NOTE_ROW, column=0, columnspan=3, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(self, padding=(12, 0, 12, 12))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Link", command=self._accept).pack(side=tk.RIGHT, padx=(0, 6))
        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())

        self._on_kind_changed()
        if enable and self._first_entry is not None:
            self._first_entry.focus_set()
            self._first_entry.select_range(0, tk.END)
        else:
            enable_box.focus_set()
        self.grab_set()

    def build(self) -> BenchLink:
        """The link the form describes; ValueError explains what is missing."""
        enable = normalize_address(self._enable_var.get().strip())
        if enable is None:
            raise ValueError("Enter the CLICK address that drives this input, such as Y001.")
        kind = self._kind()
        if bit_enable(enable):
            trigger = None if self._when_on.get() else 0
        else:
            trigger = _trigger(self._trigger_var.get())
        values: dict[str, str | bool] = {}
        for key in kind.keys:
            var = self._key_vars[key.name]
            if key.is_flag:
                # A required flag (toggle) is the kind itself.
                if key.required or var.get():
                    values[key.name] = True
                continue
            text = str(var.get()).strip()
            if not text:
                continue
            try:
                key.parse(text)
            except ValueError as exc:
                reason = str(exc).removeprefix(f"{key.name}: ")
                raise ValueError(f"{key.label}: {reason}") from None
            values[key.name] = text
        missing = [key.label.lower() for key in kind.keys if key.name in kind.missing(values)]
        if missing:
            joiner = " or " if kind.needs == "any" else " and "
            raise ValueError(f"Enter {joiner.join(missing)}.")
        return BenchLink(enable, trigger, response_of(values))
