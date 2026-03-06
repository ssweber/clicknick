# Grid Non-Empty Multi-Row Impl Smoke Verify Queue (March 6, 2026)

Scenario: `grid_nonempty_multirow_impl_smoke_20260306`  
Case count: `5`  
Payload source mode: `file`

## Why This Batch
- Smoke-check the new `synthesize_nonempty_multirow(...)` outputs in Click before broader rollout.
- Cover row-count scaling (`2`, `3`, `4`, `9`, `32`) and key topology types (`-`, `|`, `T`).
- Include one deep-row mixed-cell probe (`row30 col1`) to confirm max-depth handling.

## Cases
1. `gnmi02_horiz_r1_c1` - rows2 horizontal at `row1 col1`
2. `gnmi03_vert_chain_c1` - rows3 vertical chain at `col1` (`r0..r1`)
3. `gnmi04_t_r2_c1` - rows4 mixed `T` at `row2 col1`
4. `gnmi09_vert_chain_c3` - rows9 vertical chain at `col3` (`r0..r7`)
5. `gnmi32_t_r30_c1` - rows32 deep-row `T` at `row30 col1`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_nonempty_multirow_impl_smoke_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record for each case: `status`, `event`, `clipboard_len`.
- If observed rows diverge, choose `edit` and enter exact observed rows using `-`, `|`, `T`.

Send `done` when complete.
