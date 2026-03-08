# Phase 3 Wireframe Band Isolation Continue (March 8, 2026)

## Scope

Continue Phase 3 from the March 8 clean donor set, still with comment synthesis explicitly out of scope.

This continuation only targets the clean no-comment wireframe references:
- `grcecr_empty_native_20260308`
- `grcecr_fullwire_native_20260308`
- `grcecr_fullwire_nop_native_20260308`
- `grcecr_rows2_empty_native_20260308`
- `grcecr_rows2_vert_horiz_native_20260308`

Claim boundary:
- no comment-bearing payload bytes are synthesized here
- no comment companion-byte synthesis is claimed here
- production codec behavior remains unchanged

## New Offline Artifacts

Helper updates:
- `devtools/march8_wireframe_synth.py`
- `devtools/march8_wireframe_band_audit.py`

New explicit template spec:
- `scratchpad/phase3_wireframe_band_templates_20260308.json`

Generated outputs:
- `scratchpad/captures/phase3_wireframe_20260308_bands/empty_1row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308_bands/fullwire_1row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308_bands/fullwire_nop_1row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308_bands/empty_2row_march8_wireframe.bin`
- `scratchpad/captures/phase3_wireframe_20260308_bands/vert_horiz_2row_march8_wireframe.bin`

## Band Model Update

The March 8 helper now uses `grcecr_empty_native_20260308.bin` as the only donor baseline and overlays explicit March 8 band templates for the previously donor-backed no-comment bands.

Explicit band templates now cover:
- fullwire 1-row row1 band `0x1260..0x1A5F`
- shared tail band `0x1A60..0x1FFF`
- 2-row prefix band `0x0000..0x0253`
- 2-row empty row1 band `0x1260..0x1A5F`

The existing explicit logic still covers:
- metadata band row-word update at `0x0254`
- row0 visible wire bytes
- row0 AF-cell pair for `fullwire_nop_1row`
- row0 terminal bytes for the 2-row family
- row1 visible wire bytes for `vert_horiz_2row`

Conservative interpretation:
- these four band templates are explicit March 8 no-comment band bytes
- they are not yet a semantic or cross-family generalization beyond this March 8 no-comment scope

## Exact Native Diff Results

Command used for regenerated outputs:

```powershell
uv run python devtools/march8_wireframe_synth.py --scenario all --output-dir scratchpad/captures/phase3_wireframe_20260308_bands --json
```

All five synthesized outputs still match their March 8 native targets byte-for-byte.

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

## Exactly Which Additional Bytes Are Now Explicit

Audit command:

```powershell
uv run python devtools/march8_wireframe_band_audit.py --json
```

The helper now carries `4` explicit March 8 band templates covering `6132` band bytes total.

Additional changed bytes versus the empty 1-row control now isolated as explicit no-comment band bytes:
- fullwire 1-row row1 band `0x1260..0x1A5F`
  - explicit band length: `2048`
  - changed bytes vs empty 1-row: `421`
- shared tail band `0x1A60..0x1FFF`
  - explicit band length: `1440`
  - changed bytes vs empty 1-row: `491`
- 2-row prefix band `0x0000..0x0253`
  - explicit band length: `596`
  - changed bytes vs empty 1-row: `237`
- 2-row empty row1 band `0x1260..0x1A5F`
  - explicit band length: `2048`
  - changed bytes vs empty 1-row: `570`

Total additional changed bytes vs empty 1-row now isolated as explicit no-comment band bytes:
- `1719`

Exact offset accounting:
- `scratchpad/phase3_wireframe_band_templates_20260308.json` stores the exact relative changed-offset list for each band under `changed_offsets_vs_empty_1row`
- that same file stores the full explicit bytes for each band under `bytes_hex`

Usage by synthesized target:
- `fullwire_1row`
  - fullwire 1-row row1 band
  - shared tail band
- `fullwire_nop_1row`
  - fullwire 1-row row1 band
  - shared tail band
  - plus the already explicit row0 AF-cell pair
- `empty_2row`
  - 2-row prefix band
  - 2-row empty row1 band
  - shared tail band
  - plus the already explicit row-word and row0 terminal bytes
- `vert_horiz_2row`
  - 2-row prefix band
  - 2-row empty row1 band
  - shared tail band
  - plus the already explicit row0 and row1 visible wire bytes

## Conservative Phase 3 Status

What is now proven:
- all five March 8 clean no-comment wireframe targets still reconstruct byte-exactly
- the four previously donor-backed no-comment bands listed above are now explicit March 8 band templates
- the shared tail band is the same explicit March 8 band template in both the fullwire family and the 2-row family

What remains out of scope:
- comment-bearing payload support
- comment companion-byte synthesis
- any claim that these explicit March 8 band templates are already a general semantic model

Recommended next Phase 3 focus:
- keep the helper offline-only
- look for semantic structure inside the now-explicit March 8 band templates instead of reintroducing donor-band copies
- keep comment-family analysis separate from the no-comment wireframe baseline
