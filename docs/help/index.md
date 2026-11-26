# ClickNick help

The product tour explains why the tools are useful. This page is the starting point for using them.

## Start here

- [Install ClickNick](../install.md)
- [Connect a project and try the core workflow](../getting-started.md)
- [Take the six-part product tour](../tour/simulator.md)
- [Editing tools](../editing.md) — Address Editor, Tag Browser, Data View builder

## Check Program

Click **Check Program**. It reports findings with the rung source, a severity, and a fix hint where there is one. It reads the saved ladder files, not unsaved edits, so save in CLICK first. To choose which checks run, see [Check preferences](#check-preferences).

If ClickNick cannot read a rung outside a For loop, the checks cover only the rungs before it in that program. The report names that rung at the top. `clicknick-cli check` names it in a `NOTE:` line.

## Simulator

Run the saved program without the PLC, and keep it current as you edit.

1. Save in CLICK, then click **Simulate**. The Simulator draws your hardware from System Configuration. It reads the saved ladder files, not unsaved edits.
2. Flip the CPU to **RUN** and work the switches, or step one scan at a time.
3. Right-click a point to ask about it: **Why is it ON?** (or OFF) on any input or output, and on outputs **Show simplified logic** and **How (experimental)** to turn it on or off. The question runs in the Console, so you see the command it used.
4. Force a point from the same right-click menu (**Force ON** / **Force OFF**, or **Force value...** on an analog channel; **Release force** undoes it), or double-click an output to force it the other way from what it shows.
5. Change the ladder and save in CLICK. The simulation keeps running the program it has, as a PLC does until you load a new one. The Simulator offers you the new program. Choose how to load it:
    - In RUN, **RUN Time Edit** loads the program and keeps every value, timer and force. **Stop and Write** goes through STOP and back to RUN. It keeps retentive values and forces and clears the rest.
    - In STOP or while stepping, **Write** loads the program and keeps the values and the mode.

When you edit the workspace's ladder source (`src/plc/`), the Simulator offers the new program the same way.

The rules:

- If a save does not convert, the old program keeps running. The Simulator tells you why.
- If ClickNick cannot read a rung inside a For loop, the Simulator does not run the program, and it tells you why. A write or a Restart leaves the old program running.
- If ClickNick cannot read a rung outside a For loop, the simulation runs that program only up to that rung. The PLC runs the rungs after it. While the program runs, a notice at the top of the Simulator names the rung. If only the rungs after it use an X or Y point, the panel can leave that point out. To simulate the rest, paste that rung again in CLICK and save. If you write the rung's logic in `src/plc/` in place of the `undecoded(...)` call instead, the notice goes away when you write the program.
- A force on an input or output stays on its address. A force on internal memory stays on its address when only the nickname changed. If the nickname moved to another address, the force is released.
- A [bench link](#bench-links) follows its nicknames. If a nickname is gone, the link stays on its address. If the link's input was renamed, the link keeps its timing.
- Before you choose, the Simulator lists the forces it will release and the links that moved with a nickname. Afterwards it tells you what it kept, and why it did not keep anything else.
- **Restart** on the Simulator's toolbar starts over from what the workspace holds now (CLICK's last save and any edits). It starts from power-on values or your [PLC data file](#plc-data-file), in the same mode, and keeps your switches, forces and bench links. The Simulator also offers Restart when loading the new program fails.
- In the Console, `reload` loads the new program the same way.
- The simulation keeps running after you close the Simulator, so the Data View Editor or an HMI can stay connected. To stop it, click **Stop** beside the Test heading in the main window. That heading also shows whether the simulation is running (**Test - Sim on :502**). If another program already uses Modbus port 502, the Simulator offers **Change port...**.

Each thing you do on the panel appears in the Console as a green `#` line with the matching command, such as `# force Motor_Run false`. This teaches you the Console's commands as you use the panel.

### The Console

The Console is the pane at the bottom of the Simulator. <kbd>Ctrl</kbd>+<kbd>`</kbd> shows or hides it, and **Pop out** gives it its own window. It takes pyrung's Console commands: type `help` for the list, or see [Console commands](https://pyrung.com/pyrung/guides/console/).

Two to start with:

```text
why Motor_Run
how Motor_Run
```

When the motor is off, `why Motor_Run` tells you what is holding it off. It shows the rung that drives the motor and the contacts that are not made. `how Motor_Run` searches for inputs you can set to turn the motor on. It answers with steps, such as "Set Start_PB=True", and shows what changed after each one. `how` can take a few minutes. On real programs it sometimes stops without an answer.

### Bench links

On the real machine, an output often comes back as an input. A valve coil drives a cylinder, and the cylinder's limit switch turns on a moment later. A bench link wires this up in the Simulator, so you do not have to flip the switch by hand. It makes an output drive an input, with a delay. A bench link is not in your CLICK project. It stays in the Simulator's settings between runs.

To make one, drag from an output's label to an input, or from an input to an output. You can also right-click the input and choose **Link to the tag that drives it...**. The input then shows a chip with its driver in place of a switch, and the chip counts down while the delay runs. The **Wiring** menu lists the links. You can turn them off or discard them there.

If a tag's comment declares a link, the Simulator shows it as a program link with a blue chip. A bench link has a purple chip. Right-click an input that has a program link to change the link on the bench, or to cut it and simulate a failed sensor. **Save link to project** on a bench link writes the link into the input's comment, so it becomes part of the program. Sync in the Address Editor. When the Simulator loads the program from that Sync, the program declares the link, and the Simulator drops the bench copy.

The simulation can link only an address that a rung in the simulation names. A slot that a rung reaches only through a range, such as X005 in `pack_bits(X003..X010, DS1)`, does not count. A bench link on any other address waits. The **Wiring** menu shows it as `bench, waiting`, and the tooltip on the input's switch says what it waits for. While the link waits, the simulation runs the program's own wiring on that input. To apply it, name the address in a rung, in CLICK or in the workspace's `src/plc`, and write the program to the simulation with **RUN Time Edit**, **Stop and Write** or **Write**. A bench link that you saved waits the same way, and stays in the Simulator's settings.

### PLC data file

The simulation starts from power-on defaults. To start from the controller's live values instead, save a data file in CLICK with **PLC > Read Data from PLC... > All > Save**, then pick it with **PLC Data...** in the Simulator. The Simulator also sets the switches and analog values from that file. The file is not the nickname CSV. CLICK writes a Text comma in the file without quotes. When the comma is next to an empty Text address, the Simulator cannot tell what some Text addresses hold. It starts those addresses at their power-on values, loads the rest of the file, and names them in its message. To load them too, replace the comma in their Text values in CLICK and save the file again. Whenever the file changes while the simulation runs, the simulation starts over from what the workspace holds now.

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

On every CLICK save, ClickNick refreshes `src/plc/` (your ladder as Python), `csv/` (the CLICK snapshot it was built from), nickname data, and its generation scripts. Files you add are left alone. If you edited `src/plc/` and a CLICK save is about to replace it, ClickNick copies it to `backup/src/plc/` first; `clicknick-cli restore` puts it back. The backup that was already there moves to `backup/older/<time>/src/plc/`. ClickNick keeps the last 5 backups. `clicknick-cli restore list` lists the older ones, and `clicknick-cli restore <time>` puts one back. ClickNick does the same when you pick an existing workspace whose `src/plc/` holds edits. Before a restore, ClickNick backs up any edits in `src/plc/` that no backup holds.

## Review Changes

Edits to the ladder text go back into CLICK through **Review Changes**. It lists each program that differs from CLICK's last save and shows the rung diff underneath. It then walks you through pasting the differences into CLICK.

1. Click **Review Changes** in the main window (or **Workspace > Review Changes**).
2. Select a program. Click **Copy** to put just the rungs that differ on the clipboard. The step tells you which rung to select and paste over in CLICK's ladder editor. It also tells you where to add an empty rung for new rungs, and which rungs to delete. To select a rung, click its number at the left of the ladder. CLICK shades the rung. If you only click into the rung's logic, CLICK pastes above the rung and keeps the old rung below. The program then holds both rungs. To delete rungs, select them the same way and press <kbd>Delete</kbd>. If you only click into a rung's logic, <kbd>Delete</kbd> removes the instruction under the cursor, and the rung stays. To select several rungs, click the first rung's number and press <kbd>Shift</kbd>+<kbd>Down</kbd> until the last rung is shaded too. If CLICK's copy of the program has no rungs, click rung 1's number before you paste. If you click lower down the empty ladder, CLICK can keep empty rungs above the pasted ones.
3. Paste in CLICK with <kbd>Ctrl</kbd>+<kbd>V</kbd> and wait for the rungs to appear.
4. Click **Next** and work down the program in order, so each step's rung numbers match what CLICK shows.
5. Save in CLICK. Rows turn **Up to date** as CLICK saves what you pasted, and the window closes once CLICK has saved all of it.

To leave a difference out, untick **Take this difference** above the diff, or click its +/- gutter. CLICK keeps what it has there, and the steps are numbered around it. **◀ ▶** (Alt+Up/Alt+Down, or F7/Shift+F7) go through every difference, program by program. The bar shows how many programs you have not looked at yet. Once you click **Next** past a difference, you can no longer skip it.

When many rungs changed, switch **Copy** from **Changed rungs** to **Whole program**. This clears a program in CLICK and pastes it in one piece, which is quicker. The switch stays as you left it. The step tells you to select every rung from rung 1's number, delete them, and paste.

The rules:

- A whole-program copy keeps CLICK's version of any difference you skipped. If a skipped difference would keep a rung that CLICK holds in an old encoding, ClickNick steps through that program instead of copying it whole.
- ClickNick cannot read some rung comments. Most often, such a comment holds a character outside ASCII in a font whose script is not Western or Chinese GB2312. ClickNick leaves that comment out of the workspace. So Review Changes shows the rung as unchanged, even though the workspace has no comment on it. Before a paste or a delete erases such a comment in CLICK, Review Changes asks you, and names the rung. Cancel is the default. The question says how to keep what CLICK has. When a step deletes such a rung, or the whole program, the button reads **Delete…**, such as **Delete rung 3…**. Click it and answer the question before you delete anything in CLICK. Under **Whole program**, ClickNick steps through such a program instead of copying it whole, so the rungs that match keep their comments.
- If you run Review Changes again before CLICK saves, it goes on from what you pasted. If you have edited the pasted rungs since, it copies that program whole.
- A red row is a program whose copy in CLICK holds an old encoding from an older ClickNick. CLICK runs that encoding differently from how it reads it, so paste the program again.
- A red row can also mean that ClickNick cannot read one of the program's rungs from CLICK. The workspace's `src/plc/` then holds an `undecoded(...)` call in place of that rung, and the program stops there. To fix it, paste that rung in CLICK from your own copy of the program, and save. Until then, Review Changes refuses every program, and its message names the rung. If you write the rung's logic in place of the `undecoded(...)` call instead, Review Changes copies that program only whole. If you delete the call and put no rung in its place, Review Changes refuses that program, because copying it whole would delete the rung in CLICK. To delete the rung, click its number in CLICK and press <kbd>Delete</kbd>. Then save. Review Changes also refuses while the folder holds an UNDECODED marker or an empty rung. Inside a For loop, the workspace holds an empty rung in place of the rung, with no `undecoded(...)` call. Review Changes then refuses only that program.
- If CLICK saves before you finish, the window stays open and you can keep pasting.
- **Reload from CLICK** throws the workspace's edits away and restores the saved CLICK version. It takes the same backup first, and it closes Review Changes.

### Compare with another folder or CLICK window

The same window compares CLICK's program with other ladder, so you can take only some of the differences.

- **Ladder > Compare with > Folder** opens it on any folder of ladder CSVs, such as a program exported from pyrung or a copy of another PLC.
- **Ladder > Compare with > Other CLICK window** does the same with what another open CLICK window last saved.

For another CLICK window, the nicknames and the deletion of programs it lacks start out unticked. If ClickNick could not read a rung comment in the other window, Review Changes asks before you paste that rung, because the rung arrives in CLICK without the comment. ClickNick never writes a folder's nicknames to CLICK's database directly. **Stage nicknames** stages them in the Address Editor, and **Sync and Close** there writes them.

## Where ClickNick writes { #where-clicknick-writes }

ClickNick does not directly edit the `.ckp` file. It works through the files and workflows CLICK exposes while a project is open:

- Nickname and comment tools read and write CLICK's temporary `SC_.mdb` working database. Those changes become part of the project only when you save in CLICK.
- After a Sync, CLICK redraws the nicknames in its ladder. CLICK keeps the names it shows in memory. So ClickNick opens CLICK's **File > Import > Nickname** and cancels it. Nothing is imported, and CLICK reads every nickname again from `SC_.mdb`. CLICK then counts the project as changed. So when you close CLICK, it asks you to save the project with the new nicknames. CLICK's Open dialog shows for a moment, and the window that you were in stays in front. While the redraw runs, ClickNick shows "Redrawing nicknames in CLICK…" over CLICK's window. If CLICK has a dialog open, ClickNick leaves CLICK alone and tells you. Close the dialog, then choose **Tools > Redraw Nicknames in CLICK**. If you turn off **Tools > Redraw Ladder on Sync**, CLICK does not redraw after a Sync. Choose **Tools > Redraw Nicknames in CLICK** when you want the new names in CLICK's ladder. ClickNick remembers the setting in `%LOCALAPPDATA%\ClickNick\settings.json`.
- Data View tools read and write temporary `.cdv` files. A Data View created in ClickNick must be imported into CLICK manually.
- Ladder text edits stay in the workspace until you review them rung by rung in Review Changes and paste the ones you choose through CLICK's own ladder editor.
- The Tag Browser is built from nickname data and stores nothing.
- The Simulator saves switch positions, analog values, forces and bench links in `%LOCALAPPDATA%\ClickNick\simulator\<PLC name>.toml`, or in `simulator.toml` inside the workspace once you set one up.

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

- Nicknames changed through the Address Editor appear in autocomplete immediately, and in CLICK's ladder after a Sync. If CLICK had a dialog open, or you turned off **Tools > Redraw Ladder on Sync**, choose **Tools > Redraw Nicknames in CLICK**. Close CLICK's dialog first. See [Where ClickNick writes](#where-clicknick-writes).
- ClickNick is beta software. Review Address Editor, Data View, and ladder changes before saving in CLICK.

## Project support

- [Report a bug or request a feature](https://github.com/ssweber/clicknick/issues)
- [Ask a question or share an idea](https://github.com/ssweber/clicknick/discussions)
- [Read the changelog](https://github.com/ssweber/clicknick/blob/main/CHANGELOG.md)
- [View the source](https://github.com/ssweber/clicknick)
