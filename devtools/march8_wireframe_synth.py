#!/usr/bin/env python3
"""Offline March 8 wireframe synthesizer for clean no-comment baselines.

This helper is intentionally scoped to the March 8, 2026 clean donor set.
It does not attempt comment synthesis. It assembles exact no-comment payloads
for the five accepted wireframe targets by combining:

- a donor-backed prefix band (`0x0000..0x0253`)
- a metadata band (`0x0254..0x0A53`)
- a gap band (`0x0A54..0x0A5F`)
- a synthesized row0 band (`0x0A60..0x125F`)
- an optional donor-backed / overlay-patched row1 band (`0x1260..0x1A5F`)
- a donor-backed tail band (`0x1A60..0x1FFF`)

The current Phase 3 boundary is deliberate:
- row0 visible wire structure is written explicitly;
- row1 visible wire overlays for the 2-row mixed case are written explicitly;
- row1 companion-family bytes remain donor-backed for now.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from clicknick.ladder.topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    HEADER_ENTRY_BASE,
    cell_offset,
)

PREFIX_END = HEADER_ENTRY_BASE
GAP_BAND_START = GRID_FIRST_ROW_START - 0x0C
METADATA_BAND = slice(HEADER_ENTRY_BASE, GAP_BAND_START)
GAP_BAND = slice(GAP_BAND_START, GRID_FIRST_ROW_START)
ROW0_BAND = slice(GRID_FIRST_ROW_START, GRID_FIRST_ROW_START + 0x800)
ROW1_BAND = slice(GRID_FIRST_ROW_START + 0x800, GRID_FIRST_ROW_START + 0x1000)
DEFAULT_TEMPLATE_FILE = Path("scratchpad/phase3_wireframe_band_templates_20260308.json")


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    target_file: str
    logical_rows: int
    condition_rows: tuple[tuple[str, ...], ...]
    band_template_names: tuple[str, ...] = ()
    af_nop_rows: frozenset[int] = frozenset()


@dataclass(frozen=True)
class BandTemplate:
    start: int
    stop: int
    payload: bytes
    changed_byte_count_vs_empty_1row: int


@dataclass(frozen=True)
class WireframeBandTemplates:
    base_file: str
    bands: Mapping[str, BandTemplate]


def _blank_row() -> tuple[str, ...]:
    return ("",) * (COLS_PER_ROW - 1)


def _fullwire_row() -> tuple[str, ...]:
    return ("-",) * (COLS_PER_ROW - 1)


def _row_with_tokens(*, mapping: Mapping[int, str]) -> tuple[str, ...]:
    row = [""] * (COLS_PER_ROW - 1)
    for col, token in mapping.items():
        if not (0 <= col < COLS_PER_ROW - 1):
            raise ValueError(f"Condition column out of range: {col}")
        row[col] = token
    return tuple(row)


SCENARIOS: dict[str, ScenarioSpec] = {
    "empty_1row": ScenarioSpec(
        name="empty_1row",
        target_file="grcecr_empty_native_20260308.bin",
        logical_rows=1,
        condition_rows=(_blank_row(),),
    ),
    "fullwire_1row": ScenarioSpec(
        name="fullwire_1row",
        target_file="grcecr_fullwire_native_20260308.bin",
        logical_rows=1,
        condition_rows=(_fullwire_row(),),
        band_template_names=("fullwire_1row_row1_band", "shared_tail_band"),
    ),
    "fullwire_nop_1row": ScenarioSpec(
        name="fullwire_nop_1row",
        target_file="grcecr_fullwire_nop_native_20260308.bin",
        logical_rows=1,
        condition_rows=(_fullwire_row(),),
        band_template_names=("fullwire_1row_row1_band", "shared_tail_band"),
        af_nop_rows=frozenset({0}),
    ),
    "empty_2row": ScenarioSpec(
        name="empty_2row",
        target_file="grcecr_rows2_empty_native_20260308.bin",
        logical_rows=2,
        condition_rows=(_blank_row(), _blank_row()),
        band_template_names=("rows2_prefix_band", "rows2_empty_row1_band", "shared_tail_band"),
    ),
    "vert_horiz_2row": ScenarioSpec(
        name="vert_horiz_2row",
        target_file="grcecr_rows2_vert_horiz_native_20260308.bin",
        logical_rows=2,
        condition_rows=(
            _row_with_tokens(mapping={1: "T"}),
            _row_with_tokens(mapping={1: "-"}),
        ),
        band_template_names=("rows2_prefix_band", "rows2_empty_row1_band", "shared_tail_band"),
    ),
}


def _validate_donor_size(name: str, payload: bytes) -> None:
    if len(payload) < ROW1_BAND.stop:
        raise ValueError(f"Donor {name!r} is too short for the March 8 wireframe bands: {len(payload)} bytes")


def _copy_band(dst: bytearray, src: bytes, band: slice) -> None:
    dst[band] = src[band]


def _apply_band_template(dst: bytearray, template: BandTemplate) -> None:
    dst[template.start : template.stop] = template.payload


def _tail_region_for(payload: bytes) -> slice:
    return slice(ROW1_BAND.stop, len(payload))


def _row_word(logical_rows: int) -> int:
    return (logical_rows + 1) * 0x20


def _apply_row_word(payload: bytearray, logical_rows: int) -> None:
    row_word = _row_word(logical_rows)
    payload[HEADER_ENTRY_BASE + 0x00] = row_word & 0xFF
    payload[HEADER_ENTRY_BASE + 0x01] = (row_word >> 8) & 0xFF


def _clear_visible_wire_flags(payload: bytearray, logical_rows: int) -> None:
    for row_idx in range(logical_rows):
        for col_idx in range(COLS_PER_ROW):
            start = cell_offset(row_idx, col_idx)
            payload[start + CELL_HORIZONTAL_LEFT_OFFSET] = 0
            payload[start + CELL_HORIZONTAL_RIGHT_OFFSET] = 0
            payload[start + CELL_VERTICAL_DOWN_OFFSET] = 0


def _flags_for_token(token: str) -> tuple[int, int, int]:
    if token == "-":
        return (1, 1, 0)
    if token == "T":
        return (1, 1, 1)
    if token == "|":
        return (0, 0, 1)
    if token == "":
        return (0, 0, 0)
    raise ValueError(f"Unsupported token: {token!r}")


def _apply_condition_rows(payload: bytearray, condition_rows: tuple[tuple[str, ...], ...]) -> None:
    for row_idx, row_tokens in enumerate(condition_rows):
        if len(row_tokens) != COLS_PER_ROW - 1:
            raise ValueError(f"Row {row_idx} must have {COLS_PER_ROW - 1} condition cells")
        for col_idx, token in enumerate(row_tokens):
            left, right, down = _flags_for_token(token)
            start = cell_offset(row_idx, col_idx)
            payload[start + CELL_HORIZONTAL_LEFT_OFFSET] = left
            payload[start + CELL_HORIZONTAL_RIGHT_OFFSET] = right
            payload[start + CELL_VERTICAL_DOWN_OFFSET] = down


def _apply_af_nop_rows(payload: bytearray, rows: frozenset[int]) -> None:
    for row_idx in rows:
        start = cell_offset(row_idx, COLS_PER_ROW - 1)
        payload[start + CELL_HORIZONTAL_LEFT_OFFSET] = 1
        payload[start + CELL_HORIZONTAL_RIGHT_OFFSET] = 1


def _apply_two_row_terminal_bytes(payload: bytearray) -> None:
    row0_col31 = cell_offset(0, COLS_PER_ROW - 1)
    payload[row0_col31 + 0x38] = 0x01
    payload[row0_col31 + 0x3D] = 0x02


def synthesize_scenario_bytes(
    scenario_name: str,
    donor_payloads: Mapping[str, bytes],
    wireframe_band_templates: WireframeBandTemplates,
) -> bytes:
    scenario = SCENARIOS[scenario_name]
    base = donor_payloads[wireframe_band_templates.base_file]
    _validate_donor_size(wireframe_band_templates.base_file, base)

    out = bytearray(base)
    _copy_band(out, base, METADATA_BAND)
    _copy_band(out, base, GAP_BAND)
    _copy_band(out, base, ROW0_BAND)
    _copy_band(out, base, ROW1_BAND)

    for template_name in scenario.band_template_names:
        _apply_band_template(out, wireframe_band_templates.bands[template_name])

    _apply_row_word(out, scenario.logical_rows)
    _clear_visible_wire_flags(out, scenario.logical_rows)
    if scenario.logical_rows == 2:
        _apply_two_row_terminal_bytes(out)
    _apply_condition_rows(out, scenario.condition_rows)
    _apply_af_nop_rows(out, scenario.af_nop_rows)
    return bytes(out)


def diff_counts_by_band(left: bytes, right: bytes) -> dict[str, int]:
    tail = _tail_region_for(left)
    return {
        "prefix_band": sum(x != y for x, y in zip(left[:PREFIX_END], right[:PREFIX_END])),
        "metadata_band": sum(x != y for x, y in zip(left[METADATA_BAND], right[METADATA_BAND])),
        "gap_band": sum(x != y for x, y in zip(left[GAP_BAND], right[GAP_BAND])),
        "row0_band": sum(x != y for x, y in zip(left[ROW0_BAND], right[ROW0_BAND])),
        "row1_band": sum(x != y for x, y in zip(left[ROW1_BAND], right[ROW1_BAND])),
        "tail_band": sum(x != y for x, y in zip(left[tail], right[tail])),
        "full": sum(x != y for x, y in zip(left, right)) + abs(len(left) - len(right)),
    }


def _load_donors(capture_dir: Path) -> dict[str, bytes]:
    needed = {"grcecr_empty_native_20260308.bin"} | {spec.target_file for spec in SCENARIOS.values()}
    donors: dict[str, bytes] = {}
    for filename in sorted(needed):
        path = capture_dir / filename
        donors[filename] = path.read_bytes()
    return donors


def _load_wireframe_band_templates(path: Path) -> WireframeBandTemplates:
    raw = json.loads(path.read_text())
    bands = {
        name: BandTemplate(
            start=spec["start"],
            stop=spec["stop"],
            payload=bytes.fromhex(spec["bytes_hex"]),
            changed_byte_count_vs_empty_1row=spec["changed_byte_count_vs_empty_1row"],
        )
        for name, spec in raw["bands"].items()
    }
    return WireframeBandTemplates(base_file=raw["base_file"], bands=bands)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=[*SCENARIOS.keys(), "all"],
        default="all",
        help="Scenario to synthesize (default: all)",
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=Path("scratchpad/captures"),
        help="Directory containing March 8 canonical donor captures",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory to write synthesized payloads",
    )
    parser.add_argument(
        "--template-file",
        type=Path,
        default=DEFAULT_TEMPLATE_FILE,
        help="JSON file containing explicit March 8 band templates",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    donors = _load_donors(args.capture_dir)
    wireframe_band_templates = _load_wireframe_band_templates(args.template_file)

    scenario_names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results: list[dict[str, object]] = []
    for scenario_name in scenario_names:
        spec = SCENARIOS[scenario_name]
        synthesized = synthesize_scenario_bytes(scenario_name, donors, wireframe_band_templates)
        target = (args.capture_dir / spec.target_file).read_bytes()
        diffs = diff_counts_by_band(synthesized, target)

        output_file = None
        if args.output_dir is not None:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output_file = args.output_dir / f"{scenario_name}_march8_wireframe.bin"
            output_file.write_bytes(synthesized)

        results.append(
            {
                "scenario": scenario_name,
                "target_file": spec.target_file,
                "output_file": str(output_file) if output_file is not None else None,
                "band_template_names": list(spec.band_template_names),
                "diffs": diffs,
            }
        )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f"scenario={result['scenario']}")
            if result["output_file"] is not None:
                print(f"output_file={result['output_file']}")
            for key, value in result["diffs"].items():
                print(f"{key}={value}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
