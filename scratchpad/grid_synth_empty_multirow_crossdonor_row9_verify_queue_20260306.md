# Grid Synth Empty Multi-Row Cross-Donor Row9 Verify Queue (March 6, 2026)

Scenario: `grid_synth_empty_multirow_crossdonor_row9_20260306`  
Case count: `2`  
Payload source mode: `file`

## Why This Batch
- Prior batch proved rule-minimal synthesis passes when each row count starts from its own native donor.
- This batch removes that donor alignment and builds row9 from the row4 donor template.
- It isolates whether cross-donor metadata drift matters, and whether restoring `+0x0B/+0x15`
  changes behavior.

## Cases
1. `gmrsx_rows09_fromrow4_rule_minimal`
2. `gmrsx_rows09_fromrow4_rule_plus0b15`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_synth_empty_multirow_crossdonor_row9_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly.
- Mark `verified_pass` only when expected and observed row lists match.

Send `done` when complete.
