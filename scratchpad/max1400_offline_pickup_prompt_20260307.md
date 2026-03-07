# Pickup Prompt: Max1400 Offline Synthesis Follow-Up

## Read First
1. `HANDOFF.md`
2. `AGENTS.md`
3. `scratchpad/phase2_rungcomment_inference_20260306.md`
4. `scratchpad/max1400_structural_family_analysis_20260307.md`
5. `scratchpad/max1400_row32_native_results_20260307.md`
6. `scratchpad/max1400_row32_fullwire_row0nop_native_results_20260307.md`

## Current Commit Baseline
The latest committed offline state now includes:
- page-17 record decode
- paired-row descriptor-page model for pages `2..16`
- empty-row page-17 regeneration analysis
- exact offline body synthesis for pages `2..16`
- exact offline splice reconstruction for full row32 payloads

Useful helpers already added:
- `devtools/analyze_max1400_page17.py`
- `devtools/analyze_max1400_body_pages.py`
- `devtools/prototype_max1400_body_synth.py`
- `devtools/prototype_max1400_splice.py`

## Current Ground Truth

### Comment Storage Model
- `0x0294` = length dword
- `0x0298` = payload start
- payload is RTF-like ANSI
- `len = payload_bytes + 1`
- max comment length is `1400`

### Row32 Native Scaling Is Real
Committed row32 native pairs:
- empty-row lane:
  - `grc32_no_comment_native_20260307 = 69632`
  - `grc32_max1400_native_20260307 = 73728`
- full-wire row0-NOP lane:
  - `grc32fwnop_no_comment_native_20260307 = 69632`
  - `grc32fwnop_max1400_native_20260307 = 73728`

Decisive implication:
- max1400 allocates one extra `0x1000` page in native source capture
- this survives when visible rows are fully wired
- so the structure is not dependent on empty rows as hidden carriers

## Best Current Model

### 1) Hidden Paged Extent
Pages `2..16` are best treated as:
- a hidden comment-owned extent
- reusing the normal `0x40` cell stride
- with `64` cell-sized slots per `0x1000` page
- naturally resolving as two `32`-column row bands per page

This is more precise than:
- "empty pseudo rung with no wire markers"

Current wording:
- **hidden paged extent that reuses cell-shaped descriptor slots**

### 2) Body Pages `2..16` Are Solved Offline
Prototype:
- `devtools/prototype_max1400_body_synth.py`

Result:
- starting from row32 no-comment native controls
- pages `2..16` synthesize **exactly** in both tested lanes:
  - empty-row row32
  - full-wire row0-NOP row32

Implication:
- the bulk max1400 extent body is no longer the unresolved surface

### 3) Full Row32 Payload Can Be Reconstructed Exactly Offline
Prototype:
- `devtools/prototype_max1400_splice.py`

Construction:
1. start from row32 no-comment native base
2. synthesize pages `2..16`
3. copy donor pages `0`, `1`, and `17` from the native row32 max1400 payload

Result:
- exact full-payload reconstruction in both tested row32 lanes

Implication:
- for the tested row32 lanes, the payload decomposition is exact:
  - lead pages `0/1`
  - synthesized body pages `2..16`
  - terminal companion page `17`

## What Is Still Unresolved
The remaining max1400 synthesis unknowns are now tightly scoped to:
- page `0`
- page `1`
- page `17`

These are no longer mixed up with the repeated body chain.

## Page 17 Model

### Full-Wire Row0-NOP Lane
Page `17` is a rich renderer/fallback companion table:
- `4` top-level `74 76 00 08` records
- `3` Segoe leaf wrappers
- `1` CJK container wrapper
- CJK wrapper expands to `5` nested fallback-face slots:
  - `SimSun`
  - `@SimSun`
  - `NSimSun`
  - `@NSimSun`
  - `SimSun-ExtB`

Best current interpretation of the wrapper codes:
- `0x012C / 0x015E / 0x0190 / 0x0258`
- weight-like or fallback-class ladder (`300 / 350 / 400 / 600`)

### Empty-Row Lane
Native page `17` is sparse, but verify-back page `17` is regenerated:
- not sparse anymore
- but also not the rich full-wire font/fallback table
- instead it becomes a reduced terminal descriptor page on the same `64`-slot lattice
- dominated by the same compact `09/10/03` and `07/10/03` grammar seen elsewhere

Interpretation:
- page `17` is lane-sensitive and regeneration-sensitive
- it is the most unstable / least solved part of the max1400 extent model

## Recommended Next Offline Objective
Do not start by changing production codec behavior.

Primary question now:
- can pages `0`, `1`, and `17` be generated or normalized from:
  - row count
  - comment payload/length
  - lane class
  - existing no-comment base data

## Suggested Next Tasks
1. Diff and classify page `0` max1400 vs no-comment in both row32 lanes.
2. Diff and classify page `1` max1400 vs no-comment in both row32 lanes.
3. Determine whether page `0` and page `1` also decompose into:
   - donor-preserved subregions
   - plus rule-driven inserts similar to the solved body pages.
4. Decide whether page `17` can be:
   - synthesized directly
   - normalized from a smaller lane-specific template
   - or must remain donor-backed for now.

## Recommendation On Tooling
- do not update production codec behavior yet
- it is reasonable now to continue with:
  - offline prototype tooling
  - guarded experimental synthesis paths
- but not with:
  - default production max1400 emission

## Operator Guidance
Avoid new operator queues unless the offline pass on pages `0/1/17` clearly bottoms out.

If more captures are needed after that, the best next matrix is still:
- row9 no-comment / max1400
- row17 no-comment / max1400

Reason:
- determine how donor-page behavior scales before row32
- especially when the extra page first appears and how pages `0/1/17` evolve

## Non-Negotiables
- do not edit `scratchpad/ladder_capture_manifest.json` by hand
- keep production codec behavior unchanged during RE
- use `apply_patch` for file edits
- prefer deterministic repo-local helpers

## One-Line Intent
The body chain is solved; continue offline RE on donor/problem pages `0`, `1`, and `17` before attempting production max1400 synthesis.
