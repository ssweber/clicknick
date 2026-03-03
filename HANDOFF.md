# Click PLC Clipboard Reverse Engineering — Handoff v8

Last validated: March 3, 2026

## Goal

Reverse engineer Click Programming Software's clipboard format so `clicknick.ladder`
can generate clipboard-ready bytes for paste into Click from `RungGrid`.

## Current Status

- `clicknick.ladder` now uses a deterministic encoder (no runtime dependency on per-variant
  `.bin` templates under `src/clicknick/ladder/resources`).
- Header structural behavior is now treated as solved for current scope.
- Wire topology cell flags are mapped and validated by pasteback.
- Manual pasteback now succeeds for:
  - `smoke_simple`
  - `smoke_immediate`
  - `smoke_two_series_short` (full `X001,X002,->,:,out(Y001)` now pastes)
- `two_series_second_immediate` remains unresolved:
  - malformed generation can paste as multiple split rungs with `NOP`
  - Click may emit non-`8192` clipboard payloads (`20480`, `73728`) after split pasteback
- Instruction stream placement remains the primary engineering area (especially broader
  operand-length and multi-contact generalization).

## Canonical Structural Findings

### 1) Fixed Buffer Size

- Full rung clipboard buffer is `8192` bytes (`0x2000`), zero-padded.

### 2) Header Table (`0x0254 + n*0x40`, `n=0..31`)

- Entry `n` corresponds to column `n`.
- Entry offset `+0x0C..+0x0F` stores the column index as a little-endian dword.
- Entry offsets `+0x05` and `+0x11` are volatile across captures and are non-structural.
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

1. Header family bytes (`+0x17/+0x18`): exact semantics and complete decision table for all
   supported/unsupported rung families.
2. Per-cell structural control bytes in row0/row1 (beyond wire flags): which offsets are required
   for valid single-rung assembly vs split-rung behavior.
3. Stream metadata bytes (`65 60`, `67 60`, related blocks): exact semantics and whether
   all are mandatory per instruction family.
4. Full stream placement formula coverage for broader two-series combinations with mixed
   operand lengths and immediate flags.
5. Register-bank breadth validation beyond current proven sets (DS/T/TD families).
6. Single-cell (`4096` byte) clipboard payload viability for independent cell pasting.
7. Explicit multi-row generation API shape (if/when `RungGrid` should carry full topology).

## Next Steps

### 1) Deterministic Encoder Hardening

- Keep deterministic header writer and topology writer as baseline.
- Validate against additional pasteback scenarios beyond current topology checks.

### 2) Stream Generalization (Primary)

- Expand computed placement coverage for operand-length and immediate combinations.
- Remove residual assumptions tied to old fixed-offset variant behaviors.

### 3) Control-Byte Model Expansion

- Use targeted control-byte diffing across captures to classify structural bytes that govern
  rung assembly/linkage (not just wire flags).
- Keep `two_series_second_immediate` as the reference failing case until it pastes/copies back
  as a single `8192` record with coil intact.

### 4) Capture Expansion

- Add targeted captures for unresolved stream/operand/register-bank questions.
- Promote new vetted captures into hermetic fixture set with manifest updates.

### 5) CLI / Automation Integration

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
