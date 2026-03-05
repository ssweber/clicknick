# Grid +0x18 Isolation Verify Queue (2026-03-05)

Scenario: `grid_synth_h18_isolation_20260305`

Source baseline: `grid_synth_empty_template_20260305` pass cases only (4 labels).
Excluded baseline mismatch: `grid_synth_empty_rows1_2_synthetic` (row collapse).

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_synth_h18_isolation_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_empty_row1_synthetic__00 --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_empty_row1_synthetic__7f --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_empty_row1_synthetic__ff --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_a_synthetic__00 --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_a_synthetic__7f --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_a_synthetic__ff --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_ab_synthetic__00 --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_ab_synthetic__7f --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_ab_synthetic__ff --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_full_row_synthetic__00 --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_full_row_synthetic__7f --source file
uv run clicknick-ladder-capture verify run --label h18iso_grid_synth_wire_full_row_synthetic__ff --source file
```

## Cases

- `h18iso_grid_synth_empty_row1_synthetic__00`
- `h18iso_grid_synth_empty_row1_synthetic__7f`
- `h18iso_grid_synth_empty_row1_synthetic__ff`
- `h18iso_grid_synth_wire_a_synthetic__00`
- `h18iso_grid_synth_wire_a_synthetic__7f`
- `h18iso_grid_synth_wire_a_synthetic__ff`
- `h18iso_grid_synth_wire_ab_synthetic__00`
- `h18iso_grid_synth_wire_ab_synthetic__7f`
- `h18iso_grid_synth_wire_ab_synthetic__ff`
- `h18iso_grid_synth_wire_full_row_synthetic__00`
- `h18iso_grid_synth_wire_full_row_synthetic__7f`
- `h18iso_grid_synth_wire_full_row_synthetic__ff`
