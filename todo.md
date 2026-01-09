# todo.md

## For each TODO:

1. Clarify if needed
2. Implement + add tests if helpful
3. Ask user to test

### Todo

/views/address_editor
[~] Both panel.py and window.py are getting quite long, easy ways of refactoring? (high, medium, low priorities)
    Findings: panel.py=1414 lines, window.py=1642 lines
    High: Extract block_operations.py (~200 lines), fill_operations.py (~350 lines) from window.py
    Medium: Break up _on_sheet_modified (~200 lines), extract discard logic (~150 lines) from panel.py
    Low: Move _create_tooltip to widgets/, extract filter matching

/views/address_editor/panel.py & tab_state.py:
[] Nickname cell right-click/selection. Use same dynamic menu input as discard. UPPERCASE ctrl shift u, lowercase ctrl u, Propercase: my_existing_tag My_Existing_Tag. However for each operation, we want to do it 1 underscore split at a time, right to left. So lower_case_tag, step1: lower_case_TAG, lower_CASE_TAG, LOWER_CASE_TAG.
[] Fill down and clone should prompt and ask when incrementing initial value “Initial value looks like it matches the Array number, increment that as well? Or something like that
[] Fill down should copy initial value and retentive too (see clone logic)

/views/address_editor/sheet.py - Regex search and replace:
[] Fix: When nothing selected, but 'In Selection' is checked, it ignores and searches for everything. Perhaps a popup 'You have nothing selected'
[] Default s/r to search in selection when multiple cells/rows selected? Is this easily overriden? (the tksheet find_window is at https://raw.githubusercontent.com/ragardner/tksheet/refs/heads/master/tksheet/find_window.py)
[] Allow custom text instead of hard-coded ⚠ in custom_redraw_corner
[] Add 'original' as note to dirty cells. Use 💾 as char

/views/address_editor/window.py - change 'Save' to 'Sync'
[] Change “save” to “sync” when using mdb. Raise CLICK window? (As visual, we sent changes?)

/views/nav_window/outline_panel.py, outline_logic.py
[] When displayed, append prefix, distinguishing between folder, folder/leaf with children, and singular leaf. Use CONSTANTS that I can change easily

/views/nav_window/block_panel.py
[] Add a 'Sort A->Z' to bottom of panel

/views/address_editor/window.py - Exporting/Importing. PLAN
[] Export to csv dialog
[] Export All / Only visible rows
[] Import from csv dialog
[] Import dialog: merge all, import just these blocks. Then (selection for each column for each block): blocks only (overwrite existing blocks), whole comment (overwrite or append), nicknames, initial value, retentive