# Phase 3 Comment Stream Model (March 8, 2026)

## Scope

Explain the clean March 8 plain-comment structure in a way that is more causal than band-by-band diff accounting.

This report uses only:
- `grcecr_short_native_20260308`
- `grcecr_medium_native_20260308`
- `grcecr_max1400_native_20260308`

## Core Structural Finding

The clean March 8 plain-comment captures are best explained as:

1. a plain RTF payload block
2. followed immediately by a payload-end-anchored continuation stream

This continuation stream is not confined to one named band.
It spills through:
- metadata post-payload window
- gap band
- row0 band
- and for larger comments also row1 and the tail band

## Phase A: Universal Continuation Stream Prefix

Measured from the true payload end:
- the aligned continuation stream is identical across short, medium, and max1400 for exactly `0xFC8` bytes

That common prefix covers, for every clean plain-comment case:
- all bytes in `0x08FD..0x0A5F`
- the entire row0 band `0x0A60..0x125F`

Relative band positions from payload end:

### Short

- post-payload start: `0x05EC`
- row0 start: `0x074F`
- row1 start: `0x0F4F`
- tail start: `0x174F`

### Medium

- post-payload start: `0x04F1`
- row0 start: `0x0654`
- row1 start: `0x0E54`
- tail start: `0x1654`

### Max1400

- post-payload start: `0x0079`
- row0 start: `0x01DC`
- row1 start: `0x09DC`
- tail start: `0x11DC`

Interpretation:
- the same continuation stream lands in different absolute byte bands only because `payload_end` moves with comment length
- this explains why the same structural family looked like separate metadata/gap/row0 problems before alignment

## Exact Phase A Block Shape

Immediately after `payload_end`, all three clean comment captures enter the same `0x40`-stride block stream.

Observed per-block non-zero bytes in the first phase:
- `+0x00 = 0x01`
- `+0x09 = block_ordinal`
- `+0x11/+0x12/+0x13 = 0x01 0x01 0xFC`
- `+0x15..+0x18 = 0xFF 0xFF 0xFF 0xFF`
- `+0x19 = 0x01`
- `+0x38 = 0x01`

The first blocks are:
- block `0`: ordinal `1`
- block `1`: ordinal `2`
- block `2`: ordinal `3`
- and so on

This continues identically across all three clean comment lengths through aligned offset `0xFC7`.

## Why Payload-Only Crashed

The payload-only probe kept stale donor bytes in:
- metadata post-payload window `0x08FD..0x0A53`
- gap band `0x0A54..0x0A5F`

Under the new model, those bytes are not passive metadata.
They are part of the same continuation stream that must begin at the new `payload_end`.

So shortening the payload without moving the continuation stream leaves the stream anchored at the wrong absolute location.

That explains the clean March 8 payload-only crashes more naturally than a generic “bad companion bytes” label.

## Phase B: Length-Class Branch

After aligned offset `0xFC8`, the stream stops being universal.

Observed behavior:
- short:
  - phase B is effectively absent
  - aligned bytes from about `0xFC8` onward are mostly zero
- medium and max1400:
  - phase B is present
  - it keeps the same `0x40` block cadence
  - blocks carry recurring `0x10/0x03` pairs and varying small ordinals such as `0x07/0x09/0x0A/0x0D`

Conservative interpretation:
- phase B is a second-stage continuation or extent family
- it is not unique per absolute band
- it is another payload-end-anchored stream phase whose exact ordinal sequence depends on the comment length class

## Transplant Result That Supports The Model

If a donor continuation stream is copied onto an empty baseline and re-anchored at the target payload end:

- post-payload window diffs versus target: `0`
- row0 band diffs versus target: `0`

This is true for every donor/target pair among:
- short
- medium
- max1400

What remains after that transplant:
- row1 and tail differences only

Examples:

### Donor `short` -> target `medium`

- post-payload diffs: `0`
- row0 diffs: `0`
- row1 diffs: `388`
- tail diffs: `688`

### Donor `short` -> target `max1400`

- post-payload diffs: `0`
- row0 diffs: `0`
- row1 diffs: `88`
- tail diffs: `448`

### Donor `max1400` -> target `short`

- post-payload diffs: `0`
- row0 diffs: `0`
- row1 diffs: `531`
- tail diffs: `5`

Interpretation:
- phase A explains the entire post-payload and row0 problem
- remaining work is the phase B / later-stream family in row1 and tail

## Updated Working Model

Plain-comment synthesis is now closer to:

1. write exact plain payload bytes
2. generate the universal phase A continuation stream at `payload_end`
3. generate the length-class-specific phase B continuation stream only if needed

This is a better working model than:
- separate metadata rules
- separate gap rules
- separate row0 companion rules

Those regions are at least partly the same continuation stream seen at different absolute offsets.

## Best Next Offline Move

Do not continue treating row0 as an independent comment family first.

Better next target:
- isolate a generator for the universal phase A stream
- then classify the phase B branch into:
  - absent/short
  - medium-like
  - max-like

That path now looks materially closer to synthesis than the earlier band-by-band view.
