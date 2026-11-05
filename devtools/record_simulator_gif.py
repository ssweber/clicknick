"""Record the Simulator + Console walkthrough for docs/tour/offline-console.md.

Needs no CLICK install. The only mock is the connection to CLICK: this script
exports a conveyor program to CLICK ladder CSVs and nicknames, generates the
pyrung workspace from them the way a build does, and writes a Project.ini for
the hardware. Everything after that is real: SimulatorWindow, its ConsolePanel,
SimulationSession, the pyrung DAP subprocess and its Modbus server.

    uv run --with pillow python devtools/record_simulator_gif.py

While pyrung's release is pending, set UV_NO_SYNC=1 so `uv run` keeps the editable
sibling checkouts from `make install-dev`.

Input is synthetic Tk events, so your own mouse is left alone, but the window
takes keyboard focus and stays on top while recording. The screen is captured,
because the completion dropdown is its own window. The pointer is drawn on
afterwards. The simulator listens on Modbus port 502, so close any running
simulation first.

To try encoding settings without recording again, add `--capture PATH` once, then
use `--from-capture PATH` with `--speed`, `--fps`, `--ticker-fps` or `--colors`.
"""

from __future__ import annotations

import argparse
import ctypes
import math
import pickle
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
import zlib
from collections.abc import Callable, Iterator
from ctypes import wintypes
from dataclasses import astuple, dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageGrab
from pyclickplc import read_csv
from pyrung import (
    And,
    Bool,
    Counter,
    Int,
    Or,
    Timer,
    branch,
    comment,
    copy,
    count_up,
    latch,
    named_array,
    on_delay,
    out,
    program,
    reset,
    rise,
    rung,
)
from pyrung.click import (
    ClickBlocks,
    TagMap,
    ladder_to_pyrung,
    ladder_to_pyrung_project,
    pyrung_to_ladder,
)
from pyrung.core.analysis import build_program_graph

from clicknick.app import ICON_PNG_BASE64  # Also makes the process DPI-aware, as the app is.
from clicknick.services.analysis_service import (
    AnalysisResult,
    AnalysisService,
    AnalysisStatus,
    _build_tag_addr_key_map,
)
from clicknick.simulation_session import SimStatus, SimulationSession
from clicknick.views.simulator_window import SimulatorWindow

PROJECT_FILE = "ClickConveyor.ckp"
#: C0-11DD1E-D CPU (X001-X008, Y001-Y006) and a C0-08ND3 expansion (X101-X108).
PROJECT_INI = "[SystemConfig]\nItem1=212\nItem2=8\n"
#: Draw the UI as a 125% display does. Fonts get real extra pixels, so text stays sharp;
#: resizing a capture would only blur it.
UI_SCALE = 1.25
WINDOW_SIZE = (1125, 850)
CONSOLE_HEIGHT = 350
CAPTURE_FPS = 15
#: The highlight on the pointer, a big translucent dot so it reads at any gif scale.
DOT_RADIUS = 30
DOT_COLOR = (255, 214, 0)
DOT_ALPHA = 0.5
#: A click turns the dot orange and swells it for this long after the press.
CLICK_SECONDS = 0.45
CLICK_COLOR = (255, 90, 0)
CLICK_ALPHA = 0.65

# ---------------------------------------------------------------------------
# The mocked CLICK project: pyrung's examples/click_conveyor.py, with BinBSensor
# on the expansion because no CLICK CPU has an X009.
# ---------------------------------------------------------------------------

x, y, c, t, ct, sc, ds, dd, dh, df, xd, yd, xd0u, yd0u, td, ctd, sd, txt = ClickBlocks()

StartBtn = Bool()
StopCircuitOK = Bool()
EstopOK = Bool()
Auto = Bool()
Manual = Bool()
EntrySensor = Bool()
DiverterBtn = Bool()
BinASensor = Bool()
BinBSensor = Bool()
ConveyorMotor = Bool()
DiverterCmd = Bool()
StatusLight = Bool()
Running = Bool()
IsLarge = Bool()
CountReset = Bool()


@named_array(Int, stride=4, readonly=True)
class SortState:
    IDLE = 0
    DETECTING = 1
    SORTING = 2
    RESETTING = 3


SortState = cast(Any, SortState)

State = Int(choices=SortState)
SizeReading = Int()
SizeThreshold = Int()
DetTimer = Timer.clone("DetTimer")
HoldTimer = Timer.clone("HoldTimer")
BinACounter = Counter.clone("BinACounter")
BinBCounter = Counter.clone("BinBCounter")

mapping = TagMap(
    [
        StartBtn.map_to(x[1]),
        StopCircuitOK.map_to(x[2]),
        EstopOK.map_to(x[3]),
        Auto.map_to(x[4]),
        Manual.map_to(x[5]),
        EntrySensor.map_to(x[6]),
        DiverterBtn.map_to(x[7]),
        BinASensor.map_to(x[8]),
        BinBSensor.map_to(x[101]),
        ConveyorMotor.map_to(y[1]),
        DiverterCmd.map_to(y[2]),
        StatusLight.map_to(y[3]),
        Running.map_to(c[1]),
        IsLarge.map_to(c[2]),
        CountReset.map_to(c[3]),
        *SortState.map_to(ds.select(1, 4)),
        State.map_to(ds[5]),
        SizeReading.map_to(ds[6]),
        SizeThreshold.map_to(ds[7]),
        DetTimer.Done.map_to(t[1]),
        DetTimer.Acc.map_to(td[1]),
        HoldTimer.Done.map_to(t[2]),
        HoldTimer.Acc.map_to(td[2]),
        BinACounter.Done.map_to(ct[1]),
        BinACounter.Acc.map_to(ctd[1]),
        BinBCounter.Done.map_to(ct[2]),
        BinBCounter.Acc.map_to(ctd[2]),
    ],
    include_system=False,
)


@program
def logic():
    comment("Start/stop: the NC stop button resets when pressed or a wire breaks")
    with rung(StartBtn, Or(Auto, Manual)):
        latch(Running)
    with rung(~StopCircuitOK):
        reset(Running)
    with rung(~EstopOK):
        reset(Running)

    comment("Motor output: EstopOK gates all outputs")
    with rung(EstopOK):
        with branch(Running):
            out(ConveyorMotor)
        with branch(Running):
            out(StatusLight)

    comment("IDLE to DETECTING: a box arrives")
    with rung(State == SortState.IDLE, rise(EntrySensor)):
        copy(SortState.DETECTING, State)

    comment("DETECTING: read size for 0.5 seconds")
    with rung(State == SortState.DETECTING):
        on_delay(DetTimer, 500)
    with rung(State == SortState.DETECTING, SizeReading > SizeThreshold):
        latch(IsLarge)
    with rung(DetTimer.Done):
        copy(SortState.SORTING, State)

    comment("SORTING: hold the diverter for 2 seconds")
    with rung(State == SortState.SORTING):
        on_delay(HoldTimer, 2000)
    with rung(HoldTimer.Done):
        copy(SortState.RESETTING, State)

    comment("RESETTING: clean up and return to idle")
    with rung(State == SortState.RESETTING):
        reset(IsLarge)
        copy(SortState.IDLE, State)

    comment("Diverter output: auto sort or the manual button, gated by EstopOK")
    with rung(
        EstopOK,
        Or(
            And(State == SortState.SORTING, IsLarge, Auto),
            And(Manual, DiverterBtn),
        ),
    ):
        out(DiverterCmd)

    comment("Bin counters")
    with rung(rise(BinASensor)):
        count_up(BinACounter, preset=9999).reset(CountReset)
    with rung(rise(BinBSensor)):
        count_up(BinBCounter, preset=9999).reset(CountReset)


@dataclass(frozen=True)
class MockProject:
    analysis: AnalysisService
    store: Any  # The two members SimulatorWindow reads of an AddressStore.
    project_ini: Path


def build_mock_project(root: Path) -> MockProject:
    """Stand in for a connected CLICK project saved under *root*."""
    csv_dir = root / "csv"
    pyrung_to_ladder(logic, mapping, validate=False).write(csv_dir)
    nicknames = csv_dir / "nicknames.csv"
    mapping.to_nickname_file(nicknames)

    project_dir = root / "pyrung_project"
    ladder_to_pyrung_project(
        csv_dir, nickname_csv=nicknames, output_dir=project_dir, machine_name="ClickConveyor"
    )
    namespace: dict[str, object] = {}
    code = ladder_to_pyrung(csv_dir, nickname_csv=nicknames)
    exec(compile(code, "<analysis>", "exec"), namespace)  # noqa: S102
    generated = namespace["logic"]

    rows = dict(read_csv(nicknames))
    tag_to_key, key_to_tag = _build_tag_addr_key_map(rows)
    analysis = AnalysisService()
    analysis._result = AnalysisResult(
        graph=build_program_graph(generated),
        program=generated,
        project_dir=project_dir,
        tag_to_addr_key=tag_to_key,
        addr_key_to_tag=key_to_tag,
    )
    analysis._status = AnalysisStatus.READY
    analysis._generation = 1

    project_ini = root / "Project.ini"
    project_ini.write_text(PROJECT_INI, encoding="utf-8")
    store = SimpleNamespace(
        visible_state=rows, add_observer=lambda _cb: None, remove_observer=lambda _cb: None
    )
    return MockProject(analysis, store, project_ini)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    """The window's visible rectangle, without the invisible resize borders."""
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    return rect.left, rect.top, rect.right, rect.bottom


Box = tuple[int, int, int, int]


@dataclass
class Frame:
    start: float
    pixels: bytes
    pointer: tuple[int, int]
    #: How far the click highlight has played (0 to 1), or None with no click showing.
    click: float | None


class Recorder:
    """Grabs the window from a thread; identical frames collapse into one."""

    def _run(self) -> None:
        period = 1 / CAPTURE_FPS
        last_pixels = b""
        last_pointer: tuple[int, int] | None = None
        last_click: float | None = None
        while not self._stop.is_set():
            started = time.monotonic()
            pixels = ImageGrab.grab(bbox=self.bounds, all_screens=True).convert("RGB").tobytes()
            pointer = self.pointer
            left = self.click_until - started
            click = round(1 - left / self.click_seconds, 2) if left > 0 else None
            if pixels != last_pixels or pointer != last_pointer or click != last_click:
                self.frames.append(Frame(started, zlib.compress(pixels, 1), pointer, click))
                last_pixels, last_pointer, last_click = pixels, pointer, click
            self._stop.wait(max(0.0, period - (time.monotonic() - started)))
        self.finished_at = time.monotonic()

    def __init__(self, bounds: tuple[int, int, int, int], ticker: Box) -> None:
        self.bounds = bounds
        self.ticker = ticker
        self.size = (bounds[2] - bounds[0], bounds[3] - bounds[1])
        self.pointer = (self.size[0] // 2, self.size[1] // 2)
        self.click_until = 0.0
        self.click_seconds = CLICK_SECONDS
        self.frames: list[Frame] = []
        self.finished_at = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="gif-capture")

    def start(self) -> None:
        self._thread.start()

    def show_click(self, seconds: float = CLICK_SECONDS) -> None:
        self.click_seconds = seconds
        self.click_until = time.monotonic() + seconds

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()


#: The Windows arrow's outline in pixels, tip at (0, 0).
_ARROW = [
    (0, 0),
    (0, 21.5),
    (5, 16.8),
    (8.4, 24.6),
    (11.8, 23.2),
    (8.4, 15.6),
    (15.2, 15.6),
]


@lru_cache
def _pointer_sprite() -> tuple[Image.Image, tuple[int, int]]:
    """A smooth white arrow with a dark edge and a soft shadow, and where its tip sits."""
    scale = 8
    margin = 6
    side = 44 * scale
    tip = margin * scale
    points = [(tip + ax * UI_SCALE * scale, tip + ay * UI_SCALE * scale) for ax, ay in _ARROW]

    arrow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(arrow)
    draw.polygon(points, fill=(255, 255, 255, 255))
    draw.line([*points, points[0], points[1]], fill=(20, 20, 20, 255), width=scale, joint="curve")

    shadow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    silhouette = arrow.getchannel("A").point(lambda alpha: alpha * 0.45)
    shadow.paste((0, 0, 0, 255), (scale, 2 * scale), silhouette)
    shadow = shadow.filter(ImageFilter.GaussianBlur(1.5 * scale))
    sprite = Image.alpha_composite(shadow, arrow)
    return sprite.resize((side // scale, side // scale), Image.Resampling.LANCZOS), (margin, margin)


@lru_cache
def _dot_mask(radius: int, alpha: float) -> Image.Image:
    """A smooth-edged circle, drawn large and scaled down (Pillow draws without antialiasing)."""
    scale = 4
    side = radius * 2 * scale
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, side - 1, side - 1), fill=round(255 * alpha))
    return mask.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)


def _stamp_dot(
    image: Image.Image,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    alpha: float,
) -> None:
    box = (center[0] - radius, center[1] - radius)
    image.paste(color, box, _dot_mask(radius, round(alpha, 2)))


def _draw_pointer(image: Image.Image, pointer: tuple[int, int], click: float | None) -> None:
    if click is None:
        _stamp_dot(image, pointer, DOT_RADIUS, DOT_COLOR, DOT_ALPHA)
    else:
        radius = round(DOT_RADIUS * (1 + 0.3 * click))
        _stamp_dot(image, pointer, radius, CLICK_COLOR, CLICK_ALPHA - 0.25 * click)
    sprite, tip = _pointer_sprite()
    image.paste(sprite, (pointer[0] - tip[0], pointer[1] - tip[1]), sprite)


def _palette_sheet(samples: list[Image.Image]) -> Image.Image:
    """The samples, plus copies dotted all over, so the palette has the blended colors too."""
    width, height = samples[0].size
    dotted: list[Image.Image] = []
    for sample, color, alpha in (
        (samples[-1], DOT_COLOR, DOT_ALPHA),
        (samples[len(samples) // 2], DOT_COLOR, DOT_ALPHA),
        (samples[-1], CLICK_COLOR, CLICK_ALPHA - 0.1),
    ):
        copy_ = sample.copy()
        for cy in range(DOT_RADIUS, height, DOT_RADIUS * 3):
            for cx in range(DOT_RADIUS, width, DOT_RADIUS * 3):
                _stamp_dot(copy_, (cx, cy), DOT_RADIUS, color, alpha)
        dotted.append(copy_)
    rows = [*samples, *dotted]
    sheet = Image.new("RGB", (width, height * len(rows)))
    for row, image in enumerate(rows):
        sheet.paste(image, (0, height * row))
    return sheet


def _exact_palette(sheet: Image.Image, colors: int) -> Image.Image:
    """The most used colors, unchanged, so flat UI colors stay exact (median cut averages them)."""
    used = sheet.getcolors(maxcolors=sheet.width * sheet.height) or []
    top = sorted(used, key=lambda entry: entry[0], reverse=True)[:colors]
    palette = Image.new("P", (1, 1))
    palette.putpalette([channel for _count, color in top for channel in color])
    return palette


@dataclass(frozen=True)
class Capture:
    """A recording before encoding, so encoding can be redone without recording again."""

    size: tuple[int, int]
    ticker: Box
    frames: list[Frame]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [astuple(frame) for frame in self.frames]
        path.write_bytes(pickle.dumps((self.size, self.ticker, rows)))

    @classmethod
    def load(cls, path: Path) -> Capture:
        size, ticker, rows = pickle.loads(path.read_bytes())  # noqa: S301 - written by this script
        return cls(size, ticker, [Frame(*row) for row in rows])


@dataclass(frozen=True)
class Encoding:
    #: Playback speed, as a multiple of the recording.
    speed: float = 1.2
    #: The most frames per second a moving pointer or typing gets.
    fps: float = 12.0
    #: The scan counter changes every frame. Showing it this often is enough to look alive.
    ticker_fps: float = 4.0
    #: Below 256 the orange of the forced padlock and the pressed button turns brown.
    colors: int = 256
    #: Final frame hold, in seconds of the finished gif.
    end_hold: float = 3.0


def _inside(inner: Box, outer: Box) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _keep_frames(capture: Capture, encoding: Encoding) -> list[Frame]:
    """Drop what no one would miss: frames too close together, and most scan-counter ticks."""
    size = capture.size
    frames = capture.frames
    kept = [frames[0]]
    shown = Image.frombytes("RGB", size, zlib.decompress(frames[0].pixels))
    for frame in frames[1:-1]:
        gap = frame.start - kept[-1].start
        if gap < 1 / encoding.fps:
            continue
        image = Image.frombytes("RGB", size, zlib.decompress(frame.pixels))
        same_pointer = frame.pointer == kept[-1].pointer and frame.click == kept[-1].click
        if same_pointer and gap < 1 / encoding.ticker_fps:
            changed = ImageChops.difference(shown, image).getbbox()
            if changed is None or _inside(changed, capture.ticker):
                continue
        kept.append(frame)
        shown = image
    kept.append(frames[-1])
    return kept


def write_gif(capture: Capture, path: Path, encoding: Encoding) -> None:
    """Encode with one shared palette, so unchanged pixels stay unchanged between frames.

    That is what lets `optimize` store them as transparent, which is most of the size saving.
    """
    size = capture.size
    frames = _keep_frames(capture, encoding)
    # The window's 1 px border is translucent, so it shows the desktop behind it.
    inside = (1, 1, size[0] - 1, size[1] - 1)

    def picture(frame: Frame) -> Image.Image:
        image = Image.frombytes("RGB", size, zlib.decompress(frame.pixels))
        _draw_pointer(image, frame.pointer, frame.click)
        return image.crop(inside)

    # Sample across the recording so every LED and text color gets a palette entry.
    samples = [picture(frames[i]) for i in range(0, len(frames), max(1, len(frames) // 12))]
    samples.append(picture(frames[-1]))
    palette = _exact_palette(_palette_sheet(samples), encoding.colors)
    images: Iterator[Image.Image] = (
        picture(frame).quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames
    )

    # GIF delays are in 10 ms steps. Round the running time, not each delay, so errors don't add up.
    stamps = [
        round((frame.start - frames[0].start) / encoding.speed * 100) * 10 for frame in frames
    ]
    durations = [max(20, after - stamp) for stamp, after in zip(stamps, stamps[1:], strict=False)]
    durations.append(round(encoding.end_hold * 1000))

    first = next(images)
    path.parent.mkdir(parents=True, exist_ok=True)
    first.save(
        path,
        save_all=True,
        append_images=images,
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    print(
        f"{path}: {first.size[0]}x{first.size[1]}, {len(frames)} frames, "
        f"{sum(durations) / 1000:.1f}s, {path.stat().st_size / 1_000_000:.2f} MB"
    )


# ---------------------------------------------------------------------------
# Driving the window. A scene is a generator that yields seconds to wait.
# ---------------------------------------------------------------------------

Scene = Iterator[float]


class Driver:
    def __init__(self, win: SimulatorWindow, sim: SimulationSession, recorder: Recorder) -> None:
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
        # A Momentary input shows a pushbutton cap; its toggle knob is hidden and has no bbox.
        part = "cap" if self.sim.is_momentary(address) else "knob"
        return self._item_point(self.win._inputs[address][part])

    def output_point(self, address: str) -> tuple[int, int]:
        return self._item_point(self.win._outputs[address]["led"])

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
        self.recorder.show_click(hold + CLICK_SECONDS)
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
        """Click into the command line, then get the pointer off the Console's output."""
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

        The input is the window's last row, so they would otherwise fall outside the capture.
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


def walkthrough(driver: Driver) -> Scene:
    """Press Start and nothing happens: ask the Console why, then how, and do it on the panel."""
    sim = driver.sim
    yield from driver.wait_until(lambda: sim.status is SimStatus.READY, "the simulation", 60)
    yield from driver.wait_until(lambda: sim.modbus_available, "the Modbus server", 15)
    yield from driver.wait_until(lambda: "0 clients" in sim.modbus_text, "the Modbus client", 15)
    yield 0.3
    driver.recorder.start()
    yield 1.5

    # The machine, in STOP. RUN it and press Start: nothing happens.
    yield from driver.click(driver.mode_point("run"))
    driver.leave_canvas()
    yield from driver.wait_until(lambda: sim.switch_position == "run", "RUN")
    yield 0.9
    yield from driver.click(driver.switch_point("X001"), hold=0.5)
    yield 1.0

    # Ask the Console.
    yield from driver.click_input()
    yield from driver.command(["why ", "Conv|"])
    yield 4.5
    yield from driver.command(["how ", "Conv|"])
    yield 4.5

    # Follow the answer on the panel. Each switch writes its command to the Console.
    for address in ("X003", "X002", "X004"):
        yield from driver.click(driver.switch_point(address))
        yield 0.45
    yield from driver.click(driver.switch_point("X001"), hold=0.35)
    yield from driver.park()
    yield from driver.wait_until(lambda: driver.output("Y001") is True, "the motor output", 5)
    yield 2.0

    # Force the motor off: the padlock shows, and the program can't change it.
    yield from driver.double_click(driver.output_point("Y001"))
    driver.leave_canvas()
    yield from driver.park()
    yield from driver.wait_until(lambda: driver.output("Y001") is False, "the forced output", 5)
    yield 2.0


def run_scene(root: tk.Misc, scene: Scene, on_done: Callable[[BaseException | None], None]) -> None:
    def step() -> None:
        try:
            delay = next(scene)
        except StopIteration:
            on_done(None)
            return
        except BaseException as exc:  # noqa: BLE001 - report it after cleaning up
            on_done(exc)
            return
        root.after(max(1, round(delay * 1000)), step)

    step()


def record(*, keep_workdir: bool) -> Capture:
    workdir = Path(tempfile.mkdtemp(prefix="clicknick_gif_"))
    print(f"Mock project: {workdir}")
    project = build_mock_project(workdir)

    root = tk.Tk()
    root.withdraw()
    root.tk.call("tk", "scaling", float(root.tk.call("tk", "scaling")) * UI_SCALE)
    root.iconphoto(True, tk.PhotoImage(data=ICON_PNG_BASE64))

    sim = SimulationSession(
        scheduler=root,
        get_analysis=lambda: project.analysis,
        get_project_ini=lambda: project.project_ini,
        session_name=f"clicknick-{PROJECT_FILE}-0",
        app_data_root=workdir / "appdata",
    )
    sim.set_state_location("ClickConveyor", None)
    # StartBtn is a pushbutton on this panel.
    sim.set_momentary("X001", True)

    win = SimulatorWindow(
        root,
        simulation=sim,
        get_store=lambda: project.store,
        get_analysis=lambda: project.analysis,
        open_dataview=lambda: None,
        title_suffix=PROJECT_FILE,
    )
    width, height = WINDOW_SIZE
    win.geometry(f"{width}x{height}+60+40")
    win.attributes("-topmost", True)
    win._console_h = CONSOLE_HEIGHT
    win.update()
    win._restore_console_height()
    win.update()
    win.focus_force()

    sim.turn_on()
    win.update()
    bounds = window_bounds(int(win.wm_frame(), 16))
    label = win._scan_label
    left, top = label.winfo_rootx() - bounds[0], label.winfo_rooty() - bounds[1]
    ticker = (left, top, left + label.winfo_width(), top + label.winfo_height())
    recorder = Recorder(bounds, ticker)
    failure: list[BaseException] = []

    def finished(error: BaseException | None) -> None:
        if error is not None:
            failure.append(error)
        root.quit()

    run_scene(root, walkthrough(Driver(win, sim, recorder)), finished)
    root.mainloop()
    recorder.stop()

    transcript = "".join(text for text, _tag in win._console_transcript)
    print("--- console transcript ---")
    print(transcript)
    print("--------------------------")

    win._on_close()
    sim.close()
    root.update()
    root.destroy()

    if failure:
        raise failure[0]
    if keep_workdir:
        print(f"Kept {workdir}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return Capture(recorder.size, recorder.ticker, recorder.frames)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record the Simulator + Console gif.")
    parser.add_argument("--output", type=Path, default=Path("dist/simulator-console.gif"))
    parser.add_argument("--keep-workdir", action="store_true", help="keep the mock project")
    parser.add_argument("--capture", type=Path, help="where to save the raw recording")
    parser.add_argument(
        "--from-capture", type=Path, help="encode this saved recording instead of recording"
    )
    defaults = Encoding()
    parser.add_argument("--speed", type=float, default=defaults.speed)
    parser.add_argument("--fps", type=float, default=defaults.fps)
    parser.add_argument("--ticker-fps", type=float, default=defaults.ticker_fps)
    parser.add_argument("--colors", type=int, default=defaults.colors)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows only")
    if args.from_capture is not None:
        capture = Capture.load(args.from_capture)
    else:
        capture = record(keep_workdir=args.keep_workdir)
        if args.capture is not None:
            capture.save(args.capture)
    encoding = Encoding(
        speed=args.speed,
        fps=args.fps,
        ticker_fps=args.ticker_fps,
        colors=args.colors,
    )
    write_gif(capture, args.output, encoding)


if __name__ == "__main__":
    main()
