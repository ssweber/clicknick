"""Service for decomposing, recomposing, and validating tag annotations in comments."""

from __future__ import annotations

from pyclickplc.blocks import format_block_tag, parse_block_tag
from pyrung.click.tag_map import TagMeta, format_tag_meta, parse_tag_meta

from .physical_response import meta_response, response_check


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

        response = meta_response(meta)
        errors += response_check(response)
        if meta.system is not None and not response:
            errors.append("'system' requires a response, such as on_delay=.")
        if meta.link is not None and meta.physical is None and not response:
            errors.append("'link' requires a response, such as on_delay=, or 'physical'.")
        if not errors:
            # The writer has rules of its own, such as a flag needing link= beside it.
            try:
                format_tag_meta(meta)
            except ValueError as exc:
                errors.append(str(exc))

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
            or meta.system is not None
            or bool(meta_response(meta))
        )
