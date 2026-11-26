"""Rung commands for live editing.

Program listing, preview, and reverse-path (pyrung -> ladder) operations.
Reads from the active project workspace published by AnalysisService.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.rung_diff import ProgramChange
    from .dispatch import DispatchContext

from ..services.project_workspace import (
    NO_WINDOW,
    WorkspaceBusyError,
    exported_plc_source_set_aside,
    headless_python,
    plc_source_dir,
    plc_source_fingerprint,
    plc_source_is_exported,
    plc_source_is_modified,
    project_environment,
    record_exported_plc_source,
)
from ..services.rung_diff import BundleSources, comment_summary, rung_start_lines

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
    from ..connection_session import no_workspace_reason

    analysis = ctx.analysis
    project_dir = analysis.project_dir if analysis is not None else None
    status = getattr(getattr(analysis, "status", None), "value", None)
    if status == "building":
        raise WorkspaceBusyError(project_dir or "the workspace")
    if project_dir is None or not project_dir.is_dir():
        if status == "failed":
            error = getattr(analysis, "error", None)
            if error:
                raise ValueError(f"Could not build the workspace: {error}")
            raise ValueError("Could not build the workspace.")
        if project_dir is not None:
            # A build finished, and then the folder was deleted or moved.
            raise ValueError(
                f"The workspace folder {project_dir} is gone. Use Workspace > Reload from CLICK."
            )
        raise ValueError(f"There is no workspace. {no_workspace_reason(ctx.get_session())}")
    return project_dir


def _resolve_file(project_dir: Path, file_stem: str) -> Path:
    """Resolve a file stem (e.g. 'main', 'startup') to a .py path in the project."""
    if file_stem == "main":
        path = plc_source_dir(project_dir) / "main.py"
    else:
        path = plc_source_dir(project_dir) / "subroutines" / f"{file_stem}.py"
    if not path.is_file():
        raise ValueError(
            f"There is no program named {file_stem!r}. Run 'rung list' to see the names."
        )
    return path


def _all_file_stems(project_dir: Path) -> list[str]:
    """Return all file stems: main + sorted subroutines."""
    stems = ["main"]
    sub_dir = plc_source_dir(project_dir) / "subroutines"
    if sub_dir.is_dir():
        stems.extend(p.stem for p in sorted(sub_dir.glob("*.py")) if p.stem != "__init__")
    return stems


def _get_before_files(project_dir: Path, *, analog_inputs: frozenset[str]) -> dict[str, str]:
    """Generate the 'before' state by round-tripping ladder CSVs through pyrung.

    Pass the channels that the workspace was generated with as *analog_inputs*. Otherwise
    the regenerated tags differ from the workspace's in their ``external`` flags.
    """
    from pyrung.click import ladder_to_pyrung_project

    csv_dir = project_dir / "csv"
    if not csv_dir.is_dir():
        raise ValueError("The workspace has no csv folder. Use Workspace > Reload from CLICK.")

    nickname_csv = csv_dir / "nicknames.csv" if (csv_dir / "nicknames.csv").exists() else None
    return ladder_to_pyrung_project(
        csv_dir, nickname_csv=nickname_csv, analog_inputs=analog_inputs, index=True
    )


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
    """Map rung start lines to same-level ``comment(...)`` summaries.

    Pyrung emits CLICK comment rows immediately before the rung or section they
    introduce. The summaries are only labels for ``rung list`` output. They play no
    part in how the rungs are numbered.
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


def _extract_rungs(
    source: str, rung_lines: Mapping[int, Sequence[int]]
) -> list[tuple[int, int | None, int | None, str]]:
    """Return the rungs of one program's *source*, in order of rung number.

    Each rung is (rung number, start line, end line, comment summary). The lines count from 0,
    and the end line is the start line of the next rung in the file, or the end of the file.
    *rung_lines* is the program's part of the exporter's manifest, as ``BundleSources.lines``
    returns it. It gives the rung numbers, as it does in Review Changes. If it is empty, the
    ``# Rn`` markers give them. A rung that the manifest lists with no line in *source*, such
    as a rung that a helper module builds, has no start line, no end line and no summary.
    """
    lines = source.splitlines()
    starts = {number: line - 1 for number, line in rung_start_lines(source, rung_lines).items()}
    numbers = sorted({*rung_lines, *starts})
    heads = sorted(set(starts.values()))
    preceding = _preceding_comment_summaries(
        source,
        [
            (line_index + 1, len(lines[line_index]) - len(lines[line_index].lstrip()))
            for line_index in heads
        ],
    )

    rungs: list[tuple[int, int | None, int | None, str]] = []
    for number in numbers:
        start = starts.get(number)
        if start is None:
            rungs.append((number, None, None, ""))
            continue
        end = next((head for head in heads if head > start), len(lines))
        comment = ""
        if start + 1 < len(lines):
            next_line = lines[start + 1].strip()
            if next_line.startswith("#"):
                comment = next_line.lstrip("# ")
            elif next_line.startswith('"""') or next_line.startswith("'"):
                comment = next_line.strip("\"' ")
        rungs.append((number, start, end, preceding.get(start + 1, comment)))
    return rungs


def _rung_numbering(
    project_dir: Path, path: Path, file_stem: str, source: str
) -> tuple[Mapping[int, Sequence[int]], str]:
    """Return the rung lines that number the rungs of *source*, and a note for ``rung list``.

    The rung lines come from the last export's ``rung_sources.json`` if ``src/plc`` reads the
    same as when that export read it, and nothing has written the manifest since. Otherwise
    they are an empty dict, and ``rung list`` reads the ``# Rn`` markers. The markers are
    also used when the manifest gives a rung a line in *source* that no ``with rung()``
    block holds. The note is empty when the numbers match what ``rung apply --select``
    counts. That is when they come from the export, or when ``src/plc`` is as ClickNick
    generated it.
    """
    name = path.name
    outside = False
    if plc_source_is_exported(project_dir):
        rung_lines = BundleSources.workspace(
            plc_source_dir(project_dir), project_dir / "csv_output"
        ).lines(_program_name(project_dir, file_stem))
        starts = rung_start_lines(source, rung_lines)
        outside = any(lines and number not in starts for number, lines in rung_lines.items())
        if rung_lines and not outside:
            return rung_lines, ""
    try:
        if not plc_source_is_modified(project_dir):
            return {}, ""
    except OSError:
        pass  # A file could not be read, so nothing shows that the markers are right
    if outside:
        return {}, (
            f"NOTE: These numbers come from the # R1, # R2, ... comments in {name}. The last "
            f"export ties a rung to a line of {name} that is not inside a with rung() block, so "
            "rung list cannot use that export. The comments can be out of date, so rung apply "
            "--select may count the rungs differently."
        )
    return {}, (
        f"NOTE: These numbers come from the # R1, # R2, ... comments in {name}. Those "
        "comments can be out of date, so rung apply --select may count the rungs differently. "
        "To number them as rung apply does, run rung apply or open Review Changes, then run "
        "rung list again."
    )


def _cmd_list(ctx: DispatchContext, parts: list[str]) -> str:
    file_stem = parts[0] if parts else None
    project_dir = _get_project_dir(ctx)

    if file_stem is None:
        return "files: " + ", ".join(_all_file_stems(project_dir))

    path = _resolve_file(project_dir, file_stem)
    source = path.read_text(encoding="utf-8")
    rung_lines, note = _rung_numbering(project_dir, path, file_stem, source)
    rungs = _extract_rungs(source, rung_lines)

    if not rungs:
        return f"{file_stem}: no rungs found"

    lines = [note] if note else []
    lines.append(f"{file_stem}: {len(rungs)} rungs")
    for rung_num, start, end, comment in rungs:
        if start is None or end is None:
            lines.append(f"  R{rung_num}: no source line in this file")
            continue
        desc = f"  R{rung_num}: {end - start} lines"
        if comment:
            desc += f"  # {comment}"
        lines.append(desc)
    return "\n".join(lines)


def _program_name(project_dir: Path, stem: str) -> str:
    """Name a source file's program the way a ladder CSV bundle names it."""
    if stem == "main":
        return "main.csv"
    return f"subroutines/{_get_csv_stem(project_dir, stem)}.csv"


def _describe_change(change: ProgramChange, *, new: bool) -> str:
    """Summarise a program's change: ``R3, R5..7; removes CLICK's R9``.

    A program that ClickNick cannot fully read in CLICK is pasted whole, and the summary says so.
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
    """Compare the exported proposal with CLICK's program and show it in Review Changes.

    Return the reply and the number of rungs that the proposal changes.
    """
    from ..services.rung_diff import (
        WORKSPACE_SOURCE,
        BundleSources,
        compare_bundle,
        load_bundle,
        render_diff,
    )

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
        raise ValueError("The workspace has no csv folder. Use Workspace > Reload from CLICK.")
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
            lines.append(
                f"only in CLICK: {only}. Delete a program in CLICK if you no longer use it."
            )
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
        # A program that ClickNick cannot fully read in CLICK is pasted whole.
        rungs = None

    staged_rungs = len(rungs) if rungs else len(change.changed) + len(change.removed)
    if ctx.show_proposal is None:
        diff = render_diff(
            change,
            program.name,
            before=BundleSources.round_trip(click_dir),
            after=BundleSources.workspace(source_dir, proposal_dir),
            selected=rungs,
            source=WORKSPACE_SOURCE,
        )
        return diff.text, staged_rungs

    ctx.show_proposal(proposal_dir, source_dir, program.name, rungs, True)
    if rungs:
        what = f"{len(rungs)} selected rung{'s' if len(rungs) != 1 else ''}"
    else:
        what = _describe_change(change, new=program.name in comparison.missing_in_click)
    return f"OK: opened Review Changes for {label} ({what})", staged_rungs


def _run_export(project_dir: Path) -> Path:
    """Run ``project_to_csv.py`` to regenerate ``csv_output/``; return that dir.

    Used by ``rung apply`` to produce the proposed ladder and nickname CSVs.
    This removes CSVs that an earlier export left and this one did not write again. A
    subroutine deleted from the source then does not stay in the proposal.

    While the script runs, the earlier ``rung_sources.json`` and its record are set aside
    (``exported_plc_source_set_aside``). On success this records the ``src/plc`` that it read
    and the ``rung_sources.json`` that the script wrote (``record_exported_plc_source``), for
    ``rung list``. On failure or a timeout it raises, and puts the earlier manifest and
    record back. It removes no CSV. The CSVs that the script wrote before it failed stay,
    beside the earlier CSVs that it did not write again.

    The script runs in ``_export_worker``. If pyrung refuses the export because the source
    holds ``undecoded()``, the error names each rung that the call stands in for.
    """
    import subprocess

    script = project_dir / "project_to_csv.py"
    if not script.is_file():
        raise ValueError(
            "The workspace has no project_to_csv.py. Use Workspace > Reload from CLICK."
        )
    output_dir = project_dir / "csv_output"
    earlier = {path: path.stat().st_mtime_ns for path in output_dir.rglob("*.csv")}
    # Hash src/plc before the export runs. An edit during the export then fails to match
    # the record, and rung list reads the markers.
    try:
        read: dict[str, str] | None = plc_source_fingerprint(project_dir)
    except OSError:
        read = None  # Without a record, rung list reads the markers

    with exported_plc_source_set_aside(project_dir) as aside:
        result = subprocess.run(
            [headless_python(), "-m", "clicknick.live.rung_commands", "--export", str(script)],
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
            pass  # Already gone, or open elsewhere. A file open elsewhere stays in the proposal.
    # If rung_sources.json or its record could not be moved aside, write no record
    record_exported_plc_source(project_dir, read if aside else None)
    return output_dir


def _export_worker(script: Path) -> None:
    """Run the workspace's *script*, ``project_to_csv.py``, as Python runs a script.

    pyrung's export refuses ``undecoded()``. If the program holds one when the export fails,
    print ``export_stop_refusal`` and exit with code 1. That text names CLICK's program and
    rung for each call. pyrung's own text leaves out the subroutine's name, and it suggests
    removing the rung. Any other failure raises as the script raised it.
    """
    import runpy

    from pyrung import Program
    from pyrung.click import LadderExportError

    from ..services.analysis_service import export_stop_refusal, undecoded_rungs_in

    # The script sees the arguments that Python gives a script run on its own
    sys.argv = [str(script)]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except LadderExportError:
        # pyrung's generated project_to_csv.py exports the logic of plc.main.
        logic = getattr(sys.modules.get("plc.main"), "logic", None)
        rungs = undecoded_rungs_in(logic) if isinstance(logic, Program) else ()
        if not rungs:
            raise
        print(export_stop_refusal(rungs), file=sys.stderr)
        raise SystemExit(1) from None


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


if __name__ == "__main__":
    if sys.argv[1:2] == ["--export"] and len(sys.argv) == 3:
        _export_worker(Path(sys.argv[2]))
