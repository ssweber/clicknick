# ClickNick help

The product tour explains why the tools are useful. This page is the starting point for using them.

## Start here

- [Install ClickNick](../install.md)
- [Connect a project and try the core workflow](../getting-started.md)
- [Take the six-part product tour](../tour/autocomplete.md)
- [Tools reference](tools.md) — autocomplete, Address Editor, Tag Browser, Data View, Check Program, Console

## Workspaces and reviewed changes

A temporary workspace is enough for a quick check. A persistent workspace keeps readable source, tests, notes, fixtures, and history with a particular PLC project. It carries a small `.clicknick.toml` file with the CLICK PLC name, which is how ClickNick reconnects the same workspace when that project is opened again.

ClickNick refreshes `src/plc/` (ladder as text), `csv/` (the accepted CLICK snapshot), nickname data, and its generation scripts on every CLICK save. Files you add are left alone. Before regeneration replaces a modified `src/plc/`, ClickNick copies it to `backup/src/plc/`; `clicknick-cli restore` puts it back.

Workspace ladder edits return through **Preview Changes** and **Guided Paste**. **Reload from CLICK** discards edits to generated source and restores the saved CLICK version, taking the same snapshot first.

## Where ClickNick writes { #where-clicknick-writes }

ClickNick does not directly edit the `.ckp` file. It works through the files and workflows CLICK exposes while a project is open:

- With ODBC available, nickname and comment tools read and write CLICK's temporary `SC_.mdb` working database. Those changes become part of the project only when you save in CLICK.
- Data View tools read and write temporary `.cdv` files. A Data View created in ClickNick must be imported into CLICK manually.
- Ladder source edits stay in the workspace until Preview Changes converts them into reviewable rung differences and you copy selected changes through CLICK's normal ladder workflow.
- The Tag Browser is generated from nickname data and does not store or modify project data itself.

## Common setup questions

- Full project-aware features need the 64-bit Access ODBC driver; see the [driver notes](https://github.com/ssweber/clicknick/issues/17).
- Nicknames changed through the Address Editor appear in autocomplete immediately. Existing ladder logic may need CLICK's Address Picker or a reopened project to refresh; see [issue #36](https://github.com/ssweber/clicknick/issues/36).
- ClickNick is beta software. Review Address Editor, Data View, and ladder changes before saving in CLICK.

## Project support

- [Report a bug or request a feature](https://github.com/ssweber/clicknick/issues)
- [Ask a question or share an idea](https://github.com/ssweber/clicknick/discussions)
- [Read the changelog](https://github.com/ssweber/clicknick/blob/main/CHANGELOG.md)
- [View the source](https://github.com/ssweber/clicknick)
