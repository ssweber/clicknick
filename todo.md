# todo.md

## For each TODO:

1. Clarify if needed
2. Implement + add tests if helpful
3. Ask user to test

### Todo

### /views/nav_window/block_panel.py
- [ ] Add a '[] A->Z' to bottom, that changes sort order of displayed treeview from memory-order to a-z order

### /views/nav_window/outline_panel.py
Right-click 'Rename' dialog that will rename that specific part of Nicknames using regex. 
Create tests for this first and then implement.
Window will be like

-----------------
__________ Rename
-----------------

Regex will be like 
not-array node: `^({prefix}){current_node_text} -> \1{{new_text}
array node: `^({prefix}){current_node_text}(\d+)_ -> \1{{new_text}\2_
(please verify these)

### /views/address_editor/sheet.py - Allow both ⚠ Error notes and 💾 Dirty notes:
custom_redraw_corner is our special override to Sheet, that makes all cell-notes currently show a ⚠. We want to investigate generalizing this to allow showing 💾 for 'dirty' cells. 
- [ ] After we do above. /views/address_editor/row_styler: Add 'original' as note to dirty cells. Use new custom_redraw_corner functionality to show a 💾 for the note corner



