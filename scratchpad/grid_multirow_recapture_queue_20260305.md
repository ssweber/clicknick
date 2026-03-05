# Multi-Row Recapture Queue (2026-03-05)

Scenario: `grid_multirow_recapture_20260305`

## Step 1: Capture Native Payloads

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `2` (Capture native payload guided queue)
2. Capture both entries when prompted

## Step 2: Verify from Captured Files

Run TUI again:

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:
1. `3` (Verify run)
2. `g` (guided queue)
3. `f` (payload source override = file)
4. Scenario filter: `grid_multirow_recapture_20260305`

## Direct Commands (Alternative)

```powershell
uv run clicknick-ladder-capture entry capture --label grid_empty_rows1_2_3_recapture_native
uv run clicknick-ladder-capture entry capture --label grid_empty_rows1_2_recapture_native
uv run clicknick-ladder-capture verify run --label grid_empty_rows1_2_3_recapture_native --source file
uv run clicknick-ladder-capture verify run --label grid_empty_rows1_2_recapture_native --source file
```

## Entries

- `grid_empty_rows1_2_3_recapture_native`
- `grid_empty_rows1_2_recapture_native`
