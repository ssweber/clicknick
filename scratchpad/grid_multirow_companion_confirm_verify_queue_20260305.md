# Multi-Row Companion Confirm Queue (2026-03-05)

Scenario: `grid_multirow_companion_confirm_20260305`

Purpose: confirm tool-based two-row companion application and probe three-row companion transfer behavior.

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_companion_confirm_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label gmc_grid2_no_companion --source file
uv run clicknick-ladder-capture verify run --label gmc_grid2_with_companion --source file
uv run clicknick-ladder-capture verify run --label gmc_grid3_ablate_all --source file
uv run clicknick-ladder-capture verify run --label gmc_grid3_restore_all --source file
uv run clicknick-ladder-capture verify run --label gmc_grid3_restore_col31_only --source file
uv run clicknick-ladder-capture verify run --label gmc_grid3_restore_row1_only --source file
```

## Cases

- `gmc_grid2_no_companion`
- `gmc_grid2_with_companion`
- `gmc_grid3_ablate_all`
- `gmc_grid3_restore_all`
- `gmc_grid3_restore_col31_only`
- `gmc_grid3_restore_row1_only`
