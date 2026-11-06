"""Guided paste panel for loading a folder of ladder CSVs into Click."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from tksheet import Sheet

from ..connection_session import SavedProgram
from ..ladder.clipboard import copy_to_clipboard, is_click_v4
from ..ladder.program import (
    FolderComparison,
    compare_csv_folder,
    count_csv_rungs,
    import_nicknames_csv,
    list_csv_folder,
    prepare_csv_load,
    read_csv_comment,
)
from ..utils.win32_utils import WIN32

# Column layout
COL_STATUS = 0
COL_FILE = 1
COL_RUNGS = 2
COL_CLICK = 3
COL_DESC = 4
_NUM_COLS = 5

# Past this, CLICK's editor can sit frozen for a long time on the paste.
_SLOW_PASTE_RUNGS = 100

# Icons
_ICON_DONE = "\u2713"  # ✓
_ICON_CURRENT = "\u25b6"  # ▶
_ICON_PENDING = "\u25cb"  # ○

_ICON_MATCHES = "="
_ICON_ONLY_IN_CLICK = "!"

# "vs CLICK" column
_CLICK_CHANGED = "Changed"
_CLICK_MATCHES = "Up to date"
_CLICK_ONLY = "Only in CLICK"
_DESC_ONLY_IN_CLICK = "Not in this folder; delete it in CLICK if it is no longer used"

# Row colours
_BG_DONE = "#d4edda"
_BG_CURRENT = "#cce5ff"
_FG_MATCHES = "gray"
_FG_ONLY_IN_CLICK = "#a94442"

# Special display name for the nicknames import step
_NICKNAMES_NAME = "nicknames.csv"

# How often to check whether the program in CLICK has changed
_WATCH_INTERVAL_MS = 1000

_FIRST_TIME_TIPS = (
    "Guided Paste\n\n"
    "Each step copies one program to the clipboard. Paste it into CLICK with Ctrl+V, "
    "then wait until the rungs appear before doing anything else: a big paste can take "
    "a while, and CLICK may look frozen until it finishes.\n\n"
    "Subroutines come before main. Create each one in CLICK (New Subroutine does this "
    "for you), then paste into it."
)


def _tips_seen_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "ClickNick" / "guided_paste_popup_seen"


# CLICK's Ctrl+U dialog, and its subroutine name box
_NEW_SUB_TITLE = "New Subroutine Program"
_NEW_SUB_NAME_CONTROL = "Edit1"
_SUBROUTINE_PREFIX = "subroutines/"
# Time for CLICK to come to the front before Ctrl+U, then to open the dialog
_ACTIVATE_DELAY_MS = 100
_DIALOG_POLL_MS = 100
_DIALOG_TIMEOUT_MS = 3000


class GuidedPasteWindow(tk.Toplevel):
    """Non-modal panel that walks the user through pasting ladder CSVs."""

    # ------------------------------------------------------------------
    # Folder scanning
    # ------------------------------------------------------------------

    def _scan_folder(self) -> None:
        # Insert nicknames.csv as the first step if it exists
        nicks = self._folder / "nicknames.csv"
        if nicks.exists():
            self._nickname_path = nicks
            self._folder_items.append((_NICKNAMES_NAME, nicks, 0, "Import nicknames into MDB"))

        raw = list_csv_folder(self._folder)
        for name, path in raw:
            rungs = count_csv_rungs(path)
            desc = read_csv_comment(path)
            self._folder_items.append((name, path, rungs, desc))

    def _compare_with_click(self) -> None:
        """Compare the folder with the program now in CLICK; rebuild the rows.

        Programs CLICK has that the folder lacks are listed after the folder's
        own items, for information only: pasting cannot remove them.
        """
        program = self._saved_program = self._get_saved_program()
        if program.csv_dir is None:
            comparison = FolderComparison()
            self._compare_note = program.note
        else:
            comparison = compare_csv_folder(self._folder, program.csv_dir)
            compared = comparison.differs or comparison.only_in_click
            self._compare_note = "Compared with CLICK's last save" if compared else ""
        self._differs = comparison.differs
        self._only_in_click = set(comparison.only_in_click)
        self._missing_in_click = comparison.missing_in_click
        self._click_compared = comparison.compared
        self._items = [
            *self._folder_items,
            *(
                (name, path, count_csv_rungs(path), _DESC_ONLY_IN_CLICK)
                for name, path in comparison.only_in_click.items()
            ),
        ]

    def _can_add_subroutine(self, idx: int | None) -> bool:
        """Whether the row is a subroutine CLICK may not have yet.

        Only a comparison showing CLICK's last save has it rules it out: an
        unsaved project, or one CLICK's program could not be read from, may lack any.
        """
        if idx is None or idx >= len(self._items):
            return False
        name = self._items[idx][0]
        if not name.startswith(_SUBROUTINE_PREFIX):
            return False
        return name in self._missing_in_click or not self._click_compared

    def _is_nickname_step(self, idx: int) -> bool:
        return idx is not None and idx < len(self._items) and self._items[idx][0] == _NICKNAMES_NAME

    def _matches_click(self, name: str) -> bool:
        return self._differs.get(name) is False

    def _needs_paste(self, name: str) -> bool:
        return (
            name not in self._done
            and not self._matches_click(name)
            and name not in self._only_in_click
        )

    def _update_progress_text(self) -> None:
        todo = [
            name
            for name, *_ in self._items
            if not self._matches_click(name) and name not in self._only_in_click
        ]
        done_n = sum(1 for name in todo if name in self._done)
        text = f"{done_n} of {len(todo)} done"
        matching = sum(1 for name, *_ in self._items if self._matches_click(name))
        if matching:
            text += f" · {matching} up to date in CLICK"
        if self._only_in_click:
            text += f" · {len(self._only_in_click)} only in CLICK"
        self._progress_lbl.configure(text=text)

    # ------------------------------------------------------------------
    # Row highlighting
    # ------------------------------------------------------------------

    def _highlight_row(self, idx: int, bg: str | None = None, fg: str | None = None) -> None:
        for col in range(_NUM_COLS):
            self._sheet.highlight_cells(row=idx, column=col, bg=bg, fg=fg)

    def _dehighlight_row(self, idx: int) -> None:
        for col in range(_NUM_COLS):
            self._sheet.dehighlight_cells(row=idx, column=col)

    def _update_highlights(self) -> None:
        for idx, (name, *_) in enumerate(self._items):
            if name in self._done:
                self._highlight_row(idx, _BG_DONE)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_DONE)
            elif idx == self._current_idx:
                self._highlight_row(idx, _BG_CURRENT)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_CURRENT)
            elif self._matches_click(name):
                self._dehighlight_row(idx)
                self._highlight_row(idx, fg=_FG_MATCHES)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_MATCHES)
            elif name in self._only_in_click:
                self._dehighlight_row(idx)
                self._highlight_row(idx, fg=_FG_ONLY_IN_CLICK)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_ONLY_IN_CLICK)
            else:
                self._dehighlight_row(idx)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_PENDING)
        self._sheet.set_refresh_timer()
        self._update_progress_text()

    # ------------------------------------------------------------------
    # Action button state
    # ------------------------------------------------------------------

    def _update_action_btn(self) -> None:
        """Update the main action button text based on current state."""
        can_add = self._can_add_subroutine(self._current_idx) and not self._adding_subroutine
        self._add_sub_btn.configure(state="normal" if can_add else "disabled")
        if self._current_idx is None:
            self._action_btn.configure(state="disabled", text="Done")
            return

        if self._copied:
            self._action_btn.configure(state="normal", text="Next \u2192")
        else:
            label = "Import" if self._is_nickname_step(self._current_idx) else "Copy"
            self._action_btn.configure(state="normal", text=label)

    # ------------------------------------------------------------------
    # Sheet data
    # ------------------------------------------------------------------

    def _populate_sheet(self) -> None:
        data = []
        for name, _path, rungs, desc in self._items:
            icon = _ICON_DONE if name in self._done else _ICON_PENDING
            rung_str = "" if name == _NICKNAMES_NAME else str(rungs)
            differs = self._differs.get(name)
            if name in self._only_in_click:
                click_str = _CLICK_ONLY
            elif differs is None:
                click_str = ""
            else:
                click_str = _CLICK_CHANGED if differs else _CLICK_MATCHES
            data.append([icon, name, rung_str, click_str, desc])
        self._sheet.set_sheet_data(data)
        self._sheet.set_column_widths([30, 250, 45, 80, 370])
        self._compare_lbl.configure(text=self._compare_note)
        self._update_highlights()
        self._update_action_btn()

    def _all_done(self) -> None:
        self._current_idx = None
        self._copied = False
        self._update_highlights()
        if any(self._matches_click(name) for name, *_ in self._items):
            msg = "Every changed program has been pasted!"
        else:
            msg = "All CSVs have been pasted!"
        if self._only_in_click:
            msg += (
                f"\n{len(self._only_in_click)} program(s) in CLICK are not in this folder;"
                " delete them in CLICK if they are no longer used"
            )
        self._status_var.set(msg)
        self._update_action_btn()

    # ------------------------------------------------------------------
    # Clipboard / Import
    # ------------------------------------------------------------------

    def _do_import_nicknames(self, idx: int) -> None:
        """Import nicknames.csv into MDB."""
        _name, path, _rungs, _ = self._items[idx]
        mdb_path = self._get_mdb_path()
        if not mdb_path:
            self._status_var.set(
                "No Click database found.\n"
                "Connect to a Click instance first, then click 'Re-import'."
            )
            return

        result = import_nicknames_csv(path, mdb_path)
        if result.error:
            self._status_var.set(f"Import error: {result.error}")
            return

        self._copied = True
        msg = f"Imported {result.rows_written} nickname(s) into MDB"
        msg += '\nClick "Next" to continue to ladder CSVs'
        self._status_var.set(msg)
        self._update_action_btn()

    def _do_copy_to_clipboard(self, idx: int) -> None:
        """Copy a ladder CSV to the clipboard."""
        name, path, _rungs, _ = self._items[idx]
        try:
            mdb_path = self._get_mdb_path()
            click_hwnd = self._get_click_hwnd()
            result = prepare_csv_load(
                path,
                click_v4=is_click_v4(click_hwnd),
                mdb_path=mdb_path,
                show_nicknames=self._show_nicks_var.get(),
            )
            copy_to_clipboard(result.payload, owner_hwnd=click_hwnd)

            self._copied = True
            rung_word = "rung" if result.rung_count == 1 else "rungs"
            msg = f"{name} copied to clipboard ({result.rung_count} {rung_word})"
            if result.addresses_inserted:
                msg += f"\nMDB: inserted {result.addresses_inserted} address(es)"
            elif result.mdb_error:
                msg += f"\nMDB: {result.mdb_error}"
            msg += '\nPaste into CLICK (Ctrl+V on ladder screen), then click "Next"'
            self._status_var.set(msg)
            self._update_action_btn()
            if result.rung_count >= _SLOW_PASTE_RUNGS:
                messagebox.showinfo(
                    "Large paste",
                    f"{name} has {result.rung_count} rungs.\n\n"
                    "Pasting this might take a while, and CLICK may freeze until it finishes.",
                    parent=self,
                )
        except RuntimeError as exc:
            self._status_var.set(f"Clipboard error: {exc}\nIs Click running?")
        except Exception as exc:
            self._status_var.set(f"Error loading {name}: {exc}")

    # ------------------------------------------------------------------
    # New subroutine in CLICK
    # ------------------------------------------------------------------

    def _finish_add_subroutine(self, msg: str) -> None:
        self._adding_subroutine = False
        self._status_var.set(msg)
        self._update_action_btn()

    def _fill_new_subroutine(self, dialog: int, sub_name: str) -> None:
        if WIN32.set_control_text(dialog, _NEW_SUB_NAME_CONTROL, sub_name):
            msg = (
                f'Named the new subroutine "{sub_name}" in CLICK.\n'
                'Click OK there, then "Copy" here and paste into the new subroutine'
            )
        else:
            msg = f'CLICK\'s {_NEW_SUB_TITLE} window has no name box; type "{sub_name}" there'
        self._finish_add_subroutine(msg)

    def _wait_for_new_subroutine(self, pid: str, sub_name: str, remaining_ms: int) -> None:
        if not self.winfo_exists():
            return
        dialog = WIN32.find_process_window(pid, _NEW_SUB_TITLE)
        if dialog:
            self._fill_new_subroutine(dialog, sub_name)
        elif remaining_ms <= 0:
            self._finish_add_subroutine(
                f"CLICK did not open {_NEW_SUB_TITLE}.\n"
                "Click in CLICK's ladder editor (close any open dialogs), then try again"
            )
        else:
            self.after(
                _DIALOG_POLL_MS,
                lambda: self._wait_for_new_subroutine(
                    pid, sub_name, remaining_ms - _DIALOG_POLL_MS
                ),
            )

    def _send_new_subroutine_key(self, pid: str, sub_name: str) -> None:
        if not self.winfo_exists():
            return
        # Ctrl+U goes to whichever window is in front: make sure that is CLICK
        if WIN32.get_foreground_pid() != pid:
            self._finish_add_subroutine("Could not bring CLICK to the front; try again")
            return
        WIN32.send_ctrl_key("U")
        self._wait_for_new_subroutine(pid, sub_name, _DIALOG_TIMEOUT_MS)

    def _on_add_subroutine(self) -> None:
        """Open CLICK's New Subroutine Program (Ctrl+U) and fill in the row's name."""
        idx = self._current_idx
        if idx is None or self._adding_subroutine or not self._can_add_subroutine(idx):
            return
        hwnd = self._get_click_hwnd()
        pid = WIN32.get_pid(hwnd) if hwnd else ""
        if not pid:
            self._status_var.set("No CLICK window found. Connect to CLICK first")
            return
        sub_name = Path(self._items[idx][0]).stem
        self._adding_subroutine = True
        self._update_action_btn()
        dialog = WIN32.find_process_window(pid, _NEW_SUB_TITLE)
        if dialog:  # Already open: just fill it in
            WIN32.activate(dialog)
            self._fill_new_subroutine(dialog, sub_name)
            return
        WIN32.activate(hwnd)
        self.after(_ACTIVATE_DELAY_MS, lambda: self._send_new_subroutine_key(pid, sub_name))

    def _perform_action(self, idx: int) -> None:
        """Perform the copy or import action for the given row."""
        if self._is_nickname_step(idx):
            self._do_import_nicknames(idx)
        else:
            self._do_copy_to_clipboard(idx)

    def _select_row(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._items):
            return
        name = self._items[idx][0]
        if name in self._done:
            return
        self._current_idx = idx
        self._copied = False
        self._update_highlights()
        self._update_action_btn()

        if self._is_nickname_step(idx):
            self._status_var.set('Click "Import" to import nicknames into the Click database')
        elif self._matches_click(name):
            self._status_var.set(
                f"{name} already matches CLICK's last save.\n"
                'Click "Copy" to copy it to the clipboard anyway'
            )
        elif self._can_add_subroutine(idx):
            where = (
                "is not in CLICK's last save" if self._click_compared else "may not be in CLICK yet"
            )
            self._status_var.set(
                f"{name} {where}.\n"
                'Click "New Subroutine" to create it in CLICK, or "Copy" if it already exists'
            )
        else:
            self._status_var.set(f'Click "Copy" to copy {name} to the clipboard')

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _advance_to_first_pending(self) -> None:
        for idx, (name, *_) in enumerate(self._items):
            if self._needs_paste(name):
                self._select_row(idx)
                return
        self._all_done()

    def _advance_to_next(self) -> None:
        if self._current_idx is None:
            self._advance_to_first_pending()
            return
        start = self._current_idx + 1
        # Search forward from current, then wrap
        for idx in list(range(start, len(self._items))) + list(range(0, start)):
            name = self._items[idx][0]
            if self._needs_paste(name):
                self._select_row(idx)
                return
        self._all_done()

    # ------------------------------------------------------------------
    # Following the program in CLICK
    # ------------------------------------------------------------------

    def _on_saved_program_changed(self, program: SavedProgram) -> None:
        """Bring the rows up to date with what CLICK now has."""
        new_project = (
            program.session is not None
            and self._project_session is not None
            and program.session is not self._project_session
        )
        if program.session is not None:
            self._project_session = program.session
        if new_project:
            # What was pasted went into the other project.
            self._done.clear()
            self._current_idx = None
            self._copied = False
        elif program.building and self._differs:
            # CLICK saved: keep the rows until the new CSVs are ready.
            self._saved_program = program
            self._compare_lbl.configure(text=program.note)
            return

        self._compare_with_click()
        self._populate_sheet()
        if self._copied:
            return  # Mid-paste: the row stays current until "Next"
        idx = self._current_idx
        if idx is None or not self._needs_paste(self._items[idx][0]):
            self._advance_to_first_pending()

    def _watch_saved_program(self) -> None:
        if not self.winfo_exists():
            return
        program = self._get_saved_program()
        if program != self._saved_program:
            self._on_saved_program_changed(program)
        self.after(_WATCH_INTERVAL_MS, self._watch_saved_program)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_cell_select(self, _event: object) -> None:
        selected = self._sheet.get_currently_selected()
        if selected is None:
            return
        row = selected.row
        if 0 <= row < len(self._items):
            name = self._items[row][0]
            if name in self._only_in_click:
                self._status_var.set(
                    f"{name} is in CLICK but not in this folder. Pasting cannot remove it;\n"
                    "delete it in CLICK if it is no longer used"
                )
            elif name not in self._done:
                self._select_row(row)

    def _on_action(self) -> None:
        """Handle the main action button (Copy/Import or Next)."""
        if self._current_idx is None:
            return
        if self._copied:
            # "Next" — mark done and advance
            name = self._items[self._current_idx][0]
            self._done.add(name)
            self._advance_to_next()
        else:
            # "Copy" or "Import" — perform the action
            self._perform_action(self._current_idx)

    def _on_skip(self) -> None:
        if self._current_idx is None:
            return
        self._advance_to_next()

    def _show_first_time_tips(self) -> None:
        """Show how to paste, once per user."""
        seen = _tips_seen_path()
        if not self.winfo_exists() or seen.exists():
            return
        messagebox.showinfo("First-Time Tips", _FIRST_TIME_TIPS, parent=self)
        try:
            seen.parent.mkdir(parents=True, exist_ok=True)
            seen.touch()
        except OSError:
            pass  # A settings write failure must not get in the way of pasting

    def _on_restart(self) -> None:
        if self._done and not messagebox.askyesno(
            "Restart",
            f"Clear progress for {len(self._done)} completed CSV(s)?",
            parent=self,
        ):
            return
        self._done.clear()
        self._current_idx = None
        self._copied = False
        self._action_btn.configure(state="normal")
        self._compare_with_click()
        self._populate_sheet()
        self._advance_to_first_pending()

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------

    def _create_widgets(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # --- header ---
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(
            header,
            text=f"Guided Paste \u2014 {self._folder.name}/",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT)
        self._progress_lbl = ttk.Label(header, text="")
        self._progress_lbl.pack(side=tk.RIGHT)

        # --- options row ---
        opts = ttk.Frame(main)
        opts.pack(fill=tk.X, pady=(0, 5))

        if self._nickname_path:
            ttk.Label(opts, text="nicknames.csv found", foreground="gray").pack(side=tk.LEFT)
        self._compare_lbl = ttk.Label(opts, text="", foreground="gray")
        self._compare_lbl.pack(side=tk.LEFT, padx=(10, 0))

        self._show_nicks_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts,
            text="Show nicknames in math instructions",
            variable=self._show_nicks_var,
        ).pack(side=tk.RIGHT)

        # --- tksheet ---
        sheet_frame = tk.Frame(main, relief=tk.SUNKEN, borderwidth=2)
        sheet_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self._sheet = Sheet(
            sheet_frame,
            headers=["", "File", "Rungs", "vs CLICK", "Description"],
            show_row_index=False,
            height=300,
            width=690,
        )
        self._sheet.enable_bindings()
        self._sheet.disable_bindings(
            "column_drag_and_drop",
            "row_drag_and_drop",
            "rc_select_column",
            "rc_insert_column",
            "rc_delete_column",
            "rc_insert_row",
            "rc_delete_row",
            "sort_cells",
            "sort_row",
            "sort_column",
            "sort_rows",
            "sort_columns",
            "edit_cell",
            "find",
            "replace",
            "undo",
            "copy",
            "cut",
            "paste",
            "delete",
        )
        # Suppress the right-click popup entirely on this read-only sheet
        self._sheet.bind("<Button-3>", lambda e: "break")
        self._sheet.pack(fill=tk.BOTH, expand=True)

        self._sheet.extra_bindings("cell_select", self._on_cell_select)

        # --- status label ---
        self._status_var = tk.StringVar(value="Loading\u2026")
        status_frame = ttk.LabelFrame(main, text="Instructions", padding=5)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(
            status_frame,
            textvariable=self._status_var,
            wraplength=660,
            foreground="gray",
        ).pack(fill=tk.X)

        # --- buttons ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="⟳ Restart", command=self._on_restart, width=10).pack(
            side=tk.LEFT
        )

        self._action_btn = ttk.Button(
            btn_frame, text="Copy", command=self._on_action, width=10, state="disabled"
        )
        self._action_btn.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Button(btn_frame, text="Skip", command=self._on_skip, width=10).pack(side=tk.RIGHT)

        self._add_sub_btn = ttk.Button(
            btn_frame,
            text="New Subroutine",
            command=self._on_add_subroutine,
            state="disabled",
        )
        self._add_sub_btn.pack(side=tk.RIGHT, padx=(0, 5))

    def __init__(
        self,
        parent: tk.Widget,
        folder: Path,
        *,
        get_mdb_path: Callable[[], Path | None],
        get_click_hwnd: Callable[[], int | None],
        get_saved_program: Callable[[], SavedProgram],
    ):
        super().__init__(parent)
        self.title(f"Guided Paste \u2014 {folder.name}")
        self.geometry("820x520")
        self.minsize(520, 400)

        self._folder = folder
        self._get_mdb_path = get_mdb_path
        self._get_click_hwnd = get_click_hwnd
        # The program now in CLICK as CSVs: the generated workspace's csv/ folder
        self._get_saved_program = get_saved_program

        # (display_name, path, rung_count, description)
        self._folder_items: list[tuple[str, Path, int, str]] = []
        # The sheet rows: the folder's items, then programs only in CLICK
        self._items: list[tuple[str, Path, int, str]] = []
        self._done: set[str] = set()
        self._current_idx: int | None = None
        self._copied: bool = False
        self._nickname_path: Path | None = None
        # name -> differs from CLICK; absent when unknown (no workspace, not a program)
        self._differs: dict[str, bool] = {}
        self._only_in_click: set[str] = set()
        # Folder items CLICK's last save lacks: subroutines to create first
        self._missing_in_click: frozenset[str] = frozenset()
        self._click_compared = False
        self._adding_subroutine = False
        self._compare_note = ""

        self._scan_folder()
        self._compare_with_click()
        # The session of the project being pasted into; survives a brief disconnect
        self._project_session = self._saved_program.session
        self._create_widgets()
        self._populate_sheet()
        self._advance_to_first_pending()
        self.after(_WATCH_INTERVAL_MS, self._watch_saved_program)
        self.after_idle(self._show_first_time_tips)
