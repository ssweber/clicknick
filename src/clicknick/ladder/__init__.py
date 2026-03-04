"""Ladder module — encode/decode Click PLC clipboard rungs."""

from .clipboard import clear_clipboard, copy_to_clipboard, read_from_clipboard
from .codec import ClickCodec, HeaderSeed
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
    "HeaderSeed",
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
    "clear_clipboard",
    "copy_to_clipboard",
    "normalize_shorthand_row",
    "parse_wire_topology",
    "parse_bundle",
    "parse_csv_file",
    "parse_row",
    "read_from_clipboard",
    "to_runggrid_if_simple",
]
