from __future__ import annotations

from pathlib import Path

import pytest

from clicknick.ladder.codec import ClickCodec, EncodeResult
from clicknick.ladder.codec_v2 import LadderRungV2, V2UnsupportedShapeError


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ladder_captures"


def _fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _medium_comment() -> str:
    return "MEDIUM256_" + ("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 6) + "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"


def _max_comment() -> str:
    return "MAX1396_" + ("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 38) + "ABCDEFGHIJKLMNOPQRST1234"


@pytest.mark.parametrize(
    ("rows", "fixture_name"),
    [
        (["R,...,:,..."], "grcecr_empty_native_20260308.bin"),
        (["R,->,:,..."], "grcecr_fullwire_native_20260308.bin"),
        (["R,->,:,NOP"], "grcecr_fullwire_nop_native_20260308.bin"),
        (["R,...,:,...", ",...,:,..."], "grcecr_rows2_empty_native_20260308.bin"),
        (["R,,T,...,:,...", ",,-,...,:,..."], "grcecr_rows2_vert_horiz_native_20260308.bin"),
    ],
)
def test_v2_encode_rows_matches_march8_wireframe_fixtures(rows: list[str], fixture_name: str) -> None:
    codec = ClickCodec()
    payload = codec.encode_rows(rows, mode="strict")
    assert payload == _fixture(fixture_name)


@pytest.mark.parametrize(
    ("comment_text", "fixture_name"),
    [
        ("Hello", "grcecr_short_native_20260308.bin"),
        (_medium_comment(), "grcecr_medium_native_20260308.bin"),
        (_max_comment(), "grcecr_max1400_native_20260308.bin"),
    ],
)
def test_v2_encode_rows_matches_march8_plain_comment_fixtures(
    comment_text: str,
    fixture_name: str,
) -> None:
    codec = ClickCodec()
    payload = codec.encode_rows([f"#,{comment_text}", "R,...,:,..."], mode="strict")
    assert payload == _fixture(fixture_name)


def test_v2_strict_rejects_unsupported_contact_without_legacy_fallback() -> None:
    codec = ClickCodec()
    with pytest.raises(V2UnsupportedShapeError, match="unsupported_condition"):
        codec.encode_rows(["R,X001,->,:,out(Y001)"], mode="strict")


def test_v2_relaxed_degrades_unsupported_contact_and_af_to_fullwire_nop() -> None:
    codec = ClickCodec()
    result = codec.encode_rows(
        ["R,X001,->,:,out(Y001)"],
        mode="relaxed",
        return_metadata=True,
    )
    assert isinstance(result, EncodeResult)
    assert result.payload == _fixture("grcecr_fullwire_nop_native_20260308.bin")
    assert result.report is not None
    assert result.report.degraded is True
    assert [issue.kind for issue in result.report.degradations] == ["condition", "af"]
    assert result.report.degradations[0].column == 0
    assert result.report.degradations[0].replacement_token == "-"
    assert result.report.degradations[1].replacement_token == "NOP"


def test_strict_legacy_fallback_keeps_old_simple_instruction_path() -> None:
    codec = ClickCodec()
    result = codec.encode_rows(
        ["R,X001,->,:,out(Y001)"],
        mode="strict",
        legacy_fallback=True,
        return_metadata=True,
    )
    assert isinstance(result, EncodeResult)
    assert result.report is not None
    assert result.report.legacy_fallback_used is True
    decoded = codec.decode(result.payload)
    assert decoded.to_csv() == "X001,->,:,out(Y001)"


def test_decode_v2_recovers_plain_comment_and_visible_topology() -> None:
    codec = ClickCodec()
    decoded = codec.decode_v2(_fixture("grcecr_medium_native_20260308.bin"))
    assert isinstance(decoded, LadderRungV2)
    assert decoded.comment_lines == (_medium_comment(),)
    assert decoded.logical_rows == 1
    assert decoded.condition_rows == (("",) * 31,)
    assert decoded.af_tokens == ("",)


@pytest.mark.parametrize("length", [1, 2, 4, 6, 10, 99, 101, 512, 1024, 1399, 1400])
def test_v2_encode_rows_supports_arbitrary_plain_comment_lengths_up_to_1400(length: int) -> None:
    codec = ClickCodec()
    comment = ("A" * length)
    result = codec.encode_rows(
        [f"#,{comment}", "R,...,:,..."],
        mode="strict",
        return_metadata=True,
    )
    assert isinstance(result, EncodeResult)
    assert len(result.payload) == 8192
    assert result.report is not None
    assert result.report.family.startswith("plain_comment_")

    decoded = codec.decode_v2(result.payload)
    assert decoded.comment_lines == (comment,)
    assert decoded.condition_rows == (("",) * 31,)
    assert decoded.af_tokens == ("",)


@pytest.mark.parametrize("length", [36, 100, 164, 228])
def test_v2_encode_rows_rejects_known_bad_medium_alignment_family(length: int) -> None:
    codec = ClickCodec()
    with pytest.raises(V2UnsupportedShapeError, match="comment_alignment"):
        codec.encode_rows([f"#,{'A' * length}", "R,...,:,..."], mode="strict")


def test_v2_encode_rows_rejects_plain_comment_length_above_1400() -> None:
    codec = ClickCodec()
    with pytest.raises(V2UnsupportedShapeError, match="longer than 1400"):
        codec.encode_rows([f"#,{'A' * 1401}", "R,...,:,..."], mode="strict")
