# CLAUDE.md

**IMPORTANT: DON'T USE `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ClickNick** is a Windows desktop application providing context-aware nickname autocomplete and editing tools for CLICK PLC Programming Software (v2.60–v3.80). It connects via ODBC to read/write nicknames from the project's Access database (SC_.mdb) or can import from CSV. Core components:

- **Overlay** – Positions a combobox over instruction dialog edit controls for nickname autocomplete
- **Address Editor** – Unified tabbed tksheet-based editor with search/replace, block tagging, validation. Each tab displays ALL memory types in a single scrollable view
- **Tag Browser** – Treeview of nicknames parsed by underscore segments and array indices
- **Dataview Editor** – Edits .cdv files with nickname lookup from shared address data

## Prerequisites

- **OS:** Windows 10 or 11
- **CLICK Software:** v2.60–v3.80
- **ODBC Drivers:** Microsoft Access Database Engine (for live DB connection; optional if using CSV)
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
- `clicknick-dev` (console) - calls `clicknick:main_dev`, enables in-progress features
- Main app: `src/clicknick/app.py` -> `ClickNickApp` class

### Package Structure

```
src/clicknick/
├── app.py                 # Main ClickNickApp class
├── config.py              # AppSettings with persistence
├── models/                # Data models and constants
│   ├── address_row.py     # Frozen dataclass for address data
│   └── mutable_row_builder.py  # Builder for accumulating changes
├── data/                  # Data storage and state management
│   ├── address_store.py   # Core store: base/overlay/visible layers, undo/redo
│   ├── edit_session_new.py  # Context manager for atomic edits
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
2. **Overlay Layer** (`user_overrides`) - Sparse dictionary of user modifications only
3. **Visible Layer** (`visible_state`) - Computed projection of base + overrides

**Core Principles:**
- **Immutable Rows:** `AddressRow` is a frozen dataclass; changes create new instances via `dataclasses.replace()`
- **Targeted Refresh:** Reference equality (`is`) used for fast dirty detection
- **Undo/Redo:** Tracks overlay layer only (user intent), preserves 50-level history
- **External Updates:** Database refreshes update base layer while preserving user overrides

### Edit Session Pattern

Edits flow through an edit session that accumulates changes atomically:

1. **View** opens `AddressStore.edit_session(description)`
2. **Service** accumulates changes via `session.set_field(addr_key, field, value)`
3. Session uses `MutableRowBuilder` to accumulate changes per row
4. **On exit:** Session freezes builders → updates overrides → pushes undo frame → notifies observers
5. **All Views** receive changed `addr_keys` and refresh only those rows

**The Rules:**
1. **Models are Immutable:** `AddressRow` is `frozen=True`; all changes create new instances
2. **AddressStore is the Gatekeeper:** Only `AddressStore` manages the three data layers
3. **Services are Pure Logic:** Services **never** import `tkinter`
4. **Views are Passive:** Views lookup rows via `store.visible_state[addr_key]` and listen for change notifications

### Observer Pattern

All views register as observers with `AddressStore`:
- `add_observer(callback)` - Subscribe to data changes
- `callback(changed_keys: set[int])` - Receive notifications with affected `addr_key` sets
- Views refresh only changed rows using targeted updates
- Reference equality (`visible is base`) enables fast dirty detection

## Key Dependencies

- `pywin32` - Python for Win32 (pywin32) extensions
- `pyodbc` - ODBC connection to Access database
- `tksheet` - Spreadsheet widget for Address Editor v7 (documentation at https://ragardner.github.io/tksheet/DOCUMENTATION.md)
- `tkinter` - GUI framework (stdlib)

## Testing

Tests are in `tests/` and `src/` (pytest discovers both).

**Core data tests:**
- `test_address_store.py` - Store operations, undo/redo, base+overlay merging, cascades
- `test_mutable_row_builder.py` - Builder pattern, freeze behavior, immutability
- `test_address_model.py` - AddressRow validation, frozen dataclass behavior

**Service tests** (fully unit testable without tkinter):
- `test_block_service.py` - Block tag parsing, color assignment, range detection
- `test_row_service.py` - Fill down, clone structure, edit session integration
- `test_blocktag.py` - Tag parsing edge cases
- `test_dependency_service.py` - T/TD sync, cascade operations

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
- Cascades (T/TD sync, block tag sync) happen automatically within the session

### Dirty State Detection
- Check via `store.is_dirty(addr_key)`, not `row.is_dirty` property
- Fast reference equality: `visible_row is base_row` means clean
- Per-field dirty: `store.is_field_dirty(addr_key, "nickname")`

### Undo/Redo
- Tracks user intent (overlay layer) only, not database state
- Max 50 undo frames (configurable via `MAX_UNDO_DEPTH`)
- Undo after save restores unsaved state (overrides preserved)
- Keyboard: Ctrl+Z (undo), Ctrl+Y (redo)

### Block Colors
- Block colors are stored in `AddressStore.block_colors` dict, NOT in `AddressRow`
- Access via `store.get_block_color(addr_key)` → returns color name or None
- Colors are derived from comments (block tags) and recomputed automatically
- Kept separate to avoid row recreation on color changes and exclude from undo/redo
