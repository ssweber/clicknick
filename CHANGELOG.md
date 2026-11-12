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

- In the Address Editor, Undo and Redo wait while you are typing in a cell, and Sync and closing the window keep what you typed.
- Fill Down over a timer or counter selection numbers only the rows of the first row's type, and Fill Down and Clone no longer copy block tags into the new rows' comments (a row that already has its own block tag keeps it); after a Sync, check those comments in CLICK.
- Add Block over a selection that includes both a timer's T and TD rows (or CT and CTD) tags matching pairs, and the Tag Browser's rename changes nicknames only, leaving comments as they are; after a Sync, check the timer or counter block comments in CLICK.
- A cloned Address Editor tab shows block colors, errors and unsaved edits on every row, and opens at the saved scroll position.
- CLICK v4 projects work: autocomplete fits its instruction dialogs, and Simulate and the workspace read its hardware and PLC name.
- Check Program, Preview Changes and the simulation no longer show Windows' busy cursor while they start.
- Unsaved-change tracking is reliable: Undo, Discard and edits update duplicate marks so Sync isn't blocked by a stale "Duplicate", rows stop showing as unsaved once CLICK saves the value, changes CLICK writes right after a Sync are picked up, and an edit that fails partway changes nothing.
- Sort by nickname, block colors, the Dataview editor, the window title and Workspace details stay current after edits, CLICK saves, Sync, CSV loads and workspace changes, and the Dataview editor writes unchanged CDV files back byte-for-byte.
- Loading a CSV over unsaved changes asks to save or discard first.
- Program analysis and AI tag lookups use the same nicknames as the generated code, switching CLICK projects no longer freezes the window, and the "tags synced" count counts each tag once.
- Opening another project in the same CLICK window no longer leaves its workspace unbuilt until ClickNick restarts, and Preview Changes now updates its comparison when CLICK's program changes.
- Open Temporary Workspace and the Workspace status update as soon as a build finishes, instead of waiting for something else to refresh the window, such as opening the Simulator.

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
