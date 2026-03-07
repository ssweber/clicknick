# Max1400 Structure Scope Verify Queue (March 7, 2026)

Scenario: `grid_rungcomment_max1400_structure_scope_20260307`

Case count: `5`

Purpose:
- Determine whether the forced wire render and hidden-comment behavior are caused by:
  - the comment window only,
  - the larger comment+grid region through `0x1A5F`,
  - or bytes beyond `0x1A5F`.

## Queue Order
1. `grcmfs_nowire_fresh_control`
   - Fresh native no-comment no-wire control.
   - Expected visible shape: no rung wire.
2. `grcmfs_max1400_fresh_control`
   - Fresh native max1400 no-wire control.
   - Expected visible shape: no rung wire, immediate comment display.
3. `grcmfs_commentwin_full`
   - Fresh no-comment base plus `0x0294..0x08FC` from fresh max1400 donor.
4. `grcmfs_commentgrid`
   - Fresh no-comment base plus `0x0294..0x1A5F` from fresh max1400 donor.
5. `grcmfs_pregrid_header_commentgrid`
   - Fresh no-comment base plus `0x0000..0x1A5F` from fresh max1400 donor.

## Operator Path
1. `uv run clicknick-ladder-capture tui`
2. `3`
3. `g`
4. `f`
5. Scenario filter: `grid_rungcomment_max1400_structure_scope_20260307`

## Per-Case Operator Notes
- For copied events:
  - paste in Click
  - first classify visible rung shape:
    - `no wire`
    - `wire rung`
  - then classify comment behavior if a comment exists:
    - `immediate display`
    - `needed Edit Comment`
    - `displayed after reopen`
    - `hidden comment`
  - copy back in Click
  - press `c`
- Short notes are enough, for example:
  - `no wire; immediate display`
  - `wire rung; hidden comment`
  - `crash`

## Completion
- After the queue finishes, send `done`.
