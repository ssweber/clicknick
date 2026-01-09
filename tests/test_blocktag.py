"""Tests for blocktag.py - block tag parsing and matching."""

from dataclasses import dataclass

import pytest

from clicknick.models.blocktag import (
    BlockRange,
    BlockTag,
    compute_all_block_ranges,
    extract_block_name,
    find_block_range_indices,
    find_paired_tag_index,
    get_block_type,
    is_block_tag,
    parse_block_tag,
    strip_block_tag,
    validate_block_span,
)


class TestParseBlockTag:
    """Tests for parse_block_tag()."""

    def test_empty_comment(self):
        result = parse_block_tag("")
        assert result == BlockTag(None, None, "", None)

    def test_no_tag(self):
        result = parse_block_tag("Just a comment")
        assert result.name is None
        assert result.tag_type is None
        assert result.remaining_text == "Just a comment"

    def test_opening_tag(self):
        result = parse_block_tag("<Motor>")
        assert result.name == "Motor"
        assert result.tag_type == "open"
        assert result.remaining_text == ""
        assert result.bg_color is None

    def test_opening_tag_with_text_after(self):
        result = parse_block_tag("<Motor>Valve controls")
        assert result.name == "Motor"
        assert result.tag_type == "open"
        assert result.remaining_text == "Valve controls"

    def test_closing_tag(self):
        result = parse_block_tag("</Motor>")
        assert result.name == "Motor"
        assert result.tag_type == "close"
        assert result.remaining_text == ""

    def test_closing_tag_with_text_after(self):
        result = parse_block_tag("</Motor>end of section")
        assert result.name == "Motor"
        assert result.tag_type == "close"
        assert result.remaining_text == "end of section"

    def test_self_closing_tag(self):
        result = parse_block_tag("<Spare />")
        assert result.name == "Spare"
        assert result.tag_type == "self-closing"
        assert result.remaining_text == ""

    def test_self_closing_no_space(self):
        result = parse_block_tag("<Spare/>")
        assert result.name == "Spare"
        assert result.tag_type == "self-closing"

    def test_opening_with_bg_color(self):
        result = parse_block_tag('<Motor bg="#FFCDD2">')
        assert result.name == "Motor"
        assert result.tag_type == "open"
        assert result.bg_color == "#FFCDD2"

    def test_opening_with_bg_single_quotes(self):
        result = parse_block_tag("<Motor bg='Red'>")
        assert result.name == "Motor"
        assert result.tag_type == "open"
        assert result.bg_color == "Red"

    def test_self_closing_with_bg(self):
        result = parse_block_tag('<Spare bg="Blue" />')
        assert result.name == "Spare"
        assert result.tag_type == "self-closing"
        assert result.bg_color == "Blue"

    def test_closing_tag_no_bg(self):
        """Closing tags don't have bg attribute."""
        result = parse_block_tag('</Motor bg="Red">')
        # The bg="Red" is part of the "name" here, which is invalid
        # but the parser still extracts it as a close tag
        assert result.tag_type == "close"

    def test_name_with_spaces(self):
        result = parse_block_tag("<Alm Bits>")
        assert result.name == "Alm Bits"
        assert result.tag_type == "open"

    def test_unclosed_angle_bracket(self):
        result = parse_block_tag("<Motor")
        assert result.name is None
        assert result.tag_type is None

    def test_empty_tag(self):
        result = parse_block_tag("<>")
        assert result.name is None
        assert result.tag_type is None

    def test_whitespace_only_tag(self):
        result = parse_block_tag("<   >")
        assert result.name is None
        assert result.tag_type is None


class TestHelperFunctions:
    """Tests for is_block_tag, get_block_type, extract_block_name, strip_block_tag."""

    def test_is_block_tag_open(self):
        assert is_block_tag("<Motor>") is True

    def test_is_block_tag_close(self):
        assert is_block_tag("</Motor>") is True

    def test_is_block_tag_self_closing(self):
        assert is_block_tag("<Spare />") is True

    def test_is_block_tag_not_tag(self):
        assert is_block_tag("Just a comment") is False

    def test_get_block_type_open(self):
        assert get_block_type("<Motor>") == "open"

    def test_get_block_type_close(self):
        assert get_block_type("</Motor>") == "close"

    def test_get_block_type_self_closing(self):
        assert get_block_type("<Spare />") == "self-closing"

    def test_get_block_type_none(self):
        assert get_block_type("comment") is None

    def test_extract_block_name(self):
        assert extract_block_name("<Motor>") == "Motor"
        assert extract_block_name("</Motor>") == "Motor"
        assert extract_block_name("<Spare />") == "Spare"
        assert extract_block_name("no tag") is None

    def test_strip_block_tag_open(self):
        assert strip_block_tag("<Motor>Valve info") == "Valve info"

    def test_strip_block_tag_close(self):
        assert strip_block_tag("</Motor>end") == "end"

    def test_strip_block_tag_self_closing(self):
        assert strip_block_tag("<Spare />") == ""

    def test_strip_block_tag_no_tag(self):
        assert strip_block_tag("just comment") == "just comment"

    def test_strip_block_tag_empty(self):
        assert strip_block_tag("") == ""


# Helper dataclass for testing matching functions
@dataclass
class MockRow:
    comment: str
    memory_type: str | None = None


class TestFindPairedTagIndex:
    """Tests for find_paired_tag_index()."""

    def test_simple_open_close(self):
        rows = [
            MockRow("<Block>"),
            MockRow("middle"),
            MockRow("</Block>"),
        ]
        # From open tag, find close
        assert find_paired_tag_index(rows, 0) == 2
        # From close tag, find open
        assert find_paired_tag_index(rows, 2) == 0

    def test_self_closing_no_pair(self):
        rows = [MockRow("<Spare />")]
        assert find_paired_tag_index(rows, 0) is None

    def test_nested_blocks_same_name(self):
        """Correctly match nested blocks with same name."""
        rows = [
            MockRow("<Block>"),  # 0 -> 5
            MockRow("<Block>"),  # 1 -> 3
            MockRow("inner"),
            MockRow("</Block>"),  # 3 <- 1
            MockRow("outer"),
            MockRow("</Block>"),  # 5 <- 0
        ]
        # Outer open -> outer close
        assert find_paired_tag_index(rows, 0) == 5
        # Inner open -> inner close
        assert find_paired_tag_index(rows, 1) == 3
        # Inner close -> inner open
        assert find_paired_tag_index(rows, 3) == 1
        # Outer close -> outer open
        assert find_paired_tag_index(rows, 5) == 0

    def test_unmatched_open(self):
        rows = [
            MockRow("<Block>"),
            MockRow("no close"),
        ]
        assert find_paired_tag_index(rows, 0) is None

    def test_unmatched_close(self):
        rows = [
            MockRow("no open"),
            MockRow("</Block>"),
        ]
        assert find_paired_tag_index(rows, 1) is None

    def test_memory_type_filtering(self):
        """Only matches within same memory type (for interleaved views)."""
        rows = [
            MockRow("<Timers>", "T"),  # 0
            MockRow("T data", "T"),
            MockRow("<Timers>", "TD"),  # 2 - different memory type
            MockRow("TD data", "TD"),
            MockRow("</Timers>", "TD"),  # 4
            MockRow("</Timers>", "T"),  # 5
        ]
        # T's open (0) should match T's close (5), not TD's close (4)
        assert find_paired_tag_index(rows, 0) == 5
        # TD's open (2) should match TD's close (4)
        assert find_paired_tag_index(rows, 2) == 4


class TestFindBlockRangeIndices:
    """Tests for find_block_range_indices()."""

    def test_open_tag_range(self):
        rows = [
            MockRow("<Block>"),
            MockRow("data"),
            MockRow("</Block>"),
        ]
        assert find_block_range_indices(rows, 0) == (0, 2)

    def test_close_tag_range(self):
        rows = [
            MockRow("<Block>"),
            MockRow("data"),
            MockRow("</Block>"),
        ]
        assert find_block_range_indices(rows, 2) == (0, 2)

    def test_self_closing_range(self):
        rows = [MockRow("<Spare />")]
        assert find_block_range_indices(rows, 0) == (0, 0)

    def test_unmatched_open_singular(self):
        """Unmatched open tag returns singular range."""
        rows = [MockRow("<Block>"), MockRow("no close")]
        assert find_block_range_indices(rows, 0) == (0, 0)

    def test_no_tag(self):
        rows = [MockRow("just comment")]
        assert find_block_range_indices(rows, 0) is None


class TestComputeAllBlockRanges:
    """Tests for compute_all_block_ranges()."""

    def test_empty_rows(self):
        assert compute_all_block_ranges([]) == []

    def test_no_blocks(self):
        rows = [MockRow("comment1"), MockRow("comment2")]
        assert compute_all_block_ranges(rows) == []

    def test_single_block(self):
        rows = [
            MockRow("<Motor>"),
            MockRow("data"),
            MockRow("</Motor>"),
        ]
        ranges = compute_all_block_ranges(rows)
        assert len(ranges) == 1
        assert ranges[0].start_idx == 0
        assert ranges[0].end_idx == 2
        assert ranges[0].name == "Motor"

    def test_self_closing_block(self):
        rows = [MockRow("<Spare />")]
        ranges = compute_all_block_ranges(rows)
        assert len(ranges) == 1
        assert ranges[0].start_idx == 0
        assert ranges[0].end_idx == 0

    def test_multiple_blocks(self):
        rows = [
            MockRow("<A>"),
            MockRow("</A>"),
            MockRow("<B>"),
            MockRow("</B>"),
        ]
        ranges = compute_all_block_ranges(rows)
        assert len(ranges) == 2
        assert ranges[0].name == "A"
        assert ranges[1].name == "B"

    def test_nested_blocks(self):
        rows = [
            MockRow("<Outer>"),
            MockRow("<Inner>"),
            MockRow("</Inner>"),
            MockRow("</Outer>"),
        ]
        ranges = compute_all_block_ranges(rows)
        assert len(ranges) == 2
        # Should be sorted by start_idx
        assert ranges[0] == BlockRange(0, 3, "Outer", None, None)
        assert ranges[1] == BlockRange(1, 2, "Inner", None, None)

    def test_unclosed_tag_becomes_singular(self):
        rows = [
            MockRow("<Block>"),
            MockRow("no close"),
        ]
        ranges = compute_all_block_ranges(rows)
        assert len(ranges) == 1
        assert ranges[0].start_idx == 0
        assert ranges[0].end_idx == 0  # Singular

    def test_bg_color_preserved(self):
        rows = [MockRow('<Motor bg="Red">'), MockRow("</Motor>")]
        ranges = compute_all_block_ranges(rows)
        assert ranges[0].bg_color == "Red"

    def test_memory_type_preserved(self):
        rows = [MockRow("<Block>", "T"), MockRow("</Block>", "T")]
        ranges = compute_all_block_ranges(rows)
        assert ranges[0].memory_type == "T"


class TestValidateBlockSpan:
    """Tests for validate_block_span()."""

    @dataclass
    class FakeAddressRow:
        memory_type: str

    def test_empty_rows(self):
        is_valid, error = validate_block_span([])
        assert is_valid is True
        assert error is None

    def test_single_type(self):
        rows = [self.FakeAddressRow("DS"), self.FakeAddressRow("DS")]
        is_valid, error = validate_block_span(rows)
        assert is_valid is True

    def test_paired_types_t_td(self):
        """T and TD can be in same block (interleaved)."""
        rows = [self.FakeAddressRow("T"), self.FakeAddressRow("TD")]
        is_valid, error = validate_block_span(rows)
        assert is_valid is True

    def test_paired_types_ct_ctd(self):
        """CT and CTD can be in same block (interleaved)."""
        rows = [self.FakeAddressRow("CT"), self.FakeAddressRow("CTD")]
        is_valid, error = validate_block_span(rows)
        assert is_valid is True

    def test_incompatible_types(self):
        """Different non-paired types are invalid."""
        rows = [self.FakeAddressRow("DS"), self.FakeAddressRow("DD")]
        is_valid, error = validate_block_span(rows)
        assert is_valid is False
        assert "DS" in error
        assert "DD" in error

    def test_three_types_invalid(self):
        """More than 2 types is invalid even if some are paired."""
        rows = [
            self.FakeAddressRow("T"),
            self.FakeAddressRow("TD"),
            self.FakeAddressRow("DS"),
        ]
        is_valid, error = validate_block_span(rows)
        assert is_valid is False
