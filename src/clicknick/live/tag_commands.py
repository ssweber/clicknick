"""Tag annotation commands for live editing.

Semantic operations on bracket-syntax annotation metadata in comment fields.
All commands accept a pyrung tag name (preferred) or CLICK display address.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import TYPE_CHECKING

from pyrung.click.tag_map import TagMeta, format_tag_meta

from ..models.address_row import initial_values_differ
from ..services.annotation_service import AnnotationService
from ..services.comment_upgrade_service import stage_comment_upgrades
from ..services.physical_response import (
    PHYSICAL_KEYS,
    cli_option,
    cli_usage,
    meta_fields,
    response_of,
)
from ..services.system_nickname_service import stage_system_nickname_repairs
from .dispatch import _resolve_identifier

if TYPE_CHECKING:
    from .dispatch import DispatchContext

_BOOL_FLAGS = ("readonly", "external", "final", "public", "lock")


def _get_meta(ctx: DispatchContext, identifier: str) -> tuple[int, str | None, TagMeta, str]:
    """Resolve identifier, decompose comment into parts.

    Returns (addr_key, block_tag_str, meta, free_text).
    """
    assert ctx.store is not None
    addr_key = _resolve_identifier(ctx, identifier)
    row = ctx.store.get_visible_row(addr_key)
    if row is None:
        raise ValueError(f"{identifier}: not in store")
    block_tag, meta, free_text = AnnotationService.decompose_comment(row.comment)
    if meta is None:
        meta = TagMeta()
    return addr_key, block_tag, meta, free_text


def _apply_meta(
    ctx: DispatchContext,
    identifier: str,
    addr_key: int,
    block_tag: str | None,
    meta: TagMeta,
    free_text: str,
    description: str,
) -> str:
    """Validate, recompose, and write the modified meta back to the comment field."""
    errors = AnnotationService.validate_meta(meta)
    if errors:
        raise ValueError(f"validation failed: {'; '.join(errors)}")

    new_comment = AnnotationService.recompose_comment(block_tag, meta, free_text)
    assert ctx.store is not None
    with ctx.store.edit_session(f"AI: {description}") as session:
        session.set_field(addr_key, "comment", new_comment)

    bracket = format_tag_meta(meta)
    return f"OK: {identifier} -> {bracket or '(no annotations)'} (staged change)"


def _cmd_show(ctx: DispatchContext, parts: list[str]) -> str:
    if not parts:
        raise ValueError("usage: tag show <identifier>")
    identifier = parts[0]
    assert ctx.store is not None
    addr_key = _resolve_identifier(ctx, identifier)
    row = ctx.store.get_visible_row(addr_key)
    if row is None:
        raise ValueError(f"{identifier}: not in store")

    block_tag, meta, free_text = AnnotationService.decompose_comment(row.comment)
    dirty = ctx.store.is_dirty(addr_key)

    lines = [
        f"address: {row.display_address}",
        f"nickname: {row.nickname!r}",
    ]
    if meta:
        bracket = format_tag_meta(meta)
        if bracket:
            lines.append(f"annotations: {bracket}")
    if block_tag:
        lines.append(f"block_tag: {block_tag}")
    if free_text:
        lines.append(f"comment: {free_text!r}")
    lines.append(f"initial_value: {row.initial_value!r}")
    lines.append(f"retentive: {row.retentive}")
    if dirty:
        lines.append("status: UNSAVED")
    return "\n".join(lines)


def _cmd_repair_system_nicknames(ctx: DispatchContext, parts: list[str]) -> str:
    """Stage known vendor system-nickname repairs through the AddressStore."""
    if parts:
        raise ValueError("usage: tag repair-system-nicknames")

    assert ctx.store is not None
    repairs = stage_system_nickname_repairs(ctx.store)
    if not repairs:
        return "system nickname repair: no known corrections needed"

    if ctx.show_address_editor is not None:
        ctx.show_address_editor("changed")

    lines = [f"OK: {len(repairs)} system nickname repairs staged"]
    for repair in repairs:
        lines.append(f"{repair.display_address}: {repair.current!r} -> {repair.replacement!r}")
    lines.append("Review in Address Editor -> Changed, then Sync to save")
    return "\n".join(lines)


def _cmd_upgrade_project(ctx: DispatchContext, parts: list[str]) -> str:
    """Stage pyrung's rewrites of old annotation forms through the AddressStore."""
    if parts:
        raise ValueError("usage: tag upgrade-project")

    assert ctx.store is not None
    upgrades = stage_comment_upgrades(ctx.store)
    if not upgrades:
        return "upgrade project: every annotation is in the current form"

    staged = [upgrade for upgrade in upgrades if upgrade.staged]
    if staged and ctx.show_address_editor is not None:
        ctx.show_address_editor("changed")

    lines = [f"OK: {len(staged)} comment upgrade{'s' if len(staged) != 1 else ''} staged"]
    for upgrade in staged:
        lines.append(f"{upgrade.display_address}: {upgrade.current!r} -> {upgrade.replacement!r}")
    for upgrade in upgrades:
        if upgrade.problem:
            lines.append(f"{upgrade.display_address}: fix by hand, {upgrade.problem}")
    if staged:
        lines.append("Review in Address Editor -> Changed, then Sync to save")
    return "\n".join(lines)


def _cmd_set_flag(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError(
            f"usage: tag set-flag <identifier> <flag>  (flags: {', '.join(_BOOL_FLAGS)})"
        )
    identifier, flag = parts[0], parts[1].lower()
    if flag not in _BOOL_FLAGS:
        raise ValueError(f"unknown flag {flag!r} (expected one of: {', '.join(_BOOL_FLAGS)})")
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, **{flag: True})
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag set-flag {identifier} {flag}"
    )


def _cmd_clear_flag(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError(
            f"usage: tag clear-flag <identifier> <flag>  (flags: {', '.join(_BOOL_FLAGS)})"
        )
    identifier, flag = parts[0], parts[1].lower()
    if flag not in _BOOL_FLAGS:
        raise ValueError(f"unknown flag {flag!r} (expected one of: {', '.join(_BOOL_FLAGS)})")
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, **{flag: False})
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag clear-flag {identifier} {flag}"
    )


def _parse_choices(args: list[str]) -> dict[int | float | str, str]:
    """Parse choice arguments like 'Off:0' 'On:1' or 'Bool'."""
    if len(args) == 1 and args[0] == "Bool":
        return {0: "False", 1: "True"}
    choices: dict[int | float | str, str] = {}
    for pair in args:
        label, sep, val_str = pair.partition(":")
        if not sep or not label:
            raise ValueError(f"bad choice format {pair!r} (expected Label:value)")
        try:
            val: int | float | str = int(val_str)
        except ValueError:
            try:
                val = float(val_str)
            except ValueError:
                val = val_str
        choices[val] = label
    if not choices:
        raise ValueError("at least one choice required")
    return choices


def _cmd_set_choices(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("usage: tag set-choices <identifier> <Label:value> ... | Bool")
    identifier = parts[0]
    choices = _parse_choices(parts[1:])
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, choices=choices, min=None, max=None)
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag set-choices {identifier}"
    )


def _cmd_set_range(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 3:
        raise ValueError("usage: tag set-range <identifier> <min> <max>")
    identifier = parts[0]
    try:
        min_val: int | float = int(parts[1])
    except ValueError:
        min_val = float(parts[1])
    try:
        max_val: int | float = int(parts[2])
    except ValueError:
        max_val = float(parts[2])
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, min=min_val, max=max_val, choices=None)
    return _apply_meta(
        ctx,
        identifier,
        addr_key,
        block_tag,
        meta,
        free_text,
        f"tag set-range {identifier} {min_val} {max_val}",
    )


def _cmd_clear_constraints(ctx: DispatchContext, parts: list[str]) -> str:
    if not parts:
        raise ValueError("usage: tag clear-constraints <identifier>")
    identifier = parts[0]
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, choices=None, min=None, max=None)
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag clear-constraints {identifier}"
    )


def _cmd_set_uom(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("usage: tag set-uom <identifier> <unit>")
    identifier, uom = parts[0], parts[1]
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, uom=uom)
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag set-uom {identifier} {uom}"
    )


def _cmd_clear_uom(ctx: DispatchContext, parts: list[str]) -> str:
    if not parts:
        raise ValueError("usage: tag clear-uom <identifier>")
    identifier = parts[0]
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, uom=None)
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag clear-uom {identifier}"
    )


def _set_physical_usage() -> str:
    return f"usage: tag set-physical <identifier> <name> {cli_usage()} [--system S]"


def _cmd_set_physical(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError(_set_physical_usage())
    identifier = parts[0]
    name = parts[1]
    options = {cli_option(key): key for key in PHYSICAL_KEYS.values()}
    values: dict[str, str | bool] = {}
    system = None

    seen: set[str] = set()
    i = 2
    while i < len(parts):
        opt = parts[i].lower()
        if opt in seen:
            raise ValueError(f"{opt} is given twice")
        seen.add(opt)
        key = options.get(opt)
        if key is not None and key.is_flag:
            values[key.name] = True
            i += 1
        elif key is not None and i + 1 < len(parts):
            values[key.name] = parts[i + 1]
            i += 2
        elif opt == "--system" and i + 1 < len(parts):
            system = parts[i + 1]
            i += 2
        else:
            raise ValueError(f"unexpected argument {parts[i]!r}\n{_set_physical_usage()}")

    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(
        meta,
        physical=name,
        system=system,
        **meta_fields(response_of(values)),
    )
    return _apply_meta(
        ctx,
        identifier,
        addr_key,
        block_tag,
        meta,
        free_text,
        f"tag set-physical {identifier} {name}",
    )


def _cmd_set_link(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError("usage: tag set-link <identifier> <link>")
    identifier, link = parts[0], parts[1]
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(meta, link=link)
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag set-link {identifier} {link}"
    )


def _cmd_clear_physical(ctx: DispatchContext, parts: list[str]) -> str:
    if not parts:
        raise ValueError("usage: tag clear-physical <identifier>")
    identifier = parts[0]
    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(
        meta,
        physical=None,
        link=None,
        system=None,
        **meta_fields(()),
    )
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag clear-physical {identifier}"
    )


def _export_nicknames(tags_source: str, out_csv) -> None:
    """Exec a ``src/plc/tags.py`` source and write its full Click nickname CSV.

    Passes the ``blocks`` ClickBlockSet so configured-but-unmapped slots (plain
    nicknames + annotations, the bulk of the table) are written, not just the
    TagMap ``map_to`` entries. tags.py is generated project code, trusted here.
    """
    ns: dict[str, object] = {}
    exec(compile(tags_source, "src/plc/tags.py", "exec"), ns)  # noqa: S102
    mapping = ns.get("mapping")
    if mapping is None:
        raise ValueError("tags.py did not define `mapping`")
    mapping.to_nickname_file(out_csv, blocks=ns.get("blocks"))  # type: ignore[attr-defined]


def _load_export_rows(project_dir):
    """Return (baseline_rows, current_rows): addr_key -> AddressRow.

    ``baseline`` is the pristine tags module reconstructed from the persisted ladder
    CSVs (what the project exported *before* the agent's edits); ``current`` is
    the tags.py on disk (with edits). Diffing the two exports cancels every
    systematic round-trip artifact (``[external]`` inference, bank-default
    retentive/initial on unnamed slots, hex padding, system addresses), leaving
    only the agent's genuine edits. The baseline uses the analog input channels
    recorded in csv/ when the workspace was generated: pyrung marks them ``external``.
    """
    import tempfile
    from pathlib import Path

    from ..data.data_source import CsvDataSource
    from ..services.analysis_service import read_analog_inputs
    from ..services.project_workspace import plc_source_dir
    from .rung_commands import _get_before_files

    analog_inputs = read_analog_inputs(project_dir / "csv")
    baseline_src = _get_before_files(project_dir, analog_inputs=analog_inputs).get(
        "src/plc/tags.py"
    )
    if not baseline_src:
        raise ValueError("could not reconstruct baseline tags.py from persisted CSVs")
    current_src = (plc_source_dir(project_dir) / "tags.py").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="clicknick_tagapply_") as td:
        base_csv = Path(td) / "baseline.csv"
        cur_csv = Path(td) / "current.csv"
        _export_nicknames(baseline_src, base_csv)
        _export_nicknames(current_src, cur_csv)
        return (
            CsvDataSource(str(base_csv)).load_all_addresses(),
            CsvDataSource(str(cur_csv)).load_all_addresses(),
        )


def _merge_meta(visible: TagMeta, base: TagMeta, cur: TagMeta) -> TagMeta:
    """Take each annotation key tags.py changed; keep the others as the store holds them."""
    changed = {
        f.name: getattr(cur, f.name)
        for f in fields(TagMeta)
        if getattr(cur, f.name) != getattr(base, f.name)
    }
    return replace(visible, **changed)


def _merge_comment(display_address: str, visible: str, base: str, cur: str) -> str:
    """Carry what tags.py changed in a comment into the comment the store holds.

    tags.py holds only part of a comment (generated code leaves out the block tag
    and the text), so the comment is split into block tag, annotations and text,
    and only the parts that differ between the two exports are taken.
    """
    decompose = AnnotationService.decompose_comment
    visible_block, visible_meta, visible_text = decompose(visible)
    base_block, base_meta, base_text = decompose(base)
    cur_block, cur_meta, cur_text = decompose(cur)
    meta = _merge_meta(visible_meta or TagMeta(), base_meta or TagMeta(), cur_meta or TagMeta())
    errors = AnnotationService.validate_meta(meta)
    if errors:
        raise ValueError(
            f"{display_address}: tags.py annotations do not fit the comment "
            f"{visible!r}: {'; '.join(errors)}"
        )
    return AnnotationService.recompose_comment(
        cur_block if cur_block != base_block else visible_block,
        meta,
        cur_text if cur_text != base_text else visible_text,
    )


def _compute_tag_changes(base_rows, cur_rows, store) -> list[tuple[int, str, str | bool]]:
    """Diff current-export against baseline-export into store field edits.

    Only fields that differ between the two exports are emitted, so exactly the
    agent's edits land. A row present in ``cur`` but absent from ``base`` is a
    brand-new tag on a previously-empty slot; it's compared against a synthesized
    default (using ``is_default_initial_value`` + ``DEFAULT_RETENTIVE``) so only
    genuinely-set fields count. A changed comment is merged into the store's
    comment part by part (``_merge_comment``). (Removals — a nickname dropped from
    tags.py — are not cleared: this is the additive add/annotate flow, not a full
    replace.)
    """
    from pyclickplc.banks import DEFAULT_RETENTIVE

    changes: list[tuple[int, str, str | bool]] = []
    for addr_key, cur in cur_rows.items():
        visible = store.get_visible_row(addr_key)
        if visible is None:
            continue  # not tracked by the store (hidden/unsupported slot)
        base = base_rows.get(addr_key)
        if base is None:
            base = replace(
                cur,
                nickname="",
                comment="",
                initial_value="",
                retentive=DEFAULT_RETENTIVE.get(cur.memory_type, False),
            )
        if cur.nickname != base.nickname:
            changes.append((addr_key, "nickname", cur.nickname))
        if cur.comment != base.comment:
            comment = _merge_comment(
                visible.display_address, visible.comment, base.comment, cur.comment
            )
            if comment != visible.comment:
                changes.append((addr_key, "comment", comment))
        if initial_values_differ(base, cur):
            changes.append((addr_key, "initial_value", cur.initial_value))
        if cur.retentive != base.retentive:
            changes.append((addr_key, "retentive", cur.retentive))
    return changes


def _cmd_apply(ctx: DispatchContext, parts: list[str]) -> str:
    """Push the agent's src/plc/tags.py edits into the store, then open the editor.

    Exports both the pristine (baseline) and edited (current) tags.py, diffs
    them so only real edits survive, lands them as one batched staged change,
    and pops the Address Editor filtered to "Changed" for review + Sync.
    """
    from .rung_commands import _get_project_dir

    assert ctx.store is not None
    store = ctx.store

    project_dir = _get_project_dir(ctx)
    base_rows, cur_rows = _load_export_rows(project_dir)
    changes = _compute_tag_changes(base_rows, cur_rows, store)

    if not changes:
        return "tag apply: no changes (tags.py matches the persisted project)"

    with store.edit_session("AI: tag apply") as session:
        for addr_key, field_name, value in changes:
            session.set_field(addr_key, field_name, value)

    n_rows = len({addr_key for addr_key, _, _ in changes})
    if ctx.show_address_editor is not None:
        ctx.show_address_editor("changed")
    return (
        f"OK: {n_rows} tag{'s' if n_rows != 1 else ''} changed "
        "(review in Address Editor → Changed, then Sync to save)"
    )


_SUBCOMMANDS = {
    "show": _cmd_show,
    "repair-system-nicknames": _cmd_repair_system_nicknames,
    "upgrade-project": _cmd_upgrade_project,
    "apply": _cmd_apply,
    "set-flag": _cmd_set_flag,
    "clear-flag": _cmd_clear_flag,
    "set-choices": _cmd_set_choices,
    "set-range": _cmd_set_range,
    "clear-constraints": _cmd_clear_constraints,
    "set-uom": _cmd_set_uom,
    "clear-uom": _cmd_clear_uom,
    "set-physical": _cmd_set_physical,
    "set-link": _cmd_set_link,
    "clear-physical": _cmd_clear_physical,
}


def dispatch_tag(ctx: DispatchContext, parts: list[str]) -> str:
    """Route ``tag <subcommand> ...`` to the right handler."""
    if not parts:
        raise ValueError(f"usage: tag <subcommand> ...  (subcommands: {', '.join(_SUBCOMMANDS)})")

    sub = parts[0].lower()
    handler = _SUBCOMMANDS.get(sub)
    if handler is None:
        raise ValueError(f"unknown tag subcommand {sub!r} (expected: {', '.join(_SUBCOMMANDS)})")
    return handler(ctx, parts[1:])
