# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Added

- **Simulate** runs the saved program on your CLICK hardware as drawn from System Configuration, with input switches, output LEDs, analog values, forces, STOP / STEP / RUN with speed control, and a Modbus server on 127.0.0.1:502 that the Data View editor joins with a Force column.
- Right-click a Simulator point to ask **Why**, **How** or **Show simplified logic** in the Console, where panel actions also echo as the matching commands, and double-click an output to force it.
- Feedback links let an output drive an input on the Simulator, like a contactor's aux contact or a limit switch: drag one to add it for the session, cut it to simulate a failed sensor, or save it to the input's comment for the program.
- Copying rungs that use CLICK v4 instructions is refused when the CLICK window is older, instead of letting CLICK silently change them on paste.
- Preview Changes marks which programs differ from CLICK's last save, steps through only those, and lists subroutines CLICK has that the folder doesn't.
- Preview Changes shows the selected program's rung diff against CLICK's last save and steps through just the rungs that differ, saying which rung to paste over or delete in CLICK, or copies whole programs when you switch **Copy** to **Whole program**.
- Preview Changes' rung diff highlights only the lines and words that changed, like GitHub Desktop, with one unchanged rung on each side of a difference and separators whose arrows show more.
- Preview Changes lets you take or skip each difference: untick **Take this difference** or click its +/- gutter and CLICK keeps its rungs there, the steps are numbered around it, **Whole program** copies the program as you chose it, and ◀ ▶ (Alt+Up/Down or F7/Shift+F7) go through every difference across programs. A blue bar beside the +/- gutter marks the difference being looked at.
- **Ladder > Compare with > Folder** (it was **Open in Preview Changes**) compares CLICK's program with a folder of ladder CSVs, such as a copy of another PLC, so you can take only some of its differences; the title and the diff say which folder the changes come from.
- **Ladder > Compare with > Other CLICK window** compares CLICK's program with what another open CLICK window last saved, such as a sister PLC's project: its nicknames start out skipped and the programs only this CLICK has start out kept, and **Refresh** takes its latest save.
- ClickNick warns when CLICK holds rungs an older ClickNick pasted in a form CLICK runs differently.
  - Preview Changes shows those programs in red until you paste them again.
  - `clicknick-cli program save` lists them.
- ClickNick names each rung it cannot read from CLICK, such as a compare CLICK's own dialog refuses, and asks you to paste it again (the build stopped with `WriterError`).
  - The workspace holds an empty rung in its place. The rest of the program builds.
  - The Simulator refuses to start until you paste it again.
  - Preview Changes shows the program in red and copies it only whole (it left the program out).
  - Preview Changes refuses to copy it while the folder holds an empty rung. Paste that rung from your own copy of the program first.
  - Saving the clipboard to CSV names the rung it cannot read (it showed `WriterError`).
- Preview Changes' **New Subroutine** button opens CLICK's New Subroutine Program window with the name filled in, for any subroutine CLICK's last save doesn't show it already has.
- **Tools > Repairs > Upgrade Project** rewrites comments in pyrung's old `profile=` form into the current keys and stages them on the Changed tab for you to review and Sync, as `clicknick-cli tag upgrade-project` does.
- When the build stops on a comment in the old form, the Workspace status says to run **Tools > Repairs > Upgrade Project** (it said "Build failed").

### Changed

- The Console is now a pane in **Simulate** (<kbd>Ctrl</kbd>+<kbd>`</kbd> toggles it, **Pop out** gives it a window), and the simulation keeps running after the Simulator closes until you stop it from the main window.
- A workspace's `AGENTS.md` and `README.md` are now yours to edit: pyrung's guidance moves to `AGENTS.pyrung.md` and `README.pyrung.md`, and an older generated `AGENTS.md` or `README.md` is kept as `*.previous.md`.
- `link=` annotations take a CLICK address such as `Y001`, or `~Y001` to follow a bit while it is OFF, and need only a response such as `on_delay=`.
- The Simulator's link dialog and the annotation dialog offer every pyrung response (on/off delay, flasher, timed, toggle, ramp and approach), each with its own fields.
- `tag set-physical` takes one option per key, such as `--flasher-on 8ms --flasher-off 8ms` or `--toggle` (it took `--profile`).
- Sync and Discard clear the undo history.
- Preview Changes steps through subroutines before `main.csv`, so they exist in CLICK before main's Call instructions are pasted.
- **Preview Changes** and Guided Paste are one window, Preview Changes: the button and `clicknick-cli rung apply` open it on the workspace's whole proposed ladder (they opened one preview window per changed file), so new subroutines, rungs and subroutines an edit removes, and what CLICK has saved since are all shown in one place, and **Ladder > Open in Guided Paste** is now **Open in Preview Changes**.
- Preview Changes closes once a CLICK save holds everything it was pasting, and after a save that came too early it stays open, says so, and can keep pasting.
- A program CLICK has that the folder doesn't is a step in Preview Changes: delete it in CLICK and click **Next**, or untick **Delete it in CLICK** to keep it, and the window then closes on a CLICK save without it (it only advised deleting it, and stayed open while CLICK had it).
- Under **Copy: Changed rungs**, Preview Changes copies a program whole when stepping through it would take 6 or more steps, unless it has 100 rungs or more or CLICK holds some of its rungs in an old encoding; **Step Through** steps through that program anyway (it only suggested switching).
- A folder's `nicknames.csv` in Preview Changes is staged in the Address Editor instead of written straight into CLICK's database: **Stage nicknames** shows them on the Changed tab, validated, with a **Sync and Close** button, and the row counts what it changes ("3 new, 1 renamed") and can be skipped (it imported them unchecked, and could delete addresses the file listed blank).

### Fixed

- In the Tag Browser's Outline, Rename changes the segment you picked instead of an unrelated nickname that starts with the same letters, and nicknames like `Pump01_Run` keep their leading zeros, stay apart from `Pump1_Run`, and double-clicking one filters the Address Editor to it.
- The Tag Browser's Outline lists array indices in numeric order (Pump2 before Pump10) and lists a nickname used on two addresses once for each.
- Renaming an item in the Outline changes only the nicknames under that item, accepts a new name that starts with a digit, and is off for SC/SD entries and `__` groups.
- Double-clicking an SC or SD entry in the Outline no longer leaves a stale filter in the Address Editor, and those groups stay open when the list refreshes.
- The overlay's tooltip and the Tag Browser show a timer or counter value's initial value only when its timer or counter is not Retentive, as the Address Editor does.
- The overlay sends nothing to CLICK when you press Esc or click away, so an empty or half-typed name no longer lands in CLICK's field, Enter on an empty overlay just closes it and leaves the Address Picker open, and Esc keeps the overlay hidden for that field until you move to another field.
- The overlay comes back when you click into the same empty field again after clicking away.
- Multi-word overlay searches list matches in list order instead of a random one, and a one-letter search lists only names containing that letter.
- A nickname used twice is listed once in the overlay with its first address, sorting by nickname ignores case, and the overlay's tooltip is read from a row of the types the field accepts.
- In the Address Editor, Undo and Redo wait while you are typing in a cell, and Sync and closing the window keep what you typed.
- Fill Down over a timer or counter selection numbers only the rows of the first row's type, and Fill Down and Clone no longer copy block tags into the new rows' comments (a row that already has its own block tag keeps it); after a Sync, check those comments in CLICK.
- Add Block over a selection that includes both a timer's T and TD rows (or CT and CTD) tags matching pairs, and the Tag Browser's rename changes nicknames only, leaving comments as they are; after a Sync, check the timer or counter block comments in CLICK.
- With **Hide Used** ticked, the Address Editor's right-click menu, Discard changes and character-limit tooltip act on the column you clicked, not the one beside it.
- The Init Value and Ret cells of SC, SD, XD and YD rows are read-only instead of showing an edit that Sync never writes.
- Ctrl+W in the Address Editor closes one tab, and in either editor only its own tab, instead of closing two and then raising an error.
- Remove Block keeps the rest of the comment as it was (`<Pumps> Fill` becomes `Fill`, not ` Fill`); after a Sync, check such a comment in CLICK.
- Text still being typed in an Address Editor cell is kept when you replace the data or close ClickNick and answer the save prompt; a cell that won't commit stops the close.
- A cloned Address Editor tab shows block colors, errors and unsaved edits on every row, and opens at the saved scroll position.
- CLICK v4 projects work: autocomplete fits its instruction dialogs, and Simulate and the workspace read its hardware and PLC name.
- Check Program, Preview Changes and the simulation no longer show Windows' busy cursor while they start.
- Unsaved-change tracking is reliable: Undo, Discard and edits update duplicate marks so Sync isn't blocked by a stale "Duplicate", rows stop showing as unsaved once CLICK saves the value, changes CLICK writes right after a Sync are picked up, and an edit that fails partway changes nothing.
- Sort by nickname, block colors, the Dataview editor, the window title and Workspace details stay current after edits, CLICK saves, Sync, CSV loads and workspace changes, and the Dataview editor writes unchanged CDV files back byte-for-byte.
- Loading a CSV over unsaved changes asks to save or discard first.
- Closing a tab, the Dataview Editor or the data behind it offers every unsaved dataview for saving, untitled ones too (you pick their folder); a save that fails or is cancelled closes nothing, and a failed one says why.
- Saving a dataview that CLICK (or another program) changed after its rows were read asks whether to save over it, reload it, or do neither. A reload that replaces unsaved edits can be undone with Ctrl+Z.
- The Dataview Editor stores addresses added from the Nickname box or the Tag Browser as CLICK writes them (`X001`, `XD0u`), finds nicknames whatever their case, and refuses text that is neither a nickname nor an address. Dataviews saved by an earlier ClickNick may still hold `X1` or `XD0U`: open them in CLICK and check each row shows its address.
- Ctrl+Z and Ctrl+Y in the Dataview Editor undo and redo row moves and edits without the table and the saved file disagreeing, undoing an address change keeps its New Value, and a folder or block added from the Tag Browser is one undo step.
- The Dataview Editor no longer opens a .cdv file it cannot read, so it can't save a nearly empty file over it.
- Program analysis and AI tag lookups use the same nicknames as the generated code, switching CLICK projects no longer freezes the window, and the "tags synced" count counts each tag once.
- Opening another project in the same CLICK window no longer leaves its workspace unbuilt until ClickNick restarts, and Preview Changes now updates its comparison when CLICK's program changes.
- Open Temporary Workspace and the Workspace status update as soon as a build finishes, instead of waiting for something else to refresh the window, such as opening the Simulator.
- Choosing an existing workspace whose `src/plc` holds edits copies them to `backup/src/plc` before the next build regenerates it; `clicknick-cli restore` puts them back.
- Workspace setup no longer switches when both the current and the chosen workspace's `src/plc` hold edits; it names both folders so you can paste or discard one first.
- A chosen workspace whose `src/plc` edits were kept shows as edited instead of Clean.
- **Export Workspace** and Workspace setup after a failed build say why instead of using the workspace of an earlier save.
- "N tags synced - Save in CLICK" no longer drops to 0 when the workspace rebuilds, such as after a Sync with repairs, opening the Simulator or setting up a workspace, and opening the Simulator during a build no longer starts a second one.
- Sync counts only the rows it wrote, so an edit CLICK's database already held no longer adds to "N tags synced" and a Sync of edits CLICK already had says there was nothing to write, and Save to a CSV file counts the rows you changed (it counted every row in the file).
- A workspace `AGENTS.md` or `README.md` that is not UTF-8 no longer makes every build fail and leave the workspace without `csv/`.
- A workspace `AGENTS.md` or `README.md` with a UTF-8 BOM gets pyrung's pointer under its title.
- A workspace `pyproject.toml` ClickNick cannot read no longer reports a finished **Reload from CLICK** as failed.
- A build that cannot finish writing the workspace, such as when a file in it is open in Excel, still fails but leaves `csv/` and `src/plc` both from the save before.
- After a CLICK save whose build fails before the workspace is written, Preview Changes says it could not read CLICK's program instead of comparing with the save before.
- A CLICK save is noticed when its files get an older timestamp (a copied-back project, a clock change) and when it only deletes a subroutine.
- A broken `%LOCALAPPDATA%\ClickNick\project-sidecars.json` no longer stops ClickNick connecting to CLICK.
- Editing a timer or counter comment's text no longer deletes the block tag on its TD/CTD (or T/CT) row, renaming a block renames the matching tags where they are without adding spaces or moving text, and a rename never overwrites a tag you set in the same edit.
  - After Sync, CLICK's Address Picker shows each renamed tag with the rest of its comment as it was, such as `</Tanks> last` on the close row.
- Changing only a timer or counter block's colour no longer adds a half block tag to a TD/CTD row that has none, and Discard row changes on a T or CT row no longer changes its TD/CTD row's Retentive.
- Answering Yes to "Save before closing?" with duplicate or invalid nicknames now refuses and closes nothing, as Sync does, instead of writing them to CLICK.
- Sync keeps what CLICK changed in its database since ClickNick last read it.
  - Change a comment in CLICK, then rename that address in ClickNick and Sync right away: CLICK keeps its new comment.
- A system nickname CLICK wrote (SC, SD, X) no longer turns into an error that blocks Sync after a CLICK save or a Sync.
- The nickname tooltip and the Tag Browser show Retentive and the initial value against the address's own default: a non-retentive counter shows Non-retentive, and a retentive DS or TD no longer shows "Initial Value = 0".
- A paste that changes nothing is no longer an undo step.
- The status bar names the edit Undo and Redo acted on.
- A nickname CSV that Excel saved as "CSV UTF-8" loads its nicknames instead of loading empty.
- A file that is not a nickname CSV, such as one without Address and Nickname columns, CLICK's own Address.csv, or a row whose Address is not a CLICK address, fails to load and names the line, instead of loading as an empty project that Save then overwrites.
- In CSV mode, Save says so when the file cannot be written, such as while Excel holds it open, and keeps your edits, instead of reporting success, and refuses to overwrite a file that changed on disk into one ClickNick cannot read.
- XD and YD nicknames in a CSV (`XD0u`, `XD8`) stay on their own addresses when loaded, imported or staged.
- Nickname CSVs keep comments' leading and trailing spaces, read Retentive written as `1`/`0` or `True`/`False`, and end lines with CRLF, as CLICK's export does.
- A Text initial value holding `,`, `"` or a space is quoted when ClickNick writes a CSV, and ClickNick reads it back unchanged; whether CLICK's import shows it unchanged is not yet checked (import such a CSV into CLICK and look at the Text address).
- Import from CSV imports each row of a nested block once, under the innermost block, so unticking an inner block leaves its rows alone.
- Import from CSV skips nicknames, comments or first-scan values when the file has no column for them, instead of clearing them, and accepts a file with no Nickname column.
- Save Copy of CLICK's Address.csv keeps addresses that have only an initial value or Retentive set.
- ClickNick reloads its data when the database or CSV is replaced by an older copy, such as a restored backup.
- Closing ClickNick (the window's X or **File > Exit**) asks to save unsaved Address Editor and Dataview edits, and Cancel keeps it open (it discarded them).
- Nicknames loaded from a CSV stay loaded, with their unsaved edits, when CLICK opens another project or saves under a new name (they were closed without asking).
- A cancelled or failed CSV load leaves the loaded database as it was (the title said CSV, and the next project change in CLICK left no nicknames loaded).
- After the connected CLICK window closes, ClickNick lists the other windows and waits for you to pick one while nicknames are loaded (it connected to the first one and closed the loaded CSV).
- **Stop** in the main window turns off only autocomplete, until you click **Start** or pick a window: ClickNick still notices CLICK closing or opening another project (it kept the old project's editors, simulation and database).
- A CSV that cannot be loaded shows why, such as a missing Nickname column (the status only said "CSV load failed").
- Two CLICK windows with the same project name are listed with their PIDs, so either can be picked, and the window list and status no longer show a window or "Monitoring" that is not current.
- The window list always shows the connected CLICK window, also after ClickNick connects by itself or CLICK opens another project (it could be empty while the status said "Monitoring").
- When CLICK saves under a new name or opens another project while you have unsaved address or Dataview changes, ClickNick asks whether to keep them for the new project, where Sync and Save then write them, or discard them (it discarded them).
- **Load Ladder CSV to Clipboard** copies for the connected CLICK window and asks you to connect first (it used the first CLICK window it found).
- ClickNick deletes its copies of CLICK windows that have closed, made by **Compare with > Other CLICK window**, when it starts and when the window list is refreshed.
- `clicknick-cli tag apply` keeps a comment's text and block tag and changes only the annotations you changed in `tags.py` (it replaced the comment with them alone, such as `[uom=mm]`).
  - Comments that an earlier `tag apply` cut down to their annotations keep only the annotations in CLICK: put their text back by hand.
- `clicknick-cli tag apply` no longer stages `[external]` on analog input channels you did not edit.
- `clicknick-cli get`/`set` find tags by the names in the workspace, also when the analysis of a CLICK save failed.
- `clicknick-cli` passes each argument as you typed it, so a value can hold quotes, backslashes or `;`, such as `set DS1 comment "Don't start"`.
  - A command given as one argument is split at spaces and at `;` outside quotes. A backslash there is kept as typed (`C:\temp`), except that `\"` and `\\` still escape inside double quotes.
  - An argument ending in `;` still ends a command.
- `clicknick-cli prompt-save` answers at once while ClickNick shows the reminder, instead of holding every other command until the dialog is closed.
- Saving in CLICK while the simulation is on restarts it on the saved program, from power-on values (or your PLC data file), back in the same mode with your switches, forces and bench links, and the Simulator says so (it kept running the old program). A save that does not convert stops the simulation, and the Simulator says why; it starts again on the next save that converts.
- The simulation's forces and bench links stay on their addresses when you rename their tags, and turning it off or restarting it while it restores them no longer deletes them; a saved force or link that is not on a CLICK address is reported instead of dropped without a word.
- Closing the project or the CLICK window while the simulation starts stops it instead of leaving it holding Modbus port 502, and a simulation that exits as it starts shows as failed instead of ready.
- Switch settings on Unassigned I/O inputs survive opening the Simulator before the first build finishes, an analog input with a range gets its slider once the simulation starts, and the Simulator follows nickname edits after a CSV is loaded.
- Preview Changes remembers what you pasted until CLICK saves it: running Preview Changes again, switching **Copy**, a Sync or a failed read of CLICK's program no longer has you paste the same rungs a second time, a program whose pasted rungs the new export changes or takes back is copied whole, and **Restart** asks first.
- Preview Changes no longer forgets what you pasted when CLICK saves while it is still reading the save before.
- A program or deletion marked done in Preview Changes that CLICK's next save shows still to do is a step again, also when that save changed nothing (it stayed done, and the window never closed).
- A ladder CSV that Preview Changes cannot read is left out with a notice, so the window still closes once CLICK has saved the rest.
- **Copy: Whole program** steps through a program when a difference you skipped keeps a rung CLICK holds in an old encoding, so the paste does not rewrite that rung from ClickNick's reading of it.
- Without a comparison with CLICK, Preview Changes says to delete the program's rungs before pasting it whole, and copies only while connected to a CLICK window (it used the first CLICK window it found).
- A folder's `nicknames.csv` without an Address Comment, Initial Value or Retentive column no longer clears those fields when Preview Changes stages it.
- A program with no rungs copied whole in Preview Changes is a step of deleting its rungs in CLICK, then **Next** (copying it failed with "there are no rungs to copy").
- `clicknick-rung load` on a CSV with no rungs says so instead of crashing.

## v0.23.4 - 2026-10-11

### Fixed

- Generated workspaces remain openable, editable, and exportable when program analysis fails, while the Console reports simulation startup failures with Retry and optional diagnostic details.
- The nickname overlay's dropdown stays open when its arrow is clicked, and typing no longer raises a Tcl error, on newer Python and Tk 9 installs.
- Updated pyrung to 0.15.2 so the Console's PLC Data loads a CLICK data dump instead of failing with "no TagMap found in project", seeds plain nicknamed addresses, and rejects a file that is not a data dump; the Browse tooltip and help now say where the dump comes from.

## v0.23.3 - 2026-09-10

### Fixed

- Updated laddercodec to 0.2.2 so program imports preserve branch wiring above later rail-connected rows and parse valid populated SCR special rows without recovery.

## v0.23.2 - 2026-09-10

### Fixed

- Updated pyrung to 0.15.1 so imported CLICK CSV expressions are validated and imported names and text remain data in generated Python.
- Release trust reports use the security page as their source for behavioral disclosures.
- Build dependencies are pinned and fresh checkouts use LF line endings to support reproducible wheels.
- The security page distinguishes intentional workspace execution from imported project data and explains the PowerShell backend choice.

## v0.23.1 - 2026-09-09

### Fixed

- Fixed the missing trust report and dependency inventory downloads from 0.23.0; publishing a GitHub release now uploads the reports and refreshes the security docs automatically.

## v0.23.0 - 2026-09-09

### Features

- Releases include a trust report and CycloneDX dependency inventory with package hashes, licenses, documented purposes, source checks, and vulnerability results.

- Live database features can use Windows Jet through built-in 32-bit PowerShell when the Access ODBC driver is unavailable, with a read-only Test Connection action in Help > About ClickNick and `--db-backend jet|odbc|auto|none` to test a specific backend.

- Check Program and generated workspaces recognize analog inputs assigned in Project.ini, including built-in channels, CPU slots, and expansion modules; sampled copies no longer appear constant just because their hardware source starts at zero.

### Changed

- Runtime dependencies are pinned exactly, including pyclickplc 0.4.0, pyrung 0.15.0, tomlkit 0.15.1, and tksheet 7.6.0.

- Choose Checks saves app-wide preferences for programs without a workspace, seeds workspace check settings once, and automatically saves subsequent workspace changes to its `pyproject.toml`.

- Maintenance actions now live together under Tools > Repairs, system nickname repair no longer occupies the main window while unavailable, and the obsolete `clicknick-dev` launcher has been removed.

### Fixed

- Verify MDB & CDV now accepts ordinary X-address nicknames while continuing to validate CLICK-generated `_IO` system names.

## v0.22.1 — 2026-09-04

### Changed

- README, docs site, and package metadata point at pyrung.com/clicknick; CONTRIBUTING and issue templates added.

## v0.22.0 — 2026-09-03

### Features

- Dots in nickname autocomplete mean underscores: typing or pasting `Alm1.id` reaches `Alm1_id`, and `x.Temperature` commits as `x_Temperature`. Numeric literals such as `1.5` and quoted string literals keep their period.

## v0.21.0 — 2026-09-02

### Features

- **System nickname repair** — when analysis encounters documented CLICK SC/SD system-name problems, ClickNick offers a reviewable AddressStore repair in the GUI and through `clicknick-cli tag repair-system-nicknames`, then retries analysis after Sync.

### Fixed

- SC and SD system nicknames accept CLICK's leading-underscore naming convention while other protected address-name validation remains enforced.

## v0.20.0 — 2026-09-02

### Features

- **Persistent PLC workspaces** — create or select a durable workspace named for the PLC, keep tests, notes, and tooling across generated-program refreshes, preview edited ladder source before copying it back to CLICK, and safely reload from CLICK with a recovery snapshot of replaced source.
- **Check Program** — run pyrung's static ladder checks from Tools > Check Program or against the editable workspace with `clicknick-cli check`, inspect compiler-style diagnostics with source context and fix hints, and copy the complete report for sharing.
- **Interactive pyrung Console** — simulate the saved CLICK program with slot-aware autocomplete, live `how()` progress, CSV snapshot seeding, and automatic reloads when workspace source changes; long-running commands can be stopped without losing forces or scan position, and output can be copied directly.
- **Reviewed ladder changes** — `clicknick-cli rung apply` stages workspace edits and opens Preview Changes with semantic rung diffs, per-group Copy to CLICK actions, and repeatable whole-program copying through Guided Paste.
- **Agent CLI (`clicknick-cli`)** — inspect project status and work with tags and rungs through `info`, `tag`, and `rung` commands, apply `tags.py` edits as one staged Address Editor change, find unused addresses from one or more hints, and recover generated source with explicit backup and restore commands.
- **Program analysis filters** — the Address Editor filter box accepts `input:`, `output:`, `pivot:`, `isolated:`, `upstream:Tag`, and `downstream:Tag` prefixes, which compose with existing text filters.
- **Right-click annotation editor** — comment-field annotations (flags, choices, min/max, unit of measure, physical/link) can be edited in a structured dialog with hover tooltips instead of hand-typed bracket syntax.
- **Add Block dialog** gained an Advanced section for `:block`, `:named_array`, and `:udt` structured block kinds, with live preview and row-count display.

### Fixed

- Persistent workspaces now receive matching generated lifecycle guidance, while temporary workspaces keep their closing warning and user-authored documentation remains untouched.
- Nicknames stay synchronized across CLICK, autocomplete, and the Address Editor when edits arrive before the editor opens, after unrelated comment changes, or following a locked or failed project-database read.
- Preview Changes now compares canonical CLICK rungs, renders complete multiline source, attributes edits to the correct rung, treats displaced rungs as neutral renumbering, and copies subroutines correctly.
- Copy to CLICK now provisions every referenced address, including otherwise-unmaterialized block-copy endpoints, and the preview reliably opens focused with all Guided Paste controls visible.
- Check Program and Console now distinguish projects that are still converting, failed conversion, missing saved ladder files, and genuine launch failures, with useful progress, error details, timeouts, and retry actions instead of hanging or reporting a misleading connection error.
- Console autocomplete now follows pyrung's published command grammar, completes multi-target `how` and `avoid`/`via` clauses, handles `~`-prefixed tags, respects the selected Filter Mode, and keeps the input cursor and dropdown stable.
- Console sessions now recover when the simulation backend exits mid-command, remain independent across concurrent ClickNick instances, and stop correctly while paused at a breakpoint.
- Nickname CSV imports no longer crash, now exclude unchecked blocks, keep options separate for repeated block names, and treat blank numeric initial values like CLICK's default `0` without changing TXT semantics.
- Address rows no longer remain marked **Changed** after an unchanged value is written or an edit is returned to its original value, avoiding unnecessary database writes on save.
- Analysis-project rebuilds preserve the workspace virtual environment and lockfile without leaving stale generated files behind, and reconnecting or switching projects cleans up watchers, Modbus connections, and simulator processes.
- Copy controls and status bars remain visible at their default window sizes and use consistent plain-text labels across Console, Check Program, Preview Changes, and Guided Paste.

### Changed

- The import dialog's **Init Val** and **Retentive** columns are now a single **First Scan** column: the two are imported together, so importing a retentive setting can no longer silently shadow an initial value the program relies on.
- The main window now groups its primary actions around editing, testing, and workspace management, with dedicated action icons, menu-based settings, and an Open Temporary Workspace action before durable setup.
- About ClickNick now summarizes the editing, checking, simulation, and workspace tools, reports the installed pyrung version, and copies complete support diagnostics reliably.

## v0.19.3 — 2026-04-21

### Fixed

- Inserting rows in the Dataview Editor (including multi-row pastes) keeps the underlying data in sync with what is shown, so rows no longer land at the wrong index.

## v0.19.2 — 2026-04-21

### Fixed

- Deleting rows in the Dataview Editor keeps the underlying data in sync with what is shown, so deletes no longer leave orphaned data behind.

## v0.19.1 — 2026-04-14

### Features

- Loading a decoded `.bin` rung payload provisions any missing addresses into the project MDB, as CSV loads already did, and reports how many were inserted.

### Fixed

- Nickname edits in the Address Editor immediately refresh autocomplete and the Dataview Editor instead of leaving stale values behind.

## v0.19.0 — 2026-04-02

### Features

- **Ladder rung import/export** — a new `clicknick-rung` CLI loads and saves rungs via the clipboard and decodes a whole program to CSV, alongside a beta Ladder menu and a step-through Guided Paste panel for pasting a folder of ladder CSVs into Click with nickname import.

### Changed

- The Dataview Editor can reconnect to the PLC and uses more forgiving timeout defaults.

## v0.18.0 — 2026-02-27

### Changed
- Restored local ownership of `export_cdv`, `get_dataview_folder`, and `list_cdv_files` in `clicknick.views.dataview_editor.cdv_file`.
- Added canonical `read_mdb_csv()` in `clicknick.data.data_source` returning `dict[int, AddressRow]`.

### Compatibility
- Kept `load_addresses_from_mdb_dump()` as a backward-compatible alias to `read_mdb_csv()`.
