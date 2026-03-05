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

- Header entry-local offsets with verified-safe normalization on grid-basics:
  - `+0x11`, `+0x17` (all 32 header entries)

Context-sensitive / structural candidates (do not normalize globally yet):

- Header `+0x05`
- Trailer mirror `0x0A59`
- Header `+0x18` (not yet validated in a clean all-pass mask on this baseline)

## Manual Capture/Verify Queue (Status)

Phase 3 entries were added to active manifest under scenario:

- `grid_basics_empty_template_20260305`

Completed manual steps:

1. Captured payloads (`entry capture`) for all `grid_*_native` labels.
2. Verified from captured files (`verify run --source file`) across the full grid-basics scenario.
3. Re-ran noise overlay on completed empty/wire/width/crossapp set.

## Phase 5 Outcome (Finalized)

1. Baseline session-mask trial:
   - scenario: `grid_basics_phase5_session_mask_20260305`
   - result: `13/14` pass, `1/14` fail (`grid_empty_row2_duplicate_native`)
2. Narrowing on failing row2-duplicate case:
   - scenario: `grid_basics_phase5_narrow_row2_20260305`
   - result: only `h11` variant passes
   - variants touching `h05` and/or `0x0A59` fail
3. Refined mask trial:
   - scenario: `grid_basics_phase5_refined_h11_h17_20260305`
   - policy: normalize header `+0x11` and `+0x17` only
   - result: `14/14` `verified_pass`

## Recommended Next Lane

1. Use refined mask profile (`+0x11`/`+0x17` only) as the working session-noise normalization for empty/horizontal baseline workflows.
2. Keep `+0x05` and `0x0A59` untouched while building grid synthesis from empty-template captures.
3. Add a focused follow-up experiment for `+0x18` to classify it confidently as noise vs structure before broadening encoder scope.
