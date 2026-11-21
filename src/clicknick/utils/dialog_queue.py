"""Show modal dialogs one at a time."""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class DialogQueue:
    """Runs functions that show a modal dialog, one at a time, in the order they were asked for.

    On Windows, Tk keeps running ``after`` callbacks while a message box is open. If one of
    those callbacks opens a message box of its own, the new box opens on top of the first.
    The end of a workspace build schedules several reports with ``after``. If a box from this
    queue is open when a callback passes its box to :meth:`show`, the callback's box opens
    after that box closes.
    """

    def __init__(self) -> None:
        self._waiting: deque[Callable[[], object]] = deque()
        self._showing = False

    def show(self, dialog: Callable[[], object]) -> None:
        """Run *dialog* now, or queue it behind the dialog that this queue is showing.

        If no dialog is showing, return when *dialog* and every dialog queued meanwhile have
        closed. Otherwise return at once. If a dialog raises, log the error and go on to the
        next one.
        """
        self._waiting.append(dialog)
        if self._showing:
            return
        self._showing = True
        try:
            while self._waiting:
                current = self._waiting.popleft()
                try:
                    current()
                except Exception:
                    logger.exception("A dialog failed")
        finally:
            self._showing = False
