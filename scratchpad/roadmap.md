# ClickNick roadmap

The one live statement of what ClickNick does next. Written 2026-11-15 from the planner's handoff, this
session's reply to it and Sam's rulings on that reply. Cross-repo items and the shared rules are in the plan,
`ssweber.github.io/plan/README.md` (its numbered "Cross-repo work" items are cited below as plan 1-6).

How to use it:

- When an item lands, delete it. This file lists what is still to do.
- Each item says what it needs: **CLICK** (the CLICK software), **PLC** (a real PLC), **Sam** (his judgment
  or an action only he can take), **waits on X** (another repo's release), or **nothing** (refactor only).
  Never queue work that needs nothing behind work that needs Sam.
- Branches go into an always-releasable `main`; there is no `dev`. Sam squash-merges. A session stops at
  "CI green, ready to merge", and pushes or opens PRs only once Sam has said so directly.
- Test a branch that needs an unreleased pyrung, laddercodec or pyclickplc locally against the sibling
  checkout (`make install-dev`). It merges after that sibling's release.
- Never touch Sam's own CLICK windows, temp folders or SC_.mdb. The sandbox runner (item 4) works only on a
  CLICK that it started itself.

## Order

1. Housekeeping (nothing)
2. ssort out, tests into CI (done)
3. The bob plugin (done)
4. CLICK runner (built: `devtools/click_runner.py`; early jobs run 2026-11-16, open questions left), and the user checks it or a mock can automate (nothing)
5. ConnectionSession owns the window and project (done)
6. Split ClickNickApp (done)
7. Onto pyclickplc's readers (done)
8. Onto pyrung's named imports (waits on pyrung's deletions release)
9. The undecoded marker (waits on laddercodec, pyrung)
10. Recording, ClickNick side (waits on pyrung's recording core and console commands for every change)

Items 5 and 6 come before 10, because recording adds more per-project state. Items 8 and 9 fit in whenever
their sibling release is out.

## 1. Housekeeping (nothing)

- `dev` goes, because it holds the same tree as `origin/main` (0.24.0 was squash-merged). Done locally
  (2026-11-15): local `dev` and `bob/train4` are deleted, and local `main` is reset to `origin/main`. Deleting
  `origin/dev` is a push, so ask Sam.
- Arc folders under `../clicknick-wt/buildbot/jobs/` can go once this file holds their open items. The open
  items are the user checks (below) and two leftovers from the sweep ledger:
  - Tests and docstrings that still say "offline console".
  - A review note on `bob/followups` (landed as ba39f22). `-s/--session` and `-h` given after the command now
    reach the server as command words, so `clicknick-cli get DS1 -s MyProject` goes to the default session.
    Neither behaviour is documented. Decide whether options after the command are parsed, and test it.
- Memory: the user-checks memory points at the sweep folder. Point it here. Drop the memories that this file
  replaces.
- Issue #36 is open.
- Docs deploy on a release, not on every push to `main`. `docs.yml` builds on pull requests. It deploys
  on `workflow_dispatch` from `main`, and it builds the `ref` input (default: the latest release).
  `publish.yml` starts it with the release's tag. The scripts that the build runs (`.github/scripts/`) come
  from that tag, so a fix to them reaches the site with the next release.

## 2. ssort out, tests into CI (done)

Both landed in v0.24.1 (#95). ssort is gone from `devtools/lint.py`, `pyproject.toml`, `ci.yml`
and `AGENTS.md`. CI runs the tests on `windows-latest` with Python 3.13 and 3.14. Reorder a file
only when it becomes a problem or when you are rewriting it anyway.

## 3. The bob plugin (done)

The BOB tooling is the bob plugin (github.com/ssweber/bob). It holds the skill, the three agents, the
PreToolUse hook and the bounded runner (`run.py`: timeouts, memory cap, targeted slots, `ps`, `reap`,
`worktree new/rm/list`). There is no merge queue here, and CI is the gate. ClickNick keeps two files of its
own: `.claude/bob/config.toml` and `.claude/bob/profile.md`. Fix a fault in the tooling once, in the
plugin, through its own pull request.

Once per clone: `claude plugin install bob@bob --scope project` (the `bob` marketplace is added once per
machine: `claude plugin marketplace add ssweber/bob`).

## 4. CLICK runner spike (CLICK, Sam)

Plan 4. A runner in `devtools/` that drives CLICK unattended, so work that needs CLICK no longer needs Sam.
laddercodec and pyrung call it as a command. It relies on the clipboard (`ladder/clipboard.py` already reads
and writes CLICK's format) and on ClickNick's window code, not on pixel positions. It does not replace
readings from a real PLC.

**Status (2026-11-15):** the runner is built as `devtools/click_runner.py` (`paste CSV --out DIR`,
`record --out DIR`). Its docstring has the rules and the result format. Live on Sam's desktop, it pasted 1, 61
and 301 rungs into its own CLICK v4, which was connected to the conformance PLC. It ran Syntax Check, saved,
decoded the save back to CSV and matched every rung. A 301-rung paste freezes CLICK for about 16 s, and the
whole run took 39 s. The runner drives CLICK by posted commands only, with no keystrokes or pixels. It cannot
send a command that reads the project from the PLC or writes one into it. The PLC login is `admin` (prefilled)
/ `123click`, which is deliberately not secret. Next are the early jobs below, and subroutines. To paste into a
subroutine, first record its dialogs with `record`.

**Status (2026-11-16):** the early jobs ran live. Their results and run dirs are in the BOB job folder
`jobs/runner-jobs/`, in RESULTS-A.md to RESULTS-F.md. The runner gained these modes:
- `try --keep` saves and decodes each accepted case.
- `reopen` saves, edits the runner's own Project.ini, saves, opens and saves again.
- `read-data` runs PLC > Read Data from PLC (32851) into `DIR/plcdata.csv`.
- `picker` opens Program > Address Picker (32834). It sends keys to the picker's grid and editor by
  SendMessage, and it copies SC_.mdb before and after.

Open Project (32772) and System Configuration (32827) are on the allowlist too. `reopen` reads System
Configuration's PLC Name at each point and closes it by Cancel. Write Data into PLC (32852) is on the never
list. Sam approved these:
- Read Data from PLC.
- Editing the runner's own Project.ini.
- The one Address Picker edit (X001 `Test`, then OK).
- Writing pyclickplc's test data values into the conformance PLC by pyclickplc's Modbus client (TXT961..TXT993,
  DF251..DF258, read first and written back). The runner itself writes nothing into the PLC.
- Opening System Configuration without OK.

What the jobs answered:
- Constants (B): CLICK stores a Math real and a Copy source in its own printed form (`1.50` as `1.5`, `1e3` as
  `1000.0`, `0ffh` as `0FFh`). A hex Math reads a constant without `h` as hex. laddercodec keeps the typed
  text or refuses those. Rule table row A6: CLICK refused the 15 SC points tried between laddercodec's
  writable ones (OBJ-003), and accepted SC50 and SC162.
- Project.ini (C): CLICK carries added sections byte for byte, in either case, through Save As and Open. System
  Configuration's PLC Name shows `[Sec20] Key1=` with the section and key in each case tried (`[sec20]`,
  `[SEC20]`, `key1`, `KEY1` and mixes). When the file has two such sections or keys, it shows the first.
  `[PLCName] PLCName=` alone shows nothing (pyclickplc reads it when there is no `[Sec20]`).
- Read Data (D): CLICK writes a space, 0x01, 0x7F and 0xFF in TXT as `$20`, `$1`, `$7F`, `$FF`, as pyclickplc
  does, but the other printable punctuation tried plain (pyclickplc refuses it) and a comma raw, which splits
  the row. DF 1.8e30 and 1.5e30 print with other digits than pyclickplc's. D2 pinned the switch from 20 to 19
  digits near 1e30 between the neighbouring floats `0x7154FFFF` and `0x71550000`, and found it is no one limit
  on the first 20 digits (1.0548e35 keeps 20, 1.0546e25 keeps 19). Run d8's file went into the Save dialog's
  last folder: the dialog had emptied the path set in it, which the runner now sets again until it holds. A
  connect after an aborted connected run timed out (PTC-013) each time.
- System nicknames (E): a new project's SC_.mdb holds 3 rows until the Address Picker is closed by OK. OK
  writes 135 SC and 222 SD rows (SD19 to SD26 included), with or without an edit. When the picker was closed by
  its window's close with nothing typed, SC_.mdb stayed unchanged (e3, e4). Cancel, and a close after typing,
  were not tried.
- Reserved words (F): the Address Picker and the import refuse all 12 words tried (`MAX`, `Max`, `max`, `MIN`,
  `ABS`, `abs`, `RAND`, `MDN`, `AVG`, `LOG`, `Log`, `log`) and `A,B`. They accept `MAXIMUM` and `Max_Speed`.

Left: the rule behind CLICK's DF digits (D2 says where it switches near 1e30, not why), Cancel in the Address
Picker, and job G. Job G is one Write Data into PLC of pyclickplc's TXT-only file, run by a script outside the
repo. Its dialogs are probed (the file sets the memory types, and Cancel in its Open dialog closes the form),
but the write did not run.

**Small jobs (BOB job `runner-small`, 2026-11-16):** probes kept in the job folder ran them. The probes are
subclasses of the runner's `Run`, and the runner is unchanged. The results are in the job's RESULTS.md. What
they answered:
- Rule table A8 and A10: CLICK accepts a block Copy TXT1..TXT2 into TXT11 and a hex Math into YD0 or YD1, by
  dialog and by paste. The save decodes to the pasted rungs, and Syntax Check reports only the missing END.
  The pasted Copy (block TXT1..TXT2) lacks the flag 0x1201, which every dialog-made Copy kept so far carries.
  CLICK kept it without the flag, and its Syntax Check passed it. pyrung still refuses both.
- The Address Picker lists no SC or SD for a Copy pack and unpack destination (with no source, and after an X,
  C, DH or DS source) or for a hex Math result. That is 8 lists in all, and `sc_sd_writable.json` now holds 12
  fields. 15 `try` cases agree. laddercodec takes the same banks. For an SD hex Math result it cites OBJ-004,
  and CLICK cites OBJ-003.
- Section D: Syntax Check reports C0001 for both bridges. It reports C000A for pins that share the reset's
  contact, for a pin fed from a tee, and for a reset wire that also feeds an output. laddercodec predicts C000A,
  C0205 and C0001 for the bridge with a reset. It does not capture the two pin shapes, and it gives C0205 for
  the third case. An unwired timer or counter reset is C0202, which laddercodec's `check()` does not report.
  The rule table's D3 entry for laddercodec ("drops the pin") is stale, because laddercodec keeps the reset
  row. The D2 rungs draw no error beyond the missing END, yet the Syntax Check rewrites two of them. It drops a
  NOP on a row of its own beside a coil's rung, and it wires a rung of only wires through column AF
  (laddercodec reads that as a NOP). The paste, and a save before the check, hold the rungs as pasted.
  laddercodec's decoder drops a wires-only last rung (`_is_trailing_placeholder`), so the runner then reports
  that the paste did not land.
- Q2, for Save As and File > Open: the item's text below and "Open user checks" give the answer.

**Where it runs (Sam, 2026-11-15, replacing the plan's Sandbox-first rule):** it runs on the CLICK installed
on Sam's desktop while he is away, as long as it is deterministic. Windows Sandbox is the fallback. It is
needed only if the desktop cannot work.

**Rules that make it deterministic and keep Sam's work safe:**
- It refuses to start while any CLICK window is open, and touches only the CLICK it started.
- Each step waits for a window or a file to appear, with a timeout, never for a fixed time. An unexpected
  dialog stops the run. The runner leaves a screenshot and a log, and closes its CLICK without saving.
- It never writes to the PLC. It connects only so that the new project takes that PLC's hardware.

**How CLICK v4 is driven (from Sam):**
1. Start CLICK v4. When it prompts, connect to the only CLICK PLC on Sam's network: the conformance runner.
   Connecting is what makes the project match that PLC's hardware.
2. When it asks whether to read the project from the PLC, answer No. The open project is then
   `NewProject{n}` with an empty main program, so a probe that needs only main is quick to run.
3. To paste a test: select the first rung number, send paste, wait until the rungs appear.
4. Press "Syntax Check", then save the project. That gives the Scr*.tmp files, and from them the CSVs.

**Known and unknown:**
- The screen stays unlocked while Sam is away (Sam, 2026-11-15). The runner still checks, and it refuses to
  start on a locked desktop, because synthetic input and the clipboard do not reach one.
- The first save of `NewProject{n}` opens a Save As dialog that needs a path typed in. The runner fills it.

**Sandbox fallback:**
- Two probe files were written 2026-11-13 in `%TEMP%\clicksandbox` and never run. `click-probe.wsb` maps the
  installer folder read-only and an output folder, with networking off. `bootstrap.cmd` records the
  InstallShield answers (`/r`, `setup.iss`) on the first run and installs silently (`/s`) after that. Move both
  into `devtools/`, with paths as arguments, if the fallback is needed.
- Sam would then need to enable Windows Sandbox, reboot, and run the installer by hand once inside it.
- Inside the Sandbox, CLICK may not find the PLC, because the Sandbox's network sits behind NAT. Sam's idea is
  to keep a copy of the conformance PLC's Project.ini and put it in place of the new project's. That may work,
  because CLICK picked up a PLC name that ClickNick wrote into Project.ini (`write_plc_name`). The first thing
  to test is whether CLICK also takes the hardware (modules, I/O) from that file, and when it reads the file.
  The other way is a blank `.ckp` saved once for that PLC, which the runner opens.

Early jobs once it works:
- What CLICK writes, and in what order, on Open, New and Save As (user check Q2 below).
- What CLICK turns constants such as `005`, `+5` and `0ffh` into (for laddercodec).
- The three small checks in the plan's "Only Sam can do these": leading zeros and spaces in an address, a bare
  space as a Text initial value, and whether CLICK strips spaces from nicknames and comments.

The two answers that bear on pyclickplc's reader go to Sam. 4d answers the spaces in an address, the bare
space, the edge spaces and leading zeros for CLICK's CSV import only. A value typed in CLICK is still open (Q7).
Save As and Open (Q2) ran (job `runner-small`):
- Save As leaves SC_.mdb's bytes as they were. It changes the title last, about 0.7 s after Save.
- File > Open deletes the temp folder's files, SC_.mdb included, and the title goes bare. It writes a new
  SC_.mdb (65,536 to 81,920 bytes) before the title names the project. It writes SC_.mdb once more about 0.1 s
  after the title is final, while Project Reading still shows. The runner read the rows only once the step had
  settled, after that last write.
- New was not run, because New Project (32771) is not on the allowlist.

### 4b. User checks a mock can automate today (nothing; wording goes to Sam)

`devtools/record_simulator_gif.py` drives the real Simulator, Console, SimulationSession and pyrung with no
CLICK. It exports a program to CLICK CSVs and builds the workspace the way a build does. In the same way, a
"CLICK save" becomes regenerating the mock project and publishing it. About 30 of the open checks below can be
automated like this, as opt-in scripts or tests:

- the Simulator section, except "With pyrung 0.15.2 installed"
- unassigned I/O
- the planned-reload items
- the Dataview small fixes, against the simulator's Modbus
- the Tag Browser double-click
- CSV Save counts

A script cannot judge the wording. Collect each notice into one page for Sam to read in one sitting.
These checks cannot be automated without CLICK: the overlay, project change and Save As, Review Changes paste
steps, and Sync racing a CLICK save.

### 4c. The editor's answers for the rule table (done for Math, Copy, Out and Receive)

`click_runner.py try devtools/editor_cases.json --out DIR` opens CLICK's Math, Copy and Out dialogs from the
ribbon's commands (50030, 50040, 50010) and fills them. It presses OK and records whether CLICK refuses each
case (its `OBJ-...` box) or accepts it. An accepted case counts only when Syntax Check shows the instruction in
rung 1 (the missing END moves from rung 1 to rung 2). The runner then deletes the instruction again. The cases
cover rows A1 to A10, B1 to B6 and B8 of pyrung's and laddercodec's rule table. They include controls that
tell a refusal's reason apart (for example, X001..X016 packs into DH but not into DS). A run of 66 cases takes
about 4.5 minutes. CLICK ignores a Syntax Check posted soon after the last one, and nothing it shows says when
it would take one. So the runner posts most checks again after 2 s. Section D ran as pastes (job
`runner-small`, item 4). Left: the rows only Sam can answer. Section C is not wanted (Sam, 2026-11-16: "those
all seem correct"). E1: a new project's SC_.mdb holds SD19 to SD26 (`_RTC_Month` on SD21) only once the Address
Picker has been closed by OK (job E, item 4).

`try --keep` saves the project after each accepted case and decodes the save. That shows what CLICK stores
for a constant (job B, item 4: Math in decimal and hex, Copy into DS, DH, DF and TXT). Row A6's gaps ran as
plain `try` cases.

Long runs (BOB job `runner-grids`, 2026-11-16):
- `try` appends each case's answer to `DIR/cases.jsonl` as it comes.
- `--resume PREV_DIR` carries those answers and tries only the cases left, in a CLICK of its own. A case that
  stopped two runs (Ctrl+C aside) is not tried again.
- `--stop-after N` ends a run cleanly.
- A case's id is its `case` label.
- If a field or list is closed for entry, or reads back otherwise, the case becomes `not_taken` (once Cancel
  has closed the dialog) and the run goes on. If a field does not answer, the run stops, and the case is
  tried again on resume. So is a case whose Delete or save failed after CLICK answered it.
- Nothing starts CLICK again by itself. An unexpected window still stops the run, and the connect after an
  aborted connected run fails once.
- `try` also drives Receive (50060, B7). It picks the lists by sending Up and Down keys to the list
  (`choices`), and it never presses COM Port Setup.

laddercodec's `preflight.json` (92 cases, stopped after 40 and resumed) and `risky.json` (67) ran whole, with
`--keep`. Their answers are in the job folder as `<grid>.answers.json`, for laddercodec. What they answered:
- Receive's Starting Master Address, with Function Code 01: CLICK accepted Y001 and C1, and refused X001, T1,
  CT1, SC1 and DS1 (OBJ-004). With 03 (slave address 400001), it accepted DS1, DD1, DH1, DF1, TXT1 and YD0, and
  refused TD1, SD1, XD0, CTD1 and C1 (OBJ-004). It refuses a 984 slave address outside the function's range
  first (OBJ-010). The answer to each Receive case records the text of every open field just
  before OK was pressed. For Number of Master Addresses
  into TXT1, CLICK refused 1 (OBJ-010, range 2 to 250) and 3 (OBJ-029, even only), and accepted 2 and 4. Left
  unset, the field held 2 at OK (the dialog opens with 1) and CLICK accepted it. Into DS1, CLICK accepts 1 and
  2.
- CLICK accepts a single Copy or Pack destination with a space at either end and stores it with the space
  (laddercodec decodes the save as `raw(...)`). It drops the edge space of a Copy source and of a Math field.
- A hex Math accepts `0` and `5` without `h` (as job B found). It refuses `SUM(X001:X002)`, which laddercodec
  accepts.
- The answers now include each dialog's edit limit (EM_GETLIMITTEXT): Math result 26, formula 500, Copy source
  130, and 16 for a Copy destination, a range end and an Out address. The runner sets text by WM_SETTEXT, which
  no limit stops. So three risky cases set more text than a user can type (a 129-character quoted Copy source,
  and the quoted Out texts). CLICK refused them.

The Address Picker that a field's "..." button opens ("Address Picker : Pickup Mode", owned by the dialog)
greys the banks that the field does not accept, and it lists only the addresses that the field accepts. For a
Copy single or block destination and a decimal Math result, it lists the 29 SD of pyclickplc's `WRITABLE_SD`
and no SC. For Out, it lists the 25 SC of laddercodec's `WRITABLE_SC` and no SD. 28 new `try` cases (listed and
unlisted SD and SC in each field) agreed with the lists:
- CLICK refuses an unlisted SD in Copy (OBJ-004) and in Math (OBJ-003).
- It refuses a Block range that reaches an unlisted SD with OBJ-018 (or OBJ-004 past SD215).
- It refuses an unlisted SC in Out with OBJ-003.

So the lists answer laddercodec's `copy_sd_single`, `math_sd` and `out_sc` sweeps (3,000 cases) without
running them (`sc_sd_writable.json`). In `copy_sd_block`, every SD that a block reaches must be listed (SDn and
SDn+1 for the two-address blocks tried). Only Copy destinations and the decimal Math result were probed for SD.
laddercodec accepts every SD in those fields today. The picker's Find box did not move its grid in Pickup Mode.
Page Down and Page Up keys sent to the grid did. Left: the other grids (about 4 s a case), and the next
instructions in laddercodec's order (Compare contact, Timer, Counter, Search, Shift, For, Drum). Their ribbon
ids are known but not allowlisted.

Autocomplete's field map (BOB job `autocomplete-fields`, 2026-11-16): a probe in the job folder opened the
same picker from each field's "..." button. The probe's results, and 28 `try` cases that agreed with them, now
set the banks of CLICK v4's Receive, Send, Out, Set and Reset in `detection/window_mapping.py`.
- A v4 dialog's edits are numbered over every Edit window in it, including the hidden ones and the four inside
  the IP address control. So Receive's and Send's Starting Master Address is `Edit9`, their flags are `Edit15`
  to `Edit17`, and Exception Response is `Edit18`. The old map had `Edit5` (the IP address's last part) and
  `Edit11` to `Edit14` (hidden ASCII fields).
- Their Starting Master Address follows the Function Code list (`ComboBox2`, read when the popup shows).
  Receive FC 01 and 02 accept Y and C, and 03 and 04 accept DS, DD, DH, DF, YD and TXT. Send FC 05 and 15
  accept X, Y, C, T, CT and SC. Send 06 accepts DS, DH, XD, YD, TD, SD and TXT. Send 16 accepts DS, DD, DH,
  DF, TD, CTD, SD and TXT (laddercodec's masks).
- Out's Delay Setting edits (`Edit3` to `Edit6`, open for Debounce, Flasher and Timed) accept DS for a time
  and TD for a timer number, the same for each output type.
- Out, Set and Reset accept Y, C and SC. Out refuses X, T and CT (OBJ-004). Set and Reset have no delay
  fields.
- Only v4 is installed here, so the v2/v3 forms are unchecked. frmOut, frmSet and frmCoilReset accept Y, C and
  SC too, inferred from v4 and laddercodec's `OUT_BANKS` (one list for every version). frmRD and frmSD keep
  their field numbers and accept every function code's banks.
- Not mapped: the ASCII fields of Receive and Send, because the conformance PLC's project has no ASCII port.
- Follow-up: Copy's destinations use `ANY`, which offers banks that the picker greys there (runner-grids pk6):
  X, T, CT, SC and XD for a single Copy's destination, and YD too for a Block's.

### 4d. Importing a nickname CSV into CLICK (done)

`click_runner.py import CSV --out DIR [--each-row]` imports a nickname CSV through CLICK's File > Import >
Nickname (32900), in the mode Delete Existing, so that what CLICK stores comes from that file alone. It keeps
CLICK's answer ("Completed!", or the Import Error List's text), copies SC_.mdb and reads the copy. With
`--each-row`, it then imports each line in a file of its own with the same header. The live run for
pyclickplc's `tab_checks.csv` (19 rows, 20 imports) took 58 s. What CLICK did (live runs of 2026-11-15 and
2026-11-16):
- A row whose initial value or address CLICK refuses does not fail the file. The other rows import, and the
  error list names the refused line. (A quoted line break was tried only in a file of one row. CLICK reads it
  as the end of the line.) CLICK stores a row whose initial value it refuses with 0 as its initial value. It
  does not store a row whose address it refuses, and it writes that row's fields over the last row stored
  before it. Two files showed this, both on DS: `DS40` good, then `" DS41"`, leaves DS40 with DS41's nickname,
  initial value, Retentive and comment.
- A quoted nickname or comment loses the spaces and tabs at its ends, and a bare nickname loses its leading
  space. A tab inside is kept. A bare comment with an edge space or tab was not tried. So the import put no
  edge space in SC_.mdb. Q7 below stays open for a value typed in CLICK.
- A bare Text initial value loses its edge whitespace (a bare tab, vertical tab, form feed or space is stored
  as no value). A quoted one keeps it. A quoted comma and a doubled double quote import as `,` and `"`.
- CLICK accepts a bare number initial value with an edge space (` 5` and `5 ` are stored as `5`). It refuses a
  quoted one with an edge space or tab (`" 5 "`, `"<tab>5"`, `" 1.5"`).
- CLICK drops a bare space before or after an address. It refuses a quoted address with an edge space.

Runs of 2026-11-16 (job A):
- INT refuses `1_000`, `1e3` and `.5`.
- FLOAT refuses `1_000`. It accepts `1e3` (stored `1000`) and `.5` (stored `0.5`).
- `+5` is stored `5`.
- HEX refuses `0x1F` and stores `1F` as `001F`.
- A number with U+00A0 at an edge is refused, and so is `٥`. `５` and a U+3000 edge are accepted (as `5` and a
  space), but only from UTF-8 with a BOM.
- `DS030`, `DS0030` and `X0001`, bare or quoted, import under the plain address.
- The import refuses the reserved words tried (CLICK's `[NGWORD]`) in each letter case tried, as the Address
  Picker does (job F, item 4).

The Read Data dump and Project.ini's section case, left here before, ran as jobs D and C (item 4). These runs
answer the open check "(4b) CSV TXT quoting import", which is deleted. One finding went to pyclickplc.
pyclickplc 0.7.0 wrote a Text value without quotes when the value was a tab or had a space at either end.
CLICK's import then stored the value without that tab or space. pyclickplc 0.8.0 quotes such a value, and
CLICK's import keeps a quoted value (`test_a_txt_value_with_a_tab_or_edge_space_is_quoted`).

## 5. ConnectionSession owns the window and project (done)

The session opens on connect, before the database loads. It holds the window, the load token, the workspace
pairing, the connection watch, the popup and the Workspace setup window. `_close_session` is the one teardown.
The Workspace setup window now closes when CLICK's window closes (Sam, 2026-11-15). The project-info window
stays on the app, because it holds nothing of the connection and opens with nothing connected.

## 6. Split ClickNickApp (done)

The Workspace group, its menu entries and Workspace setup are `WorkspaceController`
(`workspace_controller.py`). `ConnectionController` (`connection_controller.py`) lists CLICK windows,
connects, loads the database, handles the project change and the watch tick, and runs the popup and
Start/Stop. `app.py` went from 3,017 lines to 1,883. Widget building stays on the app. So do `_open_data` and
`_close_data`, which write `_data`'s one home. These stay on the app, and each is a candidate for a later
split: the Tools and Repairs menu actions, launching Review Changes and Compare with,
`_export_pyrung_project`, and the unused `_check_odbc_drivers_and_warn`.

## 7. Onto pyclickplc's readers (done)

Plan 2. ClickNick reads and writes nickname CSVs with pyclickplc's `read_csv` and `format_csv`
(`CsvDataSource`), so one library writes the workspace's `nicknames.csv` and reads it for pyrung. ClickNick
keeps `_write_file` (the in-place write that keeps a Hidden file Hidden and names the Excel lock). It converts
`AddressRecord` to `AddressRow` at its boundary. Unifying the two models is not part of this.

What it changed:
- A Text initial value that CLICK exports bare as a comma or a double quote now loads. A save writes it, and
  it writes a space, quoted, so that it reads back as written.
- ClickNick refuses a file with a bad Address, a wrong Data Type or extra cells, as pyrung does, and names the
  line. In Review Changes the nicknames row says so. Whenever pyrung cannot convert the folder, the diff says
  why (`BundleSources.error`). A nickname used twice still loads in ClickNick (the store flags it), though
  pyrung refuses the file.
- `validate_nickname_format` and `detection/window_mapping.DATA_TYPES` are gone: `validate_nickname` calls
  pyclickplc's, and the combobox takes its prefixes from `BANKS`.
- `validate_click_name`, `read_plc_name`, `write_plc_name` and `iter_address_slots` come from pyclickplc 0.7.

What stays in ClickNick (Sam, 2026-11-15): its own `read_mdb_csv` for CLICK's `Address.csv`, which pyclickplc's
reader reads differently, and `convert_mdb_csv_to_user_csv`, which now writes through `format_csv`. The names
for unassigned I/O slots in `sim_hardware.py` stay too. Item 4d answered the open check on the Text quoting
import.

Left over (nothing): ClickNick's `read_mdb_csv` reads a blank DataType as BIT. The database path
(`mdb_operations`) reads it as the bank's type. Nothing shows that CLICK writes a blank DataType. If it did,
Save As CSV would write a file that ClickNick then refuses.

## 8. Onto pyrung's named imports (waits on pyrung's deletions release)

Plan 3. ClickNick imports these internal paths today. Move each onto pyrung's named home. Add a test that
fails when one disappears:

- `pyrung.click.tag_map`
- `pyrung.core` (`physical_response.py`: PHYSICAL_KEYS, FeedbackType and more)
- `pyrung.core.program.Program`
- `pyrung.core.analysis.build_program_graph`
- `pyrung.core.analysis.pdg`
- `pyrung.core.validation` and its `config`, `registry`, `report`, `stuck_bits` and `ordered_rules`
- `pyrung.dap.live`, `pyrung.dap.grammar`, `pyrung.dap.protocol`, `pyrung.dap.adapter` (some only in tests)

`dap_service.py` matches on a pyrung error string. That match goes with the console commands for every change
(item 10).

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

Moved from the sweep arc's `USER-CHECKS.md` on 2026-11-15. None blocks a release: before a tag, Sam gets a short
smoke test, and what the rest find goes into bugfix releases. Items marked (4b) a mock can automate; (runner)
waits on the CLICK runner (item 4). A check that is walked or automated is deleted here.

### Questions only CLICK can answer
- Q2 (runner): on File > Open, does SC_.mdb hold the opened project's rows when the title names it? Also, what
  does CLICK write on New Project, and when does its title change? (This bears on how soon kept edits are
  checked against the new project's database.) Sam: SC_.mdb changes every time you edit in CLICK's Address
  Editor. The rest is answered (item 4). Save As does not rewrite SC_.mdb. Open writes a new one before the
  title names the new project, and writes it once more after, while Project Reading still shows. A reader that
  goes by the title alone can catch that last write.
- Q6: after deleting all rungs, empty rungs are on screen. Is one of them selected for Ctrl+V, or must the step
  wording say to click the first empty rung? Sam (2026-11-16): "there are always empty rungs". Not to be
  automated.
- Q7: can SC_.mdb hold a nickname or address comment with a space at either end, typed in CLICK? (CLICK's own
  CSV import put none there, 4d.) ClickNick trims such a value on load as an unsaved edit ("Trim spaces"). If
  the answer is yes, the next Sync writes the trimmed value into CLICK. The recorded `tests/SC_.mdb` and
  `NicknameExport.csv` hold none.
- Q8 (CLICK v2/v3 only): autocomplete's map for the v2/v3 dialogs is inferred from v4. In an Out, Set or Reset,
  does CLICK refuse X, T and CT? (ClickNick no longer offers them.) In a Receive or Send, do the master
  address (Receive's `Edit20`, Send's `Edit16`), the flags and the exception field get the popup? ClickNick
  offers every function code's banks there.
- Q10 (runner, non-English Windows): does the redraw after a Sync complete? The live runs were on an English
  Windows. ClickNick recognises the Open dialog and its buttons by their control ids and the three import
  modes. It recognises the "Completed!" box by its title, its text and its one button. So Windows' own "Open",
  "OK" and "Cancel" can read otherwise. ClickNick assumes that CLICK's strings ("Merge (Project priority)",
  "Completed!", "Import Database", "Import - Project priority") are English on every Windows.
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
