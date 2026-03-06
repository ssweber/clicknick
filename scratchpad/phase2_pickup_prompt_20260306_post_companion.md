# Pickup Prompt: Phase 2 RungComment Follow-Up (Post-Companion Batch, March 6, 2026)

## Read First
1. `HANDOFF.md`
2. `AGENTS.md`
3. `scratchpad/phase2_rungcomment_inference_20260306.md`
4. `scratchpad/phase2_rungcomment_case_specs_20260306.json`
5. `scratchpad/phase2_rungcomment_patch_companion_case_specs_20260306.json`
6. `scratchpad/grid_rungcomment_patch_companion_isolation_verify_queue_20260306.md`

## Current Ground Truth
- Phase 1 (`AF NOP vs empty`) is complete and gate is met.
- Phase 2 (`RungComment`) is still open; gate is **not met**.
- Native mapping (`grid_rungcomment_mapping_20260306`) is complete (`11/11` pass).
- Confirmed from native:
  - length dword at `0x0294`
  - payload start at `0x0298`
  - RTF-like ANSI payload
  - max comment length `1400`
- Patch isolation summary to date:
  - `grid_rungcomment_patch_isolation_20260306`: `3` pass / `2` fail / `7` crash
  - `grid_rungcomment_patch_companion_isolation_20260306`: `3` pass / `0` fail / `13` crash

## High-Signal Findings From Latest Batch
- Short/plain lane:
  - `len+payload` passes
  - full-window (`0x0294..0x08FC`) passes
  - tail-only (`0x030E..0x08FC`) crashes
- Style lane:
  - all probes crash (bold/italic/underline), including full-window transplants
- Max1400 lane:
  - most probes crash
  - one narrow pass: `len+payload + upper tail (0x08BD..0x08FC)` with UI caveat
    (comment appears after opening/closing Edit Comment dialog)

## Immediate Task
Run one more Phase 2 narrowing round focused on unresolved style and max1400 companions.

### Target
- Determine whether required style/max companions are outside `0x08FC` and isolate a smaller decisive set.

### Required New Scenario
- Suggested scenario name:
  - `grid_rungcomment_patch_companion_ext_isolation_20260306`
- Use file-backed patch entries (`entry add --type patch --payload-source file --payload-file ...`).
- Keep fixed rung row:
  - `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP`

### Batch Design Requirements
1. Style-focused probes:
   - extend transplant windows beyond `0x08FC` (for example into next contiguous region)
   - include bold controls plus at least two split-window ablations
   - include one italic and one underline confirm probe
2. Max1400-focused probes:
   - refine `0x08BD..0x08FC` with smaller ablations
   - add clean-display checks (not just copy-back existence)
3. Preserve at least one known passing short/plain control in the same queue.

## Operator Path (for new queue)
1. `uv run clicknick-ladder-capture tui`
2. `3` -> `g` -> `f`
3. scenario filter: `<new scenario>`
4. for copied events: paste in Click, inspect comment rendering, copy back, press `c`
5. send `done`

## After Operator `done`
1. Parse manifest outcomes for the new scenario.
2. Reclassify minimal replay model for:
   - style replay
   - max1400 replay
   - display-clean vs delayed-render behavior
3. Update:
   - `scratchpad/phase2_rungcomment_inference_20260306.md`
   - `scratchpad/phase2_rungcomment_case_specs_20260306.json`
   - `HANDOFF.md`
4. Decide Phase 2 gate (`met`/`not met`).
5. Only if met, start Phase 3 setup.

## Non-Negotiables
- Do not edit `scratchpad/ladder_capture_manifest.json` by hand.
- Use only `uv run clicknick-ladder-capture ...` workflow commands.
- Keep production codec behavior stable during RE/isolation.
