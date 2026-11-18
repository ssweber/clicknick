"""Bring a folder's nicknames.csv into the Address Editor as edits to review and Sync.

A folder of ladder CSVs may carry the nicknames that its rungs use. ClickNick does not write
them to CLICK's database directly. It stages them in the AddressStore, so the Address
Editor validates them and the user Syncs them like any other edit.

Staging touches only the addresses that the file lists. An address that the file leaves out
keeps what it has. An address that the file lists with no nickname has its nickname cleared.
Only the fields that the file has a column for are set.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..models.address_row import AddressRow, initial_values_differ
from ..models.validation import trim_entry

if TYPE_CHECKING:
    from ..data.address_store import AddressStore

# The fields that a nicknames.csv sets, in the order that a change lists them
_FIELDS = ("nickname", "comment", "initial_value", "retentive")


@dataclass(frozen=True)
class FieldChange:
    """One field of one address that the file sets differently."""

    addr_key: int
    display_address: str
    field: str
    old: str | bool
    new: str | bool


@dataclass(frozen=True)
class NicknamePlan:
    """How a nicknames.csv differs from a set of rows, field by field."""

    changes: tuple[FieldChange, ...] = ()

    def _nicknames(self) -> list[FieldChange]:
        return [change for change in self.changes if change.field == "nickname"]

    @property
    def added(self) -> int:
        """Return the number of addresses that get a nickname where they had none."""
        return sum(1 for change in self._nicknames() if not change.old and change.new)

    @property
    def renamed(self) -> int:
        return sum(1 for change in self._nicknames() if change.old and change.new)

    @property
    def cleared(self) -> int:
        return sum(1 for change in self._nicknames() if change.old and not change.new)

    @property
    def other(self) -> int:
        """Return the number of addresses that keep their nickname but get a new comment,
        initial value or retentive setting.
        """
        renamed = {change.addr_key for change in self._nicknames()}
        return len({change.addr_key for change in self.changes} - renamed)

    def summary(self) -> str:
        """Return a summary such as ``40 new, 12 renamed, 3 cleared, 5 other``.

        The summary is empty when nothing differs.
        """
        parts = [
            f"{count} {word}"
            for count, word in (
                (self.added, "new"),
                (self.renamed, "renamed"),
                (self.cleared, "cleared"),
                (self.other, "other"),
            )
            if count
        ]
        return ", ".join(parts)

    def describe(self, limit: int) -> list[str]:
        """Return one line per change, ``X001 nickname: '' -> 'Start'``, up to *limit* lines."""
        lines = [
            f"{change.display_address} {change.field}: {change.old!r} -> {change.new!r}"
            for change in self.changes[:limit]
        ]
        if len(self.changes) > limit:
            lines.append(f"...and {len(self.changes) - limit} more")
        return lines

    def __bool__(self) -> bool:
        return bool(self.changes)


def plan_nicknames(
    rows: Mapping[int, AddressRow],
    current: Mapping[int, AddressRow],
    *,
    fields: Collection[str] = _FIELDS,
) -> NicknamePlan:
    """Return what staging *rows* (a nicknames.csv) would change in *current*.

    *current* is the store's visible rows, to see what is left to stage. It can also be the
    store's base rows, to see what CLICK's database still lacks. The plan leaves out
    addresses that the store does not track. It compares only *fields*. Pass the fields that
    the file has a column for (``CsvDataSource.fields``), so a column that the file lacks
    leaves that field as it is. A nickname, a comment and an initial value of any type but
    Text are taken as CLICK stores them, without a space or a tab at either end
    (``trim_entry``). So ``"Jog\\t"`` is staged as ``"Jog"``, and it is done once the database
    holds ``"Jog"``.
    """
    changes: list[FieldChange] = []
    compared = [field for field in _FIELDS if field in fields]
    for addr_key in sorted(rows):
        new = rows[addr_key]
        old = current.get(addr_key)
        if old is None:
            continue
        for field in compared:
            value = trim_entry(field, getattr(new, field), old.data_type)
            if field == "initial_value":
                differs = initial_values_differ(old, replace(new, initial_value=value))
            else:
                differs = getattr(old, field) != value
            if differs:
                changes.append(
                    FieldChange(addr_key, old.display_address, field, getattr(old, field), value)
                )
    return NicknamePlan(tuple(changes))


def stage_nicknames(store: AddressStore, plan: NicknamePlan, description: str) -> int:
    """Stage *plan* in *store* as one undoable edit and return how many fields were set."""
    if not plan:
        return 0
    with store.edit_session(description) as session:
        for change in plan.changes:
            session.set_field(change.addr_key, change.field, change.new)
    return len(plan.changes)
