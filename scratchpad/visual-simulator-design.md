# Visual Simulator — Design Notes

Design session 2026-10-18. Implemented on branch `feat/simulator` in pyclickplc (834a6c4), pyrung (100785c8)
and clicknick (f68e5a9). Not released yet.

## Agreed design

### Two channels

- **Modbus = data plane.** A `ClickServer` plus pyrung's `ClickDataProvider` run inside the pyrung DAP subprocess.
  The Dataview connects to it the same way it connects to a real PLC.
- **DAP = override back-channel.** Forces go over DAP structured requests (`pyrungForce` / `pyrungUnforce` /
  `pyrungListForces`), not a custom Modbus command. Modbus has no concept of a force, and CLICK uses a separate
  Override channel for this too.
- Values travel over Modbus. Mode, speed, stepping and forces go over DAP.

### I/O panel

- **X = switches only.** A switch sets a latched patch. The panel never forces X.
- **Y = LEDs.**
- **Analog = entry boxes** that patch the assigned DF.
- **Sim-only Modbus option:** the server accepts writes to X. pyclickplc defaults this off; ClickNick's simulator
  turns it on, because the I/O panel is itself a Modbus client for values and for X/analog writes.
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

### Known pyrung gaps (address first)

- An unpaced continue runs timers too fast.
- Live-command results emit no DAP events.
- The runner is not thread-safe for Modbus writes.

### Open TODOs

- Simulate action icon.
- Simulator screenshot in the docs.
- docs-build not run.
- Release order: pyclickplc -> pyrung (raise the `pyclickplc>=` floor) -> clicknick pins.

## To re-evaluate

### Could the simulator use only pyrung live commands?

If every simulator action (switch, analog entry, force, mode) can be sent as a pyrung live command, the simulator may
not need Modbus writes at all. Then **pyclickplc may not need any changes**: no sim-only "accept writes to X" option.
Modbus could stay a read-only data plane for the Dataview, or go away for the simulator. Check this before releasing
the pyclickplc change.

### Right-click menu on simulator elements

Right-click on an I/O element (or a tag) opens a menu with actions such as **Why**, **How** and **Simplified**. These
would be the same analysis commands the Console offers, aimed at the element under the cursor.

### Simulator actions echo into the Console

A change made on the graphical simulator shows up in the Console as the equivalent command (for example
`patch Tag`). That way the user sees and learns the command language, and the GUI and the Console share one
command path.

The Console could be re-imagined as a **drop-down / tear-off window** attached to the simulator rather than a
separate standalone window.
