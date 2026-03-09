# Clicknick Status

Last updated: March 9, 2026

This file is the repo entrypoint for current state. It replaces `HANDOFF.md`
as the short operational summary.

## Canonical Sources

- Format and encoder model: `src/clicknick/ladder/encode.py`
- Supported / guarded / unsupported surface area:
  `CHECKLIST.md`
- Shared terminology and byte-layout definitions:
  `DEFINITIONS.md`
- Manifest / capture workflow:
  `AGENTS.md`

## Current Encoder Boundary

- Supported:
  - empty rungs, 1..32 rows
  - wire-only rungs, 1..32 rows
  - wire + `NOP`, 1..32 rows
  - plain single-line comments on 1-row rungs, lengths 1..1400
  - 1-row plain comment + wires (full and sparse, via phase-A stride)
  - 1-row plain comment + `NOP` (via phase-A slot 62)
  - 1-row plain comment + wires + `NOP` (combined, up to max 1400 chars)
- Not supported:
  - multi-row comments (native 2-row captures collected for future work)
  - styled comments
  - contacts / comparisons
  - AF coils (`out`, `latch`, `reset`)
  - general instruction-stream placement

## Operational Notes

- Use `uv run clicknick-ladder-capture ...` for manifest and verify workflow.
- Do not edit `scratchpad/ladder_capture_manifest.json` by hand.
- Approved payload patch helpers currently kept in `devtools/`:
  - `noise_apply.py`
  - `patch_capture_cells.py`
  - `two_series_patch_harness.py`

## Cleanup Direction

- `HANDOFF.md` is now historical and should not be used as the primary start
  point for new work.
- Reverse-engineering notes and one-off experiments belong under `scratchpad/`.
