# ClickNick Agent Guidance

**IMPORTANT: DON'T USE `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

## Writing

Prose in this repo follows the `writing` skill in the bob plugin (`/bob:writing`, or `skills/writing/SKILL.md` in https://github.com/ssweber/bob). Read it before you write a commit message, a changelog entry, docs, a docstring, a comment, a message or UI text. The rules below are only the ones specific to this repo.

- The Unreleased section of `CHANGELOG.md` moves with what a user sees, in every pull request. Docs (`docs/`, `docs/help/`) change only where what a user does changes.

## Project Overview

**ClickNick** is a Windows desktop application (Windows 10/11, Python 3.13+) with nickname autocomplete and
editing tools for CLICK PLC Programming Software (v2.60–v4.00). It reads and writes nicknames in the project's
Access database (SC_.mdb) through Access ODBC or the built-in Windows Jet fallback, or imports them from CSV.
Core components:

- **Overlay** – Positions a combobox over instruction dialog edit controls for nickname autocomplete
- **Address Editor** – Tabbed tksheet editor with search/replace, block tagging, validation. Each tab shows ALL
  memory types in one scrollable view
- **Tag Browser** – Treeview of nicknames parsed by underscore segments and array indices
- **Dataview Editor** – Edits .cdv files with nickname lookup from shared address data
- **Review Changes** – Steps ladder from a folder of CSVs into CLICK
- **Simulator** – Runs the workspace's program in pyrung, with an I/O panel and a command console

## Build & Development Commands

```bash
# Install dependencies
make install                    # or: uv sync --all-extras --dev

# Default workflow (install + lint + test)
make

# Individual commands
make lint                       # Run ruff (check + format)
make test                       # Run pytest (ALWAYS use this, not uv run pytest)
make build                      # Build wheel with uv

# Run the app
uv run clicknick                # Run the app

# Install as editable local tool
uv tool install --editable .
```

## Architecture

### Entry Points
- `clicknick` (GUI) - calls `clicknick:main`; main app: `src/clicknick/app.py` -> `ClickNickApp`
- `clicknick-cli` - `clicknick.live.cli:main`; `clicknick-rung` - `clicknick.ladder.cli:main`
  (see `src/clicknick/ladder/AGENTS.md`)

### Package Structure

```
src/clicknick/
├── app.py                 # Main ClickNickApp class
├── config.py              # AppSettings with persistence
├── data_session.py        # DataSession: current store + Dataview model + editor windows
├── connection_session.py  # ClickConnection + ConnectionSession (watch, workspace, analysis, simulation)
├── connection_controller.py  # ConnectionController: window list, connect, project change, watch tick
├── simulation_session.py  # SimulationSession: pyrung DAP + Modbus + simulator settings (no tkinter)
├── workspace_controller.py  # WorkspaceController: the Workspace group, its menu entries, Workspace setup
├── models/                # Data models and constants
│   ├── address_row.py     # Frozen dataclass for address data
│   └── mutable_row_builder.py  # Builder for accumulating changes
├── data/                  # Data storage and state management (no tkinter)
│   ├── address_store.py   # Core store: base/overlay/visible layers, undo/redo, _derive
│   ├── edit_session.py    # Builder-backed session yielded by store.edit_session()
│   ├── cdv_file.py        # DataView folder discovery and CDV verification
│   └── undo_frame.py      # Undo/redo snapshot storage
├── services/              # Business logic (pure Python, no tkinter)
├── utils/                 # Utilities (filters, MDB, Win32)
├── ladder/                # Clipboard I/O and the clicknick-rung CLI
├── live/                  # clicknick-cli and the server it talks to in the app
├── views/                 # Windows and panels (passive observers)
│   ├── address_editor/    # Address Editor views
│   ├── dataview_editor/   # Dataview Editor views
│   └── nav_window/        # Tag Browser (outline, blocks)
├── widgets/               # Reusable UI components
├── detection/             # Window detection for Click.exe
└── resources/             # Icons and static assets
```

## Key Architectural Patterns

### Immutable Base + Overlay Model

The store keeps three layers:

1. **Base Layer** (`base_state`) - Latest snapshot from the external database (source of truth)
2. **Overlay Layer** (`user_overrides`) - Sparse dictionary of unsaved edits. It maps each `addr_key` to a
   read-only `{field: value}` that holds only the fields the user set. It has no row copies and no dirty markers
3. **Visible Layer** (`visible_state`) - Computed projection of base + overrides

- **Inputs vs derived:** base rows and the user's overrides are the inputs. One method, `AddressStore._derive()`,
  computes everything else: visible rows, validation, dirty fields, the nickname index and block
  colors. It computes them in one fixed order, after every change (edit, undo, redo, discard, save,
  external reload)
- **External Updates:** Database refreshes update the base layer and keep user overrides

### Edit Session Pattern

1. **View** opens `AddressStore.edit_session(description)`
2. **Service** accumulates changes via `session.set_field(addr_key, field, value)`. The session keeps a
   `MutableRowBuilder` per row. Many changes make one undo frame (fill-down 500 rows = 1 undo)
3. **On clean exit,** the session applies cascades and freezes the builders into overrides. A nickname or comment
   is stored without a space at either end (`trim_entry`), which is how CLICK stores it too. If the overrides
   changed, the session pushes an undo frame that holds the overrides from before and clears redo. Then it runs
   `_derive()` and notifies. A session that changes nothing is not an undo step
4. **On an exception,** nothing is committed (all-or-nothing). If the commit itself fails, the session restores
   the inputs
5. **All Views** receive the changed `addr_keys` and refresh only those rows

Cascades (`AddressStore._apply_cascades`): a Retentive change mirrors across the T/TD or CT/CTD pair. A row's
block tag can change, judged by the old tag against the new tag and not by the comment text. Then
`BlockService` updates the matching open or close tag and the `_D` tags of the pairs. It renames them in place or
removes them. If the pair is untagged and the tag was added or renamed, it appends them.
`_apply_cascades` records which fields the caller set before any cascade runs. A cascade never
writes one of those fields.

**The Rules** (`tests/test_store_boundaries.py` enforces rules 2, 3 and 5. For rule 5 it checks that nothing
outside the store touches `_current_session`):
1. **Models are Immutable:** `AddressRow` is `frozen=True`. Every change creates a new instance
   (`dataclasses.replace()`)
2. **AddressStore is the Gatekeeper:** Only `AddressStore` writes its layers (`base_state`, `user_overrides`,
   `visible_state`, `block_colors`, `row_order`)
3. **Services and data are Pure Logic:** `services/`, `data/` and `simulation_session.py` **never** import
   `tkinter`
4. **Views are Passive:** Views look up rows through `store.visible_state[addr_key]` and listen for change
   notifications. Nothing keeps a row reference across a change
5. **Every edit goes through `store.edit_session()`:** write through the session it yields, and never touch
   `store._current_session`
6. **One home per fact:** the current data lives in `ClickNickApp._data` (a `DataSession`). The connected CLICK
   window lives in `ClickNickApp._session` (a `ConnectionSession`). The session holds its `click` (an immutable
   `ClickConnection`), its workspace `pairing`, the connection watch, the autocomplete popup and the Workspace
   setup window. `ClickNickApp._click` reads it. Consumers receive getters, not copies
7. **No compatibility shims:** when an API changes, update its callers. Do not keep aliases or wrappers

### Observer Pattern

- `add_observer(callback)`; `callback(store, changed_keys: set[int] | None)` receives the affected `addr_key`s
- The store replaces changed rows in the shared unified view before it notifies. Observer exceptions are logged

## Key Dependencies

`pywin32`, `pyodbc`, `tksheet` v7 (https://ragardner.github.io/tksheet/DOCUMENTATION.md), `pyrung`, `laddercodec`,
`pyclickplc`, all pinned exactly in `pyproject.toml`; `tkinter` (stdlib).

## Testing

Tests are in `tests/` and `src/` (pytest discovers both).

**Core data tests:**
- `test_address_store.py` - Store operations, undo/redo, base+overlay merging, cascades, derived-state regressions
- `test_store_oracle.py` - Random edit/undo/redo/discard/Sync/CLICK-write sequences. The kept state must equal a
  full rebuild from the same inputs, and each edit must follow the cascade rules
- `test_store_cascades.py` - Block tag and Retentive cascades: T/TD and CT/CTD pairs, open/close renames in place
- `test_store_boundaries.py` - Source-level rules: only the store writes its layers, no tkinter in data/services
- `test_data_session.py` - Window lifecycle and save prompts when data is closed or replaced
- `test_mutable_row_builder.py` - Builder pattern, `changes()` output
- `test_address_model.py` - AddressRow validation, frozen dataclass behavior

**Service tests** (no tkinter):
- `test_block_service.py` - Block tag parsing, color assignment, range detection
- `test_row_service.py` - Fill down, clone structure, edit session integration
- `test_blocktag.py` - Tag parsing edge cases

## Key Implementation Notes

### Dirty State Detection
- Check via `store.is_dirty(addr_key)` / `store.is_field_dirty(addr_key, "nickname")`
- `_derive` first drops the override fields that the base already holds. So a field is dirty exactly when it is
  in its row's override

### Sync
- `save_all_changes` raises while any rows have validation errors, for every caller. For the database it first
  reads SC_.mdb, because CLICK writes it while connected. So the rows it writes carry CLICK's current values in
  the fields the user did not change
- CLICK's ladder paints nicknames from a table that TagDB.dll keeps in memory. It shows the names from a Sync
  only after that table reloads, and no window message reloads it. `services/click_redraw.py` forces the reload.
  It imports a header-only CSV through CLICK's File > Import > Nickname (WM_COMMAND 32900, CLICK 2.60-4.00) in
  Merge (Project priority) mode. That leaves SC_.mdb as it was, though CLICK then counts the project as changed.
  The redraw starts only while CLICK shows its main window alone, enabled and answering. It presses only the
  mode's radio button, Open and the one button of the "Completed!" box. It recognises the import's Open dialog
  by its three import modes and its control ids, never by Windows' own strings. If the redraw fails while that
  dialog is the only other window open, it cancels the dialog. It leaves any other window to the user, including
  an Open dialog it did not recognise. Tests drive it through a fake `ClickDesktop`. It was checked live after a
  Sync on CLICK 2.60, 3.43, 3.71, 3.92 and 4.00.
  `save_all_changes` calls the store's sync listeners (`add_sync_listener`) once it has written rows into the
  database. Every Sync path goes through it: the Address Editor's Sync and Sync and Close, and Yes to a save
  prompt. The app's listener runs the redraw for the connected window off the Tk thread
  (`ConnectionController.redraw_nicknames`). A request made while a redraw runs waits and runs once, after that
  redraw ends. **Tools > Redraw Nicknames in CLICK** works the same way. A redraw's result and a pending request
  belong to the CLICK window (its hwnd). If another window is connected, or none, they are dropped. A skipped or
  failed redraw shows as a status line and never fails the Sync
- `loaded_with_error` marks an X, SC or SD nickname from CLICK that breaks our nickname rules.
  The flag exempts it from those rules. One helper, `_flag_loaded_error`, sets it on every base row,
  on load, reload and Sync alike
- One edit session, "Trim spaces" (`_stage_trims`), trims a loaded nickname or comment that has a space at either
  end. It covers the rows that a load or a read of the data source (file monitor, Sync's pre-read) changed, and
  every row after a Discard. Sync writes the trim. An undone trim comes back only when the data source changes
  that row. A field the user edits is left as it is. A nickname flagged `loaded_with_error` is trimmed too. Once
  it is shown trimmed, the flag is off and `_validate_row` exempts only its format, so its duplicates are
  reported (`_is_trimmed_loaded_nickname`). No SC/SD name in pyclickplc's table has an edge space. CLICK
  generates the X `_IO` names. No table lists them, so nothing shows that they have no edge space.
  Rows read while a session is open wait until it ends (`_pending_trims`)

### Undo/Redo
- Undo and Redo track only the overlay layer (user intent), up to `MAX_UNDO_DEPTH` (50) frames
- A successful Sync or Save, or a Discard, clears Undo/Redo, because frames hold override snapshots and not old
  values. A CLICK save does not clear them
- When the database comes to match an unsaved field, that field stops being an edit (`_rebase_override`, run by
  `_derive`)

### Block Colors
- Stored in `AddressStore.block_colors`, NOT in `AddressRow`, and not part of undo/redo. Read them with
  `store.get_block_color(addr_key)` (color name or None)
- `compute_block_colors` is the one implementation that derives them from comments (block tags)
- Duplicate block names: the first definition in address order is valid, and later ones are flagged

### Program Analysis
- One build worker runs per connection. Requests made while it runs collapse into one follow-up build.
  `ConnectionSession.start_analysis` queues no build while one runs, since that build serves the request. It
  makes the ScrWatcher once per session. The watcher holds the count of tags synced since CLICK last saved
- Publishing a build swaps `csv/` and `src/plc` as a pair and records the generation last. So a workspace never
  holds `csv/` from one save and `src/plc` from another
- If a build fails before it publishes, `project_dir` stays at an earlier save (`project_is_current` is False),
  and Review Changes then has nothing to compare with
- `SavedProgram.save_count` is the one signal that CLICK saved. Only the ScrWatcher raises it, once per save,
  after a change and once the Scr*.tmp files (checked every 500 ms) are unchanged on two checks in a row. A Sync
  rebuild, Reload from CLICK, a workspace change, a retry and a failed build leave it as it was
- `AnalysisService.status` reads BUILDING until a build finishes that serves every request made so far
  (`mark_building` returns the count, and `build(serves=)` takes it). Suppose a build of the files from before a
  save publishes while the save's build is queued. The status stays BUILDING. So no reader (`saved_program()`,
  `rung apply`, the Workspace status, the simulation) pairs a new save with the `csv/` of the save before.
  Suppose a request fails before it is queued (`mark_failed` without `serves`: no database, no Scr*.tmp) while a
  build runs. The status stays BUILDING. The failure shows once the build that serves every request finishes,
  unless a later request replaced it
- The generated code, the persisted project and the tag map all come from one nickname snapshot read from
  CLICK's database. The tag names are the ones that pyrung's own reader gives that snapshot's `nicknames.csv`
  (`services/tag_names.py`). They therefore match the code, whatever pyrung does with spaces. ClickNick edits
  reach analysis on the next build after Sync.
  `clicknick-cli` finds tags by the workspace's names (`project_tag_to_addr_key`)
- `csv/analog_inputs.json` records the analog inputs a workspace was generated with. `tag apply` regenerates
  its baseline `tags.py` with them, never from CLICK's Project.ini at the time it runs
- `backup/src/plc` is the newest backup of `src/plc`. A backup is taken before a build replaces edited source,
  on `clicknick-cli backup`, and when a chosen workspace's edits are kept. Each new backup first moves the
  current one to `backup/older/<YYYYMMDDTHHMMSSZ>/src/plc`. The folder is named in UTC by the time the backup
  was taken (`backup/backup-time.txt`). When that file cannot be written, the backup's files are dated to that
  time instead. If any kept backup already holds the tree, no new backup is made, and that backup becomes the
  newest. The oldest backups are deleted so that 5 are kept in all (`KEPT_PLC_BACKUPS`). Each is renamed out of
  the listing before it is deleted, and deletion happens only once the whole backup or restore succeeded. If
  one fails, `src/plc` stays as it was and no backup is deleted. Nothing refuses a save or a backup because of
  this
- `clicknick-cli restore` takes the newest backup, and `restore <time>` takes an older one. It copies the chosen
  backup aside. Then it backs up `src/plc` if that differs from both the last generation and the chosen backup,
  and replaces `src/plc`. Its pruning keeps the restored backup, so six may be kept until the next backup
- A build, backup or restore that succeeds leaves the edits that `src/plc` held as the newest backup (or in
  `src/plc`, as the backup it restored). A tree that was once in a backup, or that was in
  `src/plc` with edits when a build, backup or restore began, can be deleted only after 5 newer
  backups are kept. `tests/test_backup_oracle.py` checks these rules over random edits, builds,
  backups and restores, with injected copy, move, time-file and prune failures
- Each workspace folder has one lock (`workspace_writing`). A build's publish holds it from its backup of edits
  to the generation record. `backup`, `restore` and choosing a workspace hold it throughout. The build waits for
  the lock. The others run on the Tk thread, so they are refused (`WorkspaceBusyError`) and do not freeze the
  window. `clicknick-cli` commands that read the workspace are refused the same way while the analysis is
  BUILDING (`_get_project_dir`)

### Review Changes
- This is the one window for getting ladder into CLICK (`views/review_changes_window.py`). **Ladder > Compare
  with > Folder** opens it on any folder of ladder CSVs. The Workspace's **Review Changes** and
  `clicknick-cli rung apply` open it on the workspace's `csv_output/`. The app keeps one window per folder and
  reloads it when the folder is shown again
- A window's `ProposalSource` says where its proposal comes from ("from workspace", "from <folder>"). That text
  appears in the title and in the diff's `+++` header. The source also decides what starts out taken. Differences
  are always taken. The folder's nicknames, and deleting programs that are only in CLICK, are taken unless the
  source is a copy of another PLC (`takes_nicknames`, `deletes_only_in_click`). The window keeps the user's
  choices as they differ from those defaults (`_flipped_in_click`). When the window is shown as another source,
  it resets only those two choices. A deletion marked done stays done. Skips and what was pasted stay too,
  because they are about what CLICK holds. The caller gives the source (`_show_review_changes(source=)`; by
  default `ProposalSource.of`)
- **Compare with > Other CLICK window** lists the CLICK windows other than the connected one. When you pick one,
  ClickNick copies its last save and its database's nicknames into
  `%LOCALAPPDATA%/ClickNick/compare/CLICK (hwnd)/` (`services/click_snapshot.py`, replaced whole each time) and
  shows that folder as `ProposalSource.other_click`. **↻ Refresh from <project>** copies it again
  (`refresh_source`). Each window-list refresh (startup included) deletes the copies of windows that are not in
  the list. It keeps a copy that is, or holds, a folder that an open Review Changes window shows
  (`remove_stale_snapshots`)
- `services/rung_diff.py` is the one comparison of a CSV bundle with CLICK's last save (`csv/`). It finds which
  programs differ, which rungs differ, and the diff text. It compares rungs by `rung_fingerprint`.
  The diff text shows the rungs that differ as pyrung source. Pyrung source plays no part in the
  comparison
- CLICK pastes over the selected rung. The first pasted rung replaces that rung and the rest go in below it.
  `ProgramChange.steps` turns a program's differences into steps on that basis. It works from the top, so each
  step's rung numbers are the ones CLICK shows. A step pastes over one rung, pastes over a new empty rung, or
  deletes rungs. The Copy switch's **Whole program** clears the program in CLICK and pastes it in one piece
- You can take or skip each difference (one non-equal opcode, `DifferenceKey`). If you skip it, CLICK keeps its
  rungs there. Steps are numbered from what CLICK holds given the skips (`steps(skipped, pasted)`). **Whole
  program** copies `merged(skipped)`. The exception is a program whose skipped difference keeps CLICK's
  legacy-encoded rungs, which is stepped through. A difference locks once its step is done ("Next"), not when it
  is copied. Choices last only as long as the window. `carry_skipped` moves them onto the comparison after a
  CLICK save
- What was pasted (`_pasted`, `_partial`; a whole copy counts every difference as taken) is in CLICK until CLICK
  saves. `SavedProgram.save_count` tells ClickNick when that happens (`_note_saves`). A Sync rebuild, a Reload or
  a failed build keep it, and so does the Copy switch. Suppose the folder is read again before a save. If CLICK
  would hold the same rungs, the paste is placed in the new comparison (`_carry_pasted`). Otherwise that program
  is copied whole until CLICK saves (`_unplaced`), whatever the comparison or the skips say. A program copied
  whole without a comparison is treated the same way. **Restart** asks before it forgets what was pasted. On the
  first comparison after a save, a program or deletion marked done may still show as to do in CLICK's save. It
  becomes a step again, unless ClickNick cannot read all of CLICK's copy of it
- A whole copy of a program with no rungs copies nothing. The step is deleting its rungs in CLICK
- ClickNick reads the folder once (`load_bundle`) and compares and copies from memory. A CLICK save regenerates
  the workspace and deletes `csv_output/`, and the window must still know whether what it pasted landed
- The window closes itself when a CLICK save holds everything it was pasting. If a save leaves work to do, the
  window stays open with a notice (the edited source is then in `backup/src/plc`). **Reload from CLICK** closes
  it, because that throws the edits away. The window is not modal, because the Address Editor's Sync is part of
  the same workflow
- Given the workspace source (`source_dir`), the diff shows that source through the exporter's
  `rung_sources.json`, and there is no nicknames step (workspace tags go through `tag apply`). Any other folder
  is shown by converting its CSVs with pyrung. When pyrung refuses the conversion, the diff says why
  (`BundleSources.error`). ClickNick reads that folder's `nicknames.csv` with the reader pyrung uses (pyclickplc's
  `read_csv`, through `CsvDataSource`). So a bad Address, Data Type or extra cell is refused for staging too. A
  nickname used twice loads (the store flags it), though pyrung refuses the file
- Under "Changed rungs", a program is still copied whole when its steps number `_MANY_STEPS` (6) or more. The
  exceptions are these: its paste as chosen (`merged`) has `_SLOW_PASTE_RUNGS` (100) rungs or more; CLICK holds
  legacy-encoded rungs of it (a whole paste re-pastes skipped rungs from ClickNick's reading); a step of it is
  done; its rungs were asked for by number; or the user clicked **Step Through** for it
  (`_copied_whole_for_steps`). Every difference of a program locks while one of its steps is half done
- A folder CSV that cannot be read is left out (`_left_out`), with a notice. It gets no step, and it
  does not hold the window open
- A program that is only in CLICK (`only_in_click`) is a row like the others. If it is taken, its step is
  deleting it in CLICK ("Next" marks it done, and a CLICK save that still has it makes it a step again). If you
  untick **Delete it in CLICK**, the program is kept (`_kept`), and a kept program does not hold the window open
- ClickNick never writes another folder's `nicknames.csv` to CLICK's database directly. **Stage nicknames**
  stages the fields the file sets as one edit in the store (`services/nickname_staging.py`, only for the
  addresses it lists) and opens the Address Editor on Changed with **Sync and Close**. The row compares the file
  with the store's visible rows (left to stage) and base rows (not synced). It is done once CLICK's database has
  them, and you can skip it

### Simulation
- `ConnectionSession.simulation` (a `SimulationSession`) is the one home of the simulated PLC. It holds the
  pyrung DAP subprocess, its Modbus client, the switch, analog and force settings, and their persistence
  (`services/sim_state.py`)
- It runs headless. `turn_on()` starts it (opening the Simulator does this). Only `turn_off()` (the Start/Stop
  beside the main window's Test legend) or connection teardown stops it. Closing windows never does. The on/off
  state is not persisted: at app start, nothing launches a subprocess or listens on port 502
- The Simulator (its Console pane is `views/console_panel.py`) and the Dataview editor only observe the
  simulation. The Dataview attaches while the simulation serves Modbus. Views never own a `DapService`. While
  the simulation is off, they stay open and offer Start
- It launches with `keepForcesOnRun`, so forces survive STOP -> RUN. Switch and analog patches ride
  `set_mode("run")`
- ClickNick reads values over Modbus. Inputs (switch and analog patches), mode, speed, stepping, forces and links
  go over DAP. The Dataview reads and writes values over Modbus, with the same client as for a real CLICK. X
  stays read-only there, as on a real CLICK, and its Force column goes through the simulation. Mode, speed and
  forces follow frames, because the Console and agents can drive the same simulation (the last command wins)
- Panel mutations (switches, analog values, forces, mode, step, speed, links) go as structured DAP requests
  today. Add no new one. The next release will send them as pyrung command lines with a source such as `panel`
  (**commands are text with a source; state is data; the write is a plan**), over the connection the session
  already has. The command language lives in pyrung, and ClickNick will send lines verbatim. Today the Console
  pane splits a line on `;` (`ConsolePanel._submit_command_text`), and its `autoreload` and `reload` refusals
  rely on that. The split goes with the rework. So does ClickNick's own echo, once pyrung broadcasts the command
  text. Frames, force and link listings, Modbus info and causal queries stay structured reads. The program write
  stays `pyrungReload` with its carry plan, and launch and terminate stay structured
  (`scratchpad/visual-simulator-design.md`, "Commands and recording")
- A user action emits an `echo` event with the equivalent console command (tag names via `to_tag()`), and the
  console pane shows it as a comment. Only actions that reach a running simulation echo. Analog values echo once
  they settle
- Bench links are session-only feedback wiring (`sim_state.BenchLink`, keyed by feedback address). They are
  desired state, like forces. ClickNick persists them, re-applies them over DAP after a launch, and adopts them
  from the simulation when a frame's `linksRevision` changes (the Console can edit them too). "Save to project"
  writes the link into the feedback's comment through the store (Simulator window,
  `services/link_annotation.py`). After Sync and a rebuild, pyrung drops the bench copy, because the program
  declares the same link
- Desired state (switches, forces, bench links) is keyed by CLICK address and never holds a tag name. pyrung
  reports tag names. ClickNick maps them with the names of the program the simulation runs (`_tag_maps`: the
  workspace's `project_tag_to_addr_key`, taken at launch and at each write). So a rename in CLICK does not move
  them until that program is written. `load_state` reports entries that are not addresses
- pyrung's autoreload is off. A changed program reaches the simulation only when the user writes it. Two events
  offer a write as `program_change`. One is a new analysis generation: a CLICK save, or "rebuilt" when the save
  count did not move, as after Reload from CLICK or a Sync. The other is an edit to the workspace's `src/plc`
  (`PlcSourceWatch`, on the 2 s watch tick). In RUN, the offer is **RUN Time Edit** (reload and continue: values,
  timers and forces stay) or **Stop and Write** (reload, STOP, RUN again in the same process: pyrung keeps
  retentive values and forces and clears the rest). In STOP or while stepping, the offer is **Write** (values and
  mode stay). A Console `reload` writes for the current mode. The Console pane refuses `autoreload`. An agent on
  `pyrung live` can still reload, or change forces while a write runs. A build that fails is a notice, and the
  old program keeps running.
  When a build finishes for the program the simulation already runs (a Sync or Reload from CLICK that leaves it
  as it was), no write is offered. Its tag names, `src/plc` and `run.py` are the ones read at the launch or
  write (`PlcSourceWatch.same`; a file that could not be read either time is no proof). The watch tick and each
  frame compare a build once (`_examine_build`). `program_change` only reads the result, and it offers nothing
  for a build that has not been compared yet
- One check says whether the workspace's program can run (`_workspace_problem`: converted, current, a `run.py`,
  no rung ClickNick cannot read). Start, a write and Restart all use it. If it refuses a write or a Restart, the
  simulation keeps running and a notice says why
- A write (`_write_program`) is one job on the action worker. The Console refuses commands until the write is
  answered. No write is offered while a Console command runs, and Restart waits for the write. Console commands
  run through `run_console_command`, which counts them in flight until each one returns. So closing the pane
  mid-command does not hold writes back. While that count is above zero (`console_busy`), every
  pane shows busy and offers Stop. The offer to write says that a Console command is still running.
  An agent on `pyrung live` can still change forces and links while a write runs. The write reads pyrung's force
  and link listing, which is the truth whatever the Console did since the last frame. `plan_carry`
  (`services/program_carry.py`) decides each entry's name in the new program. One `pyrungReload`
  (`DapService.planned_reload`, pyrung 0.16) takes the plan (`CarryPlan.as_dap()`). pyrung pauses a running
  continue first, keeps the mode, and places each entry. An entry that the plan leaves out (one the Console added
  after the listing) keeps its name:
  - A bench link follows its names while they exist, and the notice says when one now sits on another address.
    Otherwise it stays on the address under its new name. When two links land on one feedback, the one that
    followed its name wins and the other is dropped
  - A force stays on its address under the new name on a pure rename (an unnamed address that gains a nickname
    counts as one). A force whose name now sits on another address stays only on X, Y or an analog channel's DF.
    On internal memory it is released
  - A link that the program declares and runs (`declared`) follows its feedback's name while the new program
    declares a link on that name (from the workspace's `csv/nicknames.csv`, `linked_feedbacks`). When the name is
    gone, or sits on an address with no declared link, its coil carries on at its address under the new name. A
    bench link or declared link that moves keeps its coil's state, so a timer part way through carries on
- The offer lists releases, drops and moves before the user writes. After the reload, pyrung's report
  (`carried`) is the truth. ClickNick adopts the entries it placed, by address. The notice
  (`CarryPlan.written`) keeps the plan's notes for the entries placed as planned. It also says why pyrung could
  not keep any other entry. It does not list a drop that loses nothing, such as a link the program now declares.
  Suppose a write is answered after another build started. It keeps the old names and offers the change again.
  No build counts as run until the next write or launch, because which program pyrung read is unknown. The
  switch shows the position it had until the write is answered
- A reload that fails changes nothing in pyrung. The old program keeps running with its forces and links. (A
  write made in RUN sends continue again, since pyrung may have paused.) **Restart** is added to the offer. A
  pyrung without `pyrungReload` refuses the write the same way, with a notice that it needs pyrung 0.16.0.
  Nothing falls back to releasing and re-sending entries around a plain reload. Suppose pyrung never answers a
  reload. ClickNick then sends nothing by name, because which program runs is unknown, and offers Restart. Its
  notice says the simulation may be paused and names what the plan releases. The switch position stays the
  user's (`_position_held`). So Restart starts in that position, and the write offered is for it, until the user
  moves the switch
- Restart (also on the toolbar) relaunches on what the workspace holds now, from power-on values or the PLC data
  file, with the same desired state and switch position. Several events do the same:
  - Start.
  - A PLC data file change.
  - A Modbus port change. If it is seen during a write, the relaunch comes once the write is answered, unless the
    simulation relaunched meanwhile. If it is seen while a build runs, the relaunch comes once the build ends
    (`_restart_due`).
  - A simulation that failed to start, once a later build converts (`_follow_program`).

  A workspace move relaunches without the check (`relaunch`), and it waits out the build
- `_reapply` (after a launch) sends every entry, even when one goes unanswered. An unanswered entry stays set and
  is reported, and an unanswered link listing is asked for again on the next frame
- A failed DAP request undoes the user's action only when the simulation that was asked refused it. It does not
  undo it when the simulation has since stopped or restarted (token check) or never answered
  (`DapUnavailableError`)

### Main Window Refresh
- `ClickNickApp._refresh_ui()` recomputes the window title and the Workspace details. Never call it by hand
- Assigning `_data` or `_session` (`_ShownState` attributes) schedules one coalesced idle refresh.
  `ConnectionSession` events (sync count, analysis progress, staged rungs) and Workspace setup pairing another
  workspace call `_request_ui_refresh()`
- `_refresh_ui` also re-titles the open editor windows, skipping one that is being destroyed. They take the
  project name and analysis as getters, so they follow a project change

### Connection and Lifecycle
- `ConnectionController` (`ClickNickApp._connection`) lists the CLICK windows, connects, follows a project change
  and runs the watch tick. It writes the session and the data only through the app (`_session`, `_open_data`,
  `_close_data`). `WorkspaceController` (`ClickNickApp._workspace`) runs the Workspace group, its menu entries
  and Workspace setup. It reads the session through the app each time
- Connecting opens a `ConnectionSession` before CLICK's database loads. A project change replaces the session.
  `ConnectionController.close_session` is the one teardown (the database load in flight, the watch, the popup,
  the Workspace setup window, the simulation, the analysis). Until ClickNick has read the database
  (`has_database`: while it loads, and after the CSV fallback), the session builds nothing. In that time the
  Workspace's **Review Changes**, **Reload from CLICK**, the simulation and applying Workspace setup say to
  connect first (`_project_session`). **Compare with > Folder** works without it
- ClickNick drops a database load if its session closed, or if a CSV load or another connect cancelled it. It
  does this also when that happens during the prompt to save the data it replaces
- While a CLICK window is connected, its session's watch (`_monitor_task`) checks every 100 ms whether the window
  closed or shows another project. It shows autocomplete popups while `monitoring` is on and data is loaded. The
  new project's session starts watching even when following the project fails part way
- When the session opens, it pairs the durable workspace for the project's PLC name (`pair_workspace`). The
  Workspace setup window and its unapplied choice (`pending_workspace`) belong to the session. They close with
  it, when CLICK's window closes or shows another project
- `monitoring` is the user's choice. It starts on, **Stop** turns it off, and only **Start** or a window the
  user picks turns it on again. A project change, the CSV fallback and an automatic connect keep it as it was
- When the window closes, database data closes without a prompt, and CSV data stays loaded. The CSV path
  (`_csv_path`) is read from the loaded CSV store
- When the window shows another project, CSV data stays loaded. A Save As keeps the window's `CLICK (hwnd)`
  folder, database and DataView folder, and so does opening another project. ClickNick cannot tell the two apart.
  So it asks whether to keep unsaved address and Dataview edits on database data for the new project
  (`_keeps_edits_for`; text in a cell that will not commit counts). If you keep them, the data and its windows
  stay open, the store's file monitor reads the new database, and Sync and the Dataview Save write there. If
  you do not, the database data closes with nothing saved, and the new database loads. (A save after File > Open
  would overwrite the other project's .cdv files.) Over CSV data, the question covers only Dataview edits,
  including text in a Dataview cell. A Dataview Editor that stays open lists its folder again when the edits
  were kept. Otherwise it is closed without saving and opened again on the window's DataView folder
  (`_reopen_dataview_editor`)
- ClickNick looks for an open project's `CLICK ({hwnd:08X})` folder under the Windows temp folder
  (GetTempPathW), in its long form. Everything that looks for SC_.mdb, Address.csv, Project.ini, Scr*.tmp or the
  DataView folder goes through `utils/click_temp.py` (`click_temp_dir`), from the connected window's hwnd
- The Dataview Editor and Verify use only the connected window's DataView folder (`click_dataview_folder`), never
  another `CLICK (*` folder. The Dataview model takes the folder as a getter (`_dataview_folder`). With no
  window connected, the getter returns the loaded CSV's folder, or none
- Refreshing the window list connects to the first window only when nothing is connected and no data is loaded.
  Otherwise the user picks. A connected window that is missing from the list is closed only when its process is
  gone (the list skips titles without a project). The combobox always lists and selects the connected window,
  under the project it shows (`_show_instances`)
- Closing ClickNick goes through `_close_data(prompt_save=True)`. Cancel or a failed save keeps it open
