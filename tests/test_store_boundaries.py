"""Architecture rules, checked by reading the source.

1. AddressStore is the only writer of its state layers. Everything else edits
   through ``store.edit_session()`` and reads ``visible_state``.
2. Nothing outside the store touches its private ``_current_session``.
3. ``services/``, ``data/`` and the simulation session are pure Python: no tkinter.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "clicknick"
STORE = SRC / "data" / "address_store.py"

# State the store derives or owns; outside code may read but never write these.
STORE_LAYERS = {"base_state", "user_overrides", "visible_state", "block_colors", "row_order"}
MUTATING_METHODS = {
    "append",
    "clear",
    "extend",
    "insert",
    "pop",
    "popitem",
    "remove",
    "setdefault",
    "sort",
    "update",
}


def _source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _layer_attr(node: ast.AST) -> str | None:
    """Return the layer name if node is `<expr>.<layer>` or `<expr>.<layer>[...]`."""
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute) and node.attr in STORE_LAYERS:
        return node.attr
    return None


def _layer_writes(tree: ast.AST) -> list[tuple[int, str]]:
    writes: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign | ast.Delete):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if name := _layer_attr(target):
                writes.append((getattr(node, "lineno", 0), f"assigns {name}"))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATING_METHODS
            and (name := _layer_attr(node.func.value))
        ):
            writes.append((getattr(node, "lineno", 0), f"calls {name}.{node.func.attr}()"))
    return writes


def _rel(path: Path) -> str:
    return path.relative_to(SRC.parent).as_posix()


def test_only_the_store_writes_its_layers() -> None:
    violations = [
        f"{_rel(path)}:{line} {what}"
        for path in _source_files()
        if path != STORE
        for line, what in _layer_writes(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert violations == [], "Write through store.edit_session() instead:\n" + "\n".join(violations)


def test_only_the_store_uses_its_current_session() -> None:
    violations = [
        f"{_rel(path)}:{node.lineno}"
        for path in _source_files()
        if path != STORE
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and node.attr == "_current_session"
    ]
    assert violations == [], "Use the session yielded by edit_session():\n" + "\n".join(violations)


# Session objects views observe; they schedule through a Tk root but never import tkinter.
PURE_MODULES = ("simulation_session.py",)


def test_services_and_data_do_not_import_tkinter() -> None:
    violations = []
    paths = [p for package in ("services", "data") for p in sorted((SRC / package).rglob("*.py"))]
    paths += [SRC / name for name in PURE_MODULES]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            if any(m == "tkinter" or m.startswith("tkinter.") for m in modules):
                violations.append(f"{_rel(path)}:{node.lineno}")
    assert violations == [], "Move UI calls into views/:\n" + "\n".join(violations)


def test_layer_write_detector_catches_each_form() -> None:
    """Guard the guard: each write form must be detected."""
    sample = """
store.visible_state = {}
store.visible_state[1] = row
del store.user_overrides[1]
store.base_state |= other
store.block_colors.clear()
store.user_overrides.pop(1)
x = store.visible_state[1]
store.visible_state.get(1)
"""
    found = [what for _line, what in _layer_writes(ast.parse(sample))]
    assert found == [
        "assigns visible_state",
        "assigns visible_state",
        "assigns user_overrides",
        "assigns base_state",
        "calls block_colors.clear()",
        "calls user_overrides.pop()",
    ]
