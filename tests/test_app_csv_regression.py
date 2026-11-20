"""Regression tests for app state transitions around CSV loading."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_controller import ConnectionController
from clicknick.connection_session import ClickConnection, ConnectionSession
from clicknick.data_session import DataSession
from clicknick.services.workspace_mirror import ProjectWorkspaceConfig


class FakeVar:
    """Minimal Tk-like variable for get/set in unit tests."""

    def __init__(self, value: str = ""):
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class FakeCsvDataSource:
    """A stand-in for the CSV data source in load_csv tests."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path


class FakeAddressStore:
    """A stand-in for AddressStore in load_csv tests."""

    def __init__(self, data_source=None, *, is_database: bool = False, unsaved: bool = False):
        self.data_source = data_source
        self.is_database = is_database
        self._unsaved = unsaved
        self.load_initial_data = MagicMock()
        self.start_file_monitoring = MagicMock()
        self.add_sync_listener = MagicMock()
        self.stop_file_monitoring = MagicMock()
        self.save_all_changes = MagicMock()

    def has_unsaved_changes(self) -> bool:
        return self._unsaved


class FakeEditor:
    def __init__(self) -> None:
        self.closed = False

    def commit_open_cell_editor(self) -> bool:
        return True

    def close_without_prompt(self) -> None:
        self.closed = True


_MY_PROJECT = ClickConnection("111", 222, "MyProject.ckp")


def _session(click: ClickConnection = _MY_PROJECT):
    """Return a session on *click* that records its close() call."""
    session = ConnectionSession(click)
    session.close = MagicMock(wraps=session.close)
    return session


def _make_app_stub() -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app._session = _session()
    app._data = None
    app._update_status = MagicMock()
    app.root = MagicMock()
    app.nickname_manager = SimpleNamespace(set_store=MagicMock())
    app.selected_instance_var = FakeVar("MyProject.ckp")
    connection = app._connection = ConnectionController(app)
    connection._on_data_ready = MagicMock()
    connection.monitoring = False
    connection.refresh_click_instances = MagicMock()
    return app


def _patch_csv_loading(monkeypatch) -> None:
    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", FakeCsvDataSource)
    monkeypatch.setattr("clicknick.connection_controller.AddressStore", FakeAddressStore)


def test_load_csv_with_stale_connection_skips_monitoring_and_clears_connection(monkeypatch):
    _patch_csv_loading(monkeypatch)
    app = _make_app_stub()
    app.selected_instance_var = FakeVar("OldProject.ckp")
    app._session = session = _session(ClickConnection("1234", 5678, "OldProject.ckp"))
    app.detector = SimpleNamespace(check_window_exists=lambda _pid: False)

    result = app._connection.load_csv("C:/tmp/NicknameExport.csv")

    assert result is True
    assert app._connection._on_data_ready.call_count == 0
    # The window is gone, so its session closes, and so does everything the session runs.
    session.close.assert_called_once()
    assert app._session is None
    assert app.selected_instance_var.get() == ""
    assert isinstance(app._data.store, FakeAddressStore)
    assert app.using_database is False
    app._data.store.start_file_monitoring.assert_called_once_with(app.root)
    app.nickname_manager.set_store.assert_called_once_with(app._data.store)


@pytest.mark.parametrize(
    ("answer", "replaced"),
    [(None, False), (False, True), (True, True)],
    ids=["cancel", "discard", "save"],
)
def test_load_csv_over_unsaved_edits_prompts_and_closes_old_windows(monkeypatch, answer, replaced):
    _patch_csv_loading(monkeypatch)
    prompts = []
    monkeypatch.setattr(
        "tkinter.messagebox.askyesnocancel", lambda *args, **kwargs: prompts.append(args) or answer
    )
    app = _make_app_stub()
    app.detector = SimpleNamespace(check_window_exists=lambda _pid: True)
    old_store = FakeAddressStore(is_database=True, unsaved=True)
    app._data = DataSession(old_store)
    editor = FakeEditor()
    app._data.register_editor(editor)

    result = app._connection.load_csv("C:/tmp/Other.csv")

    assert len(prompts) == 1
    assert result is replaced
    if replaced:
        assert app._data.store is not old_store
        assert editor.closed
        old_store.stop_file_monitoring.assert_called_once()
        assert old_store.save_all_changes.call_count == (1 if answer else 0)
    else:
        assert app._data.store is old_store
        assert not editor.closed
        old_store.stop_file_monitoring.assert_not_called()
        app.nickname_manager.set_store.assert_not_called()


def test_handle_window_closed_keeps_csv_data():
    app = _make_app_stub()
    store = FakeAddressStore(is_database=False)
    app._data = DataSession(store)
    session = app._session
    app.root = SimpleNamespace(after=MagicMock())

    app._connection._handle_window_closed()

    session.close.assert_called_once()
    assert app._session is None
    assert app._data.store is store
    store.stop_file_monitoring.assert_not_called()
    app.nickname_manager.set_store.assert_not_called()
    assert app._click is None
    assert app.selected_instance_var.get() == ""
    app.root.after.assert_called_once_with(2000, app._connection.refresh_click_instances)


def test_handle_window_closed_closes_database_data():
    app = _make_app_stub()
    store = FakeAddressStore(is_database=True)
    app._data = DataSession(store)
    editor = FakeEditor()
    app._data.register_editor(editor)
    session = app._session
    app.root = SimpleNamespace(after=MagicMock())

    app._connection._handle_window_closed()

    session.close.assert_called_once()
    assert app._session is None
    assert app._data is None
    assert editor.closed
    store.stop_file_monitoring.assert_called_once()
    app.nickname_manager.set_store.assert_called_once_with(None)


def test_start_monitoring_twice_runs_one_loop():
    connection = _make_app_stub()._connection
    connection._monitor_task = MagicMock()

    assert connection._start_monitoring_internal()
    assert connection._start_monitoring_internal()

    connection._monitor_task.assert_called_once()


def test_project_change_loads_new_database_off_the_ui_thread(monkeypatch):
    def no_sync_store(*_args, **_kwargs):
        raise AssertionError("project change must not build a store on the Tk thread")

    monkeypatch.setattr("clicknick.connection_controller.AddressStore", no_sync_store)
    app = _make_app_stub()
    app._data = DataSession(FakeAddressStore(is_database=True))
    app.instances_combobox = {}
    # Stub the pairing lookup so that the test does not read CLICK's folder.
    monkeypatch.setattr(ConnectionSession, "load_workspace_pairing", lambda _self: None)
    app._connection._load_instance_database = MagicMock()
    app.nickname_manager.has_database_backend = lambda: True

    app._connection._handle_project_change("CLICK - Next.ckp", "Next.ckp")

    app._connection._load_instance_database.assert_called_once_with(app._session)
    assert app._click == ClickConnection("111", 222, "Next.ckp")
    assert app._data is None


@pytest.mark.parametrize("is_database", [True, False], ids=["database", "csv"])
def test_only_a_database_save_counts_as_synced_to_click(is_database):
    app = _make_app_stub()
    app._data = DataSession(FakeAddressStore(is_database=is_database))
    app._session.record_sync = MagicMock()

    app._on_editor_synced({1, 2})

    assert app._session.record_sync.call_count == (1 if is_database else 0)


def test_a_sync_rebuilds_a_build_that_needed_upgrade_project():
    app = _make_app_stub()
    app._data = DataSession(FakeAddressStore(is_database=True))
    app._start_analysis_build = MagicMock()
    app._session.record_sync = MagicMock()
    app._session.analysis = SimpleNamespace(system_nickname_repairs=(), needs_comment_upgrade=True)

    app._on_editor_synced({1})

    app._start_analysis_build.assert_called_once_with()


def test_handle_window_closed_warns_when_workspace_setup_held_a_choice_not_applied(monkeypatch):
    warning = MagicMock()
    monkeypatch.setattr("clicknick.connection_controller.messagebox.showwarning", warning)
    app = _make_app_stub()
    app._session.setup_window = MagicMock()
    app._session.pending_workspace = ProjectWorkspaceConfig("MyProject", Path("Chosen"))
    app.root = SimpleNamespace(after=MagicMock())

    app._connection._handle_window_closed()

    warning.assert_called_once()
    assert warning.call_args.args[0] == "Workspace"
    assert "was not applied" in warning.call_args.args[1]
    assert warning.call_args.kwargs["parent"] is app.root


def test_handle_window_closed_shows_no_warning_without_a_pending_choice(monkeypatch):
    warning = MagicMock()
    monkeypatch.setattr("clicknick.connection_controller.messagebox.showwarning", warning)
    app = _make_app_stub()
    app.root = SimpleNamespace(after=MagicMock())

    app._connection._handle_window_closed()

    warning.assert_not_called()
    app._update_status.assert_called_once_with("⚠ The CLICK window closed", "error")
