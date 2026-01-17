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
| **Block Sync** | `_update_block_colors_if_needed`, `_sync_paired_block_tags` | ✅ Uses BlockService (Phase 3) |
| **Dependency Sync** | `_sync_dependencies` | Uses RowDependencyService |
| **File Monitoring** | `start_file_monitoring`, `_check_file_modified`, `_reload_from_source` | ✅ Extracted to FileMonitor |
| **Persistence** | `save_all_changes`, `discard_all_changes`, `has_unsaved_changes` | Keep or move to DataSource |

### Services Layer: "Paired" Logic (✅ Clarified in Phase 3)

**Two distinct "paired" concepts now have clear ownership:**

1. **Block Tag Pairing** (vertical: open ↔ close tags)
   - `<Motor>` on row 10 paired with `</Motor>` on row 20
   - Same memory type, different rows
   - Handled by: `BlockService.auto_update_matching_block_tag()`, `block_service.find_paired_tag_index()`

2. **Interleaved Type Pairing** (horizontal: T ↔ TD at same address)
   - `T1` paired with `TD1` (Timer and Timer Done share settings)
   - Adjacent rows in unified view, same address
   - Handled by: `RowDependencyService.find_paired_row()`, `sync_interleaved_pairs()`

**Current state (after Phase 3):**

| Method | Location | Concern | Status |
|--------|----------|---------|--------|
| `auto_update_matching_block_tag()` | `BlockService` | Block tag pairing (open↔close) | ✅ Renamed |
| `find_paired_tag_index()` | `block_service.py` (module) | Block tag pairing (open↔close) | ✅ Moved from blocktag.py |
| `find_block_range_indices()` | `block_service.py` (module) | Block range lookup | ✅ Moved from blocktag.py |
| `compute_all_block_ranges()` | `block_service.py` (module) | All block ranges | ✅ Moved from blocktag.py |
| `validate_block_span()` | `block_service.py` (module) | Block validation | ✅ Moved from blocktag.py |
| `find_paired_row()` | `RowDependencyService` | Interleaved pairing (T↔TD) | ✅ Kept (efficient) |
| `sync_interleaved_pairs()` | `RowDependencyService` | Interleaved pairing (T↔TD) | ✅ Kept |
| `_sync_block_tag()` | `dependency_service.py` | Block tag sync between T↔TD pairs | ✅ Kept |
| `find_paired_row()` | `view_builder.py` | Retentive lookup (TD→T) | ✅ Kept (uses constants) |
| ~~`find_interleaved_pair_idx()`~~ | ~~`BlockService`~~ | ~~Interleaved pairing~~ | ❌ Deleted (unused) |

### Paired Type Definitions (after Phase 3) ✅

Consolidated to `models/constants.py`:

| Name | Type | Purpose | Status |
|------|------|---------|--------|
| `INTERLEAVED_TYPE_PAIRS` | `frozenset[frozenset[str]]` | Set membership test for T/TD, CT/CTD pairs | ✅ New canonical |
| `INTERLEAVED_PAIRS` | `dict[str, str]` | Bidirectional lookup `{"T": "TD", "TD": "T", ...}` | ✅ New canonical |
| `PAIRED_RETENTIVE_TYPES` | `dict[str, str]` | One-way lookup `{"TD": "T", ...}` for retentive | ✅ Kept (different use case) |
| ~~`PAIRED_BLOCK_TYPES`~~ | ~~blocktag.py~~ | ~~Deleted, uses INTERLEAVED_TYPE_PAIRS~~ | ❌ Deleted |
| ~~`paired_type_map`~~ | ~~dataview_editor~~ | ~~Deleted, uses INTERLEAVED_PAIRS~~ | ❌ Deleted |

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

### Phase 3: Consolidate Paired/Interleaved Logic ✅ DONE

**Risk:** Medium
**Value:** High - removes duplication, clarifies ownership

#### Step 3a: Consolidate Paired Type Constants ✅

Added to `models/constants.py`:
```python
# Canonical set of interleaved type pairs
INTERLEAVED_TYPE_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"T", "TD"}),
    frozenset({"CT", "CTD"}),
})

# Bidirectional lookup for interleaved pairs
INTERLEAVED_PAIRS: dict[str, str] = {
    "T": "TD", "TD": "T", "CT": "CTD", "CTD": "CT",
}
```

**Updated:**
- `blocktag.py` - Deleted `PAIRED_BLOCK_TYPES`, uses `INTERLEAVED_TYPE_PAIRS` from constants
- `dependency_service.py` - Deleted local `INTERLEAVED_PAIRS`, imports from constants
- `dataview_editor/window.py` - Deleted ad-hoc `paired_type_map`, imports `INTERLEAVED_PAIRS`

#### Step 3b: Move Across-Rows Logic from blocktag.py to BlockService ✅

Moved to `services/block_service.py` as module-level functions:
- `find_paired_tag_index(rows, row_idx, tag)` - Find matching open/close tag
- `find_block_range_indices(rows, row_idx, tag)` - Get (start, end) range
- `compute_all_block_ranges(rows)` - Compute all block ranges with stack matching
- `validate_block_span(rows)` - Validate block doesn't cross memory types

**blocktag.py now contains only:**
- `BlockTag`, `BlockRange`, `HasComment` - Data types/protocols
- `parse_block_tag()`, `format_block_tag()`, `strip_block_tag()` - Single-comment operations
- `get_block_type()`, `is_block_tag()`, `extract_block_name()` - Single-comment queries

#### Step 3c: Clean Up Duplicate find_paired_row ✅

| Location | Action | Notes |
|----------|--------|-------|
| `RowDependencyService.find_paired_row()` | **Kept** | Uses efficient addr_key lookup via SharedAddressData |
| `BlockService.find_interleaved_pair_idx()` | **Deleted** | Was unused, wrong location |
| `view_builder.find_paired_row()` | **Kept** | Already uses `PAIRED_RETENTIVE_TYPES` from constants |

#### Step 3d: Rename for Clarity ✅

| Old Name | New Name | Reason |
|----------|----------|--------|
| `auto_update_paired_tag()` | `auto_update_matching_block_tag()` | Clarifies it's open↔close tag pairing, not T↔TD type pairing |

#### Final Structure After Phase 3

```python
# models/blocktag.py - Pure data model, single-comment operations only
class BlockTag: ...
class BlockRange: ...
class HasComment(Protocol): ...
def parse_block_tag(comment: str) -> BlockTag: ...
def format_block_tag(...) -> str: ...
def strip_block_tag(comment: str) -> str: ...

# services/block_service.py - All multi-row block operations
# Module-level functions (extracted from blocktag.py):
def find_paired_tag_index(rows, row_idx, tag) -> int | None: ...
def find_block_range_indices(rows, row_idx, tag) -> tuple | None: ...
def compute_all_block_ranges(rows) -> list[BlockRange]: ...
def validate_block_span(rows) -> tuple[bool, str | None]: ...

class BlockService:
    # Color operations
    def update_colors(shared_data, affected_keys) -> set[int]: ...
    def compute_block_colors_map(rows) -> dict[int, str]: ...
    # Block tag operations (open↔close pairing)
    def auto_update_matching_block_tag(rows, row_idx, old_tag, new_tag) -> int | None: ...

# services/dependency_service.py - Interleaved type operations (T↔TD)
class RowDependencyService:
    def find_paired_row(shared_data, row) -> AddressRow | None: ...
    def sync_interleaved_pairs(shared_data, affected_keys) -> set[int]: ...
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
3. ✅ **Phase 3** - Consolidate paired logic
   - ✅ 3a: Consolidated paired type constants to `models/constants.py`
   - ✅ 3b: Moved across-rows logic from `blocktag.py` to `BlockService`
   - ✅ 3c: Deleted duplicate `find_interleaved_pair_idx` (was unused)
   - ✅ 3d: Renamed `auto_update_paired_tag()` → `auto_update_matching_block_tag()`
4. **Phase 4** - Simplify edit_session (ties everything together)
