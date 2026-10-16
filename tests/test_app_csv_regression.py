"""Regression tests for app state transitions around CSV loading."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clicknick.app import ClickNickApp
from clicknick.connection_session import ClickConnection
from clicknick.data_session import DataSession


class FakeVar:
    """Minimal Tk-like variable for get/set in unit tests."""

    def __init__(self, value: str = ""):
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class FakeCsvDataSource:
    """Minimal CSV data source stand-in for app.load_csv tests."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path


class FakeAddressStore:
    """Minimal AddressStore stand-in for app.load_csv tests."""

    def __init__(self, data_source=None, *, is_database: bool = False, unsaved: bool = False):
        self.data_source = data_source
        self.is_database = is_database
        self._unsaved = unsaved
        self.load_initial_data = MagicMock()
        self.start_file_monitoring = MagicMock()
        self.stop_file_monitoring = MagicMock()
        self.save_all_changes = MagicMock()

    def has_unsaved_changes(self) -> bool:
        return self._unsaved


class FakeEditor:
    def __init__(self) -> None:
        self.closed = False

    def close_without_prompt(self) -> None:
        self.closed = True


def _make_app_stub() -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app._request_ui_refresh = MagicMock()
    app._session = None
    app._data = None
    app._update_status = MagicMock()
    app.start_monitoring = MagicMock()
    app.stop_monitoring = MagicMock()
    app.root = MagicMock()
    app.monitoring = False
    app.nickname_manager = SimpleNamespace(set_store=MagicMock())
    app.selected_instance_var = FakeVar("MyProject.ckp")
    app._click = ClickConnection("111", 222, "MyProject.ckp")
    app.refresh_click_instances = MagicMock()
    return app


def _patch_csv_loading(monkeypatch) -> None:
    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", FakeCsvDataSource)
    monkeypatch.setattr("clicknick.app.AddressStore", FakeAddressStore)


def test_load_csv_with_stale_connection_skips_monitoring_and_clears_connection(monkeypatch):
    _patch_csv_loading(monkeypatch)
    app = _make_app_stub()
    app.csv_path_var = FakeVar("C:/tmp/NicknameExport.csv")
    app.selected_instance_var = FakeVar("OldProject.ckp")
    app._click = ClickConnection("1234", 5678, "OldProject.ckp")
    app.detector = SimpleNamespace(check_window_exists=lambda _pid: False)

    result = app.load_csv()

    assert result is True
    assert app.start_monitoring.call_count == 0
    assert app._click is None
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
    app.csv_path_var = FakeVar("C:/tmp/Other.csv")
    app.detector = SimpleNamespace(check_window_exists=lambda _pid: True)
    old_store = FakeAddressStore(is_database=True, unsaved=True)
    app._data = DataSession(old_store)
    editor = FakeEditor()
    app._data.register_editor(editor)

    result = app.load_csv()

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
    session = SimpleNamespace(close=MagicMock())
    app._session = session
    app.root = SimpleNamespace(after=MagicMock())

    app._handle_window_closed()

    app.stop_monitoring.assert_called_once_with(update_status=False)
    session.close.assert_called_once()
    assert app._session is None
    assert app._data.store is store
    store.stop_file_monitoring.assert_not_called()
    app.nickname_manager.set_store.assert_not_called()
    assert app._click is None
    assert app.selected_instance_var.get() == ""
    app.root.after.assert_called_once_with(2000, app.refresh_click_instances)


def test_handle_window_closed_closes_database_data():
    app = _make_app_stub()
    store = FakeAddressStore(is_database=True)
    app._data = DataSession(store)
    editor = FakeEditor()
    app._data.register_editor(editor)
    session = SimpleNamespace(close=MagicMock())
    app._session = session
    app.root = SimpleNamespace(after=MagicMock())

    app._handle_window_closed()

    session.close.assert_called_once()
    assert app._session is None
    assert app._data is None
    assert editor.closed
    store.stop_file_monitoring.assert_called_once()
    app.nickname_manager.set_store.assert_called_once_with(None)


def test_start_monitoring_twice_runs_one_loop():
    app = _make_app_stub()
    app._monitor_task = MagicMock()

    assert ClickNickApp._start_monitoring_internal(app)
    assert ClickNickApp._start_monitoring_internal(app)

    app._monitor_task.assert_called_once()


def test_project_change_loads_new_database_off_the_ui_thread(monkeypatch):
    def no_sync_store(*_args, **_kwargs):
        raise AssertionError("project change must not build a store on the Tk thread")

    monkeypatch.setattr("clicknick.app.AddressStore", no_sync_store)
    app = _make_app_stub()
    app._data = DataSession(FakeAddressStore(is_database=True))
    app.csv_path_var = FakeVar("")
    app.click_instances = []
    app.instances_combobox = {}
    app._load_workspace_pairing = MagicMock()
    app._load_instance_database = MagicMock()
    app.nickname_manager.has_database_backend = lambda: True

    assert app._handle_project_change("CLICK - Next.ckp", "Next.ckp")

    app._load_instance_database.assert_called_once_with("111", "Next.ckp", 222)
    assert app._click == ClickConnection("111", 222, "Next.ckp")
    assert app._data is None


@pytest.mark.parametrize("is_database", [True, False], ids=["database", "csv"])
def test_only_a_database_save_counts_as_synced_to_click(is_database):
    app = _make_app_stub()
    app._data = DataSession(FakeAddressStore(is_database=is_database))
    app._session = SimpleNamespace(record_sync=MagicMock(), analysis=None)

    app._on_editor_synced({1, 2})

    assert app._session.record_sync.call_count == (1 if is_database else 0)
