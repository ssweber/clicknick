"""Tests for outline_logic.py - tree building and flattening for address outline."""

from clicknick.views.nav_window.outline_logic import (
    DisplayItem,
    TreeNode,
    build_tree,
    flatten_tree,
    parse_segments,
)


def flatten_to_tuples(items: list[DisplayItem], depth: int = 0) -> list[tuple[str, int]]:
    """Flatten tree to (text, depth) tuples for easier testing."""
    result = []
    for item in items:
        result.append((item.text, depth))
        result.extend(flatten_to_tuples(item.children, depth + 1))
    return result


def get_all_texts(items: list[DisplayItem]) -> list[str]:
    """Get all text values from the tree, preserving pre-order traversal."""
    result = []
    for item in items:
        result.append(item.text)
        result.extend(get_all_texts(item.children))
    return result


def find_item(items: list[DisplayItem], predicate) -> DisplayItem | None:
    """Find an item matching predicate in the tree."""
    for item in items:
        if predicate(item):
            return item
        if found := find_item(item.children, predicate):
            return found
    return None


class TestLeadingUnderscorePreservation:
    """Tests for preserving leading underscores in nicknames."""

    def test_leading_underscore_preserved_simple(self):
        """Leading underscore should be preserved, not stripped."""
        # _IO1 should parse to [("_IO", 1)] not [("IO", 1)]
        assert parse_segments("_IO1") == [("_IO", 1)]

    def test_leading_underscore_preserved_with_children(self):
        """Leading underscore preserved when there are child segments."""
        assert parse_segments("_IO1_Status") == [("_IO", 1), ("Status", None)]

    def test_leading_underscore_no_array(self):
        """Leading underscore without array index."""
        assert parse_segments("_Config") == [("_Config", None)]

    def test_leading_underscore_in_tree(self):
        """Leading underscore tags should show with underscore in tree."""
        entries = [
            ("X", 1, "_IO1_Status", 1001),
            ("X", 2, "_IO2_Status", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        # Should have _IO[1-2] not IO[1-2]
        assert "_IO[1-2]" in texts
        assert "IO[1-2]" not in texts


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

    def test_double_underscore_creates_underscore_node(self):
        """Double underscore creates an intermediate _ node."""
        assert parse_segments("Modbus__x") == [("Modbus", None), ("_", None), ("x", None)]
        assert parse_segments("Test__Value") == [("Test", None), ("_", None), ("Value", None)]
        assert parse_segments("Mtr1__Debounce") == [("Mtr", 1), ("_", None), ("Debounce", None)]

    def test_double_underscore_mid_string(self):
        """Double underscore in the middle of a longer nickname."""
        assert parse_segments("Test__Value_End") == [
            ("Test", None),
            ("_", None),
            ("Value", None),
            ("End", None),
        ]

    def test_triple_underscore(self):
        """Triple underscore is __ + _, creating one _ node then split."""
        # ___ = __ + _ so we get one _ segment between A and B
        assert parse_segments("A___B") == [("A", None), ("_", None), ("B", None)]

    def test_quadruple_underscore(self):
        """Quadruple underscore is __ + __, creating two _ nodes."""
        assert parse_segments("A____B") == [("A", None), ("_", None), ("_", None), ("B", None)]

    def test_leading_underscore(self):
        """Leading underscore is preserved (prefixed to first segment)."""
        assert parse_segments("_Motor") == [("_Motor", None)]

    def test_trailing_underscore(self):
        """Trailing underscore is skipped (empty last segment)."""
        assert parse_segments("Motor_") == [("Motor", None)]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert parse_segments("") == []

    def test_only_underscores(self):
        """String of only underscores."""
        assert parse_segments("_") == []
        assert parse_segments("__") == [("_", None)]  # Double underscore creates _ node
        assert parse_segments("___") == [("_", None)]  # __ + _ = one _ node
        assert parse_segments("____") == [("_", None), ("_", None)]  # __ + __ = two _ nodes


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

        # Motor is a parent at top level
        assert len(items) == 1
        motor = items[0]
        assert motor.text == "Motor"
        assert motor.has_children is True

        # Children are nested
        assert len(motor.children) == 2
        child_texts = [c.text for c in motor.children]
        assert "Speed" in child_texts
        assert "Temp" in child_texts

    def test_single_child_collapse(self):
        """Single-child chains are collapsed."""
        entries = [("X", 1, "Timer_Ts", 1001)]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Should collapse to "Timer_Ts" as single leaf
        assert len(items) == 1
        assert items[0].text == "Timer_Ts"

    def test_array_display(self):
        """Array nodes show [min-max] suffix."""
        entries = [
            ("X", 1, "Motor1_Speed", 1001),
            ("X", 2, "Motor2_Speed", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Find the Motor[1-2] node
        motor_item = find_item(items, lambda i: "Motor" in i.text and "[" in i.text)
        assert motor_item is not None
        assert motor_item.text == "Motor[1-2]"

    def test_array_index_collapse(self):
        """Array indices with single leaf child are collapsed."""
        entries = [
            ("X", 1, "Setpoint1_Reached", 1001),
            ("X", 2, "Setpoint2_Reached", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        assert "Setpoint[1-2]" in texts
        assert "1_Reached" in texts
        assert "2_Reached" in texts

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

    def test_double_underscore_creates_underscore_branch(self):
        """Double underscore creates _ intermediate node in tree."""
        entries = [
            ("C", 1, "Modbus_x", 1001),  # Modbus -> x
            ("DS", 533, "Modbus__x", 2001),  # Modbus -> _ -> x
        ]
        root = build_tree(entries)

        modbus = root.children["Modbus"]
        assert "x" in modbus.children  # From Modbus_x
        assert "_" in modbus.children  # From Modbus__x
        assert "x" in modbus.children["_"].children  # The x under _
        assert modbus.child_order == ["x", "_"]

    def test_double_underscore_groups_items(self):
        """Double underscore groups related items under _ node."""
        entries = [
            ("C", 1, "Mtr1_Speed", 1001),
            ("C", 2, "Mtr1_Run", 1002),
            ("C", 3, "Mtr1_Error", 1003),
            ("C", 4, "Mtr1__Debounce", 1004),
            ("C", 5, "Mtr1__DebounceTms", 1005),
        ]
        root = build_tree(entries)

        # Mtr is array with child "1"
        mtr = root.children["Mtr"]
        assert mtr.is_array
        mtr1 = mtr.children["1"]

        # Regular children: Speed, Run, Error
        assert "Speed" in mtr1.children
        assert "Run" in mtr1.children
        assert "Error" in mtr1.children

        # Underscore node with Debounce and DebounceTms
        assert "_" in mtr1.children
        underscore_node = mtr1.children["_"]
        assert "Debounce" in underscore_node.children
        assert "DebounceTms" in underscore_node.children

    def test_underscore_nodes_appear_last_in_flatten(self):
        """Underscore nodes appear after regular siblings when flattened."""
        entries = [
            ("C", 1, "Mtr1_Speed", 1001),
            ("C", 2, "Mtr1__Private", 1002),  # _ node created
            ("C", 3, "Mtr1_Run", 1003),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        # Speed and Run should come before _ Private
        speed_idx = texts.index("Speed")
        run_idx = texts.index("Run")
        private_idx = texts.index("__Private")

        assert speed_idx < private_idx
        assert run_idx < private_idx


class TestTimerInterleaving:
    """Tests for T/TD and CT/CTD interleaving."""

    def test_t_td_interleaved(self):
        """T and TD entries are interleaved by address."""
        entries = [
            ("T", 1, "Timer1_Run", 1001),
            ("T", 2, "Timer2_Run", 1002),
            ("TD", 1, "Timer1_Time", 2001),
            ("TD", 2, "Timer2_Time", 2002),
        ]
        root = build_tree(entries)

        # Check tree structure: Timer -> 1 -> Run, Time (in that order)
        timer = root.children["Timer"]
        node1 = timer.children["1"]
        # T1 inserted first, then TD1 interleaved right after
        assert node1.child_order == ["Run", "Time"]

        node2 = timer.children["2"]
        assert node2.child_order == ["Run", "Time"]

    def test_ct_ctd_interleaved(self):
        """CT and CTD entries are interleaved by address."""
        entries = [
            ("CT", 1, "Counter1_Val", 1001),
            ("CT", 2, "Counter2_Val", 1002),
            ("CTD", 1, "Counter1_Done", 2001),
            ("CTD", 2, "Counter2_Done", 2002),
        ]
        root = build_tree(entries)

        counter = root.children["Counter"]
        node1 = counter.children["1"]
        assert node1.child_order == ["Val", "Done"]

    def test_td_without_t_appears_at_end(self):
        """TD entries without corresponding T appear at end."""
        entries = [
            ("T", 1, "Timer1_Run", 1001),
            ("TD", 1, "Timer1_Time", 2001),
            ("TD", 2, "Timer2_Only", 2002),  # No T2
        ]
        root = build_tree(entries)

        timer = root.children["Timer"]
        # Both 1 and 2 exist
        assert "1" in timer.children
        assert "2" in timer.children

        # Timer1 has interleaved T and TD
        node1 = timer.children["1"]
        assert node1.child_order == ["Run", "Time"]

        # Timer2 only has TD entry
        node2 = timer.children["2"]
        assert "Only" in node2.children

    def test_other_memory_types_unaffected(self):
        """Non-timer memory types preserve original order."""
        entries = [
            ("C", 1, "Pump_Run", 1001),
            ("C", 2, "Pump_Stop", 1002),
            ("DS", 1, "Pump_Speed", 2001),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # All under Pump parent
        assert len(items) == 1
        pump = items[0]
        assert pump.text == "Pump"
        child_texts = [c.text for c in pump.children]
        assert child_texts == ["Run", "Stop", "Speed"]


class TestArrayChildSingleChainCollapse:
    """Tests for collapsing array children that have single-child chains.

    When array indices have children without siblings, the entire chain
    should collapse into a single display item like "1_ResumeFromPwrLoss"
    rather than showing a nested structure.
    """

    def test_array_children_collapse_single_chain(self):
        """Array children with single-child chains collapse entirely.

        A_P1_ResumeFromPwrLoss and A_P2_PwrLossDebounce_Ts should show:
        - A_P[1-2]
          - 1_ResumeFromPwrLoss
          - 2_PwrLossDebounce_Ts

        NOT:
        - A_P[1-2]
          - 1
            - ResumeFromPwrLoss
          - 2
            - PwrLossDebounce
              - Ts
        """
        entries = [
            ("C", 1, "A_P1_ResumeFromPwrLoss", 1001),
            ("C", 2, "A_P2_PwrLossDebounce_Ts", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        # Both should be collapsed into single items
        assert "1_ResumeFromPwrLoss" in texts
        assert "2_PwrLossDebounce_Ts" in texts

        # Should NOT have separate nodes for intermediate segments
        assert "PwrLossDebounce" not in texts
        assert "ResumeFromPwrLoss" not in texts  # Should only appear as "1_ResumeFromPwrLoss"

    def test_array_children_with_shared_siblings_not_collapsed(self):
        """Array children with shared siblings should NOT collapse.

        If Motor1_Speed and Motor1_Temp both exist, they share the "1" parent,
        so we should see (single-element array collapses):
        - Motor1
          - Speed
          - Temp

        NOT collapsed to Motor1_Speed, Motor1_Temp at same level.
        """
        entries = [
            ("C", 1, "Motor1_Speed", 1001),
            ("C", 2, "Motor1_Temp", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Single-element array collapses, so Motor1 is the parent
        texts = get_all_texts(items)
        assert "Motor1" in texts
        assert "Speed" in texts
        assert "Temp" in texts

    def test_array_children_different_depths_collapse(self):
        """Array children with different depths but no siblings collapse."""
        entries = [
            ("C", 1, "Pump1_Active", 1001),  # Shallow: Pump -> 1 -> Active
            ("C", 2, "Pump2_Status_Error", 1002),  # Deeper: Pump -> 2 -> Status -> Error
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        # Both should collapse to leaf form
        assert "1_Active" in texts
        assert "2_Status_Error" in texts


class TestSingleElementArrayCollapse:
    """Tests for collapsing single-element arrays."""

    def test_single_element_array_flattens(self):
        """Single-element array collapses number into name."""
        entries = [
            ("DS", 1, "Mold_A_Prod1_DayProcCt", 1001),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Should flatten to single item: Mold_A_Prod1_DayProcCt
        assert len(items) == 1
        assert items[0].text == "Mold_A_Prod1_DayProcCt"

    def test_multi_element_array_shows_brackets(self):
        """Multi-element array still shows [min-max] brackets."""
        entries = [
            ("DS", 1, "Mold_A_Prod1_DayProcCt", 1001),
            ("DS", 2, "Mold_A_Prod2_DayProcCt", 1002),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        # Should have Mold_A_Prod[1-2] parent with children
        assert any("[1-2]" in t for t in texts)

    def test_single_element_with_non_array_siblings(self):
        """Single-element array with non-array siblings keeps brackets.

        When a node has both array children (1, 2, ...) and non-array children
        (Status, etc.), they are shown as separate entries at the same level.
        """
        entries = [
            ("DS", 1, "Pump_Status", 1001),
            ("DS", 2, "Pump1_Speed", 1002),  # Only one Pump#
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # All top-level items
        top_texts = [i.text for i in items]
        # Array portion shown with brackets (even single element, due to mixed content)
        assert "Pump[1]" in top_texts
        # Non-array sibling shown with full prefix at same level
        assert "Pump_Status" in top_texts

        # Check the array child
        pump_array = find_item(items, lambda i: i.text == "Pump[1]")
        assert pump_array is not None
        assert len(pump_array.children) == 1
        assert pump_array.children[0].text == "1_Speed"

    def test_single_element_no_siblings_collapses(self):
        """Single-element array with no siblings collapses."""
        entries = [
            ("DS", 1, "Pump1_Speed", 1001),  # Only one Pump#, no other Pump_ siblings
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Should collapse entirely
        assert len(items) == 1
        assert items[0].text == "Pump1_Speed"


class TestMixedArrayContent:
    """Tests for Rule 4: arrays with leaf values and non-numeric siblings."""

    def test_array_with_leaf_and_numeric_children(self):
        """Array node that is also a leaf emits both separately."""
        entries = [
            ("C", 1, "HMI_Alarm", 1001),  # Base name is an address
            ("C", 2, "HMI_Alarm1_id", 1002),  # Array item
            ("C", 3, "HMI_Alarm2_id", 1003),  # Array item
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        # The leaf should appear as its own item
        assert "HMI_Alarm" in texts
        # The array should be separate (no leaf attached)
        assert "HMI_Alarm[1-2]" in texts
        # Array children
        assert "1_id" in texts
        assert "2_id" in texts

        # Verify the leaf and array are separate items at top level
        top_texts = [i.text for i in items]
        assert "HMI_Alarm" in top_texts
        assert "HMI_Alarm[1-2]" in top_texts

        alarm_leaf = find_item(items, lambda i: i.text == "HMI_Alarm")
        assert alarm_leaf is not None
        assert alarm_leaf.leaf == ("C", 1)
        assert alarm_leaf.has_children is False

        array_item = find_item(items, lambda i: i.text == "HMI_Alarm[1-2]")
        assert array_item is not None
        assert array_item.leaf is None
        assert array_item.has_children is True

    def test_array_with_non_numeric_siblings(self):
        """Non-numeric siblings of array indices shown separately."""
        entries = [
            ("C", 1, "HMI_Alarm", 1001),
            ("C", 2, "HMI_Alarm1_id", 1002),
            ("C", 3, "HMI_Alarm2_id", 1003),
            ("C", 4, "HMI_Alarm_Status", 1004),  # Non-numeric sibling
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # All should be at top level
        top_texts = [i.text for i in items]
        assert "HMI_Alarm" in top_texts
        assert "HMI_Alarm[1-2]" in top_texts
        assert "HMI_Alarm_Status" in top_texts

    def test_complex_mixed_array(self):
        """Complex case from docstring example."""
        entries = [
            ("C", 1, "Command_Alarm", 1001),
            ("C", 2, "Command_Alarm1_id", 1002),
            ("C", 3, "Command_Alarm2_id", 1003),
            ("C", 4, "Command_Alarm_Status", 1004),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        texts = get_all_texts(items)
        assert "Command_Alarm" in texts
        assert "Command_Alarm[1-2]" in texts
        assert "1_id" in texts
        assert "2_id" in texts
        assert "Command_Alarm_Status" in texts


class TestDisplayItemMethods:
    """Tests for DisplayItem's tree methods."""

    def test_get_all_leaves_single(self):
        """get_all_leaves on a single leaf returns just that leaf."""
        entries = [("X", 1, "Motor", 100)]
        root = build_tree(entries)
        items = flatten_tree(root)

        assert len(items) == 1
        leaves = items[0].get_all_leaves()
        assert leaves == [("X", 1)]

    def test_get_all_leaves_nested(self):
        """get_all_leaves collects all leaves under a parent."""
        entries = [
            ("X", 1, "Motor1_Speed", 100),
            ("X", 2, "Motor2_Speed", 200),
            ("X", 3, "Motor1_Run", 300),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Find the Motor[1-2] parent
        motor_array = find_item(items, lambda i: "Motor" in i.text and i.has_children)
        assert motor_array is not None

        leaves = motor_array.get_all_leaves()
        assert len(leaves) == 3
        assert ("X", 1) in leaves
        assert ("X", 2) in leaves
        assert ("X", 3) in leaves

    def test_iter_preorder_single(self):
        """iter_preorder on a single item yields (item, 0)."""
        entries = [("X", 1, "Motor", 100)]
        root = build_tree(entries)
        items = flatten_tree(root)

        preorder = list(items[0].iter_preorder())
        assert len(preorder) == 1
        assert preorder[0] == (items[0], 0)

    def test_iter_preorder_nested(self):
        """iter_preorder yields items with correct depths."""
        entries = [
            ("X", 1, "Motor1_Speed", 100),
            ("X", 2, "Motor2_Speed", 200),
        ]
        root = build_tree(entries)
        items = flatten_tree(root)

        # Should have Motor[1-2] with children
        assert len(items) == 1
        root_item = items[0]

        preorder = list(root_item.iter_preorder())
        # Root at depth 0, two children at depth 1
        assert len(preorder) == 3
        assert preorder[0][1] == 0  # root depth
        assert preorder[1][1] == 1  # child depth
        assert preorder[2][1] == 1  # child depth

    def test_has_children_property(self):
        """has_children returns True only when children list is non-empty."""
        leaf = DisplayItem(text="test", leaf=("X", 1))
        assert leaf.has_children is False

        parent = DisplayItem(text="parent", children=[leaf])
        assert parent.has_children is True

    def test_is_leaf_property(self):
        """is_leaf returns True only when leaf data is present."""
        non_leaf = DisplayItem(text="parent")
        assert non_leaf.is_leaf is False

        leaf = DisplayItem(text="test", leaf=("X", 1))
        assert leaf.is_leaf is True
