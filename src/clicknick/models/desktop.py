"""Windows as the desktop shows them to a redraw of CLICK's nicknames.

``services/click_redraw.py`` reads them; ``utils/win32_desktop.py`` makes them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    """A visible top-level window."""

    hwnd: int
    cls: str
    title: str
    owner: int  # GW_OWNER, 0 for none
    enabled: bool


@dataclass(frozen=True)
class Control:
    """A child window of a top-level window, at any depth."""

    hwnd: int
    parent: int
    cls: str
    text: str
    id: int
