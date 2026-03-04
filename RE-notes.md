# RE Notes: Click Ladder Clipboard (Pair Workflow + Method)

## Why this note exists
This is a retrospective of how we solved a tricky reverse-engineering bug in the Click ladder clipboard format, and a repeatable collaboration flow we can reuse in future sessions.

## Problem we were solving
- Failing scenario: `X001,X002.immediate,->,:,out(Y001)`
- Symptom: pasteback split into multiple rungs with inserted `NOP`
- Observed bad payload sizes during failures: `20480`, `12288`, `73728`
- Expected good payload shape: single rung, `8192` bytes, decodes to intended CSV

## High-level approach that worked
We used a strict loop:
1. Form one narrow hypothesis.
2. Create a minimal patch payload.
3. Paste/copy in Click (manual step).
4. Recapture and inspect markers/length/decode.
5. Keep only findings supported by captures.
6. Narrow field and repeat.

This prevented random edits and kept each experiment attributable.

## Key investigation phases

### 1) Initial candidate hunt (cell bytes)
- Compared working vs broken per-cell 64-byte blocks.
- Candidate bytes emerged (`+0x1A`, `+0x1B`, others).
- Broad patching `+0x1B` across all occupied cells caused crash: stream overlap hazard.

### 2) Safer cell patching
- Switched to profile-only cell patches (`row0 col4..31`, `row1 col0`) to avoid stream cells.
- Result: not sufficient. Splits persisted.
- Important conclusion: `+0x1A/+0x1B` are relevant but not primary gate for this variant.

### 3) Clean baseline harness
- Patched from valid generated `8192` payloads (all markers intact), not from already-fragmented recaptures.
- This removed confounds from malformed source records.

### 4) Region isolation (critical breakthrough)
- Held row1/row2 parity controls.
- Split pre-grid into:
  - pre-header: `0x0000..0x0253`
  - header region: `0x0254..0x0A5F`
- Findings:
  - pre-header native copy alone -> still split
  - header native copy alone -> single-rung success
  - full pre-grid native copy -> single-rung success
- This localized the gate to the header region.

### 5) Minimal decisive bytes
For `two_series_second_immediate`, decisive header bytes were:
- header entry `+0x05 = 0x04` for all 32 entries
- header entry `+0x11 = 0x0B` for all 32 entries
- trailing byte `0x0A59 = 0x04`

After deterministic encoder wrote these values for that family:
- final recapture became `8192`
- decoded correctly as `X001,X002.immediate,->,:,out(Y001)`

## Engineering process that made pair work efficient

## Role split
- Human:
  - Runs Click UI paste/copy steps.
  - Reports visible behavior (split shape, errors like "Out of Memory").
- Agent:
  - Generates patch payloads and focused variants.
  - Runs binary diffs and marker analysis.
  - Maintains narrowing logic and documents conclusions.

## Tight loop protocol
- Use explicit experiment labels (input payload + expected discriminating outcome).
- Run one discriminating test at a time.
- Record outcome immediately in notes/handoff.
- Never merge assumptions from two experiments.

## Capture naming pattern (recommended)
- `..._generated_vN_<what_changed>.bin` for test inputs
- `..._back_after_<test_label>.bin` for Click recaptures
- This kept causality clear and sped up analysis.

## Safety rules for patching
- Avoid patching instruction-stream cells unless stream-safe.
- Prefer profile-region patches before global occupied-cell patches.
- Treat already-fragmented recapture records as potentially confounded sources.
- Validate marker integrity (`0x27xx` positions) before trusting a patch test.

## When stuck: narrowing playbook
1. Control-filtered ranking:
   - subtract mismatches that also appear in known-working cases
2. Region partitioning:
   - pre-header vs header vs grid slices
3. Binary partition tests:
   - copy one region from native at a time
4. Promote only decisive bytes to deterministic encoder logic

## Reuse next conversation
- Start from this checklist:
  1. Reproduce with one failing case and one known-good control.
  2. Build valid generated baseline payload.
  3. Run isolate-by-region tests before broad byte hunting.
  4. Patch minimally, verify in Click, recapture, decode.
  5. Update notes + handoff immediately after each decisive result.

- Keep this definition of done:
  - Pasteback is `8192`
  - markers in expected positions
  - decode equals intended CSV
  - change covered by deterministic rule + automated tests

