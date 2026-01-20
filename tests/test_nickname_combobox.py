"""Tests for nickname_combobox utility functions."""

from clicknick.widgets.nickname_combobox import (
    is_possible_address_or_literal,
    normalize_nickname,
)


class TestNormalizeNickname:
    """Tests for normalize_nickname function."""

    def test_empty_string(self):
        """Empty strings should be returned as-is."""
        assert normalize_nickname("") == ""

    def test_none_input(self):
        """None input should be returned as-is."""
        assert normalize_nickname(None) is None

    def test_pattern_bracket_single_letter_prefix(self):
        """Pattern: address_type[Numeral] -> address_typeNumeral (single letter prefix)."""
        assert normalize_nickname("x[0]") == "x0"
        assert normalize_nickname("x[1]") == "x1"
        assert normalize_nickname("x[123]") == "x123"
        assert normalize_nickname("y[5]") == "y5"
        assert normalize_nickname("C[100]") == "C100"
        assert normalize_nickname("t[42]") == "t42"

    def test_pattern_bracket_multi_letter_prefix(self):
        """Pattern: address_type[Numeral] -> address_typeNumeral (multi-letter prefix)."""
        assert normalize_nickname("CT[5]") == "CT5"
        assert normalize_nickname("DS[100]") == "DS100"
        assert normalize_nickname("DD[50]") == "DD50"
        assert normalize_nickname("CTD[10]") == "CTD10"
        assert normalize_nickname("TXT[1]") == "TXT1"

    def test_pattern_dot_single_letter_prefix(self):
        """Pattern: address_type.Nickname -> Nickname (single letter prefix)."""
        assert normalize_nickname("x.Temperature") == "Temperature"
        assert normalize_nickname("x.MyName") == "MyName"
        assert normalize_nickname("y.SomeValue") == "SomeValue"
        assert normalize_nickname("C.flag") == "flag"
        assert normalize_nickname("t.Timer1") == "Timer1"

    def test_pattern_dot_multi_letter_prefix(self):
        """Pattern: address_type.Nickname -> Nickname (multi-letter prefix)."""
        assert normalize_nickname("CT.Counter1") == "Counter1"
        assert normalize_nickname("DS.Register") == "Register"
        assert normalize_nickname("DD.DoubleData") == "DoubleData"
        assert normalize_nickname("CTD.CounterVal") == "CounterVal"
        assert normalize_nickname("TXT.TextValue") == "TextValue"

    def test_no_normalization_simple_names(self):
        """Simple names without prefix and brackets should remain unchanged."""
        assert normalize_nickname("SimpleNickname") == "SimpleNickname"
        assert normalize_nickname("CamelCaseNickname") == "CamelCaseNickname"
        assert normalize_nickname("Name_With_Underscores") == "Name_With_Underscores"

    def test_no_normalization_non_numeric_brackets(self):
        """Brackets with non-numeric content should not be normalized."""
        assert normalize_nickname("x[a]") == "x[a]"
        assert normalize_nickname("x[name]") == "x[name]"
        assert normalize_nickname("CT[abc]") == "CT[abc]"

    def test_no_normalization_invalid_patterns(self):
        """Invalid patterns should not be normalized."""
        assert normalize_nickname("123[5]") == "123[5]"  # Numbers not letters
        assert normalize_nickname("[5]") == "[5]"  # No prefix
        assert normalize_nickname("x.") == "x."  # No nickname after dot


class TestIsPossibleAddressOrLiteral:
    """Tests for is_possible_address_or_literal function."""

    def test_empty_string_is_valid(self):
        """Empty string should return True (nothing to validate against)."""
        assert is_possible_address_or_literal("") is True
        assert is_possible_address_or_literal("   ") is True

    def test_numeric_integers(self):
        """Integer values should be recognized as valid."""
        assert is_possible_address_or_literal("0") is True
        assert is_possible_address_or_literal("1") is True
        assert is_possible_address_or_literal("123") is True
        assert is_possible_address_or_literal("999999") is True

    def test_numeric_floats(self):
        """Float values should be recognized as valid."""
        assert is_possible_address_or_literal("1.0") is True
        assert is_possible_address_or_literal("3.14") is True
        assert is_possible_address_or_literal("0.5") is True
        assert is_possible_address_or_literal("123.456") is True

    def test_numeric_edge_cases(self):
        """Edge cases for numeric input."""
        assert is_possible_address_or_literal("0.") is True
        assert is_possible_address_or_literal("1.") is True
        assert is_possible_address_or_literal(".5") is False  # This will not match the regex

    def test_string_literals_with_quote(self):
        """Strings starting with single-quote should be recognized."""
        assert is_possible_address_or_literal("'") is True
        assert is_possible_address_or_literal("'hello") is True
        assert is_possible_address_or_literal("'123") is True

    def test_bit_prefixes_non_strict(self):
        """Bit type prefixes should match in non-strict mode."""
        # Single letter prefixes (BIT types)
        assert is_possible_address_or_literal("X", strict=False) is True
        assert is_possible_address_or_literal("Y", strict=False) is True
        assert is_possible_address_or_literal("C", strict=False) is True
        assert is_possible_address_or_literal("T", strict=False) is True

    def test_two_letter_prefixes_non_strict(self):
        """Two-letter prefixes should match in non-strict mode."""
        assert is_possible_address_or_literal("CT", strict=False) is True
        assert is_possible_address_or_literal("SC", strict=False) is True
        assert is_possible_address_or_literal("DS", strict=False) is True
        assert is_possible_address_or_literal("DD", strict=False) is True
        assert is_possible_address_or_literal("DH", strict=False) is True
        assert is_possible_address_or_literal("DF", strict=False) is True
        assert is_possible_address_or_literal("XD", strict=False) is True
        assert is_possible_address_or_literal("YD", strict=False) is True
        assert is_possible_address_or_literal("TD", strict=False) is True
        assert is_possible_address_or_literal("CTD", strict=False) is True
        assert is_possible_address_or_literal("SD", strict=False) is True

    def test_three_letter_prefixes_non_strict(self):
        """Three-letter prefixes should match in non-strict mode."""
        assert is_possible_address_or_literal("CTD", strict=False) is True
        assert is_possible_address_or_literal("TXT", strict=False) is True

    def test_prefix_partial_matching_non_strict(self):
        """Partial prefixes should match in non-strict mode."""
        # "C" is a prefix of "CT" and "CTD"
        assert is_possible_address_or_literal("C", strict=False) is True
        # "CT" is a complete prefix and also prefix of "CTD"
        assert is_possible_address_or_literal("CT", strict=False) is True
        # "T" is a prefix of "T", "TD", "TXT"
        assert is_possible_address_or_literal("T", strict=False) is True
        # "D" is a prefix of "DS", "DD", "DH", "DF"
        assert is_possible_address_or_literal("D", strict=False) is True

    def test_prefix_with_digits_non_strict(self):
        """Prefix followed by digits should be valid in non-strict mode."""
        assert is_possible_address_or_literal("X1", strict=False) is True
        assert is_possible_address_or_literal("CT5", strict=False) is True
        assert is_possible_address_or_literal("DS123", strict=False) is True
        assert is_possible_address_or_literal("CTD999", strict=False) is True

    def test_case_insensitive(self):
        """Input should be case-insensitive."""
        assert is_possible_address_or_literal("x", strict=False) is True
        assert is_possible_address_or_literal("X", strict=False) is True
        assert is_possible_address_or_literal("ct", strict=False) is True
        assert is_possible_address_or_literal("CT", strict=False) is True
        assert is_possible_address_or_literal("ds10", strict=False) is True
        assert is_possible_address_or_literal("DS10", strict=False) is True

    def test_invalid_prefix_non_strict(self):
        """Invalid prefixes should return False."""
        assert is_possible_address_or_literal("Z", strict=False) is False
        assert is_possible_address_or_literal("ABC", strict=False) is False
        assert is_possible_address_or_literal("Q1", strict=False) is False

    def test_strict_mode_partial_prefix(self):
        """Partial prefixes should fail in strict mode."""
        assert is_possible_address_or_literal("C", strict=True) is False
        assert is_possible_address_or_literal("T", strict=True) is False
        assert is_possible_address_or_literal("D", strict=True) is False

    def test_strict_mode_complete_prefix_no_digits(self):
        """Complete prefixes without digits should fail in strict mode."""
        # This might actually pass depending on how complete prefix matching works
        # Looking at the code, complete prefix + no digits would match Case 1 in non-strict
        # But in strict mode, it requires digits after the prefix
        assert is_possible_address_or_literal("X", strict=True) is False
        assert is_possible_address_or_literal("CT", strict=True) is False
        assert is_possible_address_or_literal("DS", strict=True) is False

    def test_strict_mode_complete_prefix_with_digits(self):
        """Complete prefixes followed by digits should pass in strict mode."""
        assert is_possible_address_or_literal("X1", strict=True) is True
        assert is_possible_address_or_literal("CT10", strict=True) is True
        assert is_possible_address_or_literal("DS123", strict=True) is True
        assert is_possible_address_or_literal("CTD999", strict=True) is True

    def test_strict_mode_numeric(self):
        """Numeric values should always be valid in strict mode."""
        assert is_possible_address_or_literal("0", strict=True) is True
        assert is_possible_address_or_literal("123", strict=True) is True
        assert is_possible_address_or_literal("45.67", strict=True) is True

    def test_strict_mode_string_literal(self):
        """String literals should be valid in strict mode."""
        assert is_possible_address_or_literal("'", strict=True) is True
        assert is_possible_address_or_literal("'hello", strict=True) is True

    def test_whitespace_handling(self):
        """Whitespace should be stripped."""
        assert is_possible_address_or_literal("  X1  ", strict=False) is True
        assert is_possible_address_or_literal("  CT10  ", strict=True) is True
        assert is_possible_address_or_literal("  123  ", strict=False) is True

    def test_invalid_characters(self):
        """Invalid characters should return False."""
        assert is_possible_address_or_literal("X@", strict=False) is False
        assert is_possible_address_or_literal("CT#1", strict=False) is False
        assert is_possible_address_or_literal("DS%", strict=False) is False

    def test_mixed_letters_and_digits_invalid(self):
        """Letters and digits mixed incorrectly should fail."""
        assert is_possible_address_or_literal("1X", strict=False) is False
        assert is_possible_address_or_literal("1CT", strict=False) is False

    def test_all_valid_prefixes(self):
        """Test all valid prefixes from DATA_TYPES."""
        valid_prefixes = [
            "X",
            "Y",
            "C",
            "T",
            "CT",
            "SC",
            "DS",
            "DD",
            "DH",
            "DF",
            "XD",
            "YD",
            "TD",
            "CTD",
            "SD",
            "TXT",
        ]

        for prefix in valid_prefixes:
            # Non-strict: should match the prefix itself
            assert is_possible_address_or_literal(prefix, strict=False) is True, (
                f"{prefix} non-strict"
            )
            # Non-strict: should match with digits
            assert is_possible_address_or_literal(f"{prefix}1", strict=False) is True, (
                f"{prefix}1 non-strict"
            )
            # Strict: should not match without digits
            assert is_possible_address_or_literal(prefix, strict=True) is False, f"{prefix} strict"
            # Strict: should match with digits
            assert is_possible_address_or_literal(f"{prefix}1", strict=True) is True, (
                f"{prefix}1 strict"
            )
