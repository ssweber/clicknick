"""Ladder module — encode/decode Click PLC clipboard rungs."""

from .clipboard import clear_clipboard, copy_to_clipboard, read_from_clipboard
from .codec import ClickCodec, EncodeResult, HeaderSeed
from .codec_v2 import LadderRungV2, V2Degradation, V2EncodeReport, V2UnsupportedShapeError
from .empty_multirow import (
    EMPTY_MULTIROW_MAX_ROWS,
    EMPTY_MULTIROW_MIN_ROWS,
    empty_multirow_payload_length,
    empty_multirow_row_word,
    synthesize_empty_multirow,
)
from .nonempty_multirow import (
    NONEMPTY_MULTIROW_MAX_ROWS,
    NONEMPTY_MULTIROW_MIN_ROWS,
    nonempty_multirow_payload_length,
    nonempty_multirow_row_word,
    synthesize_nonempty_multirow,
)
from .model import Coil, Contact, InstructionType, RungGrid
from .topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    CellWireFlags,
    WireCellTopology,
    WireTopology,
    header_structural_equal,
    normalize_header_entry,
    normalized_header_entries,
    parse_wire_topology,
)

__all__ = [
    "ClickCodec",
    "EncodeResult",
    "HeaderSeed",
    "LadderRungV2",
    "Coil",
    "Contact",
    "CellWireFlags",
    "InstructionType",
    "RungGrid",
    "WireCellTopology",
    "WireTopology",
    "CELL_HORIZONTAL_LEFT_OFFSET",
    "CELL_HORIZONTAL_RIGHT_OFFSET",
    "CELL_VERTICAL_DOWN_OFFSET",
    "header_structural_equal",
    "normalize_header_entry",
    "normalized_header_entries",
    "V2Degradation",
    "V2EncodeReport",
    "V2UnsupportedShapeError",
    "clear_clipboard",
    "copy_to_clipboard",
    "EMPTY_MULTIROW_MIN_ROWS",
    "EMPTY_MULTIROW_MAX_ROWS",
    "empty_multirow_payload_length",
    "empty_multirow_row_word",
    "synthesize_empty_multirow",
    "NONEMPTY_MULTIROW_MIN_ROWS",
    "NONEMPTY_MULTIROW_MAX_ROWS",
    "nonempty_multirow_payload_length",
    "nonempty_multirow_row_word",
    "synthesize_nonempty_multirow",
    "parse_wire_topology",
    "read_from_clipboard",
]
