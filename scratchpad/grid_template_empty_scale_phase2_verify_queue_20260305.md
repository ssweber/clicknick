# Grid Template Empty Scale Phase 2 Verify Queue (March 5, 2026)

Scenario: `grid_template_empty_scale_phase2_20260305`  
Case count: `4`  
Payload source mode: `file`

## Why This Batch
Phase 1 showed all large-row payloads collapsed to 1 or 2 rows after pasteback.
This batch tests a generalized multi-row linkage rule:
- row `>=1` col `A..AF` `+0x10` populated from donor row blocks
- per-row continuation at col `AF`: `+0x38=0x01`, `+0x3D=row_index+2` for non-terminal rows
- terminal row continuation cleared (`+0x38=0x00`, `+0x3D=0x00`)

## Cases
1. `gtes2_rows04_progressive`
2. `gtes2_rows08_progressive`
3. `gtes2_rows16_progressive`
4. `gtes2_rows32_progressive`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. scenario filter: `grid_template_empty_scale_phase2_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back from Click, then press `c`.
- Record observed rows exactly as seen.
- `verified_pass` only if observed behavior matches expected row count.
- `verified_fail` for collapse/mismatch/invalid structure.
- `blocked` for crash/stuck/edit-mode failures.

Send `done` when complete.
