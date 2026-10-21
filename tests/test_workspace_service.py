"""Workspace status and main-window workflow ownership."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.services.analysis_service import AnalysisStatus
from clicknick.services.project_workspace import record_generated_plc_source
from clicknick.services.workspace_service import (
    WorkspaceState,
    get_workspace_status,
)


def _analysis(
    status,
    project_dir: Path | None = None,
    error: str | None = None,
    system_nickname_repairs=(),
):
    return SimpleNamespace(
        status=status,
        project_dir=project_dir,
        error=error,
        system_nickname_repairs=system_nickname_repairs,
        is_available=status is AnalysisStatus.READY,
    )


def _clean_workspace(tmp_path: Path) -> Path:
    project = tmp_path / "pyrung_project"
    source = project / "src" / "plc"
    source.mkdir(parents=True)
    (source / "main.py").write_text("generated\n", encoding="utf-8")
    record_generated_plc_source(project)
    return project


def test_workspace_status_covers_unavailable_preparing_and_failure() -> None:
    assert get_workspace_status(None).state is WorkspaceState.UNAVAILABLE
    assert (
        get_workspace_status(_analysis(AnalysisStatus.BUILDING)).state is WorkspaceState.PREPARING
    )

    failed = get_workspace_status(_analysis(AnalysisStatus.FAILED, error="conversion broke"))
    assert failed.state is WorkspaceState.FAILED
    assert failed.label == "Build failed"
    assert failed.detail == "conversion broke"

    repairable = get_workspace_status(
        _analysis(
            AnalysisStatus.FAILED,
            error="system nickname mismatch",
            system_nickname_repairs=(object(),),
        )
    )
    assert repairable.label == "System names need repair"


def test_workspace_status_reports_clean_modified_and_changed_rungs(tmp_path: Path) -> None:
    project = _clean_workspace(tmp_path)
    analysis = _analysis(AnalysisStatus.READY, project)

    assert get_workspace_status(analysis).label == "Clean"

    (project / "src" / "plc" / "main.py").write_text("proposal\n", encoding="utf-8")
    assert get_workspace_status(analysis).label == "Modified"

    changed = get_workspace_status(analysis, staged_rungs=4)
    assert changed.state is WorkspaceState.MODIFIED
    assert changed.label == "4 changed rungs"
    assert changed.changed_rungs == 4


def test_generated_workspace_opens_after_analysis_failure(tmp_path: Path) -> None:
    project = _clean_workspace(tmp_path)
    analysis = _analysis(AnalysisStatus.FAILED, project, error="reset needs a condition")
    status = get_workspace_status(analysis)
    assert status.label == "Analysis failed"
    assert status.detail == "reset needs a condition"

    app = ClickNickApp.__new__(ClickNickApp)

    app._request_ui_refresh = MagicMock()
    app._session = SimpleNamespace(analysis=analysis)
    app._workspace_config = None
    app._open_folder = MagicMock()

    assert app._open_workspace_menu_options() == ("Open Temporary Workspace", "normal")
    app._open_workspace()
    app._open_folder.assert_called_once_with(
        project, title="Open Workspace", unavailable="Workspace is not available"
    )


class _Root:
    def after(self, _delay: int, callback):
        callback()
        return "after-id"


def test_connection_session_reload_uses_saved_click_project(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "SC_.mdb"
    db_path.write_text("db", encoding="utf-8")
    (tmp_path / "Scr1.tmp").write_text("ladder", encoding="utf-8")
    monkeypatch.setattr(
        "clicknick.utils.mdb_shared.find_click_database", lambda **_kwargs: str(db_path)
    )

    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session._start_analysis_thread = MagicMock()
    callback = MagicMock()
    root = _Root()

    assert session.reload_workspace_from_click(root, callback) is True
    session._start_analysis_thread.assert_called_once_with(
        tmp_path,
        db_path,
        root=root,
        on_complete=callback,
    )


def test_connection_session_reload_reports_unsaved_click_project(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "SC_.mdb"
    db_path.write_text("db", encoding="utf-8")
    monkeypatch.setattr(
        "clicknick.utils.mdb_shared.find_click_database", lambda **_kwargs: str(db_path)
    )

    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    callback = MagicMock()

    assert session.reload_workspace_from_click(_Root(), callback) is False
    callback.assert_called_once_with(
        False,
        "No saved ladder files (Scr*.tmp) in the project folder. "
        "Save the project in Click Software first.",
    )


def test_connection_session_builds_into_configured_workspace(tmp_path, monkeypatch) -> None:
    scr_folder = tmp_path / "click-temp"
    workspace = tmp_path / "durable" / "Example Workspace"
    db_path = scr_folder / "SC_.mdb"
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"), workspace_dir=workspace)
    session.analysis = MagicMock()

    class _InlineThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    monkeypatch.setattr("clicknick.connection_session.threading.Thread", _InlineThread)

    session._start_analysis_thread(scr_folder, db_path)

    session.analysis.build.assert_called_once_with(
        scr_folder,
        db_path,
        persist_dir=workspace.resolve(),
        workspace_kind="persistent",
    )


def test_connection_session_labels_click_folder_as_temporary(tmp_path, monkeypatch) -> None:
    scr_folder = tmp_path / "click-temp"
    db_path = scr_folder / "SC_.mdb"
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session.analysis = MagicMock()

    class _InlineThread:
        def __init__(self, *, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    monkeypatch.setattr("clicknick.connection_session.threading.Thread", _InlineThread)

    session._start_analysis_thread(scr_folder, db_path)

    session.analysis.build.assert_called_once_with(
        scr_folder,
        db_path,
        persist_dir=scr_folder / "pyrung_project",
        workspace_kind="temporary",
    )


def test_switching_workspace_moves_and_restarts_the_simulation(tmp_path, monkeypatch) -> None:
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session.analysis = MagicMock()
    session.simulation = MagicMock()
    monkeypatch.setattr(session, "_simulation_key", lambda: "Line1")
    workspace = tmp_path / "Example Workspace"

    session.use_workspace(workspace)

    session.analysis.invalidate.assert_called_once_with()
    session.simulation.set_state_location.assert_called_once_with("Line1", workspace.resolve())
    session.simulation.restart.assert_called_once_with()
    assert session.workspace_dir == workspace.resolve()


def test_closing_the_connection_closes_the_simulator_first() -> None:
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    order: list[str] = []
    session.simulator = MagicMock(_on_close=lambda: order.append("simulator"))
    simulation = MagicMock(close=lambda: order.append("simulation"))
    session.simulation = simulation

    session.close()

    assert order == ["simulator", "simulation"]
    assert session.simulation is None


def test_main_window_preview_changes_uses_consolidated_workflow() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app.root = MagicMock()
    app._update_status = MagicMock()
    app._live_server = SimpleNamespace(dispatch_now=MagicMock(return_value="opened"))
    app._session = SimpleNamespace(
        analysis=_analysis(AnalysisStatus.READY),
        staged_rungs=4,
    )
    app._get_workspace_status = MagicMock(
        return_value=SimpleNamespace(label="4 changed rungs", changed_rungs=4)
    )

    app._workspace_rung_apply()

    app._live_server.dispatch_now.assert_called_once_with("rung apply")
    app._update_status.assert_called_once_with("Previewing 4 changed rungs", "connected")


def test_successful_main_window_reload_clears_changed_rung_count() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app._update_status = MagicMock()
    app._session = SimpleNamespace(record_rung_stage=MagicMock())

    app._workspace_reload_finished(True, None)

    app._session.record_rung_stage.assert_called_once_with(0)
    app._update_status.assert_called_once_with("Workspace reloaded from CLICK", "connected")


def test_main_window_reload_ignores_completion_from_replaced_session(monkeypatch) -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app.root = MagicMock()
    app._update_status = MagicMock()
    app._get_workspace_status = MagicMock(
        return_value=SimpleNamespace(state=WorkspaceState.MODIFIED)
    )
    old_session = SimpleNamespace(reload_workspace_from_click=MagicMock())
    app._session = old_session
    monkeypatch.setattr("clicknick.app.messagebox.askokcancel", lambda *_a, **_k: True)

    app._workspace_reload_from_click()
    callback = old_session.reload_workspace_from_click.call_args.args[1]
    app._session = SimpleNamespace(record_rung_stage=MagicMock())
    app._workspace_reload_finished = MagicMock()

    callback(True, None)

    app._workspace_reload_finished.assert_not_called()


def test_analysis_builds_run_one_at_a_time_and_coalesce(tmp_path) -> None:
    """Requests made during a build collapse into one follow-up of the latest inputs."""
    import threading

    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []

    def build(scr_folder, db_path, **_kwargs):
        calls.append(scr_folder)
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(timeout=10)
        return True

    session.analysis = MagicMock()
    session.analysis.build.side_effect = build
    results = []
    done = threading.Event()

    def record(name):
        def on_complete(ok, error):
            results.append((name, ok, error))
            if len(results) == 3:
                done.set()

        return on_complete

    session._start_analysis_thread(tmp_path / "a", tmp_path / "db", on_complete=record("a"))
    assert first_started.wait(timeout=10)
    session._start_analysis_thread(tmp_path / "b", tmp_path / "db", on_complete=record("b"))
    session._start_analysis_thread(tmp_path / "c", tmp_path / "db", on_complete=record("c"))
    release_first.set()
    assert done.wait(timeout=10)

    assert calls == [tmp_path / "a", tmp_path / "c"]
    assert sorted(results) == [("a", True, None), ("b", True, None), ("c", True, None)]


def test_superseded_build_reports_failure_and_skips_selection_sync(tmp_path, monkeypatch) -> None:
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session.analysis = MagicMock()
    session.analysis.build.return_value = False
    selection = MagicMock()
    monkeypatch.setattr(
        "clicknick.services.program_check_selection.ProgramCheckSelection",
        lambda _workspace: selection,
    )

    class _InlineThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("clicknick.connection_session.threading.Thread", _InlineThread)
    callback = MagicMock()

    session._start_analysis_thread(tmp_path, tmp_path / "db", on_complete=callback)

    selection.sync.assert_not_called()
    ok, error = callback.call_args.args
    assert ok is False and "changed while converting" in error
