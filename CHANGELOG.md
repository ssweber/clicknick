# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Added

#### Simulate

- **Simulate** runs CLICK's last save on a picture of your CLICK hardware from System Configuration, with input switches, output LEDs, analog values, forces (double-click an output), STOP / STEP / RUN with speed control, and a Modbus server on 127.0.0.1 (port 502 by default) that the Data View editor joins with a Force column.
- X and Y addresses the program uses but no module provides get switches and LEDs on a dashed card at the position they belong to (X2xx on "Expansion 2 - unassigned"), between the real modules.
- Feedback links let an output drive an input, like a contactor's aux contact or a limit switch: drag between an output's label and an input's to add one for the session (a bench link), cut it to simulate a failed sensor, or save it to the input's comment for the program.
- When you save in CLICK or edit the workspace's ladder source, the Simulator offers to write the new program as CLICK does for a running PLC: in RUN, **RUN Time Edit** keeps every value, timer and force, and **Stop and Write** goes through STOP, keeping retentive values and forces; in STOP or while stepping, **Write** keeps values and the mode. A save that does not convert leaves the old program running, and the Simulator says why.
- Before a write the Simulator lists the forces it will release and the bench links it will drop or move, and afterwards says what was kept and why anything was not: forces on inputs and outputs stay on their addresses, a force on internal memory is released when its nickname moves to another address, and bench links follow their nicknames.
- **Restart** on the Simulator's toolbar starts the simulation over on what the workspace holds now, from power-on values or your PLC data file, with your mode, switches, forces and bench links. It is also offered when a write fails.

#### Console

- Right-click a Simulator point to ask **Why** in the Console, and on an output also **Show simplified logic** or **How (experimental)** to turn it ON or OFF.
- What you do on the Simulator shows in the Console as the matching command.

#### Review Changes

- Review Changes marks which programs differ from CLICK's last save and shows each one's rung diff, highlighting only the lines and words that changed, with one unchanged rung on each side and separators whose arrows show more.
- It steps through only the rungs that differ, saying which rung to paste over or delete in CLICK, or copies whole programs when you switch **Copy** to **Whole program**.
- You can take or skip each difference: untick **Take this difference** or click its +/- gutter and CLICK keeps its rungs there, the steps are numbered around it, and ◀ ▶ (Alt+Up/Down or F7/Shift+F7) go through every difference across programs.
- **Ladder > Compare with > Folder** compares CLICK's program with any folder of ladder CSVs, such as a copy of another PLC, so you can take only some of its differences; the title and the diff say which folder the changes come from.
- **Ladder > Compare with > Other CLICK window** compares CLICK's program with what another open CLICK window last saved, such as a sister PLC's project: its nicknames start out skipped, the programs only this CLICK has start out kept, and **Refresh from** takes its latest save.
- Review Changes remembers what you pasted until CLICK saves it, also when you switch **Copy**, Sync or open it again, and **Restart** asks before forgetting it.
- It closes once a CLICK save holds everything it was pasting; after a save made before you finished pasting, it stays open, says so, and can keep pasting.
- A program CLICK has that the folder doesn't is a step: delete it in CLICK and click **Next**, or untick **Delete it in CLICK** to keep it.
- **New Subroutine** opens CLICK's New Subroutine Program window with the name filled in, and subroutines come before `main.csv`, so they exist in CLICK before main's Call instructions are pasted.
- Under **Copy: Changed rungs**, a program that would take 6 or more steps is copied whole, unless it has 100 rungs or more or CLICK holds some of its rungs in an old encoding; **Step Through** steps through it anyway.
- ClickNick warns when CLICK holds rungs an older ClickNick pasted in a form CLICK runs differently: Review Changes shows those programs in red until you paste them again, and `clicknick-rung program save` lists them.

#### Other

- CLICK v4.00 is supported: autocomplete fits its instruction dialogs, and Simulate and the workspace read its hardware and PLC name.
- Copying rungs that use CLICK v4 instructions is refused when the CLICK window is an older version, instead of letting CLICK silently change them on paste.
- ClickNick names each rung it cannot read from CLICK, such as a compare CLICK's own dialog refuses, and asks you to paste it again instead of stopping the build (the workspace holds an empty rung in its place, and **Save Clipboard to CSV** names the rung); until then the Simulator won't start, and Review Changes shows that program in red and won't copy it from a folder.
- **Tools > Repairs > Upgrade Project** and `clicknick-cli tag upgrade-project` rewrite comments in pyrung's old `profile=` form into the current keys and stage them on the Changed tab for you to review and Sync; when the build stops on such a comment, the Workspace status says to run it.
- A CLICK save or `clicknick-cli backup` keeps the last 5 backups of edited workspace source, the newest in `backup/src/plc` and the others in `backup/older/<time>/src/plc` (it kept one); `clicknick-cli restore list` lists them, `restore <time>` puts one back, and `restore` first backs up edits in `src/plc` that no backup holds.

### Behaviour changes

- Guided Paste and the workspace's **Preview Changes** are now one window, **Review Changes**, showing the whole proposed ladder (Preview Changes opened one window per changed file).
  - Open it with the workspace's **Review Changes** (button or Workspace menu) or `clicknick-cli rung apply`, and any other folder with **Ladder > Compare with > Folder** (it was **Ladder > Open in Guided Paste**).
- A folder's `nicknames.csv` is no longer written straight into CLICK's database: **Stage nicknames** stages it on the Address Editor's Changed tab.
  - Review the staged rows there and click **Sync and Close**.
- The **Console** button and **Tools > Console** are now **Simulate**; the Console is a pane in the Simulator (<kbd>Ctrl</kbd>+<kbd>`</kbd> toggles it, **Pop out** gives it a window).
  - Open the Console from **Simulate**.
- The simulation keeps running after the Simulator closes.
  - Stop it with **Stop** beside the main window's Test legend.
- A CLICK save or an edit to the workspace's `src/plc` no longer reloads the running simulation, and the Console's `autoreload` is refused.
  - Answer the Simulator's offer to write the new program, or type `reload`.
- While a simulation serves Modbus, the Data View editor drops its PLC connection and connects to the simulation (its title says Simulator); when the simulation stops, it disconnects and leaves the host at 127.0.0.1.
  - To reach a real PLC, stop the simulation and enter the PLC's address again before **Connect**.
- A workspace's `AGENTS.md` and `README.md` are now yours; pyrung's guidance is in `AGENTS.pyrung.md` and `README.pyrung.md`, and an older generated file is moved to `*.previous.md`.
  - Copy anything you had added from the `*.previous.md` file back into yours.
- Physical responses in comments take one key per value (`flasher_on=8ms, flasher_off=8ms`, `ramp_on=`, `approach_to=`) in place of `profile=`, and the build stops on a comment in the old form.
  - Run **Tools > Repairs > Upgrade Project**, review the rewritten comments on the Changed tab, and Sync.
- `clicknick-cli tag set-physical` takes one option per key, such as `--flasher-on 8ms --flasher-off 8ms` or `--toggle`, in place of `--profile`.
  - Update scripts that pass `--profile`; `clicknick-cli help` lists the options.
- `clicknick-cli` refuses `-s`/`--session` after the command.
  - Put it first: `clicknick-cli -s <session> <command>`.
- Sync and Discard clear the undo history.
  - Undo what you need before you Sync or Discard.

### Changed

- `link=` also takes a CLICK address such as `Y001`, or `~Y001` to follow a bit while it is OFF; tag names still work.
- The annotation dialog and the Simulator's link dialog offer every pyrung response (on/off delay, flasher, timed, toggle, ramp and approach), each with its own fields, and a response no longer needs a physical name: left empty, it is named after the tag.
- The status bar names the edit Undo and Redo acted on, and a paste that changes nothing is no longer an undo step.

### Fixed

#### Autocomplete and Tag Browser

- The overlay sends nothing to CLICK when you press Esc or click away, so an empty or half-typed name no longer lands in CLICK's field; Enter on an empty overlay just closes it, Esc keeps it hidden for that field until you move to another field, and it comes back when you click into the same empty field again.
- Multi-word overlay searches list matches in list order instead of a random one, a one-letter search lists only names containing that letter, a nickname used twice is listed once with its first address, sorting by nickname ignores case, and the tooltip is read from a row of the types the field accepts.
- The overlay's tooltip and the Tag Browser show Retentive and the initial value against the address's own default: the initial value only when a timer or counter is not Retentive, Non-retentive for a non-retentive counter, and no "Initial Value = 0" on a retentive DS or TD.
- The Tag Browser's Outline shows a nickname with a double underscore (`Tank__Level`) as spelled, instead of with one underscore too many, keeps leading zeros (`Pump01_Run` stays apart from `Pump1_Run`), lists array indices in numeric order (Pump2 before Pump10), and lists a nickname used on two addresses once for each.
- In the Outline, Rename changes the segment you picked and only the nicknames under it (not an unrelated nickname that starts with the same letters), leaves comments as they are, accepts a new name that starts with a digit, and is off for SC/SD entries and `__` groups; double-clicking a nickname that has others under it (`Tank_Pump1` over `Tank_Pump1_Run`) filters the Address Editor to it and the ones under it instead of hiding its own row; and double-clicking an SC or SD entry no longer leaves a stale filter, with those groups staying open when the list refreshes.

#### Address Editor and Sync

- Undo and Redo wait while you are typing in a cell, and text still being typed is kept when you Sync, close the window, replace the data or close ClickNick; a cell that won't commit stops the close.
- Fill Down over a timer or counter selection numbers only the rows of the first row's type, and Fill Down and Clone no longer copy block tags into the new rows' comments (a row that already has its own keeps it); after a Sync, check those comments in CLICK.
- Add Block over a selection with both a timer's T and TD rows (or CT and CTD) tags matching pairs, and Remove Block keeps the rest of the comment as it was (`<Pumps> Fill` becomes `Fill`, not ` Fill`); after a Sync, check those comments in CLICK.
- Editing a timer or counter comment's text no longer deletes the block tag on its TD/CTD (or T/CT) row, renaming a block renames the matching tags in place without adding spaces or moving text (`</Tanks> last` stays `</Tanks> last`), a rename never overwrites a tag you set in the same edit, changing only a block's colour no longer adds a half block tag to an untagged TD/CTD row, and Discard row changes on a T or CT row no longer changes its TD/CTD row's Retentive.
- With **Hide Used** ticked, the right-click menu, Discard changes and the character-limit tooltip act on the column you clicked, not the one beside it.
- The Init Value and Ret cells of SC, SD, XD and YD rows are read-only instead of showing an edit that Sync never writes.
- Ctrl+W closes one tab, in either editor only its own, instead of closing two and then raising an error, and a cloned tab shows block colors, errors and unsaved edits on every row and opens at the saved scroll position.
- Undo, Discard and edits update duplicate marks, so a stale "Duplicate" no longer blocks Sync; a row stops showing as unsaved once CLICK saves its value; changes CLICK writes right after a Sync are picked up; an edit that fails partway changes nothing; and sort by nickname and block colors stay current after edits, CLICK saves, Sync and CSV loads.
- Answering Yes to "Save before closing?" with duplicate or invalid nicknames refuses and closes nothing, as Sync does, instead of writing them to CLICK.
- Sync keeps what CLICK changed in its database since ClickNick last read it: change a comment in CLICK, then rename that address in ClickNick and Sync, and CLICK keeps its new comment.
- A system nickname CLICK wrote (SC, SD, X) no longer turns into an error that blocks Sync after a CLICK save or a Sync.
- Sync counts only the rows it wrote, so an edit CLICK's database already held no longer adds to "N tags synced" and a Sync of edits CLICK already had says there was nothing to write; Save to a CSV file counts the rows you changed (it counted every row in the file).

#### Nickname CSVs

- Loading a CSV over unsaved changes asks to save or discard first, and a cancelled or failed load leaves the loaded data as it was.
- A file that is not a nickname CSV, such as one without Address and Nickname columns, CLICK's own Address.csv, or one with a row whose Address is not a CLICK address, fails to load and says why, naming the line, instead of loading as an empty project that Save then overwrites.
- Nickname CSVs load when Excel saved them as "CSV UTF-8" (they loaded empty), keep XD and YD nicknames (`XD0u`, `XD8`) on their own addresses, keep comments' leading and trailing spaces, read Retentive written as `1`/`0` or `True`/`False`, and end lines with CRLF, as CLICK's export does.
- In CSV mode, Save says so when the file cannot be written, such as while Excel holds it open, and keeps your edits, and refuses to overwrite a file that changed on disk into one ClickNick cannot read.
- A Text initial value holding `,`, `"` or a space is quoted when ClickNick writes a CSV, and ClickNick reads it back unchanged; whether CLICK's import shows it unchanged is not yet checked (import such a CSV into CLICK and look at the Text address).
- Import from CSV imports each row of a nested block once, under the innermost block, skips nicknames, comments or first-scan values when the file has no column for them instead of clearing them, and accepts a file with no Nickname column.
- Save Copy of CLICK's Address.csv keeps addresses that have only an initial value or Retentive set.
- ClickNick reloads its data when the database or CSV is replaced by an older copy, such as a restored backup.

#### Dataview Editor

- A **New Value** that is not valid for its address (such as `abc` for DS1) is refused with the reason, whether typed, pasted or filled, instead of silently keeping the earlier value that Write would send; a typed one stays in the cell for you to fix.
- Text still in a Dataview cell, such as one you typed before switching to CLICK, is saved, written or asked about when you save, export, click **Write** or **Write All**, close a tab, the Dataview Editor or the data, or CLICK opens another project (it was dropped, and Write sent the old value); closing any of them offers every unsaved dataview for saving, untitled ones too (you pick their folder), and a save that fails or is cancelled closes nothing, and a failed one says why.
- Saving a dataview that CLICK (or another program) changed after its rows were read asks whether to save over it, reload it, or do neither; a reload that replaces unsaved edits can be undone with Ctrl+Z.
- The Dataview Editor stores addresses added from the Nickname box or the Tag Browser as CLICK writes them (`X001`, `XD0u`), finds nicknames whatever their case, and refuses text that is neither a nickname nor an address. Dataviews saved by an earlier ClickNick may still hold `X1` or `XD0U`: open them in CLICK and check each row shows its address.
- Ctrl+Z and Ctrl+Y undo and redo row moves and edits without the table and the saved file disagreeing, undoing an address change keeps its New Value, and a folder or block added from the Tag Browser is one undo step.
- The Dataview Editor no longer opens a .cdv file it cannot read, so it can't save a nearly empty file over it, and it writes unchanged .cdv files back byte-for-byte.
- The Dataview Editor and **Verify** use the DataView folder of the CLICK window ClickNick is connected to (with a second CLICK window open, or a folder left by a crash, they could show, save and check another project's dataviews).
- After the CLICK window closes with a CSV loaded from its temp folder, Open and Save As start in the folder you used last (or Documents) instead of the deleted temp folder, and Save on a dataview from that folder asks where to save.

#### CLICK windows and projects

- Closing ClickNick (the window's X or **File > Exit**) asks to save unsaved Address Editor and Dataview edits, and Cancel keeps it open (it discarded them).
- When CLICK saves under a new name or opens another project while you have unsaved address or Dataview changes, ClickNick asks whether to keep them for the new project, where Sync and Save then write them, or discard them (it discarded them); nicknames loaded from a CSV stay loaded with their edits, the question then covers unsaved Dataview changes (a Save wrote them over the new project's dataviews), and a Dataview Editor without them reopens on the new project's dataviews.
- After the connected CLICK window closes, ClickNick lists the other windows and waits for you to pick one while nicknames are loaded (it connected to the first one and closed the loaded CSV); **Stop** in the main window turns off only autocomplete, until you click **Start** or pick a window, and ClickNick still notices CLICK closing or opening another project (it kept the old project's editors, simulation and database); two CLICK windows with the same project name are listed with their PIDs, and the window list always shows the connected window.
- ClickNick finds CLICK's project in the Windows temp folder when that is not under `C:\Users\<your name>`, such as on a renamed or domain account or with TEMP moved (it could not locate the CLICK database).
- **Load Ladder CSV to Clipboard** and Review Changes copy only for the connected CLICK window and ask you to connect first (they used the first CLICK window found).
- A broken `%LOCALAPPDATA%\ClickNick\project-sidecars.json` no longer stops ClickNick connecting to CLICK.

#### Workspace and builds

- A build that reads while CLICK is saving no longer takes CLICK's short-lived `Scr23.tmp~RF...TMP` copy for a second copy of that program, and a CLICK save is noticed when its files get an older timestamp (a copied-back project, a clock change) or when it only deletes a subroutine.
- Opening another project in the same CLICK window no longer leaves its workspace unbuilt until ClickNick restarts; Open Temporary Workspace and the Workspace status update as soon as a build finishes; program analysis and AI tag lookups use the same nicknames as the generated code; switching CLICK projects no longer freezes the window; and "N tags synced - Save in CLICK" counts each tag once and no longer drops to 0 when the workspace rebuilds, such as after a Sync with repairs or setting up a workspace.
- A build that cannot finish writing the workspace, such as when a file in it is open in Excel, still fails but leaves `csv/` and `src/plc` both from the save before.
- A workspace `AGENTS.md` or `README.md` that is not UTF-8, such as one Notepad saved as ANSI, no longer makes every build fail.
- A workspace `pyproject.toml` ClickNick cannot read no longer makes a finished build report failure; Check Program reports it.
- **Export Workspace**, Workspace setup and Review Changes after a failed build say why instead of using the workspace of an earlier save.
- Choosing an existing workspace whose `src/plc` holds edits copies them to `backup/src/plc` before the next build regenerates it, and shows it as edited instead of Clean (`clicknick-cli restore` puts them back); Workspace setup no longer switches when both the current and the chosen workspace's `src/plc` hold edits, and names both folders so you can paste or discard one first.
- Choosing a workspace while ClickNick regenerates it is refused with a note to try again, as `clicknick-cli backup` and `restore` are; a backup or switch made then could hold files from two saves.

#### clicknick-cli and clicknick-rung

- `clicknick-cli` passes each argument as you typed it, so a value can hold quotes, backslashes or `;`, such as `set DS1 comment "Don't start"` (a command given as one argument is split at spaces and at `;` outside quotes), and accepts options as separate words (`rung apply main --select r3`, `tag set-physical ... --on-delay 50ms`) instead of refusing them.
- `clicknick-cli tag apply` keeps a comment's text and block tag and changes only the annotations you changed in `tags.py` (it replaced the comment with them alone, such as `[uom=mm]`), and no longer stages `[external]` on analog input channels you did not edit. Comments that an earlier `tag apply` cut down to their annotations keep only the annotations in CLICK: put their text back by hand.
- `clicknick-cli get`/`set` find tags by the names in the workspace, also when the analysis of a CLICK save failed.
- `clicknick-cli prompt-save` answers at once while ClickNick shows the reminder, instead of holding every other command until the dialog is closed.
- `clicknick-rung load` on a ladder CSV with no rungs says so instead of crashing.

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
