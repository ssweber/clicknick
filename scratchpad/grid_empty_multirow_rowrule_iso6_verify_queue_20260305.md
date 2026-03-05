# Grid Empty Multi-Row Row-Rule Isolation 6 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso6_20260305`  
Case count: `9`  
Payload source mode: `file`

## Why This Batch
- Round 5 proved:
  - header-region-only transplant fails,
  - tuple + row offsets `+0x05/+0x0B/+0x39` passes.
- This batch minimizes which row offsets are actually required with tuple seed fixed.

## Cases
1. `rriso42e_control_native2`
2. `rriso42e_tuple_only`
3. `rriso42e_tuple_plus_row_05`
4. `rriso42e_tuple_plus_row_0b`
5. `rriso42e_tuple_plus_row_39`
6. `rriso42e_tuple_plus_row_05_0b`
7. `rriso42e_tuple_plus_row_05_39`
8. `rriso42e_tuple_plus_row_0b_39`
9. `rriso42e_tuple_plus_row_05_0b_39`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso6_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
