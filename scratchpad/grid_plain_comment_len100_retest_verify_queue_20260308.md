# grid_plain_comment_len100_retest_20260308

Date: 2026-03-08

Scenario: `grid_plain_comment_len100_retest_20260308`

Case spec: [phase3_plain_comment_len100_retest_case_specs_20260308.json](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/phase3_plain_comment_len100_retest_case_specs_20260308.json)

## Goal

Re-test the isolated length-100 neighborhood after the earlier ambiguous failure on generalized plain comments. This batch checks `99`, `100`, and `101`.

## Operator Path

Run:

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:

1. Select `3` for `Verify run`.
2. Press `g` for guided queue.
3. Choose payload override `f` for file-backed payloads.
4. Enter scenario filter: `grid_plain_comment_len100_retest_20260308`

After each `copied` event:

1. Paste into Click.
2. Inspect whether Click shows only one empty rung or also inserts an extra default rung such as `->,:,NOP`.
3. Copy back from Click.
4. Press `c`.

When the queue is complete, send `done`.

## Important Recording Rule

- If Click shows any extra default rung, record that explicitly in `observed_rows`.
- Do not leave `observed_rows` as only the expected empty rung if you actually saw an extra rung appear.
- If the extra rung appears only transiently during paste but is gone after copy-back, note that in the verify note.

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
R,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,:,NOP
```

If Click renders it differently, capture the actual visible shorthand as closely as possible.

## Cases

- `gpcl100r_len0099_20260308`: len `99`, file [gpcl100r_len0099_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_retest_20260308/gpcl100r_len0099_20260308.bin)
- `gpcl100r_len0100_20260308`: len `100`, file [gpcl100r_len0100_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_retest_20260308/gpcl100r_len0100_20260308.bin)
- `gpcl100r_len0101_20260308`: len `101`, file [gpcl100r_len0101_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_len100_retest_20260308/gpcl100r_len0101_20260308.bin)
