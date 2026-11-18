"""Read and write ClickNick's saved settings in ``%LOCALAPPDATA%\\ClickNick\\settings.json``.

The file holds two values:

- ``redraw_on_sync``: Tools > Redraw Ladder on Sync. ClickNick writes it only once the user
  sets it in the Tools menu.
- ``redraw_notice_shown``: whether ClickNick has shown the notice that explains the redraw
  after a Sync.

A value that is missing, or that is not a boolean, counts as never set. So does every value
in a file that is missing or unreadable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REDRAW_ON_SYNC = "redraw_on_sync"
REDRAW_NOTICE_SHOWN = "redraw_notice_shown"


@dataclass(frozen=True)
class SavedSettings:
    """The values in the settings file."""

    # None until the user sets Tools > Redraw Ladder on Sync
    redraw_on_sync: bool | None = None
    redraw_notice_shown: bool = False


def default_settings_path() -> Path:
    """Return ``%LOCALAPPDATA%\\ClickNick\\settings.json``."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "ClickNick" / "settings.json"


def read_settings(path: Path | None = None) -> SavedSettings:
    """Return the settings saved in *path*, or in ``default_settings_path()`` if it is None."""
    try:
        payload = json.loads((path or default_settings_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):  # A deeply nested file raises RecursionError
        return SavedSettings()
    if not isinstance(payload, dict):
        return SavedSettings()
    redraw = payload.get(REDRAW_ON_SYNC)
    shown = payload.get(REDRAW_NOTICE_SHOWN)
    return SavedSettings(
        redraw_on_sync=redraw if isinstance(redraw, bool) else None,
        redraw_notice_shown=shown is True,
    )


def write_settings(settings: SavedSettings, path: Path | None = None) -> bool:
    """Save *settings*. Return False if the file could not be written.

    Write *path*, or ``default_settings_path()`` if *path* is None. Leave out
    ``redraw_on_sync`` while the user has not set it. Write a staging file first and then
    replace the settings file with it. A failed write leaves the old file as it was and
    removes the staging file.
    """
    payload: dict[str, bool] = {REDRAW_NOTICE_SHOWN: settings.redraw_notice_shown}
    if settings.redraw_on_sync is not None:
        payload[REDRAW_ON_SYNC] = settings.redraw_on_sync
    target = path or default_settings_path()
    staging = target.with_suffix(".json.staging")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.replace(target)
    except OSError:
        staging.unlink(missing_ok=True)
        return False
    return True
