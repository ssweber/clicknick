# Phase 3 Plain Comment Exact Synthesis (March 8, 2026)

## Scope

Establish the strongest conservative offline statement now supported for the clean March 8 plain-comment lane.

This report remains limited to:
- `grcecr_short_native_20260308`
- `grcecr_medium_native_20260308`
- `grcecr_max1400_native_20260308`

Styled comments remain out of scope.
Production codec behavior remains unchanged.

## Exact Offline Result

All three clean March 8 plain-comment natives are now reconstructed byte-exactly offline.

Helper:
- `devtools/march8_plain_comment_synth.py`

Generated outputs:
- `scratchpad/captures/phase3_plain_comment_exact_20260308/short_plain_comment_exact.bin`
- `scratchpad/captures/phase3_plain_comment_exact_20260308/medium_plain_comment_exact.bin`
- `scratchpad/captures/phase3_plain_comment_exact_20260308/max1400_plain_comment_exact.bin`

Diff result versus the March 8 natives:
- short:
  - `0`
- medium:
  - `0`
- max1400:
  - `0`

## Accepted March 8-Scoped Model

### Shared Plain Payload Rule

Exact for all three clean cases:
- length dword at `0x0294`
- payload bytes at `0x0298`
- fixed `105`-byte RTF prefix
- `cp1252` plain-text body
- fixed `11`-byte suffix

### Shared Phase-A Rule

Exact for all three clean cases:
- universal payload-end-anchored phase-A continuation stream
- length:
  - `0xFC8`

This phase-A stream covers:
- post-payload region through `0x0A5F`
- entire row0 band `0x0A60..0x125F`

### Case-Specific Later Rule

#### Short

No visible phase-B rule is needed in the `0x2000` window.

Exact reconstruction:
- empty donor
- exact plain payload
- exact phase A

#### Medium

The remaining later branch is now exact offline as a repeating phase-B program:
- `27` full blocks
- block stride:
  - `0x40`
- visible tail:
  - truncated next block of `44` bytes
- equivalent shape:
  - `9` `ABC` triads repeated three times across the visible full-block window

This repeating program accounts exactly for the bytes that remained after phase A:
- row1:
  - `511`
- tail:
  - `596`
- total remaining after phase A:
  - `1107`

Conservative wording:
- this is an explicit March 8 medium phase-B program
- it is not yet a generalized semantic explanation for all comment lengths

#### Max1400

The remaining later branch hands off exactly to the solved March 8 no-comment `fullwire` family:
- row1 band `0x1260..0x1A5F`
- tail band `0x1A60..0x1FFF`

Equivalent statement:
- from `phase_b_start = 0x184C` to EOF, `max1400` matches clean `fullwire` exactly

## What This Means

The clean March 8 plain-comment lane is materially closer than before:
- exact offline synthesis now exists for all three clean plain-comment natives

But the model is still not fully generalized:
- short:
  - solved by payload + phase A
- medium:
  - solved by an explicit repeating phase-B program
- max1400:
  - solved by payload + phase A + late handoff into solved `fullwire`

So the remaining gap is no longer:
- "can we synthesize plain comments at all"

The remaining gap is:
- "can we replace the March 8 case-specific later rules with a broader semantic generator"

## Used Commands

```powershell
uv run python devtools/march8_plain_comment_synth.py --json
uv run python devtools/march8_plain_comment_synth.py --output-dir scratchpad/captures/phase3_plain_comment_exact_20260308 --json
uv run python -m compileall devtools/march8_plain_comment_synth.py
```
