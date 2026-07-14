# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Features

- **Check Program** — a new Tools > "Check Program..." window reports pyrung's static validation findings as compiler-style diagnostics with a source frame, severity-coloured caret, and fix hint, driven by the validation registry so new rules appear automatically.
- **Program analysis filters** — the Address Editor filter box accepts `input:`, `output:`, `pivot:`, `isolated:`, `upstream:Tag`, and `downstream:Tag` prefixes, which compose with existing text filters.
- **Interactive pyrung Console** — a new Console window runs simulations against the open project, with slot-aware autocomplete, live streaming of `how()` progress, and a button to open the `pyrung_project` directory.
- **Simulation Server** — a Start/Stop toggle launches the pyrung simulation backend in the background, seedable from a CSV snapshot, and hot-reloads when project `.py` files change instead of needing a manual restart.
- **Rung preview** — a preview window shows coloured unified diffs of pending rung changes with per-group "Copy to Click" export and a Copy All button for a whole program; `rung preview` with no argument scans main plus all subroutines.
- **Agent CLI (`clicknick-cli`)** — the IPC CLI grew into an agent-facing interface with `tag`, `rung`, `info`, and `help` commands; `tag apply` pushes `tags.py` edits into the Address Editor as one batched unsaved edit, and `unused` returns the next free address(es) in a bank from one or more address hints.
- **Right-click annotation editor** — comment-field annotations (flags, choices, min/max, unit of measure, physical/link) can be edited in a structured dialog with hover tooltips instead of hand-typed bracket syntax.
- **Add Block dialog** gained an Advanced section for `:block`, `:named_array`, and `:udt` structured block kinds, with live preview and row-count display.

### Fixed

- Console autocomplete now reads pyrung's published command grammar (`pyrung.dap.grammar`) instead of parsing its help text, so it completes multi-target `how A, B` (with or without a space after the comma), offers tag names inside `avoid`/`via` clauses — which never worked before — and suggests the `avoid` and `via` keywords themselves once a target is typed. Older pyrung versions without that module fall back to the previous help-text parsing.
- Importing a nickname CSV no longer fails outright with `cannot assign to field 'nickname'`.
- Unchecking a block in the import dialog now actually excludes it — previously a tagged block sitting between untagged rows was imported anyway, under the wrong block's merge options.
- Rows no longer show as **Changed** with no visible edit, and are no longer rewritten to the database on save, when a value is written back unchanged (re-typing the same text, or importing a CSV that already matches the project).
- Editing a value back to its original now clears the row's **Changed** marker instead of leaving it flagged.
- A blank initial value and `0` now count as the same default on numeric addresses, so importing a Click CSV export no longer marks every numeric address changed; TXT still treats `0` as real content.
- A CSV that reuses a block name no longer has one block's import options clobber another's.
- Nickname changes made externally in Click now reliably reach the Address Editor and Overlay — a locked or failed MDB read no longer drops the change permanently, and editing only a comment no longer freezes the old nickname back over later refreshes.
- Console autocomplete now completes `~`-prefixed tags, respects your Filter Mode setting rather than always matching case-insensitively, and no longer scrolls the input, misplaces the cursor, or floods the dropdown on a bare space.
- Opening the Console on a project with no saved `Scr*.tmp` files now tells you to save in Click Software first instead of opening a Console that cannot find the program.
- Running several ClickNick instances at once no longer makes them fight over a single shared simulation session.
- Stop now actually stops the simulator when it is paused at a breakpoint instead of restarting it.
- Rung preview raises and focuses itself on open, attributes changes made just before a rung marker to the correct rung, and can copy subroutines again.
- Rebuilding the analysis project no longer wipes its virtual environment and lockfile or leaves stale files behind.
- Reconnecting or switching projects no longer leaks background watchers, Modbus connections, or orphaned simulator processes.

### Changed

- The import dialog's **Init Val** and **Retentive** columns are now a single **First Scan** column: the two are imported together, so importing a retentive setting can no longer silently shadow an initial value the program relies on.

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
