# Grid Template Empty Scale Phase 3 Verify Queue (March 5, 2026)

Scenario: `grid_template_empty_scale_phase3_20260305`  
Case count: `4`  
Payload source mode: `file`

## Why This Batch
Native probe captures show row-count metadata is a 16-bit header word at entry0 (`+0x00/+0x01`), matching:
- `row_class_word = (rows + 1) * 0x20`

This batch retests progressive multi-row empty synthesis after writing that 16-bit row-class word.

## Cases
1. `gtes3_rows04_progressive_hdrword`
2. `gtes3_rows09_progressive_hdrword`
3. `gtes3_rows17_progressive_hdrword`
4. `gtes3_rows32_progressive_hdrword`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. scenario filter: `grid_template_empty_scale_phase3_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly.
- `verified_pass` only when behavior matches expected rows.

Send `done` when complete.
