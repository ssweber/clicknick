# grid_plain_comment_len100_alignment_retest_20260308

Date: 2026-03-08

Scenario: `grid_plain_comment_len100_alignment_retest_20260308`

Case spec: [phase3_plain_comment_len100_alignment_retest_case_specs_20260308.json](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/phase3_plain_comment_len100_alignment_retest_case_specs_20260308.json)

## Goal

Test whether the length-100 failure repeats on the same medium-tail alignment class. This batch checks lengths `36`, `100`, `164`, and `228`.

## Operator Path

Run:

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:

1. Select `3` for `Verify run`.
2. Press `g` for guided queue.
3. Choose payload override `f` for file-backed payloads.
4. Enter scenario filter: `grid_plain_comment_len100_alignment_retest_20260308`

After each `copied` event:

1. Paste into Click.
2. Inspect whether Click shows only one empty rung or inserts an extra default rung.
3. Copy back from Click.
4. Press `c`.

When the queue is complete, send `done`.

## Important Recording Rule

- If Click shows any extra default rung, record it explicitly in `observed_rows`.
- Do not leave `observed_rows` as only the comment + empty rung if the actual visible result included an inserted rung.
- If the comment survives but topology is wrong, that still counts as `verified_fail`.

## Expected Visible Result

- One plain comment line matching the label text.
- One empty 1-row rung.
- No visible wire.
- No AF instruction.

Expected rung row if clean:

```text
R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,...
```

Unexpected rung to watch for:

```text
R,,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,:,NOP
```

If Click renders a different default rung shape, capture the actual visible shorthand as closely as possible.

## Cases

- `gpcl100a_len0036_20260308`: len `36`, file [gpcl100a_len0036_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_alignment_retest_20260308/gpcl100a_len0036_20260308.bin)
- `gpcl100a_len0100_20260308`: len `100`, file [gpcl100a_len0100_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_alignment_retest_20260308/gpcl100a_len0100_20260308.bin)
- `gpcl100a_len0164_20260308`: len `164`, file [gpcl100a_len0164_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_alignment_retest_20260308/gpcl100a_len0164_20260308.bin)
- `gpcl100a_len0228_20260308`: len `228`, file [gpcl100a_len0228_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_alignment_retest_20260308/gpcl100a_len0228_20260308.bin)
