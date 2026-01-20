# Base + Overlay Architecture Migration Plan

## Overview

Migrate ClickNick's data layer from mutable `AddressRow` with in-place dirty tracking to an immutable Base + Overlay model with undo/redo support.

**Key Benefits:**
- Undo/Redo (Ctrl+Z/Y) with 50-level depth
- Cleaner separation: base (DB truth) vs overlay (user intent)
- Simpler dirty detection via reference equality
- External DB updates preserve user edits automatically

---

## Phase 4: Cleanup

### Window Changes (`src/clicknick/views/address_editor/window.py`)

**Add menu items:**
- Edit → Undo (with description from `get_undo_description()`)
- Edit → Redo

---

## Key Files Modified

| File | Changed |
|------|---------|
| `src/clicknick/models/address_row.py` | Freeze dataclass, remove dirty tracking |
| `src/clicknick/data/shared_data.py` | deleted |
| `src/clicknick/views/address_editor/panel.py` | Keys instead of rows, store lookup |
| `src/clicknick/views/address_editor/row_styler.py` | Store-based dirty checks |
| `src/clicknick/views/address_editor/window.py` | Undo/redo bindings |
| `src/clicknick/services/dependency_service.py` | Use builders for cascades |
| `src/clicknick/services/row_service.py` | Use builders for fill/clone |
| `src/clicknick/app.py` | Create AddressStore |

---

## Testing Strategy

### Phase 1 Tests
- `test_address_store.py`: Edit session creates override, pushes undo frame
- Undo restores previous state, redo re-applies
- Multiple edits in one session = single undo frame
- Max undo depth enforced

### Phase 2 Tests
- `test_mutable_row_builder.py`: Freeze applies changes correctly
- Frozen row cannot be modified (raises `FrozenInstanceError`)

### Phase 3 Integration
- Panel displays visible_state correctly
- Ctrl+Z reverts display
- Fill-down 500 rows = single undo frame

### Verification
1. Run `make test` after each phase
2. Manual test: Edit rows, Ctrl+Z/Y, verify display updates
3. Manual test: External MDB change preserves user edits