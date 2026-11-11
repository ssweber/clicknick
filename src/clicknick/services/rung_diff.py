"""Rung-by-rung comparison of a proposed ladder bundle with the program in CLICK.

One comparison serves Guided Paste (which programs to paste, and which of their
rungs) and ``clicknick-cli rung apply`` (what to report). A bundle is laid out
like ``program_save`` output, ``main.csv`` + ``subroutines/*.csv``, and its
programs are named like ``list_csv_folder`` names them.

Rungs are compared as CLICK would hold them (``rung_fingerprint``); pyrung
source is only how a difference is shown.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from laddercodec import Rung, read_csv

from ..ladder.program import count_csv_rungs, list_csv_folder, read_csv_comment, rung_fingerprint

_MAIN = "main.csv"
_SUBROUTINE_NAME_RE = re.compile(r'@subroutine\("([^"]+)"\)')
_RUNG_MARKER_RE = re.compile(r"#\s*R(\d+)\s*$")
_COMMENT_SUMMARY_LIMIT = 88

# One SequenceMatcher step: (tag, CLICK start, CLICK end, proposed start, proposed end)
Opcode = tuple[str, int, int, int, int]


# ---------------------------------------------------------------------------
# The proposal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedProgram:
    """One ladder CSV of a bundle, read once: what is compared is what gets copied."""

    name: str
    path: Path
    # None when the CSV could not be read; *error* says why.
    rungs: tuple[Rung, ...] | None
    rung_count: int
    description: str = ""
    error: str = ""


def load_bundle(folder: Path) -> list[ProposedProgram]:
    """Read every ladder CSV in *folder*, subroutines before main."""
    programs: list[ProposedProgram] = []
    for name, path in list_csv_folder(folder):
        description = read_csv_comment(path)
        try:
            rungs = tuple(read_csv(path))
        except Exception as exc:
            programs.append(
                ProposedProgram(name, path, None, count_csv_rungs(path), description, str(exc))
            )
        else:
            programs.append(ProposedProgram(name, path, rungs, len(rungs), description))
    return programs


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PasteStep:
    """One thing to do in CLICK to turn its program into the proposed one.

    Steps run from the top of the program: by the time one is reached,
    everything above it already matches, so its rung numbers are the ones CLICK
    shows. CLICK pastes over the selected rung: that rung is replaced by the
    first pasted rung and the rest go in below it.
    """

    # Proposed rung numbers to copy; empty when the step only deletes
    rungs: tuple[int, ...] = ()
    # CLICK's rung to select and paste over
    over: int | None = None
    # For new rungs, which have nothing to paste over: the rung they go in above.
    # None with *over* also None means after the last rung.
    above: int | None = None
    # CLICK's rungs to delete, when nothing is copied
    delete: tuple[int, ...] = ()
    # Which difference of the program the step belongs to, counting from 0
    block: int = 0
    # False when the rungs were picked by number: where they go is not known
    placed: bool = True


@dataclass(frozen=True)
class ProgramChange:
    """How a proposed program differs from the same program in CLICK."""

    # CLICK's rungs; empty when CLICK does not have the program.
    before: tuple[Rung, ...] = ()
    after: tuple[Rung, ...] = ()
    opcodes: tuple[Opcode, ...] = ()

    @property
    def differs(self) -> bool:
        return any(tag != "equal" for tag, *_ in self.opcodes)

    @property
    def changed(self) -> tuple[int, ...]:
        """Proposed rung numbers CLICK lacks: the rungs to paste."""
        return tuple(
            number
            for tag, _i1, _i2, j1, j2 in self.opcodes
            if tag in ("insert", "replace")
            for number in range(j1 + 1, j2 + 1)
        )

    @property
    def removed(self) -> tuple[int, ...]:
        """CLICK rung numbers the proposal drops without putting anything in their place."""
        return tuple(
            number
            for tag, i1, i2, _j1, _j2 in self.opcodes
            if tag == "delete"
            for number in range(i1 + 1, i2 + 1)
        )

    def touches(self, selected: Iterable[int]) -> bool:
        """Whether any of the *selected* proposed rungs is one to paste."""
        return not set(selected).isdisjoint(self.changed)

    @property
    def steps(self) -> tuple[PasteStep, ...]:
        """What to do in CLICK, from the top of the program down."""
        steps: list[PasteStep] = []
        differences = (opcode for opcode in self.opcodes if opcode[0] != "equal")
        for block, (tag, i1, i2, j1, j2) in enumerate(differences):
            rungs = tuple(range(j1 + 1, j2 + 1))
            if tag == "insert":
                # CLICK's rung i1+1 stands at j1+1 by now, if there is one
                above = j1 + 1 if i1 < len(self.before) else None
                steps.append(PasteStep(rungs, above=above, block=block))
                continue
            leftover = i2 - i1
            if tag == "replace":
                steps.append(PasteStep(rungs, over=j1 + 1, block=block))
                leftover -= 1  # The paste took the place of the first of CLICK's rungs
            if leftover:
                # They now stand right below what was pasted
                steps.append(PasteStep(delete=tuple(range(j2 + 1, j2 + 1 + leftover)), block=block))
        return tuple(steps)


def compare_rungs(before: Sequence[Rung], after: Sequence[Rung]) -> ProgramChange:
    """Align CLICK's rungs with the proposed ones.

    A rung that only moved (rungs were added or removed above it) is equal:
    its number is not part of what it is.
    """
    before_keys = [rung_fingerprint(rung) for rung in before]
    after_keys = [rung_fingerprint(rung) for rung in after]
    if before_keys == after_keys:
        opcodes: Sequence[Opcode] = [("equal", 0, len(before_keys), 0, len(after_keys))]
    else:
        matcher = difflib.SequenceMatcher(a=before_keys, b=after_keys, autojunk=False)
        opcodes = matcher.get_opcodes()
    return ProgramChange(tuple(before), tuple(after), tuple(opcodes))


@dataclass(frozen=True)
class BundleComparison:
    """How a bundle compares with the program now in CLICK."""

    # False when nothing was compared: what CLICK has is unknown.
    compared: bool = False
    # Proposed program name -> its change (a program CLICK lacks is all new
    # rungs). Programs that cannot be read are absent: unknown.
    changes: dict[str, ProgramChange] = field(default_factory=dict)
    # Programs CLICK has that the bundle does not: name -> all rungs removed.
    only_in_click: dict[str, ProgramChange] = field(default_factory=dict)
    # Proposed program names CLICK does not have yet (readable or not).
    missing_in_click: frozenset[str] = frozenset()


def compare_bundle(programs: Iterable[ProposedProgram], current_dir: Path) -> BundleComparison:
    """Compare a loaded bundle with the program now in CLICK.

    *current_dir* holds the program now in CLICK, laid out like the bundle.
    Names are matched ignoring case. A bundle without ``main.csv`` is not a
    program and compares empty.
    """
    programs = list(programs)
    proposed_names = {program.name.casefold() for program in programs}
    if _MAIN not in proposed_names:
        return BundleComparison()

    current: dict[str, Path] = {}
    only_in_click: dict[str, ProgramChange] = {}
    for name, path in list_csv_folder(current_dir):
        current[name.casefold()] = path
        if name.casefold() not in proposed_names:
            try:
                rungs = read_csv(path)
            except Exception:
                rungs = []
            only_in_click[name] = compare_rungs(rungs, [])

    changes: dict[str, ProgramChange] = {}
    for program in programs:
        if program.rungs is None:
            continue
        current_path = current.get(program.name.casefold())
        try:
            before = read_csv(current_path) if current_path is not None else []
        except Exception:
            continue  # CLICK's copy is unreadable: unknown
        changes[program.name] = compare_rungs(before, program.rungs)
    missing = frozenset(
        program.name for program in programs if program.name.casefold() not in current
    )
    return BundleComparison(
        compared=True, changes=changes, only_in_click=only_in_click, missing_in_click=missing
    )


# ---------------------------------------------------------------------------
# Paste groups
# ---------------------------------------------------------------------------


def paste_groups(rung_numbers: Iterable[int]) -> list[list[int]]:
    """Split rung numbers into runs that paste as one block.

    >>> paste_groups([3, 5, 6, 7, 10])
    [[3], [5, 6, 7], [10]]
    """
    groups: list[list[int]] = []
    for number in sorted(set(rung_numbers)):
        if groups and number == groups[-1][-1] + 1:
            groups[-1].append(number)
        else:
            groups.append([number])
    return groups


def format_group(group: Sequence[int]) -> str:
    """Name a paste group the way ``--select`` writes it: ``r3`` or ``r5..7``."""
    if not group:
        return ""
    if len(group) == 1:
        return f"r{group[0]}"
    return f"r{group[0]}..{group[-1]}"


# ---------------------------------------------------------------------------
# pyrung source for display
# ---------------------------------------------------------------------------


def comment_summary(value: str) -> str:
    """Return the first meaningful line of a CLICK comment."""
    for raw_line in value.splitlines():
        line = raw_line.strip().strip("#").strip()
        if not line or not line.strip("=-_* "):
            continue
        line = " ".join(line.split())
        if len(line) <= _COMMENT_SUMMARY_LIMIT:
            return line
        return line[: _COMMENT_SUMMARY_LIMIT - 3].rstrip() + "..."
    return ""


def _program_name(relative: Path, source: str) -> str | None:
    """Name the bundle program a ``src/plc`` file holds, or None for other files."""
    if relative.suffix != ".py":
        return None
    if relative.name == "main.py":
        return _MAIN
    if relative.parent.name != "subroutines" or relative.stem == "__init__":
        return None
    title = _SUBROUTINE_NAME_RE.search(source)
    return f"subroutines/{title.group(1) if title else relative.stem}.csv"


def _read_manifest(bundle_dir: Path) -> dict[str, dict[int, list[int]]]:
    """Read the exporter's manifest: program -> proposed rung -> source lines."""
    try:
        manifest = json.loads((bundle_dir / "rung_sources.json").read_text(encoding="utf-8"))
        entries_by_name = {
            _MAIN: manifest.get("main", []),
            **{
                f"subroutines/{title}.csv".casefold(): entries
                for title, entries in manifest.get("subroutines", {}).items()
            },
        }
    except (OSError, ValueError, TypeError, AttributeError):
        return {}

    result: dict[str, dict[int, list[int]]] = {}
    for name, entries in entries_by_name.items():
        lines: dict[int, list[int]] = {}
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, dict) or not isinstance(entry.get("rung"), int):
                continue
            sources = entry.get("sources", [])
            lines[entry["rung"]] = [
                source["source_line"]
                for source in (sources if isinstance(sources, list) else ())
                if isinstance(source, dict) and isinstance(source.get("source_line"), int)
            ]
        result[name] = lines
    return result


@dataclass(frozen=True)
class BundleSources:
    """pyrung source for a bundle's programs: how their rungs are shown.

    A program without source is shown as rung numbers with each rung's
    instructions and comment instead.
    """

    # Program name (casefolded) -> source text
    texts: Mapping[str, str] = field(default_factory=dict)
    # Program name (casefolded) -> rung number -> the source lines it came from.
    # Empty when each rung's ``# Rn`` marker already carries its number.
    rung_lines: Mapping[str, Mapping[int, Sequence[int]]] = field(default_factory=dict)

    def text(self, name: str) -> str:
        return self.texts.get(name.casefold(), "")

    def lines(self, name: str) -> Mapping[int, Sequence[int]]:
        return self.rung_lines.get(name.casefold(), {})

    @classmethod
    def round_trip(cls, csv_dir: Path) -> BundleSources:
        """Generate source for a CSV bundle by converting it with pyrung.

        Empty when pyrung cannot convert the bundle: showing it is all that is lost.
        """
        from pyrung.click import ladder_to_pyrung_project

        nickname_csv = csv_dir / "nicknames.csv"
        try:
            files = ladder_to_pyrung_project(
                csv_dir, nickname_csv=nickname_csv if nickname_csv.exists() else None, index=True
            )
        except Exception:
            return cls()
        texts: dict[str, str] = {}
        for relative, source in files.items():
            name = _program_name(Path(relative), source)
            if name is not None:
                texts[name.casefold()] = source
        return cls(texts)

    @classmethod
    def workspace(cls, source_dir: Path, bundle_dir: Path) -> BundleSources:
        """Read the workspace source that *bundle_dir* was just exported from.

        The exporter's manifest ties each exported rung to its source lines, so
        the text shown is the text that was edited.
        """
        texts: dict[str, str] = {}
        for path in (source_dir / "main.py", *sorted((source_dir / "subroutines").glob("*.py"))):
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            name = _program_name(path.relative_to(source_dir), source)
            if name is not None:
                texts[name.casefold()] = source
        return cls(texts, _read_manifest(bundle_dir))


@dataclass
class _SourceChunk:
    """One numbered pyrung block, including its comment and continuations."""

    number: int
    marker_line: int
    start_line: int
    end_line: int


def _is_named_call(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


def _rung_context_kind(node: ast.AST) -> str | None:
    if _is_named_call(node, "rung"):
        return "primary"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "continued"
        and _is_named_call(node.func.value, "rung")
    ):
        return "continued"
    return None


def _statement_rung_number(statement: ast.stmt, lines: list[str]) -> int | None:
    """Read a rung marker anywhere in a possibly multiline statement."""
    end_line = statement.end_lineno or statement.lineno
    for line in lines[statement.lineno - 1 : end_line]:
        marker = _RUNG_MARKER_RE.search(line)
        if marker:
            return int(marker.group(1))
    return None


def _source_chunks(source: str) -> list[_SourceChunk]:
    """Parse generated pyrung into display chunks without treating Rn as identity."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    chunks: list[_SourceChunk] = []

    def _visit_body(body: list[ast.stmt]) -> None:
        pending_comments: list[ast.Expr] = []
        active: _SourceChunk | None = None
        for statement in body:
            if isinstance(statement, ast.Expr) and _is_named_call(statement.value, "comment"):
                pending_comments.append(statement)
                active = None
                continue

            kind = None
            if isinstance(statement, ast.With):
                kinds = [_rung_context_kind(item.context_expr) for item in statement.items]
                kind = next((value for value in kinds if value is not None), None)

            if kind == "primary":
                rung_number = _statement_rung_number(statement, lines)
                if rung_number is not None:
                    active = _SourceChunk(
                        number=rung_number,
                        marker_line=statement.lineno,
                        start_line=(
                            pending_comments[0].lineno if pending_comments else statement.lineno
                        ),
                        end_line=statement.end_lineno or statement.lineno,
                    )
                    chunks.append(active)
                else:
                    active = None
                pending_comments.clear()
                continue

            if kind == "continued" and active is not None:
                active.end_line = max(active.end_line, statement.end_lineno or statement.lineno)
                pending_comments.clear()
                continue

            pending_comments.clear()
            active = None
            for field_name in ("body", "orelse", "finalbody"):
                child_body = getattr(statement, field_name, None)
                if isinstance(child_body, list):
                    _visit_body(child_body)

    _visit_body(tree.body)
    return chunks


def _chunks_by_rung(
    source: str, rung_lines: Mapping[int, Sequence[int]]
) -> dict[int, tuple[_SourceChunk, ...]]:
    chunks = _source_chunks(source)
    result: dict[int, tuple[_SourceChunk, ...]] = {}
    for rung_number, source_lines in rung_lines.items():
        matched: list[_SourceChunk] = []
        for source_line in source_lines:
            chunk = next(
                (
                    candidate
                    for candidate in chunks
                    if candidate.marker_line <= source_line <= candidate.end_line
                ),
                None,
            )
            if chunk is not None and chunk not in matched:
                matched.append(chunk)
        if matched:
            result[rung_number] = tuple(matched)
    for chunk in chunks:
        result.setdefault(chunk.number, (chunk,))
    return result


def _rung_summary(rung: Rung) -> str:
    """Describe a rung that has no source to show: its instructions, then its comment."""
    instructions = "; ".join(
        row[-1]
        for row in rung_fingerprint(rung)
        # Not comment rows, blank outputs, or pins (".reset()") of the instruction above
        if row[0] != "#" and row[-1] and not row[-1].startswith(".")
    )
    label = comment_summary(rung.comment or "")
    return "".join(f"  {part}" for part in (instructions, f"# {label}" if label else "") if part)


def _render_rungs(
    rungs: Sequence[Rung],
    rung_numbers: range,
    source: str,
    chunks_by_rung: dict[int, tuple[_SourceChunk, ...]],
    *,
    prefix: str,
) -> list[str]:
    lines = source.splitlines()
    result: list[str] = []
    emitted: set[tuple[int, int]] = set()
    for rung_number in rung_numbers:
        chunks = chunks_by_rung.get(rung_number, ())
        if not chunks:
            result.append(f"{prefix}R{rung_number}{_rung_summary(rungs[rung_number - 1])}\n")
            continue
        for chunk in chunks:
            identity = (chunk.start_line, chunk.end_line)
            if identity in emitted:
                continue
            emitted.add(identity)
            for line in lines[chunk.start_line - 1 : chunk.end_line]:
                result.append(f"{prefix}{line}\n")
    return result


@dataclass(frozen=True)
class RenderedDiff:
    """A program's change as text: ``-`` CLICK's rungs, ``+`` proposed, ``~`` renumbered."""

    lines: tuple[str, ...] = ()
    # Proposed rung number -> index in *lines* where the block holding it starts
    starts: Mapping[int, int] = field(default_factory=dict)
    # Index in *lines* where each difference shown starts, in order. They are
    # the program's differences (``PasteStep.block``) unless rungs were selected.
    blocks: tuple[int, ...] = ()

    @property
    def text(self) -> str:
        return "".join(self.lines)


def render_diff(
    change: ProgramChange,
    name: str,
    *,
    before: BundleSources,
    after: BundleSources,
    selected: Iterable[int] | None = None,
) -> RenderedDiff:
    """Show *change* as the pyrung source of the rungs that differ.

    With *selected*, only the blocks holding one of those proposed rungs are
    shown. Empty when nothing differs.
    """
    before_text = before.text(name)
    after_text = after.text(name)
    before_chunks = _chunks_by_rung(before_text, before.lines(name))
    after_chunks = _chunks_by_rung(after_text, after.lines(name))
    selected_set = None if selected is None else set(selected)

    body: list[str] = []
    starts: dict[int, int] = {}
    blocks: list[int] = []
    for tag, i1, i2, j1, j2 in change.opcodes:
        after_range = range(j1 + 1, j2 + 1)
        if selected_set is not None and selected_set.isdisjoint(after_range):
            continue

        if tag == "equal":
            # One line for the whole run: its rungs all moved by the same amount
            if i1 != j1 and i2 - i1 == 1:
                label = comment_summary(change.after[j1].comment or "")
                suffix = f"  # {label}" if label else ""
                body.append(f"~ R{i1 + 1} -> R{j1 + 1}{suffix}\n")
            elif i1 != j1:
                body.append(f"~ R{i1 + 1}..{i2} -> R{j1 + 1}..{j2}\n")
            continue

        start = len(body)
        blocks.append(start)
        if tag in ("delete", "replace"):
            body.extend(
                _render_rungs(
                    change.before, range(i1 + 1, i2 + 1), before_text, before_chunks, prefix="-"
                )
            )
        if tag in ("insert", "replace"):
            body.extend(
                _render_rungs(change.after, after_range, after_text, after_chunks, prefix="+")
            )
            starts.update(dict.fromkeys(after_range, start))

    if not any(line.startswith(("+", "-")) for line in body):
        return RenderedDiff()
    header = (f"--- CLICK/{name}\n", f"+++ proposed/{name}\n")
    return RenderedDiff(
        (*header, *body),
        {number: index + len(header) for number, index in starts.items()},
        tuple(index + len(header) for index in blocks),
    )
