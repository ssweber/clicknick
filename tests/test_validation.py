"""Tests for validation.py - nickname and initial value validation."""

import pytest
from pyclickplc.banks import DataType
from pyclickplc.validation import validate_initial_value

from clicknick.models.validation import (
    nickname_duplicate_checker,
    validate_comment,
    validate_nickname,
)
from clicknick.models.validation import validate_initial_value as validate_row_initial_value


class TestCharactersCp1252Lacks:
    """CLICK turns an emoji in a comment into "??", so ClickNick flags it."""

    def test_a_comment_with_an_emoji_is_an_error_that_names_it(self):
        is_valid, error = validate_comment("Pump 😊")

        assert not is_valid
        assert error == "CLICK cannot hold '😊'. Replace it"

    def test_a_nickname_with_an_arrow_is_an_error_that_names_it(self):
        is_valid, error = validate_nickname("a→b", 1, lambda _name, _key: False)

        assert not is_valid
        assert "'→'" in error

    @pytest.mark.parametrize("data_type", [DataType.TXT, DataType.INT])
    def test_an_initial_value_with_an_arrow_is_an_error(self, data_type):
        is_valid, error = validate_row_initial_value("→", data_type)

        assert not is_valid
        assert "'→'" in error

    def test_a_character_cp1252_has_is_still_valid(self):
        assert validate_comment("Café 5°C") == (True, "")

    @pytest.mark.parametrize("char", ["é", "€"])
    def test_a_txt_initial_value_that_cp1252_has_is_valid(self, char):
        assert validate_row_initial_value(char, DataType.TXT) == (True, "")


def _format_only(nickname: str) -> tuple[bool, str]:
    """Check only the format rules, by calling validate_nickname with no duplicates."""
    return validate_nickname(nickname, 0, lambda _nickname, _addr_key: False)


class TestValidateNicknameFormat:
    """The format rules that validate_nickname gets from pyclickplc."""

    def test_empty_is_valid(self):
        """Empty nickname is valid (means unassigned)."""
        is_valid, error = _format_only("")
        assert is_valid is True
        assert error == ""

    def test_valid_simple(self):
        """Simple alphanumeric nickname."""
        is_valid, error = _format_only("Motor1")
        assert is_valid is True
        assert error == ""

    def test_valid_with_underscore(self):
        """Underscore in middle is allowed."""
        is_valid, error = _format_only("Supply_Pump_Status")
        assert is_valid is True
        assert error == ""

    def test_valid_with_space(self):
        """Space is allowed in nicknames."""
        is_valid, error = _format_only("Motor Status")
        assert is_valid is True
        assert error == ""

    def test_valid_max_length(self):
        """Exactly 24 characters is valid."""
        is_valid, error = _format_only("A" * 24)
        assert is_valid is True
        assert error == ""

    def test_too_long(self):
        """More than 24 characters is invalid."""
        is_valid, error = _format_only("A" * 25)
        assert is_valid is False
        assert "25/24" in error

    def test_starts_with_underscore(self):
        """Cannot start with underscore."""
        is_valid, error = _format_only("_Motor")
        assert is_valid is False
        assert "Cannot start with _" in error

    @pytest.mark.parametrize(
        "char",
        ["%", '"', "<", ">", "!", "#", "$", "&", "'", "(", ")", "*", "+", "-", ".", "/"],
    )
    def test_forbidden_chars(self, char):
        """Various forbidden characters."""
        is_valid, error = _format_only(f"Motor{char}Status")
        assert is_valid is False
        assert "Invalid" in error

    def test_multiple_forbidden_shows_first_few(self):
        """Multiple forbidden chars shows first few in error."""
        is_valid, error = _format_only("a%b#c$d")
        assert is_valid is False
        assert "Invalid" in error
        # Should show some of the invalid chars


class TestValidateNickname:
    """Tests for validate_nickname() including uniqueness."""

    def test_format_error_takes_precedence(self):
        """Format errors are checked before uniqueness."""
        is_valid, error = validate_nickname("_Invalid", 100, nickname_duplicate_checker({}))
        assert is_valid is False
        assert "Cannot start with _" in error

    def test_unique_nickname(self):
        """Nickname not in dict is valid."""
        all_nicknames = {1: "Motor1", 2: "Motor2"}
        is_valid, error = validate_nickname(
            "Motor3", 100, nickname_duplicate_checker(all_nicknames)
        )
        assert is_valid is True
        assert error == ""

    def test_duplicate_nickname(self):
        """Duplicate nickname is invalid."""
        all_nicknames = {1: "Motor1", 2: "Motor2"}
        is_valid, error = validate_nickname(
            "Motor1", 100, nickname_duplicate_checker(all_nicknames)
        )
        assert is_valid is False
        assert "Duplicate" in error

    def test_duplicate_case_insensitive(self):
        """Duplicate check is case-insensitive."""
        all_nicknames = {1: "Motor1", 2: "Motor2"}
        is_valid, error = validate_nickname(
            "MOTOR1", 100, nickname_duplicate_checker(all_nicknames)
        )
        assert is_valid is False
        assert "Duplicate" in error

    def test_same_row_not_duplicate(self):
        """Same row (current_addr_key) is excluded from uniqueness check."""
        all_nicknames = {1: "Motor1", 2: "Motor2"}
        # Editing row 1, keeping same name is OK
        is_valid, error = validate_nickname("Motor1", 1, nickname_duplicate_checker(all_nicknames))
        assert is_valid is True
        assert error == ""

    def test_custom_duplicate_checker_used(self):
        """A custom duplicate checker decides uniqueness."""

        def custom_dup_check(nickname: str, exclude_addr_key: int) -> bool:
            return nickname.lower() == "taken"

        is_valid, error = validate_nickname("Taken", 100, custom_dup_check)
        assert is_valid is False
        assert "Duplicate" in error

    def test_custom_duplicate_checker_not_duplicate(self):
        """A checker that reports no duplicate means valid."""

        def custom_dup_check(nickname: str, exclude_addr_key: int) -> bool:
            return False

        is_valid, error = validate_nickname("AnyName", 100, custom_dup_check)
        assert is_valid is True


class TestValidateInitialValue:
    """Tests for validate_initial_value() across all data types."""

    def test_empty_is_valid_for_all_types(self):
        """Empty initial value is valid for all types."""
        for dt in [
            DataType.BIT,
            DataType.INT,
            DataType.INT2,
            DataType.FLOAT,
            DataType.HEX,
            DataType.TXT,
        ]:
            is_valid, error = validate_initial_value("", dt)
            assert is_valid is True, f"Failed for {dt}"
            assert error == ""

    # BIT tests
    def test_bit_zero(self):
        is_valid, error = validate_initial_value("0", DataType.BIT)
        assert is_valid is True

    def test_bit_one(self):
        is_valid, error = validate_initial_value("1", DataType.BIT)
        assert is_valid is True

    def test_bit_invalid(self):
        is_valid, error = validate_initial_value("2", DataType.BIT)
        assert is_valid is False
        assert "0 or 1" in error

    # INT tests (16-bit: -32768 to 32767)
    def test_int_valid(self):
        is_valid, error = validate_initial_value("100", DataType.INT)
        assert is_valid is True

    def test_int_min(self):
        is_valid, error = validate_initial_value("-32768", DataType.INT)
        assert is_valid is True

    def test_int_max(self):
        is_valid, error = validate_initial_value("32767", DataType.INT)
        assert is_valid is True

    def test_int_too_small(self):
        is_valid, error = validate_initial_value("-32769", DataType.INT)
        assert is_valid is False
        assert "Range" in error

    def test_int_too_large(self):
        is_valid, error = validate_initial_value("32768", DataType.INT)
        assert is_valid is False
        assert "Range" in error

    def test_int_not_number(self):
        is_valid, error = validate_initial_value("abc", DataType.INT)
        assert is_valid is False
        assert "integer" in error

    # INT2 tests (32-bit: -2147483648 to 2147483647)
    def test_int2_valid(self):
        is_valid, error = validate_initial_value("100000", DataType.INT2)
        assert is_valid is True

    def test_int2_min(self):
        is_valid, error = validate_initial_value("-2147483648", DataType.INT2)
        assert is_valid is True

    def test_int2_max(self):
        is_valid, error = validate_initial_value("2147483647", DataType.INT2)
        assert is_valid is True

    def test_int2_too_small(self):
        is_valid, error = validate_initial_value("-2147483649", DataType.INT2)
        assert is_valid is False

    def test_int2_too_large(self):
        is_valid, error = validate_initial_value("2147483648", DataType.INT2)
        assert is_valid is False

    # FLOAT tests
    def test_float_valid(self):
        is_valid, error = validate_initial_value("3.14159", DataType.FLOAT)
        assert is_valid is True

    def test_float_scientific(self):
        is_valid, error = validate_initial_value("-1.5E+10", DataType.FLOAT)
        assert is_valid is True

    def test_float_not_number(self):
        is_valid, error = validate_initial_value("abc", DataType.FLOAT)
        assert is_valid is False
        assert "number" in error

    # HEX tests (0000 to FFFF)
    def test_hex_valid(self):
        is_valid, error = validate_initial_value("ABCD", DataType.HEX)
        assert is_valid is True

    def test_hex_lowercase(self):
        is_valid, error = validate_initial_value("abcd", DataType.HEX)
        assert is_valid is True

    def test_hex_short(self):
        """Short hex values are valid (e.g., 'FF' for 0x00FF)."""
        is_valid, error = validate_initial_value("FF", DataType.HEX)
        assert is_valid is True

    def test_hex_too_long(self):
        is_valid, error = validate_initial_value("ABCDE", DataType.HEX)
        assert is_valid is False
        assert "4 hex" in error

    def test_hex_invalid_chars(self):
        is_valid, error = validate_initial_value("GHIJ", DataType.HEX)
        assert is_valid is False
        assert "hex" in error

    # TXT tests (a single character that cp1252 has)
    def test_txt_valid(self):
        is_valid, error = validate_initial_value("A", DataType.TXT)
        assert is_valid is True

    def test_txt_space(self):
        is_valid, error = validate_initial_value(" ", DataType.TXT)
        assert is_valid is True

    def test_txt_too_long(self):
        is_valid, error = validate_initial_value("AB", DataType.TXT)
        assert is_valid is False
        assert "single char" in error

    @pytest.mark.parametrize("char", ["\u00e9", "\u20ac"])  # e with accent, euro sign
    def test_txt_cp1252_char(self, char):
        assert validate_initial_value(char, DataType.TXT) == (True, "")

    @pytest.mark.parametrize("char", ["\x80", "\u0142"])  # U+0080, l with stroke
    def test_txt_not_in_cp1252(self, char):
        assert validate_initial_value(char, DataType.TXT) == (False, f"Not in cp1252: {char!r}")

    # Unknown data type
    def test_unknown_type_accepts_anything(self):
        """Unknown data types accept any value."""
        is_valid, error = validate_initial_value("anything", 99)
        assert is_valid is True
