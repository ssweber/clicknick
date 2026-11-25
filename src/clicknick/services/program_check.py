"""Shared program-check reporting for the GUI and live CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .project_workspace import NO_WINDOW, headless_python, project_environment

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pyrung import Program
    from pyrung.validation import CheckConfig, ValidationReport

    from .analysis_service import UndecodedRung


def check_stop_notes(rungs: Iterable[UndecodedRung]) -> list[str]:
    """Return a line for each rung in *rungs*. The line says that the checks stop at that rung."""
    return [
        f"ClickNick could not read {rung}. In {rung.program}, the checks cover only the rungs "
        "before it. To include the rest, paste that rung again in CLICK and save."
        for rung in rungs
    ]


def format_validation_report(report: ValidationReport) -> str:
    """Render Check Program findings as compact, agent-readable text."""
    from pyrung.validation import ordered_rules

    # The Check Program window groups the findings the same way.
    grouped = report.grouped()
    checked = getattr(report, "checked_rules", None)
    if not grouped:
        if checked is None:
            return "Check Program: all checks passed"
        if not checked:
            return "Check Program: no checks selected"
        passed = len(checked)
        not_run = len(ordered_rules()) - passed
        return (
            f"Check Program: the {passed} selected {_checks(passed)} passed. "
            f"{not_run} {_checks(not_run)} {_were(not_run)} not run."
        )

    specs = ordered_rules()
    known = {spec.code for spec in specs}
    rows = [(spec.code, spec.title, spec.severity) for spec in specs]
    rows.extend(
        (code, code, grouped[code][0].severity) for code in sorted(grouped) if code not in known
    )

    by_severity: dict[str, int] = {}
    for code, _title, severity in rows:
        count = len(grouped.get(code, ()))
        if count:
            by_severity[severity] = by_severity.get(severity, 0) + count
    summary = ", ".join(
        f"{count} {severity if count == 1 else 'advisories' if severity == 'advisory' else severity + 's'}"
        for severity in ("error", "warning", "info", "advisory")
        if (count := by_severity.get(severity, 0))
    )

    lines = [f"Check Program: {summary}"]
    if checked is not None:
        ran = len(checked)
        not_run = len(ordered_rules()) - ran
        lines.append(f"{ran} {_checks(ran)} ran. {not_run} {_were(not_run)} not run.")
    for code, title, severity in rows:
        displays = grouped.get(code, ())
        if not displays:
            continue
        lines.append(f"\n{severity}[{code}] {title}")
        for display in displays:
            text = display.as_text()
            if text:
                lines.append(text)
    return "\n".join(lines)


def _checks(count: int) -> str:
    return "check" if count == 1 else "checks"


def _were(count: int) -> str:
    return "was" if count == 1 else "were"


def run_project_check(project_dir: Path) -> str:
    """Lint the editable ``src/plc`` proposal in an isolated process."""
    main_file = project_dir / "src" / "plc" / "main.py"
    if not main_file.is_file():
        raise ValueError(
            "The workspace has no src/plc/main.py. Use Workspace > Reload from CLICK to "
            "generate it again."
        )

    result = subprocess.run(
        [headless_python(), "-m", "clicknick.services.program_check", "--worker"],
        cwd=str(project_dir),
        env=project_environment(project_dir),
        creationflags=NO_WINDOW,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise ValueError(
            result.stderr.strip() or f"Check Program exited with code {result.returncode}"
        )
    return result.stdout.strip()


def _worker() -> None:
    """Import the proposal and print its validation report."""
    from plc.main import logic
    from pyrung import Program

    if not isinstance(logic, Program):
        raise TypeError(
            "src/plc/main.py must define logic as a pyrung Program. It defines a "
            f"{type(logic).__name__}."
        )
    from pyrung.validation import CheckConfig, load_check_config

    config = load_check_config(Path.cwd() / "pyproject.toml") or CheckConfig()
    print(project_check_text(logic, config))


def project_check_text(logic: Program, config: CheckConfig) -> str:
    """Check *logic* with the checks that *config* selects, and return the report as text.

    The text starts with a ``NOTE:`` line for each rung that pyrung's ``undecoded()`` marker
    stands in for. The checks stop at that rung.
    """
    from .analysis_service import undecoded_rungs_in

    notes = "".join(f"NOTE: {note}\n" for note in check_stop_notes(undecoded_rungs_in(logic)))
    return notes + format_validation_report(logic.check(select=set(config.resolve())))


if __name__ == "__main__":
    _worker()
