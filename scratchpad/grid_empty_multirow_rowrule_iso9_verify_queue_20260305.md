# Grid Empty Multi-Row Row-Rule Isolation 9 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso9_20260305`  
Case count: `7`  
Payload source mode: `file`

## Why This Batch
- Round 8 left two boundary questions:
  - Is row0 col31 required at `+0x39`?
  - Is row1 col30 required at `+0x39`?
- This batch isolates those exact column-boundary dependencies.

## Cases
1. `rriso42h_control_native2`
2. `rriso42h_tuple_only`
3. `rriso42h_tuple_row39_row0full_row1c0_30` (pass anchor)
4. `rriso42h_tuple_row39_row0full_row1c0_29`
5. `rriso42h_tuple_row39_row0c0_30_row1c0_30`
6. `rriso42h_tuple_row39_row0c0_30_row1full`
7. `rriso42h_tuple_row39_row0full_row1c1_31`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso9_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
