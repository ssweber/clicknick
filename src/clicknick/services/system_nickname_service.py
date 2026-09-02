"""Reviewed repair flow for vendor-owned CLICK system nicknames."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyclickplc import AUTOMATIONDIRECT_SYSTEM_NICKNAMES, canonicalize_system_nickname
from pyclickplc.addresses import get_addr_key

if TYPE_CHECKING:
    from ..data.address_store import AddressStore


@dataclass(frozen=True)
class SystemNicknameChange:
    """One AddressStore nickname change suggested by vendor guidance."""

    addr_key: int
    display_address: str
    current: str
    replacement: str


def find_system_nickname_repairs(store: AddressStore) -> tuple[SystemNicknameChange, ...]:
    """Return known repairs without mutating the store."""

    repairs: list[SystemNicknameChange] = []
    for memory_type, address in sorted(AUTOMATIONDIRECT_SYSTEM_NICKNAMES):
        addr_key = get_addr_key(memory_type, address)
        row = store.get_visible_row(addr_key)
        if row is None:
            continue
        replacement = canonicalize_system_nickname(memory_type, address, row.nickname)
        if replacement != row.nickname:
            repairs.append(
                SystemNicknameChange(
                    addr_key=addr_key,
                    display_address=row.display_address,
                    current=row.nickname,
                    replacement=replacement,
                )
            )
    return tuple(repairs)


def stage_system_nickname_repairs(
    store: AddressStore,
) -> tuple[SystemNicknameChange, ...]:
    """Stage all known repairs through one AddressStore edit session."""

    repairs = find_system_nickname_repairs(store)
    if not repairs:
        return ()
    with store.edit_session("Repair vendor system nicknames") as session:
        for repair in repairs:
            session.set_field(repair.addr_key, "nickname", repair.replacement)
    return repairs
