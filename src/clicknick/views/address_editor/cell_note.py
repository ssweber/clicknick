"""Cell note dataclass for managing error and dirty notes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CellNote:
    """Represents a cell note with both error and dirty information.

    Error notes take display priority over dirty notes, but both can be shown.
    """

    error_note: str | None = None
    dirty_note: str | None = None

    @property
    def symbol(self) -> str:
        """Return symbol based on note type priority (error > dirty).

        Returns:
            "⚠" for errors, "💾" for dirty, "⚠" as fallback
        """
        if self.error_note:
            return "⚠"
        elif self.dirty_note:
            return "💾"
        return "⚠"  # fallback

    def __bool__(self) -> bool:
        """Return True if any note exists."""
        return bool(self.error_note or self.dirty_note)

    def __str__(self) -> str:
        """Format note text for display in tooltip.

        Combines error and dirty notes with blank line separator.
        """
        parts = []
        if self.error_note:
            parts.append(self.error_note)
        if self.dirty_note:
            parts.append(f"Original: {self.dirty_note}")
        return "\n\n".join(parts) if parts else ""
