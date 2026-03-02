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
    COIL_LATCH = 0x16  # 0x2716
    COIL_RESET = 0x17  # 0x2717


OPERAND_RE = re.compile(r"^[A-Z]{1,3}\d{1,5}$")

CONTACT_FUNC_CODES: dict[tuple[InstructionType, bool], str] = {
    (InstructionType.CONTACT_NO, False): "4097",
    (InstructionType.CONTACT_NC, False): "4098",
    (InstructionType.CONTACT_NO, True): "4099",
    (InstructionType.CONTACT_NC, True): "4100",
}

COIL_FUNC_CODES: dict[tuple[InstructionType, bool, bool], str] = {
    # (type, is_range, immediate) -> func_code
    (InstructionType.COIL_OUT, False, False): "8193",
    (InstructionType.COIL_OUT, False, True): "8197",
    (InstructionType.COIL_OUT, True, False): "8207",
    (InstructionType.COIL_OUT, True, True): "8208",
    (InstructionType.COIL_LATCH, False, False): "8195",
    (InstructionType.COIL_LATCH, False, True): "8199",
    (InstructionType.COIL_LATCH, True, False): "8213",
    (InstructionType.COIL_LATCH, True, True): "8214",
    (InstructionType.COIL_RESET, False, False): "8196",
    (InstructionType.COIL_RESET, False, True): "8200",
    (InstructionType.COIL_RESET, True, False): "8219",
    (InstructionType.COIL_RESET, True, True): "8220",
}

COIL_NAME_TO_TYPE = {
    "out": InstructionType.COIL_OUT,
    "latch": InstructionType.COIL_LATCH,
    "reset": InstructionType.COIL_RESET,
}

COIL_TYPE_TO_NAME = {v: k for k, v in COIL_NAME_TO_TYPE.items()}


def _validate_operand(operand: str) -> str:
    operand = operand.strip()
    if not OPERAND_RE.fullmatch(operand):
        raise ValueError(f"Invalid operand: {operand!r}")
    return operand


@dataclass
class Contact:
    """A contact instruction (NO or NC)."""

    type: InstructionType  # CONTACT_NO or CONTACT_NC
    operand: str  # e.g. "X001"
    immediate: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> Contact:
        """Parse 'X001', '~X001', 'X001.immediate', or '~X001.immediate'."""
        token = token.strip()
        immediate = token.endswith(".immediate")
        if immediate:
            token = token[: -len(".immediate")]

        if token.startswith("~"):
            return cls(InstructionType.CONTACT_NC, _validate_operand(token[1:]), immediate=immediate)
        return cls(InstructionType.CONTACT_NO, _validate_operand(token), immediate=immediate)

    @property
    def func_code(self) -> str:
        return CONTACT_FUNC_CODES[(self.type, self.immediate)]

    def to_csv(self) -> str:
        prefix = "~" if self.type == InstructionType.CONTACT_NC else ""
        suffix = ".immediate" if self.immediate else ""
        return f"{prefix}{self.operand}{suffix}"


@dataclass
class Coil:
    """An output coil instruction."""

    type: InstructionType  # COIL_OUT, COIL_LATCH, COIL_RESET
    operand: str  # e.g. "Y001"
    range_end: str | None = None
    immediate: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> Coil:
        """Parse coil forms with inner immediate wrapper and ranges."""
        token = token.strip()
        if token.startswith("immediate("):
            raise ValueError(
                f"Immediate must be an inner wrapper (e.g. out(immediate(Y1))): {token!r}"
            )

        m = re.fullmatch(r"(out|latch|reset)\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse coil: {token!r}")

        coil_type = COIL_NAME_TO_TYPE[m.group(1)]
        arg = m.group(2).strip()

        immediate_inner = False
        inner = re.fullmatch(r"immediate\((.+)\)", arg)
        if inner:
            immediate_inner = True
            arg = inner.group(1).strip()

        immediate = immediate_inner
        if ":" in arg:
            raise ValueError(f"Range delimiter ':' is unsupported: {token!r}")

        if ".." in arg:
            parts = [p.strip() for p in arg.split("..")]
            if len(parts) != 2 or not all(parts):
                raise ValueError(f"Cannot parse coil range: {token!r}")
            op1 = _validate_operand(parts[0])
            op2 = _validate_operand(parts[1])
            return cls(type=coil_type, operand=op1, range_end=op2, immediate=immediate)

        return cls(type=coil_type, operand=_validate_operand(arg), immediate=immediate)

    @property
    def func_code(self) -> str:
        key = (self.type, self.range_end is not None, self.immediate)
        return COIL_FUNC_CODES[key]

    def to_csv(self) -> str:
        name = COIL_TYPE_TO_NAME[self.type]
        operand = self.operand
        if self.range_end is not None:
            operand = f"{operand}..{self.range_end}"
        if self.immediate:
            operand = f"immediate({operand})"
        return f"{name}({operand})"


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
        """Parse simple rung CSV forms used by this module."""
        parts = [p.strip() for p in csv.split(",")]

        contact = Contact.from_csv_token(parts[0])

        coil = None
        for part in parts:
            token = part.lstrip(":").strip()
            if token.startswith(("out(", "latch(", "reset(", "immediate(")):
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
