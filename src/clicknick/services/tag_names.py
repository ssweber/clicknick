"""The name pyrung gives each address, read by pyrung itself.

A workspace's program and its simulation name each address by the tag pyrung
reads from the workspace's ``nicknames.csv``. pyrung decides how it reads a
nickname (whether it strips spaces, which rows it refuses), so ClickNick does
not copy that rule: it asks pyrung's own reader (``TagMap.from_nickname_file``)
and maps by what that gives. No tkinter, no store.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from pyclickplc.addresses import format_address_display, get_addr_key, parse_addr_key
from pyrung.click.tag_map import TagMap

from ..models.address_row import AddressRow


def tag_names(
    nickname_csv: Path | None,
    rows: Mapping[int, AddressRow],
    keys: Iterable[int],
) -> dict[int, str]:
    """The tag name of each address in *keys*, as the program read from *nickname_csv* has it.

    *rows* are the rows that file holds. An address pyrung reads a nickname
    for has that tag name. A CLICK system point (SC, SD) keeps its nickname:
    pyrung names those by names of its own (``sys.*``), which ClickNick does
    not use. Any other address, and every address when there is no file, is
    named by its display address (``"X001"``).

    Raises OSError when the file cannot be read and ValueError when pyrung
    refuses it, as building the program from it would.
    """
    user: dict[int, str] = {}
    system: set[int] = set()
    if nickname_csv is not None:
        for slot in TagMap.from_nickname_file(nickname_csv).mapped_slots():
            key = get_addr_key(slot.memory_type, slot.address)
            if slot.source == "user":
                user[key] = slot.logical_name
            else:
                system.add(key)
    names: dict[int, str] = {}
    for key in keys:
        name = user.get(key)
        if name is None and key in system and key in rows:
            name = rows[key].nickname
        names[key] = name or format_address_display(*parse_addr_key(key))
    return names
