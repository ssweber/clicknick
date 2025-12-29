"""Tests for outline_logic.py - tree building and flattening for address outline."""

from clicknick.views.nav_window.outline_logic import (
    TreeNode,
    build_tree,
    flatten_tree,
    parse_segments,
)


class TestParseSegments:
    """Tests for parse_segments function."""

    def test_simple_single_segment(self):
        """Single word without underscores."""
        assert parse_segments("Motor") == [("Motor", None)]

    def test_single_underscore_splits(self):
        """Single underscore splits into segments."""
        assert parse_segments("Motor_Speed") == [("Motor", None), ("Speed", None)]

    def test_multiple_underscores(self):
        """Multiple underscores create multiple segments."""
        assert parse_segments("Admin_Alarm_Reset") == [
            ("Admin", None),
            ("Alarm", None),
            ("Reset", None),
        ]

    def test_array_detection_trailing_number(self):
        """Trailing numbers on alpha segments are detected as array indices."""
        assert parse_segments("Motor1") == [("Motor", 1)]
        assert parse_segments("Motor1_Speed") == [("Motor", 1), ("Speed", None)]
        assert parse_segments("Pump2_Flow_Rate") == [
            ("Pump", 2),
            ("Flow", None),
            ("Rate", None),
        ]

    def test_pure_number_not_array(self):
        """Pure numeric segments are not treated as arrays."""
        assert parse_segments("Zone_1_Temp") == [
            ("Zone", None),
            ("1", None),
            ("Temp", None),
        ]

    def test_double_underscore_preserves_leading_underscore(self):
        """Double underscore splits but preserves leading underscore on next segment."""
        assert parse_segments("Modbus__x") == [("Modbus", None), ("_x", None)]
        assert parse_segments("Test__Value") == [("Test", None), ("_Value", None)]

    def test_double_underscore_mid_string(self):
        """Double underscore in the middle of a longer nickname."""
        assert parse_segments("Test__Value_End") == [
            ("Test", None),
            ("_Value", None),
            ("End", None),
        ]

    def test_triple_underscore(self):
        """Triple underscore creates segment with leading underscore."""
        # ___ becomes _<placeholder>_ after replace, splits to ["", "_", ""]
        # Empty segments are skipped, so we get just ["_"]
        assert parse_segments("A___B") == [("A", None), ("_", None), ("B", None)]

    def test_leading_underscore(self):
        """Leading underscore is skipped (empty first segment)."""
        assert parse_segments("_Motor") == [("Motor", None)]

    def test_trailing_underscore(self):
        """Trailing underscore is skipped (empty last segment)."""
        assert parse_segments("Motor_") == [("Motor", None)]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert parse_segments("") == []

    def test_only_underscores(self):
        """String of only underscores returns empty list."""
        assert parse_segments("_") == []
        assert parse_segments("__") == [("_", None)]  # Double underscore preserves one
        assert parse_segments("___") == [("_", None)]


class TestBuildTree:
    """Tests for build_tree function."""

    def test_empty_entries(self):
        """Empty entries list creates empty tree."""
        root = build_tree([])
        assert root.children == {}
        assert root.child_order == []

    def test_single_entry(self):
        """Single entry creates simple tree."""
        entries = [("X", 1, "Motor", 1001)]
        root = build_tree(entries)

        assert "Motor" in root.children
        motor_node = root.children["Motor"]
        assert motor_node.leaf == ("X", 1, 1001)

    def test_nested_entries(self):
        """Nested entries create proper tree structure."""
        entries = [("X", 1, "Motor_Speed", 1001)]
        root = build_tree(entries)

        assert "Motor" in root.children
        motor_node = root.children["Motor"]
        assert motor_node.leaf is None
        assert "Speed" in motor_node.children
        speed_node = motor_node.children["Speed"]
        assert speed_node.leaf == ("X", 1, 1001)

    def test_shared_prefix(self):
        """Entries with shared prefix share parent nodes."""
        entries = [
            ("X", 1, "Motor_Speed", 1001),
            ("X", 2, "Motor_Temp", 1002),
        ]
        root = build_tree(entries)

        assert "Motor" in root.children
        motor_node = root.children["Motor"]
        assert "Speed" in motor_node.children
        assert "Temp" in motor_node.children
        assert motor_node.child_order == ["Speed", "Temp"]  # Insertion order

    def test_array_indices(self):
        """Array indices create proper structure."""
        entries = [
            ("X", 1, "Motor1_Speed", 1001),
            ("X", 2, "Motor2_Speed", 1002),
        ]
        root = build_tree(entries)

        assert "Motor" in root.children
        motor_node = root.children["Motor"]
        assert motor_node.is_array is True
        assert "1" in motor_node.children
        assert "2" in motor_node.children

    def test_insertion_order_preserved(self):
        """Child order reflects insertion order."""
        entries = [
            ("X", 1, "Zebra", 1001),
            ("X", 2, "Alpha", 1002),
            ("X", 3, "Middle", 1003),
        ]
        root = build_tree(entries)

        assert root.child_order == ["Zebra", "Alpha", "Middle"]

    def test_empty_nickname_skipped(self):
        """Empty nicknames are skipped."""
        entries = [
            ("X", 1, "", 1001),
            ("X", 2, "Motor", 1002),
        ]
        root = build_tree(entries)

        assert "Motor" in root.children
        assert len(root.children) == 1


class TestFlattenTree:
    """Tests for flatten_tree function."""

    def test_empty_tree(self):
        """Empty tree returns empty list."""
        root = TreeNode()
        items = flatten_tree(root)
        assert items == []

    def test_single_leaf(self):
        """Single leaf node."""
        entries = [("X", 1, "Motor", 1001)]
        root = build_tree(entries)
        items = flatten_tree(root)

        assert len(items) == 1
        assert items[0].text == "Motor"
        assert items[0].depth == 0
        assert items[0].leaf == ("X", 1)
        assert items[0].has_children is False

    def test_parent_with_children(self):
        """Parent node with multiple children."""
        entries = [
            ("X", 1, "Motor_Speed", 1001),
            ("X", 2, "Motor_Temp", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Motor is a parent (collapsed path doesn't apply here since 2 children)
        assert items[0].text == "Motor"
        assert items[0].has_children is True
        assert items[0].depth == 0

        # Children
        assert items[1].text == "Speed"
        assert items[1].depth == 1
        assert items[2].text == "Temp"
        assert items[2].depth == 1

    def test_single_child_collapse(self):
        """Single-child chains are collapsed."""
        entries = [("X", 1, "Timer_Ts", 1001)]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Should collapse to "Timer Ts" as single leaf
        assert len(items) == 1
        assert items[0].text == "Timer Ts"

    def test_array_display(self):
        """Array nodes show [min-max] suffix."""
        entries = [
            ("X", 1, "Motor1_Speed", 1001),
            ("X", 2, "Motor2_Speed", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Find the Motor[1-2] node
        motor_item = next(i for i in items if "Motor" in i.text and "[" in i.text)
        assert motor_item.text == "Motor[1-2]"

    def test_array_index_collapse(self):
        """Array indices with single leaf child are collapsed."""
        entries = [
            ("X", 1, "Setpoint1_Reached", 1001),
            ("X", 2, "Setpoint2_Reached", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Should have Setpoint[1-2] parent with "1 Reached", "2 Reached" children
        texts = [i.text for i in items]
        assert "Setpoint[1-2]" in texts
        assert "1 Reached" in texts
        assert "2 Reached" in texts

    def test_sort_alphabetically_false(self):
        """Without alphabetical sort, insertion order is preserved."""
        entries = [
            ("X", 1, "Zebra", 1001),
            ("X", 2, "Alpha", 1002),
            ("X", 3, "Middle", 1003),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = [i.text for i in items]
        assert texts == ["Zebra", "Alpha", "Middle"]


class TestDoubleUnderscoreIntegration:
    """Integration tests for double underscore handling."""

    def test_double_underscore_separate_from_single(self):
        """Double underscore creates different tree path than single."""
        entries = [
            ("C", 1, "Modbus_x", 1001),  # Modbus -> x
            ("DS", 533, "Modbus__x", 2001),  # Modbus -> _x
        ]
        root = build_tree(entries)

        modbus = root.children["Modbus"]
        assert "x" in modbus.children
        assert "_x" in modbus.children
        assert modbus.child_order == ["x", "_x"]
