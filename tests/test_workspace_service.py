"""Workspace status and main-window workflow ownership."""

from __future__ import annotations

import threading
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
    needs_comment_upgrade=False,
):
    return SimpleNamespace(
        status=status,
        project_dir=project_dir,
        error=error,
        system_nickname_repairs=system_nickname_repairs,
        needs_comment_upgrade=needs_comment_upgrade,
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

    old_form = get_workspace_status(
        _analysis(AnalysisStatus.FAILED, error="old annotation form", needs_comment_upgrade=True)
    )
    assert old_form.label == "Run Tools > Repairs > Upgrade Project"
    assert old_form.detail == "old annotation form"


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


class _InlineThread:
    def __init__(self, *, target, daemon):
        self.target = target

    def start(self):
        self.target()


def test_queued_build_reads_as_preparing_before_its_thread_runs(tmp_path, monkeypatch) -> None:
    """A refresh in that gap used to stop the polling, leaving the window out of date."""
    from clicknick.services.analysis_service import AnalysisService

    class _NotStarted(_InlineThread):
        def start(self):
            pass

    monkeypatch.setattr("clicknick.connection_session.threading.Thread", _NotStarted)
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session.analysis = AnalysisService()
    session.analysis.mark_failed("Save the project in Click Software first.")

    session._start_analysis_thread(tmp_path, tmp_path / "db")

    assert get_workspace_status(session.analysis).state is WorkspaceState.PREPARING
    assert session.analysis.error is None


def test_finished_build_tells_the_app_with_the_result_in_place(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("clicknick.connection_session.threading.Thread", _InlineThread)
    seen: list[bool] = []
    session = ConnectionSession(
        ClickConnection("1", 2, "Example.ckp"),
        on_build_finished=lambda: seen.append(session.analysis.build.called),
    )
    session.analysis = MagicMock()

    session._start_analysis_thread(tmp_path, tmp_path / "db")

    assert seen == [True]


def test_app_refreshes_on_the_tk_thread_when_a_build_finishes() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._request_ui_refresh = MagicMock()

    app._on_build_finished()

    app.root.after.assert_called_once_with(0, app._request_ui_refresh)
    app._request_ui_refresh.assert_not_called()


def test_failure_before_the_build_starts_does_not_stay_preparing(tmp_path, monkeypatch) -> None:
    from clicknick.services.analysis_service import AnalysisService

    monkeypatch.setattr("clicknick.connection_session.threading.Thread", _InlineThread)

    def broken_selection(_workspace):
        raise OSError("selection unreadable")

    monkeypatch.setattr(
        "clicknick.services.program_check_selection.ProgramCheckSelection", broken_selection
    )
    finished = MagicMock()
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"), on_build_finished=finished)
    session.analysis = AnalysisService()
    results: list[tuple[bool, str | None]] = []

    session._start_analysis_thread(
        tmp_path, tmp_path / "db", on_complete=lambda ok, error: results.append((ok, error))
    )

    assert session.analysis.status is AnalysisStatus.FAILED
    assert session.analysis.error == "OSError: selection unreadable"
    assert results == [(False, "OSError: selection unreadable")]
    finished.assert_called_once_with()
    assert session._build_running is False


def test_new_session_builds_after_the_closed_sessions_build(tmp_path) -> None:
    """Opening another project in one window: both sessions write the same folder."""
    old = ConnectionSession(ClickConnection("1", 2, "Old.ckp"))
    new = ConnectionSession(ClickConnection("1", 2, "New.ckp"))
    old_building = threading.Event()
    release_old = threading.Event()
    order: list[str] = []

    def old_build(*_args, **_kwargs):
        order.append("old start")
        old_building.set()
        release_old.wait(5)
        order.append("old end")
        return False

    def new_build(*_args, **_kwargs):
        order.append("new")
        return True

    old.analysis = MagicMock(build=old_build)
    new.analysis = MagicMock(build=new_build)
    new_done = threading.Event()

    old._start_analysis_thread(tmp_path, tmp_path / "db")
    assert old_building.wait(5)
    old.close()
    new._start_analysis_thread(
        tmp_path, tmp_path / "db", on_complete=lambda _ok, _error: new_done.set()
    )
    assert not new_done.wait(0.1)
    release_old.set()

    assert new_done.wait(5)
    assert order == ["old start", "old end", "new"]


def test_closed_session_drops_its_queued_build_and_tells_the_caller(tmp_path) -> None:
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session.analysis = MagicMock()
    results: list[tuple[bool, str | None]] = []
    done = threading.Event()

    def finished(ok: bool, error: str | None) -> None:
        results.append((ok, error))
        done.set()

    session.close()
    session._start_analysis_thread(tmp_path, tmp_path / "db", on_complete=finished)

    assert done.wait(5)
    session.analysis.build.assert_not_called()
    assert results == [(False, "The project changed while converting; conversion was discarded.")]


def test_scr_files_appearing_after_connect_start_the_build(tmp_path, monkeypatch) -> None:
    """CLICK may still be writing the project when the new session starts."""
    db_path = tmp_path / "SC_.mdb"
    db_path.write_text("db", encoding="utf-8")
    monkeypatch.setattr(
        "clicknick.utils.mdb_shared.find_click_database", lambda **_kwargs: str(db_path)
    )
    monkeypatch.setattr("clicknick.live.session.click_temp_dir", lambda _hwnd: tmp_path)
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    session._start_analysis_thread = MagicMock()
    root = MagicMock()

    session.start_analysis(root)
    session._start_analysis_thread.assert_not_called()
    assert session.analysis.status is AnalysisStatus.FAILED

    (tmp_path / "Scr1.tmp").write_text("ladder", encoding="utf-8")
    session.scr_watcher._check()
    session._start_analysis_thread.assert_called_once_with(tmp_path, db_path)
    session.scr_watcher.stop()


def test_saved_program_reports_what_can_be_compared(tmp_path) -> None:
    session = ConnectionSession(ClickConnection("1", 2, "Example.ckp"))
    assert session.saved_program().csv_dir is None

    project = tmp_path / "pyrung_project"
    session.analysis = _analysis(AnalysisStatus.BUILDING, project)
    session.analysis.generation = 3
    (project / "csv").mkdir(parents=True)
    building = session.saved_program()
    assert building.building is True
    assert building.csv_dir is None

    session.analysis.status = AnalysisStatus.READY
    ready = session.saved_program()
    assert ready.csv_dir == project / "csv"
    assert ready.generation == 3
    assert ready != building

    session.analysis = _analysis(AnalysisStatus.FAILED, error="broken")
    session.analysis.generation = 4
    failed = session.saved_program()
    assert failed.csv_dir is None
    assert "main window" in failed.note


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


def test_guided_paste_shows_each_folder_in_one_window(monkeypatch, tmp_path: Path) -> None:
    opened: list[MagicMock] = []

    def _open(*_args, **kwargs) -> MagicMock:
        opened.append(MagicMock(opened_with=kwargs))
        return opened[-1]

    monkeypatch.setattr("clicknick.views.guided_paste_window.GuidedPasteWindow", _open)
    app = ClickNickApp.__new__(ClickNickApp)
    app.root = MagicMock()
    app._guided_paste_windows = {}
    folder, source = tmp_path / "csv_output", tmp_path / "src" / "plc"

    # Nothing to paste and no window showing the folder: none is opened
    app._show_guided_paste(folder, source, None, None, False)
    assert opened == []

    app._show_guided_paste(folder, source, "main.csv", [3], True)
    assert len(opened) == 1
    assert opened[0].opened_with["source_dir"] == source
    assert opened[0].opened_with["select"] == ("main.csv", [3])

    # Exported again: the same window reads the folder again
    app._show_guided_paste(folder, source, None, None, True)
    assert len(opened) == 1
    opened[0].reload.assert_called_once_with(source_dir=source, select=None)

    # A closed window is forgotten; another folder gets its own
    opened[0].winfo_exists.return_value = False
    app._show_guided_paste(folder)
    app._show_guided_paste(tmp_path / "other")
    assert len(opened) == 3
    assert opened[1].opened_with["source_dir"] is None


def test_successful_main_window_reload_clears_changed_rung_count() -> None:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app._update_status = MagicMock()
    app._session = SimpleNamespace(record_rung_stage=MagicMock())
    proposal = MagicMock(shows_workspace_proposal=True)
    folder = MagicMock(shows_workspace_proposal=False)
    app._guided_paste_windows = {Path("csv_output"): proposal, Path("export"): folder}

    app._workspace_reload_finished(True, None)

    app._session.record_rung_stage.assert_called_once_with(0)
    app._update_status.assert_called_once_with("Workspace reloaded from CLICK", "connected")
    # The discarded edits are no longer offered for pasting; an unrelated folder stays
    proposal.destroy.assert_called_once_with()
    folder.destroy.assert_not_called()


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
