# Phase 2 RungComment Mapping Inference (March 6, 2026)

## Scope
- Phase: `2` from `scratchpad/nop_af_rungcomment_prompt_20260306.md`
- Scenario: `grid_rungcomment_mapping_20260306`
- Goal: map `RungComment` storage bytes (flag, content, length/termination, companions).

## Setup Completed
- Added native matrix entries via workflow CLI (no manifest hand edits).
- Fixed topology/AF policy:
  - row: `R,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,:,NOP`
- Labels:
  - `grc_no_comment_native`
  - `grc_short_ascii_native`
  - `grc_medium_ascii_native`
  - `grc_maxlen_probe_native`
  - `grc_utf8_probe_native`
  - `grc_style_plain_native`
  - `grc_style_bold_native`
  - `grc_style_italic_native`
  - `grc_style_underline_native`
  - `grc_maxlen_1396_native`
  - `grc_style_mixed_selection_native`

## Artifacts
- Case spec: `scratchpad/phase2_rungcomment_case_specs_20260306.json`
- Queue doc: `scratchpad/grid_rungcomment_mapping_verify_queue_20260306.md`

## Native Outcomes (Current)
- Scenario `grid_rungcomment_mapping_20260306`: `11/11` verified pass.
- All events are `copied`; verify-back lengths are `8192`.
- Operator notes confirmed:
  - true max comment length is `1400` characters
  - UI supports `bold`, `italic`, and `underline` styles

## Preliminary Byte Findings (from captured set)
- Comment payload is stored as an RTF-like ANSI string.
  - observed prefix: `{\rtf1\ansi\ansicpg1252...`
  - UTF degree symbol appears as escaped RTF sequence (`\'b0`).
- Candidate length and payload fields:
  - dword at `0x0294` tracks comment payload length (+ NUL terminator).
  - payload starts at `0x0298`.
  - observed rule on captured variants: `len_dword = payload_byte_count + 1`.
- No-comment baseline has length dword `0x00000000` and no RTF payload at `0x0298`.
- Max-length correction evidence:
  - `grc_maxlen_1396_native` capture contains a `1400`-char body (label retained for continuity).
  - captured body tail includes appended `1234`, confirming the corrected bound.
- Style encoding evidence (plain vs style probes) appears in RTF token stream:
  - bold: `\b ... \b0`
  - italic: `\i ... \i0`
  - underline: `\ul ... \ulnone`
  - no separate style bytes outside comment payload are currently required by evidence.
- Mixed inline-style probe (`grc_style_mixed_selection_native`) confirms segment-level token combinations:
  - `BOLDTXT` section: `\b ... \b0`
  - `BOLDITALIC` section: `\b\i ... \b0\i0`
  - `BTU` section: `\ul\b ... \ulnone\b0`
  - implication: style is text-span markup inside one RTF payload, not row-global flags.

## Patch Isolation Setup (Ready)
- New scenario: `grid_rungcomment_patch_isolation_20260306`
- Case count: `12` patch payloads (file-backed)
- Case spec: `scratchpad/phase2_rungcomment_patch_case_specs_20260306.json`
- Queue doc: `scratchpad/grid_rungcomment_patch_isolation_verify_queue_20260306.md`
- Batch includes:
  - length+payload vs length-only vs payload-only controls
  - terminator/length coupling probe
  - length-zero reset probe
  - style payload transplants (bold/italic/underline)
  - max1400 payload replay probes

## Pending Operator Actions
1. Run patch queue verify:
   - `uv run clicknick-ladder-capture tui`
   - `3 -> g -> f -> grid_rungcomment_patch_isolation_20260306`
2. Send `done`.
3. We will classify minimal replay requirements and close the Phase 2 acceptance gate.

## Gate Status
- Acceptance gate not yet evaluated.
- Current status: `native_matrix_complete_patch_isolation_pending`.
