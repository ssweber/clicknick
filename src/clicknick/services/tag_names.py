"""Name each address the way pyrung does, by asking pyrung's own reader.

A workspace's program and its simulation name each address by the tag that pyrung reads
from the workspace's ``nicknames.csv``. pyrung decides how it reads a nickname, such as
whether it strips spaces and which rows it refuses. ClickNick does not copy those rules.
It calls pyrung's own reader (``TagMap.from_nickname_file``) and maps addresses by the
result. This module uses no tkinter and no store.
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
    """Return the tag name of each address in *keys*, as the program read from *nickname_csv*.

    *rows* are the rows that the file holds. An address that pyrung reads a nickname for
    gets that nickname as its tag name. A CLICK system point (SC, SD) keeps its nickname.
    pyrung names those points with names of its own (``sys.*``), and ClickNick does not use
    them. Any other address gets its display address (``"X001"``) as its name. So does
    every address when there is no file.

    Raise OSError when the file cannot be read. Raise ValueError when pyrung refuses the
    file, as building the program from it would.
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
