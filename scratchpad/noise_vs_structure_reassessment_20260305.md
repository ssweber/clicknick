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

## Confidence Calls (Current State)

Confident noise candidates:

- Header entry-local session tuple offsets:
  - `+0x05`, `+0x11`, `+0x17`, `+0x18` (all 32 header entries)
- Trailer mirror:
  - `0x0A59`

Still unresolved / needs manual evidence:

- Width-sensitive offsets (narrow/default/wide)
- Which offsets are structural for horizontal-only grid layouts vs session/context drift
- Final minimal mask that preserves Click paste semantics across empty/wire baselines

## Manual Capture/Verify Queue (Pending)

Phase 3 entries were added to active manifest under scenario:

- `grid_basics_empty_template_20260305`

Pending manual steps:

1. Capture payloads (`entry capture`) for all new `grid_*_native` labels.
2. Verify from captured files (`verify run --source file`) with note tags:
   - `[width=default|narrow|wide]`
   - `[window=A|B]`
   - `[context=row1|row2|rows1_2|crossapp]`
3. Re-run noise overlay on completed empty/wire/width/crossapp set.
4. Apply candidate masks and verify pasteback stability.

## Recommended Next Lane

1. Complete native/synthetic verify backlog in active manifest.
2. Finish empty-template + horizontal capture/verify pass.
3. Recompute overlay with width and cross-app cohorts.
4. If masked payloads paste cleanly:
   - proceed to empty-template-driven grid synthesis tooling.
5. If masked payloads fail:
   - isolate remaining volatile clusters before expanding encoder scope.
