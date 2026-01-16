# HANDOFF: SharedAddressData Refactoring Plan

## Status: Draft - Needs Validation

**Important:** This plan was drafted from repomapper signature analysis only. Before implementing, read the actual implementations to validate assumptions about method responsibilities and dependencies.

Files to review:
- `src/clicknick/data/shared_data.py` - The god object
- `src/clicknick/services/block_service.py` - Block colors, paired tags
- `src/clicknick/services/dependency_service.py` - Paired rows, sync logic

---

## Problem Summary

### SharedAddressData: God Object (~50 methods, 8+ responsibilities)

| Responsibility | Methods | Status |
|----------------|---------|--------|
| **Core State** | `_create_skeleton`, `_hydrate_from_db_data`, `get_rows`, `set_rows` | Keep |
| **Edit Sessions** | `edit_session`, `is_editing`, `mark_changed` | Keep |
| **Observer/Notify** | `add_observer`, `notify_data_changed`, `register_window` | Keep (consider extracting WindowRegistry later) |
| **Nickname Index** | `_rebuild_nickname_index`, `get_addr_keys_for_nickname`, `is_duplicate_nickname`, `all_nicknames` | Extract |
| **Validation** | `_validate_affected_rows`, `validate_affected_rows` | Extract |
| **Block Sync** | `_update_block_colors_if_needed`, `_sync_paired_block_tags` | Duplicates BlockService |
| **Dependency Sync** | `_sync_dependencies` | Duplicates RowDependencyService |
| **File Monitoring** | `start_file_monitoring`, `_check_file_modified`, `_reload_from_source` | Extract |
| **Persistence** | `save_all_changes`, `discard_all_changes`, `has_unsaved_changes` | Keep or move to DataSource |

### Services Layer: Fragmented "Paired" Logic

`BlockService` and `RowDependencyService` both handle "paired/interleaved" concepts:

| Service | Methods | Concern |
|---------|---------|---------|
| `BlockService` | `auto_update_paired_tag()`, `find_interleaved_pair_idx()` | Paired logic |
| `RowDependencyService` | `find_paired_row()`, `sync_interleaved_pairs()`, `_sync_block_tag()` | Paired logic |

This split seems awkward - needs validation by reading the code.

---

## Refactoring Plan

### Phase 1: Extract NicknameIndexService

**Risk:** Low
**Value:** High - pure logic, easy to test

Create `services/nickname_index_service.py`:

```python
class NicknameIndexService:
    def rebuild_index(self, rows: Iterable[AddressRow]) -> dict[str, set[int]]: ...
    def get_addr_keys_for_nickname(self, nickname: str) -> set[int]: ...
    def get_addr_keys_insensitive(self, nickname: str) -> set[int]: ...
    def is_duplicate(self, nickname: str, exclude_addr_key: int) -> bool: ...
    def validate_affected_rows(self, old_nickname: str, new_nickname: str) -> set[int]: ...
```

SharedAddressData keeps thin wrappers that delegate to this service.

### Phase 2: Extract FileMonitor

**Risk:** Medium
**Value:** Medium - clean boundary, isolated concern

Create `data/file_monitor.py`:

```python
class FileMonitor:
    def __init__(self, file_path: str, on_modified: Callable[[], None]): ...
    def start(self, tk_root) -> None: ...
    def stop(self) -> None: ...
    def _check_modified(self) -> None: ...
```

SharedAddressData creates and owns a FileMonitor instance.

### Phase 3: Consolidate Paired/Interleaved Logic

**Risk:** Medium
**Value:** High - removes duplication, clarifies ownership

Expand `RowDependencyService` to own all paired/interleaved logic:

```python
class RowDependencyService:
    def find_paired_row(self, ...) -> ...: ...           # existing
    def sync_interleaved_pairs(self, ...) -> ...: ...    # existing
    def find_interleaved_pair_idx(self, ...) -> ...: ... # from BlockService
    def auto_update_paired_tag(self, ...) -> ...: ...    # from BlockService
    def sync_block_tag(self, ...) -> ...: ...            # existing
```

Slim down `BlockService` to color-only:

```python
class BlockService:
    def update_colors(self, ...) -> ...: ...
    def compute_block_colors_map(self, ...) -> ...: ...
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

1. **Phase 1** - NicknameIndexService (pure logic, no UI impact)
2. **Phase 2** - FileMonitor (isolated, clear interface)
3. **Phase 3** - Consolidate paired logic (requires deeper understanding)
4. **Phase 4** - Simplify edit_session (ties everything together)

---

## Before Starting

1. Read `shared_data.py` methods listed above - understand actual responsibilities
2. Read `block_service.py` and `dependency_service.py` - understand the paired logic split
3. Trace through one `edit_session` call to understand the current flow
4. Validate that the proposed extractions won't break the unidirectional data flow
