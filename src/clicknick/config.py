import logging
import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path

from .services import settings_file

logger = logging.getLogger(__name__)


@dataclass
class AppSettings:
    """Application settings and configuration."""

    EXCLUDE_PLACEHOLDER_TEXT = "txt1, txt2, txt3"

    def __init__(self, settings_path: Path | None = None):
        """Create the settings, with the values saved in *settings_path*.

        *settings_path* defaults to ``settings_file.default_settings_path()``.
        """
        self.search_var = tk.StringVar(value="contains")
        self.sort_by_nickname_var = tk.BooleanVar(value=False)
        self.exclude_sc_sd_var = tk.BooleanVar(value=False)
        self.exclude_nicknames_var = tk.StringVar(value="")
        self.show_info_tooltip_var = tk.BooleanVar(value=True)
        # Tools > Redraw Ladder on Sync. It is on until the user turns it off.
        self._settings_path = settings_path
        self._saved = settings_file.read_settings(settings_path)
        saved_redraw = self._saved.redraw_on_sync
        self.redraw_on_sync_var = tk.BooleanVar(value=True if saved_redraw is None else saved_redraw)
        self.redraw_on_sync_var.trace_add("write", self._on_redraw_on_sync_set)

    @property
    def exclude_sc_sd(self) -> bool:
        """Get SC/SD exclusion setting."""
        return self.exclude_sc_sd_var.get() if self.exclude_sc_sd_var else False

    @property
    def exclude_terms(self) -> str:
        """Get exclude terms setting."""
        return self.exclude_nicknames_var.get() if self.exclude_nicknames_var else ""

    def get_exclude_terms_list(self) -> list[str]:
        """Parse exclude terms, handling placeholder text."""
        exclude_terms = self.exclude_terms
        if exclude_terms == AppSettings.EXCLUDE_PLACEHOLDER_TEXT:
            return []
        return [term.strip().lower() for term in exclude_terms.split(",") if term.strip()]

    @property
    def search_mode(self) -> str:
        """Get current search mode."""
        return self.search_var.get() if self.search_var else "contains"

    @property
    def sort_by_nickname(self) -> bool:
        """Get nickname sorting setting."""
        return self.sort_by_nickname_var.get() if self.sort_by_nickname_var else False

    @property
    def redraw_on_sync(self) -> bool:
        """Return True if CLICK should redraw its nicknames after each Sync."""
        return self.redraw_on_sync_var.get()

    @property
    def redraw_notice_due(self) -> bool:
        """Return True if the next redraw after a Sync should show the notice about it.

        The notice shows once per machine. It never shows once the user has set Redraw
        Ladder on Sync in the Tools menu.
        """
        return not self._saved.redraw_notice_shown and self._saved.redraw_on_sync is None

    def mark_redraw_notice_shown(self) -> None:
        """Save that the notice about the redraw after a Sync has shown."""
        self._save(replace(self._saved, redraw_notice_shown=True))

    def _on_redraw_on_sync_set(self, *_args: object) -> None:
        """Save Redraw Ladder on Sync each time the user sets it in the Tools menu."""
        self._save(replace(self._saved, redraw_on_sync=self.redraw_on_sync))

    def _save(self, saved: settings_file.SavedSettings) -> None:
        """Keep *saved* and write it to the settings file.

        If the file cannot be written, the values hold until ClickNick closes.
        """
        self._saved = saved
        if not settings_file.write_settings(saved, self._settings_path):
            logger.warning("Could not save ClickNick's settings file")

    @property
    def show_info_tooltip(self) -> bool:
        """Get info tooltip display setting."""
        return self.show_info_tooltip_var.get() if self.show_info_tooltip_var else True
