# todo.md

## For each TODO:

1. Clarify if needed
2. Implement + add tests if helpful
3. Run `make`
4. Ask user to test
5. Commit (short message)
6. Next

### Todo

New feature:

Dataview Editor

Dataview load for .cdv files - they are generated and in same path as Click Project, and we can save directly back to them and it saves when user saves project. However, new files arn't hot-loaded and will need to be exported. So in addition to 'Save' we will also want 'Load' and 'Export'.

File location: \CLICK (00010A98)\DataView (where the 00010A98) is unique, like we get for the mdb file

We can have a list of them on the left, and then each one clicked opens a new tab (horizontal)

Filename = dataview name
Max 24 chars, no special characters (like Click Nicknames)

Format:
Max rows: 100
empty rows: `,0`
Exports with 
First line is header row (if no New Values set):
0,0,0 
If it has New values set:
-1,0,0

Column 1 is memory address, X001, SC1, etc
Column 2 is special meaning (apparently to designate what kind of address this is):

"BIT" : 768
"FLOAT" : 257
"INT" : 0
"INT2" : 256
"HEX" : 3
"TXT" : 1024

Column 3 is saved “New Value” - all the same rules apply for min/max as in AddressRow - Bits are checkboxes, Int/Int2/Float/Hex/Txt and Readonly. I have a list of writeable SD/SC - all else are read-only.

writable_sc_addresses = {
            50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121
        }
        
writable_sd_addresses = {
            29, 31, 32, 34, 35, 36, 40, 41, 42, 50, 51, 60, 61, 106, 107, 108,
            112, 113, 114, 140, 141, 142, 143, 144, 145, 146, 147, 214, 215
        }

For editing:
We can monkey patch tksheet to use our autocomplete combobox instead of a dropdown
https://github.com/ragardner/tksheet/issues/71

Our 'View' will be a fixed 100 rows.
Columns:
Address, Nickname, New Value. You can input directly into 'Address', like X1, which will populate Address/Nickname with X001, NicknameForX1
OR you can input directly into the Nickname, which will become a Nickname Combobox, with autocomplete from our autocomplete function. This can be a secondary phase.

Then enable the row cutting/pasting, reordering, all the nice features of tksheet

Also can have the Navigator Dock live, with a Right-click menu: 
'Add to Open Dataview'

Let's organize this into several stages. We will want tests to make sure we are importing and exporting to match the example dataviews I have saved in tests:
DataView1.cdv
DataView1WithNewValues.cdv