# LLM Capture Checklist Guide (CLI + Guided Workflow)

## Purpose
This guide is for LLM operators adding ladder capture checklist items programmatically.
Use workflow commands only; do not edit manifest JSON by hand.
Canonical runner: `uv run clicknick-ladder-capture ...`.

## Non-Negotiable Rules
- Never edit `scratchpad/ladder_capture_manifest.json` directly.
- Use `entry add` to create new checklist items.
- Use `entry capture`, `verify ...`, and `promote` to update lifecycle fields.
- Run commands from repo root.
- Treat manifest lifecycle and payload construction as separate concerns:
  - use `uv run clicknick-ladder-capture ...` for manifest/state changes
  - generate `.bin` payload files first, then register them as file-backed entries
- Do not use retired tools:
  - `devtools/capture.py`
  - `devtools/clipboard_load.py`
  - `devtools/update_ladder_capture_manifest.py`
  - `scratchpad/pasteback_smoke.py`

## Investigator Quick Start
When starting a new reverse-engineering lane:
1. Read `HANDOFF.md` first for the latest accepted ground truth and current gate status.
2. Read the lane-specific scratchpad report/case-spec files for the active round.
3. Find an existing donor capture in `scratchpad/captures/` before inventing a new baseline.
4. Decide whether the next round needs:
   - new native captures
   - synthetic codec output
   - file-backed patch payloads built from existing captures
5. Only after the payloads exist, add checklist entries with `uv run clicknick-ladder-capture ...`.

## Approved Payload Construction Helpers
These helpers are allowed for generating patch payload files before manifest registration:
- `devtools/noise_apply.py`
  - use for explicit offset-copy or constant-write patching across the first `8192` bytes
- `devtools/patch_capture_cells.py`
  - use for per-cell offset mutations when the change is cell-local
- `devtools/two_series_patch_harness.py`
  - use as a reference pattern for donor/base patch generation and naming

If no helper exactly fits the lane:
- a short repo-local Python snippet is acceptable for one-off payload generation
- keep it deterministic, write the output under `scratchpad/captures/`, and document the exact offsets/ranges in the case spec or queue doc
- do not treat ad hoc generation as permission to edit the manifest by hand

## File-Backed Patch Workflow
Use this when the payload is derived from existing `.bin` captures rather than shorthand generation.

1. Build the payload file under `scratchpad/captures/`.
2. Sanity-check the payload length.
3. Add a patch entry with `--payload-source file --payload-file <path>`.
4. Verify the entry shows the expected payload file.
5. Add the case to a queue doc with the patch rationale, donor/base labels, and offsets or ranges used.

Minimal pattern:

```powershell
uv run clicknick-ladder-capture entry add --type patch --label <label> --scenario <scenario> --description "<desc>" --row "<row>" --payload-source file --payload-file scratchpad/captures/<file>.bin
uv run clicknick-ladder-capture entry show --label <label>
```

## Minimal Add New Checklist Item Flow
1. Ensure manifest exists.

```powershell
uv run clicknick-ladder-capture manifest init
```

If it already exists, do not use `--force` unless overwrite is intentional.

2. Add a new item.

```powershell
uv run clicknick-ladder-capture entry add --type native --label <label> --scenario <scenario> --description "<desc>" --row "R,X001,->,:,out(Y001)"
```

3. Verify creation.

```powershell
uv run clicknick-ladder-capture entry show --label <label>
```

4. Optional: capture native clipboard bytes now.

```powershell
uv run clicknick-ladder-capture entry capture --label <label>
```

5. Optional: add verify metadata.

Load payload into clipboard only:

```powershell
uv run clicknick-ladder-capture verify prepare --label <label>
```

Load payload into clipboard with owner UID/HWND spoof:

```powershell
uv run clicknick-ladder-capture verify prepare --label <label> --uid 0x1234
```

Interactive:

```powershell
uv run clicknick-ladder-capture verify run --label <label>
```

Non-interactive:

```powershell
uv run clicknick-ladder-capture verify complete --label <label> --status <unverified|verified_pass|verified_fail|blocked> --clipboard-event <copied|crash|cancelled> --note "<note>"
```

6. Optional: promote to fixtures.

```powershell
uv run clicknick-ladder-capture promote --label <label> --overwrite
```

## Programmatic Gotchas for LLMs
- `--row` is required and repeatable.
- Duplicate `--label` fails.
- `--payload-source` defaults to `shorthand`.
- `--payload-source file` does not create the file for you; the `.bin` must already exist.
- Shorthand source for prepare/verify generation currently supports a simple single-row path; it requires at least one contact and a non-empty AF instruction.
- Shorthand row syntax now also supports comment rows:
  - `#` = comment row marker
  - column `A` = comment text for that line
  - no additional columns on shorthand comment rows
  - example: `#,Initialize the light system.`
  - multi-line comments use one row per line
- For `entry add` / `entry add-patch-batch`, you can either:
  - pass repeatable `--comment "<text>"` flags
  - or pass explicit comment rows via repeatable `--row "#,<text>"`
- Comment rows must appear before the first rung row in an entry.
- Shorthand payload generation does not yet synthesize rung comments; comment-bearing entries should verify from file/native payloads unless you are only recording expected rows.
- Wire shorthand tokens used in observed/expected rows:
  - `-` = horizontal wire
  - `|` = vertical wire (valid on columns `B+`; not column `A`)
  - `T` = both horizontal and vertical at the same cell
- Empty commas in stored `--row` values often act as a shorthand placeholder for an otherwise wire-only baseline.
  - when Click visibly shows a full horizontal line, record the observed row using explicit `-` tokens if needed
  - do not assume the manifest shorthand string is the most human-readable rendering of the pasted rung
- For `entry add-patch-batch`, provide at least one `--file` or `--glob`.
- For `entry add-patch-batch`, `--file` and `--glob` are repeatable.
- For `entry add-patch-batch`, `--skip-existing` changes duplicate-label handling from fail to skip.
- Enum restrictions:
  - capture type: `native|synthetic|patch|pasteback`
  - verify event: `copied|crash|cancelled`
  - verify status: `unverified|verified_pass|verified_fail|blocked`

## Complete Supported Command List
Top level:
- `manifest`
- `entry`
- `verify`
- `report`
- `promote`
- `tui`

Manifest:
- `init [--force]`

Entry:
- `add --type {native|synthetic|patch|pasteback} --label <label> --scenario <scenario> --description <description> [--comment <text>] --row <row> [--payload-source {shorthand|file}] [--payload-file <path>] [--json]`
- `add-patch-batch --scenario <scenario> [--comment <text>] --row <row> [--file <path>] [--glob <pattern>] [--label-prefix <prefix>] [--description-prefix <text>] [--skip-existing] [--json]`
- `list [--type {native|synthetic|patch|pasteback}] [--status {unverified|verified_pass|verified_fail|blocked}] [--json]`
- `show --label <label> [--json]`
- `capture --label <label> [--output-file <path>] [--json]`

Verify:
- `prepare --label <label> [--source {shorthand|file}] [--uid <uid_or_hwnd>] [--mdb-path <path>] [--no-ensure-mdb-addresses] [--json]`
- `complete --label <label> --status {unverified|verified_pass|verified_fail|blocked} --clipboard-event {copied|crash|cancelled} [--note <text>] [--row <row>] [--result-file <path>] [--json]`
- `run --label <label> [--source {shorthand|file}] [--uid <uid_or_hwnd>] [--mdb-path <path>] [--no-ensure-mdb-addresses] [--status-default {unverified|verified_pass|verified_fail|blocked}] [--json]`

## Guided Verify Queue (File-Backed Runs)
- Use this for native/patch scenarios where payloads come from captured `.bin` files.
- Start TUI: `uv run clicknick-ladder-capture tui`
- In guided verify:
  1. Select `3` (Verify run), then `g` (guided queue).
  2. Choose payload override `f` (file).
  3. Enter a scenario filter for the current round.
- If you see `Entry has no payload_source_file or payload_file to load`, the entry is missing a
  captured/source payload; fix by running `entry capture --label <label>` (native) or adding a
  file-backed entry (`entry add ... --payload-source file --payload-file <path>`).

## Queue-and-Run Cadence (Recommended)
- For manual RE rounds, use this loop:
  1. Build a scenario and add entries (`entry add` / `entry add-patch-batch`).
  2. Generate a queue doc under `scratchpad/` (for example `scratchpad/<scenario>_verify_queue_<date>.md`).
  3. Commit queue setup before operator manual steps.
  4. Operator run path for verify queues: `tui -> 3 -> g -> f -> <scenario filter>`.
  5. For copied events, operator must paste in Click, then copy back in Click, then press `c`.
  6. Operator responds `done`.
  7. Parse manifest outcomes, classify pass/fail/blocked, build next batch, and commit outcomes.
- For narrowing/isolation batches, prefer speed and clean signal:
  - do not manually edit failed rungs.
  - record `status`, `event`, and resulting clipboard length.
  - add a short note only when outcome is surprising/ambiguous (for example accidental mis-click).
- For native recapture rounds, use: `tui -> 2` (capture queue), then `tui -> 3 -> g -> f` for verify.
- Preferred operator handoff message includes:
  - scenario name
  - case count
  - queue doc path
  - exact TUI path
  - explicit `send done` instruction
- For rows that can render differently in Click than their stored shorthand suggests:
  - tell the operator what visible shape is expected
  - tell the operator what observed-row form to enter if a rows override is needed
  - keep comment/rendering notes separate from topology notes

## What To Document In Each New RE Round
Create or update a scratchpad case spec / queue doc that records:
- scenario name and date
- donor/base labels
- payload file path for each case
- exact copied ranges or explicit offsets
- the hypothesis each case is testing
- what counts as pass/fail/blocked
- any operator-only instructions such as:
  - save and reopen before copy-back
  - inspect `Edit Comment`
  - skip conditional follow-up cases after a stop-condition failure

## Comment-Lane Example
For comment replay work, the bare minimum context to preserve in the queue doc is:
- proven model offsets such as `0x0294` and `0x0298`
- whether `len` includes trailing NUL
- the current best donor companion region, if any
- whether the goal is:
  - semantic persistence
  - immediate display parity
  - style rendering
- whether a failed styled probe should stop the styled branch entirely

Report:
- `profile (--label <label> | --all) [--json | --csv]`
- `profile-columns (--label <label> | --all) [--rows <spec>] [--cols <spec>] [--offsets <spec>] [--json | --csv]`

Promote:
- `promote --label <label> [--fixture-file <path>] [--overwrite] [--json]`

TUI:
- `tui` (no flags)
- Guided menu actions:
  1. List entries
  2. Capture native payload (guided queue)
  3. Verify run (copied/crash/cancel)
  4. Promote entry
  5. Exit

## JSON Example Envelope
```json
{
  "ok": true,
  "action": "entry.list",
  "status": "success",
  "errors": [],
  "data": []
}
```

## Quick Validation Commands
```powershell
uv run clicknick-ladder-capture --help
uv run clicknick-ladder-capture entry add --help
uv run clicknick-ladder-capture entry add-patch-batch --help
uv run clicknick-ladder-capture verify prepare --help
uv run clicknick-ladder-capture verify run --help
uv run clicknick-ladder-capture report profile --help
uv run clicknick-ladder-capture report profile-columns --help
```

## UID / HWND Notes
- `--uid` accepts decimal or `0x`-prefixed hex.
- `--uid 0` means no owner spoof.
- Omitting `--uid` keeps default auto-spoof behavior (first detected CLICK window).

Optional sanity check:

```powershell
uv run clicknick-ladder-capture entry add --type native --label <label> --scenario <scenario> --description "<desc>" --row "R,X001,->,:,out(Y001)"
uv run clicknick-ladder-capture entry show --label <label>
uv run clicknick-ladder-capture entry list --type native
```
