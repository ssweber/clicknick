# ClickNick README technical details

Moved out of the README on 2026-09-01. Preserve this material for the future ClickNick technical documentation or `pyrung.com/clicknick` site.

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

## Related material

The expanded AI and coding-agent workflow is preserved in `scratchpad/agent-workflow.md`.
