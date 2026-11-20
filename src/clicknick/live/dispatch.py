"""Dispatch commands for live editing.

``dispatch()`` ALWAYS runs on the Tk main thread (the ``LiveServer`` drain
loop marshals it there), so it may freely call ``AddressStore.edit_session``
and trigger observer refreshes.

Grammar (one command per connection)::

    ping                               -> liveness + connection state + status
    get  <ID>                          -> show current row fields + dirty flag
    set  <ID> <field> <value...>       -> edit a field (appears as a staged change)
    unused <type-or-addr>... [count]   -> free address(es); one per hint
    backup                             -> snapshot src/plc for recovery (keeps the last 5)
    restore [<time>|list]              -> replace src/plc from the newest or an older snapshot; list them
    check                              -> lint the editable pyrung proposal
    tag  <subcommand> ...              -> annotation metadata operations
    rung <subcommand> ...              -> program listing / apply
    prompt-save                        -> pop a save reminder dialog in the GUI
``<field>`` is one of: nickname, comment, initial_value, retentive.
Values may be quoted, e.g. ``set DS1 comment "Main motor run"``; a backslash
escapes only ``"`` and ``\\`` inside double quotes (``split_words``).
``<ID>`` is a pyrung tag name (preferred) or CLICK display address (``DS1``, ``C100``).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyclickplc.addresses import get_addr_key, iter_address_slots, parse_address
from pyclickplc.banks import BANKS

from ..services.annotation_service import AnnotationService

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ..connection_session import ConnectionSession
    from ..data.address_store import AddressStore

_EDITABLE_FIELDS = ("nickname", "comment", "initial_value", "retentive")


def _no_session() -> None:
    """Return None. A context with no CLICK window connected has no session."""
    return None


@dataclass
class DispatchContext:
    """Everything dispatch commands might need, rebuilt each drain cycle."""

    store: AddressStore | None = None
    resolve_tag: Callable[[str], int | None] | None = None
    analysis: Any | None = None  # AnalysisService (avoid import for lightweight CLI)
    # Returns the connected window's session, or None when no window is connected
    get_session: Callable[[], ConnectionSession | None] = _no_session
    annotation: AnnotationService = field(default_factory=AnnotationService)
    # Opens Review Changes. The arguments are the bundle folder, the workspace source
    # folder, the program to select, its rungs to paste, and whether to open a window
    # if none shows the folder.
    show_proposal: Callable[[Path, Path, str | None, list[int] | None, bool], None] | None = None
    show_address_editor: Callable[[str], None] | None = None
    show_save_prompt: Callable[[str, str], None] | None = None
    record_staged_rungs: Callable[[int], None] | None = None
    synced_pending: int = 0
    staged_rungs: int = 0
    project_saved: bool | None = None
    pyrung_live_available: bool = False


_WHITESPACE = " \t\r\n"


def _read_commands(text: str, *, chain: bool) -> list[list[str]]:
    """Read *text* into commands of words, as a POSIX shell quotes them.

    Single or double quotes group words. Inside double quotes a backslash escapes
    ``"`` and ``\\``. Anywhere else a backslash is an ordinary character, so a Windows
    path such as ``C:\\temp`` stays as typed. With *chain*, a ``;`` outside quotes ends
    a command.
    """
    commands: list[list[str]] = [[]]
    word: list[str] = []
    in_word = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _WHITESPACE or (chain and ch == ";"):
            if in_word:
                commands[-1].append("".join(word))
                word, in_word = [], False
            if ch == ";":
                commands.append([])
        elif ch == "'":
            end = text.find("'", i + 1)
            if end < 0:
                raise ValueError("No closing quotation")
            word.append(text[i + 1 : end])
            in_word, i = True, end
        elif ch == '"':
            i += 1
            while True:
                if i >= len(text):
                    raise ValueError("No closing quotation")
                ch = text[i]
                if ch == '"':
                    break
                if ch == "\\" and text[i + 1 : i + 2] in ('"', "\\"):
                    i += 1
                    ch = text[i]
                word.append(ch)
                i += 1
            in_word = True
        else:
            word.append(ch)
            in_word = True
        i += 1
    if in_word:
        commands[-1].append("".join(word))
    return [words for words in commands if words]


def split_words(command: str) -> list[str]:
    """Split one command into its words, as ``_read_commands`` does.

    ``quote_words`` writes words back so that this function returns them unchanged.
    """
    commands = _read_commands(command, chain=False)
    return commands[0] if commands else []


def split_commands(text: str) -> list[list[str]]:
    """Split a command line into commands at each ``;`` outside quotes."""
    return _read_commands(text, chain=True)


def quote_words(words: list[str]) -> str:
    """Join *words* into one command that ``split_words`` reads back unchanged."""
    return " ".join(shlex.quote(word) for word in words)


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
        return f"{identifier} has no row in the Address Editor."
    dirty = " (staged)" if ctx.store.is_dirty(addr_key) else ""
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
        raise ValueError(f"{identifier} has no row in the Address Editor.")

    value: str | bool = _parse_bool(raw_value) if field_name == "retentive" else raw_value

    with ctx.store.edit_session(f"AI: set {identifier} {field_name}") as session:
        session.set_field(addr_key, field_name, value)

    # Report the value as stored. The store strips spaces and tabs from either end of a
    # nickname, a comment and a non-Text initial value. CLICK also trims a space from either
    # end of a nickname or a comment.
    stored = getattr(ctx.store.get_visible_row(addr_key), field_name)
    return f"OK: {identifier} {field_name} = {stored!r} (staged change)"


def _iter_bank_addresses(memory_type: str, start: int | None):
    """Yield the MDB addresses of *memory_type* that CLICK shows, in ascending order.

    If *start* is given, skip the addresses below it, so that a scan can resume there.
    """
    for slot_type, addr in iter_address_slots():
        if slot_type == memory_type and (start is None or addr >= start):
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


def _project_status(ctx: DispatchContext) -> str | None:
    """Return the state of the workspace and the simulation in user-facing terms."""
    if ctx.project_saved is False:
        return "project not saved in CLICK | Save in CLICK to build the workspace"

    analysis = ctx.analysis
    if analysis is None:
        return None
    status = getattr(getattr(analysis, "status", None), "value", None)
    if status == "building":
        return "building the workspace"
    if status == "failed":
        error = getattr(analysis, "error", None)
        failed = (
            f"could not build the workspace: {error}" if error else "could not build the workspace"
        )
        if getattr(analysis, "project_dir", None) is not None:
            return f"{failed} | the last workspace built is still there"
        return failed
    if analysis.is_available:
        if ctx.pyrung_live_available:
            return "simulation ready for pyrung live"
        return "workspace ready | use Tools > Simulate to start a simulation for pyrung live"

    return None


def _workflow_status(ctx: DispatchContext) -> str | None:
    """Compose known outgoing changes and their next engineer actions."""
    facts: list[str] = []
    steps: list[str] = []
    staged_tags = 0
    if ctx.store is not None:
        staged_tags = len(ctx.store.get_dirty_keys())
        if staged_tags > 0:
            noun = "tag" if staged_tags == 1 else "tags"
            facts.append(f"{staged_tags} {noun} staged")
            save = save_command(ctx.store)
            steps.append(
                f"{save} tags in ClickNick" if staged_tags != 1 else f"{save} in ClickNick"
            )
    if ctx.synced_pending > 0:
        noun = "tag" if ctx.synced_pending == 1 else "tags"
        facts.append(f"{ctx.synced_pending} {noun} synced")
    if ctx.staged_rungs > 0:
        noun = "rung" if ctx.staged_rungs == 1 else "rungs"
        facts.append(f"{ctx.staged_rungs} {noun} staged")
        steps.append("paste rungs if needed" if ctx.staged_rungs != 1 else "paste if needed")

    if ctx.synced_pending > 0 or ctx.staged_rungs > 0:
        steps.append("Save in CLICK")
    if not facts:
        return None

    if len(steps) == 1:
        action = steps[0]
    else:
        action = ", ".join(steps[:-1]) + f", then {steps[-1]}"
    action = action[:1].upper() + action[1:]
    return " | ".join([*facts, f"Next: {action}"])


def _status_footer(ctx: DispatchContext) -> str:
    lines: list[str] = []
    workflow_status = _workflow_status(ctx)
    if workflow_status is not None:
        lines.append(f"[{workflow_status}]")
    project_status = _project_status(ctx)
    if project_status is not None:
        lines.append(f"[{project_status}]")
    if not lines:
        return ""
    return "\n" + "\n".join(lines)


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

workspace:
  backup                              -> snapshot src/plc to backup/src/plc
                                         (the one before moves to backup/older/<time>; 5 kept)
  restore                             -> replace src/plc from backup/src/plc
                                         (edits in src/plc no backup holds are backed up first)
  restore list                        -> list the older backups, newest first
  restore <time>                      -> replace src/plc from backup/older/<time>
                                         (a backup taken again takes a new name)

analysis:
  check                               -> lint src/plc with the rules that Tools > Check Program uses

tags:
  tag show <tag>
  tag repair-system-nicknames         -> the same as Tools > Repairs > System Nicknames
  tag set-flag <tag> <flag>
  tag clear-flag <tag> <flag>
  tag set-choices <tag> <Label:val> ...
  tag set-range <tag> <min> <max>
  tag clear-constraints <tag>
  tag set-uom <tag> <unit>
  tag clear-uom <tag>
  tag upgrade-project                 -> the same as Tools > Repairs > Upgrade Project
  tag set-physical <tag> <name> <response> [--system S]
    response: {physical_options}
  tag set-link <tag> <link>
  tag clear-physical <tag>
  tag apply                          -> copy your edits in src/plc/tags.py to the Address
                                        Editor as unsaved edits, and open it on Changed

rungs:
  rung list [file]
  rung apply [file] [--select r3,r7]  -> stage and open Review Changes

workflow:
  prompt-save"""


def save_command(store: AddressStore) -> str:
    """Return the Address Editor's word for writing *store*'s edits: "Sync" or "Save".

    The editor syncs edits to CLICK's database and saves them to a CSV file. The labels of its
    menu entries vary with how the editor was opened, so a message names only the verb.
    """
    return "Sync" if store.is_database else "Save"


def _rows(count: int) -> str:
    """Return "1 row" or "<count> rows"."""
    return "1 row" if count == 1 else f"{count} rows"


def _format_help() -> str:
    from ..services.physical_response import cli_usage

    return _HELP_TEXT.format(physical_options=cli_usage())


def _no_addresses_reason(ctx: DispatchContext) -> str:
    """Say why ClickNick has no addresses loaded, and what to do.

    With a CLICK window connected, the text says why ClickNick has not loaded CLICK's database for
    that window.
    """
    from ..connection_session import no_database_reason

    session = ctx.get_session()
    if session is None:
        advice = "Connect to a CLICK window, or use File > Load Nicknames from CSV"
    else:
        advice = no_database_reason(session, nicknames_needed=True)
    return f"ClickNick has no addresses loaded. {advice}."


def dispatch(ctx: DispatchContext, command: str) -> str:
    """Execute one *command* against *ctx*; return human-readable text.

    Runs on the Tk main thread. Raises on bad input; the caller turns
    exceptions into ``ERROR: ...`` replies.
    """
    parts = split_words(command)
    if not parts:
        raise ValueError("empty command")

    verb = parts[0].lower()

    if verb == "help":
        return _format_help()

    if verb == "ping":
        lines = ["pong"]
        if ctx.store is not None:
            lines.append(f"addresses loaded: {ctx.store.loaded_row_count}")
            staged = len(ctx.store.get_dirty_keys())
            if staged:
                lines.append(f"tags staged: {staged}")
        else:
            lines.append("addresses loaded: none")
        if ctx.synced_pending > 0:
            lines.append(f"tags synced: {ctx.synced_pending}")
        if ctx.staged_rungs > 0:
            lines.append(f"rungs staged: {ctx.staged_rungs}")
        workflow_status = _workflow_status(ctx)
        if workflow_status is not None:
            lines.append(f"workflow: {workflow_status}")
        if ctx.analysis is not None and (
            ctx.analysis.is_available or getattr(ctx.analysis, "project_dir", None) is not None
        ):
            pdir = ctx.analysis.project_dir
            lines.append(f"workspace: {pdir}" if pdir else "workspace: not on disk")
        project_status = _project_status(ctx)
        if project_status is not None:
            lines.append(f"status: {project_status}")
        return "\n".join(lines)

    if verb == "prompt-save":
        if ctx.store is None or not ctx.store.has_unsaved_changes():
            return "no pending changes"
        save = save_command(ctx.store)
        if ctx.store.has_errors():
            # Sync writes nothing while any row has an error, even a row that has no unsaved edit.
            bad = ctx.store.get_total_error_count()
            raise ValueError(
                f"The Address Editor shows errors in {_rows(bad)}. {save} writes nothing"
                " while any row has an error. Fix those rows first."
            )
        count = len(ctx.store.get_dirty_keys())
        if ctx.show_save_prompt is not None:
            target = "CLICK's database" if ctx.store.is_database else "the CSV file"
            ctx.show_save_prompt(
                "Unsaved Changes",
                f"{_rows(count)} in the Address Editor {'has' if count == 1 else 'have'}"
                f" unsaved edits.\n\n{save} them there to write them to {target}.",
            )
        return f"prompted: {_rows(count)} with unsaved edits"

    if ctx.store is None:
        raise ValueError(_no_addresses_reason(ctx))

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

    if verb in ("backup", "restore"):
        if verb == "backup" and len(parts) != 1:
            raise ValueError("usage: backup")
        if verb == "restore" and len(parts) > 2:
            raise ValueError("usage: restore [<time>|list]")

        from ..services.project_workspace import (
            backup_plc_source,
            older_plc_backup_time,
            older_plc_backups,
            plc_backup_dir,
            restore_plc_source,
        )
        from .rung_commands import _get_project_dir

        project_dir = _get_project_dir(ctx)
        note = ""
        if verb == "backup":
            path, file_count = backup_plc_source(project_dir)
            action, preposition = "backed up", "to"
        elif parts[1:] == ["list"]:
            names = older_plc_backups(project_dir)
            listing = (
                "\n".join(
                    f"{name}  (taken {older_plc_backup_time(name).astimezone():%Y-%m-%d %H:%M:%S})"
                    for name in names
                )
                if names
                else "no older backups"
            )
            return listing + _status_footer(ctx)
        else:
            restored = restore_plc_source(project_dir, *parts[1:])
            path, file_count = restored.restored_from, restored.file_count
            action, preposition = "restored", "from"
            if restored.edits_backed_up:
                note = f". Your edits to src/plc were backed up to {plc_backup_dir(project_dir)}"
        files = "source file" if file_count == 1 else "source files"
        return f"OK: {action} {file_count} {files} {preposition} {path}{note}" + _status_footer(ctx)

    if verb == "check":
        if len(parts) != 1:
            raise ValueError("usage: check")

        from ..services.program_check import run_project_check
        from .rung_commands import _get_project_dir

        project_dir = _get_project_dir(ctx)
        selection = getattr(ctx.analysis, "check_selection", None)
        notes = ""
        warning = getattr(ctx.analysis, "build_warning", None)
        if warning:
            notes = f"NOTE: {warning}\n"
        if selection is not None:
            selection.sync(project_dir)
            notes += "".join(f"NOTE: {item.describe()}\n" for item in selection.take_dropped())
        return notes + run_project_check(project_dir) + _status_footer(ctx)

    if verb == "tag":
        from .tag_commands import dispatch_tag

        return dispatch_tag(ctx, parts[1:]) + _status_footer(ctx)

    if verb == "rung":
        from .rung_commands import dispatch_rung

        return dispatch_rung(ctx, parts[1:]) + _status_footer(ctx)

    raise ValueError(f"unknown command {verb!r} — try 'help' for a list of commands")
