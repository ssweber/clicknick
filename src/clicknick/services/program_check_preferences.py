"""Per-user expansion preferences for Check Program, independent of validation."""

from __future__ import annotations

import json
import os
from pathlib import Path


def default_preferences_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / "ClickNick" / "check-program.json"


class ProgramCheckPreferences:
    def _read(self) -> dict[str, bool]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            states = payload.get("expanded", {}) if isinstance(payload, dict) else {}
            if isinstance(states, dict):
                return {key: value for key, value in states.items() if isinstance(value, bool)}
        except (OSError, ValueError):
            pass
        return {}

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_preferences_path()
        self.expanded = self._read()

    def is_expanded(self, code: str, *, default: bool = True) -> bool:
        return self.expanded.get(code, default)

    def set_expanded(self, code: str, expanded: bool) -> bool:
        """Save one choice; return False if it could only be kept for this window."""
        # Merge other windows' choices instead of overwriting a stale snapshot.
        states = self._read()
        states[code] = expanded
        self.expanded[code] = expanded
        staging = self.path.with_suffix(".json.staging")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            staging.write_text(
                json.dumps({"expanded": states}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            staging.replace(self.path)
        except OSError:
            return False
        return True
