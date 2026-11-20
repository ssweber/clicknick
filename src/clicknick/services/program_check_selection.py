"""Persist rule selection separately from report folding preferences."""

from __future__ import annotations

import threading
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from pyrung.validation import CheckConfig, load_check_config, save_check_config

from .program_check_preferences import default_preferences_path


@dataclass(frozen=True)
class DroppedChecks:
    """Rule names that pyrung does not know, which ClickNick removed from a saved selection."""

    path: Path
    names: tuple[str, ...]
    # True if the selection that is left turns no check on
    none_left: bool = False

    def describe(self) -> str:
        """Return the message that tells the user which names were removed, and from where."""
        *rest, last = self.names
        listed = f"{', '.join(rest)} or {last}" if rest else last
        them = "it" if len(self.names) == 1 else "them"
        what = "check" if len(self.names) == 1 else "checks"
        head = (
            f"pyrung has no {what} named {listed}, so ClickNick removed {them} from the "
            f"check selection in {self.path}."
        )
        if self.none_left:
            return (
                f"{head} No checks are left in the selection, so Check Program runs none. "
                "Open Choose Checks to choose the checks to run."
            )
        return (
            f"{head} The other checks in the selection stay. Open Choose Checks to see "
            "which checks run."
        )


def update_selection(config: CheckConfig, enabled: set[str]) -> CheckConfig:
    """Save exact overrides while retaining selectors that can match future rules."""
    selected = config.resolve()
    removed, added = selected - enabled, enabled - selected
    return replace(
        config,
        select=tuple(code for code in config.select if code not in removed)
        if config.select is not None
        else None,
        extend_select=tuple(sorted((set(config.extend_select) - removed) | added)),
        ignore=tuple(sorted((set(config.ignore) - added) | removed)),
    )


def _is_known(selector: str) -> bool:
    """Return True if pyrung knows *selector* as a rule code, a category or ``ALL``."""
    try:
        CheckConfig(select=(selector,)).resolve()
    except ValueError:
        return False
    return True


def _without_unknown(path: Path) -> tuple[CheckConfig, tuple[str, ...]] | None:
    """Return the selection saved in *path* without the names that pyrung does not know.

    Also return those names. Return None if the selection has no such name, or if the file
    cannot be read as a selection for another reason.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        config = CheckConfig.from_mapping(data["tool"]["pyrung"]["check"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    lists = (config.select or (), config.extend_select, config.ignore)
    unknown = tuple(dict.fromkeys(name for names in lists for name in names if not _is_known(name)))
    if not unknown:
        return None

    def keep(names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in names if name not in unknown)

    kept = CheckConfig(
        select=None if config.select is None else keep(config.select),
        extend_select=keep(config.extend_select),
        ignore=keep(config.ignore),
    )
    return kept, unknown


class ProgramCheckSelection:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        appdata: Path | None = None,
    ) -> None:
        root = appdata if appdata is not None else default_preferences_path().parent
        self.app_defaults_path = root / "check-defaults.toml"
        self.workspace = workspace
        self._dropped: list[DroppedChecks] = []
        # A build thread and the Tk thread can both use one selection
        self._dropped_lock = threading.Lock()

    @property
    def path(self) -> Path:
        return (
            self.workspace / "pyproject.toml"
            if self.workspace is not None
            else self.app_defaults_path
        )

    def _read(self, path: Path) -> CheckConfig | None:
        """Read the selection saved in *path*, or return None if it holds none.

        If the selection names a rule that pyrung does not know, such as a rule that pyrung
        has renamed, remove that name, write the file again, and keep the rest. ``take_dropped``
        returns the names removed. Raise ``ValueError`` for any other selection that pyrung
        refuses.
        """
        try:
            return load_check_config(path)
        except ValueError:
            repaired = _without_unknown(path)
            if repaired is None:
                raise
        config, names = repaired
        save_check_config(path, config)
        with self._dropped_lock:
            self._dropped.append(DroppedChecks(path, names, none_left=not config.resolve()))
        return config

    def load(self) -> CheckConfig:
        if self.workspace is not None:
            config = self._read(self.path)
            if config is not None:
                return config
        return self._read(self.app_defaults_path) or CheckConfig()

    def save(self, config: CheckConfig) -> None:
        config.resolve()
        save_check_config(self.path, config)

    def sync(self, project_dir: Path) -> None:
        """Refresh temporary worker settings; seed workspace settings only when absent."""
        config = self.load()
        path = project_dir / "pyproject.toml"
        if self.workspace is None or self._read(path) is None:
            save_check_config(path, config)

    def take_dropped(self) -> tuple[DroppedChecks, ...]:
        """Return the names removed from saved selections since the last call, and forget them."""
        with self._dropped_lock:
            dropped, self._dropped = tuple(self._dropped), []
        return dropped
