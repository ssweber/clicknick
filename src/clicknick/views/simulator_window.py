"""Simulator window: the user's CLICK hardware, drawn as a rack of modules.

A passive view of the connection's SimulationSession. Inputs are switches
(Momentary pushbuttons or Maintained toggles, chosen by right-click), outputs
are LEDs, analog inputs take a value (and a slider when the tag has a range),
and the CPU card carries the PWR/RUN/ERR LEDs and the STOP / STEP / RUN mode
switch. Values come from the session's Modbus reads; forces, mode and speed
from its DAP frames. Every action goes through the session.

Cards are compact and flow into rows in rack order, so a full rack (CPU, two
option slots, eight expansions and the unassigned strip) fits without
horizontal scrolling.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import TYPE_CHECKING, Any

from pyclickplc.addresses import get_addr_key, parse_address

from ..simulation_session import SPEEDS, SWITCH_LABELS, SimStatus, format_speed
from ..widgets.tooltip import bind_tooltip
from . import sim_palette as P

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data.address_store import AddressStore
    from ..services.sim_hardware import Card, PanelLayout
    from ..simulation_session import SimEvent, SimulationSession, SwitchPosition

CARD_W = 184
CARD_GAP = 12
ROW_GAP = 18
MARGIN = 16
HEADER_H = 36
ROW_H = 24
ANALOG_ROW_H = 46
SECTION_H = 18
CPU_PANEL_H = 100
BADGE_W = 20
TICK_MS = 500

_FONT = ("Segoe UI", 9)
_FONT_BOLD = ("Segoe UI", 9, "bold")
_FONT_SMALL = ("Segoe UI", 8)
_FONT_MONO = ("Consolas", 9)
_FONT_TITLE = ("Segoe UI", 10, "bold")

_POSITIONS: tuple[SwitchPosition, ...] = ("stop", "step", "run")
_POSITION_COLORS = {"stop": P.MODE_STOP, "step": P.MODE_STEP, "run": P.MODE_RUN}


def _rounded_points(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
        x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]  # fmt: skip


def _round_rect(
    canvas: tk.Canvas, x0: float, y0: float, x1: float, y1: float, r: float, **kw: Any
) -> int:
    return canvas.create_polygon(_rounded_points(x0, y0, x1, y1, r), smooth=True, **kw)


def _value_text(value: object) -> str:
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, float):
        return f"{value:.6g}"
    return "" if value is None else str(value)


class SimulatorWindow(tk.Toplevel):
    """Draws the hardware panel and turns clicks into SimulationSession calls."""

    # ------------------------------------------------------------------
    # Lookups and text fitting
    # ------------------------------------------------------------------

    def _names(self, address: str) -> tuple[str, str]:
        """Nickname and comment, read live from the address data."""
        store = self._get_store()
        if store is None:
            return "", ""
        try:
            row = store.visible_state.get(get_addr_key(*parse_address(address)))
        except (KeyError, ValueError):
            return "", ""
        if row is None:
            return "", ""
        return row.nickname or "", getattr(row, "comment", "") or ""

    def _truncate(self, text: str, width: float) -> str:
        """*text* shortened with an ellipsis to fit *width* pixels in the normal font."""
        measure = self._font.measure
        if measure(text) <= width:
            return text
        ellipsis = "\N{HORIZONTAL ELLIPSIS}"
        while text and measure(text + ellipsis) > width:
            text = text[:-1]
        return text + ellipsis if text else ""

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _tooltip_item(self, items: tuple[int, ...], text: Callable[[], str]) -> None:
        """Show *text* near the pointer while it is over any of the canvas *items*."""
        c = self._canvas

        def hide(_event: object = None) -> None:
            if self._tooltip is not None:
                self._tooltip.destroy()
                self._tooltip = None

        def show(event: tk.Event) -> None:
            hide()
            content = text()
            if not content:
                return
            tip = tk.Toplevel(self)
            tip.overrideredirect(True)
            tk.Label(
                tip, text=content, bg="#ffffe0", fg="black", font=_FONT, padx=6, pady=2,
                justify=tk.LEFT, wraplength=360,
            ).pack()  # fmt: skip
            tip.geometry(f"+{event.x_root + 12}+{event.y_root + 14}")
            self._tooltip = tip

        for item in items:
            c.tag_bind(item, "<Enter>", show, add="+")
            c.tag_bind(item, "<Leave>", hide, add="+")

    def _draw_label(self, x: float, cy: float, address: str, right: float, tag: str) -> None:
        """One line: the address, then the nickname cut to end at *right*.

        Hovering shows the full nickname and the comment.
        """
        c = self._canvas
        address_item = c.create_text(
            x, cy, text=address, anchor="w", fill=P.TEXT, font=_FONT_MONO, tags=(tag,)
        )
        nickname, comment = self._names(address)
        items = [address_item]
        if nickname:
            left = c.bbox(address_item)[2] + 5
            shown = self._truncate(nickname, right - left)
            if shown:
                items.append(
                    c.create_text(
                        left, cy, text=shown, anchor="w", fill=P.TEXT, font=_FONT, tags=(tag,)
                    )
                )
        if nickname or comment:
            tip = "\n".join(part for part in (nickname, comment) if part)
            self._tooltip_item(tuple(items), lambda: tip)

    def _draw_badge(self, cx: float, cy: float, tag: str = "") -> tuple[int, ...]:
        """A small padlock, shown while the address is forced."""
        c = self._canvas
        tags = (tag,) if tag else ()
        shackle = c.create_arc(
            cx - 4, cy - 9, cx + 4, cy - 1, start=0, extent=180, style="arc",
            outline=P.FORCED, width=2, state="hidden", tags=tags,
        )  # fmt: skip
        body = c.create_rectangle(
            cx - 6, cy - 4, cx + 6, cy + 6, fill=P.FORCED, outline="", state="hidden", tags=tags
        )
        self._tooltip_item((shackle, body), lambda: "Forced. Right-click to release.")
        return (shackle, body)

    def _row_target(
        self, x: float, y: float, tag: str, menu: Callable[[tk.Event], None], height: float = ROW_H
    ) -> None:
        """A face-colored strip under the row, so a right-click anywhere on it opens *menu*.

        Drawn before the row's own items; an unfilled rectangle would only
        respond on its outline.
        """
        c = self._canvas
        c.create_rectangle(
            x + 3, y, x + CARD_W - 3, y + height, fill=P.CARD_FACE, outline="", tags=(tag,)
        )
        c.tag_bind(tag, "<Button-3>", menu)

    def _draw_card_frame(
        self, x: float, y: float, height: float, title: str, subtitle: str, *, dashed: bool = False
    ) -> None:
        c = self._canvas
        _round_rect(
            c, x, y, x + CARD_W, y + height, 9,
            fill=P.CARD_FACE, outline=P.CARD_EDGE, width=2, dash=(4, 3) if dashed else (),
        )  # fmt: skip
        _round_rect(c, x, y, x + CARD_W, y + HEADER_H, 9, fill=P.CARD_HEADER, outline="")
        c.create_rectangle(
            x, y + HEADER_H - 9, x + CARD_W, y + HEADER_H, fill=P.CARD_HEADER, width=0
        )
        c.create_text(
            x + 10, y + 12, text=title, anchor="w", fill=P.CARD_HEADER_TEXT, font=_FONT_TITLE
        )
        c.create_text(
            x + 10, y + 27, text=subtitle, anchor="w", fill=P.CARD_SUBTEXT, font=_FONT_SMALL
        )

    def _section(self, x: float, y: float, label: str) -> float:
        c = self._canvas
        c.create_text(x + 10, y + 9, text=label.upper(), anchor="w", fill=P.MUTED, font=_FONT_SMALL)
        c.create_line(x + 10, y + SECTION_H - 2, x + CARD_W - 10, y + SECTION_H - 2, fill=P.DIVIDER)
        return y + SECTION_H

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_switch_press(self, address: str) -> None:
        sim = self._simulation
        if sim.is_momentary(address):
            self._held = address
            sim.press_input(address)
        else:
            sim.toggle_switch(address)

    def _on_switch_release(self, address: str) -> None:
        if self._held == address:
            self._held = None
            self._simulation.release_input(address)

    def _show_action_error(self, text: str) -> None:
        if not self._destroyed:
            messagebox.showerror("Simulator", text, parent=self)

    def _add_force_items(self, menu: tk.Menu, address: str, values: tuple[bool, ...]) -> None:
        sim = self._simulation
        for value in values:
            menu.add_command(
                label=f"Force {'ON' if value else 'OFF'}",
                command=lambda v=value: sim.force(address, v, on_error=self._show_action_error),
            )
        menu.add_command(
            label="Release force",
            command=lambda: sim.release_force(address),
            state=tk.NORMAL if address in sim.forces else tk.DISABLED,
        )

    def _input_menu(self, event: tk.Event, address: str) -> None:
        sim = self._simulation
        menu = tk.Menu(self, tearoff=0)
        mode = tk.StringVar(value="momentary" if sim.is_momentary(address) else "maintained")
        menu.add_radiobutton(
            label="Momentary (pushbutton, on while held)", variable=mode, value="momentary",
            command=lambda: sim.set_momentary(address, True),
        )  # fmt: skip
        menu.add_radiobutton(
            label="Maintained (switch, click to latch)", variable=mode, value="maintained",
            command=lambda: sim.set_momentary(address, False),
        )  # fmt: skip
        menu.add_separator()
        self._add_force_items(menu, address, (True, False))
        menu._mode_var = mode  # type: ignore[attr-defined]  # keep the variable alive
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # Drawing: terminals
    # ------------------------------------------------------------------

    def _draw_input(self, x: float, y: float, address: str) -> None:
        c = self._canvas
        tag = f"in:{address}"
        self._row_target(x, y, tag, lambda e, a=address: self._input_menu(e, a))
        cy = y + ROW_H / 2
        switch = f"sw:{address}"
        track = _round_rect(
            c, x + 8, cy - 7, x + 32, cy + 7, 7, fill=P.SWITCH_OFF, outline="", tags=(tag, switch)
        )
        knob = c.create_oval(
            x + 10, cy - 5, x + 20, cy + 5, fill=P.SWITCH_KNOB, outline="", tags=(tag, switch)
        )
        # A Momentary input is drawn as a round pushbutton instead of a toggle.
        bezel = c.create_oval(
            x + 12, cy - 8, x + 28, cy + 8, fill=P.BUTTON_BEZEL, outline="", state="hidden",
            tags=(tag, switch),
        )  # fmt: skip
        cap = c.create_oval(
            x + 15, cy - 5, x + 25, cy + 5, fill=P.BUTTON_CAP, outline=P.SWITCH_KNOB,
            state="hidden", tags=(tag, switch),
        )  # fmt: skip
        self._tooltip_item(
            (track, knob, bezel, cap),
            lambda a=address: (
                "Momentary pushbutton: on while held. Right-click to change."
                if self._simulation.is_momentary(a)
                else "Maintained switch: click to latch. Right-click to change."
            ),
        )
        pending = c.create_oval(
            x + 30, cy - 11, x + 36, cy - 5, fill=P.PENDING, outline="", state="hidden", tags=(tag,)
        )
        self._tooltip_item((pending,), lambda: "Waiting for the next scan")
        led = c.create_oval(
            x + 38, cy - 4, x + 46, cy + 4, fill=P.LED_OFF, outline=P.LED_RIM, tags=(tag,)
        )
        self._draw_label(x + 52, cy, address, x + CARD_W - BADGE_W, tag)
        badge = self._draw_badge(x + CARD_W - 11, cy, tag)
        self._inputs[address] = {
            "track": track, "knob": knob, "bezel": bezel, "cap": cap, "led": led,
            "badge": badge, "pending": pending, "x": x, "cy": cy,
        }  # fmt: skip
        c.tag_bind(switch, "<ButtonPress-1>", lambda _e, a=address: self._on_switch_press(a))
        c.tag_bind(switch, "<ButtonRelease-1>", lambda _e, a=address: self._on_switch_release(a))

    def _output_menu(self, event: tk.Event, address: str) -> None:
        menu = tk.Menu(self, tearoff=0)
        self._add_force_items(menu, address, (True, False))
        menu.tk_popup(event.x_root, event.y_root)

    def _draw_output(self, x: float, y: float, address: str) -> None:
        c = self._canvas
        tag = f"out:{address}"
        self._row_target(x, y, tag, lambda e, a=address: self._output_menu(e, a))
        cy = y + ROW_H / 2
        led = c.create_oval(
            x + 10, cy - 5, x + 20, cy + 5, fill=P.LED_OFF, outline=P.LED_RIM, tags=(tag,)
        )
        self._draw_label(x + 26, cy, address, x + CARD_W - BADGE_W, tag)
        badge = self._draw_badge(x + CARD_W - 11, cy, tag)
        self._outputs[address] = {"led": led, "badge": badge}

    def _force_analog(self, address: str) -> None:
        current = self._simulation.forces.get(address)
        value = simpledialog.askfloat(
            "Force Value",
            f"Force {address} to:",
            parent=self,
            initialvalue=float(current) if isinstance(current, int | float) else None,
        )
        if value is not None:
            self._simulation.force(address, value, on_error=self._show_action_error)

    def _analog_menu(self, event: tk.Event, address: str) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Force value...", command=lambda: self._force_analog(address))
        menu.add_command(
            label="Release force",
            command=lambda: self._simulation.release_force(address),
            state=tk.NORMAL if address in self._simulation.forces else tk.DISABLED,
        )
        menu.tk_popup(event.x_root, event.y_root)

    def _commit_analog(self, address: str) -> None:
        info = self._analog_in.get(address)
        if info is None:
            return
        text = info["var"].get().strip()
        if not text:
            return
        try:
            value = float(text)
        except ValueError:
            self.bell()
            return
        if value != self._simulation.analog_value(address):
            self._simulation.set_analog(address, value)

    def _on_slider(self, address: str, value: str) -> None:
        self._dragging = True
        try:
            number = round(float(value), 3)
        except ValueError:
            return
        if number != self._simulation.analog_value(address):
            self._simulation.set_analog(address, number)

    def _draw_analog_in(self, x: float, y: float, channel: int, address: str | None) -> None:
        c = self._canvas
        if address is None:
            c.create_text(
                x + 10, y + 11, text=f"CH{channel}", anchor="w", fill=P.TEXT, font=_FONT_MONO
            )
            c.create_text(
                x + 46, y + 11, text="not assigned", anchor="w", fill=P.MUTED,
                font=_FONT_SMALL,
            )  # fmt: skip
            return
        tag = f"ai:{address}"
        self._row_target(
            x, y, tag, lambda e, a=address: self._analog_menu(e, a), height=ANALOG_ROW_H
        )
        self._draw_label(x + 10, y + 11, address, x + CARD_W - BADGE_W, tag)
        badge = self._draw_badge(x + CARD_W - 11, y + 11, tag)
        var = tk.StringVar()
        entry = ttk.Entry(c, textvariable=var, width=8, justify="right")
        entry.bind("<Return>", lambda _e, a=address: self._commit_analog(a))
        entry.bind("<FocusOut>", lambda _e, a=address: self._commit_analog(a))
        c.create_window(x + 10, y + 32, window=entry, anchor="w")
        self._widgets.append(entry)
        pending = c.create_oval(
            x + 72, y + 22, x + 78, y + 28, fill=P.PENDING, outline="", state="hidden"
        )
        live = c.create_text(
            x + 84, y + 32, text="", anchor="w", fill=P.MUTED, font=_FONT_SMALL, tags=(tag,)
        )
        info: dict[str, Any] = {
            "var": var,
            "entry": entry,
            "live": live,
            "badge": badge,
            "pending": pending,
        }
        hint = self._simulation.tag_hints.get(address, {})
        low, high = hint.get("min"), hint.get("max")
        ranged = not hint.get("rangeDefault", True) and low is not None and high is not None
        if ranged and high > low:
            scale = ttk.Scale(
                c, from_=low, to=high, orient=tk.HORIZONTAL, length=CARD_W - 96,
                command=lambda value, a=address: self._on_slider(a, value),
            )  # fmt: skip
            c.create_window(x + CARD_W - 8, y + 32, window=scale, anchor="e")
            self._widgets.append(scale)
            info["scale"] = scale
        self._analog_in[address] = info

    def _draw_analog_out(self, x: float, y: float, channel: int, address: str | None) -> None:
        c = self._canvas
        cy = y + ROW_H / 2
        if address is None:
            c.create_text(x + 10, cy, text=f"CH{channel}", anchor="w", fill=P.TEXT, font=_FONT_MONO)
            c.create_text(
                x + 46, cy, text="not assigned", anchor="w", fill=P.MUTED,
                font=_FONT_SMALL,
            )  # fmt: skip
            return
        tag = f"ao:{address}"
        self._row_target(x, y, tag, lambda e, a=address: self._analog_menu(e, a))
        self._draw_label(x + 10, cy, address, x + CARD_W - 74, tag)
        value = c.create_text(
            x + CARD_W - BADGE_W - 2, cy, text="", anchor="e", fill=P.TEXT, font=_FONT_BOLD,
            tags=(tag,),
        )  # fmt: skip
        badge = self._draw_badge(x + CARD_W - 11, cy, tag)
        self._analog_out[address] = {"value": value, "badge": badge}

    # ------------------------------------------------------------------
    # Drawing: cards
    # ------------------------------------------------------------------

    @staticmethod
    def _card_height(cpu: bool, inputs: int, outputs: int, ai: int, ao: int) -> float:
        height = HEADER_H + 6 + (CPU_PANEL_H if cpu else 0)
        for count, row in ((inputs, ROW_H), (outputs, ROW_H), (ai, ANALOG_ROW_H), (ao, ROW_H)):
            if count:
                height += SECTION_H + count * row
        return height + 8

    def _draw_rows(
        self, x: float, y: float, inputs: tuple[str | None, ...], outputs: tuple[str | None, ...],
        analog_in: tuple[tuple[int, str | None], ...], analog_out: tuple[tuple[int, str | None], ...],
    ) -> None:  # fmt: skip
        if inputs:
            y = self._section(x, y, "Inputs")
            for address in inputs:
                if address:
                    self._draw_input(x, y, address)
                y += ROW_H
        if outputs:
            y = self._section(x, y, "Outputs")
            for address in outputs:
                if address:
                    self._draw_output(x, y, address)
                y += ROW_H
        if analog_in:
            y = self._section(x, y, "Analog in")
            for channel, address in analog_in:
                self._draw_analog_in(x, y, channel, address)
                y += ANALOG_ROW_H
        if analog_out:
            y = self._section(x, y, "Analog out")
            for channel, address in analog_out:
                self._draw_analog_out(x, y, channel, address)
                y += ROW_H

    @staticmethod
    def _card_parts(card: Card) -> tuple[tuple, tuple, tuple, tuple]:
        return (
            tuple(t.address for t in card.of_kind("input")),
            tuple(t.address for t in card.of_kind("output")),
            tuple((t.channel, t.address) for t in card.of_kind("analog_in")),
            tuple((t.channel, t.address) for t in card.of_kind("analog_out")),
        )

    def _module_height(self, card: Card) -> float:
        inputs, outputs, analog_in, analog_out = self._card_parts(card)
        return self._card_height(
            card.location == "cpu", len(inputs), len(outputs), len(analog_in), len(analog_out)
        )

    def _on_mode_click(self, event: tk.Event) -> None:
        sx, _sy, zone = self._mode_zone
        index = int((self._canvas.canvasx(event.x) - sx) // zone)
        if 0 <= index < len(_POSITIONS):
            self._simulation.set_switch_position(_POSITIONS[index])

    def _draw_cpu_panel(self, x: float, y: float) -> None:
        c = self._canvas
        for i, name in enumerate(("PWR", "RUN", "ERR")):
            lx = x + 12 + i * 54
            self._cpu_leds[name] = c.create_oval(
                lx, y + 4, lx + 10, y + 14, fill=P.LED_OFF, outline=P.LED_RIM
            )
            c.create_text(lx + 15, y + 9, text=name, anchor="w", fill=P.TEXT, font=_FONT_SMALL)

        # The three-position mode switch: STOP | STEP | RUN.
        sx, sy = x + 10, y + 24
        zone = (CARD_W - 20) / 3
        self._mode_hint = _round_rect(
            c, sx - 4, sy - 4, sx + 3 * zone + 4, sy + 30, 9, fill="", outline="", width=3
        )
        _round_rect(
            c, sx, sy, sx + 3 * zone, sy + 26, 8, fill=P.SWITCH_OFF, outline="", tags=("mode",)
        )
        self._mode_knob = _round_rect(
            c, sx + 2, sy + 2, sx + zone - 2, sy + 24, 7, fill=P.MODE_STOP, outline="",
            tags=("mode",),
        )  # fmt: skip
        self._mode_zone = (sx, sy, zone)
        for i, position in enumerate(_POSITIONS):
            self._mode_labels[position] = c.create_text(
                sx + (i + 0.5) * zone, sy + 13, text=SWITCH_LABELS[position], fill=P.TEXT,
                font=_FONT_BOLD, tags=("mode",),
            )  # fmt: skip
        c.tag_bind("mode", "<Button-1>", self._on_mode_click)
        c.tag_bind("mode", "<Enter>", lambda _e: c.configure(cursor="hand2"))
        c.tag_bind("mode", "<Leave>", lambda _e: c.configure(cursor=""))
        self._mode_caption = c.create_text(
            x + 10, y + 60, text="", anchor="nw", fill=P.MUTED, font=_FONT_SMALL, width=CARD_W - 20
        )

    def _draw_card(self, x: float, y: float, card: Card) -> None:
        inputs, outputs, analog_in, analog_out = self._card_parts(card)
        self._draw_card_frame(x, y, self._module_height(card), card.title, card.model)
        top = y + HEADER_H + 6
        if card.location == "cpu":
            self._draw_cpu_panel(x, top)
            top += CPU_PANEL_H
        self._draw_rows(x, top, inputs, outputs, analog_in, analog_out)

    def _placeholder_text(self) -> str:
        text = (
            "No CPU configured. In CLICK Programming Software, open System "
            "Configuration, choose your CPU and modules, then save the project. "
            "This panel updates on the next save."
        )
        error = self._simulation.layout_error
        return f"{error}\n\n{text}" if error else text

    def _placeholder_height(self) -> float:
        return 230.0 if self._simulation.layout_error else 170.0

    def _draw_placeholder(self, x: float, y: float) -> None:
        self._draw_card_frame(x, y, self._placeholder_height(), "No CPU", "System Configuration")
        self._canvas.create_text(
            x + 10, y + HEADER_H + 10, text=self._placeholder_text(), anchor="nw", fill=P.TEXT,
            font=_FONT_SMALL, width=CARD_W - 20,
        )  # fmt: skip

    def _draw_unassigned(self, x: float, y: float, layout: PanelLayout) -> None:
        inputs, outputs = layout.unassigned_inputs, layout.unassigned_outputs
        height = self._card_height(False, len(inputs), len(outputs), 0, 0)
        self._draw_card_frame(
            x, y, height, "Unassigned I/O", "Used, not on any module", dashed=True
        )
        self._draw_rows(x, y + HEADER_H + 6, inputs, outputs, (), ())

    def _draw_rail(self, x0: float, x1: float, y: float) -> None:
        """A DIN rail running behind a row of installed modules (visible in the gaps)."""
        c = self._canvas
        items = (
            c.create_rectangle(x0, y, x1, y + 3, fill=P.RAIL_TOP, width=0),
            c.create_rectangle(x0, y + 3, x1, y + 11, fill=P.RAIL_BODY, width=0),
            c.create_rectangle(x0, y + 11, x1, y + 14, fill=P.RAIL_BOTTOM, width=0),
        )
        for item in reversed(items):
            c.tag_lower(item)

    def _per_row(self) -> int:
        width = self._canvas.winfo_width()
        if width <= 1:  # not laid out yet
            width = self._requested_width
        return max(1, int((width - 2 * MARGIN + CARD_GAP) // (CARD_W + CARD_GAP)))

    # ------------------------------------------------------------------
    # Live updates (no redraw)
    # ------------------------------------------------------------------

    def _show_badge(self, badge: tuple[int, ...], forced: bool) -> None:
        for item in badge:
            self._canvas.itemconfigure(item, state="normal" if forced else "hidden")

    def _refresh_inputs(self, values: dict, forces: dict, pending: dict) -> None:
        c = self._canvas
        sim = self._simulation
        for address, info in self._inputs.items():
            on = sim.switch_on(address)
            x, cy = info["x"], info["cy"]
            momentary = sim.is_momentary(address)
            toggle_state = "hidden" if momentary else "normal"
            button_state = "normal" if momentary else "hidden"
            c.itemconfigure(
                info["track"], fill=P.SWITCH_ON if on else P.SWITCH_OFF, state=toggle_state
            )
            kx = x + 20 if on else x + 10
            c.coords(info["knob"], kx, cy - 5, kx + 10, cy + 5)
            c.itemconfigure(info["knob"], state=toggle_state)
            c.itemconfigure(info["bezel"], state=button_state)
            # A held pushbutton sits lower and lights up.
            inset = 1 if on else 0
            c.coords(info["cap"], x + 15 + inset, cy - 5 + inset, x + 25 - inset, cy + 5 - inset)
            c.itemconfigure(
                info["cap"], fill=P.SWITCH_ON if on else P.BUTTON_CAP, state=button_state
            )
            c.itemconfigure(info["led"], fill=P.LED_ON if values.get(address) else P.LED_OFF)
            self._show_badge(info["badge"], address in forces)
            c.itemconfigure(info["pending"], state="normal" if address in pending else "hidden")

    def _refresh_outputs(self, values: dict, forces: dict) -> None:
        c = self._canvas
        for address, info in self._outputs.items():
            c.itemconfigure(info["led"], fill=P.LED_ON if values.get(address) else P.LED_OFF)
            self._show_badge(info["badge"], address in forces)
        for address, info in self._analog_out.items():
            c.itemconfigure(info["value"], text=_value_text(values.get(address)))
            self._show_badge(info["badge"], address in forces)

    def _refresh_analog_inputs(self, values: dict, forces: dict, pending: dict) -> None:
        c = self._canvas
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):  # e.g. a combobox's popdown has focus
            focused = None
        for address, info in self._analog_in.items():
            desired = self._simulation.analog_value(address)
            live = values.get(address)
            if info["entry"] is not focused:
                shown = desired if desired is not None else live
                info["var"].set(_value_text(shown) if shown is not None else "")
            if "scale" not in info:
                live_text = f"now {_value_text(live)}" if live is not None else ""
                c.itemconfigure(info["live"], text=live_text)
            elif desired is not None and not self._dragging:
                info["scale"].set(desired)
            self._show_badge(info["badge"], address in forces)
            c.itemconfigure(info["pending"], state="normal" if address in pending else "hidden")

    def _refresh_cpu(self) -> None:
        c = self._canvas
        sim = self._simulation
        if not self._cpu_leds or self._mode_knob is None:
            return
        ready = sim.is_ready
        position = sim.switch_position
        c.itemconfigure(self._cpu_leds["PWR"], fill=P.LED_ON if ready else P.LED_OFF)
        run_lit = ready and (position == "run" or (position == "step" and self._blink))
        c.itemconfigure(self._cpu_leds["RUN"], fill=P.LED_ON if run_lit else P.LED_OFF)
        failed = sim.status is SimStatus.FAILED
        c.itemconfigure(self._cpu_leds["ERR"], fill=P.LED_ERR if failed else P.LED_OFF)

        sx, sy, zone = self._mode_zone
        kx = sx + _POSITIONS.index(position) * zone
        c.coords(self._mode_knob, *_rounded_points(kx + 2, sy + 2, kx + zone - 2, sy + 24, 7))
        c.itemconfigure(self._mode_knob, fill=_POSITION_COLORS[position] if ready else P.LED_OFF)
        for pos, label in self._mode_labels.items():
            c.itemconfigure(label, fill="#ffffff" if pos == position else P.TEXT)

        hint = ready and not sim.run_hint_seen
        if self._mode_hint is not None:
            c.itemconfigure(self._mode_hint, outline=P.HINT if hint and self._blink else "")
        if self._mode_caption is not None:
            if not ready:
                caption = sim.status_text
            elif hint:
                caption = "Flip to RUN to start the program, or STEP to scan one at a time."
            else:
                caption = {
                    "stop": "Stopped. Outputs are off.",
                    "step": "Scans advance only when you step.",
                    "run": f"Running at {sim.speed_text}.",
                }[position]
            c.itemconfigure(self._mode_caption, text=caption)

    def _show_details(self) -> None:
        detail = self._simulation.error_detail or ""
        window = tk.Toplevel(self)
        window.title("Simulation details")
        text = tk.Text(window, wrap=tk.NONE, font=_FONT_MONO, width=100, height=24)
        text.insert("1.0", detail)
        text.configure(state="disabled")
        text.pack(fill=tk.BOTH, expand=True)

    def _change_port(self) -> None:
        port = simpledialog.askinteger(
            "Modbus Port",
            "Serve the simulated PLC's Modbus on port:",
            parent=self,
            initialvalue=self._simulation.modbus_port,
            minvalue=1,
            maxvalue=65535,
        )
        if port is not None:
            self._simulation.set_modbus_port(port)

    def _refresh_banners(self) -> None:
        sim = self._simulation
        messages: list[tuple[str, list[tuple[str, Callable[[], None]]]]] = []
        if not sim.enabled:
            messages.append(
                (
                    "Simulation is off. Start it to run the program; your switches, "
                    "values and forces are kept.",
                    [("Start", sim.turn_on)],
                )
            )
        elif sim.status is SimStatus.FAILED and sim.error:
            actions = [("Retry", sim.retry)]
            if sim.error_detail:
                actions.append(("Show details", self._show_details))
            messages.append((f"Cannot simulate: {sim.error}", actions))
        info = sim.modbus_info
        if sim.is_ready and info.get("error"):
            messages.append(
                (
                    f"The Modbus server could not start on port {info.get('port')}: "
                    f"{info['error']}. Switches and values still work; other "
                    "Modbus clients cannot connect.",
                    [("Change port...", self._change_port)],
                )
            )
        restored = sim.restored_forces
        if restored:
            noun = "force" if restored == 1 else "forces"
            messages.append(
                (
                    f"{restored} {noun} restored from last session.",
                    [
                        ("Release all", sim.release_all_forces),
                        ("Keep", sim.dismiss_restored_forces),
                    ],
                )
            )
        if sim.notice:
            messages.append((sim.notice, [("Dismiss", sim.dismiss_notice)]))
        if self._last_error:
            messages.append((self._last_error, [("Dismiss", self._dismiss_error)]))

        key = tuple((text, tuple(label for label, _ in actions)) for text, actions in messages)
        if key == self._banner_key:
            return
        self._banner_key = key
        for child in self._banner.winfo_children():
            child.destroy()
        if not messages:
            self._banner.pack_forget()
            return
        for text, actions in messages:
            row = ttk.Frame(self._banner, style="SimBanner.TFrame", padding=(10, 4))
            ttk.Label(
                row, text=text, style="SimBanner.TLabel", wraplength=760, justify=tk.LEFT
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            for label, command in reversed(actions):
                ttk.Button(row, text=label, command=command).pack(side=tk.RIGHT, padx=(6, 0))
            row.pack(fill=tk.X, pady=(0, 1))
        if not self._banner.winfo_manager():
            self._banner.pack(fill=tk.X, after=self._toolbar)

    # ------------------------------------------------------------------
    # Toolbar and banners
    # ------------------------------------------------------------------

    def _refresh_toolbar(self) -> None:
        sim = self._simulation
        ready = sim.is_ready
        position = sim.switch_position
        scan = sim.scan_id
        # The mode itself is on the CPU switch; this line says who moved it,
        # or what the simulation is doing while it is not running.
        self._status_var.set(sim.source_text if ready else sim.status_text)
        self._scan_var.set(f"Scan {scan}" if ready and scan is not None else "")
        self._modbus_var.set(sim.modbus_text)

        show_step = ready and position == "step"
        show_run = ready and position == "run"
        if show_step and not self._step_bar.winfo_manager():
            self._step_bar.pack(side=tk.LEFT, padx=(12, 0), after=self._scan_label)
        elif not show_step and self._step_bar.winfo_manager():
            self._step_bar.pack_forget()
        if show_run and not self._run_bar.winfo_manager():
            self._run_bar.pack(side=tk.LEFT, padx=(12, 0), after=self._scan_label)
        elif not show_run and self._run_bar.winfo_manager():
            self._run_bar.pack_forget()
        if not self._speed_box_focused:
            self._speed_var.set(format_speed(sim.speed))
        self._actual_var.set(sim.speed_text.partition(" ")[2])

        count = len(sim.forces)
        self._forces_btn.configure(text=f"Forces ({count})" if count else "Forces")
        self._refresh_banners()

    def _refresh_dynamic(self) -> None:
        sim = self._simulation
        values = sim.values
        forces = sim.forces
        pending = sim.pending
        self._refresh_inputs(values, forces, pending)
        self._refresh_outputs(values, forces)
        self._refresh_analog_inputs(values, forces, pending)
        self._refresh_cpu()
        self._refresh_toolbar()

    def _redraw(self) -> None:
        c = self._canvas
        for widget in self._widgets:
            widget.destroy()
        self._widgets.clear()
        c.delete("all")
        for table in (self._inputs, self._outputs, self._analog_in, self._analog_out):
            table.clear()
        self._cpu_leds.clear()
        self._mode_labels.clear()
        self._mode_knob = None
        self._mode_hint = None
        self._mode_caption = None

        # Everything to draw, in rack order: (height, draw(x, y), sits on the rail).
        layout = self._simulation.layout
        pieces: list[tuple[float, Callable[[float, float], None], bool]] = []
        if layout is None or not layout.has_cpu:
            pieces.append((self._placeholder_height(), self._draw_placeholder, False))
        if layout is not None:
            for card in layout.cards:
                pieces.append(
                    (self._module_height(card), lambda x, y, k=card: self._draw_card(x, y, k), True)
                )
            if layout.unassigned_inputs or layout.unassigned_outputs:
                n_in, n_out = len(layout.unassigned_inputs), len(layout.unassigned_outputs)
                pieces.append(
                    (
                        self._card_height(False, n_in, n_out, 0, 0),
                        lambda x, y: self._draw_unassigned(x, y, layout),
                        False,
                    )
                )

        # Flow the cards into rows that fit the window, keeping rack order.
        per_row = self._per_row()
        self._drawn_per_row = per_row
        y = float(MARGIN)
        widest = 0.0
        for start in range(0, len(pieces), per_row):
            row = pieces[start : start + per_row]
            x = float(MARGIN)
            rail: list[float] = []
            for _height, draw, on_rail in row:
                draw(x, y)
                if on_rail:
                    rail.extend((x, x + CARD_W))
                x += CARD_W + CARD_GAP
            if rail:
                self._draw_rail(min(rail) - 6, max(rail) + 6, y + 70)
            widest = max(widest, x)
            y += max(height for height, _draw, _rail in row) + ROW_GAP
        c.configure(scrollregion=(0, 0, widest + MARGIN, y + MARGIN))
        if layout is not None:
            self._simulation.watch(self, layout.poll_addresses)
        self._refresh_dynamic()

    def _on_canvas_resized(self, _event: tk.Event) -> None:
        if self._per_row() != self._drawn_per_row:
            self._redraw()

    def _populate_forces_menu(self) -> None:
        menu = self._forces_menu
        menu.delete(0, tk.END)
        forces = self._simulation.forces
        if not forces:
            menu.add_command(label="No forces", state=tk.DISABLED)
            return
        from ..services.sim_hardware import address_sort_key

        for address in sorted(forces, key=address_sort_key):
            nickname = self._names(address)[0]
            label = f"{address} = {_value_text(forces[address])}"
            if nickname:
                label += f"   {nickname}"
            menu.add_command(
                label=f"Release {label}",
                command=lambda a=address: self._simulation.release_force(a),
            )
        menu.add_separator()
        menu.add_command(label="Release all", command=self._simulation.release_all_forces)

    def _on_any_release(self, _event: tk.Event | None) -> None:
        # The pointer can leave the switch before the button comes up.
        if self._held is not None:
            held, self._held = self._held, None
            self._simulation.release_input(held)
        self._dragging = False

    def _on_speed_selected(self, _event: object = None) -> None:
        text = self._speed_var.get()
        for speed in SPEEDS:
            if format_speed(speed) == text:
                self._simulation.set_speed(speed)
                return

    def _browse_plc_data(self) -> None:
        """Same session-level PLC data as the Console's Browse..."""
        current = self._simulation.plc_data_path
        path = filedialog.askopenfilename(
            parent=self,
            title="Load PLC Data",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=str(current.parent) if current is not None else None,
        )
        if path:
            self._simulation.set_plc_data_path(Path(path))

    def _step_n(self) -> None:
        try:
            count = int(self._step_count_var.get())
        except ValueError:
            self.bell()
            return
        if count >= 1:
            self._simulation.step(count)

    def _run_for(self) -> None:
        duration = self._run_for_var.get().strip()
        if duration:
            self._simulation.run_for(duration)

    # ------------------------------------------------------------------
    # Session and store events
    # ------------------------------------------------------------------

    def _on_simulation_event(self, event: SimEvent) -> None:
        if self._destroyed:
            return
        if event.kind == "layout":
            self._redraw()
            return
        if event.kind == "message" and event.level == "error":
            self._last_error = event.text
        self._refresh_dynamic()

    def _on_store_changed(self, _store: object = None, _keys: object = None) -> None:
        if not self._destroyed:
            self._redraw()

    def _tick(self) -> None:
        self._tick_after_id = None
        if self._destroyed:
            return
        self._blink = not self._blink
        self._refresh_cpu()
        self._tick_after_id = self.after(TICK_MS, self._tick)

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------

    def _create_toolbar(self) -> None:
        style = ttk.Style(self)
        style.configure("SimBanner.TFrame", background="#fff4e6")
        style.configure("SimBanner.TLabel", background="#fff4e6")
        style.configure("SimScan.TLabel", font=("Segoe UI", 10, "bold"))

        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill=tk.X)
        self._toolbar = bar
        self._scan_label = ttk.Label(
            bar, textvariable=self._scan_var, style="SimScan.TLabel", width=11
        )
        self._scan_label.pack(side=tk.LEFT)
        # Who moved the mode switch, or what the simulation is doing; the mode
        # itself is shown by the CPU's switch. Step/Run controls pack before it.
        ttk.Label(bar, textvariable=self._status_var, foreground=P.MUTED).pack(
            side=tk.LEFT, padx=(12, 0)
        )

        # Shown only in STEP: scans advance on request, as fast as possible.
        self._step_bar = ttk.Frame(bar)
        ttk.Button(
            self._step_bar, text="Step", width=6, command=lambda: self._simulation.step()
        ).pack(side=tk.LEFT)
        ttk.Spinbox(
            self._step_bar, from_=2, to=100000, textvariable=self._step_count_var, width=6
        ).pack(side=tk.LEFT, padx=(8, 2))
        ttk.Button(self._step_bar, text="Step N", command=self._step_n).pack(side=tk.LEFT)
        ttk.Entry(self._step_bar, textvariable=self._run_for_var, width=7).pack(
            side=tk.LEFT, padx=(8, 2)
        )
        run_for = ttk.Button(self._step_bar, text="Run for", command=self._run_for)
        run_for.pack(side=tk.LEFT)
        bind_tooltip(run_for, "Scan for a stretch of simulated time (500ms, 2 s) or N scans.")

        # Shown only in RUN: pacing applies to free-running only.
        self._run_bar = ttk.Frame(bar)
        ttk.Label(self._run_bar, text="Speed").pack(side=tk.LEFT, padx=(0, 4))
        speed_box = ttk.Combobox(
            self._run_bar,
            textvariable=self._speed_var,
            values=[format_speed(s) for s in SPEEDS],
            state="readonly",
            width=6,
        )
        speed_box.pack(side=tk.LEFT)
        speed_box.bind("<<ComboboxSelected>>", self._on_speed_selected)
        speed_box.bind("<FocusIn>", lambda _e: setattr(self, "_speed_box_focused", True))
        speed_box.bind("<FocusOut>", lambda _e: setattr(self, "_speed_box_focused", False))
        ttk.Label(self._run_bar, textvariable=self._actual_var, foreground=P.MODE_STEP).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(
            self._run_bar,
            text="Pause",
            width=6,
            command=lambda: self._simulation.set_switch_position("step"),
        ).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(bar, text="Console", command=self._open_console).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Dataview", command=self._open_dataview).pack(
            side=tk.RIGHT, padx=(0, 4)
        )
        plc_data = ttk.Button(bar, text="PLC Data...", command=self._browse_plc_data)
        plc_data.pack(side=tk.RIGHT, padx=(0, 4))
        bind_tooltip(
            plc_data,
            "Start from the PLC's live values: a CSV saved in CLICK with\n"
            "PLC > Read Data from PLC > All > Save (not the nickname CSV).\n"
            "Switches and analog values take the file's values.",
        )
        self._forces_btn = ttk.Menubutton(bar, text="Forces")
        self._forces_menu = tk.Menu(
            self._forces_btn, tearoff=0, postcommand=self._populate_forces_menu
        )
        self._forces_btn.configure(menu=self._forces_menu)
        self._forces_btn.pack(side=tk.RIGHT, padx=(0, 12))
        modbus = ttk.Label(bar, textvariable=self._modbus_var, foreground=P.MUTED)
        modbus.pack(side=tk.RIGHT, padx=(0, 12))
        bind_tooltip(
            modbus,
            "The simulated PLC's Modbus TCP server. Point an HMI or other Modbus "
            "client here; the count excludes this window's own connection.",
        )

        self._banner = ttk.Frame(self)

    def _create_canvas(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True)
        self._canvas = tk.Canvas(frame, background=P.RACK_BG, highlightthickness=0)
        ybar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=ybar.set)
        ybar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas.bind("<ButtonRelease-1>", self._on_any_release, add="+")
        self._canvas.bind("<Configure>", self._on_canvas_resized, add="+")
        self._canvas.bind(
            "<MouseWheel>", lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units")
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self._tick_after_id is not None:
            self.after_cancel(self._tick_after_id)
            self._tick_after_id = None
        if self._held is not None:
            self._simulation.release_input(self._held)
        sim = self._simulation
        sim.remove_listener(self._on_simulation_event)
        sim.unwatch(self)  # closing the window leaves the simulation running
        if self._tooltip is not None:
            self._tooltip.destroy()
        store = self._observed_store
        if store is not None:
            store.remove_observer(self._on_store_changed)
        if self._on_destroy is not None:
            self._on_destroy()
        self.destroy()

    def __init__(
        self,
        parent: tk.Misc,
        *,
        simulation: SimulationSession,
        get_store: Callable[[], AddressStore | None],
        open_dataview: Callable[[], None],
        open_console: Callable[[], None],
        on_destroy: Callable[[], None] | None = None,
        title_suffix: str = "",
    ) -> None:
        super().__init__(parent)
        self._simulation = simulation
        self._get_store = get_store
        self._open_dataview = open_dataview
        self._open_console = open_console
        self._on_destroy = on_destroy
        self._destroyed = False

        self.title(f"Simulator — {title_suffix}" if title_suffix else "Simulator")
        self._requested_width = 1180
        self.geometry(f"{self._requested_width}x720")
        self.minsize(480, 360)

        self._font = tkfont.Font(self, font=_FONT)
        self._inputs: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, dict[str, Any]] = {}
        self._analog_in: dict[str, dict[str, Any]] = {}
        self._analog_out: dict[str, dict[str, Any]] = {}
        self._cpu_leds: dict[str, int] = {}
        self._mode_labels: dict[str, int] = {}
        self._mode_knob: int | None = None
        self._mode_hint: int | None = None
        self._mode_caption: int | None = None
        self._mode_zone: tuple[float, float, float] = (0, 0, 0)
        self._widgets: list[tk.Widget] = []
        self._held: str | None = None
        self._dragging = False
        self._blink = False
        self._speed_box_focused = False
        self._last_error: str | None = None
        self._banner_key: tuple = ()
        self._tick_after_id: str | None = None
        self._tooltip: tk.Toplevel | None = None
        self._drawn_per_row = 0

        self._status_var = tk.StringVar()
        self._scan_var = tk.StringVar()
        self._modbus_var = tk.StringVar()
        self._speed_var = tk.StringVar(value=format_speed(simulation.speed))
        self._actual_var = tk.StringVar()
        self._step_count_var = tk.StringVar(value="10")
        self._run_for_var = tk.StringVar(value="1 s")

        self._create_toolbar()
        self._create_canvas()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._observed_store = get_store()
        if self._observed_store is not None:
            self._observed_store.add_observer(self._on_store_changed)
        # The opener turns the simulation on; the hardware shows either way.
        simulation.add_listener(self._on_simulation_event)
        simulation.refresh_layout()
        self._redraw()
        self._tick_after_id = self.after(TICK_MS, self._tick)

    def _dismiss_error(self) -> None:
        self._last_error = None
        self._refresh_banners()
