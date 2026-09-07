"""Exercise folding, full-report copy, and refresh with real Tk text widgets."""

from types import SimpleNamespace

import pytest
from pyrung.core.validation import FindingDisplay

from clicknick.services.program_check_preferences import ProgramCheckPreferences
from clicknick.views.analysis_report_window import AnalysisReportData, AnalysisReportWindow

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    yield root
    root.destroy()


def _data(code="RUNG_CONTRADICTION", problem="Mode cannot satisfy both conditions."):
    return AnalysisReportData(
        grouped_findings={
            code: [FindingDisplay(code=code, severity="error", problem=problem, hint="Use OR.")]
        },
        project_name="Mixer",
    )


@pytest.fixture
def report_window(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "clicknick.views.analysis_report_window.messagebox.showinfo", lambda *_a, **_kw: None
    )
    windows = []

    def create(data=None, **kwargs):
        window = AnalysisReportWindow(
            tk_root,
            data or _data(),
            preferences=ProgramCheckPreferences(tmp_path / "check-program.json"),
            **kwargs,
        )
        window.window.withdraw()
        windows.append(window)
        return window

    yield create
    for window in windows:
        if window.window.winfo_exists():
            window.window.destroy()


def _is_hidden(window, code):
    _header, body, _expanded = window._sections[code]
    return window._text.tk.getboolean(window._text.tag_cget(body, "elide"))


def test_first_time_help_is_remembered_and_help_button_reopens_it(report_window, monkeypatch):
    messages = []
    monkeypatch.setattr(
        "clicknick.views.analysis_report_window.messagebox.showinfo",
        lambda title, text, **kwargs: messages.append((title, text)),
    )
    window = report_window()
    window.window.update_idletasks()
    assert len(messages) == 1
    assert messages[0][0] == "First-Time Tips"
    assert "core set" in messages[0][1]
    assert "Choose Checks" in messages[0][1]
    assert "it still runs" in messages[0][1]
    assert "Save in CLICK" in messages[0][1]
    window.window.destroy()
    reopened = report_window()
    reopened.window.update_idletasks()
    assert len(messages) == 1
    reopened._help_btn.invoke()
    assert len(messages) == 2
    assert messages[1] == ("Check Program Help", messages[0][1])


def test_help_settings_failure_does_not_prevent_report_display(report_window, tmp_path):
    window = report_window()
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied", encoding="utf-8")
    window._help_seen_path = blocked_parent / "popup_seen"
    window.window.update_idletasks()
    assert "Mode cannot satisfy both conditions." in window._text.get("1.0", "end")
    window._help_btn.invoke()


def test_folding_persists_and_copy_includes_hidden_findings(report_window):
    window = report_window()
    assert not _is_hidden(window, "RUNG_CONTRADICTION")
    assert _is_hidden(window, "__passed__")
    original_summary = window._summary_line
    window._toggle_section("RUNG_CONTRADICTION")
    assert _is_hidden(window, "RUNG_CONTRADICTION")
    assert window._summary_line == original_summary
    assert "1 error" in original_summary
    window._copy_report()
    assert "Mode cannot satisfy both conditions." in window.window.clipboard_get()
    assert "Use OR." in window.window.clipboard_get()
    header, body, _ = window._sections["RUNG_CONTRADICTION"]
    start = window._text.tag_ranges(header)[0]
    assert window._text.get(start, f"{start} lineend").startswith(">")
    assert body not in window._text.tag_names(start)
    window.window.destroy()
    reopened = report_window()
    assert _is_hidden(reopened, "RUNG_CONTRADICTION")
    reopened._toggle_section("RUNG_CONTRADICTION")
    assert not _is_hidden(reopened, "RUNG_CONTRADICTION")


def test_refresh_retains_choice_after_rule_passes_and_fails_again(report_window):
    window = report_window()
    window._toggle_section("RUNG_CONTRADICTION")
    window._show_data(AnalysisReportData())
    assert window._summary_line == "All checks passed"
    window._show_data(_data())
    assert _is_hidden(window, "RUNG_CONTRADICTION")
    window._show_data(_data("NEW_RULE"))
    assert not _is_hidden(window, "NEW_RULE")


def test_rerun_updates_existing_window_and_keyboard_unfolds(report_window):
    calls = []

    def rerun():
        calls.append(True)
        return _data(problem="Updated finding.")

    window = report_window(rerun=rerun)
    window._toggle_section("RUNG_CONTRADICTION")
    window._run_checks()
    assert window._run_btn.instate(["disabled"])
    window.window.after_cancel(window._run_after_id)
    window._finish_run_checks()
    assert calls == [True]
    assert window._run_btn.instate(["!disabled"])
    assert "Updated finding." in window._text.get("1.0", "end")
    assert _is_hidden(window, "RUNG_CONTRADICTION")
    window._toggle_active(True)
    assert not _is_hidden(window, "RUNG_CONTRADICTION")
    window._move_section(1)
    assert window._active_section == "__passed__"


def test_failed_refresh_retains_previous_results(report_window):
    window = report_window(rerun=lambda: None)
    window._finish_run_checks()
    assert "previous results" in window._source.cget("text")
    assert "Mode cannot satisfy both conditions." in window._text.get("1.0", "end")


def test_future_registry_rules_and_severities_render_and_remember(report_window, monkeypatch):
    monkeypatch.setattr(
        "pyrung.core.validation.ordered_rules",
        lambda: [SimpleNamespace(code="FUTURE_RULE", title="A new check", severity="future")],
    )
    window = report_window(_data("FUTURE_RULE"))
    assert "A new check" in window._text.get("1.0", "end")
    assert "1 warning" in window._summary_line
    window._toggle_section("FUTURE_RULE")
    window._show_data(_data("UNKNOWN_RULE"))
    assert "UNKNOWN_RULE" in window._text.get("1.0", "end")
    assert "1 error" in window._summary_line
    assert not _is_hidden(window, "UNKNOWN_RULE")
    window._show_data(_data("FUTURE_RULE"))
    assert _is_hidden(window, "FUTURE_RULE")


def test_report_separates_passed_and_not_run_and_copies_both(report_window):
    data = AnalysisReportData(checked_rules=frozenset({"RUNG_CONTRADICTION"}))
    window = report_window(data)
    assert "1 selected checks passed" in window._summary_line
    assert "not run" in window._summary_line
    assert _is_hidden(window, "__not_run__")
    window._copy_report()
    copied = window.window.clipboard_get()
    assert "NOT RUN" in copied
    assert "Comparison May Read Backwards" in copied
    window._show_data(AnalysisReportData(checked_rules=frozenset()))
    assert "No checks selected" in window._summary_line
    assert "passed" not in window._summary_line
    assert "__passed__" not in window._sections
