# Row Rule Inference: Empty Multi-Row (March 5, 2026)

## Scope
- Goal: infer deterministic per-row bytes for EMPTY multi-row rungs.
- Native evidence used:
  - `grid_empty_row1_single_native`
  - `grid_empty_rows1_2_recapture_native`
  - `grid_empty_rows1_2_3_recapture_native`
  - `gnenp_rows04_native`
  - `gnenp_rows09_native`
  - `gnenp_rows17_native`
  - `gnenp_rows32_native`
- De-noise policy applied:
  - masked header entry offsets `+0x11`, `+0x17`, `+0x18` across all 32 header entries.
  - did not assume noise for header `+0x05` or trailer `0x0A59`.

## Proven Structural Rules

### Header row-count word (entry 0 only)
- `header[entry0 +0x00:+0x01]` is a 16-bit little-endian word:
  - `row_word = (logical_rows + 1) * 0x20`.
- Observed exact matches:
  - 1 -> `0x0040`
  - 2 -> `0x0060`
  - 3 -> `0x0080`
  - 4 -> `0x00A0`
  - 9 -> `0x0140`
  - 17 -> `0x0240`
  - 32 -> `0x0420`

### Payload length rule (native empty lane)
- `len = 0x1000 * (ceil(rows / 2) + 1)`
- Matches all native points:
  - rows 1/2 -> `8192`
  - rows 3/4 -> `12288`
  - rows 9 -> `24576`
  - rows 17 -> `40960`
  - rows 32 -> `69632`

### Cell-byte row rule (active rows only)
- For row index `r` (0-based), column `c` (0..31), terminal row `term = (r == rows-1)`:
  - `+0x01 = c` (with `c0 -> 0x00`, `c1..c31 -> 0x01..0x1F`)
  - `+0x05 = r + 1`
  - `+0x09 = 0x01`
  - `+0x0A = 0x01`
  - `+0x0C = 0x01`
  - `+0x0D = 0xFF`
  - `+0x0E = 0xFF`
  - `+0x0F = 0xFF`
  - `+0x10 = 0xFF`
  - `+0x11 = 0x01`
  - `+0x38 = 0x01` except terminal row col31 -> `0x00`
  - `+0x3D = r + 1` for cols 0..30; col31 is `r + 2` on non-terminal rows, `0x00` on terminal row

Validation:
- Checked the 12 offsets above over all active cells in all 7 native captures.
- Exact result: `26112/26112` checks matched (0 mismatches).

## Offset Rule Table

| Offset | Rule / Formula | Confidence | Evidence Labels |
|---|---|---|---|
| `header entry0 +0x00/+0x01` | `(rows + 1) * 0x20` little-endian | High | row1, row2, row3, gnenp4, gnenp9, gnenp17, gnenp32 |
| `cell +0x01` | column index (`0..31`) | High | row2, row3, gnenp4, gnenp9, gnenp17, gnenp32 |
| `cell +0x05` | `row_index + 1` (within active rows) | High (native), Medium (global context coupling unknown) | row1, row2, row3, gnenp4, gnenp9, gnenp17, gnenp32 |
| `cell +0x09` | `0x01` | High | all 7 native labels |
| `cell +0x0A` | `0x01` | High | all 7 native labels |
| `cell +0x0B` | capture-family constant (observed `0x0C`, `0x42`, `0x40`) | Medium-Low | row1 (`0x0C`), row2/row3 (`0x42`), gnenp4/9/17/32 (`0x40`) |
| `cell +0x0C` | `0x01` | High | all 7 native labels |
| `cell +0x0D..+0x10` | `0xFF` | High | all 7 native labels |
| `cell +0x11` | `0x01` | High | all 7 native labels |
| `cell +0x15` | single marker at col0; location is family-dependent (row0 in old family, terminal row in gnenp family) | Medium-Low | row1/row2/row3 vs gnenp4/9/17/32 |
| `cell +0x38` | `0x01` except terminal row col31 -> `0x00` | High | row2, row3, gnenp4, gnenp9, gnenp17, gnenp32 |
| `cell +0x3D` | row-link counter: cols0..30=`r+1`; col31=`r+2` except terminal col31=`0` | High | row2, row3, gnenp4, gnenp9, gnenp17, gnenp32 |
| `header +0x05` | required `0x00` in this empty multi-row family; nonzero (`0x01`,`0x02`) fragments verify-back | High (family-scoped) | all 7 native labels + iso2 fails |
| `0x0A59` | required `0x00` in this empty multi-row family; nonzero (`0x01`) fragments verify-back | High (family-scoped) | all 7 native labels + iso2 fails |

## Verify-Back Outcomes from Scale Attempts (`gtes*` Family)
- `gtes_rows*`:
  - no-companion variants came back as 1 row (`0x0040`).
  - with-companion variants came back as 2 rows (`0x0060`).
- `gtes2*`, `gtes3*`, `gtes4*`:
  - all came back as 2 rows (`0x0060`) despite 4/9/17/32 intent.
- Interpretation:
  - prior synthesis captured only the early row-link behavior (up to 2 rows).
  - native `gnenp*` confirms the required progressive col31 terminal behavior for all rows.

## Proven vs Unknown

Proven:
- 16-bit header row-count word formula.
- Page-aligned payload length rule for native empty captures.
- Deterministic row-index and terminal-row formulas for key cell offsets (`+0x01,+0x05,+0x09,+0x0A,+0x0C,+0x0D..+0x11,+0x38,+0x3D`).

Still unknown:
- Selection rule for family byte `cell +0x0B`.
- Selection/anchor rule for marker byte `cell +0x15`.
- Structural role of header `+0x05` and trailer `0x0A59` in this empty multi-row lane (all-zero natively; non-zero appears in some failing verify-backs).

## Isolation Batch Prepared
- Scenario: `grid_empty_multirow_rowrule_iso_20260305`
- File-backed patch labels:
  - `rriso4_control_native4`
  - `rriso4_patch_cell0b_42_only`
  - `rriso4_patch_cell15_row0_only`
  - `rriso4_patch_cell0b42_cell15row0`
  - `rriso4_patch_header05_t59_set01`
  - `rriso4_patch_cell05_plus3`

## Isolation Round 1 Outcomes (Completed)

Scenario run: `grid_empty_multirow_rowrule_iso_20260305` (`6` cases)

- `verified_pass`:
  - `rriso4_control_native4`
  - `rriso4_patch_cell0b_42_only`
  - `rriso4_patch_cell15_row0_only`
  - `rriso4_patch_cell0b42_cell15row0`
  - `rriso4_patch_cell05_plus3`
- `verified_fail`:
  - `rriso4_patch_header05_t59_set01`

Observed implications:
- `cell +0x0B` is not a hard structural gate for 4-row empty assembly in this lane.
  - Click normalized patched `+0x0B=0x42` back to `0x40` on verify-back while preserving 4-row output.
- `cell +0x15` anchor position (row0 vs terminal row) is not a hard gate for this lane.
- Absolute `cell +0x05` values are not fixed; preserving row-delta shape is sufficient.
  - `+3` shifted source values verified and were normalized back to canonical row+1 values.
- Header `+0x05` + trailer `0x0A59` remains structural/context-coupled:
  - forcing both to `0x01` caused fail with fragmentation (`verify_back len=16384`, header row word `0x00E0`, observed NOP row insertion).

Updated confidence after round 1:
- `cell +0x0B`: Medium-Low -> Low structural significance (for empty 4-row lane).
- `cell +0x15`: Medium-Low -> Low structural significance (for empty 4-row lane).
- `header +0x05` / `0x0A59`: Low -> Medium-High structural/context significance.

## Isolation Round 2 Outcomes (Completed)

Scenario run: `grid_empty_multirow_rowrule_iso2_20260305` (`5` cases)

- `verified_pass`:
  - `rriso4b_control_native4`
- `verified_fail`:
  - `rriso4b_patch_header05_only_01`
  - `rriso4b_patch_t59_only_01`
  - `rriso4b_patch_header05_t59_01`
  - `rriso4b_patch_header05_t59_02`

Observed implications:
- `header +0x05` is a hard structural/context gate in this lane.
  - `header +0x05 = 0x01` alone causes fragmentation (`len=16384`, row word `0x00E0`, NOP insertion).
- `0x0A59` is also a hard structural/context gate in this lane.
  - `0x0A59 = 0x01` alone causes stronger fragmentation (`len=20480`, row word `0x0120`, multiple NOP rows).
- Combined nonzero (`0x01` or `0x02`) also fails; Click normalizes copy-back header `+0x05` and `0x0A59` to `0x00` after fragmentation.

Updated lane rule for empty multi-row (`h17=0x40/h18=0x01` family):
- Keep `header +0x05 = 0x00`.
- Keep `0x0A59 = 0x00`.
- Treat both as structural/context-coupled required zeros for this family.

Open item after round 2:
- Determine whether the required-zero condition is universal or family-specific outside this empty multi-row lane (do not generalize yet).

## Isolation Round 3 Outcomes (Completed, 2-Row `h17=0x42` Family)

Scenario run: `grid_empty_multirow_rowrule_iso3_20260305` (`5` cases)

- `verified_pass`:
  - `rriso42_control_native2`
- `verified_fail`:
  - `rriso42_patch_header05_only_01` (`len=8192`, NOP-leading fail)
  - `rriso42_patch_t59_only_01` (`len=16384`, stronger fragmentation)
  - `rriso42_patch_header05_t59_01` (`len=4096`, severe collapse)
  - `rriso42_patch_header05_t59_02` (`len=12288`, row inflation)

Implication:
- Independent failure of `header +0x05` and `0x0A59` reproduces in both tested empty families (`h17=0x40` and `h17=0x42`).
- However, this still does not prove universal prohibition of nonzero values, because prior pass cases show nonzero values can appear in verify-back outputs under different seed tuples/families.

Current working interpretation:
- In empty native-source families, direct perturbation of `header +0x05` or `0x0A59` without compatible full-seed context breaks assembly.
- Next test must isolate tuple coherence (not single-byte values).

## Isolation Round 4 Prepared (Tuple Coherence)

- Scenario: `grid_empty_multirow_rowrule_iso4_20260305`
- Purpose: test whether coherent seed tuples can allow nonzero `h05/t59` on 2-row empty base.
- Cases:
  - `rriso42c_control_native2`
  - `rriso42c_seed_0103_84_01_t59_01`
  - `rriso42c_seed_0307_35_01_t59_03`
  - `rriso42c_seed_0103_42_01_t59_01`
  - `rriso42c_seed_0100_84_01_t59_01`
  - `rriso42c_seed_0103_84_01_t59_00`

## Isolation Round 4 Outcomes (Completed, Tuple Coherence)

Scenario run: `grid_empty_multirow_rowrule_iso4_20260305` (`6` cases)

- `verified_pass`:
  - `rriso42c_control_native2`
- `verified_fail`:
  - `rriso42c_seed_0103_84_01_t59_01`
  - `rriso42c_seed_0307_35_01_t59_03`
  - `rriso42c_seed_0103_42_01_t59_01`
  - `rriso42c_seed_0100_84_01_t59_01`
  - `rriso42c_seed_0103_84_01_t59_00`

Observed implications:
- Coherent tuple injection alone is still insufficient on the 2-row empty base.
- All nonzero seed tuples tested collapsed to fail signatures (mostly `len=12288`, row word `0x00A0`, NOP-leading behavior).
- Therefore coupling extends beyond tuple bytes into other structural regions.

## Isolation Round 5 Prepared (Region Coupling)

- Scenario: `grid_empty_multirow_rowrule_iso5_20260305`
- Queue doc: `scratchpad/grid_empty_multirow_rowrule_iso5_verify_queue_20260305.md`
- Purpose: test if nonzero-seed behavior requires donor header-region and/or row-region transplant.
- Cases:
  - `rriso42d_control_native2`
  - `rriso42d_patch_header_region_only`
  - `rriso42d_patch_preheader_header_only`
  - `rriso42d_patch_tuple_plus_row05_0b_39`
  - `rriso42d_patch_tuple_plus_full_row01`
  - `rriso42d_donor_direct`

## Isolation Round 5 Outcomes (Completed, Region Coupling)

Scenario run: `grid_empty_multirow_rowrule_iso5_20260305` (`6` cases)

- `verified_pass`:
  - `rriso42d_control_native2`
  - `rriso42d_donor_direct`
  - `rriso42d_patch_tuple_plus_row05_0b_39`
  - `rriso42d_patch_tuple_plus_full_row01`
- `verified_fail`:
  - `rriso42d_patch_header_region_only`
  - `rriso42d_patch_preheader_header_only`

Observed implications:
- Header-region tuple transplant alone is insufficient (still fragments).
- Adding row0/row1 coupled offsets (`+0x05`, `+0x0B`, `+0x39`) with the tuple restores 2-row pass.
- Full row0/row1 transplant is not required; minimal offset-set transplant already passes.
- This supports a coupled seed+row model rather than a header-only seed model.

## Isolation Round 6 Prepared (Offset Minimization)

- Scenario: `grid_empty_multirow_rowrule_iso6_20260305`
- Queue doc: `scratchpad/grid_empty_multirow_rowrule_iso6_verify_queue_20260305.md`
- Purpose: identify the minimal required subset of row offsets among `+0x05`, `+0x0B`, `+0x39` under fixed tuple seed.
- Cases:
  - `rriso42e_control_native2`
  - `rriso42e_tuple_only`
  - `rriso42e_tuple_plus_row_05`
  - `rriso42e_tuple_plus_row_0b`
  - `rriso42e_tuple_plus_row_39`
  - `rriso42e_tuple_plus_row_05_0b`
  - `rriso42e_tuple_plus_row_05_39`
  - `rriso42e_tuple_plus_row_0b_39`
  - `rriso42e_tuple_plus_row_05_0b_39`

## Isolation Round 6 Outcomes (Completed, Offset Minimization)

Scenario run: `grid_empty_multirow_rowrule_iso6_20260305` (`9` cases)

- `verified_pass`:
  - `rriso42e_control_native2`
  - `rriso42e_tuple_plus_row_39`
  - `rriso42e_tuple_plus_row_05_39`
  - `rriso42e_tuple_plus_row_0b_39`
  - `rriso42e_tuple_plus_row_05_0b_39`
- `verified_fail`:
  - `rriso42e_tuple_only`
  - `rriso42e_tuple_plus_row_05`
  - `rriso42e_tuple_plus_row_0b`
  - `rriso42e_tuple_plus_row_05_0b`

Observed implications:
- Under tuple-seeded header context, `cell +0x39` is sufficient to restore 2-row empty pass.
- `cell +0x05` and `cell +0x0B` are not independently sufficient and not required when `+0x39` is present.
- Current minimal coupling set (2-row lane) is:
  - seed tuple (`header +0x05/+0x11/+0x17/+0x18`, trailer `0x0A59`)
  - row-coupled `cell +0x39` pattern (copied from donor across row0/row1)

Current open question:
- Is `+0x39` required only with nonzero seed tuples, or also when seed tuple is zero/native?

## Isolation Round 7 Prepared (`+0x39` Dependency Shape)

- Scenario: `grid_empty_multirow_rowrule_iso7_20260305`
- Queue doc: `scratchpad/grid_empty_multirow_rowrule_iso7_verify_queue_20260305.md`
- Purpose:
  - test `+0x39` without tuple seed,
  - split row0-only vs row1-only `+0x39`,
  - test terminal col31 behavior by forcing row1 col31 `+0x39=1`.

## Isolation Round 7 Outcomes (Completed, `+0x39` Dependency Shape)

Scenario run: `grid_empty_multirow_rowrule_iso7_20260305` (`7` cases)

- `verified_pass`:
  - `rriso42f_control_native2`
  - `rriso42f_tuple_row39_canonical`
  - `rriso42f_tuple_row39_allones`
- `verified_fail`:
  - `rriso42f_row39_only_no_tuple`
  - `rriso42f_tuple_only`
  - `rriso42f_tuple_row39_row0_only`
  - `rriso42f_tuple_row39_row1_only`

Observed implications:
- `+0x39` alone is insufficient without tuple seed.
- Tuple seed alone is insufficient without `+0x39`.
- With tuple seed present, `+0x39` must be applied on both row0 and row1.
- Row1 col31-specific value at `+0x39` is not a strict gate:
  - canonical (`row1 col31 = 0`) and all-ones (`row1 col31 = 1`) both pass.

Current 2-row working rule (nonzero-seed lane):
- Need coherent seed tuple (`header +0x05/+0x11/+0x17/+0x18`, trailer `0x0A59`).
- Need row-coupled `cell +0x39` enabled on both row0 and row1.

Open item after round 7:
- Determine sparsity threshold of `+0x39` on each row (all columns vs subset).

## Isolation Round 8 Prepared (`+0x39` Sparsity Threshold)

- Scenario: `grid_empty_multirow_rowrule_iso8_20260305`
- Queue doc: `scratchpad/grid_empty_multirow_rowrule_iso8_verify_queue_20260305.md`
- Purpose:
  - test sparse `+0x39` coverage on row0 and row1 under tuple seed,
  - estimate minimum row coverage needed to preserve 2-row empty pass.

## Isolation Round 8 Outcomes (Completed, `+0x39` Sparsity Threshold)

Scenario run: `grid_empty_multirow_rowrule_iso8_20260305` (`7` cases)

- `verified_pass`:
  - `rriso42g_control_native2`
  - `rriso42g_tuple_row39_row0full_row1c0_30`
- `verified_fail`:
  - `rriso42g_tuple_only`
  - `rriso42g_tuple_row39_sparse_c0_c0`
  - `rriso42g_tuple_row39_row0full_row1c0`
  - `rriso42g_tuple_row39_row0c0_row1full`
  - `rriso42g_tuple_row39_row0full_row1c0_15`

Observed implications:
- With tuple seed present, sparse `+0x39` is insufficient.
- Row0 requires broad coverage (row0-only sparse failed even when row1 was full).
- Row1 also requires broad coverage:
  - row1 `0..15` failed,
  - row1 `0..30` passed.
- So current passing envelope in 2-row lane is:
  - row0 `+0x39` across all columns (or near-all; col31 not yet isolated),
  - row1 `+0x39` across at least cols `0..30` (col31 optional from prior round).

Open item after round 8:
- Determine whether row0 col31 is required and whether row1 col30 is required.

## Isolation Round 9 Outcomes (Completed, Boundary Columns)

Scenario run: `grid_empty_multirow_rowrule_iso9_20260305` (`7` cases)

- `verified_pass`:
  - `rriso42h_control_native2`
  - `rriso42h_tuple_row39_row0full_row1c0_30` (pass anchor)
- `verified_fail`:
  - `rriso42h_tuple_only`
  - `rriso42h_tuple_row39_row0full_row1c0_29`
  - `rriso42h_tuple_row39_row0c0_30_row1c0_30`
  - `rriso42h_tuple_row39_row0c0_30_row1full`
  - `rriso42h_tuple_row39_row0full_row1c1_31`

Boundary conclusions:
- Row0 col31 at `+0x39` is required (removing it fails).
- Row1 col0 at `+0x39` is required (using cols `1..31` fails).
- Row1 col30 at `+0x39` is required (using cols `0..29` fails).
- Row1 col31 at `+0x39` remains optional (from prior round, both `0` and `1` passed).

Current best tested 2-row nonzero-seed rule:
- Apply coherent nonzero tuple (`header +0x05/+0x11/+0x17/+0x18`, trailer `0x0A59`).
- Apply `cell +0x39 = 1` on:
  - row0 cols `0..31`
  - row1 cols `0..30`
- row1 col31 may be `0` or `1`.

Residual risk:
- Interior row1 column necessity (for example dropping only col15) is not yet directly ablated in a single-case probe.

## Isolation Round 10 Prepared (Interior Column Ablation)

- Scenario: `grid_empty_multirow_rowrule_iso10_20260305`
- Queue doc: `scratchpad/grid_empty_multirow_rowrule_iso10_verify_queue_20260305.md`
- Purpose:
  - test whether single interior row1 columns at `+0x39` are individually required under the otherwise passing anchor pattern.
- Cases:
  - `rriso42i_control_native2`
  - `rriso42i_anchor_row1_c0_30`
  - `rriso42i_anchor_drop_row1_c07`
  - `rriso42i_anchor_drop_row1_c15`
  - `rriso42i_anchor_drop_row1_c23`

## Isolation Round 10 Outcomes (Completed, Interior Column Ablation)

Scenario run: `grid_empty_multirow_rowrule_iso10_20260305` (`5` cases)

- `verified_pass`:
  - `rriso42i_control_native2`
  - `rriso42i_anchor_row1_c0_30`
- `verified_fail`:
  - `rriso42i_anchor_drop_row1_c07`
  - `rriso42i_anchor_drop_row1_c15`
  - `rriso42i_anchor_drop_row1_c23`

Final 2-row coupling conclusion (tested):
- Under nonzero tuple seed, row-coupled `cell +0x39` requirements are:
  - row0 cols `0..31` must be `1`
  - row1 cols `0..30` must be `1`
  - row1 col31 is optional (`0` or `1` both pass)
- Any tested omission in row1 cols `0..30` failed.

Status:
- 2-row nonzero-seed coupling rule is now high-confidence for empty lane.
- Remaining work is extension/generalization to `rows > 2` under seeded conditions.

## Scale Confirmation Batch (March 6, 2026)

- Scenario: `grid_synth_empty_multirow_rule_minimal_20260306`
- Goal:
  - test whether the proven empty multi-row rule set generalizes to larger row counts
    when low-confidence bytes are omitted (`cell +0x0B`, `cell +0x15`).
- Cases:
  - `gmrs_rows04_rule_minimal`
  - `gmrs_rows09_rule_minimal`
  - `gmrs_rows17_rule_minimal`
  - `gmrs_rows32_rule_minimal`

Outcome:
- `4/4` `verified_pass` (`copied` in all cases).
- Verify-back lengths matched expected page scaling:
  - row4: `12288`
  - row9: `24576`
  - row17: `40960`
  - row32: `69632`

Implication:
- For empty multi-row lane, low-confidence bytes `+0x0B` and `+0x15` are not required to
  preserve multi-row assembly at tested scales (`4/9/17/32`) when the proven rule offsets are present.

Next batch prepared:
- Scenario: `grid_synth_empty_multirow_crossdonor_row9_20260306`
- Queue doc: `scratchpad/grid_synth_empty_multirow_crossdonor_row9_verify_queue_20260306.md`
- Purpose: isolate cross-donor behavior by building row9 from row4 donor template, with and without
  restoring `+0x0B/+0x15`.

## Cross-Donor Row9 Follow-Up (March 6, 2026)

- Scenario: `grid_synth_empty_multirow_crossdonor_row9_20260306`
- Cases:
  - `gmrsx_rows09_fromrow4_rule_minimal`
  - `gmrsx_rows09_fromrow4_rule_plus0b15`

Outcome:
- `2/2` `verified_pass` (`copied` in both cases), verify-back len `24576` in both.

Implication:
- The empty multi-row row-rule remains stable under cross-donor construction (row9 from row4 base).
- Restoring low-confidence bytes (`+0x0B`, terminal `+0x15`) does not change outcome in this probe.

## Integration Status (March 6, 2026)

- Rule encoding integrated into production module:
  - `src/clicknick/ladder/empty_multirow.py`
  - public API: `synthesize_empty_multirow(...)`
- Header row-count decode now uses 16-bit row word in topology helpers:
  - `src/clicknick/ladder/topology.py`
- Fixture promotion completed for passing synthesis probes:
  - `gmrs_rows04_rule_minimal`
  - `gmrs_rows09_rule_minimal`
  - `gmrs_rows17_rule_minimal`
  - `gmrs_rows32_rule_minimal`
  - `gmrsx_rows09_fromrow4_rule_minimal`
  - `gmrsx_rows09_fromrow4_rule_plus0b15`
