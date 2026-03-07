# Max1400 Native Recapture Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_recapture_20260307`

Case count: `1`

Entry:
- `grc_max1400_fresh_native_20260307`

Authoring target:
- Row shorthand: `R,...,:,NOP`
- Canonical row: `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP`
- Comment body file: `scratchpad/max1400_comment_body_20260307.txt`
- Required comment length: `1400`

Purpose:
- Capture one fresh native max1400 `NOP` rung using the same comment body as the existing donor lane.
- Use this recapture as the direct native comparison source for the current synthetic max1400 UI-refresh defect.

## Operator Path
1. In Click, create a single rung with row `R,...,:,NOP`.
2. Open rung comment editor and paste the exact body from `scratchpad/max1400_comment_body_20260307.txt`.
3. Confirm the entered comment length is exactly `1400`.
4. Copy that rung in Click.
5. Run `uv run clicknick-ladder-capture entry capture --label grc_max1400_fresh_native_20260307`

Alternative guided path:
1. `uv run clicknick-ladder-capture tui`
2. `2`
3. Select `grc_max1400_fresh_native_20260307` when prompted

## Completion
- After the capture succeeds, send `done`.
