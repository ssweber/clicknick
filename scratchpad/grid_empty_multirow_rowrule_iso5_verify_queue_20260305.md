# Grid Empty Multi-Row Row-Rule Isolation 5 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso5_20260305`  
Case count: `6`  
Payload source mode: `file`

## Why This Batch
- Round 4 showed seed tuple edits alone still fail on 2-row empty base.
- This batch tests broader coupling by transplanting donor regions from a known nonzero-seed pass payload.

## Cases
1. `rriso42d_control_native2`
2. `rriso42d_patch_header_region_only`
3. `rriso42d_patch_preheader_header_only`
4. `rriso42d_patch_tuple_plus_row05_0b_39`
5. `rriso42d_patch_tuple_plus_full_row01`
6. `rriso42d_donor_direct`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso5_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
