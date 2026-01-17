# Services Module

This module contains the business logic layer for ClickNick, implementing complex operations on address data.

## Overview

Services perform complex data operations while maintaining strict architectural boundaries:
- **Pure Python** - Services NEVER import `tkinter` or UI code
- **Stateless** - Services operate on provided data, maintain no internal state
- **Edit Sessions** - Services use `SharedAddressData.edit_session()` for all modifications
- **Testable** - Fully unit testable without UI dependencies

## Service Layer Principles

### 1. Separation from UI
```python
# GOOD - Service has no tkinter imports
class RowService:
    @staticmethod
    def fill_down_rows(shared_data: SharedAddressData, ...):
        with shared_data.edit_session() as session:
            # Pure data manipulation
            pass

# BAD - Service importing UI code
from tkinter import messagebox  # NEVER do this in services!
```

### 2. Use Edit Sessions
```python
# GOOD - Service opens edit session
def fill_down_rows(shared_data, rows, source_row):
    with shared_data.edit_session() as session:
        for row in rows:
            row.nickname = source_row.nickname
            session.mark_changed(row)
    # Session closes → automatic validation and broadcast

# BAD - Direct modification
def fill_down_rows(shared_data, rows, source_row):
    for row in rows:
        row.nickname = source_row.nickname  # RuntimeError!
```

### 3. Return Results, Don't Show UI
```python
# GOOD - Return data, let caller handle UI
def get_dependencies(row: AddressRow) -> list[AddressRow]:
    return [r for r in all_rows if is_related(r, row)]

# BAD - Service showing dialogs
def get_dependencies(row: AddressRow):
    result = [...]
    messagebox.showinfo("Found", f"{len(result)} dependencies")  # NO!
    return result
```

## Core Services

### `row_service.py` - RowService

Operations on address rows (fill down, clone structure, dependencies).

#### `fill_down_rows()`
Propagate values from source row to target range:

```python
@staticmethod
def fill_down_rows(
    shared_data: SharedAddressData,
    rows: list[AddressRow],
    source_row: AddressRow,
    fill_nickname: bool = True,
    fill_comment: bool = True,
    fill_initial_value: bool = False,
    fill_retentive: bool = False
):
    """Fill down values from source to target rows."""
    with shared_data.edit_session() as session:
        for row in rows:
            if fill_nickname:
                row.nickname = source_row.nickname
            if fill_comment:
                row.comment = source_row.comment
            if fill_initial_value:
                row.initial_value = source_row.initial_value
            if fill_retentive:
                row.retentive = source_row.retentive
            session.mark_changed(row)
```

**Use Case:** User selects X001-X010, right-clicks X001, chooses "Fill Down"

#### `clone_structure_rows()`
Copy related addresses with auto-incrementing:

```python
@staticmethod
def clone_structure_rows(
    shared_data: SharedAddressData,
    source_row: AddressRow,
    target_rows: list[AddressRow]
):
    """Clone structure from source to targets with auto-increment."""
    # Find all related rows (by underscore segments)
    dependencies = DependencyService.get_dependencies(source_row, shared_data.all_rows)

    with shared_data.edit_session() as session:
        for target in target_rows:
            # Calculate offset between source and target
            offset = target.index - source_row.index

            # Clone each dependency with offset
            for dep in dependencies:
                target_index = dep.index + offset
                target_row = find_row(dep.memory_type, target_index)
                if target_row:
                    target_row.nickname = dep.nickname
                    target_row.comment = dep.comment
                    session.mark_changed(target_row)
```

**Use Case:** User has `Tank1_Level`, `Tank1_Setpoint`, `Tank1_Alarm` and wants to clone to Tank2, Tank3, etc.

**Example:**
```
Source: C001 = Tank1_Level
        C002 = Tank1_Setpoint
        C003 = Tank1_Alarm

Clone to C011:
Result: C011 = Tank2_Level
        C012 = Tank2_Setpoint
        C013 = Tank2_Alarm
```

#### `get_dependencies()`
Find related addresses by underscore segments:

```python
@staticmethod
def get_dependencies(
    row: AddressRow,
    all_rows: list[AddressRow]
) -> list[AddressRow]:
    """Find rows related by underscore segments."""
    if not row.nickname or "_" not in row.nickname:
        return [row]

    # Extract prefix (e.g., "Tank1" from "Tank1_Level")
    prefix = row.nickname.rsplit("_", 1)[0]

    # Find all rows starting with same prefix
    return [r for r in all_rows if r.nickname.startswith(f"{prefix}_")]
```

**Use Case:** Show user all related addresses when editing `Tank1_Level`

### `block_service.py` - BlockService

Block tag management (parsing, color assignment, range detection).

#### `parse_block_tags()`
Parse all block tags from address comments:

```python
@staticmethod
def parse_block_tags(rows: list[AddressRow]) -> list[tuple[int, BlockTag]]:
    """Parse block tags from all rows, return (row_index, tag) pairs."""
    result = []
    for i, row in enumerate(rows):
        if row.comment:
            tag = parse_block_tag(row.comment)
            if tag:
                result.append((i, tag))
    return result
```

#### `compute_block_colors()`
Precompute block colors for all skeleton rows:

```python
@staticmethod
def compute_block_colors(rows: list[AddressRow]):
    """Precompute row.block_color for all rows based on block tags."""
    # Parse all tags
    tags = BlockService.parse_block_tags(rows)

    # Match opening/closing pairs
    ranges = match_block_tags(tags)

    # Assign colors to ranges
    for start_idx, end_idx, color in ranges:
        for i in range(start_idx, end_idx + 1):
            rows[i].block_color = color  # System field, freely writable
```

**When Called:**
- On initial data load
- After any comment edit that might contain block tags
- After import

**Visual Result:**
Rows within block ranges are highlighted in the Address Editor with the specified background color.

#### `get_block_ranges()`
Get all block ranges for navigation:

```python
@staticmethod
def get_block_ranges(rows: list[AddressRow]) -> list[dict]:
    """Get list of block ranges for navigation sidebar."""
    tags = BlockService.parse_block_tags(rows)
    ranges = match_block_tags(tags)

    return [
        {
            "name": tag_name,
            "start_idx": start_idx,
            "end_idx": end_idx,
            "color": color,
            "start_address": rows[start_idx].address_key,
            "end_address": rows[end_idx].address_key
        }
        for start_idx, end_idx, color, tag_name in ranges
    ]
```

**Use Case:** Populate block navigation panel in Tag Browser

### `dependency_service.py` - DependencyService

Address dependency resolution (underscore segments, array patterns).

#### `resolve_dependencies()`
Resolve dependencies with underscore segment and array pattern matching:

```python
@staticmethod
def resolve_dependencies(
    row: AddressRow,
    all_rows: list[AddressRow],
    include_arrays: bool = True
) -> list[AddressRow]:
    """Resolve dependencies by segments and arrays."""
    if not row.nickname:
        return [row]

    deps = []

    # Underscore segment matching
    segments = row.nickname.split("_")
    for r in all_rows:
        if r.nickname.split("_")[:-1] == segments[:-1]:
            deps.append(r)

    # Array pattern matching (Tank1_Level, Tank2_Level)
    if include_arrays:
        match = re.match(r"(.+?)(\d+)(_.+)?", row.nickname)
        if match:
            base, num, suffix = match.groups()
            pattern = f"{base}\\d+{suffix or ''}"
            for r in all_rows:
                if re.match(pattern, r.nickname):
                    deps.append(r)

    return deps
```

#### `get_combined_type_pair()`
Support for combined memory types (T/TD, CT/CTD):

```python
@staticmethod
def get_combined_type_pair(memory_type: str) -> str | None:
    """Get paired type for combined types."""
    pairs = {
        "T": "TD",
        "TD": "T",
        "CT": "CTD",
        "CTD": "CT"
    }
    return pairs.get(memory_type)
```

**Use Case:** When cloning T001, automatically clone TD001 as well

### `import_service.py` - ImportService

CSV import processing (validation, duplicate detection).

#### `validate_import_data()`
Validate addresses before import:

```python
@staticmethod
def validate_import_data(
    import_rows: list[dict],
    existing_rows: list[AddressRow]
) -> tuple[list[dict], list[str]]:
    """Validate import data, return (valid_rows, error_messages)."""
    valid = []
    errors = []

    for row in import_rows:
        # Validate address format
        if not is_valid_address(row["address"]):
            errors.append(f"Invalid address: {row['address']}")
            continue

        # Validate nickname
        is_valid, error = validate_nickname(row["nickname"])
        if not is_valid:
            errors.append(f"{row['address']}: {error}")
            continue

        valid.append(row)

    return valid, errors
```

#### `detect_conflicts()`
Detect duplicate/conflicting nicknames:

```python
@staticmethod
def detect_conflicts(
    import_rows: list[dict],
    existing_rows: list[AddressRow]
) -> list[dict]:
    """Detect import rows that conflict with existing data."""
    conflicts = []

    for row in import_rows:
        existing = find_row(existing_rows, row["address"])
        if existing and existing.nickname and existing.nickname != row["nickname"]:
            conflicts.append({
                "address": row["address"],
                "existing_nickname": existing.nickname,
                "import_nickname": row["nickname"]
            })

    return conflicts
```

#### `perform_import()`
Execute import with edit session:

```python
@staticmethod
def perform_import(
    shared_data: SharedAddressData,
    import_rows: list[dict],
    overwrite: bool = False
):
    """Import validated rows into shared data."""
    with shared_data.edit_session() as session:
        for row_data in import_rows:
            row = find_row(shared_data.all_rows, row_data["address"])
            if row:
                if overwrite or not row.nickname:
                    row.nickname = row_data["nickname"]
                    row.comment = row_data.get("comment", "")
                    session.mark_changed(row)
```

## Service Operation Flow Example

**Full workflow for "Fill Down" operation:**

1. **View captures user intent**
   ```python
   # address_editor/window.py
   def on_fill_down_clicked(self):
       source_row = self.get_selected_row()
       target_rows = self.get_selected_range()
   ```

2. **View calls service**
   ```python
   RowService.fill_down_rows(
       shared_data=self.shared_data,
       rows=target_rows,
       source_row=source_row,
       fill_nickname=True,
       fill_comment=True
   )
   ```

3. **Service opens edit session**
   ```python
   # services/row_service.py
   with shared_data.edit_session() as session:
       for row in target_rows:
           row.nickname = source_row.nickname
           session.mark_changed(row)
   ```

4. **Session closes → validation**
   - All modified rows validated
   - Invalid rows marked with errors

5. **SharedData broadcasts**
   ```python
   shared_data.notify_data_changed(sender=None, changed_indices=target_indices)
   ```

6. **All views refresh**
   - Address panels repaint changed rows
   - Tag Browser rebuilds affected tree nodes
   - JumpSidebar updates status indicators

**Key Point:** Service doesn't know about UI. View orchestrates, service executes, SharedData broadcasts.

## Testing

Service tests are in `tests/test_services/`:
- `test_row_service.py` - Fill down, clone structure, dependency resolution
- `test_block_service.py` - Block tag parsing, color assignment, range detection
- `test_dependency_service.py` - Segment matching, array patterns, combined types
- `test_import_service.py` - Import validation, conflict detection

All service tests are fully unit testable without tkinter dependencies.
