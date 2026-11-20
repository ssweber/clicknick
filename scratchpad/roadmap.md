# ClickNick roadmap

The one live statement of what ClickNick does next. Cross-repo items and the shared rules are in the plan,
`ssweber.github.io/plan/README.md`. Its numbered "Cross-repo work" items are cited below as plan 1 to 7.

How to use it:

- When an item lands, delete it. This file lists what is still to do.
- Each item says what it needs: **CLICK** (the CLICK software), **PLC** (a real PLC), **Sam** (his judgment
  or an action only he can take), **waits on X** (another repo's release), or **nothing** (refactor only).
  Never queue work that needs nothing behind work that needs Sam.
- Branches go into an always-releasable `main`. There is no `dev`. A session pushes its branch, opens the PR
  and squash-merges it once CI is green and a fresh reviewer has passed the last commit. Only Sam tags and
  releases.
- Test a branch that needs an unreleased pyrung, laddercodec or pyclickplc in its own worktree venv, with the
  sibling's `main` installed there. It merges after that sibling's release.
- Never touch Sam's own CLICK windows, temp folders or SC_.mdb. The runner (item 4) works only on a CLICK that
  it started itself.

## Order

1. The next release, 0.26.0 (waits on laddercodec, pyrung and pyclickplc). The steps are below.
2. The CLICK runner's waiting jobs (CLICK). Sam ruled on 2026-11-17 that they come ahead of recording.
3. Recording, ClickNick side (item 10; waits on pyrung's recording core and console commands for every
   change).
4. Small follow-ups (nothing), whenever a branch touches their file.

## The next release, 0.26.0

The ClickNick session runs these steps. Its build notes for them, with the sibling commits that each branch
was tested against, are in `../clicknick-wt/buildbot/jobs/next-pins/`.

1. Move onto laddercodec's and pyrung's joint release: items 8 and 9 below. The branch is
   `bob/laddercodec-next`, built against laddercodec's and pyrung's `main`. It merges once both are released,
   with the pins moved to the released versions.
2. Decide the validation question for cp1252 (pyclickplc 0.11.0 is in). ClickNick's Address Editor still
   accepts a nickname, comment or initial value with a character cp1252 does not have, and the write then
   refuses it. The runner has not yet checked what CLICK shows and exports for such a character (pyclickplc's
   roadmap item 2). When it has, pyclickplc decides whether its validators refuse the character, and ClickNick
   follows. Also open: ClickNick reads CLICK's Address.csv (`read_mdb_csv`) as UTF-8 with a BOM. No fixture
   shows that encoding for a non-ASCII nickname, so a runner check of Address.csv would settle it.
3. Read the CHANGELOG from v0.25.0 against what merged, and write the summary.
4. Sam's smoke test of the release candidate, then his tag. ClickNick goes last of the four repos.

## 1. Housekeeping (nothing)

- The arc folders under `../clicknick-wt/buildbot/jobs/` can go once this file holds their open items. Keep
  the runner's job folders, because the other repos cite their answers.

## 4. CLICK runner (CLICK)

Plan 4. `devtools/click_runner.py` drives CLICK v4.00 unattended, so work that needs CLICK no longer needs Sam.
Its docstring has the modes, the rules and the result format. It runs on the CLICK installed on Sam's desktop
while he is away, and only on a CLICK that it started itself (Sam, 2026-11-15). Sam approved every runner run
on 2026-11-18, until he writes "StopRuns". The runner never writes to the PLC. A job tool that writes a
project to the conformance PLC needs Sam's go for each run. The PLC login is `admin` (prefilled) /
`123click`, which is deliberately not secret.

The runner imports laddercodec 0.4.0's names. When the main checkout's venv holds laddercodec's `main`
(`make install-dev`), the runner's decode step fails on the renamed names until `bob/laddercodec-next`
merges. A job that uses `--keep` or `--wire` then decodes with a script of its own.

Jobs waiting, from the plan's item 4 and the other sessions:
- The dialog grids, in Sam's order of 2026-11-17: Fill mode, then the Timer, Counter, Shift, For and Drum
  dialogs, then what is left of the full Math, Copy and Out grids, and the Address Picker's Pickup Mode lists
  for the other fields. A Pickup Mode case takes about 4 s.
- What CLICK writes on File > New, and when its title changes (part of Q2). New Project (32771) is not on the
  allowlist yet.
- pyclickplc's: what CLICK shows and exports for a nickname with a character that cp1252 does not have.
- laddercodec's: Fill with text or a bare number, a character above U+FFFF into TXT, a pointer on both sides,
  the Real edge and digits in Math, and PLC runs B and C. Runs B and C need distinct live X inputs, from an
  input override or from Sam.
- laddercodec's plain Copy across text (DF21 to TXT101, DF429 to TXT851, TXT851 to DS4174). Its second and
  third steps need two things that `paste` cannot do yet: copy a pasted rung back to the clipboard, and
  reopen a pasted instruction's dialog, press OK with no edit and copy the rung back.
- pyrung's: the Y gaps in slots 2 to 8, FC15 across an X gap, and reads past XD8 and YD8.
- The plan's small checks for a value typed into a dialog: leading zeros and spaces around an address, and a
  bare space as a Text initial value. The runner answered both for a CSV import, and answered the edge spaces
  of a typed nickname and comment.
- Left from earlier jobs: the rule behind the digits that CLICK prints for a DF near 1e30, Cancel in the
  Address Picker, and a tab at either end of a comment typed in CLICK.
- Low priority: after `try` picks a list item a second time, it does not check every list and option again
  (laddy's Send case 10). CLICK has not been seen to change one at that point.

Autocomplete follow-up (nothing): Copy's destinations use `ANY` in `detection/window_mapping.py`. That offers
banks that CLICK's Address Picker greys there: X, T, CT, SC and XD for a single Copy's destination, and YD too
for a Block's.

Sandbox fallback, only if the desktop stops working: Sam would have to enable Windows Sandbox and run the CLICK
installer in it once by hand. The probe files written for it on 2026-11-13 are gone, so they would have to be
written again.

### 4b. User checks a mock can automate (nothing; Sam judges the wording)

`devtools/record_simulator_gif.py` drives the real Simulator, Console, SimulationSession and pyrung with no
CLICK. In the same way, a "CLICK save" can be a regenerated mock project. About 30 of the open checks below
can be automated like this, as opt-in scripts or tests:

- the Simulator section, except "With pyrung 0.15.2 installed"
- unassigned I/O
- the planned-reload items
- the Data View small fixes, against the simulator's Modbus
- the Tag Browser double-click
- CSV Save counts

A script cannot judge the wording. Collect each notice into one page for Sam to read in one sitting.
These checks cannot be automated without CLICK: the overlay, project change and Save As, Review Changes paste
steps, and Sync racing a CLICK save.

## Small follow-ups (nothing)

Do each when a branch next touches its file.

- `tests/test_live_server.py` (`_session_in`, the "folder gone" case) sets the private `AnalysisService._status`
  and `_project_dir`. Use a stand-in such as `_UnbuiltAnalysis` in `tests/test_live_rung_apply.py`.
- The Simulator has no way to clear the PLC data file once you pick one.
- CLICK can save the PLC data file with unclear Text values after the session reads it and before pyrung's
  launch reads it. pyrung then skips those addresses, and the user sees no notice, because the session
  ignores pyrung's `skippedAddresses`.
- A bad PLC data file picked while the Simulator is off shows no message until Start.
- A failed program write shows no banner while a build runs.
- When TXT4 and TXT5 are both empty side by side, the Simulator's "next to an empty Text address" message does
  not match the line in the user's file.
- ClickNick's `read_mdb_csv` reads a blank DataType as BIT. The database path (`mdb_operations`) reads it as
  the bank's type. Nothing shows that CLICK writes a blank DataType. If it did, Save As CSV would write a file
  that ClickNick then refuses.
- `AnnotationService.recompose_comment` (`services/annotation_service.py`) strips the spaces at the ends of a
  comment's free text. Edit Annotations, `clicknick-cli tag` and the Simulator's links rebuild a comment with
  it. Sam ruled on 2026-11-18 that a comment keeps those spaces.
- The help does not say that CLICK's own CSV import drops the spaces at the ends of a comment. A comment that
  keeps them in ClickNick loses them when the user imports ClickNick's CSV into CLICK.
- Stale text: the docstring at `tests/test_analysis_service.py:126` says that pyrung refuses the row (pyclickplc's
  `read_csv` does). The `EXPORT_SAVE` comment in `devtools/click_runner.py` names a live run and its job. A
  docstring line near `devtools/click_runner.py:2398` is 137 columns.
- These parts of `app.py` are candidates for a later split: the Tools and Repairs menu actions, launching
  Review Changes and Compare with, `_export_pyrung_project`, and the unused `_check_odbc_drivers_and_warn`.

## 8. Onto pyrung's named imports (done, except the rule rename)

Plan 3. ClickNick moved to pyrung 0.17.0 and imports every pyrung name from `pyrung`, `pyrung.click`,
`pyrung.validation` or `pyrung.live`.

What it changed:
- `program.dataview()` replaces `build_program_graph`, and `AnalysisResult.dataview` replaces `graph`.
  `ValidationReport.grouped()` replaces ClickNick's `group_validation_findings`.
- `tests/test_pyrung_surface.py` fails when code imports from a pyrung module that is not public, or when a name
  that ClickNick uses leaves its module's `__all__`. It is a test and not a ruff rule, because ruff's banned-api
  rule cannot read the program text that the tests hold in strings.
- In the tests, the `pyrung_dap` fixture launches pyrung through DapService's subprocess launch in place of
  `_adapter_dap_class`. The `_parsers` asserts in `test_add_block_dialog` are gone. Test program strings use
  `from pyrung import`.
- `upstream:` and `downstream:` stop at the call site, as Sam ruled on 2026-11-18 ("the call site is the
  enable"). For a tag written in a subroutine, `upstream:` takes the conditions of every rung that calls it, at
  every level of the call chain, and not those conditions' own upstream. A tag in a call rung's condition
  reaches everything that the subroutine writes, and onward, only when it is the starting tag. The CHANGELOG
  says so for the filter box and the Console.
- The Simulator starts from a PLC data file with unclear Text values. pyrung skips those addresses, and
  ClickNick's notice names them. ClickNick's refusal before launch (`_plc_data_problem`) is gone.
- `dap_service.py` still matches pyrung's `Unsupported command` text, which 0.17.0 kept. That match goes with
  the console commands for every change (item 10).

Left over (waits on the joint laddercodec release): a saved check selection with an old rule name.
`load_check_config` raises on a rule code it doesn't know. ClickNick meets it at `ProgramCheckSelection.load()`
and `sync()` (`program_check_selection.py:48` and `:61`). At the joint release the field-rule codes become
laddercodec's names, so every saved selection of those rules holds old names. ClickNick catches the error at
those two calls, drops the names it doesn't know, keeps the rest, writes the workspace's `pyproject.toml`
without them, and says once which names it dropped.

## 9. The undecoded marker (waits on laddercodec, pyrung)

Plan 2, last bullet. laddercodec replaces a rung that it cannot decode with a marker rung. The marker rung has
the comment `UNDECODED: rung N, row R: <error>` and one `Undecoded` instruction that acts as End (Return in a
subroutine). `encode()` refuses the marker. On ClickNick's side:

- Drop the empty stand-in rung ClickNick puts in today.
- The Simulator runs up to the marker instead of refusing to run. `_workspace_problem` stops refusing "a rung
  ClickNick cannot read". Show a notice that is hard to miss.
- Check Program lists the marker.
- Review Changes can never paste the marker back, because `encode()` refuses it. Check the whole-program copy
  path that keeps CLICK's rungs, and the legacy-encoding paths.

The move to the next laddercodec release also changes how ClickNick builds a `Rung`. laddy, the agent that works
on laddercodec, listed the laddercodec changes on 2026-11-17 and 2026-11-18. Those facts are laddy's reading.
laddercodec's CHANGELOG on its main (2eaf985) lists most of them under Unreleased. The facts about ClickNick were
checked against ClickNick's main at c232d31, and the line numbers are from there.

- Nothing breaks while ClickNick pins `laddercodec==0.4.0`.
- On laddercodec's main since #110, instructions are frozen and hashable. Assigning to a field raises
  `FrozenInstanceError`. `laddercodec.replace(inst, **changes)` is public. When no value changes, `replace`
  returns an instruction that still encodes to the same bytes and carries the same warnings. When a value
  changes, it checks the instruction again. No code in ClickNick's `src` or `tests` assigns to a field of an
  instruction or a rung.
- Sam decided on two more changes. laddercodec built them on its `api/rung-grid` branch, and its CHANGELOG on
  main lists them.
  1. A down wire under a contact becomes a cell token, `Tee(Contact(...))`. `Contact.wire_down` and
     `CompareContact.wire_down` go away. The CSV form `T:X001` stays the same. Nothing in ClickNick reads
     `wire_down`.
  2. `Rung` is frozen, with tuple fields. `logical_rows` becomes a read-only property, and laddercodec refuses
     a constructor call that passes `logical_rows`.
- These calls pass `logical_rows`:
  - `src/clicknick/ladder/program.py`: `empty_rung` (lines 519-525, `logical_rows=1`).
  - `tests/ladder/test_cli.py` lines 108 and 135.
  - `tests/ladder/test_unreadable_rungs.py` lines 41, 210 and 255.
  - `tests/test_analysis_service.py` line 1143, which passes it by position.
  - `tests/test_compare_with_click_window.py` line 30.
  - `tests/test_live_rung_apply.py` line 38.
  - `tests/test_review_changes_window.py`, in `_coils`.
  - `tests/test_rung_diff.py` lines 41, 52 and 257.
- Two functions in `program.py` must unwrap a `Tee` cell to its contact. Neither raises on a `Tee`. No other
  code in `src` looks inside a condition cell.
  - `_extract_operand_candidates` (lines 169-212) returns an empty list for a cell that is not a known
    instruction and has no `to_csv`. laddy is adding `Tee.to_csv()`, which returns "T:" and then the contact's
    text. If that lands, the text match at the end of the function finds the operands. Without it, a contact
    with a wire down loses its operands.
  - `_unreadable_instructions` (lines 420-427) skips a `Tee(UnknownCondition)`, with or without
    `Tee.to_csv()`.
  - Unwrap first in both, with `if isinstance(token, Tee): token = token.contact`. laddy and the agent that
    planned this move agree that the unwrap reads better, even where `to_csv()` would work. At the move, add a
    test of a contact with a wire down.
- laddercodec keeps `decoded_rung_to_rows`, and it writes a `Tee` cell as `T:...`. ClickNick calls it in
  `program.py` lines 847-849.
- On laddercodec's main, `decode()` always returns a list. Its CHANGELOG says to remove any
  `isinstance(result, list)` check. `_decode_to_rungs` (`program.py` lines 241-244) has one. At the move, the
  fallback can never run, so remove it (rule 7).
- laddercodec's main renames many instruction fields. Its CHANGELOG lists them under Unreleased. Read that
  section whole at the move. These renames touch ClickNick:
  - `Contact.type` and `Contact.edge_kind` become one field, `Contact.kind`. Its values are "no", "nc", "rise"
    and "fall". The operand is the first argument: `Contact("X001", kind="nc")`.
  - `Coil.type` becomes `Coil.kind`. Its values are "out", "latch" and "reset".
  - `Timer.done_bit` becomes `done`, `current` becomes `accumulator`, and `setpoint` becomes `preset`.
    `_extract_operand_candidates` reads all three (`program.py` lines 194-196).
- Against laddercodec's main, five test files fail at collection with `KeyError: 'type'`. Their helpers read
  `typing.get_type_hints(Contact)["type"]` at import:
  - `tests/ladder/test_cli.py` line 41.
  - `tests/ladder/test_unreadable_rungs.py` line 32.
  - `tests/test_compare_with_click_window.py` line 25.
  - `tests/test_live_rung_apply.py` line 15.
  - `tests/test_rung_diff.py` line 35.
- Two more read it inside a function, so only the tests that call the function fail: `_coils` in
  `tests/test_review_changes_window.py`, and `tests/test_analysis_service.py` line 1139.
- At the move, the helpers call `Coil(coil)` and `Contact("X001")`. `Coil` defaults to `kind="out"` and
  `Contact` to `kind="no"`, so the helpers no longer read a type. laddercodec's main (#112) also exports a
  `Literal` alias for each fixed set of field values, such as `ContactKind` and `CoilKind`. The helpers need
  none of them.
- Nothing in ClickNick reads `edge_kind`. At the move, search `src` and `tests` for `.type`, and for
  `Contact(` and `Coil(` calls that pass an `InstructionType` first.
- laddercodec's main has `write_bundle()` and `read_bundle()` (#114). A bundle is `main.csv` and one
  `subroutines/<name>.csv` for each subroutine. The name is the subroutine's name with the whitespace stripped
  from both ends.
  - `write_bundle` refuses two subroutine names that differ only in case. It also refuses control characters
    and the names that `check_program_name` refuses. It never adds a suffix.
  - CLICK 4.00 refuses such a name too. Once a subroutine `Pump` exists, CLICK refuses `pump` with GUI-036,
    "The Program Name already exists. Please choose another name." It shows the same box as for a second
    `Pump`. The CLICK runner showed this on its own CLICK 4.00 on 2026-11-18. So `write_bundle`'s case refusal
    matches CLICK.
  - laddercodec's `check_program_name` follows CLICK.exe's Add New Subroutine dialog, by laddy's reading.
    CLICK refuses `<>:"/\|?*` and the Windows device names, such as `CON`, with GUI-040. It accepts a trailing
    dot. If CLICK accepts both `Foo.` and `Foo` as subroutines, `_slugify` gives both the stem `Foo`, and
    `program_save` writes the second as `Foo (2).csv`. Nobody has tried the pair in CLICK.
  - ClickNick's `program_save` writes its own bundle (`program.py` lines 696-717). `_slugify` (lines 461-466)
    removes only `<>:"/\|?*`. It keeps a control character, though Windows refuses one in a file name and
    `write_bundle` refuses it. `_slugify` also collapses runs of spaces, strips dots and spaces from the end,
    and returns "Untitled" for a name that comes out empty.
  - When two names give the same stem with case ignored, `_dedupe_filename_stem` adds " (2)", then " (3)",
    and so on. The test of `program_save` (`TestProgramSave`, `tests/ladder/test_cli.py` lines 638-680) uses
    made-up names.
- On laddercodec's main, `parse_bundle` returns main first, as "Main Program", then the subroutines sorted by
  name with case ignored. ClickNick never calls `parse_bundle`. Its own readers, `list_program_bundle`
  (`program.py` line 881) and `rung_diff.load_bundle` (`rung_diff.py` line 75), list the subroutines first and
  main last. Review Changes pastes the subroutines before main, so that they exist in CLICK before main's Call
  instructions. A move to `read_bundle` would reverse that order.
- laddercodec's main also has `csv_rows(rungs, *, index=False, stop="end")` and `CSV_HEADER` (#113).
  `write_csv` builds every row before it opens the file.

## 10. Recording, ClickNick side (waits on pyrung's recording core and console commands for every change)

Plan 1, step 4. pyrung, ClickNick and the VS Code extension release together.

- **Console commands for every change:** the panels send console text for every action that changes state
  (switches, analog values, forces, mode, step, speed, links). Reads stay structured requests. Delete ClickNick's
  structured requests for those actions, its `echo` of panel actions, and the Console pane's `;` split
  (`ConsolePanel._submit_command_text`, and the `autoreload` and `reload` refusals that rely on it). The program
  write stays `pyrungReload` with its carry plan, and launch and terminate stay structured
  (`scratchpad/visual-simulator-design.md`).
- **Recordings on every CLICK save:** run them after the build publishes, off the Tk thread (on the build
  worker), and only in a permanent workspace.
- **Right-click "Assert this".**
- **Setup prompt:** starting a recording opens the workspace setup, so that recordings land in a workspace
  that persists. If the user declines, nothing is recorded. A window that was never saved has no Project.ini
  and so no PLC name. In that case the prompt says to save in CLICK first.
- **Names and renames:** recordings hold names (the nickname, or the display address where there is none).
  The rewrite happens at the build that first carries the new names, which follows a Sync or a CLICK save,
  whatever made the rename. It never happens at edit time. At that build, ClickNick builds the old-to-new map
  from the old and new address-to-name maps. Then pyrung's rename function rewrites the recordings, before they
  run. A name that still exists is left alone, so a swap rewrites nothing. A name that is gone becomes whatever
  now names its old address (the display address if the nickname was deleted). `plan_carry` already builds
  these maps.
- **Where recordings live:** a permanent workspace is `<chosen folder>/<PLC name> Workspace` with a
  `.clicknick.toml` sidecar. ClickNick finds it through `%LOCALAPPDATA%\ClickNick\project-sidecars.json`, by
  the PLC name in Project.ini. A rebuild replaces only `csv/`, `src/plc`, `nicknames.csv`,
  `project_to_csv.py`, `run.py`, `AGENTS.pyrung.md` and `README.pyrung.md`, and it deletes `csv_output/`.
  Anything else is created only when it is missing, so a recordings folder survives rebuilds and the mirror
  copy. ClickNick deletes the temporary workspace (`CLICK (hwnd)\pyrung_project`) when the window closes.
- Remove the Console pane's refusals of `record` and `replay` (a3f84e1, f1b1471) once ClickNick's write and
  name mapping cover them.

## Open user checks

Sam's checks in CLICK. None blocks a release. Before a tag, Sam gets a short smoke test, and what the rest
find goes into bugfix releases. Items marked (4b) a mock
can automate. Items marked (runner) the runner can answer. When a check is walked or automated, delete it.

### Questions only CLICK can answer
- Q2 (runner): what does CLICK write on File > New, and when does its title change? This bears on how soon
  ClickNick checks kept edits against the new project's database. File > Open and Save As have run.
- Q6: after you delete all rungs, empty rungs are on screen. Is one of them selected for Ctrl+V, or must the
  step's wording say to click the first empty rung? Sam (2026-11-16): "there are always empty rungs". Not to be
  automated.
- Q8 (CLICK v2/v3 only): autocomplete's map for the v2/v3 dialogs is inferred from v4. In an Out, Set or Reset,
  does CLICK refuse X, T and CT? (ClickNick no longer offers them.) In a Receive or Send, do the master
  address (Receive's `Edit20`, Send's `Edit16`), the flags and the exception field get the popup? ClickNick
  offers every function code's banks there.
- Q10 (runner, non-English Windows): does the redraw after a Sync complete? The live runs were on an English
  Windows. ClickNick recognises the Open dialog and its Cancel button by their control ids and the three
  import modes. So Windows' own "Open" and "Cancel" can read otherwise. ClickNick assumes that CLICK's mode
  names ("Merge (Project priority)", "Merge (File priority)", "Delete Existing") are English on every Windows.
- Q11 (not for the runner): when one of CLICK's dock panes is floated (Navigation, Output, Instruction List),
  CLICK's process shows another top-level window. Does every redraw, **Tools > Redraw Nicknames in CLICK**
  included, then report CLICK busy? If so, which window classes should the redraw tolerate besides the
  main window and tooltips?

### Address Editor and store
- Fill Down / Add Block T1..TD5, then Sync.
- Block rename over T/TD, then Sync.
- Colour-only change on T with an untagged TD.
- CLICK comment edit + quick rename in ClickNick + Sync.
- Remove Block leaves 'Fill' (no leading space).
- Edit two nicknames, let CLICK save one first, Sync -> "Synced 1 changes", main window "1 tags synced".
- Edit a nickname, save the same in CLICK, Sync -> "CLICK already has these changes. There is nothing to write."
- (4b) CSV Save reports the number of rows edited.

### Database helper messages (Sync without Access ODBC)
- Not a check in CLICK. Sam decides the wording. `src/clicknick/utils/jet_sidecar.py` line 95: when the changes
  that a Sync sends come to more than 8 MB, the Sync fails with "There are too many address changes to save at
  once." The message gives no advice. Only the Jet path has this cap, because `MAX_REQUEST_BYTES` appears only
  in `jet_sidecar.py`. Installing Microsoft's Access ODBC driver avoids it. Should the message say so, or give
  other advice?
- `jet_sidecar.py` line 121: the database helper stopped answering during a save. The message says that
  ClickNick cannot tell whether the changes were saved. After this failure, the Address Editor still shows the
  edits as not synced. If the user chooses the same CLICK window again in ClickNick's window list, does
  ClickNick read SC_.mdb again and show which edits reached it? If so, the message can tell the user to do
  that.

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
