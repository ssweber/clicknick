# Utils Module

This module provides utility functions and classes for filtering, database operations, and Windows API interactions.

## Overview

The utils package contains cross-cutting concerns that don't fit cleanly into models, data, services, or views:
- **Filters** - Autocomplete filtering strategies with abbreviation matching
- **MDB Operations** - ODBC access to CLICK Access database files
- **Win32 Utilities** - Windows API wrappers for window detection and control manipulation

## Filter System

The filter system provides flexible strategies for nickname autocomplete with advanced abbreviation matching.

### Filter Architecture

All filters implement the `FilterBase` abstract class:

```python
class FilterBase(ABC):
    @abstractmethod
    def filter_matches(
        self,
        completion_list: list[Nickname],
        current_text: str
    ) -> list[Nickname]:
        """Filter completions based on current text."""
        pass
```

### Available Filters

#### `NoneFilter`
No filtering - returns all nicknames:

```python
filter = NoneFilter()
results = filter.filter_matches(all_nicknames, "pump")
# Returns all nicknames regardless of search text
```

**Use Case:** Show all available nicknames in dropdown

#### `PrefixFilter`
Simple prefix matching (case-insensitive):

```python
filter = PrefixFilter()
results = filter.filter_matches(all_nicknames, "tank")
# Returns: Tank1_Level, Tank2_Level, TankAlarm
# Does NOT return: SupplyTank_Pump (doesn't start with "tank")
```

**Use Case:** Fast, predictable autocomplete for users who type linearly

#### `ContainsFilter`
Substring matching anywhere in nickname:

```python
filter = ContainsFilter()
results = filter.filter_matches(all_nicknames, "pump")
# Returns: MainPump_Status, Tank1_PumpSpeed, PumpAlarm
```

**Use Case:** More flexible than prefix, finds matches anywhere

#### `ContainsPlusFilter` (Advanced)
Substring matching with abbreviation support:

```python
filter = ContainsPlusFilter()
results = filter.filter_matches(all_nicknames, "tp")
# Returns: Tank_Pump, TowerPressure, Transfer_Pump
# Matches: Tank_Pump (T + P), TowerPressure (T + P)
```

**Features:**
- Substring matching (like `ContainsFilter`)
- Abbreviation matching (initial letters)
- Underscore-aware abbreviations
- Performance optimized with `lru_cache`

**Algorithm:**
1. Generate abbreviation tags for each nickname
2. Match search text against:
   - Full nickname (substring)
   - Word initials (e.g., "tp" matches "Tank_Pump")
   - Segment initials (e.g., "mps" matches "Main_Pump_Status")

### Abbreviation Tag Generation

The `ContainsPlusFilter` pre-generates abbreviation tags for fast matching:

```python
def _generate_abbreviation_tags(nickname: str) -> list[str]:
    """Generate searchable abbreviation tags."""
    tags = []

    # Full nickname (lowercase)
    tags.append(nickname.lower())

    # Word initials (e.g., "Tank_Pump_Status" → "tps")
    words = nickname.split("_")
    initials = "".join(w[0].lower() for w in words if w)
    tags.append(initials)

    # All prefix combinations (e.g., "tps" → "t", "tp", "tps")
    for i in range(1, len(initials) + 1):
        tags.append(initials[:i])

    # Camel case initials (e.g., "TankPump" → "tp")
    camel_initials = "".join(c for c in nickname if c.isupper()).lower()
    if camel_initials:
        tags.append(camel_initials)

    return tags
```

**Example:**
```python
nickname = "Tank1_Pump_Status"
tags = _generate_abbreviation_tags(nickname)
# Result: ["tank1_pump_status", "tps", "t", "tp", "tps"]
```

**Performance:**
- Tags generated once and cached via `@lru_cache(maxsize=10000)`
- Cache invalidated when shared data changes
- Typical tag generation: <1ms per 1000 nicknames

### Filter Usage Example

```python
# In NicknameManager
def get_filtered_nicknames(
    self,
    filter_strategy: FilterBase,
    search_text: str,
    allowed_types: set[str] | None = None
) -> list[Nickname]:
    """Get filtered nicknames for autocomplete."""
    # Get all nicknames
    all_nicknames = self._build_nickname_cache()

    # Filter by memory type
    if allowed_types:
        all_nicknames = [n for n in all_nicknames if n.memory_type in allowed_types]

    # Apply filter strategy
    return filter_strategy.filter_matches(all_nicknames, search_text)
```

**In Overlay:**
```python
# User types "tp" in overlay
filter = ContainsPlusFilter()
results = nickname_manager.get_filtered_nicknames(
    filter_strategy=filter,
    search_text="tp",
    allowed_types={"X", "Y", "C"}
)
# Results: Tank_Pump, Transfer_Pump, Tower_Pressure, etc.
```

## MDB Operations

ODBC-based operations for reading/writing CLICK Access database files.

### `mdb_shared.py`
Shared utilities for MDB access:

**Connection Management:**
```python
def get_mdb_connection(mdb_path: str) -> pyodbc.Connection:
    """Get ODBC connection to Access database."""
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={mdb_path};"
    )
    return pyodbc.connect(conn_str)
```

**Table Queries:**
```python
def get_table_names(mdb_path: str) -> list[str]:
    """Get list of tables in MDB file."""

def table_exists(mdb_path: str, table_name: str) -> bool:
    """Check if table exists in MDB."""
```

### `mdb_operations.py`
ODBC read/write operations for Address Editor:

**Load Addresses:**
```python
def load_addresses_from_mdb(mdb_path: str) -> list[dict]:
    """Load all addresses with nicknames from MDB."""
    conn = get_mdb_connection(mdb_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Address, Nickname, Comment, InitialValue, Retentive
        FROM Addresses
        ORDER BY Address
    """)

    return [
        {
            "address": row.Address,
            "nickname": row.Nickname,
            "comment": row.Comment,
            "initial_value": row.InitialValue,
            "retentive": row.Retentive
        }
        for row in cursor.fetchall()
    ]
```

**Save Addresses:**
```python
def save_addresses_to_mdb(
    mdb_path: str,
    rows: list[AddressRow]
):
    """Write address rows to MDB."""
    conn = get_mdb_connection(mdb_path)
    cursor = conn.cursor()

    for row in rows:
        cursor.execute("""
            UPDATE Addresses
            SET Nickname = ?, Comment = ?, InitialValue = ?, Retentive = ?
            WHERE Address = ?
        """, (row.nickname, row.comment, row.initial_value, row.retentive, row.address_key))

    conn.commit()
```

**ODBC Error Handling:**
```python
try:
    conn = get_mdb_connection(mdb_path)
except pyodbc.Error as e:
    # Show ODBC warning dialog to user
    show_odbc_warning_dialog(parent, error=str(e))
```

### MDB File Detection

```python
def find_mdb_file(project_dir: str) -> str | None:
    """Find SC_.mdb file in project directory."""
    pattern = os.path.join(project_dir, "SC_*.mdb")
    matches = glob.glob(pattern)
    return matches[0] if matches else None
```

## Win32 Utilities

Windows API wrappers for window detection and control manipulation.

### `win32_utils.py`
Singleton wrapper for Windows API utilities:

**Window Enumeration:**
```python
def enum_windows() -> list[int]:
    """Enumerate all top-level windows."""
    windows = []
    def callback(hwnd, _):
        windows.append(hwnd)
        return True
    win32gui.EnumWindows(callback, None)
    return windows
```

**Window Properties:**
```python
def get_window_text(hwnd: int) -> str:
    """Get window title."""
    return win32gui.GetWindowText(hwnd)

def get_class_name(hwnd: int) -> str:
    """Get window class name."""
    return win32gui.GetClassName(hwnd)

def is_window_visible(hwnd: int) -> bool:
    """Check if window is visible."""
    return win32gui.IsWindowVisible(hwnd)
```

**Window Positioning:**
```python
def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Get window position and size (left, top, right, bottom)."""
    return win32gui.GetWindowRect(hwnd)

def get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Get client area rect."""
    return win32gui.GetClientRect(hwnd)
```

**Control Text Manipulation:**
```python
def get_control_text(hwnd: int) -> str:
    """Get text from edit control."""
    length = win32gui.SendMessage(hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
    buffer = win32gui.PyMakeBuffer(length + 1)
    win32gui.SendMessage(hwnd, win32con.WM_GETTEXT, length + 1, buffer)
    return buffer[:length].decode("utf-16-le")

def set_control_text(hwnd: int, text: str):
    """Set text in edit control."""
    win32gui.SendMessage(hwnd, win32con.WM_SETTEXT, 0, text)
```

**Child Window Enumeration:**
```python
def enum_child_windows(parent_hwnd: int) -> list[int]:
    """Enumerate child windows of parent."""
    children = []
    def callback(hwnd, _):
        children.append(hwnd)
        return True
    win32gui.EnumChildWindows(parent_hwnd, callback, None)
    return children
```

**Process Information:**
```python
def get_process_name(hwnd: int) -> str:
    """Get process name for window."""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
    exe_path = win32process.GetModuleFileNameEx(handle, 0)
    return os.path.basename(exe_path)
```

### Win32 Usage Example

**Overlay Positioning:**
```python
# Get target control rect
control_rect = win32_utils.get_window_rect(control_hwnd)
left, top, right, bottom = control_rect

# Position overlay at control location
overlay.geometry(f"{right-left}x{bottom-top}+{left}+{top}")
```

**Autocomplete Insert:**
```python
# Get current text in control
current_text = win32_utils.get_control_text(control_hwnd)

# Insert selected nickname
selected_address = "X001"
win32_utils.set_control_text(control_hwnd, selected_address)
```

## Testing

Utils tests are in `tests/test_utils/`:
- `test_filters.py` - Filter strategies, abbreviation matching edge cases
- `test_mdb_operations.py` - ODBC operations (requires Access drivers)
- Win32 utilities are integration-tested via overlay tests
