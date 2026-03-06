# Context
Read first:
- `HANDOFF.md`
- `AGENTS.md`
- `scratchpad/row_rule_inference_empty_multirow_20260305.md`

Task family update: we are now on **non-empty multi-row synthesis** focusing on **horizontal and vertical line rules**.

## Mission
Determine and isolate deterministic byte-level rules for non-empty multi-row payloads with emphasis on:
1) intra-row horizontal line continuity (wire spans in the same row)
2) inter-row vertical line continuity (down links across rows)

Production stability rule: **do not integrate into codec yet**. This turn is capture/verification-driven RE and planning only.

## Useful helper context (new + optional)

1) Noise normalization helper (new)
- `devtools/noise_apply.py` now contains `mask_session_noise(payload: bytes) -> bytes`.
- Use it as a pre-compare de-noise step during RE (it currently zeroes:
  - `0x0008..0x00B8`
  - `0x00B8..0x01F8`
  - header entry bytes `+0x11`, `+0x17`, `+0x18` across 32 entries at `0x0254`)
- This is a session-noise normalization pass, not a structural rule proof.
- It is currently a utility function (not wired as a new CLI flag yet), so call it directly in scripts/analysis flow where needed.

2) Existing empty-lane baseline (reuse only, not proof for non-empty)
- `src/clicknick/ladder/empty_multirow.py` already provides deterministic empty multi-row synthesis:
  - row count / length formulas
  - row/column byte formulas for key structural slots
  - optional probes for `set_cell_0b` and `set_terminal_15`
- For this turn (non-empty horizontal/vertical investigation), treat this as:
  - a reference baseline,
  - a possible deterministic donor/scaffold source,
  - not a direct template to generalize from.
- Non-empty findings should be proven in dedicated captures and isolation rounds first.

## Non-negotiable constraints
- Do NOT hand-edit `scratchpad/ladder_capture_manifest.json`.
- Use workflow CLI only:
  - `uv run clicknick-ladder-capture ...`
- Keep operator flow in capture/queue/verify artifacts.
- For narrowing/isolation, do NOT manually edit failed rungs.
- Log concise outcomes: `status`, `event`, `clipboard_len`; short note only for ambiguous cases.
- Preserve existing production behavior for now (no codec edits).

## Scope
Primary target:
- Non-empty multi-row lanes (2-row first, then 3/4-row expansion if stable).
- Focus on byte writes that specifically control:
  - horizontal wire metadata
  - vertical wire metadata
  - terminal/edge conditions in non-empty grids

## Prioritized execution plan

### Track H: Horizontal-line isolation
1. Build a high-signal native scenario set for 2-row non-empty lanes with explicit horizontal segments.
   - Minimal variants: isolated row0-only, row1-only, and both rows with same/different extents.
2. Capture all variants.
3. Generate session de-noise baseline (keep policy narrow and explicit).
4. Patch-synthesis ablation:
   - Hold everything except candidate horizontal offsets.
   - Find minimal offset set where acceptance diverges (pass/fail).
5. Capture and record pass/fail matrix for horizontal candidates.

### Track V: Vertical-line isolation
1. Build native 2-row/3-row non-empty donors with vertical continuity in the same column.
2. Build isolation patch variants that preserve topology but toggle suspected vertical line offsets.
3. Run guided queue verify and classify outcomes.
4. Extend to 3-4 rows only after 2-row rule is stable.

### Track X: Growth/generalization
1. Validate strongest 2-row horizontal and vertical candidate rules against 3-row and 4-row non-empty lanes (if time permits).
2. Confirm which bytes scale with row index and which are per-row offsets.

## Required outputs (mandatory)
1. Report:
- `scratchpad/nonempty_multirow_horiz_vert_inference_20260306.md`
2. Queue docs:
- `scratchpad/grid_nonempty_multirow_horiz_verify_queue_20260306.md`
- `scratchpad/grid_nonempty_multirow_vert_verify_queue_20260306.md`
(append `_01`, `_02` if needed)
3. Update:
- `HANDOFF.md` with evidence and next recommendation (`ready for integration` / `more isolation required`).
4. (Optional if discovered) synthetic helper notes in report: candidate minimal byte sets for non-empty lanes.

## Verification protocol
For each scenario run, record:
- `label`
- `scenario`
- `expected rows`
- verify `status` (`verified_pass|verified_fail|blocked|unverified`)
- `clipboard_event`
- `clipboard_len`
- short note only for exceptions/ambiguity

## Acceptance criteria
- At least one reproducible non-empty 2-row synthetic path for each:
  - horizontal continuity
  - vertical continuity
- Minimal decisive candidate byte sets identified (not full-row transplants).
- Explicit boundary statement:
  - what is proven,
  - what is assumed,
  - what remains unknown.
- One clear recommendation:
  - ready for implementation planning, or
  - more isolation required.

## Commands (operational defaults)
- For capture/verify execution:
  - `uv run clicknick-ladder-capture tui`
- In TUI: `3` → `g` → `f` (verify, guided, file-backed queue)
- For queue docs and scenario naming, include concise labels and exact scenario filters.
