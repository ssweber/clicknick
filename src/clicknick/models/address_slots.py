"""Every address slot ClickNick shows, in display order."""

from __future__ import annotations

from collections.abc import Iterator

from pyclickplc.addresses import is_xd_yd_hidden_slot
from pyclickplc.banks import BANKS


def iter_address_slots() -> Iterator[tuple[str, int]]:
    """Yield (memory_type, address) for every editable slot, bank by bank.

    Sparse banks (X/Y) use their valid ranges; hidden XD/YD slots are skipped.
    """
    for memory_type, bank in BANKS.items():
        if bank.valid_ranges is not None:
            ranges = bank.valid_ranges
        else:
            ranges = ((bank.min_addr, bank.max_addr),)
        for lo, hi in ranges:
            for address in range(lo, hi + 1):
                if not is_xd_yd_hidden_slot(memory_type, address):
                    yield memory_type, address
