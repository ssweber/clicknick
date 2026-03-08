"""Public ladder codec surface.

`ClickCodec` now fronts two paths:
- v2 March 8 proven-family encoding for row/topology/comment driven workflows
- legacy `RungGrid` compatibility encoding/decoding for the older instruction path
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from . import legacy_codec as _legacy_codec
from .codec_v2 import (
    EncodeMode,
    LadderRungV2,
    March8V2Engine,
    V2EncodeReport,
    V2UnsupportedShapeError,
)
from .csv_ast import RungAst
from .csv_shorthand import normalize_shorthand_row, render_shorthand_row
from .model import RungGrid
from .topology import WireTopology, parse_wire_topology

BUFFER_SIZE = _legacy_codec.BUFFER_SIZE
CELL_SIZE = _legacy_codec.CELL_SIZE
COLS_PER_ROW = _legacy_codec.COLS_PER_ROW
ROW_STARTS = _legacy_codec.ROW_STARTS
GRID_START = _legacy_codec.GRID_START
GRID_END = _legacy_codec.GRID_END
ROW_CLASS_BY_COUNT = _legacy_codec.ROW_CLASS_BY_COUNT
HeaderSeed = _legacy_codec.HeaderSeed
_load_scaffold = _legacy_codec._load_scaffold


@dataclass(frozen=True)
class EncodeResult:
    payload: bytes
    report: V2EncodeReport | None = None


class ClickCodec:
    """Front-door codec for v2 row compilation and legacy `RungGrid` compatibility."""

    def __init__(self) -> None:
        self._legacy = _legacy_codec.ClickCodec()
        self._v2 = March8V2Engine()
        self._last_encode_report: V2EncodeReport | None = None

    @property
    def last_encode_report(self) -> V2EncodeReport | None:
        return self._last_encode_report

    def compile_rows(self, rows: list[str], *, mode: EncodeMode = "strict") -> LadderRungV2:
        return self._v2.compile_rows(rows, mode=mode)

    def encode_rows(
        self,
        rows: list[str],
        *,
        mode: EncodeMode = "strict",
        legacy_fallback: bool = False,
        header_seed: HeaderSeed | None = None,
        return_metadata: bool = False,
    ) -> bytes | EncodeResult:
        try:
            payload, report = self._v2.encode_rows(rows, mode=mode)
            self._last_encode_report = report
            result = EncodeResult(payload=payload, report=report)
            return result if return_metadata else result.payload
        except V2UnsupportedShapeError:
            if not legacy_fallback:
                raise
            if mode != "strict":
                raise
            rung = self._rows_to_simple_rung(rows)
            payload = self._legacy.encode(rung, header_seed=header_seed)
            self._last_encode_report = V2EncodeReport(
                mode=mode,
                family="legacy_runggrid_fallback",
                degraded=False,
                degradations=tuple(),
                legacy_fallback_used=True,
            )
            result = EncodeResult(payload=payload, report=self._last_encode_report)
            return result if return_metadata else result.payload

    def encode_v2(
        self,
        rung: LadderRungV2,
        *,
        return_metadata: bool = False,
    ) -> bytes | EncodeResult:
        payload, report = self._v2.encode_compiled(rung)
        self._last_encode_report = report
        result = EncodeResult(payload=payload, report=report)
        return result if return_metadata else result.payload

    def encode(
        self,
        value: RungGrid | LadderRungV2 | RungAst | Sequence[str],
        *,
        header_seed: HeaderSeed | None = None,
        mode: EncodeMode = "strict",
        legacy_fallback: bool = False,
        return_metadata: bool = False,
    ) -> bytes | EncodeResult:
        if isinstance(value, RungGrid):
            payload = self._legacy.encode(value, header_seed=header_seed)
            self._last_encode_report = V2EncodeReport(
                mode=mode,
                family="legacy_runggrid_direct",
                degraded=False,
                degradations=tuple(),
                legacy_fallback_used=True,
            )
            result = EncodeResult(payload=payload, report=self._last_encode_report)
            return result if return_metadata else result.payload

        if isinstance(value, LadderRungV2):
            return self.encode_v2(value, return_metadata=return_metadata)

        if isinstance(value, RungAst):
            rows = [
                *[render_shorthand_row(row.canonical) for row in value.comment_rows],
                *[render_shorthand_row(row.canonical) for row in value.rows],
            ]
            return self.encode_rows(
                rows,
                mode=mode,
                legacy_fallback=legacy_fallback,
                header_seed=header_seed,
                return_metadata=return_metadata,
            )

        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
            return self.encode_rows(
                list(value),
                mode=mode,
                legacy_fallback=legacy_fallback,
                header_seed=header_seed,
                return_metadata=return_metadata,
            )

        raise TypeError(f"Unsupported encode input type: {type(value).__name__}")

    def decode(self, data: bytes) -> RungGrid | LadderRungV2:
        try:
            return self._legacy.decode(data)
        except Exception:
            if not self._v2.supports_payload(data):
                raise
            return self._v2.decode(data)

    def decode_v2(self, data: bytes) -> LadderRungV2:
        return self._v2.decode(data)

    def decode_wire_topology(self, data: bytes) -> WireTopology:
        return parse_wire_topology(data)

    def _rows_to_simple_rung(self, rows: list[str]) -> RungGrid:
        canonical_rows = [normalize_shorthand_row(row) for row in rows]
        if any(row.is_comment for row in canonical_rows):
            raise V2UnsupportedShapeError(
                reason="comment_rows",
                detail="Rung comments are unsupported by the legacy fallback path",
            )
        if len(canonical_rows) != 1:
            raise V2UnsupportedShapeError(
                reason="row_count",
                detail="Legacy fallback only supports exactly one row",
            )

        canonical = canonical_rows[0]
        if not canonical.af:
            raise V2UnsupportedShapeError(
                reason="af_blank",
                detail="Legacy fallback requires a non-empty AF instruction",
            )

        contacts = [
            token
            for token in canonical.conditions
            if token and token not in {"-", "|", "T"}
        ]
        if not contacts:
            raise V2UnsupportedShapeError(
                reason="no_contacts",
                detail="Legacy fallback requires at least one contact condition",
            )
        csv = f"{','.join(contacts)},->,:,{canonical.af}"
        try:
            return RungGrid.from_csv(csv)
        except ValueError as exc:
            raise V2UnsupportedShapeError(
                reason="legacy_parse",
                detail=str(exc),
            ) from exc
