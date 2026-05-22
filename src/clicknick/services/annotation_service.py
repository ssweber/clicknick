"""Service for decomposing, recomposing, and validating tag annotations in comments."""

from __future__ import annotations

from pyclickplc.blocks import format_block_tag, parse_block_tag
from pyrung.click.tag_map import TagMeta, format_tag_meta, parse_tag_meta


class AnnotationService:
    """Pure-Python operations on bracket-syntax annotations in comment fields."""

    @staticmethod
    def decompose_comment(comment: str) -> tuple[str | None, TagMeta | None, str]:
        """Split a comment into block tag, annotation metadata, and free text.

        Returns (block_tag_str, tag_meta, free_text).
        """
        if not comment:
            return None, None, ""

        parsed = parse_block_tag(comment)
        if parsed.name is None or parsed.tag_type is None:
            meta, remaining = parse_tag_meta(comment)
            return None, meta, remaining.strip()

        block_tag_str = format_block_tag(parsed.name, parsed.tag_type, parsed.bg_color)
        meta, remaining = parse_tag_meta(parsed.remaining_text)
        return block_tag_str, meta, remaining.strip()

    @staticmethod
    def recompose_comment(
        block_tag_str: str | None,
        meta: TagMeta | None,
        free_text: str,
    ) -> str:
        """Join block tag, annotation metadata, and free text back into a comment."""
        meta_text = format_tag_meta(meta)
        parts = [p for p in (block_tag_str, meta_text, free_text.strip()) if p]
        return " ".join(parts)

    @staticmethod
    def validate_meta(meta: TagMeta) -> list[str]:
        """Check mutual exclusion rules. Returns list of error strings (empty = valid)."""
        errors: list[str] = []

        if meta.readonly and meta.final:
            errors.append("'readonly' and 'final' cannot both be set.")
        if meta.readonly and meta.external:
            errors.append("'readonly' and 'external' cannot both be set.")
        if meta.choices is not None and (meta.min is not None or meta.max is not None):
            errors.append("'choices' cannot be combined with 'min'/'max'.")
        if meta.min is not None and meta.max is not None and meta.min >= meta.max:
            errors.append("'min' must be less than 'max'.")

        has_timing = meta.on_delay is not None or meta.off_delay is not None
        has_profile = meta.profile is not None
        if has_timing and has_profile:
            errors.append("Physical timing and profile are mutually exclusive.")
        if meta.system is not None and not has_timing and not has_profile:
            errors.append("'system' requires on_delay/off_delay or profile.")
        if meta.link is not None and meta.physical is None:
            errors.append("'link' requires 'physical' to be set.")

        return errors

    @staticmethod
    def meta_has_advanced(meta: TagMeta | None) -> bool:
        """Check if any advanced-section fields are set."""
        if meta is None:
            return False
        return (
            meta.lock
            or meta.link is not None
            or meta.physical is not None
            or meta.on_delay is not None
            or meta.off_delay is not None
            or meta.profile is not None
            or meta.system is not None
        )
