# Max1400 Fresh-Donor Narrow Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_fresh_narrow_20260307`

Case count: `7`

Fixed row:
- `R,...,:,NOP`

## Queue Order
1. `grcmf_native_fresh_control`
   - Fresh native control.
   - Record whether the comment displays immediately after paste.
2. `grcmf_synth_hidden_control_oldbest`
   - Known hidden-control synthetic from the prior round.
   - Expected control behavior: comment stays hidden at paste time.
3. `grcmf_synth_fresh_tail`
   - Fresh-donor rebuild of the prior best synthetic.
   - Only new copied byte vs the old hidden control is `0x08D7 = 0x0F`.
4. `grcmf_synth_fresh_tail_plus_0897`
   - Adds `0x0897 = 0x0F` from the fresh native donor.
5. `grcmf_synth_fresh_tail_plus_0a59`
   - Adds trailer parity `0x0A59 = 0xFF`.
6. `grcmf_synth_fresh_tail_plus_r0c31clear`
   - Clears row0 col31 `+0x19/+0x1D` (`0x1239`, `0x123D`) to match fresh native.
7. `grcmf_synth_fresh_tail_plus_0897_0a59_r0c31clear`
   - Combined parity probe for `0x0897`, `0x0A59`, and row0-col31 flag cleanup.

## Operator Path
1. `uv run clicknick-ladder-capture tui`
2. `3`
3. `g`
4. `f`
5. Scenario filter: `grid_rungcomment_max1400_fresh_narrow_20260307`

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

## Intent
- Fresh native control anchors the immediate-display target.
- Old hidden-control synthetic confirms the prior defect still reproduces.
- The five fresh-donor probes test whether the missing native-parity bytes are:
  - upper-tail `0x08D7`
  - lower-tail `0x0897`
  - trailer `0x0A59`
  - row0-col31 `+0x19/+0x1D`
  - or only the combination.

## Completion
- After the queue finishes, send `done`.
