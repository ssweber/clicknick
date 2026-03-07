# Phase 2 RungComment Mapping Inference (March 6, 2026)

## Execution Update (March 7, 2026 — Max1400 Structure Scope Narrowed)

- Fresh native controls added to remove shorthand/render ambiguity:
  - `grc_max1400_fresh_native_20260307`
  - `grc_no_comment_fresh_native_20260307`
- Important correction:
  - historical `grc_no_comment_native` was not a safe source-family donor for this lane.
  - even after obvious wire flags were cleared, synthetics built on that older donor could still paste as a full wire rung.

## Structure-Scope Outcomes (Completed)

- Scenario: `grid_rungcomment_max1400_structure_scope_20260307`
- Case count: `5`
- Verification totals:
  - `verified_pass`: `4`
  - `verified_fail`: `1`
  - `blocked`: `0`
- Copied-event verify-back lengths:
  - all `8192`

### Controls
- `grcmfs_nowire_fresh_control`: pass
- `grcmfs_max1400_fresh_control`: pass
- Interpretation:
  - the fresh no-comment and fresh max1400 controls are stable anchors for the no-wire `R,...,:,NOP` lane.

### Comment Window Only (`0x0294..0x08FC`)
- `grcmfs_commentwin_full`: fail
  - note: `hidden comment, R,-> full wire`
- Interpretation:
  - copying the full comment window alone is insufficient.
  - failure is not limited to delayed comment display; the rung also renders with the wrong wire family.

### Through Grid/Comment Region (`0x0294..0x1A5F`)
- `grcmfs_commentgrid`: pass
  - note: `worked. comment, no rung wire`
- Verify-back result:
  - exact byte match to fresh max1400 native verify-back (`0` differing offsets).
- Interpretation:
  - bytes through `0x1A5F` are sufficient for observed native-equivalent pasteback behavior in this tested lane.

### Pregrid + Header + Comment/Grid (`0x0000..0x1A5F`)
- `grcmfs_pregrid_header_commentgrid`: pass
  - note: `full comment, no rung wire`
- Verify-back result:
  - exact byte match to fresh max1400 native verify-back (`0` differing offsets).
- Interpretation:
  - extending the copy earlier than `0x0294` did not improve verify-back parity beyond the `0x0294..0x1A5F` scope.

## New High-Confidence Inference

- The old max1400 replay model (`len + payload + upper-tail 0x08BD..0x08FC`) was incomplete in a structural way.
- The smallest newly-proven sufficient scope in this lane is:
  - **`0x0294..0x1A5F`**
- Therefore the smallest unresolved additional region beyond the former comment-window model is:
  - **`0x08FD..0x1A5F`**
- Bytes in `0x0000..0x0293` are not required for observed pasteback parity in this round.

## Decisive Failing-vs-Passing Verify-Back Signature

- Failing `grcmfs_commentwin_full` verify-back vs passing fresh max1400 verify-back differed at exactly `63` offsets:
  - row0 cols `24..31`: `cell +0x05/+0x09`
  - row1 cols `0..22`: `cell +0x05/+0x09`
  - row1 col `23`: `cell +0x05`
- Passing `grcmfs_commentgrid` and `grcmfs_pregrid_header_commentgrid` both eliminated that signature entirely and matched the fresh native max1400 verify-back byte-for-byte.

## Follow-Up Narrowing Prepared

- Scenario: `grid_rungcomment_max1400_obs63_narrow_20260307`
- Purpose:
  - test whether the `63` observed verify-back offsets are themselves sufficient from the failing `commentwin` base, or whether they are only downstream markers of a larger required source region.

## Observed-63 Narrow Outcomes (Completed)

- Scenario: `grid_rungcomment_max1400_obs63_narrow_20260307`
- Case count: `6`
- Verification totals:
  - `verified_pass`: `1`
  - `verified_fail`: `1`
  - `blocked`: `4`

### Control Outcomes
- `grcmft_max1400_fresh_control`: pass
  - note: `full comment, no rung!`
- `grcmft_commentwin_fail_control`: fail
  - note: `hidden comment, full rung :(`

### 63-Offset Source Patches
- `grcmft_commentwin_plus_obs63`: crash
- `grcmft_commentwin_plus_row0tail63part`: crash
- `grcmft_commentwin_plus_row1head63part`: crash
- `grcmft_commentwin_plus_obs63_no_c23`: crash

### Updated Interpretation
- The `63` offsets discovered at verify-back are not themselves a replay-safe minimal source fix.
- They should be treated as an **observed failure signature**, not as the causal source subset.
- Directly applying that signature, or either of its coarse row splits, destabilizes the payload.

## New Source-Level Partition For The Real Remaining Region

- Passing `commentgrid` differs from failing `commentwin` at `1194` source offsets total.
- That source delta partitions cleanly into:
  - `120` non-grid bytes in approximately `0x0904..0x0A5C`
  - `685` row0 grid bytes
  - `389` row1 grid bytes

## Next Narrowing Round Prepared

- Scenario: `grid_rungcomment_max1400_struct_blocks_20260307`
- Goal:
  - test whether the fix lives in:
    - the `120`-byte non-grid block,
    - row0 structural block,
    - row1 structural block,
    - or the combined row0+row1 block.

## Structural Block Split Outcomes (Completed)

- Scenario: `grid_rungcomment_max1400_struct_blocks_20260307`
- Case count: `7`
- Verification totals:
  - `verified_pass`: `2`
  - `blocked`: `5`
  - `verified_fail`: `0`

### Controls
- `grcmfr_max1400_fresh_control`: pass
- `grcmfr_commentgrid_pass_control`: pass

### Structural Split Probes
- `grcmfr_commentwin_fail_control`: crash in this run
- `grcmfr_commentwin_plus_outside120`: crash
- `grcmfr_commentwin_plus_row0full`: crash
- `grcmfr_commentwin_plus_row1full`: crash
- `grcmfr_commentwin_plus_row0_row1full`: crash

### Updated Interpretation
- The source delta from the failing `commentwin` case to the passing `commentgrid` case is structurally coupled.
- None of the coarse block splits replay safely on their own.
- This means the remaining unresolved region `0x08FD..0x1A5F` should not currently be treated as a set of independent patchable chunks.

## Recommended Next Move

- Do an offline analysis pass before further operator queues.
- Focus on:
  - repeating cell-pattern families across row0/row1
  - the `120` non-grid bytes near `0x0904..0x0A5C`
  - whether max1400 behavior is:
    - row-metadata entanglement
    - or a pseudo-row / extent-like structure

## Offline Structural Analysis (March 7, 2026 - Structural Family Explained Better)

- New report:
  - `scratchpad/max1400_structural_family_analysis_20260307.md`
- Identity check on the unresolved region:
  - failing `grcmfs_commentwin_full` equals fresh no-comment native exactly over `0x08FD..0x1A5F`
  - passing `grcmfs_commentgrid` equals fresh max1400 native exactly over `0x0294..0x1A5F`
- Implication:
  - the unresolved family is exactly the native no-comment vs native max1400 delta for this lane.
  - there is no remaining ambiguity about synthetic-only drift inside `0x08FD..0x1A5F`.

### Reclassification Of The "120 Non-Grid Bytes"

- The `120` bytes are not best described as a free pre-grid block.
- Exact placement:
  - `3` bytes in the tail of header entry col `26`
  - `22` bytes each in header entries cols `27..31`
  - `7` trailer bytes after the 32-entry header table (`0x0A55..0x0A5C`)
- High-signal repeated pattern in header cols `27..31`:
  - `+0x01/+0x02/+0x03`: `00 00 00 -> 01 01 0F`
  - `+0x05..+0x09`: `00 00 00 00 00 -> FF FF FF FF 01`
  - `+0x15..+0x1D`: `01 01 0F 01 FF FF FF FF 01 -> 00 ... 00`
  - `+0x28`: `00 -> 01`
  - `+0x30`: `00 -> 01`
  - `+0x39`: monotonic `04/05/06/07/08`
  - `+0x3C`: `01 -> 00`
- Interpretation:
  - this is a header-tail / trailer descriptor family, not random pre-grid noise.

### Row0 Source Families

- `5` row0 shapes were isolated:
  - col `0`: body family plus extra clear at `+0x15`, `+0x2D = 0x09`
  - cols `1..22`: stable main body with `+0x01: 0x16 -> 0x00` and `+0x2D: 00 -> 1F`
  - col `23`: boundary variant with `+0x01: 0x17 -> 0x00`, loses `+0x2D`, gains `+0x29/+0x31`
  - cols `24..30`: tail variant with `+0x01: 0x1E -> 0x00` and `+0x2D: 00 -> 07`
  - col `31`: terminal variant with `+0x01: 0x1F -> 0x00`, `+0x2D: 00 -> 08`, and extra `+0x19/+0x1D/+0x38/+0x3D`
- Interpretation:
  - row0 is partitioned into head/body, boundary, tail, and terminal roles.
  - the differing bytes are structured extent markers, not a sparse set of independent fixes.

### Row1 Source Families

- `5` row1 shapes were isolated:
  - cols `0..22`: common continuation family with `+0x2D: 00 -> 1F`, `+0x37: 00 -> 0F`, `+0x39..+0x3C: 00 -> FF FF FF FF`, and multiple `00 -> 01` writes
  - col `23`: boundary cell with `+0x05/+0x09` and `+0x30/+0x34/+0x36 = 07/10/03`
  - cols `24/27/30`, `25/28/31`, `26/29`: repeating `3`-phase tail families built from `09/10/03` triplets at shifted offsets
- Interpretation:
  - row1 tail is a phased descriptor wave, not eight unrelated tail cells.

### Updated Working Model

- The region `0x08FD..0x1A5F` behaves like a coherent structural extent family that spans:
  - header-tail / trailer bytes
  - row0 boundary and terminal cells
  - row1 continuation and tail-phase cells
- This evidence favors:
  - **row-coupled extent metadata / pseudo-row-like structure**
- It does **not** favor:
  - a bag of replay-safe independent patch bytes
  - a purely local row0-only or row1-only metadata tweak
- This explains why:
  - observed-63 marker patches crashed
  - coarse block splits also crashed

### Recommendation After Offline Pass

- Do not resume manual splitting of `0x08FD..0x1A5F` as if the bytes are independent.

## Recommended Future Native Baseline

- Capture a row32 native no-comment / max1400 pair using the same max1400 body file.
- Rationale:
  - if the coupling is only row0/row1-local, the row32 lane may preserve the same low-row signature.
  - if Click is treating max comments like an extra extent/pseudo-row, the row32 lane should expose that scaling more clearly.

## Row32 Native Pair Outcomes (March 7, 2026 - Extent-Scaling Signal Confirmed)

- New report:
  - `scratchpad/max1400_row32_native_results_20260307.md`
- Scenario:
  - `grid_rungcomment_max1400_row32_native_20260307`
- Manifest statuses:
  - `2/2` recorded `verified_pass`
- Important caveat:
  - row rendering matched for both entries, but byte-length outcome is the decisive signal from this round.

### Length Outcomes

- `grc32_no_comment_native_20260307`
  - capture: `69632`
  - verify-back: `69632`
- `grc32_max1400_native_20260307`
  - capture: `73728`
  - verify-back: `73728`

Delta for row32 max1400 vs row32 no-comment:
- **`+4096` bytes exactly (`0x1000`)**

### Interpretation

- The extra `0x1000` page exists already in the native source capture.
- It is not a verify-only artifact.
- It persists through verify-back at the same total length.
- This strongly favors:
  - **a scaling extent / pseudo-row model**
- It strongly weakens:
  - a purely low-row-local row0/row1 entanglement model

### Additional Structural Notes

- Shared-prefix diff count (`row32 max1400` vs `row32 no-comment` over the first `69632` bytes):
  - `26013`
- Extra max1400-only tail page:
  - `4096` bytes
  - only `12` non-zero bytes
- Page-family breakdown by `0x1000` pages:
  - page `0`: comment/payload-heavy lead page
  - page `1`: lead-in structural page
  - pages `2..15`: identical repeated diff family (`1468` diffs each)
  - page `16`: terminal/tail variant
  - page `17`: sparse extra descriptor-like page

### Updated Recommendation

- Prefer offline page-family analysis before more operator queues.
- Best next native captures, if needed after that offline pass:
  - row9 no-comment / max1400
  - row17 no-comment / max1400
- Purpose:
  - determine when the extra `0x1000` page first appears.


## Scope
- Phase: `2` from `scratchpad/nop_af_rungcomment_prompt_20260306.md`
- Scenario: `grid_rungcomment_mapping_20260306`
- Goal: map `RungComment` storage bytes (flag, content, length/termination, companions).

## Setup Completed
- Added native matrix entries via workflow CLI (no manifest hand edits).
- Fixed topology/AF policy:
  - row: `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP`
- Labels:
  - `grc_no_comment_native`
  - `grc_short_ascii_native`
  - `grc_medium_ascii_native`
  - `grc_maxlen_probe_native`
  - `grc_utf8_probe_native`
  - `grc_style_plain_native`
  - `grc_style_bold_native`
  - `grc_style_italic_native`
  - `grc_style_underline_native`
  - `grc_maxlen_1396_native`
  - `grc_style_mixed_selection_native`

## Artifacts
- Case spec: `scratchpad/phase2_rungcomment_case_specs_20260306.json`
- Queue doc: `scratchpad/grid_rungcomment_mapping_verify_queue_20260306.md`

## Native Outcomes (Completed)
- Scenario `grid_rungcomment_mapping_20260306`: `11/11` verified pass.
- All events are `copied`; verify-back lengths are `8192`.
- Operator notes confirmed:
  - true max comment length is `1400` characters
  - UI supports `bold`, `italic`, and `underline` styles

## Preliminary Byte Findings (from captured set)
- Comment payload is stored as an RTF-like ANSI string.
  - observed prefix: `{\rtf1\ansi\ansicpg1252...`
  - UTF degree symbol appears as escaped RTF sequence (`\'b0`).
- Candidate length and payload fields:
  - dword at `0x0294` tracks comment payload length (+ NUL terminator).
  - payload starts at `0x0298`.
  - observed rule on captured variants: `len_dword = payload_byte_count + 1`.
- No-comment baseline has length dword `0x00000000` and no RTF payload at `0x0298`.
- Max-length correction evidence:
  - `grc_maxlen_1396_native` capture contains a `1400`-char body (label retained for continuity).
  - captured body tail includes appended `1234`, confirming the corrected bound.
- Style encoding evidence (plain vs style probes) appears in RTF token stream:
  - bold: `\b ... \b0`
  - italic: `\i ... \i0`
  - underline: `\ul ... \ulnone`
  - no separate style bytes outside comment payload are currently required by evidence.
- Mixed inline-style probe (`grc_style_mixed_selection_native`) confirms segment-level token combinations:
  - `BOLDTXT` section: `\b ... \b0`
  - `BOLDITALIC` section: `\b\i ... \b0\i0`
  - `BTU` section: `\ul\b ... \ulnone\b0`
  - implication: style is text-span markup inside one RTF payload, not row-global flags.

## Patch Isolation Outcomes (Completed)
- Scenario: `grid_rungcomment_patch_isolation_20260306`
- Case count: `12` file-backed patch entries
- Verification totals:
  - `verified_pass`: `3`
  - `verified_fail`: `2`
  - `blocked`: `7`
  - copied events: `5`
  - crash events: `7`
- Passing labels:
  - `grcp2_short_len_payload_from_no`
  - `grcp2_short_len_only_from_no`
  - `grcp2_short_len_payload_nonul_from_no`
- Failing labels:
  - `grcp2_short_reset_len0_from_short` (`copied`, note: `'Out of Memory'`)
  - `grcp2_style_bold_payload_only_from_plain` (`copied`, note reports raw RTF text shown in UI)
- Blocked labels (crash):
  - `grcp2_short_payload_only_from_no`
  - `grcp2_style_bold_len_payload_from_plain`
  - `grcp2_style_italic_len_payload_from_plain`
  - `grcp2_style_underline_len_payload_from_plain`
  - `grcp2_max1400_len_payload_from_no`
  - `grcp2_max1400_len_only_from_no`
  - `grcp2_max1400_payload_only_from_no`

## Required Classification Axes

### 1) Length Dword Only
- Mixed outcome:
  - short length-only (`118`) replay copied and re-copied.
  - max-length-only (`1516`) crashed.
  - zero-length reset from short baseline produced `verified_fail` with OOM note.
- Classification: length-only writes are not a stable global replay model.

### 2) Payload Only
- `short_payload_only` crashed.
- `bold_payload_only` copied but failed semantic expectation (raw RTF text note).
- `max1400_payload_only` crashed.
- Classification: payload-only is insufficient and frequently unstable.

### 3) Length + Payload
- short plain (`len+payload`) passed.
- short non-NUL length (`len=payload_bytes`) also passed.
- style transplants (`bold/italic/underline`) crashed.
- max1400 transplant crashed.
- Classification: `0x0294` length + immediate payload bytes are sufficient only for a narrow short/plain lane.

### 4) Terminator Coupling
- `grcp2_short_len_payload_nonul_from_no` passed with `len=117` (excluding trailing NUL), and verify-back preserved `117`.
- Classification: strict NUL-included length is not required in this short/plain probe.

### 5) Style Payload Transplants
- style `len+payload` transplant cases all crashed.
- payload-only style transplant failed with raw-markup presentation.
- Classification: style replay is not explained by isolated RTF token bytes at `0x0298` alone.

### 6) Max1400 Replay Cases
- all three max1400 replay probes (length+payload, length-only, payload-only) crashed.
- Classification: max-length replay requires additional coupling not covered by current patch window.

## Byte-Level Inference (from patch/native diffs)
- Confirmed patch generator behavior:
  - all patch payloads mutated only intended comment-window offsets near `0x0294`.
- Native capture comparison shows broader co-variation:
  - style variants (`plain` vs `bold/italic/underline`) differ from `0x0294` through approximately `0x08F6/0x08FB`.
  - no-comment vs short/max variants also differ through approximately `0x08F1/0x08FC`.
- Inference: comment replay has companions outside the minimal `length dword + immediate payload` window, especially for style and long-comment lanes.

## Phase 2 Gate Decision
- Acceptance gate: **not met**.
- Reason:
  - no replay-confirmed minimal model that covers style and max-length comment lanes.
  - crash rate is high (`7/12`) under current narrow transplant model.

## Next Isolation Target (Before Phase 3)
- Keep Phase 2 open and run a follow-up companion-byte isolation batch that:
  - starts from passing short/plain controls,
  - expands transplant/ablation window beyond payload end (`0x030E..0x08FC`),
  - separately isolates style and max1400 companion requirements.
- Follow-up batch was executed:
  - scenario: `grid_rungcomment_patch_companion_isolation_20260306`
  - case count: `16` file-backed patch entries (`grcp2c_*`)
  - outcomes:
    - `verified_pass`: `3`
    - `verified_fail`: `0`
    - `blocked`: `13` (`crash`)
    - copied events: `3`
    - crash events: `13`

## Follow-Up Companion Isolation Outcomes

### Short Lane (`no_comment` base, short donor)
- `grcp2c_short_lpp_control_from_no`: pass (`8192`)
- `grcp2c_short_full_0294_08fc_from_no`: pass (`8192`)
- `grcp2c_short_tail_only_030e_08fc_from_no`: crash
- Interpretation:
  - short/plain replay remains stable with coherent len+payload.
  - post-payload tail bytes by themselves are destabilizing.

### Style Lane (`style_plain` base, bold/italic/underline donors)
- All style probes crashed:
  - bold control (`len+payload` only)
  - bold full-window (`0x0294..0x08FC`)
  - all bold split-tail variants
  - italic full-window
  - underline full-window
- Interpretation:
  - required style companions are not resolved by transplants limited to `0x0294..0x08FC`.
  - additional required bytes likely exist outside this window and/or require lane-specific normalization.

### Max1400 Lane (`no_comment` base, max donor)
- `grcp2c_max_lpp_control_from_no`: crash
- `grcp2c_max_full_0294_08fc_from_no`: crash
- `grcp2c_max_lpp_plus_tail_0884_08bc_from_no`: crash
- `grcp2c_max_lpp_plus_tail_08bd_08fc_from_no`: pass (`8192`) with UI note:
  - comment content transferred but was not shown until opening `Edit Comment` and confirming.
- `grcp2c_max_tail_only_0884_08fc_from_no`: crash
- Interpretation:
  - the upper tail chunk (`0x08BD..0x08FC`) is a high-signal companion candidate for max-length replay.
  - lower tail chunk (`0x0884..0x08BC`) is insufficient and may be destabilizing in this lane.

## Updated Phase 2 Gate Decision
- Acceptance gate: **not met**.
- Why still not met:
  - style replay remains unresolved (`0` pass across all style follow-up probes).
  - max1400 replay has only a partial/non-clean pass signature (delayed UI render behavior).

## Closure Batch Outcomes (March 7, 2026)
- Scenario: `grid_rungcomment_closure_20260307`
- Case count: `11`
- Verification totals:
  - `verified_pass`: `2`
  - `verified_fail`: `4`
  - `blocked`: `3`
  - intentionally skipped / left `unverified`: `2`
- Copied-event verify-back lengths:
  - short plain control: `8192`
  - all copied max1400 cases: `8192`

### Short Plain Control
- `grcc_short_plain_control_from_no`: pass (`8192`)
- Interpretation:
  - the narrow short/plain lane remains stable.

### Hand-Crafted Minimal Styled Probe
- `grcc_style_min_bold_handcrafted`: crash
- `grcc_style_min_italic_handcrafted`: intentionally skipped by policy after bold crash
- `grcc_style_min_underline_handcrafted`: intentionally skipped by policy after bold crash
- Interpretation:
  - the bounded handcrafted-style test failed at the first decision gate.
  - styled comments are unsupported under the current replay model.
  - broad styled transplant exploration should remain closed unless a new model is established.

### Max1400 Native vs Synthetic A/B
- `grcc_max1400_native_control`: pass (`8192`)
  - operator outcome: comment displayed immediately after paste.
- `grcc_max1400_synth_compare`: fail (`8192`)
  - note: full comment remained hidden and copied back in the hidden state.
- Interpretation:
  - native and synthetic do not have the same paste-time behavior in the same session.
  - the current synthetic max1400 path does not achieve native immediate-render parity.

### Save/Reopen Check
- `grcc_max1400_synth_reopen`: fail (`8192`)
  - note: after reopen, the full comment showed; native paste showed right away.
- Interpretation:
  - the best synthetic max1400 payload persists semantically and renders normally after reload.
  - this is best classified as a paste-time UI refresh caveat, not a total encoding failure.

### Max1400 Narrowing Results
- `grcc_max1400_synth_diff22`: fail (`8192`)
  - note: hidden full comment
- `grcc_max1400_synth_coreclusters`: crash
- `grcc_max1400_synth_coreclusters_no_08fc`: crash
- `grcc_max1400_synth_singletons`: fail (`8192`)
  - note: still hidden comment
- Interpretation:
  - copying only the `22` changed offsets inside `0x08BD..0x08FC` preserves the same hidden-comment behavior as the prior best synthetic case.
  - the aggressive cluster reductions crash, while the singleton subset is insufficient.
  - narrowing did not produce a clean immediate-display synthetic path.

## Final Comment Support Classification

### Proven Comment Model
- `0x0294` = length dword
- `0x0298` = payload start
- `len = payload_bytes + 1`
- max comment length = `1400` characters
- payload encoding = RTF-like ANSI text

### 1) Plain Comments Up To 1400 Chars
- Classification: **partially working with caveat**
- Evidence:
  - short plain comment replay is clean with `len + payload`.
  - native `1400`-char comment pastes and displays immediately.
  - current best synthetic `1400`-char path copies back at `8192`, preserves `len=1516`, and displays correctly after reopen, but remains hidden at paste time in the direct A/B check.
- Best current synthetic max1400 construction:
  - `len + payload` plus donor companion region `0x08BD..0x08FC`
- Imperfection classification:
  - best described as a **paste-time UI refresh quirk with unresolved native-parity immediate display**.
  - practical meaning: the bytes are good enough to persist and render after reopen, but the synthetic path still misses clean paste-time display parity with native.

### 2) Styled Comments
- Classification: **hand-crafted minimal styled does not work**
- Evidence:
  - native captures confirm RTF style tokens (`\b`, `\i`, `\ul`) inside the payload.
  - style transplants crashed in earlier batches.
  - the bounded handcrafted minimal bold probe also crashed.
- Supported forms under the current model:
  - none proven.

### 3) Paste-Time Rendering Behavior
- Classification: **requires reopen to display**
- Important note:
  - an earlier batch also showed that opening and closing `Edit Comment` can reveal the transferred `1400`-char synthetic comment.
  - native max1400 does not require this refresh step.

## Updated Phase 2 Gate Decision
- Acceptance gate: **not met**.
- Why:
  - styled comments are unsupported under the current model.
  - plain comments are not yet cleanly reproducible at `1400` characters with native-equivalent immediate display.

## Current Status
- `phase2_rungcomment_closure_completed_gate_not_met`

## Offline Follow-Up (March 7, 2026 - Empty-Row Carrier Hypothesis Weakened)

- New report:
  - `scratchpad/max1400_row32_fullwire_row0nop_native_results_20260307.md`
- New native discriminator scenario:
  - `grid_rungcomment_max1400_row32_fullwire_row0nop_native_20260307`
- Manifest statuses:
  - `2/2` `verified_pass`

Length outcomes:
- `grc32fwnop_no_comment_native_20260307`
  - capture: `69632`
  - verify-back: `69632`
- `grc32fwnop_max1400_native_20260307`
  - capture: `73728`
  - verify-back: `73728`

Key implication:
- row32 max1400 still allocates **exactly one extra `0x1000` page** even when:
  - all visible rows are full horizontal wire rows
  - row `0` is explicitly distinguished with `NOP`

This materially weakens:
- the idea that the extra max1400 structure only works because empty rows exist as hidden carriers

This materially strengthens:
- a comment-owned extent/page-family model that coexists with normal rung topology

Additional note:
- the extra page in this full-wire row0-NOP lane is not sparse
- it contains UTF-16LE font/display strings such as:
  - `Segoe UI Variable Display Semilight`
  - `Segoe UI Variable Display Semibold`
  - `SimSun`
  - `NSimSun`
  - `SimSun-ExtB`
- these strings are absent from the comment's ANSI RTF payload, which still names only `Arial`
- this points to a renderer/layout companion page, not direct text spillover

Further offline decode of that page:
- helper added:
  - `devtools/analyze_max1400_page17.py`
- page `17` is now better described as a wrapper/slot table, not just "a page with some font strings"
- the `74 76 00 08` top-level records split into:
  - `3` Segoe leaf wrappers of `0x01EC` bytes each
  - `1` CJK container wrapper of `0x09D8` bytes
- the CJK wrapper contains `5` nested fallback-face slots on a stable `0x1E4` stride:
  - `SimSun`
  - `@SimSun`
  - `NSimSun`
  - `@NSimSun`
  - `SimSun-ExtB`
- each nested slot repeats the same skeleton:
  - family name
  - duplicate family name
  - `Regular`
  - inner descriptor header `64 76 00 08` at slot `+0x144`
- the wrapper fields `0x012C / 0x015E / 0x0190 / 0x0258` are now best interpreted as weight-like or fallback-class codes (`300 / 350 / 400 / 600`), not lengths
- this materially strengthens the "renderer/fallback metadata" model for page `17`

Additional offline refinement for the repeated row32 body pages:
- pages `2..16` are now better described as **paired-row descriptor pages**
- reason:
  - each page is `0x1000`
  - the structure still uses the ordinary `0x40` cell stride
  - so each page holds `64` cell-shaped slots, naturally resolving as two `32`-column row bands
- across pages `2..15`, the only page-to-page varying bytes are slot `+0x09` and slot `+0x11`
- those two fields advance monotonically by page, which fits extent ordinals or row-band indices much better than visible wire data
- in the full-wire row0-NOP lane:
  - `+0x09` keeps the same ordinal ladder
  - `+0x11` is shifted upward by `0x21`
- best current wording is now:
  - hidden paged extent that reuses cell-shaped descriptor slots
- this is more precise than:
  - empty pseudo rung with no wire markers

Additional empty-row page-17 refinement:
- empty-row row32 native page `17` stays extremely sparse
- but empty-row verify-back page `17` grows to `683` non-zero bytes without becoming the rich font/fallback table seen in the full-wire row0-NOP lane
- verify-back page `17` still uses the same `0x40` slot lattice (`64` slots)
- after slot `0`'s preserved `0x20` terminal anchor, the page is dominated by a repeating `3`-phase wave built from the same compact descriptor vocabulary:
  - `09/10/03`
  - `07/10/03`
  - nearby terminal variants like `08` and `0D`
- best current interpretation:
  - Click synthesizes a reduced terminal descriptor page on copy-back in the empty-row lane
  - rather than preserving the sparse native page literally
  - and without promoting it to the rich renderer/fallback form used in the full-wire lane

Updated offline interpretation:
- the row32 empty-row pair and the row32 full-wire row0-NOP pair now point to the same core conclusion:
  - the extra page is a real comment-owned scaling structure
  - not merely an empty-row-local carrier trick

Recommended next native matrix, if more capture work is needed:
- row9 no-comment / max1400
- row17 no-comment / max1400
