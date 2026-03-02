# Click PLC Clipboard Reverse Engineering — Handoff v7

## Goal

Reverse engineer Click Programming Software's clipboard format so pyrung (a Python ladder logic framework) can generate clipboard-ready bytes for paste-into-Click. The intermediate representation between pyrung and clipboard bytes is called **RungGrid**.

## Status

**WORKING MODULE in ClickNick. Template-based paste confirmed working for 4-char operands.**

The `clicknick.ladder` module encodes/decodes clipboard bytes and can paste rungs
into Click Programming Software. Tested with NO/NC contacts and Out coils using
4-char operands (X###, Y###). Read/write round-trip confirmed working.

**Key discovery:** The clipboard format uses a **variable-length stream**, not fixed
cells. Operand strings are stored as raw UTF-16LE and all downstream offsets shift
based on operand length. Current codec only handles 4-char operands. See finding 17.

## Module Location

`src/clicknick/ladder/` — self-contained, no imports from ClickNick's models/services/data/views.

```python
from clicknick.ladder import ClickCodec, RungGrid, read_from_clipboard, copy_to_clipboard

# Read from Click clipboard
raw = read_from_clipboard()
grid = ClickCodec().decode(raw)
print(grid.to_csv())  # "X006,->,:out(Y006)"

# Encode and paste
grid = RungGrid.from_csv("X001,->,:out(Y001)")
copy_to_clipboard(ClickCodec().encode(grid))
```

Tests: `tests/ladder/test_model.py`, `tests/ladder/test_codec.py`

## Exploration Tools (in clickplc-tools repo)

### dump_click_clipboard.py
Main capture/diff/report tool.
```
uv run dump_click_clipboard.py capture <label>    # capture + describe grid
uv run dump_click_clipboard.py diff <a> <b>       # manual diff
uv run dump_click_clipboard.py report             # full report
```

### hexcell.py
Standalone cell inspector. Dumps individual 64-byte cells from captures.
```
uv run hexcell.py <label> <row> <col>
uv run hexcell.py <label> all                     # cols 0,1,30,31 for rows 0-1
```

### runggrid_construct.py (original prototype)
Prototype with Construct structs (aspirational) + working template-based codec.
The working parts have been moved to `clicknick.ladder`.

## Grid Notation (RungGrid Format)

Interactive input after each capture:
```
start                        # begin a rung
X001,->,:out(Y001)           # contact, wire-fill, output
X002,...,:                    # contact, empty-fill, no output
                             # (empty line = blank row)
start                        # another rung
end                          # done
```

Character map: `-`→`─`  `T`→`┬`  `t`→`┴`  `+`→`┼`  `L`→`└`  `J`→`┘`  `r`→`┌`  `7`→`┐`

Special fills: `->` = wire-fill remaining columns, `...` = empty-fill remaining columns.
`:` separates condition columns (A–AE, 31 cols) from output column (AF).

## Architecture

```
pyrung DSL  →  RungGrid (spatial layout)  →  clipboard bytes  →  paste into Click
```

Target API:
```python
from runggrid import RungGrid

grid = RungGrid.from_csv("X001,->,:out(Y001)")
grid.copy_to_clipboard()  # pastes into Click

grid = RungGrid.from_clipboard(raw_bytes)
print(grid.to_csv())
```

---

## CONFIRMED FINDINGS

### 1. Fixed Buffer Size
Every capture is exactly **8192 bytes (0x2000)**. Zero-padded.

### 2. Header
```
0x0000-0x0007   Magic: "CLICK   " (8 bytes, padded with spaces)
0x0008-0x00B7   File path as UTF-16LE string (project .ckp path)
0x00B8-0x01F7   Pointer/rendering table (CRITICAL — see finding 14)
0x0254          Row count/allocation field (0x40=1 row, 0x60=2 rows)
```

### 3. Cell Grid Structure
**Cell stride: 0x40 (64 bytes) per column**

Row start offsets:
```
Row 0: 0x0A60
Row 1: 0x1260
Row 2: 0x1A60 (extrapolated, stride = 0x0800 per row = 32 cells × 0x40)
```

Cell address formula:
```
cell_offset = ROW_START[row] + col * 0x40
```

### 4. Empty Cell Template (No-Instruction Format)
```
+0x01: column index (00=A, 01=B, ... 1E=AE, 1F=AF)
+0x09-0x0A: 01 01
+0x0B-0x10: 5c 01 ff ff ff ff
+0x11: 01
+0x1D: horizontal wire flag (00=no wire, 01=wire)
+0x38: flag (01)
+0x3D: flag (01)
```

### 5. Column AF (Output Column) Marker
Col AF has `01` at +0x19 where condition columns have `00`.

### 6. Wire Encoding
Wires are **explicit** — 1 byte per cell, must be set for every wire cell.
- empty_rung → horizontal_wire_A: 1 byte at cell A +0x1D: `00`→`01`
- Wires between contact and coil: 59 bytes differ (2 bytes per cell × ~29 cells + flags)

### 7. Instruction Spillover = 2 Cells Per Instruction
Contact in col A occupies cells A-B. Coil in col AF occupies what maps to Row 1 cells A-B.
Normal cell structure resumes after spillover.

### 8. Two Cell Format Modes (fields shift with spillover count)

**2-cell spillover** (row 0 with contact, cells C onward):
```
+0x06: column counter (01=C, 02=D, etc.)
+0x0E-0x0F: 01 01
+0x12-0x15: ff ff ff ff
+0x16: 01
+0x1C: wire left flag
+0x22: wire right flag
+0x26: vertical down flag (┬)
+0x3D: flag (01)
```

**4-cell spillover** (row 1 with coil+contact, cells E onward):
```
+0x16: column counter
+0x1E-0x1F: 01 01
+0x22-0x25: ff ff ff ff
+0x26: 01 (structural)
```

### 9. Vertical Junction (┬) = Single Byte
`add_empty_row → vertical_wire: exactly 1 byte differs`
Row 0, Col C, +0x26 = 0x01. The ┴ is implicit (no separate flag).

### 10. Instruction Type IDs
```
0x2711 (10001) = ContactNO    function code "4097"
0x2712 (10002) = ContactNC    function code "4098"
0x2715 (10005) = Out (OTE)
```
Type ID location: Cell A +0x39 (low byte), +0x3A (high byte = 0x27)

### 11. Operand Encoding
Operand string is **UTF-16LE** in Cell B of the instruction spillover.
- "X001" = `58 00 30 00 30 00 31 00` starting at Cell B +0x09
- To change X001→X002: patch Cell B +0x0F from `31`('1') to `32`('2')
- Function code "4097"/"4098" as UTF-16LE at Cell B +0x23

Coil operand location (for 4-char operands):
- "Y001" at Row 1 Cell B +0x02 = `0x12A2` (UTF-16LE, 4 chars)
- Coil type ID at Row 1 Cell A +0x32 = `0x1292`
- Coil function code "8193" at Row 1 Cell B +0x2E (NOT +0x30 as previously documented)

### 12. Nickname Encoding
Nicknames stored as UTF-16LE in the instruction data stream, after coil data.
- Location: Row 1 Col C +0x14 onward
- "Test" = `54 00 65 00 73 00 74 00` at offsets +0x14, +0x16, +0x18, +0x1A
- Only 10 grid bytes differ vs no-nickname version
- Structural 0x01 flags at +5 and +8 from nickname start shift by nickname byte length

### 13. NOP Instruction
Click places NOP by default in output column. "empty_rung" has NOP; "totally_empty_rung" does not.

### 14. Clipboard Mechanism (NEW)
```
Format:     Private format 522 (0x020A), in CF_PRIVATEFIRST range (0x0200-0x02FF)
            No registered name. Only 1 format on clipboard.
Ownership:  Click checks GetClipboardOwner() — only pastes if its own window owns clipboard.
            Must call OpenClipboard(click_hwnd) before EmptyClipboard/SetClipboardData.
Read test:  Click DOES read from clipboard (garbage data = nothing pastes).
OLE:        Click exposes IDataObject via OLE clipboard (tymed=5 = HGLOBAL|ISTREAM).
            But simple Win32 SetClipboardData works if HWND ownership is spoofed.
```

Finding Click's HWND:
```python
import win32gui
def find_click_hwnd():
    results = []
    def cb(hwnd, _):
        if "CLICK Programming Software" in win32gui.GetWindowText(hwnd):
            results.append(hwnd)
        return True
    win32gui.EnumWindows(cb, None)
    return results[0]
```

Writing to clipboard:
```python
import ctypes
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
# (must set restype/argtypes for 64-bit — see runggrid.py)

user32.OpenClipboard(click_hwnd)
user32.EmptyClipboard()
hmem = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
ptr = kernel32.GlobalLock(hmem)
ctypes.memmove(ptr, data, len(data))
kernel32.GlobalUnlock(hmem)
user32.SetClipboardData(522, hmem)
user32.CloseClipboard()
```

### 15. Pointer Table — Works Across Sessions
The pointer/rendering table at 0x00B8-0x01F7 was initially feared to be a blocker,
but template-based generation works across sessions despite different pointer values.

Earlier test failures (patching live clipboard data) were likely caused by Click
internally caching the clipboard state. When we read Click's data via OLE,
EmptyClipboard, then SetClipboardData — Click receives WM_DESTROYCLIPBOARD and
may invalidate its internal cache. The "unmodified round-trip" appeared to work
because Click was pasting from its internal cache, not our clipboard data.

The template approach works because Click treats it as entirely new clipboard data
(not a modification of cached data).

### 17. Stream-Based Format — Variable-Length Operands (NEW)

The clipboard format is **not** a fixed grid of 64-byte cells. Instruction data is
a serialized stream where operand strings are stored at their actual length, and all
downstream fields shift accordingly.

**Evidence from captures with different operand lengths:**

| Operand | Chars | Contact FC offset | Coil type offset | Coil FC offset |
|---------|-------|-------------------|------------------|----------------|
| X002    | 4     | CellB +0x23       | CellA +0x32      | CellB +0x2E    |
| CT1     | 3     | CellB +0x21       | CellA +0x30      | CellB +0x2C    |
| C1      | 2     | CellB +0x1F       | CellA +0x2E      | CellB +0x2A    |

**Shift formula:** Each char fewer than 4 shifts all subsequent offsets left by 2 bytes
(one UTF-16LE char). The shift from the contact operand propagates through the coil
instruction in the next row — confirming this is a stream, not independent cells.

**Implication:** The current `ClickCodec` only works for 4-char operands (X###, Y###).
Supporting variable-length operands (C#, CT#, DS#, etc.) requires either:
1. Computing offsets dynamically based on operand string length, OR
2. Using separate templates per operand-length combination

The coil operand length likely causes a second shift for fields after it (nickname, etc.).

### 18. Single-Cell Clipboard Format

Copying a single instruction cell (not a full rung) produces a **4096-byte** buffer
(half of a full rung's 8192). Same `CLICK` magic header. The instruction data appears
at two locations: `0x02A9` and `0x0AA9` (offset `0x0800` apart), with identical content.

### 16. Operand Project Validation
Click silently drops operands that don't exist in the current project configuration.
A pasted rung will show the instruction type (e.g., "out") but not the operand
(e.g., "Y002") if that address isn't configured in the project. This is NOT a
clipboard format issue — the bytes are correct. The operands just need to exist
in the project.

**Workaround confirmed**: Adding operands directly to the project .mdb file
(via ClickNick or similar) before pasting works. Click picks up the new addresses
without needing to restart. This enables full automation:
  pyrung DSL → write addresses to .mdb → generate clipboard bytes → paste into Click

Confirmed working operand combinations (when operands exist in project):
- `X001,->,:out(Y001)` — NO contact ✓
- `~X001,->,:out(Y001)` — NC contact ✓
- `X002,->,:out(Y002)` — different operands ✓
- `X003,->,:out(Y003)` — operands added via Click UI with nicknames ✓
- `X004,->,:out(Y004)` — operands added directly to .mdb via ClickNick ✓

---

## PATCH MAP (for template-based generation)

**STATUS: WORKING for 4-char operands (X###, Y###). Template-based paste confirmed.**

Using `NO_X002_coil.AF.bin` as baseline template (ships with `clicknick.ladder`).
These offsets are ONLY valid for 4-char operands. See finding 17 for variable-length.

### Contact operand (change X register number)
| What | Offset | Example |
|------|--------|---------|
| Operand digit in "X00N" | Cell B +0x0F = `0x0AAF` | `31`('1') for X001, `32`('2') for X002 |

### Contact type (NO vs NC)
| What | Offset | NO value | NC value |
|------|--------|----------|----------|
| Type ID low byte | Cell A +0x39 = `0x0A99` | `11` (0x2711) | `12` (0x2712) |
| Function code digit | Cell B +0x29 = `0x0AC9` | `37`('7') = "4097" | `38`('8') = "4098" |

### Coil operand
| What | Offset | Example |
|------|--------|---------|
| Operand string | R1 Cell B +0x02 = `0x12A2` | "Y001" UTF-16LE |
| Type ID | R1 Cell A +0x32 = `0x1292` | `15 27` = 0x2715 (Out) |
| Function code | R1 Cell B +0x2E | "8193" UTF-16LE |

### Nickname (optional)
| What | Offset | Format |
|------|--------|--------|
| Flag | `0x12F0` | `0x02`=none, `0x01`=has nickname |
| Nickname chars | `0x12F4` | UTF-16LE, null-terminated |
| Structural flags | +5 and +8 from `0x12F4` | Shift right by nickname byte length |

---

## OPEN QUESTIONS

1. **Cell format shift formula** — fields move with spillover count. Formula unknown.

2. **Mystery values in cells** — Cell B +0x03-0x04 contains `65 60` for X registers,
   `67 60` for Y registers. These may be internal type/category IDs. Need to determine
   if these are fixed per register bank or per operand, and whether they need patching.

3. **Variable-length operand offset calculation** — confirmed that operand length
   shifts all downstream offsets (see finding 17). Need to determine the exact formula
   and whether coil operand length causes a second shift for nickname offsets.
   Captures exist for 2-char (C1), 3-char (CT1), and 4-char (X002) operands.

4. **Register bank encoding** — PARTIALLY ANSWERED. C and CT banks confirmed working
   with same type IDs (0x2711 NO, 0x2715 OUT). Operand string stored as-is. Still need
   DS, T, TD captures to confirm they follow the same pattern.

5. **Pointer/rendering table** (0x00B8-0x01F7) — no longer blocking, but structure
   still unknown. Template values from old sessions work. May become relevant when
   supporting more rung structures.

6. **Single-cell paste** — can a 4096-byte single-cell buffer be pasted? Could enable
   pasting contacts and coils independently instead of full rungs.

---

## NEXT STEPS

### Variable-length operand support (PRIORITY)
The stream-based format (finding 17) is the main blocker for non-X/Y addresses.
1. Derive offset formula from 3 existing captures (C1=2, CT1=3, X002=4 chars)
2. Update `ClickCodec` to compute offsets dynamically based on operand length
3. Test with DS### (3-char) operands to confirm formula

### Expand supported instructions
Continue captures:
1. **Latch/Reset coils** — capture to get OTL/OTU type IDs
2. **Series contacts** — capture `two_series` to understand AND layout
3. **Box instructions** — timers, math, move (wider cells, different spillover)

### CLI integration
Add `clicknick paste "X001,->,:out(Y001)"` command:
1. Validate operands exist in AddressStore
2. Add missing addresses to .mdb if needed
3. Encode and paste

### Full automation pipeline
1. pyrung generates ladder logic DSL
2. ClickNick writes required addresses/nicknames to project .mdb
3. `clicknick.ladder` generates clipboard bytes and pastes into Click
4. No manual Click interaction needed beyond having Click open

---

## Capture Inventory

### Phase 1 — DONE (10 captures)
```
empty_rung                    [grid: 1 row, NOP in output]
totally_empty_rung            [grid: 1 row, truly empty]
horizontal_wire_A             [grid: wire in col A]
horizontal_wire_AB            [grid: wire in cols A,B]
contact_A                     [grid: X001 in col A, no coil]
contact_A_coil_AF_nowire      [grid: X001 + out(Y001), no wires between]
contact_A_coil_AF             [grid: X001 + out(Y001), wires drawn]  ← old session baseline
add_empty_row                 [grid: same + empty row 1]
vertical_wire                 [grid: same + ┬ down from row 0 col B]
parallel_complete             [grid: X001/X002 parallel OR]
```

### Phase 2 — IN PROGRESS (7 of 10 done)
```
NO_X002_coil.AF               [grid: X002 + out(Y001)]  ← session 2 baseline, template for codec
NC_X001_coil.AF               [grid: ~X001 + out(Y001)]
nickname_X001                  [grid: X001('Test') + out(Y001)]
format_test                   [grid: unknown — captured to discover clipboard format]
NO_C1_coil_C2                  [grid: C1 + out(C2)]  ← 2-char operand, stream format proof
NO_CT1_coil_C10                [grid: CT1 + out(C10)]  ← 3-char contact + 3-char coil
single_NO_CT1                  [grid: single cell CT1 only]  ← 4096-byte single-cell format
```

### Phase 2 — REMAINING
| #  | Label | Change | Reveals |
|----|-------|--------|---------|
| 11 | `latch_Y001` | latch() not out() | OTL coil type ID |
| 12 | `reset_Y001` | reset() not out() | OTU coil type ID |
| 14 | `two_series` | X001,X002 series | Series AND layout |

---

## Links

- pyrung docs: https://ssweber.github.io/pyrung/
- pyrung llms.txt: https://ssweber.github.io/pyrung/llms.txt
- Click dialect: https://ssweber.github.io/pyrung/dialects/click/index.md
- Ladder logic reference: https://ssweber.github.io/pyrung/guides/ladder-logic/index.md
