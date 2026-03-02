"""Ladder module — encode/decode Click PLC clipboard rungs."""

from .clipboard import copy_to_clipboard, read_from_clipboard
from .codec import ClickCodec
from .model import Coil, Contact, InstructionType, RungGrid

__all__ = [
    "ClickCodec",
    "Coil",
    "Contact",
    "InstructionType",
    "RungGrid",
    "copy_to_clipboard",
    "read_from_clipboard",
]
