# Multi-Row Isolation Phase 5 Verify Queue (2026-03-05)

Scenario: `grid_multirow_isolation_phase5_20260305`

Focus: minimize row0 companion bytes while keeping row1 offset 0x10 fixed.

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_isolation_phase5_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label mriso5_control_row0full_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0_0b_0_30_plus_col31_38_3d_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0_0b_0_30_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0_0b_all_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0_0b_col31_only_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0_col31_38_3d_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0_col31_all3_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso5_row0none_row1_10 --source file
```

## Cases

- `mriso5_control_row0full_row1_10`
- `mriso5_row0_0b_0_30_plus_col31_38_3d_row1_10`
- `mriso5_row0_0b_0_30_row1_10`
- `mriso5_row0_0b_all_row1_10`
- `mriso5_row0_0b_col31_only_row1_10`
- `mriso5_row0_col31_38_3d_row1_10`
- `mriso5_row0_col31_all3_row1_10`
- `mriso5_row0none_row1_10`
