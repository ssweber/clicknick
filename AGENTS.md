# ClickNick Agent Guidance

**IMPORTANT: DON'T USE `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

This file provides guidance to coding agents working in this repository.

## Project Overview

**ClickNick** is a Windows desktop application providing context-aware nickname autocomplete and editing tools for CLICK PLC Programming Software (v2.60–v4.00). It connects via Access ODBC or the built-in Windows Jet fallback to read/write nicknames from the project's Access database (SC_.mdb) or can import from CSV. Core components:

- **Overlay** – Positions a combobox over instruction dialog edit controls for nickname autocomplete
- **Address Editor** – Unified tabbed tksheet-based editor with search/replace, block tagging, validation. Each tab displays ALL memory types in a single scrollable view
- **Tag Browser** – Treeview of nicknames parsed by underscore segments and array indices
- **Dataview Editor** – Edits .cdv files with nickname lookup from shared address data

## Prerequisites

- **OS:** Windows 10 or 11
- **CLICK Software:** v2.60–v4.00
- **Database connection:** Automatic Access ODBC or built-in Windows Jet fallback; Windows x64 normally needs no separate Access driver.
- **Python:** 3.11+ (only if using pip; uv manages Python automatically)

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
- `clicknick` (GUI) - calls `clicknick:main`
- Main app: `src/clicknick/app.py` -> `ClickNickApp` class

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

The application maintains three distinct data layers to cleanly separate database truth from user edits:

1. **Base Layer** (`base_state`) - Latest snapshot from the external database (source of truth)
2. **Overlay Layer** (`user_overrides`) - Sparse dictionary of unsaved edits: `addr_key` → read-only
   `{field: value}` holding only the fields the user set (no row copies, no dirty markers)
3. **Visible Layer** (`visible_state`) - Computed projection of base + overrides

**Core Principles:**
- **Immutable Rows:** `AddressRow` is a frozen dataclass; changes create new instances via `dataclasses.replace()`
- **Inputs vs derived:** base rows and the user's overrides are the inputs. Visible rows, validation, dirty
  fields, the nickname index and block colors are derived by one method, `AddressStore._derive()`, in one
  fixed order, after every change (edit, undo, redo, discard, save, external reload)
- **Undo/Redo:** Tracks overlay layer only (user intent), preserves 50-level history
- **External Updates:** Database refreshes update base layer while preserving user overrides

### Edit Session Pattern

Edits flow through an edit session that accumulates changes atomically:

1. **View** opens `AddressStore.edit_session(description)`
2. **Service** accumulates changes via `session.set_field(addr_key, field, value)`
3. Session uses `MutableRowBuilder` to accumulate changes per row
4. **On clean exit:** applies cascades → freezes builders into overrides → if the overrides changed, pushes the
   undo frame (the overrides before) and clears redo → `_derive()` → notifies. A session that changes nothing
   is not an undo step
5. **On an exception:** nothing is committed (all-or-nothing); a failure inside the commit restores the inputs
6. **All Views** receive changed `addr_keys` and refresh only those rows

**The Rules** (rules 2, 3 and 5 are enforced by `tests/test_store_boundaries.py`):
1. **Models are Immutable:** `AddressRow` is `frozen=True`; all changes create new instances
2. **AddressStore is the Gatekeeper:** Only `AddressStore` writes its layers (`base_state`, `user_overrides`,
   `visible_state`, `block_colors`, `row_order`)
3. **Services and data are Pure Logic:** `services/` and `data/` **never** import `tkinter`
4. **Views are Passive:** Views lookup rows via `store.visible_state[addr_key]` and listen for change notifications
5. **Use the session you are given:** write through the session yielded by `edit_session()`; never touch
   `store._current_session`
6. **One home per fact:** the current data lives in `ClickNickApp._data` (a `DataSession`), the connected CLICK
   window in `ClickNickApp._click` (an immutable `ClickConnection`). Consumers take getters, not copies
7. **No compatibility shims:** when an API changes, update its callers; do not keep aliases or wrappers

### Observer Pattern

All views register as observers with `AddressStore`:
- `add_observer(callback)` - Subscribe to data changes
- `callback(store, changed_keys: set[int] | None)` - Receive notifications with affected `addr_key` sets
- The store replaces changed rows in the shared unified view before notifying; observer exceptions are logged
- Views refresh only changed rows using targeted updates

## Key Dependencies

- `pywin32` - Python for Win32 (pywin32) extensions
- `pyodbc` - ODBC connection to Access database
- `tksheet` - Spreadsheet widget for Address Editor v7 (documentation at https://ragardner.github.io/tksheet/DOCUMENTATION.md)
- `tkinter` - GUI framework (stdlib)

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

**Service tests** (fully unit testable without tkinter):
- `test_block_service.py` - Block tag parsing, color assignment, range detection
- `test_row_service.py` - Fill down, clone structure, edit session integration
- `test_blocktag.py` - Tag parsing edge cases

**Other tests:**
- Filter tests cover abbreviation matching edge cases
- View tests are integration tests requiring tkinter

## Key Implementation Notes

### Working with AddressRow
- `AddressRow` is immutable (`frozen=True`); use `dataclasses.replace()` for changes
- Never modify row attributes directly; always use `AddressStore.edit_session()`
- Access visible data via `store.visible_state[addr_key]`, not direct row references

### Edit Sessions
- All data modifications must go through `store.edit_session(description)`
- Use `session.set_field(addr_key, field, value)` to accumulate changes
- Multiple changes batched into single undo frame (e.g., fill-down 500 rows = 1 undo)
- Cascades (T/TD|CT/CTD sync, block tag sync) happen automatically within the session
  (`AddressStore._apply_cascades`): a Retentive change mirrors across the pair; a row whose block tag changed
  (old tag vs new tag, not its text) has the matching open/close tag and the pairs' `_D` tags renamed in place,
  removed, or (on an untagged pair, when the tag was added or renamed) appended (`BlockService`). "The caller
  set this field" is read before any cascade runs, and a cascade never writes it
- A body that raises commits nothing

### Dirty State Detection
- Check via `store.is_dirty(addr_key)` / `store.is_field_dirty(addr_key, "nickname")`
- `_derive` first drops override fields the base already holds, so a field is dirty exactly when it is in
  its row's override; nothing stores a separate dirty marker

### Sync
- `save_all_changes` refuses (raises) while rows have validation errors, for every caller. For the database it
  reads SC_.mdb first (CLICK writes it while connected), so the rows written carry CLICK's current values in
  the fields the user did not change
- `loaded_with_error` (CLICK's own X/SC/SD names exempt from our nickname rules) is set on every base row by one
  helper, `_flag_loaded_error`, on load, reload and Sync alike

### Undo/Redo
- Tracks user intent (overlay layer) only, not database state
- Max 50 undo frames (configurable via `MAX_UNDO_DEPTH`)
- A successful Sync/Save, or a Discard, clears Undo/Redo (frames hold override snapshots, not old values);
  a CLICK save does not
- An unsaved field that the database now matches stops being an edit (`_rebase_override`, run by `_derive`)
- Keyboard: Ctrl+Z (undo), Ctrl+Y (redo)

### Block Colors
- Block colors are stored in `AddressStore.block_colors` dict, NOT in `AddressRow`
- Access via `store.get_block_color(addr_key)` → returns color name or None
- Colors are derived from comments (block tags) by `compute_block_colors`, the one implementation
- Kept separate to avoid row recreation on color changes and exclude from undo/redo
- Duplicate block names: the first definition in address order is valid; later ones are flagged

### Program Analysis
- One build worker per connection; requests made while it runs collapse into one follow-up build
- The generated code, persisted project and tag map all come from one nickname snapshot read from CLICK's
  database, so tag names always match the code. ClickNick edits reach analysis on the next build after Sync

### Preview Changes
- The one window for getting ladder into CLICK (`views/preview_changes_window.py`; it was called Guided Paste):
  **Ladder > Compare with > Folder** opens it on any folder of ladder CSVs, the Workspace's **Preview Changes** /
  `clicknick-cli rung apply` on the workspace's `csv_output/`. The app keeps one window per folder and reloads it
  when the folder is shown again
- A window's `ProposalSource` says where its proposal comes from ("from workspace", "from <folder>") in the title
  and the diff's `+++` header, and what starts out taken: differences always; the folder's nicknames, and deleting
  programs only in CLICK, unless the source is a copy of another PLC (`takes_nicknames`, `deletes_only_in_click`).
  The user's choices are kept as they differ from those (`_flipped_in_click`). A window shown as another source
  resets only those two choices (a deletion marked done stays one); skips and what was pasted stay, as they are
  about what CLICK holds. The caller gives the source (`_show_preview_changes(source=)`; by default
  `ProposalSource.of`)
- **Compare with > Other CLICK window** lists the CLICK windows other than the connected one. Picking one copies
  its last save and its database's nicknames into `%LOCALAPPDATA%/ClickNick/compare/CLICK (hwnd)/`
  (`services/click_snapshot.py`, replaced whole each time) and shows that folder as `ProposalSource.other_click`.
  **↻ Refresh from <project>** copies it again (`refresh_source`)
- `services/rung_diff.py` is the one comparison of a CSV bundle with CLICK's last save (`csv/`): which programs
  differ, which rungs, and the diff text. Rungs are compared by `rung_fingerprint`; pyrung source is only how a
  difference is shown
- CLICK pastes over the selected rung: that rung is replaced by the first pasted rung and the rest go in
  below it. `ProgramChange.steps` turns a program's differences into steps on that basis, worked from the top
  so each step's rung numbers are the ones CLICK shows: paste over one rung, paste over a new empty rung, or
  delete rungs. The Copy switch's **Whole program** clears the program in CLICK and pastes it in one piece
- Each difference (one non-equal opcode, `DifferenceKey`) can be taken or skipped; skipped means CLICK keeps its
  rungs there. Steps are numbered from what CLICK holds given the skips (`steps(skipped, pasted)`), and **Whole
  program** copies `merged(skipped)`. A difference locks once its step is done ("Next"), not when copied. Choices
  live only as long as the window; `carry_skipped` moves them onto the comparison after a CLICK save
- The folder is read once (`load_bundle`) and compared and copied from memory: a CLICK save regenerates the
  workspace and deletes `csv_output/`, and the window must still know whether what it pasted landed
- It closes itself when a CLICK save holds everything it was pasting. After a save that leaves work to do it
  stays open with a notice (the edited source is then in `backup/src/plc`); **Reload from CLICK** closes it,
  because that throws the edits away. It is not modal: the Address Editor's Sync is part of the same workflow
- Given the workspace source (`source_dir`), the diff shows that source through the exporter's `rung_sources.json`
  and there is no nicknames step (workspace tags go through `tag apply`). Any other folder is shown by converting
  its CSVs with pyrung
- Under "Changed rungs" a program is still copied whole when its steps number `_MANY_STEPS` (6) or more, unless
  it has `_SLOW_PASTE_RUNGS` (100) rungs, CLICK holds legacy-encoded rungs of it (a whole paste re-pastes skipped
  rungs from ClickNick's reading), a step of it is done, its rungs were asked for by number, or the user
  clicked **Step Through** for it (`_copied_whole_for_steps`; 100 counts the paste as chosen, `merged`). Every difference of a program locks while one of its steps is half done
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
  Start/Stop beside the main window's Test legend), connection teardown or a CLICK save that does not convert
  stops it. Closing windows never does. The on/off state is
  not persisted: nothing launches a subprocess or listens on port 502 at app start
- The Simulator (whose command console is a bottom pane, `views/console_panel.py`, that pops out and docks back)
  and the Dataview editor only observe it (the Dataview attaches while it serves Modbus). Views
  never own a `DapService`; while it is off they stay open and offer Start
- Launched with `keepForcesOnRun`, so forces survive STOP -> RUN; switch/analog patches ride `set_mode("run")`
- Values are read over Modbus; inputs (switch/analog patches), mode, speed, stepping and forces go over DAP.
  X stays read-only over Modbus, as on a real CLICK. Mode, speed and forces follow frames,
  because the Console and agents can drive the same simulation (last command wins)
- User actions emit an `echo` event with the equivalent console command (tag names via `to_tag()`), which the
  console pane shows as a comment; only actions that reach a running simulation echo, and analog values echo once
  they settle
- Bench links (session-only feedback wiring, `sim_state.BenchLink`, keyed by feedback address) are desired state
  like forces: persisted, re-applied over DAP after a launch, and adopted from the simulation when a frame's
  `linksRevision` changes (the Console can edit them too). "Save to project" writes the link into the feedback's
  comment through the store (Simulator window, `services/link_annotation.py`); after Sync and a rebuild, pyrung
  drops the bench copy because the program declares the same link
- Desired state (switches, forces, bench links) is keyed by CLICK address and never holds a tag name. pyrung
  reports tag names; they are mapped with the names of the program the simulation was launched on
  (`_tag_maps`), so a rename in CLICK does not move them, and `load_state` reports entries that are not addresses
- A new analysis generation (a CLICK save, Reload from CLICK) restarts a running simulation on the rebuilt
  workspace once the build is done (`_follow_program`, on the 2 s watch tick): from power-on values or the PLC
  data file, with the same desired state and switch position. Its notice is set once the restart is ready. A
  build that fails stops the simulation, since pyrung may already have loaded files of it, with a notice naming
  the reason; the next build that converts starts it again. This relies on `AnalysisService.build()` bumping
  the generation when it starts, failed or not
- Until the simulation runs the current generation (`_program_current`), pyrung's autoreload may already have
  swapped in the new program and lost forces and links on renamed tags. Frames then add forces and links (the
  Console's, last command wins) but do not release any; a release is checked again once the program is current
- `_reapply` sends every entry even when one goes unanswered; an unanswered entry stays set and is reported,
  and an unanswered link listing is asked again on the next frame
- A failed DAP request undoes the user's action only when the simulation that was asked refused it: not when it
  has since stopped or restarted (token check) or never answered (`DapUnavailableError`)

### Main Window Refresh
- The window title and Workspace details are recomputed by `ClickNickApp._refresh_ui()`; never call it by hand
- Assigning `_click`, `_data`, `_session` or the workspace pairing fields (`_ShownState` attributes)
  schedules one coalesced idle refresh. `ConnectionSession` events (sync count, analysis progress,
  staged rungs) call `_request_ui_refresh()`

### Connection and Lifecycle
- While a CLICK window is connected, `_monitor_task` checks every 100 ms whether it closed or shows
  another project, and shows autocomplete popups while `monitoring` is on and data is loaded
- `monitoring` is the user's choice: it starts on, **Stop** turns it off, and only **Start** or a window
  the user picks turns it on again. A project change, the CSV fallback and an automatic connect keep it
- When the window closes or changes project (a Save As included), database data closes without a
  prompt; CSV data stays loaded. The CSV path (`_csv_path`) is read from the loaded CSV store
- Refreshing the window list connects to the first window only when nothing is connected and no data is
  loaded; otherwise the user picks. A connected window missing from the list is closed only when its
  process is gone (the list skips titles without a project)
- Closing ClickNick goes through `_close_data(prompt_save=True)`: Cancel or a failed save keeps it open
