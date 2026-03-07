# Phase 2 RungComment Mapping Inference (March 6, 2026)

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
