# Phased Prompt: AF `NOP`, `RungComment`, and CSV Wire-Only Synthesis (March 6, 2026)

## Read First (in order)
1. `HANDOFF.md`
2. `AGENTS.md`
3. `scratchpad/nonempty_multirow_horiz_vert_inference_20260306.md`
4. `scratchpad/nonempty_multirow_implementation_plan_20260306.md`
5. `scratchpad/click_clipboard_map.html`

## Why This Is Phased
Do not run this as one combined batch. Execute in **three gated steps** so failures are attributable:
1. AF behavior (`NOP` vs `...`)
2. `RungComment` storage
3. CSV -> wire-only prove-out

Proceed to the next phase only after the current phase acceptance gate is met.

## Non-Negotiable Rules
- Do **not** hand-edit `scratchpad/ladder_capture_manifest.json`.
- Use only `uv run clicknick-ladder-capture ...` workflow commands.
- Do not use retired tools listed in `AGENTS.md`.
- Keep production codec behavior stable during RE/isolation.

## Phase 1 — AF `NOP` vs `...` (Empty) Isolation

### Goal
Find minimal decisive bytes that differentiate AF empty (`...`) from AF `NOP`.

### Work
1. Build native donor matrix with matched topology where AF intent changes only:
   - AF empty
   - AF `NOP`
   - rows: `1`, `2`, and one scaled row count (`9` or `32`)
2. Build patch isolation variants:
   - AF-adjacent transplants only
   - single-byte and small-group ablations
   - full-region transplant allowed only as control
3. Run guided file-backed verify queue and record:
   - `status`, `event`, `clipboard_len`
   - observed row/topology differences

### Deliverables
- Report section/file: `scratchpad/phase1_af_nop_inference_<date>.md`
- Queue doc: `scratchpad/grid_af_nop_vs_empty_verify_queue_<date>.md`
- Case spec: `scratchpad/phase1_af_nop_case_specs_<date>.json`

### Acceptance Gate (Phase 1)
- At least one reproducible synthetic path for AF `NOP`.
- Minimal decisive AF byte set identified (not just full-region copy).

## Phase 2 — `RungComment` Mapping

### Goal
Map where and how `RungComment` is stored, including flags/length/termination behavior.

### Work
1. Native capture matrix on fixed topology (and fixed AF policy from Phase 1):
   - no comment
   - short ASCII
   - medium ASCII
   - max-length probe
   - optional UTF/non-ASCII probe (only if UI supports cleanly)
2. Identify:
   - comment byte range
   - enable/flag bytes
   - length/termination rules
   - companion bytes affected by length
3. Patch replay:
   - inject comment bytes into non-comment baseline
   - verify deterministic roundtrip behavior

### Deliverables
- Report section/file: `scratchpad/phase2_rungcomment_inference_<date>.md`
- Queue doc: `scratchpad/grid_rungcomment_mapping_verify_queue_<date>.md`
- Case spec: `scratchpad/phase2_rungcomment_case_specs_<date>.json`

### Acceptance Gate (Phase 2)
- Replay-confirmed minimal comment byte model (flag + content + any required companions).

## Phase 3 — CSV -> Wire-Only Prove-Out

### Goal
Prove we can take normal CSV input and synthesize accepted wire-only payloads by intentionally dropping contacts/instructions.

### Work
1. Parse representative CSV rows (single + multi-row, include `-`, `|`, `T`).
2. Convert to wire topology only:
   - drop contacts
   - drop AF instruction semantics
3. Apply AF placeholder policy from Phase 1:
   - AF empty or AF `NOP` as proven.
4. Optionally apply `RungComment` model from Phase 2.
5. Verify with guided queue.

### Required Proof Set
- At least one mixed topology case at multi-row scale.
- At least one deep-row case (`>=9` rows).

### Deliverables
- Report section/file: `scratchpad/phase3_csv_wireonly_inference_<date>.md`
- Queue doc: `scratchpad/grid_csv_wireonly_dropinstr_verify_queue_<date>.md`
- Case spec: `scratchpad/phase3_csv_wireonly_case_specs_<date>.json`

### Acceptance Gate (Phase 3)
- At least one CSV-derived wire-only synthetic path passes verify with expected topology and stable clipboard length.

## Final Round-Up Required
- Consolidated report:
  - `scratchpad/nop_af_rungcomment_inference_<date>.md`
  - include: proven vs assumed vs unknown
- `HANDOFF.md` update with:
  - phase outcomes
  - minimal byte sets
  - integration recommendation

## Operator Run Path (for each queue)
- `uv run clicknick-ladder-capture tui`
- `3` -> `g` -> `f` -> `<scenario filter>`

For copied events:
- paste in Click
- copy back in Click
- press `c`

Send `done` after each queue.

## Working Hypothesis (to confirm, not assume)
- Existing `RungGrid.nickname` offsets may overlap with Click `RungComment`, but this is not proven until Phase 2 native+replay evidence confirms it.
