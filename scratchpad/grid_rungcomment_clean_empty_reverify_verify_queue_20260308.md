# Clean Empty-Rung Comment Re-Verification Queue (March 8, 2026)

## Scenario

- Scenario: `grid_rungcomment_clean_empty_reverify_20260308`
- Case count: `8`
- Case spec: `scratchpad/phase2_rungcomment_clean_empty_reverify_case_specs_20260308.json`
- Tooling audit: `scratchpad/rungcomment_tooling_audit_20260308.md`

## Intent

Reset comment support to unknown and rebuild the evidence from a truly empty visible-rung baseline.

Interpretation rules for this round:
- do **not** use the old "immediate display vs shows after reopen" explanation as a safe fallback
- if paste creates the wrong rung shape, classify it as structural failure
- metadata region and visible rows are separate:
  - metadata region: `0x0254..0x0A5F`
  - row0 band: starts at `0x0A60`

## Operator Run Path

1. Capture queue: `uv run clicknick-ladder-capture tui`
2. In TUI choose `2` for native capture queue
3. Copy each native rung in Click when prompted
4. Verify queue: `uv run clicknick-ladder-capture tui`
5. In TUI choose `3 -> g -> f`
6. Enter scenario filter: `grid_rungcomment_clean_empty_reverify_20260308`
7. After the full verify queue is complete, send `done`

## Comment Bodies

- Short body: `scratchpad/rungcomment_short_body_20260308.txt`
  - exact text: `Hello`
- Medium body: `scratchpad/rungcomment_medium_body_20260308.txt`
  - exact length: `256`
- Max body: `scratchpad/max1400_comment_body_20260307.txt`
  - exact length: `1400`

Use plain comment text only. No bold, italic, underline, font changes, or mixed styling.

## Cases

1. `grcecr_empty_native_20260308`
   - Build a truly empty 1-row rung:
   - visible row should stay empty, no wires, no AF instruction, no comment
   - expected shorthand: `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,...`

2. `grcecr_short_native_20260308`
   - Same empty 1-row rung plus short comment body `Hello`
   - visible row should still be truly empty

3. `grcecr_medium_native_20260308`
   - Same empty 1-row rung plus deterministic 256-char body from file
   - visible row should still be truly empty

4. `grcecr_max1400_native_20260308`
   - Same empty 1-row rung plus deterministic 1400-char body from file
   - visible row should still be truly empty

5. `grcecr_fullwire_native_20260308`
   - Fresh 1-row full horizontal wire reference
   - expected visible shape: full horizontal line across condition columns

6. `grcecr_fullwire_nop_native_20260308`
   - Fresh 1-row full horizontal wire with AF `NOP`
   - expected visible shape: full horizontal line plus row AF `NOP`

7. `grcecr_rows2_empty_native_20260308`
   - Fresh 2-row empty reference
   - both visible rows should stay empty

8. `grcecr_rows2_vert_horiz_native_20260308`
   - Fresh 2-row mixed-wire reference
   - expected shorthand:
   - `R,,T,...,:,...`
   - `,,-,...,:,...`

## Verify Guidance

For copied events:
- paste in Click
- inspect the immediate visible rung shape before save/reopen
- copy back in Click
- press `c`

If the visible shape is wrong:
- mark `verified_fail`
- enter observed rows that match what Click visibly rendered
- if an empty-rung comment case pastes as a default horizontal wire rung, record that explicit visible wire form

If Click crashes:
- mark `blocked`

Secondary note only:
- if you also check save/reopen, record that in the note field, but do not let it override the immediate structural classification

## Offline Follow-Up After `done`

Required comparisons after the operator run:
- empty vs short/medium/max1400 over `0x0254..0x0A5F`
- empty vs short/medium/max1400 over the row0 band
- metadata slots `0x0254 + n*0x40` vs row0-band cells `0x0A60 + n*0x40`
- gap region `0x0A54..0x0A5F`

Gate for Phase 2:
- comments only count as working if the clean empty-rung topology remains intact and copy-back behavior is native-equivalent
