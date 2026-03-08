# Reverse-Engineering View-Switch Heuristic (March 8, 2026)

## Purpose

Capture the conceptual switch that helped crack the clean March 8 plain-comment lane and make it reusable for future lanes.

## Core Idea

Different layers of a binary format want different lenses.

Do not force every question into byte-diff language.
Do not force every question into text language either.

Switch views based on what you are trying to explain:

### 1. Text / ASCII View

Best for:
- embedded payload text
- wrappers
- delimiters
- prefixes / suffixes
- semantic body extraction

Typical questions:
- where does the human-authored content begin and end?
- which bytes are just wrapper around the body?
- does the payload move while the container stays stable?

Good output:
- exact payload window
- fixed wrapper bytes
- body encoding such as `cp1252`, UTF-16LE, or ASCII-like fragments

### 2. Byte / Offset View

Best for:
- exact structural authority
- stale-byte crash causes
- row / column strides
- decisive offsets
- band accounting

Typical questions:
- which offsets actually decide structure?
- which bytes can be donor-preserved safely?
- which mismatch counts are still too large to ignore?

Good output:
- exact offsets
- exact copied ranges
- exact mismatch counts
- explicit donor-backed band templates

### 3. Block / Record View

Best for:
- repeated shapes on a fixed cadence
- lattice pages
- descriptor slots
- moving streams
- continuation programs

Typical questions:
- are these leftover bytes actually records on a stride?
- does a late window just land on the same record family at a different phase?
- can many byte diffs be reduced to a smaller repeating program?

Good output:
- block types
- record cadence such as `0x40` or `0x1000`
- repeating triads / rings / page families
- smaller generators instead of literal byte replay

## Practical Progression

When a lane stalls, use this order:

1. Find the text-bearing payload window.
2. Re-anchor comparisons on the payload or record boundary.
3. Re-check whether the apparent absolute bands are really just shifted views of one moving stream.
4. Only after that, classify the remainder on its natural stride.

This progression prevents a common mistake:
- mistaking one moving structure for many unrelated absolute regions

## Why It Worked On The March 8 Plain-Comment Lane

Old framing:
- metadata after payload
- gap
- row0
- row1
- tail

This was useful for counting bytes but weak for explanation.

The decisive switch was:
- stop treating those surfaces as separate comment families
- re-anchor everything at `payload_end`
- treat the remainder as a continuation stream

That immediately explained:
- why payload-only from a `max1400` donor crashed
- why several separate-looking surfaces collapsed into one shared phase-A stream

Then the second switch was:
- stop treating leftover row1/tail bytes as opaque residual diffs
- classify them on their native `0x40` cadence

That exposed:
- `A/B/C` block types
- a late handoff from `max1400` into solved `fullwire`
- and a medium branch that reduced from literal bytes to:
  - a repeating phase-B program
  - then four `9`-step ordinal rings plus fixed block layouts

## Rule Of Thumb

If one explanation keeps multiplying families, ask:
- is this really many families?
- or is it one moving structure seen through different absolute windows?

If one explanation keeps multiplying byte exceptions, ask:
- is there a record cadence or ring program that is being missed?

That is usually the moment to change views rather than keep counting more isolated mismatches.
