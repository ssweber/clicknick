Read these first:
- c:\Users\ssweb\Documents\GitHub\clicknick\HANDOFF.md
- c:\Users\ssweb\Documents\GitHub\clicknick\AGENTS.md
- c:\Users\ssweb\Documents\GitHub\clicknick\scratchpad\row_rule_inference_empty_multirow_20260305.md

Current baseline:
- Commit: b93988b
- Empty multi-row rule encoder is integrated and validated.
- This task is NON-EMPTY multi-row synthesis exploration only (pre-integration).

Mission:
- Determine minimal structural rules required for non-empty multi-row synthesis.
- Do not integrate non-empty rules into production codec yet.

Hard constraints:
- Do not hand-edit scratchpad/ladder_capture_manifest.json.
- Use only `uv run clicknick-ladder-capture ...` workflow commands.
- Keep production behavior stable; exploration via capture/patch scenarios first.

Required workflow:
1. Build a native non-empty multi-row probe scenario (small, high-signal matrix).
2. Verify native captures with guided file-backed verify.
3. Build patch/synthetic isolation scenarios to separate:
   - header tuple effects
   - row-block structural bytes
   - instruction-stream placement dependencies
4. Run guided verify queues and classify pass/fail/blocked.
5. Narrow to minimal passing byte set(s) per tested non-empty family.

Deliverables:
- New report: `scratchpad/nonempty_multirow_inference_<date>.md`
- Queue docs for each scenario under `scratchpad/`
- Updated HANDOFF with concrete outcomes and next batch recommendation
- Explicit recommendation: “ready for integration” or “more isolation required”

Acceptance criteria:
- At least one non-empty multi-row family has a reproducible synthetic pass path.
- Minimal decisive bytes are identified (not just full-region transplants).
- Evidence includes scenario labels, clipboard lengths, and verify-back outcomes.
