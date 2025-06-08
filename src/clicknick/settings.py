import tkinter as tk
from dataclasses import dataclass


@dataclass
class AppSettings:
    """Application settings and configuration."""

    def __init__(self):
        self.search_var = tk.StringVar(value="contains")
        self.sort_by_nickname_var = tk.BooleanVar(value=False)
        self.exclude_sc_sd_var = tk.BooleanVar(value=False)
        self.exclude_nicknames_var = tk.StringVar(value="")
        self.show_info_tooltip_var = tk.BooleanVar(value=True)

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
        if exclude_terms == "name1, name2, name3":
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
    def show_info_tooltip(self) -> bool:
        """Get info tooltip display setting."""
        return self.show_info_tooltip_var.get() if self.show_info_tooltip_var else True
