# Grid Empty Multi-Row Row-Rule Isolation 2 Verify Queue (March 5, 2026)

Scenario: `grid_empty_multirow_rowrule_iso2_20260305`  
Case count: `5`  
Payload source mode: `file`

## Why This Batch
- Isolation round 1 showed:
  - `cell +0x0B`, `cell +0x15`, and shifted `cell +0x05` still verified.
  - setting header `+0x05` with trailer `0x0A59` to `0x01` failed and fragmented.
- This batch isolates independent impact of header `+0x05` vs trailer `0x0A59`.

## Cases
1. `rriso4b_control_native4`
2. `rriso4b_patch_header05_only_01`
3. `rriso4b_patch_t59_only_01`
4. `rriso4b_patch_header05_t59_01`
5. `rriso4b_patch_header05_t59_02`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_empty_multirow_rowrule_iso2_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` first row, `,...` continuation rows).
- Use `verified_pass` only when observed matches expected 4-row empty.

Send `done` when complete.
