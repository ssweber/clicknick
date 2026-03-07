# Max1400 Row32 Native Pair Results (March 7, 2026)

## Scenario

- `grid_rungcomment_max1400_row32_native_20260307`

Entries:
- `grc32_no_comment_native_20260307`
- `grc32_max1400_native_20260307`

Reference setup:
- row count: `32`
- body file: `scratchpad/max1400_comment_body_20260307.txt`

## Manifest Outcomes

- `2/2` entries recorded `verified_pass`
- observed rows matched expected rows for both entries

Recorded verify-back lengths:
- `grc32_no_comment_native_20260307`: `69632`
- `grc32_max1400_native_20260307`: `73728`

## Key Result

The row32 max1400 native does **not** stay on the ordinary row32 empty-record size.

- row32 no-comment native capture: `69632` bytes (`0x11000`)
- row32 no-comment verify-back: `69632` bytes (`0x11000`)
- row32 max1400 native capture: `73728` bytes (`0x12000`)
- row32 max1400 verify-back: `73728` bytes (`0x12000`)

Delta:
- `+4096` bytes exactly (`0x1000`)
- that is one additional `4 KiB` page/record relative to the no-comment control

This is the decisive outcome from the row32 experiment.

## Why This Matters

The offline hypothesis before this run was:
- maybe the max1400 structure is only row0/row1-local
- or maybe it scales like an extent / pseudo-row family

The row32 outcome strongly favors the second model.

Reason:
- a purely low-row-local comment companion would not naturally predict a full `+4096` page increase in the native capture itself.
- the extra page exists already in the source capture, not just after pasteback.
- the extra page persists through verify-back with the same total length.

## Structural Summary

Overlap comparison between row32 no-comment and row32 max1400 native:
- shared prefix size: `69632`
- differing offsets inside the shared prefix: `26013`
- extra max1400-only tail: `4096` bytes

The extra tail page is sparse, not random bulk data:
- non-zero bytes in the extra page: `12`
- non-zero offsets:
  - `0x004 = 0x01`
  - `0x009 = 0x20`
  - `0x00D = 0x1F`
  - `0x011 = 0x20`
  - `0x015 = 0x01`
  - `0x016 = 0x01`
  - `0x017 = 0xFC`
  - `0x019..0x01C = 0xFF`
  - `0x01D = 0x01`

That sparse trailer strongly resembles descriptor/extent bookkeeping rather than a duplicated visible rung body.

## Repeating Page Pattern In The Shared Prefix

Comparing row32 max1400 native to row32 no-comment native by `0x1000` pages yields `4` page families:

1. page `0`
- `2154` diffs
- includes comment payload start at `0x0294/0x0298`

2. page `1`
- `1458` diffs
- lead-in structural page

3. pages `2..15`
- identical repeated pattern across `14` pages
- `1468` diffs per page

4. page `16`
- `1849` diffs
- terminal/tail variant

Interpretation:
- max1400 scaling at row32 is not just "row0/row1 plus one trailer blob"
- it introduces a repeated per-page family across most of the multi-page body plus a sparse terminal extra page

## Working Interpretation

This result is strong evidence that max1400 native handling scales like an extent / pseudo-row structure.

Current best model:
- the short-row `0x08FD..0x1A5F` family was only the low-row footprint of a larger scaling structure
- at row32, the same phenomenon becomes page-visible:
  - repeated structural families across many pages
  - plus one extra sparse `4 KiB` descriptor page

## Practical Consequence

The row32 experiment materially weakens the old "row0/row1-only entanglement" hypothesis.

It materially strengthens:
- a scaling extent descriptor model
- or an extra hidden/pseudo-row family that allocates additional page-sized structure at high comment length

## Recommended Next Step

Prefer offline comparison before more operator queues:
- map the repeated `0x1000` page families in row32 max1400 vs row32 no-comment
- determine whether the repeated families correspond to:
  - row-pair pages
  - page-local descriptor tables
  - or a hidden comment-owned extent chain

Most useful next native matrix, if more capture work is needed:
- row17 no-comment / max1400
- row9 no-comment / max1400

Reason:
- these intermediate sizes can show exactly when the extra page first appears.
