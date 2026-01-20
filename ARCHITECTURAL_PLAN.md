@ -0,0 +1,481 @@
# Architecture Plan: Base + Overlay Model

## Core Philosophy

Instead of a single "current state," the application maintains two distinct layers of data to resolve the conflict between User Edits and Database Updates.

1. **Base Layer (The Truth):** The latest snapshot from the external database/hardware.
2. **Overlay Layer (The Intent):** A sparse dictionary of user modifications (overrides).
3. **Visible Layer (The View):** A computed projection of `Base + Overlay`.

Key principles:
- **Undo/Redo** tracks the *Overlay Layer* only (user intent, not world state)
- **Targeted Refresh** uses Python's reference equality (`is`) to limit UI repaints
- **Immutable Rows** eliminate complex locking logic; new objects created on change
- **Structural Sharing** minimizes memory by reusing unchanged row objects

---

## 1. Data Model Refactor (`AddressRow`)

The `AddressRow` becomes a dumb, immutable container with a rigid contract for data integrity.

### Implementation

```python
@dataclass(frozen=True)
class AddressRow:
    """Immutable address row. Create new instances for changes."""
    addr_key: int
    memory_type: str
    address: int
    nickname: str = ""
    comment: str = ""
    initial_value: str = ""
    retentive: bool = False
    # Metadata (from DB, not user-editable)
    used: bool = False
    data_type: int = 0
    # Validation (computed, not stored in overrides)
    is_valid: bool = True
    validation_error: str = ""

    def merge_overrides(self, override: 'AddressRow') -> 'AddressRow':
        """
        Returns a new row combining 'self' (base) with user-editable
        fields from 'override'. Non-editable fields come from base.
        """
        return dataclasses.replace(
            self,
            nickname=override.nickname,
            comment=override.comment,
            initial_value=override.initial_value,
            retentive=override.retentive,
        )
```

### What's Removed
- `original_*` fields (dirty tracking moves to store)
- `_parent` weak reference (no more edit_session locking)
- `__setattr__` override (frozen dataclass handles immutability)
- `is_dirty`, `is_nickname_dirty`, etc. properties (computed by store)

---

## 3. Store Refactor (`AddressStore`)

The Store becomes the "Merger." It holds the truth and the user's deviations from the truth.

### Constants

```python
MAX_UNDO_DEPTH = 50  # Maximum undo frames to retain
```
class AddressStore:
    # The three layers
    base_state: dict[int, AddressRow]      # Latest DB snapshot (all ~17k rows)
    user_overrides: dict[int, AddressRow]  # Sparse: only user-touched rows
    visible_state: dict[int, AddressRow]   # Computed: base merged with overrides

    # Ordered list for display (replaces skeleton list)
    row_order: list[int]  # addr_keys in display order

    # Undo/Redo
    undo_stack: list[UndoFrame]
    redo_stack: list[UndoFrame]

    # Observers
    _observers: list[Callable[[set[int]], None]]
```


### Silent Merge (External DB Updates)

When the database updates, we update `base_state` but preserve user overrides.

```python
def on_database_update(self, new_rows: list[AddressRow]) -> None:
    """Handle external DB changes without losing user edits."""
    affected_keys = set()

    for row in new_rows:
        key = row.addr_key
        old_base = self.base_state.get(key)

        # 1. Update base layer
        self.base_state[key] = row

        # 2. Recompute visible for this key
        if key in self.user_overrides:
            # User has edits: merge NEW base with existing override
            new_visible = row.merge_overrides(self.user_overrides[key])
        else:
            # No user edits: visible = base
            new_visible = row

        # 3. Only mark as affected if visible actually changed
        old_visible = self.visible_state.get(key)
        if new_visible != old_visible:
            self.visible_state[key] = new_visible
            affected_keys.add(key)

    # 4. Notify observers
    if affected_keys:
        self._notify_observers(affected_keys)
```

### Undo/Redo

```python
def undo(self) -> bool:
    """Restore previous override state. Returns True if undo was performed."""
    if not self.undo_stack:
        return False

    # Save current state to redo
    self.redo_stack.append(UndoFrame(
        overrides=dict(self.user_overrides),
        description="",  # Not displayed for redo
    ))

    # Restore previous state
    frame = self.undo_stack.pop()
    old_overrides = self.user_overrides
    self.user_overrides = frame.overrides

    # Find all keys that changed (union of old and new override keys)
    affected_keys = set(old_overrides.keys()) | set(self.user_overrides.keys())

    # Recompute visible for affected keys
    self._recompute_visible(affected_keys)

    # Re-validate
    self._validate_rows(affected_keys)

    # Notify
    self._notify_observers(affected_keys)
    return True

def redo(self) -> bool:
    """Re-apply undone changes. Returns True if redo was performed."""
    if not self.redo_stack:
        return False

    # Save current to undo
    self.undo_stack.append(UndoFrame(
        overrides=dict(self.user_overrides),
        description="",
    ))

    # Restore redo state
    frame = self.redo_stack.pop()
    old_overrides = self.user_overrides
    self.user_overrides = frame.overrides

    affected_keys = set(old_overrides.keys()) | set(self.user_overrides.keys())
    self._recompute_visible(affected_keys)
    self._validate_rows(affected_keys)
    self._notify_observers(affected_keys)
    return True
```

### Save Behavior

Save persists to DB but does NOT clear undo history. User can still undo after save.

```python
def save_to_database(self) -> None:
    """Persist dirty rows to database."""
    dirty_rows = [
        self.visible_state[key]
        for key in self.user_overrides
    ]

    self.data_source.save_changes(dirty_rows)

    # After save: base_state = visible_state for saved rows
    # This means "the DB now matches what user sees"
    for key in list(self.user_overrides.keys()):
        self.base_state[key] = self.visible_state[key]

    # Clear overrides (visible now equals base)
    self.user_overrides.clear()

    # Note: undo_stack is NOT cleared
    # Undo after save will restore overrides, showing unsaved changes again
```

### Dirty State Queries

```python
def is_dirty(self, key: int) -> bool:
    """Check if a row has user modifications."""
    return key in self.user_overrides

def is_field_dirty(self, key: int, field: str) -> bool:
    """Check if a specific field differs from base."""
    if key not in self.user_overrides:
        return False
    visible = self.visible_state[key]
    base = self.base_state[key]
    return getattr(visible, field) != getattr(base, field)

def get_dirty_keys(self) -> set[int]:
    """Get all keys with user modifications."""
    return set(self.user_overrides.keys())
```

---

## 4. View Refactor

Views access data via `visible_state` lookup instead of holding direct row references.

### Panel Changes

```python
class AddressPanel:
    def __init__(self, store: AddressStore, ...):
        self.store = store
        # Keys in display order (replaces self.rows list)
        self.row_keys: list[int] = []

    def set_data(self, keys: list[int]) -> None:
        """Set the rows to display."""
        self.row_keys = keys
        self._populate_sheet_data()

    def _get_row(self, data_idx: int) -> AddressRow:
        """Get row by display index."""
        key = self.row_keys[data_idx]
        return self.store.visible_state[key]

    def refresh_targeted(self, changed_keys: set[int]) -> None:
        """Refresh only specific rows after data changes."""
        # Convert keys to display indices
        key_to_idx = {k: i for i, k in enumerate(self.row_keys)}

        for key in changed_keys:
            if key not in key_to_idx:
                continue  # Not in this panel's view

            data_idx = key_to_idx[key]
            self._update_row_display(data_idx)
            self._update_row_styling(data_idx)

    def _update_row_styling(self, data_idx: int) -> None:
        """Apply dirty/error styling to a row."""
        key = self.row_keys[data_idx]
        visible = self.store.visible_state[key]
        base = self.store.base_state[key]

        # Fast dirty check: reference equality
        if visible is base:
            self._clear_dirty_styling(data_idx)
            return

        # Per-field dirty styling
        if visible.nickname != base.nickname:
            self._style_cell_dirty(data_idx, COL_NICKNAME)
        else:
            self._style_cell_clean(data_idx, COL_NICKNAME)

        # ... repeat for other editable fields
```

### Observer Registration

```python
# In window setup
self.store.add_observer(self._on_store_changed)

def _on_store_changed(self, changed_keys: set[int]) -> None:
    """Handle store data changes."""
    for panel in self.panels:
        panel.refresh_targeted(changed_keys)
    self._update_status()
```

---

## 5. Cascade Handling

Cascades (T/TD sync, block tag sync) happen within the edit session, so they're captured in a single undo frame.

```python
def _apply_cascades(self, pending: dict[int, MutableRowBuilder]) -> None:
    """Apply automatic syncs. Modifies pending in-place."""

    # T/TD retentive sync
    for key, builder in list(pending.items()):
        # ... use service to sync, using MutableRowBuilder


    # Block tag sync (<Foo> -> </Foo>)
    for key, builder in list(pending.items()):
        if builder.comment is not None:
            # ... use service to detect tag rename, find closing tag, update pending
            pass
```

When user undoes, both the original edit AND the cascade revert together.

---

## 6. Migration Plan

### Phase 1: Immutable AddressRow
- Convert `AddressRow` to frozen dataclass
- Remove `original_*` fields, `_parent`, `__setattr__` override
- Update `AddressStore.edit_session` to use builders
- Update cascade services to work with builders

### Phase 2: Create AddressStore
- Create `AddressStore` class 
- Implement `base_state`, `user_overrides`, `visible_state`
- Implement `edit_session` with undo/redo
- Add Ctrl+Z/Ctrl+Y bindings

### Phase 3: View Migration
- Change panels from `self.rows: list[AddressRow]` to `self.row_keys: list[int]`
- Update `_get_row()` to lookup from `store.visible_state`
- Update styling to use `is` comparison + field diff
- Remove `is_dirty` property usage

### Phase 4: Cleanup
- Remove `SharedAddressData` (replaced by `AddressStore`)
- Remove `AddressRow` dirty tracking properties
- Update all services to use new patterns

---

## 7. Terminology Updates

| Concept | Old Name | New Name |
|---------|----------|----------|
| Container | `SharedAddressData` | `AddressStore` |
| DB Snapshot | `original_*` attributes | `base_state` |
| User Edits | `is_dirty` flags | `user_overrides` |
| UI Data | `AddressRow` (mutable) | `visible_state` (immutable) |
| Edit Batch | `edit_session()` | `edit_session(description)` |
| Change Notification | `notify_data_changed()` | `_notify_observers(changed_keys)` |

---

## 8. Key Behaviors

| Scenario | Behavior |
|----------|----------|
| User edits row | Override created, undo frame pushed |
| External DB update | Base updated, override preserved, visible recomputed |
| Undo | Restore previous overrides, recompute visible with current base |
| Undo after save | Overrides restored (shows "unsaved" state again) |
| Fill-down 500 rows | Single undo frame captures all 500 |
| Edit T1.retentive | Cascade to TD1 in same undo frame |
| Discard all | Clear overrides, visible = base |