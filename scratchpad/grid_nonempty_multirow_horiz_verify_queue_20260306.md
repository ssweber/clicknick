# Grid Non-Empty Multi-Row Horizontal Verify Queue (March 6, 2026)

Scenario: `grid_nonempty_multirow_horiz_20260306`  
Case count: `9`  
Payload source mode: `file`

## Why This Batch
- Establish a 2-row non-empty baseline where vertical continuity is fixed at col1.
- Isolate horizontal continuity bytes by toggling only `cell +0x19/+0x1D` around col1.
- Cover required morphology variants: row0-only, row1-only, both rows (same extent), and both rows (different extent).

## Cases
1. `gnmh_control_vert_b_only` - control (vertical-only, no horizontal span)
2. `gnmh_row0_only_horiz` - row0 horizontal only
3. `gnmh_row1_only_horiz` - row1 horizontal only
4. `gnmh_both_rows_horiz_same` - both rows horizontal (same extent)
5. `gnmh_both_rows_horiz_diff` - both rows horizontal (row0 extended to col0 right edge)
6. `gnmh_ablate_r1_hleft_only` - ablate row1 col1 `+0x19` only
7. `gnmh_ablate_r1_hright_only` - ablate row1 col1 `+0x1D` only
8. `gnmh_ablate_r1_both` - ablate row1 col1 `+0x19/+0x1D`
9. `gnmh_ablate_r0_both` - ablate row0 col1 `+0x19/+0x1D`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_nonempty_multirow_horiz_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- For each case, record: `status`, `event`, `clipboard_len`; add a short note only when ambiguous.
- Keep failed rungs unchanged; do not hand-edit payloads between runs.

Send `done` when complete.
