# Grid Empty Multi-Row Row-Rule Isolation 8 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso8_20260305`  
Case count: `7`  
Payload source mode: `file`

## Why This Batch
- Round 7 proved tuple+`+0x39` needs both rows, but not row1-col31 specifically.
- This batch probes sparsity threshold: how much `+0x39` coverage is required per row.

## Cases
1. `rriso42g_control_native2`
2. `rriso42g_tuple_only`
3. `rriso42g_tuple_row39_sparse_c0_c0`
4. `rriso42g_tuple_row39_row0full_row1c0`
5. `rriso42g_tuple_row39_row0c0_row1full`
6. `rriso42g_tuple_row39_row0full_row1c0_15`
7. `rriso42g_tuple_row39_row0full_row1c0_30`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso8_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 2-row empty.

Send `done` when complete.
