# Max1400 Payload-Only Template Verify Queue (March 8, 2026)

## Scenario

- Scenario: `grid_max1400_payload_only_template_20260308`
- Case count: `2`
- Purpose: test the narrow hypothesis that a clean March 8 `max1400` donor can paste a shorter plain comment if only the comment payload section is changed and all other sections are kept from the `max1400` donor

## Hypothesis

Starting donor:
- `grcecr_max1400_native_20260308`

Mutation rule:
- copy only `0x0294..(0x0298 + payload_len - 1)` from the shorter native donor
- keep all other sections from the `max1400` donor unchanged

Exact payload files:
- `scratchpad/captures/phase3_max1400_payload_only_template_20260308/grcmpt_short_len_payload_from_max_20260308.bin`
- `scratchpad/captures/phase3_max1400_payload_only_template_20260308/grcmpt_medium_len_payload_from_max_20260308.bin`

Expected visible topology if the hypothesis works:
- empty 1-row rung
- no visible wires
- no AF instruction

## Cases

1. `grcmpt_short_len_payload_from_max_20260308`
   - donor/base: `grcecr_max1400_native_20260308`
   - shorter source payload: `grcecr_short_native_20260308`
   - copied range: `0x0294..0x0310`
   - kept from max1400 donor:
     - `0x0000..0x0293`
     - `0x0311..0x1FFF`
   - offline mismatch versus clean short native:
     - full: `3115`
     - row0 band: `635`
     - row1 band: `436`
     - tail band: `491`
   - intent:
     - fastest pure payload-only probe

2. `grcmpt_medium_len_payload_from_max_20260308`
   - donor/base: `grcecr_max1400_native_20260308`
   - shorter source payload: `grcecr_medium_native_20260308`
   - copied range: `0x0294..0x040B`
   - kept from max1400 donor:
     - `0x0000..0x0293`
     - `0x040C..0x1FFF`
   - offline mismatch versus clean medium native:
     - full: `2956`
     - row0 band: `588`
     - row1 band: `638`
     - tail band: `457`
   - intent:
     - check whether a mid-length comment can still ride on the max1400 template

## Operator Run Path

1. Start TUI:

```powershell
uv run clicknick-ladder-capture tui
```

2. Choose `3` for verify run.
3. Choose `g` for guided queue.
4. Choose `f` for file-backed payloads.
5. Enter scenario filter:

```text
grid_max1400_payload_only_template_20260308
```

6. For each copied event:
   - paste in Click
   - inspect immediate visible rung shape
   - if possible inspect whether the comment exists or stays hidden
   - copy back in Click
   - press `c`

7. Send `done`.

## Classification Rules

- `verified_pass`
  - visible topology stays as an empty 1-row rung
  - no visible wire regression
  - no crash
- `verified_fail`
  - payload pastes but visible topology is wrong
  - or comment behavior is clearly non-native in a way that makes the payload unusable
- `blocked`
  - crash, cancel, or cannot complete trustworthy copy-back

## Notes To Record

- whether the pasted rung stays visibly empty
- whether the comment appears immediately, stays hidden, or is absent
- whether copy-back completes
- any wrong-topology shorthand if visible wires appear
