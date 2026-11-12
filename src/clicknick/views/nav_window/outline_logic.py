"""Tree building logic for address outline.

Displays a hierarchical treeview of tag nicknames, parsed by underscore segments
with array detection. Allows navigation to addresses via double-click.

Display Rules:
--------------
1. Nicknames are split by single underscore into path segments.
   Double underscores create an intermediate "_" node for grouping related items.
   Example: "Admin_Alarm_Reset" -> Admin -> Alarm -> Reset
   Example: "Mtr1__Debounce" -> Mtr[1] -> 1 -> _ -> Debounce

2. Trailing numbers on segments are detected as array indices, shown with [min-max].
   An index keeps its digits as written ("Pump01" shows 01, apart from "Pump1") and
   indices sort by value.
   Single-element arrays (only one number, no siblings) collapse the number into the name.
   Example: "Motor1_Speed", "Motor2_Speed" -> Motor[1-2] -> 1 -> Speed
   Example: "Prod1_Count" (alone) -> Prod1_Count (no brackets)

3. Array indices with a single leaf child are collapsed into "#_Name" format.
   Example: "Setpoint1_Reached", "Setpoint2_Reached" -> Setpoint[1-2] -> 1_Reached, 2_Reached

4. If both array items (Motor1_X) and non-array items (Motor_Status) share
   the same base name, they are pulled together under the same parent node
   but kept as separate entries, ordered by first occurrence of each type.
   Example: Command_Alarm, Admin_Tag1, Command_Alarm1_id, Command_Alarm2_id, Admin_Tag2, Command_Alarm_Status ->
   + Command
       - Alarm
       + Alarm[1-2]
           - 1_id
           - 2_id
       - Alarm_Status

5. Single-child nodes are collapsed with underscore "_".
   Example: "Timer_Ts" (alone) -> Timer_Ts

6. Underscore nodes (from double underscores) appear last among siblings.
   Example: Mtr1_Speed, Mtr1_Run, Mtr1__Debug -> Speed, Run, then __Debug

7. T/TD and CT/CTD entries are interleaved by address number.
   Example: T1, T2, TD1, TD2 -> T1, TD1, T2, TD2 (in tree insertion order)

8. SC and SD memory types are displayed as flat lists at the bottom of the tree
   without any structure parsing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

_ARRAY_PATTERN = re.compile(r"^(_?[A-Za-z]+)(\d+)$")

MEMORY_TYPE_ORDER = [
    "X",
    "Y",
    "C",
    "T",
    "TD",
    "CT",
    "CTD",
    "DS",
    "DD",
    "DH",
    "DF",
    "XD",
    "YD",
    "TXT",
    "SC",
    "SD",
]

FLAT_MEMORY_TYPES = frozenset({"SC", "SD"})


@dataclass
class TreeNode:
    """A node in the nickname tree (intermediate build structure).

    A node is one nickname segment: a name, an array index (``is_index``) or a "_"
    gap from a double underscore. Nodes are keyed by the segment as spelled, so
    spellings that differ ("Tank_1_Pump" and "Tank1_Pump", "A__B" and "A___B",
    "Pump_" and "Pump") are never the same node. For an ordinary name the key is
    the name.

    ``seg_start`` and ``path_end`` are the nickname text before this node's own
    segment and through it.
    """

    children: dict[str, TreeNode] = field(default_factory=dict)
    child_order: list[str] = field(default_factory=list)
    leaves: list[tuple[str, int, int]] = field(default_factory=list)  # (type, address, addr_key)
    is_array: bool = False
    is_index: bool = False
    has_gap: bool = False  # a child is a "_" gap
    name: str = ""
    seg_start: str = ""
    path_end: str = ""

    @property
    def leaf(self) -> tuple[str, int, int] | None:
        """The first address with this exact nickname."""
        return self.leaves[0] if self.leaves else None

    @property
    def is_gap(self) -> bool:
        """True for the "_" node of a double underscore."""
        return self.name == "_" and not self.is_index

    @property
    def child_start(self) -> str:
        """The nickname text every child's segment follows."""
        return self.path_end if self.is_gap else self.path_end + "_"

    def child_nodes(self) -> list[TreeNode]:
        """Children in insertion order."""
        return [self.children[k] for k in self.child_order]


@dataclass
class DisplayItem:
    """A display node with tree structure built-in."""

    text: str
    full_path: str = ""  # Path string for filtering (e.g., "Tank_1_Pump_")
    leaf: tuple[str, int] | None = None  # (memory_type, address) for leaf nodes
    addr_key: int | None = None
    children: list[DisplayItem] = field(default_factory=list)
    is_array: bool = False  # True if this node has array brackets in text
    base_text: str = ""  # Text without brackets (e.g., "Motor" from "Motor[1-2]")
    # Other addresses with the same nickname as ``leaf`` (a duplicate during edits)
    also_leaves: list[tuple[str, int]] = field(default_factory=list)
    # The nickname segment Rename changes: text before it, the segment, and whether
    # it is an array name (renamed ahead of its digits). Empty text: not renamable.
    rename_prefix: str = ""
    rename_text: str = ""
    rename_is_array: bool = False
    # Rename changes only this exact nickname (an item with nothing under it)
    rename_exact: bool = False

    @property
    def has_children(self) -> bool:
        """Check if this item has children."""
        return bool(self.children)

    @property
    def is_leaf(self) -> bool:
        """Check if this item is a leaf (has address data)."""
        return self.leaf is not None

    def iter_preorder(self, depth: int = 0) -> Iterator[tuple[DisplayItem, int]]:
        """Iterate tree in pre-order, yielding (item, depth) pairs."""
        yield self, depth
        for child in self.children:
            yield from child.iter_preorder(depth + 1)

    def get_all_leaves(self) -> list[tuple[str, int]]:
        """Collect all leaf addresses under this node (including self)."""
        leaves: list[tuple[str, int]] = []
        if self.leaf:
            leaves.append(self.leaf)
            leaves.extend(self.also_leaves)
        for child in self.children:
            leaves.extend(child.get_all_leaves())
        return leaves


def parse_segments(nickname: str) -> list[tuple[str, str | None]]:
    """Parse nickname into segments with optional array indices.

    Returns list of (name, index) tuples. Index is the digit string as written
    ("01" stays "01"), None for non-array segments.

    Single underscores split segments. Double underscores create an intermediate
    "_" node, grouping items that follow under a special underscore branch.
    Leading single underscores are preserved (prefixed to first segment).
    Example: "Motor1_Speed" -> [("Motor", "1"), ("Speed", None)]
    Example: "Mtr1__Debounce" -> [("Mtr", "1"), ("_", None), ("Debounce", None)]
    Example: "_IO1_Status" -> [("_IO", "1"), ("Status", None)]
    """
    # Replace __ with placeholder to mark where _ nodes should be inserted
    placeholder = "\x00"
    temp = nickname.replace("__", placeholder)

    # Check if we have a leading single underscore (after __ replacement)
    # This happens when original starts with single _ but not __
    has_leading_underscore = temp.startswith("_") and not nickname.startswith("__")

    segments: list[tuple[str, str | None]] = []
    first_segment_added = False
    for part in temp.split("_"):
        if not part:
            continue
        # Each placeholder in the part represents a _ segment
        subparts = part.split(placeholder)
        for i, subpart in enumerate(subparts):
            if i > 0:
                # This was preceded by __, so insert _ segment
                segments.append(("_", None))
            if not subpart:
                continue

            # Prepend underscore to first segment if original had leading _
            if has_leading_underscore and not first_segment_added:
                subpart = "_" + subpart

            first_segment_added = True

            if match := _ARRAY_PATTERN.match(subpart):
                segments.append((match.group(1), match.group(2)))
            else:
                segments.append((subpart, None))
    return segments


def _insert_path(
    root: TreeNode,
    nickname: str,
    segments: list[tuple[str, str | None]],
    memory_type: str,
    address: int,
    addr_key: int,
) -> None:
    """Insert a nickname's segments into the tree, tracking insertion order.

    A node's key is its segment as spelled: the name, plus a suffix when the
    separator before it or an underscore after it is not the usual one. The slices
    of the nickname a node records are cut only when the node is created.

    A segment sits in the nickname after its separator (zero or one "_"); a "_" gap
    is the "__" itself.
    """
    node = root
    ptr = 0  # where the next segment's separator starts
    last = len(segments) - 1
    prev_gap = True  # nothing before the first segment, or a gap, takes no separator
    for i, (name, index) in enumerate(segments):
        sep_start = ptr
        gap = name == "_" and index is None
        if gap:
            ptr += 2
            has_sep = False
            text_start = name_end = end = ptr
        else:
            has_sep = nickname.startswith("_", ptr) and not (ptr == 0 and name[0] == "_")
            text_start = ptr + has_sep
            name_end = text_start + len(name)
            end = name_end if index is None else name_end + len(index)
            ptr = end
        trailing = len(nickname) - end if i == last else 0
        name_trailing = trailing if index is None else 0

        key = "\x01" + name if name.isdigit() else name
        if name_trailing or (not gap and has_sep == prev_gap):
            # a separator where none is due, or none where one is, or a trailing "_"
            key = f"{key}\x00{int(has_sep)}{name_trailing}"
        prev_gap = gap
        child = node.children.get(key)
        if child is None:
            child = TreeNode(
                name=name,
                seg_start=nickname[: sep_start if gap else text_start],
                path_end=nickname[: (end if gap else name_end) + name_trailing],
            )
            node.children[key] = child
            node.child_order.append(key)
            if gap:
                node.has_gap = True
        node = child

        if index is not None:
            node.is_array = True
            index_key = f"{index}\x00{trailing}" if trailing else index
            child = node.children.get(index_key)
            if child is None:
                child = TreeNode(
                    name=index,
                    is_index=True,
                    seg_start=node.seg_start,
                    path_end=nickname[: end + trailing],
                )
                node.children[index_key] = child
                node.child_order.append(index_key)
            node = child

    node.leaves.append((memory_type, address, addr_key))


def _interleave_timer_entries(
    entries: list[tuple[str, int, str, int]],
) -> list[tuple[str, int, str, int]]:
    """Reorder entries to interleave T/TD and CT/CTD pairs by address.

    For each T address, the corresponding TD address follows immediately.
    Same for CT/CTD pairs. Other memory types are unaffected.

    Example: T1, T2, TD1, TD2 -> T1, TD1, T2, TD2
    """
    # Build lookup for TD and CTD entries by address
    td_by_addr: dict[int, tuple[str, int, str, int]] = {}
    ctd_by_addr: dict[int, tuple[str, int, str, int]] = {}

    result: list[tuple[str, int, str, int]] = []
    deferred_td: list[tuple[str, int, str, int]] = []
    deferred_ctd: list[tuple[str, int, str, int]] = []

    # First pass: collect TD and CTD entries
    for entry in entries:
        memory_type = entry[0]
        address = entry[1]
        if memory_type == "TD":
            td_by_addr[address] = entry
        elif memory_type == "CTD":
            ctd_by_addr[address] = entry

    # Second pass: build interleaved result
    seen_td: set[int] = set()
    seen_ctd: set[int] = set()

    for entry in entries:
        memory_type = entry[0]
        address = entry[1]

        if memory_type == "TD":
            # Will be inserted after corresponding T, or at end if no T
            if address not in seen_td:
                deferred_td.append(entry)
            continue
        elif memory_type == "CTD":
            # Will be inserted after corresponding CT, or at end if no CT
            if address not in seen_ctd:
                deferred_ctd.append(entry)
            continue

        result.append(entry)

        # If this is T, insert corresponding TD right after
        if memory_type == "T" and address in td_by_addr:
            result.append(td_by_addr[address])
            seen_td.add(address)
        # If this is CT, insert corresponding CTD right after
        elif memory_type == "CT" and address in ctd_by_addr:
            result.append(ctd_by_addr[address])
            seen_ctd.add(address)

    # Append any TD/CTD entries that didn't have a corresponding T/CT
    result.extend(deferred_td)
    result.extend(deferred_ctd)

    return result


def build_tree(entries: list[tuple[str, int, str, int]]) -> TreeNode:
    """Build tree structure from nickname entries.

    Args:
        entries: List of (memory_type, address, nickname, addr_key) tuples,
                 in the order they should appear.

    Returns:
        Root TreeNode containing the full tree structure.
    """
    # Interleave T/TD and CT/CTD pairs so related timers are adjacent
    entries = _interleave_timer_entries(entries)

    root = TreeNode()

    for memory_type, address, nickname, addr_key in entries:
        if not nickname:
            continue
        path = parse_segments(nickname)
        if not path:
            continue
        _insert_path(root, nickname, path, memory_type, address, addr_key)

    return root


def _extract_leaf_info(
    leaf: tuple[str, int, int] | None,
) -> tuple[tuple[str, int] | None, int | None]:
    """Extract (memory_type, address) tuple and addr_key from leaf data."""
    if leaf is None:
        return None, None
    memory_type, address, addr_key = leaf
    return (memory_type, address), addr_key


def _numeric_children(node: TreeNode) -> list[TreeNode]:
    """The array index children of a node, in numeric order (ties by digit string)."""
    if not node.is_array:
        return []
    return sorted(
        (c for c in node.child_nodes() if c.is_index), key=lambda c: (int(c.name), c.name)
    )


def _named_children(node: TreeNode) -> list[TreeNode]:
    """The children that are not array indices, "_" gaps last."""
    named = [c for c in node.child_nodes() if not c.is_index]
    if not node.has_gap:
        return named
    return [c for c in named if not c.is_gap] + [c for c in named if c.is_gap]


def _ordered_children(node: TreeNode) -> list[TreeNode]:
    """Children in display order: indices by value, "_" gaps last, the rest as inserted."""
    ordered = node.child_nodes()
    if node.is_array:
        indices = iter(_numeric_children(node))
        ordered = [next(indices) if c.is_index else c for c in ordered]
    if not node.has_gap:
        return ordered
    return [c for c in ordered if not c.is_gap] + [c for c in ordered if c.is_gap]


def _get_array_range(node: TreeNode) -> str:
    """Get the array range string for an array node's numeric children.

    Returns format like '[1-3]' for ranges or '[5]' for single items. Indices show
    their digits as written.
    """
    indices = _numeric_children(node)
    if not indices:
        return "[#]"  # fallback
    if len(indices) == 1:
        return f"[{indices[0].name}]"
    return f"[{indices[0].name}-{indices[-1].name}]"


def _make_item(
    text: str,
    node: TreeNode,
    children: list[DisplayItem] | None = None,
    *,
    array: bool = False,
) -> DisplayItem:
    """Create the DisplayItem for ``node``, whose own segment ends the item's text.

    Args:
        text: Display text (an array shows its [range])
        node: The node of the item's last nickname segment
        children: Child items
        array: True for an array name shown with its range: its path has no
            underscore after it, and Rename changes the name ahead of the digits
    """
    # An array name shown with its range is a folder: the name's own address (if any)
    # is a separate item
    leaf, addr_key = (None, None) if array else _extract_leaf_info(node.leaf)
    if array:
        full_path = node.path_end
    else:
        full_path = node.child_start if children else node.path_end
    return DisplayItem(
        text=text,
        full_path=full_path,
        leaf=leaf,
        addr_key=addr_key,
        children=children or [],
        is_array=array,
        base_text=text.split("[")[0] if array else "",
        also_leaves=[]
        if array or len(node.leaves) < 2
        else [(mt, a) for mt, a, _ in node.leaves[1:]],
        rename_prefix=node.seg_start,
        # A gap is not a name to rename
        rename_text="" if node.is_gap else node.path_end[len(node.seg_start) :],
        rename_is_array=array,
        # An item with nothing under it renames its own nickname, not those that
        # continue it (the array of the same name is another item)
        rename_exact=leaf is not None and not children,
    )


def _get_collapsible_leaf(node: TreeNode) -> TreeNode | None:
    """Check if an array index node should collapse with its single leaf child.

    Returns the child node if collapsible, None otherwise. An index with an address
    of its own does not collapse: that address would have no item.
    """
    if len(node.children) != 1 or node.leaves:
        return None
    child = node.child_nodes()[0]
    if child.leaf is not None and not child.children:
        return child
    return None


def _is_single_element_array(node: TreeNode) -> TreeNode | None:
    """Check if node is an array with exactly one numeric child and no others.

    Returns the index node if it should be collapsed, None otherwise.
    """
    if not node.is_array or len(node.children) != 1:
        return None
    only = node.child_nodes()[0]
    return only if only.is_index else None


def _has_mixed_array_content(node: TreeNode) -> bool:
    """Check if an array node has content that requires separate handling.

    Returns True if the node is an array AND has any of:
    - A leaf value (the base name is itself an address)
    - Non-numeric children (siblings to the array indices)
    """
    if not node.is_array:
        return False
    if node.leaf is not None:
        return True
    return any(not c.is_index for c in node.child_nodes())


def _flatten_mixed_array(name: str, node: TreeNode) -> list[DisplayItem]:
    """Flatten an array node with mixed content. Returns multiple items.

    ``name`` is the display text leading to the array name (a collapsed chain).
    """
    items: list[DisplayItem] = []

    # If array node itself is a leaf, emit that first
    if node.leaf is not None:
        items.append(_make_item(name, node))

    # Emit array portion with numeric children
    if numeric_children := _numeric_children(node):
        array_children: list[DisplayItem] = []
        for index_node in numeric_children:
            array_children.extend(_flatten_child_with_prefix(index_node.name, index_node))
        items.append(
            _make_item(f"{name}{_get_array_range(node)}", node, array_children, array=True)
        )

    # Emit non-numeric children collapsed with parent name
    for child in _named_children(node):
        items.extend(_flatten_child_with_prefix(f"{name}_{child.name}", child))

    return items


def _flatten_child_with_prefix(prefix: str, node: TreeNode) -> list[DisplayItem]:
    """Flatten a node, collapsing single-child chains. Returns list (usually 1 item).

    ``prefix`` is the display text for ``node``'s own segment.
    """
    current_path = [prefix]
    collapse_node = node
    array_chain = False  # the chain ends on an array name shown with its [range]

    # A node that is an array itself (the child of a mixed array) is shown as one
    if node.is_array and not _has_mixed_array_content(node):
        if index_node := _is_single_element_array(node):
            current_path[0] = f"{prefix}{index_node.name}"
            collapse_node = index_node
        else:
            current_path[0] = f"{prefix}{_get_array_range(node)}"
            array_chain = True

    # Collapse single-child chains
    while not array_chain and len(collapse_node.children) == 1 and not collapse_node.leaves:
        only = collapse_node.child_nodes()[0]
        if only.is_index:
            break
        if _has_mixed_array_content(only):
            current_path.append(only.name)
            collapse_node = only
            break
        if index_node := _is_single_element_array(only):
            current_path.append(f"{only.name}{index_node.name}")
            collapse_node = index_node
        elif only.is_array:
            current_path.append(f"{only.name}{_get_array_range(only)}")
            collapse_node = only
            array_chain = True
        else:
            current_path.append(only.name)
            collapse_node = only

    text = "_".join(current_path)

    # Handle mixed array content
    if _has_mixed_array_content(collapse_node):
        return _flatten_mixed_array(text, collapse_node)

    children = _flatten_node_children(collapse_node)
    return [_make_item(text, collapse_node, children, array=array_chain)]


def _flatten_node_children(node: TreeNode) -> list[DisplayItem]:
    """Flatten all children of a node into DisplayItems."""
    items: list[DisplayItem] = []

    for child in _ordered_children(node):
        # Rule 3: collapse array index with single leaf child
        if child.is_index:
            if leaf_child := _get_collapsible_leaf(child):
                items.append(_make_item(f"{child.name}_{leaf_child.name}", leaf_child))
                continue

        # Rule 4: Handle array nodes (an array with only indices is one item)
        if child.is_array and _has_mixed_array_content(child):
            items.extend(_flatten_mixed_array(child.name, child))
            continue

        # Non-array nodes, and arrays of indices only
        items.extend(_flatten_child_with_prefix(child.name, child))

    return items


def flatten_tree(root: TreeNode) -> list[DisplayItem]:
    """Flatten tree to list of top-level DisplayItems.

    Returns a tree of DisplayItems (top-level items only, with children nested).
    """
    return _flatten_node_children(root)
