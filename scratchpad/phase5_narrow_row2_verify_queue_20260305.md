# Phase 5 Narrowing Queue (2026-03-05)

Scenario: `grid_basics_phase5_narrow_row2_20260305`

Goal: isolate which header bytes break `grid_empty_row2_duplicate_native` when donor-normalized.

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_basics_phase5_narrow_row2_20260305`

Expected rung: `R,...,:,...`

## Cases

- `phase5n_grid_phase5_narrow_row2__h05_h11_no_t59`
- `phase5n_grid_phase5_narrow_row2__h05_only`
- `phase5n_grid_phase5_narrow_row2__h05_t59`
- `phase5n_grid_phase5_narrow_row2__h11`
- `phase5n_grid_phase5_narrow_row2__t59_only`
