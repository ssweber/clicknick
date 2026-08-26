"""Console startup: what happens when the pyrung project isn't ready yet.

A build rewrites the generated project folder in place, so anything reading it
mid-build sees a half-written project. These pin the behaviour that a rebuild
racing the console is a *wait*, while a genuine failure is reported with a
retry — the distinction that kept regressing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

tk = pytest.importorskip("tkinter")

from clicknick.services.analysis_service import (  # noqa: E402
    AnalysisResult,
    AnalysisService,
    AnalysisStatus,
)


@pytest.fixture(scope="module")
def tk_root():
    """One root for the whole module.

    Creating and tearing down a Tk root per test is unreliable — it fails
    intermittently, skipping a different test on each run.
    """
    root = None
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def _ready_service(project_dir: Path, *, generation: int = 1) -> AnalysisService:
    """A service reporting a complete, usable project on disk."""
    (project_dir / "run.py").write_text("x", encoding="utf-8")
    svc = AnalysisService()
    svc._result = AnalysisResult(graph=MagicMock(), program=MagicMock(), project_dir=project_dir)
    svc._status = AnalysisStatus.READY
    svc._generation = generation
    return svc


def _quiesce(win) -> None:
    """Stop a console's pending timers so it cannot outlive its test."""
    win._destroyed = True
    if win._analysis_after_id is not None:
        try:
            win.after_cancel(win._analysis_after_id)
        except Exception:
            pass
        win._analysis_after_id = None


@pytest.fixture()
def console(tk_root, monkeypatch):
    """Factory for ConsoleWindows, with the DAP launch stubbed out.

    Teardown runs even when a test fails mid-assertion — a console left with a
    live `after` timer breaks whichever test runs next.
    """
    import clicknick.services.dap_service as dap_mod

    monkeypatch.setattr(dap_mod, "DapService", MagicMock())

    from clicknick.views.console_window import ConsoleWindow

    # Grammar loading is an unrelated background task.  Letting it retain a
    # real Tk window beyond fixture teardown can finalize the window's Tk
    # variables on that worker thread.
    monkeypatch.setattr(ConsoleWindow, "_load_grammar", lambda _self: None)

    built = []

    def _make(analysis, on_retry=None):
        win = ConsoleWindow(
            tk_root,
            get_store=lambda: None,
            get_analysis=lambda: analysis,
            get_click_hwnd=lambda: None,
            get_mdb_path=lambda: None,
            get_synced_pending=lambda: 0,
            on_retry_analysis=on_retry,
        )
        built.append(win)
        win.update_idletasks()
        return win

    yield _make

    for win in built:
        _quiesce(win)
        try:
            win.destroy()
        except tk.TclError:
            pass


def _output(win) -> str:
    return win._output.get("1.0", "end-1c")


def _waiting(win) -> bool:
    return win._analysis_after_id is not None


def _retry_visible(win) -> bool:
    return bool(win._retry_btn.winfo_manager())


class TestConsoleStartup:
    def test_build_in_flight_waits_without_error(self, console, tmp_path):
        """The folder is rubble mid-build even though the old result looks fine."""
        svc = _ready_service(tmp_path)
        svc._status = AnalysisStatus.BUILDING

        win = console(svc)
        assert _waiting(win)
        assert not _retry_visible(win)
        assert _output(win).strip() == ""

    def test_failed_conversion_is_reported_with_retry(self, console, tmp_path):
        svc = AnalysisService()
        svc.mark_failed("pyrung conversion crashed", "Traceback...\nValueError: boom")

        win = console(svc)
        assert not _waiting(win)
        assert _retry_visible(win)
        assert "pyrung conversion crashed" in _output(win)
        assert "ValueError: boom" in _output(win)

    def test_launch_failure_during_rebuild_waits(self, console, tmp_path):
        """A rebuild that starts *and finishes* mid-launch must not surface as an error.

        This is the "No module named 'subroutines'" case: the launch read a
        half-written project, but by the time the failure arrives the rebuild has
        completed, so the status alone looks healthy.
        """
        svc = _ready_service(tmp_path, generation=5)
        win = console(svc)
        assert win._launch_generation == 5

        svc._generation = 6  # a rebuild ran under the launch
        svc._status = AnalysisStatus.READY  # ...and already finished
        win._on_dap_failed(
            RuntimeError("DAP launch failed: Internal adapter error: No module named 'subroutines'")
        )
        win.update_idletasks()

        assert _waiting(win), "raced launch should wait and relaunch"
        assert not _retry_visible(win)
        assert "failed to start" not in _output(win)

    def test_launch_failure_without_rebuild_is_reported(self, console, tmp_path):
        svc = _ready_service(tmp_path, generation=5)
        win = console(svc)

        win._on_dap_failed(RuntimeError("DAP launch failed: something genuinely broken"))
        win.update_idletasks()

        assert not _waiting(win)
        assert _retry_visible(win)
        assert "something genuinely broken" in _output(win)

    def test_waiting_is_bounded_by_the_timeout(self, console, tmp_path):
        """Every wait path routes through _wait_for_analysis, so none can spin forever."""
        from clicknick.views.console_window import _ANALYSIS_POLL_MS, _ANALYSIS_TIMEOUT_MS

        svc = _ready_service(tmp_path)
        svc._status = AnalysisStatus.BUILDING  # never completes
        win = console(svc)

        for _ in range(int(_ANALYSIS_TIMEOUT_MS / _ANALYSIS_POLL_MS) + 5):
            if win._analysis_after_id is None:
                break
            win.after_cancel(win._analysis_after_id)
            win._analysis_after_id = None
            win._poll_analysis()

        assert not _waiting(win), "poll loop never terminated"
        assert "timed out" in _output(win)
        assert _retry_visible(win)

    def test_retry_rebuilds_and_clears_the_wait(self, console, tmp_path):
        svc = AnalysisService()
        svc.mark_failed("no ladder files")
        calls: list[str] = []

        win = console(svc, on_retry=lambda: calls.append("rebuild"))
        assert _retry_visible(win)

        win._analysis_waited_ms = 9999
        win._retry_startup()
        win.update_idletasks()

        assert calls == ["rebuild"]
        assert win._analysis_waited_ms == 0
