# Capture Diff Results (Header Region)

Scope: captures `#1` through `#29` in `scratchpad/captures`, using header entries at:

- base: `0x0254`
- entry size: `0x40` bytes
- entries: `32` (`A..AF`)

## Normalization

Two per-entry bytes are volatile across captures and changed in every column for every pairwise diff:

- entry offset `+0x05`
- entry offset `+0x11`

All structural comparisons below mask those two bytes.

## Findings

1. Header entry `N` corresponds to column `N`:
- Each entry contains `N` as a little-endian dword at entry offsets `+0x0C..+0x0F`.
- Example: entry 30 stores `1E 00 00 00`, entry 31 stores `1F 00 00 00`.

2. Wire vs instruction does not change these header entries:
- `wire_a` vs `no_a_only`: identical after masking volatile bytes.

3. Instruction type (NO vs NC) does not change these header entries:
- `no_a_only` vs `nc_a_only`: identical after masking volatile bytes.

4. Output type (Out vs Latch vs Reset) does not change AF header entry:
- `out_af_only` vs `latch_af_only` vs `reset_af_only`: identical after masking volatile bytes.

5. Per-row signal found is global, not per-column/per-entry:
- Only one stable structural byte changed in header for row count:
  - `0x0254` (entry 0, byte 0)
  - `0x40` for 1-row captures
  - `0x60` for 2-row captures
  - `0x80` for 3-row capture (`vert_b_3rows`)

6. Header compositionality:
- For all 1-row captures, normalized header is identical (empty, wire-only, contact-only, output-only, and full simple rungs).
- This header region does not appear to encode rung topology/details beyond column index constants plus row-count class.

## Checklist Status (What We’re Trying to Answer)

- [x] Does header entry N correspond to column N?
- [x] Does wire vs instruction produce different header entries? (No in this region)
- [x] Does instruction type (NO/NC/Rise) change the header? (NO/NC: no observed change in this region)
- [x] Does output type (Out/Latch/Reset) change AF's header entry? (No in this region)
- [x] What's the per-row encoding within each 64-byte entry? (Cell `+0x21` is vertical-down-to-next-row; row blocks stride by `0x800`)
- [x] Is the header compositional (sum of parts = whole)? (Trivially yes in this region; entries are invariant for 1-row captures)

## Grid Region Findings (Topology Signals)

Row starts observed:

- row 0: `0x0A60`
- row 1: `0x1260`
- row 2 (present in 3-row capture): `0x1A60`
- stride: `0x800` bytes per row block (`32 * 0x40`)

Within a row cell (64 bytes), these offsets carry wire topology:

- `+0x19` (byte 25): horizontal flag bit
- `+0x1D` (byte 29): horizontal flag bit
- `+0x21` (byte 33): vertical-down flag bit

Evidence:

1. Horizontal wire placement is column-local:
- `wire_a -> wire_ab` changes row0 col1 at `+0x19` and `+0x1D` (`00 -> 01`).
- `wire_a -> wire_c_only` clears row0 col0 `+0x19/+0x1D` and sets row0 col2 `+0x19/+0x1D`.

2. Vertical wire placement is column-local:
- `vert_b_only` has row0 col1 `+0x21 = 01`.
- `vert_d_only` has row0 col3 `+0x21 = 01`.

3. Corner appears implicit (no dedicated corner flag found):
- `vert_b_only -> corner_b` adds horizontal flags in row0 col1 (`+0x19/+0x1D`) and row0 col0 right-connection (`+0x1D`), with the same vertical flag (`+0x21`) still in row0 col1.

4. 2-row vs 3-row vertical continuation:
- `vert_b_only` (2 rows): row0 col1 has `+0x21 = 01`; row1 col1 has `+0x21 = 00`.
- `vert_b_3rows` (3 rows): row0 col1 `+0x21 = 01`, row1 col1 `+0x21 = 01`, row2 col1 `+0x21 = 00`.
- This matches "vertical-down from this row to next row".

## Instruction Stream (Non-Header) Confirmation

From type/function markers in captures:

- NO/NC contacts differ by type/func (`0x11`/`4097` vs `0x12`/`4098`).
- Rise/Fall contacts use edge type `0x13` with funcs `4101`/`4102` (from `old/rise_*` and `old/fall_*`).
- Out/Latch/Reset coils differ by type/func (`0x15`/`8193`, `0x16`/`8195`, `0x17`/`8196`).

## Immediate Contact Validation

New captures checked:

- `no_a_immediate_only` (`X001`, NO immediate `4099`)
- `nc_a_immediate_only` (`X001`, NC immediate `4100`)
- `no_c_immediate_only` (`X001`, NO immediate `4099`, column C)

Header comparison results:

- `no_a_only` vs `no_a_immediate_only`: only header bytes `+0x05` and `+0x11` changed across all entries.
- `nc_a_only` vs `nc_a_immediate_only`: only header bytes `+0x05` and `+0x11` changed across all entries.
- `no_c_only` vs `no_c_immediate_only`: only header bytes `+0x05` and `+0x11` changed across all entries.

After masking `+0x05` and `+0x11`, all three immediate-vs-non-immediate header pairs are identical.

Conclusion: immediate NO/NC does not modify structural header entries in this region.

## Pasteback Validation (Click Round Trip)

Test performed:

- Source payload put on clipboard: `vert_b_with_horiz.bin`
- Pasted into Click, copied back
- Recaptured as: `pasteback_vert_b_with_horiz.bin`

Results:

- Header structural compare: equal (`header_structural_equal == True`)
- Normalized header entries: no diffs
- Raw header diffs: only volatile bytes `+0x05` and `+0x11` in all 32 entries
- Parsed wire topology: identical
  - source non-empty cells:
    - row0 col1: `hl=1, hr=1, vd=1`
    - row1 col1: `hl=1, hr=1, vd=0`
  - pasteback non-empty cells: exact match

Interpretation:

- Click accepts these wire topology flags as semantically valid and round-trips them unchanged.
- Large raw byte drift outside normalized header/topology exists, but it is non-structural for wire semantics.

## Two-Series Fragmentation Control-Byte Follow-Up (2026-03-03)

Reference broken capture:

- `scratchpad/captures/two_series_second_immediate_back_split_after_row0_profile.bin` (`20480` bytes)

Generated patch-test payloads (first 8192-byte record patched; remaining bytes unchanged):

- `..._patch_1a_ff.bin` (`+0x1A=0xFF` on occupied cells)
- `..._patch_1b_01.bin` (`+0x1B=0x01` on occupied cells)
- `..._patch_1a_ff_1b_01.bin` (combined)
- `..._patch_1a_ff_1b_ff.bin` (combined using immediate-family `+0x1B`)

Helper used:

- `devtools/patch_capture_cells.py`

### Native Two-Series Decision Table (`row0 col4..31` and `row1 col0`)

Observed from fixture captures:

- Normal two-series (`NO/NC`, non-immediate): `+0x1A=0xFF`, `+0x1B=0x01`
- Any single immediate contact (first OR second): `+0x1A=0xFF`, `+0x1B=0xFF`
- Both contacts immediate: `+0x1A=0x00`, `+0x1B=0xFF`
- Edge-contact first (`rise`/`fall` + NO): `+0x1A=0x00`, `+0x1B=0x00`

### `+0x17/+0x18` Note

- `smoke_immediate_native` carries non-zero values where `smoke_simple_native` is zero.
- In `two_series_second_immediate_native`, those same profile cells are zero.
- Current evidence suggests `+0x17/+0x18` are instruction-family profile bytes, not required rung-membership/group bytes.

### Important Confound in `...split_after_row0_profile.bin`

For profile cells (`row0 col4..31`, `row1 col0`) in the first 8192-byte record:

- `+0x19` and `+0x1D` are also zero (no horizontal wire flags), not just `+0x1A/+0x1B`.
- `+0x04/+0x05/+0x09/+0x11/+0x1A/+0x1B/+0x1C/+0x25/+0x29` are all zero in that same profile region.

Implication:

- Patching only `+0x1A` on this artifact is not a clean isolation test for rung-membership bytes.
- `+0x1B` broad-patch crashes were explained by stream overlap when patching every occupied cell.
- Focused profile-only patching avoids stream corruption and should be used for next manual validation rounds.

### Clean Isolation Harness (Generated 8192 Baseline)

To avoid split-record confounds, generated payload variants were created from
`ClickCodec.encode("X001,X002.immediate,->,:,out(Y001)")` (single 8192 bytes,
all 3 type markers intact at `0x0A99`, `0x0B1E`, `0x12D9`):

- `scratchpad/captures/two_series_second_immediate_generated_baseline.bin`
- `scratchpad/captures/two_series_second_immediate_generated_patch_profile_1a_00.bin`
- `scratchpad/captures/two_series_second_immediate_generated_patch_profile_1b_00.bin`
- `scratchpad/captures/two_series_second_immediate_generated_patch_profile_1a_00_1b_00.bin`
- `scratchpad/captures/two_series_second_immediate_generated_patch_profile_1a_ff_1b_01.bin`

These mutate only profile cells (`row0 col4..31`, `row1 col0`) and keep stream bytes valid,
so fragmentation outcome reflects control-byte semantics rather than missing-stream artifacts.

## Pre-Grid Differential Ranking (2026-03-03, late session)

Target comparison:

- failing case: generated `X001,X002.immediate,->,:,out(Y001)` (`generated_v2`)
- native reference: `two_series_second_immediate_native.bin`
- analyzed region: `0x0000..0x0A5F` (pre-grid)

Working control set used to filter common/non-gating drift:

- `smoke_simple`
- `smoke_immediate`
- `smoke_two_series_short`

Counts:

- failing pre-grid mismatches: `114`
- mismatches unique to failing case (absent in all 3 controls): `4`

Unique failing offsets:

- `0x006E`: generated `0x00`, native `0x61`
- `0x0072`: generated `0x00`, native `0x79`
- `0x0076`: generated `0x00`, native `0x65`
- `0x007E`: generated `0x00`, native `0x1E`

Artifacts:

- ranked table: `scratchpad/pregrid_ranked_candidates.csv`
- concise summary: `scratchpad/pregrid-candidate-results.md`
- targeted test payload:
  - `scratchpad/captures/two_series_second_immediate_generated_v2_patch_pregrid_focus4_native.bin`
  - only those 4 pre-grid bytes patched to native; stream/grid markers remain intact
