# Tools

What each ClickNick tool does, and how to use it.

## Nickname autocomplete

A dropdown appears over CLICK instruction dialogs. Start typing a nickname, pick from the filtered list, and ClickNick inserts the address into CLICK.

- Matching modes: prefix, contains, or fuzzy abbreviation.
- Hover a nickname to see its address comment.
- Hide system and internal addresses (SC/SD, `__private__` tags).
- Nicknames changed in the Address Editor show up in autocomplete right away.

![ClickNick autocomplete demo](https://github.com/user-attachments/assets/3a1cdff9-c425-46b7-8b90-4a357d43b6d3)

## Address Editor

Bulk nickname and comment work, reviewed before it syncs to CLICK.

- Open different address sections in separate windows.
- Copy and paste ranges of cells. Changes are listed for review before they sync.
- Duplicate nicknames and invalid values are flagged as you type.
- Fill down a pattern: `Alm1` becomes `Alm2`, `Alm3`, and so on.
- Clone a structure: `Alm1_ID` and `Alm1_Val` become the matching `Alm2` tags.
- Color-coded blocks for organization and navigation.
- Undo or redo a whole bulk operation as one edit.

Search with <kbd>Ctrl</kbd>+<kbd>F</kbd>, replace with <kbd>Ctrl</kbd>+<kbd>R</kbd>. Search covers nicknames and comments and can be limited to the current selection. Regular expressions work, including `^` and `$` anchors and capture groups (`\1`) in replacements.

![Address Editor demo](https://github.com/user-attachments/assets/ee7b1914-2f18-483a-ace1-84c2aa8eea98)

Existing ladder logic may not show a renamed nickname until you use CLICK's Address Picker (<kbd>Ctrl</kbd>+<kbd>T</kbd>) or reopen the project. See [issue #36](https://github.com/ssweber/clicknick/issues/36).

## Tag Browser

Turns the flat nickname list into an outline. Single underscores create levels, so `SupplyTank_Pump_Status` becomes:

```text
SupplyTank
└── Pump
    └── Status
```

Trailing numbers are read as arrays: `Alm1_id`, `Alm1_value`, `Alm2_id`, and `Alm2_value` group under `Alm[1-2]`. Double-click an item to edit it.

![Tag Browser screenshot](https://github.com/user-attachments/assets/07928355-180e-4b00-b0bb-07ad2bdbe831)

## Data View

- Loads the `.cdv` files from the open CLICK project into tabs.
- Add addresses by nickname.
- Drag, cut, paste, and reorder entries.
- Insert a nickname, a related structure, or a whole block from the Tag Browser.

A Data View created in ClickNick is imported into CLICK by hand.

## Check Program

Reports suspicious saved ladder with the rung source, a severity, and a suggested fix. Save the project in CLICK first so ClickNick reads the current ladder.

![ClickNick Check Program report](https://github.com/user-attachments/assets/38cb2f44-482a-4e60-9f56-4da95074a971)

## Console

Runs the generated program offline, on your computer. Save the project in CLICK first.

- Step scan by scan and inspect tags.
- Force inputs to set up a condition.
- Seed the session from a saved tag dump.
- `why` traces what is holding a tag on, off, or blocked.
- `how` searches for a way to reach a state, including routes that must pass through or avoid a condition. Experimental: it can take a minute and sometimes stops without a path.

The Console takes the same commands as pyrung's debug console. Type `help` for the list, or read the [command reference](https://ssweber.github.io/pyrung/guides/dap-vscode/#debug-console) in the pyrung docs.

![ClickNick Console showing simplified, why, and how queries](https://github.com/user-attachments/assets/1727f54b-7f5d-4181-923e-4fbf7628d2a6)
