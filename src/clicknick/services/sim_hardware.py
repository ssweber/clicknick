"""The simulator's hardware panel: the user's CLICK modules and their I/O terminals.

Pure data. ``read_panel_layout`` reads CLICK's Project.ini through pyclickplc's
``read_io_layout``; ``build_panel_layout`` turns that module list (or any
objects of the same shape) into cards of terminals, and lists the X/Y
addresses the program uses that no installed module provides, each as a
placeholder card at the position its address belongs to.
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
    """One module in physical order.

    A card with ``installed`` False is a placeholder: the program uses X/Y
    addresses of this position that no module in Project.ini provides. It has
    no model and is not part of ``PanelLayout.modules``.
    """

    location: Location
    position: int
    model: str
    terminals: tuple[Terminal, ...]
    installed: bool = True

    @property
    def key(self) -> str:
        return "cpu" if self.location == "cpu" else f"{self.location}{self.position}"

    @property
    def title(self) -> str:
        if self.location == "cpu":
            name = "CPU"
        elif self.location == "slot":
            name = f"Option slot {self.position}"
        else:
            name = f"Expansion {self.position}"
        return name if self.installed else f"{name} - unassigned"

    def of_kind(self, kind: TerminalKind) -> tuple[Terminal, ...]:
        return tuple(t for t in self.terminals if t.kind == kind)


@dataclass(frozen=True)
class PanelLayout:
    """Everything the Simulator window draws.

    ``cards`` holds the installed modules and, in their physical place, the
    placeholders for used X/Y addresses no module provides; a placeholder
    still gets a switch or LED so the program can be driven.
    """

    cards: tuple[Card, ...] = ()

    @property
    def has_cpu(self) -> bool:
        return any(card.location == "cpu" and card.installed for card in self.cards)

    @property
    def modules(self) -> tuple[str, ...]:
        """Stable description of the installed hardware, e.g. ``"expansion1:C0-16ND3"``."""
        return tuple(f"{card.key}:{card.model}" for card in self.cards if card.installed)

    def addresses(self, kind: TerminalKind) -> tuple[str, ...]:
        """Every address of *kind* on the panel, placeholders included."""
        found = [
            t.address
            for card in self.cards
            for t in card.terminals
            if t.kind == kind and t.address is not None
        ]
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


def _position(address: str) -> tuple[Location, int]:
    """Where an X/Y address sits: the CPU (1-20), option slot 1 (21-99) or expansion n (n01-n99)."""
    index = parse_address(address)[1]
    if index >= 100:
        return "expansion", index // 100
    return ("cpu", 0) if index <= 20 else ("slot", 1)


def _rank(location: Location, position: int, installed: bool = True) -> tuple[int, int]:
    """Sort key in rack order. A placeholder for the CPU's addresses goes after the
    option slots, so it does not split the CPU housing."""
    if location == "cpu" and not installed:
        return (1, 100)
    return ({"cpu": 0, "slot": 1, "expansion": 2}[location], position)


def _where(card: Card) -> tuple[Location, int, bool]:
    return card.location, card.position, card.installed


def _placeholder(location: Location, position: int, addresses: Sequence[str]) -> Card:
    terminals = [
        Terminal(kind, channel, address)
        for kind, bank in (("input", "X"), ("output", "Y"))
        for channel, address in enumerate((a for a in addresses if a[0] == bank), start=1)
    ]
    return Card(location, position, "", tuple(terminals), installed=False)


def build_panel_layout(modules: Iterable[ModuleIOLike], used_io: Iterable[str] = ()) -> PanelLayout:
    """Cards for *modules* (in the order given), plus a placeholder card at each position
    holding the used I/O no card provides.

    A position with both X and Y left over gets one placeholder (an assumed combo
    module). Addresses past the points of a real module at their position go on a
    placeholder right after that module.
    """
    cards = [_card(module_io) for module_io in modules]
    provided = {t.address for card in cards for t in card.terminals if t.address is not None}
    missing = sorted((a for a in set(used_io) if a not in provided), key=address_sort_key)
    by_position: dict[tuple[Location, int], list[str]] = {}
    for address in missing:
        if address[:1] in ("X", "Y"):
            by_position.setdefault(_position(address), []).append(address)
    for (location, position), addresses in sorted(
        by_position.items(), key=lambda item: _rank(*item[0], installed=False)
    ):
        placeholder = _placeholder(location, position, addresses)
        rank = _rank(location, position, installed=False)
        at = len(cards)
        while at > 0 and _rank(*_where(cards[at - 1])) > rank:
            at -= 1
        cards.insert(at, placeholder)
    return PanelLayout(cards=tuple(cards))


def read_panel_layout(project_ini: Path, used_io: Iterable[str] = ()) -> PanelLayout:
    """Read CLICK's hardware configuration from Project.ini.

    Raises OSError if the file cannot be read and ValueError if it is malformed.
    """
    from pyclickplc import read_io_layout

    return build_panel_layout(read_io_layout(project_ini), used_io)
