import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from devtools.march8_wireframe_synth import (  # noqa: E402
    METADATA_BAND,
    PREFIX_END,
    ROW1_BAND,
    SCENARIOS,
    synthesize_scenario_bytes,
)
from clicknick.ladder.topology import (  # noqa: E402
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    cell_offset,
)


BUFFER_LEN = ROW1_BAND.stop


def _make_donor(fill: int) -> bytearray:
    data = bytearray([fill] * BUFFER_LEN)
    for row in range(2):
        for col in range(COLS_PER_ROW):
            start = cell_offset(row, col)
            data[start + CELL_HORIZONTAL_LEFT_OFFSET] = 0xCC
            data[start + CELL_HORIZONTAL_RIGHT_OFFSET] = 0xCC
            data[start + CELL_VERTICAL_DOWN_OFFSET] = 0xCC
    return data


def _donor_payloads() -> dict[str, bytes]:
    empty = _make_donor(0x11)
    fullwire = _make_donor(0x22)
    rows2 = _make_donor(0x33)

    empty[0: PREFIX_END] = bytes([0x41]) * PREFIX_END
    fullwire[0: PREFIX_END] = bytes([0x42]) * PREFIX_END
    rows2[0: PREFIX_END] = bytes([0x43]) * PREFIX_END

    empty[METADATA_BAND] = bytes([0x51]) * len(range(*METADATA_BAND.indices(BUFFER_LEN)))
    fullwire[METADATA_BAND] = bytes([0x52]) * len(range(*METADATA_BAND.indices(BUFFER_LEN)))
    rows2[METADATA_BAND] = bytes([0x53]) * len(range(*METADATA_BAND.indices(BUFFER_LEN)))

    empty[ROW1_BAND] = bytes([0x61]) * len(range(*ROW1_BAND.indices(BUFFER_LEN)))
    fullwire[ROW1_BAND] = bytes([0x62]) * len(range(*ROW1_BAND.indices(BUFFER_LEN)))
    rows2[ROW1_BAND] = bytes([0x63]) * len(range(*ROW1_BAND.indices(BUFFER_LEN)))

    donors = {
        SCENARIOS["empty_1row"].base_file: bytes(empty),
        SCENARIOS["fullwire_1row"].row1_file: bytes(fullwire),
        SCENARIOS["empty_2row"].base_file: bytes(rows2),
    }
    return donors


def test_fullwire_1row_uses_empty_prefix_and_fullwire_row1_band() -> None:
    payload = synthesize_scenario_bytes("fullwire_1row", _donor_payloads())

    assert payload[:PREFIX_END] == bytes([0x41]) * PREFIX_END
    assert payload[ROW1_BAND] == bytes([0x62]) * len(payload[ROW1_BAND])

    for col in range(COLS_PER_ROW - 1):
        start = cell_offset(0, col)
        assert payload[start + CELL_HORIZONTAL_LEFT_OFFSET] == 1
        assert payload[start + CELL_HORIZONTAL_RIGHT_OFFSET] == 1
        assert payload[start + CELL_VERTICAL_DOWN_OFFSET] == 0

    af_cell = cell_offset(0, COLS_PER_ROW - 1)
    assert payload[af_cell + CELL_HORIZONTAL_LEFT_OFFSET] == 0
    assert payload[af_cell + CELL_HORIZONTAL_RIGHT_OFFSET] == 0


def test_fullwire_nop_1row_sets_af_cell_wire_pair() -> None:
    payload = synthesize_scenario_bytes("fullwire_nop_1row", _donor_payloads())
    af_cell = cell_offset(0, COLS_PER_ROW - 1)
    assert payload[af_cell + CELL_HORIZONTAL_LEFT_OFFSET] == 1
    assert payload[af_cell + CELL_HORIZONTAL_RIGHT_OFFSET] == 1


def test_empty_2row_uses_rows2_prefix_and_terminal_bytes() -> None:
    payload = synthesize_scenario_bytes("empty_2row", _donor_payloads())

    assert payload[:PREFIX_END] == bytes([0x43]) * PREFIX_END
    assert payload[GRID_FIRST_ROW_START - 0x0C] == 0x33
    row1_cell0 = cell_offset(1, 0)
    assert payload[row1_cell0 + 0x24] == 0x63
    assert payload[row1_cell0 + 0x35] == 0x63

    row0_col31 = cell_offset(0, COLS_PER_ROW - 1)
    assert payload[row0_col31 + 0x38] == 0x01
    assert payload[row0_col31 + 0x3D] == 0x02

    metadata_start = METADATA_BAND.start
    assert payload[metadata_start + 0x00] == 0x60
    assert payload[metadata_start + 0x01] == 0x00


def test_vert_horiz_2row_overlays_row0_and_row1_wire_flags() -> None:
    payload = synthesize_scenario_bytes("vert_horiz_2row", _donor_payloads())

    row0_col1 = cell_offset(0, 1)
    assert payload[row0_col1 + CELL_HORIZONTAL_LEFT_OFFSET] == 1
    assert payload[row0_col1 + CELL_HORIZONTAL_RIGHT_OFFSET] == 1
    assert payload[row0_col1 + CELL_VERTICAL_DOWN_OFFSET] == 1

    row1_col1 = cell_offset(1, 1)
    assert payload[row1_col1 + CELL_HORIZONTAL_LEFT_OFFSET] == 1
    assert payload[row1_col1 + CELL_HORIZONTAL_RIGHT_OFFSET] == 1
    assert payload[row1_col1 + CELL_VERTICAL_DOWN_OFFSET] == 0

    row1_col0 = cell_offset(1, 0)
    assert payload[row1_col0 + CELL_HORIZONTAL_LEFT_OFFSET] == 0
    assert payload[row1_col0 + CELL_HORIZONTAL_RIGHT_OFFSET] == 0
