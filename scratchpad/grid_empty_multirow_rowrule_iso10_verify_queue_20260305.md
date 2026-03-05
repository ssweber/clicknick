# Grid Empty Multi-Row Row-Rule Isolation 10 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso10_20260305`  
Case count: `5`  
Payload source mode: `file`

## Why This Batch
- Round 9 established boundary necessity for row1 col0 and col30, and row0 col31.
- This batch checks whether interior row1 columns are also required (single-column ablations).

## Cases
1. `rriso42i_control_native2`
2. `rriso42i_anchor_row1_c0_30`
3. `rriso42i_anchor_drop_row1_c07`
4. `rriso42i_anchor_drop_row1_c15`
5. `rriso42i_anchor_drop_row1_c23`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso10_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
