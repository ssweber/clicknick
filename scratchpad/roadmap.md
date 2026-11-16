# ClickNick roadmap

The one live statement of what ClickNick does next. Written 2026-11-15 from the planner's handoff, this
session's reply to it and Sam's rulings on that reply. Cross-repo items and the shared rules are in the plan,
`ssweber.github.io/plan/README.md` (its numbered "Cross-repo work" items are cited below as plan 1-6).

How to use it:

- When an item lands, delete it. This file lists what is still to do.
- Each item says what it needs: **CLICK** (the CLICK software), **PLC** (a real PLC), **Sam** (his judgment
  or an action only he can take), **waits on X** (another repo's release), or **nothing** (refactor only).
  Work that needs nothing is never queued behind work that needs Sam.
- Branches go into an always-releasable `main`; there is no `dev`. Sam squash-merges. A session stops at
  "CI green, ready to merge", and pushes or opens PRs only once Sam has said so directly.
- A branch that needs an unreleased pyrung, laddercodec or pyclickplc is tested locally against the sibling
  checkout (`make install-dev`) and merges after that sibling's release.
- Never touch Sam's own CLICK windows, temp folders or SC_.mdb. The sandbox runner (item 4) works only on a
  CLICK it started itself.

## Order

1. Housekeeping (nothing)
2. ssort out, tests into CI (nothing)
3. The bob plugin (done)
4. CLICK runner (built: `devtools/click_runner.py`; next its early jobs), and the user checks it or a mock can automate (nothing)
5. ConnectionSession owns the window and project (done)
6. Split ClickNickApp (done)
7. Onto pyclickplc's readers (done)
8. Onto pyrung's named imports (waits on pyrung's deletions release)
9. The undecoded marker (waits on laddercodec, pyrung)
10. Recording, ClickNick side (waits on pyrung's recording core and one door)

Items 5 and 6 come before 10, because recording adds more per-project state. Items 8 and 9 fit in whenever
their sibling release is out.

## 1. Housekeeping (nothing)

- `dev` goes: it holds the same tree as `origin/main` (0.24.0 was squash-merged). Done locally
  (2026-11-15): local `dev` and `bob/train4` deleted, local `main` reset to `origin/main`. Deleting
  `origin/dev` is a push: ask Sam.
- Arc folders under `../clicknick-wt/buildbot/jobs/` can go once this file holds their open items. They are
  here: the user checks (below), and two leftovers from the sweep ledger:
  - Tests and docstrings that still say "offline console".
  - A review note on `bob/followups` (landed as ba39f22): `-s/--session` and `-h` given after the command now
    reach the server as command words, so `clicknick-cli get DS1 -s MyProject` goes to the default session.
    Undocumented either way. Decide whether options after the command are parsed, and test it.
- Memory: the user-checks memory points at the sweep folder; point it here. Drop memories this file
  replaces.
- Issue #36 is open.
- Docs deploy on a release, not on every push to `main`: `docs.yml` builds on pull requests and deploys
  on `workflow_dispatch` from `main`, building the `ref` input (default: the latest release);
  `publish.yml` starts it with the release's tag. Scripts the build runs (`.github/scripts/`) come
  from that tag, so a fix to them reaches the site with the next release.

## 2. ssort out, tests into CI (nothing)

- One small commit, no reorder pass: drop ssort from `devtools/lint.py`, the dev dependencies and
  `[tool.ssort]` in `pyproject.toml`, the version line in `.github/workflows/ci.yml` and the `make lint` line
  in `AGENTS.md`. Files are reordered only when they become a problem or are being rewritten anyway.
- CI already runs on `windows-latest` (Python 3.11 to 3.13) but only lints. Add `make test` (the 1,941 tests
  take about 2 minutes). CI installs the pinned PyPI releases, not the sibling checkouts. On the first run,
  watch the tests that start pyrung's DAP subprocess or bind Modbus port 502.

## 3. The bob plugin (done)

The BOB tooling is the bob plugin (github.com/ssweber/bob): the skill, the three agents, the
PreToolUse hook and the bounded runner (`run.py`: timeouts, memory cap, targeted slots, `ps`, `reap`,
`worktree new/rm/list`). There is no merge queue here; CI is the gate. ClickNick keeps two files of its
own: `.claude/bob/config.toml` and `.claude/bob/profile.md`. A fault in the tooling is fixed once, in the
plugin, through its own pull request.

Once per clone: `claude plugin install bob@bob --scope project` (the `bob` marketplace is added once per
machine: `claude plugin marketplace add ssweber/bob`).

## 4. CLICK runner spike (CLICK, Sam)

Plan 4. A runner in `devtools/` that drives CLICK unattended, so work that needs CLICK no longer needs Sam.
laddercodec and pyrung call it as a command. It leans on the clipboard (`ladder/clipboard.py` already reads
and writes CLICK's format) and ClickNick's window code, not on pixel positions. It does not replace readings
from a real PLC.

**Status (2026-11-15):** built as `devtools/click_runner.py` (`paste CSV --out DIR`, `record --out DIR`; its
docstring has the rules and the result format). Live on Sam's desktop it pasted 1, 61 and 301 rungs into its
own CLICK v4 connected to the conformance PLC, ran Syntax Check, saved, decoded the save back to CSV and
matched every rung (a 301-rung paste freezes CLICK about 16 s; the whole run took 39 s). It drives CLICK by
posted commands only, no keystrokes or pixels, and no command that reads the project from the PLC or writes
one into it can be sent. The PLC login is `admin` (prefilled) / `123click`, deliberately not secret. Next: the
early jobs below, and subroutines (pasting into one needs its dialogs recorded first, `record`).

**Where it runs (Sam, 2026-11-15, replacing the plan's Sandbox-first rule):** on the CLICK installed on Sam's
desktop, while he is away, as long as it is deterministic. Windows Sandbox is the fallback, and is needed only
if the desktop cannot work.

**Rules that make it deterministic and keep Sam's work safe:**
- It refuses to start while any CLICK window is open, and touches only the CLICK it started.
- Each step waits for a window or a file to appear, with a timeout, never for a fixed time. Any unexpected
  dialog stops the run, leaving a screenshot and a log, and closes the runner's CLICK without saving.
- It never writes to the PLC. It connects only so that the new project takes that PLC's hardware.

**How CLICK v4 is driven (from Sam):**
1. Start CLICK v4. When it prompts, connect to the only CLICK PLC on Sam's network: the conformance runner.
   Connecting is what makes the project match that PLC's hardware.
2. When it asks whether to read the project from the PLC, answer No. The open project is then
   `NewProject{n}` with an empty main program, so a probe that needs only main is quick to run.
3. To paste a test: select the first rung number, send paste, wait until the rungs appear.
4. Press "Syntax Check", then save the project. That gives the Scr*.tmp files, and from them the CSVs.

**Known and unknown:**
- The screen stays unlocked while Sam is away (Sam, 2026-11-15). The runner still checks, and refuses to start
  on a locked desktop: synthetic input and the clipboard do not reach one.
- The first save of `NewProject{n}` opens a Save As dialog that needs a path typed in (the runner fills it).

**Sandbox fallback:**
- Two probe files were written 2026-11-13 in `%TEMP%\clicksandbox` and never run. `click-probe.wsb` maps the
  installer folder read-only and an output folder, with networking off. `bootstrap.cmd` records the
  InstallShield answers (`/r`, `setup.iss`) on the first run and installs silently (`/s`) after that. Move both
  into `devtools/`, with paths as arguments, if the fallback is needed.
- Needs from Sam then: enable Windows Sandbox and reboot, and run the installer by hand once inside it.
- Inside the Sandbox, CLICK may not find the PLC: the Sandbox's network sits behind NAT. Sam's idea is to keep a
  copy of the conformance PLC's Project.ini and put it in place of the new project's. That may work: CLICK
  picked up a PLC name ClickNick wrote into Project.ini (`write_plc_name`). Whether it also takes the hardware
  (modules, I/O) from there, and when it reads the file, is the first thing to test. The other way is a blank
  `.ckp` saved once for that PLC, which the runner opens.

Early jobs once it works: what CLICK writes, and in what order, on Open, New and Save As (user check Q2 below);
what CLICK turns constants such as `005`, `+5` and `0ffh` into (for laddercodec); the three small checks in the
plan's "Only Sam can do these" (leading zeros and spaces in an address, a bare space as a Text initial value,
whether CLICK strips spaces from nicknames and comments). The two answers that bear on pyclickplc's reader go
to Sam.

### 4b. User checks a mock can automate today (nothing; wording goes to Sam)

`devtools/record_simulator_gif.py` drives the real Simulator, Console, SimulationSession and pyrung with no
CLICK: it exports a program to CLICK CSVs and builds the workspace the way a build does. In the same way, a
"CLICK save" becomes regenerating the mock project and publishing it. About 30 of the open checks below can be
automated like this, as opt-in scripts or tests:

- the Simulator section, except "With pyrung 0.15.2 installed"
- unassigned I/O
- the planned-reload items
- the Dataview small fixes, against the simulator's Modbus
- the Tag Browser double-click
- CSV Save counts and Text quoting import

What a script cannot judge is the wording: collect each notice into one page for Sam to read in one sitting.
Not without CLICK: the overlay, project change and Save As, Review Changes paste steps, and Sync racing a
CLICK save.

### 4c. The editor's answers for the rule table (done for Math, Copy and Out)

`click_runner.py try devtools/editor_cases.json --out DIR` opens CLICK's Math, Copy and Out dialogs from the
ribbon's commands (50030, 50040, 50010), fills them, presses OK and records whether CLICK accepts each case or
which error box it shows (`OBJ-...`). An accepted one is checked with Syntax Check and deleted again. The cases
cover rows A1 to A10, B1 to B6 and B8 of pyrung's and laddercodec's rule table, with controls that tell a
refusal's reason apart (for example, X and Y pack only into DH). A run of 58 cases takes about 5 minutes,
mostly Syntax Checks. Left: the Receive dialog (B7), section D, and the rows only Sam can answer. E1 is not in
a new project's SC_.mdb; CLICK's `PLCType.ini` names SD21 `_RTC_Month`.

## 5. ConnectionSession owns the window and project (done)

The session opens on connect, before the database loads, and holds the window, the load token, the workspace
pairing, the connection watch, the popup and the Workspace setup window; `_close_session` is the one teardown.
The Workspace setup window now closes when CLICK's window closes (Sam, 2026-11-15). The project-info window
stays on the app: it holds nothing of the connection and opens with nothing connected.

## 6. Split ClickNickApp (done)

The Workspace group, its menu entries and Workspace setup are `WorkspaceController`
(`workspace_controller.py`). Listing CLICK windows, connecting, the database load, the project change, the
watch tick, the popup and Start/Stop are `ConnectionController` (`connection_controller.py`). `app.py` went
from 3,017 lines to 1,883. Widget building stays on the app, and so do `_open_data` and `_close_data`, which
write `_data`'s one home. Left on the app, each a candidate for a later split: the Tools and Repairs menu
actions, launching Review Changes and Compare with, `_export_pyrung_project`, and the unused
`_check_odbc_drivers_and_warn`.

## 7. Onto pyclickplc's readers (done)

Plan 2. ClickNick reads and writes nickname CSVs with pyclickplc's `read_csv` and `format_csv`
(`CsvDataSource`), so one library writes the workspace's `nicknames.csv` and reads it for pyrung. It keeps
`_write_file` (the in-place write that keeps a Hidden file Hidden and names the Excel lock) and converts
`AddressRecord` to `AddressRow` at its boundary; unifying the two models is not part of this.

What it changed:
- A Text initial value that CLICK exports bare as a comma or a double quote now loads; a save writes it, and a
  space, quoted, so it reads back as written.
- A file with a bad Address, a wrong Data Type or extra cells is refused by ClickNick as by pyrung, naming the
  line: in Review Changes the nicknames row says so. Whenever pyrung cannot convert the folder, the diff says why
  (`BundleSources.error`). A nickname used twice still loads in ClickNick (the store flags it) though pyrung
  refuses the file.
- `validate_nickname_format` and `detection/window_mapping.DATA_TYPES` are gone: `validate_nickname` calls
  pyclickplc's, and the combobox takes its prefixes from `BANKS`.
- `validate_click_name`, `read_plc_name`, `write_plc_name` and `iter_address_slots` come from pyclickplc 0.7.

What stays in ClickNick (Sam, 2026-11-15): its own `read_mdb_csv` for CLICK's `Address.csv`, which pyclickplc's
reads differently, and `convert_mdb_csv_to_user_csv`, which now writes through `format_csv`. The names for
unassigned I/O slots in `sim_hardware.py` stay too. The Text quoting import is an open user check (4b).

Left over (nothing): ClickNick's `read_mdb_csv` reads a blank DataType as BIT, not the bank's type as the
database path does (`mdb_operations`); nothing shows CLICK writes one, but if it did, Save As CSV would write a
file ClickNick then refuses.

## 8. Onto pyrung's named imports (waits on pyrung's deletions release)

Plan 3. ClickNick imports these internal paths today. Move each onto pyrung's named home, and add a test that
fails when one disappears:

- `pyrung.click.tag_map`
- `pyrung.core` (`physical_response.py`: PHYSICAL_KEYS, FeedbackType and more)
- `pyrung.core.program.Program`
- `pyrung.core.analysis.build_program_graph`
- `pyrung.core.analysis.pdg`
- `pyrung.core.validation` and its `config`, `registry`, `report`, `stuck_bits` and `ordered_rules`
- `pyrung.dap.live`, `pyrung.dap.grammar`, `pyrung.dap.protocol`, `pyrung.dap.adapter` (some only in tests)

`dap_service.py` matches on a pyrung error string; that goes with the one door (item 10).

## 9. The undecoded marker (waits on laddercodec, pyrung)

Plan 2, last bullet. laddercodec replaces a rung it cannot decode with a marker rung: the comment
`UNDECODED: rung N, row R: <error>` and one `Undecoded` instruction that acts as End (Return in a subroutine).
`encode()` refuses the marker. On ClickNick's side:

- Drop the empty stand-in rung ClickNick puts in today.
- The Simulator runs up to the marker instead of refusing to run. `_workspace_problem` stops refusing "a rung
  ClickNick cannot read". Show a notice that is hard to miss.
- Check Program lists the marker.
- Review Changes can never paste the marker back, since `encode()` refuses it. Check the whole-program copy
  path that keeps CLICK's rungs, and the legacy-encoding paths.

## 10. Recording, ClickNick side (waits on pyrung's recording core and one door)

Plan 1, step 4. pyrung, ClickNick and the VS Code extension release together.

- **One door:** the panels send console text for every action that changes state (switches, analog values,
  forces, mode, step, speed, links). Reads stay structured requests. Delete ClickNick's structured requests for
  those actions, its `echo` of panel actions, and the Console pane's `;` split (`ConsolePanel._submit_command_text`,
  and the `autoreload` and `reload` refusals that rely on it). The program write stays `pyrungReload` with its
  carry plan, and launch and terminate stay structured (`scratchpad/visual-simulator-design.md`).
- **Recordings on every CLICK save:** after the build publishes, off the Tk thread (on the build worker), and
  only in a permanent workspace.
- **Right-click "Assert this".**
- **Setup prompt:** starting a recording opens the workspace setup, so recordings land in a workspace that
  persists. Declining means no recording. A window that was never saved has no Project.ini and so no PLC name,
  and the prompt says to save in CLICK first.
- **Names and renames:** recordings hold names (the nickname, or the display address where there is none).
  At the build that first carries new names (a Sync or a CLICK save, whatever made the rename; never at edit
  time), ClickNick builds the old-to-new map from the old and new address-to-name maps and pyrung's rename
  function rewrites the recordings, before they run. A name that still exists is left alone, so a swap rewrites
  nothing. A name that is gone becomes whatever now names its old address (the display address if the nickname
  was deleted). `plan_carry` already builds these maps.
- **Where recordings live:** a permanent workspace is `<chosen folder>/<PLC name> Workspace` with a
  `.clicknick.toml` sidecar. ClickNick finds it through `%LOCALAPPDATA%\ClickNick\project-sidecars.json`, by
  the PLC name in Project.ini. A rebuild replaces only `csv/`, `src/plc`, `nicknames.csv`,
  `project_to_csv.py`, `run.py`, `AGENTS.pyrung.md` and `README.pyrung.md`, and deletes `csv_output/`.
  Anything else is seeded only when missing, so a recordings folder survives rebuilds and the mirror copy.
  The temporary workspace (`CLICK (hwnd)\pyrung_project`) is deleted when the window closes.
- Remove the Console pane's refusals of `record` and `replay` (a3f84e1, f1b1471) once ClickNick's write and
  name mapping cover them.

## Open user checks

Moved from the sweep arc's `USER-CHECKS.md` on 2026-11-15. None blocks a release: before a tag, Sam gets a short
smoke test, and what the rest find goes into bugfix releases. Items marked (4b) a mock can automate; (runner)
waits on the CLICK runner (item 4). A check that is walked or automated is deleted here.

### Questions only CLICK can answer
- Q2 (runner): does CLICK rewrite SC_.mdb on File > Open and Save As, and before or after the window title
  changes? (How soon kept edits are checked against the new project's database.) Sam: SC_.mdb changes every
  time you edit in CLICK's Address Editor.
- Q6: after deleting all rungs, empty rungs are on screen. Is one of them selected for Ctrl+V, or must the step
  wording say to click the first empty rung?
- Q7: can SC_.mdb hold a nickname or address comment with a space at either end (typed in CLICK, or from
  CLICK's own CSV import)? ClickNick trims one on load as an unsaved edit ("Trim spaces"), so on a yes the next
  Sync writes the trimmed value into CLICK. The recorded `tests/SC_.mdb` and `NicknameExport.csv` hold none.

### Address Editor and store
- Fill Down / Add Block T1..TD5, then Sync.
- Block rename over T/TD, then Sync.
- Colour-only change on T with an untagged TD.
- CLICK comment edit + quick rename in ClickNick + Sync.
- Remove Block leaves 'Fill' (no leading space).
- Edit two nicknames, let CLICK save one first, Sync -> "Synced 1 changes", main window "1 tags synced".
- Edit a nickname, save the same in CLICK, Sync -> "CLICK already had these changes; nothing to write."
- (4b) CSV Save reports the number of rows edited.
- (4b) CSV TXT quoting import: a quoted comma, double quote and space, and a Text value of a tab, which
  pyclickplc's writer writes bare (`test_a_txt_value_with_a_tab_or_edge_space_is_written_bare`).

### Tag Browser, Dataview, Overlay
- x1 / XD0u from the Tag Browser.
- Dataview save-over prompt (CLICK wrote the .cdv since load).
- Overlay: Esc, click away, click back, Enter on a nickname, empty Enter in the Address Picker.

### App lifecycle
- Stop, then open another project in CLICK -> monitoring stays off.
- CSV loaded, then Save As in CLICK -> CSV stays loaded.
- Close ClickNick with unsaved edits -> prompt; Cancel keeps it open.
- Start ClickNick with CLICK open -> Select Window box shows the project.
- Unsaved Address Editor edits, CLICK File > Save As -> "Project Changed": Yes, Sync -> edits in the renamed
  project (Address Picker); open editor shows the new project name.
- Unsaved edits, open another project in the same CLICK window -> No -> new project loads clean, its nicknames
  untouched.
- Unsaved Dataview edit + Save As -> one Keep question -> Yes, then save the Dataview -> .cdv under the renamed
  project.
- Unsaved Dataview edit + File > Open another project in the same window -> No -> the other project's .cdv
  untouched.
- A cell mid-edit with CLICK focused, then change project in CLICK -> the Keep question still appears.
- Two CLICK windows, connected to the second -> Load Ladder CSV to Clipboard pastes in the second; not
  connected -> refuses.
- Save As with unsaved edits, Keep -> open Address Editor and Dataview titles show the new name; an `input:`
  filter works once the new build finishes.

### Live CLI and workspace
- `clicknick-cli tag apply` + Sync on a row with block tag + text -> comment text and block tag kept.
- `tag apply` on an unedited workspace leaves analog inputs alone (no `[external]`).
- Workspace setup refuses when both workspaces' src/plc hold edits, naming both.
- `clicknick-cli get/set` by workspace tag names.

### Review Changes
- Whole copy with no comparison: wording says delete the program's rungs first; refuses to copy while
  disconnected.
- Re-export that changes already-pasted rungs -> program copied whole.
- Whole program with a skipped legacy-encoded rung -> stepped through instead.
- Zero-rung program under Whole program: delete all its rungs in CLICK, Next -> matches the folder.
- Unsaved paste then a re-export taking it back: delete all rungs + paste whole -> CLICK holds the new export.
- Paste a step, Sync in ClickNick, back to Review Changes -> goes on from the paste.
- Next without pasting, then save in CLICK -> that program is a step again.

### Simulator (all 4b, a "save in CLICK" being a regenerated mock project)
- Save in CLICK while the simulation runs -> notice; nothing changes until you choose.
- In RUN: RUN Time Edit keeps values/timers/forces; Stop and Write keeps retentive, clears the rest, keeps
  forces.
- In STOP: Write.
- Edit workspace src/plc -> "ladder source changed" notice with the same choices.
- A save pyrung can't convert -> old program keeps running, notice gives the reason.
- Restart -> back to power-on values (or the PLC data file), switches/forces/bench links and mode restored.
- Console unforce/restore during a CLICK save build are kept.
- In STOP, Write leaves the simulation in STOP.
- Console: `reload` works (RUN Time Edit in RUN, Write otherwise); `autoreload` is refused.
- RUN Time Edit after a save that renames a tag: that tag's value starts over (pyrung keys values by name).
- Write while a bench on-delay link is timing -> timing carries on.
- Console commands typed right after `reload` -> refused while writing, then kept.
- CLICK save with a rung ClickNick can't read while the sim runs -> Write refuses, names the rung, old program
  keeps running. (Changes with item 9.)
- Move a nickname in CLICK onto an input that has its own bench change, then Write -> notice lists the dropped
  one; the moved link is kept.
- Rename a linked input while its on_delay runs (a bench link, and one saved in the input's comment), save in
  CLICK, RUN Time Edit -> the delay carries on; the notice reads well.
- Run a Console command right before RUN Time Edit -> the write waits or the command is refused, nothing lost.
- Close the Simulator while a Console command runs, reopen it, save in CLICK -> the Write buttons appear.
- Console `run 10m`, close the Simulator, reopen, save in CLICK -> banner shows the Console line, pane shows
  Stop; after Stop the Write buttons appear.
- "CLICK saved a new program" after Stage nicknames + Sync + paste + CLICK save: one Write click is enough now
  (fixed in 418a132); check the wording of any second notice.

### Simulator unassigned I/O (4b)
- Program using X101-X108 and Y101-Y108 with no module -> one dashed 'Expansion 1 - unassigned' card in order;
  X201 only -> input placeholder between real cards; switches drive, LEDs show; switch positions kept when a
  module is later configured.

### Simulator planned reload (4b)
- Write in STOP -> stays in STOP; the next RUN clears non-retentive values.
- With pyrung 0.15.2 installed: a write is refused with the "pyrung 0.16.0 or later" notice and offers Restart.
  (Needs a second environment.)
- A link saved in a comment: rename its nickname, save, write -> its timing carries on. Swap two linked
  nicknames together with their comments -> each keeps its own state. Move only the nickname (comment stays) ->
  the link stays on the comment's address. Check the notice wording each time.

### Temp folder and Dataview
- Two CLICK windows open -> Verify checks only the connected window's .cdv files (listing already passed).
- CSV nicknames loaded + a Dataview edit, File > Open in CLICK -> the question appears; Yes keeps edits and
  Save writes into that window's DataView folder; No reopens the editor on the new project's dataviews, nothing
  saved.
- TMP/TEMP redirected to an 8.3 short path -> ClickNick still finds SC_.mdb and the DataView folder (the long
  path passed).
- CSV nicknames loaded, type in a Dataview cell without Enter, File > Open in CLICK -> the question appears.
- Save As in CLICK with kept database edits -> the Dataview Editor stays open with its tabs and Modbus
  connection.
- Type in a Dataview cell, switch to CLICK and back: closing the tab and the window each ask; Ctrl+S writes the
  typed address to the .cdv; closing ClickNick asks about the Dataview.
- (4b) Simulator or PLC connected: type 100 in DS1's New Value, click Write All without Enter -> 100 is written.

### Small fixes (4b unless noted)
- Dataview: type abc in DS1 New Value + Enter -> warning, cell reopens with abc; Write with the cell open sends
  nothing; clicking another cell while it is open does not loop the warning; Esc restores the old value.
- CLICK window closed, CSV loaded from its temp folder -> Dataview Open/Save As start in the last-used folder or
  Documents. (CLICK)
- Tag Browser: double-click Tank_Pump1 (with Tank_Pump1_Run, Tank_Pump10) -> filter tree:Tank_Pump1 shows only
  Tank_Pump1 and Tank_Pump1_Run.
- Simulator: run 10m, close, reopen, Pop out works.
- Dataview: rejected New Value (abc) open, click another tab -> warning shows, no stuck editor.
- CLICK window closed (temp folder deleted), Save on a tab opened from its DataView folder -> asks where to
  save. (CLICK)

### Leftovers
- Save the PLC data file while a RUN Time Edit is in flight -> the simulation restarts from the data file right
  after "OK - the simulation runs the new program." (Hard to hit by hand; a mock can time it.)
- (4b) Dataview: paste a column with some invalid New Values (and Fill one invalid value over a selection) ->
  valid cells applied, one "Invalid New Value" warning listing the rejected cells.
