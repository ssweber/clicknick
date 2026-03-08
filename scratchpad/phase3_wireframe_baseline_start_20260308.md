# Phase 3 Wireframe Baseline Start (March 8, 2026)

## Scope

Start Phase 3 from the March 8 clean donor set, with comment synthesis explicitly out of scope.

This pass only targets the clean no-comment wireframe references:
- `grcecr_empty_native_20260308`
- `grcecr_fullwire_native_20260308`
- `grcecr_fullwire_nop_native_20260308`
- `grcecr_rows2_empty_native_20260308`
- `grcecr_rows2_vert_horiz_native_20260308`

Comment claim boundary:
- no comment-bearing payload bytes are synthesized here
- comment companion bytes remain a separate unresolved family layered on top of this baseline

## New Offline Helper

Helper:
- `devtools/march8_wireframe_synth.py`

Generated outputs:
- `scratchpad/captures/phase3_wireframe_20260308/empty_1row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308/fullwire_1row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308/fullwire_nop_1row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308/empty_2row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308/vert_horiz_2row_march8_wireframe.bin`

The helper is intentionally March 8-scoped. It assembles payloads as:
- donor-backed prefix band `0x0000..0x0253`
- metadata band `0x0254..0x0A53`
- gap band `0x0A54..0x0A5F`
- synthesized row0 band `0x0A60..0x125F`
- optional row1 band `0x1260..0x1A5F`
- donor-backed tail band `0x1A60..0x1FFF`

## Exact Native Diff Results

All five synthesized outputs match their March 8 native targets byte-for-byte.

Per-target diff result:

1. `empty_1row`
   - prefix band: `0`
   - metadata band: `0`
   - gap band: `0`
   - row0 band: `0`
   - row1 band: `0`
   - tail band: `0`
   - full: `0`
2. `fullwire_1row`
   - prefix band: `0`
   - metadata band: `0`
   - gap band: `0`
   - row0 band: `0`
   - row1 band: `0`
   - tail band: `0`
   - full: `0`
3. `fullwire_nop_1row`
   - prefix band: `0`
   - metadata band: `0`
   - gap band: `0`
   - row0 band: `0`
   - row1 band: `0`
   - tail band: `0`
   - full: `0`
4. `empty_2row`
   - prefix band: `0`
   - metadata band: `0`
   - gap band: `0`
   - row0 band: `0`
   - row1 band: `0`
   - tail band: `0`
   - full: `0`
5. `vert_horiz_2row`
   - prefix band: `0`
   - metadata band: `0`
   - gap band: `0`
   - row0 band: `0`
   - row1 band: `0`
   - tail band: `0`
   - full: `0`

## Exact Byte Accounting

This section uses the clean empty 1-row control as the reference baseline for the 1-row family,
and the clean empty 2-row native as the reference baseline for the 2-row mixed case.

### Empty 1-Row -> Fullwire 1-Row

Observed diff counts:
- prefix band: `0`
- metadata band: `0`
- gap band: `0`
- row0 band: `62`
- row1 band: `421`
- tail band: `491`
- full: `974`

Bytes now explicitly explained by the wireframe model:
- all `62` row0-band deltas
- exact rule:
  - row0 condition cols `0..30`
  - cell `+0x19 = 0x01`
  - cell `+0x1D = 0x01`

Bytes still donor-backed in this start-of-Phase-3 model:
- row1 band: `421`
- tail band: `491`

Conservative interpretation:
- single-row fullwire visible topology is now explained in the row0 band
- the matching row1 companion family and tail family are still donor-backed, not generalized

### Fullwire 1-Row -> Fullwire+NOP 1-Row

Observed diff counts:
- prefix band: `0`
- metadata band: `0`
- gap band: `0`
- row0 band: `2`
- row1 band: `0`
- tail band: `0`
- full: `2`

Bytes now explicitly explained by the wireframe model:
- `0x1239: 00 -> 01`
- `0x123D: 00 -> 01`

Equivalent row/cell wording:
- row0 AF cell (col `31`)
- `+0x19` and `+0x1D`

Conservative interpretation:
- the March 8 `NOP` distinction is currently only the AF-cell horizontal pair on row0

### Empty 1-Row -> Empty 2-Row

Observed diff counts:
- prefix band: `237`
- metadata band: `1`
- gap band: `0`
- row0 band: `2`
- row1 band: `570`
- tail band: `491`
- full: `1301`

Bytes now explicitly explained by the wireframe model:
- metadata band:
  - `0x0254: 40 -> 60`
- row0 band:
  - `0x1258: 00 -> 01`
  - `0x125D: 00 -> 02`

Equivalent row/cell wording:
- row-word low byte for 2 visible rows
- row0 col31 terminal bytes:
  - `+0x38 = 0x01`
  - `+0x3D = 0x02`

Bytes still donor-backed in this start-of-Phase-3 model:
- prefix band: `237`
- row1 band: `570`
- tail band: `491`

Conservative interpretation:
- the 2-row family is not metadata-band-only
- it has a large donor-backed prefix/row1/tail companion surface beyond the now-explained row-word and row0 terminal bytes

### Empty 2-Row -> 2-Row Vertical+Horizontal

Observed diff counts:
- prefix band: `0`
- metadata band: `0`
- gap band: `0`
- row0 band: `3`
- row1 band: `2`
- tail band: `0`
- full: `5`

Bytes now explicitly explained by the wireframe model:
- row0 band:
  - `0x0AB9: 00 -> 01`
  - `0x0ABD: 00 -> 01`
  - `0x0AC1: 00 -> 01`
- row1 band:
  - `0x12B9: 00 -> 01`
  - `0x12BD: 00 -> 01`

Equivalent row/cell wording:
- row0 col1:
  - `+0x19`
  - `+0x1D`
  - `+0x21`
- row1 col1:
  - `+0x19`
  - `+0x1D`

Conservative interpretation:
- the March 8 2-row mixed geometry delta is fully explained by visible wire-flag bytes
- no additional metadata-band, gap-band, prefix-band, or tail-band changes were needed

## Conservative Phase 3 Status

What is now proven:
- the March 8 clean no-comment structural captures can be reconstructed exactly with a banded offline helper
- row0 visible wireframe bytes are now explicit for:
  - empty 1-row
  - fullwire 1-row
  - fullwire+NOP 1-row
  - empty 2-row terminal row0 bytes
  - 2-row vertical+horizontal
- the 2-row mixed delta is fully explained by visible wire bytes alone

What remains donor-backed / not yet generalized:
- 1-row fullwire row1 companion family (`421` bytes vs empty 1-row)
- 2-row prefix band (`237` bytes vs empty 1-row)
- 2-row empty row1 companion family (`570` bytes vs empty 1-row)
- family tail band `0x1A60..0x1FFF` (`491` bytes in both the fullwire and 2-row baselines)

What this does **not** claim:
- no comment-bearing payload support
- no comment companion-byte synthesis
- no production codec rollout

Recommended next Phase 3 focus:
- keep the current helper offline-only
- next isolate the donor-backed no-comment surfaces in this order:
  1. fullwire 1-row row1 band
  2. shared tail band `0x1A60..0x1FFF`
  3. 2-row prefix band
  4. 2-row empty row1 band
