# Max1400 Structural Blocks Verify Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_struct_blocks_20260307`

Case count: `7`

Purpose:
- Start from the known failing `commentwin` control.
- Split the true source delta to the passing `commentgrid` case into:
  - non-grid `120`-byte block
  - row0 structural block
  - row1 structural block
  - combined row0+row1 block

## Queue Order
1. `grcmfr_max1400_fresh_control`
   - Fresh native max1400 no-wire control.
2. `grcmfr_commentwin_fail_control`
   - Known fail control.
   - Expected behavior: `wire rung; hidden comment`.
3. `grcmfr_commentgrid_pass_control`
   - Known pass control.
   - Expected behavior: `no wire; immediate display`.
4. `grcmfr_commentwin_plus_outside120`
   - Add only the `120` non-grid source offsets.
5. `grcmfr_commentwin_plus_row0full`
   - Add only the full row0 structural source block.
6. `grcmfr_commentwin_plus_row1full`
   - Add only the full row1 structural source block.
7. `grcmfr_commentwin_plus_row0_row1full`
   - Add the full row0+row1 structural source blocks.

## Operator Path
1. `uv run clicknick-ladder-capture tui`
2. `3`
3. `g`
4. `f`
5. Scenario filter: `grid_rungcomment_max1400_struct_blocks_20260307`

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
