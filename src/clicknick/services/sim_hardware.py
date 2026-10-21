"""The simulator's hardware panel: the user's CLICK modules and their I/O terminals.

Pure data. ``read_panel_layout`` reads CLICK's Project.ini through pyclickplc's
``read_io_layout``; ``build_panel_layout`` turns that module list (or any
objects of the same shape) into cards of terminals, and lists the X/Y
addresses the program uses that no installed module provides.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pyclickplc.addresses import format_address_display, parse_addr_key, parse_address

TerminalKind = Literal["input", "output", "analog_in", "analog_out"]
Location = Literal["cpu", "slot", "expansion"]


class _Module(Protocol):
    @property
    def model(self) -> str: ...


class ModuleIOLike(Protocol):
    """The shape of ``pyclickplc.ModuleIO``."""

    @property
    def location(self) -> str: ...
    @property
    def position(self) -> int: ...
    @property
    def module(self) -> _Module: ...
    @property
    def inputs(self) -> Sequence[str]: ...
    @property
    def outputs(self) -> Sequence[str]: ...
    @property
    def analog_inputs(self) -> Sequence[str | None]: ...
    @property
    def analog_outputs(self) -> Sequence[str | None]: ...


@dataclass(frozen=True)
class Terminal:
    """One I/O point on a card. Analog channels with no DF assigned have no address."""

    kind: TerminalKind
    channel: int
    address: str | None


@dataclass(frozen=True)
class Card:
    """One installed module, in physical order."""

    location: Location
    position: int
    model: str
    terminals: tuple[Terminal, ...]

    @property
    def key(self) -> str:
        return "cpu" if self.location == "cpu" else f"{self.location}{self.position}"

    @property
    def title(self) -> str:
        if self.location == "cpu":
            return "CPU"
        if self.location == "slot":
            return f"Option slot {self.position}"
        return f"Expansion {self.position}"

    def of_kind(self, kind: TerminalKind) -> tuple[Terminal, ...]:
        return tuple(t for t in self.terminals if t.kind == kind)


@dataclass(frozen=True)
class PanelLayout:
    """Everything the Simulator window draws.

    ``unassigned_*`` are X/Y addresses the program uses that no installed
    module provides; they still get a switch or LED so the program can be driven.
    """

    cards: tuple[Card, ...] = ()
    unassigned_inputs: tuple[str, ...] = ()
    unassigned_outputs: tuple[str, ...] = ()

    @property
    def has_cpu(self) -> bool:
        return any(card.location == "cpu" for card in self.cards)

    @property
    def modules(self) -> tuple[str, ...]:
        """Stable description of the installed hardware, e.g. ``"expansion1:C0-16ND3"``."""
        return tuple(f"{card.key}:{card.model}" for card in self.cards)

    def addresses(self, kind: TerminalKind) -> tuple[str, ...]:
        """Every address of *kind* on the panel, unassigned strip included."""
        found = [
            t.address
            for card in self.cards
            for t in card.terminals
            if t.kind == kind and t.address is not None
        ]
        if kind == "input":
            found.extend(self.unassigned_inputs)
        elif kind == "output":
            found.extend(self.unassigned_outputs)
        return tuple(dict.fromkeys(found))

    @property
    def poll_addresses(self) -> tuple[str, ...]:
        """Every address whose value the panel shows."""
        kinds: tuple[TerminalKind, ...] = ("input", "output", "analog_in", "analog_out")
        return tuple(dict.fromkeys(a for kind in kinds for a in self.addresses(kind)))


def address_sort_key(address: str) -> tuple[str, int]:
    try:
        return parse_address(address)
    except ValueError:
        return (address, 0)


#: CLICK's generated module status bits (_IO1_Module_Error, _IO1_CH1_Burnout, ...) sit in
#: X addresses but are not terminals, so they never count as used I/O.
MODULE_STATUS_PREFIX = "_IO"


def io_addresses(addr_keys: Iterable[int]) -> set[str]:
    """X and Y display addresses among *addr_keys*."""
    found: set[str] = set()
    for addr_key in addr_keys:
        try:
            bank, index = parse_addr_key(addr_key)
        except (KeyError, ValueError):
            continue
        if bank in ("X", "Y"):
            found.add(format_address_display(bank, index))
    return found


def _card(module_io: ModuleIOLike) -> Card:
    terminals: list[Terminal] = []
    for kind, addresses in (
        ("input", module_io.inputs),
        ("output", module_io.outputs),
        ("analog_in", module_io.analog_inputs),
        ("analog_out", module_io.analog_outputs),
    ):
        for channel, address in enumerate(addresses, start=1):
            terminals.append(Terminal(kind, channel, address))  # type: ignore[arg-type]
    location = module_io.location if module_io.location in ("cpu", "slot") else "expansion"
    return Card(
        location=location,  # type: ignore[arg-type]
        position=module_io.position,
        model=module_io.module.model,
        terminals=tuple(terminals),
    )


def build_panel_layout(modules: Iterable[ModuleIOLike], used_io: Iterable[str] = ()) -> PanelLayout:
    """Cards for *modules* (in the order given), plus the used I/O no card provides."""
    cards = tuple(_card(module_io) for module_io in modules)
    provided = {t.address for card in cards for t in card.terminals if t.address is not None}
    missing = sorted((a for a in set(used_io) if a not in provided), key=address_sort_key)
    return PanelLayout(
        cards=cards,
        unassigned_inputs=tuple(a for a in missing if a.startswith("X")),
        unassigned_outputs=tuple(a for a in missing if a.startswith("Y")),
    )


def read_panel_layout(project_ini: Path, used_io: Iterable[str] = ()) -> PanelLayout:
    """Read CLICK's hardware configuration from Project.ini.

    Raises OSError if the file cannot be read and ValueError if it is malformed.
    """
    from pyclickplc import read_io_layout

    return build_panel_layout(read_io_layout(project_ini), used_io)
