# ClickNick Agent Guidance

**IMPORTANT: DON'T USE `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

This file provides guidance to coding agents working in this repository.

## Project Overview

**ClickNick** is a Windows desktop application providing context-aware nickname autocomplete and editing tools for CLICK PLC Programming Software (v2.60–v3.90). It connects via Access ODBC or the built-in Windows Jet fallback to read/write nicknames from the project's Access database (SC_.mdb) or can import from CSV. Core components:

- **Overlay** – Positions a combobox over instruction dialog edit controls for nickname autocomplete
- **Address Editor** – Unified tabbed tksheet-based editor with search/replace, block tagging, validation. Each tab displays ALL memory types in a single scrollable view
- **Tag Browser** – Treeview of nicknames parsed by underscore segments and array indices
- **Dataview Editor** – Edits .cdv files with nickname lookup from shared address data

## Prerequisites

- **OS:** Windows 10 or 11
- **CLICK Software:** v2.60–v3.90
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
├── connection_session.py  # ClickConnection value + ConnectionSession (analysis, Scr watcher, console)
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
4. **On clean exit:** pushes undo frame → applies cascades → freezes builders into overrides → `_derive()` → notifies
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
  full rebuild from the same inputs
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
- A body that raises commits nothing

### Dirty State Detection
- Check via `store.is_dirty(addr_key)` / `store.is_field_dirty(addr_key, "nickname")`
- `_derive` first drops override fields the base already holds, so a field is dirty exactly when it is in
  its row's override; nothing stores a separate dirty marker

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

### Main Window Refresh
- The window title and Workspace details are recomputed by `ClickNickApp._refresh_ui()`; never call it by hand
- Assigning `_click`, `_data`, `_session` or the workspace pairing fields (`_ShownState` attributes), or
  setting the CSV path, schedules one coalesced idle refresh. `ConnectionSession` events (sync count,
  analysis progress, staged rungs) call `_request_ui_refresh()`
