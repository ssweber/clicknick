# The tag list, fixed

CLICK gives you one flat table: every address, one nickname column, one comment column, edited a cell at a time or round-tripped through Excel. Everything on this page is about that table: adding to it, editing it, organizing it, and finding your way around it.

## Add

Fill a pattern down a selection: `Alm1` becomes `Alm2`, `Alm3`, and so on. Clone a structure: `Alm1_ID` and `Alm1_Val` become the matching `Alm2` pair. In any CLICK instruction dialog, type `Alm1.id` and autocomplete reaches `Alm1_id`.

## Edit

The Address Editor opens different address sections in separate windows, takes pasted ranges of cells, and flags duplicate nicknames and invalid values as you type. Search with <kbd>Ctrl</kbd>+<kbd>F</kbd> and replace with <kbd>Ctrl</kbd>+<kbd>R</kbd>, across nicknames and comments or within the current selection; regular expressions work, including `^` and `$` anchors and `` capture groups in replacements. Right-click a comment cell to set its annotations in a dialog (read-only, external, choices, min and max, unit of measure, physical timing) instead of typing bracket syntax; Check Program and the Console read them. Undo a whole bulk operation as one step, and review every change before it syncs to CLICK.

![Address Editor demo](https://github.com/user-attachments/assets/ee7b1914-2f18-483a-ace1-84c2aa8eea98)

Existing ladder logic may not show a renamed nickname until you use CLICK's Address Picker (<kbd>Ctrl</kbd>+<kbd>T</kbd>) or reopen the project. See [issue #36](https://github.com/ssweber/clicknick/issues/36).

## Organize

Give a range of addresses a name and a color. Blocks show up in the editor, in the Tag Browser, and as a unit you can drop into a Data View.

CLICK has no UDTs, but structured names don't have to look like one giant flat table. The Tag Browser turns the nickname list into an outline. Single underscores create levels, so `SupplyTank_Pump_Status` becomes:

```text
SupplyTank
└── Pump
    └── Status
```

Trailing numbers are read as arrays: `Alm1_id`, `Alm1_value`, `Alm2_id`, and `Alm2_value` group under `Alm[1-2]`. Double-click an item to edit it. The outline is built from names alone; nothing in the project changes, and a naming convention you already follow is all it takes.

![Tag Browser screenshot](https://github.com/user-attachments/assets/07928355-180e-4b00-b0bb-07ad2bdbe831)

## Navigate

Autocomplete in every instruction dialog is [tour stop 1](tour/autocomplete.md).

The Address Editor's filter box also understands what the program does with a tag. `input:` shows tags the ladder reads but never writes, your physical inputs and HMI bits. `output:` shows tags it writes but never reads, your physical outputs. `pivot:` shows the ones in between, and `isolated:` shows nicknamed addresses no rung touches. `upstream:MotorOut` shows everything that feeds a tag, however many rungs away; `downstream:StartPB` shows everything a tag feeds. Prefixes combine with text, so `upstream:MotorOut ^Alm` narrows to the alarms that can hold a motor off.

Data Views are built by name. Load the `.cdv` files from the open project into tabs, add addresses by nickname, and drag to reorder. Double-click a tag in the Tag Browser to add it to the Data View, or double-click a group to add the whole structure or block at once. A Data View created in ClickNick is imported into CLICK by hand.

## Where these write

Address Editor and Data View changes live in CLICK's temporary files until you save in CLICK Programming Software. Review them before you do. [Where ClickNick writes.](help/index.md#where-clicknick-writes)

[Back to the tour](tour/autocomplete.md) · [Help](help/index.md)
