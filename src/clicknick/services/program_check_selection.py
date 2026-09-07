"""Persist rule selection separately from report folding preferences."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pyrung.core.validation.config import CheckConfig, load_check_config, save_check_config

from .program_check_preferences import default_preferences_path


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

    @property
    def path(self) -> Path:
        return (
            self.workspace / "pyproject.toml"
            if self.workspace is not None
            else self.app_defaults_path
        )

    def load(self) -> CheckConfig:
        if self.workspace is not None:
            config = load_check_config(self.path)
            if config is not None:
                return config
        return load_check_config(self.app_defaults_path) or CheckConfig()

    def save(self, config: CheckConfig) -> None:
        config.resolve()
        save_check_config(self.path, config)

    def sync(self, project_dir: Path) -> None:
        """Refresh temporary worker settings; seed workspace settings only when absent."""
        config = self.load()
        path = project_dir / "pyproject.toml"
        if self.workspace is None or load_check_config(path) is None:
            save_check_config(path, config)
