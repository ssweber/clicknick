# Max1400 Row32 Full-Wire Row0-NOP Native Pair Results (March 7, 2026)

## Scenario

- `grid_rungcomment_max1400_row32_fullwire_row0nop_native_20260307`

Entries:
- `grc32fwnop_no_comment_native_20260307`
- `grc32fwnop_max1400_native_20260307`

Reference setup:
- row count: `32`
- visible geometry:
  - full horizontal wire on every row
  - GUI row `0` ends with `NOP`
  - GUI rows `1..31` have blank AF
- body file:
  - `scratchpad/max1400_comment_body_20260307.txt`

## Manifest Outcomes

- `2/2` entries recorded `verified_pass`
- observed rows matched expected rows for both entries

Recorded verify-back lengths:
- `grc32fwnop_no_comment_native_20260307`: `69632`
- `grc32fwnop_max1400_native_20260307`: `73728`

## Key Result

The full-wire row0-NOP pair shows the **same page-scale max1400 jump** as the earlier empty-row row32 pair.

- no-comment native capture: `69632` bytes (`0x11000`)
- no-comment verify-back: `69632` bytes (`0x11000`)
- max1400 native capture: `73728` bytes (`0x12000`)
- max1400 verify-back: `73728` bytes (`0x12000`)

Delta:
- **`+4096` bytes exactly (`0x1000`)**

This is the decisive discriminator for the "comment row must be empty" question.

## Primary Interpretation

The extra max1400 page does **not** require empty rows as carriers.

Why:
- the extra `0x1000` page persists when all `32` visible rows are full horizontal wire rows
- it also persists when GUI row `0` is structurally distinguished by `NOP`
- therefore the scaling page cannot be explained only as a hidden empty-row companion behind the previously tested empty geometry

This materially weakens:
- "the comment-owned extra structure only works because the rows are empty"

It materially strengthens:
- "the extra structure is comment-owned extent metadata that coexists with ordinary rung topology"

## Shared-Prefix Structure

Shared-prefix diff count (`full-wire max1400` vs `full-wire no-comment` over first `69632` bytes):
- `28369`

Page-family breakdown by `0x1000` pages:
- page `0`: `2501` diffs
- page `1`: `1584` diffs
- pages `2..15`: identical repeated diff-offset family, `1592` diffs each
- page `16`: `1996` diffs
- page `17`: extra max1400-only page

The repeated middle-page family is still present:
- pages `2..15` share the same diff-offset signature exactly

So the page-cadence found in the empty-row pair survives topology changes.

## Extra Page Character

Unlike the sparse extra page in the empty-row pair, the full-wire row0-NOP extra page is contentful.

Extra page facts:
- length: `4096`
- non-zero bytes: `793`

The first `0x40` bytes still look descriptor-like:
- early bytes retain the same terminal-row markers seen in the empty-row pair (`0x20`, `0x1F`, `01 01 FC`, `FF FF FF FF 01`)
- but now with additional lead bytes (`+0x05 = 0x01`, `+0x11 = 0x41`)

The remainder of the page includes UTF-16LE strings such as:
- `Segoe UI Variable Display Semilight`
- `Segoe UI Variable Display Semibold`
- `SimSun`
- `NSimSun`
- `SimSun-ExtB`
- `Regular`

The page is not one undifferentiated blob. It splits into `4` top-level blocks:
- block `0x0064..0x024F` (`492` bytes): `Segoe UI Variable Display Semilight`
- block `0x0250..0x043B` (`492` bytes): `Segoe UI Variable Display`
- block `0x043C..0x0627` (`492` bytes): `Segoe UI Variable Display Semibold`
- block `0x0628..0x0FFF` (`2520` bytes): `SimSun` / `@SimSun` / `NSimSun` / `@NSimSun` / `SimSun-ExtB` with `Regular`

All `4` blocks begin with the same header pattern:
- `74 76 00 08`
- followed by a stable field set including:
  - `0x00000002`
  - a block-local code (`0x012C`, `0x015E`, `0x0190`, `0x0258`)
  - stable literals such as `0x24`, `0x2B`, `0x23`, `0x08`, `0x0B`, `0x12`, `0x37`, `0x60`

Within each block, the first font-name string begins at a stable relative offset:
- `+0xAC`

This strongly suggests page `17` is a small record table, not free-form spillover.

## Offline Decode Of Page 17 Record Layout

Repro helper:
- `devtools/analyze_max1400_page17.py`

The wrapper fields are not arbitrary.

For the three Segoe records:
- `+0x84 = 0x01EC` exactly matches the full record length (`492`)
- `+0x88 = 0x0178`
- `0x0178 + 0x74 = 0x01EC`

For the large CJK wrapper:
- `+0x84 = 0x01E4`
- `+0x88 = 0x0170`
- `0x0170 + 0x74 = 0x01E4`

Interpretation:
- the wrapper appears to carry a fixed-structure size pair rather than random literals
- `0x74` is a stable descriptor-header size in both the leaf and nested-slot forms

The large CJK block is a repeated slot run, not one special-case blob.

After the `0xA8`-byte wrapper, it contains nested slots at:
- `0x0A8`
- `0x28C`
- `0x470`
- `0x654`
- `0x838`

Slot facts:
- stride between slot starts: `0x1E4` (`484`) for the first four slots
- first four slots are full `0x1E4` entries
- the fifth slot is a terminal/truncated `0x1A0` entry
- every slot begins with `03 02 01 xx`
- every slot contains:
  - family name at slot `+0x04`
  - duplicated family name at slot `+0x44`
  - style string at slot `+0xC4` (`Regular` for all five CJK slots)
  - secondary descriptor header `64 76 00 08` at slot `+0x144`

Nested CJK slot families:
- slots `0/1`: `SimSun`, `@SimSun`, tag byte `0x02`
- slots `2/3`: `NSimSun`, `@NSimSun`, tag byte `0x31`
- slot `4`: `SimSun-ExtB`, also tag byte `0x31`, but terminal metrics differ

The first four full CJK slots are byte-identical outside:
- the UTF-16LE family names
- the tag byte at slot `+0x03`
- the corresponding class byte inside the secondary descriptor (`0x07` vs `0x36`)

The terminal `SimSun-ExtB` slot keeps the same slot skeleton but changes descriptor-tail fields:
- inner `+0x20`: `0x05 -> 0x00`
- inner `+0x28`: `0x20 -> 0x22`
- inner `+0x3C..+0x3F`: `0xFFE50020 -> 0x20260020`

Interpretation:
- the large block is best described as one wrapper record that owns a run of uniform fallback-face slots
- the last slot is not a different format; it is the same format with terminal coverage/class variations

## Meaning Of The 0x012C / 0x015E / 0x0190 / 0x0258 Codes

Best current offline interpretation:
- they are **weight-like / fallback-class codes**, not lengths or offsets

Why this is the strongest fit:
- decimal forms are `300 / 350 / 400 / 600`
- those values match a plausible Windows font-weight ladder much better than a size or pointer ladder
- the named Segoe records are exactly the kinds of faces that would align with:
  - `350` semilight
  - `400` regular
  - `600` semibold
- the large CJK slots all carry `Regular`, and their nested descriptors pin `0x0190` (`400`) consistently

Most defensible model from the bytes alone:
- top-level wrappers are ordered by a monotonic weight/fallback ladder (`300 -> 350 -> 400 -> 600`)
- the secondary code at wrapper `+0xA0` behaves like the chosen or linked face weight for the wrapped content
- this is why the three Segoe wrappers step into one another (`0x015E`, `0x0190`, `0x0258`)
- and why the CJK wrapper still points back to `0x0190` for its regular fallback faces

This is strong inference, not final proof, but it fits the observed names and record chaining materially better than a record-size interpretation.

Important negative check:
- the actual RTF comment payload at `0x0298` still uses a simple ANSI font table with `Arial`
- these UTF-16LE font names do **not** appear in the RTF payload
- they appear only in the extra page
- they are also absent from:
  - the full-wire row0-NOP no-comment capture
  - the empty-row max1400 capture

Interpretation:
- the extra page is still part of the same scaling mechanism
- but in the full-wire row0-NOP lane it carries richer display/font-related data instead of being almost empty
- this makes the extra page look more like a renderer/layout companion page than direct comment-text overflow
- more specifically, it looks like a terminal record table whose entries enumerate display/fallback font families

## Updated Working Model

Best current interpretation:
- the max1400 structure is not an "empty comment row" that must remain blank
- it is a comment-owned extent/page family that can coexist with populated rung rows
- visible rung topology changes how much data the extra page carries, but do not suppress the extra-page allocation itself
- page `17` now looks like a mixed descriptor/render-companion page:
  - sparse descriptor-only in the empty-row lane
  - richer font/layout companion in the full-wire row0-NOP lane

Most defensible current refinement:
- empty-row row32 pair:
  - proved the extra page exists in native source capture
- full-wire row0-NOP row32 pair:
  - proves the extra page is not contingent on empty rows
- together:
  - strongly favor a hidden extent/descriptor chain owned by the comment lane, not a row-local empty-line carrier trick
  - and suggest that the terminal extra page can host renderer/layout companions, not only minimal extent markers

Cross-lane stability check against the empty-row row32 pair:
- shared diff offsets over the common `69632` bytes:
  - `25042`
- empty-row-only diff offsets:
  - `971`
- full-wire-row0-NOP-only diff offsets:
  - `3327`

Interpretation:
- most of the row32 max1400 footprint is shared across both lanes
- the lane-specific increment is secondary, not primary
- so the conceptual model should be:
  - a large lane-stable comment extent family through the body pages
  - plus a lane-sensitive terminal render/layout companion page

## Additional Offline Refinement: Shared Body Pages Look Like Paired-Row Descriptors

The repeated body-page family can now be described more concretely.

Shared across the empty-row and full-wire row0-NOP lanes:
- pages `2..15` are built on the ordinary `0x40` cell stride
- each `0x1000` page therefore contains `64` cell-sized slots
- the special slot roles recur at `+32`, which strongly suggests two coupled `32`-column row bands per page

Across pages `2..15`:
- the only page-to-page varying bytes are slot `+0x09` and slot `+0x11`
- those fields advance monotonically by page

Lane relationship:
- empty-row lane:
  - `+0x09` and `+0x11` carry the same ordinal ladder
- full-wire GUI-row0-NOP lane:
  - `+0x09` keeps the same ladder
  - `+0x11` is shifted upward by `0x21`

Interpretation:
- the shared body pages are best treated as **paired-row descriptor pages** inside a hidden comment-owned extent chain
- the full-wire lane does not replace that body chain; it overlays a lane-class shift on top of the same ordinal structure

This is a better fit than describing the mechanism as:
- a literal empty pseudo rung with no wire markers

Current best wording:
- **hidden paged extent that reuses cell-shaped descriptor slots**

## Recommended Next Step

Offline recommendation:
- treat the "comment row must be empty" hypothesis as materially weakened
- update the row32 page-family write-up so the extent model explicitly allows coexistence with non-empty topology

If more native capture work is still needed after that:
- row9 no-comment / max1400
- row17 no-comment / max1400

Purpose:
- determine when the extra `0x1000` page first appears
- check whether the richer extra-page content only emerges after certain row/topology thresholds
