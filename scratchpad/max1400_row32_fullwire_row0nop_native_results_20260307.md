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
  - row `0` ends with `NOP`
  - rows `1..31` have blank AF
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
- it also persists when row `0` is structurally distinguished by `NOP`
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
