# Click Instruction RE — Capture Checklist

## Goal

Validate instruction-stream generation across immediate, series, NC, and coil variants
using repeatable matrix IDs.

## Matrix Source

- Matrix file: `scratchpad/instruction-matrix.json`
- Tool: `clicknick-ladder-capture` (CLI) or `clicknick-ladder-capture tui`

## One-Time Setup

1. `uv run clicknick-ladder-capture manifest init`
2. Confirm each matrix/native case has a scratchpad entry:
   - `uv run clicknick-ladder-capture entry list`

## Per-Case Workflow

For each ID in the phase tables below:

1. Prepare payload to clipboard:
   - `uv run clicknick-ladder-capture verify prepare --label <id_or_label> --source shorthand`
2. In Click: paste rung, then copy that same rung back.
3. Complete verification (interactive, crash-aware):
   - `uv run clicknick-ladder-capture verify run --label <id_or_label>`
4. Build the same rung natively in Click and capture it:
   - `uv run clicknick-ladder-capture entry capture --label <native_label>`
5. Promote eligible entries to hermetic fixtures:
   - `uv run clicknick-ladder-capture promote --label <native_label> --overwrite`

## Phase 1 — Baseline Smoke

| ID | CSV | Native Label |
|---|---|---|
| `smoke_simple` | `X001,->,:,out(Y001)` | `smoke_simple_native` |
| `smoke_immediate` | `X001.immediate,->,:,out(Y001)` | `smoke_immediate_native` |
| `smoke_two_series_short` | `X1,X2,->,:,out(Y001)` | `smoke_two_series_short_native` |
| `smoke_range` | `X001,->,:,out(C1..C2)` | `smoke_range_native` |

## Phase 2 — Two-Series Immediate Matrix

| ID | CSV | Native Label |
|---|---|---|
| `two_series_first_immediate` | `X001.immediate,X002,->,:,out(Y001)` | `two_series_first_immediate_native` |
| `two_series_second_immediate` | `X001,X002.immediate,->,:,out(Y001)` | `two_series_second_immediate_native` |
| `two_series_both_immediate` | `X001.immediate,X002.immediate,->,:,out(Y001)` | `two_series_both_immediate_native` |

## Phase 3 — NC Contact Matrix

| ID | CSV | Native Label |
|---|---|---|
| `single_nc` | `~X001,->,:,out(Y001)` | `single_nc_native` |
| `two_series_nc_no` | `~X001,X002,->,:,out(Y001)` | `two_series_nc_no_native` |
| `two_series_nc_nc` | `~X001,~X002,->,:,out(Y001)` | `two_series_nc_nc_native` |

## Phase 4 — Rise/Fall Edge Contacts

These complete contact-family coverage.

| ID | CSV | Native Label |
|---|---|---|
| `single_rise` | `rise(X001),->,:,out(Y001)` | `single_rise_native` |
| `single_fall` | `fall(X001),->,:,out(Y001)` | `single_fall_native` |
| `two_series_rise_no` | `rise(X001),X002,->,:,out(Y001)` | `two_series_rise_no_native` |
| `two_series_fall_no` | `fall(X001),X002,->,:,out(Y001)` | `two_series_fall_no_native` |

## Phase 5 — Coil Variants

| ID | CSV | Native Label |
|---|---|---|
| `simple_latch` | `X001,->,:,latch(Y001)` | `simple_latch_native` |
| `simple_reset` | `X001,->,:,reset(Y001)` | `simple_reset_native` |
| `simple_out_immediate` | `X001,->,:,out(immediate(Y001))` | `simple_out_immediate_native` |
| `simple_range_immediate` | `X001,->,:,out(immediate(Y001..Y002))` | `simple_range_immediate_native` |

## Progress Snapshot

- Quick status of manifest entries:
  - `uv run clicknick-ladder-capture entry list`

## Promotion Gate (to Hermetic Fixtures)

Promote a case to `tests/fixtures/ladder_captures` only when:

1. Matrix verify is green (`header_ok`, `topology_ok`, `decode_ok`).
2. Matrix compare is structurally green (`header_structural_equal`, `topology_equal`).
3. Native capture is stable (re-capture does not materially change semantic checks).
