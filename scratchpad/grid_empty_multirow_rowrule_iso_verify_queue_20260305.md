# Grid Empty Multi-Row Row-Rule Isolation Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso_20260305`  
Case count: `6`  
Payload source mode: `file`

## Why This Batch
- Confirm whether unresolved bytes (`cell +0x0B`, `cell +0x15`, header `+0x05`, trailer `0x0A59`, `cell +0x05` base shift) are structural or context-only for empty multi-row behavior.
- All cases are derived from native `gnenp_rows04_native` (4-row empty).

## Cases
1. `rriso4_control_native4`
2. `rriso4_patch_cell0b_42_only`
3. `rriso4_patch_cell15_row0_only`
4. `rriso4_patch_cell0b42_cell15row0`
5. `rriso4_patch_header05_t59_set01`
6. `rriso4_patch_cell05_plus3`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 4-row empty.

Send `done` when complete.
