"""History panel: logs watched-tag transitions with auto-populated causes.

Pure view. The owning window holds the watch list, diffs each scan frame, and
feeds rows in through :meth:`append_row` / :meth:`set_row_cause`.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from tksheet import Sheet

from ...widgets.nickname_combobox import NicknameCombobox

COL_SCAN = 0
COL_TAG = 1
COL_PREVIOUS = 2
COL_CURRENT = 3
COL_CAUSE = 4

COLUMN_HEADERS = ["Scan", "Tag", "Previous", "Current", "Cause"]
COLUMN_WIDTHS = [60, 150, 80, 80, 230]
MAX_ROWS = 5000


class HistoryPanel(ttk.Frame):
    """Displays watched-tag transitions and their causal chains.

    Upper area: a nickname picker to add watched tags, watch chips, and a
    tksheet table of transitions. Lower area: the full causal chain for the
    selected row.
    """

    # ------------------------------------------------------------------
    # Watch input
    # ------------------------------------------------------------------

    def _on_insert(self) -> None:
        self._nickname_combo.finalize_entry()

    def _on_nickname_selected(self, nickname: str) -> None:
        if nickname:
            self._on_watch_add(nickname)
        self._nickname_combo.reset()

    def _show_detail(self, text: str) -> None:
        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", text or "(no causal data yet)")
        self.detail_text.config(state=tk.DISABLED)

    def _on_row_selected(self, event: Any = None) -> None:
        selected = self.sheet.get_currently_selected()
        if selected is None:
            return
        row_idx = selected.row
        if row_idx is None or row_idx < 0 or row_idx >= len(self._rows):
            return
        self._show_detail(self._rows[row_idx]["cause_full"])

    def _create_widgets(self) -> None:
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(paned)
        paned.add(table_frame, weight=3)

        # Watch input — nickname autocomplete + Insert, mirroring the
        # DataView editor's toolbar.
        watch_bar = ttk.Frame(table_frame)
        watch_bar.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(watch_bar, text="Nickname:").pack(side=tk.LEFT, padx=(0, 4))

        # NicknameCombobox calls master.withdraw(); wrap it in a frame with a
        # dummy withdraw so it does not hide the watch bar.
        combo_frame = ttk.Frame(watch_bar)
        combo_frame.pack(side=tk.LEFT, padx=(0, 4))
        combo_frame.withdraw = lambda: None  # type: ignore[method-assign]
        self._nickname_combo = NicknameCombobox(combo_frame, width=24)
        self._nickname_combo.pack()
        self._nickname_combo.set_data_provider(self._nickname_provider)
        self._nickname_combo.set_selection_callback(self._on_nickname_selected)

        ttk.Button(watch_bar, text="Insert", command=self._on_insert, width=7).pack(
            side=tk.LEFT, padx=(0, 6)
        )

        self._chip_frame = ttk.Frame(table_frame)
        self._chip_frame.pack(fill=tk.X, padx=4, pady=(0, 2))

        self.sheet = Sheet(
            table_frame,
            headers=COLUMN_HEADERS,
            show_x_scrollbar=False,
            show_y_scrollbar=True,
        )
        self.sheet.pack(fill=tk.BOTH, expand=True)

        for i, w in enumerate(COLUMN_WIDTHS):
            self.sheet.column_width(column=i, width=w)

        self.sheet.disable_bindings()
        self.sheet.enable_bindings(
            "single_select",
            "row_select",
            "copy",
            "arrowkeys",
        )
        self.sheet.extra_bindings("cell_select", self._on_row_selected)

        detail_frame = ttk.LabelFrame(paned, text="Causal Chain")
        paned.add(detail_frame, weight=1)

        self.detail_text = tk.Text(
            detail_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            height=6,
            font=("Consolas", 9),
        )
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail_text.yview)
        self.detail_text.config(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.detail_text.pack(fill=tk.BOTH, expand=True)

    def __init__(
        self,
        parent: tk.Widget,
        *,
        nickname_provider: Callable[[str], Any],
        on_watch_add: Callable[[str], None],
        on_watch_remove: Callable[[str], None],
    ) -> None:
        """Initialize the history panel.

        Args:
            parent: Parent widget.
            nickname_provider: Autocomplete data provider for the nickname picker.
            on_watch_add: Called with the picked nickname (or address) to watch.
            on_watch_remove: Called with a chip's key to stop watching it.
        """
        super().__init__(parent)
        self._nickname_provider = nickname_provider
        self._on_watch_add = on_watch_add
        self._on_watch_remove = on_watch_remove
        self._rows: list[dict[str, Any]] = []
        self._next_row_id = 0
        self._auto_scroll = True
        self._create_widgets()

    def set_watch_chips(self, items: list[tuple[str, str]]) -> None:
        """Render the watch list. *items* is a list of ``(key, label)`` pairs.

        The key is opaque to the panel and is passed back to ``on_watch_remove``.
        """
        for child in self._chip_frame.winfo_children():
            child.destroy()
        for key, label in items:
            ttk.Button(
                self._chip_frame,
                text=f"{label}  ✕",
                command=lambda k=key: self._on_watch_remove(k),
            ).pack(side=tk.LEFT, padx=2, pady=2)

    # ------------------------------------------------------------------
    # Row data
    # ------------------------------------------------------------------

    def append_row(
        self,
        scan: int | None,
        tag_label: str,
        previous: str,
        current: str,
    ) -> int:
        """Append a transition row. Returns a stable row id for cause updates."""
        row_id = self._next_row_id
        self._next_row_id += 1
        self._rows.append(
            {
                "id": row_id,
                "scan": scan,
                "tag": tag_label,
                "previous": previous,
                "current": current,
                "cause": "",
                "cause_full": "",
            }
        )
        self.sheet.insert_rows(
            rows=[
                [
                    "" if scan is None else str(scan),
                    tag_label,
                    previous,
                    current,
                    "",
                ]
            ],
            idx="end",
            emit_event=False,
        )

        if len(self._rows) > MAX_ROWS:
            excess = len(self._rows) - MAX_ROWS
            self._rows = self._rows[excess:]
            self.sheet.delete_rows(list(range(excess)), emit_event=False)

        if self._auto_scroll and self._rows:
            self.sheet.see(row=len(self._rows) - 1)

        return row_id

    def set_row_cause(self, row_id: int, text: str) -> None:
        """Fill in the auto-queried cause for a previously appended row."""
        summary = text.split("\n")[0][:80] if text else ""
        for idx, row in enumerate(self._rows):
            if row["id"] == row_id:
                row["cause"] = summary
                row["cause_full"] = text
                self.sheet.set_cell_data(idx, COL_CAUSE, summary)
                selected = self.sheet.get_currently_selected()
                if selected is not None and selected.row == idx:
                    self._show_detail(text)
                return

    def clear(self) -> None:
        """Clear all logged transitions (watch list is unaffected)."""
        self._rows.clear()
        self.sheet.set_sheet_data([], reset_col_positions=False)
        self._show_detail("")
