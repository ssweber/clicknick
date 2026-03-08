# Phase 3 Plain Comment Exact Verify Results (March 8, 2026)

## Scenario

- `grid_plain_comment_exact_20260308`

## Outcome

All three exact March 8 plain-comment synth payloads verified pass in Click.

Cases:
- `gpcx_short_exact_20260308`
  - status:
    - `verified_pass`
  - event:
    - `copied`
  - clipboard len:
    - `8192`
- `gpcx_medium_exact_20260308`
  - status:
    - `verified_pass`
  - event:
    - `copied`
  - clipboard len:
    - `8192`
- `gpcx_max1400_exact_20260308`
  - status:
    - `verified_pass`
  - event:
    - `copied`
  - clipboard len:
    - `8192`

Observed rows:
- short:
  - comment row preserved
  - empty 1-row rung preserved
- medium:
  - comment row preserved
  - empty 1-row rung preserved
- max1400:
  - empty 1-row rung preserved
  - manifest row tracking does not capture the full long comment body, so this round should still be read primarily as paste-safety plus structural success

## Accepted Result

The clean March 8 plain-comment model is now:
- exact offline
- and live verify-backed

Conservative scope:
- this is proven for the clean March 8 plain-comment lane only
- styled comments remain out of scope
- generalized comment synthesis beyond the March 8 clean family remains a separate question

## Conceptual Switch That Unblocked The Lane

The decisive switch was moving from:
- static absolute-band thinking

to:
- payload-end-anchored stream thinking

What changed in practice:
- the old framing treated metadata post-payload bytes, the gap, row0, row1, and tail as separate comment families
- the new framing asked:
  - what if those surfaces are just different absolute windows onto one continuation stream whose start moves with `payload_end`

Why that mattered:
- it explained the payload-only `max1400` crash causally:
  - the payload was shortened, but the continuation stream was left anchored at the old end
- it collapsed several apparently unrelated surfaces into one phase-A stream
- that left a much smaller residual problem:
  - the later phase-B branch

Second switch inside the residual problem:
- stop counting leftover row1/tail bytes as opaque residue
- instead classify them on their native `0x40` block cadence

That exposed:
- a repeating `A/B/C` block lattice
- exact late handoff from `max1400` into solved no-comment `fullwire`
- and a medium branch that could be reduced from:
  - literal bytes
  - to a repeating phase-B program
  - then further to four `9`-step ordinal rings plus fixed block layouts

Short version:
- the crack came from re-anchoring by `payload_end`, then treating the remainder as a moving stream and block program rather than as many unrelated absolute bands
