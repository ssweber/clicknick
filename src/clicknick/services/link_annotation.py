"""Bench links written into, and read back from, a feedback tag's comment.

A bench link is a change to the feedback wiring of one input that the user makes in the
Simulator window. The program does not declare it. ClickNick saves it and applies it each
time a simulation starts, until the user removes it. "Save to project" writes the link
into the comment metadata that pyrung reads
(``[link=Motor_Run, on_delay=2s, off_delay=500ms]``). It does not remove the bench link.
After a Sync and a rebuild, the program declares the link. pyrung then drops the bench
copy if the declared link has the same wiring. If the wiring differs, the bench link
stays while it still fits the program.

This module has no tkinter code and no store. `linked_feedbacks` reads a workspace's
nicknames.csv.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pyclickplc.addresses import normalize_address, parse_address
from pyclickplc.banks import BANKS, DataType
from pyrung.click.tag_map import TagMeta

from ..data.data_source import CsvDataSource
from .annotation_service import AnnotationService
from .physical_response import meta_fields, meta_response, same_response
from .sim_state import BenchLink
from .tag_names import tag_names


def bit_enable(address: str | None) -> bool:
    """Return True if the CLICK *address* is a bit (X, Y, C, T, CT, SC), which is only ON or OFF.

    A bit enable's trigger is 0 (drive while it is OFF) or None (drive while it is ON).
    """
    normalized = normalize_address(address or "")
    if normalized is None:
        return False
    bank, _index = parse_address(normalized)
    return BANKS[bank].data_type == DataType.BIT


def when_text(enable: str | None, trigger: int | str | None) -> str:
    """Return when the enable drives the link, for labels: ``""``, ``" when OFF"`` or ``" = 3"``."""
    if trigger is None:
        return ""
    if bit_enable(enable):
        return " when OFF" if trigger == 0 else ""
    return f" = {trigger}"


def link_text(enable_name: str, link: BenchLink) -> str:
    """Return the ``link=`` value: the enable's nickname (or address), plus ``:trigger``.

    A bit enable that drives while OFF is written ``~Motor_Run``.
    """
    if link.trigger is None:
        return enable_name
    if link.trigger == 0 and bit_enable(link.enable):
        return f"~{enable_name}"
    return f"{enable_name}:{link.trigger}"


def _link_texts(enable_name: str, link: BenchLink) -> set[str]:
    """Return every ``link=`` value that declares *link*. Older projects spell ``~X`` as ``X:0``."""
    texts = {link_text(enable_name, link)}
    if link.trigger is not None:
        texts.add(f"{enable_name}:{link.trigger}")
    return texts


def comment_with_link(comment: str, link: BenchLink, enable_name: str) -> str:
    """Return *comment* with its link and response replaced by *link*.

    The block tag, other metadata and free text stay. The ``physical=`` key is dropped, so
    the response belongs to this tag alone. It cannot clash with a shared definition of
    that name.
    """
    if link.cut:
        raise ValueError("a cut link has nothing to write to the project")
    block_tag, meta, free_text = AnnotationService.decompose_comment(comment)
    meta = replace(
        meta or TagMeta(),
        link=link_text(enable_name, link),
        physical=None,
        **meta_fields(link.response),
    )
    return AnnotationService.recompose_comment(block_tag, meta, free_text)


def comment_has_link(comment: str, link: BenchLink, enable_names: tuple[str, ...]) -> bool:
    """Return True if *comment* already declares *link*, with any of *enable_names* as enable."""
    if link.cut:
        return False
    try:
        _block_tag, meta, _free_text = AnnotationService.decompose_comment(comment)
    except ValueError:
        return False
    if meta is None or meta.link is None:
        return False
    names_enable = any(meta.link in _link_texts(name, link) for name in enable_names if name)
    return names_enable and same_response(meta_response(meta), link.response)


def declares_link(comment: str) -> bool:
    """Return True if *comment* declares a link that pyrung runs.

    Such a comment has ``link=`` together with a response or a ``physical=`` key.
    """
    try:
        _block_tag, meta, _free_text = AnnotationService.decompose_comment(comment)
    except ValueError:
        return False
    if meta is None or meta.link is None:
        return False
    return meta.physical is not None or bool(meta_response(meta))


def linked_feedbacks(csv_dir: Path) -> frozenset[str]:
    """Return the tags that a workspace's program declares links on, from its ``nicknames.csv``.

    Each tag is named as pyrung reads the file (``tag_names``). Return an empty set if the
    file is missing or cannot be read.
    """
    path = csv_dir / "nicknames.csv"
    try:
        rows = CsvDataSource(str(path)).load_all_addresses()
        linked = [key for key, row in rows.items() if declares_link(row.comment)]
        return frozenset(tag_names(path, rows, linked).values()) if linked else frozenset()
    except (OSError, ValueError):
        return frozenset()
