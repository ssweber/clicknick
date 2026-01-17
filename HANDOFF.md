# HANDOFF: SharedAddressData Refactoring Plan

## Status: In Progress

---

## Problem Summary

### SharedAddressData: God Object (~50 methods, 8+ responsibilities)

| Responsibility | Methods | Status |
|----------------|---------|--------|
| **Core State** | `_create_skeleton`, `_hydrate_from_db_data`, `get_rows`, `set_rows` | Keep |
| **Edit Sessions** | `edit_session`, `is_editing`, `mark_changed` | Keep |
| **Observer/Notify** | `add_observer`, `notify_data_changed`, `register_window` | Keep (consider extracting WindowRegistry later) |
| **Nickname Index** | `_rebuild_nickname_index`, `get_addr_keys_for_nickname`, `is_duplicate_nickname`, `all_nicknames` | ✅ Extracted to NicknameIndexService |
| **Validation** | `_validate_affected_rows`, `validate_affected_rows` | Extract |
| **Block Sync** | `_update_block_colors_if_needed`, `_sync_paired_block_tags` | Duplicates BlockService |
| **Dependency Sync** | `_sync_dependencies` | Duplicates RowDependencyService |
| **File Monitoring** | `start_file_monitoring`, `_check_file_modified`, `_reload_from_source` | ✅ Extracted to FileMonitor |
| **Persistence** | `save_all_changes`, `discard_all_changes`, `has_unsaved_changes` | Keep or move to DataSource |

### Services Layer: Fragmented "Paired" Logic

**Two distinct "paired" concepts are conflated:**

1. **Block Tag Pairing** (vertical: open ↔ close tags)
   - `<Motor>` on row 10 paired with `</Motor>` on row 20
   - Same memory type, different rows
   - Handled by: `BlockService.auto_update_paired_tag()`, `blocktag.find_paired_tag_index()`

2. **Interleaved Type Pairing** (horizontal: T ↔ TD at same address)
   - `T1` paired with `TD1` (Timer and Timer Done share settings)
   - Adjacent rows in unified view, same address
   - Handled by: `RowDependencyService.find_paired_row()`, `sync_interleaved_pairs()`

**Current fragmentation:**

| Method | Location | Actual Concern |
|--------|----------|----------------|
| `find_interleaved_pair_idx()` | `BlockService:133` | Interleaved pairing (T↔TD) - wrong place! |
| `auto_update_paired_tag()` | `BlockService:80` | Block tag pairing (open↔close) |
| `find_paired_row()` | `RowDependencyService:80` | Interleaved pairing (T↔TD) |
| `sync_interleaved_pairs()` | `RowDependencyService:104` | Interleaved pairing (T↔TD) |
| `_sync_block_tag()` | `dependency_service.py:31` | Block tag sync between T↔TD pairs |
| `find_paired_tag_index()` | `blocktag.py:279` | Block tag pairing (open↔close) - across-rows logic in model! |
| `find_block_range_indices()` | `blocktag.py:340` | Block range lookup - across-rows logic in model! |
| `compute_all_block_ranges()` | `blocktag.py:382` | All block ranges - across-rows logic in model! |
| `validate_block_span()` | `blocktag.py:430` | Block validation - across-rows logic in model! |
| `find_paired_row()` | `view_builder.py:198` | Interleaved pairing - duplicate in view! |

### Duplicate Paired Type Definitions

Same concept defined 3+ times with different representations:

| Location | Name | Type | Value |
|----------|------|------|-------|
| `models/constants.py:130` | `PAIRED_RETENTIVE_TYPES` | `dict[str, str]` | `{"TD": "T", "CTD": "CT"}` |
| `models/blocktag.py:268` | `PAIRED_BLOCK_TYPES` | `set[frozenset]` | `{frozenset({"T", "TD"}), ...}` |
| `services/dependency_service.py:23` | `INTERLEAVED_PAIRS` | `dict[str, str]` | `{"T": "TD", "TD": "T", ...}` |
| `views/dataview_editor/window.py:339` | `paired_type_map` | ad-hoc dict | `{"T": "TD", "CT": "CTD"}` |

---

## Refactoring Plan

### Phase 1: Extract NicknameIndexService ✅ DONE

**Commit:** `1b0c43a` - refact/Extract NicknameIndexService from SharedAddressData

Created `services/nickname_index_service.py` with:
- `rebuild_index(rows)` - rebuilds indices from rows
- `get_addr_keys(nickname)` - exact case lookup
- `get_addr_keys_insensitive(nickname)` - case-insensitive lookup
- `is_duplicate(nickname, exclude_addr_key)` - O(1) duplicate detection
- `update(addr_key, old_nickname, new_nickname)` - incremental index updates

SharedAddressData now delegates via thin wrappers. 24 new tests added.

### Phase 2: Extract FileMonitor ✅ DONE

**Commit:** `7b8cfd8` - refact/Extract FileMonitor from SharedAddressData

Created `data/file_monitor.py` with:
- `FileMonitor(file_path, on_modified)` - captures initial mtime
- `start(tk_root)` - begins polling with tk.after()
- `stop()` - cancels polling
- `update_mtime()` - refresh stored mtime after saves (prevents false detection)
- `is_active` property - check if monitoring is running

SharedAddressData now creates and owns a FileMonitor instance. 25 new tests added.

### Phase 3: Consolidate Paired/Interleaved Logic

**Risk:** Medium
**Value:** High - removes duplication, clarifies ownership

#### Step 3a: Consolidate Paired Type Constants

Create single source of truth in `models/constants.py`:

```python
# Canonical definitions
INTERLEAVED_TYPE_PAIRS = {("T", "TD"), ("CT", "CTD")}  # Set of tuples
INTERLEAVED_PAIRS = {"T": "TD", "TD": "T", "CT": "CTD", "CTD": "CT"}  # Bidirectional lookup
PAIRED_RETENTIVE_TYPES = {"TD": "T", "CTD": "CT"}  # Keep - one-directional for retentive
```

**Delete/update:**
- `blocktag.py:268` - Delete `PAIRED_BLOCK_TYPES`, import from constants
- `dependency_service.py:23` - Delete `INTERLEAVED_PAIRS`, import from constants
- `dataview_editor/window.py:339` - Delete ad-hoc `paired_type_map`, import from constants

#### Step 3b: Move Across-Rows Logic from blocktag.py to BlockService

`models/blocktag.py` should be a pure data model (single-comment parsing).
Move these to `BlockService`:

| Function | Current | New Home |
|----------|---------|----------|
| `find_paired_tag_index()` | blocktag.py:279 | BlockService |
| `find_block_range_indices()` | blocktag.py:340 | BlockService |
| `compute_all_block_ranges()` | blocktag.py:382 | BlockService |
| `validate_block_span()` | blocktag.py:430 | BlockService |

**Keep in blocktag.py** (single-comment operations):
- `BlockTag`, `BlockRange` dataclasses
- `parse_block_tag()`, `format_block_tag()`, `strip_block_tag()`
- `get_block_type()`, `is_block_tag()`, `extract_block_name()`

#### Step 3c: Clean Up Duplicate find_paired_row

Three implementations exist - consolidate to one:

| Location | Keep/Delete | Notes |
|----------|-------------|-------|
| `RowDependencyService.find_paired_row()` | **Keep** | Uses efficient addr_key lookup |
| `BlockService.find_interleaved_pair_idx()` | Delete | Duplicate, wrong service |
| `view_builder.find_paired_row()` | Refactor | Call service or use constants |

#### Step 3d: Rename for Clarity

| Current Name | New Name | Reason |
|--------------|----------|--------|
| `auto_update_paired_tag()` | `auto_update_matching_block_tag()` | Clarifies it's open↔close, not T↔TD |

#### Final Structure After Phase 3

```python
# models/blocktag.py - Pure data model, single-comment operations only
class BlockTag: ...
class BlockRange: ...
def parse_block_tag(comment: str) -> BlockTag: ...
def format_block_tag(...) -> str: ...
def strip_block_tag(comment: str) -> str: ...

# services/block_service.py - All multi-row block operations
class BlockService:
    # Color operations
    def update_colors(shared_data, affected_keys) -> set[int]: ...
    def compute_block_colors_map(rows) -> dict[int, str]: ...

    # Block tag operations (open↔close pairing)
    def auto_update_matching_block_tag(rows, row_idx, old_tag, new_tag) -> int | None: ...
    def find_paired_tag_index(rows, row_idx, tag) -> int | None: ...  # from blocktag.py
    def find_block_range_indices(rows, row_idx, tag) -> tuple | None: ...  # from blocktag.py
    def compute_all_block_ranges(rows) -> list[BlockRange]: ...  # from blocktag.py
    def validate_block_span(rows) -> tuple[bool, str | None]: ...  # from blocktag.py

# services/dependency_service.py - Interleaved type operations (T↔TD)
class RowDependencyService:
    def find_paired_row(shared_data, row) -> AddressRow | None: ...
    def sync_interleaved_pairs(shared_data, affected_keys) -> set[int]: ...
    # _sync_block_tag() stays as module-level helper
```

### Phase 4: Simplify edit_session Orchestration

**Risk:** Higher - touches core data flow
**Value:** High - makes the flow explicit

After phases 1-3, `edit_session` becomes an orchestrator:

```python
@contextmanager
def edit_session(self):
    # ... setup ...
    yield self
    # On exit - orchestrate services:
    self._nickname_service.rebuild_index(changed_rows)
    self._dependency_service.sync_interleaved_pairs(changed_rows)
    self._block_service.update_colors(affected_rows)
    self._validate_and_notify(changed_indices)
```

---

## Implementation Order

1. ✅ **Phase 1** - NicknameIndexService (pure logic, no UI impact)
2. ✅ **Phase 2** - FileMonitor (isolated, clear interface)
3. **Phase 3** - Consolidate paired logic
   - 3a: Consolidate paired type constants to `models/constants.py`
   - 3b: Move across-rows logic from `blocktag.py` to `BlockService`
   - 3c: Delete duplicate `find_paired_row` implementations
   - 3d: Rename `auto_update_paired_tag()` for clarity
4. **Phase 4** - Simplify edit_session (ties everything together)
