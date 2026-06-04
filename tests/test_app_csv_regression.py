"""Regression tests for app state transitions around CSV-only loading."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from clicknick.app import ClickNickApp


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

    def __init__(self, data_source):
        self.data_source = data_source
        self.load_initial_data = MagicMock()
        self.start_file_monitoring = MagicMock()
        self.stop_file_monitoring = MagicMock()


def _make_app_stub() -> ClickNickApp:
    app = ClickNickApp.__new__(ClickNickApp)
    app._session = None
    app._csv_only_store = None
    app._csv_only_dataview = None
    app._update_status = MagicMock()
    app._update_window_title = MagicMock()
    app.start_monitoring = MagicMock()
    app.stop_monitoring = MagicMock()
    app.root = MagicMock()
    app.monitoring = False
    app.using_database = True
    return app


def test_load_csv_with_stale_connection_skips_monitoring_and_clears_connection(monkeypatch):
    monkeypatch.setattr("clicknick.data.data_source.CsvDataSource", FakeCsvDataSource)
    monkeypatch.setattr("clicknick.app.AddressStore", FakeAddressStore)

    app = _make_app_stub()
    app.csv_path_var = FakeVar("C:/tmp/NicknameExport.csv")
    app.selected_instance_var = FakeVar("OldProject.ckp")
    app.connected_click_pid = 1234
    app.connected_click_hwnd = 5678
    app.connected_click_filename = "OldProject.ckp"
    app.detector = SimpleNamespace(check_window_exists=lambda _pid: False)
    app.settings = SimpleNamespace(sort_by_nickname=False)
    app.nickname_manager = SimpleNamespace(
        set_shared_data=MagicMock(),
        apply_sorting=MagicMock(),
    )

    result = app.load_csv()

    assert result is True
    assert app.start_monitoring.call_count == 0
    assert app.connected_click_pid is None
    assert app.connected_click_hwnd is None
    assert app.connected_click_filename is None
    assert app.selected_instance_var.get() == ""
    assert app._csv_only_store is not None
    app.nickname_manager.set_shared_data.assert_called_once()


def test_handle_window_closed_preserves_csv_loaded_store():
    app = _make_app_stub()
    store = SimpleNamespace(
        force_close_all_windows=MagicMock(),
        stop_file_monitoring=MagicMock(),
    )

    app._csv_only_store = store
    app._session = None
    app.nickname_manager = SimpleNamespace(set_shared_data=MagicMock())
    app.selected_instance_var = FakeVar("MyProject.ckp")
    app.connected_click_pid = 111
    app.connected_click_hwnd = 222
    app.connected_click_filename = "MyProject.ckp"
    app.refresh_click_instances = MagicMock()
    app.root = SimpleNamespace(after=MagicMock())

    app._handle_window_closed()

    app.stop_monitoring.assert_called_once_with(update_status=False)
    # CSV store survives — no session means nothing to force_close
    assert app._csv_only_store is store
    app.nickname_manager.set_shared_data.assert_not_called()
    store.force_close_all_windows.assert_not_called()
    assert app.connected_click_pid is None
    assert app.connected_click_hwnd is None
    assert app.connected_click_filename is None
    assert app.selected_instance_var.get() == ""
    app.root.after.assert_called_once_with(2000, app.refresh_click_instances)


def test_handle_window_closed_with_session_csv_detaches():
    """When Click dies but data is CSV-backed, session resources close but store survives."""
    app = _make_app_stub()
    app.using_database = False

    store = SimpleNamespace(
        _windows=[],
        force_close_all_windows=MagicMock(),
        stop_file_monitoring=MagicMock(),
    )
    session = SimpleNamespace(
        store=store,
        dataview=None,
        console=None,
        force_close=MagicMock(),
        detach_click_resources=MagicMock(),
    )
    app._session = session
    app.nickname_manager = SimpleNamespace(set_shared_data=MagicMock())
    app.selected_instance_var = FakeVar("MyProject.ckp")
    app.connected_click_pid = 111
    app.connected_click_hwnd = 222
    app.connected_click_filename = "MyProject.ckp"
    app.refresh_click_instances = MagicMock()
    app.root = SimpleNamespace(after=MagicMock())

    app._handle_window_closed()

    session.detach_click_resources.assert_called_once()
    assert app._csv_only_store is store
    assert app._session is None
    app.nickname_manager.set_shared_data.assert_not_called()


def test_handle_window_closed_with_session_mdb_force_closes():
    """When Click dies and data is MDB-backed, everything is torn down."""
    app = _make_app_stub()
    app.using_database = True

    session = SimpleNamespace(
        store=SimpleNamespace(_windows=[], force_close_all_windows=MagicMock()),
        dataview=None,
        console=None,
        force_close=MagicMock(),
        detach_click_resources=MagicMock(),
    )
    app._session = session
    app.nickname_manager = SimpleNamespace(set_shared_data=MagicMock())
    app.selected_instance_var = FakeVar("MyProject.ckp")
    app.connected_click_pid = 111
    app.connected_click_hwnd = 222
    app.connected_click_filename = "MyProject.ckp"
    app.refresh_click_instances = MagicMock()
    app.root = SimpleNamespace(after=MagicMock())

    app._handle_window_closed()

    session.force_close.assert_called_once()
    app.nickname_manager.set_shared_data.assert_called_once_with(None)
    assert app._session is None
