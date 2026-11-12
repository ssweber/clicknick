"""What a write does with each force and bench link when the program changes.

pyrung carries forces and bench links over a reload by tag name. A program
change can rename a tag, give its name to another address or drop it, so
:func:`plan_carry` decides, for each entry pyrung lists, which name it has in
the new program, or that it is released. The plan is keyed by the running
program's names, in the shape pyrung's reload plan takes (:meth:`CarryPlan.as_dap`).
Pure logic: no tkinter, no DAP.

The rule:

- A bench link (or cut) follows each of its names, feedback and enable, while
  the new program still has it. A name that is gone stays on its address,
  under the address's new name. A name that now sits on another address is
  noted.
- Two links that land on one feedback: the one that followed its name wins
  and the other is dropped (released), with a note.
- A force stays on its address, under the address's new name when its name
  is gone (a pure rename, an unnamed address gaining a nickname included).
- A force whose name now sits on another address stays on its address too
  when that is hardware (X, Y and the analog channels' DF registers). On
  internal memory it is released.

Entries whose name is on no CLICK address are not the user's: pyrung carries
them as they are.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from pyclickplc.addresses import (
    format_address_display,
    get_addr_key,
    normalize_address,
    parse_addr_key,
    parse_address,
)

#: tag name -> addr_key and addr_key -> tag name, for one program.
TagMaps = tuple[Mapping[str, int], Mapping[int, str]]


@dataclass(frozen=True)
class LinkTarget:
    """A bench link's names in the new program; no *enable* for a cut."""

    feedback: str
    enable: str | None

    def as_dap(self) -> dict[str, Any]:
        if self.enable is None:
            return {"cut": True, "fb": self.feedback}
        return {"en": self.enable, "fb": self.feedback}


@dataclass(frozen=True)
class CarryPlan:
    """Each listed entry, by its name in the running program.

    *forces* maps an old tag name to its new name, or None to release it;
    *links* an old feedback name to its new names, or None to drop it. The
    notes say why a force is released, an entry renamed, a link moved with its
    names or dropped, in listing order.
    """

    forces: Mapping[str, str | None] = field(default_factory=dict)
    links: Mapping[str, LinkTarget | None] = field(default_factory=dict)
    released: tuple[str, ...] = ()
    renamed: tuple[str, ...] = ()
    moved: tuple[str, ...] = ()

    def as_dap(self) -> dict[str, Any]:
        """The plan as pyrung's reload takes it: ``{"forces": ..., "links": ...}``."""
        return {
            "forces": dict(self.forces),
            "links": {
                fb: None if target is None else target.as_dap() for fb, target in self.links.items()
            },
        }

    def describe(self, *, written: bool) -> str:
        """What the write does (before it) or did (*written*); "" when nothing."""
        parts: list[str] = []
        if self.released:
            count = len(self.released)
            forces = "force" if count == 1 else "forces"
            verb = "Released" if written else "Writing releases"
            parts.append(f"{verb} {count} {forces}: {', '.join(self.released)}.")
        if self.renamed:
            parts.append(f"Kept under new names: {', '.join(self.renamed)}.")
        parts.extend(f"{note[0].upper()}{note[1:]}." for note in self.moved)
        return " ".join(parts)

    @property
    def notice(self) -> str:
        """What the write would do, listed before the user writes."""
        return self.describe(written=False)


class _Program:
    def __init__(self, maps: TagMaps) -> None:
        self.tags, self.keys = maps

    def address(self, name: str) -> str | None:
        """The CLICK address *name* is on in this program; None for a tag on none."""
        address = normalize_address(name)
        if address is not None:
            # An address no nickname covers keeps its address as its name.
            key = get_addr_key(*parse_address(address))
            return address if self.keys.get(key, address) == name else None
        key = self.tags.get(name)
        return None if key is None else format_address_display(*parse_addr_key(key))

    def name(self, address: str) -> str:
        """This program's tag on *address*: its nickname, or the address itself."""
        return self.keys.get(get_addr_key(*parse_address(address))) or address


def address_of(name: str, maps: TagMaps) -> str | None:
    """The CLICK address tag *name* is on in the program *maps* names; None for none."""
    return _Program(maps).address(name)


def _hardware(address: str, analog: Collection[str]) -> bool:
    return parse_address(address)[0] in ("X", "Y") or address in analog


def _force(
    name: str, old: _Program, new: _Program, analog: Collection[str]
) -> tuple[str | None, str]:
    """The new name for a force on *name* (None: released) and the note when it changes."""
    address = old.address(name)
    if address is None:
        return name, ""  # not on a CLICK address: pyrung carries it
    where = new.address(name)
    if where == address:
        return name, ""
    if where is not None and not _hardware(address, analog):
        return None, f"{name} (now on {where}, was {address})"
    moved = new.name(address)
    shown = "" if address in (name, moved) else f" ({address})"
    return moved, f"{name} -> {moved}{shown}"


def _link_name(name: str, address: str, new: _Program) -> str:
    """One name of a bench link, on *address* now: followed, or the address's new name."""
    return name if new.address(name) is not None else new.name(address)


def _kind(enable: str | None) -> str:
    return "cut" if enable is None else "link"


def plan_carry(
    old: TagMaps,
    new: TagMaps,
    forces: Mapping[str, object],
    links: Mapping[str, str | None],
    analog: Collection[str] = (),
) -> CarryPlan:
    """Decide what a write does with each force and bench link pyrung lists.

    *old* and *new* are the tag maps of the running and the new program.
    *forces* is pyrung's force listing (tag name -> value); *links* its bench
    links (feedback name -> enable name, None for a cut). *analog* holds the
    DF addresses the I/O configuration gives analog channels.
    """
    before, after = _Program(old), _Program(new)
    carried_forces: dict[str, str | None] = {}
    released_forces: list[str] = []
    renamed: list[str] = []
    for name in forces:
        target, note = _force(name, before, after, analog)
        carried_forces[name] = target
        if target is None:
            released_forces.append(note)
        elif note:
            renamed.append(note)

    carried_links: dict[str, LinkTarget | None] = {}
    notes: dict[str, tuple[list[str], list[str]]] = {}  # feedback -> (renamed, moved)
    followed: dict[str, str] = {}  # new feedback -> the old feedback name that followed to it
    for feedback, enable in links.items():
        feedback_at = before.address(feedback)
        enable_at = None if enable is None else before.address(enable)
        if feedback_at is None or (enable is not None and enable_at is None):
            carried_links[feedback] = LinkTarget(feedback, enable)  # not the user's
            continue
        new_feedback = _link_name(feedback, feedback_at, after)
        new_enable = (
            None if enable is None or enable_at is None else _link_name(enable, enable_at, after)
        )
        carried_links[feedback] = LinkTarget(new_feedback, new_enable)
        kind = _kind(enable)
        names, places = notes[feedback] = ([], [])
        if new_feedback == feedback and after.address(feedback) is not None:
            followed[new_feedback] = feedback
        if new_feedback != feedback:
            names.append(f"the {kind} on {feedback} is now on {new_feedback}")
        if new_enable != enable:
            names.append(f"the link on {feedback} now comes from {new_enable} (was {enable})")
        # A name followed to another address: the link now runs between other points.
        now = after.address(feedback) if new_feedback == feedback else feedback_at
        if now != feedback_at:
            places.append(f"the {kind} on {feedback} now feeds {now} (was {feedback_at})")
        now = after.address(enable) if enable is not None and new_enable == enable else enable_at
        if now != enable_at:
            places.append(f"the link on {feedback} now follows {enable} on {now} (was {enable_at})")

    # A link that stayed on its address can land where another followed its name:
    # the one that followed wins, and the other is dropped.
    moved: list[str] = []
    for feedback, (names, places) in notes.items():
        target = carried_links[feedback]
        winner = None if target is None else followed.get(target.feedback)
        if target is not None and winner is not None and winner != feedback:
            carried_links[feedback] = None
            where = after.address(target.feedback)
            kind = _kind(links[feedback])
            moved.append(f"the {kind} on {feedback} is dropped: {winner} now feeds {where}")
            continue
        renamed.extend(names)
        moved.extend(places)
    return CarryPlan(
        carried_forces, carried_links, tuple(released_forces), tuple(renamed), tuple(moved)
    )
