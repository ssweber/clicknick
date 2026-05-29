"""Tag annotation commands for live editing.

Semantic operations on bracket-syntax annotation metadata in comment fields.
All commands accept a pyrung tag name (preferred) or CLICK display address.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pyrung.click.tag_map import TagMeta, format_tag_meta

from ..services.annotation_service import AnnotationService
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
    return f"OK: {identifier} -> {bracket or '(no annotations)'} (unsaved change)"


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


def _cmd_set_physical(ctx: DispatchContext, parts: list[str]) -> str:
    if len(parts) < 2:
        raise ValueError(
            "usage: tag set-physical <identifier> <name> "
            "[--on-delay D] [--off-delay D] [--profile P] [--system S]"
        )
    identifier = parts[0]
    name = parts[1]
    on_delay = off_delay = profile = system = None

    i = 2
    while i < len(parts):
        opt = parts[i].lower()
        if opt == "--on-delay" and i + 1 < len(parts):
            on_delay = parts[i + 1]
            i += 2
        elif opt == "--off-delay" and i + 1 < len(parts):
            off_delay = parts[i + 1]
            i += 2
        elif opt == "--profile" and i + 1 < len(parts):
            profile = parts[i + 1]
            i += 2
        elif opt == "--system" and i + 1 < len(parts):
            system = parts[i + 1]
            i += 2
        else:
            raise ValueError(f"unexpected argument {parts[i]!r}")

    addr_key, block_tag, meta, free_text = _get_meta(ctx, identifier)
    meta = replace(
        meta,
        physical=name,
        on_delay=on_delay,
        off_delay=off_delay,
        profile=profile,
        system=system,
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
        meta, physical=None, link=None, on_delay=None, off_delay=None, profile=None, system=None
    )
    return _apply_meta(
        ctx, identifier, addr_key, block_tag, meta, free_text, f"tag clear-physical {identifier}"
    )


_SUBCOMMANDS = {
    "show": _cmd_show,
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
