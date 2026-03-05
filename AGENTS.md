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
- Do not use retired tools:
  - `devtools/capture.py`
  - `devtools/clipboard_load.py`
  - `devtools/update_ladder_capture_manifest.py`
  - `scratchpad/pasteback_smoke.py`

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
- Shorthand source for prepare/verify generation currently supports a simple single-row path; it requires at least one contact and a non-empty AF instruction.
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
- `add --type {native|synthetic|patch|pasteback} --label <label> --scenario <scenario> --description <description> --row <row> [--payload-source {shorthand|file}] [--payload-file <path>] [--json]`
- `add-patch-batch --scenario <scenario> --row <row> [--file <path>] [--glob <pattern>] [--label-prefix <prefix>] [--description-prefix <text>] [--skip-existing] [--json]`
- `list [--type {native|synthetic|patch|pasteback}] [--status {unverified|verified_pass|verified_fail|blocked}] [--json]`
- `show --label <label> [--json]`
- `capture --label <label> [--output-file <path>] [--json]`

Verify:
- `prepare --label <label> [--source {shorthand|file}] [--uid <uid_or_hwnd>] [--mdb-path <path>] [--no-ensure-mdb-addresses] [--json]`
- `complete --label <label> --status {unverified|verified_pass|verified_fail|blocked} --clipboard-event {copied|crash|cancelled} [--note <text>] [--row <row>] [--result-file <path>] [--json]`
- `run --label <label> [--source {shorthand|file}] [--uid <uid_or_hwnd>] [--mdb-path <path>] [--no-ensure-mdb-addresses] [--status-default {unverified|verified_pass|verified_fail|blocked}] [--json]`

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
