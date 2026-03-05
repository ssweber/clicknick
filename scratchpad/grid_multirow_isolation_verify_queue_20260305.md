# Multi-Row Isolation Verify Queue (2026-03-05)

Scenario: `grid_multirow_isolation_20260305`

Base failing source: `grid_synth_empty_rows1_2_synthetic`
Donor native source: `grid_empty_rows1_2_recapture_native`

## Recommended Guided Run

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_isolation_20260305`

## Direct Label Commands (Alternative)

```powershell
uv run clicknick-ladder-capture verify run --label mriso_mriso_all_native2_control --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_h17_only --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_header_full --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_header_row1 --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_header_tail --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_pre_full --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_pre_header --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_row0_full --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_row1_full --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_row1_tail --source file
uv run clicknick-ladder-capture verify run --label mriso_mriso_tail_full --source file
```

## Cases

- `mriso_mriso_all_native2_control`
- `mriso_mriso_h17_only`
- `mriso_mriso_header_full`
- `mriso_mriso_header_row1`
- `mriso_mriso_header_tail`
- `mriso_mriso_pre_full`
- `mriso_mriso_pre_header`
- `mriso_mriso_row0_full`
- `mriso_mriso_row1_full`
- `mriso_mriso_row1_tail`
- `mriso_mriso_tail_full`
