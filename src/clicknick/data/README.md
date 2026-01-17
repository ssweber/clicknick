# Data Module

This module manages the shared state and data sources for ClickNick, implementing the observer pattern for reactive UI updates.

## Overview

The data package is the **single source of truth** for all address and dataview data in the application. It enforces unidirectional data flow through edit sessions and broadcasts changes to all observers (views).

## Core Architecture

### Static Skeleton Pattern

ClickNick uses a "skeleton" of persistent `AddressRow` objects:
- On initialization, ~17,000 empty `AddressRow` objects are created (one per valid PLC address)
- All tabs and windows reference the **same** row objects (not copies)
- Edits to any row are instantly visible in all views
- Skeleton rows are hydrated with data from the database, not replaced

### Observer Pattern

All views register as observers and receive change notifications:
```python
class MyView:
    def on_data_changed(self, sender, changed_indices: set[int]):
        """Called when data changes. Refresh only changed rows."""
        self.refresh_rows(changed_indices)

shared_data.register_observer(my_view)
```

## Core Components

### `shared_data.py` - SharedAddressData

The central data manager for all address data.

**Key Methods:**
```python
class SharedAddressData:
    def __init__(self, data_source: DataSource):
        """Initialize with MDB or CSV data source."""

    @contextmanager
    def edit_session(self):
        """Context manager for controlled state modifications."""
        # Unlocks AddressRow fields, tracks changes, validates on close

    def notify_data_changed(self, sender, changed_indices: set[int]):
        """Broadcast changes to all observers except sender."""

    def register_observer(self, observer):
        """Register a view to receive change notifications."""

    def load_initial_data(self):
        """Load data from source into skeleton rows."""

    def start_file_monitoring(self):
        """Begin polling for external file changes (every 2 seconds)."""

    def save_changes(self):
        """Write dirty rows to database."""

    def discard_changes(self):
        """Revert all dirty rows to original values."""
```

**Edit Session Pattern:**
Edit sessions enforce the unidirectional data flow:

```python
# CORRECT - controlled modification
with shared_data.edit_session() as session:
    row.nickname = "NewName"
    row.comment = "Updated comment"
    session.mark_changed(row)
# Session closes → validates → broadcasts to all observers

# INCORRECT - direct modification
row.nickname = "NewName"  # RuntimeError! Must use edit_session
```

**Why Edit Sessions?**
1. **Centralized Control** - Only `SharedAddressData` can unlock row fields
2. **Automatic Validation** - All changes validated before broadcast
3. **Batch Updates** - Multiple changes broadcast together efficiently
4. **Predictable Flow** - Views always receive notifications, never miss changes

### `data_source.py` - Data Source Abstraction

Abstract interface for reading/writing address data:

```python
class DataSource(ABC):
    @abstractmethod
    def load_all_addresses(self) -> list[dict]:
        """Load all addresses with nicknames/comments."""

    @abstractmethod
    def save_addresses(self, rows: list[AddressRow]):
        """Write modified addresses to storage."""

    @abstractmethod
    def get_file_path(self) -> str | None:
        """Get file path for monitoring."""
```

**Implementations:**
- `MdbDataSource` - Reads/writes to CLICK Access database (SC_.mdb) via ODBC
- `CsvDataSource` - Reads/writes to CSV file (nickname export)

### `nickname_manager.py` - NicknameManager

Read-only shim over `SharedAddressData` for autocomplete:

**Features:**
- Builds lightweight `Nickname` objects from skeleton rows
- Caches nickname list for performance
- Invalidates cache on data changes (via observer pattern)
- Provides filtering for overlay autocomplete

**Usage:**
```python
manager = NicknameManager()
manager.set_shared_data(shared_data)  # Registers as observer

# Get filtered nicknames for autocomplete
nicknames = manager.get_filtered_nicknames(
    filter_strategy=ContainsPlusFilter(),
    search_text="pump",
    allowed_types={"X", "Y"}
)
```

### `shared_dataview.py` - SharedDataviewData

Read-only shim over `SharedAddressData` for dataview editor:

**Features:**
- Provides nickname lookups for CDV files
- Manages list of dataview files in project directory
- No direct editing of address data (delegates to SharedAddressData)

**Usage:**
```python
dataview_data = SharedDataviewData(shared_data)
dataview_data.load_cdv_files(project_dir)

# Lookup nickname for address
nickname = dataview_data.get_nickname_for_address("X001")
```

## Data Flow Details

### Initialization Flow (on connect_to_instance)

1. **Create SharedAddressData**
   ```python
   data_source = MdbDataSource(mdb_path) or CsvDataSource(csv_path)
   shared_data = SharedAddressData(data_source)
   ```

2. **Create Skeleton**
   ```python
   # _create_skeleton() creates ~17,000 empty AddressRow objects
   # One row per valid PLC address (X001-X999, Y001-Y999, etc.)
   ```

3. **Load Initial Data**
   ```python
   shared_data.load_initial_data()
   # Hydrates skeleton rows in-place from database
   # row.update_from_db(db_data) - does NOT replace rows
   ```

4. **Start File Monitoring**
   ```python
   shared_data.start_file_monitoring()
   # Polls file modification time every 2 seconds
   # Reloads on external changes (preserves dirty fields)
   ```

5. **Wire Observers**
   ```python
   NicknameManager.set_shared_data(shared_data)  # Cache invalidation
   address_panel.register_with_shared_data(shared_data)  # UI updates
   nav_window.register_with_shared_data(shared_data)  # Tree refresh
   ```

### Edit Flow (Unidirectional)

1. **User edits cell in panel**
   - User types in tksheet cell
   - Panel captures edit in `on_cell_edit()` event

2. **Panel opens edit session**
   ```python
   with shared_data.edit_session() as session:
       row = self.view.rows[row_index]
       row.nickname = new_value
       session.mark_changed(row)
   ```

3. **Session closes → validation**
   - All modified rows validated
   - Invalid rows marked with `validation_error`
   - Valid rows remain dirty until saved

4. **Broadcast to observers**
   ```python
   shared_data.notify_data_changed(sender=self, changed_indices={row_index})
   ```

5. **All OTHER panels refresh**
   ```python
   def on_data_changed(self, sender, changed_indices):
       if sender is self:
           return  # Don't refresh own changes
       self.refresh_rows(changed_indices)  # Repaint only changed rows
   ```

**Key Insight:** Views don't manage state; they react to broadcasts.

### Service Operation Flow

Services perform complex operations using edit sessions:

```python
class RowService:
    @staticmethod
    def fill_down_rows(shared_data: SharedAddressData, rows: list[AddressRow], source_row: AddressRow):
        with shared_data.edit_session() as session:
            for row in rows:
                row.nickname = source_row.nickname
                row.comment = source_row.comment
                session.mark_changed(row)
        # Session closes → automatic validation and broadcast
        # All views refresh via observer pattern
```

### External Change Flow

When the MDB file is modified externally (e.g., by CLICK software):

1. **File monitor detects change**
   ```python
   # Polls every 2 seconds
   if current_mtime > self._last_mtime:
       self._reload_from_source()
   ```

2. **Reload from source**
   ```python
   def _reload_from_source(self):
       db_data = self.data_source.load_all_addresses()
       for row in self.all_rows:
           if not row.is_dirty():  # Preserve user edits!
               row.update_from_db(db_data)
   ```

3. **Broadcast changes**
   ```python
   self.notify_data_changed(sender=None, changed_indices=all_indices)
   ```

4. **All views refresh**
   - Address panels repaint affected rows
   - Tag Browser rebuilds tree
   - JumpSidebar updates status indicators

### Save/Discard Flow

**Save Changes:**
```python
def save_changes(self):
    dirty_rows = [row for row in self.all_rows if row.is_dirty()]
    self.data_source.save_addresses(dirty_rows)

    for row in dirty_rows:
        row.mark_saved()  # Resets dirty tracking, keeps current values

    self.notify_data_changed(sender=None, changed_indices=dirty_indices)
```

**Discard Changes:**
```python
def discard_changes(self):
    dirty_rows = [row for row in self.all_rows if row.is_dirty()]

    for row in dirty_rows:
        row.discard()  # Reverts to original snapshot values

    self.notify_data_changed(sender=None, changed_indices=dirty_indices)
```

### `file_monitor.py` - FileMonitor

Watches a file for external modifications and triggers a callback:

```python
class FileMonitor:
    def __init__(self, file_path: str | None, on_modified: Callable[[], None]):
        """Initialize with file path and callback."""

    def start(self, tk_root) -> None:
        """Start polling with tk.after()."""

    def stop(self) -> None:
        """Stop polling."""

    def update_mtime(self) -> None:
        """Refresh stored mtime after saving (prevents false detection)."""
```

**Usage:**
```python
monitor = FileMonitor(
    file_path="/path/to/file.mdb",
    on_modified=self._reload_from_source
)
monitor.start(tk_root)
# ... after saving ...
monitor.update_mtime()  # Prevent immediate reload
# ... on shutdown ...
monitor.stop()
```

## Thread Safety

**File monitoring runs on the main thread:**
- `start()` schedules polling via `tk.after()` (main thread)
- Polls file mtime every 2 seconds
- Callback runs on main thread
- All data modifications happen on main thread

## Performance Optimizations

1. **Lazy Nickname Cache** - `NicknameManager` builds cache only when needed
2. **Targeted Refreshes** - Views refresh only changed rows, not entire table
3. **Batch Updates** - Edit sessions batch multiple changes into single broadcast
4. **In-Place Hydration** - Skeleton rows updated in-place, not replaced (preserves references)

## Testing

Data tests are in `tests/test_data/`:
- `test_shared_data.py` - Edit sessions, observer pattern, validation
- `test_data_source.py` - MDB and CSV loading/saving
- `test_nickname_manager.py` - Cache invalidation, filtering
