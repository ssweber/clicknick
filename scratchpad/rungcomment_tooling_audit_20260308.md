# Rung Comment Tooling Audit (March 8, 2026)

## Scope

Audit the current repo tooling before trusting historical comment-lane conclusions.

Questions:
- Does current tooling use `0x0A60` as the first visible grid row?
- Does any row-labeling path count `0x0254..0x0A5F` as visible row `0`?
- Were earlier "row N" references in comment work code bugs or naming ambiguity?

## Result

No current code path was found that treats `0x0254..0x0A5F` as visible row `0`.

Current tooling uses:
- metadata/header band: `0x0254..0x0A53`
- 12-byte gap/trailer band: `0x0A54..0x0A5F`
- GUI row `0` starts at: `0x0A60`

`devtools/capture.py` is not present in the repo. It is already retired by policy, so there is no live code path there to audit or fix.

## Code Audit Findings

### 1. Canonical topology helpers are correct

File:
- `src/clicknick/ladder/topology.py`

Confirmed constants:
- `HEADER_ENTRY_BASE = 0x0254`
- `GRID_FIRST_ROW_START = 0x0A60`
- `GRID_ROW_STRIDE = 0x800`

Confirmed behavior:
- `cell_offset(row, column)` computes from `0x0A60 + row * 0x800 + column * 0x40`
- all row/column helpers that import `cell_offset()` therefore refer to visible rows only

### 2. CLI report row labels are visible-row labels

Files:
- `src/clicknick/ladder/capture_workflow.py`
- `src/clicknick/ladder/capture_cli.py`

Confirmed behavior:
- `report profile-columns` resolves requested `row`/`column` cells through `cell_offset(row, col)`
- reported `row` values in CLI output therefore start at visible row `0` at `0x0A60`
- no report path maps metadata slots at `0x0254 + n*0x40` onto visible row numbers

### 3. Diff helpers are anchored to visible-grid origin

Files:
- `devtools/control_byte_diff.py`
- `devtools/patch_capture_cells.py`
- `devtools/grid_template_synth.py`

Confirmed behavior:
- `control_byte_diff.py` uses `clicknick.ladder.topology.cell_offset()`
- `patch_capture_cells.py` hard-codes `GRID_FIRST_ROW_START = 0x0A60`
- `grid_template_synth.py` imports `GRID_FIRST_ROW_START` and `cell_offset()`

Implication:
- current diff/patch helpers that speak in row/column terms are already aligned to visible row `0 = 0x0A60`

### 4. Metadata/trailer region is already modeled separately in current docs/code

Files:
- `scratchpad/click_clipboard_map.html`
- `scratchpad/capture-diff-results.md`
- `src/clicknick/ladder/empty_multirow.py`

Confirmed behavior:
- the header entry table is described separately from the rung/grid region
- `0x0A54..0x0A5F` is already treated as a gap/trailer region, not as visible row data
- `0x0A59` is handled as a trailer mirror byte, not as part of visible row `0`

## Historical Interpretation Risk

The main risk appears to be terminology, not indexing bugs.

Likely ambiguity sources:
- phrases such as "row0/row1-local" in older comment notes can be read too loosely
- some notes grouped header-tail bytes, trailer bytes, and visible row0/row1 cell families into one structural discussion
- that wording can obscure the distinction between:
  - metadata/header-tail structure before `0x0A60`
  - row0/row1 byte bands starting at `0x0A60`

Current evidence does **not** show:
- a code path that mislabeled `0x0254..0x0A5F` as visible row `0`
- a report helper that shifted visible rows by one because of the metadata region

## Audit Decision

Use this nomenclature going forward:
- metadata region: `0x0254..0x0A5F`
- row0 band: `0x0A60..0x125F`
- row1 band: `0x1260..0x1A5F`

Conservative conclusion:
- prior comment-lane confusion was primarily documentation/naming ambiguity plus contaminated test baselines
- it was not an established tooling indexing bug in the currently-audited repo code

## Actionable Follow-Up

- Keep production geometry/constants unchanged.
- Re-run comment verification from a truly empty-rung native baseline.
- In all new docs, reserve `row` for GUI-visible rows only.
- Use `band` for byte ranges.
- When discussing `0x0254 + n*0x40`, call them metadata slots or header entries.
- When discussing `0x0A60 + row * 0x800`, call them GUI rows.
