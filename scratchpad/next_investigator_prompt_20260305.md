Start by reading:
- HANDOFF: `C:\Users\Sam\Documents\GitHub\clicknick\HANDOFF.md`
- AGENTS workflow guide: `C:\Users\Sam\Documents\GitHub\clicknick\AGENTS.md`

Mission:
Derive a deterministic per-row byte rule for EMPTY multi-row rungs after de-noising known header/session bytes.

Scope guardrails:
1. Do NOT expand codec feature scope or change production behavior yet.
2. Do NOT hand-edit manifest JSON; use capture CLI workflow only.
3. Focus on evidence from native captures first, then isolate with patch cases.

Primary evidence to use:
- Native n-row probes:
  - `scratchpad/captures/gnenp_rows04_native.bin`
  - `scratchpad/captures/gnenp_rows09_native.bin`
  - `scratchpad/captures/gnenp_rows17_native.bin`
  - `scratchpad/captures/gnenp_rows32_native.bin`
- Also compare to known baselines:
  - `grid_empty_row1_single_native.bin`
  - `grid_empty_rows1_2_recapture_native.bin`
  - `grid_empty_rows1_2_3_recapture_native.bin`
- Verify-back outcomes from scaling attempts (`gtes*`, `gtes2*`, `gtes3*`, `gtes4*` verify-back files).

De-noise policy for this task:
- Mask header entry offsets `+0x11`, `+0x17`, `+0x18` across all 32 header entries.
- Treat `+0x05` and `0x0A59` as unresolved (analyze separately; do not assume noise).
- Distinguish session/app noise from row-structural bytes.

What to produce:
1. A row-rule report:
   - `scratchpad/row_rule_inference_empty_multirow_20260305.md`
   - Include table: `offset -> rule/formula -> confidence -> evidence labels`.
2. A minimal isolation scenario queue (small, high-signal patch set) to validate uncertain offsets.
3. Clear statement of what is proven vs still unknown.

Acceptance criteria:
- Proposed rule explains native 4/9/17/32 captures with high match after de-noise.
- Rule identifies row-index and terminal-row behavior (not just row1/row2 special-casing).
- Validation plan is executable through guided verify workflow (`tui -> verify guided -> file source`).

Important:
Current code changes were intentionally rolled back; captures were kept. Stay in capture/isolation lane until rule confidence is high.
