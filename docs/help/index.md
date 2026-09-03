# ClickNick help

The product tour explains why the tools are useful. This page is the starting point for using them.

## Start here

- [Install ClickNick](../install.md)
- [Connect a project and try the core workflow](../getting-started.md)
- [Take the six-part product tour](../tour/autocomplete.md)
- [Editing tools](../editing.md) — Address Editor, Tag Browser, Data View builder

## Check Program and Console

Both read the saved ladder files, not unsaved edits, so save in CLICK first. Check Program reports findings with the rung source, a severity, and a fix hint where there is one. The Console runs the program offline and takes the same commands as pyrung's debug console. Type `help` for the list, or read the [command reference](https://pyrung.com/pyrung/guides/dap-vscode/#debug-console) in the pyrung docs.

## Workspaces and reviewed changes

A temporary workspace is enough for a quick check. A persistent workspace keeps readable source, tests, notes, fixtures, and history with a particular PLC project. It carries a small `.clicknick.toml` file with the CLICK PLC name, which is how ClickNick reconnects the same workspace when that project is opened again.

ClickNick refreshes `src/plc/` (ladder as text), `csv/` (the CLICK snapshot it was built from), nickname data, and its generation scripts on every CLICK save. Files you add are left alone. If you edited `src/plc/` and a CLICK save is about to replace it, ClickNick copies it to `backup/src/plc/` first; `clicknick-cli restore` puts it back.

Edits to the ladder text go back into CLICK through **Preview Changes** and **Guided Paste**. **Reload from CLICK** throws those edits away and restores the saved CLICK version, taking the same backup first.

## Where ClickNick writes { #where-clicknick-writes }

ClickNick does not directly edit the `.ckp` file. It works through the files and workflows CLICK exposes while a project is open:

- With the Access driver installed, nickname and comment tools read and write CLICK's temporary `SC_.mdb` working database. Those changes become part of the project only when you save in CLICK.
- Data View tools read and write temporary `.cdv` files. A Data View created in ClickNick must be imported into CLICK manually.
- Ladder text edits stay in the workspace until you review them rung by rung in Preview Changes and paste the ones you choose through CLICK's own ladder editor.
- The Tag Browser is built from nickname data and stores nothing.

## Common setup questions

- Check Program, Console, and workspaces need the 64-bit Access ODBC driver; see the [driver notes](https://github.com/ssweber/clicknick/issues/17).
- Nicknames changed through the Address Editor appear in autocomplete immediately. Existing ladder logic may need CLICK's Address Picker or a reopened project to refresh; see [issue #36](https://github.com/ssweber/clicknick/issues/36).
- ClickNick is beta software. Review Address Editor, Data View, and ladder changes before saving in CLICK.

## Project support

- [Report a bug or request a feature](https://github.com/ssweber/clicknick/issues)
- [Ask a question or share an idea](https://github.com/ssweber/clicknick/discussions)
- [Read the changelog](https://github.com/ssweber/clicknick/blob/main/CHANGELOG.md)
- [View the source](https://github.com/ssweber/clicknick)
