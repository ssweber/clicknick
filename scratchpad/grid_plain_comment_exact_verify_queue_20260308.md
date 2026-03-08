# Grid Plain Comment Exact Verify Queue (March 8, 2026)

## Scenario

- `grid_plain_comment_exact_20260308`

## Goal

Live-verify the exact offline March 8 plain-comment synth outputs.

All three payload files are byte-exact versus the clean March 8 natives offline.
This round checks whether those exact synthetic payloads paste safely in Click.

## Cases

### `gpcx_short_exact_20260308`

- payload file:
  - `scratchpad/captures/phase3_plain_comment_exact_20260308/short_plain_comment_exact.bin`
- model:
  - empty donor + exact plain payload + phase A
- expected visible result:
  - empty 1-row rung
  - short comment `Hello`

### `gpcx_medium_exact_20260308`

- payload file:
  - `scratchpad/captures/phase3_plain_comment_exact_20260308/medium_plain_comment_exact.bin`
- model:
  - empty donor + exact plain payload + phase A + medium phase-B ring program
- expected visible result:
  - empty 1-row rung
  - deterministic 256-char comment

### `gpcx_max1400_exact_20260308`

- payload file:
  - `scratchpad/captures/phase3_plain_comment_exact_20260308/max1400_plain_comment_exact.bin`
- model:
  - empty donor + exact plain payload + phase A + fullwire row1/tail handoff
- expected visible result:
  - empty 1-row rung
  - long plain comment should remain structurally safe

## Operator Path

```powershell
uv run clicknick-ladder-capture tui
```

Then:
- `3`
- `g`
- `f`
- scenario filter:

```text
grid_plain_comment_exact_20260308
```

## Operator Notes

- Treat this as a pure paste-safety round first.
- For all three cases:
  - the visible rung should stay an empty 1-row rung
  - if the paste crashes or mutates topology, record it directly
- For `short` and `medium`:
  - the manifest already carries the expected comment row
- For `max1400`:
  - the manifest expected rows only track the empty rung shape
  - if practical, also inspect `Edit Comment` before copy-back to confirm a long comment is present
  - do not block the queue on hand-transcribing the whole 1400-char body

## Stop Conditions

- none; run all three cases

## Sendback

After the guided queue finishes, send:

```text
done
```
