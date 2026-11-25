"""Record every warning that laddercodec issues, and sort each one by a rule.

laddercodec reports trouble as a placeholder with a warning beside it. A rung that it cannot
decode becomes an UNDECODED marker, and a comment that it cannot decode becomes
``UNDECODED comment: ...``. A value that CLICK's editor refuses stays in the instruction.
Nothing in the placeholder alone tells ClickNick that the user must hear about it.

So every call into laddercodec that reads CLICK's bytes or writes a CSV runs inside
``recording()``, and ``sort_warnings`` gives each warning a rule. A warning from laddercodec
that no rule knows counts as a rung that ClickNick cannot read.

``recording()`` changes the warning filters of the whole process, and the build worker and
the Tk thread both call laddercodec. So one lock guards each block, and each block holds
one laddercodec call. The Tk thread then waits for one call at most, never for a whole
save. Warnings are passed on under the same lock, so that no other block records them.
"""

from __future__ import annotations

import threading
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import laddercodec
from laddercodec import (
    LegacyEncodingWarning,
    RefusedFieldWarning,
    Undecoded,
    UndecodedCommentWarning,
    UndecodedRungWarning,
)

_PACKAGE = Path(laddercodec.__file__).resolve().parent
# How laddercodec starts the warning for blank rows at the end of a rung that a CSV drops
_LOST_BLANK_ROWS = "CSV round-trip lost "
# Held across each recording() block, and while a warning is passed on
_LOCK = threading.RLock()


class Rule(Enum):
    """What ClickNick does with one laddercodec warning."""

    # CLICK holds the rung in a form an older laddercodec wrote. A save reports it as a
    # legacy encoding. Anywhere else it stays a warning.
    LEGACY = "legacy"
    # Nothing that the user needs to act on. It stays a warning.
    WARN = "warn"
    # ClickNick cannot copy the rung as it is. A save writes a stand-in rung in its place.
    RUNG = "rung"
    # laddercodec cannot read the rung's comment, and its comment says so. A save keeps the
    # rung and leaves the comment out, as 0.25.0 did. Save Clipboard to CSV refuses.
    COMMENT = "comment"
    # The rung reads, but laddercodec cannot read the program's CSV back. A save reports
    # the whole program, and Review Changes pastes it whole.
    PROGRAM = "program"


@dataclass(frozen=True)
class Note:
    """One laddercodec warning, with its rule, its rung and what to tell the user."""

    warning: Warning
    rule: Rule
    # The rung's index from 0 in what laddercodec read, or None if the warning names none
    rung: int | None
    detail: str

    @property
    def reported(self) -> bool:
        """True if the user must hear about the warning before anything is copied."""
        return self.rule in (Rule.RUNG, Rule.PROGRAM)


def _from_laddercodec(record: warnings.WarningMessage) -> bool:
    module = type(record.message).__module__
    if module == "laddercodec" or module.startswith("laddercodec."):
        return True
    if record.category is not UserWarning:
        # Python's own kinds, such as DeprecationWarning from a library that laddercodec calls
        return False
    try:
        return Path(record.filename).resolve().is_relative_to(_PACKAGE)
    except (OSError, ValueError):
        return False


@contextmanager
def recording() -> Iterator[list[Warning]]:
    """Record each warning that laddercodec issues in the block into the list yielded.

    Warnings from anything else are passed on when the block ends. Keep the block to one
    laddercodec call, because another thread waits for it to end.
    """
    found: list[Warning] = []
    records: list[warnings.WarningMessage] = []
    with _LOCK:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                records = caught
                yield found
        finally:
            # After the block, so that a warning passed on is not recorded again
            for record in records:
                if _from_laddercodec(record):
                    found.append(record.message)
                else:
                    warnings.warn_explicit(
                        record.message, record.category, record.filename, record.lineno
                    )


def _pass_on(warning: Warning) -> None:
    with _LOCK:
        warnings.warn(warning, stacklevel=3)


def pass_on(found: list[Warning]) -> None:
    """Pass on every warning in *found*, for a call whose result ClickNick only compares.

    ``rung_fingerprint`` writes CSV rows only to tell rungs apart, and copies nothing.
    """
    for warning in found:
        _pass_on(warning)


def marker_detail(marker: Undecoded) -> str:
    """Say why laddercodec put an UNDECODED marker in place of a rung, with no rung number.

    The caller names the rung. If the marker also stands for every rung after it, the text
    says that those rungs are missing too.
    """
    error = marker.error.rstrip(".")
    if not marker.to_the_end:
        return f"laddercodec cannot read this rung: {error}."
    return (
        f"laddercodec cannot read this rung, and it stopped reading the program there: "
        f"{error}. The rungs after it are missing too."
    )


def _first_line(value: object) -> str:
    lines = str(value).strip().splitlines()
    return lines[0].rstrip(".") if lines else type(value).__name__


def _note(warning: Warning, *, writing: bool) -> Note:
    """Return the rule for *warning*. *writing* is True for a warning from writing a CSV."""
    if isinstance(warning, LegacyEncodingWarning):
        return Note(warning, Rule.LEGACY, warning.rung, str(warning))
    if isinstance(warning, UndecodedRungWarning):
        marker = warning.marker
        if writing:
            detail = f"laddercodec cannot write this rung to a CSV: {_first_line(marker.error)}."
        else:
            detail = marker_detail(marker)
        return Note(warning, Rule.RUNG, marker.rung, detail)
    if isinstance(warning, UndecodedCommentWarning):
        what = "part of this rung's comment" if warning.partial else "this rung's comment"
        detail = f"laddercodec cannot read {what}: {_first_line(warning.error)}."
        return Note(warning, Rule.COMMENT, warning.rung, detail)
    if isinstance(warning, RefusedFieldWarning):
        return Note(warning, Rule.PROGRAM, warning.rung, _first_line(warning.error))
    if type(warning) is UserWarning and str(warning).startswith(_LOST_BLANK_ROWS):
        # laddercodec says that the loss is cosmetic: the rung runs the same without them
        return Note(warning, Rule.WARN, None, str(warning))
    rung = getattr(warning, "rung", None)
    rung = rung if isinstance(rung, int) else None
    detail = f"laddercodec warned about this rung: {_first_line(warning)}."
    return Note(warning, Rule.RUNG if rung is not None else Rule.PROGRAM, rung, detail)


def sort_warnings(found: list[Warning], *, writing: bool = False) -> list[Note]:
    """Return a note for each laddercodec warning in *found*, in order.

    Pass on each warning whose rule is ``Rule.WARN`` at once. The caller handles the rest.
    """
    notes = [_note(warning, writing=writing) for warning in found]
    for note in notes:
        if note.rule is Rule.WARN:
            _pass_on(note.warning)
    return notes


def pass_on_legacy(notes: list[Note]) -> list[Note]:
    """Pass on each legacy-encoding warning in *notes*, and return the other notes."""
    for note in notes:
        if note.rule is Rule.LEGACY:
            _pass_on(note.warning)
    return [note for note in notes if note.rule is not Rule.LEGACY]
