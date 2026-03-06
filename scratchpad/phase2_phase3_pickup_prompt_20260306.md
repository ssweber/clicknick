# Pickup Prompt: Phase 2 Patch Isolation -> Phase 3 Start (March 6, 2026)

## Read First
1. `HANDOFF.md`
2. `AGENTS.md`
3. `scratchpad/nop_af_rungcomment_prompt_20260306.md`
4. `scratchpad/phase1_af_nop_inference_20260306.md`
5. `scratchpad/phase2_rungcomment_inference_20260306.md`
6. `scratchpad/phase2_rungcomment_patch_case_specs_20260306.json`

## Current Ground Truth
- Phase 1 (`AF NOP vs empty`) is complete and gate is met.
  - row0 NOP: `row0 col31 +0x1D = 1`
  - non-first-row NOP (tested): required
    - `target row col31 +0x1D = 1`
    - `target row col0 +0x15 = 1`
- Phase 2 native mapping is complete (`11/11` pass).
  - comment length dword: `0x0294`
  - comment payload start: `0x0298`
  - observed rule: `len_dword = payload_bytes + 1` (NUL included)
  - payload is RTF-like ANSI string
  - style is inline RTF token markup (`\b`, `\i`, `\ul`) including mixed segment styling
  - max comment length confirmed at `1400` chars

## Immediate Task
Run Phase 2 patch isolation queue and classify minimal replay model.

Scenario: `grid_rungcomment_patch_isolation_20260306`
Queue doc: `scratchpad/grid_rungcomment_patch_isolation_verify_queue_20260306.md`

Operator path:
1. `uv run clicknick-ladder-capture tui`
2. `3` -> `g` -> `f`
3. scenario filter: `grid_rungcomment_patch_isolation_20260306`
4. for each case: paste in Click, inspect comment text/style, copy back, press `c`
5. send `done`

## After Operator `done`
1. Parse manifest outcomes for `grid_rungcomment_patch_isolation_20260306`.
2. Classify sufficiency/necessity for:
   - length dword only
   - payload only
   - length+payload
   - terminator coupling
   - style payload transplants
   - max1400 replay cases
3. Update artifacts:
   - `scratchpad/phase2_rungcomment_inference_20260306.md`
   - `scratchpad/phase2_rungcomment_case_specs_20260306.json`
   - `HANDOFF.md`
4. Decide Phase 2 gate: met/not met.

## If Phase 2 Gate Is Met
Begin Phase 3 setup (`CSV -> wire-only prove-out`) using the proven AF policy and optional comment model.
Create:
- `scratchpad/phase3_csv_wireonly_case_specs_20260306.json`
- `scratchpad/grid_csv_wireonly_dropinstr_verify_queue_20260306.md`
- update `scratchpad/nop_af_rungcomment_inference_20260306.md` (consolidated report scaffold if absent)

## Non-Negotiables
- Do not edit `scratchpad/ladder_capture_manifest.json` by hand.
- Use only `uv run clicknick-ladder-capture ...` workflow commands.
- Keep production codec behavior stable during RE/isolation.
