# grid_plain_comment_generalized_20260308

Date: 2026-03-08

Scenario: `grid_plain_comment_generalized_20260308`

Case spec: [phase3_plain_comment_generalized_case_specs_20260308.json](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/phase3_plain_comment_generalized_case_specs_20260308.json)

## Goal

Verify that the generalized plain-comment encoder accepts arbitrary plain comment lengths `<= 1400` on the proven empty 1-row rung shape, with stable paste behavior and correct comment persistence.

## Operator Path

Run:

```powershell
uv run clicknick-ladder-capture tui
```

In TUI:

1. Select `3` for `Verify run`.
2. Press `g` for guided queue.
3. Choose payload override `f` for file-backed payloads.
4. Enter scenario filter: `grid_plain_comment_generalized_20260308`

After each `copied` event:

1. Paste into Click.
2. Copy back from Click.
3. Press `c`.

When the queue is complete, send `done`.

## Expected Visible Result

- Each case should paste as a single empty 1-row rung with no visible wire and no AF instruction.
- Each case should carry a single plain comment line matching the registered comment text for that label.
- If Click visibly renders any wire on the rung, mark the case `verified_fail`.
- If Click crashes or rejects paste, mark the case `blocked` or `verified_fail` as appropriate and add a short note.

Expected rung row if no override is needed:

```text
R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,...
```

## Pass / Fail

- `verified_pass`: paste succeeds, copy-back succeeds, visible rung remains empty, and the comment text matches the label's expected comment.
- `verified_fail`: paste succeeds but the rung topology or comment text is wrong.
- `blocked`: Click crashes, refuses paste, or cannot be evaluated cleanly.

## Cases

- `gpcg_len0001_20260308`: len `1`, file [gpcg_len0001_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0001_20260308.bin)
- `gpcg_len0002_20260308`: len `2`, file [gpcg_len0002_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0002_20260308.bin)
- `gpcg_len0004_20260308`: len `4`, file [gpcg_len0004_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0004_20260308.bin)
- `gpcg_len0006_20260308`: len `6`, file [gpcg_len0006_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0006_20260308.bin)
- `gpcg_len0010_20260308`: len `10`, file [gpcg_len0010_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0010_20260308.bin)
- `gpcg_len0032_20260308`: len `32`, file [gpcg_len0032_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0032_20260308.bin)
- `gpcg_len0100_20260308`: len `100`, file [gpcg_len0100_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0100_20260308.bin)
- `gpcg_len0255_20260308`: len `255`, file [gpcg_len0255_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0255_20260308.bin)
- `gpcg_len0257_20260308`: len `257`, file [gpcg_len0257_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0257_20260308.bin)
- `gpcg_len0512_20260308`: len `512`, file [gpcg_len0512_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len0512_20260308.bin)
- `gpcg_len1024_20260308`: len `1024`, file [gpcg_len1024_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len1024_20260308.bin)
- `gpcg_len1399_20260308`: len `1399`, file [gpcg_len1399_20260308.bin](/c:/Users/ssweb/Documents/GitHub/clicknick/scratchpad/captures/phase3_plain_comment_generalized_20260308/gpcg_len1399_20260308.bin)
