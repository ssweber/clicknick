"""Scoped ladder codec compatibility surface.

This module restores the public `clicknick.ladder.codec` API after the
instruction-heavy codecs were removed. The supported shorthand encode path is
the slimmed encoder in `encode.py`; direct `RungGrid` encode/decode and header
seed extraction continue to use `legacy_codec.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ..csv.shorthand import normalize_shorthand_row
from . import legacy_codec as _legacy_codec
from .encode import encode_rung
from .model import RungGrid
from .topology import WireTopology, parse_wire_topology

EncodeMode = Literal["strict", "relaxed"]

BUFFER_SIZE = _legacy_codec.BUFFER_SIZE
CELL_SIZE = _legacy_codec.CELL_SIZE
COLS_PER_ROW = _legacy_codec.COLS_PER_ROW
ROW_STARTS = _legacy_codec.ROW_STARTS
GRID_START = _legacy_codec.GRID_START
GRID_END = _legacy_codec.GRID_END
ROW_CLASS_BY_COUNT = _legacy_codec.ROW_CLASS_BY_COUNT
HeaderSeed = _legacy_codec.HeaderSeed
_load_scaffold = _legacy_codec._load_scaffold

_SUPPORTED_CONDITION_TOKENS = {"", "-", "|", "T"}


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
        location: list[str] = []
        if row is not None:
            location.append(f"row={row}")
        if column is not None:
            location.append(f"column={column}")
        if token is not None:
            location.append(f"token={token!r}")
        message = f"{reason}: {detail}"
        if location:
            message = f"{message} ({', '.join(location)})"
        super().__init__(message)


@dataclass(frozen=True)
class EncodeResult:
    payload: bytes
    report: V2EncodeReport | None = None


def _normalize_af_token(
    token: str, *, row_idx: int, mode: EncodeMode
) -> tuple[str, V2Degradation | None]:
    stripped = token.strip()
    normalized = stripped.upper()
    if normalized == "":
        return "", None
    if normalized == "NOP":
        return "NOP", None
    if mode == "relaxed":
        return (
            "NOP",
            V2Degradation(
                kind="af",
                row=row_idx,
                column=None,
                source_token=token,
                replacement_token="NOP",
            ),
        )
    raise V2UnsupportedShapeError(
        reason="unsupported_af",
        detail="AF token is outside the scoped encoder surface",
        row=row_idx,
        token=token,
    )


def _normalize_condition_token(
    token: str,
    *,
    row_idx: int,
    col_idx: int,
    mode: EncodeMode,
) -> tuple[str, V2Degradation | None]:
    if token in _SUPPORTED_CONDITION_TOKENS:
        return token, None
    if mode == "relaxed":
        return (
            "-",
            V2Degradation(
                kind="condition",
                row=row_idx,
                column=col_idx,
                source_token=token,
                replacement_token="-",
            ),
        )
    raise V2UnsupportedShapeError(
        reason="unsupported_condition",
        detail="Condition token is outside the scoped encoder surface",
        row=row_idx,
        column=col_idx,
        token=token,
    )


def _compile_rows(rows: list[str], *, mode: EncodeMode = "strict") -> LadderRungV2:
    if mode not in {"strict", "relaxed"}:
        raise ValueError(f"Unsupported mode {mode!r}")

    comment_lines: list[str] = []
    condition_rows: list[tuple[str, ...]] = []
    af_tokens: list[str] = []
    degradations: list[V2Degradation] = []
    seen_rung = False

    for row in rows:
        canonical = normalize_shorthand_row(row)
        if canonical.is_comment:
            if seen_rung:
                raise V2UnsupportedShapeError(
                    reason="comment_rows",
                    detail="Comment rows must appear before the first rung row",
                )
            comment_lines.append(canonical.comment_text or "")
            continue

        seen_rung = True
        row_idx = len(condition_rows)
        if canonical.marker == "R" and row_idx > 0:
            raise V2UnsupportedShapeError(
                reason="row_count",
                detail="Only the first rung row may use marker 'R'",
                row=row_idx,
            )

        normalized_row: list[str] = []
        for col_idx, token in enumerate(canonical.conditions):
            normalized, degradation = _normalize_condition_token(
                token,
                row_idx=row_idx,
                col_idx=col_idx,
                mode=mode,
            )
            normalized_row.append(normalized)
            if degradation is not None:
                degradations.append(degradation)

        af_token, degradation = _normalize_af_token(canonical.af, row_idx=row_idx, mode=mode)
        if degradation is not None:
            degradations.append(degradation)

        condition_rows.append(tuple(normalized_row))
        af_tokens.append(af_token)

    if not condition_rows:
        raise V2UnsupportedShapeError(
            reason="row_count",
            detail="At least one rung row is required",
        )

    return LadderRungV2(
        logical_rows=len(condition_rows),
        condition_rows=tuple(condition_rows),
        af_tokens=tuple(af_tokens),
        comment_lines=tuple(comment_lines),
        degradations=tuple(degradations),
        mode=mode,
    )


def _family_name(rung: LadderRungV2) -> str:
    if rung.comment_lines:
        comment_bytes = len(rung.comment_lines[0].encode("cp1252"))
        return f"plain_comment_len_{comment_bytes}"
    if any(token == "NOP" for token in rung.af_tokens):
        return "wire_topology_nop"
    return "wire_topology"


def _encode_compiled(
    rung: LadderRungV2,
    *,
    header_seed: HeaderSeed | None = None,
) -> tuple[bytes, V2EncodeReport]:
    if len(rung.comment_lines) > 1:
        raise V2UnsupportedShapeError(
            reason="comment_rows",
            detail="Only single-line comments are supported by the scoped encoder",
        )

    comment = rung.comment_lines[0] if rung.comment_lines else None
    try:
        payload = encode_rung(
            logical_rows=rung.logical_rows,
            condition_rows=rung.condition_rows,
            af_tokens=rung.af_tokens,
            comment=comment,
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise V2UnsupportedShapeError(
            reason="unsupported_shape",
            detail=str(exc),
        ) from exc

    has_comment = comment is not None and comment != ""
    if header_seed is not None and not has_comment:
        out = bytearray(payload)
        header_seed.apply_to_buffer(out)
        payload = bytes(out)

    report = V2EncodeReport(
        mode=rung.mode,
        family=_family_name(rung),
        degraded=bool(rung.degradations),
        degradations=rung.degradations,
    )
    return payload, report


class ClickCodec:
    """Compatibility codec over the scoped encoder plus legacy model helpers."""

    def __init__(self) -> None:
        self._legacy = _legacy_codec.ClickCodec()
        self._last_encode_report: V2EncodeReport | None = None

    @property
    def last_encode_report(self) -> V2EncodeReport | None:
        return self._last_encode_report

    def compile_rows(self, rows: list[str], *, mode: EncodeMode = "strict") -> LadderRungV2:
        return _compile_rows(rows, mode=mode)

    def encode_rows(
        self,
        rows: list[str],
        *,
        mode: EncodeMode = "strict",
        header_seed: HeaderSeed | None = None,
        return_metadata: bool = False,
        legacy_fallback: bool | None = None,
    ) -> bytes | EncodeResult:
        _ = legacy_fallback
        payload, report = _encode_compiled(
            self.compile_rows(rows, mode=mode),
            header_seed=header_seed,
        )
        self._last_encode_report = report
        result = EncodeResult(payload=payload, report=report)
        return result if return_metadata else result.payload

    def encode_v2(
        self,
        rung: LadderRungV2,
        *,
        header_seed: HeaderSeed | None = None,
        return_metadata: bool = False,
    ) -> bytes | EncodeResult:
        payload, report = _encode_compiled(rung, header_seed=header_seed)
        self._last_encode_report = report
        result = EncodeResult(payload=payload, report=report)
        return result if return_metadata else result.payload

    def encode(
        self,
        value: RungGrid | LadderRungV2 | Sequence[str],
        *,
        header_seed: HeaderSeed | None = None,
        mode: EncodeMode = "strict",
        return_metadata: bool = False,
        legacy_fallback: bool | None = None,
    ) -> bytes | EncodeResult:
        _ = legacy_fallback
        if isinstance(value, RungGrid):
            payload = self._legacy.encode(value, header_seed=header_seed)
            report = V2EncodeReport(
                mode=mode,
                family="legacy_runggrid_direct",
                degraded=False,
                degradations=tuple(),
            )
            self._last_encode_report = report
            result = EncodeResult(payload=payload, report=report)
            return result if return_metadata else result.payload

        if isinstance(value, LadderRungV2):
            return self.encode_v2(
                value,
                header_seed=header_seed,
                return_metadata=return_metadata,
            )

        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return self.encode_rows(
                list(value),
                mode=mode,
                header_seed=header_seed,
                return_metadata=return_metadata,
            )

        raise TypeError(f"Unsupported encode input type: {type(value).__name__}")

    def decode(self, data: bytes) -> RungGrid:
        return self._legacy.decode(data)

    def decode_wire_topology(self, data: bytes) -> WireTopology:
        return parse_wire_topology(data)
