# Ladder Encoder — LLM Workflow

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

## Current state (2026-03-09)

All tested shapes pass Click round-trip:
- Empty rungs (1/2/8/32 rows)
- Wire topologies (horizontal, vertical, T-junction, mixed, partial)
- NOP on AF column (row 0, multi-row with wires)
- Plain comments (1 char, 100 chars, 1400 max, cp1252 specials)
- Edge cases (all 31 cols dashed, vertical B-only, T at column AE)
- Comment + wires (full and sparse, 1-row)
- Comment + NOP (1-row)
- Comment + wires + NOP (1-row)

One known Click rendering quirk: multi-row NOP shows extra visual artifacts (Click bug, not encoder bug).

## Known limitations (not yet implemented)

- Multi-row comments (needs extra 0x1000 page for terminal companion extent)
- Styled comments (RTF bold/italic/underline — crashes under current model)
- Contacts (NO, NC, edge, comparison, immediate variants)
- Coils / AF instructions (out, latch, reset)
- Instruction stream placement

## Important patterns

- **Header seed clobbers comment bytes.** The `HeaderSeed.apply_to_buffer()` writes +0x05/+0x11/+0x17/+0x18 uniformly across all 32 header entries. Comment rungs need entry0 +0x17 = 0x5A. Fix: skip header seed entirely for comment rungs in `_encode_compiled()`.
- **Comment wire encoding uses phase-A stride, not cell grid.** For comment rungs, wire data goes at phase-A-relative positions (+0x21 left, +0x25 right, slot = col_idx + 31), NOT at cell grid +0x19/+0x1D. NOP uses phase-A slot 62 + 0x25. The cell grid wire bytes are all zero in native comment captures.
- **Comment flag is 0x5A universally.** Not grid-dependent (was previously 0x65/0x67). Wire seed bytes (+0x05, +0x11) stay 0x00 for comment rungs. Trailer 0x0A59 = 0x01 for all comment rungs.
- **Native captures are the ground truth.** When something doesn't work, capture a native rung with the same shape and diff against synthetic. The `scratchpad/captures/` directory has reference captures.
- **Verify workflow:** `uv run clicknick-ladder-capture verify prepare --label <label>` loads clipboard, user pastes in Click, copies back, then `verify complete` or `verify run` records result.
