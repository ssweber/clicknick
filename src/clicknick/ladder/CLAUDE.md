# Ladder Encoder — CLAUDE Workflow

## Shell hygiene
Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
This triggers Claude Code's quoted-newline security check and stalls the workflow.
Instead:
- Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
- For quick Python one-liners, keep them truly single-line.

## Roles

**Lead (you):** High-level investigator. You read the user's results, decide what to try next, make code changes to `encode.py` / `codec.py`, and run tests (`make test`). You write prompts and interpret assistant findings. You own the encode pipeline and commit decisions.

**Assistant (subagent):** Scut work. Binary diffing, byte-level analysis, building verify queue entries, generating patch payloads, narrowing isolation batches. Give them a self-contained prompt with file paths and specific instructions. They should always read `AGENTS.md` and `encode.py` first.

## How to delegate

Write a prompt block the user can paste to a separate Claude Code session. Include:
- What files to read first (`AGENTS.md`, `encode.py`, relevant captures)
- Specific byte-level tasks (diff two .bin files, check offsets, build patch payloads)
- What NOT to do (don't edit source, don't run verify, etc.)
- What to report back

## Key files

- `encode.py` — Unified encoder. Public API is `encode_rung()`. Comment framing is hardcoded (prefix/suffix literals + `comment_phase_a.bin` resource).
- `codec.py` — Compatibility shim. Routes shorthand rows through `encode_rung()`. Applies header seed for non-comment rungs. `_encode_compiled()` is the integration point.
- `empty_multirow.py` — Scaffold synthesis (steps 1-2 of the pipeline).
- `topology.py` — Cell offset math, wire flag constants.
- `legacy_codec.py` — `HeaderSeed`, `RungGrid` decode, scaffold loading. Used by codec.py for decode and header seed extraction.
- `AGENTS.md` — Capture/verify CLI guide. Give this to assistants.
- `resources/comment_phase_a.bin` — Phase-A continuation stream (4040 bytes, native-derived).
- `resources/grcecr_empty_native_20260308.bin` — Native empty donor (kept for reference diffing, not used in encode path).

## Current state (2026-03-10)

All tested shapes pass Click round-trip:
- Empty rungs (1/2/8/32 rows)
- Wire topologies (horizontal, vertical, T-junction, mixed, partial)
- NOP on AF column (row 0, multi-row with wires)
- Edge cases (all 31 cols dashed, vertical B-only, T at column AE)
- **Comment + empty (2-row)**
- **Comment + NOP on row 1 (2-row)**
- **Comment + sparse wire on both rows (2-row)**
- **Comment + empty (3-row)**
- **Comment + NOP on row 2 (3-row)**
- **Comment + wire on rows 1+2, including same-col (3-row)**
- **Comment + empty (4-row)**

## Known regressions

- **1-row comment rungs broken** — pastes as full wire, no comment visible.
  Was previously verified (empty, wire, NOP combos). Needs investigation.
  2+ row comment rungs are unaffected.

## Known limitations (not yet implemented)

- Multi-row comments with vertical wire (T on row 0, receiving wire on row 1; native capture exists but not yet verified as synthetic)
- Styled comments (RTF bold/italic/underline — crashes under current model)
- Contacts (NO, NC, edge, comparison, immediate variants)
- Coils / AF instructions (out, latch, reset)
- Instruction stream placement

## Validation rules

- T/| tokens rejected on the last row (vertical-down has nowhere to go)
- T/| tokens rejected on column A
- At most one NOP per rung (multiple NOPs render as tiny dots in Click)

## Important patterns

- **Header seed clobbers comment bytes.** The `HeaderSeed.apply_to_buffer()` writes +0x05/+0x11/+0x17/+0x18 uniformly across all 32 header entries. Comment rungs need entry0 +0x17 = 0x5A. Fix: skip header seed entirely for comment rungs in `_encode_compiled()`.
- **Comment wire encoding uses phase-A stride, not cell grid.** For comment rungs row 0, wire data goes at phase-A-relative positions (+0x21 left, +0x25 right, +0x29 down, slot = col_idx + 31), NOT at cell grid +0x19/+0x1D. NOP uses phase-A slot 62 + 0x25. The cell grid wire bytes are all zero in native comment captures.
- **Comment row 1+ wire/NOP uses continuation stream records.** 32 records (one per column) after phase-A. Wire at +0x19/+0x1D. NOP at cont[31] +0x19=1 AND +0x1D=1, plus cont[0] +0x15=1.
- **No payload padding.** Phase-A starts immediately after the RTF payload — no cell-size alignment. Click locates phase-A and cont records by reading the payload length field.
- **Comment flag varies by session (0x5A, 0x41, 0x67, 0x65).** Not grid-dependent. Encoder uses 0x5A; Click accepts all observed values.
- **Native captures are the ground truth.** When something doesn't work, capture a native rung with the same shape and diff against synthetic. The `scratchpad/captures/` directory has reference captures.
- **Verify workflow:** `uv run clicknick-ladder-capture verify prepare --label <label>` loads clipboard, user pastes in Click, copies back, then `verify complete` or `verify run` records result.
