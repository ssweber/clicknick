"""Define the timer scheduling interface for pure-Python polling code.

Tk widgets satisfy this protocol, so the UI passes its root window in. Services and data
code depend only on these two methods, and never on tkinter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class Scheduler(Protocol):
    """Describe anything that can run a callback later and cancel it, such as a Tk widget."""

    def after(self, ms: int, func: Callable[[], object]) -> str: ...

    def after_cancel(self, id: str) -> None: ...
