"""Command dispatch for live editing.

``dispatch()`` ALWAYS runs on the Tk main thread (the ``LiveServer`` drain
loop marshals it there), so it may freely call ``AddressStore.edit_session``
and trigger observer refreshes.

Grammar (one command per connection)::

    ping                               -> liveness + connection state + status
    get  <ID>                          -> show current row fields + dirty flag
    set  <ID> <field> <value...>       -> edit a field (appears as unsaved change)
    unused <type-or-addr>... [count]   -> free address(es); one per hint
    tag  <subcommand> ...              -> annotation metadata operations
    rung <subcommand> ...              -> program listing / preview / apply
    prompt-save                        -> pop a save reminder dialog in the GUI
``<field>`` is one of: nickname, comment, initial_value, retentive.
Values may be quoted (shlex), e.g. ``set DS1 comment "Main motor run"``.
``<ID>`` is a pyrung tag name (preferred) or CLICK display address (``DS1``, ``C100``).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyclickplc.addresses import get_addr_key, is_xd_yd_hidden_slot, parse_address
from pyclickplc.banks import BANKS

from ..services.annotation_service import AnnotationService

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..data.address_store import AddressStore

_EDITABLE_FIELDS = ("nickname", "comment", "initial_value", "retentive")


@dataclass
class DispatchContext:
    """Everything dispatch commands might need, rebuilt each drain cycle."""

    store: AddressStore | None = None
    resolve_tag: Callable[[str], int | None] | None = None
    analysis: Any | None = None  # AnalysisService (avoid import for lightweight CLI)
    annotation: AnnotationService = field(default_factory=AnnotationService)
    show_preview: Callable[..., None] | None = None
    show_address_editor: Callable[[str], None] | None = None
    show_save_prompt: Callable[[str, str], None] | None = None
    synced_pending: int = 0


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes", "on", "y", "t"):
        return True
    if lowered in ("false", "0", "no", "off", "n", "f"):
        return False
    raise ValueError(f"expected a boolean for retentive, got {value!r}")


def _resolve_addr_key(addr: str) -> int:
    """Resolve a display address (e.g. 'D1') to its addr_key."""
    memory_type, mdb_address = parse_address(addr)
    return get_addr_key(memory_type, mdb_address)


def _resolve_identifier(ctx: DispatchContext, identifier: str) -> int:
    """Resolve a pyrung tag name or display address to addr_key.

    Tries tag name first (via AnalysisService reverse lookup), then falls
    back to Click address parsing.
    """
    if ctx.resolve_tag is not None:
        key = ctx.resolve_tag(identifier)
        if key is not None:
            return key
    return _resolve_addr_key(identifier)


def _cmd_get(ctx: DispatchContext, identifier: str) -> str:
    assert ctx.store is not None
    addr_key = _resolve_identifier(ctx, identifier)
    row = ctx.store.get_visible_row(addr_key)
    if row is None:
        return f"{identifier}: <not in store>"
    dirty = " (unsaved)" if ctx.store.is_dirty(addr_key) else ""
    return (
        f"{identifier}{dirty}: nickname={row.nickname!r} comment={row.comment!r} "
        f"initial_value={row.initial_value!r} retentive={row.retentive}"
    )


def _cmd_set(ctx: DispatchContext, identifier: str, field_name: str, raw_value: str) -> str:
    if field_name not in _EDITABLE_FIELDS:
        raise ValueError(
            f"unknown field {field_name!r} (expected one of {', '.join(_EDITABLE_FIELDS)})"
        )

    assert ctx.store is not None
    addr_key = _resolve_identifier(ctx, identifier)
    if ctx.store.get_visible_row(addr_key) is None:
        raise ValueError(f"identifier {identifier!r} is not present in this store")

    value: str | bool = _parse_bool(raw_value) if field_name == "retentive" else raw_value

    with ctx.store.edit_session(f"AI: set {identifier} {field_name}") as session:
        session.set_field(addr_key, field_name, value)

    return f"OK: {identifier} {field_name} = {value!r} (unsaved change)"


def _iter_bank_addresses(memory_type: str, start: int | None):
    """Yield MDB addresses for *memory_type* in ascending order.

    Skips hidden XD/YD slots. If *start* is given, addresses below it are
    skipped (used to resume scanning from a specific address).
    """
    bank = BANKS[memory_type]
    ranges = bank.valid_ranges or ((bank.min_addr, bank.max_addr),)
    for lo, hi in ranges:
        for addr in range(lo, hi + 1):
            if start is not None and addr < start:
                continue
            if is_xd_yd_hidden_slot(memory_type, addr):
                continue
            yield addr


def _parse_hint(hint: str) -> tuple[str, int | None]:
    """Parse a hint into (memory_type, start).

    A bare memory type ("C", "DS") scans the whole bank (start is None); a
    display address ("C100") resumes scanning from there. Parsed via display
    rules so X/Y padding and XD/YD encoding resolve to the right MDB address.
    """
    if any(ch.isdigit() for ch in hint):
        return parse_address(hint)
    memory_type = hint.upper()
    if memory_type not in BANKS:
        raise ValueError(f"unknown memory type {memory_type!r}")
    return memory_type, None


def _first_free(
    store, memory_type: str, start: int | None, taken: set[int]
) -> tuple[int, str] | None:
    """Return (addr_key, display) of the first free address at or after *start*.

    An address is "free" when it is not used in the program and carries no
    content (nickname/comment/non-default initial value or retentive), and is
    not already in *taken*. Returns None if the bank has no such address.
    """
    for addr in _iter_bank_addresses(memory_type, start):
        addr_key = get_addr_key(memory_type, addr)
        if addr_key in taken:
            continue
        row = store.visible_state.get(addr_key)
        if row is None:
            continue
        if not row.used and not row.has_content:
            return addr_key, row.display_address
    return None


def _cmd_unused(ctx: DispatchContext, hints: list[str], count: int) -> str:
    """Return free addresses, one per output line.

    With a single hint and ``count`` > 1, returns that many consecutive free
    addresses at or after the hint. With multiple hints, returns one free
    address per hint, each distinct from the others (so grabbing a pair for an
    interlock never hands back the same bit twice).
    """
    assert ctx.store is not None
    taken: set[int] = set()
    results: list[str] = []

    if count > 1:
        # count mode: one hint, `count` consecutive free addresses.
        memory_type, start = _parse_hint(hints[0])
        for _ in range(count):
            found = _first_free(ctx.store, memory_type, start, taken)
            if found is None:
                break
            addr_key, display = found
            taken.add(addr_key)
            results.append(display)
        if not results:
            where = f" at or after {hints[0].upper()}" if start is not None else ""
            raise ValueError(f"no free {memory_type} addresses{where}")
        return "\n".join(results)

    # hint mode: one free address per hint (each must resolve).
    for hint in hints:
        memory_type, start = _parse_hint(hint)
        found = _first_free(ctx.store, memory_type, start, taken)
        if found is None:
            where = f" at or after {hint.upper()}" if start is not None else ""
            raise ValueError(f"no free {memory_type} addresses{where}")
        addr_key, display = found
        taken.add(addr_key)
        results.append(display)
    return "\n".join(results)


def _status_footer(ctx: DispatchContext) -> str:
    parts: list[str] = []
    if ctx.store is not None:
        unsaved = len(ctx.store.user_overrides)
        if unsaved > 0:
            parts.append(f"{unsaved} unsaved")
    if ctx.synced_pending > 0:
        parts.append(f"{ctx.synced_pending}↑ not saved in Click")
    if not parts:
        return ""
    return "\n[" + " | ".join(parts) + "]"


_HELP_TEXT = """\
connection:
  ping
  help

data:
  get <tag-or-addr>
  set <tag-or-addr> <field> <value>
  unused <type-or-addr>... [count]   -> free address(es)
    unused C            -> first free C          (e.g. C5)
    unused C 3          -> 3 consecutive free C
    unused C1031 C1414  -> one free bit near each neighbor

tags:
  tag show <tag>
  tag set-flag <tag> <flag>
  tag clear-flag <tag> <flag>
  tag set-choices <tag> <Label:val> ...
  tag set-range <tag> <min> <max>
  tag clear-constraints <tag>
  tag set-uom <tag> <unit>
  tag clear-uom <tag>
  tag set-physical <tag> <name> [--on-delay D] [--off-delay D] [--profile P] [--system S]
  tag set-link <tag> <link>
  tag clear-physical <tag>
  tag apply                          -> edit tags.py, then push the diff
    (regenerates nicknames.csv, lands changed rows, opens Address Editor → Changed)

rungs:
  rung list [file]
  rung preview [file] [--select r3,r7]
  rung apply [file]
  (run apply before preview to enable the Copy button)

workflow:
  prompt-save"""


def _format_help() -> str:
    return _HELP_TEXT


def dispatch(ctx: DispatchContext, command: str) -> str:
    """Execute one *command* against *ctx*; return human-readable text.

    Runs on the Tk main thread. Raises on bad input; the caller turns
    exceptions into ``ERROR: ...`` replies.
    """
    parts = shlex.split(command)
    if not parts:
        raise ValueError("empty command")

    verb = parts[0].lower()

    if verb == "help":
        return _format_help()

    if verb == "ping":
        lines = ["pong"]
        if ctx.store is not None:
            lines.append(f"store: {len(ctx.store.visible_state)} rows")
            unsaved = len(ctx.store.user_overrides)
            if unsaved:
                lines.append(f"unsaved: {unsaved}")
        else:
            lines.append("store: not connected")
        if ctx.synced_pending > 0:
            lines.append(f"synced: {ctx.synced_pending}↑ not saved in Click")
        if ctx.analysis is not None and ctx.analysis.is_available:
            pdir = ctx.analysis.project_dir
            lines.append(f"project: {pdir}" if pdir else "project: (not persisted)")
        return "\n".join(lines)

    if verb == "prompt-save":
        if ctx.store is None or not ctx.store.has_unsaved_changes():
            return "no pending changes"
        count = len(ctx.store.user_overrides)
        if ctx.store.has_errors():
            raise ValueError(f"{count} unsaved change(s) have validation errors — fix errors first")
        if ctx.show_save_prompt is not None:
            ctx.show_save_prompt(
                "Unsaved Changes",
                f"You have {count} unsaved change{'s' if count != 1 else ''} "
                f"in the Address Editor.\n\n"
                f"Use File → Sync to write them to the Click database.",
            )
        return f"prompted: {count} unsaved change{'s' if count != 1 else ''}"

    if ctx.store is None:
        raise ValueError("no project loaded (connect a CLICK project or load a CSV first)")

    if verb == "get":
        if len(parts) != 2:
            raise ValueError("usage: get <ID>")
        return _cmd_get(ctx, parts[1]) + _status_footer(ctx)

    if verb == "set":
        if len(parts) < 4:
            raise ValueError("usage: set <ID> <field> <value...>")
        identifier, field_name = parts[1], parts[2].lower()
        raw_value = " ".join(parts[3:])
        return _cmd_set(ctx, identifier, field_name, raw_value) + _status_footer(ctx)

    if verb == "unused":
        hints = parts[1:]
        if not hints:
            raise ValueError(
                "usage: unused <type-or-addr> [more...|count]  "
                "(e.g. 'unused C', 'unused C 3', 'unused C1031 C1414')"
            )
        # A single hint followed by a bare integer means "count" (a bare number
        # is never a valid address hint, so this is unambiguous).
        count = 1
        if len(hints) == 2 and hints[1].isdigit():
            count = int(hints[1])
            if count < 1:
                raise ValueError("count must be >= 1")
            hints = hints[:1]
        # No status footer: keep output clean/scriptable (just the address(es)).
        return _cmd_unused(ctx, hints, count)

    if verb == "tag":
        from .tag_commands import dispatch_tag

        return dispatch_tag(ctx, parts[1:]) + _status_footer(ctx)

    if verb == "rung":
        from .rung_commands import dispatch_rung

        return dispatch_rung(ctx, parts[1:]) + _status_footer(ctx)

    raise ValueError(f"unknown command {verb!r} — try 'help' for a list of commands")
