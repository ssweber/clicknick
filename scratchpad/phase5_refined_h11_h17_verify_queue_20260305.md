# Phase 5 Refined Verify Queue (2026-03-05)

Scenario: `grid_basics_phase5_refined_h11_h17_20260305`

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_basics_phase5_refined_h11_h17_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_crossapp_a_source_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_crossapp_b_pasteback_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_row1_single_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_row2_duplicate_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_rows1_2_combined_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_width_default_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_width_narrow_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_empty_width_wide_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_wire_a_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_width_default_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_width_narrow_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_width_wide_native --source file
uv run clicknick-ladder-capture verify run --label phase5r_grid_phase5_refined_h11_h17__grid_wire_full_row_native --source file
```

## Cases

- `phase5r_grid_phase5_refined_h11_h17__grid_empty_crossapp_a_source_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_crossapp_b_pasteback_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_row1_single_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_row2_duplicate_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_rows1_2_combined_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_width_default_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_width_narrow_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_empty_width_wide_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_wire_a_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_width_default_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_width_narrow_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_wire_ab_width_wide_native`
- `phase5r_grid_phase5_refined_h11_h17__grid_wire_full_row_native`
