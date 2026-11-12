"""Rung commands for live editing.

Program listing, preview, and reverse-path (pyrung -> ladder) operations.
Reads from the active project workspace published by AnalysisService.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.rung_diff import ProgramChange
    from .dispatch import DispatchContext

from ..services.project_workspace import (
    NO_WINDOW,
    headless_python,
    plc_source_dir,
    project_environment,
)
from ..services.rung_diff import comment_summary

_SUBROUTINE_NAME_RE = re.compile(r'@subroutine\("([^"]+)"\)')


def _get_csv_stem(project_dir: Path, stem: str) -> str:
    """Map a Python file stem to the subroutine display name used in CSV filenames."""
    if stem == "main":
        return "main"
    path = plc_source_dir(project_dir) / "subroutines" / f"{stem}.py"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return stem
    m = _SUBROUTINE_NAME_RE.search(source)
    return m.group(1) if m else stem


def _get_project_dir(ctx: DispatchContext) -> Path:
    """Get the active project workspace, or raise."""
    analysis = ctx.analysis
    if analysis is None:
        raise ValueError("workspace not available (no Click project connected)")
    if getattr(getattr(analysis, "status", None), "value", None) == "building":
        raise ValueError("workspace is being regenerated; try again when generation finishes")
    project_dir = analysis.project_dir
    if project_dir is None or not project_dir.is_dir():
        raise ValueError("pyrung project not persisted to disk yet")
    return project_dir


def _resolve_file(project_dir: Path, file_stem: str) -> Path:
    """Resolve a file stem (e.g. 'main', 'startup') to a .py path in the project."""
    if file_stem == "main":
        path = plc_source_dir(project_dir) / "main.py"
    else:
        path = plc_source_dir(project_dir) / "subroutines" / f"{file_stem}.py"
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    return path


def _all_file_stems(project_dir: Path) -> list[str]:
    """Return all file stems: main + sorted subroutines."""
    stems = ["main"]
    sub_dir = plc_source_dir(project_dir) / "subroutines"
    if sub_dir.is_dir():
        stems.extend(p.stem for p in sorted(sub_dir.glob("*.py")) if p.stem != "__init__")
    return stems


def _get_before_files(project_dir: Path) -> dict[str, str]:
    """Generate the 'before' state by round-tripping ladder CSVs through pyrung."""
    from pyrung.click import ladder_to_pyrung_project

    csv_dir = project_dir / "csv"
    if not csv_dir.is_dir():
        raise ValueError("workspace ladder CSV is missing; reload the workspace from CLICK")

    nickname_csv = csv_dir / "nicknames.csv" if (csv_dir / "nicknames.csv").exists() else None
    return ladder_to_pyrung_project(csv_dir, nickname_csv=nickname_csv, index=True)


def _parse_rung_selection(selection: str) -> list[int]:
    """Parse rung selection: r3, r1..5, r3,r7 -> list of 1-based rung numbers."""
    parts = selection.upper().replace("R", "").split(",")
    rungs: list[int] = []
    for part in parts:
        part = part.strip()
        if ".." in part:
            lo, hi = part.split("..", 1)
            rungs.extend(range(int(lo), int(hi) + 1))
        else:
            rungs.append(int(part))
    return rungs


def _preceding_comment_summaries(
    source: str,
    markers: list[tuple[int, int]],
) -> dict[int, str]:
    """Map rung marker lines to same-level ``comment(...)`` summaries.

    Pyrung emits CLICK comment rows immediately before the rung or section they
    introduce. ``# Rn`` remains the rung identity; these summaries are only
    labels for ``rung list`` output.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    comments: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != "comment" or not call.args:
            continue
        value = call.args[0]
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        summary = comment_summary(value.value)
        if summary:
            comments.append((node.lineno, node.col_offset, summary))

    result: dict[int, str] = {}
    previous_marker_line = 0
    for marker_line, marker_indent in markers:
        candidates = [
            (line, summary)
            for line, indent, summary in comments
            if previous_marker_line < line < marker_line and indent == marker_indent
        ]
        if candidates:
            result[marker_line] = max(candidates, key=lambda item: item[0])[1]
        previous_marker_line = marker_line
    return result


def _extract_rungs(source: str) -> list[tuple[int, int, int, str]]:
    """Extract rung boundaries from pyrung source.

    Returns list of (rung_number, start_line, end_line, first_comment).
    Detects ``# RN`` markers on ``with rung():`` lines.
    """
    lines = source.splitlines()
    rung_marker = re.compile(r"#\s*R(\d+)\s*$")
    markers: list[tuple[int, int, int, str]] = []

    for i, line in enumerate(lines):
        m = rung_marker.search(line)
        if m:
            rung_num = int(m.group(1))
            comment = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith("#"):
                    comment = next_line.lstrip("# ")
                elif next_line.startswith('"""') or next_line.startswith("'"):
                    comment = next_line.strip("\"' ")
            indent = len(line) - len(line.lstrip())
            markers.append((rung_num, i, indent, comment))

    preceding = _preceding_comment_summaries(
        source,
        [(line_index + 1, indent) for _, line_index, indent, _ in markers],
    )
    rungs = [
        (rung_num, line_index, 0, preceding.get(line_index + 1, fallback))
        for rung_num, line_index, _, fallback in markers
    ]

    for idx in range(len(rungs) - 1):
        num, start, _, comment = rungs[idx]
        rungs[idx] = (num, start, rungs[idx + 1][1], comment)
    if rungs:
        num, start, _, comment = rungs[-1]
        rungs[-1] = (num, start, len(lines), comment)

    return rungs


def _cmd_list(ctx: DispatchContext, parts: list[str]) -> str:
    file_stem = parts[0] if parts else None
    project_dir = _get_project_dir(ctx)

    if file_stem is None:
        return "files: " + ", ".join(_all_file_stems(project_dir))

    path = _resolve_file(project_dir, file_stem)
    source = path.read_text(encoding="utf-8")
    rungs = _extract_rungs(source)

    if not rungs:
        return f"{file_stem}: no rungs found"

    lines = []
    for rung_num, start, end, comment in rungs:
        row_count = end - start
        desc = f"  R{rung_num}: {row_count} lines"
        if comment:
            desc += f"  # {comment}"
        lines.append(desc)
    return f"{file_stem}: {len(rungs)} rungs\n" + "\n".join(lines)


def _program_name(project_dir: Path, stem: str) -> str:
    """Name a source file's program the way a ladder CSV bundle names it."""
    if stem == "main":
        return "main.csv"
    return f"subroutines/{_get_csv_stem(project_dir, stem)}.csv"


def _describe_change(change: ProgramChange, *, new: bool) -> str:
    """Summarise a program's change: ``R3, R5..7; removes CLICK's R9``.

    A program ClickNick cannot read all of in CLICK is pasted whole, and the summary says so.
    """
    from ..services.rung_diff import format_group, paste_groups

    if new:
        count = len(change.after)
        return f"new, {count} rung{'s' if count != 1 else ''}"

    def _runs(numbers: tuple[int, ...]) -> str:
        return ", ".join(format_group(group).upper() for group in paste_groups(numbers))

    parts: list[str] = []
    if change.changed:
        parts.append(_runs(change.changed))
    if change.removed:
        parts.append(f"removes CLICK's {_runs(change.removed)}")
    for unreadable, fault in ((False, "in an old encoding"), (True, "unreadable")):
        found = [item for item in change.legacy if item.unreadable is unreadable]
        stale = tuple(sorted({item.rung for item in found if item.rung is not None}))
        if stale:
            parts.append(f"CLICK's {_runs(stale)} {fault}")
        elif found:
            parts.append(f"CLICK's copy {fault}")
    if change.unreadable:
        parts.append("paste it whole")
    return "; ".join(parts)


def _open_proposal(ctx: DispatchContext, parts: list[str]) -> tuple[str, int]:
    """Compare the exported proposal with CLICK's program and show it in Preview Changes.

    Returns the reply and how many rungs the proposal changes.
    """
    from ..services.rung_diff import BundleSources, compare_bundle, load_bundle, render_diff

    file_stem = None
    selection = None

    i = 0
    while i < len(parts):
        if parts[i] == "--select" and i + 1 < len(parts):
            selection = parts[i + 1]
            i += 2
        elif file_stem is None:
            file_stem = parts[i]
            i += 1
        else:
            raise ValueError(f"unexpected argument: {parts[i]}")

    project_dir = _get_project_dir(ctx)
    click_dir = project_dir / "csv"
    if not click_dir.is_dir():
        raise ValueError("workspace ladder CSV is missing; reload the workspace from CLICK")
    proposal_dir = project_dir / "csv_output"
    source_dir = plc_source_dir(project_dir)
    programs = load_bundle(proposal_dir)
    comparison = compare_bundle(programs, click_dir)
    if not comparison.compared:
        raise ValueError("project_to_csv.py wrote no main.csv to csv_output")

    if file_stem is None and selection is None:
        stems = {
            _program_name(project_dir, stem).casefold(): stem
            for stem in _all_file_stems(project_dir)
        }
        changed: list[str] = []
        staged_rungs = 0
        for program in programs:
            change = comparison.changes.get(program.name)
            if change is None or not change.differs:
                continue
            staged_rungs += len(change.changed) + len(change.removed)
            stem = stems.get(program.name.casefold(), Path(program.name).stem)
            new = program.name in comparison.missing_in_click
            changed.append(f"  {stem}: {_describe_change(change, new=new)}")
        lines = ["changed files:", *changed] if changed else []
        if comparison.only_in_click:
            only = ", ".join(Path(name).stem for name in sorted(comparison.only_in_click))
            lines.append(f"only in CLICK (delete there if no longer used): {only}")
        if ctx.show_proposal is not None:
            ctx.show_proposal(proposal_dir, source_dir, None, None, bool(lines))
        return "\n".join(lines) or "(no changes)", staged_rungs

    label = file_stem or "main"
    _resolve_file(project_dir, label)
    name = _program_name(project_dir, label).casefold()
    program = next((item for item in programs if item.name.casefold() == name), None)
    change = comparison.changes.get(program.name) if program is not None else None
    if program is None:
        raise ValueError(f"{label} was not exported to csv_output")
    if change is None:
        raise ValueError(
            f"{label}: {program.error or 'could not be compared with the program in CLICK'}"
        )

    rungs = _parse_rung_selection(selection) if selection else None
    if not (change.touches(rungs) if rungs else change.differs):
        if ctx.show_proposal is not None:
            ctx.show_proposal(proposal_dir, source_dir, None, None, False)
        return "(no changes)", 0
    if change.unreadable:
        # A program ClickNick cannot read all of in CLICK is pasted whole
        rungs = None

    staged_rungs = len(rungs) if rungs else len(change.changed) + len(change.removed)
    if ctx.show_proposal is None:
        diff = render_diff(
            change,
            program.name,
            before=BundleSources.round_trip(click_dir),
            after=BundleSources.workspace(source_dir, proposal_dir),
            selected=rungs,
        )
        return diff.text, staged_rungs

    ctx.show_proposal(proposal_dir, source_dir, program.name, rungs, True)
    if rungs:
        what = f"{len(rungs)} selected rung{'s' if len(rungs) != 1 else ''}"
    else:
        what = _describe_change(change, new=program.name in comparison.missing_in_click)
    return f"OK: paste window opened for {label} ({what})", staged_rungs


def _run_export(project_dir: Path) -> Path:
    """Run ``project_to_csv.py`` to regenerate ``csv_output/``; return that dir.

    Used by ``rung apply`` to produce the proposed ladder and nickname CSVs.
    CSVs left by an earlier export that this one did not write again are
    removed, so a subroutine deleted from the source does not stay in the
    proposal. Raises on failure, leaving the earlier export as it was.
    """
    import subprocess

    script = project_dir / "project_to_csv.py"
    if not script.is_file():
        raise ValueError("project_to_csv.py not found in project directory")
    output_dir = project_dir / "csv_output"
    earlier = {path: path.stat().st_mtime_ns for path in output_dir.rglob("*.csv")}

    result = subprocess.run(
        [headless_python(), str(script)],
        cwd=str(project_dir),
        env=project_environment(project_dir),
        creationflags=NO_WINDOW,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise ValueError(
            result.stderr.strip() or f"project_to_csv.py exited with code {result.returncode}"
        )
    for path, written in earlier.items():
        try:
            if path.stat().st_mtime_ns == written:
                path.unlink()
        except OSError:
            pass  # Already gone, or open elsewhere: it stays in the proposal
    return output_dir


def _cmd_apply(ctx: DispatchContext, parts: list[str]) -> str:
    project_dir = _get_project_dir(ctx)
    pending_dir = _run_export(project_dir)
    proposal_status, staged_rungs = _open_proposal(ctx, parts)
    ctx.staged_rungs = staged_rungs
    if ctx.record_staged_rungs is not None:
        ctx.record_staged_rungs(staged_rungs)
    return f"OK: wrote ladder CSVs to {pending_dir}\n{proposal_status}"


_SUBCOMMANDS = {
    "list": _cmd_list,
    "apply": _cmd_apply,
}


def dispatch_rung(ctx: DispatchContext, parts: list[str]) -> str:
    """Route ``rung <subcommand> ...`` to the right handler."""
    if not parts:
        raise ValueError(f"usage: rung <subcommand> ...  (subcommands: {', '.join(_SUBCOMMANDS)})")

    sub = parts[0].lower()
    handler = _SUBCOMMANDS.get(sub)
    if handler is None:
        raise ValueError(f"unknown rung subcommand {sub!r} (expected: {', '.join(_SUBCOMMANDS)})")
    return handler(ctx, parts[1:])
