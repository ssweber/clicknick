"""Where CLICK keeps an open project: the ``CLICK (hwnd)`` folder in the temp folder.

CLICK makes one folder per window, ``CLICK ({hwnd:08X})``, holding SC_.mdb, Address.csv,
Project.ini, the Scr*.tmp saves and the DataView folder. ClickNick looks for it under
the Windows temp folder (GetTempPathW; USER-CHECKS Q8), and everything that looks for
it goes through ``click_temp_dir``. Pure ``os``/``pathlib``/``ctypes``, so the
lightweight CLI can use it.
"""

from __future__ import annotations

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
    """The Windows temp path (GetTempPathW: TMP, then TEMP, then the user profile)."""
    try:
        import ctypes

        get_temp_path = ctypes.windll.kernel32.GetTempPathW  # pyright: ignore[reportAttributeAccessIssue]
    except (ImportError, AttributeError, OSError):
        return None
    return _call_with_buffer(get_temp_path)


def _long_path(path: str) -> str:
    """*path* with 8.3 short names spelled out (GetLongPathNameW); as given if that fails.

    TMP can hold a short name (``C:\\PROGRA~1``) while a file dialog returns the long
    one, and paths of one file must compare equal.
    """
    try:
        import ctypes

        get_long_path = ctypes.windll.kernel32.GetLongPathNameW  # pyright: ignore[reportAttributeAccessIssue]
    except (ImportError, AttributeError, OSError):
        return path
    return _call_with_buffer(lambda size, buffer: get_long_path(path, buffer, size)) or path


def temp_root() -> Path:
    """The folder CLICK makes its ``CLICK (hwnd)`` folders in, in its long form.

    CLICK is a Win32 app and gets the temp folder from Windows, so this is the
    Windows temp path, or Python's temp folder where Windows gives none.
    """
    return Path(_long_path(_windows_temp_path() or tempfile.gettempdir()))


def click_temp_dir(hwnd: int) -> Path:
    """The temp folder of the CLICK window *hwnd* (it may not exist)."""
    return temp_root() / f"CLICK ({hwnd:08X})"
