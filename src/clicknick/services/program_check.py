"""Shared program-check reporting for the GUI and live CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .project_workspace import project_environment

if TYPE_CHECKING:
    from pyrung.core.validation import FindingDisplay, ValidationReport


def group_validation_findings(
    report: ValidationReport | None,
) -> dict[str, list[FindingDisplay]]:
    """Group findings exactly as the Check Program window does."""
    from pyrung.core.validation.stuck_bits import StuckBitFinding, StuckBitReport

    grouped: dict[str, list[FindingDisplay]] = {}
    if report is None:
        return grouped

    stuck: list[StuckBitFinding] = []
    for finding in report:
        if isinstance(finding, StuckBitFinding):
            stuck.append(finding)
        else:
            grouped.setdefault(finding.code, []).append(finding.display)
    for group in StuckBitReport(findings=tuple(stuck)).grouped():
        grouped.setdefault(group.code, []).append(group.display)
    return grouped


def format_validation_report(report: ValidationReport) -> str:
    """Render Check Program findings as compact, agent-readable text."""
    from pyrung.core.validation import ordered_rules

    grouped = group_validation_findings(report)
    if not grouped:
        return "Check Program: all checks passed"

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
        f"{count} {severity if count == 1 else severity + 's'}"
        for severity in ("error", "warning", "info", "advisory")
        if (count := by_severity.get(severity, 0))
    )

    lines = [f"Check Program: {summary}"]
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


def run_project_check(project_dir: Path) -> str:
    """Lint the editable ``src/plc`` proposal in an isolated process."""
    main_file = project_dir / "src" / "plc" / "main.py"
    if not main_file.is_file():
        raise ValueError("src/plc/main.py not found in project directory")

    result = subprocess.run(
        [sys.executable, "-m", "clicknick.services.program_check", "--worker"],
        cwd=str(project_dir),
        env=project_environment(project_dir),
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
    from pyrung.core.program import Program

    if not isinstance(logic, Program):
        raise TypeError(f"Expected plc.main.logic to be Program, got {type(logic).__name__}")
    print(format_validation_report(logic.validate()))


if __name__ == "__main__":
    _worker()
