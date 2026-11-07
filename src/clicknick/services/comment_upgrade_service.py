"""Upgrade Project rewrites old annotation forms in nickname comments and stages them.

pyrung reads only the current annotation form and refuses an old one, such as
``profile=pulse:on_dwell=8ms|off_dwell=8ms``. pyrung's numbered migrations rewrite it
(``flasher_on=8ms, flasher_off=8ms``). This stages every rewrite in one edit session, so
the user reviews them on the Changed tab and Syncs. ClickNick keeps no knowledge of the
old forms itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyrung.click.tag_map import comment_needs_upgrade, old_form_tokens, upgrade_comment

from .annotation_service import AnnotationService

if TYPE_CHECKING:
    from ..data.address_store import AddressStore


@dataclass(frozen=True)
class CommentUpgrade:
    """One comment with an old annotation form.

    ``replacement`` is the upgraded comment. ``problem`` says why pyrung still refuses it,
    such as an old token no migration reads. Such a comment is left for the user to fix.
    """

    addr_key: int
    display_address: str
    current: str
    replacement: str
    problem: str = ""

    @property
    def staged(self) -> bool:
        """True when Upgrade Project writes the replacement into the store."""
        return not self.problem and self.replacement != self.current


def _problem(replacement: str) -> str:
    """Why pyrung refuses *replacement*, or ``""`` when it reads it."""
    tokens = old_form_tokens(replacement)
    if tokens:
        return f"no upgrade reads {', '.join(tokens)}"
    try:
        AnnotationService.decompose_comment(replacement)
    except ValueError as exc:
        return str(exc)
    return ""


def find_comment_upgrades(store: AddressStore) -> tuple[CommentUpgrade, ...]:
    """Every comment that holds an old annotation form, without changing the store."""
    found: list[CommentUpgrade] = []
    for addr_key, row in store.visible_state.items():
        comment = row.comment
        # Most comments carry no metadata group, and pyrung's check needs one.
        if "[" not in comment or not comment_needs_upgrade(comment):
            continue
        replacement = upgrade_comment(comment)
        found.append(
            CommentUpgrade(
                addr_key=addr_key,
                display_address=row.display_address,
                current=comment,
                replacement=replacement,
                problem=_problem(replacement),
            )
        )
    return tuple(found)


def stage_comment_upgrades(store: AddressStore) -> tuple[CommentUpgrade, ...]:
    """Stage every rewrite through one edit session, and return every comment found.

    A comment pyrung would still refuse is returned with its problem but not staged.
    """
    upgrades = find_comment_upgrades(store)
    changed = [upgrade for upgrade in upgrades if upgrade.staged]
    if changed:
        with store.edit_session("Upgrade project annotations") as session:
            for upgrade in changed:
                session.set_field(upgrade.addr_key, "comment", upgrade.replacement)
    return upgrades
