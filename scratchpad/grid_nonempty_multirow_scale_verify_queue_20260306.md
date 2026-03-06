# Grid Non-Empty Multi-Row Scale Verify Queue (March 6, 2026)

Scenario: `grid_nonempty_multirow_scale_20260306`  
Case count: `8`  
Payload source mode: `file`

## Why This Batch
- Validate that non-empty wire-topology findings scale beyond 5 rows to deep payloads.
- Include explicit row-count checkpoints (`9`, `17`, `32`).
- Probe deep-row asymmetry (`row30`) for `T`/horizontal behavior at max row depth.

## Cases
1. `gnms09_vert_chain_c1` - rows9 vertical chain at col1 (`r0..r7`)
2. `gnms17_vert_chain_c1` - rows17 vertical chain at col1 (`r0..r15`)
3. `gnms32_vert_chain_c1` - rows32 vertical chain at col1 (`r0..r30`)
4. `gnms32_vert_chain_c3` - rows32 vertical chain shifted to col3 (`r0..r30`)
5. `gnms32_horiz_r30_c1_only` - rows32 deep-row horizontal-only at `r30 c1`
6. `gnms32_t_r30_c1` - rows32 deep-row `T` at `r30 c1`
7. `gnms32_t_r30_c1_keep_hright` - rows32 deep-row asymmetry (`hright+vdown`)
8. `gnms32_t_r30_c1_keep_hleft` - rows32 deep-row asymmetry (`hleft+vdown`)

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_nonempty_multirow_scale_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record for each case: `status`, `event`, `clipboard_len`.
- If observed rows diverge, choose `edit` and enter exact observed rows with `-`, `|`, `T`.

Send `done` when complete.
