"""Upgrade Project: rewrite old annotation forms in nickname comments, staged for review.

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

if TYPE_CHECKING:
    from ..data.address_store import AddressStore


@dataclass(frozen=True)
class CommentUpgrade:
    """One comment with an old annotation form.

    ``replacement`` is the upgraded comment. ``unresolved`` lists the old tokens no
    migration can rewrite, which the user fixes by hand.
    """

    addr_key: int
    display_address: str
    current: str
    replacement: str
    unresolved: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.replacement != self.current


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
                unresolved=old_form_tokens(replacement),
            )
        )
    return tuple(found)


def stage_comment_upgrades(store: AddressStore) -> tuple[CommentUpgrade, ...]:
    """Stage every rewrite through one edit session, and return every comment found.

    A comment no migration can change is returned but not staged.
    """
    upgrades = find_comment_upgrades(store)
    changed = [upgrade for upgrade in upgrades if upgrade.changed]
    if changed:
        with store.edit_session("Upgrade project annotations") as session:
            for upgrade in changed:
                session.set_field(upgrade.addr_key, "comment", upgrade.replacement)
    return upgrades
