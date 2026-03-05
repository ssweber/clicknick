# Grid Empty Multi-Row Row-Rule Isolation 7 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso7_20260305`  
Case count: `7`  
Payload source mode: `file`

## Why This Batch
- Round 6 found minimal pass condition under tuple seed includes `cell +0x39`.
- This batch answers:
  - does `+0x39` work without tuple?
  - is row0-only or row1-only `+0x39` sufficient?
  - does terminal-row col31 behavior at `+0x39` matter?

## Cases
1. `rriso42f_control_native2`
2. `rriso42f_row39_only_no_tuple`
3. `rriso42f_tuple_only`
4. `rriso42f_tuple_row39_canonical`
5. `rriso42f_tuple_row39_row0_only`
6. `rriso42f_tuple_row39_row1_only`
7. `rriso42f_tuple_row39_allones`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso7_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
