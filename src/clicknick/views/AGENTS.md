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
- `rung apply` writes `csv_output/` with the workspace's `project_to_csv.py`, which `_export_worker` runs.
  While an export runs, `_run_export` moves `csv_output/rung_sources.json` and `csv_output/source_state.json`
  aside. If the export fails, it moves them back. If it succeeds, it records in `source_state.json` the hash of
  each file in `src/plc`, as it read them before the export ran, and the hash of the `rung_sources.json` that
  the export wrote. `rung list <file>` runs no export. It numbers the rungs from the last export's
  `rung_sources.json` if `src/plc` and the manifest still match that record. Otherwise it reads the `# Rn`
  markers. It says so in a note, unless `src/plc` is as ClickNick generated it, because the markers are right
  then.
  pyrung's export refuses `undecoded()`. The worker then names CLICK's program and rung for each call
  (`export_stop_refusal`). Its text never tells the user to delete the call, because the whole paste of that
  program would then delete the rung in CLICK.
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
  programs differ, which rungs differ, and the diff text. It compares rungs by `compare_key`. The window
  calls the same function wherever it asks whether two rungs are the same. The diff text shows the rungs
  that differ as pyrung source. Pyrung source plays no part in the comparison.
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
- A click on a rung's number selects the rung, and CLICK shades it. If the user only clicks into the rung's
  logic, CLICK inserts the paste above that rung and keeps the rung. Insert Rung After Cursor leaves the cursor
  on the new empty rung without selecting it, so a paste there also goes above the empty rung. CLICK 4.00 was
  observed to do both. The status bar shows the same cursor position whether the rung is selected or not. Each
  step that pastes over a rung says to click the rung's number (`_where_to_paste`).
- Delete in CLICK also acts on the selection. With a rung selected, it deletes the rung. With only the cursor in
  the rung's logic, it deletes the instruction under the cursor, and the rung stays. From a selected rung, each
  Shift+Down adds the next rung. From the cursor in the logic, the first Shift+Down selects only the cursor's
  rung, so a selection started there ends one rung short. After a delete of every rung, nothing is selected and
  the cursor is at 1:1:A. A paste there adds exactly the pasted rungs. A paste into a new subroutine does the
  same. In a program with no rungs, a click lower down the number column can select empty rung 2 or 3. A paste
  there keeps the empty rungs above it. CLICK 4.00 was observed to do all of this, with keys and clicks that the
  runner sent.
- Each step that deletes rungs says to click the first rung's number and press Shift+Down until the last rung is
  shaded too (`delete_rungs` in `ladder/program.py`). For one rung, the text says to click its number and press
  Delete. A delete of every rung does not name CLICK's last rung. ClickNick counts only CLICK's last save, and
  CLICK can hold pastes that ClickNick has no record of. A paste into a program with no rungs says to click rung
  1's number first (`_whole_placement`).
- Some texts outside a Review Changes step tell the user to paste a rung again over CLICK's copy of it, because
  ClickNick cannot read that copy. Each one names the steps in order: click the rung's number, then paste
  (`paste_again`). A user who acts as they read would otherwise paste before the click. Most of these texts
  also end with the save. A text that sends the user to their own copy of the program leaves the save out. A
  text about several rungs names the rungs again in its step, such as "each rung that ClickNick cannot read"
  or "each rung in the list". The step can be sentences away from the list. `paste_again` takes these words as
  `which`. These texts are this window's refusals, `prepare_rungs_load`'s refusals, the analysis notices in
  `services/`, the Simulator's refusal to run, the Paste Again box and `clicknick-rung program save`. Each
  such text about a whole program says to delete all its rungs first, and then paste (`clear_before_paste`).
  `paste_again`, `clear_before_paste` and `delete_rungs` live in `ladder/program.py`, which `services/`, the
  views and the CLIs can all import.
- These texts say neither:
  - This window's notes on an old encoding or a rung that ClickNick cannot read (`_legacy_note`,
    `_legacy_line`). The step under each note says how to select the rung, or how to delete the program's rungs.
  - The text about rungs in an old encoding in the Paste Again box and in `clicknick-rung program save`. The
    box offers Review Changes, whose steps say how. A finding can also have no rung number. Review Changes then
    pastes the program whole, and a text about the rung's number would be wrong.
  - The comment of the empty rung that `program_save` writes in place of a rung that it cannot read, such as
    one inside a For loop (`_stand_in`, "Paste it again."). The user sees it in `src/plc/` and in the diff.
    Every message about that rung already says how.
- The runner also saw Ctrl+Shift+End, pressed from rung 1's number, select every rung. The texts name Shift+Down,
  which the earlier texts named, until a person has tried Ctrl+Shift+End. The roadmap's "Open user checks" asks
  Sam to try it.
- The Copy switch's **Whole program** clears the program in CLICK and pastes it in one piece.
- You can take or skip each difference. A difference is one non-equal opcode (`DifferenceKey`). If you skip
  it, CLICK keeps its rungs there. Steps are numbered from what CLICK holds given the skips
  (`steps(skipped, pasted)`). **Whole program** copies `merged(skipped)`. There are two exceptions. One is a
  program whose skipped difference keeps CLICK's legacy-encoded rungs. The other is a program with a comment
  that ClickNick could not read (see "Comments that ClickNick could not read"). The window steps through both.
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
  - It has a comment that ClickNick could not read (`_has_unread_comments`).
- A whole copy of a program with no rungs copies nothing. The step is deleting its rungs in CLICK.
- A program whose CLICK copy ClickNick cannot read is copied whole (`ProgramChange.unreadable`). Two checks
  can refuse that copy. Review Changes runs both before it shows the prompt, and again at the copy.
  `_placeholder_refusal` refuses an empty rung or an UNDECODED marker in the folder. `_dropped_refusal`
  refuses a folder that leaves out a CLICK rung that ClickNick cannot read (`dropped_unreadable`), because the
  whole paste would delete that rung in CLICK. A difference with fewer folder rungs than CLICK rungs drops
  each unreadable rung in it.
- `dropped_unreadable` cannot tell the rung's logic from another rung. It misses a dropped rung when the same
  difference adds a rung in its place. It refuses wrongly when the user writes the rung's logic in its place
  and deletes a rung next to it in the same difference. A finding with no rung number makes every rung
  unequal, so the program is one difference, and a rung added anywhere hides a deleted call.

## Comments that ClickNick could not read

- `program_save` leaves out each rung comment that laddercodec cannot read, and records it in
  `unread_comments.json` (see `ladder/AGENTS.md`). The rung's logic stays, so the rung compares equal to a
  proposed rung with the same logic. The diff then never shows that a paste erases the comment.
- `compare_bundle` reads the record from CLICK's folder. It also reads the record from the proposal's
  folder, if that folder holds one. A copy of another CLICK window holds one. `ProgramChange` lists the
  rungs in `unread_comments_before` (CLICK's) and `unread_comments_after` (the proposal's).
- `compare_bundle` also lists CLICK's record for a program that is only in CLICK, and for each program
  of a folder without `main.csv` (`BundleComparison.unread_comments`). Nothing is compared for that folder,
  but each of its programs is copied whole.
- A paste or a delete in Review Changes loses such a comment in these cases:
  - A step pastes over or deletes CLICK's rung (`unread_comments_in`). A pure delete counts, because the
    rung may have moved.
  - A step pastes the proposed rung.
  - A whole copy writes the program. A record with no rung number counts only here and in the next two.
  - The user deletes CLICK's rungs, because the program is copied whole and has no rungs (`_empty_whole`).
  - The user deletes a program that is only in CLICK. The program may have been renamed.
- Under **Whole program**, and for a program of `_MANY_STEPS` steps or more, the window steps through a
  program that has such a record (`_has_unread_comments`). The steps leave the equal rungs alone.
- Every other paste or delete that loses such a comment asks first (`_agrees_to_lose_comments`), with
  Cancel as the default. The question names each rung. For CLICK's rung, it says that CLICK loses the
  comment. For a proposed rung, it says that the rung arrives without the comment from the proposal's
  source. Each question also says how to keep what CLICK has.
- A delete copies nothing, so there is no Copy to ask at (`_deleted_unread`). The button reads "Delete
  rung N…", "Delete all rungs…" or "Delete program…" until the user clicks OK (`_asks_before_delete`). The
  question says that the user deletes the rungs in CLICK and then clicks "Next". It also says that a moved or
  renamed copy has no comment. After OK, the button reads "Next".
- The guard does not cover a paste made outside Review Changes, such as with `clicknick-rung`.

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
- The step says to make sure that CLICK's main program no longer calls the subroutine, and then to right-click
  the subroutine in CLICK's list of programs and click Delete (`delete_subroutine` in `ladder/program.py`).
  `clicknick-cli rung apply` gives the same steps. No one has checked what CLICK does when its main program
  still calls the subroutine.
- The rows of programs only in CLICK come after the folder's rows, and main comes last of those. So "Next"
  reaches each delete after main's steps. The user can still click the row sooner. While main still has steps
  to do, the prompt says to do them first, because a change to CLICK's main program by hand would move the rungs
  that main's steps name.
- If the folder's main still calls a subroutine that the folder lacks, Review Changes refuses nothing. It pastes
  main with the call and offers to delete the subroutine. pyrung refuses to convert such a folder, unless it is
  the workspace's. The diff then shows the folder's rungs by their instructions.
- CLICK's main program is never only in CLICK, because a folder without `main.csv` is not compared. To empty
  CLICK's main program, the user puts in the folder a `main.csv` that holds only the header row.
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
