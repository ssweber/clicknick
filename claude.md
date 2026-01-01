# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ClickNick** is a Windows desktop application providing context-aware nickname autocomplete and editing tools for CLICK PLC Programming Software (v2.60–v3.80). It connects via ODBC to read/write nicknames from the project's Access database (SC_.mdb) or can import from CSV. Core components:

- **Overlay** – Positions a combobox over instruction dialog edit controls for nickname autocomplete
- **Address Editor** – Multi-window tksheet-based editor with search/replace, block tagging, validation
- **Navigation Dock** – Treeview of nicknames parsed by underscore segments and array indices
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
├── utils/                 # Utilities (filters, MDB, Win32)
├── views/                 # Windows and panels
│   ├── address_editor/    # Address Editor views
│   ├── dataview_editor/   # Dataview Editor views
│   └── nav_window/        # Navigation window (outline, blocks)
├── widgets/               # Reusable UI components
├── detection/             # Window detection for Click.exe
└── resources/             # Icons and static assets
```

### Core Packages

**`models/`** - Data models and constants
- `constants.py` - ADDRESS_RANGES, MEMORY_TYPE_BASES, DEFAULT_RETENTIVE, DataType enum
- `address_row.py` - `AddressRow` dataclass with dirty tracking, validation, CRUD helpers
- `nickname.py` - `Nickname` dataclass for autocomplete (lightweight, immutable)
- `dataview_row.py` - `DataviewRow` dataclass for CDV files
- `blocktag.py` - BlockTag model for block-level tagging in comments
- `validation.py` - Nickname and initial value validation functions

**`data/`** - Data loading and shared state
- `shared_data.py` - `SharedAddressData`: single source of truth for all address data, observer pattern, file monitoring
- `shared_dataview.py` - `SharedDataviewData`: read-only shim over `SharedAddressData` for nickname lookups, manages CDV files
- `data_source.py` - Abstract `DataSource` with `MdbDataSource` and `CsvDataSource`
- `nickname_manager.py` - Read-only shim over `SharedAddressData`, provides filtering for Overlay autocomplete

**`utils/`** - Utilities
- `filters.py` - Filter strategies: `NoneFilter`, `PrefixFilter`, `ContainsFilter`, `ContainsPlusFilter`
- `mdb_shared.py` - Shared MDB/Access database utilities
- `mdb_operations.py` - ODBC read/write operations for Address Editor
- `win32_utils.py` - Singleton wrapper for Windows API utilities

**`views/`** - Windows and panels
- `overlay.py` - `tk.Toplevel` overlay positioned over target edit controls
- `dialogs.py` - About and ODBC warning dialogs
- `address_editor/` - Multi-window editor for PLC addresses
  - `window.py` - Main AddressEditorWindow
  - `panel.py` - AddressPanel (tksheet-based) for each memory type
  - `view_builder.py` - TypeView construction for shared display data
  - `jump_sidebar.py` - JumpSidebar for quick navigation
  - `row_styler.py` - Visual styling for validation, dirty tracking, blocks
- `dataview_editor/` - Editor for CLICK DataView files (.cdv)
  - `window.py` - DataviewEditorWindow with file list sidebar
  - `panel.py` - DataviewPanel (tksheet-based) for editing
  - `cdv_file.py` - CDV file I/O (UTF-16 CSV format)
- `nav_window/` - Floating navigation window
  - `window.py` - NavWindow that docks to parent
  - `outline_panel.py` - Hierarchical treeview of nicknames by underscore segments
  - `outline_logic.py` - Tree building logic (segment parsing, array detection)
  - `block_panel.py` - Block navigation from `<Block>` tags in comments

**`widgets/`** - Reusable UI components
- `nickname_combobox.py` - Custom autocomplete combobox with keyboard navigation
- `floating_tooltip.py` - Shows nickname details on hover
- `prefix_autocomplete.py` - Prefix-based autocomplete logic
- `add_block_dialog.py` - Dialog for adding address blocks
- `char_limit_tooltip.py` - Character limit indicator
- `colors.py` - Color constants for the editor UI

**`detection/`** - Window detection
- `window_detector.py` - Detects Click.exe child windows, validates controls
- `window_mapping.py` - Maps window classes to edit controls and allowed address types

### Data Flow

**Initialization (on connect_to_instance):**
1. `SharedAddressData` created with `MdbDataSource` or `CsvDataSource`
2. `load_initial_data()` populates `all_rows: dict[int, AddressRow]`
3. `start_file_monitoring()` begins polling for external MDB/CSV changes
4. `NicknameManager.set_shared_data()` wires it as observer for cache invalidation

**Autocomplete Flow:**
1. `ClickWindowDetector` polls for Click.exe child windows (instruction dialogs)
2. When detected, `Overlay` positions over the target edit control
3. `NicknameManager.get_filtered_nicknames()` builds/uses cached `Nickname` list from `SharedAddressData.all_rows`
4. Selection inserts address via Win32 `set_control_text`

**Change Propagation:**
1. Address Editor or external MDB change triggers `SharedAddressData.notify_data_changed()`
2. All observers notified (NicknameManager, AddressEditorWindows, SharedDataviewData)
3. NicknameManager invalidates its nickname cache, rebuilt on next filter request
4. SharedDataviewData triggers `refresh_nicknames_from_shared()` on DataviewEditorWindow

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

## Block Tag Specification

Block tags are added in the Comment field to create visual blocks in the Address Editor.

**Syntax:**
- `<BlockName>` – Opening tag for a range
- `</BlockName>` – Closing tag for a range
- `<BlockName />` – Self-closing tag for a single address
- `<BlockName bg="#color">` – Adds background color

**Colors:** HEX codes or keywords: Red, Pink, Purple, Deep Purple, Indigo, Blue, Light Blue, Cyan, Teal, Green, Light Green, Lime, Yellow, Amber, Orange, Deep Orange, Brown, Blue Grey

Example: `<Alm Bits bg="Red">` ... `</Alm Bits>`

## Navigation Dock Logic

**Hierarchy:** Single underscores create tree levels.
- `SupplyTank_Pump_Status` → `SupplyTank` > `Pump` > `Status`

**Arrays:** Trailing numbers auto-group.
- `Alm1_id`, `Alm1_value`, `Alm2_id`, `Alm2_value` → `Alm[1-2]` with nested `id`, `value` leaves
