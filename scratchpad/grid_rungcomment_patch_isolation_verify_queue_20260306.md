# Grid RungComment Patch Isolation Verify Queue (March 6, 2026)

Scenario: `grid_rungcomment_patch_isolation_20260306`  
Case count: `12`  
Payload source mode: `file`

## Why This Batch
- Validate minimal replay model for RungComment (length dword + payload bytes).
- Test terminator/length coupling and reset behavior (length zero).
- Confirm style is encoded in comment payload (RTF tokens), not separate external flags.
- Confirm max-length (1400-char body) replay behavior.

## Cases (inspect comment text/style in Click)
1. `grcp2_short_len_payload_from_no` - copy short comment length+payload region from donor onto no-comment baseline (expect comment=`A1`, style=`plain`)
2. `grcp2_short_len_only_from_no` - set short donor length dword only (no payload bytes copied) (expect comment=`A1`, style=`plain`)
3. `grcp2_short_payload_only_from_no` - copy short donor payload bytes only (leave length dword at zero) (expect comment=`A1`, style=`plain`)
4. `grcp2_short_len_payload_nonul_from_no` - copy short payload but set length to exclude trailing NUL (expect comment=`A1`, style=`plain`)
5. `grcp2_short_reset_len0_from_short` - from short donor baseline set comment length dword to zero only (expect comment=`(empty)`, style=`plain`)
6. `grcp2_style_bold_len_payload_from_plain` - from plain style donor copy bold len+payload region (expect comment=`STYLE_PROBE`, style=`bold`)
7. `grcp2_style_italic_len_payload_from_plain` - from plain style donor copy italic len+payload region (expect comment=`STYLE_PROBE`, style=`italic`)
8. `grcp2_style_underline_len_payload_from_plain` - from plain style donor copy underline len+payload region (expect comment=`STYLE_PROBE`, style=`underline`)
9. `grcp2_style_bold_payload_only_from_plain` - from plain style donor copy bold payload bytes only (no length update) (expect comment=`STYLE_PROBE`, style=`bold`)
10. `grcp2_max1400_len_payload_from_no` - copy max(1400-char) donor len+payload region from no-comment baseline (expect comment=`MAX1400_BODY`, style=`plain`)
11. `grcp2_max1400_len_only_from_no` - set max(1400-char) donor length only without payload copy (expect comment=`MAX1400_BODY`, style=`plain`)
12. `grcp2_max1400_payload_only_from_no` - copy max(1400-char) donor payload only with length left zero (expect comment=`MAX1400_BODY`, style=`plain`)

## Operator Run Path
1. `uv run clicknick-ladder-capture tui`
2. `3` (Verify run)
3. `g` (guided queue)
4. `f` (payload source override = file)
5. Scenario filter: `grid_rungcomment_patch_isolation_20260306`

For copied events:
- paste in Click
- inspect displayed comment text and style (bold/italic/underline)
- copy back in Click
- press `c`

## Verify Discipline
- Because rung rows are identical across cases, classify pass/fail by comment text/style behavior.
- Use short notes for mismatches, for example `length only shows garbage` or `style token ignored`.
- Record `clipboard_len` for each case.

Send `done` when complete.
