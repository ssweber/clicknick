# Grid Template Empty Scale Verify Queue (March 5, 2026)

Scenario: `grid_template_empty_scale_20260305`  
Case count: `8`  
Payload source mode: `file`

## Goal
Verify synthetic empty-rung payloads at larger logical row counts (4/8/16/32) with and without companion normalization.

## Cases
1. `gtes_rows04_no_companion`
2. `gtes_rows04_with_companion`
3. `gtes_rows08_no_companion`
4. `gtes_rows08_with_companion`
5. `gtes_rows16_no_companion`
6. `gtes_rows16_with_companion`
7. `gtes_rows32_no_companion`
8. `gtes_rows32_with_companion`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. scenario filter: `grid_template_empty_scale_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back from Click, then press `c`.
- Record observed rows as shown by Click after copy-back.
- Use `verified_pass` only when observed rows match expected behavior.
- Use `verified_fail` for mismatch/collapse/invalid structure.
- Use `blocked` for crash/stuck/edit-mode failures.

Send `done` when this scenario run is complete.
