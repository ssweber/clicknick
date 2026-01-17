# Separation of Concerns Review: `SharedAddressData`

**File:** `src/clicknick/data/shared_data.py`
**Class:** `SharedAddressData` (lines 32-1032, ~1000 lines, 35+ methods)

## Identified Responsibilities (Too Many)

| Concern | Methods | Issue? |
|---------|---------|--------|
| **Skeleton/Data Storage** | `_create_skeleton`, `get_rows`, `set_rows`, `_hydrate_from_db_data` | ✅ Core responsibility |
| **Edit Session (Transactions)** | `edit_session`, `mark_changed`, `is_editing` | ✅ Core responsibility |
| **Nickname Indexing** | `_rebuild_nickname_index`, `get_addr_keys_for_nickname*`, `is_duplicate_nickname`, `all_nicknames` | ⚠️ Could be extracted |
| **Block Tag Sync** | `_update_block_colors_if_needed`, `_sync_paired_block_tags`, `get_block_addresses` | ⚠️ Could be extracted |
| **Dependency Sync** | `_sync_dependencies` | ⚠️ Could be extracted |
| **Validation** | `_validate_affected_rows`, `validate_affected_rows` | ⚠️ Could be delegated to service |
| **Observer/Events** | `add_observer`, `remove_observer`, `notify_data_changed` | ✅ Acceptable here |
| **Window Management** | `register_window`, `unregister_window`, `close_all_windows`, `force_close_all_windows` | ❌ **UI concern leaked into data layer** |
| **Unified View** | `get_unified_view`, `set_unified_view` | ❌ **UI concern** |
| **File Monitoring** | `start_file_monitoring`, `stop_file_monitoring`, `_check_file_modified`, `_reload_from_source` | ⚠️ Could be a separate `FileMonitor` class |
| **Persistence** | `save_all_changes`, `discard_all_changes`, `load_initial_data` | ✅ Acceptable |
| **Change/Error Tracking** | `has_unsaved_changes`, `get_*_count*` methods | ✅ Acceptable |

## Key Violations

1. **Window Management in Data Layer** (lines 484-565): `register_window`, `close_all_windows`, etc. are UI concerns. A data class shouldn't know about windows.

2. **UnifiedView Reference** (lines 400-408): Direct reference to a view type violates the "Services are Pure Logic" and "Views are Passive" rules from CLAUDE.md.

3. **File Monitoring with tkinter** (line 740): `start_file_monitoring(self, tk_root)` takes a tkinter root - data layer shouldn't depend on tk.

## Suggested Extractions

- **`NicknameIndex`** - nickname lookup/duplicate detection
- **`BlockTagManager`** - block color assignment and paired tag sync
- **`FileMonitor`** - file change detection (inject tk callback externally)
- **`WindowRegistry`** - move window tracking to app layer

## Summary

The class is doing the job of a "God object" - it's the central hub, but it's accumulated responsibilities that belong elsewhere.

