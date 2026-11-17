"""Review Changes window: walk a folder of ladder CSVs into CLICK and show the rung diff.

This is the one window for getting ladder into CLICK. The Ladder menu opens it on any
folder of CSVs. The Workspace's Review Changes button (``clicknick-cli rung apply``)
opens it on the workspace's ``csv_output/``. Each row is a program. The pane below
shows how the selected program differs from CLICK's last save. The step copies either
the whole program or just the rungs that differ.

You can take or skip each difference. CLICK keeps a skipped difference as it is. The
choices, and how far each program's steps have got, belong to the program, so you can
look at rows and differences in any order.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from laddercodec import Rung
from tksheet import Sheet

from ..connection_session import SavedProgram
from ..data.address_store import AddressStore
from ..data.data_source import CsvDataSource
from ..ladder.clipboard import copy_to_clipboard, is_click_v4
from ..ladder.program import (
    LegacyEncoding,
    describe_legacy_encoding,
    prepare_rungs_load,
)
from ..models.address_row import AddressRow
from ..services.nickname_staging import NicknamePlan, plan_nicknames, stage_nicknames
from ..services.rung_diff import (
    WORKSPACE_SOURCE,
    BundleComparison,
    BundleSources,
    DifferenceKey,
    Opcode,
    PasteStep,
    ProgramChange,
    ProposedProgram,
    RenderedDiff,
    carry_skipped,
    compare_bundle,
    format_group,
    load_bundle,
    paste_groups,
    render_diff,
)
from ..utils.win32_utils import WIN32
from ..widgets.tooltip import bind_tooltip

# Column layout
COL_STATUS = 0
COL_FILE = 1
COL_RUNGS = 2
COL_CLICK = 3
COL_DESC = 4
_NUM_COLS = 5

# A paste of this many rungs or more can leave CLICK's editor frozen for a long time.
_SLOW_PASTE_RUNGS = 100

# When a program that CLICK has needs this many steps or more, clearing it and pasting it
# whole is likely less work. ClickNick then copies it whole, unless that paste would be slow
# (_SLOW_PASTE_RUNGS). See _copied_whole_for_steps.
_MANY_STEPS = 6

# Icons
_ICON_DONE = "✓"
_ICON_CURRENT = "▶"
_ICON_PENDING = "○"
# A program whose difference has not been shown yet
_ICON_UNREVIEWED = "●"
# Every difference of the program is skipped, so CLICK keeps what it has
_ICON_SKIPPED = "–"

_ICON_MATCHES = "="
_ICON_ONLY_IN_CLICK = "!"

# "vs CLICK" column
_CLICK_NEW = "New"
_CLICK_MATCHES = "Up to date"
# CLICK holds pastes of the program that ClickNick cannot match to this comparison
# (_unplaced)
_CLICK_UNSAVED = "Pasted, not saved"
_CLICK_ONLY = "Only in CLICK"
_DESC_ONLY_IN_CLICK = "Not in this folder: delete it in CLICK, or keep it"
_DELETE_IN_CLICK = "Delete it in CLICK"

# Row colours
_BG_DONE = "#d4edda"
_BG_CURRENT = "#cce5ff"
_FG_MATCHES = "gray"
_FG_ONLY_IN_CLICK = "#a94442"
# CLICK holds some of the program's rungs in a legacy encoding, or ClickNick cannot read them
_BG_LEGACY = "#f8d7da"
_FG_LEGACY = "#842029"
# A note lists this many of a program's legacy-encoded rungs and counts the rest
_LEGACY_LISTED = 5
# The "vs CLICK" column's word for a legacy encoding (False) and for a rung it cannot read (True)
_LEGACY_LABELS = {False: "old encoding", True: "unreadable"}

# Colours of the diff pane's text, from GitHub Desktop's light theme. _create_widgets
# configures the colours of the diff's tags.
_DIFF_TEXT = "#24292e"
_DIFF_MUTED = "#586069"
_MARGIN = 5  # Pixels left of the +/- gutter, where the current difference's bar goes
_DIFF_LINE_TAGS = {"+": "added", "-": "removed"}

# The Copy switch chooses what a step copies for a program that CLICK already has
_COPY_CHANGED = "Changed rungs"
_COPY_WHOLE = "Whole program"
# The button that steps through a program that is copied whole because it has many steps
_STEP_THROUGH = "Step Through"

# A folder's nicknames.csv gets its own row. ClickNick stages the nicknames in the Address
# Editor, and the user Syncs them from there.
_NICKNAMES_NAME = "nicknames.csv"
_DESC_NICKNAMES = "Nicknames, staged in the Address Editor for you to Sync"
_STAGE = "Stage nicknames"
_OPEN_EDITOR = "Open Address Editor"
# The pane lists this many of the nickname changes and counts the rest
_NICKNAMES_LISTED = 200

# How often to check whether the program in CLICK has changed
_WATCH_INTERVAL_MS = 1000

_FIRST_TIME_TIPS = (
    "Review Changes\n\n"
    "Each step copies rungs to the clipboard. If CLICK does not have the program yet, the "
    "step copies the whole program. If CLICK has it, the Copy buttons at the bottom choose "
    "between Changed rungs and Whole program. The pane "
    "under the list shows the difference. Work down each program in order. A step's rung "
    "numbers are the ones CLICK shows once the steps before it are done. "
    "Paste into CLICK with Ctrl+V. Then wait until the rungs appear before you do anything "
    "else. A big paste can take a while, and CLICK may look frozen until it finishes.\n\n"
    "To leave a difference out, untick Take this difference above the pane, or click its "
    "+/- gutter. CLICK keeps what it has there. Alt+Down and Alt+Up (or F7 and Shift+F7) "
    "go through every difference, program by program.\n\n"
    "Subroutines come before main. Create each subroutine in CLICK before you paste into "
    "it. The New Subroutine button does this for you."
)


def _tips_seen_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "ClickNick" / "guided_paste_popup_seen"


def _preferences_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "ClickNick" / "guided-paste.json"


def _read_copy_whole() -> bool:
    """Return True if the user chose to copy whole programs. The default is changed rungs."""
    try:
        payload = json.loads(_preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("copy_whole_program") is True


def _save_copy_whole(whole: bool) -> None:
    """Remember the user's Copy switch choice for the next Review Changes window."""
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

    CLICK pastes over the selected rung. The first pasted rung replaces it, and the
    rest go in below it.
    """
    if step.over is not None:
        return f"In CLICK, select rung {step.over} and paste over it (Ctrl+V)"
    where = "after the last rung" if step.above is None else f"above rung {step.above}"
    return f"In CLICK, insert an empty rung {where} and paste over it (Ctrl+V)"


def _fault(found: Sequence[LegacyEncoding]) -> str:
    """Return what is wrong with CLICK's copy, as a phrase that follows "CLICK's copy"."""
    if all(item.unreadable for item in found):
        return "cannot be read"
    if any(item.unreadable for item in found):
        return "cannot be read or has an old encoding"
    return "has an old encoding"


def _finding(item: LegacyEncoding) -> str:
    """Return the finding as ``Math H70000: it is stored as ...``.

    If the item names no instruction and no token, return its detail alone.
    """
    what = " ".join(part for part in (item.instruction, item.token) if part)
    return f"{what}: {item.detail}" if what else item.detail


def _listed_rungs(rungs: Sequence[int]) -> str:
    """Return rung numbers as ``2, 5 to 7``, with each run of consecutive rungs shortened."""
    return ", ".join(
        str(run[0]) if len(run) == 1 else f"{run[0]} to {run[-1]}" for run in paste_groups(rungs)
    )


def _legacy_note(change: ProgramChange, *, instead: str = "") -> str:
    """Say which of CLICK's rungs hold a legacy encoding or cannot be read, and what to do.

    ClickNick does not paste a program that exists only in CLICK. Its note uses
    *instead*, which says what happens to the program, in place of the advice to paste
    again.
    """
    if not change.legacy:
        return ""
    fault = _fault(change.legacy)
    rungs = sorted({item.rung for item in change.legacy if item.rung is not None})
    if not rungs or any(item.rung is None for item in change.legacy):
        head, again = f"CLICK's copy {fault}.", "Paste the whole program again."
    elif len(rungs) == 1:
        head, again = f"CLICK's copy of rung {rungs[0]} {fault}.", "Paste it again."
    else:
        head, again = f"CLICK's copy of rungs {_listed_rungs(rungs)} {fault}.", "Paste them again."
    if change.unreadable:
        again = "Paste the whole program again."
    if instead:
        again = instead
    lines = [
        f"  {describe_legacy_encoding(item, program=False)}"
        for item in change.legacy[:_LEGACY_LISTED]
    ]
    if len(change.legacy) > _LEGACY_LISTED:
        lines.append(f"  ...and {len(change.legacy) - _LEGACY_LISTED} more")
    return "\n".join([f"{head} {again}", *lines])


def _empty_refusal(name: str, change: ProgramChange) -> str:
    """Return why the program may not be copied yet, or an empty string.

    ClickNick pastes a program whole when it cannot read all of CLICK's copy. An empty
    rung in the folder may stand in for one of CLICK's rungs. The whole paste would then
    leave that rung empty in CLICK.
    """
    empty = change.empty_rungs
    if not change.unreadable or not empty:
        return ""
    program = next((item.program for item in change.legacy if item.program), Path(name).stem)
    if len(empty) == 1:
        head = f"Rung {empty[0]} of {program} is empty in this folder."
    else:
        head = f"Rungs {_listed_rungs(empty)} of {program} are empty in this folder."
    unread = sorted({item.rung for item in change.legacy if item.unreadable and item.rung})
    if not unread:
        what = "ClickNick cannot read CLICK's copy of the program."
    elif len(unread) == 1:
        what = f"CLICK's rung {unread[0]} cannot be read."
    else:
        what = f"CLICK's rungs {_listed_rungs(unread)} cannot be read."
    rung = "those rungs" if len(empty) > 1 else "that rung"
    return f"{head} {what} Paste {rung} from your own copy of the program first."


def _change_label(change: ProgramChange) -> str:
    """Return the "vs CLICK" label for a program that CLICK already has.

    The label counts the changed and removed rungs. It also says if some of CLICK's rungs
    have an old encoding or cannot be read.
    """
    changed, removed = len(change.changed), len(change.removed)
    if changed and removed:
        label = f"{changed} changed, {removed} removed"
    else:
        count, verb = (changed, "changed") if changed else (removed, "removed")
        label = f"{count} rung{'s' if count != 1 else ''} {verb}"
    if not change.legacy:
        return label
    kinds = {item.unreadable for item in change.legacy}
    return f"{label}, {', '.join(_LEGACY_LABELS[kind] for kind in sorted(kinds))}"


def _differences_of(change: ProgramChange) -> list[Opcode]:
    """Return the program's differences, in ``ProgramChange.differences`` order."""
    return [opcode for opcode in change.opcodes if opcode[0] != "equal"]


def _what_skipping_keeps(opcode: Opcode) -> str:
    """Say what a skipped difference leaves in CLICK."""
    _tag, i1, i2, _j1, _j2 = opcode
    if i1 == i2:
        return "Skipped: the new rungs are not added"
    return f"Skipped: CLICK keeps its {_rungs_in_click(range(i1 + 1, i2 + 1))}"


# CLICK's Ctrl+U dialog, and its subroutine name box
_NEW_SUB_TITLE = "New Subroutine Program"
_NEW_SUB_NAME_CONTROL = "Edit1"
_SUBROUTINE_PREFIX = "subroutines/"
# Time for CLICK to come to the front before Ctrl+U, then to open the dialog
_ACTIVATE_DELAY_MS = 100
_DIALOG_POLL_MS = 100
_DIALOG_TIMEOUT_MS = 3000


@dataclass(frozen=True)
class ProposalSource:
    """Where a window's proposal comes from, which decides what starts out taken.

    The workspace's own edits and a folder opened to load into CLICK are meant to
    replace what CLICK has. For them, every difference starts out taken. So do the
    folder's nicknames and the deletion of programs that CLICK has and the proposal
    lacks. A copy of another PLC is compared to bring some of it over. For it, the
    nicknames and those deletions start out skipped. Differences always start out taken.
    """

    label: str  # Shown as "from <label>" in the title, and in the diff's +++ header
    takes_nicknames: bool = True
    deletes_only_in_click: bool = True

    @classmethod
    def of(cls, folder: Path, source_dir: Path | None) -> ProposalSource:
        """Return the source for the workspace's export if *source_dir* is given.

        Otherwise return the source for a folder that the user opened.
        """
        return cls(WORKSPACE_SOURCE if source_dir is not None else folder.name)

    @classmethod
    def other_click(cls, project: str) -> ProposalSource:
        """Return the source for what another CLICK window with *project* open last saved.

        That is a copy of another PLC.
        """
        return cls(project, takes_nicknames=False, deletes_only_in_click=False)

    @property
    def title(self) -> str:
        return f"Review Changes — from {self.label}"


class ReviewChangesWindow(tk.Toplevel):
    """A non-modal panel that walks the user through pasting ladder CSVs."""

    # ------------------------------------------------------------------
    # The folder's nicknames
    # ------------------------------------------------------------------

    def _refresh_nicknames(self) -> bool:
        """Compare the folder's nicknames with the Address Editor's data.

        Return True if the comparisons changed. It makes two comparisons: one with the
        rows as edited (what is left to stage) and one with CLICK's database (what it
        still lacks). It stores None in place of both while there is no readable
        nicknames.csv, or no data to stage the nicknames in.
        """
        store = self._get_project_store()
        rows = self._nickname_rows
        plans = (
            None
            if store is None or rows is None
            else (
                plan_nicknames(rows, store.visible_state, fields=self._nickname_fields),
                plan_nicknames(rows, store.base_state, fields=self._nickname_fields),
            )
        )
        changed = plans != self._nickname_plans
        self._nickname_plans = plans
        return changed

    # ------------------------------------------------------------------
    # Folder scanning
    # ------------------------------------------------------------------

    def _scan_folder(self) -> None:
        """Read the folder's CSVs. The window compares and copies the programs as read here.

        Later changes to the files do not reach the window until the next read.

        If the folder has since been emptied, keep what was read. A CLICK save
        regenerates the workspace and removes its ``csv_output/``.
        """
        programs = load_bundle(self._folder)
        if not programs and self._programs:
            return
        self._programs = {program.name: program for program in programs}
        self._read_at = datetime.now().strftime("%H:%M")
        self._folder_items = []
        # A workspace's tags reach CLICK through the Address Editor (tag apply),
        # so only a plain folder gets the nicknames row.
        nicks = self._folder / _NICKNAMES_NAME
        self._nickname_path = nicks if self._source_dir is None and nicks.exists() else None
        self._nickname_rows, self._nickname_error = None, ""
        self._nickname_fields = frozenset()
        if self._nickname_path is not None:
            source = CsvDataSource(str(nicks))
            try:
                self._nickname_rows = source.load_all_addresses()
                self._nickname_fields = source.fields
            except (OSError, ValueError) as exc:
                self._nickname_error = str(exc) or type(exc).__name__
            self._folder_items.append((_NICKNAMES_NAME, nicks, 0, _DESC_NICKNAMES))
        self._refresh_nicknames()
        self._folder_items.extend(
            (program.name, program.path, program.rung_count, program.description)
            for program in programs
        )
        self._after_sources = (
            None
            if self._source_dir is None
            else BundleSources.workspace(self._source_dir, self._folder)
        )

    def _skipped_of(self, name: str) -> frozenset[DifferenceKey]:
        return self._skipped.get(name, frozenset())

    def _carry_pasted(
        self,
        name: str,
        basis: ProgramChange,
        old_skipped: frozenset[DifferenceKey],
        change: ProgramChange,
    ) -> None:
        """Carry what was pasted of the program into a new comparison against the same save.

        The folder has been read again, for example after another export, and CLICK has
        not saved since the pastes. CLICK still holds the pasted rungs. ClickNick matches
        them to the new comparison only if three things hold. The new comparison has the
        same differences pasted. Those differences leave the same rungs in CLICK. A step
        that was begun is still the next step, in the same place. Otherwise ClickNick cannot
        number the program's steps from what CLICK holds. It adds the program to _unplaced
        and copies the program whole until CLICK saves.
        """
        pasted = self._pasted.pop(name, frozenset())
        partial = self._partial.pop(name, 0)
        if not pasted and not partial:
            return
        carried = pasted & frozenset(change.differences)
        held = basis.merged(frozenset(basis.differences) - pasted)
        placed = not change.unreadable and held == change.merged(
            frozenset(change.differences) - carried
        )
        if placed and partial:
            begun = basis.steps(old_skipped, pasted)[: partial + 1]
            now = change.steps(self._skipped_of(name), carried)[: partial + 1]
            placed = (
                len(now) == len(begun)
                and change.differences[now[0].block] == basis.differences[begun[0].block]
                and [(step.over, step.above, step.delete) for step in now]
                == [(step.over, step.above, step.delete) for step in begun]
            )
        if not placed:
            self._unplaced.add(name)
            return
        if carried:
            self._pasted[name] = carried
        if partial:
            self._partial[name] = partial

    # ------------------------------------------------------------------
    # Taking and skipping differences
    # ------------------------------------------------------------------

    def _choosable(self, name: str | None) -> ProgramChange | None:
        """Return the folder program's change if it has differences to take or skip.

        Return None for a program that ClickNick cannot read all of in CLICK. ClickNick
        pastes that program whole. A skip would keep the empty rung that ClickNick reads in
        place of the CLICK rung that it cannot read.
        """
        if name is None or name in self._only_in_click:
            return None
        change = self._changes.get(name)
        if change is None or change.unreadable or not change.differences:
            return None
        return change

    def _kept(self, name: str) -> bool:
        """Return whether a program only in CLICK is kept there rather than deleted."""
        return (name in self._flipped_in_click) == self._source.deletes_only_in_click

    def _all_skipped(self, name: str) -> bool:
        """Return whether every difference of the program is skipped, so nothing is pasted.

        Return False for a program when CLICK holds pastes of it that the comparison
        cannot place (_unplaced). ClickNick pastes that program whole, skips and all,
        until CLICK saves.
        """
        if name == _NICKNAMES_NAME:
            return self._nicknames_skipped
        if name in self._only_in_click:
            return self._kept(name)
        if name in self._unplaced:
            return False
        change = self._choosable(name)
        return change is not None and set(change.differences) <= self._skipped_of(name)

    def _still_to_do(self, name: str) -> bool:
        """Return whether CLICK's last save shows the program still to paste or to delete.

        Return False for a program that ClickNick cannot read all of in CLICK. It
        differs after every paste, so ClickNick cannot tell whether the paste landed.
        """
        if name in self._only_in_click:
            return not self._kept(name)
        change = self._changes.get(name)
        return (
            change is not None
            and change.differs
            and not change.unreadable
            and not self._all_skipped(name)
        )

    def _carry_choices(self) -> None:
        """Carry each program's choices and progress over to the new comparison.

        A program that is not in the new comparison keeps them for when it returns.
        Skips follow the differences they were made on. What was pasted stays in CLICK
        until CLICK saves (_note_saves). Until then, the pastes are placed in each new
        comparison (_carry_pasted). The first comparison after a save shows what is
        left. A program marked done that this comparison shows still to do is no longer
        done.
        """
        for name, basis in list(self._basis.items()):
            change = self._changes.get(name)
            if change is None:
                continue
            old_skipped = self._skipped_of(name)
            self._skipped[name] = carry_skipped(old_skipped, basis, change)
            if change != basis:
                self._carry_pasted(name, basis, old_skipped, change)
            self._basis[name] = change
        if self._click_compared and self._done_unchecked:
            self._done_unchecked = False
            # CLICK may not have the work: it was not pasted, was pasted into the wrong
            # program, or was deleted and then undone.
            self._done = {name for name in self._done if not self._still_to_do(name)}
        for name, rungs in list(self._selection.items()):
            change = self._changes.get(name)
            if change is None:
                continue  # Applied once there is a comparison to pick from
            del self._selection[name]
            # Paste the rungs that were asked for, not the whole program
            self._step_through.add(name)
            if name not in self._missing_in_click:
                self._skipped[name] = frozenset(change.differences) - change.blocks_holding(rungs)
                self._basis[name] = change

    def _note_saves(self, program: SavedProgram) -> None:
        """Forget what was pasted once CLICK saves, and recheck the programs marked done.

        The recheck happens at the next comparison. Only a change in CLICK's save_count
        counts as a save. The workspace is also rebuilt after a Sync or a Reload, but that
        build may fail while CLICK still holds the pastes. Ignore *program* if it has no
        session, because then nothing is connected.
        """
        if program.session is None:
            return
        if self._save_count is not None and program.save_count != self._save_count:
            self._pasted.clear()
            self._partial.clear()
            self._unplaced.clear()
            self._done_unchecked = True
        self._save_count = program.save_count

    def _compare_with_click(self) -> None:
        """Compare the folder with the program now in CLICK and rebuild the rows.

        Programs that CLICK has and the folder lacks are listed after the folder's own
        items. Pasting cannot remove them. The user deletes each one in CLICK, or keeps it.
        """
        program = self._saved_program = self._get_saved_program()
        self._note_saves(program)
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
        self._carry_choices()
        self._items = [
            *self._folder_items,
            *(
                (name, Path(name), len(change.before), _DESC_ONLY_IN_CLICK)
                for name, change in comparison.only_in_click.items()
            ),
        ]

    def _unsaved_pastes(self) -> bool:
        """Return whether CLICK holds rungs pasted from this window that it has not saved."""
        return any(self._pasted.values()) or any(self._partial.values()) or bool(self._unplaced)

    def _forget_progress(self) -> None:
        self._pasted.clear()
        self._partial.clear()
        self._unplaced.clear()
        self._basis = {name: self._basis[name] for name in self._skipped if name in self._basis}

    def _forget_choices(self) -> None:
        self._skipped.clear()
        self._step_through.clear()
        self._flipped_in_click.clear()
        self._nicknames_skipped = not self._source.takes_nicknames
        self._forget_progress()

    def _can_add_subroutine(self, idx: int | None) -> bool:
        """Return whether the row is a subroutine that CLICK may not have yet.

        Only a comparison that shows CLICK's last save having the subroutine rules this
        out. If the project is unsaved, or ClickNick could not read CLICK's program, the
        subroutine may be missing.
        """
        if idx is None or idx >= len(self._items):
            return False
        name = self._items[idx][0]
        if not name.startswith(_SUBROUTINE_PREFIX) or name in self._unplaced:
            return False  # CLICK holds pastes into it, so it exists
        return name in self._missing_in_click or not self._click_compared

    def _is_nickname_step(self, idx: int | None) -> bool:
        return idx is not None and idx < len(self._items) and self._items[idx][0] == _NICKNAMES_NAME

    def _nicknames_in_click(self) -> bool:
        """Return whether CLICK's database holds every nickname that the folder sets."""
        return self._nickname_plans is not None and not self._nickname_plans[1]

    def _nicknames_staged(self) -> bool:
        """Return whether the folder's nicknames are all staged and some are not synced yet."""
        plans = self._nickname_plans
        return plans is not None and not plans[0] and bool(plans[1])

    def _nicknames_label(self) -> str:
        """Return the text for the nicknames row's "vs CLICK" column."""
        plans = self._nickname_plans
        if self._nickname_rows is None:
            label = "unreadable"
        elif plans is None:
            label = "needs CLICK's database"
        elif not plans[1]:
            return _CLICK_MATCHES
        elif plans[0]:
            label = plans[0].summary()
        else:
            label = f"{plans[1].summary()}, staged"
        return f"{label}, skipped" if self._nicknames_skipped else label

    def _describe_nicknames(self) -> str:
        """Return the pane's note for the nicknames row, with one line per field it changes."""
        plans = self._nickname_plans
        if self._nickname_rows is None:
            return f"{_NICKNAMES_NAME} could not be read: {self._nickname_error}"
        if plans is None:
            return (
                f"{_NICKNAMES_NAME} is staged in the Address Editor as edits to CLICK's "
                "database. Connect to the CLICK project to see what it changes."
            )
        to_stage, unsynced = plans
        if not unsynced:
            return f"CLICK's database has every nickname in {_NICKNAMES_NAME}."
        if to_stage:
            head = f"{_NICKNAMES_NAME} changes {to_stage.summary()} in the Address Editor:"
            plan = to_stage
        else:
            head = f"Staged in the Address Editor, not synced yet: {unsynced.summary()}"
            plan = unsynced
        return "\n".join([head, *plan.describe(_NICKNAMES_LISTED)])

    def _nicknames_prompt(self) -> str:
        """Return what the user should do on the nicknames row."""
        plans = self._nickname_plans
        if self._nickname_rows is None:
            return (
                f"{_NICKNAMES_NAME} could not be read: {self._nickname_error}\n"
                "Untick Take these nicknames to go on without them"
            )
        if plans is None:
            return (
                "The nicknames are staged as edits to CLICK's database. Connect to the "
                "CLICK project, or untick Take these nicknames to go on without them"
            )
        if self._nicknames_staged():
            return (
                f"The nicknames are staged ({plans[1].summary()}). Check them in the Address "
                'Editor under Changed and click "Sync and Close" there, then "Next" here'
            )
        return (
            f'{_NICKNAMES_NAME} sets {plans[0].summary()}. Click "{_STAGE}" to stage them in '
            'the Address Editor, then "Sync and Close" there.\n'
            "Sync before pasting, so the pasted rungs show the names"
        )

    def _has_legacy(self, name: str) -> bool:
        """Return whether some of CLICK's rungs of the program are legacy or unreadable."""
        change = self._changes.get(name)
        return change is not None and bool(change.legacy)

    def _legacy_in_step(self, name: str, step: PasteStep) -> list[LegacyEncoding]:
        """Return CLICK's rungs in a legacy encoding that *step* pastes over or deletes."""
        change = self._changes.get(name)
        if change is None or not change.legacy:
            return []
        differences = _differences_of(change)
        if step.block >= len(differences):
            return []
        tag, i1, i2, _j1, _j2 = differences[step.block]
        if step.rungs:
            # A paste replaces CLICK's first rung of the difference, if there is one
            numbers = range(i1 + 1, i1 + 2) if step.over is not None else range(0)
        else:
            # A delete removes the rungs that the paste before it did not replace
            numbers = range(i1 + 2 if tag == "replace" else i1 + 1, i2 + 1)
        return [item for item in change.legacy if item.rung is None or item.rung in numbers]

    def _legacy_line(self, name: str, step: PasteStep) -> str:
        """Return a note if the step's rungs in CLICK have an old encoding or cannot be read."""
        stale = self._legacy_in_step(name, step)
        if not stale:
            return ""
        found = " ".join(dict.fromkeys(_finding(item) for item in stale))
        line = f"\nCLICK's copy {_fault(stale)}. {found}"
        if not step.rungs:
            return line
        again = "it" if len({item.rung for item in stale}) == 1 else "them"
        return f"{line} Paste {again} again."

    def _left_out(self, name: str) -> bool:
        """Return whether the folder's CSV of the program could not be read.

        CLICK keeps what it has for such a program.
        """
        program = self._programs.get(name)
        return program is not None and program.rungs is None

    def _left_out_names(self) -> list[str]:
        return [name for name, *_ in self._folder_items if self._left_out(name)]

    def _matches_click(self, name: str) -> bool:
        if name == _NICKNAMES_NAME:
            return self._nickname_path is not None and self._nicknames_in_click()
        if name in self._unplaced:
            return False  # CLICK holds unsaved pastes of it
        change = self._changes.get(name)
        return change is not None and not change.differs

    def _rest_skipped(self, name: str) -> bool:
        """Return whether every difference not pasted yet is skipped, leaving nothing to paste."""
        if name == _NICKNAMES_NAME:
            return self._nicknames_skipped
        if name in self._only_in_click:
            return self._kept(name)
        if name in self._unplaced:
            return False
        change = self._choosable(name)
        taken = self._skipped_of(name) | self._pasted.get(name, frozenset())
        return change is not None and set(change.differences) <= taken

    def _skipped_in(self, name: str) -> int:
        """Return how many of the program's differences are skipped."""
        change = self._choosable(name)
        return 0 if change is None else len(self._skipped_of(name) & set(change.differences))

    def _skipped_count(self) -> int:
        return sum(self._skipped_in(name) for name, *_ in self._folder_items)

    def _whole_program(self, name: str, rungs: tuple[Rung, ...]) -> list[Rung]:
        """Return the program to paste whole.

        It is the folder's program, except that a skipped difference keeps CLICK's rungs.
        """
        change = self._choosable(name)
        if change is None or not self._skipped_in(name):
            return list(rungs)
        return list(change.merged(self._skipped_of(name)))

    def _copied_whole_for_steps(self, name: str) -> int:
        """Return how many steps the program would take, if that count is why it is copied whole.

        A program that CLICK has is copied whole when it needs _MANY_STEPS steps or more.
        Return zero in every other case. These are the main ones:

        - "Whole program" is on, so every program is copied whole anyway.
        - CLICK lacks the program, or holds pastes of it that ClickNick cannot match to
          this comparison (_unplaced). The program is copied whole for that reason.
        - The program keeps its steps. That happens when a step is done, the user asked to
          step through it, its paste would be slow, or CLICK holds some of its rungs in an
          old encoding. In the last case a whole paste would re-paste the rungs of skipped
          differences from ClickNick's reading of them.
        """
        if self._copy_whole_var.get() or name in self._step_through or name in self._unplaced:
            return 0
        change = self._changes.get(name)
        if change is None or change.legacy or name in self._missing_in_click:
            return 0
        if self._pasted.get(name) or self._partial.get(name):
            return 0
        program = self._programs.get(name)
        # Measure the program as it would be pasted, with CLICK's rungs where a difference
        # is skipped
        if program is None or program.rungs is None:
            return 0
        if len(self._whole_program(name, program.rungs)) >= _SLOW_PASTE_RUNGS:
            return 0
        count = len(change.steps(self._skipped_of(name)))
        return count if count >= _MANY_STEPS else 0

    def _skipped_legacy(self, name: str) -> list[int]:
        """Return the numbers of CLICK's legacy-encoded rungs that a skipped difference keeps.

        ClickNick steps through such a program even under "Whole program". A whole paste
        would write these rungs back from ClickNick's reading of them.
        """
        change = self._choosable(name)
        if change is None or not change.legacy:
            return []
        skipped = self._skipped_of(name)
        every = any(item.rung is None for item in change.legacy)
        legacy = {item.rung for item in change.legacy}
        return [
            number
            for key, (_tag, i1, i2, _j1, _j2) in zip(
                change.differences, _differences_of(change), strict=True
            )
            if key in skipped
            for number in range(i1 + 1, i2 + 1)
            if every or number in legacy
        ]

    def _whole_refusal(self, name: str) -> str:
        """Return why the program may not be copied whole now, or an empty string.

        ClickNick copies the program whole while CLICK holds pastes of it that ClickNick
        cannot match to this comparison (_unplaced). It refuses when a skipped difference
        keeps rungs that CLICK holds in a legacy encoding.
        """
        kept = self._skipped_legacy(name) if name in self._unplaced else []
        if not kept:
            return ""
        which = f"rung {kept[0]}" if len(kept) == 1 else f"rungs {_listed_rungs(kept)}"
        return (
            f"CLICK holds rungs of {name} that you pasted before ClickNick read this folder "
            f"again. CLICK has not saved them. A whole paste would replace CLICK's {which} with "
            "ClickNick's reading of the old encoding. You skipped that difference to keep "
            "CLICK's own copy. Save in CLICK first, then step through the changed rungs. Or "
            "take that difference."
        )

    def _program_steps(
        self, name: str, *, pasted: frozenset[DifferenceKey] = frozenset()
    ) -> list[PasteStep]:
        if name in self._unplaced:
            return []  # Steps cannot be numbered from what CLICK holds, so copy it whole
        if self._copy_whole_var.get() and not self._skipped_legacy(name):
            return []
        if self._copied_whole_for_steps(name):
            return []
        change = self._changes.get(name)
        if change is None or name in self._missing_in_click:
            return []
        return list(change.steps(self._skipped_of(name), pasted))

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _steps(self, name: str) -> list[PasteStep]:
        """Return what is left to do in CLICK for a program CLICK has, one difference at a time.

        Return an empty list when nothing differs, or when the whole program is pasted
        instead. The whole program is pasted in these cases:

        - The Copy switch says so.
        - The program has many steps (_copied_whole_for_steps).
        - CLICK holds pastes of it that ClickNick cannot match to this comparison.
        - CLICK lacks the program.
        - ClickNick does not know what CLICK has, or cannot read all of CLICK's copy.
        """
        return self._program_steps(name, pasted=self._pasted.get(name, frozenset()))

    def _pasted_already(self, name: str, block: int) -> bool:
        """Return whether the difference is already in CLICK, pasted or with its step begun."""
        change = self._choosable(name)
        if change is None:
            return False
        if change.differences[block] in self._pasted.get(name, ()):
            return True
        steps = self._steps(name)
        return bool(self._partial.get(name)) and bool(steps) and steps[0].block == block

    def _locked(self, name: str, block: int) -> bool:
        """Return whether the difference can no longer be taken or skipped.

        A difference that is already in CLICK is locked. So is every difference of a
        program while one of its differences is half done (pasted, with rungs left to
        delete). Taking or skipping one then would renumber the step under way.
        """
        if self._choosable(name) is None or name in self._done:
            return True
        return bool(self._partial.get(name)) or self._pasted_already(name, block)

    def _all_differences(self) -> list[tuple[str, int]]:
        """Return every difference that can be taken or skipped, program by program."""
        return [
            (name, block)
            for name, *_ in self._folder_items
            if (change := self._choosable(name)) is not None
            for block in range(len(change.differences))
        ]

    def _viewed_difference(self, differences: list[tuple[str, int]]) -> int | None:
        """Return the position of the difference being looked at in *differences*, or None."""
        if self._view_name is None:
            return None
        here = (self._view_name, self._view_block)
        return differences.index(here) if here in differences else None

    def _current_steps(self) -> list[PasteStep]:
        if self._current_idx is None:
            return []
        return self._steps(self._items[self._current_idx][0])

    def _current_step(self) -> PasteStep | None:
        """Return the current row's step, or None when the whole program is copied in one go."""
        if self._current_idx is None:
            return None
        name = self._items[self._current_idx][0]
        steps = self._steps(name)
        partial = self._partial.get(name, 0)
        return steps[partial] if partial < len(steps) else None

    def _whole_placement(self, name: str) -> str:
        """Say how a whole program goes into CLICK, given what CLICK has of it."""
        clear_first = (
            "In CLICK, select all of its rungs (Shift+Up/Down) and delete them, then paste (Ctrl+V)"
        )
        if name in self._unplaced:
            return clear_first  # CLICK holds what was pasted of it before
        change = self._changes.get(name)
        if change is None:
            return (
                "In CLICK, if the program has rungs, select all of them (Shift+Up/Down) and "
                "delete them, then paste (Ctrl+V)"
            )
        # A copy ClickNick cannot read may hold rungs even when none could be counted
        if not (change.before or change.unreadable) or name in self._missing_in_click:
            return "In CLICK, paste into the program's ladder (Ctrl+V)"
        return clear_first

    def _click_label(self, name: str) -> str:
        if name == _NICKNAMES_NAME:
            return self._nicknames_label()
        if self._left_out(name):
            return "unreadable"
        if name in self._only_in_click:
            return f"{_CLICK_ONLY}, kept" if self._kept(name) else _CLICK_ONLY
        change = self._changes.get(name)
        if change is None:
            return ""
        if name in self._unplaced:
            return _CLICK_UNSAVED
        if not change.differs:
            return _CLICK_MATCHES
        label = _CLICK_NEW if name in self._missing_in_click else _change_label(change)
        skipped = self._skipped_in(name)
        if self._all_skipped(name):
            return f"{label}, all skipped"
        return f"{label}, {skipped} skipped" if skipped else label

    def _update_progress_text(self) -> None:
        todo = [
            name
            for name, *_ in self._items
            if not self._matches_click(name)
            and not self._all_skipped(name)
            and not self._left_out(name)
        ]
        done_n = sum(1 for name in todo if name in self._done)
        text = f"{done_n} of {len(todo)} done"
        matching = sum(1 for name, *_ in self._items if self._matches_click(name))
        if matching:
            text += f" · {matching} up to date in CLICK"
        skipped = self._skipped_count()
        if skipped:
            text += f" · {skipped} difference{'s' if skipped != 1 else ''} skipped"
        if self._only_in_click:
            text += f" · {len(self._only_in_click)} only in CLICK"
        if left_out := self._left_out_names():
            text += f" · {len(left_out)} unreadable"
        self._progress_lbl.configure(text=text)

    # ------------------------------------------------------------------
    # Rung diff pane
    # ------------------------------------------------------------------

    def _click_sources(self) -> BundleSources:
        """Return the program in CLICK as pyrung source. Generate it the first time it is shown."""
        csv_dir = self._saved_program.csv_dir
        if csv_dir is None:
            return self._before_sources or BundleSources()
        if self._before_sources is None:
            self._before_sources = BundleSources.round_trip(csv_dir)
        return self._before_sources

    def _proposed_sources(self) -> BundleSources:
        """Return the folder's programs as pyrung source.

        Use the workspace's own source if there is one. Otherwise generate it.
        """
        if self._after_sources is None:
            self._after_sources = BundleSources.round_trip(self._folder)
        return self._after_sources

    def _describe_view(self) -> tuple[str, RenderedDiff]:
        """Return a note about the viewed row and, if there is one, its difference from CLICK."""
        name = self._view_name
        if name is None:
            return "", RenderedDiff()
        if name == _NICKNAMES_NAME:
            return self._describe_nicknames(), RenderedDiff()

        change = self._only_in_click.get(name)
        if change is None:
            program = self._programs.get(name)
            if program is not None and program.error:
                return (
                    f"{name} could not be read: {program.error}\n"
                    "It is left out. CLICK keeps what it has of it.",
                    RenderedDiff(),
                )
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
        instead = ""
        if name in self._only_in_click:
            instead = (
                "This folder does not have the program. CLICK keeps it as it is."
                if self._kept(name)
                else "This folder does not have the program. The step is to delete it in CLICK."
            )
        notes = [_legacy_note(change, instead=instead)]
        if after.error and not after.text(name) and name not in self._only_in_click:
            # For example, pyrung may refuse a nicknames.csv. The error names the line.
            notes.append(
                f"pyrung could not convert the rungs from {self._source.label}, so they are "
                f"listed by their instructions. The error was: {after.error}"
            )
        elif not before.text(name) and not after.text(name):
            notes.append(
                "pyrung could not show this program as text. "
                "Each rung is listed by its instructions."
            )
        note = "\n".join(line for line in notes if line)
        if change is not self._expanded_change:
            # Reset the expanded rungs. They belong to the difference they were expanded in.
            self._expanded_change, self._expanded = change, {}
        return note, render_diff(
            change,
            name,
            before=before,
            after=after,
            shown=self._expanded,
            source=self._source.label,
        )

    def _scroll_to_view(self) -> None:
        """Bring the difference being looked at to the top of the pane."""
        blocks = self._shown_diff.blocks
        if self._view_block >= len(blocks):
            self._text.yview_moveto(0)
            return
        # Lines never wrap, so a line's number divided by the total is its scroll position
        total = int(self._text.index("end-1c").split(".")[0])
        self._text.yview_moveto((blocks[self._view_block] + self._diff_first_line - 1) / total)

    def _mark_differences(self, diff: RenderedDiff) -> None:
        """Grey out the skipped differences of the program shown, and mark the current one.

        The current difference gets a solid bar in the margin left of its +/- gutter.
        The difference bar and the Take checkbox act on that difference.
        """
        change = self._choosable(self._view_name)
        if change is None or self._view_name is None:
            return
        skipped = self._skipped_of(self._view_name)
        first = self._diff_first_line
        for block, key in enumerate(change.differences):
            if block >= len(diff.changed):
                break
            start, end = diff.changed[block]
            if key in skipped:
                self._text.tag_add("skipped", f"{start + first}.0", f"{end + first}.0")
            if block == self._view_block:
                for line in range(start + first, end + first):
                    self._text.tag_add("current", f"{line}.0", f"{line}.1")

    def _update_difference_bar(self) -> None:
        """Say which difference is being looked at, and whether it is taken."""
        differences = self._all_differences()
        here = self._viewed_difference(differences)
        unreviewed = sum(
            1
            for name, *_ in self._folder_items
            if self._choosable(name) and name not in self._viewed
        )
        self._review_lbl.configure(
            text=f"{unreviewed} program{'s' if unreviewed != 1 else ''} not reviewed yet"
            if unreviewed
            else ""
        )
        moving = "normal" if differences else "disabled"
        self._prev_btn.configure(state=moving)
        self._next_btn.configure(state=moving)
        if self._view_name == _NICKNAMES_NAME:
            # The nicknames are taken or skipped as a whole. Skipping stays available when
            # CLICK's database or a readable file is missing, so the user can go on.
            choosable = not self._nicknames_in_click()
            self._bar_lbl.configure(text=_NICKNAMES_NAME)
            self._take_var.set(not self._nicknames_skipped)
            self._take_chk.configure(
                text="Take these nicknames", state="normal" if choosable else "disabled"
            )
            self._detail_lbl.configure(
                text="Skipped: CLICK keeps its nicknames" if self._nicknames_skipped else ""
            )
            return
        if self._view_name in self._only_in_click:
            # A program only in CLICK is deleted or kept as a whole
            kept = self._kept(self._view_name)
            self._bar_lbl.configure(text=_CLICK_ONLY)
            self._take_var.set(not kept)
            self._take_chk.configure(
                text=_DELETE_IN_CLICK,
                state="disabled" if self._view_name in self._done else "normal",
            )
            self._detail_lbl.configure(text="Kept: CLICK keeps the program" if kept else "")
            return
        self._take_chk.configure(text="Take this difference")
        change = self._choosable(self._view_name)
        if change is None or self._view_name is None or here is None:
            count = len(differences)
            self._bar_lbl.configure(
                text=f"{count} difference{'s' if count != 1 else ''}" if count else "No differences"
            )
            self._take_var.set(False)
            self._take_chk.configure(state="disabled")
            self._detail_lbl.configure(text="")
            return
        self._bar_lbl.configure(text=f"Difference {here + 1} of {len(differences)}")
        key = change.differences[self._view_block]
        skipped = key in self._skipped_of(self._view_name)
        locked = self._locked(self._view_name, self._view_block)
        self._take_var.set(not skipped)
        self._take_chk.configure(state="disabled" if locked else "normal")
        if skipped:
            detail = _what_skipping_keeps(_differences_of(change)[self._view_block])
        elif self._view_name not in self._done and self._pasted_already(
            self._view_name, self._view_block
        ):
            detail = "Pasted"
        else:
            detail = ""
        self._detail_lbl.configure(text=detail)

    def _show_diff(self, *, keep_scroll: bool = False) -> None:
        """Show how the viewed row's program differs from CLICK.

        Scroll to the difference being looked at. If *keep_scroll* is set, stay where the
        pane was.
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
            # Colour the +/- in the gutter colour and the changed words in a darker shade
            self._text.insert(tk.END, line[0], (tag, f"{tag}_gutter"))
            column = 1
            for start, end in diff.words.get(index, ()):
                if column < start:
                    self._text.insert(tk.END, line[column:start], tag)
                self._text.insert(tk.END, line[start:end], (tag, f"{tag}_word"))
                column = end
            self._text.insert(tk.END, line[column:], tag)
        self._shown_diff = diff
        # The Text widget numbers lines from 1, and the diff starts below the note
        self._diff_first_line = note.count("\n") + 2 if note else 1
        self._text.tag_add("margin", "1.0", tk.END)
        self._mark_differences(diff)
        self._text.configure(state=tk.DISABLED)
        name = self._view_name
        if name is not None and diff.lines and self._choosable(name) is not None:
            self._viewed.add(name)
        self._update_difference_bar()
        if keep_scroll:
            total = int(self._text.index("end-1c").split(".")[0])
            self._text.yview_moveto((top_line - 1) / total)
        else:
            self._scroll_to_view()

    # ------------------------------------------------------------------
    # Row highlighting
    # ------------------------------------------------------------------

    def _highlight_row(self, idx: int, bg: str | None = None, fg: str | None = None) -> None:
        for col in range(_NUM_COLS):
            self._sheet.highlight_cells(row=idx, column=col, bg=bg, fg=fg)

    def _dehighlight_row(self, idx: int) -> None:
        for col in range(_NUM_COLS):
            self._sheet.dehighlight_cells(row=idx, column=col)

    def _pending_icon(self, name: str) -> str:
        """Return the icon for a program still to paste.

        The icon is a filled dot until the program's difference has been shown, and a
        hollow one after that. A program with no differences to take or skip always gets
        the hollow one.
        """
        if self._choosable(name) is not None and name not in self._viewed:
            return _ICON_UNREVIEWED
        return _ICON_PENDING

    def _update_highlights(self) -> None:
        for idx, (name, *_) in enumerate(self._items):
            self._sheet.set_cell_data(idx, COL_CLICK, self._click_label(name))
            if name in self._done:
                self._highlight_row(idx, _BG_DONE)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_DONE)
            elif idx == self._current_idx:
                self._highlight_row(idx, _BG_CURRENT)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_CURRENT)
            elif self._left_out(name):
                self._dehighlight_row(idx)
                self._highlight_row(idx, _BG_LEGACY, _FG_LEGACY)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_SKIPPED)
            elif self._matches_click(name):
                self._dehighlight_row(idx)
                self._highlight_row(idx, fg=_FG_MATCHES)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_MATCHES)
            elif self._all_skipped(name):
                self._dehighlight_row(idx)
                self._highlight_row(idx, fg=_FG_MATCHES)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_SKIPPED)
            elif name in self._only_in_click:
                self._dehighlight_row(idx)
                self._highlight_row(idx, fg=_FG_ONLY_IN_CLICK)
                self._sheet.set_cell_data(idx, COL_STATUS, _ICON_ONLY_IN_CLICK)
            elif self._has_legacy(name):
                self._dehighlight_row(idx)
                self._highlight_row(idx, _BG_LEGACY, _FG_LEGACY)
                self._sheet.set_cell_data(idx, COL_STATUS, self._pending_icon(name))
            else:
                self._dehighlight_row(idx)
                self._sheet.set_cell_data(idx, COL_STATUS, self._pending_icon(name))
        self._sheet.set_refresh_timer()
        self._update_progress_text()

    # ------------------------------------------------------------------
    # Action button state
    # ------------------------------------------------------------------

    @staticmethod
    def _nothing_to_copy(step: PasteStep | None) -> bool:
        """Return whether the step only deletes rungs, so the user does it in CLICK alone."""
        return step is not None and not step.rungs

    def _empty_whole(self, name: str, step: PasteStep | None) -> bool:
        """Return whether the program is copied whole and has no rungs, so CLICK's are deleted."""
        program = self._programs.get(name)
        if step is not None or program is None or program.rungs is None:
            return False
        return name not in self._only_in_click and not self._whole_program(name, program.rungs)

    def _update_action_btn(self) -> None:
        """Update the action buttons based on current state."""
        can_add = self._can_add_subroutine(self._current_idx) and not self._adding_subroutine
        self._add_sub_btn.configure(state="normal" if can_add else "disabled")
        many = self._current_idx is not None and bool(
            self._copied_whole_for_steps(self._items[self._current_idx][0])
        )
        if many:
            self._step_through_btn.pack(side=tk.RIGHT, padx=(0, 5), before=self._add_sub_btn)
        else:
            self._step_through_btn.pack_forget()
        if self._current_idx is None:
            self._action_btn.configure(state="disabled", text="Done")
            return

        step = self._current_step()
        name = self._items[self._current_idx][0]
        if (
            self._copied
            or self._nothing_to_copy(step)
            or self._empty_whole(name, step)
            or self._rest_skipped(name)
            # A program only in CLICK has nothing to copy. The user deletes it there or keeps it.
            or name in self._only_in_click
        ):
            self._action_btn.configure(state="normal", text="Next →")
        elif self._is_nickname_step(self._current_idx):
            text = _OPEN_EDITOR if self._nicknames_staged() else _STAGE
            self._action_btn.configure(state="normal", text=text)
        elif step is not None:
            self._action_btn.configure(state="normal", text=f"Copy {format_group(step.rungs)}")
        else:
            skipped = self._skipped_in(name)
            label = f"Copy, {skipped} skipped" if skipped else "Copy"
            self._action_btn.configure(state="normal", text=label)

    def _only_in_click_prompt(self, name: str) -> str:
        """Return what to do with a program that CLICK has and the folder lacks."""
        if self._kept(name):
            return (
                f"{name} is not in this folder. CLICK keeps the program.\n"
                f'Click "Next" to go on, or tick {_DELETE_IN_CLICK} to delete it there'
            )
        stem = Path(name).stem
        what = "main program" if name == "main.csv" else f"subroutine {stem}"
        return (
            f"{name} is in CLICK but not in this folder.\n"
            f'Delete the {what} in CLICK, then click "Next". To keep it, untick '
            f"{_DELETE_IN_CLICK}"
        )

    def _stepped_line(self, name: str) -> str:
        """Return why the program is stepped through under "Whole program", or an empty string."""
        kept = self._skipped_legacy(name) if self._copy_whole_var.get() else []
        if not kept:
            return ""
        which = f"rung {kept[0]}" if len(kept) == 1 else f"rungs {_listed_rungs(kept)}"
        return (
            "\nClickNick steps through this program and does not copy it whole. A whole "
            f"paste would replace CLICK's {which} with ClickNick's reading of the old encoding. "
            "You skipped that difference to keep CLICK's own copy"
        )

    def _step_prompt(self, idx: int) -> str:
        """Return what the current step of the row does."""
        name, _path, rung_count, _ = self._items[idx]
        if self._is_nickname_step(idx):
            if self._nicknames_skipped:
                return (
                    "The nicknames are skipped. CLICK keeps its own.\n"
                    'Click "Next" to go on, or tick Take these nicknames to stage them'
                )
            return self._nicknames_prompt()
        if name in self._only_in_click:
            return self._only_in_click_prompt(name)
        if self._rest_skipped(name):
            which = "Every difference" if self._all_skipped(name) else "What is left"
            return (
                f"{which} of {name} is skipped. CLICK keeps what it has.\n"
                'Click "Next" to go on, or tick Take this difference to paste one'
            )
        step = self._current_step()
        if step is not None:
            total = len(self._program_steps(name))
            # The steps done are all the steps of pasted differences, and the steps of the
            # difference begun that are done already
            partial = self._partial.get(name, 0)
            number = total - len(self._current_steps()) + partial + 1
            head = f"{name}, step {number} of {total}"
            label = format_group(step.rungs)
            if not step.rungs:
                old = _rungs_in_click(step.delete)
                legacy = self._legacy_line(name, step)
                # After a paste of fresh copies of old-encoded rungs, the rungs left to delete
                # are CLICK's old copies. The program still has those rungs, so the prompt
                # must not say that they are gone from it.
                after_paste = bool(legacy) and partial > 0
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
                return f"{head}: {what}.\n{action}{legacy}{self._stepped_line(name)}"
            if step.over is not None:
                what = f"{label} replaces rung {step.over}"
            else:
                what = f"{label} is new"
            prompt = f'{head}: {what}.\nClick "Copy {label}". {_where_to_paste(step)}'
            prompt += self._legacy_line(name, step)
            return prompt + self._stepped_line(name)
        if self._matches_click(name):
            if self._empty_whole(name, step):
                return (
                    f"{name} already matches CLICK's last save. Neither has rungs.\n"
                    'Click "Next" to go on'
                )
            return (
                f"{name} already matches CLICK's last save.\n"
                'Click "Copy" to copy it to the clipboard anyway'
            )
        if self._empty_whole(name, step):
            if self._can_add_subroutine(idx):
                return (
                    f"{name} has no rungs in this folder.\n"
                    'Click "New Subroutine" to create it in CLICK, then click "Next"'
                )
            return (
                f"{name} has no rungs in this folder.\n"
                'In CLICK, delete all the rungs of the program, then click "Next"'
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
        if change is not None and (
            name in self._unplaced
            or ((change.before or change.unreadable) and name not in self._missing_in_click)
        ):
            skipped = self._skipped_in(name)
            if skipped:
                program = self._programs.get(name)
                count = (
                    len(self._whole_program(name, program.rungs))
                    if program and program.rungs
                    else 0
                )
                kept = "difference" if skipped == 1 else "differences"
                whole = (
                    f"the whole program as you chose it, {count} rungs, with {skipped} skipped "
                    f"{kept} left as CLICK has them, replaces what CLICK has"
                )
                button = f"Copy, {skipped} skipped"
            else:
                whole = f"the whole program, {rung_count} rungs, replaces what CLICK has"
                button = "Copy"
            prompt = f'{name}: {whole}.\nClick "{button}". {self._whole_placement(name)}'
            if steps := self._copied_whole_for_steps(name):
                prompt += (
                    f"\nStepping through the changed rungs would take {steps} steps, so it is "
                    f'copied whole. Click "{_STEP_THROUGH}" to step through them instead'
                )
            if change.legacy:
                prompt += f"\n{_legacy_note(change)}"
            if refusal := _empty_refusal(name, change) or self._whole_refusal(name):
                prompt += f"\n{refusal}"
            elif name in self._unplaced:
                prompt += (
                    f"\nYou pasted rungs of {name} into CLICK before ClickNick read this folder "
                    "again, and CLICK has not saved them. ClickNick cannot number the changed "
                    f"rungs, so it copies {name} whole. To step through the changed rungs "
                    "instead, save in CLICK first"
                )
            return prompt
        return f'Click "Copy" to copy {name} to the clipboard. {self._whole_placement(name)}'

    def _toggle_kept(self, name: str) -> None:
        """Keep a program only in CLICK, or delete it there after all."""
        if name in self._done:
            return
        self._flipped_in_click ^= {name}
        idx = self._current_idx
        if idx is not None and self._items[idx][0] == name:
            self._status_var.set(self._step_prompt(idx))
        self._update_highlights()
        self._update_action_btn()
        self._show_diff(keep_scroll=True)

    def _toggle_nicknames(self) -> None:
        """Take the folder's nicknames, or leave CLICK's as they are."""
        self._nicknames_skipped = not self._nicknames_skipped
        idx = self._current_idx
        if idx is not None and self._is_nickname_step(idx):
            self._copied = False
            self._status_var.set(self._step_prompt(idx))
        self._update_highlights()
        self._update_action_btn()
        self._show_diff(keep_scroll=True)

    def _stage_folder_nicknames(self) -> None:
        """Stage the folder's nicknames in the Address Editor and open it on them, ready to Sync."""
        store = self._get_project_store()
        if store is None or self._nickname_rows is None:
            self._status_var.set(self._nicknames_prompt())
            return
        plan = plan_nicknames(
            self._nickname_rows, store.visible_state, fields=self._nickname_fields
        )
        try:
            stage_nicknames(store, plan, f"Nicknames from {self._folder.name}")
        except Exception as exc:
            self._status_var.set(f"Could not stage the nicknames: {exc}")
            return
        self._refresh_nicknames()
        self._open_staged_nicknames()
        self._copied = True
        staged = f"Staged {plan.summary()}" if plan else "The nicknames are staged"
        self._status_var.set(
            f'{staged} in the Address Editor. Check them under Changed and click "Sync and '
            'Close" there, then "Next" here to paste the programs'
        )
        self._update_highlights()
        self._update_action_btn()
        self._show_diff(keep_scroll=True)

    def _needs_paste(self, name: str) -> bool:
        return (
            name not in self._done
            and not self._matches_click(name)
            and not self._all_skipped(name)
            and not self._left_out(name)
        )

    def _follow_in_sheet(self, idx: int) -> None:
        """Move the sheet's own selection to the row and scroll it into view.

        If the user clicked a cell in that row, that cell stays selected.
        """
        selected = self._sheet.get_currently_selected()
        if not selected or selected.row != idx:
            self._sheet.select_cell(idx, COL_FILE, run_binding_func=False)
        self._sheet.see(idx, COL_FILE, keep_xscroll=True)

    def _select_row(self, idx: int, *, block: int | None = None) -> None:
        """Make the row the current one, and show its difference *block*.

        If *block* is None, show the difference of the row's current step. The program's
        steps continue from where they stopped.
        """
        if idx < 0 or idx >= len(self._items):
            return
        name = self._items[idx][0]
        if name in self._done or self._left_out(name):
            return
        self._current_idx = idx
        self._copied = False
        self._view_name = name
        step = self._current_step()
        self._view_block = block if block is not None else step.block if step is not None else 0
        self._follow_in_sheet(idx)
        self._update_highlights()
        self._update_action_btn()
        self._status_var.set(self._step_prompt(idx))
        self._show_diff()

    def _all_done(self) -> None:
        self._current_idx = None
        self._copied = False
        self._sheet.deselect()
        self._update_highlights()
        if any(not self._kept(name) for name in self._only_in_click):
            msg = "Every change has been made in CLICK!"
        elif any(self._matches_click(name) for name, *_ in self._items):
            msg = "Every changed program has been pasted!"
        else:
            msg = "All CSVs have been pasted!"
        kept = sum(1 for name in self._only_in_click if self._kept(name))
        if kept:
            programs = "program" if kept == 1 else "programs"
            msg += f"\nCLICK keeps {kept} {programs} that this folder does not have"
        if left_out := self._left_out_names():
            files = "CSV file" if len(left_out) == 1 else "CSV files"
            verb = "is" if len(left_out) == 1 else "are"
            msg += f"\n{len(left_out)} {files} could not be read and {verb} left out"
        self._status_var.set(msg)
        self._update_action_btn()

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

    def _on_nicknames_changed(self) -> None:
        """Bring the nicknames row up to date after the Address Editor stages, syncs or discards."""
        self._update_highlights()
        idx = self._current_idx
        if idx is not None and self._is_nickname_step(idx):
            if not self._needs_paste(_NICKNAMES_NAME):
                self._advance_to_next()
                return
            if self._nickname_plans is not None and self._nickname_plans[0]:
                # The user discarded or undid the staging in the Address Editor, so there is
                # staging to do again
                self._copied = False
            if not self._copied:
                self._status_var.set(self._step_prompt(idx))
            self._update_action_btn()
        elif idx is None and self._needs_paste(_NICKNAMES_NAME):
            self._advance_to_first_pending()
            return
        if self._view_name == _NICKNAMES_NAME:
            self._show_diff(keep_scroll=True)

    # ------------------------------------------------------------------
    # Sheet data
    # ------------------------------------------------------------------

    def _settled(self) -> bool:
        """Return whether CLICK's last save holds everything taken from the folder and no more."""
        return (
            self._click_compared
            and all(self._kept(name) for name in self._only_in_click)
            and all(
                self._matches_click(name) or self._all_skipped(name) or self._left_out(name)
                for name in self._programs
            )
            and (
                self._nickname_path is None or self._nicknames_skipped or self._nicknames_in_click()
            )
        )

    def _skipped_edits_line(self) -> str:
        """Return a warning that a CLICK save leaves skipped workspace edits only in the backup."""
        skipped = self._skipped_count()
        if self._source_dir is None or not skipped:
            return ""
        what = "difference is an edit" if skipped == 1 else "differences are edits"
        return (
            f"{skipped} skipped {what} in the workspace source. When CLICK saves, the "
            "workspace goes back to CLICK's version. Skipped edits then stay only in "
            "backup/src/plc. For older backups, run clicknick-cli restore list."
        )

    def _update_notice(self) -> None:
        """Show a notice when the folder no longer holds what the window is still pasting.

        A CLICK save, or Reload from CLICK, regenerates the workspace. It removes
        ``csv_output/`` and sets ``src/plc`` back to what CLICK has. Skipped workspace
        edits are lost from ``src/plc`` the same way, so the notice warns of that too.
        """
        gone = bool(self._programs) and not any(
            program.path.is_file() for program in self._programs.values()
        )
        lines: list[str] = []
        if gone and not self._settled():
            if self._source_dir is None:
                lines.append(
                    "This folder's CSVs are gone. The window still holds them as read at "
                    f"{self._read_at} and can keep pasting them."
                )
            else:
                lines.append(
                    "ClickNick rebuilt the workspace from CLICK before you pasted every "
                    "change. This window still holds the proposal exported at "
                    f"{self._read_at} and can keep pasting it.\n"
                    "The edited source is kept in backup/src/plc. For older backups, run "
                    "clicknick-cli restore list. To work on it again, run clicknick-cli "
                    "restore, then Review Changes."
                )
        elif skipped := self._skipped_edits_line():
            lines.append(skipped)
        if left_out := self._left_out_names():
            verb = "is" if len(left_out) == 1 else "are"
            lines.append(
                f"{', '.join(left_out)} could not be read and {verb} left out. CLICK keeps "
                "what it has. Fix the CSV and open the folder again to paste it."
            )
        if not lines:
            self._notice_lbl.pack_forget()
            return
        self._notice_lbl.configure(text="\n".join(lines))
        self._notice_lbl.pack(fill=tk.X, pady=(0, 5), after=self._opts)

    def _toggle(self, name: str, block: int) -> None:
        """Take a difference that was skipped, or skip one that was taken."""
        change = self._choosable(name)
        if change is None or block >= len(change.differences):
            return
        self._view_name, self._view_block = name, block
        if self._locked(name, block):
            if self._pasted_already(name, block):
                why = "That difference is already pasted into CLICK, so you can no longer skip it"
            elif name in self._done:
                why = f"{name} is marked done, so you can no longer take or skip its differences"
            else:
                why = (
                    f"A step of {name} is under way in CLICK. Finish it and click "
                    '"Next" before taking or skipping another of its differences'
                )
            self._status_var.set(why)
            self._show_diff(keep_scroll=True)
            return
        self._skipped[name] = self._skipped_of(name) ^ {change.differences[block]}
        self._basis[name] = change
        idx = self._current_idx
        if idx is not None and self._items[idx][0] == name:
            self._copied = False  # The clipboard still holds the earlier choice
            self._status_var.set(self._step_prompt(idx))
        self._update_notice()
        self._update_highlights()
        self._update_action_btn()
        self._show_diff(keep_scroll=True)

    def _go_to_difference(self, offset: int) -> None:
        """Show the next (+1) or previous (-1) difference, crossing into other programs."""
        differences = self._all_differences()
        if not differences:
            return
        here = self._viewed_difference(differences)
        if here is not None:
            position = (here + offset) % len(differences)
        else:
            position = 0 if offset > 0 else len(differences) - 1
        name, block = differences[position]
        idx = next(index for index, (item, *_) in enumerate(self._items) if item == name)
        if name in self._done or idx == self._current_idx:
            # The row is done or is already the current row, so only the view moves
            self._view_name, self._view_block = name, block
            self._show_diff()
        else:
            self._select_row(idx, block=block)

    def _on_gutter(self, event: tk.Event) -> None:
        """Take or skip the difference whose +/- gutter was clicked."""
        position = self._text.index(f"@{event.x},{event.y}")
        line = int(position.split(".")[0]) - self._diff_first_line
        for block, (start, end) in enumerate(self._shown_diff.changed):
            if start <= line < end and self._view_name is not None:
                self._toggle(self._view_name, block)
                return

    def _on_take(self) -> None:
        """Handle the Take checkbox for the difference shown, the nicknames, or a deletion."""
        if self._view_name == _NICKNAMES_NAME:
            self._toggle_nicknames()
        elif self._view_name in self._only_in_click:
            self._toggle_kept(self._view_name)
        elif self._view_name is not None:
            self._toggle(self._view_name, self._view_block)

    def _on_expand(self, event: tk.Event) -> None:
        """Show more of the unchanged rungs behind the clicked separator arrow."""
        position = self._text.index(f"@{event.x},{event.y}")
        gap = self._shown_diff.gaps.get(int(position.split(".")[0]) - self._diff_first_line)
        arrow = self._text.get(position)
        if gap is None or arrow not in gap.arrows:
            return
        self._expanded[gap.opcode] = gap.expand(arrow)
        self._show_diff(keep_scroll=True)

    def _populate_sheet(self) -> None:
        data = []
        for name, _path, rungs, desc in self._items:
            icon = _ICON_DONE if name in self._done else self._pending_icon(name)
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

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def _copy_rungs(self, idx: int, step: PasteStep | None) -> bool:
        """Copy a program to the clipboard, or just the rungs of *step*.

        Return whether the clipboard now holds them.
        """
        name = self._items[idx][0]
        program = self._programs.get(name)
        change = self._changes.get(name)
        group = step.rungs if step is not None else None
        try:
            if program is None or program.rungs is None:
                raise ValueError(program.error if program else "it is not in this folder")
            refusal = _empty_refusal(name, change) if change is not None else ""
            if refusal:
                raise ValueError(refusal)
            if group is None:
                rungs = self._whole_program(name, program.rungs)
            else:
                # A step's rung numbers count the folder's rungs, not CLICK's
                rungs = [
                    program.rungs[number - 1]
                    for number in group
                    if 1 <= number <= len(program.rungs)
                ]
            if not rungs:
                raise ValueError("there are no rungs to copy")
            if group is None and (refusal := self._whole_refusal(name)):
                raise ValueError(refusal)
            click_hwnd = self._get_click_hwnd()
            if click_hwnd is None:
                # The copy depends on the CLICK window it goes into and on that CLICK's version
                self._status_var.set(
                    "Not connected to CLICK. Connect to the CLICK window to paste into, "
                    "then copy again"
                )
                return False
            result = prepare_rungs_load(
                rungs,
                click_v4=is_click_v4(click_hwnd),
                mdb_path=self._get_mdb_path(),
                show_nicknames=self._show_nicks_var.get(),
                first_rung=group[0] if group else 1,
            )
            copy_to_clipboard(result.payload, owner_hwnd=click_hwnd)
        except RuntimeError as exc:
            self._status_var.set(
                f"Could not copy to the clipboard: {exc}\nCheck that CLICK is running, then "
                "copy again"
            )
            return False
        except Exception as exc:
            self._status_var.set(f"Could not copy {name}: {exc}")
            return False

        self._copied = True
        what = name if group is None else f"{format_group(group)} of {name}"
        rung_word = "rung" if result.rung_count == 1 else "rungs"
        msg = f"{what} copied to clipboard ({result.rung_count} {rung_word})"
        if result.addresses_inserted:
            count = result.addresses_inserted
            addresses = "address" if count == 1 else "addresses"
            msg += f"\nAdded {count} missing {addresses} to CLICK's database"
        elif result.mdb_error:
            msg += f"\nCould not add the rungs' addresses to CLICK's database: {result.mdb_error}"
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
            msg = (
                f"ClickNick could not type the name into CLICK's {_NEW_SUB_TITLE} window. "
                f'Type "{sub_name}" there yourself'
            )
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
        # Ctrl+U goes to the window in front, so check that CLICK is in front
        if WIN32.get_foreground_pid() != pid:
            self._finish_add_subroutine("Could not bring CLICK to the front. Try again")
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
        if dialog:  # The dialog is already open, so only fill it in
            WIN32.activate(dialog)
            self._fill_new_subroutine(dialog, sub_name)
            return
        WIN32.activate(hwnd)
        self.after(_ACTIVATE_DELAY_MS, lambda: self._send_new_subroutine_key(pid, sub_name))

    def _perform_action(self, idx: int) -> None:
        """Copy the row's rungs, or stage its nicknames."""
        if self._is_nickname_step(idx):
            if self._nicknames_staged():
                self._open_staged_nicknames()
                self._copied = True
                self._update_action_btn()
            else:
                self._stage_folder_nicknames()
        else:
            self._copy_rungs(idx, self._current_step())

    def _start(self, select: str | None = None, *, keep_done: bool = False) -> None:
        """Read the folder, compare it with CLICK, and begin at *select* or the first step.

        If *keep_done* is set, programs marked done stay done when the folder still has
        the same rungs for them, and what was pasted is carried into the new comparison
        (_carry_pasted). Otherwise both are forgotten. Skipped differences stay skipped
        either way.
        """
        previous = self._programs
        previous_only_in_click = set(self._only_in_click)
        self._scan_folder()
        if keep_done:
            self._done = {
                name
                for name in self._done
                if (
                    name in previous
                    and name in self._programs
                    and previous[name].rungs == self._programs[name].rungs
                )
                # A deletion marked done stays done while the folder still lacks it
                or (name in previous_only_in_click and name not in self._programs)
            }
        else:
            self._done.clear()
            self._forget_progress()
        self._current_idx = None
        self._copied = False
        self._compare_with_click()
        self._done -= previous_only_in_click - set(self._only_in_click)
        self._populate_sheet()
        wanted = None if select is None else select.casefold()
        for idx, (name, *_) in enumerate(self._items):
            if name.casefold() == wanted:
                self._select_row(idx)  # It does nothing for a row that is done or left out
                break
        if self._current_idx is None:
            self._advance_to_first_pending()

    def _pasted_message(self) -> str:
        """Return what the window did, for when a CLICK save holds all of it and it closes."""
        skipped = self._skipped_count()
        if not skipped:
            message = "CLICK saved everything from Review Changes"
        else:
            message = (
                f"CLICK saved everything taken from Review Changes; {skipped} skipped "
                f"difference{'s' if skipped != 1 else ''} left as CLICK has "
                f"{'it' if skipped == 1 else 'them'}"
            )
            if self._source_dir is not None:
                message += (
                    " (skipped edits are in backup/src/plc; clicknick-cli restore list for "
                    "older ones)"
                )
        if left_out := self._left_out_names():
            verb = "was" if len(left_out) == 1 else "were"
            message += f"; {', '.join(left_out)} could not be read and {verb} left out"
        return message

    def _close_if_settled(self, was_pending: bool) -> bool:
        """Close the window once CLICK holds the last of what was left to do.

        Return whether the window closed.
        """
        if not was_pending or not self._settled():
            return False
        if self._on_pasted is not None:
            self._on_pasted(self._pasted_message())
        self.destroy()
        return True

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
            # The pastes and the choices belong to the other project, so forget them.
            self._done.clear()
            self._forget_choices()
            self._viewed.clear()
            self._current_idx = None
            self._copied = False
            self._save_count = None  # Each project counts its own saves
            self._done_unchecked = False
        elif program.building and self._changes:
            # CLICK saved: keep the rows until the new CSVs are ready.
            self._saved_program = program
            self._compare_lbl.configure(text=program.note)
            return

        old_steps = self._current_steps()
        current = self._items[self._current_idx][0] if self._current_idx is not None else None
        # was_pending is True only if ClickNick had compared with CLICK and something was left
        # to do. If ClickNick could not read CLICK's program, nothing counts as pending.
        was_pending = self._click_compared and not self._settled()
        self._compare_with_click()
        # The rows only in CLICK may have changed, so find the current row again by its name
        self._current_idx = next(
            (idx for idx, (name, *_) in enumerate(self._items) if name == current), None
        )
        if not new_project and self._close_if_settled(was_pending):
            return
        self._populate_sheet()
        steps = self._current_steps()
        row = self._items[self._current_idx][0] if self._current_idx is not None else None
        if steps != old_steps and (steps or (row is not None and self._needs_paste(row))):
            # The steps changed, so what was copied is out of date. Either CLICK's save holds
            # some of the row's rungs and the steps cover what is left, or the row is now
            # copied whole. If CLICK's save holds all of the row, the row stays as it is
            # until "Next".
            self._copied = False
        if self._copied:
            return  # The user is mid-paste, so the row stays current until "Next"
        idx = self._current_idx
        if idx is None or not self._needs_paste(self._items[idx][0]):
            self._advance_to_first_pending()
        elif steps != old_steps:
            self._select_row(idx)

    def _watch_saved_program(self) -> None:
        if not self.winfo_exists():
            return
        # Pick up nicknames that the user staged, Synced or discarded in the Address Editor
        was_pending = self._click_compared and not self._settled()
        if self._refresh_nicknames():
            if self._close_if_settled(was_pending):
                return
            self._on_nicknames_changed()
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
            if name in self._done or self._left_out(name):
                # The row is not a step any more, but the user can still read its difference
                self._view_name, self._view_block = name, 0
                self._show_diff()
            else:
                self._select_row(row)

    def _finish_step(self, name: str, step: PasteStep) -> None:
        """Record that *step* is done in CLICK.

        Move to the next step of its difference. If none is left, record the difference
        as pasted.
        """
        change = self._changes[name]
        steps = self._steps(name)
        partial = self._partial.get(name, 0)
        self._basis[name] = change
        if partial + 1 < len(steps) and steps[partial + 1].block == step.block:
            self._partial[name] = partial + 1
            return
        self._pasted[name] = self._pasted.get(name, frozenset()) | {change.differences[step.block]}
        self._partial.pop(name, None)

    def _record_whole_paste(self, name: str) -> None:
        """Record that CLICK holds the whole program as copied.

        Every difference that is not skipped then counts as pasted. If there is no
        comparison for the program, or ClickNick cannot read all of CLICK's copy, the steps
        cannot be numbered from what CLICK holds. The program then goes into _unplaced.
        """
        change = self._changes.get(name)
        self._partial.pop(name, None)
        if change is None or change.unreadable:
            self._pasted.pop(name, None)
            self._unplaced.add(name)
            return
        self._pasted[name] = frozenset(change.differences) - self._skipped_of(name)
        self._unplaced.discard(name)
        self._basis[name] = change

    def _on_action(self) -> None:
        """Handle the main action button (Copy, Stage nicknames, or Next)."""
        idx = self._current_idx
        if idx is None:
            return
        name = self._items[idx][0]
        step = self._current_step()
        if self._rest_skipped(name):
            # The button says "Next". CLICK keeps what it has, and a program that was partly
            # pasted is marked done.
            if self._pasted.get(name):
                self._done.add(name)
            self._advance_to_next()
            return
        if (
            not self._copied
            and not self._nothing_to_copy(step)
            and not self._empty_whole(name, step)
            and name not in self._only_in_click
        ):
            # The button says "Copy" or "Stage nicknames"
            self._perform_action(idx)
            return
        if step is not None:
            self._finish_step(name, step)
            next_step = self._current_step()
            if next_step is not None:
                # The button says "Next". Go to the row's next step.
                self._copied = False
                self._view_name, self._view_block = name, next_step.block
                self._update_action_btn()
                self._status_var.set(self._step_prompt(idx))
                self._show_diff()
                return
        # "Next": mark the row done and advance. The nicknames are done once CLICK's
        # database has them (_matches_click), not when they are staged.
        if not self._is_nickname_step(idx):
            if step is None:
                self._record_whole_paste(name)
            self._done.add(name)
        self._advance_to_next()

    def _on_copy_mode(self) -> None:
        """Save the Copy switch's setting, and show the current row's step under that setting.

        What was pasted stays pasted, because the steps are numbered from what CLICK holds.
        """
        _save_copy_whole(self._copy_whole_var.get())
        idx = self._current_idx
        if idx is not None:
            self._select_row(idx)

    def _on_step_through(self) -> None:
        """Step through the current program's changed rungs, though it has many steps."""
        idx = self._current_idx
        if idx is None:
            return
        self._step_through.add(self._items[idx][0])
        self._select_row(idx)

    def _on_difference_key(self, offset: int) -> str:
        self._go_to_difference(offset)
        return "break"

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

    def _restart_question(self) -> str:
        """Return the question to ask before Restart forgets progress, or an empty string."""
        if not self._done and not self._unsaved_pastes():
            return ""
        question = (
            f"Clear progress for {len(self._done)} completed "
            f"{'program' if len(self._done) == 1 else 'programs'}?"
            if self._done
            else "Clear progress?"
        )
        if self._unsaved_pastes():
            question += (
                "\n\nCLICK holds rungs pasted from this window that it has not saved. "
                "Restart numbers the steps from CLICK's last save, as if those pastes were "
                "not there. Undo the pastes in CLICK first, or save in CLICK instead."
            )
        return question

    def _on_restart(self) -> None:
        question = self._restart_question()
        if question and not messagebox.askyesno("Restart", question, parent=self):
            return
        self._action_btn.configure(state="normal")
        self._start()

    def _on_refresh_source(self) -> None:
        """Copy the folder again from where it came from. The window then reloads on it."""
        if self._refresh_source is not None:
            self._refresh_source()

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------

    def _create_widgets(self) -> None:
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # --- header ---
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 5))
        # Says where the proposal comes from (_show_source)
        self._title_lbl = ttk.Label(header, font=("TkDefaultFont", 10, "bold"))
        self._title_lbl.pack(side=tk.LEFT)
        # _show_source shows this button when the folder is a copy that can be made again
        self._refresh_btn = ttk.Button(header, command=self._on_refresh_source)
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
        # The Copy switch. When it is off, the steps go through the rungs that differ. When
        # it is on, a step copies a whole program. It opens as the user last left it.
        self._copy_whole_var = tk.BooleanVar(value=_read_copy_whole())
        ttk.Checkbutton(
            opts,
            text="Show nicknames in math instructions",
            variable=self._show_nicks_var,
        ).pack(side=tk.RIGHT)

        # Pack the buttons and the status against the bottom *before* the panes. The sheet
        # and the diff ask for more height than the window has, and pack gives too little
        # room to whatever it packs last. These widgets are packed from the bottom up.
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

        # --- rung diff of the selected row, under the difference bar ---
        diff_pane = ttk.Frame(panes)
        panes.add(diff_pane, weight=3)
        bar = ttk.Frame(diff_pane)
        bar.pack(fill=tk.X, pady=(0, 3))
        self._prev_btn = ttk.Button(
            bar, text="◀", width=3, command=lambda: self._go_to_difference(-1)
        )
        self._prev_btn.pack(side=tk.LEFT)
        self._bar_lbl = ttk.Label(bar, text="", width=20, anchor="center")
        self._bar_lbl.pack(side=tk.LEFT, padx=3)
        self._next_btn = ttk.Button(
            bar, text="▶", width=3, command=lambda: self._go_to_difference(1)
        )
        self._next_btn.pack(side=tk.LEFT)
        bind_tooltip(self._prev_btn, "Previous difference (Alt+Up, Shift+F7)")
        bind_tooltip(self._next_btn, "Next difference (Alt+Down, F7)")
        self._take_var = tk.BooleanVar(value=False)
        self._take_chk = ttk.Checkbutton(
            bar, text="Take this difference", variable=self._take_var, command=self._on_take
        )
        self._take_chk.pack(side=tk.LEFT, padx=(12, 0))
        self._detail_lbl = ttk.Label(bar, text="", foreground=_DIFF_MUTED)
        self._detail_lbl.pack(side=tk.LEFT, padx=(8, 0))
        self._review_lbl = ttk.Label(bar, text="", foreground=_DIFF_MUTED)
        self._review_lbl.pack(side=tk.RIGHT)
        for sequence, offset in (
            ("<Alt-Down>", 1),
            ("<Alt-Up>", -1),
            ("<F7>", 1),
            ("<Shift-F7>", -1),
        ):
            self.bind(sequence, lambda _e, offset=offset: self._on_difference_key(offset))

        diff_frame = tk.Frame(diff_pane, relief=tk.SUNKEN, borderwidth=2)
        diff_frame.pack(fill=tk.BOTH, expand=True)

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
        # The tag of a skipped difference is configured last, so it draws over the line colours
        self._text.tag_configure("skipped", background="#f6f8fa", foreground="#959da5")
        # The margin is a column left of the +/- gutter. The "current" tag colours it along
        # the lines of the current difference.
        self._text.tag_configure("margin", lmargin1=_MARGIN, lmargin2=_MARGIN)
        self._text.tag_configure(
            "current", lmargin1=_MARGIN, lmargin2=_MARGIN, lmargincolor="#0969da"
        )
        self._text.tag_raise("current")
        for gutter in ("added_gutter", "removed_gutter"):
            self._text.tag_bind(gutter, "<Button-1>", self._on_gutter)
            self._text.tag_bind(gutter, "<Enter>", lambda _e: self._text.configure(cursor="hand2"))
            self._text.tag_bind(gutter, "<Leave>", lambda _e: self._text.configure(cursor="xterm"))

        # --- buttons (frame packed above, before the panes) ---
        ttk.Button(btn_frame, text="⟳ Restart", command=self._on_restart, width=10).pack(
            side=tk.LEFT
        )

        # The Copy switch chooses what a step copies for a program that CLICK already has
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
            btn_frame, text="Copy", command=self._on_action, width=-14, state="disabled"
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

        # _update_action_btn shows this button only for a program that is copied whole
        # because it has many steps
        self._step_through_btn = ttk.Button(
            btn_frame, text=_STEP_THROUGH, command=self._on_step_through
        )

    def _show_source(self) -> None:
        self.title(self._source.title)
        self._title_lbl.configure(text=self._source.title)
        if self._refresh_source is None:
            self._refresh_btn.pack_forget()
        else:
            self._refresh_btn.configure(text=f"↻ Refresh from {self._source.label}")
            self._refresh_btn.pack(side=tk.LEFT, padx=(10, 0))

    def __init__(
        self,
        parent: tk.Widget,
        folder: Path,
        *,
        get_mdb_path: Callable[[], Path | None],
        get_click_hwnd: Callable[[], int | None],
        get_saved_program: Callable[[], SavedProgram],
        get_project_store: Callable[[], AddressStore | None],
        open_staged_nicknames: Callable[[], None],
        source: ProposalSource,
        source_dir: Path | None = None,
        refresh_source: Callable[[], None] | None = None,
        select: tuple[str, list[int] | None] | None = None,
        on_pasted: Callable[[str], None] | None = None,
    ):
        """Open the window on *folder*.

        *source* says where the folder's proposal comes from, which decides what starts
        out taken. *source_dir* is the workspace ``src/plc`` that the folder was just
        exported from. The diff then shows that source as written, and the Address
        Editor handles the nicknames. *refresh_source* copies the folder again from where
        it came from, such as another CLICK window's last save. The window shows a button
        that calls it.
        *select* starts on one program, and may name rungs of it to paste. The
        differences that hold those rungs are taken and the others are skipped.
        *on_pasted* is called with a status message when a CLICK save holds everything
        taken and the window closes itself.

        For a plain folder, nicknames.csv is staged in the store that *get_project_store*
        returns. That store holds the data of CLICK's database. *get_project_store* returns
        None when there is no such store. *open_staged_nicknames* opens the Address Editor on
        the staged nicknames so that the user can Sync.
        """
        super().__init__(parent)
        self.geometry("900x720")
        self.minsize(660, 480)

        self._folder = folder
        self._source_dir = source_dir
        # Where the proposal comes from, which sets what starts out taken
        self._source = source
        self._refresh_source = refresh_source
        self._get_mdb_path = get_mdb_path
        self._get_click_hwnd = get_click_hwnd
        # Returns CLICK's last save of the program as CSVs, in the generated workspace's
        # csv/ folder
        self._get_saved_program = get_saved_program
        self._on_pasted = on_pasted
        self._get_project_store = get_project_store
        self._open_staged_nicknames = open_staged_nicknames

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
        # Program name -> the rung numbers asked for. After the comparison, the differences
        # that hold those rungs are taken and the others are skipped.
        self._selection: dict[str, list[int]] = {}
        # These are per program and for this window only. Skipped differences stay as CLICK
        # has them. Pasted ones are in CLICK but not saved yet. *partial* counts the steps
        # done of the difference begun (a paste, then the rungs to delete).
        self._skipped: dict[str, frozenset[DifferenceKey]] = {}
        self._pasted: dict[str, frozenset[DifferenceKey]] = {}
        self._partial: dict[str, int] = {}
        # Programs that CLICK holds unsaved pastes of, where ClickNick cannot match the pastes
        # to the current comparison. This happens when a new reading of the folder changed
        # the program (_carry_pasted), or when ClickNick cannot read all of CLICK's copy
        # (_record_whole_paste). ClickNick copies these programs whole until CLICK saves.
        self._unplaced: set[str] = set()
        # Programs to step through even though they have many steps (_copied_whole_for_steps)
        self._step_through: set[str] = set()
        # Programs only in CLICK whose keep-or-delete choice is the opposite of the source's
        # default (ProposalSource.deletes_only_in_click, see _kept)
        self._flipped_in_click: set[str] = set()
        # The comparison that the skips and pastes were made on, to carry them over
        self._basis: dict[str, ProgramChange] = {}
        # Programs whose difference has been shown
        self._viewed: set[str] = set()
        self._nickname_path: Path | None = None
        # The folder's nicknames.csv as read (None when there is none, or it is
        # unreadable), whether they are skipped, and how they differ (_refresh_nicknames)
        self._nickname_rows: dict[int, AddressRow] | None = None
        self._nickname_error = ""
        # The fields that nicknames.csv has a column for. Staging leaves the other fields as
        # they are.
        self._nickname_fields: frozenset[str] = frozenset()
        self._nicknames_skipped = not self._source.takes_nicknames
        self._nickname_plans: tuple[NicknamePlan, NicknamePlan] | None = None
        # Program name -> how the program differs from CLICK. A name is missing when
        # ClickNick does not know, for example with no workspace or an unreadable CSV.
        self._changes: dict[str, ProgramChange] = {}
        # Programs that CLICK has and the folder lacks. Each change shows all of the
        # program's rungs as removed.
        self._only_in_click: dict[str, ProgramChange] = {}
        # Folder items that CLICK's last save lacks. A subroutine among them must be created
        # in CLICK first.
        self._missing_in_click: frozenset[str] = frozenset()
        self._click_compared = False
        self._adding_subroutine = False
        self._compare_note = ""
        # The row whose difference the pane shows (the current step, or a row clicked
        # to read), and which of its differences is being looked at
        self._view_name: str | None = None
        self._view_block = 0
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
        # CLICK's save count as last seen (SavedProgram.save_count). A different count means
        # that CLICK saved.
        self._save_count: int | None = None
        # True when CLICK has saved since programs were marked done. The next comparison
        # checks them.
        self._done_unchecked = False

        self._create_widgets()
        self._show_source()
        self.reload(source, source_dir=source_dir, refresh_source=refresh_source, select=select)
        # The session of the project being pasted into. It is kept through a brief
        # disconnect.
        self._project_session = self._saved_program.session
        self.after(_WATCH_INTERVAL_MS, self._watch_saved_program)
        self.after_idle(self._show_first_time_tips)

    def reload(
        self,
        source: ProposalSource,
        *,
        source_dir: Path | None = None,
        refresh_source: Callable[[], None] | None = None,
        select: tuple[str, list[int] | None] | None = None,
    ) -> None:
        """Read the folder again after it was exported, opened or copied again.

        The arguments are the same as for the constructor. Programs already marked done
        stay done unless their rungs changed. What was pasted stays pasted if ClickNick can
        match it to the new reading (_carry_pasted). Skipped differences stay skipped.
        Rungs asked for by number replace the program's choices. If the source is a
        different one (the workspace's export, or the folder itself), the nicknames and the
        programs only in CLICK start over from the new source's defaults. Skips and what
        was pasted stay, because they are about what CLICK holds.
        """
        self._source_dir = source_dir
        if refresh_source is not self._refresh_source:
            self._refresh_source = refresh_source
            self._show_source()
        if source != self._source:
            # A deletion marked done stays a deletion under the new default
            deleted = {
                name for name in self._done if name in self._only_in_click and not self._kept(name)
            }
            self._source = source
            self._flipped_in_click = set() if source.deletes_only_in_click else deleted
            self._nicknames_skipped = not source.takes_nicknames
            self._show_source()
        self._selection = {select[0]: select[1]} if select and select[1] else {}
        if self._selection:
            # Rungs were asked for by number. This is not the user's choice, so it is not saved.
            self._copy_whole_var.set(False)
        self._start(select[0] if select else None, keep_done=True)

    @property
    def shows_workspace_proposal(self) -> bool:
        """Return whether the folder is the export of the workspace's own source."""
        return self._source_dir is not None

    def show(self) -> None:
        """Bring the window to the front. A new Toplevel may not be mapped yet, so deiconify it."""
        self.deiconify()
        self.lift()
        self.focus_force()
