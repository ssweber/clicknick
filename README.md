# ClickNick

![ClickNick logo](https://github.com/user-attachments/assets/2cb7f411-3174-478c-a6c9-409aaa788376)

**Tools to make AutomationDirect CLICK PLC ladder easier to write, test, troubleshoot, and maintain.**

ClickNick works alongside [CLICK Programming Software](https://www.automationdirect.com/clickplcs/free-software/free-click-software). Start with better nickname and address tools, then use program checks, an offline test bench, persistent workspaces, and optional AI-assisted ladder programming as you need them.

> [!IMPORTANT]
> ClickNick never edits your `.ckp` project file directly. You review proposed changes, and nothing becomes part of the project until you save it in CLICK Programming Software. Close CLICK without saving to discard changes made through ClickNick.

ClickNick is a free, open-source Windows application. It runs locally, with no telemetry or required cloud service.

## Install

ClickNick supports Windows 10 and 11 and CLICK Programming Software v2.60-v3.90.

### 1. Install uv

Open PowerShell and run:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Already have uv? Skip this step. Other installation methods are available in the [uv documentation](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Install and run ClickNick

```powershell
uv tool install clicknick
clicknick
```

To upgrade later, run `uv tool upgrade clicknick`. To try the latest release without installing it, run `uvx clicknick@latest`.

Then open your CLICK project as usual. ClickNick detects the open project and connects to it.

### Microsoft Access driver

Full project-aware features - including live nickname sync, Check Program, Console, workspaces, testing, and pyrung analysis - require the **64-bit Microsoft Access ODBC driver** so ClickNick can read CLICK's open project database. See the [Access driver installation notes](https://github.com/ssweber/clicknick/issues/17).

If the driver is missing, ClickNick explains what is unavailable and continues in a reduced CSV mode. Nickname autocomplete and the lighter Address Editor and Data View workflows can still be used with nickname data loaded from CSV.

<details>
<summary>Install with pip instead</summary>

Python 3.11 or newer is required.

```powershell
pip install clicknick
python -m clicknick
```

</details>

![ClickNick main window connected to a CLICK project](https://github.com/user-attachments/assets/de4148a2-cbc5-4b11-95e5-f884c59d70e0)

## Make everyday CLICK programming easier

- **Nickname autocomplete** appears directly in CLICK instruction dialogs, so you can find `Valve5` instead of remembering `C123`.
- **Address Editor** supports bulk nickname, comment, block, and annotation work with validation, search/replace, undo/redo, fill down, and structure cloning.
- **Tag Browser** organizes nicknames into a navigable hierarchy and recognizes related arrays.
- **Data View tools** add nickname lookup, grouped insertion, and drag-and-drop reordering.
- **Project navigation filters** show tag relationships such as inputs, outputs, upstream, downstream, and isolated tags.

ClickNick started by fixing a few editor annoyances - especially the need to remember addresses. You do not need Git, Python experience, an LLM, or a new programming environment to benefit from it. Start with autocomplete, open the Address Editor when it helps, and run Check Program when you want another set of eyes.

## Check the program before running the machine

ClickNick automatically generates a readable, executable [pyrung](https://pyrung.com/) version of the saved ladder in the open CLICK project. This powers two built-in testing tools:

### Check Program

**Check Program** catches common ladder mistakes and questionable patterns without running the machine. Findings include the relevant ladder source, severity, and a suggested fix.

![ClickNick Check Program report](https://github.com/user-attachments/assets/38cb2f44-482a-4e60-9f56-4da95074a971)

### Console

The **Console** is an offline CLICK test bench. It lets you:

- Run and inspect the program scan by scan.
- Force inputs and set up machine conditions without changing the live PLC.
- Work from saved PLC and tag data while troubleshooting.
- Ask why something happened - or why it did not.
- Ask how to reach a state, including routes that must pass through or avoid particular conditions.

![ClickNick Console demonstrating simplified, why, and how queries](https://github.com/user-attachments/assets/1727f54b-7f5d-4181-923e-4fbf7628d2a6)

Save the project in CLICK before opening Check Program or Console so ClickNick can read the latest ladder files.

## Keep engineering work with the machine

The generated pyrung project begins as a temporary workspace. That is convenient for quick checks and experiments. When you want tests, notes, and other engineering work to accumulate with the machine, create or select a persistent workspace from ClickNick.

In a persistent workspace, you can:

- Read the ladder as ordinary, structured Python source with PLC scan semantics.
- Add automated tests alongside the ladder program.
- Keep notes, test fixtures, source history, and other project-specific files.
- Use normal software tools such as diffs, Git, editors, and coding agents.
- Edit generated ladder source and use **Preview Changes** to review the proposed CLICK rungs.
- Copy approved rung changes into CLICK through the guided paste workflow.
- Use **Reload from CLICK** to discard workspace changes and return to the saved CLICK program.

![ClickNick Preview Changes showing a proposed ladder rung edit](https://github.com/user-attachments/assets/78fc0d24-22d9-4f8d-8fa9-6b6e1507b891)

ClickNick preserves a recovery snapshot before regeneration replaces generated source. Files outside ClickNick's generated areas - such as your tests, notes, and editor configuration - remain yours.

## Optional AI-assisted ladder programming

Because the workspace is readable source, you can point an LLM or coding agent at the same ladder program you can inspect yourself. It can explain logic, review the program, improve comments, write tests, or propose changes.

The approval boundary stays the same:

1. The agent edits the workspace, not the `.ckp` file.
2. ClickNick converts proposed source changes back into ordinary CLICK ladder.
3. **Preview Changes** shows the rung differences.
4. You choose what to copy into CLICK.
5. CLICK Programming Software remains the final authority, and the project changes only when you save it there.

CLICK is inexpensive, approachable, and easy to troubleshoot. That simplicity is a feature. ClickNick adds better tools around the existing workflow without trying to turn CLICK into something else.

**CLICK stays CLICK. ClickNick gives you better tools around it.**

## How pyrung fits in

[pyrung](https://pyrung.com/) is a textual ladder representation that executes with PLC scan semantics. Converting the open CLICK program gives it access to normal software tooling - automated tests, diffs, source history, editors, and coding agents - along with PLC-specific analysis such as static validation, causal tracing, reachability, and `why` / `how` queries.

The workflow is reversible: workspace changes can be converted back into ordinary CLICK ladder for review and paste in CLICK Programming Software.

## Feature details

### Nickname autocomplete

An autocomplete dropdown appears over CLICK instruction dialogs. Start typing a nickname and select from the filtered list; ClickNick inserts the address into CLICK.

- Choose prefix, partial/contains, or fuzzy abbreviation matching.
- Hover over a nickname to see its address comment.
- Hide system or internal addresses such as SC/SD and `__private__` tags.
- Keep autocomplete synchronized with Address Editor changes.

![ClickNick autocomplete demo](https://github.com/user-attachments/assets/3a1cdff9-c425-46b7-8b90-4a357d43b6d3)

### Address Editor

- Edit different address sections in multiple windows.
- Copy and paste multiple cells, then review changes before syncing them to CLICK.
- Detect duplicate nicknames and invalid values as you work.
- Fill a nickname pattern down a selection, such as `Alm1` to `Alm2`, `Alm3`, and so on.
- Clone related structures, such as `Alm1_ID` and `Alm1_Val` into the corresponding `Alm2` tags.
- Create color-coded blocks for organization and navigation.
- Undo or redo an entire bulk operation as one edit.

Search with <kbd>Ctrl</kbd>+<kbd>F</kbd> and replace with <kbd>Ctrl</kbd>+<kbd>R</kbd>. Searches cover nickname and comment fields and can be limited to the current selection. The editor also accepts regular expressions, including `^` and `$` anchors and capture groups such as `\1` in replacements.

![Address Editor demo](https://github.com/user-attachments/assets/ee7b1914-2f18-483a-ace1-84c2aa8eea98)

> [!NOTE]
> Nicknames edited in the Address Editor appear immediately in autocomplete. Existing ladder logic refreshes after using CLICK's Address Picker (<kbd>Ctrl</kbd>+<kbd>T</kbd>) or reopening the project. See [issue #36](https://github.com/ssweber/clicknick/issues/36) for details.

### Tag Browser

The Tag Browser turns a flat nickname list into an outline. Single underscores create hierarchy, so `SupplyTank_Pump_Status` becomes:

```text
SupplyTank
└── Pump
    └── Status
```

Trailing numbers are recognized as arrays. Tags such as `Alm1_id`, `Alm1_value`, `Alm2_id`, and `Alm2_value` are grouped beneath `Alm[1-2]`. Double-click an item to edit it.

![Tag Browser screenshot](https://github.com/user-attachments/assets/07928355-180e-4b00-b0bb-07ad2bdbe831)

### Data View Editor

- Load the `.cdv` files from an open CLICK project into tabs.
- Add addresses by nickname instead of raw address.
- Drag, cut, paste, and reorder entries freely.
- Insert a nickname, related structure, or whole block from the Tag Browser.

## Block tags

The Address Editor provides controls to create and manage visual blocks. Power users can also place block tags directly in the Comment field:

```text
<BlockName>                 Start a range
</BlockName>                End a range
<BlockName />               Tag one address
<BlockName bg="#color">     Start a range with a background color
```

Colors may use hex values or these names: Red, Pink, Purple, Deep Purple, Indigo, Blue, Light Blue, Cyan, Teal, Green, Light Green, Lime, Yellow, Amber, Orange, Deep Orange, Brown, and Blue Grey.

For example, use `<Alm Bits bg="Red">` at the start of a range and `</Alm Bits>` at the end.

## Under the hood

ClickNick works with the temporary files that CLICK Programming Software creates when a project is open.

### Address data

- CLICK extracts a temporary Access database named `SC_.mdb` containing address information such as nicknames, comments, and initial values.
- With the Access ODBC driver installed, ClickNick reads and writes that temporary database for live synchronization.
- Without the driver, ClickNick can load nickname data from CLICK's generated `Address.csv` snapshot or a CSV exported through CLICK's **File > Export** command.
- Changes synchronized through ODBC affect CLICK's temporary working data. They become permanent only when you save in CLICK Programming Software.

### Ladder data

- CLICK stores the open program's ladder in temporary files beside the project database.
- ClickNick decodes the saved ladder and generates a local pyrung project for testing and analysis.
- Workspace edits are converted into reviewable rung differences. Copying them back uses CLICK's ordinary ladder workflow rather than modifying the `.ckp` file.

### Data View files

- CLICK stores Data View configurations as UTF-16 `.cdv` files in the temporary project folder.
- ClickNick reads and writes those working files.
- A new Data View created in ClickNick must be imported into CLICK manually.

### Tag Browser

The Tag Browser is generated dynamically by parsing nicknames. It does not store or modify project data itself.

## Project links

- [Report a bug or request a feature](https://github.com/ssweber/clicknick/issues)
- [Ask a question or share an idea](https://github.com/ssweber/clicknick/discussions)
- [View the source](https://github.com/ssweber/clicknick)
- [Read the changelog](CHANGELOG.md)
- [Read the license](LICENSE)

ClickNick is beta software. Review Address Editor, Data View, and ladder changes before saving them in CLICK.
