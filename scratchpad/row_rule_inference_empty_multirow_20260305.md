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
