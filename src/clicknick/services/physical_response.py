"""How a feedback answers its command, read from pyrung's table of physical kinds.

pyrung's ``PHYSICAL_KINDS`` lists every kind (delay, flasher, timed, toggle, ramp,
approach) and its keys. Every ClickNick view of a response reads pyrung's table through
this module, so a kind pyrung adds needs no change here. This module is pure logic, with
no tkinter and no store.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pyrung import Physical
from pyrung.click.tag_map import TagMeta
from pyrung.core import (
    PHYSICAL_KEYS,
    PHYSICAL_KINDS,
    FeedbackType,
    PhysicalKey,
    PhysicalKind,
    kind_of_keys,
    physical_kind,
)

#: A response as a comment writes it, in table order, such as
#: ``(("on_delay", "2s"), ("toggle", True))``. It is a tuple so a link that holds one stays
#: hashable.
Response = tuple[tuple[str, str | bool], ...]

__all__ = [
    "PHYSICAL_KEYS",
    "PHYSICAL_KINDS",
    "FeedbackType",
    "PhysicalKey",
    "PhysicalKind",
    "Response",
    "cli_option",
    "cli_usage",
    "dap_arguments",
    "kinds_for",
    "meta_fields",
    "meta_response",
    "physical_kind",
    "response",
    "response_check",
    "response_from_dap",
    "response_kind",
    "response_label",
    "response_of",
    "response_tokens",
    "same_response",
    "shown_keys",
]


def response_of(values: Mapping[str, Any]) -> Response:
    """The response keys set in *values*, in table order. ``None`` and ``False`` are unset.

    Other names in *values* (``link``, ``system``...) are ignored.
    """
    out: list[tuple[str, str | bool]] = []
    for name, key in PHYSICAL_KEYS.items():
        value = values.get(name)
        if value is None or value is False:
            continue
        if key.is_flag:
            out.append((name, True))
        else:
            text = str(value).strip()
            if text:
                out.append((name, text))
    return tuple(out)


def response(**values: str | bool | None) -> Response:
    """``response(on_delay="2s")`` builds a response from keyword arguments."""
    return response_of(values)


def same_response(a: Response, b: Response) -> bool:
    """True when pyrung reads *a* and *b* as one response.

    The simulation reports a number as pyrung writes it (``1`` for ``1.0``) and leaves out
    a key at its default (``ramp_off=0``), so equal responses can differ in text.
    """
    if a == b:
        return True
    try:
        return Physical.from_text("_", dict(a)) == Physical.from_text("_", dict(b))
    except ValueError:
        return False


def response_kind(keys: Response | Iterable[str]) -> PhysicalKind | None:
    """The kind of *keys*, or ``None`` when they are none or make no one kind."""
    names = [item[0] if isinstance(item, tuple) else item for item in keys]
    try:
        return kind_of_keys(names)
    except ValueError:
        return None


def kinds_for(feedback: FeedbackType | None) -> tuple[PhysicalKind, ...]:
    """The kinds a bool or an analog feedback can have. ``None`` gives every kind."""
    return tuple(kind for kind in PHYSICAL_KINDS if feedback in (None, kind.feedback))


def shown_keys(kind: PhysicalKind) -> tuple[PhysicalKey, ...]:
    """The keys a form asks for. A required flag (``toggle``) is set by picking its kind."""
    return tuple(key for key in kind.keys if not (key.is_flag and key.required))


def response_check(values: Response) -> list[str]:
    """What is wrong with *values*, one message per problem. Empty means pyrung reads it.

    Each value goes through its key's own parser, so a duration needs units and a rate
    must be a number.
    """
    errors: list[str] = []
    for name, value in values:
        key = PHYSICAL_KEYS.get(name)
        if key is None:
            errors.append(f"unknown key {name!r}.")
        elif not key.is_flag:
            try:
                key.parse(str(value))
            except ValueError as exc:
                errors.append(str(exc))
    if errors:
        return errors
    try:
        kind_of_keys([name for name, _value in values])
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def response_tokens(values: Response) -> list[str]:
    """Comment and console tokens: ``on_delay=2s``, or the bare key for a flag."""
    return [
        name if PHYSICAL_KEYS[name].is_flag else f"{name}={value}"
        for name, value in values
        if name in PHYSICAL_KEYS
    ]


def response_label(values: Response) -> str:
    """The response for a label or tooltip: ``on_delay=2s, off_delay=500ms``."""
    return ", ".join(response_tokens(values))


def meta_fields(values: Response) -> dict[str, str | bool | None]:
    """Every response field of a ``TagMeta`` set to *values*, ready for ``replace(meta, **...)``.

    The keys *values* leaves out are cleared, so the response is replaced whole.
    """
    given = dict(values)
    return {
        name: bool(given.get(name)) if key.is_flag else given.get(name)
        for name, key in PHYSICAL_KEYS.items()
    }


def meta_response(meta: TagMeta | None) -> Response:
    """The response a ``TagMeta`` declares."""
    return () if meta is None else response_of(meta.physical_values())


def dap_arguments(values: Response) -> dict[str, str | bool]:
    """The ``pyrungLink`` request fields for *values*: ``{"onDelay": "2s"}``."""
    return {PHYSICAL_KEYS[name].dap_field: value for name, value in values if name in PHYSICAL_KEYS}


def response_from_dap(row: Mapping[str, Any]) -> Response:
    """The response in a ``pyrungListLinks`` row, which uses the request field names."""
    return response_of({name: row.get(key.dap_field) for name, key in PHYSICAL_KEYS.items()})


def key_tooltip(key: PhysicalKey) -> str:
    """A field's tooltip. The form shows the key's label, so the tooltip names the key."""
    return f"{key.help}\nWritten in the comment as {key.name}."


def cli_option(key: PhysicalKey) -> str:
    """The CLI option for *key*: ``--on-delay``."""
    return "--" + key.name.replace("_", "-")


def _value_hint(key: PhysicalKey) -> str:
    return {"duration": "TIME", "number": "N", "number_or_tag": "N|TAG"}.get(key.value_type, "")


def cli_usage() -> str:
    """The response options of ``tag set-physical``, one kind per bracket group."""
    groups = []
    for kind in PHYSICAL_KINDS:
        parts = []
        for key in kind.keys:
            if key.is_flag:
                parts.append(cli_option(key))
            else:
                parts.append(f"{cli_option(key)} {_value_hint(key)}")
        groups.append(f"[{' '.join(parts)}]")
    return " | ".join(groups)
