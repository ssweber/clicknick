# Visual Simulator — Design Notes

Design session 2026-10-18. Implemented on branch `feat/simulator` in pyclickplc (834a6c4), pyrung (100785c8)
and clicknick (f68e5a9). Not released yet. Re-grounded 2026-10-21: Modbus input writes dropped (below), links added.

## Agreed design

### Two channels

- **Modbus = data plane.** A `ClickServer` plus pyrung's `ClickDataProvider` run inside the pyrung DAP subprocess.
  The Dataview connects to it the same way it connects to a real PLC.
- **DAP = control plane.** Forces go over DAP structured requests (`pyrungForce` / `pyrungUnforce` /
  `pyrungListForces`), not a custom Modbus command. Modbus has no concept of a force, and CLICK uses a separate
  Override channel for this too.
- Values are read over Modbus. Inputs (switches, analog), mode, speed, stepping, forces and links go over DAP.

### I/O panel

- **X = switches only.** A switch sets a latched patch. The panel never forces X.
- **Y = LEDs.**
- **Analog = entry boxes** that patch the assigned DF.
- ~~Sim-only Modbus option: the server accepts writes to X.~~ Dropped 2026-10-21, see
  [Modbus input writes](#resolved-modbus-input-writes-are-not-needed).
- The Dataview gets a Force column only while it is attached to a sim session.

### CPU mode switch

- Three positions: **STOP / STEP** (neutral position, label TBD) **/ RUN**.
- The position is derived from frames (mode + running). The last command wins, because the Console and agents can
  drive the same simulation.
- Forces survive STOP -> RUN through an opt-in: a pyrung runner setting plus a DAP launch arg (`keepForcesOnRun`),
  which the simulator turns on. `PLC.mode`, `pending_patches` and `start()` became public pyrung API.

### Lifecycle

- One sim session object (not `ConsoleWindow`) owns the `DapService`, the Modbus port, desired forces and switch
  state. It re-applies them after STOP -> RUN, reboot or relaunch.
- The simulation can run headless. There is an on/off toggle in the main window, and it turns on automatically when
  the Console or Simulate window opens. Closing windows does not stop it. The on/off state is not persisted across
  app restarts.

### UX

- Front-door **Simulate** button.
- Opens in STOP, with the RUN switch highlighted (pulsing) until it is first used.
- Switch positions and forces are remembered between sessions. They are stored in
  `%LOCALAPPDATA%\ClickNick\simulator\<PLC name>.toml` (same key as workspaces) until a workspace is chosen, then
  moved into `<workspace>/simulator.toml`. The workspace copy wins on conflict.
- Hardware is configured only in CLICK's System Configuration. ClickNick has no hardware picker.

### Known pyrung gaps — addressed on the pyrung branch

- ~~An unpaced continue runs timers too fast.~~ `speed` launch arg / `pyrungSetSpeed` pace Continue to real time.
- ~~Live-command results emit no DAP events.~~ `LiveServer` now forwards a live command's events, its trace and a
  `pyrungScanFrame` (`source.origin = "live"`).
- ~~The runner is not thread-safe for Modbus writes.~~ `SessionDataProvider` reads and writes under the adapter's
  `_state_lock`.

### Open TODOs

- Simulate action icon.
- Simulator screenshot in the docs.
- docs-build not run.
- Release order: see [Modbus input writes](#resolved-modbus-input-writes-are-not-needed); pyrung no longer needs a
  new pyclickplc floor.

## Resolved: Modbus input writes are not needed

The question was whether every simulator action can go over DAP, so pyclickplc needs no "accept writes to X"
option. It can. Nothing on the branch needs Modbus writes to X.

### Findings

- A Modbus write to X runs `ClickServer` -> `SessionDataProvider.write` (under `_state_lock`) ->
  `ClickDataProvider.write` -> `runner.patch({tag: value})`. `pyrungPatch` over DAP ends in the same
  `runner.patch`, and since this branch it resolves CLICK addresses (`X001`) itself. The effect and scan timing
  are identical.
- `SimulationSession` already uses DAP for inputs in most paths: `_reapply` and `set_switch_position` send
  switches and analog values with `pyrungSetMode(patches=...)`, and `_write` / `set_analog` fall back to
  `dap.patch` when the Modbus server is not up. Modbus is a second route to the same call.
- The only other user is the Dataview (`allow_input_writes = self._sim is not None`), so Write Checked / Write All
  can hit X rows while it is attached to the simulator. A real CLICK rejects those writes too. The Force column
  (DAP) is the sim-only way to override an input from the Dataview.

### Plan

- **ClickNick:** switches, pushbuttons and analog entries always go through DAP patch. That gives one command path,
  which the Console-echo idea below also wants. The sim's Modbus client becomes read-only polling. Drop
  `allow_input_writes=True` from both `connect` calls and `"allowInputWrites": True` from the launch args. While
  the Dataview is attached to the sim, X rows behave as they would on a real PLC: writes are rejected, so force
  them instead.
- **pyrung:** drop `ModbusConfig.allow_input_writes`, the `allowInputWrites` launch key, the
  "(X inputs writable)" banner, the `modbus_info` field and their docs and tests.
- **pyclickplc:** revert `allow_input_writes` in `server.py`, `client.py` and `modbus_service.py`, along with its
  docs, tests and changelog line. **Keep `read_io_layout`.** The panel needs each module's analog DF assignments
  in channel order. `read_channel_parameters` returns unordered frozensets, so it cannot provide that, and
  Project.ini parsing belongs in pyclickplc. The pyclickplc change becomes purely additive: one new function, plus
  an internal refactor that `read_channel_parameters` shares.
- **Release order:** pyrung's only use of the new pyclickplc API was `allow_input_writes`, so pyrung no longer
  needs a raised `pyclickplc>=` floor. pyclickplc and pyrung release independently, then ClickNick pins both.
- **Revisit if** external plant simulators (Factory I/O and similar) need to write the sim's X over Modbus. Even
  then, only the server needs the option.

## Links (feedback wiring) as a first-class visual

### What exists

- **pyrung:** a feedback tag declares `physical=` (bool `on_delay`/`off_delay`, or a `ramp`/`approach`/`pulse`
  profile) and `link=<enable tag>[:<trigger>]`. This round-trips through the CLICK comment (`TagMeta`). At launch
  the DAP auto-installs a `Harness` when any coupling exists. The harness lowers each coupling to plant rungs that
  run before logic, in the input-read phase. Console verbs: `harness status|install|remove`.
  `Harness.unlink(tags)` exists for fault injection, but nothing can add a coupling at runtime. The only way a DAP
  client sees couplings is the text of `harness status`.
- **ClickNick:** the annotation dialog edits `physical`/`link` in the comment. The simulator knows nothing about
  links.
- **Consequence today:** a linked X still shows a switch, but the switch does nothing useful. Plant rungs rewrite
  the feedback every scan before logic runs, so a patch is overwritten (to verify). A force still wins.

### Two kinds of link

- **Project link (permanent):** lives in the feedback tag's comment. It is written through
  `AddressStore.edit_session` (`AnnotationService.recompose_comment`) like any other comment edit. It reaches the
  sim only after Sync -> build -> relaunch, because the generated project comes from CLICK's DB snapshot.
- **Bench link (session-only):** lives in `SimulationSession`'s desired state next to forces and switches. It is
  sent over DAP and re-applied after relaunch and STOP -> RUN, like forces. It never touches the comment. Use it to
  try out commissioning ideas.
- **Cut:** the bench can also cut a project link, to simulate a failed sensor or a stuck contactor. The input then
  becomes a free switch again. `Harness.unlink` already models this.

### Model: the store's base + overlay, again

- **Declared** = the links from the build's metadata (the base).
- **Overlay** = `{feedback: LinkSpec | None}`, where `None` means cut.
- **Effective** = declared merged with the overlay. This is what the harness runs and what the panel draws.
- **Promote** ("Save to project") writes an overlay entry into the comment. Once a later build declares the same
  link, the overlay entry equals the base and is dropped, the same way `_rebase_override` drops matching edits.
  Until then, the bench copy keeps the link alive in the running sim.
- **Discard** clears the overlay.

### Visual

- **A linked input terminal is not a switch.** Show a driven indicator plus a chip: `← Y001 · 2s/0.5s`, or a ramp
  glyph and target for analog. While the dwell is running, the chip shows progress.
- **Ends:** hovering or selecting a link highlights both ends (the output LED and the input). Draw a wire overlay
  between the two terminals only on hover or select. Cards sit in physical order, so drawing every wire all the
  time would be spaghetti.
- **Style by source:** project link solid, bench link dashed in an accent colour, cut link shown as a broken-wire
  glyph on the input with the switch enabled again. A promoted link waiting for Sync gets a "pending Sync" badge.
- **Enable not on the panel:** the enable can be a C bit, a DS value with a trigger and so on. In that case the
  chip shows the nickname and gives nothing to highlight.
- **Create:** drag from an output LED to an input terminal, or right-click an input and choose "Link to output…".
  A popover asks for on/off delay, or for analog targets the profile, plus a trigger value for integer enables. It
  creates a bench link and has a "Save to project" button.
- **Right-click a linked input:** Edit, Cut (simulate failure) / Restore, Save to project, Remove (bench only).
- **Wiring list:** a drawer or tab listing every effective link with a Project / Bench / Cut / Pending Sync
  badge, plus "Save all to project" and "Discard bench changes".
- **Console echo:** every action maps to a console command (`link X002 Y001 on=2s off=500ms`, `unlink X002`,
  `restore X002`). This fits "Simulator actions echo into the Console" below.

### pyrung work

**Status 2026-10-21: implemented on pyrung `feat/simulator` (uncommitted).**

- `Harness.declared()` / `set_overrides()` / `pending()`, plus `link_problem()`; `unlink` is now a cut override.
- `pyrung.dap.links` keeps the overlay on the adapter and adds the `link` / `unlink` / `restore` / `links` verbs.
  `dap/handlers/link_requests.py` adds `pyrungLink` / `pyrungUnlink` / `pyrungRestoreLink` / `pyrungSetLinks` /
  `pyrungListLinks`. Frames carry `linksRevision`.
- `try_auto_install` (launch, reload, replay, `harness install`) refits the overlay to the new program. A bench
  link the program now declares the same way is dropped; that is the "promote then rebuild" path.
- Capture records the link verbs, including DAP requests, as console commands. Replay runs them only with
  `--harness current`.
- PILOT (`how`) carries the runner's overrides into its own harness, so it plans with the bench wiring.
- Comments: `link=Y001` reads as the nickname at Y001 (or `Y001` when unnamed), and `link=Tag:trigger` parses.
- Not done: per-coupling dwell progress (only the `pending` flag exists).

Original plan:

- `Harness`: keep declared couplings apart from runtime changes. Add `link(fb, en, physical, trigger=None)`,
  `unlink(fb)` and `restore(fb)`, each rebuilding the effective synthesis. Allow an installed harness with zero
  couplings, because `try_auto_install` currently uninstalls when it finds none.
- Resolve CLICK addresses for both ends with `resolve_target_locked`, as force and patch now do.
- DAP: `pyrungLink` / `pyrungUnlink` / `pyrungListLinks`, mirroring the force trio, plus console verbs.
  Couplings carry a `source` field (`declared` / `session`), and cut declared links are listed too. Frames
  carry a links revision, so clients refetch only after a change, wherever that change came from.
- Report per-coupling pending dwell or progress for the chip. Only the aggregate `pending_count` exists today.
- Capture/replay records the link verbs, so a replay reproduces the bench wiring. Check how this interacts with
  `--harness current|recorded|off`.
- Validation: reject a bench link whose feedback the program writes, or whose feedback is `readonly`.

### ClickNick work

- `SimState.links` persisted in `simulator.toml` (decision below). `SimulationSession` gets `link` / `cut` /
  `restore` / `remove` / `promote`. It re-applies links after relaunch, before `set_mode("run")` the way forces
  are re-applied, and adopts link changes made from the Console the way `_adopt_forces` does.
- **Promote** needs the current `DataSession`'s store. Give `SimulationSession` a getter (rule 6), not a copy.
  Today `link=` in a comment takes nicknames only, because the harness looks up `_known_tags_by_name`; the
  decision below adds CLICK addresses.
- The panel layout gains a per-terminal link state. `sim_hardware` stays pure data; the link state comes from the
  session, not from the layout.

### Decisions (2026-10-21)

- **Bench links persist** in `simulator.toml`, like switches and forces, with a Bench badge and a restored-count
  notice like the one for restored forces. "Session-only" means "not in the project", not "forgotten".
- **Easy toggle:** one **Bench wiring** on/off switch on the simulator. Off sends the declared (project) links
  only; on applies the overlay again. The overlay is kept either way. Each bench entry also has its own enable
  checkbox in the wiring list, so one link can be compared without deleting it. Because the adapter owns
  the overlay, both are adapter state: the master switch is `links bench on|off` / `pyrungSetLinks`, and each entry
  carries an `enabled` flag. Disabled entries stay listed, and the Console sees the same state.
- **`link=` accepts CLICK addresses** as well as nicknames (a pyrung parser and harness change), so promoting
  works for unnamed points. When both ends have nicknames, promote writes nicknames.
- **Dataview X writes** while attached to the sim are rejected, as on a real PLC. Users press Force.

### pyrung link decisions (2026-10-21)

- **Scope:** the first cut covers bool dwell (`on_delay`/`off_delay`), trigger values and all three profiles
  (`ramp`/`approach`/`pulse`). The harness already lowers all of them, so the extra work is the popover fields.
- **Ownership:** the pyrung DAP adapter holds the overlay. It keeps declared and session links apart, re-applies
  session links across `reload`, and lists each link with its source. The Console, VS Code and `pyrung live`
  all see and edit the same bench wiring. ClickNick persists the overlay in `simulator.toml` and re-sends it after
  a relaunch, the way it handles forces.
- **Console syntax:** comment-style keys, so what you type is what promote writes:

  ```
  link X002 Y001 on_delay=2s off_delay=500ms
  link DF5 Y003 profile=ramp:up=0.8|down=-0.05
  link X010 State:3 on_delay=1s
  unlink X002        # cut a project link / remove a bench link
  restore X002       # back to the project link
  links              # list with Project / Bench / Cut
  ```

  The feedback comes first, then the enable (`[:trigger]`), then the `physical` keys. The physical name
  defaults to the feedback's name, which the comment format already omits when it matches.
- **Validation:** reject a bench link whose feedback the program writes (an OUT coil, or a C bit set by logic)
  and say which rung writes it. Reject `readonly` feedbacks too.

### Open

- Draw wires on hover/select only, or offer an "always show wiring" toggle?

## To re-evaluate

### Right-click menu on simulator elements

Right-click on an I/O element (or a tag) opens a menu with actions such as **Why**, **How** and **Simplified**. These
would be the same analysis commands the Console offers, aimed at the element under the cursor. The link actions
above join this menu.

### Simulator actions echo into the Console

A change made on the graphical simulator shows up in the Console as the equivalent command (for example
`patch Tag`). That way the user sees and learns the command language, and the GUI and the Console share one
command path. Routing all inputs through DAP (above) is the first step. Frames already carry
`source = {origin, command}`.

The Console could be re-imagined as a **drop-down / tear-off window** attached to the simulator rather than a
separate standalone window.
