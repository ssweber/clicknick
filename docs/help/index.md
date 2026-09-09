# ClickNick help

The product tour explains why the tools are useful. This page is the starting point for using them.

## Start here

- [Install ClickNick](../install.md)
- [Connect a project and try the core workflow](../getting-started.md)
- [Take the six-part product tour](../tour/autocomplete.md)
- [Editing tools](../editing.md) — Address Editor, Tag Browser, Data View builder

## Check Program and Console

Both read the saved ladder files, not unsaved edits, so save in CLICK first. Check Program reports findings with the rung source, a severity, and a fix hint where there is one. The Console runs the program offline and takes the same commands as pyrung's debug console. Type `help` for the list, or read the [command reference](https://pyrung.com/pyrung/guides/dap-vscode/#debug-console) in the pyrung docs.

## Workspaces

### Check preferences

**Choose Checks** controls which checks run. Without a workspace, **Save and Run**
saves your app-wide defaults in `%LOCALAPPDATA%\ClickNick\check-defaults.toml`.
All programs without a workspace use these preferences, starting with pyrung's
core checks until you customize them.

When you create or open a workspace without check settings, ClickNick copies your
current preferences into `[tool.pyrung.check]` in its `pyproject.toml`. Existing
workspace settings take precedence and survive regeneration. With a workspace
open, **Save and Run** updates that file automatically; your app-wide defaults
stay unchanged. The window shows where changes will be saved.

```toml
[tool.pyrung.check]
extend-select = ["CMP"]
ignore = ["CMP_STATIC_ON_LEFT"]
```

Omit `select` to inherit pyrung's core defaults, use `extend-select` to add checks,
and `ignore` to exclude them. An explicit `select` replaces the core selection.
Prefixes continue matching checks added in future pyrung versions. The GUI and
`clicknick-cli check` use the same settings.

Collapsing a result only hides its details; the check still runs. **Copy Full Report**
includes collapsed details. **Help** reopens the first-time tips.

### Workspace files

A workspace is a folder that links up with your open project. Until you pick one, ClickNick uses a temporary folder. Pick a real one from the Workspace controls to keep the work with the machine; a small `.clicknick.toml` inside it carries the CLICK PLC name, which is how ClickNick reconnects the same folder when that project is opened again.

On every CLICK save, ClickNick refreshes `src/plc/` (your ladder as Python), `csv/` (the CLICK snapshot it was built from), nickname data, and its generation scripts. Files you add are left alone. If you edited `src/plc/` and a CLICK save is about to replace it, ClickNick copies it to `backup/src/plc/` first; `clicknick-cli restore` puts it back.

Edits to the ladder text go back into CLICK through **Preview Changes**: review the rung diff, **Copy to Click** the rungs you want, and paste them in CLICK's ladder editor. (**Guided Paste**, under the Ladder menu, is different: it walks you through pasting a whole folder of ladder CSVs, such as a program exported from pyrung.) **Reload from CLICK** throws those edits away and restores the saved CLICK version, taking the same backup first.

## Where ClickNick writes { #where-clicknick-writes }

ClickNick does not directly edit the `.ckp` file. It works through the files and workflows CLICK exposes while a project is open:

- Nickname and comment tools read and write CLICK's temporary `SC_.mdb` working database. Those changes become part of the project only when you save in CLICK.
- Data View tools read and write temporary `.cdv` files. A Data View created in ClickNick must be imported into CLICK manually.
- Ladder text edits stay in the workspace until you review them rung by rung in Preview Changes and paste the ones you choose through CLICK's own ladder editor.
- The Tag Browser is built from nickname data and stores nothing.

## Database connection

ClickNick uses an installed Access ODBC driver when available, or Windows' built-in Jet engine through 32-bit PowerShell. Selection is automatic.

If connecting fails, open **Help > About ClickNick > Test Connection**. Choose the project's MDB file if prompted. The test checks read access and reports which connection worked. Use **Copy System Info** to include the result in a [support issue](https://github.com/ssweber/clicknick/issues).

On managed computers, PowerShell restrictions may block Jet. Your administrator can check the reported error or provide a compatible Access ODBC driver.

### Connection options

For troubleshooting, close ClickNick and launch with a specific option:

| Command | Behavior |
| --- | --- |
| `clicknick --db-backend auto` | Prefer Access ODBC, fall back to Jet (default). |
| `clicknick --db-backend jet` | Use Jet even if Access ODBC is installed. |
| `clicknick --db-backend odbc` | Use Access ODBC only. |
| `clicknick --db-backend none` | Use CSV mode. |

Forced `jet` and `odbc` modes report errors instead of switching connections. You can also set `CLICKNICK_DB_BACKEND` to one of these values; the command-line option takes precedence.

### CSV mode

Load a nickname CSV manually, or save a copy of CLICK's project CSV when offered. CSV mode supports autocomplete and CSV editing, but does not sync changes with CLICK's database. Check Program, Console, and workspaces require a database connection.

## Common setup questions

- Nicknames changed through the Address Editor appear in autocomplete immediately. Existing ladder logic may need CLICK's Address Picker or a reopened project to refresh; see [issue #36](https://github.com/ssweber/clicknick/issues/36).
- ClickNick is beta software. Review Address Editor, Data View, and ladder changes before saving in CLICK.

## Project support

- [Report a bug or request a feature](https://github.com/ssweber/clicknick/issues)
- [Ask a question or share an idea](https://github.com/ssweber/clicknick/discussions)
- [Read the changelog](https://github.com/ssweber/clicknick/blob/main/CHANGELOG.md)
- [View the source](https://github.com/ssweber/clicknick)
