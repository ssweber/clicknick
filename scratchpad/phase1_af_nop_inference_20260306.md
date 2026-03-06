# Phase 1 AF `NOP` vs Empty Inference (March 6, 2026)

## Scope
- Phase: `1` from `scratchpad/nop_af_rungcomment_prompt_20260306.md`
- Scenario: `grid_af_nop_vs_empty_20260306`
- Goal: identify minimal decisive bytes that differentiate AF empty (`...`) from AF `NOP`.

## Setup Completed
- Added native matrix entries to manifest via workflow CLI (no manifest hand edits).
- Matrix dimensions:
  - AF mode: `empty`, `NOP`
  - row counts: `1`, `2`, `9`
  - NOP row placements currently tracked: `row0`, `row1`, `row4`, `row8`
- Labels:
  - `gafn_rows01_empty_native`
  - `gafn_rows01_nop_native`
  - `gafn_rows02_empty_native`
  - `gafn_rows02_nop_native`
  - `gafn_rows02_nop_row1_native`
  - `gafn_rows09_empty_native`
  - `gafn_rows09_nop_native`
  - `gafn_rows09_nop_row4_native`
  - `gafn_rows09_nop_row8_native`

## Artifacts
- Case spec: `scratchpad/phase1_af_nop_case_specs_20260306.json`
- Queue doc: `scratchpad/grid_af_nop_vs_empty_verify_queue_20260306.md`

## Native Outcomes (Completed)
- Scenario `grid_af_nop_vs_empty_20260306`: `9/9` verified pass.
- All events were `copied`.
- Verify-back lengths:
  - rows1 cases: `8192`
  - rows2 cases: `8192`
  - rows9 cases: `24576`
- All observed rows matched expected rows exactly.

## Operator Note (Important)
- Direct copy/paste workflow could not place `NOP` on continuation rows reliably.
- Insert-row-above/insert-row-below workflow preserved non-first-row `NOP` placement.
- Implication: when synthetic replay does not match, treat authoring-path dependence as a risk signal and record it explicitly in notes.

## Byte-Level Findings
- Row0 `NOP` placement (`rows1/rows2/rows9`) differs from empty by one grid byte:
  - `0x123D`: row0 col31 `+0x1D` (`0x00 -> 0x01`)
- Non-first-row `NOP` placements (rows2 row1, rows9 row4/row8) showed many raw diffs, but grid-region diffs were stable and minimal:
  - `0x0A75`: row0 col0 `+0x15` (`0x01 -> 0x00`)
  - `target_row col0 +0x15`: (`0x00 -> 0x01`)
  - `target_row col31 +0x1D`: (`0x00 -> 0x01`)
- Concrete grid diff sets observed:
  - rows2 row1: `0x0A75`, `0x1275`, `0x1A3D`
  - rows9 row4: `0x0A75`, `0x2A75`, `0x323D`
  - rows9 row8: `0x0A75`, `0x4A75`, `0x523D`

## Patch Isolation Setup (Ready)
- New scenario: `grid_af_nop_patch_isolation_20260306`
- Case count: `17` patch payloads (file-backed)
- Case spec: `scratchpad/phase1_af_nop_patch_case_specs_20260306.json`
- Queue doc: `scratchpad/grid_af_nop_patch_isolation_verify_queue_20260306.md`
- Batch includes:
  - row0 synthetic single-byte controls (`+0x1D` only)
  - non-first-row full 3-byte grid-diff controls
  - ablations/sufficiency probes for `{target +0x1D, target +0x15, row0 +0x15 clear}`

## Patch Isolation Outcomes (Completed)
- Scenario `grid_af_nop_patch_isolation_20260306`: `17` cases total.
  - `11` verified pass
  - `6` verified fail
  - all events `copied`
- Row0 synthetic controls:
  - `gafnp01r0_hright_only`: pass
  - `gafnp09r0_hright_only`: pass
  - implication: row0 NOP is reproducible with one-byte synthetic write (`row0 col31 +0x1D = 1`).
- Non-first-row sufficiency/necessity at tested rows (`row1`, `row4`, `row8`):
  - `target +0x1D` only: fail
  - `target +0x15` only: fail (rows2 probe)
  - `target +0x15` + `target +0x1D`: pass
  - `target +0x15` + `target +0x1D` + clear `row0 +0x15`: pass
  - clear `row0 +0x15` only: fail
- Minimal passing set for tested non-first-row NOP placement:
  - `target_row col31 +0x1D = 1`
  - `target_row col0 +0x15 = 1`
- Native-parity companion (observed in native captures, optional in tested synthetic replay):
  - `row0 col0 +0x15 = 0`

## Phase 1 Conclusion
- Proven:
  - AF `NOP` behavior is synthetically reproducible at row0 and non-first-row placements in tested cases.
  - Minimal decisive byte model is identified and is not a full-region copy.
- Inference (from tested rows 0/1/4/8):
  - For non-first-row `NOP`, required bytes are row-local (`target +0x15` and target `+0x1D`).
  - row0 `+0x15` clear is not required for acceptance in tested replay, but matches native shape.
- Residual caution:
  - Manifest fail entries include notes like `no NOP`, while observed rows were not edited in those entries.
  - Status codes are treated as authoritative for pass/fail classification.

## Gate Status
- Acceptance gate: **met**.
  - reproducible synthetic path for AF `NOP`: yes
  - minimal decisive AF byte set: yes
- Current status: `phase1_complete_ready_for_phase2_rungcomment_mapping`.
