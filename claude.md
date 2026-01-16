# CLAUDE.md

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

**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

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

### Optional: Context with RepoMapper

When working on specific files, get targeted context:  
```bash
uv run repomapper src/clicknick/ --map-tokens 1500 --chat-files src/clicknick/specific_file.py
```

Don't use RepoMapper for simple searches or finding definitions—use lsp (or grep/glob) for those instead.

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
├── data/                  # Data loading and shared state
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

## Module Documentation

For detailed information about each module, see:
- **[models/](src/clicknick/models/README.md)** - Data models, validation, block tags
- **[data/](src/clicknick/data/README.md)** - Shared state, data sources, observer pattern
- **[services/](src/clicknick/services/README.md)** - Business logic layer
- **[views/](src/clicknick/views/README.md)** - UI windows and panels
- **[widgets/](src/clicknick/widgets/README.md)** - Reusable UI components
- **[utils/](src/clicknick/utils/README.md)** - Filters, MDB operations, Win32 utilities
- **[detection/](src/clicknick/detection/README.md)** - Window detection for Click.exe

## Key Architectural Patterns

### Unidirectional Data Flow

The application uses a strict unidirectional data flow pattern:

1. **View** requests an edit via `SharedData.edit_session()`
2. **Service** (or View) modifies **Model** properties inside the session
3. **Model** marks itself as dirty and reports to the session
4. **SharedData** closes session → validates → broadcasts changed indices
5. **All Views** receive changed indices and redraw only those rows

**The Rules:**
1. **Models are Locked:** `AddressRow` raises `RuntimeError` if modified outside `edit_session`
2. **SharedData is the Gatekeeper:** Only `SharedAddressData` can open `edit_session`
3. **Services are Pure Logic:** Services **never** import `tkinter`
4. **Views are Passive:** Views only read state and listen for `on_data_changed` signals

### Static Skeleton Architecture

The Address Editor uses a "skeleton" of persistent `AddressRow` objects:
- ~17,000 empty `AddressRow` objects created at initialization (one per valid PLC address)
- All tabs and windows reference the **same** row objects (not copies)
- Edits to any row are instantly visible everywhere
- Skeleton rows are hydrated in-place from database, not replaced

### Observer Pattern

All views register as observers with `SharedAddressData`:
- `register_observer()` - Subscribe to data changes
- `on_data_changed(sender, changed_indices)` - Receive change notifications
- Views refresh only changed rows, not entire table
- Sender excluded from notifications (no self-refresh)

## Key Dependencies

- `pywin32` - Python for Win32 (pywin32) extensions
- `pyodbc` - ODBC connection to Access database
- `tksheet` - Spreadsheet widget for Address Editor v7 (documentation at https://ragardner.github.io/tksheet/DOCUMENTATION.md)
- `tkinter` - GUI framework (stdlib)

## Testing

Tests are in `tests/` and `src/` (pytest discovers both).

**Service tests** (fully unit testable without tkinter):
- `test_block_service.py` - Block tag parsing, color assignment, range detection
- `test_row_service.py` - Fill down, clone structure, dependency resolution
- `test_blocktag.py` - Tag parsing edge cases

**Other tests:**
- Filter tests cover abbreviation matching edge cases
- Address model tests cover validation and dirty tracking
- View tests are integration tests requiring tkinter
