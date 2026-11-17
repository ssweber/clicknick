"""Locate the ``CLICK (hwnd)`` folder in the temp folder, where CLICK keeps an open project.

CLICK makes one folder per window, ``CLICK ({hwnd:08X})``. It holds SC_.mdb, Address.csv,
Project.ini, the Scr*.tmp saves and the DataView folder. ClickNick looks for the folder
under the Windows temp folder (GetTempPathW), and everything that looks for it goes
through ``click_temp_dir``. The module uses only ``os``, ``pathlib`` and ``ctypes``, so
the lightweight CLI can use it.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from pathlib import Path


def _call_with_buffer(call: Callable[[int, object], int]) -> str | None:
    """Run a Win32 call that fills a string buffer, growing it until the text fits."""
    import ctypes

    size = 261
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = call(size, buffer)
        if length == 0:
            return None
        if length < size:
            return buffer.value
        size = length + 1


def _windows_temp_path() -> str | None:
    """Return the Windows temp path (GetTempPathW: TMP, then TEMP, then the user profile)."""
    try:
        import ctypes

        get_temp_path = ctypes.windll.kernel32.GetTempPathW  # pyright: ignore[reportAttributeAccessIssue]
    except (ImportError, AttributeError, OSError):
        return None
    return _call_with_buffer(get_temp_path)


def _long_path(path: str) -> str:
    """Return *path* with 8.3 short names spelled out (GetLongPathNameW), or as given on failure.

    TMP can hold a short name (``C:\\PROGRA~1``) while a file dialog returns the long
    one, so two paths to the same file must compare equal.
    """
    try:
        import ctypes

        get_long_path = ctypes.windll.kernel32.GetLongPathNameW  # pyright: ignore[reportAttributeAccessIssue]
    except (ImportError, AttributeError, OSError):
        return path
    return _call_with_buffer(lambda size, buffer: get_long_path(path, buffer, size)) or path


def temp_root() -> Path:
    """Return the folder in which CLICK makes its ``CLICK (hwnd)`` folders, in its long form.

    ClickNick takes CLICK's temp folder to be the Windows temp path, or Python's temp folder
    if Windows gives none.
    """
    return Path(_long_path(_windows_temp_path() or tempfile.gettempdir()))


def click_temp_dir(hwnd: int) -> Path:
    """Return the temp folder of the CLICK window *hwnd*. The folder may not exist."""
    return temp_root() / f"CLICK ({hwnd:08X})"


_SCR_NAME = re.compile(r"Scr\d+\.tmp", re.IGNORECASE)


def scr_files(folder: Path) -> list[Path]:
    """Return the program files that CLICK saved in *folder*: ``Scr<N>.tmp``, sorted by name.

    A save also makes short-lived copies such as ``Scr23.tmp~RFcf1eba5.TMP``. If CLICK is
    killed mid-save, one can be left behind. Those copies are not programs.
    """
    return sorted(
        (p for p in folder.glob("Scr*") if _SCR_NAME.fullmatch(p.name)),
        key=lambda p: p.name.casefold(),
    )
