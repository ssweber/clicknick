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

More specific decode from `devtools/analyze_max1400_page17.py`:
- the three Segoe records are leaf wrappers:
  - wrapper length field `+0x84 = 0x01EC` matches the full record length
  - paired field `+0x88 = 0x0178`
  - `0x0178 + 0x74 = 0x01EC`, implying a fixed `0x74` descriptor-header span
  - after the wrapper, each leaf contains one `0x144` slot starting at `+0xA8` with tag `03 02 01 02`
- the large CJK record is a container wrapper:
  - wrapper subtype changes from `0x0040` to `0x0020`
  - `+0x84 = 0x01E4`, `+0x88 = 0x0170`, again preserving the same `0x74` gap
  - after its `0xA8`-byte wrapper it contains `5` nested slots at:
    - `0x0A8`, `0x28C`, `0x470`, `0x654`, `0x838`
  - the first four nested slots are full `0x1E4` entries on a stable `0x1E4` stride
  - the fifth is a terminal `0x1A0` slot
  - every nested slot contains:
    - family name at slot `+0x04`
    - duplicate family name at slot `+0x44`
    - style string at slot `+0xC4` (`Regular`)
    - secondary descriptor tag `64 76 00 08` at slot `+0x144`

Implication:
- the large CJK block is not an unrelated one-off blob
- it is a wrapper plus a run of uniform fallback-face subrecords using a slightly richer nested form than the Segoe leaf records

High-confidence interpretation of the wrapper codes:
- `0x012C / 0x015E / 0x0190 / 0x0258` are best treated as weight-like or fallback-class codes, not lengths
- decimal forms are `300 / 350 / 400 / 600`
- the three Segoe wrappers chain through those values in order
- the repeated CJK nested descriptors pin `0x0190` (`400`) while the face names all resolve to `Regular`

Most defensible current model:
- top-level page-17 wrappers are organized by a monotonic font-weight/fallback ladder
- the larger CJK wrapper then expands that ladder entry into multiple concrete fallback faces (`SimSun`, `@SimSun`, `NSimSun`, `@NSimSun`, `SimSun-ExtB`)
- this is materially more consistent with renderer/fallback metadata than with comment-text overflow

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

## Repeated Body Pages Decode: Paired-Row Descriptor Pages

Further offline decoding of row32 pages `2..16` strengthens the extent model.

High-signal facts:
- pages `2..15` are not just "same diff masks"
- they are structured on the ordinary `0x40` cell lattice
- each `0x1000` page holds `64` cell-sized slots:
  - `64 * 0x40 = 0x1000`
  - this matches two ordinary `32`-column row bands per page
- the repeated family therefore looks like a **paired-row descriptor page**, not a free-form blob

### Page-Local Ladder Fields

Across pages `2..15`, the only bytes that vary from page to page are:
- cell `+0x09`
- cell `+0x11`

Those offsets repeat across all `64` slots in the page, so the varying-byte count is:
- `64 * 2 = 128`

Empty-row lane:
- page `2`
  - first half-row `+0x09/+0x11`: `02, 03, 03, ...`
  - second half-row `+0x09/+0x11`: `03, 04, 04, ...`
- page `3`
  - first half-row: `04, 05, 05, ...`
  - second half-row: `05, 06, 06, ...`
- page `15`
  - first half-row: `1C, 1D, 1D, ...`
  - second half-row: `1D, 1E, 1E, ...`
- page `16`
  - first half-row: `1E, 1F, 1F, ...`
  - second half-row: `1F, 20, 20, ...`

Full-wire row0-NOP lane:
- `+0x09` follows the same page ladder as the empty-row lane
- `+0x11` is shifted upward by `0x21`:
  - page `2`: `23/24`
  - page `3`: `25/26`
  - ...
  - page `16`: `3F/40`

Interpretation:
- `+0x09` and `+0x11` are strong candidates for page/row ordinal or extent-index fields
- they do not behave like visible wire-topology authoring
- the full-wire lane preserves the same ordinal ladder while adding a lane-class offset at `+0x11`

### Slot Families Inside A Repeated Body Page

Within page `2`, most of the `64` slots fall into a small number of repeated families.

Empty-row lane:
- one dominant family covers `60/64` slots
- one special family appears at slots `1` and `33`
- one special family appears at slots `9` and `41`

Full-wire row0-NOP lane:
- one dominant family covers `56/64` slots
- paired boundary families appear at:
  - `0/32`
  - `1/33`
  - `8/40`
  - `9/41`

Important pattern:
- the special slots recur exactly `+32` apart
- that is, the same local role repeats once in each half-page row band

Interpretation:
- this is the clearest evidence so far that a body page is modeling two coupled `32`-column row descriptors
- not one flat `4096`-byte payload slab

### Terminal Body Page Versus Repeated Body Pages

Page `16` is a terminal variant of the same paired-row form.

Relative to page `2`:
- the dominant body structure stays intact
- the same `+0x09/+0x11` ladder advances to the terminal values
- only one extra differing offset appears in the empty-row lane, and no broad format break appears in the full-wire lane

Interpretation:
- page `16` is best described as the terminal paired-row descriptor page of the extent chain
- page `17` then sits after that chain as the terminal companion page

## Updated Extent Model After Body-Page Decode

The strongest current offline model is now:

1. pages `2..16` form a hidden comment-owned descriptor chain on the ordinary cell lattice
2. each `0x1000` body page represents two `32`-slot row bands
3. the per-page ladder is carried mainly by slot bytes `+0x09/+0x11`
4. page `17` is not another ordinary body page:
   - in the full-wire lane it is a rich render/fallback companion table
   - in the empty-row lane it is a sparse or regenerated terminal companion

This is a better fit than the older phrasing:
- "empty pseudo rung with no wire markers"

Updated phrasing:
- **hidden paged extent that reuses cell-shaped descriptor slots**

That keeps the useful part of the pseudo-rung idea:
- the structure is laid out on the same row/column lattice

But it avoids the misleading part:
- it is not simply an empty visible rung authored with missing wire flags
