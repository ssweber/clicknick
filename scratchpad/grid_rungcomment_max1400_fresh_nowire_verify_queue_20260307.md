# Max1400 Fresh No-Wire Verify Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_fresh_nowire_20260307`

Case count: `5`

Important:
- This queue supersedes the mixed fresh-narrow batch for direct fresh-native comparison.
- Every synthetic here is source-level `R,...,:,NOP` with row0 col31 `+0x19/+0x1D` cleared to match the fresh native capture.

## Queue Order
1. `grcmfw_native_fresh_control`
   - Fresh native no-wire control.
   - Record whether the comment displays immediately after paste.
2. `grcmfw_synth_nowire_base`
   - Fresh-donor no-wire synthetic base.
   - This is the correct first synthetic comparison against the fresh native control.
3. `grcmfw_synth_nowire_plus_0897`
   - Adds fresh-native lower-tail byte `0x0897`.
4. `grcmfw_synth_nowire_plus_0a59`
   - Adds fresh-native trailer byte `0x0A59`.
5. `grcmfw_synth_nowire_plus_0897_0a59`
   - Adds both `0x0897` and `0x0A59`.

## Operator Path
1. `uv run clicknick-ladder-capture tui`
2. `3`
3. `g`
4. `f`
5. Scenario filter: `grid_rungcomment_max1400_fresh_nowire_20260307`

## Per-Case Operator Notes
- For copied events:
  - paste in Click
  - inspect the comment immediately
  - if hidden, open `Edit Comment` only if needed to classify whether that refresh reveals it
  - copy back in Click
  - press `c`
- Record one short note:
  - `immediate display`
  - `needed Edit Comment`
  - `displayed after reopen`
  - `hidden comment`
  - `crash`

## Completion
- After the queue finishes, send `done`.
