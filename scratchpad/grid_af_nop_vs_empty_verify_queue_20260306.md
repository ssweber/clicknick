# Grid AF `NOP` vs Empty Verify Queue (March 6, 2026)

Scenario: `grid_af_nop_vs_empty_20260306`  
Case count: `9`  
Payload source mode: `file` for verify (after native capture)

## Why This Batch
- Build matched native donor pairs where topology is fixed and AF intent changes only (`...` vs `NOP`).
- Cover row scales `1`, `2`, and `9` for phase-1 AF behavior isolation.
- Produce donor payloads needed for patch-based minimal-byte narrowing.

## Cases
1. `gafn_rows01_empty_native` - rows1 AF empty baseline
2. `gafn_rows01_nop_native` - rows1 AF `NOP`
3. `gafn_rows02_empty_native` - rows2 AF empty baseline
4. `gafn_rows02_nop_native` - rows2 AF `NOP` on row0
5. `gafn_rows02_nop_row1_native` - rows2 AF `NOP` on row1
6. `gafn_rows09_empty_native` - rows9 AF empty baseline
7. `gafn_rows09_nop_native` - rows9 AF `NOP` on row0
8. `gafn_rows09_nop_row4_native` - rows9 AF `NOP` on row4
9. `gafn_rows09_nop_row8_native` - rows9 AF `NOP` on row8

## Current State
- Payloads already captured for labels 1, 2, 3, 4, 6, and 7.
- New capture-needed labels are 5, 8, and 9.

## Operator Run Path (Capture)
1. `uv run clicknick-ladder-capture tui`
2. `2` (Capture native payload guided queue)
3. Capture all pending labels in scenario `grid_af_nop_vs_empty_20260306` (currently 3 labels)

## Operator Run Path (Verify)
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_af_nop_vs_empty_20260306`

For copied events:
- paste in Click
- copy back in Click
- press `c`

## Verify Discipline
- Record `status`, `event`, and `clipboard_len` for each case.
- If observed rows differ, enter exact observed rows.
- Add short notes only for ambiguous/operator-error outcomes.

Send `done` when both capture and verify passes are complete.
