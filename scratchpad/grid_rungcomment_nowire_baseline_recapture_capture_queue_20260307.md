# No-Wire Baseline Recapture Queue (March 7, 2026)

Scenario: `grid_rungcomment_nowire_baseline_recapture_20260307`

Case count: `1`

Entry:
- `grc_no_comment_fresh_native_20260307`

Authoring target:
- Row shorthand: `R,...,:,NOP`
- Comment: none

Purpose:
- Capture a true fresh native `R,...,:,NOP` no-comment baseline in the same family/session lane as `grc_max1400_fresh_native_20260307`.
- Stop using the older `grc_no_comment_native` as the synthetic base for this lane until family parity is re-established.

## Operator Path
1. In Click, create a single rung with row `R,...,:,NOP`.
2. Do not add a rung comment.
3. Copy that rung in Click.
4. Run `uv run clicknick-ladder-capture entry capture --label grc_no_comment_fresh_native_20260307`

Alternative guided path:
1. `uv run clicknick-ladder-capture tui`
2. `2`
3. Select `grc_no_comment_fresh_native_20260307`

## Completion
- After the capture succeeds, send `done`.
