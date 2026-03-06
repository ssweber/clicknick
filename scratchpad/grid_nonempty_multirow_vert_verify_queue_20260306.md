# Grid Non-Empty Multi-Row Vertical Verify Queue (March 6, 2026)

Scenario: `grid_nonempty_multirow_vert_20260306`  
Case count: `8`  
Payload source mode: `file`

## Why This Batch
- Establish 2-row and 3-row non-empty vertical controls.
- Isolate inter-row continuity by toggling only `cell +0x21` at the active vertical column.
- Probe column scaling by shifting continuity from col1 to col3.

## Cases
1. `gnmv_control_vert_b_only_2rows` - 2-row control at col1
2. `gnmv_control_vert_d_only_2rows` - 2-row control at col3
3. `gnmv_control_vert_b_3rows` - 3-row control at col1 (`r0->r1->r2`)
4. `gnmv_force_terminal_r2c1_vdown0` - terminal-row guard (explicit `r2 c1 +0x21 = 0`)
5. `gnmv_ablate_r1c1_vdown` - clear middle link (`r1 c1 +0x21 = 0`)
6. `gnmv_ablate_r0c1_vdown` - clear top link (`r0 c1 +0x21 = 0`)
7. `gnmv_ablate_r0r1_vdown` - clear both links (`r0/r1 c1 +0x21 = 0`)
8. `gnmv_shift_col1_to_col3` - shift 3-row continuity from col1 to col3

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_nonempty_multirow_vert_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- For each case, record: `status`, `event`, `clipboard_len`; add a short note only when ambiguous.
- Keep failed rungs unchanged; do not hand-edit payloads between runs.

Send `done` when complete.
