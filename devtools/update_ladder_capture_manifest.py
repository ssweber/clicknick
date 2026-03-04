"""Regenerate ladder capture manifest with schema v2 metadata."""

from __future__ import annotations

import csv
import json
import re
from io import StringIO
from pathlib import Path

from clicknick.ladder.codec import ClickCodec
from clicknick.ladder.csv_contract import CONDITION_COLUMNS
from clicknick.ladder.csv_shorthand import normalize_shorthand_row
from clicknick.ladder.topology import header_structural_equal, parse_wire_topology

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "ladder_captures" / "manifest.json"
FIXTURES_DIR = MANIFEST_PATH.parent
CAPTURE_CHECKLIST_PATH = ROOT / "scratchpad" / "capture-checklist.md"
INSTRUCTION_CHECKLIST_PATH = ROOT / "scratchpad" / "instruction-capture-checklist.md"
INSTRUCTION_MATRIX_PATH = ROOT / "scratchpad" / "instruction-matrix.json"

TODO_LABELS = {
    "nc_a_immediate_only",
    "no_a_immediate_only",
    "no_c_immediate_only",
    "pasteback_vert_b_with_horiz",
}

_TOKEN_NORMALIZATION = {
    r"\|": "|",
    "t": "-",
    "r": "T",
}

_COLUMN_INDEX = {name: idx for idx, name in enumerate(CONDITION_COLUMNS)}
_COLUMN_HINTS = {
    "wire_c_only": [{"C": "-"}],
    "wire_a_and_e": [{"A": "-", "E": "-"}],
    "vert_b_only": [{"B": "|"}, {"B": "|"}],
    "vert_b_with_horiz": [{"B": "T"}, {"B": "-"}],
    "corner_b": [{"A": "-", "B": "T"}, {"B": "|"}],
    "vert_d_only": [{"D": "|"}, {"D": "|"}],
    "vert_b_3rows": [{"B": "|"}, {"B": "|"}, {"B": "|"}],
    "no_c_only": [{"C": "X001"}],
    "no_a_no_c": [{"A": "X001", "C": "X002"}],
    "no_ae_only": [{"AE": "X001"}],
    "no_p_only": [{"P": "X001"}],
}


def _split_markdown_row(line: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    idx = 0
    while idx < len(line):
        ch = line[idx]
        if ch == "\\" and idx + 1 < len(line) and line[idx + 1] == "|":
            current.append("|")
            idx += 2
            continue
        if ch == "|":
            fields.append("".join(current).strip())
            current = []
            idx += 1
            continue
        current.append(ch)
        idx += 1

    fields.append("".join(current).strip())
    if len(fields) >= 2 and fields[0] == "" and fields[-1] == "":
        return fields[1:-1]
    return fields


def _iter_markdown_tables(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = _split_markdown_row(line)
        if not cells:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def _strip_code(value: str) -> str:
    text = value.strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        return text[1:-1]
    return text


def _normalize_raw_row(text: str) -> str:
    fields = next(csv.reader(StringIO(text)), [])
    normalized = [_TOKEN_NORMALIZATION.get(field.strip(), field.strip()) for field in fields]
    return ",".join(normalized)


def _ensure_separator_and_af(row: str) -> str:
    return f"{row},:,..." if ":" not in row else row


def _parse_row_fields(row: str) -> tuple[list[str], str]:
    normalized = _ensure_separator_and_af(_normalize_raw_row(row))
    fields = [token.strip() for token in next(csv.reader(StringIO(normalized)), [])]
    colon_positions = [idx for idx, token in enumerate(fields) if token == ":"]
    if len(colon_positions) != 1:
        raise ValueError(f"Expected exactly one ':' separator in row {row!r}")
    colon_idx = colon_positions[0]
    if colon_idx != len(fields) - 2:
        raise ValueError(f"Expected AF token immediately after ':' in row {row!r}")
    return fields[:colon_idx], fields[-1]


def _extract_af_token(row: str) -> str:
    _conditions, af = _parse_row_fields(row)
    return af


def _canonicalize_row(raw_row: str, *, marker: str) -> str:
    conditions, af = _parse_row_fields(raw_row)
    canonical = ",".join([marker, *conditions, ":", af])
    normalize_shorthand_row(canonical)
    return canonical


def _row_from_hints(
    *,
    marker: str,
    column_tokens: dict[str, str],
    af: str,
) -> str:
    if not column_tokens:
        raise ValueError("Expected at least one column token override")

    indexed = {
        _COLUMN_INDEX[column]: _TOKEN_NORMALIZATION.get(token, token)
        for column, token in column_tokens.items()
    }
    max_index = max(indexed)
    fields = [""] * (max_index + 1)
    for idx, token in indexed.items():
        fields[idx] = token

    row_tokens = [marker, *fields]
    if max_index < len(CONDITION_COLUMNS) - 1:
        row_tokens.append("...")
    row_tokens.extend([":", af])
    row = ",".join(row_tokens)
    normalize_shorthand_row(row)
    return row


def _build_capture_metadata() -> dict[str, tuple[str, list[str]]]:
    metadata: dict[str, tuple[str, list[str]]] = {}
    for cells in _iter_markdown_tables(CAPTURE_CHECKLIST_PATH):
        if len(cells) != 4:
            continue
        if not cells[0].isdigit():
            continue
        label = _strip_code(cells[1])
        description = cells[2].strip()
        raw_rows = re.findall(r"`([^`]+)`", cells[3])
        if not raw_rows:
            raise ValueError(f"Could not parse shorthand rows for capture label {label!r}")

        if label in _COLUMN_HINTS:
            hints = _COLUMN_HINTS[label]
            if len(hints) != len(raw_rows):
                raise ValueError(
                    f"Override row count mismatch for {label!r}: hints={len(hints)} rows={len(raw_rows)}"
                )
            rung_rows = [
                _row_from_hints(
                    marker="R" if row_index == 0 else "",
                    column_tokens=hints[row_index],
                    af=_extract_af_token(raw_rows[row_index]),
                )
                for row_index in range(len(raw_rows))
            ]
        else:
            rung_rows = [
                _canonicalize_row(raw_row, marker="R" if row_index == 0 else "")
                for row_index, raw_row in enumerate(raw_rows)
            ]
        metadata[label] = (description, rung_rows)
    return metadata


def _build_instruction_metadata() -> dict[str, tuple[str, list[str]]]:
    matrix = json.loads(INSTRUCTION_MATRIX_PATH.read_text(encoding="utf-8"))
    scenario_by_native_label = {
        case["native_label"]: case["scenario"] for case in matrix["cases"]
    }

    metadata: dict[str, tuple[str, list[str]]] = {}
    for cells in _iter_markdown_tables(INSTRUCTION_CHECKLIST_PATH):
        if len(cells) != 3:
            continue
        if cells[0].strip() == "ID":
            continue
        matrix_id = _strip_code(cells[0])
        if not matrix_id:
            continue
        csv_row = _strip_code(cells[1])
        native_label = _strip_code(cells[2])
        description = scenario_by_native_label.get(native_label)
        if description is None:
            raise ValueError(f"No instruction-matrix case found for native label {native_label!r}")
        metadata[native_label] = (description, [_canonicalize_row(csv_row, marker="R")])
    return metadata


def _codec_generatable(codec: ClickCodec, fixture_path: Path) -> bool:
    fixture = fixture_path.read_bytes()
    try:
        decoded = codec.decode(fixture)
        generated = codec.encode(decoded)
        return header_structural_equal(generated, fixture) and (
            parse_wire_topology(generated) == parse_wire_topology(fixture)
        )
    except Exception:
        return False


def _build_enriched_manifest() -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    capture_metadata = _build_capture_metadata()
    instruction_metadata = _build_instruction_metadata()
    metadata_by_label = {**capture_metadata, **instruction_metadata}

    entries = manifest["entries"]
    manifest_labels = {entry["capture_label"] for entry in entries}
    expected_metadata_labels = manifest_labels - TODO_LABELS
    missing_metadata = sorted(expected_metadata_labels - metadata_by_label.keys())
    if missing_metadata:
        raise ValueError(f"Metadata missing for manifest labels: {missing_metadata}")

    codec = ClickCodec()
    enriched_entries: list[dict[str, object]] = []
    for entry in entries:
        label = entry["capture_label"]
        if label in TODO_LABELS:
            description = ""
            rung_rows: list[str] = []
            metadata_todo = True
        else:
            description, rung_rows = metadata_by_label[label]
            metadata_todo = False

        enriched_entries.append(
            {
                "fixture_file": entry["fixture_file"],
                "capture_label": label,
                "scenario": entry["scenario"],
                "source": entry["source"],
                "description": description,
                "rung_rows": rung_rows,
                "verified": False,
                "codec_generatable": _codec_generatable(codec, FIXTURES_DIR / entry["fixture_file"]),
                "metadata_todo": metadata_todo,
            }
        )

    return {
        "version": 2,
        "description": manifest["description"],
        "entries": enriched_entries,
    }


def main() -> int:
    manifest = _build_enriched_manifest()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {MANIFEST_PATH}")
    print(f"Schema version: {manifest['version']}")
    print(f"Entries: {len(manifest['entries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
