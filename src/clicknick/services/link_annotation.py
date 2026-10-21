"""Bench links written into, and read back from, a feedback tag's comment.

"Save to project" turns a simulator bench link into the comment metadata
pyrung reads (``[on_delay=2s, off_delay=500ms, link=Motor_Run]``); after a
Sync the program declares the link itself and the bench copy drops away.
Pure logic: no tkinter, no store.
"""

from __future__ import annotations

from dataclasses import replace

from pyrung.click.tag_map import TagMeta

from .annotation_service import AnnotationService
from .sim_state import BenchLink

#: The parameters each pyrung profile takes, in the order a form shows them.
PROFILE_PARAMS: dict[str, tuple[str, str]] = {
    "pulse": ("on_dwell", "off_dwell"),
    "ramp": ("up", "down"),
    "approach": ("toward", "rate"),
}


def profile_token(kind: str, first: str, second: str) -> str:
    """``ramp:up=0.8|down=-0.05`` from a profile kind and its two parameters."""
    a, b = PROFILE_PARAMS[kind]
    return f"{kind}:{a}={first.strip()}|{b}={second.strip()}"


def split_profile(token: str) -> tuple[str, dict[str, str]]:
    """The kind and parameters of a profile token; ``("", {})`` if it is not one."""
    kind, sep, params = token.partition(":")
    if not sep or kind not in PROFILE_PARAMS:
        return "", {}
    values: dict[str, str] = {}
    for pair in params.split("|"):
        key, eq, value = pair.partition("=")
        if eq:
            values[key.strip()] = value.strip()
    return kind, values


def link_text(enable_name: str, link: BenchLink) -> str:
    """The ``link=`` value: the enable's nickname (or address), plus ``:trigger``."""
    return enable_name if link.trigger is None else f"{enable_name}:{link.trigger}"


def comment_with_link(comment: str, link: BenchLink, enable_name: str) -> str:
    """*comment* with its link and response replaced by *link*.

    The block tag, other metadata and free text are kept. A physical name is
    dropped: the response now belongs to this tag alone, so it cannot clash
    with a definition shared under that name.
    """
    if link.cut:
        raise ValueError("a cut link has nothing to write to the project")
    block_tag, meta, free_text = AnnotationService.decompose_comment(comment)
    meta = replace(
        meta or TagMeta(),
        link=link_text(enable_name, link),
        physical=None,
        on_delay=link.on_delay,
        off_delay=link.off_delay,
        profile=link.profile,
    )
    return AnnotationService.recompose_comment(block_tag, meta, free_text)


def comment_has_link(comment: str, link: BenchLink, enable_names: tuple[str, ...]) -> bool:
    """True when *comment* already declares *link* (enable by any of *enable_names*)."""
    if link.cut:
        return False
    try:
        _block_tag, meta, _free_text = AnnotationService.decompose_comment(comment)
    except ValueError:
        return False
    if meta is None or meta.link is None:
        return False
    return (
        meta.link in {link_text(name, link) for name in enable_names if name}
        and meta.on_delay == link.on_delay
        and meta.off_delay == link.off_delay
        and meta.profile == link.profile
    )
