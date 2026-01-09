# Manual Testing Checklist

This document contains manual testing procedures for ClickNick's Address Editor.

## Address Editor - Multi-Tab/Window Sync

These tests verify the Static Skeleton Architecture where all tabs and windows share the same AddressRow objects.

### 1. Multi-Tab Sync (Same Window)
- [ ] Open Address Editor
- [ ] Press `Ctrl+T` to create a second tab
- [ ] In Tab A, edit a nickname (e.g., X1 -> "TestNick")
- [ ] **Verify**: Tab B shows "TestNick" immediately when you switch to it
- [ ] In Tab A, edit a comment
- [ ] **Verify**: Tab B shows the updated comment
- [ ] **Verify**: Row styling (dirty indicator) appears in both tabs

### 2. Multi-Window Sync
- [ ] Open two Address Editor windows
- [ ] In Window 1, edit a nickname
- [ ] **Verify**: Window 2 shows the change
- [ ] In Window 2, edit a comment
- [ ] **Verify**: Window 1 shows the change

### 3. Save/Discard Roundtrip
- [ ] Make several edits (nicknames, comments) across multiple tabs
- [ ] **Save**: Verify dirty indicators clear, data persists after closing/reopening
- [ ] Make more edits
- [ ] **Discard**: Verify all edits revert to saved values, dirty indicators clear

### 4. Filter/Scroll Persistence
- [ ] Apply a filter (e.g., type "pump" in filter box)
- [ ] Scroll down to a specific position
- [ ] In another tab, make an edit that triggers refresh
- [ ] **Verify**: Your filter text is still there, scroll position preserved

### 5. External MDB Change (if possible)
- [ ] Make some edits (don't save)
- [ ] Externally modify the MDB file (e.g., via Access or another tool)
- [ ] Wait 2 seconds for file monitoring
- [ ] **Verify**: External changes appear, but your unsaved edits are preserved

### 6. Validation Sync
- [ ] In Tab A, create a duplicate nickname (e.g., set X1 and X2 both to "Dup")
- [ ] **Verify**: Both rows show validation error styling in Tab A
- [ ] **Verify**: Tab B also shows validation error styling on those rows

## Running Tests

```bash
# Run the app for manual testing
uv run clicknick

# Run automated tests
make test
```
