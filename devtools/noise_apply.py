#!/usr/bin/env python3
"""Apply a noise mask to a capture by copying donor bytes or setting constants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BUFFER_SIZE = 8192


def mask_session_noise(payload: bytes) -> bytes:
    """Apply the current session-noise normalization pass for ladder payloads."""
    if len(payload) < BUFFER_SIZE:
        raise ValueError(f"Input payload too short ({len(payload)} bytes)")

    out = bytearray(payload)
    out[0x0008:0x00B8] = b"\x00" * (0x00B8 - 0x0008)
    out[0x00B8:0x01F8] = b"\x00" * (0x01F8 - 0x00B8)

    for n in range(32):
        entry = 0x0254 + n * 0x40
        for rel in (0x11, 0x17, 0x18):
            if entry + rel < len(out):
                out[entry + rel] = 0x00

    return bytes(out)


def _coerce_offset(value: Any) -> int:
    if isinstance(value, int):
        offset = value
    elif isinstance(value, str):
        offset = int(value, 0)
    else:
        raise ValueError(f"Invalid offset value {value!r}")
    if not (0 <= offset < BUFFER_SIZE):
        raise ValueError(f"Offset out of range 0..{BUFFER_SIZE - 1}: {offset}")
    return offset


def _coerce_offset_list(values: list[Any]) -> list[int]:
    return sorted({_coerce_offset(item) for item in values})


def _extract_mask_class(mask: dict[str, Any], class_name: str) -> list[int]:
    classification = mask.get("classification")
    if isinstance(classification, dict) and class_name in classification:
        values = classification[class_name]
        if not isinstance(values, list):
            raise ValueError(f"mask.classification[{class_name!r}] must be a list")
        return _coerce_offset_list(values)
    if class_name in mask:
        values = mask[class_name]
        if not isinstance(values, list):
            raise ValueError(f"mask[{class_name!r}] must be a list")
        return _coerce_offset_list(values)
    raise KeyError(f"Mask class not found: {class_name!r}")


def resolve_offsets(
    *,
    mask: dict[str, Any],
    classes: list[str] | None = None,
    explicit_offsets: list[int] | None = None,
) -> list[int]:
    selected: set[int] = set(explicit_offsets or [])
    if classes:
        for class_name in classes:
            selected.update(_extract_mask_class(mask, class_name))
        return sorted(selected)

    if selected:
        return sorted(selected)

    global_section = mask.get("global")
    if isinstance(global_section, dict):
        volatile = global_section.get("volatile_offsets")
        if isinstance(volatile, list):
            return _coerce_offset_list(volatile)

    top_level_volatile = mask.get("volatile_offsets")
    if isinstance(top_level_volatile, list):
        return _coerce_offset_list(top_level_volatile)

    raise ValueError(
        "No offsets selected. Provide --class/--offset or ensure mask has global.volatile_offsets."
    )


def apply_copy_from_donor(input_bytes: bytes, donor_bytes: bytes, offsets: list[int]) -> tuple[bytes, int]:
    if len(input_bytes) < BUFFER_SIZE:
        raise ValueError(f"Input payload too short ({len(input_bytes)} bytes)")
    if len(donor_bytes) < BUFFER_SIZE:
        raise ValueError(f"Donor payload too short ({len(donor_bytes)} bytes)")

    output = bytearray(input_bytes)
    changed = 0
    for offset in offsets:
        old = output[offset]
        new = donor_bytes[offset]
        if old != new:
            changed += 1
        output[offset] = new
    return bytes(output), changed


def apply_set_constant(input_bytes: bytes, offsets: list[int], constant: int) -> tuple[bytes, int]:
    if not (0 <= constant <= 0xFF):
        raise ValueError(f"constant must be 0..255, got {constant}")
    if len(input_bytes) < BUFFER_SIZE:
        raise ValueError(f"Input payload too short ({len(input_bytes)} bytes)")

    output = bytearray(input_bytes)
    changed = 0
    for offset in offsets:
        old = output[offset]
        if old != constant:
            changed += 1
        output[offset] = constant
    return bytes(output), changed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Input payload .bin")
    parser.add_argument("--output", required=True, help="Output payload .bin")
    parser.add_argument("--mask-json", required=True, help="Mask JSON from noise_overlay")
    parser.add_argument(
        "--mode",
        choices=("copy-from-donor", "set-constant"),
        default="copy-from-donor",
    )
    parser.add_argument("--donor", help="Donor payload (required for copy-from-donor)")
    parser.add_argument(
        "--constant",
        help="Constant byte for set-constant mode (decimal or 0x..)",
    )
    parser.add_argument(
        "--class",
        dest="classes",
        action="append",
        default=[],
        help="Mask class name (repeatable), e.g. session_tuple_candidates",
    )
    parser.add_argument(
        "--offset",
        dest="offsets",
        action="append",
        default=[],
        help="Explicit offset (repeatable, decimal or 0x..)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    mask = json.loads(Path(args.mask_json).read_text(encoding="utf-8"))
    explicit_offsets = [_coerce_offset(raw) for raw in args.offsets]
    offsets = resolve_offsets(
        mask=mask,
        classes=args.classes,
        explicit_offsets=explicit_offsets,
    )
    if not offsets:
        raise ValueError("Resolved offset list is empty")

    input_path = Path(args.input)
    output_path = Path(args.output)
    input_bytes = input_path.read_bytes()

    if args.mode == "copy-from-donor":
        if not args.donor:
            raise ValueError("--donor is required in copy-from-donor mode")
        donor_bytes = Path(args.donor).read_bytes()
        patched, changed = apply_copy_from_donor(input_bytes, donor_bytes, offsets)
    else:
        if args.constant is None:
            raise ValueError("--constant is required in set-constant mode")
        constant = int(args.constant, 0)
        patched, changed = apply_set_constant(input_bytes, offsets, constant)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(patched)

    print("=== Noise Mask Apply ===")
    print(f"input:   {input_path}")
    print(f"output:  {output_path}")
    print(f"mode:    {args.mode}")
    print(f"offsets: {len(offsets)}")
    print(f"changed: {changed}")
    print(f"classes: {', '.join(args.classes) if args.classes else '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
