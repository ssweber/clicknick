# Profile Byte Formula Investigation — Capture Checklist

## Goal

Determine whether the per-cell profile bytes (`+0x05`, `+0x11`) and header family bytes
(`+0x17`, `+0x18`, `0x0A59`) are computed from instruction properties rather than
arbitrary per-variant constants.

## Current Status

All requested native captures for this checklist are already present in
`scratchpad/ladder_capture_manifest.json` as of 2026-03-04.

## What We Know

Current observed profile cell values (`+0x05`/`+0x11`) for two-series `row0 col4..31`:

| First Contact | Second Contact | +0x05 | +0x11 |
|---|---|---|---|
| NO | NO | 0x00 | 0x00 |
| NO.imm | NO | 0x25 | 0x52 |
| NO | NO.imm | 0x04 | 0x0C |
| NO.imm | NO.imm | 0x00 | 0x00 |
| rise | NO | 0x62 | 0x01 |
| fall | NO | 0x64 | 0x01 |

Observations suggesting a formula:

- Symmetric immediate pairs (both on or both off) produce `0x00/0x00` (cancellation).
- Asymmetric pairs produce nonzero values that differ by position (not commutative).
- Header `+0x17` progression: `0x05`, `0x0D`, `0x15` (step by 8).
- `0x0A59` mirrors `+0x05` of the header entry for second-immediate.

## Hypothesis

These bytes are computed from per-contact properties (type, immediate flag, possibly
operand bank/encoding class) combined with position index. The function is
position-sensitive and equal inputs cancel to zero.

## One-Time Setup (Current CLI)

1. Confirm working-manifest entries are present:
   - `uv run clicknick-ladder-capture entry list --type native`
2. Optionally inspect a specific entry:
   - `uv run clicknick-ladder-capture entry show --label <native_label>`

## Per-Case Workflow

No new captures are required for this checklist right now because they are already in
`scratchpad/ladder_capture_manifest.json`.

If any case needs to be re-captured:

1. Build rung natively in Click.
2. Copy rung to clipboard.
3. Capture into existing manifest entry:
   - `uv run clicknick-ladder-capture entry capture --label <native_label>`
4. If you need verify metadata, run:
   - `uv run clicknick-ladder-capture verify run --label <native_label>`

## Phase A — NC Position Variation

| ID | CSV | Native Label | Notes |
|---|---|---|---|
| `two_series_nc_no` | `~X001,X002,->,:,out(Y001)` | `two_series_nc_no_native` | captured |
| `no_first_nc_second` | `X001,~X002,->,:,out(Y001)` | `no_first_nc_second_native` | captured |
| `two_series_nc_nc` | `~X001,~X002,->,:,out(Y001)` | `two_series_nc_nc_native` | captured |

## Phase B — NC x Immediate Cross

| ID | CSV | Native Label | Notes |
|---|---|---|---|
| `nc_first_imm_no_second` | `~X001.immediate,X002,->,:,out(Y001)` | `nc_first_imm_no_second_native` | captured |
| `no_first_nc_second_imm` | `X001,~X002.immediate,->,:,out(Y001)` | `no_first_nc_second_imm_native` | captured |
| `nc_first_imm_nc_second_imm` | `~X001.immediate,~X002.immediate,->,:,out(Y001)` | `nc_first_imm_nc_second_imm_native` | captured |

## Phase C — Operand Bank Variation (No Immediate on C Bank)

Immediate mode is X-bank only for this investigation. `C1.immediate` and `C2.immediate`
cases are intentionally removed.

| ID | CSV | Native Label | Notes |
|---|---|---|---|
| `c_first_no_second` | `C1,X002,->,:,out(Y001)` | `c_first_no_second_native` | captured |
| `no_first_c_second` | `X001,C2,->,:,out(Y001)` | `no_first_c_second_native` | captured |

## Phase D — Edge in Second Position

| ID | CSV | Native Label | Notes |
|---|---|---|---|
| `no_first_rise_second` | `X001,rise(X002),->,:,out(Y001)` | `no_first_rise_second_native` | captured |
| `no_first_fall_second` | `X001,fall(X002),->,:,out(Y001)` | `no_first_fall_second_native` | captured |
| `rise_first_rise_second` | `rise(X001),rise(X002),->,:,out(Y001)` | `rise_first_rise_second_native` | captured |

## Phase E — Header Family Byte Expansion

Collect `+0x17`/`+0x18` from every capture above.

Currently known:

| Variant | +0x17 | +0x18 |
|---|---|---|
| simple NO (baseline) | 0x05 | 0x01 |
| second immediate two-series | 0x0D | 0x01 |
| everything else so far | 0x15 | 0x01 |

## Analysis Protocol (Investigator)

### Step 1: Build a Raw Table from Captured Labels

Run this from repo root to print per-label profile/header bytes using existing captures.

```powershell
@'
import json
from pathlib import Path

manifest = json.loads(Path("scratchpad/ladder_capture_manifest.json").read_text(encoding="utf-8"))
labels = [
    "two_series_nc_no_native",
    "no_first_nc_second_native",
    "two_series_nc_nc_native",
    "nc_first_imm_no_second_native",
    "no_first_nc_second_imm_native",
    "nc_first_imm_nc_second_imm_native",
    "c_first_no_second_native",
    "no_first_c_second_native",
    "no_first_rise_second_native",
    "no_first_fall_second_native",
    "rise_first_rise_second_native",
]
entries = {entry["capture_label"]: entry for entry in manifest["entries"]}

print("label,cell_05,cell_11,cell_1a,cell_1b,header_05,header_11,header_17,header_18,trailer_0a59")
for label in labels:
    payload = Path(entries[label]["payload_file"]).read_bytes()[:8192]
    cell = 0x0B60   # row0,col4
    hdr = 0x0254    # header entry 0
    print(
        f"{label},"
        f"0x{payload[cell + 0x05]:02X},"
        f"0x{payload[cell + 0x11]:02X},"
        f"0x{payload[cell + 0x1A]:02X},"
        f"0x{payload[cell + 0x1B]:02X},"
        f"0x{payload[hdr + 0x05]:02X},"
        f"0x{payload[hdr + 0x11]:02X},"
        f"0x{payload[hdr + 0x17]:02X},"
        f"0x{payload[hdr + 0x18]:02X},"
        f"0x{payload[0x0A59]:02X}"
    )
'@ | uv run python -
```

`cell=0x0B60` is `row0,col4` and `hdr=0x0254` is header entry 0.

### Step 2: Test Cancellation Hypothesis

- Do symmetric pairs produce `0x00/0x00`?
- Does `NC.imm + NC.imm` cancel like `NO.imm + NO.imm`?
- Does `rise + rise` cancel?

### Step 3: Test Position Effects

- Compare first-slot vs second-slot immediate and edge variants.
- If values are additive inverses mod 256, slot flips sign.
- If magnitudes differ, slots likely have independent weights.

### Step 4: Test Operand-Bank Dependence

- Compare `C1/X002` and `X001/C2` against X-bank analogs.
- If bytes match analogs, bank is probably not an input.
- If bytes differ, compute deltas and correlate with encoding class/length.

### Step 5: Propose Formula

Attempt formulas for `+0x05` and `+0x11` using:

- `contact_type_1`, `contact_type_2`
- `immediate_1`, `immediate_2`
- `operand_bank_1`, `operand_bank_2` (only if Step 4 shows dependence)

Also test whether `+0x17` is a bitwise OR of per-contact feature flags.

### Step 6: Validate

Validate candidate formulas against all existing captures in the manifest.
Any mismatch means the formula is incomplete.
