# Grid Non-Empty Multi-Row 4+/Row-Combo Verify Queue (March 6, 2026)

Scenario: `grid_nonempty_multirow_rowcombo_20260306`  
Case count: `12`  
Payload source mode: `file`

## Why This Batch
- Validate 2/3-row horizontal/vertical findings against 4-row and 5-row payloads before implementation planning.
- Probe non-contiguous link combinations (sparse vertical placement) and asymmetry (`T` cell with one-sided horizontal flags).
- Confirm column-scaling behavior beyond prior col1-only controls.

## Cases
1. `gnmr4_vert_chain_c1` - rows4 vertical chain at col1 (`r0->r1->r2`)
2. `gnmr4_vert_chain_c1_drop_r1` - rows4 chain with middle link dropped
3. `gnmr4_vert_chain_c1_drop_r2` - rows4 chain with lower link dropped
4. `gnmr4_vert_only_r2_c1` - rows4 sparse single link at `r2 c1`
5. `gnmr4_vert_chain_c3` - rows4 vertical chain shifted to col3
6. `gnmr4_horiz_r2_c1_only` - rows4 horizontal-only at `r2 c1`
7. `gnmr4_t_r2_c1` - rows4 `T` at `r2 c1`
8. `gnmr4_t_r2_c1_keep_hright` - rows4 asymmetry (`hright+vdown` only)
9. `gnmr4_t_r2_c1_keep_hleft` - rows4 asymmetry (`hleft+vdown` only)
10. `gnmr5_vert_chain_c1` - rows5 vertical chain at col1 (`r0->r1->r2->r3`)
11. `gnmr5_vert_alt_r0_r2` - rows5 sparse links at `r0 c1` and `r2 c1`
12. `gnmr5_mix_row1T_row3D` - rows5 mixed topology (`row1 col1 T`, `row3 col3 vertical`)

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_nonempty_multirow_rowcombo_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- For each case, record: `status`, `event`, `clipboard_len`.
- If observed rows diverge, choose `edit` and enter exact observed rows using `-`, `|`, `T`.
- Short note only for ambiguous/operator-error situations.

Send `done` when complete.
