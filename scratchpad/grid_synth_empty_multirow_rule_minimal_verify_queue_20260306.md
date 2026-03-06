# Grid Synth Empty Multi-Row Rule-Minimal Verify Queue (March 6, 2026)

Scenario: `grid_synth_empty_multirow_rule_minimal_20260306`  
Case count: `4`  
Payload source mode: `file`

## Why This Batch
- Applies the proven empty multi-row row rules to the larger native families (`4/9/17/32` rows),
  while intentionally dropping low-confidence bytes (`cell +0x0B`, `cell +0x15`).
- Goal: confirm whether the proven rule set alone is sufficient for synthetic multi-row pasteback.

## Cases
1. `gmrs_rows04_rule_minimal`
2. `gmrs_rows09_rule_minimal`
3. `gmrs_rows17_rule_minimal`
4. `gmrs_rows32_rule_minimal`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_synth_empty_multirow_rule_minimal_20260306`

## Verify Discipline
- For copied events: paste in Click, then copy back in Click, then press `c`.
- Record observed rows exactly (`R,...` for row 1, `,...` for continuation rows).
- Mark `verified_pass` only when row count and row content match expected.

Send `done` when complete.
