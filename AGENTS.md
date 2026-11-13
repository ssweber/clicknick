# ClickNick Agent Guidance

**IMPORTANT: DON'T USE `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

## Project Overview

**ClickNick** is a Windows desktop application (Windows 10/11, Python 3.11+) with nickname autocomplete and
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
make lint                       # Run codespell, ssort, ruff (check + format)
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
├── connection_session.py  # ClickConnection value + ConnectionSession (analysis, Scr watcher, simulation)
├── simulation_session.py  # SimulationSession: pyrung DAP + Modbus + simulator settings (no tkinter)
├── models/                # Data models and constants
│   ├── address_row.py     # Frozen dataclass for address data
│   ├── address_slots.py   # Every address slot in display order
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
2. **Overlay Layer** (`user_overrides`) - Sparse dictionary of unsaved edits: `addr_key` → read-only
   `{field: value}` holding only the fields the user set (no row copies, no dirty markers)
3. **Visible Layer** (`visible_state`) - Computed projection of base + overrides

- **Inputs vs derived:** base rows and the user's overrides are the inputs. Visible rows, validation, dirty
  fields, the nickname index and block colors are derived by one method, `AddressStore._derive()`, in one
  fixed order, after every change (edit, undo, redo, discard, save, external reload)
- **External Updates:** Database refreshes update the base layer and keep user overrides

### Edit Session Pattern

1. **View** opens `AddressStore.edit_session(description)`
2. **Service** accumulates changes via `session.set_field(addr_key, field, value)`; the session keeps a
   `MutableRowBuilder` per row. Many changes make one undo frame (fill-down 500 rows = 1 undo)
3. **On clean exit:** applies cascades → freezes builders into overrides → if the overrides changed, pushes the
   undo frame (the overrides before) and clears redo → `_derive()` → notifies. A session that changes nothing
   is not an undo step
4. **On an exception:** nothing is committed (all-or-nothing); a failure inside the commit restores the inputs
5. **All Views** receive changed `addr_keys` and refresh only those rows

Cascades (`AddressStore._apply_cascades`): a Retentive change mirrors across the T/TD or CT/CTD pair; a row
whose block tag changed (old tag vs new tag, not its text) has the matching open/close tag and the pairs' `_D`
tags renamed in place, removed, or (on an untagged pair, when the tag was added or renamed) appended
(`BlockService`). "The caller set this field" is read before any cascade runs, and a cascade never writes it.

**The Rules** (`tests/test_store_boundaries.py` enforces rules 2, 3 and 5; for rule 5 it checks that nothing
outside the store touches `_current_session`):
1. **Models are Immutable:** `AddressRow` is `frozen=True`; all changes create new instances
   (`dataclasses.replace()`)
2. **AddressStore is the Gatekeeper:** Only `AddressStore` writes its layers (`base_state`, `user_overrides`,
   `visible_state`, `block_colors`, `row_order`)
3. **Services and data are Pure Logic:** `services/`, `data/` and `simulation_session.py` **never** import
   `tkinter`
4. **Views are Passive:** Views lookup rows via `store.visible_state[addr_key]` and listen for change
   notifications; nothing keeps a row reference across a change
5. **Every edit goes through `store.edit_session()`:** write through the session it yields; never touch
   `store._current_session`
6. **One home per fact:** the current data lives in `ClickNickApp._data` (a `DataSession`), the connected CLICK
   window in `ClickNickApp._click` (an immutable `ClickConnection`). Consumers take getters, not copies
7. **No compatibility shims:** when an API changes, update its callers; do not keep aliases or wrappers

### Observer Pattern

- `add_observer(callback)`; `callback(store, changed_keys: set[int] | None)` receives the affected `addr_key`s
- The store replaces changed rows in the shared unified view before notifying; observer exceptions are logged

## Key Dependencies

`pywin32`, `pyodbc`, `tksheet` v7 (https://ragardner.github.io/tksheet/DOCUMENTATION.md), `pyrung`, `laddercodec`,
`pyclickplc`, all pinned exactly in `pyproject.toml`; `tkinter` (stdlib).

## Testing

Tests are in `tests/` and `src/` (pytest discovers both).

**Core data tests:**
- `test_address_store.py` - Store operations, undo/redo, base+overlay merging, cascades, derived-state regressions
- `test_store_oracle.py` - Random edit/undo/redo/discard/Sync/CLICK-write sequences; kept state must equal a
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
- `_derive` first drops override fields the base already holds, so a field is dirty exactly when it is in
  its row's override

### Sync
- `save_all_changes` refuses (raises) while rows have validation errors, for every caller. For the database it
  reads SC_.mdb first (CLICK writes it while connected), so the rows written carry CLICK's current values in
  the fields the user did not change
- `loaded_with_error` (CLICK's own X/SC/SD names exempt from our nickname rules) is set on every base row by one
  helper, `_flag_loaded_error`, on load, reload and Sync alike

### Undo/Redo
- Tracks the overlay layer (user intent) only; at most `MAX_UNDO_DEPTH` (50) frames
- A successful Sync/Save, or a Discard, clears Undo/Redo (frames hold override snapshots, not old values);
  a CLICK save does not
- An unsaved field that the database now matches stops being an edit (`_rebase_override`, run by `_derive`)

### Block Colors
- Stored in `AddressStore.block_colors`, NOT in `AddressRow`, and not part of undo/redo; read them with
  `store.get_block_color(addr_key)` (color name or None)
- `compute_block_colors` is the one implementation that derives them from comments (block tags)
- Duplicate block names: the first definition in address order is valid; later ones are flagged

### Program Analysis
- One build worker per connection; requests made while it runs collapse into one follow-up build.
  `ConnectionSession.start_analysis` queues no build while one runs (that build serves it) and makes the
  ScrWatcher once per session: the watcher holds the count of tags synced since CLICK last saved
- Publishing a build swaps `csv/` and `src/plc` as a pair and records the generation last, so a workspace
  never holds `csv/` from one save and `src/plc` from another
- A build that fails before it publishes leaves `project_dir` an earlier save's (`project_is_current`
  is False), and Review Changes then has nothing to compare with
- `SavedProgram.save_count` is the one signal that CLICK saved: only the ScrWatcher bumps it, once per save
  (once the Scr*.tmp files, checked every 500 ms, are unchanged on two checks in a row after a change).
  A Sync rebuild, Reload from CLICK, a workspace change, a retry and a failed build leave it as it was
- `AnalysisService.status` reads BUILDING until a build that serves every request made so far
  (`mark_building` returns the count, `build(serves=)` takes it) finishes. A build of the files before a save
  that publishes while the save's build is queued leaves it BUILDING, so no reader (`saved_program()`,
  `rung apply`, the Workspace status, the simulation) pairs a new save with the `csv/` of the save before.
  A request that fails before it is queued (`mark_failed` without `serves`: no database, no Scr*.tmp) while a
  build runs leaves it BUILDING; that failure shows once the build serving every request finishes, unless a
  later request replaced it
- The generated code, persisted project and tag map all come from one nickname snapshot read from CLICK's
  database, so tag names always match the code. ClickNick edits reach analysis on the next build after Sync.
  `clicknick-cli` finds tags by the workspace's names (`project_tag_to_addr_key`)
- `csv/analog_inputs.json` records the analog inputs a workspace was generated with; `tag apply` regenerates
  its baseline `tags.py` with them, never from CLICK's Project.ini at the time it runs
- `backup/src/plc` is the newest backup of `src/plc` (taken before a build replaces edited source, on
  `clicknick-cli backup`, and when a chosen workspace's edits are kept). Each new backup first moves it to
  `backup/older/<YYYYMMDDTHHMMSSZ>/src/plc`, named in UTC by the time it was taken (`backup/backup-time.txt`;
  when that cannot be written, the backup's files are dated to it instead). A tree that any kept backup holds
  makes no new one: that backup becomes the newest. The oldest go so that 5 are kept in all
  (`KEPT_PLC_BACKUPS`), each renamed out of the listing before it is deleted, and only once the whole backup or
  restore succeeded; one that fails leaves `src/plc` as it was and deletes no backup. Nothing refuses a save or
  a backup over this
- `clicknick-cli restore` takes the newest backup, `restore <time>` an older one. It copies the chosen backup
  aside, then backs up `src/plc` if it differs from both the last generation and that backup, then replaces
  `src/plc`. Its pruning keeps the restored backup, so six may be kept until the next backup
- A build, backup or restore that succeeds leaves the edits `src/plc` held as the newest backup (or in `src/plc`,
  as the backup it restored). A tree once in a backup, or in `src/plc` with edits as one began, is gone only
  when 5 kept backups were the newest after it. `tests/test_backup_oracle.py` checks these rules over random
  edits, builds, backups and restores with injected copy, move, time-file and prune failures
- Each workspace folder has one lock (`workspace_writing`). A build's publish holds it from its backup of
  edits to the generation record; `backup`, `restore` and choosing a workspace hold it throughout. The
  build waits for it; the others run on the Tk thread and are refused (`WorkspaceBusyError`) instead of
  freezing the window. `clicknick-cli` commands that read the workspace are refused the same way while the
  analysis is BUILDING (`_get_project_dir`)

### Review Changes
- The one window for getting ladder into CLICK (`views/review_changes_window.py`): **Ladder > Compare with >
  Folder** opens it on any folder of ladder CSVs, the Workspace's **Review Changes** / `clicknick-cli rung apply`
  on the workspace's `csv_output/`. The app keeps one window per folder and reloads it when the folder is shown
  again
- A window's `ProposalSource` says where its proposal comes from ("from workspace", "from <folder>") in the title
  and the diff's `+++` header, and what starts out taken: differences always; the folder's nicknames, and deleting
  programs only in CLICK, unless the source is a copy of another PLC (`takes_nicknames`, `deletes_only_in_click`).
  The user's choices are kept as they differ from those (`_flipped_in_click`). A window shown as another source
  resets only those two choices (a deletion marked done stays one); skips and what was pasted stay, as they are
  about what CLICK holds. The caller gives the source (`_show_review_changes(source=)`; by default
  `ProposalSource.of`)
- **Compare with > Other CLICK window** lists the CLICK windows other than the connected one. Picking one copies
  its last save and its database's nicknames into `%LOCALAPPDATA%/ClickNick/compare/CLICK (hwnd)/`
  (`services/click_snapshot.py`, replaced whole each time) and shows that folder as `ProposalSource.other_click`.
  **↻ Refresh from <project>** copies it again (`refresh_source`). Each window-list refresh (startup included)
  deletes the copies of windows not in the list, except one that is or holds a folder an open Review
  Changes window shows (`remove_stale_snapshots`)
- `services/rung_diff.py` is the one comparison of a CSV bundle with CLICK's last save (`csv/`): which programs
  differ, which rungs, and the diff text. Rungs are compared by `rung_fingerprint`; pyrung source is only how a
  difference is shown
- CLICK pastes over the selected rung: that rung is replaced by the first pasted rung and the rest go in
  below it. `ProgramChange.steps` turns a program's differences into steps on that basis, worked from the top
  so each step's rung numbers are the ones CLICK shows: paste over one rung, paste over a new empty rung, or
  delete rungs. The Copy switch's **Whole program** clears the program in CLICK and pastes it in one piece
- Each difference (one non-equal opcode, `DifferenceKey`) can be taken or skipped; skipped means CLICK keeps its
  rungs there. Steps are numbered from what CLICK holds given the skips (`steps(skipped, pasted)`), and **Whole
  program** copies `merged(skipped)`, except that a program whose skipped difference keeps CLICK's legacy-encoded
  rungs is stepped through. A difference locks once its step is done ("Next"), not when copied. Choices live only
  as long as the window; `carry_skipped` moves them onto the comparison after a CLICK save
- What was pasted (`_pasted`, `_partial`; a whole copy counts every difference taken) is in CLICK until CLICK
  saves, as `SavedProgram.save_count` tells (`_note_saves`); a Sync rebuild, a Reload or a failed build keep it.
  The Copy switch keeps it. A new reading of the folder before a save places it in the new comparison
  when CLICK would hold the same rungs (`_carry_pasted`); otherwise that program is copied whole until CLICK saves
  (`_unplaced`), whatever the comparison or the skips say, and so is one copied whole without a comparison.
  **Restart** asks before forgetting it. On the first comparison after a save, a program or deletion marked done
  that CLICK's save still shows to do is a step again, unless ClickNick cannot read all of CLICK's copy of it
- A whole copy of a program with no rungs copies nothing: the step is deleting its rungs in CLICK
- The folder is read once (`load_bundle`) and compared and copied from memory: a CLICK save regenerates the
  workspace and deletes `csv_output/`, and the window must still know whether what it pasted landed
- It closes itself when a CLICK save holds everything it was pasting. After a save that leaves work to do it
  stays open with a notice (the edited source is then in `backup/src/plc`); **Reload from CLICK** closes it,
  because that throws the edits away. It is not modal: the Address Editor's Sync is part of the same workflow
- Given the workspace source (`source_dir`), the diff shows that source through the exporter's `rung_sources.json`
  and there is no nicknames step (workspace tags go through `tag apply`). Any other folder is shown by converting
  its CSVs with pyrung
- Under "Changed rungs" a program is still copied whole when its steps number `_MANY_STEPS` (6) or more, unless
  its paste as chosen (`merged`) has `_SLOW_PASTE_RUNGS` (100) rungs or more, CLICK holds legacy-encoded rungs
  of it (a whole paste re-pastes skipped rungs from ClickNick's reading), a step of it is done, its rungs were
  asked for by number, or the user clicked **Step Through** for it (`_copied_whole_for_steps`). Every
  difference of a program locks while one of its steps is half done
- A folder CSV that cannot be read is left out (`_left_out`), with a notice: it is no step and does not hold the
  window open
- A program only in CLICK (`only_in_click`) is a row like the others: taken, its step is deleting it in CLICK
  ("Next" marks it done; a CLICK save that still has it makes it a step again); unticking **Delete it in CLICK**
  keeps it (`_kept`), and a kept program does not hold the window open
- Any other folder's `nicknames.csv` is never written to CLICK's database directly: **Stage nicknames** stages
  the fields it sets as one edit in the store (`services/nickname_staging.py`; only the addresses it lists) and
  opens the Address Editor on Changed with **Sync and Close**. The row compares the file with the store's visible
  rows (left to stage) and base rows (not synced), is done once CLICK's database has them, and can be skipped

### Simulation
- `ConnectionSession.simulation` (a `SimulationSession`) is the one home of the simulated PLC: the pyrung DAP
  subprocess, its Modbus client, switch/analog/force settings and their persistence (`services/sim_state.py`)
- It runs headless: `turn_on()` starts it (opening the Simulator does this), and only `turn_off()` (the
  Start/Stop beside the main window's Test legend) or connection teardown stops it. Closing windows never
  does. The on/off state is not persisted: nothing launches a subprocess or listens on port 502 at app start
- The Simulator (its Console pane is `views/console_panel.py`) and the Dataview editor only observe it (the
  Dataview attaches while it serves Modbus). Views never own a `DapService`; while it is off they stay open and
  offer Start
- Launched with `keepForcesOnRun`, so forces survive STOP -> RUN; switch/analog patches ride `set_mode("run")`
- Values are read over Modbus; inputs (switch/analog patches), mode, speed, stepping, forces and links go over
  DAP. The Dataview reads and writes values over Modbus, the same client as for a real CLICK, and X stays
  read-only there, as on a real CLICK (its Force column goes through the simulation). Mode, speed and forces
  follow frames, because the Console and agents can drive the same simulation (last command wins)
- Panel mutations (switches, analog values, forces, mode, step, speed, links) go as structured DAP requests
  today; add no new one. The next release sends them as pyrung command lines with a source such as `panel`
  (**commands are text with a source; state is data; the write is a plan**), over the connection the session
  already has. The command language lives in pyrung, and ClickNick will send lines verbatim. The Console pane
  splits a line on `;` today (`ConsolePanel._submit_command_text`; its `autoreload` and `reload` refusals rely
  on it); that, and ClickNick's own echo once pyrung broadcasts the command text, go with the rework. Frames,
  force and link listings, Modbus info and causal queries stay structured reads; the program write stays
  `pyrungReload` with its carry plan; launch and terminate stay structured
  (`scratchpad/visual-simulator-design.md`, "Commands and recording")
- User actions emit an `echo` event with the equivalent console command (tag names via `to_tag()`), which the
  console pane shows as a comment; only actions that reach a running simulation echo, and analog values echo once
  they settle
- Bench links (session-only feedback wiring, `sim_state.BenchLink`, keyed by feedback address) are desired state
  like forces: persisted, re-applied over DAP after a launch, and adopted from the simulation when a frame's
  `linksRevision` changes (the Console can edit them too). "Save to project" writes the link into the feedback's
  comment through the store (Simulator window, `services/link_annotation.py`); after Sync and a rebuild, pyrung
  drops the bench copy because the program declares the same link
- Desired state (switches, forces, bench links) is keyed by CLICK address and never holds a tag name. pyrung
  reports tag names; they are mapped with the names of the program the simulation runs (`_tag_maps`: the
  workspace's `project_tag_to_addr_key`, taken at launch and at each write), so a rename in CLICK does not move
  them until that program is written, and `load_state` reports entries that are not addresses
- pyrung's autoreload is off: a changed program reaches the simulation only when the user writes it. A new
  analysis generation (a CLICK save; "rebuilt" when the save count did not move, as after Reload from CLICK or a
  Sync) or an edit to the workspace's `src/plc` (`PlcSourceWatch`, on the 2 s watch tick) is offered as
  `program_change`: in RUN, **RUN Time Edit** (reload, continue: values, timers and forces stay) or **Stop and
  Write** (reload, STOP, RUN again in the same process: pyrung keeps retentive values and forces, clears the
  rest); in STOP or while stepping, **Write** (values and mode stay). A Console `reload` writes for the current
  mode. The Console pane refuses `autoreload`; an agent on `pyrung live` can still reload, or change forces
  while a write runs. A build that fails is a notice; the old program keeps running.
  A finished build of the program the simulation runs (a Sync or Reload from CLICK that leaves it as it
  was) is not offered: its tag names, `src/plc` and `run.py` are those read at the launch or write
  (`PlcSourceWatch.same`; a file that could not be read either time is no proof). The watch tick and
  each frame compare a build once (`_examine_build`); `program_change` only reads the result and offers
  nothing for a build not compared yet
- One check says whether the workspace's program can run (`_workspace_problem`: converted, current, a
  `run.py`, no rung ClickNick cannot read). Start, a write and Restart all use it; a write or Restart it
  refuses leaves the simulation running and sets a notice saying why
- A write (`_write_program`) is one job on the action worker. The Console refuses commands until it is
  answered, no write is offered while a Console command runs, and Restart waits for it. Console commands run
  through `run_console_command`, which counts them in flight until each one returns, so closing the pane
  mid-command does not hold writes back. Every pane shows busy, with Stop, from that count (`console_busy`),
  and the offer says a Console command holds the write.
  An agent on `pyrung live` can still change forces and links while a write runs. The write reads pyrung's
  force and link listing (the truth, whatever the Console did since the last frame), `plan_carry`
  (`services/program_carry.py`) decides each entry's name in the new program, and one `pyrungReload`
  (`DapService.planned_reload`, pyrung 0.16) takes the plan (`CarryPlan.as_dap()`). pyrung pauses a running
  continue first, keeps the mode, and places each entry; an entry the plan leaves out (one the Console added
  after the listing) keeps its name:
  - a bench link follows its names while they exist (noted when one now sits on another address), else stays
    on the address under its new name; when two land on one feedback, the one that followed its name wins and
    the other is dropped
  - a force stays on its address under the new name on a pure rename (an unnamed address gaining a nickname
    included); a force whose name now sits on another address stays only on X, Y or an analog channel's DF and
    is released on internal memory
  - a link the program declares and runs (`declared`) follows its feedback's name while the new program declares
    a link on that name (from the workspace's `csv/nicknames.csv`, `linked_feedbacks`); when the name is gone
    or sits on an address with no declared link, its coil carries on at its address under the new name. A
    bench link or declared link that moves keeps its coil's state, so a timer part way through carries on
- The offer lists releases, drops and moves before the user writes. After the reload, pyrung's report
  (`carried`) is the truth: the entries it placed are adopted by address, and the notice
  (`CarryPlan.written`) keeps the plan's notes for the entries placed as planned and says why pyrung could
  not keep any other (a drop that loses nothing, such as a link the program now declares, is not listed).
  A write answered after another build started keeps the old names and offers the change again; no build
  is taken as run until the next write or launch, as which program pyrung read is unknown. The switch
  shows the position it had until the write is answered
- A reload that fails changes nothing in pyrung: the old program keeps running with its forces and links (a
  write made in RUN sends continue again, since pyrung may have paused), and **Restart** is added to the offer.
  A pyrung without `pyrungReload` refuses the write the same way, with a notice that it needs pyrung 0.16.0;
  nothing falls back to releasing and re-sending entries around a plain reload. A reload pyrung never
  answers sends nothing by name (which program runs is unknown) and offers Restart; its notice says the
  simulation may be paused and names what the plan releases, and the switch position stays the
  user's (`_position_held`) so Restart starts in it and the write offered is for it, until the user moves
  the switch
- Restart (also on the toolbar) relaunches on what the workspace holds now, from power-on values or the PLC
  data file, with the same desired state and switch position; so do Start, a PLC data file change and a
  Modbus port change (one seen during a write: once the write is answered, unless the simulation relaunched
  meanwhile; one seen while a build runs: once it ends, `_restart_due`), and a simulation that failed to
  start once a later build converts (`_follow_program`). A workspace move relaunches without the check
  (`relaunch`), waiting out the build
- `_reapply` (after a launch) sends every entry even when one goes unanswered; an unanswered entry stays set
  and is reported, and an unanswered link listing is asked again on the next frame
- A failed DAP request undoes the user's action only when the simulation that was asked refused it: not when it
  has since stopped or restarted (token check) or never answered (`DapUnavailableError`)

### Main Window Refresh
- The window title and Workspace details are recomputed by `ClickNickApp._refresh_ui()`; never call it by hand
- Assigning `_click`, `_data`, `_session` or the workspace pairing fields (`_ShownState` attributes)
  schedules one coalesced idle refresh. `ConnectionSession` events (sync count, analysis progress,
  staged rungs) call `_request_ui_refresh()`
- `_refresh_ui` also re-titles the open editor windows, skipping one being destroyed. They take the
  project name and analysis as getters, so they follow a project change

### Connection and Lifecycle
- While a CLICK window is connected, `_monitor_task` checks every 100 ms whether it closed or shows
  another project, and shows autocomplete popups while `monitoring` is on and data is loaded
- `monitoring` is the user's choice: it starts on, **Stop** turns it off, and only **Start** or a window
  the user picks turns it on again. A project change, the CSV fallback and an automatic connect keep it
- When the window closes, database data closes without a prompt; CSV data stays loaded. The CSV path
  (`_csv_path`) is read from the loaded CSV store
- When the window shows another project, CSV data stays loaded. A Save As keeps the window's
  `CLICK (hwnd)` folder, database and DataView folder, and so does opening another project; ClickNick
  cannot tell them apart, so it asks whether to keep unsaved address and Dataview edits on database data
  for the new project (`_keeps_edits_for`; text in a cell that will not commit counts). If they are kept,
  the data and its windows stay open, the store's file monitor reads the new database, and Sync and the
  Dataview Save write there. If not, the database data closes with nothing saved (a save after File > Open
  would overwrite the other project's .cdv files) and the new database loads. Over CSV data the question
  covers only Dataview edits, text in a Dataview cell included. A Dataview Editor that stays open lists
  its folder again when the edits were kept; otherwise it is closed without saving and opened again on
  the window's DataView folder (`_reopen_dataview_editor`)
- ClickNick looks for an open project's `CLICK ({hwnd:08X})` folder under the Windows temp folder
  (GetTempPathW), in its long form. Everything that looks for SC_.mdb, Address.csv, Project.ini, Scr*.tmp or
  the DataView folder goes through `utils/click_temp.py` (`click_temp_dir`), from the connected window's hwnd
- The Dataview Editor and Verify use only the connected window's DataView folder
  (`click_dataview_folder`), never another `CLICK (*` folder. The Dataview model takes the folder as a
  getter (`_dataview_folder`): with no window connected it is the loaded CSV's folder, or none
- Refreshing the window list connects to the first window only when nothing is connected and no data is
  loaded; otherwise the user picks. A connected window missing from the list is closed only when its
  process is gone (the list skips titles without a project). The combobox always lists and selects the
  connected window, under the project it shows (`_show_instances`)
- Closing ClickNick goes through `_close_data(prompt_save=True)`: Cancel or a failed save keeps it open
