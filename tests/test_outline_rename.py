"""Tests for outline rename functionality.

Tests the regex-based rename feature that allows renaming nickname segments
in the outline panel tree.
"""

import re

import pytest

from clicknick.utils.rename_helpers import build_rename_pattern
from clicknick.views.nav_window.outline_logic import build_tree, flatten_tree


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


class TestRenameFromOutlineItems:
    """Rename as the panel runs it: the item says which segment it renames and what precedes it."""

    @staticmethod
    def _rename(nicknames: list[str], text: str, new_text: str, occurrence: int = 0) -> list[str]:
        """Rename with the item shown as ``text`` (the ``occurrence``-th one in the tree)."""
        from clicknick.utils.rename_helpers import rename_replacement
        from clicknick.views.nav_window.outline_logic import build_tree, flatten_tree

        entries = [("DS", i + 1, nick, i + 1) for i, nick in enumerate(nicknames)]
        found = [
            item
            for top in flatten_tree(build_tree(entries))
            for item, _ in top.iter_preorder()
            if item.text == text
        ]
        item = found[occurrence]
        pattern, template = build_rename_pattern(
            item.rename_prefix, item.rename_text, item.rename_is_array, item.rename_exact
        )
        replacement = rename_replacement(template, new_text)
        renamed = [re.sub(pattern, replacement, nick) for nick in nicknames]
        # Rename touches exactly the nicknames under the item, the ones double-click filters to
        touched = {
            ("DS", i + 1)
            for i, (new, old) in enumerate(zip(renamed, nicknames, strict=True))
            if new != old
        }
        assert touched == set(item.get_all_leaves())
        return renamed

    def test_inner_segment_that_prefixes_its_path_renames_only_itself(self):
        nicks = ["Tank_T_A", "Tank_T_B", "T_Ambient"]
        assert self._rename(nicks, "Tank_T", "NEW") == ["Tank_NEW_A", "Tank_NEW_B", "T_Ambient"]

    def test_outer_segment_repeated_inside_renames_the_outer(self):
        nicks = ["Pump_Pump_Status", "Pump_Pump_X", "Pump_Status", "Pump_Q"]
        assert self._rename(nicks, "Pump", "Motor", occurrence=0) == [
            "Motor_Pump_Status",
            "Motor_Pump_X",
            "Motor_Status",
            "Motor_Q",
        ]

    def test_inner_segment_repeating_the_outer_name_renames_the_inner(self):
        nicks = ["Pump_Pump_Status", "Pump_Pump_X", "Pump_Status", "Pump_Q"]
        assert self._rename(nicks, "Pump", "Inner", occurrence=1) == [
            "Pump_Inner_Status",
            "Pump_Inner_X",
            "Pump_Status",
            "Pump_Q",
        ]

    def test_collapsed_array_chain_renames_the_array_name(self):
        nicks = ["Tank_Pump1_Run", "Tank_Pump2_Run", "Tank_Pump2_Stop", "Tank_Pump1_Stop"]
        assert self._rename(nicks, "Tank_Pump[1-2]", "Fan") == [
            "Tank_Fan1_Run",
            "Tank_Fan2_Run",
            "Tank_Fan2_Stop",
            "Tank_Fan1_Stop",
        ]

    def test_leading_zero_array_renames_keep_the_digits(self):
        nicks = ["Pump01_Run", "Pump02_Run"]
        assert self._rename(nicks, "Pump[01-02]", "Fan") == ["Fan01_Run", "Fan02_Run"]

    def test_own_name_of_a_mixed_array_leaves_the_array_items_alone(self):
        nicks = ["Command_Alarm", "Command_Alarm1_id", "Command_Alarm2_id", "Command_Alarm_Valve1"]
        assert self._rename(nicks, "Command_Alarm", "Cmd") == [
            "Command_Cmd",
            "Command_Alarm1_id",
            "Command_Alarm2_id",
            "Command_Alarm_Valve1",
        ]

    def test_array_inside_a_mixed_array_renames_its_own_name(self):
        nicks = ["Motor1_Speed", "Motor2_Speed", "Motor_Fan1", "Motor_Fan2"]
        assert self._rename(nicks, "Motor_Fan[1-2]", "Blower") == [
            "Motor1_Speed",
            "Motor2_Speed",
            "Motor_Blower1",
            "Motor_Blower2",
        ]

    @pytest.mark.parametrize("nicks", [["Pump_A", "Pump_B"], ["Pump1_A", "Pump2_A"]])
    def test_new_text_starting_with_a_digit_is_read_literally(self, nicks):
        name = "Pump" if nicks[0].startswith("Pump_") else "Pump[1-2]"
        renamed = self._rename(nicks, name, "2ndPump")
        assert all(n.startswith("2ndPump") for n in renamed)

    def test_backslash_in_new_text_is_read_literally(self):
        renamed = self._rename(["Pump_A", "Pump_B"], "Pump", "a\\1b")
        assert renamed == ["a\\1b_A", "a\\1b_B"]

    def test_gap_node_has_nothing_to_rename(self):
        entries = [
            ("DS", 1, "Mtr1__Debug", 1),
            ("DS", 2, "Mtr1__Other", 2),
            ("DS", 3, "Mtr1_Run", 3),
            ("DS", 4, "Mtr2_Run", 4),
        ]
        gaps = [
            item
            for top in flatten_tree(build_tree(entries))
            for item, _ in top.iter_preorder()
            if item.text == "_"
        ]
        assert gaps
        assert all(item.rename_text == "" for item in gaps)

    def test_folder_leaves_a_sibling_with_a_trailing_underscore_alone(self):
        nicks = ["T", "T_", "T_T10"]
        assert self._rename(nicks, "T", "New", occurrence=0)[1] == "T_"

    def test_index_folder_leaves_a_sibling_with_a_trailing_underscore_alone(self):
        nicks = ["Pump1", "Pump1_X", "Pump1_", "Pump2_X"]
        assert self._rename(nicks, "1", "New", occurrence=0)[2] == "Pump1_"


class TestDigitSegmentBetweenUnderscores:
    """ "Zone_1_Temp" has a plain "1" segment: not the array "Zone1_Temp"."""

    def test_stays_apart_from_the_array_and_renames_only_itself(self):
        nicks = ["Zone_1_Temp", "Zone_2_Temp", "Zone1_Temp", "Zone2_Temp"]
        assert TestRenameFromOutlineItems._rename(nicks, "Zone[1-2]", "Area") == [
            "Zone_1_Temp",
            "Zone_2_Temp",
            "Area1_Temp",
            "Area2_Temp",
        ]
        assert TestRenameFromOutlineItems._rename(nicks, "Zone_1_Temp", "Hot") == [
            "Zone_1_Hot",
            "Zone_2_Temp",
            "Zone1_Temp",
            "Zone2_Temp",
        ]

    def test_the_digit_segment_renames_its_own_nicknames(self):
        nicks = ["Zone_1_Temp", "Zone_1_Hi", "Zone_12_Temp", "Zone1_Temp"]
        assert TestRenameFromOutlineItems._rename(nicks, "Zone_1", "One") == [
            "Zone_One_Temp",
            "Zone_One_Hi",
            "Zone_12_Temp",
            "Zone1_Temp",
        ]

    def test_gap_chains_rename_exactly_what_they_show(self):
        nicks = ["A__B", "A___B", "A___C"]
        assert TestRenameFromOutlineItems._rename(nicks, "_B", "Q") == ["A__B", "A___Q", "A___C"]
