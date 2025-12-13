# todo.md

## For each TODO:

1. Clarify if needed
2. Implement + add tests if helpful
3. Run `make`
4. Ask user to test
5. Commit (short message)
6. Next

[ ] Monitor file (like we do for the overlays). When file changes, update the "Use" column, as well as any row cell that isn't dirty. (The Click Programming software updates the mdb often as instructions are used. And we want to sync with builtin Address Picker changes).
[ ] Convert the Memory address column (X1, X2, …) to the row index. This allows us to have user select entire rows
[ ] With Search and Replace, can we disallow certain columns? We'd want to disallow Use, Init, Ret, Ok, and Validation issues. Only Nickname and Comments
[ ] If easily changed: Change binding for tksheet Replace menu from Ctrl + H to Ctrl + R
[ ] Use tksheet Undo/Redo stack for User edits. Use Ctrl Z, Ctrl Shift Z. Stack resets on Save.

## User Defined Blocks

[ ] Rename the sidebar "Tags" to "Blocks" Go ahead and add that name to the jump menu even if there arnt any (for discovery)
[ ] Blocks can be ranges: X1 comment: <name1>, X10 comment </name1>. This would display "name1 (X1-X10)" in the jump menu, and jump to X1. Blocks can also be singular points, expressed as self-closing tag <name1 />. Blocks can be nested
[ ] Add a button "Add block" with a tooltip "Select row(s)" that is disabled if no row index is selected and able to be clicked if a row is selected. Put it right of "Refresh". User selects row(s), clicks button. Input window pops up. "Block Name".
[ ] On the "Add Block" dialog, allow color selection, load with a random light material design color, default to none. This would be added as <name bg=""> to the tag if so selected. We can then use this to highlight the Row indexes at that point or range. Nested blocks bg color overrides other colors
[ ] Add this "Add Block" as a right-click menu item in the Row selection (if easily allowed through standard tksheet settings)