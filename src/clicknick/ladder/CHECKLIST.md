# Ladder Encoder — Supported Features Checklist

Status of each feature in `encode.py` as of this version.
Updated per integration session.


## Rung Types

| Feature | Status | Rows | Notes |
|---------|--------|------|-------|
| Empty rung | **Supported** | 1–32 | Verified at 1/2/3/4/9/17/32 rows |
| Wire-only rung | **Supported** | 1–32 | All combos of `- \| T` tokens |
| Wire + NOP | **Supported** | 1–32 | NOP on any row verified through row32 |
| Comment (empty rung) | **Supported** | 1 | Plain text, 1–1400 chars, all lengths |
| Comment + wires | **Supported** | 1 | Full and sparse wires verified (phase-A stride encoding) |
| Comment + NOP | **Supported** | 1 | NOP via phase-A slot 62 + 0x25 |
| Comment + wires + NOP | **Supported** | 1 | All three combined verified |
| Comment (multi-row) | **Not supported** | 2–32 | Needs extra page + terminal companion synthesis |
| Condition contacts | **Not supported** | — | Needs instruction stream builder |
| AF coils (out/latch/reset) | **Not supported** | — | Needs instruction stream + AF cell model |
| Styled comments | **Not supported** | — | RTF bold/italic/underline crashes |
| Multi-line comments | **Not supported** | — | Only single-line proven |


## Wire Tokens (Condition Columns A..AE)

| Token | Meaning | Flags set | Status |
|-------|---------|-----------|--------|
| `""` | Blank cell | none | **Supported** |
| `"-"` | Horizontal wire | +0x19=1, +0x1D=1 (cell grid) or +0x21=1, +0x25=1 (phase-A stride for comment rungs) | **Supported** |
| `"\|"` | Vertical pass-through | +0x21=1 | **Supported** (not on col A) |
| `"T"` | Junction down | +0x19=1, +0x1D=1, +0x21=1 | **Supported** (not on col A) |


## AF Column

| Token | Meaning | Status |
|-------|---------|--------|
| `""` | Blank | **Supported** |
| `"NOP"` | No operation | **Supported** (row 0: col31 +0x1D; row N: + col0 +0x15) |
| `"out(Y001)"` | Output coil | **Not supported** |
| `"latch(Y001)"` | Latch coil | **Not supported** |
| `"reset(Y001)"` | Reset coil | **Not supported** |


## Comments

| Feature | Status | Notes |
|---------|--------|-------|
| Plain text body | **Supported** | cp1252 encoded, max 1400 bytes |
| RTF prefix/suffix | **Supported** | Extracted from single donor file |
| Phase-A stream | **Supported** | Universal across all lengths |
| Length 100 (formerly mod-36) | **Supported** | Was caused by wrong flag byte (0x65), not length |
| On wire rungs | **Supported** | Uses phase-A stride (+0x21/+0x25) not cell grid (+0x19/+0x1D) |
| On NOP rungs | **Supported** | NOP at phase-A slot 62 + 0x25 |
| Styled (bold) | **Not supported** | Crashes — needs companion bytes |
| Styled (italic) | **Not supported** | Skipped after bold failure |
| Styled (underline) | **Not supported** | Skipped after bold failure |
| Multi-line | **Not supported** | Only single-line proven in captures |
| On multi-row rungs | **Not supported** | Needs page-extent synthesis |


## Header / Structural

| Feature | Status | Notes |
|---------|--------|-------|
| Row word (row count) | **Supported** | Formula: (rows + 1) × 0x20 |
| Buffer allocation | **Supported** | Page-aligned: 0x1000 × (ceil(rows/2) + 1) |
| Header +0x05 (zero) | **Supported** | Zero for wire-only and comment rungs |
| Header +0x11 (zero) | **Supported** | Zero for wire-only and comment rungs |
| Header +0x17 (comment flag) | **Supported** | 0x5A for all comment rungs (unified, not grid-dependent) |
| Header +0x05 (nonzero) | **Not supported** | Needed for instruction families |
| Header +0x11 (nonzero) | **Not supported** | Needed for instruction families |
| Header +0x17/+0x18 (instructions) | **Not supported** | Decision table incomplete for instruction families |
| Trailer 0x0A59 | **Supported** | Zero for wire-only; 0x01 for comment rungs |
| Cell +0x39 linkage | **Not supported** | Needed for instruction-bearing rungs |


## Column A Constraints

| Token | Col A | Other cols | Notes |
|-------|-------|------------|-------|
| `""` | Allowed | Allowed | |
| `"-"` | Allowed | Allowed | |
| `"\|"` | **Rejected** | Allowed | No valid structural encoding at col A |
| `"T"` | **Rejected** | Allowed | No valid structural encoding at col A |


## Resource Files Required

| File | Used by | Purpose | Status |
|------|---------|---------|--------|
| `empty_multirow_rule_minimal.scaffold.bin` | `synthesize_empty_multirow` | Base template for all row counts | **Keep** |
| `grcecr_short_native_20260308.bin` | `encode._load_comment_framing` | RTF prefix, suffix, phase-A | **Keep** |
| `grcecr_medium_native_20260308.bin` | (nothing) | Was used by phase-B program | **Delete** |
| `grcecr_max1400_native_20260308.bin` | (nothing) | Was used by long comment family | **Delete** |
| `grcecr_fullwire_native_20260308.bin` | (nothing) | Was wireframe donor | **Delete** |
| `grcecr_fullwire_nop_native_20260308.bin` | (nothing) | Was wireframe donor | **Delete** |
| `grcecr_rows2_empty_native_20260308.bin` | (nothing) | Was wireframe donor | **Delete** |
| `grcecr_rows2_vert_horiz_native_20260308.bin` | (nothing) | Was wireframe donor | **Delete** |


## Verification Evidence

All "supported" items above are backed by Click round-trip verification
(encode → paste → copy back → decode) from the March 2026 capture series.

| Evidence | Scenarios verified |
|----------|-------------------|
| Empty 1-row | `grcecr_empty_native_20260308` |
| Empty multi-row | `gmrs_rows04/09/17/32_rule_minimal` |
| Cross-donor scaling | `gmrsx_rows09_fromrow4_rule_minimal` |
| Fullwire 1-row | `grcecr_fullwire_native_20260308` |
| Fullwire + NOP | `grcecr_fullwire_nop_native_20260308` |
| 2-row wire topology | `grcecr_rows2_vert_horiz_native_20260308` |
| Non-empty horiz/vert | `grid_nonempty_multirow_horiz/vert_20260306` (17 cases) |
| Row-combo (4–5 rows) | `grid_nonempty_multirow_rowcombo_20260306` (12 cases) |
| Scale to 32 | `grid_nonempty_multirow_scale_20260306` (8 cases) |
| Impl smoke | `grid_nonempty_multirow_impl_smoke_20260306` (5 cases) |
| Asymmetry edges | `grid_nonempty_multirow_impl_asymmetry_20260306` (9 cases) |
| NOP row placement | `grid_af_nop_vs_empty_20260306` (9 cases) |
| NOP byte isolation | `grid_af_nop_patch_isolation_20260306` (17 cases) |
| Plain comment (short) | `gpcx_short_exact_20260308` |
| Plain comment (medium) | `gpcx_medium_exact_20260308` |
| Plain comment (max1400) | `gpcx_max1400_exact_20260308` |
| Comment + wires/NOP (0x5A flag) | `verify-0x5A-flag-20260309` (10 shapes: comment-only, 1char, 100char, 100m, NOP, fullwire, partial-wire, fullwire+NOP, empty baseline, fullwire+NOP baseline) |
| Native comment references | `comment-family-flag-20260309` (sparse wire, fullwire, NOP-only — all 0x5A) |
