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

## Region Isolation Result (2026-03-03 final pass)

On top of `generated_v2` with row1/row2 parity controls:

- `..._patch_r12native_preheader_native.bin` (`0x0000..0x0253` copied from native) => still split (`12288`)
- `..._patch_r12native_header_native.bin` (`0x0254..0x0A5F` copied from native) => single rung (`8192`)
- `..._patch_r12native_pregrid_full_native.bin` (entire `0x0000..0x0A5F` copied) => single rung (`8192`)

Conclusion:

- The remaining split gate was in the header region (`0x0254..0x0A5F`), not pre-header.
- For `two_series_second_immediate`, decisive bytes were header-entry `+0x05` and `+0x11`
  across all 32 entries, plus trailing header-area byte `0x0A59`:
  - `+0x05 = 0x04`
  - `+0x11 = 0x0B`
  - `0x0A59 = 0x04`

Encoder status:

- Deterministic encoder now writes these bytes for the second-immediate two-series family.
- Validation payload: `scratchpad/captures/two_series_second_immediate_generated_v3_headerfix.bin`
- Final recapture: `scratchpad/captures/two_series_second_immediate_back_after_generated_v3_headerfix.bin`
  - length: `8192`
  - markers: `0x0A99` (contact1), `0x0B1E` (contact2), `0x12D9` (coil)
  - decode: `X001,X002.immediate,->,:,out(Y001)`

## Profile Byte Formula Investigation (2026-03-04)

Scope:

- New native captures listed in `scratchpad/capture-checklist.md` (11 labels).
- Existing native fixture captures in `tests/fixtures/ladder_captures` for cross-check.

### New-Capture Raw Table (`row0,col4` + header entry 0)

| Label | Contacts | cell `+0x05` | cell `+0x11` | cell `+0x1A` | cell `+0x1B` | hdr `+0x05` | hdr `+0x11` | hdr `+0x17` | `0x0A59` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `two_series_nc_no_native` | `~X001 , X002` | `0x00` | `0x00` | `0xFF` | `0x01` | `0x00` | `0x00` | `0x4E` | `0x00` |
| `no_first_nc_second_native` | `X001 , ~X002` | `0x00` | `0x00` | `0xFF` | `0x01` | `0x01` | `0x02` | `0x4E` | `0x01` |
| `two_series_nc_nc_native` | `~X001 , ~X002` | `0x00` | `0x00` | `0xFF` | `0x01` | `0x02` | `0x04` | `0x4E` | `0x02` |
| `nc_first_imm_no_second_native` | `~X001.immediate , X002` | `0x03` | `0x07` | `0xFF` | `0xFF` | `0x03` | `0x06` | `0x4E` | `0x03` |
| `no_first_nc_second_imm_native` | `X001 , ~X002.immediate` | `0x04` | `0x09` | `0xFF` | `0xFF` | `0x04` | `0x08` | `0x4E` | `0x04` |
| `nc_first_imm_nc_second_imm_native` | `~X001.immediate , ~X002.immediate` | `0x00` | `0x00` | `0x00` | `0xFF` | `0x05` | `0x0A` | `0x4E` | `0x05` |
| `c_first_no_second_native` | `C1 , X002` | `0x00` | `0x00` | `0x00` | `0x00` | `0x06` | `0x0C` | `0x4E` | `0x06` |
| `no_first_c_second_native` | `X001 , C2` | `0x00` | `0x00` | `0x00` | `0x00` | `0x07` | `0x0E` | `0x4E` | `0x07` |
| `no_first_rise_second_native` | `X001 , rise(X002)` | `0x11` | `0x01` | `0x00` | `0x00` | `0x08` | `0x10` | `0x4E` | `0x08` |
| `no_first_fall_second_native` | `X001 , fall(X002)` | `0x11` | `0x01` | `0x00` | `0x00` | `0x08` | `0x10` | `0x4E` | `0x08` |
| `rise_first_rise_second_native` | `rise(X001) , rise(X002)` | `0xFF` | `0x00` | `0x00` | `0x00` | `0x08` | `0x10` | `0x4E` | `0x08` |

### Findings

1. `+0x1A/+0x1B` is compositional by contact family and immediate count.
   - Any edge contact OR any non-X-bank contact => `0x00/0x00`.
   - Both immediate (X-bank contacts) => `0x00/0xFF`.
   - Exactly one immediate (X-bank contacts) => `0xFF/0xFF`.
   - No immediate (X-bank contacts, non-edge) => `0xFF/0x01`.

2. `+0x05/+0x11` for two-series profile cells is not a fixed literal table.
   - Best-fit rule uses header seed bytes (`hdr+0x05`, `hdr+0x11`) plus contact features:
     - both edge => `0xFF/0x00`
     - exactly one edge => `(hdr11 + 1) / 0x01`
     - both immediate => `0x00/0x00`
     - exactly one immediate => `hdr05 / (hdr11 + 1)`
     - else => `0x00/0x00`
   - This matched all decoded two-series native captures tested:
     - `18/18` in `scratchpad/captures`
     - `9/9` in `tests/fixtures/ladder_captures`

3. Header bytes are context-dependent, not instruction-only constants.
   - For almost all captures, all 32 entries share the same per-entry `+0x05`, `+0x11`, `+0x17`.
   - `0x0A59` mirrors header entry `+0x05` in all non-fragmented records checked.
   - Same rung shape can appear with different header families:
     - `two_series_nc_no_native` fixture: `hdr+0x17=0x15`, `hdr+0x05=0x29`, `hdr+0x11=0x59`
     - `two_series_nc_no_native` new capture: `hdr+0x17=0x4E`, `hdr+0x05=0x00`, `hdr+0x11=0x00`
   - Their profile/control cell bytes remained identical, indicating header family bytes are influenced by broader capture context.

## Three-Series Generalization Pass (2026-03-04)

New native captures under scenario `three_series_generalization`:

- `three_series_no_no_no_native`
- `three_series_first_imm_native`
- `three_series_second_imm_native`
- `three_series_third_imm_native`
- `three_series_first_second_imm_native`
- `three_series_first_third_imm_native`
- `three_series_first_rise_native`
- `three_series_second_rise_native`
- `three_series_c_first_native`

All decode to expected 3-contact CSV forms.

### Header observations

- In this pass, header entry 0 stayed in one family: `+0x17 = 0x4E`, `+0x18 = 0x01`.
- `0x0A59` mirrored header entry `+0x05` for every new capture.
- Header entry `+0x05` progressed `0x09..0x11`; `+0x11` progressed `0x12..0x22` with `+0x11 = 2 * (+0x05)`.

### Strong generalized rule (`row0,col4 +0x05/+0x11`)

Let `first`, `second` be the first two contacts and `h05/h11` be header entry 0 bytes.

- If both are edge contacts: `cell+0x05 = 0xFF`, `cell+0x11 = 0x00`
- Else if exactly one is edge: `cell+0x05 = h11 + 1`, `cell+0x11 = 0x01`
- Else if immediate flags differ: `cell+0x05 = h05`, `cell+0x11 = h11 + 1`
- Else: `cell+0x05 = 0x00`, `cell+0x11 = 0x00`

Validation:

- Matched all decoded captures with at least two contacts:
  - `27/27` in `scratchpad/captures`
  - `9/9` in `tests/fixtures/ladder_captures`

### Three-series tail profile region

For 3-series captures, `row0,col6..31` had one constant tuple per capture for `(+0x05,+0x11,+0x1A,+0x1B)`.
This tuple mirrors to `row1,col0` and `row1,col1` in all nine captures (and to `row1,col2` except `three_series_c_first_native`).

Observed rule candidate:

- Any edge contact present: `00/00/00/00`
- Any non-X-bank contact present: `00/00/FF/FF`
- Otherwise (all X-bank, non-edge):
  - `+0x05/+0x11 = 00/00`
  - `+0x1A/+0x1B = 01/01` when immediate count is odd, else `00/00`

### Three-series `row0,col4 +0x1B` state byte

`row0,col4 +0x1A` stayed `0x00` in this pass.
`row0,col4 +0x1B` tracked first-pair immediate state (for non-edge X-bank pair):

- first/second both non-immediate: `0x01`
- exactly one immediate: `0x00`
- both immediate: `0x02`

For first-pair edge/non-X cases observed, this byte was `0x00`.

### Remaining gaps

To tighten formulas, still useful:

- `X001.immediate,X002.immediate,X003.immediate` (odd-count parity check at count 3)
- `X001,X002,fall(X003)` and `X001,X002,rise(X003)` (edge in third slot)
- `X001,C2,X003` and `X001,X002,C3` (non-X bank in later slots)

## Five/Eight-Series + Gaps + Bank Pass (2026-03-04)

New native captures processed:

- series length + gap:
  - `five_series_no_no_no_no_no_native`
  - `eight_series_no_x8_native`
  - `five_series_gap_alternating_native`
  - `five_series_gap_front_loaded_native`
  - `eight_series_gap_alternating_native`
  - `eight_series_gap_staggered_native`
  - `eight_series_gap_split_blocks_native`
- bank set:
  - `five_series_contact_y_native`
  - `five_series_contact_c_native`
  - `five_series_contact_t_native`
  - `five_series_contact_ct_native`
  - `five_series_contact_sc_native`

### Header pattern update

- Header family remained fixed for all new captures:
  - `+0x17 = 0x4E`
  - `+0x18 = 0x01`
- Header entry 0 relation remained stable:
  - `+0x11 = 2 * (+0x05)`
  - `0x0A59` mirrors `+0x05`

### `row0,col4 +0x05/+0x11` generalized rule status

The first-two-contact rule from the prior section still holds across the expanded corpus.

Validation after adding 5/8/gap captures:

- `39/39` decoded captures in `scratchpad/captures`
- `9/9` decoded captures in `tests/fixtures/ladder_captures`

### Gap-layout effect (`row0,col4 +0x1A/+0x1B`)

For 5/8-series non-edge/non-immediate X-bank captures, `row0,col4 +0x1A/+0x1B` varied by layout:

- contiguous: `00/01`
- alternating gaps: `FF/FF`
- staggered: `FF/01`
- front-loaded gaps: `00/00`

Interpretation:

- For longer/gapped rungs, `row0,col4` control bytes are topology-sensitive and no longer just a simple pairwise instruction signature.

### Bank-series clarification

This bank set is now explicitly treated as contact-bank variation with AF fixed at `out(Y001)`:

- `five_series_contact_y_native`: `Y001..Y005 -> out(Y001)`
- `five_series_contact_c_native`: `C1..C5 -> out(Y001)`
- `five_series_contact_t_native`: `T1..T5 -> out(Y001)`
- `five_series_contact_ct_native`: `CT1..CT5 -> out(Y001)`
- `five_series_contact_sc_native`: `SC1..SC5 -> out(Y001)`

Coil-isolation follow-up is now captured with fixed contacts `X001..X005`:

- `five_series_x_out_c_native` => decodes `...->,:,out(C1)`
- `five_series_x_out_sc_native` => decodes `...->,:,out(SC50)` (`SC50` used because SC writability is range-limited)

Observed profile/header bytes:

- `five_series_x_out_c_native`: `cell(0,4) +0x1A/+0x1B = 00/01`, header `+0x05/+0x11/+0x17 = 22/44/4E`, trailer `0x0A59=22`
- `five_series_x_out_sc_native`: `cell(0,4) +0x1A/+0x1B = 00/01`, header `+0x05/+0x11/+0x17 = 23/46/4E`, trailer `0x0A59=23`

## Investigator Handoff (2026-03-04)

State at pause:

- Working manifest contains two-series, three-series, five/eight-series, gap-layout, contact-bank, and valid OUT-target isolation captures.
- Generalized `row0,col4 +0x05/+0x11` first-two-contact rule remains validated on all decoded captures in `scratchpad/captures` and fixture natives.
- Long-series/gap captures show topology-sensitive variation in `row0,col4 +0x1A/+0x1B`.
- Contact-bank labels are normalized to `five_series_contact_*`.
- OUT target constraint is recorded: valid targets are `Y`, `C`, `SC` (with `SC50` used for writable SC range).

Suggested next investigator steps:

1. Re-run one consolidated profile export:
   - `uv run clicknick-ladder-capture report profile --all --csv`
2. Build per-column (not only `row0,col4`) modeling for 5/8-series to separate stream-overlap bytes from stable profile region bytes.
3. Decide whether to extend encoder beyond 2-series now or defer until compare-family captures are added.

## Per-Column Modeling Pass (2026-03-04, continuation)

Scope:

- Existing native captures in `series_length_and_gap_generalization`.
- To avoid stream-anchor confounds, analysis was split by fixed contact count:
  - 5-contact set: `five_series_no_no_no_no_no_native`, `five_series_gap_alternating_native`, `five_series_gap_front_loaded_native`
  - 8-contact set: `eight_series_no_x8_native`, `eight_series_gap_alternating_native`, `eight_series_gap_staggered_native`, `eight_series_gap_split_blocks_native`

### Findings

1. Stream-overlap windows are count-dependent.
   - 5-series: high-entropy row0 window is `col4..col13` (last contact marker reaches row0 col13).
   - 8-series: high-entropy row0 window is `col4..col24` (last contact marker reaches row0 col23).

2. Stable tail regions isolate deterministic family bytes.
   - 5-series stable tail:
     - row0 `col14..col31`
     - row1 `col0..col4`
     - only varying offsets per cell: `+0x12` and `+0x1E`
     - per-capture constants:
       - contiguous: `12/25`
       - alternating gaps: `14/29`
       - front-loaded gaps: `15/2B`
   - 8-series stable tail:
     - row0 `col25..col31`
     - row1 `col0..col6`
     - only varying offsets per cell: `+0x21` and `+0x2D`
     - per-capture constants:
       - contiguous: `13/27`
       - alternating gaps: `16/2D`
       - staggered gaps: `17/2F`
       - split blocks: `18/31`

3. Tail bytes follow one shifted header-seed rule.
   - `tail_first = header_entry0(+0x05)`
   - `tail_second = header_entry0(+0x11) + 1`
   - Observed offset shifts:
     - 5-series: logical `(+0x05,+0x11)` appears at `(+0x12,+0x1E)` (shift `+0x0D`)
     - 8-series: logical `(+0x05,+0x11)` appears at `(+0x21,+0x2D)` (shift `+0x1C`)

### Implication

- For long-series modeling, treat early row0 columns as stream-overlap (non-stationary) and derive deterministic profile bytes from the stable tail region.
- `row0,col4` alone is not sufficient once series length/gap layout increases.

## Regression Triage: Long-Series Crash (2026-03-04, late)

Observed in manual Click verify runs:

- Random and "safe" long-series synthetic payloads (`>2` contacts) consistently produced Click `"Out of Memory"` crashes.

Codec vs native comparison for contiguous references:

- `X001..X005 -> out(Y001)`:
  - type marker offsets matched native exactly
  - but header/profile family bytes diverged:
    - generated: `hdr +0x05/+0x11/+0x17/+0x18 = 00/00/15/01`, `0x0A59=00`
    - native: `12/24/4E/01`, `0x0A59=12`
- `X001..X008 -> out(Y001)` showed the same pattern:
  - generated `00/00/15/01`, native `13/26/4E/01`.

Conclusion:

- Long-series deterministic model is incomplete; stream placement alone is insufficient.
- Safety rollback applied in encoder:
  - Click-safe path is now restricted back to `1..2` series contacts.
  - Attempting `>2` now fails fast with a clear error before any clipboard write.

## Session-Counter Model (2026-03-04, late-night pass)

Scope:

- All `*_native.bin` in `scratchpad/captures` (`50` files).
- Cross-check overlap against `tests/fixtures/ladder_captures` for same labels.

### Strong header/trailer invariants

For every decodeable instruction capture checked:

1. Header-entry bytes are column-uniform for all 32 entries:
   - `+0x05`, `+0x11`, `+0x17`, `+0x18` each had one constant value per file.
2. Trailer mirror holds:
   - `0x0A59 == header_entry0(+0x05)`.
3. `+0x11` is affine in `+0x05` with family-specific bias:
   - family `+0x17 = 0x4E` (and observed `0x43`): `+0x11 = 2*(+0x05) + 0x00 (mod 256)`
   - family `+0x17 = 0x15`: `+0x11 = 2*(+0x05) + 0x07 (mod 256)`
   - family `+0x17 = 0x0D` (single sample): `+0x11 = 2*(+0x05) + 0x03 (mod 256)`

Interpretation:

- `(+0x05,+0x11,+0x17,0x0A59)` behaves like a session/family seed tuple, not a direct rung-topology encoding.
- This is consistent with same rung topology appearing under different seed families.

### Same-rung cross-session proof point

`two_series_nc_no_native.bin`:

- scratchpad copy: `h05/h11/h17/h18/t59 = 00/00/4E/01/00`
- fixture copy: `29/59/15/01/29`

Both decode to `~X001,X002,->,:,out(Y001)`.

Pairwise compare:

- topology equal: `True`
- header equal when masking `+0x05/+0x11/+0x17/+0x18`: `True`

This supports session-derived seed drift rather than semantic drift.

### Rule re-validation (first-two-contact profile bytes)

Across all decodeable captures with at least two contacts in `scratchpad/captures`:

- `row0,col4 +0x05/+0x11` first-two-contact rule matched `40/40`.
- `row0,col4 +0x1A/+0x1B` two-series compositional rule matched `17/17` for exactly two contacts.
- As expected, that `+0x1A/+0x1B` two-series rule does **not** extend to 3/5/8-series (`23/40` if applied blindly).

### Row1 vs Row2 duplicate experiment design (for next capture pass)

Goal: discriminate session-counter bytes from row-placement bytes.

Capture sequence in one uninterrupted Click session:

1. Copy a single rung from row1 (baseline).
2. Duplicate same rung into row2 and copy only row2 rung.
3. Copy rows1+2 together (two-row payload).

Expected if session-counter hypothesis is right:

- Steps 1 and 2:
  - same decoded CSV/topology
  - row class remains one-row
  - seed tuple (`h05/h11/h17/t59`) advances, but masked structure stays equal.
- Step 3:
  - row class changes to two-row class (`0x60`) and topology changes by row-count.
  - seed still advances independently.

Analyzer prepared:

- `devtools/analyze_session_counter.py`
- Example:
  - `uv run python devtools/analyze_session_counter.py --file <cap1.bin> --file <cap2.bin> --file <cap3.bin>`

### Session-counter row-duplicate experiment result (captured)

Labels:

- `session_counter_row1_single_native`
- `session_counter_row2_duplicate_native`
- `session_counter_rows1_2_combined_native`

Observed (`analyze_session_counter.py`):

- Row1 single:
  - `len=8192`, `row_class=0x40`, `h05/h11/h17/t59 = 00/00/4D/00`
- Row2 duplicate (same rung only):
  - `len=8192`, `row_class=0x40`, `h05/h11/h17/t59 = 01/02/4D/01`
- Rows1+2 combined copy:
  - `len=12288`, `row_class=0x80`, `h05/h11/h17/t59 = 00/00/4D/00`

Pairwise interpretation:

- Row1 single -> Row2 duplicate:
  - topology equal
  - `h05/h11/t59` advanced by `+1/+2/+1`
  - structural header equal under masks (`+0x05/+0x11`, and `+0x05/+0x11/+0x17/+0x18`)
  - This is direct evidence that these bytes include a session/capture counter component, independent of rung semantics.
- Row1 single -> Rows1+2 combined:
  - topology changed and row class changed (`0x40 -> 0x80`)
  - masked structural headers are not equal
  - This capture is a different record class (multi-row/multi-rung context), so it should not be used as a pure counter-isolation pair.

New family note:

- `h17 = 0x4D` appears as another session-family byte alongside previously seen `0x4E`, `0x15`, `0x0D`, etc.

## Session-UID Isolation Pass (2026-03-04, follow-up)

Scope:

- Session-control captures for one fixed rung (`~X001,X002,->,:,out(Y001)`):
  - `session_counter_row1_single_native`
  - `session_counter_row2_duplicate_native`
  - `session_counter_mono_01_native`
  - `session_counter_mono_02_native`
  - `session_counter_mono_03_native`
  - `session_counter_crossapp_a_source_native`
  - `session_counter_crossapp_b_pasteback_native`
  - `session_counter_crossuid_yes_a_source_native`
  - `session_counter_crossuid_yes_b_pasteback_native`
- Analyzer invocation (payload-only to avoid verify backfill masking):
  - `uv run python devtools/analyze_session_counter.py --source payload --label ...`

### Header offset isolation result

Across that fixed-topology set, only three entry-local header offsets varied:

- `+0x05`
- `+0x11`
- `+0x17`

All three were column-uniform across all 32 header entries in each file.

No other header-entry offsets varied for this set.

### Cross-app and cross-UID observations

Same decoded topology, payload captures only:

- Cross-app transfer:
  - `A source`: `h17=0x58`
  - `B pasteback`: `h17=0x32`
- Cross-UID "YES" scenario:
  - `A source`: `h17=0x88`
  - `B pasteback payload`: `h17=0x20`

In both cases, `h05/h11/t59` stayed `0x00/0x00/0x00` while `h17` changed.

Interpretation:

- `+0x17` is the strongest current candidate for a session/window-family UID byte (or direct function of it).

### Counter-like bytes status update

Row-duplicate pair still shows:

- row1 -> row2: `h05/h11/t59 = +1/+2/+1`, with same topology.

But monotonic same-window test (`mono_01 -> mono_02 -> mono_03`) showed no movement:

- `h05/h11/t59` remained `0x00/0x00/0x00`.

Interpretation:

- `+0x05/+0x11` (and `0x0A59`) are volatile and non-structural, but current evidence does not support a simple "always monotonic per copy" model.
- These bytes likely include additional state (selection/context class) besides pure copy count.

### Verify-file caveat

For labels with `verify_result_file`, auto label resolution can hide payload-session drift.

Example (`session_counter_crossuid_yes_b_pasteback_native`):

- payload file: `h17=0x20`
- verify result file: `h17=0x88`

Both decode to the same rung.

Action taken:

- `analyze_session_counter.py` now supports `--source {auto,payload,verify}` to make this explicit.

