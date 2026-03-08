# Phase 3 Comment Phase-B Analysis (March 8, 2026)

## Scope

Push past diff accounting and explain why the clean March 8 plain-comment cases separate into:
- exact short synthesis
- exact max1400 synthesis with a no-comment handoff
- one unresolved medium branch

This report uses only the clean March 8 plain-comment natives plus the clean empty/fullwire donors.

## Highest-Signal Result

The clean plain-comment lane is now best modeled as:

1. exact plain payload bytes
2. universal phase-A continuation stream of `0xFC8` bytes at `payload_end`
3. a later phase-B continuation stream that is visible only when enough file space remains after phase A

That later phase-B stream is not random.
In the clean captures it lands on a repeating `0x40`-block cadence with three stable block types:
- `A`
- `B`
- `C`

Observed full-block sequences:
- medium:
  - `ABCABCABCABCABCABCABCABCABCABCABCABCABCABCABCABC`
  - `48` full blocks before EOF
- max1400:
  - `CABCABCABCABCABCABCABCABC`
  - `25` full blocks before EOF

Interpretation:
- both later branches use the same three block shapes
- `max1400` starts on `C` because its payload ends later, so phase B reaches the remaining file window at a different triad position
- the main unresolved problem is therefore the phase-B ordinal program, not arbitrary per-band bytes

Additional mechanical result:
- from `phase_b_start` to EOF, `grcecr_max1400_native_20260308` matches `grcecr_fullwire_native_20260308` exactly:
  - diff count: `0`
- medium does not:
  - diff count from its `phase_b_start`: `996`

Interpretation:
- the solved `fullwire` donor itself enters the same visible `A/B/C` lattice late in the file
- `max1400` reaches that late window exactly, so its post-phase-A bytes can hand off to the solved no-comment family
- medium reaches phase B earlier, before that handoff window

## Exact Synthesis Boundaries

### Short

From the empty donor:
- exact plain payload
- exact phase A

Result:
- full diff versus native: `0`

Interpretation:
- short has no meaningful later phase-B branch in the visible `0x2000` window

### Max1400

From the empty donor:
- exact plain payload
- exact phase A
- then solved no-comment `fullwire` row1/tail bands `0x1260..0x1FFF`

Result:
- full diff versus native: `0`

Interpretation:
- for clean max1400, the bytes after phase A do not need a distinct comment-owned row1/tail template
- they hand off exactly to the solved March 8 no-comment `fullwire` row1/tail family
- more specifically, the visible window starting at `phase_b_start = 0x184C` already matches the late `fullwire` lattice exactly

### Medium

From the empty donor:
- exact plain payload
- exact phase A

Remaining diffs:
- row1: `511`
- tail: `596`
- full: `1107`

If solved `fullwire` row1/tail bands are used instead:
- row1: `638`
- tail: `457`
- full: `1095`

Interpretation:
- medium does not collapse to either:
  - the empty baseline after phase A
  - or the solved `fullwire` row1/tail family
- medium therefore owns a distinct visible phase-B branch

## Why The Structure Looks This Way

The clean March 8 data now reads more naturally as a moving continuation stream than as many unrelated bands.

Phase A explains:
- metadata after the payload
- the gap band
- the whole row0 band

Phase B explains:
- why only longer comments still differ after phase A
- why the remaining bytes stay on a rigid `0x40` block lattice
- why `max1400` can rejoin the no-comment `fullwire` family while medium cannot

Practical reading:
- short runs out of visible room before a meaningful phase-B branch appears
- max1400 enters the remaining visible window late enough that its post-phase-A bytes match the `fullwire` row1/tail family exactly
- medium exposes the unresolved middle of the later continuation stream

## Current Readiness

Conservative statement:
- clean plain-comment synthesis is now exact offline for:
  - short
  - max1400
- only clean medium remains unresolved in the March 8 plain-comment lane

That is materially closer than the earlier comment-band framing suggested.

## Tooling

New helper:
- `devtools/march8_comment_phase_b_analysis.py`
- exact phase-A synthesis outputs already generated at:
  - `scratchpad/captures/phase3_comment_phase_a_20260308/`

Used commands:

```powershell
uv run python devtools/march8_comment_phase_b_analysis.py --json
uv run python -m compileall devtools/march8_comment_phase_b_analysis.py
```
