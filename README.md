![clicknick_logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

# clicknick

Nickname autocomplete for ClickPLC instruction windows and modern Address Editor tool.

![ClickNick demo](https://github.com/user-attachments/assets/0275dcf4-6d79-4775-8763-18b13e8fd3a3)

## Features

- **Live Nicknames**: Immediate access to Nicknames in your CLICK Programming Software, via ODBC connection.
- **Smart Autocomplete**: Shows only relevant nicknames based on the open instruction window.
- **Multiple Filter Modes**: Flexible search options:  
  - **Prefix**: Match starting characters (e.g., `"Val"` → `"Valve_1"`).  
  - **Contains**: Find nicknames with any part of the text (e.g., `"Run"` → `"Motor_Run"`).  
  - **Abbreviation**: Supports **two-way shorthand** and **multi-word matching** (e.g., `"Motor Speed"` → `"Mtr_Spd"` or `"MtrSpd"` → `"MotorSpeed"`).
- **Helpful Tooltips**: Displays address comments on hover for quick reference.
- **Exclusion Filters**:  
  - Hide system addresses (SC/SD) to reduce clutter.  
  - Exclude addresses based on custom naming conventions (e.g., omit nicknames containing double underscores `__` if you use them for private or internal variables).
## Address Editor  

A powerful alternative to ClickPLC's built-in Address Picker, bringing modern editing capabilities to tag management.

- **Multiple Windows**: Edit different tag sections simultaneously.
- **Bulk Editing**: Work on addresses before saving, with live duplicate and validation error highlighting.
- **Copy/Paste Multiple Rungs**
- **Search & Replace**:Search (Ctrl+F) and Replace (Ctrl+H) with 'In Selection' support.
- **Smart Filtering**
- **Organized Navigation**: Add `<Tags>` in address comments to create hierarchical headers in address jump-to lists.

![Address Editor](https://github.com/user-attachments/assets/REPLACE_WITH_ACTUAL_SCREENSHOT)  

## How to Run
> [!NOTE]
> For live nickname database functionality, you'll need Microsoft Access ODBC drivers installed. If you see an "ODBC drivers not found" warning, see our [installation guide](https://github.com/ssweber/clicknick/issues/17) for help. CSV nickname file loading works without these drivers.

### Option 1: Using uv (recommended)
**Try it out:**
```cmd
uvx clicknick@latest
```

**Install for offline use:**
```cmd
uv tool install clicknick
```

**Run:** `clicknick` (from command line or Start Menu)

**Uninstall:** `uv tool uninstall clicknick`  
**Upgrade:** `uv tool upgrade clicknick`

If you don't have uv: https://github.com/astral-sh/uv#installation

### Option 2: Using pip
```cmd
pip install clicknick
python -m clicknick
```

## Usage

1. Open CLICK Programming Software project.
2. Launch ClickNick to add Auto-Complete to where you typically enter Memory Addresses.
3. Open Tools -> Address Editor for advanced tag management with full search, filtering, and bulk editing capabilities

## Requirements

- Windows 10 or 11
- CLICK Programming Software (v2.60 – v3.71).
- Address Editor requires Microsoft Access ODBC drivers

## Auto-Complete Supported Windows

- Contact Normally Open/Closed
- Edge Contact
- Out, Set, Reset
- Compare (A with B)
- Timer, Counter
- Math instructions
- Shift Register
- Copy instruction
- Search instruction
- Search & Replace dialogs
- Data Views
- Address Picker `Find`
- Modbus Send/Receive

* * *

## Project Docs

For how to install uv and Python, see [installation.md](installation.md).

For development workflows, see [development.md](development.md).

For instructions on publishing to PyPI, see [publishing.md](publishing.md).

* * *

*This project was built from
[simple-modern-uv](https://github.com/jlevy/simple-modern-uv).*

