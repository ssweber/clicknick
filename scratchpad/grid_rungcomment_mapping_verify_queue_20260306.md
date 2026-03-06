# Grid RungComment Mapping Verify Queue (March 6, 2026)

Scenario: `grid_rungcomment_mapping_20260306`  
Case count: `11`  
Payload source mode: `file` for verify (after native capture)

## Why This Batch
- Map where RungComment bytes live while holding topology and AF policy fixed.
- Compare no-comment baseline against short/medium/max/UTF comment variants.
- Build donor set for follow-up patch replay (flag/content/length isolation).

## Fixed Ladder Topology
- Use exactly one row: `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP`
- Keep all other rung geometry unchanged between cases.

## Cases (set comment text/style exactly before copy)
1. `grc_no_comment_native` - empty comment field
2. `grc_short_ascii_native` - `A1`
3. `grc_medium_ascii_native` - `PHASE2_MEDIUM_COMMENT_1234567890`
4. `grc_maxlen_probe_native` - `MAXLEN_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz_0123456789`
5. `grc_utf8_probe_native` - `TEMP_degC_25` (or UI-safe non-ASCII probe if supported)
6. `grc_style_plain_native` - text `STYLE_PROBE`, plain style
7. `grc_style_bold_native` - text `STYLE_PROBE`, bold only
8. `grc_style_italic_native` - text `STYLE_PROBE`, italic only
9. `grc_style_underline_native` - text `STYLE_PROBE`, underline only
10. `grc_maxlen_1396_native` - 1400-character plain-style comment (label is historical)
  - helper text file: `scratchpad/rungcomment_1400_plain.txt` (exactly 1400 chars)
11. `grc_style_mixed_selection_native` - text `BOLDTXT BOLDITALIC BTU` with inline selection styles:
  - `BOLDTXT` = bold
  - `BOLDITALIC` = bold+italic
  - `BTU` = bold+underline

## Operator Run Path (Capture)
1. `uv run clicknick-ladder-capture tui`
2. `2` (Capture native payload guided queue)
3. Capture pending labels in scenario `grid_rungcomment_mapping_20260306`

## Current State
- Labels `1..11` are captured and verified.
- This native mapping queue is complete; keep for provenance/reference.

## Operator Run Path (Verify)
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_rungcomment_mapping_20260306`

For copied events:
- paste in Click
- copy back in Click
- press `c`

## Verify Discipline
- Record `status`, `event`, and `clipboard_len`.
- If observed rows differ, enter exact observed rows.
- For UTF probe, if UI input is blocked or normalized, use `blocked` or `verified_fail` with a short note.
- For `grc_maxlen_1396_native`, include note confirming the entered length is exactly `1400`.

Send `done` after capture+verify complete.
