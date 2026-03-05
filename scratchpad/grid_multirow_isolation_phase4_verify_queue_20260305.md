# Multi-Row Isolation Phase 4 Verify Queue (2026-03-05)

Scenario: `grid_multirow_isolation_phase4_20260305`

Focus: minimize row1 subset within 0x0D..0x11 when row0 key bytes are present.

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_isolation_phase4_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label mriso4_control_row0_plus_0d_11 --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_0d_0f --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_0d_10 --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_0d_only --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_0e_only --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_0f_11 --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_0f_only --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_10_11 --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_10_only --source file
uv run clicknick-ladder-capture verify run --label mriso4_row0_plus_11_only --source file
```

## Cases

- `mriso4_control_row0_plus_0d_11`
- `mriso4_row0_plus_0d_0f`
- `mriso4_row0_plus_0d_10`
- `mriso4_row0_plus_0d_only`
- `mriso4_row0_plus_0e_only`
- `mriso4_row0_plus_0f_11`
- `mriso4_row0_plus_0f_only`
- `mriso4_row0_plus_10_11`
- `mriso4_row0_plus_10_only`
- `mriso4_row0_plus_11_only`
