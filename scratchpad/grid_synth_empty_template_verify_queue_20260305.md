# Grid Synthesis Verify Queue (2026-03-05)

Scenario: `grid_synth_empty_template_20260305`

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_synth_empty_template_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label grid_synth_empty_row1_synthetic --source file
uv run clicknick-ladder-capture verify run --label grid_synth_empty_rows1_2_synthetic --source file
uv run clicknick-ladder-capture verify run --label grid_synth_wire_a_synthetic --source file
uv run clicknick-ladder-capture verify run --label grid_synth_wire_ab_synthetic --source file
uv run clicknick-ladder-capture verify run --label grid_synth_wire_full_row_synthetic --source file
```

## Cases

- `grid_synth_empty_row1_synthetic`
- `grid_synth_empty_rows1_2_synthetic`
- `grid_synth_wire_a_synthetic`
- `grid_synth_wire_ab_synthetic`
- `grid_synth_wire_full_row_synthetic`
