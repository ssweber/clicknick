# Click Header RE — Capture Checklist

## How to Capture

1. Build the rung in Click exactly as described
2. Select the rung (Ctrl+A)
3. Copy (Ctrl+C)
4. Ensure the label exists in scratchpad manifest:
   - `uv run clicknick-ladder-capture entry show --label <label>`
5. Save clipboard payload to the entry:
   - `uv run clicknick-ladder-capture entry capture --label <label>`
6. Move to next capture

## Shorthand Reference

Condition columns (A–AE) use: `-` wire, `...` empty fill, `->` wire fill, instruction names.
`:` separates conditions from output column AF.
Rows separated by `/`.

## Phase 1 — Empty and Horizontal Wires

Goal: understand what the header records for wire presence per column.

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 1 | `totally_empty` | Completely empty rung, no NOP | `...,:,...` |
| 2 | `empty_nop` | Empty rung with default NOP in AF | `...,:,nop` |
| 3 | `wire_a` | Draw one horizontal wire in column A only | `-,...,:,...` |
| 4 | `wire_ab` | Horizontal wire in columns A and B | `-,-,...,:,...` |
| 5 | `wire_abc` | Horizontal wire in A, B, C | `-,-,-,...,:,...` |
| 6 | `wire_abcde` | Horizontal wire in A through E | `-,-,-,-,-,...,:,...` |
| 7 | `wire_full_row` | Horizontal wire across all condition columns A–AE | `->,:,...` |
| 8 | `wire_c_only` | Wire in column C only, A and B empty | `...,-,...,:,...` |
| 9 | `wire_a_and_e` | Wire in A and E, B/C/D empty | `-,...,-,...,:,...` |

**After these 9:** diff headers. Which `0x0254 + n*0x40` entries light up? Do they match column positions? What does NOP add vs truly empty?

## Phase 2 — Vertical Wires, Junctions, and Multi-Row

Goal: understand how the header encodes vertical connections and whether junctions are explicit or implicit.

Click allows both vertical and horizontal lines in the same cell. We need to capture them separately to see which flags are independent.

Using `|` for vertical-only (no horizontal wire in cell).

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 10 | `vert_b_only` | Vertical line in B, no horizontal wires anywhere | Row 0: `...,\|,...,:,...` / Row 1: `...,\|,...,:,...` |
| 11 | `vert_b_with_horiz` | Vertical + horizontal in B (┬/┴ junction) | Row 0: `...,T,...,:,...` / Row 1: `...,t,...,:,...` |
| 12 | `corner_b` | Horizontal enters B, vertical goes down (┌) | Row 0: `-,r,...,:,...` / Row 1: `...,\|,...,:,...` |
| 13 | `vert_d_only` | Vertical line in D, no horizontal | Row 0: `...,...,\|,...,:,...` / Row 1: `...,...,\|,...,:,...` |

**After these 4:** diff #10 vs #11. The difference is horizontal wire presence — isolates the vertical flag from the horizontal flag. Diff #10 vs #12 — does a corner look different from a straight vertical? If not, corners are implicit (renderer sees horizontal ending + vertical starting at same cell).

Diff #10 vs #13 — same vertical pattern at different column. Entries should be identical but in different positions.

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 14 | `vert_b_3rows` | Vertical line in B spanning 3 rows | Row 0: `...,\|,...` / Row 1: `...,\|,...` / Row 2: `...,\|,...` |

**After this:** which bytes in B's entry change when going from 2 rows to 3? That's the row stride.

**After these 4:** which bytes within each column's 64-byte entry change when rows are added?

## Phase 3 — Contacts (No Wires, No Coils)

Goal: what does an instruction add to the header vs a wire?

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 15 | `no_a_only` | NO contact X001 in column A, nothing else | `X001,...,:,...` |
| 16 | `no_c_only` | NO contact X001 in column C, nothing else | `...,X001,...,:,...` |
| 17 | `nc_a_only` | NC contact X001 in column A, nothing else | `~X001,...,:,...` |
| 18 | `no_a_no_c` | NO X001 in A, NO X002 in C | `X001,...,X002,...,:,...` |

**After these 4:** diff #15 vs #3 (contact vs wire in same column). What's the header delta? Diff #15 vs #17 — does instruction type matter?

## Phase 4 — Output Column

Goal: is AF's header entry independent of condition columns?

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 19 | `out_af_only` | Out Y001 in AF, nothing in conditions | `...,:,out(Y001)` |
| 20 | `no_a_out_af` | NO X001 in A + Out Y001 in AF, no wires | `X001,...,:,out(Y001)` |
| 21 | `latch_af_only` | Latch Y001 in AF, nothing in conditions | `...,:,latch(Y001)` |
| 22 | `reset_af_only` | Reset Y001 in AF, nothing in conditions | `...,:,reset(Y001)` |

**After these 4:** diff #19 vs #21 vs #22 — does output type change the header? Diff #19 vs #20 — does adding a condition change AF's entry?

## Phase 5 — Simple Complete Rungs

Goal: confirm full-rung header = sum of parts.

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 23 | `simple_rung` | NO X001, wire to AF, Out Y001 | `X001,->,:,out(Y001)` |
| 24 | `two_series_rung` | NO X001, NO X002, wire to AF, Out Y001 | `X001,X002,->,:,out(Y001)` |
| 25 | `parallel_rung` | X001 and X002 parallel OR into Out Y001 | Row 0: `X001,T,->,:,out(Y001)` / Row 1: `X002,t,...,:,...` |

**After these 3:** does header of #23 = header entries from individual captures combined? If yes, header is compositional and we can generate it from RungGrid.

## Bonus Captures — Extra Data Points

These are quick to do and could prevent wrong assumptions later.

| # | Label | Build in Click | Shorthand |
|---|-------|---------------|-----------|
| 26 | `no_ae_only` | NO contact X001 in last condition column AE | `...,X001,:,...` |
| 27 | `no_p_only` | NO contact X001 in column P (middle of grid) | `...,X001,...,:,...` |
| 28 | `no_a_C1` | NO C1 (2-char operand) in column A | `C1,...,:,...` |
| 29 | `no_a_no_b` | NO X001 in A, NO X002 in B — can you even do this? | `X001,X002,...,:,...` |

- **#26 and #27:** rules out any special casing for early columns. Does column AE/P's header entry look the same as A's?
- **#28:** same position as #14 but shorter operand. If header is identical, operand length is irrelevant to the header.
- **#29:** if Click allows adjacent contacts, what does the header look like? If it doesn't allow it, that's useful to know too.

## Analysis After Each Phase

```python
# Extract and print non-zero header entries
data = open("scratchpad/captures/<label>.bin", "rb").read()
for n in range(32):
    entry = data[0x254 + n*0x40 : 0x254 + (n+1)*0x40]
    if any(entry):
        print(f"Col {n:2d}: {entry.hex()}")
```

Compare entries between captures. Look for:
- Which entries are non-zero (column mapping)
- Which bytes within an entry change (row mapping)
- Whether the pattern is the same at different column positions (independence)

## What We're Trying to Answer

- [ ] Does header entry N correspond to column N?
- [ ] Does wire vs instruction produce different header entries?
- [ ] Does instruction type (NO/NC/Rise) change the header?
- [ ] Does output type (Out/Latch/Reset) change AF's header entry?
- [ ] What's the per-row encoding within each 64-byte entry?
- [ ] Is the header compositional (sum of parts = whole)?
