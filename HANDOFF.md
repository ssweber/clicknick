# Click PLC Clipboard Reverse Engineering — Handoff v16

Last validated: March 6, 2026

## Execution Update (March 6, 2026 — Phase 2 Companion Isolation Follow-Up Completed, Gate Still Not Met)

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

## Execution Update (March 6, 2026 — Phase 2 Companion Isolation Follow-Up Batch Prepared)

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

## Execution Update (March 6, 2026 — Phase 2 RungComment Patch Isolation Completed, Gate Not Met)

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

## Execution Update (March 6, 2026 — Phase 1 AF `NOP` vs Empty Completed)

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

## Execution Update (March 6, 2026 — Phase 2 RungComment Native Mapping Completed, Patch Isolation Ready)

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

## Execution Update (March 4, 2026 — Two-Series Hardening Pass)

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

## Execution Update (March 5, 2026 — Empty-Template Reset + Phase 5 Masking)

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

## Execution Update (March 5, 2026 — Grid Synthesis Lane + `+0x18` Isolation)

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

## Execution Update (March 5, 2026 — Multi-Row Recapture + Isolation)

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

## Execution Update (March 5, 2026 — Empty Multi-Row Row-Rule Inference, Rounds 1-10)

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

## Execution Update (March 6, 2026 — Empty Multi-Row Scale Confirmation)

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

## Execution Update (March 6, 2026 — Empty Multi-Row Cross-Donor Row9)

- Scenario `grid_synth_empty_multirow_crossdonor_row9_20260306` completed:
  - `2/2` pass:
    - `gmrsx_rows09_fromrow4_rule_minimal`
    - `gmrsx_rows09_fromrow4_rule_plus0b15`
  - verify-back length for both: `24576`.
- Result interpretation:
  - row-rule synthesis remains stable under cross-donor construction (row9 built from row4 donor).
  - restoring `+0x0B` and terminal `+0x15` did not affect outcome in this probe.

## Execution Update (March 6, 2026 — Empty Multi-Row Rule Encoding Integrated)

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

## Execution Update (March 6, 2026 — Non-Empty Multi-Row Horizontal/Vertical Isolation Setup)

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

## Execution Update (March 6, 2026 — Non-Empty Horizontal Batch Completed)

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

## Execution Update (March 6, 2026 — Non-Empty Vertical Batch Completed + Combined Conclusion)

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

## Execution Update (March 6, 2026 — 4+/Row-Combo Validation Completed)

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

## Execution Update (March 6, 2026 — Scale-to-32 Validation Completed)

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

## Execution Update (March 6, 2026 — Non-Empty Synthesis Impl + Asymmetry Confirmation)

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

## New Findings (March 3, 2026 — v2 Isolation Pass)

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
2. Per-cell structural control bytes in row0/row1 (beyond wire flags): exact role in broader
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
