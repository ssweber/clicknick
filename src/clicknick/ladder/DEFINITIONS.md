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

**Wire flags (cell grid model — non-comment rungs)**
Three single-byte flags per cell that control visual wire rendering:
- `+0x19` — horizontal-left
- `+0x1D` — horizontal-right (decisive for continuity; left alone is
  insufficient)
- `+0x21` — vertical-down-to-next-row

**Wire flags (phase-A stride model — comment rungs, row 0)**
For comment rungs, row 0 wire data lives in the phase-A stride, NOT in the
cell grid. The cell grid `+0x19/+0x1D` bytes are all zero in native comment
captures. Instead, wires are at phase-A-relative positions:
- Phase-A slot = `col_idx + 31` (within the 0x40-byte stride)
- `slot_base + 0x21` — left wire
- `slot_base + 0x25` — right wire
- `slot_base + 0x29` — down/vertical (T junctions only)
- `slot_base = phase_a_start + slot × 0x40`
- `phase_a_start = 0x0298 + payload_length` (no padding)
NOP uses phase-A slot 62 (AF column) + 0x25.

**Wire flags (continuation stream — comment rungs, rows 1+)**
For multi-row comment rungs, rows 1+ wire data lives in the continuation
stream records (32 × 0x40 bytes after phase-A), NOT in cell grid positions.
Each record is indexed by column (+0x01). Wire offsets within records:
- `+0x19` — left wire
- `+0x1D` — right wire
No down flags in cont records — vertical connections from row 0 T junctions
appear as horizontal wire (+0x19/+0x1D) at the receiving column on row 1.

**Structural fields** (written by `synthesize_empty_multirow`)
- `+0x01` — column index
- `+0x05` — row index + 1
- `+0x09`, `+0x0A`, `+0x0C` — constants (0x01)
- `+0x0D..+0x10` — constants (0xFF)
- `+0x11` — constant (0x01)
- `+0x38` — next-row flag (1, except terminal-row col31 → 0)
- `+0x3D` — next-row linkage pointer

**NOP-specific**
- `col31 +0x1D` — NOP marker on the AF column (cell grid and cont records)
- `col31 +0x19` — also required for NOP in continuation stream records
- `col0 +0x15` — row enable for non-first-row NOP
- At most one NOP per rung (multiple NOPs render as tiny dots in Click)

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

**Comment flag byte**
`+0x17` on header entry 0. Set to `0x5A` by the encoder for all comment
rungs. This value is mirrored into all 63 phase-A periodic slots at
`phase_a[0x13 + 0x40*k]` and into continuation stream records at `+0x0B`.
Native captures show session-dependent variation (`0x5A`, `0x41`, `0x67`,
`0x65`). Click accepts all observed values on paste.

**Header seed bytes** *(instruction-specific, not yet used)*
- `+0x05` — structural gate (zero for wire-only and comment rungs; e.g.
  `0x04` for second-immediate)
- `+0x11` — family classifier (zero for wire-only and comment rungs; e.g.
  `0x0B` for second-immediate)
- `+0x17/+0x18` — capture-family classifiers (decision table incomplete
  for instruction families)

**Trailer byte**
`0x0A59` — zero for wire-only rungs. For 1-row comment rungs this offset
falls inside the phase-A stream and is owned by the resource file — do NOT
overwrite it. For multi-row non-comment rungs it is `0x01` when instructions
are present (not yet used in encoder).

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
A fixed continuation stream of `0xFC8` bytes (63 slots × `0x40` + 8 tail
bytes) written immediately after the payload body — no cell-size padding.
Click locates phase-A by reading the payload length field, not by cell grid
alignment. Universal across all tested comment lengths. Contains the comment
flag byte at periodic offset `+0x13` in each slot. For comment rungs, the
phase-A stride carries row 0 wire data at `+0x21` (left), `+0x25` (right),
and `+0x29` (down) — these positions overlap the cell grid address range but
are distinct from the cell grid wire flag offsets (`+0x19/+0x1D`).

**Continuation stream** *(multi-row comment rungs only)*
32 records × `0x40` bytes written immediately after phase-A. One record per
column, indexed by `+0x01`. Contains structural constants (comment flag at
`+0x0B`, logical_rows at `+0x05`, terminal flags at `+0x38/+0x3D`) and row
1+ wire/NOP data at `+0x19/+0x1D`. Click reads row 1+ data from these
records, NOT from cell grid positions (which overlap phase-A at a
comment-length-dependent shift).

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

**Comment buffer limits**
Comments occupy the payload region (0x0294+), followed by phase-A
(0xFC8 bytes) and continuation records ((rows-1) × 32 × 0x40 bytes).
All must fit within the allocated buffer:
- 1-row: max 1400 bytes (fits easily — phase-A ends at ~0x184C)
- 2-row: max **1324 bytes** (payload 105+1324+11 = 1440 → phase-A ends
  at 0x1800 → cont ends at exactly 0x2000 = buffer limit). Note: Click
  accepts the 8192-byte paste but on copy-back allocates 12288 (extra
  page). This is not corruption — Click is more generous on re-export.
- 3+ rows: max 1400 bytes (buffer is large enough)

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
