# Grid Native Empty N-Rows Probe Queue (March 5, 2026)

Scenario: `grid_native_empty_nrows_probe_20260305`  
Case count: `4`  
Capture type: `native`

## Purpose
Capture true native payloads for larger empty-rung row counts so we can infer real row-linkage structure beyond 2-3 rows.

## Cases
1. `gnenp_rows04_native`
2. `gnenp_rows09_native`
3. `gnenp_rows17_native`
4. `gnenp_rows32_native`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `2` (Capture native payload guided queue)
3. Scenario filter: `grid_native_empty_nrows_probe_20260305`
4. Complete all captures.
5. Run verify:
6. `3` (Verify run)
7. `g` (guided queue)
8. `f` (payload source override = file)
9. Scenario filter: `grid_native_empty_nrows_probe_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly.
- `verified_pass` only when expected and observed match.

Send `done` when complete.
