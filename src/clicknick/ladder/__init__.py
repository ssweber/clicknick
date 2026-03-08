"""Ladder module — encode/decode Click PLC clipboard rungs."""

from .clipboard import clear_clipboard, copy_to_clipboard, read_from_clipboard
from .codec import ClickCodec, EncodeResult, HeaderSeed
from .codec_v2 import LadderRungV2, V2Degradation, V2EncodeReport, V2UnsupportedShapeError
from .csv_adapter import UnsupportedComplexRungError, to_runggrid_if_simple
from .csv_ast import (
    AfBlank,
    AfCall,
    CanonicalRow,
    ParsedCsvFileAst,
    ProgramBundleAst,
    RowAst,
    RungAst,
)
from .csv_bundle import parse_bundle
from .csv_parser import parse_csv_file, parse_row
from .csv_shorthand import normalize_shorthand_row
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
    "AfBlank",
    "AfCall",
    "CanonicalRow",
    "ParsedCsvFileAst",
    "ProgramBundleAst",
    "RowAst",
    "RungAst",
    "CELL_HORIZONTAL_LEFT_OFFSET",
    "CELL_HORIZONTAL_RIGHT_OFFSET",
    "CELL_VERTICAL_DOWN_OFFSET",
    "header_structural_equal",
    "normalize_header_entry",
    "normalized_header_entries",
    "UnsupportedComplexRungError",
    "V2Degradation",
    "V2EncodeReport",
    "V2UnsupportedShapeError",
    "clear_clipboard",
    "copy_to_clipboard",
    "normalize_shorthand_row",
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
    "parse_bundle",
    "parse_csv_file",
    "parse_row",
    "read_from_clipboard",
    "to_runggrid_if_simple",
]
