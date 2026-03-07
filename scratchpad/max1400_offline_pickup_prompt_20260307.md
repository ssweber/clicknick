# Pickup Prompt: Max1400 Offline Structural Analysis

## Read First
1. `HANDOFF.md`
2. `AGENTS.md`
3. `scratchpad/phase2_rungcomment_inference_20260306.md`
4. `scratchpad/phase2_rungcomment_max1400_structure_scope_20260307.json`
5. `scratchpad/phase2_rungcomment_max1400_obs63_narrow_20260307.json`
6. `scratchpad/phase2_rungcomment_max1400_struct_blocks_20260307.json`

## Current Ground Truth
- Comment storage model is still:
  - `0x0294` = length dword
  - `0x0298` = payload start
  - `len = payload_bytes + 1`
  - payload is RTF-like ANSI
  - max comment length is `1400`
- Fresh no-wire native anchors for this lane:
  - `scratchpad/captures/grc_no_comment_fresh_native_20260307.bin`
  - `scratchpad/captures/grc_max1400_fresh_native_20260307.bin`
- Full comment-window-only replay (`0x0294..0x08FC`) is insufficient:
  - can produce `hidden comment`
  - can also force a visible wire rung even though the native lane is `R,...,:,NOP`
- Copying `0x0294..0x1A5F` from the fresh max1400 native onto the fresh no-comment base is sufficient:
  - no rung wire
  - correct max comment behavior
  - verify-back exact match to the fresh native max1400 control
- Copying earlier than `0x0294` was not required for observed parity.

## Important Negative Results
- The `63` observed verify-back offsets from the failing `commentwin` case are **not** a safe source-level fix.
  - forcing them directly caused crashes.
- Coarse structural block splits also crashed:
  - `120` non-grid bytes alone
  - row0 structural block alone
  - row1 structural block alone
  - row0+row1 structural block without the accompanying non-grid bytes

## What Is Actually Unresolved
The unresolved source region is still:
- `0x08FD..0x1A5F`

But current evidence says this region is not a bag of independent patch bytes.
It behaves like a coherent structural family spanning:
- pre-grid bytes near `0x0904..0x0A5C`
- row0 cell metadata
- row1 cell metadata

## Offline Analysis Objective
Do not start with more operator queues.
First do an offline-only pass that tries to explain the structural family inside `0x08FD..0x1A5F`.

Primary question:
- Is Click treating the max1400 comment as:
  - row0/row1 metadata entanglement only
  - or some kind of pseudo-row / extra-extent structure

## High-Signal Offline Facts

### 1) Failing vs Passing Source Delta
`grcmfs_commentwin_full_0294_08fc_from_freshnowire.bin`
vs
`grcmfs_commentgrid_0294_1a5f_from_freshnowire.bin`

Source delta count:
- `1194` bytes total

Partition:
- `120` non-grid bytes near `0x0904..0x0A5C`
- `685` row0 bytes
- `389` row1 bytes

### 2) Repeating Cell Shapes
The row-structured portion is not random.
Observed repeating source-diff families:
- row0 cols `1..22`: shared shape
- row0 col `0`: same family plus extra `+0x15`
- row0 col `23`: boundary variant
- row0 cols `24..30`: tail variant
- row0 col `31`: terminal variant with `+0x19/+0x1D/+0x38/+0x3D`
- row1 cols `0..22`: shared shape
- row1 col `23`: boundary variant
- row1 cols `24/27/30`: one repeating tail shape
- row1 cols `25/28/31`: second repeating tail shape
- row1 cols `26/29`: third repeating tail shape

### 3) The 120 Non-Grid Bytes Also Repeat
Those bytes appear in `6` buckets, spaced by `0x40`, starting around:
- `0x0904`
- `0x0944`
- `0x0984`
- `0x09C4`
- `0x0A04`
- `0x0A44`

That pattern strongly suggests a descriptor table / per-column-family structure, not random noise.

## Suggested Offline Tasks
1. Build a compact table of the repeated row0/row1 shape families and their exact rel-offset/value transitions.
2. Determine whether the `120` non-grid bytes align semantically with:
   - row0 cols `24..31`
   - row1 cols `24..31`
   - or some separate extent table.
3. Compare these max1400-specific structures against:
   - fresh no-comment native
   - fresh max1400 native
   - passing `commentgrid` synthetic
4. Check whether the row-diff families look like:
   - terminal-row linkage rules
   - per-cell extent/ownership flags
   - or a compacted descriptor for hidden rows / pseudo-rows.

## Recommended Future Native Experiment
After the offline pass, strongly consider a new native matrix:
- row32 no-comment control
- row32 max1400 comment control

Use the same body file:
- `scratchpad/max1400_comment_body_20260307.txt`

Why:
- If max1400 is only entangled with the first visible rows, row32 may preserve the same low-row signature.
- If Click is treating the max comment as a pseudo-row / extra structural extent, row32 should expose how that scaling behaves.

## Non-Negotiables
- Do not edit `scratchpad/ladder_capture_manifest.json` by hand
- Keep using `uv run clicknick-ladder-capture ...` workflow commands
- Keep production codec behavior unchanged during RE
- Prefer offline analysis before adding more operator queues

## One-Line Intent
Explain the structural family in `0x08FD..0x1A5F` before asking for more manual max1400 pasteback runs.
