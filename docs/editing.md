# More ways ClickNick fixes the CLICK editor

Still editing addresses in Excel because you can't stand CLICK's Address Editor?

Autocomplete is the editing fix you feel in the first minute. These are the ones you keep coming back to: bulk nickname work, a structured view of a flat tag list, and Data Views built by name instead of by address.

## Address Editor

Bulk nickname and comment work, with every change listed for review before it syncs to CLICK.

![Address Editor demo](https://github.com/user-attachments/assets/ee7b1914-2f18-483a-ace1-84c2aa8eea98)

- Open different address sections in separate windows.
- Copy and paste ranges of cells.
- Duplicate nicknames and invalid values are flagged as you type.
- Undo or redo a whole bulk operation as one edit.

**Fill and clone.** Fill a pattern down a selection: `Alm1` becomes `Alm2`, `Alm3`, and so on. Clone a structure: `Alm1_ID` and `Alm1_Val` become the matching `Alm2` tags.

**Search and replace with regular expressions.** Search with <kbd>Ctrl</kbd>+<kbd>F</kbd>, replace with <kbd>Ctrl</kbd>+<kbd>R</kbd>. Search covers nicknames and comments and can be limited to the current selection. Regular expressions work, including `^` and `$` anchors and capture groups (`\1`) in replacements.

**Blocks.** Give a range of addresses a name and a color. Blocks organize the editor, show up in the Tag Browser, and can be inserted into a Data View as a unit.

**Annotations.** Right-click a comment cell to edit its annotations in a dialog: flags such as read-only or external, choices, min and max, unit of measure, and physical timing. The bracket syntax in the comment is written for you, and the offline Console and program checks read it.

**Filter by what the program does with a tag.** The filter box accepts analysis prefixes alongside ordinary text. `input:` and `output:` show the tags at the program's edges, `pivot:` the ones in the middle, and `isolated:` the ones nothing reads or writes. `upstream:MotorOut` shows everything that feeds a tag; `downstream:StartPB` shows everything a tag feeds. Prefixes compose with text, so `upstream:MotorOut ^Alm` narrows to the alarms that hold a motor off.

Existing ladder logic may not show a renamed nickname until you use CLICK's Address Picker (<kbd>Ctrl</kbd>+<kbd>T</kbd>) or reopen the project. See [issue #36](https://github.com/ssweber/clicknick/issues/36).

## Tag Browser

**No UDTs? We gotchu.**

Okay, not actual UDTs. But structured names don't have to look like one giant flat address table.

The Tag Browser turns the nickname list into an outline. Single underscores create levels, so `SupplyTank_Pump_Status` becomes:

```text
SupplyTank
└── Pump
    └── Status
```

Trailing numbers are read as arrays: `Alm1_id`, `Alm1_value`, `Alm2_id`, and `Alm2_value` group under `Alm[1-2]`. A Blocks panel lists the named blocks from the Address Editor. Double-click an item to edit it.

![Tag Browser screenshot](https://github.com/user-attachments/assets/07928355-180e-4b00-b0bb-07ad2bdbe831)

The outline is built from names alone. It changes nothing in your project, and a naming convention you already follow is all it takes.

## Data View builder

CLICK's Data View asks for addresses. ClickNick's asks for names.

- Loads the `.cdv` files from the open CLICK project into tabs.
- Add addresses by nickname.
- Drag, cut, paste, and reorder entries.
- Insert a nickname, a related structure, or a whole block from the Tag Browser in one step.

A Data View created in ClickNick is imported into CLICK by hand.

## Where these write

Address Editor and Data View changes live in CLICK's temporary files until you save in CLICK Programming Software. ClickNick is beta software, so review them before you do. [Where ClickNick writes.](help/index.md#where-clicknick-writes)

[Back to the tour](tour/autocomplete.md) · [Help](help/index.md)
