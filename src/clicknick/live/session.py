"""Session discovery for live editing.

A running ClickNick advertises its live TCP port by writing
``clicknick-live.port`` into its *current* session directory:

- the connected CLICK instance's temp folder (next to ``SC_.mdb``), so the
  port file sits with the project it edits and is keyed per instance; or
- a ClickNick-owned fallback (``%LOCALAPPDATA%\\ClickNick\\live``) when no
  CLICK window is connected (e.g. a standalone CSV loaded from disk).

Clients scan these locations for live port files; stale ones are pruned.
Pure ``os``/``pathlib`` only, so the lightweight CLI need not import pyodbc.
The ``CLICK (hwnd)`` convention mirrors ``utils.mdb_shared``.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

PORT_FILENAME = "clicknick-live.port"
LABEL_FILENAME = "clicknick-live.label"
WORKSPACE_FILENAME = "clicknick-live.workspace"

_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or Path.home())


def _temp_root() -> Path:
    """Directory CLICK creates its per-instance ``CLICK (hwnd)`` folders in."""
    return _LOCALAPPDATA / "Temp"


def click_temp_dir(hwnd: int) -> Path:
    """The CLICK instance temp folder for *hwnd* (may not exist)."""
    return _temp_root() / f"CLICK ({hwnd:08X})"


def fallback_dir() -> Path:
    """ClickNick-owned dir for sessions with no connected CLICK window."""
    return _LOCALAPPDATA / "ClickNick" / "live"


def label_for_dir(directory: Path) -> str:
    """Human/CLI label for a session directory.

    Reads ``clicknick-live.label`` if present (contains .ckp stem), otherwise
    falls back to ``CLICK (000A1B2C)`` -> ``000A1B2C``; fallback -> ``standalone``.
    """
    label_file = directory / LABEL_FILENAME
    if label_file.is_file():
        try:
            label = label_file.read_text(encoding="utf-8").strip()
            if label:
                return label
        except OSError:
            pass
    name = directory.name
    if name.startswith("CLICK (") and name.endswith(")"):
        return name[len("CLICK (") : -1]
    return "standalone"


def workspace_for_port_file(port_file: Path) -> Path | None:
    """Read the active workspace advertised beside one live port file."""
    workspace_file = port_file.parent / WORKSPACE_FILENAME
    try:
        value = workspace_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(value) if value else None


def iter_session_dirs() -> list[Path]:
    """All directories that may contain a live port file."""
    dirs: list[Path] = []
    temp = _temp_root()
    if temp.is_dir():
        dirs.extend(p for p in temp.glob("CLICK (*)") if p.is_dir())
    fb = fallback_dir()
    if fb.is_dir():
        dirs.append(fb)
    return dirs


def _is_port_alive(port: int) -> bool:
    """Return True if something is listening on localhost:*port*."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.1)
    try:
        sock.connect(("localhost", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def find_sessions() -> list[tuple[str, int, Path]]:
    """Return ``(label, port, port_file)`` for each reachable live session.

    Stale port files (unparseable, or whose port no longer answers) are removed.
    """
    found: list[tuple[str, int, Path]] = []
    for directory in iter_session_dirs():
        pf = directory / PORT_FILENAME
        if not pf.is_file():
            continue
        try:
            port = int(pf.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pf.unlink(missing_ok=True)
            continue
        if _is_port_alive(port):
            found.append((label_for_dir(directory), port, pf))
        else:
            pf.unlink(missing_ok=True)
    return found


def list_sessions() -> list[str]:
    """Labels of all reachable live sessions (stale files pruned)."""
    return sorted(label for label, _, _ in find_sessions())


def resolve_address(label: str | None = None) -> tuple[str, int]:
    """Resolve a session *label* (or the sole active one) to ``('localhost', port)``.

    Raises ``FileNotFoundError`` when nothing matches and ``LookupError`` when
    *label* is omitted but several sessions are active.
    """
    sessions = find_sessions()
    if label is not None:
        for lbl, port, _ in sessions:
            if lbl == label:
                return ("localhost", port)
        raise FileNotFoundError(f"Session '{label}' not found")
    if not sessions:
        raise FileNotFoundError("No active ClickNick session found")
    if len(sessions) > 1:
        labels = ", ".join(lbl for lbl, _, _ in sessions)
        raise LookupError(f"Multiple sessions active ({labels}); pick one with --session")
    return ("localhost", sessions[0][1])
