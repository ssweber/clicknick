# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

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
