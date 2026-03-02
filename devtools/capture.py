"""Clipboard capture analysis tool for Click PLC reverse engineering.

Usage:
    uv run devtools/capture.py [label]

Reads Click clipboard data, prints a structural analysis report, and optionally
saves the .bin file to scratchpad/captures/<label>.bin.

The analysis is stream-based: it finds type IDs (0x27XX markers) and probes
at known relative offsets for operands and function codes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from clicknick.ladder.clipboard import read_from_clipboard
from clicknick.ladder.codec import (
    BUFFER_SIZE,
    CELL_SIZE,
    COLS_PER_ROW,
    ROW_STARTS,
    _load_template,
)
from clicknick.ladder.model import InstructionType

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "scratchpad" / "captures"
GRID_START = min(ROW_STARTS.values())

# --- Stream-relative offsets (from type ID byte) ---
# These are consistent across all instruction types tested so far.
TYPE_TO_OPERAND = 16  # type_id + 16 = operand start (UTF-16LE)
TYPE_TO_FUNC_CONTACT = 42  # type_id + 42 = func code for contacts
TYPE_TO_FUNC_COIL = 60  # type_id + 60 = func code for coils

# Known type ID names
TYPE_NAMES: dict[int, str] = {t.value: t.name for t in InstructionType}
TYPE_NAMES.update({0x13: "EDGE (rise/fall)"})

# Known func codes (value -> description)
FUNC_CODE_NAMES: dict[str, str] = {
    "4097": "NO",
    "4098": "NC",
    "4099": "NO immediate",
    "4100": "NC immediate",
    "4101": "Rise",
    "4102": "Fall",
    "8193": "Out",
}

# Operand pattern: 1-3 uppercase letters + 1-4 digits
_OPERAND_RE = re.compile(r"^[A-Z]{1,3}\d{1,4}$")


def _read_utf16le(data: bytes, offset: int, max_chars: int = 8) -> str | None:
    """Read a null-terminated UTF-16LE string at offset. Returns None if invalid."""
    chars = []
    for i in range(max_chars):
        pos = offset + i * 2
        if pos + 1 >= len(data):
            break
        c = data[pos] | (data[pos + 1] << 8)
        if c == 0:
            break
        if not (0x20 <= c < 0x7F):
            return None
        chars.append(chr(c))
    return "".join(chars) if chars else None


def locate(offset: int) -> str:
    """Describe an absolute offset's position in the buffer."""
    for row, start in sorted(ROW_STARTS.items()):
        end = start + COLS_PER_ROW * CELL_SIZE
        if start <= offset < end:
            rel = offset - start
            return f"row{row} +0x{rel:03X}"
    if offset < GRID_START:
        return "header"
    return f"+0x{offset:04X}"


def scan_type_ids(data: bytes) -> list[tuple[int, int, str]]:
    """Find all 0x27XX patterns in the grid region."""
    results = []
    for i in range(GRID_START, len(data) - 1):
        if data[i + 1] == 0x27 and data[i] != 0x00:
            type_byte = data[i]
            name = TYPE_NAMES.get(type_byte, f"UNKNOWN_0x{type_byte:02X}")
            results.append((i, type_byte, name))
    return results


def probe_instruction(data: bytes, type_offset: int, is_coil: bool = False) -> dict:
    """Probe stream-relative offsets from a type ID to extract instruction details."""
    info: dict = {"type_offset": type_offset}

    # Type ID
    info["type_byte"] = data[type_offset]
    info["type_name"] = TYPE_NAMES.get(info["type_byte"], f"UNKNOWN_0x{info['type_byte']:02X}")

    # Operand at type + 16
    op_offset = type_offset + TYPE_TO_OPERAND
    operand = _read_utf16le(data, op_offset)
    if operand and _OPERAND_RE.match(operand):
        info["operand"] = operand
        info["operand_offset"] = op_offset
        info["operand_chars"] = len(operand)
    else:
        info["operand"] = None

    # Func code — try standard offset first, then +2 (immediate flag shifts it)
    fc_base = TYPE_TO_FUNC_COIL if is_coil else TYPE_TO_FUNC_CONTACT
    for fc_delta in (fc_base, fc_base + 2):
        fc_offset = type_offset + fc_delta
        fc_str = _read_utf16le(data, fc_offset, max_chars=4)
        if fc_str and fc_str.isdigit() and len(fc_str) == 4:
            info["func_code"] = fc_str
            info["func_code_offset"] = fc_offset
            info["func_code_delta"] = fc_delta
            info["func_code_name"] = FUNC_CODE_NAMES.get(fc_str, "UNKNOWN")
            break

    return info


def check_nickname(data: bytes) -> tuple[int, str | None]:
    """Check nickname flag and decode string if present."""
    flag_offset = 0x12F0
    if flag_offset >= len(data):
        return 0, None
    flag = data[flag_offset]
    if flag == 0x01:
        nickname = _read_utf16le(data, 0x12F4)
        return flag, nickname
    return flag, None


def template_diff(data: bytes, template: bytes, max_diffs: int = 30) -> list[tuple[int, int, int]]:
    """Diff data against template, grid region only."""
    diffs = []
    for i in range(GRID_START, min(len(data), len(template))):
        if data[i] != template[i]:
            diffs.append((i, template[i], data[i]))
    return diffs[:max_diffs]


def print_report(data: bytes, label: str | None = None) -> None:
    """Print structural analysis of clipboard data."""
    size_desc = (
        "full rung"
        if len(data) == BUFFER_SIZE
        else "single cell"
        if len(data) == 4096
        else "unknown"
    )
    print("\n=== Click Clipboard Capture ===")
    print(f"Size: {len(data)} bytes ({size_desc})")
    if label:
        print(f"Label: {label}")

    # Find type IDs and probe each instruction
    type_ids = scan_type_ids(data)

    if not type_ids:
        print("\n  (no type IDs found)")
        print()
        return

    for idx, (offset, _type_byte, _name) in enumerate(type_ids):
        # Heuristic: first type ID is contact, second is coil
        is_coil = idx > 0
        role = "Coil" if is_coil else "Contact"
        info = probe_instruction(data, offset, is_coil=is_coil)

        print(f"\n--- {role} ---")
        print(
            f"  Type:      0x27{info['type_byte']:02X}  {info['type_name']:<20s} @ 0x{offset:04X} ({locate(offset)})"
        )

        if info.get("operand"):
            print(
                f"  Operand:   {info['operand']!r:<8s} {info['operand_chars']} chars"
                f"          @ 0x{info['operand_offset']:04X} (type+{TYPE_TO_OPERAND})"
            )
        else:
            print("  Operand:   (not found at type+16)")

        if info.get("func_code"):
            delta = info["func_code_delta"]
            shifted = (
                " (shifted +2, immediate?)"
                if delta != (TYPE_TO_FUNC_COIL if is_coil else TYPE_TO_FUNC_CONTACT)
                else ""
            )
            print(
                f"  Func code: {info['func_code']!r:<8s} {info['func_code_name']:<20s}"
                f" @ 0x{info['func_code_offset']:04X} (type+{delta}){shifted}"
            )
        else:
            print(
                f"  Func code: (not found at type+{TYPE_TO_FUNC_COIL if is_coil else TYPE_TO_FUNC_CONTACT})"
            )

    # Nickname
    flag, nickname = check_nickname(data)
    print("\n--- Nickname ---")
    flag_desc = "has nickname" if flag == 0x01 else "none" if flag == 0x02 else f"0x{flag:02X}"
    print(f"  0x12F0: 0x{flag:02X} ({flag_desc})", end="")
    if nickname:
        print(f'  "{nickname}"')
    else:
        print()

    # Template diff
    if len(data) == BUFFER_SIZE:
        template = _load_template()
        diffs = template_diff(data, template)
        total = sum(
            1 for i in range(GRID_START, min(len(data), len(template))) if data[i] != template[i]
        )
        print("\n--- Template Diff (vs NO_X002_coil.AF, grid only) ---")
        print(f"  {total} byte diffs")
        for offset, old, new in diffs:
            old_ch = chr(old) if 0x20 <= old < 0x7F else "."
            new_ch = chr(new) if 0x20 <= new < 0x7F else "."
            print(
                f"  0x{offset:04X}: {old:02X}->{new:02X}  '{old_ch}'->'{new_ch}'  ({locate(offset)})"
            )
        if total > len(diffs):
            print(f"  ... ({total - len(diffs)} more)")

    print()


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else None

    data = read_from_clipboard()
    print_report(data, label)

    if label:
        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        path = CAPTURES_DIR / f"{label}.bin"
        path.write_bytes(data)
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
