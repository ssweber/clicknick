"""Compatibility adapter from contract AST rungs to legacy RungGrid."""

from __future__ import annotations

from dataclasses import dataclass

from .csv_ast import (
    AfCall,
    BlankCondition,
    ComparisonCondition,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
    HorizontalWire,
    JunctionDownWire,
    RungAst,
    VerticalPassThroughWire,
)
from .model import Coil, Contact, InstructionType, RungGrid


@dataclass
class UnsupportedComplexRungError(ValueError):
    reason: str
    detail: str

    def __str__(self) -> str:
        return f"{self.reason}: {self.detail}"


def _to_model_contact(contact: ContactCondition | EdgeCondition) -> Contact:
    if isinstance(contact, EdgeCondition):
        return Contact(
            type=InstructionType.CONTACT_EDGE,
            operand=contact.operand,
            immediate=False,
            edge_kind=contact.kind,
        )
    return Contact(
        type=InstructionType.CONTACT_NC if contact.negated else InstructionType.CONTACT_NO,
        operand=contact.operand,
        immediate=contact.immediate,
    )


def _unsupported(reason: str, detail: str) -> UnsupportedComplexRungError:
    return UnsupportedComplexRungError(reason=reason, detail=detail)


def to_runggrid_if_simple(rung: RungAst) -> RungGrid:
    if len(rung.rows) != 1:
        raise _unsupported("row_count", "Only single-row rungs are supported by RungGrid adapter")

    row = rung.rows[0]
    af_node = row.af_node
    if not isinstance(af_node, AfCall):
        raise _unsupported("af_blank", "AF must contain an out/latch/reset call")
    if af_node.name not in {"out", "latch", "reset"}:
        raise _unsupported("af_not_coil", f"Unsupported AF token name {af_node.name!r}")

    try:
        coil = Coil.from_csv_token(row.canonical.af)
    except ValueError as exc:
        raise _unsupported("af_parse", f"Could not parse AF coil token: {exc}") from exc

    disallowed_condition_types = (
        JunctionDownWire,
        VerticalPassThroughWire,
        ComparisonCondition,
        GenericCondition,
    )
    for idx, node in enumerate(row.condition_nodes):
        if isinstance(node, disallowed_condition_types):
            raise _unsupported(
                "complex_condition",
                f"Condition column index {idx} uses unsupported node {type(node).__name__}",
            )

    contact_positions = [
        idx
        for idx, node in enumerate(row.condition_nodes)
        if isinstance(node, (ContactCondition, EdgeCondition))
    ]
    if not contact_positions:
        raise _unsupported("no_contacts", "At least one contact is required")
    if len(contact_positions) > 2:
        raise _unsupported("too_many_contacts", "Only up to two series contacts are supported")

    first_contact_idx = contact_positions[0]
    if any(isinstance(node, HorizontalWire) for node in row.condition_nodes[:first_contact_idx]):
        raise _unsupported("leading_wire", "Wire before first contact is unsupported")

    if len(contact_positions) == 2:
        left, right = contact_positions
        if right <= left + 1:
            raise _unsupported("not_series", "Two contacts must have wire cells between them")
        between = row.condition_nodes[left + 1 : right]
        if any(not isinstance(node, HorizontalWire) for node in between):
            raise _unsupported("not_series", "Cells between two contacts must be wire '-' cells")

    contacts = [
        _to_model_contact(node)
        for node in row.condition_nodes
        if isinstance(node, (ContactCondition, EdgeCondition))
    ]

    trailing_nodes = row.condition_nodes[contact_positions[-1] + 1 :]
    if any(not isinstance(node, (BlankCondition, HorizontalWire)) for node in trailing_nodes):
        raise _unsupported("complex_tail", "Trailing condition cells must be blank or wire")

    return RungGrid(contact=contacts[0], series_contacts=contacts[1:], coil=coil)
