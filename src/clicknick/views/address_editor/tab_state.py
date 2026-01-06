"""Tab state dataclass for Address Editor tabs.

Each tab maintains independent filter and view state while sharing
the underlying address data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TabState:
    """State for a single Address Editor tab.

    Tracks filter settings, column visibility, and scroll position.
    Multiple tabs can have different filter states while sharing
    the same underlying AddressRow data.
    """

    # Filter settings
    filter_enabled: bool = True  # Filter checkbox state
    filter_text: str = ""
    hide_empty: bool = False
    hide_assigned: bool = False
    show_unsaved_only: bool = False

    # Column visibility
    hide_used_column: bool = False
    hide_init_ret_columns: bool = True  # Hidden by default

    # Scroll position (row index in displayed rows)
    scroll_row_index: int = 0

    # Tab display name (for tab title)
    name: str = field(default="")

    def clone(self) -> TabState:
        """Create a copy of this state for a new tab.

        Returns:
            New TabState with same settings.
        """
        return TabState(
            filter_enabled=self.filter_enabled,
            filter_text=self.filter_text,
            hide_empty=self.hide_empty,
            hide_assigned=self.hide_assigned,
            show_unsaved_only=self.show_unsaved_only,
            hide_used_column=self.hide_used_column,
            hide_init_ret_columns=self.hide_init_ret_columns,
            scroll_row_index=self.scroll_row_index,
            name="",  # New tab gets fresh name
        )

    @classmethod
    def fresh(cls) -> TabState:
        """Create a fresh default state.

        Returns:
            New TabState with default settings.
        """
        return cls()
