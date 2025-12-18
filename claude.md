# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ClickNick** is a Windows desktop application providing context-aware nickname autocomplete for ClickPLC instruction windows. It connects to the CLICK Programming Software via ODBC to read nicknames from its Access database (SC_.mdb) and displays an overlay combobox when users interact with supported PLC instruction dialogs.

## Build & Development Commands

```bash
# Install dependencies
make install                    # or: uv sync --all-extras --dev

# Default workflow (install + lint + test)
make

# Individual commands
make lint                       # Run codespell, ssort, ruff (check + format)
make test                       # Run pytest
make build                      # Build wheel with uv

# Run directly
uv run clicknick                # Run the app
uv run pytest                   # All tests
uv run pytest tests/test_filters.py  # Single test file
uv run pytest -s tests/test_filters.py::test_name  # Single test with output

# Install as editable local tool
uv tool install --editable .
```

## Architecture

### Entry Points
- `clicknick` (GUI) / `clicknick-debug` (console) - both call `clicknick:main`
- Main app: `src/clicknick/clicknick.py` -> `ClickNickApp` class

### Core Components

**Window Detection & Integration**
- `window_detector.py` - Detects Click.exe child windows, validates controls using AHK
- `window_mapping.py` - Maps window classes to edit controls and their allowed address types
- `win32_utils.py` - Singleton wrapper for Windows API utilities using pywin32

**Nickname Management**
- `nickname_manager.py` - Loads nicknames from CSV or ODBC (Access .mdb), manages filtering
- `nickname.py` - `Nickname` dataclass with address, type, comment, abbreviation tags
- `filters.py` - Filter strategies: `NoneFilter`, `PrefixFilter`, `ContainsFilter`, `ContainsPlusFilter`
- `mdb_shared.py` - Shared MDB/Access database utilities (used both by NicknameManager and the Address Editor)

**UI Components**
- `overlay.py` - `tk.Toplevel` overlay positioned over target edit controls
- `nickname_combobox.py` - Custom autocomplete combobox with keyboard navigation
- `floating_tooltip.py` - Shows nickname details on hover
- `prefix_autocomplete.py` - Prefix-based autocomplete for combobox
- `settings.py` - `AppSettings` with persistence (search mode, exclusions, tooltips)
- `dialogs.py` - About and ODBC warning dialogs

**Address Editor** (`src/clicknick/address_editor/`)
- Multi-window editor for PLC addresses with sync between instances
- `address_editor_window.py` - Main editor window & Outline window
- `address_panel.py` - Tab panel for each memory type
- `address_model.py` - Data model, validation, constants (ADDRESS_RANGES, MEMORY_TYPE_BASES)
- `address_outline.py` - Hierarchical treeview of nicknames (toggleable right sidebar)
- `blocktag_model.py` - BlockTag model for block-level tagging
- `add_block_dialog.py` - Dialog for adding address blocks
- `jump_sidebar.py` - JumpSidebar and JumpButton for quick navigation
- `colors.py` - Color constants and functions for the editor UI
- `mdb_operations.py` - ODBC read/write to Access database
- `shared_data.py` - `SharedAddressData` for cross-window synchronization
- `outline_panel.py` - OutlinePanel displays a tkinter treeview of nicknames, parsed hierarchically by underscore segments. Double-click navigates to the address in the main panel.
- `outline_logic.py` - Tree building logic for the outline. Parses nicknames into segments (single _ splits, double __ preserves literal underscore), detects array indices from trailing numbers, collapses single-child chains. Entry order is memory type (per MEMORY_TYPE_ORDER) then address.

### Data Flow
1. `ClickWindowDetector` polls for Click.exe child windows (instruction dialogs)
2. When detected, `Overlay` positions over the target edit control
3. `NicknameManager.get_filtered_nicknames()` filters by address type + search text
4. Selection inserts address via Win32 `set_control_text`

### Filter System
Filters implement `FilterBase.filter_matches(completion_list, current_text)`:
- `ContainsPlusFilter` is the advanced filter with abbreviation support, uses `lru_cache` for tag generation
- Abbreviation tags are pre-generated per nickname via `_generate_abbreviation_tags()`

## Key Dependencies
- `pywin32` - Python for Win32 (pywin32) extensions
- `pyodbc` - ODBC connection to Access database
- `tksheet` - Spreadsheet widget for Address Editor v7 (documentation at https://ragardner.github.io/tksheet/DOCUMENTATION.md)
- `tkinter` - GUI framework (stdlib)

## Testing
Tests are in `tests/` and `src/` (pytest discovers both). Filter tests cover abbreviation matching edge cases.
