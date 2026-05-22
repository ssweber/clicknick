"""Tests for AnnotationService: decompose, recompose, validate."""

from __future__ import annotations

import pytest
from pyrung.click.tag_map import TagMeta

from clicknick.services.annotation_service import AnnotationService


class TestDecomposeComment:
    def test_empty_comment(self) -> None:
        block, meta, text = AnnotationService.decompose_comment("")
        assert block is None
        assert meta is None
        assert text == ""

    def test_plain_text_only(self) -> None:
        block, meta, text = AnnotationService.decompose_comment("Plain comment")
        assert block is None
        assert meta is None
        assert text == "Plain comment"

    def test_annotations_only(self) -> None:
        block, meta, text = AnnotationService.decompose_comment("[readonly, public]")
        assert block is None
        assert meta is not None
        assert meta.readonly is True
        assert meta.public is True
        assert text == ""

    def test_annotations_with_text(self) -> None:
        block, meta, text = AnnotationService.decompose_comment("[min=0, max=100] Temperature")
        assert block is None
        assert meta is not None
        assert meta.min == 0
        assert meta.max == 100
        assert text == "Temperature"

    def test_block_tag_with_annotations(self) -> None:
        block, meta, text = AnnotationService.decompose_comment(
            "<Motor> [readonly] Speed controller"
        )
        assert block is not None
        assert "Motor" in block
        assert meta is not None
        assert meta.readonly is True
        assert text == "Speed controller"

    def test_block_tag_only(self) -> None:
        block, meta, text = AnnotationService.decompose_comment("<Motor>")
        assert block is not None
        assert meta is None
        assert text == ""

    def test_choices_bool(self) -> None:
        _, meta, _ = AnnotationService.decompose_comment("[choices=Bool]")
        assert meta is not None
        assert meta.choices == {0: "False", 1: "True"}

    def test_choices_custom(self) -> None:
        _, meta, _ = AnnotationService.decompose_comment("[choices=Off:0|On:1|Auto:2]")
        assert meta is not None
        assert meta.choices == {0: "Off", 1: "On", 2: "Auto"}

    def test_physical_with_timing(self) -> None:
        _, meta, _ = AnnotationService.decompose_comment(
            "[physical=Sensor, on_delay=50ms, off_delay=10ms]"
        )
        assert meta is not None
        assert meta.physical == "Sensor"
        assert meta.on_delay == "50ms"
        assert meta.off_delay == "10ms"


class TestRecomposeComment:
    def test_round_trip_plain(self) -> None:
        original = "Plain comment"
        block, meta, text = AnnotationService.decompose_comment(original)
        result = AnnotationService.recompose_comment(block, meta, text)
        assert result == original

    def test_round_trip_with_meta(self) -> None:
        original = "[readonly, public] Speed controller"
        block, meta, text = AnnotationService.decompose_comment(original)
        result = AnnotationService.recompose_comment(block, meta, text)
        assert result == original

    def test_preserves_block_tag(self) -> None:
        original = "<Motor> [readonly] Speed"
        block, _, text = AnnotationService.decompose_comment(original)
        new_meta = TagMeta(public=True)
        result = AnnotationService.recompose_comment(block, new_meta, text)
        assert result.startswith("<Motor>")
        assert "[public]" in result
        assert result.endswith("Speed")

    def test_empty_meta_produces_no_brackets(self) -> None:
        result = AnnotationService.recompose_comment(None, TagMeta(), "Hello")
        assert result == "Hello"

    def test_none_meta_produces_no_brackets(self) -> None:
        result = AnnotationService.recompose_comment(None, None, "Hello")
        assert result == "Hello"


class TestValidateMeta:
    def test_valid_empty(self) -> None:
        assert AnnotationService.validate_meta(TagMeta()) == []

    def test_valid_combined(self) -> None:
        meta = TagMeta(public=True, min=0, max=100, uom="psi")
        assert AnnotationService.validate_meta(meta) == []

    def test_readonly_final_conflict(self) -> None:
        meta = TagMeta(readonly=True, final=True)
        errors = AnnotationService.validate_meta(meta)
        assert len(errors) == 1
        assert "readonly" in errors[0] and "final" in errors[0]

    def test_readonly_external_conflict(self) -> None:
        meta = TagMeta(readonly=True, external=True)
        errors = AnnotationService.validate_meta(meta)
        assert len(errors) == 1
        assert "readonly" in errors[0] and "external" in errors[0]

    def test_choices_with_min_conflict(self) -> None:
        meta = TagMeta(choices={0: "Off", 1: "On"}, min=0)
        errors = AnnotationService.validate_meta(meta)
        assert any("choices" in e for e in errors)

    def test_choices_with_max_conflict(self) -> None:
        meta = TagMeta(choices={0: "Off", 1: "On"}, max=100)
        errors = AnnotationService.validate_meta(meta)
        assert any("choices" in e for e in errors)

    def test_min_greater_than_max(self) -> None:
        meta = TagMeta(min=100, max=0)
        errors = AnnotationService.validate_meta(meta)
        assert any("min" in e for e in errors)

    def test_physical_timing_and_profile_conflict(self) -> None:
        meta = TagMeta(physical="Sensor", on_delay="50ms", profile="generic_thermal")
        errors = AnnotationService.validate_meta(meta)
        assert any("timing" in e.lower() or "profile" in e.lower() for e in errors)

    def test_system_without_physical_details(self) -> None:
        meta = TagMeta(physical="Sensor", system="Group1")
        errors = AnnotationService.validate_meta(meta)
        assert any("system" in e for e in errors)

    def test_link_without_physical(self) -> None:
        meta = TagMeta(link="EnableField")
        errors = AnnotationService.validate_meta(meta)
        assert any("link" in e for e in errors)

    def test_link_with_physical_valid(self) -> None:
        meta = TagMeta(link="EnableField", physical="Sensor", on_delay="50ms", off_delay="10ms")
        assert AnnotationService.validate_meta(meta) == []


class TestMetaHasAdvanced:
    def test_empty_meta(self) -> None:
        assert AnnotationService.meta_has_advanced(TagMeta()) is False

    def test_none_meta(self) -> None:
        assert AnnotationService.meta_has_advanced(None) is False

    def test_lock_only(self) -> None:
        assert AnnotationService.meta_has_advanced(TagMeta(lock=True)) is True

    def test_link_only(self) -> None:
        assert AnnotationService.meta_has_advanced(TagMeta(link="Cmd")) is True

    def test_physical_only(self) -> None:
        assert AnnotationService.meta_has_advanced(TagMeta(physical="Sensor")) is True

    @pytest.mark.parametrize(
        "field",
        ["on_delay", "off_delay", "profile", "system"],
    )
    def test_physical_detail_fields(self, field: str) -> None:
        meta = TagMeta(**{field: "value"})  # type: ignore[arg-type]
        assert AnnotationService.meta_has_advanced(meta) is True
