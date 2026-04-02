"""Tests for nav_window.block_logic tree building."""

from pyclickplc.blocks import BlockRange

from clicknick.models.address_row import AddressRow
from clicknick.views.nav_window.block_logic import build_block_tree


def _make_rows(addresses: list[tuple[str, int]]) -> list[AddressRow]:
    return [
        AddressRow(memory_type=memory_type, address=address) for memory_type, address in addresses
    ]


class TestBuildBlockTree:
    def test_non_udt_and_named_array_stay_flat(self):
        rows = _make_rows([("X", 1), ("X", 2)])
        ranges = [
            BlockRange(0, 0, "Simple", None, "X"),
            BlockRange(1, 1, "Base:named_array(2,3)", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert [node.text for node in nodes] == [
            f"Simple ({rows[0].display_address})",
            f"Base:named_array(2,3) ({rows[1].display_address})",
        ]
        assert all(not node.children for node in nodes)

    def test_udt_names_group_under_base_parent(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3)])
        ranges = [
            BlockRange(0, 0, "Alarm.id", None, "X"),
            BlockRange(1, 1, "Alarm.On", None, "X"),
            BlockRange(2, 2, "Pump", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert len(nodes) == 2
        alarm = nodes[0]
        assert alarm.is_group
        assert alarm.text == "Alarm"
        assert [child.text for child in alarm.children] == [
            f"id ({rows[0].display_address})",
            f"On ({rows[1].display_address})",
        ]
        assert alarm.addresses == (("X", 1), ("X", 2))

        pump = nodes[1]
        assert not pump.is_group
        assert pump.text == f"Pump ({rows[2].display_address})"

    def test_udt_names_with_metadata_group_under_base_parent(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3), ("X", 4)])
        ranges = [
            BlockRange(0, 0, "Parent.Childs", None, "X"),
            BlockRange(1, 1, "Parent.Clothes:meta", None, "X"),
            BlockRange(2, 2, "Parent.Cars", None, "X"),
            BlockRange(3, 3, "Pump", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert len(nodes) == 2
        parent = nodes[0]
        assert parent.is_group
        assert parent.text == "Parent"
        assert [child.text for child in parent.children] == [
            f"Childs ({rows[0].display_address})",
            f"Clothes:meta ({rows[1].display_address})",
            f"Cars ({rows[2].display_address})",
        ]

        pump = nodes[1]
        assert not pump.is_group
        assert pump.text == f"Pump ({rows[3].display_address})"

    def test_udt_names_with_space_flags_group_under_base_parent(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3), ("X", 4)])
        ranges = [
            BlockRange(0, 0, "Custom.Childs", None, "X"),
            BlockRange(1, 1, "Custom.TasksStatus READONLY", None, "X"),
            BlockRange(2, 2, "Custom.Cars", None, "X"),
            BlockRange(3, 3, "Pump", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert len(nodes) == 2
        custom = nodes[0]
        assert custom.is_group
        assert custom.text == "Custom"
        assert [child.text for child in custom.children] == [
            f"Childs ({rows[0].display_address})",
            f"TasksStatus READONLY ({rows[1].display_address})",
            f"Cars ({rows[2].display_address})",
        ]

        pump = nodes[1]
        assert not pump.is_group
        assert pump.text == f"Pump ({rows[3].display_address})"

    def test_unsorted_top_level_and_child_order_follow_first_occurrence(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3), ("X", 4), ("X", 5)])
        ranges = [
            BlockRange(0, 0, "FlatA", None, "X"),
            BlockRange(1, 1, "B.z", None, "X"),
            BlockRange(2, 2, "FlatB", None, "X"),
            BlockRange(3, 3, "B.a", None, "X"),
            BlockRange(4, 4, "A.x", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert [node.text for node in nodes] == [
            f"FlatA ({rows[0].display_address})",
            "B",
            f"FlatB ({rows[2].display_address})",
            "A",
        ]
        b_children = [child.text for child in nodes[1].children]
        assert b_children == [
            f"z ({rows[1].display_address})",
            f"a ({rows[3].display_address})",
        ]

    def test_sorted_mode_sorts_top_level_and_children(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3), ("X", 4), ("X", 5)])
        ranges = [
            BlockRange(0, 0, "Beta.z", None, "X"),
            BlockRange(1, 1, "Beta.a", None, "X"),
            BlockRange(2, 2, "Alpha.x", None, "X"),
            BlockRange(3, 3, "Zulu", None, "X"),
            BlockRange(4, 4, "Echo", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=True)

        assert [node.text for node in nodes] == [
            "Alpha",
            "Beta",
            f"Echo ({rows[4].display_address})",
            f"Zulu ({rows[3].display_address})",
        ]
        beta = nodes[1]
        assert [child.text for child in beta.children] == [
            f"a ({rows[1].display_address})",
            f"z ({rows[0].display_address})",
        ]

    def test_duplicate_udt_fields_keep_individual_children(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3)])
        ranges = [
            BlockRange(0, 0, "Alarm.id", None, "X"),
            BlockRange(1, 1, "Alarm.id", None, "X"),
            BlockRange(2, 2, "Alarm.On", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert len(nodes) == 1
        alarm = nodes[0]
        assert [child.text for child in alarm.children] == [
            f"id ({rows[0].display_address})",
            f"id ({rows[1].display_address})",
            f"On ({rows[2].display_address})",
        ]
        assert alarm.children[0].addresses == (("X", 1),)
        assert alarm.children[1].addresses == (("X", 2),)

    def test_parent_aggregation_dedupes_addresses_in_child_order(self):
        rows = _make_rows([("X", 1), ("X", 2), ("X", 3)])
        ranges = [
            BlockRange(0, 1, "Alarm.id", None, "X"),
            BlockRange(1, 2, "Alarm.On", None, "X"),
        ]

        nodes = build_block_tree(ranges, rows, sort_alphabetically=False)

        assert len(nodes) == 1
        alarm = nodes[0]
        assert alarm.addresses == (("X", 1), ("X", 2), ("X", 3))
        assert alarm.children[0].addresses == (("X", 1), ("X", 2))
        assert alarm.children[1].addresses == (("X", 2), ("X", 3))
