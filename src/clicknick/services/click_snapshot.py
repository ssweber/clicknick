"""A copy of what another CLICK window last saved, as a folder that Review Changes compares.

When you compare with another CLICK window, such as a sister PLC's project, ClickNick
reads that window's last save the way it reads a folder of ladder CSVs. The Scr*.tmp
files become main.csv and subroutines/, and the database's nicknames become nicknames.csv.
The copy lives in a ClickNick folder, one per CLICK window. Each new copy replaces the
old one whole, so a copy never mixes two saves.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

from ..data.data_source import CsvDataSource

# Inside a CLICK window's own temp folder
_DATABASE = "SC_.mdb"
_NICKNAMES = "nicknames.csv"


def _snapshots_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return root / "ClickNick" / "compare"


def snapshot_dir(hwnd: int) -> Path:
    """Return the folder that holds the copy of the CLICK window *hwnd*'s last save."""
    return _snapshots_root() / f"CLICK ({hwnd:08X})"


def remove_stale_snapshots(keep_hwnds: Iterable[int], keep_dirs: Iterable[Path]) -> list[Path]:
    """Delete the copies of CLICK windows other than *keep_hwnds*; return what was deleted.

    A copy that is one of *keep_dirs*, or holds one, stays. Those are the folders that a
    window shows. Anything in the folder that is not a copy stays too. A copy that was cut
    short leaves a ``.CLICK (hwnd)-*`` folder behind. Those are deleted as well.
    """
    root = _snapshots_root()
    if not root.is_dir():
        return []
    keep = {snapshot_dir(hwnd).resolve() for hwnd in keep_hwnds}
    shown = [Path(folder).resolve() for folder in keep_dirs]
    removed = []
    for path in root.iterdir():
        if not path.name.startswith(("CLICK (", ".CLICK (")) or not path.is_dir():
            continue
        copy = path.resolve()
        if copy in keep or any(folder.is_relative_to(copy) for folder in shown):
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path)
    return removed


def _copy_nicknames(click_dir: Path, staged: Path) -> str:
    """Write the window's nicknames beside its program. Return why not, or "" on success."""
    from ..utils.mdb_operations import MdbConnection, load_all_addresses

    database = click_dir / _DATABASE
    if not database.is_file():
        return "its nicknames were left out: it has no database"
    try:
        with MdbConnection(str(database)) as conn:
            rows = load_all_addresses(conn)
    except Exception as exc:  # The driver's own errors, or a locked file
        return f"its nicknames were left out: {exc}"
    CsvDataSource(str(staged / _NICKNAMES)).save_changes(list(rows.values()))
    return ""


def snapshot_click_program(click_dir: Path, dest: Path) -> str:
    """Copy the program CLICK last saved in *click_dir*, and its nicknames, into *dest*.

    *click_dir* is the CLICK window's ``CLICK (hwnd)`` temp folder. This function replaces
    *dest* with the new copy only after it has written all of it. It first renames the last
    copy aside. A file that is held open in the last copy then leaves that copy whole.

    It returns the reason the nicknames were left out, or "" when it copied them. Only the
    nicknames need the database. It raises FileNotFoundError when the window has nothing
    saved, as ``program_save`` does. It raises ValueError when the save has no main program,
    and OSError when it cannot move the last copy aside.
    """
    from ..ladder.program import program_save

    dest.parent.mkdir(parents=True, exist_ok=True)
    # A copy that is left behind, or that has a file held open in it, must not fail a good copy
    with TemporaryDirectory(
        prefix=f".{dest.name}-", dir=dest.parent, ignore_cleanup_errors=True
    ) as stage_root:
        staged = Path(stage_root) / "copy"
        program_save(click_dir, staged)
        note = _copy_nicknames(click_dir, staged)
        old = Path(stage_root) / "old"
        if dest.exists():
            dest.replace(old)
        try:
            staged.replace(dest)
        except OSError:
            if old.exists():
                old.replace(dest)
            raise
    return note
