# Agent Workflow — Skills, Scenarios, and ClickNick Integration

## Overview

ClickNick generates a workspace directory that a coding agent (Claude Code, etc.) can use to interact with a pyrung program. The agent gets access to diagnosis, simulation, verification, and code generation — all grounded in the engineer's actual program. The engineer talks; the agent reasons formally and produces verified, paste-ready output.

The key insight: the agent doesn't need the Click GUI. pyrung IS the program. The agent works against it directly, and ClickNick handles the bridge back to Click Programming Software.

### Two workflows

**Click-first** — Click Programming Software is the source of truth. ClickNick generates the pyrung project from the .ckp project's Scr*.tmp files. When the engineer saves in Click, the project auto-regenerates (ScrWatcher). Annotations live in ClickNick's own layer (the address editor), not in the Python source — they survive regeneration. The agent annotates via ClickNick Live CLI commands. This is the lower bar: the engineer stays in their familiar tool, never touches Python.

**pyrung-first** — pyrung is the source of truth. The engineer writes Python, tests with pytest, runs CI, uses prove() directly. Annotations live in the source. Click is a deployment target. This is the higher bar: full engineering workflow with version control, test suites, and lock files.

This document describes the Click-first workflow. The agent works through ClickNick's layer because that's where the data lives when Click is the source of truth.

---

## Implementation Status

### What's built and working

**ClickNick Live** (IPC bridge — fully implemented):
- TCP server embedded in the GUI, drains commands on Tk main thread
- Session discovery by `.ckp` filename (label file), stale port pruning
- `DispatchContext` rebuilt each drain cycle (store, analysis, tag resolver, annotation service)
- `get`/`set` commands with pyrung tag name resolution (falls back to Click display address)
- **Tag commands** (13 subcommands): flags, choices, range, UOM, physical devices, queries
- **Rung commands**: `list`, `preview` (with rung selection), `apply` (pyrung → ladder CSVs)
- All edits land as unsaved changes in the address editor — engineer reviews and saves

**AnalysisService** (pyrung project generation — fully implemented):
- Builds ProgramGraph from Scr*.tmp via `ladder_to_pyrung()` pipeline
- Persists `pyrung_project/` to disk on every ScrWatcher-triggered rebuild
- Output: `tags.py`, `main.py`, `subroutines/*.py`, `csv/`, `project_to_csv.py`, `.vscode/`
- Bidirectional `tag_to_addr_key` map for tag name ↔ addr_key resolution

**DAP / Simulation** (GUI-managed, pyrung-live for agent interaction):
- DapService manages pyrung DAP subprocess (pure Python, no tkinter)
- GUI toggle button starts/stops DAP (lifecycle in app.py, not dispatch layer)
- pyrung-live (in pyrung repo) provides out-of-process console attachment to DAP
- Agent talks to pyrung-live for simulation; clicknick-live for annotations/rung edits
- VS Code extension provides visual debugging for engineers who want to watch

**pyrung** (core engine — fully implemented):
- Full DSL: tags, rungs, conditions, coils, timers, counters, math, data movement, comms
- `ladder_to_pyrung()` and `pyrung_to_ladder()` round-trip conversion
- `ladder_to_pyrung_project()` generates multi-file projects
- DAP server with breakpoints, stepping, force/patch, causal analysis, history
- State-space exploration, `prove()`, `why()`, `how()`, `cause()`, `effect()`
- Lock file system (`pyrung lock` / `pyrung check`) for CI verification
- Static click-cheatsheet in `docs/guides/click-cheatsheet.md`

### What's NOT built yet (next phase)

The workspace that ClickNick generates is missing the agent-facing artifacts:

| Artifact | Purpose | Status |
|----------|---------|--------|
| `CLAUDE.md` | Tells the agent what it has and how to use it | Not generated |
| `click-cheatsheet.md` | pyrung DSL reference for writing/reading code | Static doc only, not emitted into workspace |
| `.claude/skills/` | Structured skill definitions for agent workflows | Not generated |
| `.claude/settings.json` | Permissions and MCP tool config | Not generated |

The project_emitter generates `tags.py`, `main.py`, `subroutines/`, `run.py`, `project_to_csv.py`, `.vscode/launch.json`, `pyproject.toml`, `README.md` — but none of the agent-facing files.

---

## Primary Workflow — Simulation

The day-one workflow that handles most scenarios: force inputs, step the scan, ask why.

### Discover → Force → Step → Why

```
pyrung live "dataview i:"                           # what inputs can I toggle?
pyrung live "force HMI_on true; step 1; dataview fill"  # change input, step, observe
pyrung live "why fill_stepNumber"                    # explain the current state
```

**`dataview`** is the discovery tool. It shows tags with their PDG-classified roles:
- `(input)` — never written by the program, only read. The agent can force these.
- `(pivot)` — read and written. Internal state the program manages.
- `(terminal)` — written but never read. Outputs (solenoids, lights, alarms).

Query patterns: `dataview fill` (name match), `dataview i:` (all inputs), `dataview p:` (pivots), `dataview t:` (terminals), `dataview upstream:Motor` (everything that feeds a tag).

**`why()`** is the primary analysis tool. Walks backward from any tag and explains how it reached its current state — which contacts are blocking, which latches are held, which roots are contributing. Zero setup, no annotations needed.

**`force` + `step`** is hypothesis testing. Force an input to a value, step the scan, then `why()` again to see what changed. The agent can iterate this loop freely — each force simulates a field change, each `why()` shows what remains.

This loop handles: "my machine faulted", "why won't this start", "what happens if this sensor fails", and most diagnostic questions. No annotations, no explore(), no prove() required.

### Other simulation commands

```
pyrung live "cause FaultAlarm"     # what transition caused this? (needs scan history)
pyrung live "effect HMI_on"        # what did toggling this cause? (needs scan history)
pyrung live "upstream Motor"       # static: everything that feeds this tag
pyrung live "downstream StartBtn"  # static: everything this tag feeds
pyrung live "simplified fill_solv_nc"  # resolve pivot chain to single expression
```

---

## Formal Verification — explore / how / prove

For programs with purely discrete logic (Bool and Int-with-choices tags), the formal verification tools provide exhaustive analysis. These require annotations and are most valuable for safety-critical changes.

**Current limitation:** `explore()` varies Bool inputs and Int choices, but cannot vary Real (float) tags. Programs with analog values (levels, temperatures, pressures) will have a limited state graph. For those programs, the simulation workflow above is more practical.

### `explore()` + `how()` — Reachability

```
pyrung live "explore; how fill_stepNumber == 5"
```

`explore()` builds the full reachable-state graph via BFS. `how()` queries it for the minimum input changes to reach a target state. `explore()` is called once (expensive); `how()` is cheap and repeatable.

If `explore()` returns Intractable, the blocker hint identifies which tag needs a constraint. The agent annotates via clicknick-live and retries after a save cycle (see tractability conversation below).

### `prove()` — Safety properties

```
pyrung live "prove not (OverTemp and not CoolingPump)"
```

Exhaustively verifies a property over all reachable states. Returns `Proven`, `Counterexample` (with step-by-step trace), or `Intractable` (with blocker hint).

**The proof obligation:** `prove()` every logic change before preparing output. The fix isn't done until the proof passes. The engineer is the decision-maker (is this the behavior I want?), not the verifier (is this code correct?). `prove()` is the verifier.

### `cause()` / `effect()` — History-based tracing

**Needs:** recorded scan history (simulation session or live trace).

`cause(tag)` traces backward through recorded scans to the exact contact that flipped. `effect(tag)` traces forward to see what a transition triggered. Richer than `why()` because history distinguishes triggers from enablers.

### Escalation

The tools form a gradient. The agent should reach for the cheapest one that answers the question:

`why()` → "I can see what's blocking but I want recovery steps" → `how()` → "I want to know which contact flipped first" → `cause()` → "I want to prove this can never happen" → `prove()`

Each tool is honest about what it can't tell you, and what it can't tell you is exactly what the next tool up can.

---

## Workspace Structure

ClickNick + pyrung generate a project directory. Currently the project_emitter produces the program files; the next phase adds the agent-facing artifacts.

### Current output (project_emitter)

```
pyrung_project/
├── tags.py                # Tag declarations + TagMap
├── main.py                # Program with main rungs + call() statements
├── subroutines/           # Individual subroutine files
│   ├── __init__.py
│   └── <name>.py
├── run.py                 # Instantiate PLC and step logic
├── project_to_csv.py      # Export back to Click CSV
├── csv/                   # Ladder CSVs (source of truth for regeneration)
│   ├── Scr0.csv
│   └── nicknames.csv
├── csv_output/            # Created by `rung apply` (pending changes)
├── .vscode/
│   ├── launch.json        # DAP launch configuration
│   └── extensions.json    # pyrung-debug recommendation
├── pyproject.toml         # Dependencies (pyrung >= version)
└── README.md              # Setup instructions
```

### Target output (next phase — pyrung emits these)

```
pyrung_project/
├── ... (existing files above)
├── CLAUDE.md              # Agent instructions: tools, workflows, escalation
├── click-cheatsheet.md    # pyrung DSL quick reference
└── .claude/
    ├── settings.json      # Permissions for clicknick-live, pyrung-live
    └── skills/
        ├── diagnose.md    # "My machine faulted" / "Why won't this start?"
        ├── fix.md         # "Fix this so it can't happen again"
        ├── review.md      # "Review / explain this program"
        └── failure.md     # "What happens if this sensor fails?"
```

### CLAUDE.md — what the agent needs to know

The CLAUDE.md tells the agent what it has and how to use it. Not API docs — workflows, in escalation order. This is generated by pyrung's project_emitter, tailored to the specific program.

```markdown
# Machine: [name from .ckp project]

## Tools

Two CLI tools. Chain commands with `;` to avoid repeated process launches.

- **pyrung live** — simulation and analysis (step, force, why, prove)
- **clicknick-live** — push annotations and rung edits back to Click

## Start here — discover and diagnose

Find what inputs exist, then ask why a tag is in its current state:

    pyrung live "dataview i:"                            # list all inputs
    pyrung live "dataview fill"                          # tags matching 'fill'
    pyrung live "why FaultAlarm"                         # backward walk — what's blocking?
    pyrung live "why FaultAlarm MotorStall"              # unified across multiple tags

Dataview roles: `i:` = inputs (force these), `p:` = pivots (internal), `t:` = terminals (outputs).
Also: `upstream:Tag` and `downstream:Tag` for static dependency queries.

## Test a hypothesis — force, step, observe

    pyrung live "force EstopOK true; step 1; why FaultAlarm"

Each force simulates a field change. Each `why()` shows what remains. Iterate
until you understand the causal chain. This handles most diagnostic questions
without any annotations or setup.

## Annotate tags (via clicknick-live)

Annotations constrain the state space for formal verification and survive
program regeneration:

    clicknick-live "tag set-choices StateCurrent IDLE:0 FILLING:1 DRAINING:2 FAULTED:3"
    clicknick-live "tag set-range FillLevel 0 1000"
    clicknick-live "tag show StateCurrent"

All edits land as unsaved changes — engineer reviews and saves in the address
editor. Batch annotations before asking the engineer to save (two sync points:
save in ClickNick, then save in Click to trigger regeneration).

## Formal verification (discrete programs)

    pyrung live "explore; how fill_stepNumber == 5"
    pyrung live "prove not (OverTemp and not CoolingPump)"

explore/how/prove work best with Bool and Int-with-choices tags. Programs with
Real (float) values will have limited coverage — use force+step+why for those.
Always prove after making logic changes.

## Read and edit program structure (via clicknick-live)

    clicknick-live rung list                  # summary per rung
    clicknick-live rung list init             # subroutine rungs
    clicknick-live rung preview --select r3   # before/after diff
    clicknick-live rung apply                 # convert edits to ladder CSVs

## Generate paste-ready output

Edit pyrung source (main.py, subroutines/) directly. Then:

1. `clicknick-live rung preview` — see what changed as a diff
2. `clicknick-live rung apply` — convert to ladder CSVs in csv_output/
3. Engineer reviews, applies in Click, saves
4. ScrWatcher detects save → auto-regenerates pyrung_project/
5. Re-prove against regenerated source (round-trip check)

## Reference

- `tags.py`, `main.py`, `subroutines/` — pyrung model of this machine's logic
- `click-cheatsheet.md` — pyrung DSL quick reference (read before writing code)
- `pyrung live help` — full command list
```

### click-cheatsheet.md

The static cheatsheet from `pyrung/docs/guides/click-cheatsheet.md` — pyrung DSL quick reference covering imports, memory banks, conditions, coils, math, timers, counters, program structure, TagMap, and common patterns. Emitted as-is into the workspace so the agent has it without web access.

### .claude/settings.json

Permissions for the two CLI tools the agent uses:

```json
{
  "permissions": {
    "allow": [
      "Bash(clicknick-live *)",
      "Bash(pyrung live *)"
    ]
  }
}
```

### Skills

Each skill is a structured workflow the agent can invoke. They map to the scenarios below — the skill tells the agent what to do step by step, which tools to reach for, and when to escalate.

---

## Scenarios

### 1. "My machine faulted"

**Trigger:** Engineer reports a fault, alarm, or unexpected state.

**Workflow:**
1. `pyrung live "dataview t:"` — see what outputs/alarms are active
2. `pyrung live "why FaultAlarm"` — backward walk, what's causing it?
3. Explain the causal tree in plain English — name the specific tags and rungs
4. If multiple tags are alarming — `why FaultAlarm MotorStall` for a unified explanation
5. If engineer asks "how do I clear it?" — force-and-step loop:
   `pyrung live "force EstopOK true; step 1; why FaultAlarm"` — see what remains
6. Iterate: force the next blocker, step, why again, until the path is clear

**Agent should:** Start with `why()` — it needs nothing. The force+step+why loop answers "how do I recover?" interactively. Only reach for `how()` if the program is fully annotated with discrete choices and the engineer wants a formal minimum-step recovery plan.

**Output:** Natural language explanation + specific tags/rungs to check on the machine.

### 2. "Why won't this start?" / "It's stuck at step 5"

**Trigger:** Machine is stuck mid-sequence, not faulted but not advancing.

**Workflow:**
1. `pyrung live "dataview step"` or `dataview fill` — find the sequence tag
2. `pyrung live "why StepCurrent"` — what's blocking advancement?
3. `pyrung live "upstream StepCurrent"` — what feeds this tag? Look for inputs.
4. Force the blocking input, step, check if the sequence advances
5. `why()` again on anything that didn't change as expected

**Output:** "ConveyorMotor is OFF because Running is blocked by EstopOK(False) on rung 2. Check the e-stop circuit."

### 3. "Fix this so it can't happen again"

**Trigger:** Engineer understands the fault and wants a logic change.

**Workflow:**
1. Discuss the fix — what permissive/interlock is missing?
2. Draft the new rung(s) by editing pyrung source (main.py or subroutines/)
3. Simulate — force the scenario that caused the fault, step through, confirm new behavior blocks it
4. If program is discrete: `prove()` the bad state is no longer reachable
5. If prove fails or is intractable — iterate with force+step to cover edge cases manually
6. `clicknick-live rung apply` to prepare ladder CSVs
7. Engineer reviews via `clicknick-live rung preview`, applies in Click, saves
8. ScrWatcher triggers regeneration — re-verify against the regenerated source

**Agent must:** Verify every logic change before preparing output. `prove()` when the program is tractable. Simulation-based verification (force known-bad scenarios, confirm they're blocked) when it's not. The engineer is the decision-maker (is this the behavior I want?), not the verifier.

**Output:** Verified rung edits + plain English description of what changed and why.

### 4. "Add a new feature"

**Trigger:** Engineer wants new logic (new sequence step, new alarm, new mode).

**Workflow:**
1. Understand requirements
2. `pyrung live "dataview i:"` — what inputs are available? What tags are free?
3. Draft the new rungs in pyrung source
4. Simulate: force inputs through the new scenarios, confirm expected behavior
5. Prove relevant properties if tractable
6. `clicknick-live rung apply` to prepare output

**Output:** Verified rung edits + simulation walkthrough or prove results.

### 5. "Review / explain this program"

**Trigger:** Engineer is unfamiliar with a program, or doing a handoff.

**Workflow:**
1. Read the pyrung source (main.py, subroutines/, tags.py)
2. `pyrung live "dataview i:; dataview t:"` — understand the I/O boundary
3. `pyrung live "upstream CriticalOutput"` — trace what drives key outputs
4. `pyrung live "simplified CriticalOutput"` — resolve pivot chains to readable expressions
5. Explain the logic in plain English — what each section does, what the sequence is, what the interlocks are
6. Identify gaps — alarms without coverage, interlocks that can be bypassed

**Output:** Program narrative with I/O map and dependency analysis.

### 6. "What happens if this sensor fails?"

**Trigger:** Engineer wants to understand failure modes.

**Workflow:**
1. `pyrung live "dataview i:"` — find the sensor tag
2. `pyrung live "force FlowSensor false; step 10; dataview alarm"` — simulate failure
3. `pyrung live "why FaultAlarm"` — explain the cascade
4. `pyrung live "effect FlowSensor"` — what else did the failure trigger? (needs history)
5. If the engineer wants exhaustive analysis and the program is tractable — `prove()` that the alarm catches the failure across all states, not just the current one

**Output:** "If FlowSensor goes FALSE while FillEnable is TRUE, the watchdog timer starts. After 5s, FlowAlarm latches."

---

## Reverse Path — Pasting Back to Click

The agent edits pyrung source files directly (main.py, subroutines/). The reverse path converts those edits back to Click's format.

### Rung-level workflow (via clicknick-live)

```
clicknick-live rung list                  # see program structure
# Agent edits pyrung source files...
clicknick-live rung preview --select r3   # diff showing what changed
clicknick-live rung apply                 # convert to ladder CSVs in csv_output/
```

The engineer reviews the diff, applies in Click (paste/import), and saves. ScrWatcher detects the save and auto-regenerates pyrung_project/ — the agent re-proves against the regenerated source as a round-trip check.

### Which approach to use

- Fix to one rung, adding a contact, modifying a condition → edit the rung in main.py, apply
- Adding a new section, new alarm logic → edit/add source files, apply
- Restructuring logic, new program, major refactor → full program paste via ClickNick export
- When in doubt, smaller changes are lower risk — the engineer sees and applies each change individually

---

## DAP Integration — Simulation

ClickNick manages the DAP subprocess lifecycle via a GUI toggle button. The engineer starts DAP when they want simulation available; the agent connects via pyrung-live.

### Architecture

```
┌─────────────────────┐     ┌───────────────────┐     ┌──────────────┐
│  ClickNick GUI      │     │  pyrung DAP        │     │  Agent       │
│                     │     │  (subprocess)      │     │  (Claude)    │
│  [Start/Stop DAP]───┼────▶│  adapter.py        │◀────┼──pyrung live │
│  DapService manages │     │  breakpoints       │     │  console     │
│  subprocess lifecycle│     │  stepping          │     │              │
│                     │     │  force/patch        │     │              │
│  LiveServer─────────┼─────┼──clicknick-live────┼─────┼──annotations │
│  (tag/rung cmds)    │     │                    │     │  rung edits  │
└─────────────────────┘     └───────────────────┘     └──────────────┘
```

- **pyrung-live** — agent uses for simulation: step, force, why, how, prove, cause, effect
- **clicknick-live** — agent uses for data: tag annotations, rung list/preview/apply, get/set fields
- **VS Code** — optional, engineer can watch the debug session visually

### Launch flow

1. Engineer opens project in ClickNick (connects to Click instance or opens .ckp)
2. ScrWatcher triggers AnalysisService → generates pyrung_project/ on disk
3. Engineer clicks Start DAP → DapService launches pyrung subprocess
4. Engineer points agent at the pyrung_project/ directory
5. Agent reads CLAUDE.md, discovers available tools, ready to go

The engineer doesn't configure anything beyond clicking Start. ClickNick sets up the workspace and the simulation. The agent discovers what's available from CLAUDE.md.

---

## ClickNick Live — Annotation Interface

ClickNick Live exposes structured CLI commands for annotating tags directly. The agent uses these instead of editing Python source — no syntax errors, no wrong files, no merge conflicts. Every command lands as an unsaved change in the ClickNick address editor.

**The agent can edit. It cannot save.** Saving is always the engineer's action. The unsaved-changes workflow already exists for human edits — ClickNick Live just writes into the same pending state via CLI. The agent proposes; the engineer reviews the diff and commits.

This means the agent can run the full tractability loop autonomously — `explore()`, read blocker, annotate via clicknick-live, retry, next blocker, annotate, retry, success — without asking permission at each step. The engineer reviews the batch at the end: "The agent added six annotations to close the state space. Review in the address editor." The engineer glances at the diff, corrects the one wrong sensor range, saves. Ten seconds.

### Commands (implemented)

**Flags:**
```
clicknick-live tag set-flag <tag> <flag>      # readonly, external, final, public, lock
clicknick-live tag clear-flag <tag> <flag>
```

**Value constraints:**
```
clicknick-live tag set-choices <tag> <Label:val> ...   # or Bool
clicknick-live tag set-range <tag> <min> <max>
clicknick-live tag clear-constraints <tag>
clicknick-live tag set-uom <tag> <unit>
clicknick-live tag clear-uom <tag>
```

**Physical devices:**
```
clicknick-live tag set-physical <tag> <name> [--on-delay D] [--off-delay D] [--profile P] [--system S]
clicknick-live tag set-link <tag> <link>
clicknick-live tag clear-physical <tag>
```

**Queries:**
```
clicknick-live tag show <tag>
```

**Rung operations:**
```
clicknick-live rung list [file]
clicknick-live rung preview [file] [--select r3,r7]
clicknick-live rung apply [file]
```

**Basic operations:**
```
clicknick-live ping
clicknick-live info
clicknick-live get <tag-or-addr>
clicknick-live set <tag-or-addr> <field> <value>
```

All tag/rung identifiers resolve by pyrung tag name first, Click display address (DS1) as fallback.

Both `pyrung live` and `clicknick-live` support `;` chaining — batch commands in one call:

```
clicknick-live "tag set-range LevelPV 0 100; tag set-flag LevelPV external; tag show LevelPV"
pyrung live "force HMI_on true; step 5; dataview fill; why fill_stepNumber"
```

### The tractability conversation

When the agent needs `how()` or `prove()` and annotations are missing, the workflow is
conversational — and requires the engineer to participate at two sync points:

1. Agent runs `explore()` via pyrung-live, gets Intractable with blocker hints
2. Agent reads the program to infer constraints, asks the engineer to confirm unknowns
3. Agent batch-annotates via clicknick-live (`tag set-choices`, `tag set-range`, etc.)
4. **Sync point 1 — engineer reviews and saves in ClickNick** (writes annotations to MDB)
5. **Sync point 2 — engineer saves in Click Programming Software** (triggers ScrWatcher → pyrung_project/ regenerates with annotations baked into the source)
6. Agent retries `explore()` against the regenerated program

The agent cannot skip these sync points. Annotations flow through a pipeline:
`clicknick-live` → unsaved changes in address editor → **engineer saves to MDB** →
Click project save triggers ScrWatcher → AnalysisService rebuilds pyrung_project/ →
annotations appear in tags.py → `explore()`/`prove()` can read them.

The agent should batch as many annotations as possible before asking the engineer to
sync, rather than one-at-a-time round trips. Use `pyrung live "dataview i:"` to see
all inputs, read the program to infer constraints, annotate the full batch, then ask
for one save cycle.

The agent drives the conversation; the verifier tells it which questions to ask;
clicknick-live is the mechanism; the engineer confirms by reviewing the diff in the
address editor and saving when ready.

### Why CLI commands instead of source edits

- In Click-first mode, pyrung source is regenerated on every save — source edits to annotations would be overwritten
- Annotations live in ClickNick's layer (address editor comments), which survives regeneration
- Structured commands can't produce syntax errors or break the program
- Edits land as unsaved changes — the engineer reviews before committing
- The agent can work autonomously without the engineer gating each annotation

The annotation is a fact about the machine, not a line of code. CLI commands treat it that way. The edit/save boundary keeps the engineer in control without making them a bottleneck.

---

## Next Phase — pyrung Workspace Emission

### Goal

`ladder_to_pyrung_project()` (via project_emitter.py) already generates the program files. Extend it to also emit the agent-facing workspace artifacts so that the pyrung_project/ directory is a complete, self-contained agent workspace.

### What pyrung needs to emit

**1. CLAUDE.md** — generated from a template, populated with:
- Machine name (from .ckp filename or project metadata)
- Available tools and their commands (clicknick-live, pyrung-live)
- Workflow escalation: why → how → cause → prove
- Program structure summary (main rung count, subroutine list)
- Quick reference for reading the generated code

**2. click-cheatsheet.md** — the existing static cheatsheet from `docs/guides/click-cheatsheet.md`, copied into the workspace. The agent needs pyrung DSL reference to read and write code. Could be:
- Literal copy of the static file (simplest, keeps one source of truth)
- Trimmed version omitting sections not relevant to the specific program
- Embedded in CLAUDE.md instead of a separate file (fewer files for the agent to discover)

**3. .claude/settings.json** — permissions for the CLI tools:
```json
{
  "permissions": {
    "allow": [
      "Bash(clicknick-live *)",
      "Bash(pyrung live *)"
    ]
  }
}
```

**4. .claude/skills/** — structured workflow definitions for each scenario. Each skill tells the agent when to trigger, what tools to use, and how to escalate. Maps to the scenarios in this document.

### Where this lives in pyrung

The project_emitter already has `_generate_project() → dict[str, str]`. The new artifacts are additional entries in that dict:
- `_generate_claude_md(...)` — template with program-specific metadata
- `_generate_cheatsheet()` — copy or trim the static reference
- `_generate_claude_settings()` — permissions JSON
- `_generate_skills()` — skill markdown files

The AnalysisService in ClickNick calls `ladder_to_pyrung_project()` and writes the result to disk. No changes needed in ClickNick — pyrung emits the files, ClickNick persists them.

---

## What makes this different

Every other AI-for-PLC tool generates code and stops. The engineer is the verification layer.

This stack generates code, simulates it, proves it correct, and only then hands it to the engineer as paste-ready output. The engineer is the decision-maker — is this the behavior I want? — not the verifier — is this code correct? `prove()` is the verifier.

The agent is allowed to be wrong. It will draft bad fixes sometimes. But it can't ship them — `prove()` catches them first. The engineer never sees unverified output for safety-critical changes.

And when the machine is down right now, the agent doesn't need any of that infrastructure. `why()` works from a tag dump and the program — no annotations, no history, no simulation session. The cheapest tool answers the most urgent question.

That's not AI-assisted programming. That's AI with a proof obligation.
