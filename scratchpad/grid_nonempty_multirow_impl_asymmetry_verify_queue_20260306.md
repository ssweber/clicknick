# Grid Non-Empty Multi-Row Impl Asymmetry Verify Queue (March 6, 2026)

Scenario: `grid_nonempty_multirow_impl_asymmetry_20260306`  
Case count: `9`  
Payload source mode: `file`

## Why This Batch
- Stress-test the known horizontal asymmetry edge under implementation-generated payloads.
- Compare `keep_hright` vs `keep_hleft` outcomes at multiple scales and columns.
- Keep expected topology fixed to `T` so degradation to `|` is captured as a fail.

## Cases
1. `gnmia04_t_r2_c1_control` - rows4 control `T` at `row2 col1`
2. `gnmia04_t_r2_c1_keep_hright` - rows4 keep `hright+vdown` at `row2 col1`
3. `gnmia04_t_r2_c1_keep_hleft` - rows4 keep `hleft+vdown` at `row2 col1`
4. `gnmia09_t_r7_c3_control` - rows9 control `T` at `row7 col3`
5. `gnmia09_t_r7_c3_keep_hright` - rows9 keep `hright+vdown` at `row7 col3`
6. `gnmia09_t_r7_c3_keep_hleft` - rows9 keep `hleft+vdown` at `row7 col3`
7. `gnmia32_t_r30_c1_control` - rows32 control `T` at `row30 col1`
8. `gnmia32_t_r30_c1_keep_hright` - rows32 keep `hright+vdown` at `row30 col1`
9. `gnmia32_t_r30_c1_keep_hleft` - rows32 keep `hleft+vdown` at `row30 col1`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_nonempty_multirow_impl_asymmetry_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record for each case: `status`, `event`, `clipboard_len`.
- If observed rows diverge, choose `edit` and enter exact observed rows using `-`, `|`, `T`.

Send `done` when complete.
