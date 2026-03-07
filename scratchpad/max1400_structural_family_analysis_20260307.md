# Max1400 Offline Structural Family Analysis (March 7, 2026)

## Scope

Explain the still-unresolved max1400 structural family in `0x08FD..0x1A5F` using offline diff analysis only.

Compared files:
- `scratchpad/captures/grcmfs_commentwin_full_0294_08fc_from_freshnowire.bin`
- `scratchpad/captures/grcmfs_commentgrid_0294_1a5f_from_freshnowire.bin`
- `scratchpad/captures/grc_no_comment_fresh_native_20260307.bin`
- `scratchpad/captures/grc_max1400_fresh_native_20260307.bin`

## Identity Check

The unresolved region is not synthetic-only noise.

- Failing `commentwin` payload equals fresh no-comment native exactly over `0x08FD..0x1A5F`.
- Passing `commentgrid` payload equals fresh max1400 native exactly over `0x0294..0x1A5F`.

Implication:
- the remaining structural family is exactly the native no-comment vs native max1400 delta for this lane.
- offline source-delta analysis is therefore the right next step; no additional operator queue was needed to establish this.

## Region Partition

Diff count between failing `commentwin` and passing `commentgrid` inside `0x08FD..0x1A5F`:

- `120` bytes before row0 grid start (`0x08FD..0x0A5C`)
- `685` bytes in row0
- `389` bytes in row1
- total: `1194`

## Key Correction: The "120 Non-Grid Bytes" Are Header-Tail/Trailer Structure

The pre-row portion is not a loose block near `0x0904..0x0A5C`.

Exact placement:
- header entry col `26`: tail lead-in at `+0x30`, `+0x39`, `+0x3C`
- header entries cols `27..31`: full repeated descriptor family
- trailing bytes after the 32-entry header table: `0x0A55..0x0A5C`

So the `120` bytes resolve to:
- `3` bytes in header col `26`
- `22 * 5 = 110` bytes across header cols `27..31`
- `7` trailer bytes after the header table

High-signal repeated pattern for header cols `27..31`:
- `+0x01/+0x02/+0x03`: `00 00 00 -> 01 01 0F`
- `+0x05..+0x09`: `00 00 00 00 00 -> FF FF FF FF 01`
- `+0x15..+0x1D`: `01 01 0F 01 FF FF FF FF 01 -> 00 ... 00`
- `+0x28`: `00 -> 01`
- `+0x30`: `00 -> 01`
- `+0x39`: monotonic column-tail code `04/05/06/07/08`
- `+0x3C`: `01 -> 00`

Per-column monotonic bytes:
- header col `27`: `+0x0D 0x1B -> 0x00`, `+0x39 0x04`
- header col `28`: `+0x0D 0x1C -> 0x00`, `+0x39 0x05`
- header col `29`: `+0x0D 0x1D -> 0x00`, `+0x39 0x06`
- header col `30`: `+0x0D 0x1E -> 0x00`, `+0x39 0x07`
- header col `31`: `+0x0D 0x1F -> 0x00`, `+0x39 0x08`

Interpretation:
- this behaves like a tail descriptor table anchored in the last header entries, not random pre-grid noise.
- the monotonic `0x1B..0x1F` and `0x04..0x08` sequences strongly suggest extent indexing or terminal bookkeeping.

## Row0 Structural Families

Row0 has `5` distinct diff shapes.

### Family A: Col `0`

Offsets:
- clears `+0x05/+0x09..+0x11/+0x15`
- sets `+0x1C`, `+0x24`
- sets tail block `+0x2D`, `+0x35..+0x3C`

Distinctive values:
- `+0x2D: 00 -> 09`
- extra clear at `+0x15`

### Family B: Cols `1..22`

Shared body:
- `+0x01: 0x16 -> 0x00`
- clears `+0x05/+0x09..+0x11`
- sets `+0x1C`, `+0x24`
- `+0x2D: 00 -> 1F`
- `+0x35/+0x36/+0x37: 00 -> 01 01 0F`
- `+0x39..+0x3C: 00 -> FF FF FF FF`

Interpretation:
- this is a stable body family across most of row0, not per-column noise.

### Family C: Col `23` Boundary

Changes relative to Family B:
- `+0x01: 0x17 -> 0x00`
- loses `+0x2D`
- gains `+0x29`, `+0x31`

Interpretation:
- row0 col `23` is a real boundary cell, not just the next member of the `1..22` family.

### Family D: Cols `24..30` Tail

Changes relative to Family B:
- `+0x01: 0x1E -> 0x00`
- drops `+0x1C`
- keeps `+0x24/+0x29/+0x31`
- `+0x2D: 00 -> 07`

Interpretation:
- row0 cols `24..30` are a separate tail run with a different extent code.

### Family E: Col `31` Terminal

Changes relative to Family D:
- `+0x01: 0x1F -> 0x00`
- adds terminal/linkage bytes:
  - `+0x19: 01 -> 00`
  - `+0x1D: 01 -> 00`
  - `+0x38: 00 -> 01`
  - `+0x3D: 00 -> 01`
- `+0x2D: 00 -> 08`

Interpretation:
- row0 col `31` is an explicit terminal marker.
- the added `+0x19/+0x1D/+0x38/+0x3D` reinforces that the max1400 structure is using real grid-control bytes, not only comment-window metadata.

## Row1 Structural Families

Row1 also has `5` distinct diff shapes.

### Family F: Cols `0..22`

Offsets:
- `+0x24`, `+0x29`, `+0x2D`, `+0x31`, `+0x35`, `+0x36`, `+0x37`, `+0x38`, `+0x39`, `+0x3A`, `+0x3B`, `+0x3C`, `+0x3D`

Distinctive values:
- `+0x2D: 00 -> 1F`
- `+0x37: 00 -> 0F`
- `+0x39..+0x3C: 00 -> FF FF FF FF`
- `+0x24/+0x29/+0x31/+0x35/+0x36/+0x38/+0x3D: 00 -> 01`

Interpretation:
- row1 head carries a continuation descriptor aligned with the broad row0 body.

### Family G: Col `23` Boundary

Offsets:
- `+0x05`, `+0x09`, `+0x30`, `+0x34`, `+0x36`

Values:
- `+0x05/+0x09: 00 -> 01`
- `+0x30/+0x34/+0x36: 00 -> 07/10/03`

Interpretation:
- row1 col `23` is a transition cell between the row1 head block and the tail-phase families.

### Families H/I/J: Tail Phase Wave Across Cols `24..31`

The remaining tail is not column-unique. It repeats in a `3`-phase pattern:

- phase H at cols `24/27/30`
- phase I at cols `25/28/31`
- phase J at cols `26/29`

Phase H writes triplets on `+0x00/+0x08/+0x18/+0x20/+0x30/+0x38` with companions:
- `+0x00/+0x18/+0x30: 00 -> 01`
- `+0x08: 00 -> 09`
- `+0x0C/+0x24/+0x3C: 00 -> 10`
- `+0x0E/+0x26/+0x3E: 00 -> 03`
- `+0x20: 00 -> 08`
- `+0x38: 00 -> 0A`

Phase I:
- `+0x08/+0x20/+0x38: 00 -> 01`
- `+0x10: 00 -> 09`
- `+0x14/+0x2C: 00 -> 10`
- `+0x16/+0x2E: 00 -> 03`
- `+0x28: 00 -> 03`

Phase J:
- `+0x00/+0x18/+0x30: 00 -> 09`
- `+0x04/+0x1C/+0x34: 00 -> 10`
- `+0x06/+0x1E/+0x36: 00 -> 03`
- `+0x10/+0x28: 00 -> 01`

Interpretation:
- row1 tail is a phased descriptor wave, not eight unrelated cell patches.
- the repeating `09/10/03` triplets look more like compact extent metadata than visible rung-topology authoring.

## Working Interpretation

This region does not behave like:
- an isolated comment companion blob
- a bag of replay-safe patch bytes
- a purely row0-only or row1-only metadata tweak

It does behave like a coherent structural extent family that:
- starts in the tail of the header table
- spans row0 across multiple boundary classes
- continues through row1 as a head block plus a `3`-phase tail wave
- terminates explicitly at row0 col `31` and the header-table trailer

Most defensible current model:
- max1400 plain-comment support is expressed through row-coupled extent metadata, not only through the comment payload window.
- that metadata is likely extent-like or pseudo-row-like rather than ordinary visible wire topology.
- the earlier crashes from block-split patches make sense under this model because the descriptor family is internally coupled across header tail, row0, and row1.

## Practical Consequence For Next RE Step

Do not resume manual patch splitting inside `0x08FD..0x1A5F` as if the bytes are independent.

The next native experiment should be:
- a fresh row32 no-comment control
- a fresh row32 max1400 control
- same body file: `scratchpad/max1400_comment_body_20260307.txt`

Reason:
- if this is only a low-row entanglement, the same row0/row1 family should persist with little scaling change.
- if this is a true extra extent or pseudo-row family, the row32 pair should expose how the descriptor scales beyond the current 2-row footprint.

## Follow-Up Native Discriminator: Row32 Full-Wire Row0-NOP

Follow-up report:
- `scratchpad/max1400_row32_fullwire_row0nop_native_results_20260307.md`

New result:
- the row32 full-wire row0-NOP pair also shows `69632 -> 73728`
- delta remains **`+4096` exactly**

Implication:
- the extra page is not contingent on empty visible rows
- the "comment row must stay empty" interpretation is now materially weakened

Additional high-signal fact:
- the full-wire row0-NOP extra page is no longer sparse
- it contains `793` non-zero bytes and UTF-16LE strings including:
  - `Segoe UI Variable Display Semilight`
  - `Segoe UI Variable Display Semibold`
  - `SimSun`
  - `NSimSun`
  - `SimSun-ExtB`

Important negative check:
- the comment's RTF payload still advertises only `Arial` in its ANSI `{\fonttbl...}` block
- the UTF-16LE font names above do not come from direct payload spillover
- they appear in the extra page only
- they are absent from the corresponding no-comment and empty-row max1400 row32 captures

Updated interpretation:
- the same extra-page mechanism survives topology changes
- visible rung content affects what the extra page carries
- but does not suppress the extra-page allocation itself
- this fits a comment-owned extent/page family better than an empty-line carrier model
- the extra page now looks plausibly like a terminal descriptor page that can also carry renderer/layout companion records

Additional structural refinement from the full-wire row0-NOP page:
- page `17` decomposes into `4` top-level records, all beginning with `74 76 00 08`
- three `492`-byte records carry `Segoe UI Variable Display` family variants
- one larger `2520`-byte record carries `SimSun` / `NSimSun` / `SimSun-ExtB` fallback-family data
- the first UTF-16LE family name in each record begins at relative offset `+0xAC`

This makes page `17` look like a compact record table for renderer/font fallback metadata.

## Cross-Lane Stability Check: Empty-Row Row32 vs Full-Wire Row0-NOP Row32

Comparing the two row32 max1400-vs-control diff sets over the shared `69632` bytes:

- shared diff offsets between the two lanes:
  - `25042`
- empty-row-only diff offsets:
  - `971`
- full-wire-row0-NOP-only diff offsets:
  - `3327`

Implication:
- about `96%` of the empty-row row32 max1400 diff footprint is also present in the full-wire row0-NOP lane
- about `88%` of the full-wire row0-NOP diff footprint is shared with the empty-row lane

Interpretation:
- the bulk of the row32 max1400 structure is lane-invariant
- topology changes add secondary lane-specific companions
- the most visible lane-specific addition is the richer terminal page `17` font/layout table

This supports a two-layer working model:
1. a large lane-stable comment-owned extent family spanning the repeated body pages
2. a smaller lane-sensitive terminal companion layer that can carry renderer/layout metadata
