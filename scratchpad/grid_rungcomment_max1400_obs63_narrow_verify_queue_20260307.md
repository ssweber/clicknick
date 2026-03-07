# Max1400 Observed-63 Narrow Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_obs63_narrow_20260307`

Case count: `6`

Purpose:
- Start from the known failing `commentwin` scope.
- Test whether the `63` observed verify-back offsets are enough to restore the passing no-wire/max1400 behavior.

## Queue Order
1. `grcmft_max1400_fresh_control`
   - Fresh native max1400 no-wire control.
2. `grcmft_commentwin_fail_control`
   - Known fail control.
   - Expected behavior: `wire rung; hidden comment`.
3. `grcmft_commentwin_plus_obs63`
   - Add all 63 observed offsets.
4. `grcmft_commentwin_plus_row0tail63part`
   - Add only row0 c24..31 `+0x05/+0x09`.
5. `grcmft_commentwin_plus_row1head63part`
   - Add only row1 c0..22 `+0x05/+0x09` plus row1 c23 `+0x05`.
6. `grcmft_commentwin_plus_obs63_no_c23`
   - Add all 63 observed offsets except row1 c23 `+0x05`.

## Operator Path
1. `uv run clicknick-ladder-capture tui`
2. `3`
3. `g`
4. `f`
5. Scenario filter: `grid_rungcomment_max1400_obs63_narrow_20260307`

## Per-Case Operator Notes
- For copied events:
  - paste in Click
  - classify visible rung shape first:
    - `no wire`
    - `wire rung`
  - then classify comment behavior:
    - `immediate display`
    - `needed Edit Comment`
    - `displayed after reopen`
    - `hidden comment`
  - copy back in Click
  - press `c`
- Short combined notes are enough:
  - `no wire; immediate display`
  - `no wire; hidden comment`
  - `wire rung; hidden comment`
  - `crash`

## Completion
- After the queue finishes, send `done`.
