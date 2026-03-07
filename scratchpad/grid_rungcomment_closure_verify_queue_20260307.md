# RungComment Closure Verify Queue (March 7, 2026)

Scenario: `grid_rungcomment_closure_20260307`

Case count: `11`

Fixed row:
- `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP`

## Queue Order
1. `grcc_short_plain_control_from_no`
   - Expect `A1` to paste and copy back cleanly.
2. `grcc_style_min_bold_handcrafted`
   - Hand-crafted minimal bold RTF: `{\rtf1\ansi\ansicpg1252 \b Hello \b0}`
   - Record one of: `renders bold`, `raw RTF text`, `plain text only`, `crash`.
3. `grcc_style_min_italic_handcrafted`
   - Only run if the bold handcrafted probe passed cleanly.
   - If bold did not pass cleanly, use `s` to skip this entry.
4. `grcc_style_min_underline_handcrafted`
   - Only run if the bold handcrafted probe passed cleanly.
   - If bold did not pass cleanly, use `s` to skip this entry.
5. `grcc_max1400_native_control`
   - Native 1400-char control.
   - Record whether the comment displays immediately after paste.
6. `grcc_max1400_synth_compare`
   - Current best synthetic 1400-char payload (`len+payload + 0x08BD..0x08FC`).
   - Record whether display is immediate, requires `Edit Comment` open/close, or is otherwise wrong.
7. `grcc_max1400_synth_reopen`
   - Same payload as the prior case.
   - Special step: after paste, save project, reopen Click/project, inspect comment display, then copy back.
8. `grcc_max1400_synth_diff22`
   - Narrowing case: only the 22 changed offsets in `0x08BD..0x08FC`.
9. `grcc_max1400_synth_coreclusters`
   - Narrowing case: `0x08D5..0x08DD` (minus `0x08D8`), `0x08E9..0x08F1`, and `0x08FC`.
10. `grcc_max1400_synth_coreclusters_no_08fc`
   - Narrowing case: same core clusters without `0x08FC`.
11. `grcc_max1400_synth_singletons`
   - Narrowing case: only `0x08C4`, `0x08CD`, `0x08D0`, `0x08E1`, and `0x08FC`.

## Operator Path
1. `uv run clicknick-ladder-capture tui`
2. `3`
3. `g`
4. `f`
5. Scenario filter: `grid_rungcomment_closure_20260307`

## Per-Case Operator Notes
- For copied events:
  - paste in Click
  - inspect comment rendering immediately
  - if the case is `grcc_max1400_synth_reopen`, save and reopen before copy-back
  - copy back in Click
  - press `c`
- Put the rendering observation in the notes field. Short notes are enough:
  - `immediate display`
  - `needed Edit Comment open/close`
  - `displayed after reopen`
  - `raw RTF text`
  - `plain only`
  - `crash`
- If `grcc_style_min_bold_handcrafted` does not pass cleanly, skip the italic/underline entries with `s`.

## Completion
- After the queue finishes, send `done`.
