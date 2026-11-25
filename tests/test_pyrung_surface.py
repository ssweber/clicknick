"""ClickNick imports pyrung only from pyrung's public modules.

pyrung 0.17.0 made ``pyrung.core``, ``pyrung.dap`` and ``pyrung.click.tag_map`` internal. They can
change in any release. These tests fail when a name that ClickNick uses leaves its public home,
and when any code in the repo reaches a pyrung module that is not public.

They are tests and not a ruff rule. Ruff's banned-api rule (TID251) reads only import statements,
and only for the modules that it lists. These tests also read the program text and the dotted
names in strings, and they accept only the public modules, so a new internal path fails too.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: pyrung's public modules, as its 0.17.0 changelog lists them.
PUBLIC_MODULES = frozenset(
    {"pyrung", "pyrung.click", "pyrung.circuitpy", "pyrung.validation", "pyrung.live"}
)

#: Every pyrung name that ClickNick's code, tests and devtools import, by its public home.
#: The test programs that the tests pass to pyrung as text are included.
USED_NAMES = {
    "pyrung": (
        "And",
        "Bool",
        "Char",
        "Counter",
        "DataView",
        "FeedbackType",
        "Int",
        "Or",
        "PHYSICAL_KEYS",
        "PHYSICAL_KINDS",
        "PLC",
        "Physical",
        "PhysicalKey",
        "PhysicalKind",
        "Program",
        "Timer",
        "branch",
        "calc",
        "call",
        "comment",
        "copy",
        "count_up",
        "kind_of_keys",
        "latch",
        "named_array",
        "on_delay",
        "out",
        "pack_bits",
        "physical_kind",
        "program",
        "reset",
        "rise",
        "rung",
        "subroutine",
        "system",
    ),
    "pyrung.click": (
        "ClickBlocks",
        "LadderExportError",
        "MIGRATIONS",
        "OldCommentFormError",
        "SkippedAddressesWarning",
        "SystemNicknameRepair",
        "SystemNicknameRepairRequired",
        "TagMap",
        "TagMeta",
        "comment_needs_upgrade",
        "format_tag_meta",
        "ladder_to_pyrung",
        "ladder_to_pyrung_project",
        "old_form_tokens",
        "parse_tag_meta",
        "pyrung_to_ladder",
        "undecoded",
        "undecoded_notice",
        "undecoded_rungs",
        "upgrade_comment",
    ),
    "pyrung.validation": (
        "CheckConfig",
        "FindingDisplay",
        "ValidationReport",
        "default_on_rules",
        "load_check_config",
        "ordered_rules",
        "save_check_config",
    ),
    "pyrung.live": ("command_grammar", "send_command"),
}

# This file splits the name of each internal module, so that its own strings name none of them.
_CORE = "pyrung." + "core"
_DAP = "pyrung." + "dap"
_TAG_MAP = "pyrung.click." + "tag_map"

#: Strings that may name a module that is not public, by file. ``python -m pyrung.dap`` is how
#: pyrung's DAP server starts, so DapService names that module in its command line.
ALLOWED_STRINGS = {"src/clicknick/services/dap_service.py": frozenset({_DAP})}

#: The import lines in program text that a string holds, such as a test program for pyrung.
_TEXT_FROM_IMPORT = re.compile(r"^\s*from\s+(pyrung[\w.]*)\s+import\s+([\w, ()*]+)$", re.MULTILINE)
_TEXT_IMPORT = re.compile(r"^\s*import\s+(pyrung[\w.]*)", re.MULTILINE)

#: A dotted name in a string, such as a ``monkeypatch.setattr`` target or a module to import.
_DOTTED = re.compile(r"\bpyrung(?:\.\w+)+")

#: The dotted names in ClickNick's strings that are not pyrung paths. They are the website in
#: ``https://pyrung.com/...``, the file names ``AGENTS.pyrung.md`` and ``README.pyrung.md``, and
#: the ``tool.pyrung.check`` table of a pyproject.toml.
NOT_PYRUNG = frozenset({"pyrung.com", "pyrung.md", "pyrung.check"})


def _public_names(module_name: str) -> frozenset[str]:
    module = importlib.import_module(module_name)
    return frozenset(module.__all__)


@pytest.mark.parametrize("module_name", sorted(USED_NAMES))
def test_each_name_clicknick_uses_is_in_its_public_home(module_name):
    missing = [name for name in USED_NAMES[module_name] if name not in _public_names(module_name)]
    assert missing == [], f"{module_name} no longer exports {missing}"


def _strings(tree: ast.AST):
    """Yield each string constant in *tree* that is not a docstring.

    A docstring describes code and imports nothing, so it may name an internal module.
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                yield node


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _pyrung_imports(path: Path):
    """Yield (line, module, names) for each pyrung import in the Python file at *path*.

    The ``from pyrung... import`` and ``import pyrung...`` lines in program text inside a
    string count too, such as a program that a test hands to pyrung. Their imports carry the
    line of the string.
    """
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] == "pyrung":
                yield node.lineno, node.module, [alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "pyrung":
                    yield node.lineno, alias.name, []
    for node in _strings(tree):
        for match in _TEXT_FROM_IMPORT.finditer(node.value):
            names = [name.strip("() ") for name in match.group(2).split(",")]
            yield node.lineno, match.group(1), [name for name in names if name]
        for match in _TEXT_IMPORT.finditer(node.value):
            yield node.lineno, match.group(1), []


def _is_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError:
        return False


def _hidden_path(dotted: str) -> str | None:
    """Return how the dotted name *dotted* reaches past pyrung's public surface, or None.

    The longest part of *dotted* that is a module must be public. The name after it, if any,
    must be in that module's ``__all__``. A name in ``NOT_PYRUNG`` passes.
    """
    if dotted in NOT_PYRUNG:
        return None
    parts = dotted.split(".")
    modules = [".".join(parts[:n]) for n in range(2, len(parts) + 1)]
    found = [name for name in modules if _is_module(name)]
    module = found[-1] if found else "pyrung"
    if module not in PUBLIC_MODULES:
        return f"names {module}, which is not public"
    rest = parts[len(module.split(".")) :]
    if rest and rest[0] not in _public_names(module):
        return f"names {rest[0]} in {module}, which does not export it"
    return None


def _hidden_strings(path: Path):
    """Yield (line, problem) for each string in *path* that names a hidden pyrung path."""
    allowed = ALLOWED_STRINGS.get(path.relative_to(ROOT).as_posix(), frozenset())
    for node in _strings(_parse(path)):
        for match in _DOTTED.finditer(node.value):
            dotted = match.group(0)
            problem = None if dotted in allowed else _hidden_path(dotted)
            if problem is not None:
                yield node.lineno, f"{dotted!r} {problem}"


def _python_files():
    for folder in ("src", "tests", "devtools"):
        yield from sorted((ROOT / folder).rglob("*.py"))


def test_no_code_reaches_a_pyrung_module_that_is_not_public():
    """Each pyrung import names a public module, and each name is in that module's __all__.

    The walk covers every import, also those inside functions and ``TYPE_CHECKING`` blocks,
    and the import lines in program text inside a string. Any other string that names a
    pyrung module, such as a ``monkeypatch.setattr`` target, must name a public one too.
    """
    wrong: list[str] = []
    for path in _python_files():
        where = path.relative_to(ROOT).as_posix()
        for line, module, names in _pyrung_imports(path):
            if module not in PUBLIC_MODULES:
                wrong.append(f"{where}:{line} imports {module}")
                continue
            hidden = [name for name in names if name != "*" and name not in _public_names(module)]
            if hidden:
                wrong.append(f"{where}:{line} imports {hidden} from {module}, which hides them")
        wrong.extend(f"{where}:{line} {problem}" for line, problem in _hidden_strings(path))
    assert wrong == []


def test_used_names_lists_exactly_the_names_that_the_code_imports():
    """``USED_NAMES`` names each pyrung import, so the first test covers all of them.

    A name that no code imports any more must leave the list too.
    """
    imported: dict[str, set[str]] = {}
    for path in _python_files():
        for _line, module, names in _pyrung_imports(path):
            imported.setdefault(module, set()).update(name for name in names if name != "*")
    listed = {module: set(names) for module, names in USED_NAMES.items()}
    assert {m: sorted(n) for m, n in imported.items()} == {m: sorted(n) for m, n in listed.items()}


def test_the_check_catches_an_internal_import(tmp_path):
    source = tmp_path / "internal.py"
    source.write_text(
        f"def f():\n    from {_CORE}.analysis.pdg import TagRole\n"
        f"import {_DAP}\n"
        f"PROGRAM = 'from {_CORE} import Bool, rung'\n"
        f"OTHER = 'import {_DAP}.live'\n",
        encoding="utf-8",
    )
    found = sorted((line, module) for line, module, _names in _pyrung_imports(source))
    assert found == [(2, f"{_CORE}.analysis.pdg"), (3, _DAP), (4, _CORE), (5, f"{_DAP}.live")]
    assert not {module for _line, module in found} & PUBLIC_MODULES


@pytest.mark.parametrize(
    "line",
    [
        f'monkeypatch.setattr("{_CORE}.validation.ordered_rules", rules)',
        f'pytest.importorskip("{_DAP}.adapter")',
        f'importlib.import_module("{_CORE}")',
        f'__import__("{_DAP}.live")',
        f'monkeypatch.setattr("{_TAG_MAP}.TagMap", fake)',
        'monkeypatch.setattr("pyrung.validation.' + 'RULES", {})',
        'monkeypatch.setattr("pyrung.' + 'Rung", fake)',
    ],
    ids=[
        "setattr",
        "importorskip",
        "import_module",
        "__import__",
        "tag_map",
        "hidden name",
        "name pyrung does not export",
    ],
)
def test_the_check_catches_a_string_that_names_a_hidden_path(tmp_path, line):
    source = tmp_path / "strings.py"
    source.write_text(f"{line}\n", encoding="utf-8")
    problems = [
        _hidden_path(match.group(0))
        for node in _strings(_parse(source))
        for match in _DOTTED.finditer(node.value)
    ]
    assert any(problem is not None for problem in problems), line


@pytest.mark.parametrize(
    "text",
    [
        "pyrung.validation.ordered_rules",
        "pyrung.click.ladder_to_pyrung",
        "pyrung.live",
        "pyrung.Program",
        "pyrung.com",
        "https://pyrung.com/pyrung/guides/console/",
        "AGENTS.pyrung.md",
        "tool.pyrung.check",
    ],
)
def test_the_check_passes_a_public_path_and_a_name_that_is_not_pyrung(text):
    assert [_hidden_path(match.group(0)) for match in _DOTTED.finditer(text)] == [None]


def test_pyrung_loads_the_rest_of_a_plc_data_file_with_unclear_text(tmp_path):
    """pyrung skips the Text addresses that a PLC data file leaves unclear, and warns.

    ClickNick relies on this, so it lets a simulation start from such a file.
    """
    from pyrung.click import SkippedAddressesWarning, TagMap

    lines = [
        "<TXT=START>",
        "Address,1,2,3,4,5,6,7,8,9,10,",
        "TXT1,A,B,C,,,,,,,,",
        "TXT11,H,i,,,,,,,,,,",  # CLICK writes the comma in "Hi," without quotes.
        "</TXT=END>",
        "",
    ]
    data = tmp_path / "data.csv"
    data.write_bytes("\r\n".join(lines).encode("ascii"))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        TagMap([], include_system=False).load_snapshot(data)

    (skipped,) = [w.message for w in caught if issubclass(w.category, SkippedAddressesWarning)]
    assert isinstance(skipped, SkippedAddressesWarning)
    assert skipped.addresses == tuple(f"TXT{n}" for n in range(13, 21))
