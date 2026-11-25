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

1. The CLICK runner's waiting jobs (CLICK). Sam ruled on 2026-11-17 that they come ahead of recording.
2. Recording, ClickNick side (item 10; waits on pyrung's recording core and console commands for every
   change).
3. Small follow-ups (nothing), whenever a branch touches their file.
4. The release after 0.26.0. Sam has not ranked it yet.

## The release after 0.26.0

Sam ruled on 2026-11-20 that the pyrung APIs for links wait for this release: "we can figure out better apis
for this in next release". Each item says what it needs, as above.

- pyrung APIs for links (waits on pyrung). pyrung would hold a link on an address that no rung names, and say
  which addresses it can link or resolve. ClickNick then drops its own waiting state: `_held`,
  `_restore_bench` and the patch retry in `simulation_session.py`. The same APIs bring three changes to the
  Simulator: a link on a slot that a range reaches, a dimmed point where no rung touches the address, and a
  placeholder CPU with live switches when no CPU is configured.
- The refused-link text (waits on pyrung's next release). At the next pyrung pin, run
  `tests/test_simulation_session.py` on the release.
- An unknown module (waits on pyclickplc). pyclickplc would read a module that it does not know as unknown,
  instead of raising `ValueError`. This is item 3 of pyclickplc's roadmap.

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

Jobs waiting, from the plan's item 4 and the other sessions:
- The encoding of the Address.csv that CLICK 3.43 and 2.x write, once the branch `probe/click-export-mdb`
  merges with the runner's CLICK 3.x support. `read_mdb_csv` reads Address.csv only as UTF-8 with a BOM
  (`utf-8-sig`). If an older CLICK writes it in cp1252, the read raises `UnicodeDecodeError` for a file with a
  non-ASCII nickname or comment.

Needs Sam or the PLC:
- laddercodec's PLC runs B and C. They need distinct live X inputs, from an input override or from Sam.
- laddercodec's question: which X point is the 17th element of a Send or Receive that starts at X001. Only a
  running PLC shows which X point it reads.
- pyrung's Y gaps in slots 2 to 8, and `fc15_y_gap` in slot 1. Both drive outputs. Each run needs Sam's go,
  with outputs allowed.
- The rule behind the digits that CLICK prints for a DF near 1e30. It needs data writes to the PLC.
- A real Tab key press or a Ctrl+V paste into a comment in the Address Picker. The runner sends only window
  messages.

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

- A notice about an unreadable rung in a subroutine uses pyrung's name for the subroutine. When main does not
  call the subroutine by name, pyrung falls back to the CSV file name, which can differ from CLICK's name
  after `_slugify` or a " (2)" suffix. Carry `prog.name` with the marker to fix it.
- The Address Editor sets its filter notice only in `_apply_filters`. When a build finishes, it recomputes
  neither the notice nor the rows, so a notice can name a rung that the new build no longer has.
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
- cp1252's five undefined bytes, 0x81, 0x8D, 0x8F, 0x90 and 0x9D
  (`../clicknick-wt/buildbot/jobs/runner-batch2/RESULTS.md`, J2). CLICK stores U+0081 and exports it as the
  byte 0x81. ClickNick and pyclickplc refuse it, and Python's cp1252 cannot read such an export. The planner
  decides, with pyclickplc's session, whether ClickNick and pyclickplc follow Windows' table for these five
  bytes.
- A bare space in CLICK's own export (`../clicknick-wt/buildbot/jobs/runner-batch2/RESULTS.md`, J3.1). CLICK
  writes a Text initial value of a bare space unquoted, and its own import of that file stores NULL. Check that
  pyclickplc reads that line.
- These parts of `app.py` are candidates for a later split: the Tools and Repairs menu actions, launching
  Review Changes and Compare with, `_export_pyrung_project`, and the unused `_check_odbc_drivers_and_warn`.

## 9. The undecoded marker (waits on pyrung's release after 0.18.0)

laddercodec replaces a rung that it cannot decode with a marker rung. The marker rung has the comment
`UNDECODED: rung N, row R: <error>` and one `Undecoded` instruction that acts as End (Return in a subroutine).
`encode()` refuses the marker. `write_csv` also writes a marker in place of a rung that no CSV cell reads back
as CLICK holds it, such as a text compare that reads two ways.

The branch `bob/laddercodec-next` did this much:

- It moved ClickNick onto laddercodec's renamed API, and dropped unknown rule names from saved check
  selections. That finished the move onto pyrung's named imports.
- Every call into laddercodec that reads CLICK's bytes or writes a CSV records laddercodec's warnings
  (`ladder/codec_warnings.py`). Each warning class has a rule, and a laddercodec warning with no rule counts
  as a rung that ClickNick cannot read. The coordinator asked for this on 2026-11-20, after two review rounds
  found placeholders that reached the workspace with no finding.
- A rung whose comment laddercodec cannot decode keeps its logic and loses its comment in a save, as in
  0.25.0 (laddercodec v0.4.0 set the comment to None). Save Clipboard to CSV refuses it, and a paste refuses a
  comment that starts with `UNDECODED comment:`.
- One lock guards each `recording()` block, because the build worker and the Tk thread both call laddercodec.
- `program_save` writes an unreadable finding, and a replacement rung, for three kinds of rung: a rung that
  decodes as a marker, a rung that `write_csv` would write as a marker, and a rung that `write_csv` would split
  into more than one rung. The replacement is laddercodec's marker, or ClickNick's empty stand-in inside a For
  loop (see the branch `feat/marker-findings` below). The runner showed on CLICK 4.00 that a paste, and a save
  before Syntax Check, keep a NOP fed from the rail beside outputs on one rung. One function makes the check
  (`_rung_problems` in `ladder/program.py`).
- Save Clipboard to CSV refuses the same three kinds of rung. `clicknick-rung load` copies a .bin file that
  decodes as a marker as it is, and adds no addresses to SC_.mdb. It passes every other laddercodec warning on
  and adds the addresses. Every paste path refuses a marker in a CSV, with the rung's number
  (`prepare_rungs_load`).
- `program_save` writes each subroutine with `stop="return"`.

The branch `feat/marker-findings` needs pyrung 0.18.1, which ClickNick pins. On it, `program_save` writes laddercodec's marker in place of a rung that it cannot read. It still
records the finding with the rung's number. The planner ruled the For loop cases on 2026-11-21:

- A rung inside a For loop gets the empty stand-in. pyrung refuses a marker inside a loop, so one such rung
  would fail the whole workspace build.
- An unreadable `next()` gets the stand-in too. The stand-in closes no loop. So pyrung's loop goes on past it,
  and each later unreadable rung gets a stand-in until a `next()` that `program_save` writes closes the loop.
  `program_save` reads the loops from the rungs that it writes, as pyrung does.
- An unreadable `for()` outside a loop gets a marker. At 79fc8a6, pyrung's main refused the `next()` below
  it, whatever `program_save` wrote, and its message named the marker's rung as the one that may have held
  the `for()`. The paragraph below says what pyrung 0.18.1 does.

pyrung took the `lone_next` change in #124 (0d59e21). 0.18.1 is the first release that holds it. When pyrung's import finds a `next()` with no `for()` above it, and a marker stands above that
`next()`, it writes the `next()` as an empty placeholder rung, `with rung(): pass`. It adds `lone_next=[...]`
to the marker's `undecoded(...)` call, with the `next()` rungs counted from 0. The Program ends at the marker,
and the workspace builds. pyrung's message for the marker names the `next()` rung. pyrung still refuses a lone
`next()` with no marker above it, and a marker inside a loop. So the marker for an unreadable `for()` builds.
A stand-in there would be refused, unless an earlier marker stood above it.
`test_an_unreadable_for_gets_a_marker_and_the_program_stops_there` pins the marker case. pyrung 0.18.0 fails
the build with the stand-in that 0.26.0 writes. Its `ladder_to_pyrung` returns source with a `next()` and no
`for()` above it, and running that source raises a `TypeError` that names no rung. The reviewer of
`feat/marker-findings` checked this on 2026-11-21.

No branch changes these two cases yet:

- If the user writes the loop in place of `undecoded()` and does not delete pyrung's placeholder for a lone
  `next()`, the exported folder holds an empty rung there. While CLICK's copy still holds the unreadable rung,
  Review Changes refuses that program. Its message names the placeholder as an empty rung, as if it stood in
  for CLICK's unreadable rung. After CLICK's copy reads cleanly, Review Changes would propose the placeholder
  as an extra empty rung after the loop. No one has checked that second step.
- A `for()` that ClickNick reads, a `for()` inside it that it cannot read, and the two `next()` rungs (saved
  as `-S---M`: S is the stand-in and M the marker) stay refused. The stand-in opens no loop, so the second `next()` has no `for()` above it and no
  marker above it. The case would build if ClickNick wrote a stand-in in place of the readable inner `next()`
  that pairs with the unreadable `for()`. It can pair them only while the unreadable rung still shows its
  `ForLoop`. The refusal also tells the user to "Add the for() rung in CLICK", which CLICK already has.

pyrung's roadmap plans a marker that stops the scan only when a scan reaches it. pyrung could then accept the
marker inside a loop, and the stand-in could go.

pyrung 0.18.1 reads the marker. Its `ladder_to_pyrung` writes an `undecoded(...)` call in place of the rung.
The Program ends at that call. pyrung 0.18.0 raised `ValueError` there, because it did not know `undecoded`
in the AF column. These steps are left:

- Drop the empty stand-in rung that a For loop still needs (`_replace_unreadable`, `is_stand_in`, and the
  refusals in `prepare_rungs_load` and `_placeholder_refusal`). `feat/marker-findings` already writes the marker
  outside a loop.
- Check Program lists the marker.
- When the stand-in goes, check again that Review Changes' whole-program paste (`ProgramChange.merged` when
  CLICK's copy is unreadable) refuses a marker, and that the legacy-encoding record still names the rung.
  `feat/marker-findings` has tests for both on the marker.
- Review Changes refuses a whole copy that leaves out a CLICK rung that ClickNick cannot read
  (`ProgramChange.dropped_unreadable`, `feat/marker-simulator`). It cannot tell the rung's logic from another
  rung, so two gaps stay. It misses a dropped rung when the user adds another rung in its place: CLICK
  `[R1, M, R3]` against the folder `[R1, NEW, R3]` is a 1:1 replace, and `[R1, R3', R4new]` is a 2:2 one. It
  refuses wrongly when the user writes the logic in place and deletes a rung next to it: `[R1, M, R3, R4]`
  against `[R1, L, R4]` is a 2:1 replace, and the text says that the folder leaves the rung out. Deleting R3
  in CLICK first works around it. A whole-copy finding (`rung=None`) beside a marker makes every rung unequal,
  so the program is one difference, and a rung added anywhere hides a deleted call. This case is rare.
- Follow-up branch, which needs no pyrung release: make Review Changes refuse before the first step when
  CLICK's copy is readable, so that CLICK is never left half pasted. Today the earlier steps paste, and then
  `prepare_rungs_load` refuses the step that holds a marker, a comment that starts with `UNDECODED comment:`,
  or a rung that needs CLICK v4 (`NeedsClickV4Error`). The new refusal counts only the rungs that the copy
  would really take, and leaves out skipped differences. The planner schedules it.
- Follow-up, which needs no pyrung release: a Simulator write after a CLICK save waits about 0.8 s for the
  read of `src/plc` (`read_program_stops`). The worker's Python start and its import of pyrung take most of
  that time. pyrung's reload alone takes about 0.035 s. The builder of `feat/marker-simulator` measured both
  on 2026-11-25. A write skips the read only while `src/plc` has not changed since the last read, and the
  build of a CLICK save writes `src/plc` again. The fix to try: take a snapshot of `src/plc` right after the
  analysis build writes it. While `src/plc` still matches that snapshot, take the stops from that build
  (`AnalysisService.undecoded_rungs`) and do not read. The coordinator asked for this bullet on 2026-11-25.

What a move to laddercodec's `read_bundle` and `write_bundle` would change (out of scope for
`bob/laddercodec-next`):

- `write_bundle` names a subroutine's file after its name with the whitespace stripped from both ends. It
  refuses two names that differ only in case, a control character, and the names that `check_program_name`
  refuses. It never adds a suffix. ClickNick's `_slugify` also collapses runs of spaces and strips dots from
  the end, and `_dedupe_filename_stem` adds " (2)". So a subroutine whose name has two spaces in a row or a
  trailing dot gets a new file name, and Review Changes would compare it as a removed program and a new one.
  CLICK refuses two subroutine names that differ only in case (GUI-036, seen by the CLICK runner on
  2026-11-18). Nobody has tried `Foo.` and `Foo` in CLICK.
- `read_bundle` returns main first, then the subroutines sorted by name with case ignored.
  `list_program_bundle` and `rung_diff.load_bundle` list the subroutines first and main last, so that Review
  Changes pastes the subroutines before main's Call instructions. A move would have to keep that order.
- `write_bundle` writes main with `stop="end"` and each subroutine with `stop="return"`, as `program_save`
  does.

## 10. Recording, ClickNick side (waits on pyrung's recording core and console commands for every change)

Plan 1, step 4. pyrung, ClickNick and the VS Code extension release together.

- **Console commands for every change:** the panels send console text for every action that changes state
  (switches, analog values, forces, mode, step, speed, links). Reads stay structured requests. Delete ClickNick's
  structured requests for those actions, its `echo` of panel actions, and the Console pane's `;` split
  (`ConsolePanel._submit_command_text`, and the `autoreload` and `reload` refusals that rely on it). The program
  write stays `pyrungReload` with its carry plan, and launch and terminate stay structured
  (`scratchpad/visual-simulator-design.md`). `dap_service.py` still matches pyrung's `Unsupported command`
  text, which pyrung 0.17.0 kept. Remove that match with the structured requests.
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
- Q13 (Sam, not the runner: changing the code page needs a reboot): on a Windows whose ANSI code page is not
  1252, what does CLICK hold and export for `ł` or `Ж`? ClickNick flags both, because it keeps cp1252 until this
  is answered. Sam saw CLICK turn one emoji into `??`, which fits a conversion through the system code page.
  The five bytes that Python's cp1252 lacks are a small follow-up ("cp1252's five undefined bytes").
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
- Q14 (Sam): CLICK can hold a Modbus TCP address with leading zeros, such as `010.002.003.004`, after an
  earlier paste. laddercodec 0.5.0 reads it as `10.2.3.4`, so Review Changes no longer lists that rung, and
  CLICK keeps the padded bytes. Does a Send with such a pasted address connect to 10.2.3.4 on the PLC? If it
  does not, laddercodec needs a legacy-encoding finding for the padded address.
- Q15 (the runner for 4.00, Sam for 2.60-3.x): the connection watch treats a non-empty title of CLICK's main
  window with no `- name.ckp` as CLICK unloading the project. The next project that the title names is then a
  project change, even with the same file name. Nobody has checked this against the titles of CLICK 2.60-3.x, an
  online CLICK, or a project saved in capitals as `X.CKP`. `parse_click_filename` matches only a lowercase `.ckp`.
  ClickNick does not list a window whose title names `X.CKP`, and a connected window that shows `X.CKP` after a
  Save As is treated as if CLICK had unloaded the project. Matching without case needs more than the regex,
  because `project_name` and two other places strip only a lowercase `.ckp`.
- Q16 (Sam): in Program > Edit Rung Comments, type `a → b`, then `中` through an IME, then `😀`, each in a rung
  of its own. Save the project, close it and open it again. Does the editor show →, 中 and 😀, or `?`? The
  runner's WM_CHAR test gave `?` for each. No one has typed them by hand. To keep the result, keep the saved
  project. If the RTF is wanted, the runner opens that project and reads each rung's RTF from the clipboard.
  A pasted RTF escape already survives: CLICK kept a pasted → through an edit, a save and a reopen. So the
  answer decides only whether laddercodec must also read the form that CLICK writes for typed text, such as
  中 as GBK bytes in a SimSun font.
- Q17 (the runner or Sam): nobody has checked whether CLICK's comment editor writes an accented Western letter
  such as `é` in a charset-0 font or as a `\u` escape. laddercodec reads both forms in full. It reads only part
  of a comment that holds `é` as a byte in a font of a charset other than 0 or 134. The 0.26.1 CHANGELOG tells
  you to replace a comment that laddercodec reads only in part with ASCII text. If CLICK writes `é` in one of the
  two forms that laddercodec reads, that advice can allow accented Western text too.
- CLICK's **Export Nicknames** was seen to leave out a nickname that ClickNick wrote, before 0.26.0. If it
  happens again, note the CLICK version, and whether the project was saved or reopened before the export.

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
