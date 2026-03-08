# Click PLC Clipboard Reverse Engineering - Handoff v24

Last validated: March 8, 2026

## Execution Update (March 8, 2026 - Exact Plain Comment Synth Verified In Click)

- New verify result report:
  - `scratchpad/phase3_plain_comment_exact_verify_results_20260308.md`
- Verify scenario:
  - `grid_plain_comment_exact_20260308`

Verify outcomes:
- `gpcx_short_exact_20260308`
  - `verified_pass`
- `gpcx_medium_exact_20260308`
  - `verified_pass`
- `gpcx_max1400_exact_20260308`
  - `verified_pass`

Accepted result:
- the exact March 8 plain-comment synth model is now:
  - exact offline
  - and live verify-backed in Click

Conservative boundary:
- this proof is still March 8 clean-family scoped
- styled comments remain out of scope
- broader generalized comment synthesis remains a separate step

## Execution Update (March 8, 2026 - Plain Comment Exact Offline Synthesis Reached)

- New offline report:
  - `scratchpad/phase3_plain_comment_exact_synth_20260308.md`
- New offline helper:
  - `devtools/march8_plain_comment_synth.py`
- Generated offline outputs:
  - `scratchpad/captures/phase3_plain_comment_exact_20260308/`

Highest-signal accepted result:
- all three clean March 8 plain-comment natives are now reconstructed byte-exactly offline

Accepted March 8-scoped synthesis model:
- shared rule for all three clean cases:
  - exact plain payload bytes
  - universal phase-A continuation stream at `payload_end`
- short:
  - exact from empty donor + plain payload + phase A
- medium:
  - exact from empty donor + plain payload + phase A + explicit repeating phase-B program
  - phase-B program shape:
    - `27` full `0x40` blocks
    - equivalent to `9` repeating `ABC` triads
    - generated from four `9`-step ordinal rings with a fixed `+5` triad-step relation
    - plus a truncated next block of `44` bytes at EOF
- max1400:
  - exact from empty donor + plain payload + phase A + solved no-comment `fullwire` row1/tail bands

What this does and does not mean:
- it does mean the clean March 8 plain-comment lane is now exact offline
- it does not yet mean comment synthesis is generalized
- medium phase B is still an explicit March 8 program, not yet a broader semantic generator
- styled comments remain out of scope
- production codec behavior remains unchanged

## Execution Update (March 8, 2026 - Plain Comment Model Tightened)

- New offline reports:
  - `scratchpad/phase3_comment_stream_model_20260308.md`
  - `scratchpad/phase3_comment_phase_b_analysis_20260308.md`
- New offline helpers:
  - `devtools/march8_comment_stream_analysis.py`
  - `devtools/march8_comment_phase_b_analysis.py`

Highest-signal accepted model:
- the clean March 8 plain-comment lane is now best described as:
  - exact plain payload bytes
  - universal phase-A continuation stream at `payload_end`
  - later phase-B continuation stream only when enough visible file space remains after phase A

What is now explicitly proven:
- after the true payload end, short / medium / max1400 share an identical phase-A continuation stream of:
  - `0xFC8` bytes
- that universal phase A covers, for all three clean plain-comment captures:
  - the post-payload region through `0x0A5F`
  - the entire row0 band `0x0A60..0x125F`
- exact offline synthesis boundaries are now:
  - short:
    - exact from empty donor + plain payload + phase A
  - max1400:
    - exact from empty donor + plain payload + phase A + solved no-comment `fullwire` row1/tail bands
  - medium:
    - exact offline once the explicit March 8 phase-B program is applied
    - still not reduced to a broader semantic generator

Why this matters:
- it replaces the older "many comment bands" wording with one moving continuation-stream model
- it explains why payload-only from a `max1400` donor crashed:
  - shortening the payload without moving the continuation stream leaves that stream anchored at the wrong absolute offsets
- it narrows the remaining problem from exact offline synthesis to later-stream generalization

Accepted phase-B structure:
- phase B is not random row1/tail residue
- in the clean captures it follows a repeating `0x40`-block triad:
  - `A`
  - `B`
  - `C`
- observed full-block sequences:
  - medium:
    - `ABCABCABCABCABCABCABCABCABCABCABCABCABCABCABCABC`
  - max1400:
    - `CABCABCABCABCABCABCABCABC`
- from `max1400` phase-B start `0x184C` to EOF:
  - diff versus clean `fullwire`: `0`
- from `medium` phase-B start `0x13D4` to EOF:
  - diff versus clean `fullwire`: `996`

Current unresolved boundary:
- medium still owns a distinct visible phase-B branch across row1 and tail
- that branch is now exact offline as an explicit March 8 program
- short does not expose a meaningful visible phase-B branch in the `0x2000` window
- max1400 hands off exactly to the solved March 8 no-comment `fullwire` row1/tail family after phase A

## Execution Update (March 8, 2026 - Payload-End Continuation Stream Model Identified)

- New offline report:
  - `scratchpad/phase3_comment_stream_model_20260308.md`
- New offline helper:
  - `devtools/march8_comment_stream_analysis.py`

Highest-signal new finding:
- the clean March 8 plain-comment structure is better modeled as:
  - exact plain payload bytes
  - followed by a payload-end-anchored continuation stream

What is now explicitly proven:
- after the true payload end, short / medium / max1400 share an identical continuation stream prefix of:
  - `0xFC8` bytes
- that universal prefix lands, for all three clean plain-comment captures, across:
  - the post-payload region through `0x0A5F`
  - the entire row0 band `0x0A60..0x125F`

Why this matters:
- it explains why payload-only from a `max1400` donor crashed:
  - shortening the payload without moving the continuation stream leaves that stream anchored at the wrong absolute offsets
- it replaces the older "many comment bands" wording:
  - the earlier metadata / gap / row0 surfaces are different absolute slices of one stream whose start moves with `payload_end`

Updated comment-lane working model:
- step 1:
  - write exact plain payload bytes
- step 2:
  - generate the universal phase-A continuation stream at `payload_end`
- step 3:
  - handle the later length-class branch that begins after aligned offset `0xFC8`

Current unresolved boundary:
- after aligned offset `0xFC8`, the stream branches by length class
- short:
  - later phase effectively absent / zero-filled
- medium and max1400:
  - later phase present
  - see the newer phase-B update above for the tighter model

## Execution Update (March 8, 2026 - Max1400 Payload-Only Template Hypothesis Rejected)

- New offline report:
  - `scratchpad/phase3_max1400_payload_only_probe_results_20260308.md`
- Offline helper:
  - `devtools/march8_max1400_template_probe.py`
- Verify scenario:
  - `grid_max1400_payload_only_template_20260308`

Tested hypothesis:
- start from clean `grcecr_max1400_native_20260308`
- replace only the shorter plain-comment `len + payload` bytes
- keep all other sections from the clean `max1400` donor unchanged

Observed verify outcomes:
- short payload-only probe:
  - `blocked`
  - event: `crash`
  - note: `Out of Memory`
- medium payload-only probe:
  - `blocked`
  - event: `crash`

Accepted conclusion:
- payload-only reuse of the clean March 8 `max1400` donor is not replay-safe for the clean short or medium plain-comment lanes

Offline implication:
- the failure is consistent with leaving the continuation stream anchored at the old `max1400` payload end
- payload-only is therefore too narrow for the clean March 8 plain-comment lane

High-signal next probe if more online work is attempted:
- copy target bytes through the gap band:
  - `0x0294..0x0A5F`
- this is now the narrowest defensible next candidate after the payload-only crash

## Execution Update (March 8, 2026 - Plain Comment Readiness Assessed)

- New offline report:
  - `scratchpad/phase3_comment_synthesis_readiness_20260308.md`
- New offline helper:
  - `devtools/march8_comment_synthesis_readiness.py`

Scope of this assessment:
- use the March 8 clean empty-rung native set only
- assess plain-comment synthesis readiness conservatively
- keep styled-comment synthesis out of scope
- keep production codec behavior unchanged

What is now explicitly proven:
- the clean March 8 plain-comment payload window is exact for:
  - short
  - medium
  - max1400
- exact March 8 plain payload envelope:
  - length dword at `0x0294`
  - bytes at `0x0298`
  - fixed `105`-byte RTF prefix
  - plain text body in `cp1252`
  - fixed `11`-byte suffix
- the prefix band `0x0000..0x0253` remains unchanged for all three clean plain-comment captures
- metadata before the payload length dword `0x0254..0x0293` remains unchanged for all three clean plain-comment captures

New high-signal readiness result:
- `grcecr_max1400_native_20260308` reuses solved no-comment bands exactly at:
  - fullwire 1-row row1 band `0x1260..0x1A5F`
  - shared tail band `0x1A60..0x1FFF`
- this exact fullwire-band reuse is **not** true for the clean short or medium comment captures

Conservative interpretation:
- plain payload serialization is now much closer than the later-stream branch problem
- the later-stream framing is better than the older companion-band framing
- all three clean March 8 plain-comment cases are now exact offline under the newer stream model documented above
- the remaining gap is later-stream generalization, especially the medium phase-B program
- comment synthesis is still not ready for production

## Execution Update (March 8, 2026 - Phase 3 Wireframe Band Isolation Continued)

- New offline reports:
  - `scratchpad/phase3_wireframe_baseline_start_20260308.md`
  - `scratchpad/phase3_wireframe_band_isolation_20260308.md`
- Offline helpers:
  - `devtools/march8_wireframe_synth.py`
  - `devtools/march8_wireframe_band_audit.py`
- Explicit March 8 no-comment band template spec:
  - `scratchpad/phase3_wireframe_band_templates_20260308.json`
- Generated offline outputs:
  - `scratchpad/captures/phase3_wireframe_20260308/`
  - `scratchpad/captures/phase3_wireframe_20260308_bands/`

Scope of the accepted wireframe model:
- stay on the March 8 clean donor set
- keep comment synthesis explicitly out of scope
- keep production codec behavior unchanged

What the helper now reconstructs byte-exactly:
- `grcecr_empty_native_20260308`
- `grcecr_fullwire_native_20260308`
- `grcecr_fullwire_nop_native_20260308`
- `grcecr_rows2_empty_native_20260308`
- `grcecr_rows2_vert_horiz_native_20260308`

Accepted March 8 no-comment band model:
- base donor:
  - `grcecr_empty_native_20260308`
- explicit prefix band:
  - `0x0000..0x0253`
- metadata band:
  - `0x0254..0x0A53`
- gap band:
  - `0x0A54..0x0A5F`
- explicit row0 band logic:
  - `0x0A60..0x125F`
- explicit row1 band templates:
  - `0x1260..0x1A5F`
- explicit shared tail band template:
  - `0x1A60..0x1FFF`

Bytes now explicitly covered by the March 8 no-comment wireframe model:
- previously accepted explicit bytes:
  - empty 1-row -> fullwire 1-row row0 band:
    - all `62` visible wire deltas
  - fullwire 1-row -> fullwire+NOP 1-row row0 band:
    - `2` AF-cell deltas
  - empty 1-row -> empty 2-row:
    - metadata `0x0254: 0x40 -> 0x60`
    - row0 col31 `+0x38: 0x00 -> 0x01`
    - row0 col31 `+0x3D: 0x00 -> 0x02`
  - empty 2-row -> 2-row vertical+horizontal:
    - all `5` visible wire deltas
- newly explicit March 8 band-template coverage:
  - fullwire 1-row row1 band:
    - `421` changed bytes vs empty 1-row
  - shared tail band `0x1A60..0x1FFF`:
    - `491` changed bytes vs empty 1-row
    - same explicit band template in the fullwire and 2-row families
  - 2-row prefix band:
    - `237` changed bytes vs empty 1-row
  - 2-row empty row1 band:
    - `570` changed bytes vs empty 1-row

Conservative interpretation:
- the March 8 clean no-comment wireframe targets are now reconstructed from one empty 1-row donor baseline plus explicit March 8 band templates and explicit row0/metadata logic
- those explicit band templates are March 8-scoped no-comment findings, not yet a general semantic model
- this remains a wireframe-only milestone and does not claim comment support or comment companion-byte synthesis

## Execution Update (March 8, 2026 - Clean Empty-Rung Re-Verification Completed)

- New result report:
  - `scratchpad/rungcomment_clean_empty_reverify_results_20260308.md`
- Scenario completed:
  - `grid_rungcomment_clean_empty_reverify_20260308`
- Manifest verify statuses:
  - `8/8` `verified_pass`

Fresh canonical capture set:
- `grcecr_empty_native_20260308`
- `grcecr_short_native_20260308`
- `grcecr_medium_native_20260308`
- `grcecr_max1400_native_20260308`
- `grcecr_fullwire_native_20260308`
- `grcecr_fullwire_nop_native_20260308`
- `grcecr_rows2_empty_native_20260308`
- `grcecr_rows2_vert_horiz_native_20260308`

Key outcome:
- native plain comments on a truly empty 1-row rung are now re-verified as working at:
  - short length
  - medium length (`256`)
  - max tested length (`1400`)
- all three comment-bearing cases pasted and copied back with the visible rung still empty

Critical correction to prior interpretation:
- the old fallback explanation "comment exists but only appears after reopen" should not be used as the default interpretation for comment-lane anomalies
- the clean empty-rung native round shows that plain comments can work without introducing malformed visible topology
- earlier failures were at least partly caused by structurally bad bytes in contaminated lanes, not by a generic comment-only UI refresh rule

Conservative byte-level interpretation from the clean round:
- comments are **not** metadata-only
- versus the empty control, comment-bearing natives changed bytes in:
  - metadata band `0x0254..0x0A5F`
  - row0 band `0x0A60..0x125F`
  - row1 band `0x1260..0x1A5F`
- but row0/row1 band wire flags at `+0x19/+0x1D/+0x21` stayed unchanged
- therefore:
  - comment support is topology-neutral in visible wire terms on the clean empty baseline
  - but still structurally coupled to non-wire companion bytes in the row0/row1 bands

12-byte gap result:
- `0x0A54..0x0A5F` varies by comment length and round-trips exactly
- treat it as structural trailer/separator state, not padding

Native versus verify-back result on the clean empty-baseline set:
- metadata: exact
- `0x0A54..0x0A5F`: exact
- row0 band: exact
- row1 band: regeneration-sensitive

Tooling audit result:
- `scratchpad/rungcomment_tooling_audit_20260308.md`
- current code paths correctly keep GUI row `0` at `0x0A60`
- no live indexing bug was found that counts `0x0254..0x0A5F` as GUI row `0`

Accepted classification after the reset:
- native plain comments on empty rungs:
  - **proven working**
- deterministic synthesis model for comment-bearing payloads:
  - **still unresolved**
- Phase 2 synthesis gate:
  - **still not met**

Recommended next step:
- use the March 8 canonical captures as the clean donor set for Phase 3 wireframe synthesis
- keep comment synthesis outside the production path until the later continuation-stream branch is modeled explicitly

## Execution Update (March 8, 2026 - Comment Lane Reset / Clean-Slate Queue Prepared)

This update supersedes the earlier March 7 comment-support wording below until the clean re-verification round is completed.

Status:
- no new native comment captures were accepted on March 8 yet
- Phase 2 comment support is reopened and remains **not met**

Why the reset happened:
- earlier comment conclusions were confounded by testing on non-empty or structurally non-neutral rungs
- the old explanation "`comment exists but only appears after reopen`" is no longer accepted as a safe comment-specific UI quirk
- if a pasted comment lane produces the wrong visible rung shape, that result should now be classified as **structural failure**

Tooling audit result:
- new audit note:
  - `scratchpad/rungcomment_tooling_audit_20260308.md`
- confirmed current code/tools use:
  - metadata region: `0x0254..0x0A5F`
  - GUI row `0`: `0x0A60`
- no current code path was found that counts the metadata region as GUI row `0`
- `devtools/capture.py` is not present in the repo and remains retired by policy
- current best interpretation:
  - historical confusion was primarily naming/documentation ambiguity plus contaminated baselines
  - not a proven live indexing bug in the current audited tooling

Prepared clean-slate re-verification round:
- scenario:
  - `grid_rungcomment_clean_empty_reverify_20260308`
- artifacts:
  - `scratchpad/phase2_rungcomment_clean_empty_reverify_case_specs_20260308.json`
  - `scratchpad/grid_rungcomment_clean_empty_reverify_verify_queue_20260308.md`
  - `scratchpad/rungcomment_short_body_20260308.txt`
  - `scratchpad/rungcomment_medium_body_20260308.txt`
  - `scratchpad/max1400_comment_body_20260307.txt`

Prepared native cases:
- `grcecr_empty_native_20260308`
- `grcecr_short_native_20260308`
- `grcecr_medium_native_20260308`
- `grcecr_max1400_native_20260308`
- `grcecr_fullwire_native_20260308`
- `grcecr_fullwire_nop_native_20260308`
- `grcecr_rows2_empty_native_20260308`
- `grcecr_rows2_vert_horiz_native_20260308`

Ground-truth rule until that round is complete:
- treat comment support of any length as **unsettled**
- do not rely on the earlier:
  - "short comments are working"
  - "plain max1400 is partially working"
  - "requires reopen to display" as a sufficient explanation

Next required step:
- run the prepared clean empty-rung native capture + verify queue
- only after those results land should `HANDOFF.md` be rewritten as the next clean canonical version

## Execution Update (March 7, 2026 - Full-Wire Row0-NOP Discriminator Weakens Empty-Carrier Model)

- New result report:
  - `scratchpad/max1400_row32_fullwire_row0nop_native_results_20260307.md`
- Scenario completed:
  - `grid_rungcomment_max1400_row32_fullwire_row0nop_native_20260307`
- Manifest verify statuses:
  - `2/2` `verified_pass`

Observed native lengths:
- `grc32fwnop_no_comment_native_20260307`
  - capture: `69632`
  - verify-back: `69632`
- `grc32fwnop_max1400_native_20260307`
  - capture: `73728`
  - verify-back: `73728`

Key outcome:
- the row32 full-wire row0-NOP max1400 native also allocates **exactly one additional `0x1000` page** relative to its no-comment control.
- this matches the earlier row32 empty-row pair exactly in total-length delta.

Why this matters:
- the extra page survives when:
  - all visible rows are full horizontal wire rows
  - row `0` is explicitly distinguished with `NOP`
- therefore the extra page is not dependent on empty visible rows acting as hidden carriers.

Additional offline summary from the full-wire row0-NOP pair:
- shared-prefix diff count (`full-wire max1400` vs `full-wire no-comment` over first `69632` bytes):
  - `28369`
- page-family structure by `0x1000` pages remains the same class:
  - page `0`: comment/payload-heavy lead page
  - page `1`: lead-in structural page
  - pages `2..15`: identical repeated diff family
  - page `16`: terminal/tail variant
  - page `17`: extra max1400-only page
- difference from the empty-row pair:
  - the extra page is no longer sparse
  - it contains `793` non-zero bytes and UTF-16LE font/display strings including:
    - `Segoe UI Variable Display Semilight`
    - `Segoe UI Variable Display Semibold`
    - `SimSun`
    - `NSimSun`
    - `SimSun-ExtB`
  - those strings are absent from the comment's ANSI RTF payload, which still uses `Arial`
  - they are also absent from the no-comment row32 full-wire control and the empty-row row32 max1400 capture
  - implication: the extra page is not just payload spillover; it likely carries renderer/layout companion records
  - more specifically:
    - page `17` decomposes into `4` top-level records, each beginning with `74 76 00 08`
    - three `492`-byte records carry `Segoe UI Variable Display` family variants
    - one larger `2520`-byte record carries `SimSun` / `NSimSun` / `SimSun-ExtB` fallback-family data
    - the first family-name string appears at relative offset `+0xAC` inside each record
    - helper for reproducible decode:
      - `devtools/analyze_max1400_page17.py`
    - record-layout decode now established:
      - the three Segoe records are leaf wrappers with:
        - `+0x84 = 0x01EC` (full record length)
        - `+0x88 = 0x0178`
        - stable gap `0x74`
      - the large CJK record is a container wrapper with:
        - `+0x84 = 0x01E4`
        - `+0x88 = 0x0170`
        - the same stable gap `0x74`
      - after its `0xA8`-byte wrapper, the CJK record expands into `5` nested fallback-face slots at:
        - `0x0A8`, `0x28C`, `0x470`, `0x654`, `0x838`
      - first four nested slots are full `0x1E4` entries on a `0x1E4` stride
      - the fifth is a terminal `0x1A0` slot
      - each nested slot contains:
        - family name
        - duplicate family name
        - `Regular`
        - secondary descriptor header `64 76 00 08` at slot `+0x144`
    - strongest current interpretation of the `0x012C / 0x015E / 0x0190 / 0x0258` codes:
      - weight-like or fallback-class ladder (`300 / 350 / 400 / 600`)
      - not record lengths or offsets
- cross-lane stability check against the empty-row row32 pair:
  - shared diff offsets over the common `69632` bytes: `25042`
  - empty-row-only diff offsets: `971`
  - full-wire-row0-NOP-only diff offsets: `3327`
  - implication:
    - most of the row32 max1400 footprint is shared across both lanes
    - lane-specific additions are secondary companions, not the core structure

Best current interpretation:
- the "comment row must be empty" model is materially weakened.
- the max1400 lane is better explained as a comment-owned extent/page family that can coexist with ordinary rung topology.
- topology changes affect what the extra page carries, but do not suppress the extra-page allocation.
- the terminal extra page now looks like a descriptor/render-companion page whose richness depends on the surrounding topology lane.
- current best conceptual model is:
  - a large lane-stable comment extent family spanning the repeated body pages
  - plus a smaller lane-sensitive terminal companion layer that can carry renderer/layout metadata

Additional offline refinement on the repeated body pages:
- pages `2..16` are now better modeled as **paired-row descriptor pages**
- basis:
  - each page is `0x1000`
  - the data still sits on the normal `0x40` cell stride
  - so each body page contains `64` cell-sized slots, naturally resolving as two `32`-column row bands
- across pages `2..15`, the only page-to-page varying bytes are slot `+0x09` and slot `+0x11`
- those bytes form a monotonic ladder by page, which fits extent ordinals / row-band indices better than visible wire markers
- lane relation:
  - empty-row lane: `+0x09` and `+0x11` share the same ordinal ladder
  - full-wire row0-NOP lane: `+0x09` keeps that ladder, while `+0x11` is shifted upward by `0x21`
- updated wording:
  - better than "empty pseudo rung with no wire markers"
  - current best phrase is "hidden paged extent that reuses cell-shaped descriptor slots"

Additional empty-row page-17 asymmetry:
- empty-row native page `17` remains extremely sparse
- empty-row verify-back page `17` does not remain sparse:
  - it grows to `683` non-zero bytes
- but it also does **not** become the rich full-wire `74 76 00 08` font/fallback table
- instead, verify-back page `17` resolves as another `64`-slot lattice page with:
  - slot `0` preserving the `0x20` terminal anchor
  - the remaining slots dominated by a repeating `3`-phase descriptor wave
  - compact patterns built from the same `09/10/03` and `07/10/03` vocabulary seen elsewhere in the structural family
- strongest current interpretation:
  - in the empty-row lane, Click synthesizes a reduced terminal descriptor page on copy-back
  - in the full-wire lane, it preserves a richer renderer/fallback companion page
  - so page `17` is now best treated as the most lane- and regeneration-sensitive terminal companion in the extent model

New offline prototype milestone:
- helper added:
  - `devtools/prototype_max1400_body_synth.py`
- result:
  - starting from the row32 no-comment native controls, the inferred rules now synthesize pages `2..16` exactly in both tested lanes:
    - empty-row row32
    - full-wire row0-NOP row32
- this includes:
  - all repeated body pages `2..15`
  - the terminal body page `16`
- practical implication:
  - the remaining unknown for max1400 synthesis is no longer the bulk body extent
  - it is concentrated in:
    - page `0`
    - page `1`
    - page `17`

New offline splice milestone:
- helper added:
  - `devtools/prototype_max1400_splice.py`
- construction:
  - row32 no-comment native base
  - synthesized pages `2..16`
  - donor pages `0/1/17` copied from the native row32 max1400 payload
- result:
  - full byte-for-byte reconstruction is now exact in both tested row32 lanes:
    - empty-row row32
    - full-wire row0-NOP row32
- implication:
  - for the tested row32 lanes, the current decomposition is exact and sufficient:
    - lead pages `0/1`
    - body pages `2..16`
    - terminal companion page `17`
  - the remaining synthesis problem is now tightly scoped to generating or selecting donor pages `0/1/17`

Recommended next step:
- continue offline interpretation/documentation first.
- if more native captures are still needed afterward, the best next size matrix remains:
  - row9 no-comment / max1400
  - row17 no-comment / max1400

## Execution Update (March 7, 2026 - Row32 Native Pair Strongly Favors Extent-Scaling)

- New result report:
  - `scratchpad/max1400_row32_native_results_20260307.md`
- Scenario completed:
  - `grid_rungcomment_max1400_row32_native_20260307`
- Manifest verify statuses:
  - `2/2` `verified_pass`
- Important interpretation note:
  - row rendering matched expected rows for both entries, but the decisive signal from this round is payload length, not the pass/fail label alone.

Observed native lengths:
- `grc32_no_comment_native_20260307`
  - capture: `69632`
  - verify-back: `69632`
- `grc32_max1400_native_20260307`
  - capture: `73728`
  - verify-back: `73728`

Key outcome:
- row32 max1400 native allocates **exactly one additional `0x1000` page** relative to row32 no-comment.
- the extra page exists in the native source capture itself and survives verify-back unchanged in total length.

Why this matters:
- this materially weakens the old idea that max1400 behavior is only a low-band row0/row1-band-local entanglement.
- it materially strengthens an extent-like / pseudo-row-like scaling model.

Additional offline summary from the row32 pair:
- shared-prefix diff count (`row32 max1400` vs `row32 no-comment` over first `69632` bytes):
  - `26013`
- extra max1400-only tail page:
  - `4096` bytes total
  - only `12` non-zero bytes
- page-family structure by `0x1000` pages:
  - page `0`: comment/payload-heavy lead page
  - page `1`: lead-in structural page
  - pages `2..15`: identical repeated diff family
  - page `16`: terminal/tail variant
  - page `17`: sparse extra descriptor-like page

Best current interpretation:
- the short-row `0x08FD..0x1A5F` family was probably only the low-row footprint of a larger scaling structure.
- at row32, max1400 reveals page-level repetition plus an extra sparse descriptor page.

Recommended next step:
- do offline page-family analysis before more operator queues.
- if another native matrix is needed afterward, capture:
  - row9 no-comment / max1400
  - row17 no-comment / max1400
- purpose:
  - locate when the extra `0x1000` page first appears.

## Execution Update (March 7, 2026 - Max1400 Offline Structural Analysis Completed)

- New offline report:
  - `scratchpad/max1400_structural_family_analysis_20260307.md`
- Identity check for the unresolved region is now explicit:
  - failing `grcmfs_commentwin_full_0294_08fc_from_freshnowire.bin` matches `grc_no_comment_fresh_native_20260307.bin` exactly over `0x08FD..0x1A5F`
  - passing `grcmfs_commentgrid_0294_1a5f_from_freshnowire.bin` matches `grc_max1400_fresh_native_20260307.bin` exactly over `0x0294..0x1A5F`
- Implication:
  - the unresolved family is exactly the native no-comment vs native max1400 delta in this lane, not synthetic drift.

Key structural findings from the offline pass:
- the so-called `120` non-grid bytes are not a loose pre-grid block.
- exact placement is:
  - `3` bytes in the tail of header entry col `26`
  - `22` bytes each in header entries cols `27..31`
  - `7` trailer bytes after the 32-entry header table (`0x0A55..0x0A5C`)
- row0 source deltas collapse into `5` stable families:
  - col `0`
  - cols `1..22`
  - col `23` boundary
  - cols `24..30` tail
  - col `31` terminal
- row1 source deltas also collapse into `5` stable families:
  - cols `0..22`
  - col `23` boundary
  - tail phases at cols `24/27/30`, `25/28/31`, `26/29`
- repeated monotonic codes and phased `09/10/03` triplets strongly suggest a coupled extent descriptor, not independent patch bytes.

Best current interpretation:
- the max1400 lane is still expressed through row0/row1-band metadata, but not as isolated local tweaks.
- evidence now favors a coherent extent-like / pseudo-row-like structural family spanning header-tail, row0, and row1.
- this explains why both:
  - observed-63 source patches
  - coarse structural block splits
  crashed instead of yielding a clean minimal fix.

Status after the offline pass:
- Phase 2 acceptance gate remains:
  - **not met**
- Recommended next native experiment:
  - capture a fresh row32 no-comment control and row32 max1400 control using `scratchpad/max1400_comment_body_20260307.txt`
- Reason:
  - this should distinguish low-row-only coupling from a genuinely scaling extent/pseudo-row model.

## Execution Update (March 7, 2026 - Max1400 Structure Scope Narrowed to 0x08FD..0x1A5F)

- Fresh recaptures established the correct no-wire lane for this investigation:
  - `grc_max1400_fresh_native_20260307`
  - `grc_no_comment_fresh_native_20260307`
- Important correction:
  - earlier synthetic max1400 probes built from historical `grc_no_comment_native` were not source-family matches for the fresh `R,...,:,NOP` lane.
  - symptom: synthetic probes could paste with a visible full wire rung even when authored/recorded as no-wire.
- Structure-scope scenario `grid_rungcomment_max1400_structure_scope_20260307` completed (`5` cases):
  - `2` `verified_pass` controls
  - `1` decisive fail
  - `2` decisive pass probes
  - all copied-event cases: `8192` bytes.

Key outcomes:
- `grcmfs_commentwin_full` (`0x0294..0x08FC` only):
  - failed
  - operator note: `hidden comment, R,-> full wire`
  - verify-back differed from fresh max1400 native at exactly `63` grid offsets.
- `grcmfs_commentgrid` (`0x0294..0x1A5F`):
  - passed
  - operator note: `worked. comment, no rung wire`
  - verify-back matched fresh max1400 native exactly (`0` diff bytes).
- `grcmfs_pregrid_header_commentgrid` (`0x0000..0x1A5F`):
  - passed
  - operator note: `full comment, no rung wire`
  - verify-back also matched fresh max1400 native exactly.

Strong inference from this round:
- bytes in `0x0000..0x0293` are not required for observed pasteback parity in this lane.
- bytes in `0x0294..0x08FC` are insufficient; that scope causes both:
  - hidden comment behavior
  - forced full-wire rung render
- copying through `0x1A5F` is sufficient for native-equivalent pasteback behavior in the tested lane.
- current smallest unresolved additional region beyond the old comment-window model is:
  - **`0x08FD..0x1A5F`**

Observed decisive 63-offset verify-back signature for the failing `commentwin` scope:
- row0 cols `24..31`: `cell +0x05/+0x09`
- row1 cols `0..22`: `cell +0x05/+0x09`
- row1 col `23`: `cell +0x05`

Status after this update:
- styled comments remain unsupported under the current model.
- max1400 plain lane is no longer best explained as a pure UI-refresh quirk.
- the defect is structural: the old comment-window transplant model omits required bytes through `0x1A5F`.
- Phase 2 acceptance gate remains:
  - **not met**
  - reason: a smaller minimal subset inside `0x08FD..0x1A5F` is still unresolved.

Next queued narrowing round:
- scenario: `grid_rungcomment_max1400_obs63_narrow_20260307`
- purpose:
  - test whether the `63` observed verify-back offsets are sufficient to restore native-equivalent behavior from the failing `commentwin` base.

## Execution Update (March 7, 2026 - Observed-63 Signature Is Marker, Not Minimal Source Fix)

- Scenario `grid_rungcomment_max1400_obs63_narrow_20260307` completed (`6` cases):
  - `1` `verified_pass` control
  - `1` `verified_fail` control
  - `4` `blocked` (`crash`)
- Key results:
  - `grcmft_commentwin_fail_control` reproduced the known failure:
    - note: `hidden comment, full rung :(`
  - `grcmft_commentwin_plus_obs63`: crash
  - `grcmft_commentwin_plus_row0tail63part`: crash
  - `grcmft_commentwin_plus_row1head63part`: crash
  - `grcmft_commentwin_plus_obs63_no_c23`: crash
- Interpretation:
  - the `63` observed verify-back offsets are **not** a safe minimal source patch.
  - they are downstream markers of the failing/passing difference, not a directly replayable fix set.

New source-level characterization from failing `commentwin` vs passing `commentgrid`:
- total source delta: `1194` bytes
- partition:
  - `120` non-grid bytes in approximately `0x0904..0x0A5C`
  - `685` row0 grid bytes
  - `389` row1 grid bytes

Next queued narrowing round:
- scenario: `grid_rungcomment_max1400_struct_blocks_20260307`
- purpose:
  - test the real source partitions:
    - non-grid `120`-byte block
    - row0 structural block
    - row1 structural block
    - combined row0+row1 block

## Execution Update (March 7, 2026 - Structural Block Splits Crash; Offline Analysis Recommended)

- Scenario `grid_rungcomment_max1400_struct_blocks_20260307` completed (`7` cases):
  - `2` `verified_pass` controls
  - `5` `blocked` (`crash`)
- Outcomes:
  - `grcmfr_max1400_fresh_control`: pass
  - `grcmfr_commentgrid_pass_control`: pass
  - `grcmfr_commentwin_fail_control`: crash in this run
  - `grcmfr_commentwin_plus_outside120`: crash
  - `grcmfr_commentwin_plus_row0full`: crash
  - `grcmfr_commentwin_plus_row1full`: crash
  - `grcmfr_commentwin_plus_row0_row1full`: crash

Interpretation:
- The real source delta from failing `commentwin` to passing `commentgrid` does not decompose cleanly into:
  - non-grid `120`-byte block alone
  - row0 structural block alone
  - row1 structural block alone
  - row0+row1 block without the accompanying non-grid bytes
- Current evidence favors a **coherent structural family spanning both pre-grid and row-structured bytes**, rather than a small replay-safe patch subset already isolated by manual splitting.

Recommended next step:
- pause manual patch-batch narrowing
- do an offline analysis pass first on the `0x08FD..0x1A5F` source delta:
  - classify repeating per-cell patterns
  - model the `120` non-grid bytes near `0x0904..0x0A5C`
  - determine whether the max1400 lane is:
    - entangled with row0/row1-band metadata
    - or represented through a pseudo-row/pseudo-extent structure

Recommended future native baseline experiment:
- capture a **32-row native max1400 comment** lane, paired with a 32-row no-comment control, using the same comment body.
- purpose:
  - test whether the max-comment coupling remains tied only to row0/row1-band-style metadata
  - or scales like a pseudo-row / extra structural extent at larger row counts

## Execution Update (March 7, 2026 - RungComment Closure Batch Completed, Gate Still Not Met)

- Scenario `grid_rungcomment_closure_20260307` completed (`11` cases):
  - `2` `verified_pass`
  - `4` `verified_fail`
  - `3` `blocked` (`crash`)
  - `2` intentionally skipped / left `unverified` after the styled stop condition
  - copied-event cases: `8192` bytes.
- Proven comment model remains:
  - length dword at `0x0294`
  - payload starts at `0x0298`
  - `len = payload_bytes + 1` including trailing NUL
  - payload is RTF-like ANSI text
  - max comment length is `1400` characters
- Styled lane closure:
  - hand-crafted minimal bold RTF probe crashed
  - italic/underline handcrafted probes were skipped by policy after the bold failure
  - classification: styled comments are unsupported under the current model
- Max1400 plain lane closure:
  - native `1400`-char control displayed immediately
  - current best synthetic (`len+payload + 0x08BD..0x08FC`) copied back at `8192` but stayed hidden at paste time
  - reopen check showed the same synthetic comment displays normally after reload
  - narrowing results:
    - `22`-offset refinement inside `0x08BD..0x08FC`: still hidden
    - core-cluster reductions: crash
    - singleton-only subset: still hidden
  - classification: plain comments up to `1400` chars are **partially working with caveat**
  - best current interpretation:
    - persisted bytes are semantically good enough to render after reopen
    - native-equivalent immediate display is still not achieved on the synthetic path
    - treat this as a paste-time UI refresh caveat with unresolved immediate-display parity
- Paste-time rendering classification for the best synthetic max1400 path:
  - **requires reopen to display**
  - prior probe also showed `Edit Comment` open/close can reveal the comment
- Phase 2 acceptance gate:
  - **not met**
- Phase 3 status:
  - still blocked by Phase 2 gate.
- Artifacts updated:
  - `scratchpad/phase2_rungcomment_inference_20260306.md`
  - `HANDOFF.md`

## Execution Update (March 6, 2026 - Phase 2 Companion Isolation Follow-Up Completed, Gate Still Not Met)

- Scenario `grid_rungcomment_patch_companion_isolation_20260306` completed (`16` cases):
  - `3` `verified_pass`
  - `0` `verified_fail`
  - `13` `blocked` (`crash`)
  - copied-event cases: `8192` bytes.
- Short lane (`no_comment` -> short donor):
  - len+payload control: pass
  - full-window (`0x0294..0x08FC`): pass
  - tail-only (`0x030E..0x08FC`): crash
  - implication: tail bytes alone are destabilizing, but tolerated when paired with coherent short len+payload.
- Style lane (`style_plain` -> bold/italic/underline donors):
  - all probes crashed, including:
    - bold len+payload control
    - bold full-window
    - bold split-tail variants
    - italic/underline full-window controls
  - implication: style replay requires companions outside the current `0x0294..0x08FC` probe window and/or additional lane normalization.
- Max1400 lane (`no_comment` -> max donor):
  - len+payload control: crash
  - full-window (`0x0294..0x08FC`): crash
  - lower-tail split (`0x0884..0x08BC`): crash
  - upper-tail split (`0x08BD..0x08FC`): pass with caveat (comment appears after opening/closing Edit Comment dialog)
  - tail-only: crash
  - implication: `0x08BD..0x08FC` is a high-signal companion candidate, but replay quality is not yet clean.
- Phase 2 acceptance gate:
  - **not met**.
- Phase 3 status:
  - still blocked by Phase 2 gate.
- Artifacts updated:
  - `scratchpad/phase2_rungcomment_inference_20260306.md`
  - `scratchpad/phase2_rungcomment_case_specs_20260306.json`
  - `scratchpad/phase2_rungcomment_patch_companion_case_specs_20260306.json`

## Execution Update (March 6, 2026 - Phase 2 Companion Isolation Follow-Up Batch Prepared)

- Follow-up scenario added to continue Phase 2 comment replay isolation:
  - scenario: `grid_rungcomment_patch_companion_isolation_20260306`
  - case count: `16` file-backed patch entries (`grcp2c_*`)
  - all new entries currently `unverified`.
- New artifact files:
  - case spec: `scratchpad/phase2_rungcomment_patch_companion_case_specs_20260306.json`
  - queue doc: `scratchpad/grid_rungcomment_patch_companion_isolation_verify_queue_20260306.md`
- Follow-up case design targets post-payload companion region:
  - short lane controls: len+payload, tail-only, full-window
  - style lane probes:
    - bold control (`0x0294..0x031C`)
    - bold full-window (`0x0294..0x08FC`)
    - bold split-tail ablations (`0x031D..0x03FF`, `0x0400..0x08FC`, half splits)
    - italic/underline full-window transplants
  - max1400 lane probes:
    - control (`0x0294..0x0883`)
    - full-window (`0x0294..0x08FC`)
    - tail chunk ablations (`0x0884..0x08BC`, `0x08BD..0x08FC`)
    - tail-only (`0x0884..0x08FC`)
- Purpose:
  - distinguish required post-payload companions from known noise-like co-variation.
- Phase 2 gate status remains:
  - **not met** (awaiting guided verify outcomes for this follow-up batch).

## Execution Update (March 6, 2026 - Phase 2 RungComment Patch Isolation Completed, Gate Not Met)

- Patch isolation scenario `grid_rungcomment_patch_isolation_20260306` completed (`12` cases):
  - `3` `verified_pass`
  - `2` `verified_fail`
  - `7` `blocked` (all `crash`)
  - copied-event cases remained `8192` bytes.
- Outcome highlights by required classification axis:
  - length dword only:
    - short length-only probe passed
    - max-length length-only probe crashed
    - short `len=0` reset probe copied back but failed with OOM note.
  - payload only:
    - short/max payload-only probes crashed
    - style payload-only probe copied but failed semantic expectation (raw RTF text shown).
  - length+payload:
    - short/plain probes passed (`len+payload`, and non-NUL length variant)
    - style (`bold/italic/underline`) transplants crashed
    - max1400 transplant crashed.
- Native-vs-native diff scope for comment variants was rechecked:
  - differences are not confined to `0x0294 + len window`;
  - observed co-varying region extends through approximately `0x08F1..0x08FC`.
- Current implication:
  - minimal replay model is incomplete for styled and long comments;
  - additional companion-byte isolation is required before claiming deterministic comment replay.
- Phase 2 acceptance gate:
  - **not met**.
- Phase 3 status:
  - not started (gated on Phase 2 completion).
- Artifacts updated:
  - `scratchpad/phase2_rungcomment_inference_20260306.md`
  - `scratchpad/phase2_rungcomment_case_specs_20260306.json`

## Execution Update (March 6, 2026 - Phase 1 AF `NOP` vs Empty Completed)

- Native AF matrix scenario `grid_af_nop_vs_empty_20260306` completed:
  - `9/9` `verified_pass`
  - placements validated at rows `0/1/4/8` (within row-count sets `1/2/9`)
  - verify-back lengths matched expected scale (`8192`, `24576`).
- Operator workflow note captured:
  - continuation-row `NOP` placement is reliable via insert-row-above/below authoring path.
- Patch isolation scenario `grid_af_nop_patch_isolation_20260306` completed:
  - `11` pass / `6` fail, all events `copied`
  - decisive sufficiency/necessity pattern isolated.
- Minimal AF `NOP` byte model (tested):
  - row0 `NOP`: set `row0 col31 +0x1D` (`0x123D`) to `1` (single-byte sufficient).
  - non-first-row `NOP` at target row `r`:
    - required: `r col31 +0x1D = 1`
    - required: `r col0 +0x15 = 1`
    - optional native-parity companion: `row0 col0 +0x15 = 0`
- Phase 1 acceptance gate status:
  - reproducible synthetic path for AF `NOP`: met
  - minimal decisive byte set identified (not full-region copy): met
- Artifacts:
  - `scratchpad/phase1_af_nop_inference_20260306.md`
  - `scratchpad/phase1_af_nop_case_specs_20260306.json`
  - `scratchpad/phase1_af_nop_patch_case_specs_20260306.json`
  - `scratchpad/grid_af_nop_patch_isolation_verify_queue_20260306.md`

## Execution Update (March 6, 2026 - Phase 2 RungComment Native Mapping Completed, Patch Isolation Ready)

- Native comment scenario `grid_rungcomment_mapping_20260306` completed:
  - `11/11` `verified_pass`
  - all events `copied`
  - verify-back length `8192` across cases.
- Comment payload model from native captures:
  - length dword at `0x0294`
  - payload starts at `0x0298`
  - observed rule: `len_dword = payload_bytes + 1` (includes trailing NUL).
- Content encoding:
  - RTF-like ANSI payload (`{\\rtf1\\ansi\\ansicpg1252...}`).
  - UTF probe showed degree-symbol escape (`\\'b0`) as expected for RTF/CP1252.
- Style mapping confirmed in payload token stream:
  - bold: `\\b ... \\b0`
  - italic: `\\i ... \\i0`
  - underline: `\\ul ... \\ulnone`
  - mixed inline styling (selected text segments) confirmed:
    - `\\b ... \\b0`
    - `\\b\\i ... \\b0\\i0`
    - `\\ul\\b ... \\ulnone\\b0`
- Max-length correction:
  - true comment max is `1400` chars (initial `1396` estimate corrected).
  - existing label `grc_maxlen_1396_native` is historical; captured payload body is `1400` chars.
- Phase 2 patch-isolation setup prepared:
  - scenario: `grid_rungcomment_patch_isolation_20260306`
  - case count: `12` file-backed patch entries
  - artifacts:
    - `scratchpad/phase2_rungcomment_patch_case_specs_20260306.json`
    - `scratchpad/grid_rungcomment_patch_isolation_verify_queue_20260306.md`
    - `scratchpad/phase2_rungcomment_inference_20260306.md`

## Execution Update (March 4, 2026 - Two-Series Hardening Pass)

- Click-safe encoder scope remains intentionally limited to `1..2` series contacts.
- Header seed model is now context-seeded:
  - `ClickCodec.encode(..., header_seed=HeaderSeed(...))` is supported.
  - Seed writes entry-uniform header bytes `+0x05/+0x11/+0x17/+0x18`.
  - `0x0A59` now mirrors header entry `+0x05` via seed application.
- Fixed header-family literals are no longer treated as rung semantics.
- Second-immediate (`X001,X002.immediate`) keeps a guarded compatibility override for header
  `+0x05/+0x11` and trailer mirror when no explicit seed is provided.
- Capture workflow/CLI now supports seed-source selection for verify prepare/run:
  - `--seed-source {clipboard,scaffold,entry,file}`
  - default `clipboard` with explicit scaffold fallback warning.
- Capture workflow/CLI now supports manifest deletion:
  - `entry delete --label ...`
  - `entry delete --scenario ...`
  - dry-run by default; apply with `--yes`.
- Working manifest was de-swamped:
  - backup created at `scratchpad/archive/ladder_capture_manifest.pre_prune_20260304.json`
  - exploratory scenarios removed from active manifest
  - deterministic `two_series_hardening_matrix_20260304` (9 rows) added for focused verify.

## Execution Update (March 5, 2026 - Empty-Template Reset + Phase 5 Masking)

- Baseline scenario `grid_basics_empty_template_20260305` is complete:
  - `14/14` native captures verified (`verify run --source file`), all `verified_pass`.
- Width experiment conclusion:
  - `default/narrow/wide` variants produced no byte-level diffs in tested empty and wire baselines.
- Phase 5 mask trials completed:
  - `grid_basics_phase5_session_mask_20260305`: `13/14` pass, `1/14` fail
    (`grid_empty_row2_duplicate_native` broke after first column).
  - Narrowing scenario `grid_basics_phase5_narrow_row2_20260305`:
    - only `h11`-only normalization passed;
    - variants touching `+0x05` and/or `0x0A59` failed.
  - Refined scenario `grid_basics_phase5_refined_h11_h17_20260305`:
    - normalize `+0x11/+0x17` only;
    - `14/14` pass.
- Working classification for grid-basics lane:
  - safe session normalization: header `+0x11`, `+0x17`
  - keep untouched for now: header `+0x05`, trailer `0x0A59`
  - unresolved at this stage: header `+0x18` (resolved later in same day; see next update)
- Full gate notes and artifact links:
  - `scratchpad/noise_vs_structure_reassessment_20260305.md`

## Execution Update (March 5, 2026 - Grid Synthesis Lane + `+0x18` Isolation)

- Lane 1 (`grid_synth_empty_template_20260305`) from empty native template:
  - `4/5` pass for single-row empty/horizontal cases
  - failing case: `grid_synth_empty_rows1_2_synthetic` pasted as one row
- Lane 2 (`grid_synth_h18_isolation_20260305`) focused `+0x18` sweep:
  - 12 patch cases across 4 passing lane-1 baselines
  - `+0x18 = 0x00/0x7F/0xFF` all pass (`12/12`)
- Updated classification for empty/horizontal baseline:
  - safe session normalization: `+0x11`, `+0x17`, `+0x18`
  - keep donor-preserved: `+0x05`, `0x0A59`
- Queue/reference artifacts:
  - `scratchpad/grid_synth_empty_template_verify_queue_20260305.md`
  - `scratchpad/grid_synth_h18_isolation_verify_queue_20260305.md`
  - `scratchpad/noise_vs_structure_reassessment_20260305.md`

## Execution Update (March 5, 2026 - Multi-Row Recapture + Isolation)

- Fresh recaptures validated native multi-row empties:
  - `grid_empty_rows1_2_recapture_native` (2-row pass)
  - `grid_empty_rows1_2_3_recapture_native` (3-row pass)
- Multi-row isolation phase 1 (`grid_multirow_isolation_20260305`):
  - only full-native control passed;
  - most partial-region variants collapsed to one row.
- Multi-row isolation phase 2 (`grid_multirow_isolation_phase2_20260305`):
  - `row0+row1` copy passed while preserving synthetic pre/header/tail;
  - row0 + pre/header/tail combinations blocked (edit/crash/stuck).
- Current inference:
  - two-row collapse gate is row-block structural bytes (priority on row1-linked region),
    not pre/header/tail session metadata.
- Multi-row narrowing phases (3..6) produced a minimal observed two-row fix:
  - required row1 bytes: `+0x10` across all row1 columns
  - required row0 bytes: col31 `+0x38` and `+0x3D`
  - insufficiency checks:
    - row1 `+0x10` without row0 companions fails
    - row0 col31 `+0x38` only fails
    - row0 col31 `+0x3D` only fails
  - passing check:
    - row1 `+0x10` + row0 col31 `{+0x38,+0x3D}` passes (2-row empty)
- Tool confirmation/probe (`grid_multirow_companion_confirm_20260305`):
  - 2-row synthetic with companion mode: pass
  - 2-row synthetic without companion mode: fail (collapses to 1 row)
  - 3-row native ablate/restore:
    - ablate companion offsets: fail (collapses to 1 row)
    - restore companion offsets: pass (3 rows)
    - restore row1-only: fail (1 row)
    - restore col31-only: fail (invalid boxes)
- Updated inference:
  - companion bytes act as a required combination for valid multi-row empty synthesis.
  - same companion set currently restores both 2-row and 3-row empty baselines.

## Execution Update (March 5, 2026 - Empty Multi-Row Row-Rule Inference, Rounds 1-10)

- New report artifact:
  - `scratchpad/row_rule_inference_empty_multirow_20260305.md`
- Native empty captures (`1/2/3/4/9/17/32 rows`) support deterministic row geometry rules:
  - header entry0 word (`+0x00/+0x01` little-endian):
    - `row_word = (logical_rows + 1) * 0x20`
  - empty payload length scaling:
    - `len = 0x1000 * (ceil(rows / 2) + 1)`
  - active-row cell formulas validated across native set:
    - `+0x01 = col_index`
    - `+0x05 = row_index + 1`
    - constants: `+0x09/+0x0A/+0x0C = 0x01`, `+0x0D..+0x10 = 0xFF`, `+0x11 = 0x01`
    - terminal-row linkage:
      - `+0x38 = 1`, except terminal-row col31 -> `0`
      - `+0x3D = row+1` for cols `0..30`; col31 is next-row marker or terminal `0`
- High-signal verified outcomes from row-rule isolation:
  - header `+0x05` and trailer `0x0A59` are independent structural/context gates in empty lanes.
  - simple tuple injection (`h05/h11/h17/h18/t59`) is insufficient by itself for 2-row nonzero-seed replay.
  - tuple + row-coupled `cell +0x39` is the decisive 2-row restoration pattern.
- Current high-confidence 2-row nonzero-seed coupling rule (empty lane):
  - require tuple seed (`header +0x05/+0x11/+0x17/+0x18` and `0x0A59`)
  - require `cell +0x39 = 1` on:
    - row0 cols `0..31`
    - row1 cols `0..30`
  - row1 col31 is optional (`0` or `1` both validated pass)
- Implication:
  - for empty 2-row synthesis under this seed lane, header-only patching is insufficient;
    coupled row-level control bytes must be applied.
- Supporting scenarios/queues:
  - `grid_empty_multirow_rowrule_iso_20260305` through
    `grid_empty_multirow_rowrule_iso10_20260305`
  - queue docs in `scratchpad/grid_empty_multirow_rowrule_iso*_verify_queue_20260305.md`

## Execution Update (March 6, 2026 - Empty Multi-Row Scale Confirmation)

- Scenario `grid_synth_empty_multirow_rule_minimal_20260306` completed:
  - `4/4` pass (`gmrs_rows04/09/17/32_rule_minimal`).
  - verify-back lengths matched expected scaling:
    - row4 `12288`
    - row9 `24576`
    - row17 `40960`
    - row32 `69632`
- These synthetic files intentionally omitted low-confidence bytes
  (`cell +0x0B`, `cell +0x15`) while preserving proven row-rule offsets.
- Updated implication:
  - in empty multi-row lane, `+0x0B/+0x15` are not required at tested scales (`4/9/17/32`)
    when the proven rule offsets are present.
- Next queued batch prepared:
  - scenario: `grid_synth_empty_multirow_crossdonor_row9_20260306`
  - queue doc: `scratchpad/grid_synth_empty_multirow_crossdonor_row9_verify_queue_20260306.md`
  - purpose: cross-donor row9 synthesis from row4 template (with/without restoring `+0x0B/+0x15`).

## Execution Update (March 6, 2026 - Empty Multi-Row Cross-Donor Row9)

- Scenario `grid_synth_empty_multirow_crossdonor_row9_20260306` completed:
  - `2/2` pass:
    - `gmrsx_rows09_fromrow4_rule_minimal`
    - `gmrsx_rows09_fromrow4_rule_plus0b15`
  - verify-back length for both: `24576`.
- Result interpretation:
  - row-rule synthesis remains stable under cross-donor construction (row9 built from row4 donor).
  - restoring `+0x0B` and terminal `+0x15` did not affect outcome in this probe.

## Execution Update (March 6, 2026 - Empty Multi-Row Rule Encoding Integrated)

- Production code now includes deterministic empty multi-row synthesis:
  - module: `src/clicknick/ladder/empty_multirow.py`
  - API: `synthesize_empty_multirow(logical_rows, ...)`
  - validated range: `1..32` logical rows (empty lane).
- Topology decode was corrected for larger row counts:
  - `logical_row_count_from_header(...)` now uses the 16-bit header row word (`+0x00/+0x01`)
    before legacy 1-byte class fallback.
  - fixes alias case where row9 row-word `0x0140` previously looked like class `0x40`.
- Passing empty-lane synthetic entries were promoted to fixtures:
  - `gmrs_rows04_rule_minimal`
  - `gmrs_rows09_rule_minimal`
  - `gmrs_rows17_rule_minimal`
  - `gmrs_rows32_rule_minimal`
  - `gmrsx_rows09_fromrow4_rule_minimal`
  - `gmrsx_rows09_fromrow4_rule_plus0b15`
- Current boundary:
  - Empty multi-row generation is now codified for this family.
  - Non-empty multi-row synthesis still requires separate rule work before claiming
    arbitrary row-height rung generation for general ladders.

## Execution Update (March 6, 2026 - Non-Empty Multi-Row Horizontal/Vertical Isolation Setup)

- New non-empty multi-row scenarios were added (file-backed patch entries, no codec changes):
  - `grid_nonempty_multirow_horiz_20260306` (`9` labels: `gnmh_*`)
  - `grid_nonempty_multirow_vert_20260306` (`8` labels: `gnmv_*`)
- Required queue docs created:
  - `scratchpad/grid_nonempty_multirow_horiz_verify_queue_20260306.md`
  - `scratchpad/grid_nonempty_multirow_vert_verify_queue_20260306.md`
- New round report created:
  - `scratchpad/nonempty_multirow_horiz_vert_inference_20260306.md`

Horizontal track setup highlights:
- Base donor lane: `vert_b_only` (2-row vertical at col1).
- Minimal candidate bytes under active isolation:
  - `r0 c1 +0x19/+0x1D` (`0x0AB9`, `0x0ABD`)
  - `r1 c1 +0x19/+0x1D` (`0x12B9`, `0x12BD`)
  - extent probe: `r0 c0 +0x1D` (`0x0A7D`)
- Generated variants include row0-only, row1-only, both-rows (same extent), both-rows (different extent), and single-byte ablations.

Vertical track setup highlights:
- Base donor lane: `vert_b_3rows` (3-row col1 continuity).
- Minimal candidate bytes under active isolation:
  - `r0 c1 +0x21` (`0x0AC1`)
  - `r1 c1 +0x21` (`0x12C1`)
  - column-shift probe to col3 (`0x0B41`, `0x1341`)
- Generated variants include 2-row controls, 3-row control, single-link ablations, dual-link ablation, and col1->col3 shift.

Current status:
- All new non-empty entries are currently `unverified` and queued for guided run (`tui -> 3 -> g -> f`).
- No production codec integration was performed for non-empty multi-row logic in this pass.

Recommendation:
- **more isolation required** (pending guided verify outcomes for the new horizontal and vertical scenario queues).

## Execution Update (March 6, 2026 - Non-Empty Horizontal Batch Completed)

- Scenario `grid_nonempty_multirow_horiz_20260306` completed (`9` cases):
  - `8` `verified_pass`
  - `1` `verified_fail` (`gnmh_ablate_r1_hright_only`)
  - all events `copied`
  - all verify-back lengths `8192`
- Verified pass path for non-empty 2-row horizontal continuity is now reproducible.

High-signal horizontal inference (col1, 2-row non-empty lane):
- `r1 c1 +0x1D` (absolute `0x12BD`) is decisive for row1 horizontal continuity.
- `r1 c1 +0x19` (absolute `0x12B9`) alone is insufficient.
  - evidence:
    - `gnmh_ablate_r1_hleft_only` (keep `+0x1D`, clear `+0x19`) passed.
    - `gnmh_ablate_r1_hright_only` (keep `+0x19`, clear `+0x1D`) failed.
- Row0 extent probe (`r0 c0 +0x1D`) remained compatible (`gnmh_both_rows_horiz_diff` passed).

Status after this update:
- Horizontal track: complete for this round.
- Vertical track (`grid_nonempty_multirow_vert_20260306`): still pending (`8` unverified).

Recommendation:
- **more isolation required** until vertical queue outcomes are recorded and combined
  horizontal/vertical minimal sets are finalized.

## Execution Update (March 6, 2026 - Non-Empty Vertical Batch Completed + Combined Conclusion)

- Scenario `grid_nonempty_multirow_vert_20260306` completed (`8` cases):
  - `8` `verified_pass`
  - `0` `verified_fail`
  - all events `copied`
  - verify-back lengths:
    - 2-row controls: `8192`
    - 3-row cases: `12288`

High-signal vertical inference (tested non-empty lane):
- `cell +0x21` is the deterministic inter-row continuity control at target row/column cells.
  - clearing `r1 c1 +0x21` leaves only the top link.
  - clearing `r0 c1 +0x21` leaves only the middle link.
  - clearing both removes vertical continuity entirely.
- Column scaling is direct:
  - moving `+0x21` writes from `c1` to `c3` moved observed continuity from column B to D.
- Terminal 3-row endpoint behavior stayed stable (`gnmv_force_terminal_r2c1_vdown0` pass).

Combined non-empty horiz/vert conclusion for this round:
- Reproducible synthetic path exists for both horizontal and vertical continuity.
- Minimal decisive candidate sets identified in tested lanes:
  - horizontal: row1 col1 `+0x1D` decisive (`+0x19` alone insufficient in this geometry)
  - vertical: per-cell `+0x21` controls continuity links

Recommendation:
- **ready for implementation planning** for scoped non-empty wire-topology synthesis
  (2-row/3-row continuity rules proven here).
- Keep follow-up validation queued for:
  - 4-row non-empty lanes
  - mixed instruction-heavy non-empty families.

## Execution Update (March 6, 2026 - 4+/Row-Combo Validation Completed)

- Scenario `grid_nonempty_multirow_rowcombo_20260306` completed (`12` cases):
  - `11` `verified_pass`
  - `1` `verified_fail` (`gnmr4_t_r2_c1_keep_hleft`)
  - all events `copied`
- Queue and case-spec artifacts used:
  - `scratchpad/grid_nonempty_multirow_rowcombo_verify_queue_20260306.md`
  - `scratchpad/nonempty_multirow_rowcombo_case_specs_20260306.json`

Row-count scaling checks from verify-back:
- rows4 cases: `12288` bytes, row-word `0x00A0`
- rows5 cases: `16384` bytes, row-word `0x00C0`

4+/row-combo implications:
- Vertical continuity (`+0x21`) remained deterministic across rows4/5, including sparse
  and non-contiguous link placements.
- Column-scaling remained deterministic (`c1 -> c3` chain probe passed).
- Horizontal asymmetry under `T` at row2 reinforces prior gate:
  - `+0x1D` retained (`gnmr4_t_r2_c1_keep_hright`): pass
  - `+0x19` only without `+0x1D` (`gnmr4_t_r2_c1_keep_hleft`): fail and collapsed to vertical-only (`|`).
  - corrected observed rows were backfilled in manifest for the fail case.

Updated recommendation:
- Non-empty wire-topology findings are now validated through 5-row row-combo probes.
- Proceed to implementation planning for scoped topology synthesis rules, with follow-up
  validation still advised for instruction-stream-heavy mixed families.

## Execution Update (March 6, 2026 - Scale-to-32 Validation Completed)

- Scenario `grid_nonempty_multirow_scale_20260306` completed (`8` cases):
  - `7` `verified_pass`
  - `1` `verified_fail` (`gnms32_t_r30_c1_keep_hleft`)
  - all events `copied`
- Scale checkpoints validated:
  - rows9 chain: len `24576`, row-word `0x0140`
  - rows17 chain: len `40960`, row-word `0x0240`
  - rows32 cases: len `69632`, row-word `0x0420`

High-signal scale findings:
- Vertical continuity remains deterministic through row32:
  - `gnms32_vert_chain_c1` and `gnms32_vert_chain_c3` both passed.
- Deep-row mixed-cell asymmetry at row30 matches lower-row findings:
  - `gnms32_t_r30_c1` pass
  - `gnms32_t_r30_c1_keep_hright` pass
  - `gnms32_t_r30_c1_keep_hleft` fail; observed collapse from `T` to `|`.
- `gnms09_vert_chain_c1` was re-run explicitly and verified pass with matching rows/topology.

Updated recommendation:
- Non-empty wire-topology findings now have direct evidence through row32 for tested patterns.
- Proceed to implementation planning for scoped topology synthesis, with explicit caveat that
  instruction-stream-heavy non-empty families still need dedicated follow-up validation.

## Execution Update (March 6, 2026 - Non-Empty Synthesis Impl + Asymmetry Confirmation)

- Production now has scoped non-empty multi-row wire synthesis:
  - module: `src/clicknick/ladder/nonempty_multirow.py`
  - API: `synthesize_nonempty_multirow(logical_rows, wire_rows, ...)`
  - supported range/tokens:
    - rows `2..32`
    - tokens `""`, `-`, `|`, `T` across condition columns `A..AE`
  - guard behavior:
    - column-A `|` is rejected by default (`col_a_vertical_policy='reject'`)
    - optional normalization path: `col_a_vertical_policy='blank'`
- Unit coverage added:
  - `tests/ladder/test_nonempty_multirow.py`
  - validates length/row-word scaling, token mapping, row-shape guards, column-A policy, and stale-flag clearing.
- Implementation smoke verify batch completed:
  - scenario: `grid_nonempty_multirow_impl_smoke_20260306`
  - result: `5/5` `verified_pass`
  - lengths: `8192`, `12288`, `24576`, `69632` (matched expected rows).
- Asymmetry edge batch completed:
  - scenario: `grid_nonempty_multirow_impl_asymmetry_20260306` (`9` cases)
  - result: `6` pass / `3` fail; all fails are `*_keep_hleft`
    - `gnmia04_t_r2_c1_keep_hleft`
    - `gnmia09_t_r7_c3_keep_hleft`
    - `gnmia32_t_r30_c1_keep_hleft`
  - all `*_keep_hright` passed at rows `4/9/32`.
  - verify-back target-cell flags confirmed consistent signature:
    - control `T`: `(1,1,1)`
    - keep-hright: `(0,1,1)` -> pass
    - keep-hleft: `(0,0,1)` -> fail (collapse to vertical-only behavior).

Updated recommendation:
- Non-empty multi-row wire synthesis is validated for a guarded integration path.
- Keep default codec behavior unchanged until gated wiring is added and one post-wire manual verify sweep is completed.
- Continue separate follow-up for instruction-stream-heavy mixed families.

## Goal

Reverse engineer Click Programming Software's clipboard format so `clicknick.ladder`
can generate clipboard-ready bytes for paste into Click from `RungGrid`.

## Current Status

- `clicknick.ladder` now uses a deterministic encoder (no runtime dependency on per-variant
  `.bin` templates under `src/clicknick/ladder/resources`).
- Header behavior is partially characterized:
  - refined session normalization (`+0x11/+0x17/+0x18`) is validated for empty/horizontal baselines.
  - `+0x05` and `0x0A59` are context-sensitive and can be structural.
- Wire topology cell flags are mapped and validated by pasteback.
- Manual pasteback now succeeds for:
  - `smoke_simple`
  - `smoke_immediate`
  - `smoke_two_series_short` (full `X001,X002,->,:,out(Y001)` now pastes)
- `two_series_second_immediate` is now resolved:
  - final validation capture: `two_series_second_immediate_back_after_generated_v3_headerfix.bin`
  - pasteback length `8192`, decodes as `X001,X002.immediate,->,:,out(Y001)`
- New intermediate progress (March 3, 2026, afternoon):
  - deterministic profile-cell fixes for `+0x05/+0x11` were added and validated against fixture tables
  - failure mode improved from total fragmentation to a consistent two-rung split
  - current split signature after pasteback is `12288` bytes with marker relocation:
    - contact1 at `0x0A99`
    - contact2 at `0x1B1E`
    - coil at `0x22D9`
- Instruction stream placement remains the primary engineering area (especially broader
  operand-length and multi-contact generalization).

## New Findings (March 3, 2026 - v2 Isolation Pass)

### A) `+0x1A/+0x1B` are not the primary split gate

Using valid generated 8192 payloads (all 3 markers present) and mutating only profile cells
(`row0 col4..31`, `row1 col0`):

- `two_series_second_immediate_generated_v2_baseline.bin`
- `..._patch_profile_1a_00.bin`
- `..._patch_profile_1b_00.bin`

All three paste back as `12288` and split into two rungs with the same marker relocation pattern.
Interpretation: `+0x1A/+0x1B` influence profile/family behavior but do not by themselves determine
single-rung assembly for this variant.

### B) Row1/Row2 grid content is no longer the dominant unknown

Two stronger controls were tested:

- `..._patch_zero_row1tail_row2.bin` (zero row1 tail and row2)
- `..._patch_row1row2_from_native.bin` (copy row1+row2 grid region exactly from native)

Observed outcome (user-verified): still two rungs.

Important implication:
- Even with row1/row2 grid bytes forced to native, split persists.
- Remaining blocker likely resides outside those row blocks (pre-grid metadata and/or header-family
  bytes that were previously treated as non-structural, plus possible stream-to-grid coupling bytes
  in the pre-grid region).

### D) Pre-grid shortlist extracted by control-filtered ranking

Method:
- Compare failing `two_series_second_immediate` generated-v2 pre-grid bytes against native.
- Remove offsets that also mismatch in known-working controls:
  - `smoke_simple`
  - `smoke_immediate`
  - `smoke_two_series_short`

Result:
- Failing pre-grid mismatches: `114`
- Unique-to-failing offsets after control filtering: `4`
  - `0x006E`: gen `0x00`, native `0x61`
  - `0x0072`: gen `0x00`, native `0x79`
  - `0x0076`: gen `0x00`, native `0x65`
  - `0x007E`: gen `0x00`, native `0x1E`

Targeted payload generated for direct pasteback validation:
- `scratchpad/captures/two_series_second_immediate_generated_v2_patch_pregrid_focus4_native.bin`

### E) Header-region gate confirmed

Isolation tests on generated-v2 payloads established:

- `0x0000..0x0253` (pre-header) native copy alone: still split (`12288`)
- `0x0254..0x0A5F` (header region) native copy alone: single rung (`8192`)

Within that header region for `two_series_second_immediate`, generated-v2 differed from native
almost exclusively at:

- entry `+0x05` (all 32 entries): generated `0x00`, native `0x04`
- entry `+0x11` (all 32 entries): generated `0x00`, native `0x0B`
- trailing byte `0x0A59`: generated `0x00`, native `0x04`

Applying those bytes restores single-rung pasteback behavior.

Final validation:

- `two_series_second_immediate_generated_v3_headerfix.bin` pasted and copied back as
  `two_series_second_immediate_back_after_generated_v3_headerfix.bin`
- Result: `8192` bytes, marker triad at `0x0A99 / 0x0B1E / 0x12D9`, decode
  `X001,X002.immediate,->,:,out(Y001)`

Encoder update now in place:

- For second-immediate two-series (`X001,X002.immediate` family), deterministic encoder writes:
  - header `+0x05 = 0x04`
  - header `+0x11 = 0x0B`
  - `0x0A59 = 0x04`

### C) `+0x05/+0x11` profile table is now characterized for two-series fixtures

Observed fixture-backed profile values in `row0 col4..31` and `row1 col0`:

- non-immediate NO/NC series: `+0x05=0x00`, `+0x11=0x00`
- first immediate only: `+0x05=0x25`, `+0x11=0x52`
- second immediate only: `+0x05=0x04`, `+0x11=0x0C`
- both immediate: `+0x05=0x00`, `+0x11=0x00`
- rise first: `+0x05=0x62`, `+0x11=0x01`
- fall first: `+0x05=0x64`, `+0x11=0x01`

This table is implemented in deterministic encoder logic and covered by tests.

## Canonical Structural Findings

### 1) Fixed Buffer Size

- Full rung clipboard buffer is `8192` bytes (`0x2000`), zero-padded.

### 2) Header Table (`0x0254 + n*0x40`, `n=0..31`)

- Entry `n` corresponds to column `n`.
- Entry offset `+0x0C..+0x0F` stores the column index as a little-endian dword.
- Entry offsets `+0x05/+0x11/+0x17/+0x18` vary across captures, but are not uniformly
  non-structural:
  - grid-basics + lane-2 isolation show `+0x11/+0x17/+0x18` can be normalized safely for
    empty/horizontal baseline workflows.
  - `+0x05` can be structural (row2-duplicate empty case).
- Global row-class byte is at `0x0254`:
  - `0x40` => 1 logical row
  - `0x60` => 2 logical rows
  - `0x80` => 3 logical rows
- Observed non-volatile header family bytes at `+0x17/+0x18` are capture-family classifiers
  (uniform across all 32 entries in a given capture), but the decision table is incomplete.
  Examples observed so far: `0x15/0x01`, `0x0D/0x01`, `0xEA/0x00`.
- Topology/instruction content still lives in grid + stream regions; header family bytes alone
  do not encode per-cell wire layout and are not sufficient to guarantee valid rung assembly.

### 3) Grid Layout

- Row 0 start: `0x0A60`
- Row stride: `0x800` (`32 * 0x40`)
- Cell stride (column): `0x40`

### 4) Wire Topology Flags (Per 64-byte Cell)

- `+0x19`: horizontal-left flag
- `+0x1D`: horizontal-right flag
- `+0x21`: vertical-down-to-next-row flag

Corners are implicit from flag combinations on the same cell.

### 5) Additional Per-Cell Structural Control Bytes (New)

- Wire flags are necessary but not sufficient.
- Two-series immediate experiments show additional non-stream cell bytes participate in rung
  assembly/linkage.
- When these bytes are wrong, Click can split a single intended rung into multiple records/rungs
  (with intermediate `NOP`), even when instruction markers and operands are otherwise valid.
- Practical symptom: pasteback clipboard length changes from `8192` to multi-record sizes
  (for example `20480` or `73728`) and coil markers may disappear from the first record.

### 6) Instruction Stream

- Instructions are serialized stream content; fields are stable at stream-relative offsets
  from the type marker (`0x27XX`).
- Operand strings are UTF-16LE and variable length; downstream fields shift accordingly.
- Immediate contact variants shift function-code location by `+2` bytes relative to
  non-immediate.

## Instruction Type / Function Code Summary

Contacts:
- NO: `0x2711` + `4097`
- NC: `0x2712` + `4098`
- NO immediate: `0x2711` + `4099`
- NC immediate: `0x2712` + `4100`
- Rise/Fall edge: `0x2713` + `4101/4102`

Coils:
- Out: `0x2715` + `8193` (plus immediate/range variants)
- Latch: `0x2716` + `8195` (plus immediate/range variants)
- Reset: `0x2717` + `8196` (plus immediate/range variants)

## Superseded Findings (Historical)

### Superseded: Old Finding 19 (Header Coupling/Pointer Dependency)

Prior handoff versions suggested immediate placement required structural header table
mutations (and possibly pointer/rendering table coupling) for safe generation.

This is superseded by the normalized diff and pasteback evidence in
`scratchpad/capture-diff-results.md`:

- After masking volatile bytes (`+0x05`, `+0x11`), header entries remain structurally
  invariant across tested immediate vs non-immediate comparisons.
- Pasteback (`vert_b_with_horiz` -> recapture) shows structural header equality and
  identical parsed topology.

Interpretation: header coupling is not a blocker for current codec goals; instruction
stream and grid topology are the main work surfaces.

## Hypothesis Check: Per-Row Header Descriptor Table

Hypothesis reviewed:
- `0x0254 + n*0x40` is a per-column table that encodes per-row state (`2` bytes per row).

Current evidence status: **not supported**.

What we observed:
- The stable row-count indicator is a single global class byte at `0x0254` (`0x40/0x60/0x80`).
- Per-entry `+0x0C..+0x0F` is a fixed column index dword.
- Newly confirmed header family bytes `+0x17/+0x18` are global per-capture-family constants,
  not row-addressed fields.
- Wire topology authority remains in cell flags (`+0x19`, `+0x1D`, `+0x21`) with row stride
  `0x800` and column stride `0x40`.

Interpretation:
- We do not currently see evidence for a "2 bytes per row per column" encoding model in this
  header table.
- The earlier ghost-row/red-invalid behavior is better explained by malformed stream/structural
  bytes during transitional encoder experiments, not by missing per-row header writes.
- This hypothesis is not mathematically impossible, but it is not supported by current capture
  diffs/pasteback behavior.
- Important refinement: while the header table is not the per-row authority, grid-level control
  bytes beyond `+0x19/+0x1D/+0x21` do affect assembly/segmentation behavior.

## Legacy Runtime Templates (Planned Removal Complete Path)

These files were legacy runtime templates and are tracked here for retirement context:

1. `src/clicknick/ladder/resources/NO_X002_coil.AF.bin`
2. `src/clicknick/ladder/resources/NO_X001_X002_coil.AF.two_series.bin`
3. `src/clicknick/ladder/resources/NO_X001_immediate_X002_coil.AF.two_series.bin`
4. `src/clicknick/ladder/resources/NO_X001_X002_immediate_coil.AF.two_series.bin`
5. `src/clicknick/ladder/resources/NO_X001_immediate_X002_immediate_coil.AF.two_series.bin`

Rationale for retirement:
- They are compatibility artifacts, not canonical format documentation.
- Vetted captures in `scratchpad/captures` are treated as provenance for fixture curation.

## Hermetic Fixture Policy

Capture-backed tests should use checked-in fixtures under:

- `tests/fixtures/ladder_captures/`
- `tests/fixtures/ladder_captures/manifest.json`

Manifest entries map:
- fixture filename
- original capture label
- intended scenario

This avoids local-only dependency on gitignored `scratchpad/captures` during CI/local test runs.

## Open Questions

1. Multi-row non-empty (horizontal/mixed-wire) synthesis: does the empty-template companion rule
   remain sufficient when row2/row3 include wire geometry?
2. Per-cell structural control bytes in the row0/row1 bands (beyond wire flags): exact role in broader
   instruction families now that second-immediate is solved.
3. Stream metadata bytes (`65 60`, `67 60`, related blocks): exact semantics and whether
   all are mandatory per instruction family.
4. Full stream placement formula coverage for broader two-series combinations with mixed
   operand lengths and immediate flags.
5. Register-bank breadth validation beyond current proven sets (DS/T/TD families).
6. Single-cell (`4096` byte) clipboard payload viability for independent cell pasting.
7. Explicit multi-row generation API shape (if/when `RungGrid` should carry full topology).

## Next Steps

### 1) Empty-Template Grid Synthesis (Immediate)

- Use verified empty-rung template captures plus refined mask policy (`+0x11/+0x17/+0x18`)
  as the active synthesis baseline.
- Keep `+0x05` and `0x0A59` donor-preserved until further isolation is complete.

### 2) Multi-Row Empty Isolation Follow-Up

- Keep companion rule active for empty multi-row synthesis:
  - row1 `+0x10` (all columns) plus row0 col31 `{+0x38,+0x3D}`.
- Move next to non-empty multi-row probes to test whether additional row2/row3 companions emerge.

### 3) Deterministic Encoder Hardening

- Keep deterministic header writer and topology writer as baseline.
- Validate against additional pasteback scenarios beyond current topology checks.

### 4) Stream Generalization (Primary)

- Expand computed placement coverage for operand-length and immediate combinations.
- Remove residual assumptions tied to old fixed-offset variant behaviors.

### 5) Control-Byte Model Expansion

- Use targeted control-byte diffing across captures to classify structural bytes that govern
  rung assembly/linkage (not just wire flags).
- Expand from second-immediate to remaining unresolved families using the same isolation method
  (profile cells, then row blocks, then pre-grid/header partitions).

### 5a) Pre-Grid Metadata Differential (New Priority)

- Reuse this method for future failing families:
  - compare generated payloads against native with row-block parity controls
  - partition `0x0000..0x0A5F` into pre-header and header slices
  - identify minimal decisive byte set and codify deterministic write rules

### 6) Capture Expansion

- Add targeted captures for unresolved stream/operand/register-bank questions.
- Promote new vetted captures into hermetic fixture set with manifest updates.

### 7) CLI / Automation Integration

- Build/extend `clicknick paste ...` flow:
  - validate/add operands in project data
  - encode deterministic payload
  - paste through Click clipboard mechanism

## References

- Header + topology validation report:
  - `scratchpad/capture-diff-results.md`
- Capture checklist:
  - `scratchpad/capture-checklist.md`
- Control-byte diff tool:
  - `devtools/control_byte_diff.py`
- Ladder module code:
  - `src/clicknick/ladder/`
