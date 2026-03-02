"""Ladder domain objects — contacts, coils, rung grid.

Pure Python, no Win32 or binary dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class InstructionType(IntEnum):
    """Instruction type IDs (low byte; high byte is always 0x27)."""

    CONTACT_NO = 0x11  # 0x2711
    CONTACT_NC = 0x12  # 0x2712
    COIL_OUT = 0x15  # 0x2715


FUNC_CODES = {
    InstructionType.CONTACT_NO: "4097",
    InstructionType.CONTACT_NC: "4098",
    InstructionType.COIL_OUT: "8193",
}


@dataclass
class Contact:
    """A contact instruction (NO or NC)."""

    type: InstructionType  # CONTACT_NO or CONTACT_NC
    operand: str  # e.g. "X001"

    @classmethod
    def from_csv_token(cls, token: str) -> Contact:
        """Parse 'X001' (NO) or '~X001' (NC)."""
        if token.startswith("~"):
            return cls(InstructionType.CONTACT_NC, token[1:])
        return cls(InstructionType.CONTACT_NO, token)

    @property
    def func_code(self) -> str:
        return FUNC_CODES[self.type]

    def to_csv(self) -> str:
        prefix = "~" if self.type == InstructionType.CONTACT_NC else ""
        return f"{prefix}{self.operand}"


@dataclass
class Coil:
    """An output coil instruction."""

    type: InstructionType  # COIL_OUT (future: COIL_LATCH, COIL_RESET)
    operand: str  # e.g. "Y001"

    @classmethod
    def from_csv_token(cls, token: str) -> Coil:
        """Parse 'out(Y001)', future: 'latch(Y001)', 'reset(Y001)'."""
        m = re.match(r"^(out|latch|reset)\(([A-Z]+\d+)\)$", token)
        if not m:
            raise ValueError(f"Cannot parse coil: {token!r}")
        type_map = {"out": InstructionType.COIL_OUT}
        coil_type = type_map.get(m.group(1))
        if coil_type is None:
            raise ValueError(f"Unsupported coil type: {m.group(1)!r} (needs capture data)")
        return cls(coil_type, m.group(2))

    @property
    def func_code(self) -> str:
        return FUNC_CODES[self.type]

    def to_csv(self) -> str:
        type_names = {InstructionType.COIL_OUT: "out"}
        name = type_names[self.type]
        return f"{name}({self.operand})"


@dataclass
class RungGrid:
    """A single-row contact->wire->coil rung.

    This is the domain model. It knows nothing about bytes.
    """

    contact: Contact
    coil: Coil
    nickname: str | None = None

    @classmethod
    def from_csv(cls, csv: str) -> RungGrid:
        """Parse 'X001,->,:out(Y001)' or '~X001,->,:out(Y001)'."""
        parts = [p.strip() for p in csv.split(",")]

        contact = Contact.from_csv_token(parts[0])

        coil = None
        for part in parts:
            token = part.lstrip(":")
            if token.startswith(("out(", "latch(", "reset(")):
                coil = Coil.from_csv_token(token)
                break

        if coil is None:
            raise ValueError(f"No coil found in: {csv!r}")

        return cls(contact=contact, coil=coil)

    def to_csv(self) -> str:
        return f"{self.contact.to_csv()},->,:{self.coil.to_csv()}"

    def __repr__(self) -> str:
        nn = f", nickname={self.nickname!r}" if self.nickname else ""
        return f"RungGrid({self.contact.to_csv()} -> {self.coil.to_csv()}{nn})"
