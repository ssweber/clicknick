# Max1400 Row32 Native Pair Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_row32_native_20260307`

Case count: `2`

Case spec:
- `scratchpad/phase2_rungcomment_max1400_row32_native_20260307.json`

Purpose:
- Capture a fresh row32 no-comment / max1400 native pair using the standard 32-row empty geometry.
- Use the pair to test whether the max1400 structural family stays localized to the low rows or scales like an extent / pseudo-row structure.

Entries:
1. `grc32_no_comment_native_20260307`
   - Row32 native no-comment control.
2. `grc32_max1400_native_20260307`
   - Row32 native max1400 control.
   - Comment body file: `scratchpad/max1400_comment_body_20260307.txt`
   - Required comment length: `1400`

## Authoring Target
- Row count: `32`
- Row 0:
  - `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,...`
- Rows 1..31:
  - `,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,...`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `2`
3. Scenario filter: `grid_rungcomment_max1400_row32_native_20260307`
4. Capture both entries.
5. In the same TUI session, run verify:
6. `3`
7. `g`
8. `f`
9. Scenario filter: `grid_rungcomment_max1400_row32_native_20260307`

## Per-Case Notes
- `grc32_no_comment_native_20260307`
  - Leave rung comment empty.
- `grc32_max1400_native_20260307`
  - Paste the exact body from `scratchpad/max1400_comment_body_20260307.txt`.
  - Confirm the comment length is exactly `1400`.
- For copied events:
  - paste in Click
  - inspect whether the row32 object displays as expected
  - copy back in Click
  - press `c`
- Expected copied verify-back length:
  - `69632`
- Record short notes only if something is surprising or ambiguous.

## Completion
- After both captures and both verify runs finish, send `done`.
