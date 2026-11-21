"""Drive the real Simulator window with synthetic Tk events.

record_simulator_gif.py records a walkthrough with ``Driver``. click_smoke.py presses the
panel with it in its ``panel`` check. A scene is a generator that yields the seconds to wait
before its next step.

``Driver`` moves a drawn pointer and shows each click on it. The object that draws it is a
``Pointer``. The recorder's ``Recorder`` draws it into the gif. The smoke passes an object that
draws nothing.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from clicknick.simulation_session import SimulationSession
    from clicknick.views.simulator_window import SimulatorWindow


class Pointer(Protocol):
    """The pointer that ``Driver`` moves.

    Its position is in pixels from the top left corner of the captured area.
    """

    # The captured area on the screen: left, top, right, bottom
    bounds: tuple[int, int, int, int]
    pointer: tuple[int, int]

    def show_click(self, seconds: float = ...) -> None:
        """Show a click at the pointer for *seconds*."""
        ...


Scene = Iterator[float]


class MenuLookalike:
    """Draws a real menu's entries in a plain window, in the colors of Tk's native menus.

    Windows' popup runs its own loop until it is dismissed. That would stall a scene.
    """

    BACKGROUND = "#f0f0f0"
    TEXT = "#000000"
    DISABLED = "#a0a0a0"
    ACTIVE = "#0078d7"
    ACTIVE_TEXT = "#ffffff"

    def __init__(self, parent: tk.Misc, menu: tk.Menu, x_root: int, y_root: int) -> None:
        self.window = tk.Toplevel(parent, bg="#a0a0a0", padx=1, pady=1)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        body = tk.Frame(self.window, bg=self.BACKGROUND, pady=3)
        body.pack()
        self.rows: dict[str, tuple[int, tk.Frame, list[tk.Label]]] = {}
        for index in range(cast(int, menu.index("end")) + 1):
            if menu.type(index) == "separator":
                tk.Frame(body, bg="#c8c8c8", height=1).pack(fill="x", padx=4, pady=4)
                continue
            label = menu.entrycget(index, "label")
            enabled = menu.entrycget(index, "state") != "disabled"
            style: dict[str, Any] = {
                "bg": self.BACKGROUND,
                "fg": self.TEXT if enabled else self.DISABLED,
                "font": ("Segoe UI", 9),
            }
            row = tk.Frame(body, bg=self.BACKGROUND)
            row.pack(fill="x")
            text = tk.Label(row, text=label, anchor="w", padx=26, pady=3, **style)
            text.pack(side="left")
            mark = "›" if menu.type(index) == "cascade" else ""
            arrow = tk.Label(row, text=mark, padx=8, **style)
            arrow.pack(side="right")
            self.rows[label] = (index, row, [text, arrow])
        self.window.geometry(f"+{x_root}+{y_root}")
        self.window.update()

    def row_center(self, label: str) -> tuple[int, int]:
        """Return the screen coordinates of the middle of *label*'s row."""
        _index, row, _labels = self.rows[label]
        return (
            row.winfo_rootx() + row.winfo_width() // 2,
            row.winfo_rooty() + row.winfo_height() // 2,
        )

    def highlight(self, label: str) -> None:
        _index, row, labels = self.rows[label]
        row.configure(bg=self.ACTIVE)
        for widget in labels:
            widget.configure(bg=self.ACTIVE, fg=self.ACTIVE_TEXT)
        self.window.update()


class Driver:
    def __init__(self, win: SimulatorWindow, sim: SimulationSession, recorder: Pointer) -> None:
        self.win = win
        self.sim = sim
        self.recorder = recorder
        self.left, self.top = recorder.bounds[:2]

    # -- Finding things on screen ------------------------------------------

    def _canvas_point(self, canvas_x: float, canvas_y: float) -> tuple[int, int]:
        canvas = self.win._canvas
        return (
            round(canvas_x - canvas.canvasx(0)) + canvas.winfo_rootx() - self.left,
            round(canvas_y - canvas.canvasy(0)) + canvas.winfo_rooty() - self.top,
        )

    def _item_point(self, item: int) -> tuple[int, int]:
        x0, y0, x1, y1 = self.win._canvas.bbox(item)
        return self._canvas_point((x0 + x1) / 2, (y0 + y1) / 2)

    def switch_point(self, address: str) -> tuple[int, int]:
        # A Momentary input shows a pushbutton cap. Its toggle knob is hidden and has no bbox.
        if not self.sim.is_momentary(address):
            return self._item_point(self.win._inputs[address]["knob"])
        # Press the bezel just below the cap, so the arrow doesn't hide it lighting up.
        x, y = self._item_point(self.win._inputs[address]["cap"])
        return x, y + 6

    def output_point(self, address: str) -> tuple[int, int]:
        return self._item_point(self.win._outputs[address]["led"])

    def padlock_point(self, address: str) -> tuple[int, int]:
        """Return the middle of the padlock of the forced output *address*.

        The padlock is hidden while the output is not forced, and a hidden item has no bbox.
        """
        return self._item_point(self.win._outputs[address]["badge"][1])

    def mode_point(self, position: str) -> tuple[int, int]:
        return self._item_point(self.win._mode_labels[position])

    def input_point(self) -> tuple[int, int]:
        entry = self.win._console._console_input
        return (
            entry.winfo_rootx() - self.left + entry.winfo_width() // 3,
            entry.winfo_rooty() - self.top + entry.winfo_height() // 2,
        )

    # -- Actions -----------------------------------------------------------

    def wait_until(self, condition: Callable[[], bool], what: str, timeout: float = 30.0) -> Scene:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise TimeoutError(f"timed out waiting for {what}")
            yield 0.05

    def move(self, target: tuple[int, int], seconds: float = 0.6) -> Scene:
        start = self.recorder.pointer
        steps = max(1, round(seconds / 0.03))
        for step in range(1, steps + 1):
            eased = (1 - math.cos(math.pi * step / steps)) / 2
            self.recorder.pointer = (
                round(start[0] + (target[0] - start[0]) * eased),
                round(start[1] + (target[1] - start[1]) * eased),
            )
            yield 0.03

    def _canvas_event(self, sequence: str, point: tuple[int, int]) -> None:
        canvas = self.win._canvas
        canvas.event_generate(
            sequence,
            x=point[0] + self.left - canvas.winfo_rootx(),
            y=point[1] + self.top - canvas.winfo_rooty(),
        )

    def click(self, point: tuple[int, int], *, hold: float = 0.12) -> Scene:
        yield from self.move(point)
        self._canvas_event("<Motion>", point)
        self.recorder.show_click()
        self._canvas_event("<ButtonPress-1>", point)
        yield hold
        self._canvas_event("<ButtonRelease-1>", point)

    def double_click(self, point: tuple[int, int]) -> Scene:
        yield from self.move(point)
        self._canvas_event("<Motion>", point)
        self.recorder.show_click()
        # Tk recognizes the double-click from the second press following the first.
        self._canvas_event("<ButtonPress-1>", point)
        self._canvas_event("<ButtonRelease-1>", point)
        self._canvas_event("<ButtonPress-1>", point)
        yield 0.12
        self._canvas_event("<ButtonRelease-1>", point)

    def _right_click_menu(self, point: tuple[int, int]) -> tk.Menu:
        """Right-click *point* and return the menu the app built, without posting it."""
        built: list[tk.Menu] = []
        real_popup = tk.Menu.tk_popup
        tk.Menu.tk_popup = lambda menu, *_args, **_kwargs: built.append(menu)  # type: ignore[method-assign]
        try:
            self._canvas_event("<Motion>", point)
            self._canvas_event("<ButtonPress-3>", point)
            self._canvas_event("<ButtonRelease-3>", point)
        finally:
            tk.Menu.tk_popup = real_popup  # type: ignore[method-assign]
        return built[0]

    def choose_from_menu(self, point: tuple[int, int], label: str) -> Scene:
        """Right-click *point*, then run the app's own *label* entry from a drawn menu."""
        yield from self.move(point)
        self.recorder.show_click()
        menu = self._right_click_menu(point)
        self.leave_canvas()
        drawn = MenuLookalike(self.win, menu, point[0] + self.left, point[1] + self.top)
        yield 0.8
        x_root, y_root = drawn.row_center(label)
        yield from self.move((x_root - self.left, y_root - self.top), 0.45)
        drawn.highlight(label)
        yield 0.5
        self.recorder.show_click()
        yield 0.12
        drawn.window.destroy()
        menu.invoke(drawn.rows[label][0])
        menu.destroy()
        yield 0.1
        yield from self.wait_until(
            lambda: not self.win._console.busy, f"the Console command from {label!r}", 30
        )

    def park(self) -> Scene:
        """Move the pointer into the empty rack, off anything worth watching."""
        canvas = self.win._canvas
        yield from self.move(
            (
                canvas.winfo_rootx() - self.left + canvas.winfo_width() * 3 // 4,
                canvas.winfo_rooty() - self.top + canvas.winfo_height() * 2 // 3,
            ),
            0.4,
        )

    def click_input(self) -> Scene:
        """Click into the command line, then move the pointer off the Console's output."""
        yield from self.move(self.input_point())
        self.recorder.show_click()
        self.win._console._console_input.focus_force()
        yield 0.25
        yield from self.park()

    def leave_canvas(self) -> None:
        """Clear any hover tooltip the last click left behind."""
        self._canvas_event("<Leave>", (0, 0))

    def _dropdown_above_input(self) -> None:
        """Open completions upward, as they do at the bottom of the screen.

        The input is the window's last row, so the completions would otherwise fall outside the
        capture.
        """
        entry = self.win._console._console_input
        if not entry._dropdown.is_dropdown_open():
            return
        popdown = entry.tk.call("ttk::combobox::PopdownWindow", entry)
        entry.update_idletasks()
        height = int(entry.tk.call("winfo", "height", popdown))
        position = f"+{entry.winfo_rootx()}+{entry.winfo_rooty() - height}"
        entry.tk.call("wm", "geometry", popdown, position)

    def type_text(self, text: str, per_char: float = 0.09) -> Scene:
        entry = self.win._console._console_input
        for char in text:
            keysym = "space" if char == " " else char
            entry.event_generate(f"<KeyPress-{keysym}>")
            entry.event_generate(f"<KeyRelease-{keysym}>")
            self._dropdown_above_input()
            yield per_char

    def tab_accept(self) -> None:
        self.win._console._console_input.event_generate("<KeyPress-Tab>")

    def enter(self) -> None:
        self.win._console._console_input.event_generate("<KeyPress-Return>")

    def command(self, parts: list[str]) -> Scene:
        """Type *parts*, taking each completed word from the dropdown with Tab.

        A part ending in ``|`` is typed up to the bar and then accepted with Tab.
        """
        console = self.win._console
        console.focus_input()
        console._console_input.focus_force()
        yield 0.2
        for part in parts:
            if part.endswith("|"):
                yield from self.type_text(part[:-1])
                yield 0.4
                self.tab_accept()
                yield 0.25
            else:
                yield from self.type_text(part)
        yield 0.3
        self.enter()
        yield 0.1
        yield from self.wait_until(lambda: not self.win._console.busy, "the console command", 90)
        yield 0.1

    def output(self, address: str) -> object:
        return self.sim.values.get(address)
