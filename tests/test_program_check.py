"""Tests for the agent-facing Check Program command."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pyrung.core.validation import FindingDisplay, ValidationReport

from clicknick.live.dispatch import DispatchContext, dispatch
from clicknick.services.program_check import format_validation_report, run_project_check


class _Analysis:
    is_available = True

    def __init__(self, project_dir):
        self.project_dir = project_dir


class _Store:
    user_overrides = {}


class _Finding:
    code = "CMP_EXAMPLE"
    target_name = "State"
    severity = "advisory"
    display = FindingDisplay(
        code=code,
        severity=severity,
        problem="State is compared directly in several rungs.",
        hint="decode frequently used choices into Bool tags",
    )
    message = display.as_text()


def test_format_validation_report_passes_clean_program() -> None:
    assert format_validation_report(ValidationReport(findings=())) == (
        "Check Program: all checks passed"
    )


def test_format_validation_report_includes_structured_finding() -> None:
    report = ValidationReport(findings=(_Finding(),))

    text = format_validation_report(report)

    assert text.startswith("Check Program: 1 advisory")
    assert "advisory[CMP_EXAMPLE] CMP_EXAMPLE" in text
    assert "State is compared directly in several rungs." in text
    assert "decode frequently used choices into Bool tags" in text


def test_run_project_check_uses_isolated_project_environment(tmp_path, monkeypatch) -> None:
    main_file = tmp_path / "src" / "plc" / "main.py"
    main_file.parent.mkdir(parents=True)
    main_file.write_text("logic = object()\n", encoding="utf-8")
    calls = []

    def _run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="Check Program: all checks passed\n", stderr="")

    monkeypatch.setattr("clicknick.services.program_check.subprocess.run", _run)

    assert run_project_check(tmp_path) == "Check Program: all checks passed"
    command = calls[0][0][0]
    assert command[-3:] == ["-m", "clicknick.services.program_check", "--worker"]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert str(tmp_path / "src") in calls[0][1]["env"]["PYTHONPATH"]


def test_run_project_check_reports_worker_failure(tmp_path, monkeypatch) -> None:
    main_file = tmp_path / "src" / "plc" / "main.py"
    main_file.parent.mkdir(parents=True)
    main_file.write_text("broken source\n", encoding="utf-8")
    monkeypatch.setattr(
        "clicknick.services.program_check.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="SyntaxError: invalid syntax\n"
        ),
    )

    with pytest.raises(ValueError, match="SyntaxError: invalid syntax"):
        run_project_check(tmp_path)


def test_dispatch_check_lints_editable_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "clicknick.services.program_check.run_project_check",
        lambda project_dir: f"checked {project_dir}",
    )
    ctx = DispatchContext(store=_Store(), analysis=_Analysis(tmp_path))

    assert dispatch(ctx, "check").startswith(f"checked {tmp_path}")
