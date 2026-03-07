# Max1400 Row32 Full-Wire Native Pair Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_row32_fullwire_native_20260307`

Case count: `2`

Case spec:
- `scratchpad/phase2_rungcomment_max1400_row32_fullwire_native_20260307.json`

Purpose:
- Capture a fresh row32 full-wire no-comment / max1400 native pair.
- Use the pair to test whether the max1400 scaling signature depends on empty rows acting as carriers.

Entries:
1. `grc32fw_no_comment_native_20260307`
   - Row32 native full-wire no-comment control.
2. `grc32fw_max1400_native_20260307`
   - Row32 native full-wire max1400 control.
   - Comment body file: `scratchpad/max1400_comment_body_20260307.txt`
   - Required comment length: `1400`

## Authoring Target
- Row count: `32`
- Visible shape:
  - every row should show a full horizontal wire across all condition columns A..AE
- Stored rows:
  - row 0: `R,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,:,...`
  - rows 1..31: `,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,:,...`

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `2`
3. Scenario filter: `grid_rungcomment_max1400_row32_fullwire_native_20260307`
4. Capture both entries.
5. In the same TUI session, run verify:
6. `3`
7. `g`
8. `f`
9. Scenario filter: `grid_rungcomment_max1400_row32_fullwire_native_20260307`

## Per-Case Notes
- `grc32fw_no_comment_native_20260307`
  - Leave rung comment empty.
- `grc32fw_max1400_native_20260307`
  - Paste the exact body from `scratchpad/max1400_comment_body_20260307.txt`.
  - Confirm the comment length is exactly `1400`.
- For copied events:
  - paste in Click
  - confirm the visible shape is still a full horizontal wire on all 32 rows
  - copy back in Click
  - press `c`
- Record short notes only if something is surprising or ambiguous.

## Decision Readout
- If the max1400 case still allocates the same extra `0x1000` page class seen in the empty-row pair, empty-row carriers are weakened.
- If the full-wire pair collapses to the no-comment size or changes family sharply, empty-row carriers become more plausible.

## Completion
- After both captures and both verify runs finish, send `done`.
