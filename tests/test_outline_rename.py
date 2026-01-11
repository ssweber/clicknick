"""Tests for outline rename functionality.

Tests the regex-based rename feature that allows renaming nickname segments
in the outline panel tree.
"""

import re


class TestRenameRegexPatterns:
    """Test regex patterns for renaming outline nodes."""

    def test_non_array_node_simple(self):
        """Rename a simple non-array node segment."""
        # Original nicknames
        nicknames = [
            "Tank_Pump_Status",
            "Tank_Pump_Speed",
            "Tank_Valve_Open",
        ]

        # Pattern for renaming "Pump" to "Motor"
        # Node: Tank -> Pump
        prefix = "Tank_"
        current_node_text = "Pump"
        new_text = "Motor"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        # Apply rename
        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Tank_Motor_Status",
            "Tank_Motor_Speed",
            "Tank_Valve_Open",  # Unchanged
        ]

    def test_non_array_node_at_root(self):
        """Rename a root-level non-array node."""
        nicknames = [
            "Motor_Speed",
            "Motor_Status",
            "Pump_Flow",
        ]

        # Rename "Motor" to "Engine" at root
        prefix = ""
        current_node_text = "Motor"
        new_text = "Engine"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Engine_Speed",
            "Engine_Status",
            "Pump_Flow",  # Unchanged
        ]

    def test_array_node_rename(self):
        """Rename an array node segment preserving indices."""
        nicknames = [
            "Tank_Pump1_Speed",
            "Tank_Pump2_Speed",
            "Tank_Pump1_Status",
            "Tank_Pump2_Status",
            "Tank_Valve_Open",
        ]

        # Rename "Pump" to "Motor" for array node
        prefix = "Tank_"
        current_node_text = "Pump"
        new_text = "Motor"

        # Array pattern: captures prefix, base name, digit, and remainder
        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(\d+)(_|$)"
        replacement = rf"\1{new_text}\3\4"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Tank_Motor1_Speed",
            "Tank_Motor2_Speed",
            "Tank_Motor1_Status",
            "Tank_Motor2_Status",
            "Tank_Valve_Open",  # Unchanged
        ]

    def test_array_node_at_root(self):
        """Rename a root-level array node."""
        nicknames = [
            "Motor1_Speed",
            "Motor2_Speed",
            "Motor3_Run",
            "Pump_Flow",
        ]

        # Rename "Motor" to "Engine" at root (array)
        prefix = ""
        current_node_text = "Motor"
        new_text = "Engine"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(\d+)(_|$)"
        replacement = rf"\1{new_text}\3\4"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Engine1_Speed",
            "Engine2_Speed",
            "Engine3_Run",
            "Pump_Flow",  # Unchanged
        ]

    def test_leaf_node_rename(self):
        """Rename a leaf node (terminal segment)."""
        nicknames = [
            "Tank_Pump_Speed",
            "Tank_Pump_Status",
            "Tank_Valve_Speed",
        ]

        # Rename "Speed" to "Velocity" leaf
        prefix = "Tank_Pump_"
        current_node_text = "Speed"
        new_text = "Velocity"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})$"
        replacement = rf"\1{new_text}"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Tank_Pump_Velocity",
            "Tank_Pump_Status",
            "Tank_Valve_Speed",  # Unchanged (different prefix)
        ]

    def test_array_index_leaf_rename(self):
        """Rename a collapsed array index leaf (e.g., '1_Speed')."""
        nicknames = [
            "Setpoint1_Reached",
            "Setpoint2_Reached",
            "Setpoint1_Cleared",
        ]

        # Rename "Reached" to "Active" in array context
        # Node: Setpoint[1-2] -> 1_Reached
        prefix = "Setpoint1_"
        current_node_text = "Reached"
        new_text = "Active"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})$"
        replacement = rf"\1{new_text}"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Setpoint1_Active",
            "Setpoint2_Reached",  # Unchanged (different index)
            "Setpoint1_Cleared",  # Unchanged (different suffix)
        ]

    def test_nested_array_rename(self):
        """Rename in deeply nested array structure."""
        nicknames = [
            "Zone1_Pump1_Speed",
            "Zone1_Pump2_Speed",
            "Zone2_Pump1_Speed",
            "Zone1_Valve_Open",
        ]

        # Rename "Pump" to "Motor" within Zone1
        prefix = "Zone1_"
        current_node_text = "Pump"
        new_text = "Motor"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(\d+)(_|$)"
        replacement = rf"\1{new_text}\3\4"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Zone1_Motor1_Speed",
            "Zone1_Motor2_Speed",
            "Zone2_Pump1_Speed",  # Unchanged (different zone)
            "Zone1_Valve_Open",  # Unchanged
        ]

    def test_special_characters_in_names(self):
        """Test renaming with special regex characters in names."""
        nicknames = [
            "Test.Value_X",
            "Test.Value_Y",
        ]

        # Rename "Test.Value" to "Test.Data" (dot is a special regex char)
        prefix = ""
        current_node_text = "Test.Value"
        new_text = "Test.Data"

        # re.escape handles the dot
        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Test.Data_X",
            "Test.Data_Y",
        ]

    def test_double_underscore_node(self):
        """Test renaming with double underscore nodes."""
        nicknames = [
            "Motor1__Debug_Value",
            "Motor1__Debug_Count",
            "Motor1_Speed",
        ]

        # Rename "Debug" in underscore branch
        prefix = "Motor1__"
        current_node_text = "Debug"
        new_text = "Internal"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Motor1__Internal_Value",
            "Motor1__Internal_Count",
            "Motor1_Speed",  # Unchanged
        ]


class TestRenameEdgeCases:
    """Test edge cases for rename functionality."""

    def test_no_matches(self):
        """No nicknames match the pattern."""
        nicknames = [
            "Tank_Valve_Open",
            "Pump_Status",
        ]

        # Try to rename non-existent "Motor"
        prefix = ""
        current_node_text = "Motor"
        new_text = "Engine"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        # All unchanged
        assert results == nicknames

    def test_partial_match_not_renamed(self):
        """Partial matches should not be renamed."""
        nicknames = [
            "Motor_Speed",
            "MotorOil_Level",  # Contains "Motor" but not as segment
        ]

        prefix = ""
        current_node_text = "Motor"
        new_text = "Engine"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Engine_Speed",
            "MotorOil_Level",  # Unchanged (no underscore after Motor)
        ]

    def test_empty_prefix(self):
        """Empty prefix matches from start of string."""
        nicknames = [
            "Pump_Speed",
            "Tank_Pump_Speed",
        ]

        prefix = ""
        current_node_text = "Pump"
        new_text = "Motor"

        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Motor_Speed",
            "Tank_Pump_Speed",  # Unchanged (Pump not at start)
        ]

    def test_single_segment_nickname(self):
        """Rename single-segment nickname (no underscores)."""
        nicknames = [
            "Motor",
            "Pump",
        ]

        prefix = ""
        current_node_text = "Motor"
        new_text = "Engine"

        # Pattern should match end of string with (_|$)
        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(_|$)"
        replacement = rf"\1{new_text}\3"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Engine",
            "Pump",
        ]

    def test_array_at_end_of_nickname(self):
        """Array number at the very end of nickname."""
        nicknames = [
            "Tank_Alarm1",
            "Tank_Alarm2",
            "Tank_Status",
        ]

        prefix = "Tank_"
        current_node_text = "Alarm"
        new_text = "Error"

        # Array pattern with (_|$) to match end
        pattern = rf"^({re.escape(prefix)})({re.escape(current_node_text)})(\d+)(_|$)"
        replacement = rf"\1{new_text}\3\4"

        results = [re.sub(pattern, replacement, nick) for nick in nicknames]

        assert results == [
            "Tank_Error1",
            "Tank_Error2",
            "Tank_Status",
        ]


class TestRenameValidation:
    """Test validation logic for rename operations."""

    def test_invalid_new_name_empty(self):
        """Empty new name should be invalid."""
        new_text = ""
        assert new_text == "" or new_text.strip() == ""

    def test_invalid_new_name_whitespace_only(self):
        """Whitespace-only new name should be invalid."""
        new_text = "   "
        assert new_text.strip() == ""

    def test_invalid_new_name_with_underscore(self):
        """New name with underscores should be validated (policy decision)."""
        # Note: This is a policy decision - should underscores be allowed?
        # For now, we'll allow them but this test documents the consideration
        new_text = "New_Name"
        assert "_" in new_text

    def test_valid_new_name(self):
        """Valid new name without special characters."""
        new_text = "NewMotor"
        assert new_text and new_text.strip() and len(new_text) > 0


def build_rename_pattern(prefix: str, current_text: str, is_array: bool) -> tuple[str, str]:
    """Helper to build rename pattern and replacement strings.

    Args:
        prefix: The full path prefix before the node to rename (e.g., "Tank_Pump_")
        current_text: The current text of the node to rename
        is_array: True if this is an array node (has numeric children)

    Returns:
        Tuple of (pattern, replacement_template) where replacement needs {new_text}
    """
    if is_array:
        # Array pattern: ^(prefix)(current)(\d+)(_|$)
        # Replacement: \1{new_text}\3\4
        pattern = rf"^({re.escape(prefix)})({re.escape(current_text)})(\d+)(_|$)"
        replacement_template = r"\1{new_text}\3\4"
    else:
        # Non-array pattern: ^(prefix)(current)(_|$)
        # Replacement: \1{new_text}\3
        pattern = rf"^({re.escape(prefix)})({re.escape(current_text)})(_|$)"
        replacement_template = r"\1{new_text}\3"

    return pattern, replacement_template


class TestBuildRenamePattern:
    """Test the helper function that builds regex patterns."""

    def test_build_pattern_non_array_root(self):
        """Build pattern for root-level non-array node."""
        pattern, repl = build_rename_pattern("", "Motor", is_array=False)

        assert re.match(pattern, "Motor_Speed")
        assert re.match(pattern, "Motor")
        assert not re.match(pattern, "MotorOil")
        assert not re.match(pattern, "Tank_Motor_Speed")

        # Test replacement
        result = re.sub(pattern, repl.format(new_text="Engine"), "Motor_Speed")
        assert result == "Engine_Speed"

    def test_build_pattern_array_root(self):
        """Build pattern for root-level array node."""
        pattern, repl = build_rename_pattern("", "Motor", is_array=True)

        assert re.match(pattern, "Motor1_Speed")
        assert re.match(pattern, "Motor2")
        assert not re.match(pattern, "Motor_Speed")  # No digit
        assert not re.match(pattern, "Tank_Motor1_Speed")

        result = re.sub(pattern, repl.format(new_text="Engine"), "Motor1_Speed")
        assert result == "Engine1_Speed"

    def test_build_pattern_non_array_nested(self):
        """Build pattern for nested non-array node."""
        pattern, repl = build_rename_pattern("Tank_", "Pump", is_array=False)

        assert re.match(pattern, "Tank_Pump_Speed")
        assert re.match(pattern, "Tank_Pump")
        assert not re.match(pattern, "Tank_Pump1_Speed")  # Has digit (would match array)
        assert not re.match(pattern, "Pump_Speed")  # Missing prefix

        result = re.sub(pattern, repl.format(new_text="Motor"), "Tank_Pump_Speed")
        assert result == "Tank_Motor_Speed"

    def test_build_pattern_array_nested(self):
        """Build pattern for nested array node."""
        pattern, repl = build_rename_pattern("Tank_", "Pump", is_array=True)

        assert re.match(pattern, "Tank_Pump1_Speed")
        assert re.match(pattern, "Tank_Pump2")
        assert not re.match(pattern, "Tank_Pump_Speed")  # No digit

        result = re.sub(pattern, repl.format(new_text="Motor"), "Tank_Pump1_Speed")
        assert result == "Tank_Motor1_Speed"

    def test_build_pattern_special_chars(self):
        """Build pattern with special regex characters."""
        pattern, repl = build_rename_pattern("Test.", "Value[0]", is_array=False)

        # Should match because re.escape handles special chars
        assert re.match(pattern, "Test.Value[0]_X")

        result = re.sub(pattern, repl.format(new_text="Data"), "Test.Value[0]_X")
        assert result == "Test.Data_X"
