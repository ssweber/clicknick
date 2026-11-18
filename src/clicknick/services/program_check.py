"""Shared program-check reporting for the GUI and live CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .project_workspace import NO_WINDOW, headless_python, project_environment

if TYPE_CHECKING:
    from pyrung.validation import ValidationReport


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
    print(format_validation_report(logic.check(select=set(config.resolve()))))


if __name__ == "__main__":
    _worker()
