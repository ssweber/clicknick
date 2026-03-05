# Noise vs Structure Reassessment (2026-03-05)

## Scope

This note is the Phase 6 gate artifact for:

- Empty-template grid baseline captures (`grid_basics_empty_template_20260305`)
- Session/application noise overlays
- Mask-application safety checks

## What Is Implemented

Tooling added:

- `devtools/noise_overlay.py`
- `devtools/noise_apply.py`
- `devtools/verify_mismatch_report.py`

Coverage tests added:

- `tests/ladder/test_noise_overlay.py`
- `tests/ladder/test_noise_apply.py`
- `tests/ladder/test_verify_mismatch_report.py`

All three test files pass locally.

## Current Automated Findings

1. Synthetic mismatch summary is now machine-reported.
   - `two_series_harden_02_imm_no` is currently the known copied-but-mismatched synthetic case.

2. Session-counter pair smoke check works with new mask tooling.
   - Generated:
     - `scratchpad/noise_overlay_session_test.json`
     - `scratchpad/noise_overlay_session_test.csv`
   - Applied mask class:
     - `session_tuple_candidates` via donor-copy mode.
   - Output test artifact:
     - `scratchpad/captures/session_counter_row2_duplicate_native_masked_test.bin`

3. Width-variant check (`default/narrow/wide`) currently shows no byte-level effect.
   - Manual observation: no discernible paste difference for width variants.
   - Strict payload diff checks:
     - `grid_empty_width_default_native` vs `narrow/wide`: `0` byte diffs
     - `grid_wire_ab_width_default_native` vs `narrow/wide`: `0` byte diffs
   - `noise_overlay.py` width-family heuristic was tightened to require variation
     within true width triplets before classifying `width_candidates`.
   - Re-run result on full `grid_basics_empty_template_20260305` set:
     - `width_candidates = 0`

4. Grid-basics capture/verify pass is complete.
   - Scenario `grid_basics_empty_template_20260305`: `14/14` entries captured.
   - Verification: `14/14` `verified_pass` with clipboard event `copied`.
   - Overlay artifacts generated for both payload and verify sources:
     - `scratchpad/noise_overlay_grid_basics_20260305.json`
     - `scratchpad/noise_overlay_grid_basics_20260305.csv`
     - `scratchpad/noise_overlay_grid_basics_verify_20260305.json`
     - `scratchpad/noise_overlay_grid_basics_verify_20260305.csv`

## Confidence Calls (Current State)

Confident noise candidates:

- Header entry-local session tuple offsets:
  - `+0x05`, `+0x11`, `+0x17`, `+0x18` (all 32 header entries)
- Trailer mirror:
  - `0x0A59`

Still unresolved / needs manual evidence:

- Which offsets are structural for horizontal-only grid layouts vs session/context drift
- Final minimal mask that preserves Click paste semantics across empty/wire baselines

## Manual Capture/Verify Queue (Status)

Phase 3 entries were added to active manifest under scenario:

- `grid_basics_empty_template_20260305`

Completed manual steps:

1. Captured payloads (`entry capture`) for all `grid_*_native` labels.
2. Verified from captured files (`verify run --source file`) across the full grid-basics scenario.
3. Re-ran noise overlay on completed empty/wire/width/crossapp set.

## Recommended Next Lane

1. Execute Phase 5 mask trials on grid-basics captures:
   - start with `session_tuple_candidates` donor-copy normalization.
2. Register mask-patched payloads as `patch` entries and run guided verify.
3. If patched payloads paste cleanly:
   - proceed to empty-template-driven grid synthesis tooling.
4. If patched payloads fail:
   - narrow mask classes by removing the last-added class and retesting.
