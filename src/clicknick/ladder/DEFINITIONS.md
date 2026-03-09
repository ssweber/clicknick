# Ladder Encoder — Definitions

Terms used in encode.py, topology.py, empty_multirow.py, and STATUS.md.
Canonical reference to prevent confusion across sessions.


## Rung Content Tiers

**Empty rung**
A rung where every condition cell is blank (`""`) and the AF column has no
instruction. No wire flags are set. The cell grid contains only the
deterministic structural fields (column index, row index, constants,
linkage). This is what `synthesize_empty_multirow` produces directly.

**Wire rung**
A rung that contains wire topology but no contacts or instructions. Cells
may be horizontal wire (`-`), vertical pass-through (`|`), or
junction-down (`T`). The AF column may contain `NOP`. Wire flags are the
only per-cell content beyond the empty structural fields.

**Condition rung** *(not yet supported)*
A rung with contact or comparison elements on condition columns (A..AE).
Each contact sets wire flags (like `-`) *plus* writes an instruction stream
entry into the payload region with a type marker, function code, and
operand. Examples: `NO(X001)`, `NC(X002)`, `X001.immediate`.

**Instruction rung** *(not yet supported)*
A rung with output instructions on the AF column. Coils (out, latch,
reset) and their immediate/range variants. These also write instruction
stream entries. A full rung typically has conditions + wires + AF
instruction. Example: `X001,->,->,:,out(Y001)`.


## Grid Geometry

**Logical row**
A row of the rung as the programmer sees it. Row 0 is the first/top row.
A rung has 1..32 logical rows.

**Column A..AE**
The 31 condition columns (indices 0..30). These hold wire tokens or
contacts.

**Column AF**
The output column (index 31). Holds NOP or output instructions (coils).

**Cell**
A 64-byte (`0x40`) structure at a fixed grid position. Addressed by
`cell_offset(row, column)`. Contains structural fields, wire flags, and
(for instruction rungs) additional control bytes.

**Cell grid**
The region starting at `0x0A60` that contains all cell data. Row stride
is `0x800` (32 columns × 64 bytes). The grid is separate from the header
table and the payload region.


## Cell Byte Offsets

**Wire flags**
Three single-byte flags per cell that control visual wire rendering:
- `+0x19` — horizontal-left
- `+0x1D` — horizontal-right (decisive for continuity; left alone is
  insufficient)
- `+0x21` — vertical-down-to-next-row

**Structural fields** (written by `synthesize_empty_multirow`)
- `+0x01` — column index
- `+0x05` — row index + 1
- `+0x09`, `+0x0A`, `+0x0C` — constants (0x01)
- `+0x0D..+0x10` — constants (0xFF)
- `+0x11` — constant (0x01)
- `+0x38` — next-row flag (1, except terminal-row col31 → 0)
- `+0x3D` — next-row linkage pointer

**NOP-specific**
- `col31 +0x1D` — NOP marker on the AF column
- `col0 +0x15` — row enable for non-first-row NOP

**Instruction-specific** *(not yet used in encode.py)*
- `+0x39` — rung-assembly linkage flag (required = 1 on row0/row1 cells
  for instruction-bearing rungs; 0 for wire-only)


## Header Table

**Header entry**
One of 32 entries at `0x0254 + n × 0x40` (n = 0..31). Entry n
corresponds to column n.

**Row word**
Little-endian 16-bit value at entry 0 offsets `+0x00/+0x01`. Encodes
logical row count: `row_word = (logical_rows + 1) × 0x20`. Example:
2 rows → `0x0060`, 32 rows → `0x0420`.

**Row class** *(legacy)*
The low byte of the row word. Historical 1-byte shorthand: `0x40` = 1
row, `0x60` = 2 rows, `0x80` = 3 rows. Superseded by the full row word
for row counts > 3.

**Header seed bytes** *(instruction-specific, not yet used)*
- `+0x05` — structural gate (zero for wire-only; e.g. `0x04` for
  second-immediate)
- `+0x11` — family classifier (zero for wire-only; e.g. `0x0B` for
  second-immediate)
- `+0x17/+0x18` — capture-family classifiers (decision table incomplete)

**Trailer byte**
`0x0A59` — mirrors header `+0x05`. Zero for wire-only rungs.

**Volatile bytes**
`+0x05` and `+0x11` on header entries can vary between capture sessions
without affecting wire topology. Safe to normalize for wire-only
comparisons. However `+0x05` becomes structural for instruction families.


## Payload Region

**Payload length dword**
4-byte little-endian integer at `0x0294`. Stores the byte count of the
payload that follows.

**Payload body**
Starts at `0x0298`. For comment rungs, this is: 105-byte RTF prefix +
cp1252 body text + 11-byte RTF suffix (includes trailing NUL).

**Phase-A**
A fixed continuation stream of `0xFC8` bytes written immediately after
the payload body. Universal across all tested comment lengths. This is
stream data, not cell grid data — it merely passes through grid-range
addresses for short comments in small buffers.

**Phase-B** *(deleted from encoder)*
A repeating block pattern that was observed after phase-A in the medium
comment donor. Was a 64-byte triad (A/B/C blocks, 9-period ring). Not
semantically required — was incidental memory content from the donor
capture. Caused the mod-36 length bug when a partial tail block wrote
stray bytes that Click misinterpreted as cell flags.


## Buffer Allocation

**Page**
`0x1000` (4096) bytes. Buffer size scales in pages.

**Buffer size formula**
`0x1000 × (ceil(logical_rows / 2) + 1)`. Examples:
- 1 row: `0x2000` (8192)
- 2 rows: `0x2000` (8192)
- 3–4 rows: `0x3000` (12288)
- 32 rows: `0x11000` (69632)

**Comment page**
A max-length comment on a multi-row rung adds one extra `0x1000` page.
This page is a terminal companion extent carrying renderer/layout
metadata (font descriptors, CJK fallback tables). For 1-row rungs, the
comment fits within the existing buffer.

**Split signature**
A verify-back length that is a multiple of the expected size indicates
Click interpreted one rung as multiple records. Example: expected 8192,
got 12288 = two records (failure).


## Verification

**Native capture**
A clipboard payload captured directly from Click after manual authoring.
This is ground truth.

**Verify-back / round-trip**
Encode → paste into Click → copy back → decode. A pass means the
verify-back length matches expected scaling, and decoded content matches
the input.

**Donor file**
A native capture used as a binary template or reference. The encoder
currently uses two donors: the scaffold template (for
`synthesize_empty_multirow`) and the short comment donor (for RTF
prefix/suffix and phase-A extraction).
