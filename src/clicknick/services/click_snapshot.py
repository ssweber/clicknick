"""A copy of what another CLICK window last saved, as a folder Preview Changes compares.

Comparing with another CLICK window (a sister PLC's project, say) reads its
last save the way a folder of ladder CSVs is read: its Scr*.tmp files become
main.csv and subroutines/, and its database's nicknames become nicknames.csv.
The copy lives in a ClickNick folder, one per CLICK window, and is replaced
whole each time it is taken, so it never mixes two saves.
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
    """Where the copy of the CLICK window *hwnd*'s last save is kept."""
    return _snapshots_root() / f"CLICK ({hwnd:08X})"


def remove_stale_snapshots(keep_hwnds: Iterable[int], keep_dirs: Iterable[Path]) -> list[Path]:
    """Delete the copies of CLICK windows other than *keep_hwnds*; return what was deleted.

    A copy that is or holds one of *keep_dirs* (folders a window shows) stays, and
    so does anything in the folder that is not a copy. A copy cut short leaves a
    ``.CLICK (hwnd)-*`` folder behind; those go too.
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
    """Write the window's nicknames beside its program; say why not, or return ""."""
    from ..utils.mdb_operations import MdbConnection, load_all_addresses

    database = click_dir / _DATABASE
    if not database.is_file():
        return "its nicknames were left out: it has no database"
    try:
        with MdbConnection(str(database)) as conn:
            rows = load_all_addresses(conn)
    except Exception as exc:  # The driver's own errors, a locked file
        return f"its nicknames were left out: {exc}"
    CsvDataSource(str(staged / _NICKNAMES)).save_changes(list(rows.values()))
    return ""


def snapshot_click_program(click_dir: Path, dest: Path) -> str:
    """Copy the program CLICK last saved in *click_dir*, and its nicknames, into *dest*.

    *click_dir* is the CLICK window's ``CLICK (hwnd)`` temp folder. *dest* is
    swapped for the copy only once all of it is written: the last copy is
    renamed aside first, so a file held open in it leaves it whole. Returns
    why the nicknames were left out ("" when they were copied); its database is
    only needed for them. Raises FileNotFoundError when the window has nothing
    saved, as ``program_save`` does, ValueError when the save has no main
    program, and OSError when the last copy cannot be moved aside.
    """
    from ..ladder.program import program_save

    dest.parent.mkdir(parents=True, exist_ok=True)
    # A copy left behind, or one a file is held open in, must not fail a good copy
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
