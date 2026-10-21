"""Simulator window: the user's CLICK hardware, drawn as a rack of modules.

A passive view of the connection's SimulationSession. Inputs are switches
(Momentary pushbuttons or Maintained toggles, chosen by right-click), outputs
are LEDs, analog inputs take a value (and a slider when the tag has a range).
A slim CPU card carries the RUN / STEP / STOP mode switch and the PWR/RUN/ERR
LEDs; the CPU's built-in I/O and option slots sit tight beside it as cards of
their own, one housing as on the hardware. Values come from the session's Modbus reads; forces, mode, speed and
feedback links from its DAP frames. Every action goes through the session.

An input driven by a feedback link shows a chip naming its driver instead of
a switch (blue for the program's link, purple for a bench link); hovering the
chip draws the wire to the driving terminal. Links are made, cut and saved to
the project from the right-click menu; the Wiring menu lists them all.

Cards are compact and flow into rows in rack order, so a full rack (CPU, two
option slots, eight expansions and the unassigned strip) fits without
horizontal scrolling.

The command console is a resizable pane under the rack (Ctrl+` shows or hides
it) and pops out into its own window; closing that window docks it back.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import TYPE_CHECKING, Any, NamedTuple

from pyclickplc.addresses import get_addr_key, parse_address

from ..services.link_annotation import comment_has_link, comment_with_link, when_text
from ..services.sim_state import BenchLink
from ..simulation_session import SPEEDS, SWITCH_LABELS, SimStatus, format_speed
from ..widgets.tooltip import bind_tooltip
from . import sim_palette as P
from .console_panel import ConsolePanel, ConsoleWindow, Transcript
from .sim_link_dialog import LinkDialog

if TYPE_CHECKING:
    from ..data.address_store import AddressStore
    from ..services.analysis_service import AnalysisService
    from ..services.sim_hardware import Card, PanelLayout
    from ..simulation_session import SimEvent, SimulationSession, SwitchPosition, WiredLink

CARD_W = 184
CARD_GAP = 12
#: Between cards in one housing: the CPU, its built-in I/O and its option slots.
HOUSING_GAP = 4
ROW_GAP = 18
MARGIN = 12
HEADER_H = 36
#: Between a card's header and its first section.
BODY_PAD = 4
ROW_H = 24
ANALOG_ROW_H = 46
SECTION_H = 18
#: The slim CPU card: mode switch over the PWR/RUN/ERR LEDs.
CPU_CARD_W = 96
CPU_CARD_MIN_H = 164
#: One position of the CPU's vertical mode switch.
MODE_ZONE_H = 16
BADGE_W = 20
#: The console pane's height when shown again after hiding, until the user sizes it.
CONSOLE_H = 170
#: The least the rack keeps when the console pane is dragged taller.
MIN_RACK_H = 120
#: The least the console pane keeps when its header is dragged down: header and command line.
MIN_CONSOLE_H = 70
#: Characters of the PLC data file's name shown on its toolbar button.
PLC_DATA_NAME_MAX = 24
TICK_MS = 500

_FONT = ("Segoe UI", 9)
_FONT_BOLD = ("Segoe UI", 9, "bold")
_FONT_SMALL = ("Segoe UI", 8)
_FONT_MONO = ("Consolas", 9)
_FONT_TITLE = ("Segoe UI", 10, "bold")

#: Top to bottom, as on the CPU: RUN up, STOP down.
_POSITIONS: tuple[SwitchPosition, ...] = ("run", "step", "stop")
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


class _Piece(NamedTuple):
    """One card to place in the rack."""

    width: float
    height: float
    draw: Callable[[float, float], None]
    #: Installed on the DIN rail (the placeholder and unassigned strip are not).
    on_rail: bool = True
    #: Space before it when it follows another card in the same rack row.
    gap: float = CARD_GAP


def _countdown_text(ms: int) -> str:
    """Time left on a link's delay, short enough for its chip: ``1.2s``, ``12s``."""
    seconds = ms / 1000
    return f"{seconds:.1f}s" if seconds < 10 else f"{seconds:.0f}s"


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
            x + 3, y, x + self._card_w - 3, y + height, fill=P.CARD_FACE, outline="", tags=(tag,)
        )
        c.tag_bind(tag, "<Button-3>", menu)

    def _draw_card_frame(
        self, x: float, y: float, height: float, title: str, subtitle: str, *,
        dashed: bool = False, width: float | None = None,
    ) -> None:  # fmt: skip
        c = self._canvas
        right = x + (self._card_w if width is None else width)
        _round_rect(
            c, x, y, right, y + height, 9,
            fill=P.CARD_FACE, outline=P.CARD_EDGE, width=2, dash=(4, 3) if dashed else (),
        )  # fmt: skip
        _round_rect(c, x, y, right, y + HEADER_H, 9, fill=P.CARD_HEADER, outline="")
        c.create_rectangle(x, y + HEADER_H - 9, right, y + HEADER_H, fill=P.CARD_HEADER, width=0)
        c.create_text(
            x + 10, y + 12, text=title, anchor="w", fill=P.CARD_HEADER_TEXT, font=_FONT_TITLE
        )
        c.create_text(
            x + 10, y + 27, text=subtitle, anchor="w", fill=P.CARD_SUBTEXT, font=_FONT_SMALL
        )

    def _section(self, x: float, y: float, label: str) -> float:
        c = self._canvas
        c.create_text(x + 10, y + 9, text=label.upper(), anchor="w", fill=P.MUTED, font=_FONT_SMALL)
        c.create_line(
            x + 10, y + SECTION_H - 2, x + self._card_w - 10, y + SECTION_H - 2, fill=P.DIVIDER
        )
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

    # ------------------------------------------------------------------
    # Feedback links
    # ------------------------------------------------------------------

    def _saved_to_project(self, address: str, link: BenchLink) -> bool:
        """True when the project's comment on *address* already declares this bench link."""
        if link.enable is None:
            return False
        _nickname, comment = self._names(address)
        enable_names = (self._names(link.enable)[0], link.enable)
        return comment_has_link(comment, link, enable_names)

    def _link_text(self, address: str) -> str:
        """Tooltip for an input's link chip or cut mark."""
        sim = self._simulation
        link = sim.driving_link(address)
        if link is None:
            bench = sim.bench_links.get(address)
            if bench is not None and bench.cut:
                return (
                    "The program's link is cut on the bench, as if the sensor failed; "
                    "the switch drives this input. Right-click to restore it."
                )
            return ""
        enable = link.enable or ""
        nickname = self._names(enable)[0]
        driver = f"{enable} {nickname}" if nickname else enable
        when = when_text(link.enable, link.trigger)
        kind = "Program link" if link.source == "project" else "Bench link"
        text = f"{kind}: driven by {driver}{when} ({link.response})."
        bench = sim.bench_links.get(address)
        if link.source == "bench" and bench is not None and self._saved_to_project(address, bench):
            text += "\nSaved to the project; the program takes it over after the next Sync."
        return f"{text}\nRight-click for options."

    def _enables(self) -> list[str]:
        layout = self._simulation.layout
        if layout is None:
            return []
        return [*layout.addresses("output"), *layout.addresses("input")]

    def _open_link_dialog(self, address: str, *, analog: bool, enable: str | None = None) -> None:
        sim = self._simulation
        current = sim.bench_links.get(address)
        if current is None or current.cut:
            wired = sim.driving_link(address) or sim.project_link(address)
            if wired is not None and not wired.cut:
                current = BenchLink(
                    wired.enable, wired.trigger, wired.on_delay, wired.off_delay, wired.profile
                )
            else:
                current = None
        LinkDialog(
            self,
            feedback=address,
            analog=analog,
            current=current,
            enables=self._enables(),
            on_ok=lambda link: sim.link(address, link, on_error=self._show_action_error),
            enable=enable,
        )

    def _terminal_center(self, address: str) -> tuple[float, float] | None:
        """Where the LED of the terminal at *address* is drawn, if it is on the panel."""
        info = self._outputs.get(address) or self._inputs.get(address)
        if info is None:
            return None
        x0, y0, x1, y1 = self._canvas.coords(info["led"])
        return (x0 + x1) / 2, (y0 + y1) / 2

    # Drag an output onto an input (or analog input) to link them.

    def _start_link_drag(self, address: str) -> None:
        start = self._terminal_center(address)
        if start is not None:
            self._link_drag = {"source": address, "start": start, "target": None}

    def _link_target_at(self, x: float, y: float, source: str) -> str | None:
        """The ``in:`` / ``ai:`` row tag under canvas point (x, y), if it can be linked."""
        c = self._canvas
        for item in reversed(c.find_overlapping(x, y, x, y)):
            for tag in c.gettags(item):
                kind, _, address = tag.partition(":")
                if kind in ("in", "ai") and address and address != source:
                    return tag
        return None

    def _on_link_drag(self, event: tk.Event) -> None:
        drag = self._link_drag
        if drag is None:
            return
        c = self._canvas
        c.configure(cursor="crosshair")
        x, y = c.canvasx(event.x), c.canvasy(event.y)
        c.delete("drag")
        target = self._link_target_at(x, y, drag["source"])
        drag["target"] = target
        if target is not None:
            x0, y0, x1, y1 = c.bbox(target)
            _round_rect(
                c, x0, y0 - 1, x1, y1 + 1, 6, fill="", outline=P.LINK_BENCH, width=2,
                tags=("drag",),
            )  # fmt: skip
        sx, sy = drag["start"]
        c.create_oval(sx - 8, sy - 8, sx + 8, sy + 8, outline=P.LINK_BENCH, width=2, tags=("drag",))
        c.create_line(
            sx, sy, x, y, fill=P.LINK_BENCH, width=2, dash=(5, 3), arrow=tk.LAST, tags=("drag",)
        )

    def _end_link_drag(self) -> None:
        drag, self._link_drag = self._link_drag, None
        if drag is None:
            return
        self._canvas.delete("drag")
        self._canvas.configure(cursor="")
        target = drag["target"]
        if target is not None:
            kind, _, address = target.partition(":")
            self._open_link_dialog(address, analog=kind == "ai", enable=drag["source"])

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
        restored_links = sim.restored_links
        if restored_links:
            noun = "bench link" if restored_links == 1 else "bench links"
            messages.append(
                (
                    f"{restored_links} {noun} restored from last session.",
                    [
                        ("Discard all", sim.discard_bench_links),
                        ("Keep", sim.dismiss_restored_links),
                    ],
                )
            )
        if sim.notice:
            messages.append((sim.notice, [("Dismiss", sim.dismiss_notice)]))
        if self._note:
            messages.append((self._note, [("Dismiss", self._dismiss_note)]))
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

    def _save_link_to_project(self, address: str) -> None:
        """Write the bench link on *address* into its comment, through an undoable edit."""
        link = self._simulation.bench_links.get(address)
        store = self._get_store()
        if link is None or link.cut or link.enable is None or store is None:
            return
        addr_key = get_addr_key(*parse_address(address))
        row = store.visible_state.get(addr_key)
        if row is None or not row.nickname:
            self._show_action_error(
                f"Give {address} a nickname first: the program reads links only from named tags."
            )
            return
        enable_name = self._names(link.enable)[0] or link.enable
        try:
            comment = comment_with_link(getattr(row, "comment", "") or "", link, enable_name)
        except ValueError as exc:
            self._show_action_error(f"Could not save the link on {address}: {exc}")
            return
        with store.edit_session(f"Save link on {address}") as session:
            session.set_field(addr_key, "comment", comment)
        self._note = (
            f"Saved the link on {address} to the project. Sync to write it to CLICK; "
            "after the next build the program declares it and the bench copy is dropped."
        )
        self._refresh_banners()

    def _add_link_items(self, menu: tk.Menu, address: str, *, analog: bool) -> None:
        sim = self._simulation
        bench = sim.bench_links.get(address)
        project = sim.project_link(address)
        menu.add_separator()
        if bench is not None and bench.cut:
            menu.add_command(
                label="Restore the program's link", command=lambda: sim.restore_link(address)
            )
            return
        if bench is not None:
            menu.add_command(
                label="Edit bench link...",
                command=lambda: self._open_link_dialog(address, analog=analog),
            )
            saved = self._saved_to_project(address, bench)
            menu.add_command(
                label="Saved to project" if saved else "Save link to project",
                command=lambda: self._save_link_to_project(address),
                state=tk.DISABLED if saved or self._get_store() is None else tk.NORMAL,
            )
            menu.add_command(
                label="Disable bench link" if bench.enabled else "Enable bench link",
                command=lambda: sim.set_link_enabled(address, not bench.enabled),
            )
            menu.add_command(
                label="Remove bench link"
                if project is None
                else "Remove bench link (back to the program's)",
                command=lambda: sim.restore_link(address),
            )
            return
        if project is not None:
            menu.add_command(
                label="Change link on the bench...",
                command=lambda: self._open_link_dialog(address, analog=analog),
            )
            menu.add_command(
                label="Cut link (simulate a failure)",
                command=lambda: sim.cut_link(address, on_error=self._show_action_error),
            )
            return
        menu.add_command(
            label="Link to the tag that drives it...",
            command=lambda: self._open_link_dialog(address, analog=analog),
        )

    def _wire_points(
        self,
        source: dict[str, Any],
        start: tuple[float, float],
        target: dict[str, Any],
        end: tuple[float, float],
    ) -> list[float]:
        """A wire that stays in the gaps between cards, clear of the other cards.

        It leaves the source card through the gap on its left. Within one card
        it runs straight down that gap into the chip; from the card just right
        of the target, down the gap they share to the end of the target's row.
        Otherwise it climbs into the space above the source's rack row, and in
        another rack row it changes rows down the left margin, which is clear
        in every row; then it comes down the gap left of the target's card into
        the chip.
        """
        (sx, sy), (ex, ey) = start, end
        tx, tg, t_top = target["x"], target["gutter"], target["top"]
        sg, s_top = source.get("gutter", tg), source.get("top", t_top)
        if s_top == t_top:
            if source.get("x") == tx:
                return [sx, sy, sg, sy, sg, ey, ex, ey]
            row_end = tx + self._card_w - 2
            if abs(sg - row_end) <= CARD_GAP:  # the card just right of the target
                return [sx, sy, sg, sy, sg, ey, row_end, ey]
            over = s_top - 8
            return [sx, sy, sg, sy, sg, over, tg, over, tg, ey, ex, ey]
        lane = MARGIN / 2
        s_over, t_over = s_top - 8, t_top - 8
        return [
            sx, sy, sg, sy, sg, s_over, lane, s_over, lane, t_over, tg, t_over, tg, ey, ex, ey,
        ]  # fmt: skip

    def _show_wire(self, address: str) -> None:
        """Draw the wire from the driving terminal to *address* while the chip is hovered."""
        c = self._canvas
        c.delete("wire")
        link = self._simulation.driving_link(address)
        info = self._inputs.get(address)
        if link is None or link.enable is None or info is None:
            return
        source = self._terminal_center(link.enable)
        if source is None:
            return
        x0, y0, x1, y1 = c.bbox(info["pill"])
        ex, ey = x0 + 1, (y0 + y1) / 2
        color = P.LINK if link.source == "project" else P.LINK_BENCH
        sx, sy = source
        source_info = self._outputs.get(link.enable) or self._inputs.get(link.enable) or {}
        points = self._wire_points(source_info, (sx, sy), info, (ex, ey))
        c.create_oval(sx - 8, sy - 8, sx + 8, sy + 8, outline=color, width=2, tags=("wire",))
        c.create_line(
            *points, fill=color, width=2, arrow=tk.LAST, joinstyle=tk.ROUND,
            dash=() if link.source == "project" else (5, 3), tags=("wire",),
        )  # fmt: skip

    def _console_shown(self) -> bool:
        """The console is in its pane (not hidden, not popped out)."""
        panes = {str(pane) for pane in self._paned.panes()}
        return self._console_window is None and str(self._console) in panes

    def _restore_console_height(self) -> None:
        total = self._paned.winfo_height()
        if total > 1 and self._console_shown():
            self._paned.sashpos(0, max(MIN_RACK_H, total - self._console_h))

    def _show_console(self) -> None:
        window = self._console_window
        if window is not None:
            window.deiconify()
            window.lift()
        elif not self._console_shown():
            self._paned.add(self._console, weight=0)
            # Lay the new pane out first: a sash set before that is overridden, which
            # left the console as a sliver at the bottom.
            self._paned.update_idletasks()
            self._restore_console_height()
        self._console.focus_input()

    def _run_in_console(self, command: str) -> None:
        """Type *command* into the console pane and run it, showing the pane first."""
        self._show_console()
        if not self._console.run(command):
            self._show_action_error(
                "The console is still running a command. Wait for it, or press Stop."
            )

    def _add_analysis_items(self, menu: tk.Menu, address: str, *, output: bool = False) -> None:
        """Questions about *address*, answered in the console pane."""
        sim = self._simulation
        tag = sim.to_tag(address)
        state = tk.NORMAL if sim.is_ready and not self._console.busy else tk.DISABLED
        value = sim.values.get(address)
        if isinstance(value, bool):
            why = f"Why is it {'ON' if value else 'OFF'}?"
        else:
            why = "Why this value?" if value is not None else "Why?"
        menu.add_command(label=why, command=lambda: self._run_in_console(f"why {tag}"), state=state)
        if output:
            menu.add_command(
                label="Show simplified logic",
                command=lambda: self._run_in_console(f"simplified {tag}"),
                state=state,
            )
            how = tk.Menu(menu, tearoff=0)
            how.add_command(
                label="How to turn it ON", command=lambda: self._run_in_console(f"how {tag}")
            )
            how.add_command(
                label="How to turn it OFF", command=lambda: self._run_in_console(f"how ~{tag}")
            )
            menu.add_cascade(label="How (experimental)", menu=how, state=state)
        menu.add_separator()

    def _input_menu(self, event: tk.Event, address: str) -> None:
        sim = self._simulation
        menu = tk.Menu(self, tearoff=0)
        self._add_analysis_items(menu, address)
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
        self._add_link_items(menu, address, analog=False)
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
        # Shown instead of the switch while a feedback link drives this input.
        # Solid for the program's link, dashed outline for a bench link.
        pill = _round_rect(
            c, x + 6, cy - 8, x + 36, cy + 8, 7, fill=P.LINK, outline="", state="hidden",
            tags=(tag,),
        )  # fmt: skip
        pill_text = c.create_text(
            x + 21, cy, text="", fill=P.LINK_TEXT, font=_FONT_SMALL, state="hidden", tags=(tag,)
        )
        # Around the switch while the program's link is cut: the switch stands in for it.
        cut = _round_rect(
            c, x + 5, cy - 10, x + 35, cy + 10, 9, fill="", outline=P.LINK_CUT, width=2,
            dash=(3, 2), state="hidden", tags=(tag,),
        )  # fmt: skip
        self._tooltip_item((pill, pill_text, cut), lambda a=address: self._link_text(a))
        for item in (pill, pill_text):
            c.tag_bind(item, "<Enter>", lambda _e, a=address: self._show_wire(a), add="+")
            c.tag_bind(item, "<Leave>", lambda _e: c.delete("wire"), add="+")
        self._draw_label(x + 52, cy, address, x + self._card_w - BADGE_W, tag)
        badge = self._draw_badge(x + self._card_w - 11, cy, tag)
        self._inputs[address] = {
            "track": track, "knob": knob, "bezel": bezel, "cap": cap, "led": led,
            "badge": badge, "pending": pending, "pill": pill, "pill_text": pill_text,
            "cut": cut, "x": x, "cy": cy, "top": self._card_top, "gutter": self._card_gutter,
        }  # fmt: skip
        c.tag_bind(switch, "<ButtonPress-1>", lambda _e, a=address: self._on_switch_press(a))
        c.tag_bind(switch, "<ButtonRelease-1>", lambda _e, a=address: self._on_switch_release(a))

    def _output_menu(self, event: tk.Event, address: str) -> None:
        menu = tk.Menu(self, tearoff=0)
        self._add_analysis_items(menu, address, output=True)
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
        self._draw_label(x + 26, cy, address, x + self._card_w - BADGE_W, tag)
        badge = self._draw_badge(x + self._card_w - 11, cy, tag)
        self._outputs[address] = {
            "led": led, "badge": badge, "x": x, "top": self._card_top, "gutter": self._card_gutter,
        }  # fmt: skip
        self._tooltip_item((led,), lambda: "Drag onto an input to link it.")
        c.tag_bind(tag, "<ButtonPress-1>", lambda _e, a=address: self._start_link_drag(a))

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

    def _analog_menu(self, event: tk.Event, address: str, *, linkable: bool = False) -> None:
        menu = tk.Menu(self, tearoff=0)
        self._add_analysis_items(menu, address)
        menu.add_command(label="Force value...", command=lambda: self._force_analog(address))
        menu.add_command(
            label="Release force",
            command=lambda: self._simulation.release_force(address),
            state=tk.NORMAL if address in self._simulation.forces else tk.DISABLED,
        )
        if linkable:
            self._add_link_items(menu, address, analog=True)
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
            x, y, tag, lambda e, a=address: self._analog_menu(e, a, linkable=True),
            height=ANALOG_ROW_H,
        )  # fmt: skip
        self._draw_label(x + 10, y + 11, address, x + self._card_w - BADGE_W, tag)
        badge = self._draw_badge(x + self._card_w - 11, y + 11, tag)
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
        self._tooltip_item((live,), lambda a=address: self._link_text(a))
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
                c, from_=low, to=high, orient=tk.HORIZONTAL, length=self._card_w - 96,
                command=lambda value, a=address: self._on_slider(a, value),
            )  # fmt: skip
            c.create_window(x + self._card_w - 8, y + 32, window=scale, anchor="e")
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
        self._draw_label(x + 10, cy, address, x + self._card_w - 74, tag)
        value = c.create_text(
            x + self._card_w - BADGE_W - 2, cy, text="", anchor="e", fill=P.TEXT, font=_FONT_BOLD,
            tags=(tag,),
        )  # fmt: skip
        badge = self._draw_badge(x + self._card_w - 11, cy, tag)
        self._analog_out[address] = {"value": value, "badge": badge}

    # ------------------------------------------------------------------
    # Drawing: cards
    # ------------------------------------------------------------------

    @staticmethod
    def _card_height(inputs: int, outputs: int, ai: int, ao: int) -> float:
        height = HEADER_H + BODY_PAD
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
        return self._card_height(len(inputs), len(outputs), len(analog_in), len(analog_out))

    def _on_mode_click(self, event: tk.Event) -> None:
        _sx, sy, zone = self._mode_zone
        index = int((self._canvas.canvasy(event.y) - sy) // zone)
        if 0 <= index < len(_POSITIONS):
            self._simulation.set_switch_position(_POSITIONS[index])

    def _mode_text(self) -> str:
        """What the CPU's mode switch is doing, for its tooltip."""
        sim = self._simulation
        if not sim.is_ready:
            return sim.status_text
        if not sim.run_hint_seen:
            return "Flip to RUN to start the program, or STEP to scan one at a time."
        return {
            "stop": "STOP: the program is stopped and outputs are off.",
            "step": "STEP: scans advance only when you step.",
            "run": f"RUN: running at {sim.speed_text}.",
        }[sim.switch_position]

    def _draw_cpu_card(self, x: float, y: float, card: Card, height: float) -> None:
        """The slim CPU card: the vertical RUN / STEP / STOP switch over the PWR/RUN/ERR LEDs."""
        c = self._canvas
        self._draw_card_frame(x, y, height, "CPU", card.model, width=CPU_CARD_W)
        sx, sy, zone = x + 12, y + HEADER_H + 10, MODE_ZONE_H
        height = len(_POSITIONS) * zone
        self._mode_hint = _round_rect(
            c, sx - 5, sy - 4, sx + 72, sy + height + 4, 8, fill="", outline="", width=3
        )
        slot = _round_rect(
            c, sx, sy, sx + 24, sy + height, 7, fill=P.SWITCH_OFF, outline="", tags=("mode",)
        )
        self._mode_knob = _round_rect(
            c, sx + 2, sy + 2, sx + 22, sy + zone - 2, 6, fill=P.MODE_STOP, outline="",
            tags=("mode",),
        )  # fmt: skip
        self._mode_zone = (sx, sy, zone)
        items = [slot, self._mode_knob]
        for i, position in enumerate(_POSITIONS):
            self._mode_labels[position] = c.create_text(
                sx + 31, sy + (i + 0.5) * zone, text=SWITCH_LABELS[position], anchor="w",
                fill=P.TEXT, font=_FONT_BOLD, tags=("mode",),
            )  # fmt: skip
            items.append(self._mode_labels[position])
        c.tag_bind("mode", "<Button-1>", self._on_mode_click)
        c.tag_bind("mode", "<Enter>", lambda _e: c.configure(cursor="hand2"))
        c.tag_bind("mode", "<Leave>", lambda _e: c.configure(cursor=""))
        self._tooltip_item(tuple(items), self._mode_text)

        for i, name in enumerate(("PWR", "RUN", "ERR")):
            ly = sy + height + 14 + i * MODE_ZONE_H
            self._cpu_leds[name] = c.create_oval(
                x + 14, ly, x + 24, ly + 10, fill=P.LED_OFF, outline=P.LED_RIM
            )
            c.create_text(x + 30, ly + 5, text=name, anchor="w", fill=P.TEXT, font=_FONT_SMALL)

    def _card_subtitle(self, model: str, counts: tuple[int, int, int, int]) -> str:
        """The module's model and what it carries, or just the model when that won't fit."""
        parts = [model] + [
            f"{count} {label}"
            for count, label in zip(
                counts, ("inputs", "outputs", "analog in", "analog out"), strict=True
            )
            if count
        ]
        text = " \N{MIDDLE DOT} ".join(parts)
        return text if self._small.measure(text) <= self._card_w - 20 else model

    def _draw_card(self, x: float, y: float, card: Card) -> None:
        """A module's I/O; the CPU's own I/O is the card beside the slim CPU card."""
        inputs, outputs, analog_in, analog_out = self._card_parts(card)
        title = "Built-in I/O" if card.location == "cpu" else card.title
        counts = (len(inputs), len(outputs), len(analog_in), len(analog_out))
        subtitle = self._card_subtitle(card.model, counts)
        self._draw_card_frame(x, y, self._module_height(card), title, subtitle)
        self._card_top = y
        self._draw_rows(x, y + HEADER_H + BODY_PAD, inputs, outputs, analog_in, analog_out)

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
            font=_FONT_SMALL, width=self._card_w - 20,
        )  # fmt: skip

    def _draw_unassigned(self, x: float, y: float, layout: PanelLayout) -> None:
        inputs, outputs = layout.unassigned_inputs, layout.unassigned_outputs
        height = self._card_height(len(inputs), len(outputs), 0, 0)
        self._draw_card_frame(
            x, y, height, "Unassigned I/O", "Used, not on any module", dashed=True
        )
        self._card_top = y
        self._draw_rows(x, y + HEADER_H + BODY_PAD, inputs, outputs, (), ())

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

    def _fit_card_width(self, layout: PanelLayout | None) -> float:
        """A card width that shows every nickname on the panel in full.

        CLICK nicknames run to 24 characters; cards widen only as far as the
        longest one present needs, so short names keep the rack compact.
        """
        width = float(CARD_W)
        if layout is None:
            return width
        # Where each kind of row starts its label, and what sits right of the nickname.
        rows = (("input", 52, BADGE_W), ("output", 26, BADGE_W), ("analog_in", 10, BADGE_W),
                ("analog_out", 10, 74))  # fmt: skip
        for kind, start, right in rows:
            for address in layout.addresses(kind):
                nickname = self._names(address)[0]
                if nickname:
                    label = self._mono.measure(address) + 5 + self._font.measure(nickname)
                    width = max(width, start + label + right + 4)
        return float(width)

    def _pieces(self, layout: PanelLayout | None) -> list[_Piece]:
        """Everything to draw, in rack order."""
        pieces: list[_Piece] = []
        if layout is None or not layout.has_cpu:
            pieces.append(
                _Piece(self._card_w, self._placeholder_height(), self._draw_placeholder, False)
            )
        if layout is None:
            return pieces
        # The CPU card stands as tall as the I/O cards in its housing.
        housing = [card for card in layout.cards if card.location in ("cpu", "slot")]
        cpu_h = max([CPU_CARD_MIN_H] + [self._module_height(card) for card in housing])
        for card in layout.cards:
            draw = partial(self._draw_card, card=card)
            if card.location == "cpu":
                pieces.append(
                    _Piece(CPU_CARD_W, cpu_h, partial(self._draw_cpu_card, card=card, height=cpu_h))
                )
                if any(self._card_parts(card)):
                    pieces.append(
                        _Piece(self._card_w, self._module_height(card), draw, gap=HOUSING_GAP)
                    )
            else:
                gap = HOUSING_GAP if card.location == "slot" else CARD_GAP
                pieces.append(_Piece(self._card_w, self._module_height(card), draw, gap=gap))
        if layout.unassigned_inputs or layout.unassigned_outputs:
            n_in, n_out = len(layout.unassigned_inputs), len(layout.unassigned_outputs)
            height = self._card_height(n_in, n_out, 0, 0)
            pieces.append(
                _Piece(self._card_w, height, partial(self._draw_unassigned, layout=layout), False)
            )
        return pieces

    def _flow(self, pieces: list[_Piece]) -> list[list[_Piece]]:
        """*pieces* wrapped into rack rows that fit the canvas, keeping rack order."""
        width = self._canvas.winfo_width()
        if width <= 1:  # not laid out yet
            width = self._requested_width
        room = width - 2 * MARGIN
        rows: list[list[_Piece]] = []
        used = 0.0
        for piece in pieces:
            if rows and rows[-1] and used + piece.gap + piece.width <= room:
                rows[-1].append(piece)
                used += piece.gap + piece.width
            else:
                rows.append([piece])
                used = piece.width
        return rows

    # ------------------------------------------------------------------
    # Live updates (no redraw)
    # ------------------------------------------------------------------

    def _show_badge(self, badge: tuple[int, ...], forced: bool) -> None:
        for item in badge:
            self._canvas.itemconfigure(item, state="normal" if forced else "hidden")

    def _show_link_chip(self, info: dict[str, Any], link: WiredLink | None) -> None:
        c = self._canvas
        if link is None or link.enable is None:
            c.itemconfigure(info["pill"], state="hidden")
            c.itemconfigure(info["pill_text"], state="hidden")
            return
        if link.source == "project":
            c.itemconfigure(info["pill"], fill=P.LINK, outline="", dash=(), state="normal")
            c.itemconfigure(info["pill_text"], text=link.enable, fill=P.LINK_TEXT, state="normal")
        else:
            c.itemconfigure(
                info["pill"], fill=P.LINK_BENCH_BG, outline=P.LINK_BENCH, dash=(3, 2),
                state="normal",
            )  # fmt: skip
            c.itemconfigure(info["pill_text"], text=link.enable, fill=P.LINK_BENCH, state="normal")

    def _refresh_inputs(self, values: dict, forces: dict, pending: dict) -> None:
        c = self._canvas
        sim = self._simulation
        for address, info in self._inputs.items():
            on = sim.switch_on(address)
            x, cy = info["x"], info["cy"]
            link = sim.driving_link(address)
            self._show_link_chip(info, link)
            # While the link's delay counts, the chip counts down (simulated time).
            countdown = sim.link_countdown(address) if link is not None else None
            if countdown is not None:
                c.itemconfigure(info["pill_text"], text=_countdown_text(countdown))
            momentary = sim.is_momentary(address)
            toggle_state = "hidden" if momentary or link else "normal"
            button_state = "normal" if momentary and not link else "hidden"
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
            waiting = address in pending or countdown is not None
            c.itemconfigure(info["pending"], state="normal" if waiting else "hidden")
            bench = sim.bench_links.get(address)
            cut = bench is not None and bench.cut and bench.enabled and sim.bench_wiring
            c.itemconfigure(info["cut"], state="normal" if cut else "hidden")

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
            link = self._simulation.driving_link(address)
            entry_state = "disabled" if link else "normal"
            if str(info["entry"].cget("state")) != entry_state:
                info["entry"].configure(state=entry_state)
                if "scale" in info:
                    info["scale"].state(["disabled"] if link else ["!disabled"])
            if link is not None:
                color = P.LINK if link.source == "project" else P.LINK_BENCH
                kind = (link.profile or "delay").partition(":")[0]
                c.itemconfigure(
                    info["live"], text=f"\N{LEFTWARDS ARROW} {link.enable} {kind}", fill=color
                )
                info["var"].set(_value_text(live) if live is not None else "")
                self._show_badge(info["badge"], address in forces)
                continue
            c.itemconfigure(info["live"], fill=P.MUTED)
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
        ky = sy + _POSITIONS.index(position) * zone
        c.coords(self._mode_knob, *_rounded_points(sx + 2, ky + 2, sx + 22, ky + zone - 2, 6))
        c.itemconfigure(self._mode_knob, fill=_POSITION_COLORS[position] if ready else P.LED_OFF)
        for pos, label in self._mode_labels.items():
            color = _POSITION_COLORS[pos] if ready and pos == position else P.MUTED
            c.itemconfigure(label, fill=color)

        hint = ready and not sim.run_hint_seen
        if self._mode_hint is not None:
            c.itemconfigure(self._mode_hint, outline=P.HINT if hint and self._blink else "")

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
        if ready and not sim.run_hint_seen:
            status = "Flip the CPU to RUN to start."
        else:
            status = sim.source_text if ready else sim.status_text
        self._status_var.set(status)
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

        plc_data = sim.plc_data_path
        name = plc_data.name if plc_data is not None else ""
        if len(name) > PLC_DATA_NAME_MAX:
            name = name[: PLC_DATA_NAME_MAX - 1] + "\N{HORIZONTAL ELLIPSIS}"
        self._plc_data_btn.configure(text=f"PLC Data: {name}" if name else "PLC Data...")

        count = len(sim.forces)
        self._forces_btn.configure(text=f"Forces ({count})" if count else "Forces")
        bench = len(sim.bench_links)
        wiring = f"Wiring ({bench} bench)" if bench else "Wiring"
        if not sim.bench_wiring and bench:
            wiring += " off"
        self._wiring_btn.configure(text=wiring)
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

        layout = self._simulation.layout
        self._card_w = self._fit_card_width(layout)
        self._drawn_pieces = self._pieces(layout)
        rows = self._flow(self._drawn_pieces)
        self._drawn_rows = tuple(len(row) for row in rows)
        y = float(MARGIN)
        widest = 0.0
        for row in rows:
            x = float(MARGIN) - row[0].gap
            rail: list[float] = []
            for piece in row:
                x += piece.gap
                # Wires run down the middle of the gap left of the card.
                self._card_gutter = x - (piece.gap if x > MARGIN else MARGIN) / 2
                piece.draw(x, y)
                if piece.on_rail:
                    rail.extend((x, x + piece.width))
                x += piece.width
            if rail:
                self._draw_rail(min(rail) - 6, max(rail) + 6, y + 70)
            widest = max(widest, x)
            y += max(piece.height for piece in row) + ROW_GAP
        c.configure(scrollregion=(0, 0, widest + MARGIN, y + MARGIN))
        if layout is not None:
            self._simulation.watch(self, layout.poll_addresses)
        self._refresh_dynamic()

    def _on_canvas_resized(self, _event: tk.Event) -> None:
        if tuple(len(row) for row in self._flow(self._drawn_pieces)) != self._drawn_rows:
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

    def _populate_wiring_menu(self) -> None:
        menu = self._wiring_menu
        menu.delete(0, tk.END)
        sim = self._simulation
        self._bench_var.set(sim.bench_wiring)
        menu.add_checkbutton(
            label="Apply bench links",
            variable=self._bench_var,
            command=lambda: sim.set_bench_wiring(self._bench_var.get()),
        )
        menu.add_separator()
        links = sorted(sim.links, key=lambda link: (link.source != "project", link.feedback))
        if not links:
            menu.add_command(label="No links", state=tk.DISABLED)
        self._link_vars = []
        self._wiring_entries = {}
        for link in links:
            nickname = self._names(link.feedback)[0]
            name = f"{link.feedback} {nickname}" if nickname else link.feedback
            if link.cut:
                label = f"{name}: program link cut"
            else:
                when = when_text(link.enable, link.trigger)
                label = f"{name} \N{LEFTWARDS ARROW} {link.enable}{when}   {link.response}"
            if link.source == "project":
                suffix = "" if link.active else "   (changed on the bench)"
                menu.add_command(label=f"{label}   program{suffix}", state=tk.DISABLED)
            else:
                var = tk.BooleanVar(value=link.enabled)
                self._link_vars.append(var)
                menu.add_checkbutton(
                    label=f"{label}   bench",
                    variable=var,
                    command=lambda f=link.feedback, v=var: sim.set_link_enabled(f, v.get()),
                )
            index = menu.index(tk.END)
            if index is not None and not link.cut:
                self._wiring_entries[index] = link.feedback
        if sim.bench_links:
            menu.add_separator()
            menu.add_command(label="Discard bench links", command=sim.discard_bench_links)

    def _on_wiring_select(self, _event: tk.Event | None = None) -> None:
        """Draw the wire of the link under the pointer in the Wiring menu (none once it closes)."""
        try:
            index = self._wiring_menu.index("active")
        except tk.TclError:
            index = None
        feedback = self._wiring_entries.get(index) if index is not None else None
        if feedback is None:
            self._canvas.delete("wire")
        else:
            self._show_wire(feedback)

    def _on_any_release(self, _event: tk.Event | None) -> None:
        # The pointer can leave the switch before the button comes up.
        if self._held is not None:
            held, self._held = self._held, None
            self._simulation.release_input(held)
        self._dragging = False
        self._end_link_drag()

    def _on_speed_selected(self, _event: object = None) -> None:
        text = self._speed_var.get()
        for speed in SPEEDS:
            if format_speed(speed) == text:
                self._simulation.set_speed(speed)
                return

    def _browse_plc_data(self) -> None:
        """Start the simulation from a CLICK data dump (the session watches it for changes)."""
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

    def _hide_console(self) -> None:
        if self._console_shown():
            # A pane dragged nearly shut comes back at the slim default, not as a sliver.
            height = self._paned.winfo_height() - self._paned.sashpos(0)
            self._console_h = height if height >= MIN_CONSOLE_H else CONSOLE_H
            self._paned.forget(self._console)

    def _toggle_console(self) -> None:
        if self._console_shown():
            self._hide_console()
        else:
            self._show_console()

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

        console_btn = ttk.Button(bar, text="Console", command=self._toggle_console)
        console_btn.pack(side=tk.RIGHT)
        bind_tooltip(console_btn, "Show or hide the command console (Ctrl+`)")
        ttk.Button(bar, text="Dataview", command=self._open_dataview).pack(
            side=tk.RIGHT, padx=(0, 4)
        )
        # Names the loaded file: it sets where both the panel and the console start.
        self._plc_data_btn = ttk.Button(bar, text="PLC Data...", command=self._browse_plc_data)
        self._plc_data_btn.pack(side=tk.RIGHT, padx=(0, 4))
        bind_tooltip(
            self._plc_data_btn,
            "Start from the PLC's live values: a CSV saved in CLICK with\n"
            "PLC > Read Data from PLC > All > Save (not the nickname CSV).\n"
            "Switches and analog values take the file's values, and the\n"
            "simulation reloads whenever the file changes.",
        )
        self._forces_btn = ttk.Menubutton(bar, text="Forces")
        self._forces_menu = tk.Menu(
            self._forces_btn, tearoff=0, postcommand=self._populate_forces_menu
        )
        self._forces_btn.configure(menu=self._forces_menu)
        self._forces_btn.pack(side=tk.RIGHT, padx=(0, 12))
        self._wiring_btn = ttk.Menubutton(bar, text="Wiring")
        self._wiring_menu = tk.Menu(
            self._wiring_btn, tearoff=0, postcommand=self._populate_wiring_menu
        )
        self._wiring_btn.configure(menu=self._wiring_menu)
        self._wiring_menu.bind("<<MenuSelect>>", self._on_wiring_select)
        self._wiring_btn.pack(side=tk.RIGHT, padx=(0, 4))
        bind_tooltip(
            self._wiring_btn,
            "Feedback links: which output drives which input, from the program\n"
            "and from the bench. Right-click an input to link, cut or save one.",
        )
        modbus = ttk.Label(bar, textvariable=self._modbus_var, foreground=P.MUTED)
        modbus.pack(side=tk.RIGHT, padx=(0, 12))
        bind_tooltip(
            modbus,
            "The simulated PLC's Modbus TCP server. Point an HMI or other Modbus "
            "client here; the count excludes this window's own connection.",
        )

        self._banner = ttk.Frame(self)

    def _create_canvas(self) -> None:
        # The rack over the console pane; the rack takes any height the window gains.
        self._paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self._paned.pack(fill=tk.BOTH, expand=True)
        frame = ttk.Frame(self._paned)
        self._paned.add(frame, weight=1)
        self._canvas = tk.Canvas(frame, background=P.RACK_BG, highlightthickness=0)
        ybar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=ybar.set)
        ybar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas.bind("<ButtonRelease-1>", self._on_any_release, add="+")
        self._canvas.bind("<B1-Motion>", self._on_link_drag, add="+")
        self._canvas.bind("<Configure>", self._on_canvas_resized, add="+")
        self._canvas.bind(
            "<MouseWheel>", lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units")
        )

    # ------------------------------------------------------------------
    # Console pane
    # ------------------------------------------------------------------

    def _console_options(self) -> dict[str, Any]:
        return {
            "simulation": self._simulation,
            "get_analysis": self._get_analysis,
            "filter_func": self._filter_func,
            "transcript": self._console_transcript,
            "history": self._console_history,
        }

    def _resize_console(self, y_root: int, start: bool) -> None:
        """Move the sash with the console's header, keeping the grab point under the pointer."""
        if not self._console_shown():
            return
        top = self._paned.winfo_rooty()
        if start:
            self._resize_grab = y_root - top - self._paned.sashpos(0)
            return
        limit = self._paned.winfo_height() - MIN_CONSOLE_H
        position = y_root - top - self._resize_grab
        self._paned.sashpos(0, max(MIN_RACK_H, min(position, limit)))

    def _new_console_panel(self) -> ConsolePanel:
        return ConsolePanel(
            self._paned,
            on_pop=self._pop_out_console,
            on_hide=self._hide_console,
            on_resize=self._resize_console,
            **self._console_options(),
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
        self._console.close()
        if self._console_window is not None:
            self._console_window.destroy()
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
        get_analysis: Callable[[], AnalysisService | None],
        open_dataview: Callable[[], None],
        filter_func: Callable[[list[str], str], list[str]] | None = None,
        on_destroy: Callable[[], None] | None = None,
        title_suffix: str = "",
    ) -> None:
        super().__init__(parent)
        self._simulation = simulation
        self._get_store = get_store
        self._get_analysis = get_analysis
        self._open_dataview = open_dataview
        self._filter_func = filter_func
        self._on_destroy = on_destroy
        self._title_suffix = title_suffix
        self._destroyed = False

        self.title(f"Simulator — {title_suffix}" if title_suffix else "Simulator")
        self._requested_width = 1180
        self._card_w = float(CARD_W)
        self._card_top = 0.0
        self._card_gutter = 0.0
        self.geometry(f"{self._requested_width}x760")
        self.minsize(480, 360)

        self._font = tkfont.Font(self, font=_FONT)
        self._mono = tkfont.Font(self, font=_FONT_MONO)
        self._small = tkfont.Font(self, font=_FONT_SMALL)
        self._inputs: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, dict[str, Any]] = {}
        self._analog_in: dict[str, dict[str, Any]] = {}
        self._analog_out: dict[str, dict[str, Any]] = {}
        self._cpu_leds: dict[str, int] = {}
        self._mode_labels: dict[str, int] = {}
        self._mode_knob: int | None = None
        self._mode_hint: int | None = None
        self._mode_zone: tuple[float, float, float] = (0, 0, 0)
        self._widgets: list[tk.Widget] = []
        self._held: str | None = None
        self._link_drag: dict[str, Any] | None = None
        self._dragging = False
        self._blink = False
        self._speed_box_focused = False
        self._last_error: str | None = None
        self._note: str | None = None
        self._bench_var = tk.BooleanVar(value=True)
        self._link_vars: list[tk.BooleanVar] = []
        # Wiring menu entry index -> the feedback whose wire it shows on hover.
        self._wiring_entries: dict[int, str] = {}
        self._banner_key: tuple = ()
        self._tick_after_id: str | None = None
        self._tooltip: tk.Toplevel | None = None
        self._drawn_pieces: list[_Piece] = []
        self._drawn_rows: tuple[int, ...] = ()

        self._status_var = tk.StringVar()
        self._scan_var = tk.StringVar()
        self._modbus_var = tk.StringVar()
        self._speed_var = tk.StringVar(value=format_speed(simulation.speed))
        self._actual_var = tk.StringVar()
        self._step_count_var = tk.StringVar(value="10")
        self._run_for_var = tk.StringVar(value="1 s")

        # The console's transcript and history outlive any one panel showing them.
        self._console_transcript: Transcript = []
        self._console_history: list[str] = []
        self._console_window: ConsoleWindow | None = None
        self._console_h = CONSOLE_H
        # Where in the header the pointer grabbed it, measured from the sash.
        self._resize_grab = 0

        self._create_toolbar()
        self._create_canvas()
        # Open from the start, slim, so the simulation's startup shows in it.
        self._console = self._new_console_panel()
        self._paned.add(self._console, weight=0)
        self.bind("<Control-grave>", lambda _e: self._toggle_console())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._observed_store = get_store()
        if self._observed_store is not None:
            self._observed_store.add_observer(self._on_store_changed)
        # The opener turns the simulation on; the hardware shows either way.
        simulation.add_listener(self._on_simulation_event)
        simulation.refresh_layout()
        self._redraw()
        self._tick_after_id = self.after(TICK_MS, self._tick)

    def _pop_out_console(self) -> None:
        """Move the console to its own window, transcript and history included."""
        if self._console.busy:
            return
        self._hide_console()
        self._console.close()
        title = f"Console \N{EM DASH} {self._title_suffix}" if self._title_suffix else "Console"
        window = ConsoleWindow(
            self, title=title, on_dock=self._dock_console, **self._console_options()
        )
        self._console_window = window
        self._console = window.panel

    def _dock_console(self) -> None:
        """Close the console's own window and put it back in its pane."""
        window = self._console_window
        if window is None:
            return
        self._console_window = None
        self._console.close()
        window.destroy()
        self._console = self._new_console_panel()
        self._show_console()

    def _dismiss_note(self) -> None:
        self._note = None
        self._refresh_banners()

    def _dismiss_error(self) -> None:
        self._last_error = None
        self._refresh_banners()
