# grid_plain_comment_alignment_repaired_20260308

Date: 2026-03-08

Scenario: `grid_plain_comment_alignment_repaired_20260308`

Case spec: [phase3_plain_comment_alignment_repaired_case_specs_20260308.json](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/phase3_plain_comment_alignment_repaired_case_specs_20260308.json)

## Goal

Verify the runtime repair candidate for the previously failing plain-comment medium alignment class. This batch checks lengths `36`, `100`, `164`, and `228` after the new grid-repair path.

## Operator Path

Run:

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:

1. Select `3` for `Verify run`.
2. Press `g` for guided queue.
3. Choose payload override `f` for file-backed payloads.
4. Enter scenario filter: `grid_plain_comment_alignment_repaired_20260308`

After each `copied` event:

1. Paste into Click.
2. Inspect whether Click shows exactly one empty rung with the expected comment.
3. Copy back from Click.
4. Press `c`.

When the queue is complete, send `done`.

## Important Recording Rule

- If Click still inserts a default rung, record that explicitly in `observed_rows`.
- If the comment survives but topology is wrong, mark `verified_fail`.
- If the repair changes the comment text or truncates it, record the actual visible comment text.

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

## Cases

- `gpcar_len0036_20260308`: len `36`, file [gpcar_len0036_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_alignment_repaired_20260308/gpcar_len0036_20260308.bin)
- `gpcar_len0100_20260308`: len `100`, file [gpcar_len0100_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_alignment_repaired_20260308/gpcar_len0100_20260308.bin)
- `gpcar_len0164_20260308`: len `164`, file [gpcar_len0164_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_alignment_repaired_20260308/gpcar_len0164_20260308.bin)
- `gpcar_len0228_20260308`: len `228`, file [gpcar_len0228_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_alignment_repaired_20260308/gpcar_len0228_20260308.bin)
