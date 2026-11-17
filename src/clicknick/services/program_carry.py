"""Decide what a write does with each force and bench link when the program changes.

pyrung carries forces and bench links over a plain reload by tag name. A program change
can rename a tag, give its name to another address or drop it. For each entry that pyrung
lists, :func:`plan_carry` decides which name the entry has in the new program, or that it
is released. The plan uses the running program's names as keys. It goes with the write in
the form that pyrung's ``pyrungReload`` takes (:meth:`CarryPlan.as_dap`). pyrung answers
with what became of each entry, and :meth:`CarryPlan.written` puts that in words. This
module is pure logic. It uses no tkinter and no DAP.

The rules:

- A bench link (or cut) follows each of its names, the feedback and the enable, while the
  new program still has that name. A name that is gone stays on its address, under the
  address's new name. If a name now sits on another address, the plan adds a note.
- If two links land on one feedback, the one that followed its name wins. The other is
  dropped (released), with a note.
- A force stays on its address. If its name is gone, it takes the address's new name.
  This includes a pure rename, and an unnamed address that gains a nickname.
- If a force's name now sits on another address, the force still stays on its own address
  when that is hardware (X, Y and the analog channels' DF registers). On internal memory
  the force is released.
- A link that the program declares (in its feedback's comment) follows its feedback's name
  while the new program declares a link on that name. pyrung carries the coil on by name.
  If the name is gone, or now sits on an address where the new program declares no link,
  the coil carries on at its address, under the address's new name, with its timing
  (``declared``).

An entry whose name is on no CLICK address is not the user's. pyrung carries it as it is.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pyclickplc.addresses import (
    format_address_display,
    get_addr_key,
    normalize_address,
    parse_addr_key,
    parse_address,
)

#: tag name -> addr_key and addr_key -> tag name, for one program.
TagMaps = tuple[Mapping[str, int], Mapping[int, str]]

Section = Literal["released", "renamed", "moved"]


@dataclass(frozen=True)
class LinkTarget:
    """A bench link's names in the new program. A cut has no *enable*."""

    feedback: str
    enable: str | None

    def as_dap(self) -> dict[str, Any]:
        if self.enable is None:
            return {"cut": True, "fb": self.feedback}
        return {"en": self.enable, "fb": self.feedback}


@dataclass(frozen=True)
class CarryNote:
    """One part of the notice, about the force on *name* or the bench change on feedback *name*."""

    kind: Literal["force", "link"]
    name: str
    section: Section
    text: str


#: Drops that lose nothing. Either the Console already removed the entry, or the
#: program now declares the bench link itself.
_NO_LOSS = frozenset({"not forced", "no bench change", "in program"})
#: These reasons mean the new program has no link like the old one at the coil's place.
#: The coil does not move. The program changed, so that is expected.
_DECLARED_NO_LOSS = frozenset({"unlinked", "gone", "changed kind"})


def _drop_line(entry: Mapping[str, Any], declared: Mapping[str, str]) -> str:
    """Describe in words an entry of pyrung's ``carried`` that could not be kept, or return "".

    *declared* is the plan's. It says where each declared link's coil was to go.
    """
    if not entry.get("dropped"):
        return ""
    reason = str(entry.get("reason") or "")
    kind = entry.get("kind")
    if reason in _NO_LOSS or (kind == "declared" and reason in _DECLARED_NO_LOSS):
        return ""
    tag = str(entry.get("tag"))
    detail = entry.get("detail") or reason
    if kind == "declared":
        onto = f" to {declared[tag]}" if tag in declared else ""
        return f"The program's link on {tag} could not move{onto}: {detail}."
    what = {"force": "force", "cut": "cut"}.get(str(kind), "bench link")
    return f"Could not keep the {what} on {tag}: {detail}."


def _render(notes: Iterable[CarryNote], *, written: bool) -> str:
    notes = tuple(notes)
    parts: list[str] = []
    released = [note.text for note in notes if note.section == "released"]
    if released:
        count = len(released)
        forces = "force" if count == 1 else "forces"
        verb = "Released" if written else "Writing the program releases"
        parts.append(f"{verb} {count} {forces}: {', '.join(released)}.")
    renamed = [note.text for note in notes if note.section == "renamed"]
    if renamed:
        parts.append(f"Kept under new names: {', '.join(renamed)}.")
    parts.extend(
        f"{note.text[0].upper()}{note.text[1:]}." for note in notes if note.section == "moved"
    )
    return " ".join(parts)


@dataclass(frozen=True)
class CarryPlan:
    """What happens to each listed entry, keyed by its name in the running program.

    *forces* maps an old tag name to its new name, or to None to release it. *links* maps an
    old feedback name to its new names, or to None to drop it. *declared* maps the feedback
    of a link that the program declares to the name that its address has in the new program.
    The notes say, in listing order, why a force is released, which entry is renamed, and
    which link moved with its names or was dropped.
    """

    forces: Mapping[str, str | None] = field(default_factory=dict)
    links: Mapping[str, LinkTarget | None] = field(default_factory=dict)
    declared: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[CarryNote, ...] = ()

    def as_dap(self) -> dict[str, Any]:
        """Return the plan as ``pyrungReload`` takes it: ``{"forces", "links", "declared"}``."""
        return {
            "forces": dict(self.forces),
            "links": {
                fb: None if target is None else target.as_dap() for fb, target in self.links.items()
            },
            "declared": dict(self.declared),
        }

    @property
    def notice(self) -> str:
        """Return what the write would do, listed before the user writes, or "" for nothing."""
        return _render(self.notes, written=False)

    def _as_planned(self, note: CarryNote, entry: Mapping[str, Any] | None) -> bool:
        """Return True when pyrung did with the entry what the plan asked."""
        if entry is None or entry.get("dropped"):
            return False
        to = entry.get("to")
        if note.kind == "force":
            target = self.forces.get(note.name)
            return bool(entry.get("released")) if target is None else to == target
        link = self.links.get(note.name)
        if link is None:
            return bool(entry.get("released"))
        return to == link.feedback and entry.get("enable") == link.enable

    def written(self, carried: Iterable[Mapping[str, Any]]) -> str:
        """Return what the write did, from pyrung's ``carried`` report, or "" for nothing.

        The result keeps a note for each entry that pyrung placed as planned. It also says
        which entries pyrung could not keep, with pyrung's reason for each.
        """
        entries = [entry for entry in carried if isinstance(entry, Mapping)]
        outcome = {
            ("force" if entry.get("kind") == "force" else "link", str(entry.get("tag"))): entry
            for entry in entries
            if entry.get("kind") in ("force", "link", "cut")
        }
        done = [
            note
            for note in self.notes
            if self._as_planned(note, outcome.get((note.kind, note.name)))
        ]
        drops = [line for entry in entries if (line := _drop_line(entry, self.declared))]
        return " ".join(part for part in (_render(done, written=True), *drops) if part)


class _Program:
    def __init__(self, maps: TagMaps) -> None:
        self.tags, self.keys = maps

    def address(self, name: str) -> str | None:
        """Return the CLICK address that *name* is on in this program, or None for a tag on none."""
        address = normalize_address(name)
        if address is not None:
            # An address that no nickname covers has the address itself as its name.
            key = get_addr_key(*parse_address(address))
            return address if self.keys.get(key, address) == name else None
        key = self.tags.get(name)
        return None if key is None else format_address_display(*parse_addr_key(key))

    def name(self, address: str) -> str:
        """Return this program's tag on *address*, which is its nickname or the address itself."""
        return self.keys.get(get_addr_key(*parse_address(address))) or address


def address_of(name: str, maps: TagMaps) -> str | None:
    """Return the CLICK address that tag *name* is on in the program *maps* describes, or None."""
    return _Program(maps).address(name)


def _hardware(address: str, analog: Collection[str]) -> bool:
    return parse_address(address)[0] in ("X", "Y") or address in analog


def _force(
    name: str, old: _Program, new: _Program, analog: Collection[str]
) -> tuple[str | None, str]:
    """Return the new name for a force on *name*, and the note if it changes.

    The new name is None when the force is released.
    """
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
    """Return one name of a bench link, which is on *address* now.

    The name is the old name if it was followed, or else the address's new name.
    """
    return name if new.address(name) is not None else new.name(address)


def _kind(enable: str | None) -> str:
    return "cut" if enable is None else "link"


def plan_carry(
    old: TagMaps,
    new: TagMaps,
    forces: Mapping[str, object],
    links: Mapping[str, str | None],
    analog: Collection[str] = (),
    declared: Collection[str] = (),
    linked: Collection[str] = (),
) -> CarryPlan:
    """Decide what a write does with each force and bench link pyrung lists.

    *old* and *new* are the tag maps of the running and the new program. *forces* is pyrung's
    force listing (tag name -> value). *links* is its bench links (feedback name -> enable
    name, None for a cut). *analog* holds the DF addresses that the I/O configuration gives
    analog channels. *declared* holds the feedbacks of the links that the running program
    declares and runs, which are the links that no bench change replaces. *linked* holds the
    feedbacks that the new program declares links on.
    """
    before, after = _Program(old), _Program(new)
    carried_forces: dict[str, str | None] = {}
    notes: list[CarryNote] = []
    for name in forces:
        target, note = _force(name, before, after, analog)
        carried_forces[name] = target
        if target is None:
            notes.append(CarryNote("force", name, "released", note))
        elif note:
            notes.append(CarryNote("force", name, "renamed", note))

    carried_links: dict[str, LinkTarget | None] = {}
    link_notes: dict[str, tuple[list[str], list[str]]] = {}  # feedback -> (renamed, moved)
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
        names, places = link_notes[feedback] = ([], [])
        if new_feedback == feedback and after.address(feedback) is not None:
            followed[new_feedback] = feedback
        if new_feedback != feedback:
            names.append(f"the {kind} on {feedback} is now on {new_feedback}")
        if new_enable != enable:
            names.append(f"the link on {feedback} now comes from {new_enable} (was {enable})")
        # If a name followed to another address, the link now runs between other points.
        now = after.address(feedback) if new_feedback == feedback else feedback_at
        if now != feedback_at:
            places.append(f"the {kind} on {feedback} now feeds {now} (was {feedback_at})")
        now = after.address(enable) if enable is not None and new_enable == enable else enable_at
        if now != enable_at:
            places.append(f"the link on {feedback} now follows {enable} on {now} (was {enable_at})")

    # A link that stayed on its address can land where another link followed its name.
    # The one that followed wins, and the other is dropped.
    moved: list[CarryNote] = []
    for feedback, (names, places) in link_notes.items():
        target = carried_links[feedback]
        winner = None if target is None else followed.get(target.feedback)
        if target is not None and winner is not None and winner != feedback:
            carried_links[feedback] = None
            text = (
                f"the {_kind(links[feedback])} on {feedback} is removed, because the link on "
                f"{winner} moved onto the same address"
            )
            moved.append(CarryNote("link", feedback, "moved", text))
            continue
        notes.extend(CarryNote("link", feedback, "renamed", text) for text in names)
        moved.extend(CarryNote("link", feedback, "moved", text) for text in places)
    notes.extend(moved)

    # A declared link's coil follows its name while the new program declares a link on
    # that name. pyrung carries it on by name, with no plan. Otherwise the coil stays on
    # its address, under the address's new name.
    carried_declared: dict[str, str] = {}
    for feedback in declared:
        address = before.address(feedback)
        if address is None or feedback in linked or after.address(feedback) == address:
            continue
        carried_declared[feedback] = after.name(address)
    return CarryPlan(carried_forces, carried_links, carried_declared, tuple(notes))
