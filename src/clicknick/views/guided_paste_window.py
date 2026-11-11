"""Guided paste panel: walk a folder of ladder CSVs into Click, with the rung diff.

The one window for getting ladder into CLICK. The Ladder menu opens it on any
folder of CSVs; Preview Changes (``clicknick-cli rung apply``) opens it on the
workspace's ``csv_output/``. Each row is a program; the pane below shows how the
selected one differs from CLICK's last save, and the step copies either the
whole program or just the rungs that differ.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from tksheet import Sheet

from ..connection_session import SavedProgram
from ..ladder.clipboard import copy_to_clipboard, is_click_v4
from ..ladder.program import (
    LegacyEncoding,
    describe_legacy_encoding,
    import_nicknames_csv,
    prepare_rungs_load,
)
from ..services.rung_diff import (
    BundleComparison,
    BundleSources,
    PasteStep,
    ProgramChange,
    ProposedProgram,
    RenderedDiff,
    compare_bundle,
    format_group,
    load_bundle,
    paste_groups,
    render_diff,
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

# From this many steps in one program, clearing it and pasting it whole is likely less work.
_MANY_STEPS = 6

# Icons
_ICON_DONE = "✓"  # ✓
_ICON_CURRENT = "▶"  # ▶
_ICON_PENDING = "○"  # ○

_ICON_MATCHES = "="
_ICON_ONLY_IN_CLICK = "!"

# "vs CLICK" column
_CLICK_NEW = "New"
_CLICK_MATCHES = "Up to date"
_CLICK_ONLY = "Only in CLICK"
_DESC_ONLY_IN_CLICK = "Not in this folder; delete it in CLICK if it is no longer used"

# Row colours
_BG_DONE = "#d4edda"
_BG_CURRENT = "#cce5ff"
_FG_MATCHES = "gray"
_FG_ONLY_IN_CLICK = "#a94442"
# CLICK holds some of the program's rungs in a legacy encoding
_BG_LEGACY = "#f8d7da"
_FG_LEGACY = "#842029"
# A note lists this many of a program's legacy-encoded rungs and counts the rest
_LEGACY_LISTED = 5

# Diff pane text (GitHub Desktop's light theme); see the tags in _build_ui
_DIFF_TEXT = "#24292e"
_DIFF_MUTED = "#586069"
_DIFF_LINE_TAGS = {"+": "added", "-": "removed"}

# The Copy switch: what a step copies for a program CLICK already has
_COPY_CHANGED = "Changed rungs"
_COPY_WHOLE = "Whole program"

# Special display name for the nicknames import step
_NICKNAMES_NAME = "nicknames.csv"

# How often to check whether the program in CLICK has changed
_WATCH_INTERVAL_MS = 1000

_FIRST_TIME_TIPS = (
    "Guided Paste\n\n"
    "Each step copies rungs to the clipboard: a whole program, or just the rungs that "
    "differ when CLICK already has it (the Copy switch chooses). The pane under the list "
    "shows the difference. Work down each program in order: a step's rung numbers are "
    "the ones CLICK shows once the steps before it are done. "
    "Paste into CLICK with Ctrl+V, then wait until the rungs appear before doing anything "
    "else: a big paste can take a while, and CLICK may look frozen until it finishes.\n\n"
    "Subroutines come before main. Create each one in CLICK (New Subroutine does this "
    "for you), then paste into it."
)


def _tips_seen_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "ClickNick" / "guided_paste_popup_seen"


def _preferences_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "ClickNick" / "guided-paste.json"


def _read_copy_whole() -> bool:
    """Read the user's Copy switch choice; changed rungs until they choose otherwise."""
    try:
        payload = json.loads(_preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("copy_whole_program") is True


def _save_copy_whole(whole: bool) -> None:
    """Remember the user's Copy switch choice for the next Guided Paste window."""
    path = _preferences_path()
    staging = path.with_suffix(".json.staging")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        staging.write_text(
            json.dumps({"copy_whole_program": whole}, indent=2) + "\n", encoding="utf-8"
        )
        staging.replace(path)
    except OSError:
        pass  # The choice still holds for this window


def _rungs_in_click(numbers: Sequence[int]) -> str:
    """Name rungs by the numbers CLICK shows: ``rung 5`` or ``rungs 5 to 7``."""
    if len(numbers) == 1:
        return f"rung {numbers[0]}"
    return f"rungs {numbers[0]} to {numbers[-1]}"


def _where_to_paste(step: PasteStep) -> str:
    """Say where in CLICK a step's rungs go.

    CLICK pastes over the selected rung: that rung is replaced by the first
    pasted rung and the rest go in below it.
    """
    if not step.placed:
        return "Paste it in CLICK (Ctrl+V) over the rung it replaces, or over a new empty rung"
    if step.over is not None:
        return f"In CLICK, select rung {step.over} and paste over it (Ctrl+V)"
    where = "after the last rung" if step.above is None else f"above rung {step.above}"
    return f"In CLICK, insert an empty rung {where} and paste over it (Ctrl+V)"


def _legacy_note(change: ProgramChange) -> str:
    """Say which of CLICK's rungs hold a legacy encoding and that they need pasting again."""
    if not change.legacy:
        return ""
    rungs = sorted({item.rung for item in change.legacy if item.rung is not None})
    if not rungs:
        head = "CLICK's copy has an old encoding. Paste the whole program again."
    elif len(rungs) == 1:
        head = f"CLICK's copy of rung {rungs[0]} has an old encoding. Paste it again."
    else:
        listed = ", ".join(
            str(run[0]) if len(run) == 1 else f"{run[0]} to {run[-1]}"
            for run in paste_groups(rungs)
        )
        head = f"CLICK's copy of rungs {listed} has an old encoding. Paste them again."
    lines = [
        f"  {describe_legacy_encoding(item, program=False)}"
        for item in change.legacy[:_LEGACY_LISTED]
    ]
    if len(change.legacy) > _LEGACY_LISTED:
        lines.append(f"  ...and {len(change.legacy) - _LEGACY_LISTED} more")
    return "\n".join([head, *lines])


def _change_label(change: ProgramChange) -> str:
    """Say how much of a program CLICK already has differs, for the "vs CLICK" column."""
    changed, removed = len(change.changed), len(change.removed)
    if changed and removed:
        label = f"{changed} changed, {removed} removed"
    else:
        count, verb = (changed, "changed") if changed else (removed, "removed")
        label = f"{count} rung{'s' if count != 1 else ''} {verb}"
    return f"{label}, old encoding" if change.legacy else label


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
        """Read the folder's CSVs; they are compared and copied as read here.

        A folder that has since been emptied keeps what was read: a CLICK save
        regenerates the workspace and removes its ``csv_output/``.
        """
        programs = load_bundle(self._folder)
        if not programs and self._programs:
            return
        self._programs = {program.name: program for program in programs}
        self._read_at = datetime.now().strftime("%H:%M")
        self._folder_items = []
        # A workspace's tags reach CLICK through the Address Editor (tag apply),
        # so only a plain folder gets the nicknames import step.
        nicks = self._folder / "nicknames.csv"
        self._nickname_path = nicks if self._source_dir is None and nicks.exists() else None
        if self._nickname_path is not None:
            self._folder_items.append((_NICKNAMES_NAME, nicks, 0, "Import nicknames into MDB"))
        self._folder_items.extend(
            (program.name, program.path, program.rung_count, program.description)
            for program in programs
        )
        self._after_sources = (
            None
            if self._source_dir is None
            else BundleSources.workspace(self._source_dir, self._folder)
        )

    def _compare_with_click(self) -> None:
        """Compare the folder with the program now in CLICK; rebuild the rows.

        Programs CLICK has that the folder lacks are listed after the folder's
        own items, for information only: pasting cannot remove them.
        """
        program = self._saved_program = self._get_saved_program()
        self._before_sources = None
        if program.csv_dir is None:
            comparison = BundleComparison()
            self._compare_note = program.note
        else:
            comparison = compare_bundle(self._programs.values(), program.csv_dir)
            compared = comparison.changes or comparison.only_in_click
            self._compare_note = "Compared with CLICK's last save" if compared else ""
        self._changes = comparison.changes
        self._only_in_click = comparison.only_in_click
        self._missing_in_click = comparison.missing_in_click
        self._click_compared = comparison.compared
        self._items = [
            *self._folder_items,
            *(
                (name, Path(name), len(change.before), _DESC_ONLY_IN_CLICK)
                for name, change in comparison.only_in_click.items()
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

    def _has_legacy(self, name: str) -> bool:
        """Whether CLICK holds some of the program's rungs in a legacy encoding."""
        change = self._changes.get(name)
        return change is not None and bool(change.legacy)

    def _legacy_in_step(self, name: str, step: PasteStep) -> list[LegacyEncoding]:
        """CLICK's rungs in a legacy encoding that *step* pastes over or deletes."""
        change = self._changes.get(name)
        if change is None or not change.legacy or not step.placed:
            return []
        differences = [opcode for opcode in change.opcodes if opcode[0] != "equal"]
        if step.block >= len(differences):
            return []
        tag, i1, i2, _j1, _j2 = differences[step.block]
        if step.rungs:
            # A paste takes the place of CLICK's first rung of the difference, if any
            numbers = range(i1 + 1, i1 + 2) if tag == "replace" else range(0)
        else:
            # A delete takes what the paste before it did not
            numbers = range(i1 + 2 if tag == "replace" else i1 + 1, i2 + 1)
        return [item for item in change.legacy if item.rung is None or item.rung in numbers]

    def _legacy_line(self, name: str, step: PasteStep) -> str:
        """Say that the step's rungs in CLICK hold an old encoding, or nothing."""
        stale = self._legacy_in_step(name, step)
        if not stale:
            return ""
        found = " ".join(
            dict.fromkeys(f"{item.instruction} {item.token}: {item.detail}" for item in stale)
        )
        line = f"\nCLICK's copy has an old encoding. {found}"
        if not step.rungs:
            return line
        again = "it" if len({item.rung for item in stale}) == 1 else "them"
        return f"{line} Paste {again} again."

    def _matches_click(self, name: str) -> bool:
        change = self._changes.get(name)
        return change is not None and not change.differs

    def _needs_paste(self, name: str) -> bool:
        return (
            name not in self._done
            and not self._matches_click(name)
            and name not in self._only_in_click
        )

    def _steps(self, name: str) -> list[PasteStep]:
        """What to do in CLICK, one difference at a time, for a program CLICK has.

        Empty when the whole program is pasted instead: the Copy switch says so,
        CLICK lacks it, what CLICK has is unknown, or nothing of it differs.
        """
        if self._copy_whole_var.get():
            return []
        selected = self._selection.get(name)
        if selected:
            return [PasteStep(tuple(group), placed=False) for group in paste_groups(selected)]
        change = self._changes.get(name)
        if change is None or name in self._missing_in_click:
            return []
        return list(change.steps)

    def _current_steps(self) -> list[PasteStep]:
        if self._current_idx is None:
            return []
        return self._steps(self._items[self._current_idx][0])

    def _current_step(self) -> PasteStep | None:
        """The current row's step; None when the whole program is copied in one."""
        steps = self._current_steps()
        return steps[self._step_idx] if self._step_idx < len(steps) else None

    def _whole_placement(self, name: str) -> str:
        """Say how a whole program goes into CLICK, given what CLICK has of it."""
        change = self._changes.get(name)
        if change is None or not change.before or name in self._missing_in_click:
            return "Paste into CLICK (Ctrl+V on ladder screen)"
        return (
            "In CLICK, select all of its rungs (Shift+Up/Down) and delete them, then paste (Ctrl+V)"
        )

    def _click_label(self, name: str) -> str:
        if name in self._only_in_click:
            return _CLICK_ONLY
        change = self._changes.get(name)
        if change is None:
            return ""
        if not change.differs:
            return _CLICK_MATCHES
        if name in self._missing_in_click:
            return _CLICK_NEW
        return _change_label(change)

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
    # Rung diff pane
    # ------------------------------------------------------------------

    def _click_sources(self) -> BundleSources:
        """The program in CLICK as pyrung source, generated when first shown."""
        csv_dir = self._saved_program.csv_dir
        if csv_dir is None:
            return self._before_sources or BundleSources()
        if self._before_sources is None:
            self._before_sources = BundleSources.round_trip(csv_dir)
        return self._before_sources

    def _proposed_sources(self) -> BundleSources:
        """The folder's programs as pyrung source: the workspace's own, or generated."""
        if self._after_sources is None:
            self._after_sources = BundleSources.round_trip(self._folder)
        return self._after_sources

    def _describe_view(self) -> tuple[str, RenderedDiff]:
        """A note about the viewed row, and its difference from CLICK when there is one."""
        name = self._view_name
        if name is None:
            return "", RenderedDiff()
        if name == _NICKNAMES_NAME:
            return f"{name} is imported into CLICK's database; it has no rungs.", RenderedDiff()

        change = self._only_in_click.get(name)
        if change is None:
            program = self._programs.get(name)
            if program is not None and program.error:
                return f"{name} could not be read: {program.error}", RenderedDiff()
            change = self._changes.get(name)
            if change is None:
                if self._saved_program.csv_dir is None:
                    return self._saved_program.note, RenderedDiff()
                if not self._click_compared:
                    return (
                        "This folder has no main.csv, so it is not compared with CLICK's program.",
                        RenderedDiff(),
                    )
                return f"{name} could not be compared with CLICK's program.", RenderedDiff()
            if not change.differs:
                return f"{name} matches CLICK's last save.", RenderedDiff()

        before, after = self._click_sources(), self._proposed_sources()
        notes = [_legacy_note(change)]
        if not before.text(name) and not after.text(name):
            notes.append(
                "pyrung could not show this program as text; each rung is listed by its instructions."
            )
        note = "\n".join(line for line in notes if line)
        if change is not self._expanded_change:
            # What was expanded belongs to the difference it was expanded in
            self._expanded_change, self._expanded = change, {}
        return note, render_diff(change, name, before=before, after=after, shown=self._expanded)

    def _scroll_to_step(self) -> None:
        """Bring the difference the current step works on to the top of the pane."""
        line = None
        current = self._items[self._current_idx][0] if self._current_idx is not None else None
        step = self._current_step() if current == self._view_name else None
        if step is not None and step.placed and step.block < len(self._shown_diff.blocks):
            line = self._shown_diff.blocks[step.block]
        elif step is not None:
            starts = (self._shown_diff.starts.get(number) for number in step.rungs)
            line = next((start for start in starts if start is not None), None)
        if line is None:
            self._text.yview_moveto(0)
        else:
            # Lines never wrap, so a line's share of the text is its scroll position
            total = int(self._text.index("end-1c").split(".")[0])
            self._text.yview_moveto((line + self._diff_first_line - 1) / total)

    def _show_diff(self, *, keep_scroll: bool = False) -> None:
        """Show how the viewed row's program differs from CLICK.

        Scrolls to the current step's difference, or with *keep_scroll* stays
        where the pane was.
        """
        top_line = int(self._text.index("@0,0").split(".")[0]) if keep_scroll else 0
        note, diff = self._describe_view()
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        if note:
            self._text.insert(tk.END, f"{note}\n", "note")
        for index, line in enumerate(diff.lines):
            if index < 2:
                self._text.insert(tk.END, line, "file_header")
                continue
            gap = diff.gaps.get(index)
            if gap is not None:
                for arrow in gap.arrows:
                    self._text.insert(tk.END, arrow, ("separator", "expander"))
                self._text.insert(tk.END, f" {line}", "separator")
                continue
            tag = _DIFF_LINE_TAGS.get(line[0])
            if tag not in ("added", "removed"):
                self._text.insert(tk.END, line, tag or ())
                continue
            # The +/- sits in its own gutter colour; the changed words are darker
            self._text.insert(tk.END, line[0], (tag, f"{tag}_gutter"))
            column = 1
            for start, end in diff.words.get(index, ()):
                if column < start:
                    self._text.insert(tk.END, line[column:start], tag)
                self._text.insert(tk.END, line[start:end], (tag, f"{tag}_word"))
                column = end
            self._text.insert(tk.END, line[column:], tag)
        self._text.configure(state=tk.DISABLED)
        self._shown_diff = diff
        # The Text widget numbers lines from 1, and the diff starts below the note
        self._diff_first_line = note.count("\n") + 2 if note else 1
        if keep_scroll:
            total = int(self._text.index("end-1c").split(".")[0])
            self._text.yview_moveto((top_line - 1) / total)
        else:
            self._scroll_to_step()

    def _on_expand(self, event: tk.Event) -> None:
        """Show more of the unchanged rungs behind the clicked separator arrow."""
        position = self._text.index(f"@{event.x},{event.y}")
        gap = self._shown_diff.gaps.get(int(position.split(".")[0]) - self._diff_first_line)
        arrow = self._text.get(position)
        if gap is None or arrow not in gap.arrows:
            return
        self._expanded[gap.opcode] = gap.expand(arrow)
        self._show_diff(keep_scroll=True)

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
            elif self._has_legacy(name):
                self._dehighlight_row(idx)
                self._highlight_row(idx, _BG_LEGACY, _FG_LEGACY)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_PENDING)
            else:
                self._dehighlight_row(idx)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_PENDING)
        self._sheet.set_refresh_timer()
        self._update_progress_text()

    # ------------------------------------------------------------------
    # Action button state
    # ------------------------------------------------------------------

    @staticmethod
    def _nothing_to_copy(step: PasteStep | None) -> bool:
        """Whether the step is done in CLICK alone: rungs to delete, none to paste."""
        return step is not None and not step.rungs

    def _update_action_btn(self) -> None:
        """Update the action buttons based on current state."""
        can_add = self._can_add_subroutine(self._current_idx) and not self._adding_subroutine
        self._add_sub_btn.configure(state="normal" if can_add else "disabled")
        if self._current_idx is None:
            self._action_btn.configure(state="disabled", text="Done")
            return

        step = self._current_step()
        if self._copied or self._nothing_to_copy(step):
            self._action_btn.configure(state="normal", text="Next →")
        elif self._is_nickname_step(self._current_idx):
            self._action_btn.configure(state="normal", text="Import")
        else:
            label = f"Copy {format_group(step.rungs)}" if step else "Copy"
            self._action_btn.configure(state="normal", text=label)

    # ------------------------------------------------------------------
    # Sheet data
    # ------------------------------------------------------------------

    def _settled(self) -> bool:
        """Whether CLICK's last save holds everything the folder does, and nothing more."""
        return (
            self._click_compared
            and not self._only_in_click
            and all(self._matches_click(name) for name in self._programs)
            and (self._nickname_path is None or _NICKNAMES_NAME in self._done)
        )

    def _update_notice(self) -> None:
        """Say so when the folder no longer holds what the window is still pasting.

        A CLICK save, or Reload from CLICK, regenerates the workspace: its
        ``csv_output/`` is removed and ``src/plc`` goes back to what CLICK has.
        """
        gone = bool(self._programs) and not any(
            program.path.is_file() for program in self._programs.values()
        )
        if not gone or self._settled():
            self._notice_lbl.pack_forget()
            return
        if self._source_dir is None:
            text = (
                "This folder's CSVs are gone. The window still holds them as read at "
                f"{self._read_at} and can keep pasting them."
            )
        else:
            text = (
                "CLICK was saved before all of this was pasted, so the workspace is back to "
                f"CLICK's version. This window still holds the proposal exported at "
                f"{self._read_at} and can keep pasting it.\n"
                "The edited source is kept in backup/src/plc: run clicknick-cli restore, "
                "then Preview Changes, to work on it again."
            )
        self._notice_lbl.configure(text=text)
        self._notice_lbl.pack(fill=tk.X, pady=(0, 5), after=self._opts)

    def _populate_sheet(self) -> None:
        data = []
        for name, _path, rungs, desc in self._items:
            icon = _ICON_DONE if name in self._done else _ICON_PENDING
            rung_str = "" if name == _NICKNAMES_NAME else str(rungs)
            data.append([icon, name, rung_str, self._click_label(name), desc])
        self._sheet.set_sheet_data(data)
        self._sheet.set_column_widths([30, 250, 45, 150, 350])
        self._nick_lbl.configure(text="nicknames.csv found" if self._nickname_path else "")
        self._compare_lbl.configure(text=self._compare_note)
        self._update_notice()
        self._update_highlights()
        self._update_action_btn()
        if self._view_name not in {name for name, *_ in self._items}:
            self._view_name = None
        self._show_diff()

    def _all_done(self) -> None:
        self._current_idx = None
        self._copied = False
        self._sheet.deselect()
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

    def _copy_rungs(self, idx: int, step: PasteStep | None) -> bool:
        """Copy a program to the clipboard, or just the rungs of *step*.

        Returns whether the clipboard now holds them.
        """
        name = self._items[idx][0]
        program = self._programs.get(name)
        group = step.rungs if step is not None else None
        try:
            if program is None or program.rungs is None:
                raise ValueError(program.error if program else "it is not in this folder")
            rungs = list(program.rungs)
            if group is not None:
                rungs = [rungs[number - 1] for number in group if 1 <= number <= len(rungs)]
            if not rungs:
                raise ValueError("there are no rungs to copy")
            click_hwnd = self._get_click_hwnd()
            result = prepare_rungs_load(
                rungs,
                click_v4=is_click_v4(click_hwnd),
                mdb_path=self._get_mdb_path(),
                show_nicknames=self._show_nicks_var.get(),
                first_rung=group[0] if group else 1,
            )
            copy_to_clipboard(result.payload, owner_hwnd=click_hwnd)
        except RuntimeError as exc:
            self._status_var.set(f"Clipboard error: {exc}\nIs Click running?")
            return False
        except Exception as exc:
            self._status_var.set(f"Error loading {name}: {exc}")
            return False

        self._copied = True
        what = name if group is None else f"{format_group(group)} of {name}"
        rung_word = "rung" if result.rung_count == 1 else "rungs"
        msg = f"{what} copied to clipboard ({result.rung_count} {rung_word})"
        if result.addresses_inserted:
            msg += f"\nMDB: inserted {result.addresses_inserted} address(es)"
        elif result.mdb_error:
            msg += f"\nMDB: {result.mdb_error}"
        where = _where_to_paste(step) if step is not None else self._whole_placement(name)
        msg += f'\n{where}, then click "Next". To copy it again, click its row'
        self._status_var.set(msg)
        self._update_action_btn()
        if result.rung_count >= _SLOW_PASTE_RUNGS:
            messagebox.showinfo(
                "Large paste",
                f"{what} has {result.rung_count} rungs.\n\n"
                "Pasting this might take a while, and CLICK may freeze until it finishes.",
                parent=self,
            )
        return True

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
            self._copy_rungs(idx, self._current_step())

    def _step_prompt(self, idx: int) -> str:
        """Say what the current step of the row does."""
        name, _path, rung_count, _ = self._items[idx]
        if self._is_nickname_step(idx):
            return 'Click "Import" to import nicknames into the Click database'
        step = self._current_step()
        if step is not None:
            head = f"{name}, step {self._step_idx + 1} of {len(self._current_steps())}"
            label = format_group(step.rungs)
            if not step.rungs:
                old = _rungs_in_click(step.delete)
                legacy = self._legacy_line(name, step)
                steps = self._current_steps()
                # After a paste of fresh copies of old-encoded rungs, the rungs left to delete
                # are CLICK's old copies. The program still has those rungs.
                after_paste = (
                    bool(legacy)
                    and self._step_idx > 0
                    and steps[self._step_idx - 1].block == step.block
                )
                if after_paste:
                    what = (
                        "CLICK's old copy of this rung is"
                        if len(step.delete) == 1
                        else "CLICK's old copies of these rungs are"
                    )
                    what = f"{what} now below the pasted ones, at {old}"
                else:
                    verb = "is" if len(step.delete) == 1 else "are"
                    what = f"{old} {verb} not in the program any more"
                if len(step.delete) == 1:
                    action = 'Delete it in CLICK, then click "Next"'
                else:
                    action = (
                        'Select them in CLICK (Shift+Up/Down) and delete them, then click "Next"'
                    )
                return f"{head}: {what}.\n{action}{legacy}"
            if not step.placed:
                what = f"{label} was asked for by number"
            elif step.over is not None:
                what = f"{label} replaces rung {step.over}"
            else:
                what = f"{label} is new"
            prompt = f'{head}: {what}.\nClick "Copy {label}". {_where_to_paste(step)}'
            prompt += self._legacy_line(name, step)
            steps = len(self._current_steps())
            if self._step_idx == 0 and steps >= _MANY_STEPS:
                prompt += (
                    f'\nWith {steps} steps, switching Copy to "{_COPY_WHOLE}" may be quicker: '
                    "delete all its rungs in CLICK and paste once"
                )
            return prompt
        if self._matches_click(name):
            return (
                f"{name} already matches CLICK's last save.\n"
                'Click "Copy" to copy it to the clipboard anyway'
            )
        if self._can_add_subroutine(idx):
            where = (
                "is not in CLICK's last save" if self._click_compared else "may not be in CLICK yet"
            )
            return (
                f"{name} {where}.\n"
                'Click "New Subroutine" to create it in CLICK, or "Copy" if it already exists'
            )
        change = self._changes.get(name)
        if change is not None and change.before and name not in self._missing_in_click:
            prompt = (
                f"{name}: the whole program, {rung_count} rungs, replaces what CLICK has.\n"
                f'Click "Copy". {self._whole_placement(name)}'
            )
            if change.legacy:
                prompt += f"\n{_legacy_note(change)}"
            return prompt
        return f'Click "Copy" to copy {name} to the clipboard'

    def _follow_in_sheet(self, idx: int) -> None:
        """Move the sheet's own selection to the row and bring it into view.

        A cell the user clicked in that row stays the selected one.
        """
        selected = self._sheet.get_currently_selected()
        if not selected or selected.row != idx:
            self._sheet.select_cell(idx, COL_FILE, run_binding_func=False)
        self._sheet.see(idx, COL_FILE, keep_xscroll=True)

    def _select_row(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._items):
            return
        name = self._items[idx][0]
        if name in self._done:
            return
        if idx != self._current_idx or self._step_idx >= len(self._steps(name)):
            self._step_idx = 0
        self._current_idx = idx
        self._copied = False
        self._view_name = name
        self._follow_in_sheet(idx)
        self._update_highlights()
        self._update_action_btn()
        self._status_var.set(self._step_prompt(idx))
        self._show_diff()

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

    def _start(self, select: str | None = None, *, keep_done: bool = False) -> None:
        """Read the folder, compare it with CLICK, and begin at *select* or the first step.

        With *keep_done*, programs marked done stay done if the folder still
        holds the same rungs for them.
        """
        previous = self._programs
        self._scan_folder()
        if keep_done:
            self._done = {
                name
                for name in self._done
                if name in previous
                and name in self._programs
                and previous[name].rungs == self._programs[name].rungs
            }
        else:
            self._done.clear()
        self._current_idx = None
        self._copied = False
        self._step_idx = 0
        self._compare_with_click()
        self._populate_sheet()
        wanted = None if select is None else select.casefold()
        for idx, (name, *_) in enumerate(self._items):
            if name.casefold() == wanted:
                self._select_row(idx)
                return
        self._advance_to_first_pending()

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
            self._step_idx = 0
        elif program.building and self._changes:
            # CLICK saved: keep the rows until the new CSVs are ready.
            self._saved_program = program
            self._compare_lbl.configure(text=program.note)
            return

        old_steps = self._current_steps()
        # Something was known to be left to do; an unread program is not that
        was_pending = self._click_compared and not self._settled()
        self._compare_with_click()
        if was_pending and self._settled() and not new_project:
            # CLICK saved the last of it: nothing is left for this window to do.
            if self._on_pasted is not None:
                self._on_pasted()
            self.destroy()
            return
        self._populate_sheet()
        steps = self._current_steps()
        if steps and steps != old_steps:
            # CLICK took some of the row's rungs: step through what is left.
            self._step_idx = 0
            self._copied = False
        if self._copied:
            return  # Mid-paste: the row stays current until "Next"
        idx = self._current_idx
        if idx is None or not self._needs_paste(self._items[idx][0]):
            self._advance_to_first_pending()
        elif steps != old_steps:
            self._select_row(idx)

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
            if name in self._only_in_click or name in self._done:
                # Not a step, but its difference can still be read
                self._view_name = name
                self._show_diff()
            else:
                self._select_row(row)

    def _on_action(self) -> None:
        """Handle the main action button (Copy/Import or Next)."""
        idx = self._current_idx
        if idx is None:
            return
        if not self._copied and not self._nothing_to_copy(self._current_step()):
            # "Copy" or "Import" — perform the action
            self._perform_action(idx)
        elif self._step_idx + 1 < len(self._current_steps()):
            # "Next" — the row's next step
            self._step_idx += 1
            self._copied = False
            self._update_action_btn()
            self._status_var.set(self._step_prompt(idx))
            self._scroll_to_step()
        else:
            # "Next" — mark done and advance
            self._done.add(self._items[idx][0])
            self._advance_to_next()

    def _on_copy_mode(self) -> None:
        """Handle the Copy switch: remember it, and start the current row's step over."""
        _save_copy_whole(self._copy_whole_var.get())
        idx = self._current_idx
        if idx is not None:
            self._step_idx = 0
            self._select_row(idx)

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
        self._action_btn.configure(state="normal")
        self._start()

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
            text=f"Guided Paste — {self._folder.name}/",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT)
        self._progress_lbl = ttk.Label(header, text="")
        self._progress_lbl.pack(side=tk.RIGHT)

        # --- options row ---
        opts = self._opts = ttk.Frame(main)
        opts.pack(fill=tk.X, pady=(0, 5))

        # Shown under the options row only while there is something to say (_update_notice)
        self._notice_lbl = tk.Label(
            main, background="#fff3cd", foreground="#664d03", justify=tk.LEFT, anchor="w"
        )
        self._notice_lbl.configure(padx=8, pady=5)
        self._notice_lbl.bind(
            "<Configure>",
            lambda event: self._notice_lbl.configure(wraplength=max(event.width - 16, 200)),
        )

        self._nick_lbl = ttk.Label(opts, text="", foreground="gray")
        self._nick_lbl.pack(side=tk.LEFT)
        self._compare_lbl = ttk.Label(opts, text="", foreground="gray")
        self._compare_lbl.pack(side=tk.LEFT, padx=(10, 0))

        self._show_nicks_var = tk.BooleanVar(value=True)
        # The Copy switch: off steps through the rungs that differ, on copies whole
        # programs. It opens as the user last left it.
        self._copy_whole_var = tk.BooleanVar(value=_read_copy_whole())
        ttk.Checkbutton(
            opts,
            text="Show nicknames in math instructions",
            variable=self._show_nicks_var,
        ).pack(side=tk.RIGHT)

        # Buttons and status are packed against the bottom *before* the panes:
        # the sheet and the diff ask for more height than the window has, and
        # pack starves whatever is packed last. Bottom-up order.
        btn_frame = ttk.Frame(main)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_var = tk.StringVar(value="Loading…")
        status_frame = ttk.LabelFrame(main, text="Instructions", padding=5)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 5))
        ttk.Label(
            status_frame,
            textvariable=self._status_var,
            wraplength=660,
            foreground="gray",
        ).pack(fill=tk.X)

        panes = ttk.PanedWindow(main, orient=tk.VERTICAL)
        panes.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # --- tksheet ---
        sheet_frame = tk.Frame(panes, relief=tk.SUNKEN, borderwidth=2)
        panes.add(sheet_frame, weight=1)

        self._sheet = Sheet(
            sheet_frame,
            headers=["", "File", "Rungs", "vs CLICK", "Description"],
            show_row_index=False,
            height=140,
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

        # --- rung diff of the selected row ---
        diff_frame = tk.Frame(panes, relief=tk.SUNKEN, borderwidth=2)
        panes.add(diff_frame, weight=3)

        self._text = tk.Text(
            diff_frame,
            font=("Consolas", 10),
            wrap=tk.NONE,
            height=10,
            state=tk.DISABLED,
            background="#ffffff",
            foreground=_DIFF_TEXT,
        )
        scrollbar_y = ttk.Scrollbar(diff_frame, orient=tk.VERTICAL, command=self._text.yview)
        scrollbar_x = ttk.Scrollbar(diff_frame, orient=tk.HORIZONTAL, command=self._text.xview)
        self._text.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # GitHub Desktop's light diff colours. Tags configured later draw on top,
        # so the gutter and word tags come after the line tags.
        self._text.tag_configure("added", background="#e6ffed")
        self._text.tag_configure("removed", background="#ffeef0")
        self._text.tag_configure("added_gutter", background="#cdffd8")
        self._text.tag_configure("removed_gutter", background="#ffdce0")
        self._text.tag_configure("added_word", background="#acf2bd")
        self._text.tag_configure("removed_word", background="#fdb8c0")
        self._text.tag_configure("separator", background="#f1f8ff", foreground=_DIFF_MUTED)
        self._text.tag_configure("expander", background="#dbedff", foreground="#0366d6")
        self._text.tag_bind("expander", "<Button-1>", self._on_expand)
        self._text.tag_bind("expander", "<Enter>", lambda _e: self._text.configure(cursor="hand2"))
        self._text.tag_bind("expander", "<Leave>", lambda _e: self._text.configure(cursor="xterm"))
        self._text.tag_configure(
            "file_header", foreground=_DIFF_MUTED, font=("Consolas", 10, "bold")
        )
        self._text.tag_configure("note", foreground=_DIFF_MUTED, font=("TkDefaultFont", 9))

        # --- buttons (frame packed above, before the panes) ---
        ttk.Button(btn_frame, text="⟳ Restart", command=self._on_restart, width=10).pack(
            side=tk.LEFT
        )

        # What a step copies for a program CLICK already has (_steps)
        ttk.Label(btn_frame, text="Copy:").pack(side=tk.LEFT, padx=(15, 0))
        for label, whole in ((_COPY_CHANGED, False), (_COPY_WHOLE, True)):
            ttk.Radiobutton(
                btn_frame,
                text=label,
                variable=self._copy_whole_var,
                value=whole,
                command=self._on_copy_mode,
            ).pack(side=tk.LEFT, padx=(5, 0))

        self._action_btn = ttk.Button(
            btn_frame, text="Copy", command=self._on_action, width=14, state="disabled"
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
        source_dir: Path | None = None,
        select: tuple[str, list[int] | None] | None = None,
        on_pasted: Callable[[], None] | None = None,
    ):
        """Open on *folder*.

        *source_dir* is the workspace ``src/plc`` the folder was just exported
        from: the diff then shows that source as written, and nicknames are left
        to the Address Editor. *select* starts on one program, optionally with
        the rungs of it to paste instead of the ones that differ. *on_pasted* is
        called when a CLICK save holds everything and the window closes itself.
        """
        super().__init__(parent)
        self.title(f"Guided Paste — {folder.name}")
        self.geometry("900x720")
        self.minsize(660, 480)

        self._folder = folder
        self._source_dir = source_dir
        self._get_mdb_path = get_mdb_path
        self._get_click_hwnd = get_click_hwnd
        # The program now in CLICK as CSVs: the generated workspace's csv/ folder
        self._get_saved_program = get_saved_program
        self._on_pasted = on_pasted

        # The folder's ladder CSVs as read, by name, and the time they were read
        self._programs: dict[str, ProposedProgram] = {}
        self._read_at = ""
        # (display_name, path, rung_count, description)
        self._folder_items: list[tuple[str, Path, int, str]] = []
        # The sheet rows: the folder's items, then programs only in CLICK
        self._items: list[tuple[str, Path, int, str]] = []
        self._done: set[str] = set()
        self._current_idx: int | None = None
        self._copied: bool = False
        # Which of the current row's runs of rungs is being pasted
        self._step_idx = 0
        # Program name -> the rungs asked for, in place of the ones that differ
        self._selection: dict[str, list[int]] = {}
        self._nickname_path: Path | None = None
        # name -> how it differs from CLICK; absent when unknown (no workspace, unreadable)
        self._changes: dict[str, ProgramChange] = {}
        # Programs CLICK has that the folder lacks, as all rungs removed
        self._only_in_click: dict[str, ProgramChange] = {}
        # Folder items CLICK's last save lacks: subroutines to create first
        self._missing_in_click: frozenset[str] = frozenset()
        self._click_compared = False
        self._adding_subroutine = False
        self._compare_note = ""
        # The row whose difference the pane shows: the current step, or a row clicked to read
        self._view_name: str | None = None
        self._shown_diff = RenderedDiff()
        self._diff_first_line = 1
        # Unchanged rungs shown behind each separator (render_diff's *shown*), for the
        # difference the pane shows
        self._expanded: dict[int, tuple[int, int]] = {}
        self._expanded_change: ProgramChange | None = None
        # pyrung source of CLICK's program and the folder's, generated when first shown
        self._before_sources: BundleSources | None = None
        self._after_sources: BundleSources | None = None
        self._saved_program = SavedProgram()

        self._create_widgets()
        self.reload(source_dir=source_dir, select=select)
        # The session of the project being pasted into; survives a brief disconnect
        self._project_session = self._saved_program.session
        self.after(_WATCH_INTERVAL_MS, self._watch_saved_program)
        self.after_idle(self._show_first_time_tips)

    def reload(
        self,
        *,
        source_dir: Path | None = None,
        select: tuple[str, list[int] | None] | None = None,
    ) -> None:
        """Read the folder again: it was exported or opened again.

        *source_dir* and *select* are as for the constructor. Programs already
        marked done stay done unless their rungs changed.
        """
        self._source_dir = source_dir
        self._selection = {select[0]: select[1]} if select and select[1] else {}
        if self._selection:
            # Rungs were asked for by number. This is not the user's choice, so it is not saved.
            self._copy_whole_var.set(False)
        self._start(select[0] if select else None, keep_done=True)

    @property
    def shows_workspace_proposal(self) -> bool:
        """Whether the folder is the export of the workspace's own source."""
        return self._source_dir is not None

    def show(self) -> None:
        """Bring the window to the front; a new Toplevel may not be mapped yet."""
        self.deiconify()
        self.lift()
        self.focus_force()
