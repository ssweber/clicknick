"""March 8 proven-family ladder codec v2.

This module is intentionally conservative. It encodes only the proven March 8
wireframe/comment families exactly, and supports a relaxed degradation mode for
unsupported condition/AF tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Literal

from .csv_ast import (
    AfBlank,
    AfCall,
    BlankCondition,
    ComparisonCondition,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
    HorizontalWire,
    JunctionDownWire,
    RungAst,
    RowAst,
    VerticalPassThroughWire,
)
from .csv_shorthand import normalize_shorthand_row
from .csv_token_parser import parse_af_token, parse_condition_token
from .topology import (
    CELL_HORIZONTAL_LEFT_OFFSET,
    CELL_HORIZONTAL_RIGHT_OFFSET,
    CELL_VERTICAL_DOWN_OFFSET,
    COLS_PER_ROW,
    cell_offset,
    parse_wire_topology,
)

EncodeMode = Literal["strict", "relaxed"]

PAYLOAD_LENGTH_OFFSET = 0x0294
PAYLOAD_BYTES_OFFSET = 0x0298
COMMENT_PREFIX_LEN = 105
COMMENT_SUFFIX_LEN = 11
PHASE_A_LEN = 0xFC8
MEDIUM_PHASE_B_TRIAD_PERIOD = 9
BLOCK_SIZE = 0x40
_MARCH8_RESOURCE_ROOT = "resources/march8"
_ROW_TOKEN_COUNT = COLS_PER_ROW - 1
_KNOWN_BAD_MEDIUM_LENGTH_MOD = 36

MEDIUM_TYPE_A_OFFSETS = {
    0x00: 0x10,
    0x02: 0x03,
    0x0C: 0x01,
    0x18: 0x10,
    0x1A: 0x03,
    0x24: 0x01,
    0x30: 0x10,
    0x32: 0x03,
    0x3C: 0x01,
}

MEDIUM_TYPE_B_OFFSETS = {
    0x08: 0x10,
    0x0A: 0x03,
    0x14: 0x01,
    0x20: 0x10,
    0x22: 0x03,
    0x2C: 0x01,
    0x38: 0x10,
    0x3A: 0x03,
}

MEDIUM_TYPE_C_OFFSETS = {
    0x04: 0x01,
    0x10: 0x10,
    0x12: 0x03,
    0x1C: 0x01,
    0x28: 0x10,
    0x2A: 0x03,
    0x34: 0x01,
}


@dataclass(frozen=True)
class V2Degradation:
    kind: Literal["condition", "af"]
    row: int
    column: int | None
    source_token: str
    replacement_token: str


@dataclass(frozen=True)
class V2EncodeReport:
    mode: EncodeMode
    family: str
    degraded: bool
    degradations: tuple[V2Degradation, ...]
    legacy_fallback_used: bool = False


@dataclass(frozen=True)
class LadderRungV2:
    logical_rows: int
    condition_rows: tuple[tuple[str, ...], ...]
    af_tokens: tuple[str, ...]
    comment_lines: tuple[str, ...] = ()
    degradations: tuple[V2Degradation, ...] = ()
    mode: EncodeMode = "strict"

    def comment_text(self) -> str:
        return "\n".join(self.comment_lines)


class V2UnsupportedShapeError(ValueError):
    def __init__(
        self,
        *,
        reason: str,
        detail: str,
        row: int | None = None,
        column: int | None = None,
        token: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.row = row
        self.column = column
        self.token = token
        location = []
        if row is not None:
            location.append(f"row={row}")
        if column is not None:
            location.append(f"column={column}")
        if token is not None:
            location.append(f"token={token!r}")
        prefix = f"{reason}: {detail}"
        if location:
            prefix = f"{prefix} ({', '.join(location)})"
        super().__init__(prefix)


@dataclass(frozen=True)
class _CommentDonor:
    payload: bytes
    payload_prefix: bytes
    payload_suffix: bytes


def _load_bytes(name: str) -> bytes:
    return resources.files("clicknick.ladder").joinpath(f"{_MARCH8_RESOURCE_ROOT}/{name}").read_bytes()


def _payload_end(data: bytes) -> int:
    return PAYLOAD_BYTES_OFFSET + int.from_bytes(
        data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET],
        "little",
    )


def _normalize_af_token(token: str) -> str:
    if token.strip().upper() == "NOP":
        return "NOP"
    return ""


def _blank_row() -> tuple[str, ...]:
    return ("",) * _ROW_TOKEN_COUNT


def _full_row() -> tuple[str, ...]:
    return ("-",) * _ROW_TOKEN_COUNT


def _load_comment_donors() -> dict[int, _CommentDonor]:
    donors: dict[int, _CommentDonor] = {}
    for filename in (
        "grcecr_short_native_20260308.bin",
        "grcecr_medium_native_20260308.bin",
        "grcecr_max1400_native_20260308.bin",
    ):
        payload = _load_bytes(filename)
        comment_payload = payload[PAYLOAD_BYTES_OFFSET:_payload_end(payload)]
        donors[len(comment_payload) - COMMENT_PREFIX_LEN - COMMENT_SUFFIX_LEN] = _CommentDonor(
            payload=payload,
            payload_prefix=comment_payload[:COMMENT_PREFIX_LEN],
            payload_suffix=comment_payload[-COMMENT_SUFFIX_LEN:],
        )
    return donors


def _derive_shared_comment_wrapper(donors: dict[int, _CommentDonor]) -> tuple[bytes, bytes]:
    values = list(donors.values())
    prefix = values[0].payload_prefix
    suffix = values[0].payload_suffix
    for donor in values[1:]:
        if donor.payload_prefix != prefix or donor.payload_suffix != suffix:
            raise ValueError("March 8 comment donors do not share a common payload wrapper")
    return prefix, suffix


def _derive_phase_a_stream(donors: dict[int, _CommentDonor]) -> bytes:
    chunks = [
        donor.payload[_payload_end(donor.payload) : _payload_end(donor.payload) + PHASE_A_LEN]
        for donor in donors.values()
    ]
    if len(set(chunks)) != 1:
        raise ValueError("March 8 comment donors do not share a universal phase-A stream")
    return chunks[0]


def _derive_medium_phase_b_program(medium_payload: bytes) -> dict[str, object]:
    start = _payload_end(medium_payload) + PHASE_A_LEN
    full_block_count = (0x2000 - start) // BLOCK_SIZE
    full_blocks = [
        medium_payload[start + idx * BLOCK_SIZE : start + (idx + 1) * BLOCK_SIZE]
        for idx in range(full_block_count)
    ]
    period = MEDIUM_PHASE_B_TRIAD_PERIOD * 3
    for idx in range(full_block_count - period):
        if full_blocks[idx] != full_blocks[idx + period]:
            raise ValueError("Medium phase-B program is not periodic")

    triads = []
    for triad_idx in range(MEDIUM_PHASE_B_TRIAD_PERIOD):
        a = full_blocks[triad_idx * 3 + 0]
        b = full_blocks[triad_idx * 3 + 1]
        triads.append(
            {
                "a1": a[0x14],
                "a2": a[0x2C],
                "b1": b[0x04],
                "b2": b[0x1C],
            }
        )
    return {
        "triad_period": MEDIUM_PHASE_B_TRIAD_PERIOD,
        "ring_r1": [triad["a1"] for triad in triads],
        "ring_r2": [triad["a2"] for triad in triads],
        "ring_r3": [triad["b1"] for triad in triads],
        "ring_r4": [triad["b2"] for triad in triads],
    }


_WIREFRAME_PAYLOADS = {
    "empty_1row": _load_bytes("grcecr_empty_native_20260308.bin"),
    "fullwire_1row": _load_bytes("grcecr_fullwire_native_20260308.bin"),
    "fullwire_nop_1row": _load_bytes("grcecr_fullwire_nop_native_20260308.bin"),
    "empty_2row": _load_bytes("grcecr_rows2_empty_native_20260308.bin"),
    "vert_horiz_2row": _load_bytes("grcecr_rows2_vert_horiz_native_20260308.bin"),
}
_COMMENT_DONORS = _load_comment_donors()
_COMMENT_PAYLOAD_PREFIX, _COMMENT_PAYLOAD_SUFFIX = _derive_shared_comment_wrapper(_COMMENT_DONORS)
_COMMENT_PHASE_A_STREAM = _derive_phase_a_stream(_COMMENT_DONORS)
_MEDIUM_PHASE_B_PROGRAM = _derive_medium_phase_b_program(_COMMENT_DONORS[256].payload)


def _canonical_row_ast(row: str) -> RowAst:
    canonical = normalize_shorthand_row(row)
    nodes = tuple(parse_condition_token(token) for token in canonical.conditions)
    af_node = parse_af_token(canonical.af)
    return RowAst(canonical=canonical, condition_nodes=nodes, af_node=af_node)


def _rung_from_rows(rows: list[str]) -> RungAst:
    row_asts = [_canonical_row_ast(row) for row in rows]
    comment_rows = [row for row in row_asts if row.canonical.is_comment]
    rung_rows = [row for row in row_asts if not row.canonical.is_comment]
    if not rung_rows:
        raise V2UnsupportedShapeError(reason="row_count", detail="At least one rung row is required")
    if any(row.canonical.marker == "R" for row in rung_rows[1:]):
        raise V2UnsupportedShapeError(
            reason="row_count",
            detail="Only a single rung is supported by the v2 compiler",
        )
    return RungAst(rows=tuple(rung_rows), comment_rows=tuple(comment_rows))


def _condition_token_for_node(
    node: object,
    *,
    row_idx: int,
    col_idx: int,
    source_token: str,
    mode: EncodeMode,
) -> tuple[str, V2Degradation | None]:
    if isinstance(node, BlankCondition):
        return ("", None)
    if isinstance(node, HorizontalWire):
        return ("-", None)
    if isinstance(node, JunctionDownWire):
        return ("T", None)
    if isinstance(node, VerticalPassThroughWire):
        return ("|", None)

    if isinstance(node, (ContactCondition, EdgeCondition, ComparisonCondition, GenericCondition)):
        if mode == "relaxed":
            return (
                "-",
                V2Degradation(
                    kind="condition",
                    row=row_idx,
                    column=col_idx,
                    source_token=source_token,
                    replacement_token="-",
                ),
            )
        raise V2UnsupportedShapeError(
            reason="unsupported_condition",
            detail="Condition token is outside the proven March 8 family",
            row=row_idx,
            column=col_idx,
            token=source_token,
        )

    raise V2UnsupportedShapeError(
        reason="unsupported_condition",
        detail=f"Unhandled condition node {type(node).__name__}",
        row=row_idx,
        column=col_idx,
        token=source_token,
    )


def _af_token_for_node(
    node: object,
    *,
    row_idx: int,
    source_token: str,
    mode: EncodeMode,
) -> tuple[str, V2Degradation | None]:
    if isinstance(node, AfBlank):
        return ("", None)
    if isinstance(node, AfCall) and node.args == () and node.name.upper() == "NOP":
        return ("NOP", None)

    if mode == "relaxed":
        return (
            "NOP",
            V2Degradation(
                kind="af",
                row=row_idx,
                column=None,
                source_token=source_token,
                replacement_token="NOP",
            ),
        )

    raise V2UnsupportedShapeError(
        reason="unsupported_af",
        detail="AF token is outside the proven March 8 family",
        row=row_idx,
        token=source_token,
    )


def compile_rung_v2(rung: RungAst, *, mode: EncodeMode = "strict") -> LadderRungV2:
    if mode not in {"strict", "relaxed"}:
        raise ValueError(f"Unsupported mode {mode!r}")

    degradations: list[V2Degradation] = []
    condition_rows: list[tuple[str, ...]] = []
    af_tokens: list[str] = []

    for row_idx, row in enumerate(rung.rows):
        if len(row.condition_nodes) != _ROW_TOKEN_COUNT:
            raise V2UnsupportedShapeError(
                reason="row_shape",
                detail="Unexpected condition column count",
                row=row_idx,
            )

        normalized_row: list[str] = []
        for col_idx, node in enumerate(row.condition_nodes):
            token, degradation = _condition_token_for_node(
                node,
                row_idx=row_idx,
                col_idx=col_idx,
                source_token=row.canonical.conditions[col_idx],
                mode=mode,
            )
            normalized_row.append(token)
            if degradation is not None:
                degradations.append(degradation)

        af_token, degradation = _af_token_for_node(
            row.af_node,
            row_idx=row_idx,
            source_token=row.canonical.af,
            mode=mode,
        )
        if degradation is not None:
            degradations.append(degradation)

        condition_rows.append(tuple(normalized_row))
        af_tokens.append(af_token)

    return LadderRungV2(
        logical_rows=len(rung.rows),
        condition_rows=tuple(condition_rows),
        af_tokens=tuple(af_tokens),
        comment_lines=tuple(row.canonical.comment_text or "" for row in rung.comment_rows),
        degradations=tuple(degradations),
        mode=mode,
    )


def compile_rows_v2(rows: list[str], *, mode: EncodeMode = "strict") -> LadderRungV2:
    return compile_rung_v2(_rung_from_rows(rows), mode=mode)


def _match_wireframe_family(rung: LadderRungV2) -> str | None:
    blank = _blank_row()
    full = _full_row()

    if rung.comment_lines:
        return None

    if rung.logical_rows == 1:
        row0 = rung.condition_rows[0]
        af0 = _normalize_af_token(rung.af_tokens[0])
        if row0 == blank and af0 == "":
            return "empty_1row"
        if row0 == full and af0 == "":
            return "fullwire_1row"
        if row0 == full and af0 == "NOP":
            return "fullwire_nop_1row"
        return None

    if rung.logical_rows == 2 and all(_normalize_af_token(token) == "" for token in rung.af_tokens):
        if rung.condition_rows == (blank, blank):
            return "empty_2row"
        row0 = list(blank)
        row1 = list(blank)
        row0[1] = "T"
        row1[1] = "-"
        if rung.condition_rows == (tuple(row0), tuple(row1)):
            return "vert_horiz_2row"

    return None


def _supported_comment_text(rung: LadderRungV2) -> str:
    if rung.logical_rows != 1:
        raise V2UnsupportedShapeError(
            reason="comment_rows",
            detail="March 8 plain comments are only proven on 1-row empty rungs",
        )
    if rung.condition_rows != (_blank_row(),):
        raise V2UnsupportedShapeError(
            reason="comment_topology",
            detail="March 8 plain comments require an empty visible topology",
        )
    if any(_normalize_af_token(token) != "" for token in rung.af_tokens):
        raise V2UnsupportedShapeError(
            reason="comment_af",
            detail="March 8 plain comments require blank AF cells",
        )
    if not rung.comment_lines:
        raise V2UnsupportedShapeError(reason="comment_rows", detail="Comment text is required")
    if len(rung.comment_lines) != 1:
        raise V2UnsupportedShapeError(
            reason="comment_rows",
            detail="Only single-line plain comments are proven in the March 8 family",
        )
    return rung.comment_lines[0]


def _build_plain_comment_payload(text: str) -> bytes:
    encoded_body = text.encode("cp1252")
    if len(encoded_body) > 1400:
        raise V2UnsupportedShapeError(
            reason="comment_length",
            detail="Plain comments longer than 1400 characters are unsupported",
            token=text,
        )
    return _COMMENT_PAYLOAD_PREFIX + encoded_body + _COMMENT_PAYLOAD_SUFFIX


def _is_known_bad_medium_comment_length(body_len: int) -> bool:
    return 5 < body_len < 1400 and body_len % BLOCK_SIZE == _KNOWN_BAD_MEDIUM_LENGTH_MOD


def _apply_payload_and_phase_a(base: bytes, payload: bytes) -> bytearray:
    out = bytearray(base)
    out[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET] = len(payload).to_bytes(4, "little")
    payload_end = PAYLOAD_BYTES_OFFSET + len(payload)
    out[PAYLOAD_BYTES_OFFSET:payload_end] = payload
    out[payload_end : payload_end + len(_COMMENT_PHASE_A_STREAM)] = _COMMENT_PHASE_A_STREAM
    return out


def _apply_medium_phase_b(out: bytearray, start: int) -> None:
    triad_period = _MEDIUM_PHASE_B_PROGRAM["triad_period"]
    ring_r1 = _MEDIUM_PHASE_B_PROGRAM["ring_r1"]
    ring_r2 = _MEDIUM_PHASE_B_PROGRAM["ring_r2"]
    ring_r3 = _MEDIUM_PHASE_B_PROGRAM["ring_r3"]
    ring_r4 = _MEDIUM_PHASE_B_PROGRAM["ring_r4"]

    full_block_count = (0x2000 - start) // BLOCK_SIZE
    for idx in range(full_block_count):
        triad_idx = (idx // 3) % triad_period
        block_type = idx % 3
        shifted = (triad_idx + 5) % triad_period
        block = bytearray(BLOCK_SIZE)
        if block_type == 0:
            for off, value in MEDIUM_TYPE_A_OFFSETS.items():
                block[off] = value
            block[0x14] = ring_r1[triad_idx]
            block[0x2C] = ring_r2[triad_idx]
        elif block_type == 1:
            for off, value in MEDIUM_TYPE_B_OFFSETS.items():
                block[off] = value
            block[0x04] = ring_r3[triad_idx]
            block[0x1C] = ring_r4[triad_idx]
            block[0x34] = ring_r1[shifted]
        else:
            for off, value in MEDIUM_TYPE_C_OFFSETS.items():
                block[off] = value
            block[0x0C] = ring_r2[shifted]
            block[0x24] = ring_r3[shifted]
            block[0x3C] = ring_r4[shifted]
        off = start + idx * BLOCK_SIZE
        out[off : off + BLOCK_SIZE] = block

    tail_len = (0x2000 - start) % BLOCK_SIZE
    if tail_len:
        tail_off = start + full_block_count * BLOCK_SIZE
        triad_idx = (full_block_count // 3) % triad_period
        block = bytearray(BLOCK_SIZE)
        for off, value in MEDIUM_TYPE_A_OFFSETS.items():
            block[off] = value
        block[0x14] = ring_r1[triad_idx]
        block[0x2C] = ring_r2[triad_idx]
        out[tail_off:0x2000] = block[:tail_len]


def _encode_plain_comment_payload(text: str, *, mode: EncodeMode = "strict") -> tuple[bytes, str]:
    if text == "":
        return (_WIREFRAME_PAYLOADS["empty_1row"], "plain_comment_len_0")

    encoded_body = text.encode("cp1252")
    if _is_known_bad_medium_comment_length(len(encoded_body)):
        raise V2UnsupportedShapeError(
            reason="comment_alignment",
            detail=(
                "Plain-comment medium family lengths congruent to 36 mod 64 are currently "
                "unsupported due to a verified default-rung insertion bug"
            ),
            token=text,
        )
    canonical_length = len(encoded_body) in {5, 256, 1400}
    payload = _build_plain_comment_payload(text)
    out = _apply_payload_and_phase_a(_WIREFRAME_PAYLOADS["empty_1row"], payload)

    if len(encoded_body) >= 1400:
        out[0x1260:0x2000] = _WIREFRAME_PAYLOADS["fullwire_1row"][0x1260:0x2000]
        family = "plain_comment_len_1400" if len(encoded_body) == 1400 else "plain_comment_max_family"
    elif len(encoded_body) > 5:
        _apply_medium_phase_b(out, PAYLOAD_BYTES_OFFSET + len(payload) + PHASE_A_LEN)
        family = (
            "plain_comment_len_256"
            if len(encoded_body) == 256
            else f"plain_comment_medium_family_len_{len(encoded_body)}"
        )
    else:
        family = (
            "plain_comment_len_5"
            if len(encoded_body) == 5
            else f"plain_comment_short_family_len_{len(encoded_body)}"
        )

    if not canonical_length:
        _clear_visible_wire_flags(out, rows=2)

    return (bytes(out), family)


def _decode_comment_text(data: bytes) -> tuple[str, ...]:
    if len(data) <= PAYLOAD_BYTES_OFFSET:
        return ()
    payload_len = int.from_bytes(data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], "little")
    if payload_len == 0:
        return ()
    payload = data[PAYLOAD_BYTES_OFFSET : PAYLOAD_BYTES_OFFSET + payload_len]
    if len(payload) < COMMENT_PREFIX_LEN + COMMENT_SUFFIX_LEN:
        return ()
    body_len = len(payload) - COMMENT_PREFIX_LEN - COMMENT_SUFFIX_LEN
    if body_len < 0 or body_len > 1400:
        return ()
    if not (
        payload.startswith(_COMMENT_PAYLOAD_PREFIX)
        and payload.endswith(_COMMENT_PAYLOAD_SUFFIX)
    ):
        return ()
    try:
        return (payload[COMMENT_PREFIX_LEN:-COMMENT_SUFFIX_LEN].decode("cp1252"),)
    except UnicodeDecodeError:
        return ()


def _token_from_flags(left: bool, right: bool, down: bool) -> str:
    if down and left and right:
        return "T"
    if down:
        return "|"
    if left or right:
        return "-"
    return ""


def _clear_visible_wire_flags(payload: bytearray, *, rows: int = 2) -> None:
    for row_idx in range(rows):
        for col_idx in range(COLS_PER_ROW):
            start = cell_offset(row_idx, col_idx)
            payload[start + CELL_HORIZONTAL_LEFT_OFFSET] = 0
            payload[start + CELL_HORIZONTAL_RIGHT_OFFSET] = 0
            payload[start + CELL_VERTICAL_DOWN_OFFSET] = 0


def _af_token_for_decoded_row(row_tokens: tuple[str, ...], row_idx: int, topology: object) -> str:
    flags = topology.flags_at(row_idx, COLS_PER_ROW - 1)
    if flags and flags.horizontal_left and flags.horizontal_right:
        return "NOP"
    return ""


class March8V2Engine:
    def compile_rows(self, rows: list[str], *, mode: EncodeMode = "strict") -> LadderRungV2:
        return compile_rows_v2(rows, mode=mode)

    def encode_compiled(self, rung: LadderRungV2) -> tuple[bytes, V2EncodeReport]:
        family = _match_wireframe_family(rung)
        if family is not None:
            return (
                _WIREFRAME_PAYLOADS[family],
                V2EncodeReport(
                    mode=rung.mode,
                    family=family,
                    degraded=bool(rung.degradations),
                    degradations=rung.degradations,
                ),
            )

        text = _supported_comment_text(rung)
        payload, family = _encode_plain_comment_payload(text, mode=rung.mode)
        return (
            payload,
            V2EncodeReport(
                mode=rung.mode,
                family=family,
                degraded=bool(rung.degradations),
                degradations=rung.degradations,
            ),
        )

    def encode_rows(self, rows: list[str], *, mode: EncodeMode = "strict") -> tuple[bytes, V2EncodeReport]:
        compiled = self.compile_rows(rows, mode=mode)
        return self.encode_compiled(compiled)

    def supports_payload(self, data: bytes) -> bool:
        if data in _WIREFRAME_PAYLOADS.values():
            return True

        payload_len = int.from_bytes(data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], "little")
        if payload_len == 0:
            return False
        body_lines = _decode_comment_text(data)
        if len(body_lines) != 1:
            return False
        body = body_lines[0]
        try:
            rebuilt, _ = _encode_plain_comment_payload(body)
        except V2UnsupportedShapeError:
            return False
        return rebuilt == data

    def decode(self, data: bytes) -> LadderRungV2:
        topology = parse_wire_topology(data)
        condition_rows: list[tuple[str, ...]] = []
        for row_idx in range(topology.row_count):
            row_tokens = []
            for col_idx in range(_ROW_TOKEN_COUNT):
                flags = topology.flags_at(row_idx, col_idx)
                row_tokens.append(
                    _token_from_flags(
                        bool(flags and flags.horizontal_left),
                        bool(flags and flags.horizontal_right),
                        bool(flags and flags.vertical_down),
                    )
                )
            condition_rows.append(tuple(row_tokens))

        af_tokens = tuple(
            _af_token_for_decoded_row(condition_rows[row_idx], row_idx, topology)
            for row_idx in range(topology.row_count)
        )
        return LadderRungV2(
            logical_rows=topology.row_count,
            condition_rows=tuple(condition_rows),
            af_tokens=af_tokens,
            comment_lines=_decode_comment_text(data),
            mode="strict",
        )
