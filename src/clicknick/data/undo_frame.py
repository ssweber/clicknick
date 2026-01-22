"""Undo frame for storing snapshots of address row overrides.

A single UndoFrame captures the state of user overrides before a change,
allowing undo/redo operations to restore previous states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.address_row import AddressRow

# Maximum number of undo frames to retain
MAX_UNDO_DEPTH = 50


@dataclass
class UndoFrame:
    """Snapshot of user overrides before a change.

    Attributes:
        overrides: Dict mapping addr_key to AddressRow state at that point.
                   Only contains rows that had user modifications.
        description: Human-readable description of the change (for menu display).
    """

    overrides: dict[int, AddressRow] = field(default_factory=dict)
    description: str = ""

    def __repr__(self) -> str:
        return f"UndoFrame({self.description!r}, {len(self.overrides)} overrides)"
