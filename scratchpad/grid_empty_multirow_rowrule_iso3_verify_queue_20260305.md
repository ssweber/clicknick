# Grid Empty Multi-Row Row-Rule Isolation 3 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso3_20260305`  
Case count: `5`  
Payload source mode: `file`

## Why This Batch
- Round 2 proved `header +0x05` and `0x0A59` are hard gates in the 4-row family (`h17=0x40`).
- This batch tests whether the same gate behavior holds in the 2-row recapture family (`h17=0x42`).

## Cases
1. `rriso42_control_native2`
2. `rriso42_patch_header05_only_01`
3. `rriso42_patch_t59_only_01`
4. `rriso42_patch_header05_t59_01`
5. `rriso42_patch_header05_t59_02`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso3_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
