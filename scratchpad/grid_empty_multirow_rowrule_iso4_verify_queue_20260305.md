# Grid Empty Multi-Row Row-Rule Isolation 4 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso4_20260305`  
Case count: `6`  
Payload source mode: `file`

## Why This Batch
- Round 3 showed single-byte edits to `header +0x05` or `0x0A59` fail in the 2-row `h17=0x42` family.
- Hypothesis: nonzero values may still work if a coherent full seed tuple is applied (`h05/h11/h17/h18/t59` together).

## Cases
1. `rriso42c_control_native2`
2. `rriso42c_seed_0103_84_01_t59_01`
3. `rriso42c_seed_0307_35_01_t59_03`
4. `rriso42c_seed_0103_42_01_t59_01`
5. `rriso42c_seed_0100_84_01_t59_01`
6. `rriso42c_seed_0103_84_01_t59_00`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso4_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
