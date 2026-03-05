# Click PLC Clipboard Reverse Engineering — Handoff v11

Last validated: March 5, 2026

## Execution Update (March 4, 2026 — Two-Series Hardening Pass)

- Click-safe encoder scope remains intentionally limited to `1..2` series contacts.
- Header seed model is now context-seeded:
  - `ClickCodec.encode(..., header_seed=HeaderSeed(...))` is supported.
  - Seed writes entry-uniform header bytes `+0x05/+0x11/+0x17/+0x18`.
  - `0x0A59` now mirrors header entry `+0x05` via seed application.
- Fixed header-family literals are no longer treated as rung semantics.
- Second-immediate (`X001,X002.immediate`) keeps a guarded compatibility override for header
  `+0x05/+0x11` and trailer mirror when no explicit seed is provided.
- Capture workflow/CLI now supports seed-source selection for verify prepare/run:
  - `--seed-source {clipboard,scaffold,entry,file}`
  - default `clipboard` with explicit scaffold fallback warning.
- Capture workflow/CLI now supports manifest deletion:
  - `entry delete --label ...`
  - `entry delete --scenario ...`
  - dry-run by default; apply with `--yes`.
- Working manifest was de-swamped:
  - backup created at `scratchpad/archive/ladder_capture_manifest.pre_prune_20260304.json`
  - exploratory scenarios removed from active manifest
  - deterministic `two_series_hardening_matrix_20260304` (9 rows) added for focused verify.

## Execution Update (March 5, 2026 — Empty-Template Reset + Phase 5 Masking)

- Baseline scenario `grid_basics_empty_template_20260305` is complete:
  - `14/14` native captures verified (`verify run --source file`), all `verified_pass`.
- Width experiment conclusion:
  - `default/narrow/wide` variants produced no byte-level diffs in tested empty and wire baselines.
- Phase 5 mask trials completed:
  - `grid_basics_phase5_session_mask_20260305`: `13/14` pass, `1/14` fail
    (`grid_empty_row2_duplicate_native` broke after first column).
  - Narrowing scenario `grid_basics_phase5_narrow_row2_20260305`:
    - only `h11`-only normalization passed;
    - variants touching `+0x05` and/or `0x0A59` failed.
  - Refined scenario `grid_basics_phase5_refined_h11_h17_20260305`:
    - normalize `+0x11/+0x17` only;
    - `14/14` pass.
- Working classification for grid-basics lane:
  - safe session normalization: header `+0x11`, `+0x17`
  - keep untouched for now: header `+0x05`, trailer `0x0A59`
  - unresolved: header `+0x18`
- Full gate notes and artifact links:
  - `scratchpad/noise_vs_structure_reassessment_20260305.md`

## Goal

Reverse engineer Click Programming Software's clipboard format so `clicknick.ladder`
can generate clipboard-ready bytes for paste into Click from `RungGrid`.

## Current Status

- `clicknick.ladder` now uses a deterministic encoder (no runtime dependency on per-variant
  `.bin` templates under `src/clicknick/ladder/resources`).
- Header behavior is partially characterized:
  - refined session normalization (`+0x11/+0x17`) is validated for empty/horizontal baselines.
  - `+0x05` and `0x0A59` are context-sensitive and can be structural.
- Wire topology cell flags are mapped and validated by pasteback.
- Manual pasteback now succeeds for:
  - `smoke_simple`
  - `smoke_immediate`
  - `smoke_two_series_short` (full `X001,X002,->,:,out(Y001)` now pastes)
- `two_series_second_immediate` is now resolved:
  - final validation capture: `two_series_second_immediate_back_after_generated_v3_headerfix.bin`
  - pasteback length `8192`, decodes as `X001,X002.immediate,->,:,out(Y001)`
- New intermediate progress (March 3, 2026, afternoon):
  - deterministic profile-cell fixes for `+0x05/+0x11` were added and validated against fixture tables
  - failure mode improved from total fragmentation to a consistent two-rung split
  - current split signature after pasteback is `12288` bytes with marker relocation:
    - contact1 at `0x0A99`
    - contact2 at `0x1B1E`
    - coil at `0x22D9`
- Instruction stream placement remains the primary engineering area (especially broader
  operand-length and multi-contact generalization).

## New Findings (March 3, 2026 — v2 Isolation Pass)

### A) `+0x1A/+0x1B` are not the primary split gate

Using valid generated 8192 payloads (all 3 markers present) and mutating only profile cells
(`row0 col4..31`, `row1 col0`):

- `two_series_second_immediate_generated_v2_baseline.bin`
- `..._patch_profile_1a_00.bin`
- `..._patch_profile_1b_00.bin`

All three paste back as `12288` and split into two rungs with the same marker relocation pattern.
Interpretation: `+0x1A/+0x1B` influence profile/family behavior but do not by themselves determine
single-rung assembly for this variant.

### B) Row1/Row2 grid content is no longer the dominant unknown

Two stronger controls were tested:

- `..._patch_zero_row1tail_row2.bin` (zero row1 tail and row2)
- `..._patch_row1row2_from_native.bin` (copy row1+row2 grid region exactly from native)

Observed outcome (user-verified): still two rungs.

Important implication:
- Even with row1/row2 grid bytes forced to native, split persists.
- Remaining blocker likely resides outside those row blocks (pre-grid metadata and/or header-family
  bytes that were previously treated as non-structural, plus possible stream-to-grid coupling bytes
  in the pre-grid region).

### D) Pre-grid shortlist extracted by control-filtered ranking

Method:
- Compare failing `two_series_second_immediate` generated-v2 pre-grid bytes against native.
- Remove offsets that also mismatch in known-working controls:
  - `smoke_simple`
  - `smoke_immediate`
  - `smoke_two_series_short`

Result:
- Failing pre-grid mismatches: `114`
- Unique-to-failing offsets after control filtering: `4`
  - `0x006E`: gen `0x00`, native `0x61`
  - `0x0072`: gen `0x00`, native `0x79`
  - `0x0076`: gen `0x00`, native `0x65`
  - `0x007E`: gen `0x00`, native `0x1E`

Targeted payload generated for direct pasteback validation:
- `scratchpad/captures/two_series_second_immediate_generated_v2_patch_pregrid_focus4_native.bin`

### E) Header-region gate confirmed

Isolation tests on generated-v2 payloads established:

- `0x0000..0x0253` (pre-header) native copy alone: still split (`12288`)
- `0x0254..0x0A5F` (header region) native copy alone: single rung (`8192`)

Within that header region for `two_series_second_immediate`, generated-v2 differed from native
almost exclusively at:

- entry `+0x05` (all 32 entries): generated `0x00`, native `0x04`
- entry `+0x11` (all 32 entries): generated `0x00`, native `0x0B`
- trailing byte `0x0A59`: generated `0x00`, native `0x04`

Applying those bytes restores single-rung pasteback behavior.

Final validation:

- `two_series_second_immediate_generated_v3_headerfix.bin` pasted and copied back as
  `two_series_second_immediate_back_after_generated_v3_headerfix.bin`
- Result: `8192` bytes, marker triad at `0x0A99 / 0x0B1E / 0x12D9`, decode
  `X001,X002.immediate,->,:,out(Y001)`

Encoder update now in place:

- For second-immediate two-series (`X001,X002.immediate` family), deterministic encoder writes:
  - header `+0x05 = 0x04`
  - header `+0x11 = 0x0B`
  - `0x0A59 = 0x04`

### C) `+0x05/+0x11` profile table is now characterized for two-series fixtures

Observed fixture-backed profile values in `row0 col4..31` and `row1 col0`:

- non-immediate NO/NC series: `+0x05=0x00`, `+0x11=0x00`
- first immediate only: `+0x05=0x25`, `+0x11=0x52`
- second immediate only: `+0x05=0x04`, `+0x11=0x0C`
- both immediate: `+0x05=0x00`, `+0x11=0x00`
- rise first: `+0x05=0x62`, `+0x11=0x01`
- fall first: `+0x05=0x64`, `+0x11=0x01`

This table is implemented in deterministic encoder logic and covered by tests.

## Canonical Structural Findings

### 1) Fixed Buffer Size

- Full rung clipboard buffer is `8192` bytes (`0x2000`), zero-padded.

### 2) Header Table (`0x0254 + n*0x40`, `n=0..31`)

- Entry `n` corresponds to column `n`.
- Entry offset `+0x0C..+0x0F` stores the column index as a little-endian dword.
- Entry offsets `+0x05/+0x11/+0x17/+0x18` vary across captures, but are not uniformly
  non-structural:
  - grid-basics masking shows `+0x11/+0x17` can be normalized safely.
  - `+0x05` can be structural (row2-duplicate empty case).
- Global row-class byte is at `0x0254`:
  - `0x40` => 1 logical row
  - `0x60` => 2 logical rows
  - `0x80` => 3 logical rows
- Observed non-volatile header family bytes at `+0x17/+0x18` are capture-family classifiers
  (uniform across all 32 entries in a given capture), but the decision table is incomplete.
  Examples observed so far: `0x15/0x01`, `0x0D/0x01`, `0xEA/0x00`.
- Topology/instruction content still lives in grid + stream regions; header family bytes alone
  do not encode per-cell wire layout and are not sufficient to guarantee valid rung assembly.

### 3) Grid Layout

- Row 0 start: `0x0A60`
- Row stride: `0x800` (`32 * 0x40`)
- Cell stride (column): `0x40`

### 4) Wire Topology Flags (Per 64-byte Cell)

- `+0x19`: horizontal-left flag
- `+0x1D`: horizontal-right flag
- `+0x21`: vertical-down-to-next-row flag

Corners are implicit from flag combinations on the same cell.

### 5) Additional Per-Cell Structural Control Bytes (New)

- Wire flags are necessary but not sufficient.
- Two-series immediate experiments show additional non-stream cell bytes participate in rung
  assembly/linkage.
- When these bytes are wrong, Click can split a single intended rung into multiple records/rungs
  (with intermediate `NOP`), even when instruction markers and operands are otherwise valid.
- Practical symptom: pasteback clipboard length changes from `8192` to multi-record sizes
  (for example `20480` or `73728`) and coil markers may disappear from the first record.

### 6) Instruction Stream

- Instructions are serialized stream content; fields are stable at stream-relative offsets
  from the type marker (`0x27XX`).
- Operand strings are UTF-16LE and variable length; downstream fields shift accordingly.
- Immediate contact variants shift function-code location by `+2` bytes relative to
  non-immediate.

## Instruction Type / Function Code Summary

Contacts:
- NO: `0x2711` + `4097`
- NC: `0x2712` + `4098`
- NO immediate: `0x2711` + `4099`
- NC immediate: `0x2712` + `4100`
- Rise/Fall edge: `0x2713` + `4101/4102`

Coils:
- Out: `0x2715` + `8193` (plus immediate/range variants)
- Latch: `0x2716` + `8195` (plus immediate/range variants)
- Reset: `0x2717` + `8196` (plus immediate/range variants)

## Superseded Findings (Historical)

### Superseded: Old Finding 19 (Header Coupling/Pointer Dependency)

Prior handoff versions suggested immediate placement required structural header table
mutations (and possibly pointer/rendering table coupling) for safe generation.

This is superseded by the normalized diff and pasteback evidence in
`scratchpad/capture-diff-results.md`:

- After masking volatile bytes (`+0x05`, `+0x11`), header entries remain structurally
  invariant across tested immediate vs non-immediate comparisons.
- Pasteback (`vert_b_with_horiz` -> recapture) shows structural header equality and
  identical parsed topology.

Interpretation: header coupling is not a blocker for current codec goals; instruction
stream and grid topology are the main work surfaces.

## Hypothesis Check: Per-Row Header Descriptor Table

Hypothesis reviewed:
- `0x0254 + n*0x40` is a per-column table that encodes per-row state (`2` bytes per row).

Current evidence status: **not supported**.

What we observed:
- The stable row-count indicator is a single global class byte at `0x0254` (`0x40/0x60/0x80`).
- Per-entry `+0x0C..+0x0F` is a fixed column index dword.
- Newly confirmed header family bytes `+0x17/+0x18` are global per-capture-family constants,
  not row-addressed fields.
- Wire topology authority remains in cell flags (`+0x19`, `+0x1D`, `+0x21`) with row stride
  `0x800` and column stride `0x40`.

Interpretation:
- We do not currently see evidence for a "2 bytes per row per column" encoding model in this
  header table.
- The earlier ghost-row/red-invalid behavior is better explained by malformed stream/structural
  bytes during transitional encoder experiments, not by missing per-row header writes.
- This hypothesis is not mathematically impossible, but it is not supported by current capture
  diffs/pasteback behavior.
- Important refinement: while the header table is not the per-row authority, grid-level control
  bytes beyond `+0x19/+0x1D/+0x21` do affect assembly/segmentation behavior.

## Legacy Runtime Templates (Planned Removal Complete Path)

These files were legacy runtime templates and are tracked here for retirement context:

1. `src/clicknick/ladder/resources/NO_X002_coil.AF.bin`
2. `src/clicknick/ladder/resources/NO_X001_X002_coil.AF.two_series.bin`
3. `src/clicknick/ladder/resources/NO_X001_immediate_X002_coil.AF.two_series.bin`
4. `src/clicknick/ladder/resources/NO_X001_X002_immediate_coil.AF.two_series.bin`
5. `src/clicknick/ladder/resources/NO_X001_immediate_X002_immediate_coil.AF.two_series.bin`

Rationale for retirement:
- They are compatibility artifacts, not canonical format documentation.
- Vetted captures in `scratchpad/captures` are treated as provenance for fixture curation.

## Hermetic Fixture Policy

Capture-backed tests should use checked-in fixtures under:

- `tests/fixtures/ladder_captures/`
- `tests/fixtures/ladder_captures/manifest.json`

Manifest entries map:
- fixture filename
- original capture label
- intended scenario

This avoids local-only dependency on gitignored `scratchpad/captures` during CI/local test runs.

## Open Questions

1. Header `+0x18`: classify as noise vs structure with a dedicated all-pass/all-fail mask test.
2. Per-cell structural control bytes in row0/row1 (beyond wire flags): exact role in broader
   instruction families now that second-immediate is solved.
3. Stream metadata bytes (`65 60`, `67 60`, related blocks): exact semantics and whether
   all are mandatory per instruction family.
4. Full stream placement formula coverage for broader two-series combinations with mixed
   operand lengths and immediate flags.
5. Register-bank breadth validation beyond current proven sets (DS/T/TD families).
6. Single-cell (`4096` byte) clipboard payload viability for independent cell pasting.
7. Explicit multi-row generation API shape (if/when `RungGrid` should carry full topology).

## Next Steps

### 1) Empty-Template Grid Synthesis (Immediate)

- Use verified empty-rung template captures plus refined mask policy (`+0x11/+0x17` only)
  as the active synthesis baseline.
- Keep `+0x05` and `0x0A59` donor-preserved until further isolation is complete.

### 2) `+0x18` Isolation Follow-Up

- Run focused mask variants that differ only at `+0x18` on the same grid-basics family.
- Promote `+0x18` to safe normalization only if clean all-pass behavior is demonstrated.

### 3) Deterministic Encoder Hardening

- Keep deterministic header writer and topology writer as baseline.
- Validate against additional pasteback scenarios beyond current topology checks.

### 4) Stream Generalization (Primary)

- Expand computed placement coverage for operand-length and immediate combinations.
- Remove residual assumptions tied to old fixed-offset variant behaviors.

### 5) Control-Byte Model Expansion

- Use targeted control-byte diffing across captures to classify structural bytes that govern
  rung assembly/linkage (not just wire flags).
- Expand from second-immediate to remaining unresolved families using the same isolation method
  (profile cells, then row blocks, then pre-grid/header partitions).

### 5a) Pre-Grid Metadata Differential (New Priority)

- Reuse this method for future failing families:
  - compare generated payloads against native with row-block parity controls
  - partition `0x0000..0x0A5F` into pre-header and header slices
  - identify minimal decisive byte set and codify deterministic write rules

### 6) Capture Expansion

- Add targeted captures for unresolved stream/operand/register-bank questions.
- Promote new vetted captures into hermetic fixture set with manifest updates.

### 7) CLI / Automation Integration

- Build/extend `clicknick paste ...` flow:
  - validate/add operands in project data
  - encode deterministic payload
  - paste through Click clipboard mechanism

## References

- Header + topology validation report:
  - `scratchpad/capture-diff-results.md`
- Capture checklist:
  - `scratchpad/capture-checklist.md`
- Control-byte diff tool:
  - `devtools/control_byte_diff.py`
- Ladder module code:
  - `src/clicknick/ladder/`
