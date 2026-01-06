"""Nav Window views package.

Tag Browser (NavWindow) with Outline and Block panels for navigating addresses.

Double-Click Behavior by Context
================================

Address Editor:
+-----------------+---------------------------+
| Source          | Action                    |
+-----------------+---------------------------+
| Outline leaf    | Jump to address           |
| Outline folder  | Filter by prefix          |
| Block           | Jump to first address     |
+-----------------+---------------------------+

Dataview Editor:
+-----------------+---------------------------+
| Source          | Action                    |
+-----------------+---------------------------+
| Outline leaf    | Insert one address        |
| Outline folder  | Insert all children       |
| Block           | Insert all in range       |
+-----------------+---------------------------+

Callback Signatures:
- on_outline_select(path: str, leaves: list[tuple[str, int]])
  Path is the filter prefix for folders or exact nickname for leaves.
- on_block_select(leaves: list[tuple[str, int]])
  Always provides all addresses in the block range.
"""
