# Multi-Row Isolation Phase 2 Verify Queue (2026-03-05)

Scenario: `grid_multirow_isolation_phase2_20260305`

Goal: resolve row0-driven blocked/fail behavior by testing row0 plus companion regions.

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_isolation_phase2_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label mriso2_all_native2_control --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_header --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_header_tail --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_pre --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_pre_header --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_pre_header_tail --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_pre_tail --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_row1 --source file
uv run clicknick-ladder-capture verify run --label mriso2_row0_tail --source file
```

## Cases

- `mriso2_all_native2_control`
- `mriso2_row0_header`
- `mriso2_row0_header_tail`
- `mriso2_row0_pre`
- `mriso2_row0_pre_header`
- `mriso2_row0_pre_header_tail`
- `mriso2_row0_pre_tail`
- `mriso2_row0_row1`
- `mriso2_row0_tail`
