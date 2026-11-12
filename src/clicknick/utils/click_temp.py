"""Where CLICK keeps an open project: the ``CLICK (hwnd)`` folder in the Windows temp folder.

CLICK makes one folder per window, ``CLICK ({hwnd:08X})``, holding SC_.mdb, Address.csv,
Project.ini, the Scr*.tmp saves and the DataView folder. Everything that looks for it
goes through ``click_temp_dir``. Pure ``os``/``pathlib``/``ctypes``, so the lightweight
CLI can use it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def _windows_temp_path() -> str | None:
    """The Windows temp path (GetTempPathW: TMP, then TEMP, then the user profile)."""
    try:
        import ctypes

        get_temp_path = ctypes.windll.kernel32.GetTempPathW  # pyright: ignore[reportAttributeAccessIssue]
    except (ImportError, AttributeError, OSError):
        return None
    size = 261
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = get_temp_path(size, buffer)
        if length == 0:
            return None
        if length < size:
            return buffer.value
        size = length + 1


def temp_root() -> Path:
    """The folder CLICK makes its ``CLICK (hwnd)`` folders in.

    CLICK is a Win32 app and gets the temp folder from Windows, so this is the
    Windows temp path, or Python's temp folder where Windows gives none.
    """
    return Path(_windows_temp_path() or tempfile.gettempdir())


def click_temp_dir(hwnd: int) -> Path:
    """The temp folder of the CLICK window *hwnd* (it may not exist)."""
    return temp_root() / f"CLICK ({hwnd:08X})"
