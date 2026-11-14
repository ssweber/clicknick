# ClickNick help

The product tour explains why the tools are useful. This page is the starting point for using them.

## Start here

- [Install ClickNick](../install.md)
- [Connect a project and try the core workflow](../getting-started.md)
- [Take the six-part product tour](../tour/autocomplete.md)
- [Editing tools](../editing.md) — Address Editor, Tag Browser, Data View builder

## Check Program

Click **Check Program**. It reports findings with the rung source, a severity, and a fix hint where there is one. It reads the saved ladder files, not unsaved edits, so save in CLICK first. To choose which checks run, see [Check preferences](#check-preferences).

## Simulator

Run the saved program without the PLC, and keep it current as you edit.

1. Save in CLICK, then click **Simulate**. The Simulator draws your hardware from System Configuration. It reads the saved ladder files, not unsaved edits.
2. Flip the CPU to **RUN** and work the switches, or step one scan at a time.
3. Right-click a point to ask about it: **Why is it ON?** (or OFF) on any input or output, and on outputs **Show simplified logic** and **How (experimental)** to turn it on or off. The question runs in the Console, so you see the command it used.
4. Force a point from the same right-click menu (**Force ON**, **Force OFF**, **Release force**), or double-click an output to force it the other way from what it shows.
5. Change the ladder and save in CLICK. The simulation keeps running the program it has, as a PLC does until you load a new one, and the Simulator offers the new program. Choose how to load it:
    - In RUN, **RUN Time Edit** loads it and keeps every value, timer and force. **Stop and Write** goes through STOP and back to RUN, which keeps retentive values and forces and clears the rest.
    - In STOP or while stepping, **Write** loads it and keeps the values and the mode.

An edit to the workspace's ladder source (`src/plc/`) is offered the same way.

The rules:

- A save that does not convert, or that holds a rung ClickNick cannot read, leaves the old program running, and the Simulator says why.
- A force on an input or output stays on its address. A force on internal memory stays on its address when only the nickname changed, and is released when its nickname moved to another address.
- A [bench link](#bench-links) follows its nicknames, or stays on its address when a nickname is gone. A link whose input was renamed keeps its timing.
- The Simulator lists the releases, and the links that moved with a nickname, before you choose, and afterwards says what was kept and why anything was not.
- **Restart** on the Simulator's toolbar starts over on what the workspace holds now (CLICK's last save and any edits), from power-on values or your [PLC data file](#plc-data-file), in the same mode and with your switches, forces and bench links. It is also offered when loading the new program fails.
- In the Console, `reload` loads the new program the same way.
- The simulation keeps running after you close the Simulator, so a Data View or HMI can stay connected. Stop it with **Stop** beside the Test heading in the main window, which also shows whether it is running (**Test - Sim on :502**). If another program already uses Modbus port 502, the Simulator offers **Change port...**.

What you do on the panel shows in the Console as a green `#` line with the matching command (`# force Motor_Run false`), so the panel teaches the Console's language.

### The Console

The Console is the pane at the bottom of the Simulator. <kbd>Ctrl</kbd>+<kbd>`</kbd> shows or hides it, and **Pop out** gives it its own window. It takes pyrung's debug console commands: type `help` for the list, or see [Console commands](PYRUNG_CONSOLE_URL).

Two to start with:

```text
why Motor_Run
how Motor_Run
```

When the motor is off, `why Motor_Run` answers what is holding it off: the rung that drives it and the contacts that are not made. `how Motor_Run` searches for inputs to set that turn it on and answers with them as steps, such as "Set Start_PB=True", with what changed after each. `how` can take a few minutes, and on real programs it sometimes stops without an answer.

### Bench links

On the real machine, an output often comes back as an input: a valve coil drives a cylinder, and the cylinder's limit switch turns on a moment later. A bench link wires that up in the Simulator so you do not have to flip the switch by hand: an output drives an input, with a delay. It lives on the bench: it is not in your CLICK project, and it stays in the Simulator's settings between runs.

To make one, drag from an output's label to an input (or the other way), or right-click the input and choose **Link to the tag that drives it...**. The input then shows a chip with its driver in place of a switch, and the chip counts down while the delay runs. The **Wiring** menu lists the links, and turns them off or discards them.

A link the program itself declares in a tag's comment shows as a program link (blue chip; a bench link is purple). Right-click an input with one to change it on the bench, or cut it to simulate a failed sensor. **Save link to project** on a bench link writes it into the input's comment, so it becomes part of the program: Sync in the Address Editor, and after the next build the bench copy is dropped.

### PLC data file

The simulation starts from power-on defaults. To start from the controller's live values instead, save a data file in CLICK with **PLC > Read Data from PLC > All > Save**, then pick it with **PLC Data...** in the Simulator. That also sets the switches and analog values from it. It is not the nickname CSV. The simulation starts over whenever the file changes, on what the workspace holds now.

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

On every CLICK save, ClickNick refreshes `src/plc/` (your ladder as Python), `csv/` (the CLICK snapshot it was built from), nickname data, and its generation scripts. Files you add are left alone. If you edited `src/plc/` and a CLICK save is about to replace it, ClickNick copies it to `backup/src/plc/` first; `clicknick-cli restore` puts it back. The backup already there moves to `backup/older/<time>/src/plc/`, and the last 5 backups are kept; `clicknick-cli restore list` lists the older ones and `clicknick-cli restore <time>` puts one back. The same goes for an existing workspace you pick whose `src/plc/` holds edits. A restore first backs up edits in `src/plc/` that no backup holds.

## Review Changes

Edits to the ladder text go back into CLICK through **Review Changes**. It lists each program that differs from CLICK's last save, with the rung diff underneath, and walks you through pasting the differences into CLICK.

1. Click **Review Changes** in the main window (or **Workspace > Review Changes**).
2. Select a program. Click **Copy** to put just the rungs that differ on the clipboard. The step says which rung to select and paste over in CLICK's ladder editor, where to add an empty rung for new ones, and which rungs to delete.
3. Paste in CLICK with <kbd>Ctrl</kbd>+<kbd>V</kbd> and wait for the rungs to appear.
4. Click **Next** and work down the program in order, so each step's rung numbers match what CLICK shows.
5. Save in CLICK. Rows turn **Up to date** as CLICK saves what you pasted, and the window closes once CLICK has saved all of it.

To leave a difference out, untick **Take this difference** above the diff, or click its +/- gutter: CLICK keeps what it has there, and the steps are numbered around it. **◀ ▶** (Alt+Up/Alt+Down, or F7/Shift+F7) go through every difference, program by program, and the bar says how many programs you have not looked at yet. Once you click **Next** past a difference, it can no longer be skipped.

When many rungs changed, switch **Copy** from **Changed rungs** to **Whole program**. It clears a program in CLICK and pastes it in one piece, which is quicker. The switch stays as you left it.

The rules:

- A program whose skipped difference keeps CLICK's rung in an old encoding is stepped through instead of copied whole. The whole program otherwise keeps CLICK's version of any difference you skipped.
- Running Review Changes again before CLICK saves goes on from what you pasted. A program whose pasted rungs you edited since is copied whole.
- A red row is a program whose copy in CLICK holds an old encoding from an older ClickNick. CLICK runs it differently from how it reads, so paste it again.
- A red row can also mean ClickNick cannot read one of the program's rungs from CLICK. The workspace holds an empty rung in its place. Paste that rung from your own copy of the program. Review Changes copies such a program only whole, and not while its folder holds an empty rung.
- If CLICK is saved before you finish, the window stays open and can keep pasting.
- **Reload from CLICK** throws the workspace's edits away and restores the saved CLICK version, taking the same backup first. It closes Review Changes.

### Compare with another folder or CLICK window

The same window compares CLICK's program with other ladder, so you can take only some of its differences.

- **Ladder > Compare with > Folder** opens it on any folder of ladder CSVs, such as a program exported from pyrung or a copy of another PLC.
- **Ladder > Compare with > Other CLICK window** does the same with what another open CLICK window last saved.

For another CLICK window, its nicknames and the deletion of programs it lacks start out unticked. A folder's nicknames are never written to CLICK's database directly: **Stage nicknames** stages them in the Address Editor, and **Sync and Close** there writes them.

## Where ClickNick writes { #where-clicknick-writes }

ClickNick does not directly edit the `.ckp` file. It works through the files and workflows CLICK exposes while a project is open:

- Nickname and comment tools read and write CLICK's temporary `SC_.mdb` working database. Those changes become part of the project only when you save in CLICK.
- Data View tools read and write temporary `.cdv` files. A Data View created in ClickNick must be imported into CLICK manually.
- Ladder text edits stay in the workspace until you review them rung by rung in Review Changes and paste the ones you choose through CLICK's own ladder editor.
- The Tag Browser is built from nickname data and stores nothing.
- The Simulator remembers switch positions, analog values, forces and bench links in `%LOCALAPPDATA%\ClickNick\simulator\<PLC name>.toml`, or in `simulator.toml` inside the workspace once you set one up.

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

Load a nickname CSV manually, or save a copy of CLICK's project CSV when offered. CSV mode supports autocomplete and CSV editing, but does not sync changes with CLICK's database. Check Program, Simulate, and workspaces require a database connection.

## Common setup questions

- Nicknames changed through the Address Editor appear in autocomplete immediately. Existing ladder logic may need CLICK's Address Picker or a reopened project to refresh; see [issue #36](https://github.com/ssweber/clicknick/issues/36).
- ClickNick is beta software. Review Address Editor, Data View, and ladder changes before saving in CLICK.

## Project support

- [Report a bug or request a feature](https://github.com/ssweber/clicknick/issues)
- [Ask a question or share an idea](https://github.com/ssweber/clicknick/discussions)
- [Read the changelog](https://github.com/ssweber/clicknick/blob/main/CHANGELOG.md)
- [View the source](https://github.com/ssweber/clicknick)
