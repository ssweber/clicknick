# Multi-Row Isolation Phase 3 Verify Queue (2026-03-05)

Scenario: `grid_multirow_isolation_phase3_20260305`

Focus: row0 key-byte companion + row1 offset-band minimization.

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_isolation_phase3_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label mriso3_control_row0_row1_full --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_only_keybytes --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_plus_row1_01_05 --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_plus_row1_01_05_38_3d --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_plus_row1_09_0c --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_plus_row1_09_11 --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_plus_row1_0d_11 --source file
uv run clicknick-ladder-capture verify run --label mriso3_row0_plus_row1_38_3d --source file
uv run clicknick-ladder-capture verify run --label mriso3_row1_only_full --source file
```

## Cases

- `mriso3_control_row0_row1_full`
- `mriso3_row0_only_keybytes`
- `mriso3_row0_plus_row1_01_05`
- `mriso3_row0_plus_row1_01_05_38_3d`
- `mriso3_row0_plus_row1_09_0c`
- `mriso3_row0_plus_row1_09_11`
- `mriso3_row0_plus_row1_0d_11`
- `mriso3_row0_plus_row1_38_3d`
- `mriso3_row1_only_full`
