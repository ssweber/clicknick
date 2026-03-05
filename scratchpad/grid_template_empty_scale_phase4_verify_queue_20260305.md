# Grid Template Empty Scale Phase 4 Verify Queue (March 5, 2026)

Scenario: `grid_template_empty_scale_phase4_20260305`  
Case count: `4`  
Payload source mode: `file`

## Why This Batch
Phase 3 still collapsed to 2 rows. Native probes revealed one additional mismatch:
- native multi-row payloads are page-aligned (`0x1000`) in total length.

This batch uses all currently known rules together:
- progressive row-linkage bytes
- 16-bit row-class word at header entry0 (`(rows + 1) * 0x20`)
- page-aligned payload length

## Cases
1. `gtes4_rows04_progressive_hdrword_paged`
2. `gtes4_rows09_progressive_hdrword_paged`
3. `gtes4_rows17_progressive_hdrword_paged`
4. `gtes4_rows32_progressive_hdrword_paged`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. scenario filter: `grid_template_empty_scale_phase4_20260305`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- For multi-row observed text: only row 1 uses `R,...`; subsequent rows use `,...`.
- Record observed rows exactly and status accurately.

Send `done` when complete.
