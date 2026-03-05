# Multi-Row Isolation Phase 6 Verify Queue (2026-03-05)

Scenario: `grid_multirow_isolation_phase6_20260305`

Focus: determine whether row0 col31 +0x38 and +0x3D are jointly required, and confirm row1 +0x10 dependency.

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_isolation_phase6_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label mriso6_col31_38_3d_no_row1 --source file
uv run clicknick-ladder-capture verify run --label mriso6_col31_38_only_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso6_col31_3d_only_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso6_control_col31_38_3d_row1_10 --source file
uv run clicknick-ladder-capture verify run --label mriso6_row1_10_only_no_row0 --source file
```

## Cases

- `mriso6_col31_38_3d_no_row1`
- `mriso6_col31_38_only_row1_10`
- `mriso6_col31_3d_only_row1_10`
- `mriso6_control_col31_38_3d_row1_10`
- `mriso6_row1_10_only_no_row0`
