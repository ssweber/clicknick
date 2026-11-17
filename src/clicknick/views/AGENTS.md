# Review Changes

These notes cover Review Changes (`views/review_changes_window.py`) and the services that it uses
(`services/rung_diff.py`, `services/click_snapshot.py`, `services/nickname_staging.py`). Views are passive
(rule 4 in the root `AGENTS.md`). The notes for the other windows in this folder are elsewhere. The table at
the end of the root `AGENTS.md` names the file for each one.

## Rule

ClickNick never writes another folder's `nicknames.csv` to CLICK's database directly. **Stage nicknames**
stages them in the store instead.

## The window

- Review Changes is the one window for getting ladder into CLICK. **Ladder > Compare with > Folder** opens it
  on any folder of ladder CSVs. The Workspace's **Review Changes** and `clicknick-cli rung apply` open it on the
  workspace's `csv_output/`. The app keeps one window per folder, and it reloads the window when the folder is
  shown again.
- The window is not modal, because the Address Editor's Sync is part of the same workflow.

## Where the proposal comes from

- A window's `ProposalSource` says where its proposal comes from ("from workspace", "from <folder>"). That text
  appears in the title and in the diff's `+++` header.
- The source also decides what starts out taken. Differences are always taken. The folder's nicknames, and
  deleting programs that are only in CLICK, are taken unless the source is a copy of another PLC
  (`takes_nicknames`, `deletes_only_in_click`). The window keeps the user's choices as they differ from those
  defaults (`_flipped_in_click`).
- When the window is shown as another source, it resets only those two choices. A deletion marked done stays
  done. Skips and what was pasted stay too, because they are about what CLICK holds.
- The caller gives the source (`_show_review_changes(source=)`). The default is `ProposalSource.of`.
- **Compare with > Other CLICK window** lists the CLICK windows other than the connected one. When you pick
  one, ClickNick copies its last save and its database's nicknames into
  `%LOCALAPPDATA%/ClickNick/compare/CLICK (hwnd)/` (`services/click_snapshot.py`). It replaces that folder whole
  each time. It shows the folder as `ProposalSource.other_click`. **↻ Refresh from <project>** copies it again
  (`refresh_source`).
- Each refresh of the window list, startup included, deletes the copies of windows that are not in the list.
  It keeps a copy that is, or holds, a folder that an open Review Changes window shows
  (`remove_stale_snapshots`).

## The comparison

- `services/rung_diff.py` is the one comparison of a CSV bundle with CLICK's last save (`csv/`). It finds which
  programs differ, which rungs differ, and the diff text. It compares rungs by `rung_fingerprint`. The diff text
  shows the rungs that differ as pyrung source. Pyrung source plays no part in the comparison.
- ClickNick reads the folder once (`load_bundle`) and compares and copies from memory. A CLICK save generates
  the workspace again and deletes `csv_output/`, and the window must still know whether what it pasted landed.
- Given the workspace source (`source_dir`), the diff shows that source through the exporter's
  `rung_sources.json`. There is no nicknames step. Workspace tags go through `tag apply`.
- ClickNick shows any other folder by converting its CSVs with pyrung. When pyrung refuses the conversion, the
  diff says why (`BundleSources.error`).
- ClickNick reads that folder's `nicknames.csv` with the reader that pyrung uses (pyclickplc's `read_csv`,
  through `CsvDataSource`). So staging refuses a bad Address, a bad Data Type or an extra cell too. A nickname
  used twice loads, and the store flags it, though pyrung refuses the file.

## Steps

- CLICK pastes over the selected rung. The first pasted rung replaces that rung, and the rest go in below it.
  `ProgramChange.steps` turns a program's differences into steps on that basis. It works from the top, so each
  step's rung numbers are the ones that CLICK shows. A step pastes over one rung, pastes over a new empty rung,
  or deletes rungs.
- The Copy switch's **Whole program** clears the program in CLICK and pastes it in one piece.
- You can take or skip each difference. A difference is one non-equal opcode (`DifferenceKey`). If you skip
  it, CLICK keeps its rungs there. Steps are numbered from what CLICK holds given the skips
  (`steps(skipped, pasted)`). **Whole program** copies `merged(skipped)`. The exception is a program whose
  skipped difference keeps CLICK's legacy-encoded rungs. The window steps through that program.
- A difference locks once its step is done ("Next"), not when it is copied. Every difference of a program
  locks while one of its steps is half done.
- Choices last only as long as the window. `carry_skipped` moves them onto the comparison after a CLICK save.
- Under "Changed rungs", the window still copies a program whole when its steps number `_MANY_STEPS` (6) or
  more. These are the exceptions (`_copied_whole_for_steps`):
  - Its paste as chosen (`merged`) has `_SLOW_PASTE_RUNGS` (100) rungs or more.
  - CLICK holds legacy-encoded rungs of it. A whole paste would paste the skipped rungs again from ClickNick's
    reading of them.
  - A step of it is done.
  - Its rungs were asked for by number.
  - The user clicked **Step Through** for it.
- A whole copy of a program with no rungs copies nothing. The step is deleting its rungs in CLICK.

## What was pasted

- What was pasted (`_pasted`, `_partial`) is in CLICK until CLICK saves. A whole copy counts every difference
  as taken. `SavedProgram.save_count` tells ClickNick when CLICK saves (`_note_saves`).
- A Sync rebuild, a Reload or a failed build keeps what was pasted, and so does the Copy switch.
- Suppose the folder is read again before a save. If CLICK would hold the same rungs, the window places the
  paste in the new comparison (`_carry_pasted`). Otherwise it copies that program whole until CLICK saves
  (`_unplaced`), whatever the comparison or the skips say. It treats a program copied whole without a
  comparison the same way.
- **Restart** asks before it forgets what was pasted.
- On the first comparison after a save, a program or deletion marked done may still show as to do in CLICK's
  save. It becomes a step again, unless ClickNick cannot read all of CLICK's copy of it.

## Other rows

- A folder CSV that ClickNick cannot read is left out (`_left_out`), with a notice. It gets no step, and it does
  not hold the window open.
- A program that is only in CLICK (`only_in_click`) is a row like the others. If it is taken, its step is
  deleting it in CLICK. "Next" marks it done, and a CLICK save that still has it makes it a step again. If you
  untick **Delete it in CLICK**, the window keeps the program (`_kept`). A kept program does not hold the window
  open.
- **Stage nicknames** stages the fields that the file sets as one edit in the store
  (`services/nickname_staging.py`). It stages only the addresses that the file lists. Then it opens the Address
  Editor on Changed with **Sync and Close**. The row compares the file with the store's visible rows to find
  what is left to stage, and with the base rows to find what is not synced. The row is done once CLICK's
  database has the fields. You can skip it.

## When the window closes

- The window closes itself when a CLICK save holds everything that it was pasting.
- If a save leaves work to do, the window stays open with a notice. For the workspace's source, the notice says
  that the edited source is then in `backup/src/plc`.
- **Reload from CLICK** closes the windows that show the workspace's edits, because it throws those edits away.
  A window on another folder stays open.
