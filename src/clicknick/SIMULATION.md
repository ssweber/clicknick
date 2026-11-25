# Simulation

Nothing loads this file automatically. The table in the root `AGENTS.md` says when to read it.

These notes cover `simulation_session.py` and the code that it drives: the simulation services
(`services/dap_service.py`, `services/sim_state.py`, `services/program_carry.py`,
`services/link_annotation.py`, `services/program_stops.py`), the Simulator (`views/simulator_window.py`, `views/console_panel.py`) and the
Dataview Editor's link to the simulation.

## Rules

- Add no new structured DAP request for a panel change. See "Commands".
- Desired state is what the user chose for the simulation: the switches, the forces and the bench links. Key
  it by CLICK address. It never holds a tag name.

## Who owns it

- `ConnectionSession.simulation`, a `SimulationSession`, is the one home of the simulated PLC. It holds the
  pyrung DAP subprocess, its Modbus client, the switch, analog and force settings, and the saving of those
  settings (`services/sim_state.py`).
- It runs headless. `turn_on()` starts it, and opening the Simulator calls `turn_on()`. Only `turn_off()` or
  connection teardown stops it. The Start/Stop button beside the main window's Test legend calls `turn_off()`.
  Closing windows never stops it.
- ClickNick does not save the on/off state. At app start, nothing launches a subprocess or listens on port 502.
- The Simulator and the Dataview editor only observe the simulation. The Simulator's Console pane is
  `views/console_panel.py`. The Dataview attaches while the simulation serves Modbus. While the simulation is
  off, both windows stay open and offer Start.

## How ClickNick talks to it

- The session launches pyrung with `keepForcesOnRun`, so forces survive STOP -> RUN. The switch and analog
  patches go with `set_mode("run")`.
- ClickNick reads values over Modbus. Inputs (switch and analog patches), mode, speed, stepping, forces and
  links go over DAP.
- The Data View reads and writes values over Modbus, with the same client as for a real CLICK. That client
  refuses an X write. The Simulator's Modbus server accepts one, as a CLICK does, so a client outside
  ClickNick can change an input. The Data View's Force column goes through the simulation.
- A frame is an update that pyrung sends about the mode, the scan, the forces and the links. Mode, speed and
  forces follow the frames, because the Console and agents can drive the same simulation. The last command
  takes effect.
- When the user acts on the panel, the session emits an `echo` event with the equivalent console command. It
  writes the tag names with `to_tag()`. The console pane shows the command as a comment. Only actions that
  reach a running simulation echo. Analog values echo once they settle.

## Commands

Panel changes (switches, analog values, forces, mode, step, speed, links) go as structured DAP requests today.
Add no new one. The design that replaces them is in `scratchpad/visual-simulator-design.md`, in the section
"Commands and recording".

The Console pane splits a line on `;` (`ConsolePanel._submit_command_text`). Its `autoreload` and `reload`
refusals rely on that split.

## Bench links and names

- A bench link is feedback wiring that the user adds in the Simulator and the program does not declare
  (`sim_state.BenchLink`, keyed by feedback address). Bench links are desired state, like forces. ClickNick
  saves them. It applies them again over DAP after every launch, until the user removes one. It adopts them
  from the simulation when a frame's `linksRevision` changes, because the Console can edit them too.
- "Save to project" in the Simulator window writes the link into the feedback's comment through the store
  (`services/link_annotation.py`). It does not remove the bench link, and ClickNick keeps applying it. After a
  Sync and a rebuild, pyrung drops the bench copy, because the program declares the same link.
- pyrung reports tag names. ClickNick maps them with the names of the program that the simulation runs
  (`_tag_maps`). Those are the workspace's `project_tag_to_addr_key`, which the session takes at launch and at
  each write. So a rename in CLICK does not move desired state until that program is written.
- When the session loads its saved settings, `load_state` skips and lists each force whose key is not a CLICK
  address, and each bench link whose key is not an address or whose value does not parse. The session reports
  each one as an error.

## Bench links on an address that no rung names

- pyrung knows the tags that a rung names (`_known_tags_by_name`). Its `link_problem` refuses a link whose
  feedback or enable is any other tag, with `cannot link X001: unknown tag: X001`. From pyrung PR #119
  (after 0.18.0), pyrung words the refusal differently when the project's TagMap or bank blocks give the
  address a tag: `cannot link X001: no rung uses X001, so the program has no tag for it`. If the TagMap names
  the address `Start`, the text is `cannot link Start: no rung uses Start (X001), so the program has no tag
  for it`. After "no rung uses", the text names the end that pyrung refused, which can be the enable. A slot
  that a rung reaches only through a range is not known. With pyrung 0.18.0, `pack_bits(X003..X010, DS1)`, in
  the form that ClickNick generates, was observed to make pyrung know none of X003 to X010.
- pyrung was observed to accept a force or a patch on such a slot. A patch on X005 moved DS1. It refuses a
  force or a patch on an address that no rung names or reaches and that the project's TagMap does not map,
  with `Unknown tag 'X002' (address X002 is not mapped to a tag)`. The Console's `why` answers for any
  address. `simplified` and `how` answer for a slot that a rung reaches, and refuse any other address that
  pyrung does not know.
- The Simulator draws every point the same way, and every action works on every point. A link drag can start
  and end on any point. Only a bench link depends on the named addresses.
- Each frame lists the tags that pyrung knows (`tagTypes`). `DapService.program_tags` holds them. The session
  maps them to addresses with the running program's tag names (`named_addresses`, read in `_on_frame` and
  after a write). The set is `None` while the simulation is off, from a launch until its first frame, and
  from a write's reload until the frame after it.
- A bench link waits when ClickNick holds it back because pyrung would refuse it (`link_waits`). ClickNick
  keeps it in the desired state and saves it. `links` lists it with `waiting=True`, the **Wiring** menu shows
  it as `bench, waiting`, and the frame that adopts pyrung's links keeps it. No error is shown.
- While ClickNick holds the named set, it decides from the set whether a link waits, and sends nothing for a
  link that waits. `link()` does this, and so does a write once the frame with the new tags has arrived.
  While the set is `None`, the session sends the link. Whenever pyrung refuses a link with "unknown tag" or
  "no rung uses", the link waits (`_held`). The match ignores case. A link leaves `_held` when pyrung lists it
  as a bench link, when the user changes it, and when the simulation stops. If the user only disables or
  enables a held link, the link stays in `_held`.
- A link that waits is not in the simulation, so the simulation runs the program's own wiring on its
  feedback. `_change_links` keeps the two in agreement. When a change in ClickNick makes a link wait, or
  drops a link that waited, it restores the program's wiring on that feedback (`_restore_bench`) if pyrung
  lists a bench link or cut there. That covers a waiting link that replaces a running link or a cut, and
  `restore_link`, `set_link_enabled` and `discard_bench_links` on a link that waits. When pyrung refuses a
  link for an unknown tag, `link()` restores the feedback too. pyrung checks a link before it replaces
  anything, so the link that the refused one was to replace still runs. `links` lists one bench row for
  each feedback. A link that waits hides a bench row that pyrung still lists there until the next listing.
- A listing can predate a link change. pyrung answers it, and the user changes a link before ClickNick
  reads the answer. `_change_links` counts the changes (`_links_edits`), and `_fetch_links` passes the count
  from when it asked to `_on_links`. If the count has moved, `_on_links` only shows the rows. It does not
  copy them into the settings, and the next frame asks for the links again.
- A write sends each waiting link again after the reload, unless the frame with the new tags shows that a
  rung still does not name both ends. If pyrung drops a link or a force as `gone`, the new program does not
  have one of its tags, either end of a link. The link then waits, and the notice says so. The force goes
  again by address to where the plan put it. Every other drop reason, such as `conflict`, `in program`,
  `invalid` or `unlinked`, loses the entry as before.
- The notice that an earlier write showed may name a link that no longer waits. A write with nothing new
  to report replaces that notice with one that names only the links that still wait. If no link waits, it
  clears the notice.
- The texts never say that the program does not use an address, because a range can reach it. They say that
  no rung in the simulation names it.

## A switch on an address that pyrung cannot resolve

- Switch and analog values stay in the desired state on any address and go with every patch. pyrung 0.18.0
  was observed to refuse a whole `patch` or `set_mode` request when it cannot resolve one address in it. The
  refusal names that address as an unknown tag.
- Every patch that the session sends goes through `_send_patches`. That covers a switch, a button, an analog
  value, the switch to RUN, the settings after a launch and the inputs after a write. When pyrung refuses
  the request with "unknown tag" and names an address in the patch, `_send_patches` sends the request again
  without that address. The match ignores case. Each retry leaves out one more address, so the loop ends.
  No error is shown for a left-out address. Any other refusal raises, and its error is shown as before.
- The switch, its shown position and the saved setting stay. The session remembers no left-out address, so
  the next patch sends it again. After a write whose program resolves it, the next patch applies it. In RUN
  and STEP, that is the patch that the write sends after the reload.
- In a workspace that ClickNick generates, pyrung 0.18.0 was observed to resolve every CLICK address that
  was tried through the workspace's TagMap. With a CPU and no rungs, X001, X101, X816 and DF5 resolved. With
  one rung on X001, X002 resolved. An address goes unresolved when the workspace's TagMap does not map it
  and no rung names or reaches it, as with a hand-written `TagMap({})`.

## Restoring saved settings

- The session applies the saved switches, analog values, forces and links at launch, whatever the hardware.
- `_restore_when_known` trims only the analog values, to the DFs that an installed analog input has. Only a
  module assigns a DF to an analog input, so it waits for a hardware configuration with a CPU that it could
  read. It does not wait for a build. Until then nothing is trimmed, and the saved `modules` stay in the file,
  because `_save_now` writes `modules` only with a CPU.
- Nothing trims a switch, a force or a bench link. A switch on an X address that no module provides stays.

## Writing a changed program

The workspace is the pyrung project that ClickNick generates from the connected CLICK project.

- pyrung's autoreload is off. A changed program reaches the simulation only when the user writes it. Two events
  offer a write as `program_change`:
  - A new analysis generation. That is a CLICK save, or "rebuilt" when the save count did not move, as after
    Reload from CLICK or a Sync.
  - An edit to the workspace's `src/plc` (`PlcSourceWatch`, checked on the 2 s watch tick).
- In RUN, the offer is **RUN Time Edit** or **Stop and Write**. RUN Time Edit reloads and continues, and values,
  timers and forces stay. Stop and Write reloads, goes to STOP and goes to RUN again in the same process. pyrung
  then keeps the retentive values and forces and clears the rest.
- In STOP or while stepping, the offer is **Write**. Values and mode stay.
- A Console `reload` writes for the current mode. The Console pane refuses `autoreload`.
- An agent on `pyrung live` can still reload, or change forces and links while a write runs.
- A build that fails is a notice, and the old program keeps running.
- When a build finishes for the program that the simulation already runs, no write is offered. This happens
  after a Sync, or a Reload from CLICK, that leaves the program as it was. The program is the same when its tag
  names, `src/plc` and `run.py` are the ones that the session read at the launch or the write
  (`PlcSourceWatch.same`). A file that could not be read at either time proves nothing.
- The watch tick and each frame compare a build once (`_examine_build`). `program_change` only reads the result.
  It offers nothing for a build that has not been compared yet.
- One check says whether the workspace's program can run (`_workspace_problem`). It needs a conversion that
  succeeded, a current workspace, a `run.py`, and no empty stand-in rung (`_stand_in_reason`). Start, a write
  and Restart all use it. If it refuses a write or a Restart, the simulation keeps running and a notice says
  why. A rung that the workspace holds as pyrung's `undecoded()` marker does not refuse. See "A program that
  stops at a marker".
- A write (`_write_program`) is one job on the action worker. The Console refuses commands until the write is
  answered. No write is offered while a Console command runs. The Restart button is disabled until the write is
  answered, and `restart()` refuses with a message meanwhile.
- Console commands run through `run_console_command`, which counts each command in flight until it returns. So
  closing the pane in the middle of a command does not hold writes back. While that count is above zero
  (`console_busy`), every pane shows busy and offers Stop. The offer to write says that a Console command is
  still running.

## A program that stops at a marker

When ClickNick cannot read a rung from CLICK, the workspace holds pyrung's `undecoded()` marker in its place.
Inside a For loop, and for a `next()`, it holds an empty stand-in rung instead (`is_stand_in`).

- pyrung leaves out every rung after a marker in the same main program or subroutine. The simulation runs the
  program up to the marker. The PLC runs the rest.
- A stand-in refuses the launch, a write and a Restart. The simulation would run the empty rung and look
  right. `stand_in_findings` reads the workspace's `csv/` to tell a stand-in from a marker, because both come
  with the same finding in `legacy_encodings.json`.
- The session keeps the markers of the program that runs (`_program_stops`). The user can edit `src/plc`, so
  they come from the source that pyrung loads, not from the analysis build of CLICK's save. A launch and a
  write each read them (`read_program_stops`, `services/program_stops.py`) on a thread beside pyrung's load
  (`_StopsRead`). A process of its own imports `plc.main` and lists its markers, as `clicknick-cli check`
  does. So the app never imports the workspace's code. pyrung's DAP prints its own notice only as Console
  text, and that text names a subroutine by pyrung's name. Like `PlcSourceWatch`, the read sees `src/plc` as
  it was at the launch or the write. A later edit is offered as a write.
- The worker writes its answer to a temporary file, because the workspace's source may print to stdout.
- The read takes about as long as a Python start that imports pyrung, near 0.8 s. A launch hides it behind
  pyrung's own start. A write waits for it, and pyrung's reload alone takes a few hundredths of a second. So a
  write does not read again while `src/plc` and `run.py` match the snapshot that the last good read took
  (`_stops_reading`, `PlcSourceWatch.same`). It keeps those stops. A launch always reads. A build of a CLICK
  save writes `src/plc` again, so the write after it still waits for the read.
- If the read fails or times out, the session keeps the stops that the program had. If it had none, it uses
  the markers of the latest build (`AnalysisService.undecoded_rungs`). It sends the failure as an error, and
  the Simulator shows that as a banner. pyrung imports the same source, so its launch or write usually fails
  too.
- `stop_notice` names each program and CLICK rung where the program stops. The Simulator shows it as a banner.
  The banner has no Dismiss button. It stays while the program runs. The session also sends the notice to the
  Console at each launch, and after a write that changes the rungs.
- The panel shows the X and Y points that the latest build uses (`_used_io`), plus every point of an
  installed module. That build leaves out the rungs after its own markers, so a point that only those rungs
  use drops off the panel. Until the next write, the build can differ from the program that runs. So the
  notice says only that the panel can leave out such a point. ClickNick does not mark such points. It would
  have to read the program's CSVs again to list them, and the Simulator draws every point the same way.

## Carrying forces and links

The write reads pyrung's force and link listing. That listing is the truth, whatever the Console did since the
last frame. `plan_carry` (`services/program_carry.py`) decides each entry's name in the new program. One
`pyrungReload` (`DapService.planned_reload`, pyrung 0.16) takes the plan (`CarryPlan.as_dap()`). pyrung first
pauses a running continue, keeps the mode, and places each entry. An entry that the plan leaves out keeps its
name. That is an entry that the Console added after the listing.

- A bench link follows its names while they exist. The notice says when one now sits on another address.
  Otherwise the link stays on the address under its new name. When two links land on one feedback, the plan
  keeps the one that followed its name and drops the other.
- A force stays on its address under the new name on a pure rename. An unnamed address that gains a nickname
  counts as a pure rename. A force whose name now sits on another address stays only on X, Y or an analog
  channel's DF. On internal memory the plan releases it.
- A link that the program declares and runs (`declared`) follows its feedback's name while the new program
  declares a link on that name. The plan reads the declared links from the workspace's `csv/nicknames.csv`
  (`linked_feedbacks`). When the name is gone, or sits on an address with no declared link, the link's coil
  carries on at its address under the new name.
- A bench link or declared link that moves keeps its coil's state, so a timer part way through carries on.

The offer lists releases, drops and moves before the user writes. After the reload, pyrung's report
(`carried`) is the truth. ClickNick adopts the entries that pyrung placed, by address. The notice
(`CarryPlan.written`) keeps the plan's notes for the entries placed as planned. It also says why pyrung could
not keep any other entry. It does not list a drop that loses nothing, such as a link that the program now
declares.

Suppose a write is answered after another build started. The session keeps the old names and offers the change
again. No build counts as run until the next write or launch, because nobody knows which program pyrung read.
The switch shows the position that it had until the write is answered.

## When a write fails

- A reload that fails changes nothing in pyrung. The old program keeps running with its forces and links. A
  write made in RUN sends continue again, because pyrung may have paused. **Restart** is added to the offer.
- A pyrung without `pyrungReload` refuses the write the same way, with a notice that it needs pyrung 0.16.0.
  Nothing falls back to releasing and sending entries again around a plain reload.
- Suppose pyrung never answers a reload. ClickNick then sends nothing by name, because nobody knows which
  program runs, and it offers Restart. Its notice says that the simulation may be paused, and it names what the
  plan releases. The switch position stays the user's (`_position_held`). So Restart starts in that position,
  and the write offered is for that position, until the user moves the switch.

## Restart

**Restart**, which is also on the toolbar, launches the simulation again on what the workspace holds now. It
starts from power-on values or the PLC data file, with the same desired state and switch position. These events
do the same:

- Start.
- A change to the PLC data file while a simulation runs.
- A change to the Modbus port.
- A later build that converts, when the simulation failed to start (`_follow_program`).

A PLC data file change and a Modbus port change wait (`_restart_due`). If one is seen during a write, the
relaunch comes once the write is answered, unless the simulation relaunched meanwhile. If one is seen while a
build runs, the relaunch comes once the build ends.

When you pick the PLC data file, when the watch tick sees it change, and at Start when it changed since the
last read, the session sets the switches and analog inputs from it (`_adopt_snapshot`). A Restart reads it
only through Start, when it changed. pyclickplc raises `PlcDataReadError` when it cannot tell what some Text
addresses hold. The error's `values` has every other address, and its `addresses` lists the unclear ones. The
session sets the switches from `values`. Once the next launch succeeds (`_on_launched`), the session's notice
names `addresses`, as an error message. A launch that fails shows no such notice. At launch, pyrung 0.17.0
skips the same addresses and loads the rest. It names them in an `output` event and in the launch response's
`skippedAddresses`. The session ignores both, so you read only ClickNick's notice. The session leaves any
other failure to read the file to pyrung's launch, which reports it.

`start()` records the file's modification time and reads a changed file into the switches
(`_plc_data_changed`). So the next watch tick does not restart the simulation a second time. When the user
saves the file again, the watch tick restarts the simulation from it.

A workspace move relaunches through `relaunch`, without Restart's check. So it stops the running simulation
even when the moved workspace cannot run. It waits out the build.

After a launch, `_reapply` sends every entry, even when one goes unanswered. An unanswered entry stays set and
is reported. An unanswered link listing is asked for again on the next frame.

A failed DAP request undoes the user's action only when the simulation that was asked refused it. It does not
undo the action when the simulation has since stopped or restarted (the token check) or never answered
(`DapUnavailableError`).
