# Non-Empty Multi-Row Horizontal/Vertical Inference (March 6, 2026)

## Scope
- Task family: non-empty multi-row synthesis, horizontal and vertical continuity.
- Production rule held: no codec integration changes in this round.
- Workflow rule held: manifest updated only through `uv run clicknick-ladder-capture ...`.

## Inputs and Donors
- Existing capture donors:
  - `scratchpad/captures/vert_b_only.bin` (2-row, col1 vertical)
  - `scratchpad/captures/vert_b_with_horiz.bin` (2-row, col1 vertical + horizontal)
  - `scratchpad/captures/corner_b.bin` (2-row corner shape)
  - `scratchpad/captures/vert_b_3rows.bin` (3-row, col1 vertical continuation)
  - `scratchpad/captures/vert_d_only.bin` (2-row, col3 vertical)
- Noise helper available and used for structural sanity checks:
  - `devtools/noise_apply.py::mask_session_noise(...)`

## Static Evidence Before Verify
- Parsed topology confirms expected wire semantics in donors:
  - horizontal flags: `cell +0x19/+0x1D`
  - vertical-down flag: `cell +0x21`
- `vert_b_only` vs `vert_b_with_horiz` cell-level diffs show horizontal signal at col1 with session drift (`+0x05/+0x39`) in parallel.
- `vert_b_only` vs `vert_b_3rows` confirms vertical continuation pattern:
  - 2-row: `r0 c1 +0x21 = 1`, `r1 c1 +0x21 = 0`
  - 3-row: `r0 c1 +0x21 = 1`, `r1 c1 +0x21 = 1`, terminal row down-link `0`

## Track H: Horizontal Isolation Setup
Scenario: `grid_nonempty_multirow_horiz_20260306` (`9` file-backed patch entries)

Queue doc:
- `scratchpad/grid_nonempty_multirow_horiz_verify_queue_20260306.md`

Patch construction baseline:
- Base payload: `gnmh_control_vert_b_only` (`vert_b_only` copy)
- Variants toggle only horizontal bytes around active cells.

Decisive candidate offsets under test:
- `r0 c1 +0x19/+0x1D` (`0x0AB9`, `0x0ABD`)
- `r1 c1 +0x19/+0x1D` (`0x12B9`, `0x12BD`)
- extent probe: `r0 c0 +0x1D` (`0x0A7D`)

Minimality check (vs `gnmh_control_vert_b_only`):
- `gnmh_row0_only_horiz`: 2 byte changes (`0x0AB9`, `0x0ABD`)
- `gnmh_row1_only_horiz`: 2 byte changes (`0x12B9`, `0x12BD`)
- `gnmh_both_rows_horiz_same`: 4 byte changes (union of both rows)
- `gnmh_both_rows_horiz_diff`: 5 byte changes (union + `0x0A7D`)

## Track H: Horizontal Verify Outcomes (Completed)
Scenario run: `grid_nonempty_multirow_horiz_20260306` (`9` cases)

Outcome summary:
- `verified_pass`: `8`
- `verified_fail`: `1`
- `blocked`: `0`
- `unverified`: `0`
- clipboard length: `8192` for all 9 cases

Per-label results:
- `gnmh_control_vert_b_only`: `verified_pass`, `copied`, len `8192`
- `gnmh_row0_only_horiz`: `verified_pass`, `copied`, len `8192`
- `gnmh_row1_only_horiz`: `verified_pass`, `copied`, len `8192`
- `gnmh_both_rows_horiz_same`: `verified_pass`, `copied`, len `8192`
- `gnmh_both_rows_horiz_diff`: `verified_pass`, `copied`, len `8192`
- `gnmh_ablate_r1_hleft_only`: `verified_pass`, `copied`, len `8192`
- `gnmh_ablate_r1_hright_only`: `verified_fail`, `copied`, len `8192`, note: `Only T in Row0, no horizontal in Row1`
- `gnmh_ablate_r1_both`: `verified_pass`, `copied`, len `8192`
- `gnmh_ablate_r0_both`: `verified_pass`, `copied`, len `8192`

Topology check from verify-back payloads:
- `gnmh_ablate_r1_hleft_only` verify-back retained `r1 c1` horizontal-right-only (`R`), and passed.
- `gnmh_ablate_r1_hright_only` verify-back dropped `r1 c1` horizontal completely, and failed.

Horizontal inference update (col1 in this 2-row non-empty lane):
- Decisive byte: `r1 c1 +0x1D` (`0x12BD`) is required for row1 horizontal continuity.
- Non-decisive alone: `r1 c1 +0x19` (`0x12B9`) is not sufficient by itself.
- Row0 extent probe (`r0 c0 +0x1D`) remained compatible (`gnmh_both_rows_horiz_diff` pass).

## Track V: Vertical Isolation Setup
Scenario: `grid_nonempty_multirow_vert_20260306` (`8` file-backed patch entries)

Queue doc:
- `scratchpad/grid_nonempty_multirow_vert_verify_queue_20260306.md`

Patch construction baseline:
- Base payload: `gnmv_control_vert_b_3rows` (`vert_b_3rows` copy)
- Variants toggle only vertical-down bytes at continuity points.

Decisive candidate offsets under test:
- `r0 c1 +0x21` (`0x0AC1`)
- `r1 c1 +0x21` (`0x12C1`)
- column-scaling probe:
  - clear col1 down-links (`0x0AC1`, `0x12C1`)
  - set col3 down-links (`0x0B41`, `0x1341`)

Minimality check (vs `gnmv_control_vert_b_3rows`):
- `gnmv_ablate_r1c1_vdown`: 1 byte change (`0x12C1`)
- `gnmv_ablate_r0c1_vdown`: 1 byte change (`0x0AC1`)
- `gnmv_ablate_r0r1_vdown`: 2 byte changes (`0x0AC1`, `0x12C1`)
- `gnmv_shift_col1_to_col3`: 4 byte changes (`0x0AC1`, `0x12C1`, `0x0B41`, `0x1341`)

## Track V: Vertical Verify Outcomes (Completed)
Scenario run: `grid_nonempty_multirow_vert_20260306` (`8` cases)

Outcome summary:
- `verified_pass`: `8`
- `verified_fail`: `0`
- `blocked`: `0`
- `unverified`: `0`

Per-label results:
- `gnmv_control_vert_b_only_2rows`: `verified_pass`, `copied`, len `8192`
- `gnmv_control_vert_d_only_2rows`: `verified_pass`, `copied`, len `8192`
- `gnmv_control_vert_b_3rows`: `verified_pass`, `copied`, len `12288`
- `gnmv_force_terminal_r2c1_vdown0`: `verified_pass`, `copied`, len `12288`
- `gnmv_ablate_r1c1_vdown`: `verified_pass`, `copied`, len `12288`
- `gnmv_ablate_r0c1_vdown`: `verified_pass`, `copied`, len `12288`
- `gnmv_ablate_r0r1_vdown`: `verified_pass`, `copied`, len `12288`
- `gnmv_shift_col1_to_col3`: `verified_pass`, `copied`, len `12288`

Topology check from verify-back payloads:
- `gnmv_ablate_r1c1_vdown` retained only `r0 c1` vertical-down.
- `gnmv_ablate_r0c1_vdown` retained only `r1 c1` vertical-down.
- `gnmv_ablate_r0r1_vdown` retained no vertical cells.
- `gnmv_shift_col1_to_col3` moved continuity from `c1` to `c3` on rows `0/1`.

Vertical inference update:
- Deterministic control bytes for this lane are `cell +0x21` at target row/column cells.
- Column scaling behaves directly: moving `+0x21` from `c1` to `c3` moves observed continuity.
- Terminal row remains a no-down endpoint (`r2` terminal check passed).

## Manifest State
- Added scenarios:
  - `grid_nonempty_multirow_horiz_20260306`
  - `grid_nonempty_multirow_vert_20260306`
- Added entries:
  - horizontal: `9` labels (`gnmh_*`)
  - vertical: `8` labels (`gnmv_*`)
- Current verify status:
  - horizontal (`gnmh_*`): complete (`8` pass, `1` fail)
  - vertical (`gnmv_*`): complete (`8` pass, `0` fail)

## Boundary Statement
Proven in this round:
- Byte-level candidate sets and minimal ablation payloads were constructed for horizontal (`+0x19/+0x1D`) and vertical (`+0x21`) continuity.
- Horizontal scenario has a reproducible non-empty 2-row synthetic pass path.
- Horizontal decisive candidate behavior at row1 col1 was isolated (`+0x1D` decisive vs `+0x19` alone).
- Vertical scenario has reproducible non-empty 2-row and 3-row synthetic pass paths with deterministic `+0x21` control.

Assumed (not yet proven by this round's Click verify):
- Horizontal `+0x1D` decisiveness generalizes beyond the tested col1 row1 geometry.

Unknown:
- Whether the same minimal sets hold for 4-row non-empty lanes.
- Whether these lane rules remain stable when instruction-stream-heavy non-empty families are mixed into the same rows.

## Recommendation
- `ready for implementation planning` (scoped to tested non-empty wire-topology lanes).
- Keep implementation scope explicit: 2-row/3-row wire continuity rules proven here; 4-row and mixed instruction-heavy lanes remain follow-up validation items.
